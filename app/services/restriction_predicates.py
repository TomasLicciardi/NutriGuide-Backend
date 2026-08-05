# app/services/restriction_predicates.py
"""
Predicados declarativos de restricciones — el "rule base".

Cada restricción es un predicado puro sobre IngredientFacts que decide
si el ingrediente es apto. Agregar una restricción nueva = agregar una
entrada al dict, sin tocar la caracterización de ingredientes.

Política sobre aromatizantes (CAA Cap. XVIII Art. 1383):
  - Calificador "artificial" / "idéntico al natural" → safe por defecto.
  - Calificador "natural" → safe excepto si target sensorial es alérgeno crítico.
  - target_sensory ∈ {frutos secos, maní} → NUNCA safe automático
    (riesgo anafiláctico requiere confirmación por declaración legal).

Política sobre declaración legal:
  - Resuelta en una capa anterior (analysis_pipeline) — los predicados
    aquí solo evalúan IngredientFacts ya enriquecidos.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Optional

from app.services.ingredient_facts import (
    ANIMAL_SOURCES,
    DAIRY_SOURCES,
    FlavoringType,
    GLUTEN_SOURCES,
    IngredientCategory,
    IngredientFacts,
    NUT_SOURCES,
    Origin,
    allergens_es,
)


@dataclass
class PredicateResult:
    """Resultado de evaluar un predicado sobre un IngredientFacts."""
    apto: bool
    motivo: Optional[str] = None
    confidence: float = 1.0


# ═══════════════════════════════════════════════════════════════════════════
# Política "default unsafe" para ingredientes base no verificables
# ═══════════════════════════════════════════════════════════════════════════


def _is_unverifiable_base(f: IngredientFacts) -> bool:
    """
    Un ingrediente es "base no verificable" cuando:
      - No es aromatizante (los aromatizantes tienen su propia política CAA).
      - Es categoría BASE o UNKNOWN (alimentos crudos, no aditivos).
      - Su origen es UNKNOWN (ninguna fuente lo clasificó).

    Política de seguridad heredada del consensus engine v1
    (`_should_block_unresolved`): un BASE no verificable bloquea las cuatro
    restricciones por defecto, porque puede ser cualquier cosa (carne,
    harina, cereal, etc). Los aditivos no verificables NO bloquean — su
    impacto es marginal y la cobertura de Codex/OFF es alta.
    """
    if f.is_flavoring():
        return False
    if f.category not in (IngredientCategory.BASE, IngredientCategory.UNKNOWN):
        return False
    return f.origin == Origin.UNKNOWN


def _block_unverifiable(label: str, f: IngredientFacts) -> PredicateResult:
    return PredicateResult(
        apto=False,
        motivo=(
            f"ingrediente base no verificable — sin fuentes para "
            f"determinar si cumple '{label}'"
        ),
        confidence=0.5,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Predicados individuales
# ═══════════════════════════════════════════════════════════════════════════


def _evaluate_sin_tacc(f: IngredientFacts) -> PredicateResult:
    if f.is_flavoring():
        return _flavoring_default_safe(f, GLUTEN_SOURCES, "gluten")

    if f.allergens_intersect(GLUTEN_SOURCES):
        matched = f.allergens & GLUTEN_SOURCES
        return PredicateResult(False, f"contiene {allergens_es(matched)}", f.confidence)

    if f.derived_from_any({"wheat", "barley", "rye", "oats"}):
        matched = f.derived_from & {"wheat", "barley", "rye", "oats"}
        return PredicateResult(False, f"derivado de {allergens_es(matched)}", f.confidence)

    if _is_unverifiable_base(f):
        return _block_unverifiable("sin TACC", f)

    return PredicateResult(True, confidence=f.confidence)


def _evaluate_sin_lactosa(f: IngredientFacts) -> PredicateResult:
    if f.is_flavoring():
        return _flavoring_default_safe(f, DAIRY_SOURCES, "lácteo")

    if f.allergens_intersect(DAIRY_SOURCES):
        matched = f.allergens & DAIRY_SOURCES
        return PredicateResult(False, f"contiene {allergens_es(matched)}", f.confidence)

    if f.derived_from_any({"milk", "dairy"}):
        return PredicateResult(False, "derivado lácteo", f.confidence)

    if _is_unverifiable_base(f):
        return _block_unverifiable("sin lactosa", f)

    return PredicateResult(True, confidence=f.confidence)


def _evaluate_sin_frutos_secos(f: IngredientFacts) -> PredicateResult:
    if f.is_flavoring():
        # Excepción crítica: target sensorial de alto riesgo nunca asume safe
        if f.is_high_risk_flavoring():
            return PredicateResult(
                False,
                f"aromatizante con target sensorial de alto riesgo: '{f.target_sensory}' "
                f"(la declaración legal del producto es la fuente que confirma o niega)",
                confidence=0.5,
            )
        return _flavoring_default_safe(f, NUT_SOURCES, "fruto seco")

    if f.allergens_intersect(NUT_SOURCES):
        matched = f.allergens & NUT_SOURCES
        return PredicateResult(False, f"contiene {allergens_es(matched)}", f.confidence)

    if _is_unverifiable_base(f):
        return _block_unverifiable("sin frutos secos", f)

    return PredicateResult(True, confidence=f.confidence)


def _evaluate_vegano(f: IngredientFacts) -> PredicateResult:
    if f.is_flavoring():
        if f.flavoring_type in (FlavoringType.ARTIFICIAL, FlavoringType.IDENTICAL_TO_NATURAL):
            return PredicateResult(True, confidence=0.92)
        return PredicateResult(True, confidence=f.confidence or 0.7)

    if f.allergens_intersect(ANIMAL_SOURCES):
        matched = f.allergens & ANIMAL_SOURCES
        return PredicateResult(False, f"origen animal: {allergens_es(matched)}", f.confidence)

    if f.origin == Origin.ANIMAL:
        return PredicateResult(False, "ingrediente de origen animal", f.confidence)

    if f.origin in (Origin.PLANT, Origin.SYNTHETIC, Origin.MINERAL):
        return PredicateResult(True, confidence=f.confidence)

    if _is_unverifiable_base(f):
        return _block_unverifiable("vegano", f)

    return PredicateResult(True, confidence=f.confidence * 0.8 if f.confidence > 0 else 0.5)


def _flavoring_default_safe(
    f: IngredientFacts, allergen_set: frozenset, label: str
) -> PredicateResult:
    """
    Política CAA Cap. XVIII para aromatizantes en restricciones médicas.

    Si el target sensorial menciona un alérgeno relevante PERO el calificador
    es artificial/idéntico al natural → safe (síntesis química).
    Si calificador es natural → safe con menor confianza.
    """
    if f.flavoring_type in (FlavoringType.ARTIFICIAL, FlavoringType.IDENTICAL_TO_NATURAL):
        return PredicateResult(True, confidence=0.92)
    if f.flavoring_type == FlavoringType.NATURAL:
        return PredicateResult(True, confidence=0.75)
    return PredicateResult(True, confidence=0.6)


# ═══════════════════════════════════════════════════════════════════════════
# Registro de predicados
# ═══════════════════════════════════════════════════════════════════════════


RESTRICTION_PREDICATES: Dict[str, Callable[[IngredientFacts], PredicateResult]] = {
    "sin_tacc": _evaluate_sin_tacc,
    "sin_lactosa": _evaluate_sin_lactosa,
    "sin_frutos_secos": _evaluate_sin_frutos_secos,
    "vegano": _evaluate_vegano,
}

ALL_RESTRICTIONS = list(RESTRICTION_PREDICATES.keys())


def evaluate_restriction(restriction: str, facts: IngredientFacts) -> PredicateResult:
    """Aplica el predicado de una restricción a un IngredientFacts."""
    predicate = RESTRICTION_PREDICATES.get(restriction)
    if predicate is None:
        return PredicateResult(True, motivo=f"restricción desconocida: {restriction}")
    return predicate(facts)
