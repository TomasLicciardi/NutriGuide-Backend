# tests/simulate_pipeline.py
"""
Simulación del pipeline completo de NutriGuide.

Muestra qué pasa con cada ingrediente cuando llegan productos nuevos:
- Cuántos resuelve el clasificador determinista
- Cuántos necesitan la cadena inteligente (DB → embeddings → RAG+Gemini)
- Cómo el sistema APRENDE: ingredientes resueltos en el producto N
  se encuentran en la DB para el producto N+1
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils.allergen_parser import parse_allergen_text
from app.services.deterministic_classifier import classifier


PRODUCTS = [
    {
        "id": "foto_27",
        "desc": "Galletitas dulces",
        "ingredients": [
            "harina de trigo enriquecida", "azúcar", "grasa bovina refinada",
            "jarabe de maíz de alta fructosa", "cacao alcalinizado", "sal",
            "bicarbonato de sodio (INS 500ii)", "bicarbonato de amonio (INS 503ii)",
            "lecitina de soja (INS 322)", "aromatizante artificial a vainilla",
            "caramelo IV (INS 150d)",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO Y DE SOJA. PUEDE CONTENER LECHE, MANÍ Y AVENA.",
    },
    {
        "id": "foto_28",
        "desc": "Jugo de naranja",
        "ingredients": [
            "agua", "jugo concentrado de naranja", "azúcar",
            "ácido cítrico (INS 330)", "benzoato de sodio (INS 211)",
            "sorbato de potasio (INS 202)", "sucralosa (INS 955)",
            "acesulfame K (INS 950)",
            "aromatizante idéntico al natural de naranja",
            "amarillo ocaso FCF (INS 110)", "tartrazina (INS 102)",
        ],
        "allergens": "CONTIENE TARTRAZINA.",
    },
    {
        "id": "foto_38",
        "desc": "Yogur con durazno",
        "ingredients": [
            "leche entera pasteurizada", "azúcar",
            "pulpa de durazno", "almidón modificado",
            "aromatizante natural a durazno",
            "sorbato de potasio", "annatto",
            "leche en polvo descremada",
            "cultivos lácticos", "gelatina",
        ],
        "allergens": "CONTIENE LECHE.",
    },
    {
        "id": "foto_41",
        "desc": "Gomitas",
        "ingredients": [
            "jarabe de glucosa", "azúcar", "agua", "gelatina",
            "ácido cítrico (INS 330)", "ácido láctico (INS 270)",
            "aromatizantes artificiales",
            "aceite vegetal",
            "cera de abejas (INS 901)", "cera de carnauba (INS 903)",
            "rojo allura AC (INS 129)", "amarillo ocaso (INS 110)",
            "tartrazina (INS 102)", "azul brillante FCF (INS 133)",
        ],
        "allergens": "CONTIENE TARTRAZINA. PUEDE CONTENER DERIVADOS DE SOJA Y LECHE.",
    },
    {
        "id": "foto_43",
        "desc": "Alfajor",
        "ingredients": [
            "dulce de leche", "leche entera", "azúcar",
            "jarabe de glucosa", "bicarbonato de sodio",
            "sorbato de potasio",
            "aceite vegetal fraccionado",
            "leche descremada en polvo", "suero de queso en polvo",
            "lecitina de soja", "aromatizante artificial a vainilla",
            "harina de trigo enriquecida Ley 25.630",
            "grasa bovina", "cacao en polvo", "sal",
            "bicarbonato de amonio", "propionato de calcio",
        ],
        "allergens": "CONTIENE LECHE Y DERIVADOS DE TRIGO Y SOJA. PUEDE CONTENER MANÍ.",
    },
    {
        "id": "foto_44",
        "desc": "Sopa instantánea sabor pollo",
        "ingredients": [
            "fideos", "harina de trigo enriquecida ley 25.630",
            "agua", "cúrcuma", "sal", "almidón de maíz", "azúcar",
            "aceite vegetal de palma",
            "glutamato monosódico (INS 621)",
            "inosinato disódico (INS 631)",
            "carne de pollo deshidratada",
            "perejil", "cebolla", "apio",
            "aromatizante idéntico al natural a pollo",
            "caramelo IV (INS 150d)",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO Y APIO. PUEDE CONTENER HUEVO, SOJA Y DERIVADOS DE LECHE.",
    },
]


def simulate():
    print("\n" + "=" * 80)
    print(" SIMULACIÓN: Pipeline NutriGuide — Cold Start → Aprendizaje")
    print("=" * 80)

    simulated_db = {}
    total_deterministic = 0
    total_ins = 0
    total_essential = 0
    total_needs_ai = 0
    total_from_db = 0
    total_ingredients = 0

    for product in PRODUCTS:
        allergen_result = parse_allergen_text(product["allergens"])
        classification = classifier.classify_product(
            product["ingredients"], allergen_result,
        )

        needs_ai = []
        resolved_from_db = []

        for ing in classification.classified_ingredients:
            if ing.status == "needs_ai":
                if ing.name_normalized in simulated_db:
                    resolved_from_db.append(
                        (ing.name, simulated_db[ing.name_normalized])
                    )
                else:
                    needs_ai.append(ing.name)
                    simulated_db[ing.name_normalized] = "gemini"

        actual_ai_calls = len(needs_ai)
        actual_db_hits = len(resolved_from_db)

        total_ingredients += classification.stats["total"]
        total_deterministic += classification.stats["by_deterministic"]
        total_ins += classification.stats["by_ins_code"]
        total_essential += classification.stats["by_essential_safe"]
        total_needs_ai += actual_ai_calls
        total_from_db += actual_db_hits

        print(f"\n{'─' * 80}")
        print(f" {product['id']}: {product['desc']}")
        print(f"{'─' * 80}")
        print(f" Ingredientes: {classification.stats['total']}")
        print(f"   ├── Determinista (keywords):  {classification.stats['by_deterministic']}")
        print(f"   ├── INS codes:                {classification.stats['by_ins_code']}")
        print(f"   ├── Base esencial:            {classification.stats['by_essential_safe']}")
        print(f"   ├── Encontrado en DB (ya aprendido): {actual_db_hits}")
        print(f"   └── NECESITA IA (Gemini):     {actual_ai_calls}")

        if needs_ai:
            print(f"\n   Ingredientes que requieren cadena inteligente:")
            for name in needs_ai:
                print(f"     → \"{name}\" → DB vacía → embeddings → RAG+Gemini → APRENDE")

        if resolved_from_db:
            print(f"\n   Ingredientes resueltos por aprendizaje previo:")
            for name, source in resolved_from_db:
                print(f"     → \"{name}\" → encontrado en DB (aprendido antes)")

        r = classification.restrictions
        verdicts = []
        for rest in ["vegano", "vegetariano", "sin_gluten", "sin_lactosa", "sin_frutos_secos"]:
            status = "APTO" if r[rest]["apto"] else "NO APTO"
            verdicts.append(f"{rest}={status}")
        print(f"\n   Resultado: {' | '.join(verdicts)}")
        print(f"   Método: {classification.method} | Confianza: {classification.confidence:.0%}")

    # Resumen final
    print(f"\n{'=' * 80}")
    print(f" RESUMEN ACUMULADO ({len(PRODUCTS)} productos, {total_ingredients} ingredientes)")
    print(f"{'=' * 80}")
    print(f"  Resueltos por determinístico (keywords): {total_deterministic:>4}  ({total_deterministic/total_ingredients:.0%})")
    print(f"  Resueltos por INS codes:                 {total_ins:>4}  ({total_ins/total_ingredients:.0%})")
    print(f"  Resueltos por base esencial:             {total_essential:>4}  ({total_essential/total_ingredients:.0%})")
    print(f"  Resueltos por DB (aprendizaje):          {total_from_db:>4}  ({total_from_db/total_ingredients:.0%})")
    print(f"  Resueltos por IA (Gemini):               {total_needs_ai:>4}  ({total_needs_ai/total_ingredients:.0%})")
    print(f"{'─' * 80}")
    print(f"  Ingredientes en DB después:              {len(simulated_db):>4}")
    print(f"  Llamadas a Gemini totales:               {total_needs_ai:>4}")
    print(f"  Llamadas ahorradas por aprendizaje:      {total_from_db:>4}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    simulate()
