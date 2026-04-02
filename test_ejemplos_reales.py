"""
Test con etiquetas argentinas reales — Pipeline optimizado.
Ejecutar: python test_ejemplos_reales.py
"""

import asyncio
import sys
import os
import time

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(__file__))

PRODUCTOS = {
    "Ketchup (Foto 11)": {
        "ingredientes": [
            "agua", "concentrado doble de tomate", "azucar", "vinagre de alcohol",
            "maltodextrina", "sal", "cebolla en polvo", "ajo en polvo", "especias",
            "goma xantica", "acido citrico", "sorbato de potasio",
            "aromatizantes naturales",
        ],
        "alergenos": "",
    },
    "Mostaza (Foto 12)": {
        "ingredientes": [
            "agua", "vinagre de alcohol", "vinagre de vino", "almidon modificado",
            "mostaza blanca", "curcuma", "canela", "nuez moscada", "semilla de apio",
            "aji molido", "comino", "clavo de olor", "pimienta negra", "tomillo",
            "oregano", "jengibre", "laurel", "azucar", "sal", "aceite de girasol",
            "cebolla", "ajo", "goma xantica", "acido sorbico", "caramelo IV",
            "clorofila", "aromatizante identico al natural", "EDTA disodico calcico",
            "BHA", "BHT",
        ],
        "alergenos": "PUEDE CONTENER TRIGO, AVENA, CEBADA Y CENTENO.",
    },
    "Harina 0000 (Foto 13)": {
        "ingredientes": [
            "harina 0000 enriquecida", "harina de trigo", "sulfato ferroso",
            "nicotinamida", "tiamina", "acido folico", "riboflavina",
            "INS 341iii", "INS 928",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER DERIVADOS DE SOJA.",
    },
    "Chocolatada en polvo (Foto 14)": {
        "ingredientes": [
            "azucar", "cacao en polvo", "suero de leche",
            "vitamina C", "vitamina D", "vitamina B1",
            "pirofosfato ferrico", "sulfato de zinc",
            "sal", "canela en polvo", "lecitina de soja",
            "vainilla",
        ],
        "alergenos": "CONTIENE DERIVADOS DE LECHE Y DE SOJA.",
    },
    "Sal (Foto 15)": {
        "ingredientes": [
            "sal", "cloruro de sodio", "yodato de potasio",
            "INS 551", "INS 536",
        ],
        "alergenos": "Libre de gluten - Sin T.A.C.C.",
    },
    "Tapas de empanadas (Foto 16)": {
        "ingredientes": [
            "harina de trigo 000 enriquecida", "aceite de girasol alto oleico",
            "vinagre de alcohol", "sal", "cloruro de potasio",
            "INS 422", "INS 471", "INS 412", "INS 282", "INS 330", "INS 920",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO, LECHE, DERIVADOS DE SOJA, DE AVENA Y DE CEBADA.",
    },
    "Caldo en cubo (Foto 17)": {
        "ingredientes": [
            "sal", "grasa vegetal", "almidon de maiz", "azucar",
            "aceite de palma", "BHA", "BHT", "pimienta roja",
            "perejil", "laurel en polvo", "ajo en polvo",
            "carne bovina deshidratada", "glutamato monosodico",
            "inosinato de sodio", "aromatizantes", "caramelo",
            "rocu", "acido citrico",
        ],
        "alergenos": "CONTIENE DERIVADOS DE SOJA. PUEDE CONTENER CEBADA.",
    },
    "Sopa instantanea (Foto 18)": {
        "ingredientes": [
            "almidon de papa", "zapallo", "cebolla", "perejil",
            "azucar", "maltodextrina", "jarabe de glucosa", "sal",
            "aceites vegetales", "romero", "caseinato de sodio",
            "pimienta negra", "glutamato monosodico", "inosinato disodico",
            "guanilato disodico", "goma xantica", "aromatizantes naturales",
            "annatto",
        ],
        "alergenos": "CONTIENE DERIVADO DE LECHE. PUEDE CONTENER PESCADO Y DERIVADOS DE SOJA Y DE TRIGO.",
    },
}


async def analyze_single_product(name, ingredientes, alergenos_text):
    """Pipeline completo: T1 -> Traduccion -> OFF -> PubChem+Gemini -> Consenso."""
    from app.services.deterministic_classifier import classifier
    from app.services.translation_service import translation_service
    from app.services.openfoodfacts_service import openfoodfacts_service
    from app.services.pubchem_service import pubchem_service
    from app.services.gemini_service import gemini_service
    from app.services.consensus_engine import consensus_engine
    from app.utils.allergen_parser import parse_allergen_text

    start = time.time()
    timings = {}

    # Tier 1: Determinista
    t = time.time()
    tier1 = classifier.classify_batch(ingredientes)
    timings["tier1"] = time.time() - t

    # Traduccion
    t = time.time()
    traducciones = translation_service.translate_batch(ingredientes)
    timings["traduccion"] = time.time() - t
    pairs = dict(zip(ingredientes, traducciones))

    # Mapa inverso EN -> ES
    en_to_es = {en: es for es, en in pairs.items()}

    # Tier 2: Knowledge Base (simulado — no hay DB en test)
    unresolved_en = [pairs[es] for es in tier1.unresolved]

    # Tier 3: Open Food Facts
    t = time.time()
    try:
        off_results = await openfoodfacts_service.analyze_ingredients(unresolved_en)
    except Exception:
        off_results = {}
    timings["off"] = time.time() - t

    # Filtrar: solo lo que OFF no reconoció
    off_misses = [n for n in unresolved_en if n not in off_results or not off_results[n].in_taxonomy]

    # Tier 4 + Tier 5: PubChem y Gemini en paralelo (solo OFF misses)
    pubchem_results = {}
    gemini_results = {}
    if off_misses:
        gemini_pairs = [
            {"name_es": en_to_es.get(en, en), "name_en": en}
            for en in off_misses
        ]
        t = time.time()
        t4_raw, t5_raw = await asyncio.gather(
            pubchem_service.identify_compounds(off_misses),
            gemini_service.classify_unknown_ingredients(gemini_pairs),
            return_exceptions=True,
        )
        timings["pubchem_gemini"] = time.time() - t

        if not isinstance(t4_raw, Exception):
            pubchem_results = t4_raw
        if not isinstance(t5_raw, Exception):
            gemini_results = t5_raw
    else:
        timings["pubchem_gemini"] = 0.0

    # Alergenos
    t = time.time()
    allergen_result = parse_allergen_text(alergenos_text)
    timings["alergenos"] = time.time() - t

    # Consenso
    t = time.time()
    verdicts = []
    for name_es, name_en in pairs.items():
        t1 = tier1.resolved.get(name_es)
        t3 = off_results.get(name_en)
        t4 = pubchem_results.get(name_en)
        t5 = gemini_results.get(name_en)
        v = consensus_engine.merge_tier_results(
            name_es=name_es, name_en=name_en,
            tier1_result=t1, tier3_result=t3, tier4_result=t4, tier5_result=t5,
        )
        verdicts.append(v)

    product_verdict = consensus_engine.build_product_verdict(
        verdicts, allergen_result,
        ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"],
    )
    timings["consenso"] = time.time() - t
    timings["total"] = time.time() - start

    return {
        "tier1": tier1,
        "pairs": pairs,
        "off_results": off_results,
        "off_misses": off_misses,
        "pubchem_results": pubchem_results,
        "gemini_results": gemini_results,
        "allergen_result": allergen_result,
        "verdicts": verdicts,
        "product_verdict": product_verdict,
        "timings": timings,
    }


def print_result(name, result):
    """Imprime resultado detallado de un producto."""
    t = result["timings"]
    tier1 = result["tier1"]
    pv = result["product_verdict"]
    verdicts = result["verdicts"]
    allergen = result["allergen_result"]
    off = result["off_results"]
    pubchem = result["pubchem_results"]

    gemini = result["gemini_results"]

    total_ing = len(verdicts)
    resolved_t1 = len(tier1.resolved)
    off_count = sum(1 for r in off.values() if r.in_taxonomy)
    pub_count = sum(1 for r in pubchem.values() if r.found)
    gem_count = sum(1 for r in gemini.values() if r.origin is not None)
    unresolved = sum(1 for v in verdicts if v.resolved_by == "unresolved")

    print(f"\n{'='*70}")
    print(f"  {name}   [{t['total']:.1f}s]")
    print(f"{'='*70}")
    print(f"  Tiempos: T1={t['tier1']*1000:.0f}ms | Trad={t['traduccion']*1000:.0f}ms | "
          f"OFF={t['off']:.1f}s | PubChem+Gemini={t['pubchem_gemini']:.1f}s | Alerg={t['alergenos']*1000:.0f}ms")
    print(f"  Pipeline: {total_ing} ing -> T1:{resolved_t1} | OFF:{off_count} | "
          f"PubChem:{pub_count} | Gemini:{gem_count} | Sin resolver:{unresolved}")

    # Restricciones
    for r, data in pv.restrictions.items():
        emoji = "APTO" if data["apto"] else "NO APTO"
        motivo = f" -- {data['motivo']}" if data.get("motivo") else ""
        print(f"    {r:25} {emoji}{motivo}")

    # Alergenos
    if allergen.contiene or allergen.puede_contener or allergen.declaraciones_positivas:
        parts = []
        if allergen.declaraciones_positivas:
            parts.append(f"+: {', '.join(allergen.declaraciones_positivas)}")
        if allergen.contiene:
            parts.append(f"Contiene: {', '.join(allergen.contiene)}")
        if allergen.puede_contener:
            parts.append(f"Puede contener: {', '.join(allergen.puede_contener)}")
        print(f"  Texto alergenos: {' | '.join(parts)}")

    # Ingredientes
    print(f"\n  Ingredientes:")
    for v in verdicts:
        flags = []
        if v.is_tacc_safe is False: flags.append("TACC:X")
        elif v.is_tacc_safe is None: flags.append("TACC:?")
        if v.is_lactose_safe is False: flags.append("Lac:X")
        elif v.is_lactose_safe is None: flags.append("Lac:?")
        if v.is_nut_safe is False: flags.append("Nut:X")
        elif v.is_nut_safe is None: flags.append("Nut:?")
        if v.is_vegan_safe is False: flags.append("Veg:X")
        elif v.is_vegan_safe is None: flags.append("Veg:?")

        flag_str = " ".join(flags) if flags else "OK"
        src = v.resolved_by[:5] if v.resolved_by else "?"
        print(f"    {v.name_es:35} -> {v.name_en:30} [{src:5}] {flag_str}")


async def main():
    print("\n" + "=" * 70)
    print("  NUTRIGUIDE — TEST PIPELINE OPTIMIZADO (8 productos reales)")
    print("=" * 70)

    # Precalentar modelo
    print("\n  Cargando modelo de traduccion...", end=" ", flush=True)
    t = time.time()
    from app.services.translation_service import translation_service
    translation_service.translate("agua")
    print(f"OK ({time.time()-t:.1f}s)")

    all_times = []
    total_start = time.time()

    for name, data in PRODUCTOS.items():
        result = await analyze_single_product(name, data["ingredientes"], data["alergenos"])
        print_result(name, result)
        all_times.append((name, result["timings"]["total"]))

    total = time.time() - total_start

    print(f"\n{'='*70}")
    print(f"  RESUMEN DE TIEMPOS POR PRODUCTO")
    print(f"{'='*70}")
    for pname, ptime in all_times:
        bar = "#" * int(ptime * 5)
        print(f"  {pname:35} {ptime:5.1f}s  {bar}")
    print(f"\n  Total (8 productos secuenciales): {total:.1f}s")
    print(f"  Promedio por producto:             {total/len(PRODUCTOS):.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
