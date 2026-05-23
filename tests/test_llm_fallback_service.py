"""
Tests del tier LLM fallback para enrichment v3.

El tier 5 ahora opera en batch (una llamada Gemini por imagen, no por
ingrediente). Los tests cubren:
  - Parsing de respuestas individuales (compat con classify())
  - Parsing del array para classify_batch()
  - Threshold y persistencia al KB
  - Hook a nivel de pipeline (apply_llm_batch_fallback)
  - Flag LLM_FALLBACK_ENABLED
  - No invocación cuando todo resolvió antes

Ejecutar:
    python -m pytest tests/test_llm_fallback_service.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.image_analysis_config import KB_CONFIG
from app.core.config import settings
from app.services.enrichment_service import EnrichmentService
from app.services.gemini_service import gemini_service
from app.services.ingredient_facts import (
    ALLERGEN_MILK,
    IngredientCategory,
    IngredientFacts,
    Origin,
)
from app.services.knowledge_base_service import knowledge_base_service
from app.services.llm_fallback_service import _parse_array_response, _parse_response
from app.services.loaders.off_taxonomy_loader import OffTaxonomyEntry
from app.services.parser import ParsedIngredient


class DummyDB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _payload_obj(
    confidence: float = 0.9,
    category: str = "BASE",
    origin: str = "plant",
    allergens=None,
    contains=None,
    derived_from=None,
) -> dict:
    return {
        "category": category,
        "origin": origin,
        "function_tag": None,
        "allergens": allergens or [],
        "contains": contains or [],
        "derived_from": derived_from or [],
        "description_es": "Ingrediente clasificado por fallback",
        "confidence": confidence,
        "reasoning": "Clasificacion controlada para test",
    }


def _payload(**kwargs) -> str:
    return json.dumps(_payload_obj(**kwargs))


def _array(*objs) -> str:
    return json.dumps(list(objs))


# ════════════════════════════════════════════════════════════════════════════
# Parsing — respuesta individual (legacy classify())
# ════════════════════════════════════════════════════════════════════════════


def test_parse_response_valida():
    result = _parse_response(
        _payload(
            category="ADITIVO",
            origin="animal",
            allergens=["milk"],
            contains=["milk"],
            derived_from=["milk"],
        )
    )
    assert result is not None
    assert result.category == IngredientCategory.ADITIVO
    assert result.origin == Origin.ANIMAL
    assert ALLERGEN_MILK in result.allergens
    assert result.confidence == 0.9


def test_parse_response_json_malformado():
    assert _parse_response('{"category":"BASE",') is None


def test_parse_response_filtra_allergen_desconocido():
    result = _parse_response(_payload(allergens=["milk", "alien-protein"]))
    assert result is not None
    assert result.allergens == {ALLERGEN_MILK}


def test_parse_response_confidence_baja_descartada():
    assert _parse_response(_payload(confidence=0.49)) is None
    assert _parse_response(_payload(confidence=0.60)) is not None


# ════════════════════════════════════════════════════════════════════════════
# Parsing — array para classify_batch
# ════════════════════════════════════════════════════════════════════════════


def test_parse_array_response_valida():
    raw = _array(
        _payload_obj(category="BASE", origin="plant"),
        _payload_obj(category="ADITIVO", origin="synthetic"),
    )
    results = _parse_array_response(raw, expected_count=2)
    assert len(results) == 2
    assert results[0] is not None and results[0].origin == Origin.PLANT
    assert results[1] is not None and results[1].category == IngredientCategory.ADITIVO


def test_parse_array_longitud_incorrecta_descarta_todo():
    raw = _array(_payload_obj())  # 1 elemento, esperaban 2
    results = _parse_array_response(raw, expected_count=2)
    assert results == [None, None]


def test_parse_array_no_es_array():
    assert _parse_array_response('{"category":"BASE"}', expected_count=1) == [None]


def test_parse_array_json_malformado():
    assert _parse_array_response("[{", expected_count=3) == [None, None, None]


def test_parse_array_item_individual_invalido_es_none():
    raw = _array(
        _payload_obj(category="BASE"),
        {"category": "INEXISTENTE"},  # categoría inválida
        _payload_obj(category="FLAVORING"),
    )
    results = _parse_array_response(raw, expected_count=3)
    assert results[0] is not None
    assert results[1] is None
    assert results[2] is not None


# ════════════════════════════════════════════════════════════════════════════
# Hook batch a nivel de pipeline (apply_llm_batch_fallback)
# ════════════════════════════════════════════════════════════════════════════


def _make_unresolved_facts(name_es: str) -> IngredientFacts:
    """Construye un IngredientFacts que cae en _should_use_llm_fallback."""
    return IngredientFacts(
        name_es=name_es,
        name_en=None,
        category=IngredientCategory.BASE,
        origin=Origin.UNKNOWN,
        confidence=0.0,
    )


def test_batch_persiste_al_kb_solo_los_que_pasan_threshold(monkeypatch):
    """
    Dos ingredientes a clasificar, uno con confidence alta y otro baja.
    Solo el alto se persiste al KB; el bajo queda unresolved.
    """
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", True)
    monkeypatch.setitem(KB_CONFIG, "min_write_confidence", 0.70)

    service = EnrichmentService()
    db = DummyDB()
    saved = []
    gemini_calls = []

    async def fake_generate_text(*args, **kwargs):
        gemini_calls.append((args, kwargs))
        return _array(
            _payload_obj(confidence=0.92, origin="plant"),  # alto → aplica
            _payload_obj(confidence=0.55, origin="plant"),  # bajo → ignora
        )

    def fake_save(*args, **kwargs):
        saved.append(kwargs)
        return SimpleNamespace(id=1)

    monkeypatch.setattr(gemini_service, "generate_text", fake_generate_text)
    monkeypatch.setattr(knowledge_base_service, "save_ingredient", fake_save)

    facts_list = [_make_unresolved_facts("a"), _make_unresolved_facts("b")]
    parsed_list = [
        ParsedIngredient(name="a", raw_text="a"),
        ParsedIngredient(name="b", raw_text="b"),
    ]

    n = asyncio.run(service.apply_llm_batch_fallback(facts_list, parsed_list, db))

    assert len(gemini_calls) == 1, "debe ser UNA sola llamada para los dos ingredientes"
    assert n == 1, "solo el de confidence alta se aplica"
    assert "llm_fallback" in facts_list[0].sources
    assert facts_list[0].origin == Origin.PLANT
    assert "llm_fallback" not in facts_list[1].sources
    assert facts_list[1].origin == Origin.UNKNOWN
    assert len(saved) == 1
    assert saved[0]["provenance"] == "llm_fallback"
    assert db.commits == 1


def test_batch_no_invoca_gemini_si_no_hay_unresolved(monkeypatch):
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", True)
    service = EnrichmentService()
    db = DummyDB()
    gemini_calls = []

    async def fake_generate_text(*args, **kwargs):
        gemini_calls.append((args, kwargs))
        return _array(_payload_obj())

    monkeypatch.setattr(gemini_service, "generate_text", fake_generate_text)

    # facts ya resueltos por OFF (origin != UNKNOWN)
    resolved = IngredientFacts(
        name_es="agua",
        category=IngredientCategory.BASE,
        origin=Origin.PLANT,
    )
    resolved.sources.append("off_taxonomy")

    n = asyncio.run(
        service.apply_llm_batch_fallback(
            [resolved],
            [ParsedIngredient(name="agua", raw_text="agua")],
            db,
        )
    )

    assert n == 0
    assert gemini_calls == []


def test_batch_flag_desactivado_no_llama_a_gemini(monkeypatch):
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", False)
    service = EnrichmentService()
    db = DummyDB()
    gemini_calls = []

    async def fake_generate_text(*args, **kwargs):
        gemini_calls.append((args, kwargs))
        return _array(_payload_obj())

    monkeypatch.setattr(gemini_service, "generate_text", fake_generate_text)

    facts_list = [_make_unresolved_facts("ingrediente raro")]
    parsed_list = [ParsedIngredient(name="ingrediente raro", raw_text="ingrediente raro")]

    n = asyncio.run(service.apply_llm_batch_fallback(facts_list, parsed_list, db))

    assert n == 0
    assert gemini_calls == []
    assert facts_list[0].origin == Origin.UNKNOWN


def test_batch_una_llamada_para_n_ingredientes(monkeypatch):
    """
    Verifica el invariante clave: N ingredientes unresolved → 1 sola llamada
    a Gemini, no N. Es lo que protege la cuota free tier.
    """
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", True)
    monkeypatch.setitem(KB_CONFIG, "min_write_confidence", 0.70)

    service = EnrichmentService()
    db = DummyDB()
    gemini_calls = []

    async def fake_generate_text(*args, **kwargs):
        gemini_calls.append((args, kwargs))
        return _array(*[_payload_obj(confidence=0.85) for _ in range(5)])

    def fake_save(*args, **kwargs):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(gemini_service, "generate_text", fake_generate_text)
    monkeypatch.setattr(knowledge_base_service, "save_ingredient", fake_save)

    facts_list = [_make_unresolved_facts(f"ing_{i}") for i in range(5)]
    parsed_list = [ParsedIngredient(name=f"ing_{i}", raw_text=f"ing_{i}") for i in range(5)]

    n = asyncio.run(service.apply_llm_batch_fallback(facts_list, parsed_list, db))

    assert len(gemini_calls) == 1, "DEBE ser una sola llamada para los 5 ingredientes"
    assert n == 5


def test_batch_fallo_gemini_no_aplica_nada(monkeypatch):
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", True)
    service = EnrichmentService()
    db = DummyDB()

    async def fake_generate_text(*args, **kwargs):
        return None  # como si Gemini fallase / 429 sin retry exitoso

    monkeypatch.setattr(gemini_service, "generate_text", fake_generate_text)

    facts_list = [_make_unresolved_facts("x"), _make_unresolved_facts("y")]
    parsed_list = [
        ParsedIngredient(name="x", raw_text="x"),
        ParsedIngredient(name="y", raw_text="y"),
    ]
    n = asyncio.run(service.apply_llm_batch_fallback(facts_list, parsed_list, db))

    assert n == 0
    assert all(f.origin == Origin.UNKNOWN for f in facts_list)
    assert db.commits == 0


# ════════════════════════════════════════════════════════════════════════════
# enrich_one ya NO debe llamar al LLM (regression test)
# ════════════════════════════════════════════════════════════════════════════


def test_enrich_one_no_llama_al_llm_directamente(monkeypatch):
    """
    enrich_one no debe disparar Gemini; el tier 5 vive en el orquestador.
    Esto previene regresiones a la versión anterior que llamaba per-ingrediente.
    """
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", True)
    service = EnrichmentService()
    db = DummyDB()
    gemini_calls = []

    async def no_lookup(*args, **kwargs):
        return None

    async def fake_generate_text(*args, **kwargs):
        gemini_calls.append((args, kwargs))
        return _payload(confidence=0.9)

    monkeypatch.setattr(service, "_lookup_kb_candidates", no_lookup)
    monkeypatch.setattr(service, "_lookup_off_candidates", no_lookup)
    monkeypatch.setattr(gemini_service, "generate_text", fake_generate_text)

    parsed = ParsedIngredient(name="ingrediente raro", raw_text="ingrediente raro")
    facts = asyncio.run(service.enrich_one(parsed, db, name_en=None))

    assert gemini_calls == [], "enrich_one NO debe llamar a Gemini"
    assert facts.origin == Origin.UNKNOWN  # default-unsafe se aplicará en predicados


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
