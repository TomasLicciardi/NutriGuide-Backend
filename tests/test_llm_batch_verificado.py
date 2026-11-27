"""El lote LLM lleva lo que las fuentes ya verificaron de cada ingrediente."""
from app.services.enrichment_service import EnrichmentService
from app.services.ingredient_facts import IngredientFacts, IngredientCategory, Origin, TagProvenance
from app.services.llm_fallback_service import _format_item, _align_by_name


def _lactosuero():
    f = IngredientFacts(name_es="lactosuero", name_en="whey", category=IngredientCategory.BASE, origin=Origin.ANIMAL)
    prov = TagProvenance(source="off_taxonomy", confidence=0.85, evidence="OFF")
    f.add_allergen("milk", prov)
    f.add_derived_from("milk", prov)
    f._record_provenance("source:off_taxonomy", prov)
    return f


def test_resumen_verificado_en_espanol():
    hint = EnrichmentService._verified_hint(_lactosuero())
    assert hint.startswith("verificado por Open Food Facts:")
    assert "alérgenos: leche" in hint
    assert "deriva de: leche" in hint
    assert "origen: animal" in hint


def test_sin_datos_no_hay_resumen():
    f = IngredientFacts(name_es="goma guar", category=IngredientCategory.BASE, origin=Origin.UNKNOWN)
    assert EnrichmentService._verified_hint(f) is None


def test_prompt_lleva_la_linea_ya_verificado():
    line = _format_item(0, ("lactosuero", "whey", "verificado por Open Food Facts: alérgenos: leche"))
    assert line.startswith("1. lactosuero (en: whey)")
    assert "YA_VERIFICADO: verificado por Open Food Facts" in line
    assert "YA_VERIFICADO" not in _format_item(1, ("goma guar", "guar gum"))
    assert "YA_VERIFICADO" not in _format_item(2, ("goma guar", "guar gum", None))


def test_emparejamiento_acepta_tuplas_de_tres():
    raw = '[{"name": "lactosuero", "category": "BASE", "origin": "animal", "allergens": ["milk"], "contains": [], "derived_from": ["milk"], "description_es": "proteína de la leche", "confidence": 0.9, "reasoning": "x"}]'
    aligned = _align_by_name(raw, [("lactosuero", "whey", "verificado por Open Food Facts: alérgenos: leche")])
    assert aligned[0] is not None and aligned[0].description_es == "proteína de la leche"
