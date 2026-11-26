"""Sub-ingredientes entre paréntesis: se aplanan y el padre es un grupo."""
from app.services.analysis_pipeline import _flatten_sub_ingredients
from app.services.parser import parse_ingredient_list
from app.services.ingredient_facts import IngredientFacts, IngredientCategory, Origin
from app.services.restriction_predicates import _is_unverifiable_base


def test_aplanar_incluye_los_componentes():
    parsed = _flatten_sub_ingredients(parse_ingredient_list("Arroz, chocolate (azúcar, leche en polvo), sal"))
    nombres = [p.name for p in parsed]
    assert nombres == ["arroz", "chocolate", "azúcar", "leche en polvo", "sal"]
    assert parsed[1].sub_ingredients and not parsed[2].sub_ingredients


def test_grupo_no_bloquea_aunque_no_se_resuelva():
    grupo = IngredientFacts(name_es="mezcla energética", category=IngredientCategory.BASE, origin=Origin.UNKNOWN, is_group=True)
    suelto = IngredientFacts(name_es="mezcla energética", category=IngredientCategory.BASE, origin=Origin.UNKNOWN)
    assert _is_unverifiable_base(grupo) is False
    assert _is_unverifiable_base(suelto) is True
