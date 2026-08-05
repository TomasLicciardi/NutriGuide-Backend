"""
Fallback LLM text-only para ingredientes no resueltos por el cascade v3.

Este servicio se usa como ultimo tier antes de la politica default-unsafe:
si KB/Codex/OFF/Gemini Vision no lograron fijar origen para un ingrediente
base, se consulta Gemini con salida JSON estricta y se valida antes de usarlo.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Set, Tuple

from app.core.config import settings
from app.services.gemini_service import gemini_service
from app.services.ingredient_facts import (
    ALLERGEN_BARLEY,
    ALLERGEN_DAIRY,
    ALLERGEN_EGG,
    ALLERGEN_FISH,
    ALLERGEN_GLUTEN,
    ALLERGEN_HONEY,
    ALLERGEN_LACTOSE,
    ALLERGEN_MILK,
    ALLERGEN_OATS,
    ALLERGEN_PEANUT,
    ALLERGEN_RYE,
    ALLERGEN_SESAME,
    ALLERGEN_SHELLFISH,
    ALLERGEN_SOY,
    ALLERGEN_SULFITES,
    ALLERGEN_TREE_NUT,
    ALLERGEN_WHEAT,
    IngredientCategory,
    Origin,
)

logger = logging.getLogger(__name__)


@dataclass
class LLMClassification:
    category: IngredientCategory
    origin: Origin
    function_tag: Optional[str]
    allergens: Set[str]
    contains: Set[str]
    derived_from: Set[str]
    description_es: Optional[str]
    confidence: float
    reasoning: str
    raw_response: str


_PROMPT_V1 = """Eres un experto en regulación alimentaria argentina (CAA Cap. XVIII).
Te paso el nombre de un ingrediente que apareció en la etiqueta de un producto
y los demás ingredientes del mismo producto como contexto. Tu tarea es
clasificarlo de forma estructurada para evaluar restricciones dietéticas.

Restricciones del usuario: sin TACC (gluten), sin lactosa, sin frutos secos, vegano.

INGREDIENTE: {name_es}
TRADUCCION_EN: {name_en}
CONTEXTO_DEL_PRODUCTO: {context}

Devolvé SOLO un JSON válido (sin markdown, sin texto antes ni después) con esta forma:
{{
  "category": "BASE | ADITIVO | FLAVORING | VITAMIN | MINERAL",
  "origin": "plant | animal | synthetic | mineral | natural_extract | unknown",
  "function_tag": "emulsionante | conservante | colorante | ... | null",
  "allergens": ["gluten", "wheat", "milk", "lactose", "dairy", "tree-nut", "peanut", "soy", "egg", "fish", "shellfish", "sesame", "sulfites", "honey"],
  "contains": [...],
  "derived_from": ["wheat", "milk", "soy", ...],
  "description_es": "explicación corta (<200 chars)",
  "confidence": 0.0_to_1.0,
  "reasoning": "por qué llegaste a esa clasificación, una oración"
}}

Reglas:
- Si tenés duda real entre dos categorías → confidence < 0.7
- "allergens" lista los tags canónicos del Codex Alimentarius que el ingrediente CONTIENE.
- "derived_from" lista las fuentes biológicas (wheat/milk/etc.) — usar SOLO los tags listados arriba.
- Si es un químico de síntesis sin origen biológico → origin=synthetic, derived_from=[].
- Si es un aromatizante/saborizante → category=FLAVORING; los predicados aplican política CAA aparte.

EJEMPLOS:

INGREDIENTE: caseinato de calcio
{{"category":"ADITIVO","origin":"animal","function_tag":"estabilizante","allergens":["milk","dairy","lactose"],"contains":["milk","dairy"],"derived_from":["milk"],"description_es":"Proteína derivada de la caseína de la leche","confidence":0.95,"reasoning":"Caseinato es derivado lácteo, el calcio es solo el contraión"}}

INGREDIENTE: ácido cítrico
{{"category":"ADITIVO","origin":"synthetic","function_tag":"acidulante","allergens":[],"contains":[],"derived_from":[],"description_es":"Acidulante sintético E330","confidence":0.97,"reasoning":"Producción industrial por fermentación de Aspergillus, sin alérgenos"}}

INGREDIENTE: aroma natural a vainilla
{{"category":"FLAVORING","origin":"natural_extract","function_tag":"saborizante","allergens":[],"contains":[],"derived_from":[],"description_es":"Aroma natural extraído de vaina de vainilla","confidence":0.85,"reasoning":"CAA Cap. XVIII clasificación natural"}}
"""


_PROMPT_BATCH_V1 = """Eres un experto en regulación alimentaria argentina (CAA Cap. XVIII).
Te paso una LISTA de ingredientes que aparecieron en la MISMA etiqueta de un
producto y los demás ingredientes del producto como contexto. Clasificá cada
ingrediente de forma estructurada para evaluar restricciones dietéticas.

Restricciones del usuario: sin TACC (gluten), sin lactosa, sin frutos secos, vegano.

CONTEXTO_DEL_PRODUCTO (todos los ingredientes): {context}

INGREDIENTES_A_CLASIFICAR:
{ingredients_block}

Devolvé SOLO un array JSON (sin markdown, sin texto antes ni después) con
EXACTAMENTE {count} elementos en el MISMO ORDEN que la lista de entrada.
Cada elemento es un objeto con esta forma:
{{
  "category": "BASE | ADITIVO | FLAVORING | VITAMIN | MINERAL",
  "origin": "plant | animal | synthetic | mineral | natural_extract | unknown",
  "function_tag": "emulsionante | conservante | colorante | ... | null",
  "allergens": ["gluten", "wheat", "milk", "lactose", "dairy", "tree-nut", "peanut", "soy", "egg", "fish", "shellfish", "sesame", "sulfites", "honey"],
  "contains": [...],
  "derived_from": ["wheat", "milk", "soy", ...],
  "description_es": "explicación corta (<200 chars)",
  "confidence": 0.0_to_1.0,
  "reasoning": "por qué llegaste a esa clasificación, una oración"
}}

Reglas:
- Si tenés duda real entre dos categorías → confidence < 0.7
- "allergens" lista los tags canónicos del Codex Alimentarius que el ingrediente CONTIENE.
- "derived_from" lista las fuentes biológicas (wheat/milk/etc.) — usar SOLO los tags listados arriba.
- Si es un químico de síntesis sin origen biológico → origin=synthetic, derived_from=[].
- Si es un aromatizante/saborizante → category=FLAVORING; los predicados aplican política CAA aparte.

EJEMPLOS de salidas válidas (referencia para items individuales):

caseinato de calcio
{{"category":"ADITIVO","origin":"animal","function_tag":"estabilizante","allergens":["milk","dairy","lactose"],"contains":["milk","dairy"],"derived_from":["milk"],"description_es":"Proteína derivada de la caseína de la leche","confidence":0.95,"reasoning":"Caseinato es derivado lácteo"}}

ácido cítrico
{{"category":"ADITIVO","origin":"synthetic","function_tag":"acidulante","allergens":[],"contains":[],"derived_from":[],"description_es":"Acidulante sintético E330","confidence":0.97,"reasoning":"Producción industrial sin alérgenos"}}

aroma natural a vainilla
{{"category":"FLAVORING","origin":"natural_extract","function_tag":"saborizante","allergens":[],"contains":[],"derived_from":[],"description_es":"Aroma natural extraído de vainilla","confidence":0.85,"reasoning":"CAA Cap. XVIII clasificación natural"}}
"""


_CANONICAL_TAGS = {
    ALLERGEN_GLUTEN,
    ALLERGEN_WHEAT,
    ALLERGEN_BARLEY,
    ALLERGEN_RYE,
    ALLERGEN_OATS,
    ALLERGEN_MILK,
    ALLERGEN_LACTOSE,
    ALLERGEN_DAIRY,
    ALLERGEN_TREE_NUT,
    ALLERGEN_PEANUT,
    ALLERGEN_SOY,
    ALLERGEN_EGG,
    ALLERGEN_FISH,
    ALLERGEN_SHELLFISH,
    ALLERGEN_SESAME,
    ALLERGEN_SULFITES,
    ALLERGEN_HONEY,
}


def _clamp_confidence(value) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.0
    return max(0.0, min(1.0, confidence))


def _parse_category(value) -> Optional[IngredientCategory]:
    if not isinstance(value, str):
        return None
    try:
        return IngredientCategory(value.strip().upper())
    except ValueError:
        logger.warning(f"LLM fallback: categoria invalida '{value}'")
        return None


def _parse_origin(value) -> Optional[Origin]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized == "unknown":
        return Origin.UNKNOWN
    try:
        return Origin(normalized)
    except ValueError:
        logger.warning(f"LLM fallback: origin invalido '{value}'")
        return None


def _parse_tag_set(data: dict, field: str) -> Set[str]:
    raw_values = data.get(field, [])
    if raw_values is None:
        return set()
    if not isinstance(raw_values, list):
        logger.warning(f"LLM fallback: campo '{field}' no es lista")
        return set()

    tags: Set[str] = set()
    unknown = []
    for raw in raw_values:
        if not isinstance(raw, str):
            unknown.append(repr(raw))
            continue
        tag = raw.strip().lower()
        if tag in _CANONICAL_TAGS:
            tags.add(tag)
        elif tag:
            unknown.append(tag)

    if unknown:
        logger.warning(
            f"LLM fallback: tags desconocidos en '{field}' filtrados: {unknown}"
        )
    return tags


def _parse_response(raw: str) -> Optional[LLMClassification]:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as e:
        logger.warning(f"LLM fallback: JSON invalido: {e}")
        return None

    if not isinstance(data, dict):
        logger.warning("LLM fallback: respuesta JSON no es un objeto")
        return None

    category = _parse_category(data.get("category"))
    if category is None:
        return None

    origin = _parse_origin(data.get("origin"))
    if origin is None:
        return None

    confidence = _clamp_confidence(data.get("confidence"))
    if confidence < 0.5:
        logger.info(
            f"LLM fallback: respuesta rechazada por baja confianza ({confidence:.2f})"
        )
        return None

    function_tag = data.get("function_tag")
    if function_tag is not None and not isinstance(function_tag, str):
        function_tag = None

    description_es = data.get("description_es")
    if description_es is not None and not isinstance(description_es, str):
        description_es = None

    reasoning = data.get("reasoning")
    if not isinstance(reasoning, str):
        reasoning = ""

    return LLMClassification(
        category=category,
        origin=origin,
        function_tag=function_tag.strip() if function_tag else None,
        allergens=_parse_tag_set(data, "allergens"),
        contains=_parse_tag_set(data, "contains"),
        derived_from=_parse_tag_set(data, "derived_from"),
        description_es=description_es.strip() if description_es else None,
        confidence=confidence,
        reasoning=reasoning.strip(),
        raw_response=raw,
    )


def _parse_array_response(raw: str, expected_count: int) -> List[Optional[LLMClassification]]:
    """
    Parsea un array JSON con `expected_count` clasificaciones individuales.
    Si la longitud no coincide o el JSON es inválido, retorna lista de Nones
    del largo esperado.
    """
    fallback = [None] * expected_count
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as e:
        logger.warning(f"LLM batch fallback: JSON invalido: {e}")
        return fallback

    if not isinstance(data, list):
        logger.warning("LLM batch fallback: respuesta JSON no es un array")
        return fallback

    if len(data) != expected_count:
        logger.warning(
            f"LLM batch fallback: longitud incorrecta ({len(data)} vs "
            f"{expected_count} esperados). Descartando batch entero."
        )
        return fallback

    results: List[Optional[LLMClassification]] = []
    for item in data:
        if not isinstance(item, dict):
            results.append(None)
            continue
        # Reusamos el parser individual sobre el sub-objeto serializado.
        parsed = _parse_response(json.dumps(item))
        results.append(parsed)
    return results


class LLMFallbackService:
    async def classify(
        self,
        name_es: str,
        name_en: Optional[str],
        context: str,
    ) -> Optional[LLMClassification]:
        prompt = _PROMPT_V1.format(
            name_es=name_es,
            name_en=name_en or "null",
            context=context or "null",
        )
        # Usamos el mismo modelo que la Fase 1 (configurable vía
        # GEMINI_VISION_MODEL en .env). Coherente y le saca partido al RPD
        # más alto si el usuario configuró gemini-2.5-flash en lugar del lite.
        try:
            raw = await gemini_service.generate_text(
                prompt,
                model_name=settings.GEMINI_VISION_MODEL,
                temperature=0.1,
                response_mime_type="application/json",
                timeout=15,
            )
        except Exception as e:
            logger.warning(
                f"LLM fallback: error clasificando '{name_es}': {type(e).__name__}: {e}"
            )
            return None

        if not raw:
            return None
        return _parse_response(raw.strip())

    async def classify_batch(
        self,
        items: Sequence[Tuple[str, Optional[str]]],
        context: str,
    ) -> List[Optional[LLMClassification]]:
        """
        Clasifica todos los ingredientes de UNA imagen en una sola llamada
        Gemini. Recibe pares (name_es, name_en) y devuelve una lista del mismo
        largo, en el mismo orden, con None en los que no pudieron resolverse.

        Esto es lo que el pipeline usa en producción: por cada foto que el
        usuario toma, los N ingredientes que cayeron a tier 5 se mandan
        juntos en una request, no N requests.
        """
        items = list(items)
        if not items:
            return []

        ingredients_block = "\n".join(
            f"{i+1}. {name_es} (en: {name_en or 'null'})"
            for i, (name_es, name_en) in enumerate(items)
        )
        prompt = _PROMPT_BATCH_V1.format(
            context=context or "null",
            ingredients_block=ingredients_block,
            count=len(items),
        )

        try:
            raw = await gemini_service.generate_text(
                prompt,
                model_name=settings.GEMINI_VISION_MODEL,
                temperature=0.1,
                response_mime_type="application/json",
                timeout=30,
            )
        except Exception as e:
            logger.warning(
                f"LLM batch fallback: error clasificando lote de {len(items)}: "
                f"{type(e).__name__}: {e}"
            )
            return [None] * len(items)

        if not raw:
            return [None] * len(items)
        return _parse_array_response(raw.strip(), expected_count=len(items))


llm_fallback_service = LLMFallbackService()
