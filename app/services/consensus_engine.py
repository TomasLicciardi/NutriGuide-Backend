# app/services/consensus_engine.py
"""
Motor de Consenso — Fase final del pipeline multi-fuente.

Agrega resultados de 6 fuentes + texto de alérgenos para producir
un veredicto final ponderado por ingrediente y por restricción.

Fuentes (importadas de config como única fuente de verdad):
  Texto alérgenos:       0.98 (declaración legal del fabricante)
  Tier 1 Determinista:   0.97 (reglas factuales)
  Tier 2 Knowledge Base: 0.93 (previamente verificado)
  Tier 3 Embedding:      0.88 (similitud semántica con modelo local)
  Tier 4 Open Food Facts:0.85 (comunitario)
  Tier 5 PubChem:        0.75 (identificación química)
  Gemini (del OCR):      0.65 (puede alucinar)

Política: "default unsafe" para restricciones médicas (TACC, lactosa, frutos secos).
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from app.config.image_analysis_config import TIER_WEIGHTS
from app.utils.allergen_parser import AllergenParseResult, POSITIVE_DECLARATION_MAP

logger = logging.getLogger(__name__)

ALL_RESTRICTIONS = ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"]

_RESTRICTION_FIELD = {
    "sin_tacc": "is_tacc_safe",
    "sin_lactosa": "is_lactose_safe",
    "sin_frutos_secos": "is_nut_safe",
    "vegano": "is_vegan_safe",
}

MEDICAL_RESTRICTIONS = {"sin_tacc", "sin_lactosa", "sin_frutos_secos"}


@dataclass
class IngredientVerdict:
    name_es: str
    name_en: str
    category: str                        # BASE / ADITIVO
    origin: Optional[str] = None         # animal/vegetal/sintetico/mineral/desconocido
    function_tag: Optional[str] = None
    description_es: Optional[str] = None
    is_tacc_safe: Optional[bool] = None
    is_lactose_safe: Optional[bool] = None
    is_nut_safe: Optional[bool] = None
    is_vegan_safe: Optional[bool] = None
    confidence: float = 0.0
    resolved_by: str = "unresolved"
    evidence: List[str] = field(default_factory=list)


@dataclass
class ProductVerdict:
    ingredients: List[IngredientVerdict] = field(default_factory=list)
    restrictions: Dict[str, dict] = field(default_factory=dict)
    overall_confidence: float = 0.0
    user_verdict: bool = True


class ConsensusEngine:
    """Agrega resultados multi-fuente en veredictos finales."""

    def build_product_verdict(
        self,
        ingredient_verdicts: List[IngredientVerdict],
        allergen_result: AllergenParseResult,
        user_restrictions: List[str],
    ) -> ProductVerdict:
        """Construye el veredicto final del producto."""
        restrictions = {r: {"apto": True, "motivo": None} for r in ALL_RESTRICTIONS}

        for v in ingredient_verdicts:
            for restriction in ALL_RESTRICTIONS:
                field_name = _RESTRICTION_FIELD[restriction]
                value = getattr(v, field_name)
                if value is False and restrictions[restriction]["apto"]:
                    restrictions[restriction] = {
                        "apto": False,
                        "motivo": f"Contiene {v.name_es}",
                    }
                elif value is None and restriction in MEDICAL_RESTRICTIONS:
                    if restrictions[restriction]["apto"]:
                        restrictions[restriction] = {
                            "apto": False,
                            "motivo": f"Ingrediente no verificable: {v.name_es}",
                        }

        for declaration in allergen_result.declaraciones_positivas:
            mapped = POSITIVE_DECLARATION_MAP.get(declaration)
            if mapped and mapped in restrictions:
                restrictions[mapped] = {"apto": True, "motivo": f"Declaración: {declaration}"}

        for restriction, data in allergen_result.restricciones_afectadas.items():
            if restriction in restrictions:
                restrictions[restriction] = {
                    "apto": False,
                    "motivo": data["fuente"],
                }

        confidences = [v.confidence for v in ingredient_verdicts if v.confidence > 0]
        overall_confidence = min(confidences) if confidences else 0.0

        user_verdict = self._calculate_user_verdict(restrictions, user_restrictions)

        return ProductVerdict(
            ingredients=ingredient_verdicts,
            restrictions=restrictions,
            overall_confidence=overall_confidence,
            user_verdict=user_verdict,
        )

    def merge_tier_results(
        self,
        name_es: str,
        name_en: str,
        tier1_result=None,
        tier2_result=None,
        tier3_embedding_result=None,
        tier4_result=None,
        tier5_result=None,
        gemini_result=None,
    ) -> IngredientVerdict:
        """
        Fusiona resultados de múltiples tiers para un solo ingrediente.
        Toma el resultado del tier con mayor peso que haya resuelto cada campo.

        Fuentes en orden de confianza:
          1. deterministic (tier1)    — 0.97
          2. knowledge_base (tier2)   — 0.93
          3. embedding (tier3)        — 0.88
          4. openfoodfacts (tier4)    — 0.85
          5. pubchem (tier5)          — 0.75
          6. gemini (del OCR)         — 0.65
        """
        verdict = IngredientVerdict(name_es=name_es, name_en=name_en, category="BASE")

        sources = [
            ("deterministic", tier1_result, TIER_WEIGHTS["deterministic"]),
            ("knowledge_base", tier2_result, TIER_WEIGHTS["knowledge_base"]),
            ("embedding", tier3_embedding_result, TIER_WEIGHTS["embedding"]),
            ("openfoodfacts", tier4_result, TIER_WEIGHTS["openfoodfacts"]),
            ("pubchem", tier5_result, TIER_WEIGHTS["pubchem"]),
            ("gemini", gemini_result, TIER_WEIGHTS["gemini"]),
        ]

        best_weight = 0.0
        best_source = "unresolved"

        for source_name, source_result, weight in sources:
            if source_result is None:
                continue

            evidence = getattr(source_result, "evidence", [])
            verdict.evidence.extend(evidence)

            cat = getattr(source_result, "category", None)
            if cat and verdict.category == "BASE":
                verdict.category = cat

            if weight > best_weight:
                origin = (
                    getattr(source_result, "origin", None)
                    or getattr(source_result, "inferred_origin", None)
                )
                if origin:
                    verdict.origin = origin
                fn = getattr(source_result, "function_tag", None)
                if fn:
                    verdict.function_tag = fn
                desc = getattr(source_result, "description_es", None)
                if desc:
                    verdict.description_es = desc

            for restriction in ALL_RESTRICTIONS:
                field_name = _RESTRICTION_FIELD[restriction]
                current = getattr(verdict, field_name)
                source_val = getattr(source_result, field_name, None)

                if source_val is not None:
                    if current is None:
                        setattr(verdict, field_name, source_val)
                        if weight > best_weight:
                            best_weight = weight
                            best_source = source_name
                    elif current is True and source_val is False and weight >= best_weight * 0.8:
                        setattr(verdict, field_name, False)
                        verdict.evidence.append(
                            f"Consenso: {source_name} contradice → no apto {restriction}"
                        )

        verdict.resolved_by = best_source
        verdict.confidence = best_weight if best_source != "unresolved" else 0.0

        return verdict

    @staticmethod
    def _calculate_user_verdict(restrictions: dict, user_restrictions: list) -> bool:
        if not user_restrictions:
            return True

        mapping = {
            "sin_tacc": "sin_tacc",
            "celiacos": "sin_tacc",
            "lactose_free": "sin_lactosa",
            "sin_lactosa": "sin_lactosa",
            "nut_free": "sin_frutos_secos",
            "sin_frutos_secos": "sin_frutos_secos",
            "vegan": "vegano",
            "vegano": "vegano",
        }

        for restriction in user_restrictions:
            mapped = mapping.get(restriction, restriction)
            if mapped in restrictions:
                if not restrictions[mapped]["apto"]:
                    return False

        return True


consensus_engine = ConsensusEngine()
