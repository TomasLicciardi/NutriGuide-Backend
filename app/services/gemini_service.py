# app/services/gemini_service.py
"""
Servicio Gemini para NutriGuide v2.1.

OPTIMIZACIÓN: Una sola llamada a Gemini hace OCR + clasificación de ingredientes.
Antes se necesitaban 2 llamadas (OCR + Tier 5 fallback), ahora se reduce a 1.

Responsabilidades:
  1. OCR+Clasificación: Extraer ingredientes + alérgenos + clasificar cada ingrediente
     (origen, gluten, lactosa, frutos secos, vegano) en UNA sola llamada.
"""

import os
import re
import json
import logging
import io
import asyncio
import time
from collections import deque
from typing import Dict, List, Optional
from dataclasses import dataclass, field

import google.generativeai as genai
from PIL import Image

from app.utils.image_tools import comprimir_imagen_inteligente, analizar_calidad_imagen
from app.core.config import settings
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# Modelo de la Fase 1 (OCR + clasificación). Configurable vía settings:
# GEMINI_VISION_MODEL en .env. Default: gemini-2.5-flash-lite (free tier vigente).
model = genai.GenerativeModel(settings.GEMINI_VISION_MODEL)
logger.info(f"Gemini Vision: usando modelo '{settings.GEMINI_VISION_MODEL}'")


# ── Rate limiter para el free tier de Gemini ──
# Free tier de gemini-2.0-flash: 15 RPM. Mantenemos margen y permitimos 12 RPM
# para no rozar el límite con clock skew. El limiter es global porque la cuota
# se aplica por API key, no por request.
_RPM_LIMIT = int(os.getenv("GEMINI_RPM_LIMIT", "12"))
_RATE_WINDOW_S = 60.0
_call_timestamps: deque = deque(maxlen=_RPM_LIMIT)
_rate_lock = asyncio.Lock()


def _extract_retry_delay(msg: str) -> Optional[int]:
    """Parsea el `retry_delay { seconds: N }` del mensaje 429 de Gemini."""
    m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", msg)
    return int(m.group(1)) if m else None


def _classify_429(msg: str) -> str:
    """
    Identifica el tipo de cuota agotada de un mensaje 429 de Gemini.

    Returns:
        "daily"     — RPD por proyecto/modelo agotada. No sirve reintentar.
        "rpm"       — Per-minute rate limit. Esperar retry_delay y reintentar.
        "tokens"    — Tokens por minuto agotados. Esperar y reintentar.
        "unknown"   — No matcheó ningún patrón conocido.
    """
    # Orden: chequear el patrón MÁS específico primero. "PerMinute" es
    # subcadena de "InputTokensPerModelPerMinute", así que tokens va antes.
    if "InputTokensPerModelPerMinute" in msg or "InputTokensPerModel" in msg:
        return "tokens"
    if "PerDay" in msg:
        return "daily"
    if "PerMinute" in msg:
        return "rpm"
    return "unknown"


def _is_429(exc: Exception) -> bool:
    msg = str(exc)
    return "429" in msg or "ResourceExhausted" in type(exc).__name__


class QuotaExhaustedError(Exception):
    """Raised cuando la cuota diaria del modelo está agotada (no sirve reintentar)."""
    def __init__(self, model_name: str, original_msg: str = ""):
        self.model_name = model_name
        self.original_msg = original_msg
        super().__init__(
            f"Cuota diaria agotada para '{model_name}'. "
            f"Reintentar no ayuda hasta el reset (~24h) o activar billing."
        )


async def _rate_limit_acquire() -> None:
    """Bloquea hasta que sea seguro hacer una nueva llamada bajo el RPM limit."""
    async with _rate_lock:
        now = time.monotonic()
        # Purgar timestamps fuera de la ventana
        while _call_timestamps and now - _call_timestamps[0] > _RATE_WINDOW_S:
            _call_timestamps.popleft()
        if len(_call_timestamps) >= _RPM_LIMIT:
            wait = _RATE_WINDOW_S - (now - _call_timestamps[0]) + 0.1
            logger.info(f"Gemini rate limit alcanzado, esperando {wait:.1f}s")
            await asyncio.sleep(wait)
            now = time.monotonic()
            while _call_timestamps and now - _call_timestamps[0] > _RATE_WINDOW_S:
                _call_timestamps.popleft()
        _call_timestamps.append(now)


@dataclass
class GeminiIngredientClassification:
    """Clasificación de un ingrediente individual obtenida del OCR+Clasificación."""
    name_es: str
    origin: Optional[str] = None
    function_tag: Optional[str] = None
    description_es: Optional[str] = None
    is_tacc_safe: Optional[bool] = None
    is_lactose_safe: Optional[bool] = None
    is_nut_safe: Optional[bool] = None
    is_vegan_safe: Optional[bool] = None
    evidence: List[str] = field(default_factory=list)


@dataclass
class OCRResult:
    """Resultado completo del OCR+Clasificación unificado."""
    success: bool
    ingredients: List[str] = field(default_factory=list)
    classifications: Dict[str, GeminiIngredientClassification] = field(default_factory=dict)
    allergen_warnings: Optional[str] = None
    confidence: float = 0.0
    error: Optional[str] = None
    message: Optional[str] = None


class GeminiService:
    """OCR de etiquetas con clasificación de ingredientes en una sola llamada."""

    async def generate_text(
        self,
        prompt: str,
        model_name: str = "gemini-2.0-flash",
        temperature: float = 0.1,
        response_mime_type: Optional[str] = None,
        timeout: float = 10.0,
        max_retries: int = 2,
    ) -> Optional[str]:
        """
        Llamada text-only a Gemini para servicios auxiliares del pipeline.

        Maneja 429 (rate limit) reintentando hasta `max_retries` veces. Respeta
        el `retry_delay` que devuelve la API si lo extrae del mensaje.
        """
        generation_config = {"temperature": temperature}
        if response_mime_type:
            generation_config["response_mime_type"] = response_mime_type

        attempt = 0
        while True:
            await _rate_limit_acquire()
            try:
                text_model = genai.GenerativeModel(
                    model_name,
                    generation_config=generation_config,
                )
                response = await asyncio.wait_for(
                    asyncio.to_thread(text_model.generate_content, prompt),
                    timeout=timeout,
                )
                return getattr(response, "text", None)
            except asyncio.TimeoutError:
                logger.error(f"Timeout Gemini text-only ({timeout}s)")
                return None
            except Exception as e:
                msg = str(e)
                is_429 = "429" in msg or "ResourceExhausted" in type(e).__name__
                if is_429 and attempt < max_retries:
                    delay = _extract_retry_delay(msg) or (5 * (attempt + 1))
                    logger.warning(
                        f"Gemini 429 (intento {attempt+1}/{max_retries}), "
                        f"esperando {delay}s antes de reintentar"
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                logger.error(f"Error Gemini text-only: {type(e).__name__}: {e}")
                return None

    async def extract_and_classify(
        self, image_content: bytes, image_type: str
    ) -> OCRResult:
        """
        Extrae ingredientes, advertencias de alérgenos Y clasifica cada ingrediente
        en UNA sola llamada a Gemini. Reemplaza las 2 llamadas anteriores
        (OCR + Tier 5 fallback).
        """
        try:
            logger.info("Gemini: OCR + clasificación unificada")

            calidad = analizar_calidad_imagen(image_content)
            if not calidad["es_valida"]:
                return OCRResult(
                    success=False, error="poor_quality", message=calidad["razon"]
                )

            imagen_pil = comprimir_imagen_inteligente(image_content, image_type)
            if not imagen_pil:
                return OCRResult(
                    success=False, error="compression_failed",
                    message="No se pudo procesar la imagen",
                )

            imagen_bytes = self._pil_to_jpeg_bytes(imagen_pil)
            logger.info(f"Imagen procesada: {len(imagen_bytes)} bytes")

            prompt = self._get_unified_prompt()
            response = await self._call_gemini_with_retry(
                content=[prompt, {"mime_type": "image/jpeg", "data": imagen_bytes}],
                timeouts=[25, 45],
            )

            if response is None:
                return OCRResult(
                    success=False, error="timeout",
                    message="Timeout en extracción de ingredientes",
                )

            result = self._parse_unified_response(response.text)
            if not result.success:
                logger.error(f"Fallo parsing OCR. Respuesta: {response.text[:500]}")

            logger.info(
                f"OCR+Clasificación: {len(result.ingredients)} ingredientes, "
                f"{len(result.classifications)} clasificados"
            )
            return result

        except QuotaExhaustedError as e:
            # Cuota diaria agotada: error específico para que el caller
            # (script de batch, endpoint) pueda decidir abortar el lote
            # completo en lugar de seguir intentando con cada foto.
            return OCRResult(
                success=False,
                error="quota_exhausted_daily",
                message=str(e),
            )

        except Exception as e:
            logger.error(f"Error general en OCR+Clasificación: {type(e).__name__}: {e}")
            return OCRResult(
                success=False, error="general_error",
                message=f"Error general: {e}",
            )

    # ══════════════════════════════════════════════════════════════════════
    # Prompt unificado
    # ══════════════════════════════════════════════════════════════════════

    def _get_unified_prompt(self) -> str:
        return """Analiza esta etiqueta de producto alimenticio (Argentina/Latinoamérica).

TAREA DOBLE: Extrae los ingredientes Y clasifica cada uno.

═══ EXTRACCIÓN DE INGREDIENTES ═══

REGLAS CRÍTICAS PARA ETIQUETAS ARGENTINAS:
- Abreviaturas funcionales: extraer solo el ingrediente que sigue:
  EMU: lecitina de soja -> "lecitina de soja"
  ACI: ácido cítrico (INS 330) -> "ácido cítrico"
  ARO: sabor a vainilla -> "sabor a vainilla"
  CON: sorbato de potasio -> "sorbato de potasio"
  COL: caramelo IV -> "caramelo IV"
  EST: goma xántica -> "goma xántica"
  RES: glutamato monosódico -> "glutamato monosódico"
  SEC: EDTA disódico -> "EDTA disódico"
  RAI: bicarbonato de sodio -> "bicarbonato de sodio"

- Enriquecimiento por ley (Ley 25.630): extraer SOLO el ingrediente base:
  "harina de trigo enriquecida ley 25.630 (sulfato ferroso: 30mg/kg...)" -> "harina de trigo enriquecida"

- Sub-ingredientes entre paréntesis SI se extraen por separado:
  "sazonador (sal, azúcar, glutamato monosódico)" -> "sazonador", "sal", "azúcar", "glutamato monosódico"

- Códigos INS o E: incluirlos tal como aparecen:
  "lecitina de soja (INS 322)" -> "lecitina de soja"

- Ingredientes con origen especificado: mantener descripción completa:
  "aceite vegetal de palma y canola (TBHQ)" -> "aceite vegetal de palma y canola", "TBHQ"

═══ CLASIFICACIÓN POR INGREDIENTE ═══

Para CADA ingrediente extraído, clasifica:
- origin: "animal" | "vegetal" | "synthetic" | "mineral" | "unknown"
- function: "conservante" | "colorante" | "emulsionante" | "estabilizante" | "acidulante" | "antioxidante" | "edulcorante" | "espesante" | "saborizante" | "base" | "otro"
- contains_gluten: true SOLO si deriva de trigo, cebada, centeno o avena
- contains_lactose: true SOLO si deriva de leche o lácteos
- is_nut: true SOLO si es un fruto seco o maní
- is_animal_derived: true si proviene de un animal (incluye lácteos, huevo, carne, miel, insectos)
- description_es: Breve descripción en español (máximo 15 palabras)

═══ ALÉRGENOS ═══

Extrae el texto completo de CONTIENE, PUEDE CONTENER, SIN TACC, LIBRE DE GLUTEN, etc.

Si la imagen NO es una etiqueta alimentaria o no se pueden leer ingredientes, responde con listas vacías.

RESPONDE ÚNICAMENTE EN JSON VÁLIDO (sin texto extra):
{
  "ingredientes": [
    {
      "nombre": "harina de trigo enriquecida",
      "origin": "vegetal",
      "function": "base",
      "contains_gluten": true,
      "contains_lactose": false,
      "is_nut": false,
      "is_animal_derived": false,
      "description_es": "Harina refinada de trigo con fortificación obligatoria"
    }
  ],
  "alergenos_advertencias": "CONTIENE: GLUTEN. PUEDE CONTENER: SOJA." o null,
  "confidence": 0.95
}"""

    # ══════════════════════════════════════════════════════════════════════
    # Parsing
    # ══════════════════════════════════════════════════════════════════════

    def _parse_unified_response(self, response_text: str) -> OCRResult:
        """Parsea la respuesta unificada de OCR + clasificación."""
        try:
            json_match = re.search(
                r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL
            )
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                data = json.loads(response_text)

            raw_ingredients = data.get("ingredientes", [])
            if not isinstance(raw_ingredients, list) or not raw_ingredients:
                return OCRResult(
                    success=False, error="no_ingredients",
                    message="No se detectaron ingredientes",
                )

            ingredient_names: List[str] = []
            classifications: Dict[str, GeminiIngredientClassification] = {}

            for item in raw_ingredients:
                if isinstance(item, str):
                    ingredient_names.append(item)
                    continue

                name = item.get("nombre", "").strip()
                if not name:
                    continue

                ingredient_names.append(name)
                classifications[name] = GeminiIngredientClassification(
                    name_es=name,
                    origin=item.get("origin"),
                    function_tag=item.get("function"),
                    description_es=item.get("description_es"),
                    is_tacc_safe=not item.get("contains_gluten", False),
                    is_lactose_safe=not item.get("contains_lactose", False),
                    is_nut_safe=not item.get("is_nut", False),
                    is_vegan_safe=not item.get("is_animal_derived", False),
                    evidence=[
                        f"Gemini OCR: origin={item.get('origin')}, "
                        f"function={item.get('function')}"
                    ],
                )

            return OCRResult(
                success=True,
                ingredients=ingredient_names,
                classifications=classifications,
                allergen_warnings=data.get("alergenos_advertencias"),
                confidence=data.get("confidence", 0.5),
            )

        except Exception as e:
            logger.error(f"Error parseando OCR+Clasificación: {e}")
            return OCRResult(
                success=False, error="parse_failed",
                message="No se pudo interpretar la respuesta de Gemini",
            )

    # ══════════════════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _pil_to_jpeg_bytes(imagen_pil: Image.Image) -> bytes:
        buf = io.BytesIO()
        imagen_pil.save(buf, format="JPEG", quality=60, optimize=True)
        data = buf.getvalue()

        if len(data) > 50_000:
            buf = io.BytesIO()
            if max(imagen_pil.size) > 600:
                imagen_pil.thumbnail((600, 600), Image.Resampling.LANCZOS)
            imagen_pil.save(buf, format="JPEG", quality=50, optimize=True)
            data = buf.getvalue()

        return data

    async def _call_gemini_with_retry(self, content, timeouts: List[int]):
        """
        Llama a Gemini Vision con retries adaptados al tipo de error.

        Política de 429:
          - "daily" (RPD agotado): aborta inmediato. Reintentar no sirve hasta
            el reset (~24h). Lanza QuotaExhaustedError para que el caller pueda
            cortar el batch completo y no perder tiempo con timeouts inútiles.
          - "rpm" / "tokens": respeta el `retry_delay` que devuelve la API y
            reintenta. Si no hay retry_delay parseable, usa backoff exponencial
            (5s, 10s, 20s).
          - Otros errores: reintenta con el siguiente timeout de la lista.

        Para errores transitorios (timeout, errores de red), reintenta con el
        siguiente timeout más largo de la lista `timeouts`.
        """
        backoff_429 = [5, 10, 20]  # fallback si no hay retry_delay en el msg
        attempt_429 = 0
        attempt_general = 0

        while attempt_general < len(timeouts):
            timeout = timeouts[attempt_general]
            try:
                logger.info(
                    f"Gemini intento {attempt_general + 1}/{len(timeouts)}, "
                    f"timeout={timeout}s (modelo: {settings.GEMINI_VISION_MODEL})"
                )
                response = await asyncio.wait_for(
                    asyncio.to_thread(model.generate_content, content),
                    timeout=timeout,
                )
                return response

            except asyncio.TimeoutError:
                logger.error(f"Timeout Gemini intento {attempt_general + 1}")
                attempt_general += 1

            except Exception as e:
                if not _is_429(e):
                    logger.error(
                        f"Error Gemini intento {attempt_general + 1}: "
                        f"{type(e).__name__}: {e}"
                    )
                    attempt_general += 1
                    continue

                # ── Es 429: clasificar y decidir ──
                msg = str(e)
                kind = _classify_429(msg)
                if kind == "daily":
                    logger.error(
                        f"Gemini 429 RPD agotado para '{settings.GEMINI_VISION_MODEL}'. "
                        f"Abortando — no sirve reintentar hasta el reset."
                    )
                    raise QuotaExhaustedError(settings.GEMINI_VISION_MODEL, msg)

                # RPM o tokens: esperar y reintentar
                if attempt_429 >= len(backoff_429):
                    logger.error(
                        f"Gemini 429 ({kind}): agotados los reintentos "
                        f"({len(backoff_429)}). Abortando esta llamada."
                    )
                    attempt_general += 1
                    continue

                delay = _extract_retry_delay(msg) or backoff_429[attempt_429]
                # Margen sobre el delay sugerido por la API
                delay = delay + 1
                logger.warning(
                    f"Gemini 429 ({kind}), esperando {delay}s antes de reintentar "
                    f"(intento 429 #{attempt_429 + 1}/{len(backoff_429)})"
                )
                await asyncio.sleep(delay)
                attempt_429 += 1
                # NO incrementamos attempt_general: el 429 no consume un slot
                # de los timeouts generales.

        return None


gemini_service = GeminiService()
