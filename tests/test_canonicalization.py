from app.services.canonicalization_service import canonicalization_service
from app.services.parser import parse_ingredient_list


def _canon(text: str):
    parsed = parse_ingredient_list(text)[0]
    return canonicalization_service.canonicalize(parsed)


def test_enriched_wheat_flour_variants_canonicalize():
    variants = [
        "harina de trigo enriquecida",
        "harina de trigo 000 enriquecida",
        "harina de trigo 0000 enriquecida",
        "harina de trigo tipo 000 enriquecida",
    ]
    for variant in variants:
        result = _canon(variant)
        assert result.canonical_name_es == "harina enriquecida"
        assert result.source.startswith("pattern:")


def test_additive_color_and_synonym_aliases():
    assert _canon("caramelo III").canonical_name_es == "caramelo"
    assert _canon("cloruro de sodio").canonical_name_es == "sal"


def test_vitamin_aliases_are_data_driven():
    result = _canon("vitamina B2")
    assert result.canonical_name_es == "riboflavina"
    assert result.canonical_name_en == "riboflavin"


def test_additive_synonyms_canonicalize():
    result = _canon("inosinato de sodio")
    assert result.canonical_name_es == "inosinato disodico"
    assert _canon("rocú").canonical_name_es == "annatto"


def test_cheese_varieties_canonicalize_without_vegan_cheese():
    assert _canon("queso sardo").canonical_name_es == "queso"
    assert _canon("queso mar del plata").canonical_name_es == "queso"
    assert _canon("queso de almendra").canonical_name_es == "queso de almendra"


def test_processing_state_candidates_keep_original_as_fallback():
    # La regla milk_variants normaliza las variedades de leche al termino
    # canonico "leche" (misma huella alergenica). El nombre original se
    # conserva como candidato de fallback para el lookup en KB/OFF.
    result = _canon("leche entera pasteurizada")
    assert result.canonical_name_es == "leche"
    assert "leche entera pasteurizada" in result.candidates_es


def test_dataset_gap_aliases_are_generalized():
    assert _canon("cacao alcalinizado").canonical_name_es == "cacao alcalinizado en polvo"
    assert _canon("hidrolizado de prote\u00edna de ma\u00edz").canonical_name_es == "proteina de maiz"
    assert _canon("grasa bovina").canonical_name_es == "grasa bovina"
