# app/services/gemini_service.py
"""
Servicio Gemini para NutriGuide.

Responsabilidades:
  1. OCR: Extraer ingredientes + alérgenos de imágenes de etiquetas
  2. Fallback (Tier 5): Clasificar ingredientes desconocidos con las 4 restricciones
"""

import os
import re
import json
import logging
import io
import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass, field

import google.generativeai as genai
from PIL import Image

from app.utils.image_tools import comprimir_imagen_inteligente, analizar_calidad_imagen
from app.config.image_analysis_config import VALIDATION_CONFIG, ERROR_MESSAGES
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash-lite")


@dataclass
class GeminiFallbackResult:
    name_en: str
    origin: Optional[str] = None       # animal/vegetal/synthetic/mineral/unknown
    function_tag: Optional[str] = None  # conservante/colorante/emulsionante/...
    description_es: Optional[str] = None
    is_tacc_safe: Optional[bool] = None
    is_lactose_safe: Optional[bool] = None
    is_nut_safe: Optional[bool] = None
    is_vegan_safe: Optional[bool] = None
    evidence: List[str] = field(default_factory=list)


class GeminiService:
    """Servicio de IA para OCR de etiquetas y fallback de ingredientes desconocidos."""

    # ══════════════════════════════════════════════════════════════════════
    # OCR — Fase 1 del pipeline
    # ══════════════════════════════════════════════════════════════════════

    async def extract_ingredients_ocr(self, image_content: bytes, image_type: str) -> Dict:
        """Extrae ingredientes y advertencias de alérgenos de una imagen."""
        try:
            logger.info("Iniciando extracción OCR con Gemini")

            calidad = analizar_calidad_imagen(image_content)
            if not calidad["es_valida"]:
                return self._error("poor_quality", calidad["razon"])

            imagen_pil = comprimir_imagen_inteligente(image_content, image_type)
            if not imagen_pil:
                return self._error("compression_failed", "No se pudo procesar la imagen")

            imagen_bytes = self._pil_to_jpeg_bytes(imagen_pil)
            logger.info(f"Imagen procesada: {len(imagen_bytes)} bytes")

            prompt = self._get_ocr_prompt()
            response = await self._call_gemini_with_retry(
                content=[prompt, {"mime_type": "image/jpeg", "data": imagen_bytes}],
                timeouts=[10, 20],
            )

            if response is None:
                return self._error("timeout", "Timeout en extracción de ingredientes")

            result = self._parse_ocr_response(response.text)
            if not result.get("success"):
                logger.error(f"Fallo parsing OCR. Respuesta: {response.text[:500]}")
                return self._error("parse_failed", "No se pudo interpretar la respuesta de Gemini")

            logger.info(f"OCR exitoso: {len(result.get('ingredients', []))} ingredientes")
            return result

        except Exception as e:
            logger.error(f"Error general en OCR: {type(e).__name__}: {e}")
            return self._error("general_error", f"Error general en OCR: {e}")

    # ══════════════════════════════════════════════════════════════════════
    # FALLBACK — Tier 5: clasificar ingredientes desconocidos
    # ══════════════════════════════════════════════════════════════════════

    async def classify_unknown_ingredients(
        self, ingredients: List[Dict[str, str]]
    ) -> Dict[str, GeminiFallbackResult]:
        """
        Clasifica ingredientes desconocidos como último recurso.
        Recibe lista de {"name_es": ..., "name_en": ...}.
        """
        if not ingredients:
            return {}

        results: Dict[str, GeminiFallbackResult] = {}
        for ing in ingredients:
            name_es = ing["name_es"]
            name_en = ing["name_en"]
            r = await self._classify_single(name_es, name_en)
            results[name_en] = r

        found = sum(1 for r in results.values() if r.origin is not None)
        logger.info(f"Gemini fallback: {found}/{len(ingredients)} ingredientes clasificados")
        return results

    async def _classify_single(
        self, name_es: str, name_en: str
    ) -> GeminiFallbackResult:
        """Clasifica un ingrediente individual con Gemini."""
        result = GeminiFallbackResult(name_en=name_en)

        try:
            prompt = f"""Analiza el ingrediente alimentario: "{name_es}" (en inglés: "{name_en}")

Responde ÚNICAMENTE en JSON válido:
{{
  "origin": "animal|vegetal|synthetic|mineral|unknown",
  "function": "conservante|colorante|emulsionante|estabilizante|acidulante|antioxidante|edulcorante|espesante|saborizante|otro",
  "contains_gluten": true/false,
  "contains_lactose": true/false,
  "is_nut": true/false,
  "is_animal_derived": true/false,
  "description_es": "Breve descripción en español de qué es este ingrediente"
}}

Reglas:
- "origin": de dónde proviene el ingrediente (animal, vegetal, sintético, mineral)
- "contains_gluten": true si deriva de trigo, cebada, centeno o avena
- "contains_lactose": true si deriva de leche o lácteos
- "is_nut": true si es un fruto seco o maní
- "is_animal_derived": true si proviene de un animal (incluye lácteos, huevo, carne, miel, insectos)
- Si no reconoces el ingrediente, usa "unknown" para origin y false para los booleanos
"""
            response = await self._call_gemini_with_retry(
                content=[prompt], timeouts=[8, 15]
            )

            if response is None:
                result.evidence.append("Gemini: timeout")
                return result

            parsed = self._parse_fallback_response(response.text)
            if parsed is None:
                result.evidence.append("Gemini: error parseando respuesta")
                return result

            result.origin = parsed.get("origin")
            result.function_tag = parsed.get("function")
            result.description_es = parsed.get("description_es")
            result.is_tacc_safe = not parsed.get("contains_gluten", False)
            result.is_lactose_safe = not parsed.get("contains_lactose", False)
            result.is_nut_safe = not parsed.get("is_nut", False)
            result.is_vegan_safe = not parsed.get("is_animal_derived", False)
            result.evidence.append(
                f"Gemini: origin={result.origin}, function={result.function_tag}"
            )

        except Exception as e:
            logger.error(f"Error Gemini fallback para '{name_es}': {e}")
            result.evidence.append(f"Gemini: error ({type(e).__name__})")

        return result

    # ══════════════════════════════════════════════════════════════════════
    # Helpers internos
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
        for attempt, timeout in enumerate(timeouts):
            try:
                logger.info(f"Gemini intento {attempt + 1}/{len(timeouts)}, timeout={timeout}s")
                response = await asyncio.wait_for(
                    asyncio.to_thread(model.generate_content, content),
                    timeout=timeout,
                )
                return response
            except asyncio.TimeoutError:
                logger.error(f"Timeout Gemini intento {attempt + 1}")
            except Exception as e:
                logger.error(f"Error Gemini intento {attempt + 1}: {type(e).__name__}: {e}")
        return None

    def _get_ocr_prompt(self) -> str:
        return """Analiza esta etiqueta de producto alimenticio (Argentina/Latinoamerica).

EXTRAE:
1. LISTA DE INGREDIENTES: Cada ingrediente/aditivo por separado.

REGLAS CRITICAS PARA ETIQUETAS ARGENTINAS:
- Abreviaturas funcionales: extraer solo el ingrediente que sigue:
  EMU: lecitina de soja -> "lecitina de soja"
  ACI: acido citrico (INS 330) -> "acido citrico"
  ARO: sabor a vainilla -> "sabor a vainilla"
  CON: sorbato de potasio -> "sorbato de potasio"
  COL: caramelo IV -> "caramelo IV"
  EST: goma xantica -> "goma xantica"
  RES: glutamato monosodico -> "glutamato monosodico"
  SEC: EDTA disodico -> "EDTA disodico"
  RAI: bicarbonato de sodio -> "bicarbonato de sodio"

- Enriquecimiento por ley (Ley 25.630): extraer SOLO el ingrediente base:
  "harina de trigo enriquecida ley 25.630 (sulfato ferroso: 30mg/kg...)" -> "harina de trigo enriquecida"

- Sub-ingredientes entre parentesis SI se extraen por separado:
  "sazonador (sal, azucar, glutamato monosodico)" -> "sazonador", "sal", "azucar", "glutamato monosodico"

- Codigos INS o E: incluirlos tal como aparecen:
  "lecitina de soja (INS 322)" -> "lecitina de soja"
  "bicarbonato de sodio (INS 500ii)" -> "bicarbonato de sodio"

- Ingredientes con origen especificado: mantener descripcion completa:
  "aceite vegetal de palma y canola (TBHQ)" -> "aceite vegetal de palma y canola", "TBHQ"

2. ADVERTENCIAS DE ALERGENOS: Texto completo de CONTIENE, PUEDE CONTENER, SIN TACC, LIBRE DE GLUTEN, etc.

Si la imagen NO es una etiqueta alimentaria o no se pueden leer ingredientes, responde con listas vacias.

RESPONDE UNICAMENTE EN JSON VALIDO (sin texto extra):
{
  "ingredientes_detectados": ["ingrediente1", "ingrediente2", "aditivo1"],
  "alergenos_advertencias": "CONTIENE: GLUTEN. PUEDE CONTENER: SOJA." o null,
  "confidence": 0.95
}
"""

    def _parse_ocr_response(self, response_text: str) -> Dict:
        try:
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                result = json.loads(response_text)

            if not isinstance(result.get("ingredientes_detectados"), list):
                raise ValueError("ingredientes_detectados debe ser una lista")

            return {
                "success": True,
                "ingredients": result["ingredientes_detectados"],
                "allergen_warnings": result.get("alergenos_advertencias"),
                "confidence": result.get("confidence", 0.5),
            }
        except Exception as e:
            logger.error(f"Error parseando OCR: {e}")
            return {"success": False, "error": "parse_failed"}

    @staticmethod
    def _parse_fallback_response(response_text: str) -> Optional[dict]:
        try:
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            raw = json.loads(json_match.group(1)) if json_match else json.loads(response_text)
            return raw
        except Exception as e:
            logger.error(f"Error parseando respuesta fallback: {e}")
            return None

    @staticmethod
    def _error(error_type: str, message: str) -> Dict:
        return {"success": False, "error": error_type, "message": message, "confidence": 0.0}


gemini_service = GeminiService()
