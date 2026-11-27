"""El ingrediente que bloquea por derived_from figura como disparador con explicación."""
from app.services.analysis_pipeline import AnalysisPipeline
from app.services.ingredient_facts import IngredientFacts, IngredientCategory, Origin
from app.services.ingredient_explanations import explain_ingredient


def _avena():
    f = IngredientFacts(name_es="harina de avena", category=IngredientCategory.BASE, origin=Origin.PLANT)
    f.derived_from.add("oats")
    return f


def test_harina_de_avena_es_disparador_de_sin_tacc():
    triggers = AnalysisPipeline._find_trigger_ingredients("sin_tacc", [_avena()])
    assert [t.name for t in triggers] == ["harina de avena"]
    assert "avena" in triggers[0].allergen
    assert "avena" in triggers[0].explanation


def test_explicacion_generica_por_derivado():
    assert "avena" in explain_ingredient(_avena())
