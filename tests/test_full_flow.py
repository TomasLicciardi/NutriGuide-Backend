# tests/test_full_flow.py
"""
Test integral del flujo completo de NutriGuide.

Secciones:
  A) Precision de los 42 test cases existentes
  B) Distincion vegano vs vegetariano (casos criticos)
  C) Simulacion de pipeline completo con ingredientes desconocidos
     - Clasificador determinista
     - Simulacion de DB lookup
     - Simulacion de embeddings (similitud)
     - Simulacion de Gemini fallback
     - Aprendizaje (guardar en DB simulada)
  D) Metricas finales
"""

import sys
import os
import unicodedata
from typing import Dict, List, Tuple
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils.allergen_parser import parse_allergen_text
from app.services.deterministic_classifier import (
    classifier, DeterministicClassifier, IngredientClassification,
    ProductClassification, ALL_RESTRICTIONS,
)

# ═══════════════════════════════════════════════════════════════════════════════
# SECCION A: Precision base con los 42 tests
# ═══════════════════════════════════════════════════════════════════════════════

from test_classification import TEST_CASES, run_single_test


def run_section_a():
    print("\n" + "=" * 80)
    print(" SECCION A: Precision determinista (42 etiquetas reales)")
    print("=" * 80)

    passed = 0
    failed = 0
    total_r = 0
    correct_r = 0

    for case in TEST_CASES:
        result = run_single_test(case)
        if result["passed"]:
            passed += 1
        else:
            failed += 1
            print(f"  [FAIL] {result['id']}: {result['desc']}")
            for err in result["errors"]:
                print(f"    {err}")

        for r_data in result["results"].values():
            total_r += 1
            if r_data["ok"]:
                correct_r += 1

    pct = 100 * correct_r / total_r if total_r else 0
    print(f"\n  Resultado: {passed}/{len(TEST_CASES)} tests OK")
    print(f"  Precision: {correct_r}/{total_r} restricciones correctas ({pct:.1f}%)")
    if failed:
        print(f"  !! {failed} tests fallaron")
    else:
        print(f"  TODOS LOS 42 TESTS PASARON")

    return failed == 0, pct


# ═══════════════════════════════════════════════════════════════════════════════
# SECCION B: Distincion vegano vs vegetariano
# ═══════════════════════════════════════════════════════════════════════════════

VEGAN_VS_VEGETARIAN_CASES = [
    {
        "desc": "Huevo liquido -> NO vegano, SI vegetariano",
        "ingredient": "huevo líquido pasteurizado",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Leche entera -> NO vegano, SI vegetariano",
        "ingredient": "leche entera",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Queso sardo -> NO vegano, SI vegetariano",
        "ingredient": "queso sardo",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Miel -> NO vegano, SI vegetariano",
        "ingredient": "miel",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Cera de abeja -> NO vegano, SI vegetariano",
        "ingredient": "cera de abeja",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Suero de leche -> NO vegano, SI vegetariano",
        "ingredient": "suero de leche en polvo",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Yema de huevo -> NO vegano, SI vegetariano",
        "ingredient": "yema de huevo pasteurizada",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Carne bovina -> NO vegano, NO vegetariano",
        "ingredient": "carne bovina deshidratada",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": True,
    },
    {
        "desc": "Carne aviar (pollo) -> NO vegano, NO vegetariano",
        "ingredient": "carne aviar",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": True,
    },
    {
        "desc": "Gelatina (animal) -> NO vegano, NO vegetariano",
        "ingredient": "gelatina",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": True,
    },
    {
        "desc": "Gelatina vegetal -> SI vegano, SI vegetariano",
        "ingredient": "gelatina vegetal",
        "expect_vegano_affected": False,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Primer jugo bovino -> NO vegano, NO vegetariano",
        "ingredient": "primer jugo bovino",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": True,
    },
    {
        "desc": "Grasa bovina -> NO vegano, NO vegetariano",
        "ingredient": "grasa bovina refinada",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": True,
    },
    {
        "desc": "Atun -> NO vegano, NO vegetariano",
        "ingredient": "atún en aceite",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": True,
    },
    {
        "desc": "Carmin (INS 120, insecto) -> NO vegano, SI vegetariano",
        "ingredient": "carmín (INS 120)",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Leche de coco -> SI vegano, SI vegetariano (safe compound)",
        "ingredient": "leche de coco",
        "expect_vegano_affected": False,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Manteca de cacao -> SI vegano, SI vegetariano (safe compound)",
        "ingredient": "manteca de cacao",
        "expect_vegano_affected": False,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Acido lactico -> SI vegano (safe compound, NO es lacteo)",
        "ingredient": "ácido láctico",
        "expect_vegano_affected": False,
        "expect_vegetariano_affected": False,
    },
    {
        "desc": "Nuez moscada -> SI para frutos secos (safe compound)",
        "ingredient": "nuez moscada",
        "expect_nuez_safe": True,
    },
    {
        "desc": "Jamon -> NO vegano, NO vegetariano",
        "ingredient": "jamón cocido",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": True,
    },
    {
        "desc": "Caseinato de sodio -> NO vegano, SI vegetariano",
        "ingredient": "caseinato de sodio",
        "expect_vegano_affected": True,
        "expect_vegetariano_affected": False,
    },
]


def run_section_b():
    print("\n" + "=" * 80)
    print(" SECCION B: Distincion VEGANO vs VEGETARIANO (21 casos criticos)")
    print("=" * 80)

    passed = 0
    failed = 0

    for case in VEGAN_VS_VEGETARIAN_CASES:
        result = classifier.classify_ingredient(case["ingredient"])
        errors = []

        if "expect_nuez_safe" in case:
            nuez_affected = "sin_frutos_secos" in result.restrictions_affected
            if nuez_affected:
                errors.append(f"sin_frutos_secos deberia ser APTO (safe compound)")
        else:
            vegano_affected = "vegano" in result.restrictions_affected
            vegetariano_affected = "vegetariano" in result.restrictions_affected

            if vegano_affected != case["expect_vegano_affected"]:
                errors.append(
                    f"vegano: esperado={'AFECTA' if case['expect_vegano_affected'] else 'NO AFECTA'}, "
                    f"obtenido={'AFECTA' if vegano_affected else 'NO AFECTA'}"
                )
            if vegetariano_affected != case["expect_vegetariano_affected"]:
                errors.append(
                    f"vegetariano: esperado={'AFECTA' if case['expect_vegetariano_affected'] else 'NO AFECTA'}, "
                    f"obtenido={'AFECTA' if vegetariano_affected else 'NO AFECTA'}"
                )

        if errors:
            failed += 1
            print(f"  [FAIL] {case['desc']}")
            print(f"         Ingrediente: \"{case['ingredient']}\"")
            print(f"         Restricciones afectadas: {result.restrictions_affected}")
            for err in errors:
                print(f"         {err}")
        else:
            passed += 1
            extras = ""
            if result.restrictions_affected:
                extras = f" -> afecta: {list(result.restrictions_affected.keys())}"
            elif result.status == "needs_ai":
                extras = " -> needs_ai (sin keywords)"
            else:
                extras = " -> seguro (safe compound o essential)"
            print(f"  [OK]   {case['desc']}{extras}")

    print(f"\n  Resultado: {passed}/{len(VEGAN_VS_VEGETARIAN_CASES)} distinciones correctas")
    if failed:
        print(f"  !! {failed} distinciones fallaron")
    else:
        print(f"  TODAS LAS DISTINCIONES VEGANO/VEGETARIANO SON CORRECTAS")

    return failed == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SECCION C: Simulacion de pipeline completo con ingredientes desconocidos
# ═══════════════════════════════════════════════════════════════════════════════

SIMULATED_GEMINI_RESPONSES: Dict[str, Dict[str, bool]] = {
    "jarabe de maiz de alta fructosa": {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "cacao alcalinizado":              {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "aromatizante artificial a vainilla": {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "jugo concentrado de naranja":     {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "aromatizante identico al natural de naranja": {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "pulpa de durazno":                {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "almidon modificado":              {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "aromatizante natural a durazno":  {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "cultivos lacticos":               {"dairy": True,  "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "annatto":                         {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "aromatizantes artificiales":      {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "jarabe de glucosa":               {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "cacao en polvo":                  {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "fideos":                          {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": True,  "nuts": False},
    "curcuma":                         {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "perejil":                         {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "cebolla":                         {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "apio":                            {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "aromatizante identico al natural a pollo": {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "aceite vegetal fraccionado":       {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "aromatizante artificial a vainilla": {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "colageno hidrolizado":            {"dairy": False, "egg": False, "meat_fish": True,  "honey_insect": False, "gluten": False, "nuts": False},
    "proteina de soja":                {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "extracto de levadura":            {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "agar agar":                       {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "aceite vegetal de palma":          {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "levadura":                        {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "especias":                        {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
    "sorbato de potasio":              {"dairy": False, "egg": False, "meat_fish": False, "honey_insect": False, "gluten": False, "nuts": False},
}


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()


PIPELINE_PRODUCTS = [
    {
        "id": "sim_01",
        "desc": "Yogur con durazno (leche, gelatina, cultivos lacticos)",
        "ingredients": [
            "leche entera pasteurizada", "azucar",
            "pulpa de durazno", "almidon modificado",
            "aromatizante natural a durazno",
            "sorbato de potasio", "annatto",
            "leche en polvo descremada",
            "cultivos lacticos", "gelatina",
        ],
        "allergens": "CONTIENE LECHE.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": True,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "sim_02",
        "desc": "Sopa de pollo (carne, fideos, curcuma, apio)",
        "ingredients": [
            "fideos", "harina de trigo enriquecida ley 25.630",
            "agua", "curcuma", "sal", "almidon de maiz", "azucar",
            "aceite vegetal de palma",
            "glutamato monosodico (INS 621)",
            "inosinato disodico (INS 631)",
            "carne de pollo deshidratada",
            "perejil", "cebolla", "apio",
            "aromatizante identico al natural a pollo",
            "caramelo IV (INS 150d)",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO Y APIO. PUEDE CONTENER HUEVO, SOJA Y DERIVADOS DE LECHE.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": False,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "sim_03",
        "desc": "Suplemento con colageno (ingrediente critico desconocido)",
        "ingredients": [
            "agua", "azucar", "colageno hidrolizado",
            "acido citrico", "sorbato de potasio",
            "aromatizante artificial a vainilla",
        ],
        "allergens": "",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "sim_04",
        "desc": "Pan vegano con agar-agar (sin ningun animal)",
        "ingredients": [
            "harina de trigo enriquecida", "agua", "levadura",
            "azucar", "sal", "aceite de girasol",
            "agar agar", "extracto de levadura",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "sim_05",
        "desc": "Galletitas dulces (ingredientes repetidos de sim_01/02)",
        "ingredients": [
            "harina de trigo enriquecida", "azucar",
            "aceite de girasol", "jarabe de glucosa",
            "cacao en polvo", "sal",
            "aromatizante artificial a vainilla",
            "lecitina de soja (INS 322)",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO Y SOJA.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "sim_06",
        "desc": "Salchicha con colageno (aprendido de sim_03)",
        "ingredients": [
            "carne bovina", "agua", "sal", "especias",
            "colageno hidrolizado", "proteina de soja",
            "sorbato de potasio", "carmin (INS 120)",
        ],
        "allergens": "",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
]


def run_section_c():
    print("\n" + "=" * 80)
    print(" SECCION C: Simulacion de pipeline COMPLETO (cold start -> aprendizaje)")
    print("=" * 80)
    print(" Simula: Determinista -> DB lookup -> Embeddings -> Gemini -> Aprender")

    simulated_db: Dict[str, Dict[str, bool]] = {}

    total_ingredients = 0
    total_deterministic = 0
    total_ins = 0
    total_essential = 0
    total_from_db = 0
    total_from_embedding = 0
    total_gemini = 0
    all_verdicts_correct = True
    total_verdicts = 0
    correct_verdicts = 0

    for product in PIPELINE_PRODUCTS:
        allergen_result = parse_allergen_text(product["allergens"])
        classification = classifier.classify_product(
            product["ingredients"], allergen_result,
        )

        from_db = []
        from_embedding = []
        from_gemini = []

        for ing in classification.classified_ingredients:
            if ing.status == "needs_ai":
                norm = ing.name_normalized

                # Nivel 1: DB lookup exacto
                if norm in simulated_db:
                    from_db.append((ing.name, simulated_db[norm]))
                    gemini_resp = simulated_db[norm]
                    ing.resolved_by = "db"
                    ing.status = "known"
                    ing.confidence = 0.92

                # Nivel 2: embedding similarity (buscar keys similares)
                else:
                    embedding_match = None
                    for db_key, db_val in simulated_db.items():
                        if _simple_similarity(norm, db_key) > 0.7:
                            embedding_match = (db_key, db_val)
                            break

                    if embedding_match:
                        from_embedding.append((ing.name, embedding_match[0]))
                        gemini_resp = embedding_match[1]
                        ing.resolved_by = "embedding"
                        ing.status = "known"
                        ing.confidence = 0.88

                    # Nivel 3: Gemini fallback
                    elif norm in SIMULATED_GEMINI_RESPONSES:
                        gemini_resp = SIMULATED_GEMINI_RESPONSES[norm]
                        from_gemini.append(ing.name)
                        ing.resolved_by = "rag_gemini"
                        ing.status = "known"
                        ing.confidence = 0.85
                        simulated_db[norm] = gemini_resp
                    else:
                        gemini_resp = {"dairy": False, "egg": False, "meat_fish": False,
                                       "honey_insect": False, "gluten": False, "nuts": False}
                        from_gemini.append(ing.name)
                        ing.resolved_by = "default"
                        ing.status = "known"
                        ing.confidence = 0.60
                        simulated_db[norm] = gemini_resp

                classifier.apply_external_classification(
                    classification, ing.name, gemini_resp,
                )

        total_ingredients += classification.stats["total"]
        total_deterministic += classification.stats["by_deterministic"]
        total_ins += classification.stats["by_ins_code"]
        total_essential += classification.stats["by_essential_safe"]
        total_from_db += len(from_db)
        total_from_embedding += len(from_embedding)
        total_gemini += len(from_gemini)

        print(f"\n{'~' * 80}")
        print(f"  {product['id']}: {product['desc']}")
        print(f"{'~' * 80}")
        print(f"  Ingredientes totales: {classification.stats['total']}")
        print(f"    Determinista (keywords): {classification.stats['by_deterministic']}")
        print(f"    INS codes:              {classification.stats['by_ins_code']}")
        print(f"    Base esencial:          {classification.stats['by_essential_safe']}")
        print(f"    DB lookup (aprendido):  {len(from_db)}")
        print(f"    Embedding (similar):    {len(from_embedding)}")
        print(f"    Gemini (IA):            {len(from_gemini)}")

        if from_db:
            print(f"\n    Resueltos por DB (aprendizaje previo):")
            for name, _ in from_db:
                print(f"      [DB]        \"{name}\"")

        if from_embedding:
            print(f"\n    Resueltos por embedding (similitud semantica):")
            for name, matched_key in from_embedding:
                print(f"      [EMBEDDING] \"{name}\" ~ \"{matched_key}\"")

        if from_gemini:
            print(f"\n    Resueltos por Gemini (llamada IA):")
            for name in from_gemini:
                norm = _normalize(name)
                resp = simulated_db.get(norm, {})
                flags = [k for k, v in resp.items() if v]
                flag_str = ", ".join(flags) if flags else "todo seguro"
                print(f"      [GEMINI]    \"{name}\" -> {flag_str} -> GUARDADO EN DB")

        r = classification.restrictions
        print(f"\n    Veredicto final:")
        product_ok = True
        for rest in ALL_RESTRICTIONS:
            expected_apto = product["expected"][rest]
            actual_apto = r[rest]["apto"]
            ok = expected_apto == actual_apto
            total_verdicts += 1
            if ok:
                correct_verdicts += 1
            else:
                product_ok = False
                all_verdicts_correct = False

            status = "APTO" if actual_apto else "NO APTO"
            expected_str = "APTO" if expected_apto else "NO APTO"
            marker = "OK" if ok else "FAIL"
            motivo = f" ({r[rest]['motivo']})" if r[rest].get('motivo') else ""
            print(f"      [{marker}] {rest:20s} = {status:8s} (esperado: {expected_str}){motivo}")

        if not product_ok:
            print(f"    !! VEREDICTO INCORRECTO en este producto")

    # Resumen
    print(f"\n{'=' * 80}")
    print(f" RESUMEN PIPELINE ({len(PIPELINE_PRODUCTS)} productos, {total_ingredients} ingredientes)")
    print(f"{'=' * 80}")
    print(f"  Por determinista (keywords): {total_deterministic:>3}")
    print(f"  Por INS codes:               {total_ins:>3}")
    print(f"  Por base esencial:           {total_essential:>3}")
    print(f"  Por DB (aprendizaje):        {total_from_db:>3}")
    print(f"  Por embedding (similitud):   {total_from_embedding:>3}")
    print(f"  Por Gemini (IA):             {total_gemini:>3}")
    print(f"{'~' * 80}")
    print(f"  Ingredientes en DB al final: {len(simulated_db):>3}")
    print(f"  Llamadas Gemini reales:      {total_gemini:>3}")
    print(f"  Llamadas ahorradas (DB+emb): {total_from_db + total_from_embedding:>3}")
    print(f"{'~' * 80}")
    pct = 100 * correct_verdicts / total_verdicts if total_verdicts else 0
    print(f"  Veredictos correctos: {correct_verdicts}/{total_verdicts} ({pct:.1f}%)")
    if all_verdicts_correct:
        print(f"  TODOS LOS VEREDICTOS DEL PIPELINE SON CORRECTOS")
    else:
        print(f"  !! Hay veredictos incorrectos")

    return all_verdicts_correct, pct


def _simple_similarity(a: str, b: str) -> float:
    """Similitud basica por tokens compartidos (simula embedding similarity)."""
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    jaccard = len(intersection) / len(union)
    prefix_match = 1.0 if a[:5] == b[:5] else 0.0
    return min(1.0, jaccard * 0.7 + prefix_match * 0.3)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "#" * 80)
    print("#" + " " * 20 + "NUTRIGUIDE - TEST INTEGRAL DE FLUJO" + " " * 23 + "#")
    print("#" * 80)

    ok_a, pct_a = run_section_a()
    ok_b = run_section_b()
    ok_c, pct_c = run_section_c()

    print("\n" + "#" * 80)
    print("#" + " " * 25 + "RESULTADO FINAL" + " " * 38 + "#")
    print("#" * 80)

    all_ok = ok_a and ok_b and ok_c

    print(f"\n  Seccion A (42 etiquetas):            {'PASS' if ok_a else 'FAIL'} - {pct_a:.1f}% precision")
    print(f"  Seccion B (vegano vs vegetariano):   {'PASS' if ok_b else 'FAIL'}")
    print(f"  Seccion C (pipeline + aprendizaje):  {'PASS' if ok_c else 'FAIL'} - {pct_c:.1f}% precision")
    print()

    if all_ok:
        print("  === TODAS LAS SECCIONES PASARON ===")
        print("  El sistema clasifica correctamente:")
        print("    - 42 etiquetas reales argentinas")
        print("    - Distincion vegano vs vegetariano")
        print("    - Pipeline completo con ingredientes desconocidos")
        print("    - Aprendizaje: ingredientes resueltos se reusan")
    else:
        print("  === HAY SECCIONES QUE FALLARON ===")

    print("#" * 80 + "\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
