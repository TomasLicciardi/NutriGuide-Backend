"""
Overrides contextuales para términos ambiguos del dominio alimentario argentino.

Algunos ingredientes tienen homónimos peligrosos: "burro" en yerba mate es
una hierba (Aloysia polystachya), pero Open Food Facts lo mapea como animal
(lácteo). Sin esta capa, un análisis vegano/sin-lactosa marca el producto
como NO APTO incorrectamente.

Diseño: capa que se ejecuta antes de los lookups externos (KB/Codex/OFF).
Si el ingrediente está en `_AMBIGUOUS_TERMS` y el contexto del producto
incluye indicadores específicos, aplicamos el override y saltamos los demás
lookups — el override es autoritativo.

Para agregar un caso nuevo:
  1. Identificar el término ambiguo y el contexto en que su sentido cambia.
  2. Listar `context_indicators` que solo aparecen en el contexto correcto.
  3. Definir el override con (category, origin, description, confidence, reason).

La confianza por defecto es alta (0.92) porque es una regla de dominio
verificable manualmente — no es una inferencia.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import unicodedata

from app.services.ingredient_facts import (
    IngredientCategory,
    IngredientFacts,
    Origin,
    TagProvenance,
)


@dataclass
class ContextualOverride:
    canonical_name_es: str
    category: IngredientCategory
    origin: Origin
    description_es: str
    confidence: float
    matched_term: str
    matched_context_terms: List[str] = field(default_factory=list)
    reason: str = ""


# Diccionario de términos ambiguos.
# Estructura: { término_normalizado: [ { context_indicators, override } ] }
# Múltiples variantes por término permiten un mismo nombre con desambiguaciones
# distintas según contexto (no se usa todavía, pero la estructura lo permite).
_AMBIGUOUS_TERMS: Dict[str, List[dict]] = {
    "burro": [
        {
            "context_indicators": {
                "yerba", "mate", "menta", "cedron", "poleo", "te",
                "marcela", "boldo", "tilo", "manzanilla", "peperina",
                "hierba", "hierbas", "yuyo", "yuyos",
            },
            "override": {
                "canonical_name_es": "burrito (Aloysia polystachya)",
                "category": IngredientCategory.BASE,
                "origin": Origin.PLANT,
                "description_es": (
                    "Burrito (Aloysia polystachya), hierba aromática usada en "
                    "yerbas mate compuestas. No es el animal Equus africanus."
                ),
                "confidence": 0.92,
                "reason": (
                    "En contexto de yerba mate / infusiones de hierbas, "
                    "'burro' refiere a la hierba Aloysia polystachya."
                ),
            },
        },
    ],
    # Espacio para futuras desambiguaciones:
    #   "ojo de buey" (animal vs especia/pez), "lengua" (animal vs hierba), etc.
}


# Correcciones INCONDICIONALES: ingredientes cuyo nombre induce a una
# clasificación errónea sin importar el contexto. A diferencia de los términos
# ambiguos de arriba, estos siempre tienen el mismo sentido.
#
# Caso canónico: "nuez moscada" contiene "nuez" pero es una especia (semilla de
# Myristica fragrans), NO un fruto seco de árbol — segura para alérgicos a
# frutos secos. Fuentes como Gemini la marcan como nut por el nombre.
# El match es por substring normalizado para cubrir "nuez moscada molida/en polvo".
_KNOWN_OVERRIDES: Dict[str, dict] = {
    "nuez moscada": {
        "canonical_name_es": "nuez moscada",
        "category": IngredientCategory.BASE,
        "origin": Origin.PLANT,
        "description_es": (
            "Especia obtenida de la semilla de Myristica fragrans. Pese a su "
            "nombre, NO es un fruto seco de árbol; es segura para personas con "
            "alergia a frutos secos."
        ),
        "confidence": 0.95,
        "reason": (
            "'nuez moscada' contiene 'nuez' pero es una especia (semilla), "
            "no un fruto seco de árbol."
        ),
    },
}


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").strip()


def resolve_known_ingredient(name_es: str) -> Optional[ContextualOverride]:
    """
    Corrección incondicional para ingredientes cuyo nombre induce a una
    clasificación errónea (homónimos), independientemente del contexto.
    Retorna el override si el nombre coincide por substring normalizado, o None.
    """
    if not name_es:
        return None
    norm = _normalize(name_es)
    for key, data in _KNOWN_OVERRIDES.items():
        if key in norm:
            return ContextualOverride(
                canonical_name_es=data["canonical_name_es"],
                category=data["category"],
                origin=data["origin"],
                description_es=data["description_es"],
                confidence=data["confidence"],
                matched_term=key,
                matched_context_terms=[],
                reason=data["reason"],
            )
    return None


def resolve_ambiguous_term(
    name_es: str,
    context_names: Optional[List[str]],
) -> Optional[ContextualOverride]:
    """
    Si `name_es` es un término ambiguo y el contexto del producto contiene
    al menos un indicador que lo desambigua, retorna el override.
    Caso contrario, retorna None y el flujo normal de enrichment sigue.
    """
    if not name_es:
        return None

    norm_name = _normalize(name_es)
    variants = _AMBIGUOUS_TERMS.get(norm_name)
    if not variants:
        return None

    norm_context = " ".join(
        _normalize(c) for c in (context_names or []) if c and _normalize(c) != norm_name
    )
    if not norm_context:
        return None

    for variant in variants:
        indicators: Set[str] = variant["context_indicators"]
        matched = sorted(ind for ind in indicators if ind in norm_context)
        if matched:
            data = variant["override"]
            return ContextualOverride(
                canonical_name_es=data["canonical_name_es"],
                category=data["category"],
                origin=data["origin"],
                description_es=data["description_es"],
                confidence=data["confidence"],
                matched_term=norm_name,
                matched_context_terms=matched,
                reason=data["reason"],
            )
    return None


def apply_override(facts: IngredientFacts, override: ContextualOverride) -> None:
    """
    Pisa los facts con los valores del override. El override es autoritativo:
    los lookups externos no deben ejecutarse después de esto.
    """
    facts.category = override.category
    facts.origin = override.origin
    facts.description_es = override.description_es
    facts.confidence = max(facts.confidence, override.confidence)

    prov = TagProvenance(
        source="contextual_override",
        confidence=override.confidence,
        evidence=(
            f"Override de homonimia: '{override.matched_term}' en contexto "
            f"con {override.matched_context_terms} -> {override.canonical_name_es}. "
            f"{override.reason}"
        ),
    )
    facts._record_provenance("source:contextual_override", prov)
    facts._record_provenance(f"origin:{override.origin.value}", prov)
