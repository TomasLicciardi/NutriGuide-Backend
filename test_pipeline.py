"""
Script de testing del pipeline multi-fuente de NutriGuide.

Ejecutar: python test_pipeline.py

Prueba cada tier por separado y luego simula el pipeline completo
con ejemplos reales de ingredientes argentinos.
"""

import asyncio
import sys
import os
import time

os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(__file__))

SEPARATOR = "=" * 70
SUB_SEP = "-" * 50

# Ingredientes de ejemplo: simulan una etiqueta real argentina
INGREDIENTES_EJEMPLO = [
    "harina de trigo enriquecida",
    "azucar",
    "aceite vegetal de girasol",
    "leche en polvo",
    "cacao en polvo",
    "lecitina de soja",
    "sal",
    "bicarbonato de sodio",
    "acido citrico",
    "saborizante artificial",
    "TBHQ",
    "carboximetilcelulosa",
    "caseinato de sodio",
    "goma xantica",
    "almendras",
    "gelatina",
    "maltodextrina",
    "acido lactico",
    "nuez moscada",
    "INS 120",
]

TEXTO_ALERGENOS = "CONTIENE: GLUTEN, LECHE, SOJA. PUEDE CONTENER: FRUTOS SECOS, MANI."


def print_header(title):
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def print_sub(title):
    print(f"\n{SUB_SEP}")
    print(f"  {title}")
    print(SUB_SEP)


# ══════════════════════════════════════════════════════════════════════════
# TEST 1: Clasificador Determinista (Tier 1)
# ══════════════════════════════════════════════════════════════════════════

def test_tier1():
    print_header("TIER 1: Clasificador Determinista")

    from app.services.deterministic_classifier import classifier

    result = classifier.classify_batch(INGREDIENTES_EJEMPLO)

    print(f"\nTotal: {result.stats['total']} ingredientes")
    print(f"Resueltos: {len(result.resolved)} ({result.stats['by_keyword']} keyword, "
          f"{result.stats['by_ins']} INS, {result.stats['by_safe']} seguros)")
    print(f"No resueltos: {len(result.unresolved)}")

    print_sub("Resueltos")
    for name, r in result.resolved.items():
        safe = []
        if r.is_tacc_safe is False: safe.append("TACC❌")
        elif r.is_tacc_safe: safe.append("TACC✓")
        if r.is_lactose_safe is False: safe.append("Lact❌")
        elif r.is_lactose_safe: safe.append("Lact✓")
        if r.is_nut_safe is False: safe.append("Nut❌")
        elif r.is_nut_safe: safe.append("Nut✓")
        if r.is_vegan_safe is False: safe.append("Veg❌")
        elif r.is_vegan_safe: safe.append("Veg✓")
        print(f"  [{r.category:7}] {name:35} → {' '.join(safe):30} ({r.resolved_by}, {r.confidence:.2f})")
        for ev in r.evidence:
            print(f"           {ev}")

    print_sub("No resueltos (pasan a Tier 2+)")
    for name in result.unresolved:
        print(f"  ? {name}")

    return result


# ══════════════════════════════════════════════════════════════════════════
# TEST 2: Traduccion MarianMT (Fase 3)
# ══════════════════════════════════════════════════════════════════════════

def test_translation():
    print_header("TRADUCCION: MarianMT (ES → EN)")

    from app.services.translation_service import translation_service

    start = time.time()
    traducciones = translation_service.translate_batch(INGREDIENTES_EJEMPLO)
    elapsed = time.time() - start

    print(f"\nTiempo de traduccion: {elapsed:.2f}s para {len(INGREDIENTES_EJEMPLO)} ingredientes")
    print(f"Cache actual: {translation_service.get_cache_size()} entradas\n")

    for es, en in zip(INGREDIENTES_EJEMPLO, traducciones):
        print(f"  {es:35} → {en}")

    # Segunda vez (cache)
    start = time.time()
    translation_service.translate_batch(INGREDIENTES_EJEMPLO)
    elapsed2 = time.time() - start
    print(f"\nSegunda vez (cache): {elapsed2:.4f}s")

    return dict(zip(INGREDIENTES_EJEMPLO, traducciones))


# ══════════════════════════════════════════════════════════════════════════
# TEST 3: Open Food Facts (Tier 3)
# ══════════════════════════════════════════════════════════════════════════

async def test_tier3(ingredients_en):
    print_header("TIER 3: Open Food Facts API")

    from app.services.openfoodfacts_service import openfoodfacts_service

    start = time.time()
    results = await openfoodfacts_service.analyze_ingredients(ingredients_en)
    elapsed = time.time() - start

    print(f"\nTiempo: {elapsed:.2f}s")
    print(f"Resultados: {len(results)} ingredientes")

    in_taxonomy = sum(1 for r in results.values() if r.in_taxonomy)
    print(f"En taxonomia: {in_taxonomy}/{len(results)}\n")

    for name, r in results.items():
        status = "✓ EN TAXONOMIA" if r.in_taxonomy else "✗ NO RECONOCIDO"
        print(f"  {name:35} {status}")
        if r.in_taxonomy:
            print(f"    ID: {r.taxonomy_id}")
            print(f"    Vegan: {r.vegan}, Vegetarian: {r.vegetarian}")
            safe = []
            if r.is_tacc_safe is not None:
                safe.append(f"TACC:{'✓' if r.is_tacc_safe else '❌'}")
            if r.is_lactose_safe is not None:
                safe.append(f"Lact:{'✓' if r.is_lactose_safe else '❌'}")
            if r.is_nut_safe is not None:
                safe.append(f"Nut:{'✓' if r.is_nut_safe else '❌'}")
            if r.is_vegan_safe is not None:
                safe.append(f"Veg:{'✓' if r.is_vegan_safe else '❌'}")
            if safe:
                print(f"    Restricciones: {' '.join(safe)}")
        for ev in r.evidence:
            print(f"    {ev}")

    return results


# ══════════════════════════════════════════════════════════════════════════
# TEST 4: PubChem (Tier 4)
# ══════════════════════════════════════════════════════════════════════════

async def test_tier4(ingredients_en):
    print_header("TIER 4: PubChem API")

    from app.services.pubchem_service import pubchem_service

    start = time.time()
    results = await pubchem_service.identify_compounds(ingredients_en)
    elapsed = time.time() - start

    found = sum(1 for r in results.values() if r.found)
    print(f"\nTiempo: {elapsed:.2f}s")
    print(f"Encontrados: {found}/{len(results)}\n")

    for name, r in results.items():
        if r.found:
            print(f"  ✓ {name:35} CID={r.cid}")
            if r.description:
                print(f"    Desc: {r.description[:100]}...")
            if r.inferred_origin:
                print(f"    Origen: {r.inferred_origin}")
            safe = []
            if r.is_tacc_safe is not None:
                safe.append(f"TACC:{'✓' if r.is_tacc_safe else '❌'}")
            if r.is_vegan_safe is not None:
                safe.append(f"Veg:{'✓' if r.is_vegan_safe else '❌'}")
            if safe:
                print(f"    Restricciones: {' '.join(safe)}")
            for ev in r.evidence:
                print(f"    {ev}")
        else:
            print(f"  ✗ {name:35} NO ENCONTRADO")

    return results


# ══════════════════════════════════════════════════════════════════════════
# TEST 5: Parser de Alergenos (Fase 5)
# ══════════════════════════════════════════════════════════════════════════

def test_allergen_parser():
    print_header("PARSER DE ALERGENOS")

    from app.utils.allergen_parser import parse_allergen_text

    textos = [
        "CONTIENE: GLUTEN, LECHE, SOJA. PUEDE CONTENER: FRUTOS SECOS, MANI.",
        "SIN TACC. Libre de gluten.",
        "CONTIENE: LECHE. NO CONTIENE GLUTEN.",
        "PUEDE CONTENER TRAZAS DE: LECHE, HUEVO Y FRUTOS SECOS",
        "Elaborado en lineas que tambien procesan mani y trigo",
    ]

    for texto in textos:
        print(f"\n  Texto: \"{texto}\"")
        result = parse_allergen_text(texto)
        if result.contiene:
            print(f"    CONTIENE: {', '.join(result.contiene)}")
        if result.puede_contener:
            print(f"    PUEDE CONTENER: {', '.join(result.puede_contener)}")
        if result.declaraciones_positivas:
            print(f"    DECLARACIONES +: {', '.join(result.declaraciones_positivas)}")
        if result.restricciones_afectadas:
            for r, data in result.restricciones_afectadas.items():
                print(f"    → {r}: {data['fuente']} ({data['tipo']})")


# ══════════════════════════════════════════════════════════════════════════
# TEST 6: Motor de Consenso (Fase 6 - simulacion)
# ══════════════════════════════════════════════════════════════════════════

def test_consensus(tier1_result, translations, off_results, pubchem_results):
    print_header("MOTOR DE CONSENSO")

    from app.services.consensus_engine import consensus_engine, IngredientVerdict
    from app.utils.allergen_parser import parse_allergen_text

    allergen_result = parse_allergen_text(TEXTO_ALERGENOS)
    ingredient_verdicts = []

    for name_es in INGREDIENTES_EJEMPLO:
        name_en = translations.get(name_es, name_es)
        t1 = tier1_result.resolved.get(name_es)
        t3 = off_results.get(name_en) if off_results else None
        t4 = pubchem_results.get(name_en) if pubchem_results else None

        verdict = consensus_engine.merge_tier_results(
            name_es=name_es,
            name_en=name_en,
            tier1_result=t1,
            tier3_result=t3,
            tier4_result=t4,
        )
        ingredient_verdicts.append(verdict)

    product_verdict = consensus_engine.build_product_verdict(
        ingredient_verdicts, allergen_result, ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"],
    )

    print(f"\n  VEREDICTO DEL PRODUCTO:")
    print(f"  {'='*50}")
    for r, data in product_verdict.restrictions.items():
        emoji = "✓ APTO" if data["apto"] else "❌ NO APTO"
        motivo = f" — {data['motivo']}" if data.get("motivo") else ""
        print(f"    {r:25} {emoji}{motivo}")
    print(f"\n  Confianza global: {product_verdict.overall_confidence:.2f}")
    print(f"  Veredicto usuario: {'✓ APTO' if product_verdict.user_verdict else '❌ NO APTO'}")

    print_sub("Detalle por ingrediente")
    for v in ingredient_verdicts:
        safe = []
        if v.is_tacc_safe is False: safe.append("TACC❌")
        elif v.is_tacc_safe: safe.append("TACC✓")
        else: safe.append("TACC?")
        if v.is_lactose_safe is False: safe.append("Lact❌")
        elif v.is_lactose_safe: safe.append("Lact✓")
        else: safe.append("Lact?")
        if v.is_nut_safe is False: safe.append("Nut❌")
        elif v.is_nut_safe: safe.append("Nut✓")
        else: safe.append("Nut?")
        if v.is_vegan_safe is False: safe.append("Veg❌")
        elif v.is_vegan_safe: safe.append("Veg✓")
        else: safe.append("Veg?")

        print(f"  {v.name_es:35} {' '.join(safe):30} [{v.resolved_by}, {v.confidence:.2f}]")


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

async def main():
    print("\n")
    print("=" * 70)
    print("  NUTRIGUIDE — TEST COMPLETO DEL PIPELINE MULTI-FUENTE")
    print("=" * 70)
    print(f"\n  Ingredientes de prueba: {len(INGREDIENTES_EJEMPLO)}")
    print(f"  Texto alergenos: \"{TEXTO_ALERGENOS}\"")

    total_start = time.time()

    # Tier 1
    tier1_result = test_tier1()

    # Traduccion
    translations = test_translation()

    # Solo ingredientes no resueltos para APIs
    unresolved_en = [translations[es] for es in tier1_result.unresolved if es in translations]
    print(f"\n  >> Ingredientes para APIs (no resueltos): {len(unresolved_en)}")
    for ing in unresolved_en:
        print(f"     - {ing}")

    # Tier 3 + Tier 4 en paralelo
    print_header("TIERS 3 + 4 EN PARALELO (asyncio.gather)")
    start = time.time()

    off_results, pubchem_results = await asyncio.gather(
        test_tier3(unresolved_en),
        test_tier4(unresolved_en),
        return_exceptions=True,
    )

    if isinstance(off_results, Exception):
        print(f"\n  ⚠ Open Food Facts fallo: {off_results}")
        off_results = {}
    if isinstance(pubchem_results, Exception):
        print(f"\n  ⚠ PubChem fallo: {pubchem_results}")
        pubchem_results = {}

    elapsed_parallel = time.time() - start
    print(f"\n  Tiempo total APIs en paralelo: {elapsed_parallel:.2f}s")

    # Alergenos
    test_allergen_parser()

    # Consenso
    test_consensus(tier1_result, translations, off_results, pubchem_results)

    total_elapsed = time.time() - total_start
    print_header(f"TESTING COMPLETO — {total_elapsed:.2f}s total")


if __name__ == "__main__":
    asyncio.run(main())
