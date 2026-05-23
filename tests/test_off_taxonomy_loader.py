# tests/test_off_taxonomy_loader.py
"""
Tests del loader de OFF taxonomy contra un cache SQLite construido on-the-fly.

Fixture sintético: un mini-archivo `ingredients.txt` con cuatro entries que
ejercita lo que necesitamos validar:
  - lookup exacto en español
  - lookup en inglés
  - herencia de propiedades por parents (vegan)
  - propagación de allergens y derived_from desde ancestros
  - comportamiento ante un nombre inexistente

Ejecutar:
    python -m pytest tests/test_off_taxonomy_loader.py -v
    python tests/test_off_taxonomy_loader.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.ingredient_facts import (
    ALLERGEN_DAIRY,
    ALLERGEN_GLUTEN,
    ALLERGEN_MILK,
    ALLERGEN_WHEAT,
    Origin,
)
from app.services.loaders.off_taxonomy_loader import (
    OffTaxonomyLoader,
    _taxonomy_id_matches,
)
from scripts.build_off_cache import parse_taxonomy, write_sqlite


# ════════════════════════════════════════════════════════════════════════════
# Fixture: mini ingredients.txt sintético
# ════════════════════════════════════════════════════════════════════════════

# Cuatro entries:
#   1. en:wheat — base, declara vegan:yes y allergens:wheat
#   2. en:wheat-flour — hijo de wheat (debería heredar vegan:yes y wheat allergen)
#   3. en:cocoa — base, vegan:yes
#   4. en:cocoa-butter — hijo de cocoa (hereda vegan:yes; sin allergens propios)
#   5. en:milk — base, vegan:no, allergens:milk
SYNTHETIC_TAXONOMY = """\
# Mini taxonomy para tests
synonyms:en: cocoa, cacao
stopwords:en: of, the

en: Wheat, wheats
es: trigo
fr: blé
vegan:en: yes
vegetarian:en: yes
allergens:en: en:wheat
description:es: Cereal del género Triticum

< en:wheat
en: Wheat flour, flour wheat
es: harina de trigo, harina trigo
fr: farine de blé

en: Cocoa, cacao
es: cacao
vegan:en: yes
vegetarian:en: yes

< en:cocoa
en: Cocoa butter
es: manteca de cacao, mantequilla de cacao

en: Milk
es: leche
vegan:en: no
vegetarian:en: yes
allergens:en: en:milk
"""


def _build_synthetic_db(tmp_path: Path) -> Path:
    """Parsea el fixture sintético y construye un SQLite en tmp_path."""
    entries = parse_taxonomy(SYNTHETIC_TAXONOMY)
    db_path = tmp_path / "off_test.sqlite"
    write_sqlite(entries, db_path, source="<synthetic>")
    return db_path


def _make_loader(db_path: Path) -> OffTaxonomyLoader:
    loader = OffTaxonomyLoader(db_path=db_path)
    loader.initialize()
    return loader


# ════════════════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════════════════


def test_taxonomy_prefix_match_uses_real_boundaries():
    # Test legacy preservado.
    assert _taxonomy_id_matches("en:malt-extract", "en:malt")
    assert not _taxonomy_id_matches("en:maltodextrin", "en:malt")


def test_lookup_finds_entry_by_spanish_synonym(tmp_path):
    loader = _make_loader(_build_synthetic_db(tmp_path))
    entry = asyncio.run(loader.lookup("trigo"))
    assert entry is not None
    assert entry.in_taxonomy
    assert entry.taxonomy_id == "en:wheat"
    assert entry.vegan == "yes"
    assert entry.origin == Origin.PLANT
    assert ALLERGEN_WHEAT in entry.allergens
    assert ALLERGEN_GLUTEN in entry.allergens  # mapping wheat → gluten también
    assert "wheat" in entry.derived_from


def test_lookup_finds_entry_by_english_name(tmp_path):
    loader = _make_loader(_build_synthetic_db(tmp_path))
    entry = asyncio.run(loader.lookup("milk"))
    assert entry is not None
    assert entry.taxonomy_id == "en:milk"
    assert entry.vegan == "no"
    assert entry.origin == Origin.ANIMAL
    assert ALLERGEN_MILK in entry.allergens
    assert ALLERGEN_DAIRY in entry.allergens


def test_child_inherits_vegan_from_parent(tmp_path):
    """manteca de cacao no declara vegan, debe heredarlo de cacao (yes)."""
    loader = _make_loader(_build_synthetic_db(tmp_path))
    entry = asyncio.run(loader.lookup("manteca de cacao"))
    assert entry is not None
    assert entry.taxonomy_id == "en:cocoa-butter"
    assert entry.vegan == "yes"
    assert entry.origin == Origin.PLANT


def test_child_inherits_allergens_from_parent(tmp_path):
    """harina de trigo no declara allergens, hereda de wheat."""
    loader = _make_loader(_build_synthetic_db(tmp_path))
    entry = asyncio.run(loader.lookup("harina de trigo"))
    assert entry is not None
    assert entry.taxonomy_id == "en:wheat-flour"
    assert ALLERGEN_WHEAT in entry.allergens
    assert ALLERGEN_GLUTEN in entry.allergens
    assert "wheat" in entry.derived_from


def test_lookup_normalizes_accents_and_case(tmp_path):
    loader = _make_loader(_build_synthetic_db(tmp_path))
    # "TRIGO" en mayúsculas y "Harina De Trigo" deberían matchear.
    e1 = asyncio.run(loader.lookup("TRIGO"))
    e2 = asyncio.run(loader.lookup("Harina De Trigo"))
    assert e1 is not None and e1.taxonomy_id == "en:wheat"
    assert e2 is not None and e2.taxonomy_id == "en:wheat-flour"


def test_lookup_returns_none_for_unknown(tmp_path):
    loader = _make_loader(_build_synthetic_db(tmp_path))
    entry = asyncio.run(loader.lookup("yerba mate del paraguay"))
    assert entry is None


def test_lookup_works_via_alternate_synonym(tmp_path):
    """'mantequilla de cacao' es sinónimo registrado de 'manteca de cacao'."""
    loader = _make_loader(_build_synthetic_db(tmp_path))
    entry = asyncio.run(loader.lookup("mantequilla de cacao"))
    assert entry is not None
    assert entry.taxonomy_id == "en:cocoa-butter"
    assert entry.vegan == "yes"


# ════════════════════════════════════════════════════════════════════════════
# Runner standalone
# ════════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        db_path = _build_synthetic_db(tmp_path)
        loader = _make_loader(db_path)

        try:
            print("\n=== Tests del loader de OFF taxonomy ===\n")
            cases = [
                ("trigo", "en:wheat", "yes", {"wheat", "gluten"}),
                ("milk", "en:milk", "no", {"milk", "dairy", "lactose"}),
                ("manteca de cacao", "en:cocoa-butter", "yes", set()),
                ("harina de trigo", "en:wheat-flour", "yes", {"wheat", "gluten"}),
                ("yerba mate", None, None, None),
            ]
            for name, expect_id, expect_vegan, expect_allergens in cases:
                result = asyncio.run(loader.lookup(name))
                if expect_id is None:
                    status = "OK" if result is None else "FAIL"
                    print(f"[{status}] '{name}' -> None (esperado)")
                    continue
                if result is None:
                    print(f"[FAIL] '{name}' -> None pero esperaba {expect_id}")
                    continue
                ok = (
                    result.taxonomy_id == expect_id
                    and result.vegan == expect_vegan
                    and (expect_allergens is None or expect_allergens.issubset(result.allergens))
                )
                print(
                    f"[{'OK' if ok else 'FAIL'}] '{name}' -> "
                    f"{result.taxonomy_id}, vegan={result.vegan}, "
                    f"allergens={sorted(result.allergens)}, "
                    f"origin={result.origin.value}"
                )
            print()
        finally:
            # Cierre explícito para que Windows libere el handle del SQLite
            # antes que tempfile intente borrar el directorio.
            loader.close()
