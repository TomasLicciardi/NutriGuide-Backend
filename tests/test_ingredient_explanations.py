"""Diccionario curado: match al inicio de palabra, clave más larga primero."""
from app.services.ingredient_explanations import _curated_match, _normalize, has_curated_explanation


def _m(name):
    return _curated_match(_normalize(name))


def test_prefijo_cubre_derivados():
    assert _m("Caseinato de sodio") == "sal de caseína (proteína láctea)"
    assert _m("Anchoas") is not None


def test_clave_mas_larga_gana():
    assert _m("manteca de cerdo") == "grasa de cerdo"
    assert _m("extracto de malta") == "derivado de cebada germinada (contiene gluten)"


def test_claves_cortas_exigen_palabra_completa():
    assert _m("manitol") is None
    assert _m("maní tostado") is not None
    assert _m("saborizante natural") is None
    assert _m("declarado") is None
    assert _m("maltodextrina") is None


def test_has_curated_explanation_coincide():
    assert has_curated_explanation("Lactosuero en polvo")
    assert not has_curated_explanation("azúcar")
