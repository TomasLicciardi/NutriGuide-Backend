# app/services/openfoodfacts_service.py
"""
Servicio Open Food Facts — Tier 3 del pipeline multi-fuente.

Usa el SDK oficial (openfoodfacts v5) con API v3 para parsear ingredientes
en inglés y obtener clasificación de alérgenos, vegano/vegetariano,
y taxonomía de ingredientes.
"""

import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_GLUTEN_TAXONOMY_PREFIXES = [
    "en:wheat", "en:barley", "en:rye", "en:oat", "en:spelt",
    "en:kamut", "en:triticale", "en:seitan", "en:gluten",
    "en:malt", "en:semolina",
]

_DAIRY_TAXONOMY_PREFIXES = [
    "en:milk", "en:dairy", "en:cheese", "en:yogurt", "en:butter",
    "en:cream", "en:whey", "en:casein", "en:lactose", "en:curd",
]

_NUT_TAXONOMY_PREFIXES = [
    "en:almond", "en:walnut", "en:hazelnut", "en:pistachio",
    "en:cashew", "en:macadamia", "en:pecan", "en:peanut",
    "en:tree-nut", "en:nut",
]


@dataclass
class OFFIngredientResult:
    name_en: str
    taxonomy_id: Optional[str] = None
    in_taxonomy: bool = False
    vegan: Optional[str] = None        # 'yes', 'no', 'maybe', None
    vegetarian: Optional[str] = None   # 'yes', 'no', 'maybe', None
    is_tacc_safe: Optional[bool] = None
    is_lactose_safe: Optional[bool] = None
    is_nut_safe: Optional[bool] = None
    is_vegan_safe: Optional[bool] = None
    evidence: List[str] = field(default_factory=list)


class OpenFoodFactsService:
    """Tier 3: analiza ingredientes usando Open Food Facts API v3."""

    def __init__(self):
        self._api = None

    def _get_api(self):
        if self._api is None:
            from openfoodfacts import API, APIVersion, Environment
            self._api = API(
                user_agent="NutriGuide/2.0 (thesis project)",
                version=APIVersion.v3,
                environment=Environment.net,
            )
        return self._api

    async def analyze_ingredients(
        self, ingredients_en: List[str]
    ) -> Dict[str, OFFIngredientResult]:
        """
        Envía la lista de ingredientes en inglés a OFF y retorna
        clasificación por ingrediente.
        """
        if not ingredients_en:
            return {}

        try:
            text = ", ".join(ingredients_en)
            api = self._get_api()
            parsed = await asyncio.to_thread(
                api.product.parse_ingredients, text, lang="en"
            )

            if not parsed:
                logger.warning("Open Food Facts retornó respuesta vacía")
                return {}

            results: Dict[str, OFFIngredientResult] = {}
            for i, item in enumerate(parsed):
                name_en = ingredients_en[i] if i < len(ingredients_en) else item.get("text", "")
                result = self._parse_item(item, name_en)
                results[name_en] = result

            logger.info(f"OFF: {len(results)} ingredientes analizados, "
                        f"{sum(1 for r in results.values() if r.in_taxonomy)} en taxonomía")
            return results

        except Exception as e:
            logger.error(f"Error en Open Food Facts: {type(e).__name__}: {e}")
            return {}

    def _parse_item(self, item: dict, name_en: str) -> OFFIngredientResult:
        """Parsea un item de la respuesta de OFF."""
        taxonomy_id = item.get("id")
        in_taxonomy = bool(item.get("is_in_taxonomy", 0))
        vegan = item.get("vegan")
        vegetarian = item.get("vegetarian")

        result = OFFIngredientResult(
            name_en=name_en,
            taxonomy_id=taxonomy_id,
            in_taxonomy=in_taxonomy,
            vegan=vegan,
            vegetarian=vegetarian,
        )

        if not in_taxonomy:
            result.evidence.append(f"OFF: ingrediente '{name_en}' no reconocido en taxonomía")
            return result

        result.evidence.append(f"OFF: id='{taxonomy_id}', vegan='{vegan}', vegetarian='{vegetarian}'")

        # Gluten: inferir de taxonomía
        if taxonomy_id:
            tid = taxonomy_id.lower()
            if any(tid.startswith(p) or tid == p for p in _GLUTEN_TAXONOMY_PREFIXES):
                result.is_tacc_safe = False
                result.evidence.append(f"OFF taxonomía: '{taxonomy_id}' es fuente de gluten")
            else:
                result.is_tacc_safe = True

            # Lácteos
            if any(tid.startswith(p) or tid == p for p in _DAIRY_TAXONOMY_PREFIXES):
                result.is_lactose_safe = False
                result.evidence.append(f"OFF taxonomía: '{taxonomy_id}' es fuente láctea")
            else:
                result.is_lactose_safe = True

            # Frutos secos
            if any(tid.startswith(p) or tid == p for p in _NUT_TAXONOMY_PREFIXES):
                result.is_nut_safe = False
                result.evidence.append(f"OFF taxonomía: '{taxonomy_id}' es fruto seco")
            else:
                result.is_nut_safe = True

        # Vegano: directamente del campo vegan
        if vegan == "yes":
            result.is_vegan_safe = True
        elif vegan == "no":
            result.is_vegan_safe = False
            result.evidence.append("OFF: marcado como no vegano")
        # 'maybe' o None → dejar como None (no determinado)

        return result


openfoodfacts_service = OpenFoodFactsService()
