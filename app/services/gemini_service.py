# app/services/gemini_service.py
"""
Servicio Gemini simplificado para NutriGuide.

Responsabilidades:
  1. OCR: Extraer ingredientes + alérgenos de imágenes de etiquetas
  2. Fallback: Clasificar ingredientes desconocidos individuales (último recurso)

La clasificación de restricciones dietéticas se hace por el clasificador
determinista (deterministic_classifier.py), NO por Gemini.
"""

import os
import re
import json
import logging
import io
import asyncio
import google.generativeai as genai
from PIL import Image
from app.utils.image_tools import comprimir_imagen_inteligente, analizar_calidad_imagen
from app.config.image_analysis_config import VALIDATION_CONFIG, ERROR_MESSAGES
from dotenv import load_dotenv
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash-lite")


class GeminiService:
    """Servicio de IA para OCR de etiquetas y fallback de ingredientes desconocidos."""

    # ══════════════════════════════════════════════════════════════════════
    # OCR — Primera (y normalmente única) llamada a Gemini
    # ══════════════════════════════════════════════════════════════════════

    async def extract_ingredients_ocr(self, image_content: bytes, image_type: str) -> Dict:
        """
        Extrae ingredientes y advertencias de alérgenos de una imagen de etiqueta.
        """
        try:
            logger.info("Iniciando extraccion OCR de ingredientes con Gemini")

            # 1. Validar calidad de imagen
            calidad = analizar_calidad_imagen(image_content)
            if not calidad["es_valida"]:
                return self._error("poor_quality", calidad["razon"])

            # 2. Comprimir imagen
            imagen_pil = comprimir_imagen_inteligente(image_content, image_type)
            if not imagen_pil:
                return self._error("compression_failed", "No se pudo procesar la imagen")

            # 3. Convertir a bytes JPEG optimizado
            imagen_bytes = self._pil_to_jpeg_bytes(imagen_pil)
            logger.info(f"Imagen procesada: {len(imagen_bytes)} bytes")

            # 4. Enviar a Gemini con reintentos
            prompt = self._get_ocr_prompt()
            response = await self._call_gemini_with_retry(
                content=[prompt, {"mime_type": "image/jpeg", "data": imagen_bytes}],
                timeouts=[10, 20],
            )

            if response is None:
                return self._error("timeout", "Timeout en extraccion de ingredientes")

            # 5. Parsear respuesta
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
    # FALLBACK — Clasificar un ingrediente desconocido individual
    # ══════════════════════════════════════════════════════════════════════

    async def classify_unknown_ingredient(self, ingredient_name: str) -> Optional[Dict[str, bool]]:
        """
        Pregunta a Gemini sobre un ingrediente desconocido.
        Solo se usa cuando el clasificador determinista Y los embeddings fallaron.

        Returns:
            Dict con categorías booleanas o None si falla:
            {"dairy": bool, "egg": bool, "meat_fish": bool,
             "honey_insect": bool, "gluten": bool, "nuts": bool}
        """
        try:
            prompt = f"""Analiza el ingrediente alimentario: "{ingredient_name}"

Responde UNICAMENTE en JSON valido:
{{
  "dairy": true/false,
  "egg": true/false,
  "meat_fish": true/false,
  "honey_insect": true/false,
  "gluten": true/false,
  "nuts": true/false
}}

Donde:
- dairy: Derivado lacteo (leche, suero, caseina, etc.)
- egg: Derivado de huevo
- meat_fish: Derivado de carne o pescado
- honey_insect: Derivado de miel o insectos
- gluten: Contiene gluten (trigo, avena, cebada, centeno)
- nuts: Fruto seco o mani

Si no reconoces el ingrediente o es sintetico/vegetal, responde todo false.
"""
            response = await self._call_gemini_with_retry(
                content=[prompt], timeouts=[8, 15]
            )

            if response is None:
                return None

            return self._parse_unknown_ingredient_response(response.text)

        except Exception as e:
            logger.error(f"Error clasificando ingrediente desconocido '{ingredient_name}': {e}")
            return None

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
        """Llama a Gemini con reintentos y timeouts progresivos."""
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

    def _parse_unknown_ingredient_response(self, response_text: str) -> Optional[Dict[str, bool]]:
        try:
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            raw = json.loads(json_match.group(1)) if json_match else json.loads(response_text)

            expected_keys = ["dairy", "egg", "meat_fish", "honey_insect", "gluten", "nuts"]
            return {k: bool(raw.get(k, False)) for k in expected_keys}
        except Exception as e:
            logger.error(f"Error parseando respuesta de ingrediente desconocido: {e}")
            return None

    @staticmethod
    def _error(error_type: str, message: str) -> Dict:
        return {"success": False, "error": error_type, "message": message, "confidence": 0.0}


# Instancia global
gemini_service = GeminiService()
