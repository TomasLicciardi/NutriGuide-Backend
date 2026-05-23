"""
Trace de un producto del Dataset por el pipeline.

Modo default:
    python -m evaluation.trace_v3_product foto17

Modo imagen real (usa Gemini OCR y puede tener costo/cuota):
    python -m evaluation.trace_v3_product foto17 --mode image

El modo texto salta solo la Fase 1 (OCR) y usa la transcripcion del
ground truth. Ejecuta parser, canonicalization, declaracion legal,
enrichment, predicados y veredicto.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Dataset.ground_truth import GROUND_TRUTH
from app.database.connection import get_db, init_database
from app.services.analysis_pipeline import analysis_pipeline
from app.services.restriction_predicates import ALL_RESTRICTIONS
from app.utils.initialization import initialize_system


async def trace_product(product_id: str, mode: str, skip_init: bool) -> bool:
    if product_id not in GROUND_TRUTH:
        available = ", ".join(sorted(GROUND_TRUTH.keys())[:12])
        raise SystemExit(f"Producto desconocido: {product_id}. Ejemplos: {available}, ...")

    case = GROUND_TRUTH[product_id]
    init_database()
    if not skip_init:
        initialize_system()

    db = next(get_db())
    try:
        if mode == "image":
            image_path = Path("Dataset") / case["archivo"]
            result = await analysis_pipeline.run(
                image_data=image_path.read_bytes(),
                image_type="image/jpeg",
                user_restrictions=list(ALL_RESTRICTIONS),
                db=db,
            )
            input_label = str(image_path)
        else:
            result = await analysis_pipeline.run_from_text(
                ingredients_text=", ".join(case["ingredientes"]),
                allergen_text=case.get("alergenos") or "",
                user_restrictions=list(ALL_RESTRICTIONS),
                db=db,
            )
            input_label = "Dataset.ground_truth text"
    finally:
        db.close()

    print("=" * 88)
    print(f"PRODUCTO: {product_id} - {case['nombre']}")
    print(f"MODO: {mode} | INPUT: {input_label}")
    print(f"EXPECTED: {case['expected']}")
    print("=" * 88)

    if not result.success:
        print(f"ERROR: {result.error_type} - {result.error}")
        return False

    if result.ocr_result is not None:
        print("\nFASE 1 - OCR/GEMINI")
        for i, ing in enumerate(result.ocr_result.ingredients, 1):
            print(f"  {i:02d}. {ing}")
        print(f"  alergenos OCR: {result.ocr_result.allergen_warnings}")

    print("\nFASE 2/4 - INGREDIENT FACTS")
    for i, facts in enumerate(result.ingredient_facts, 1):
        print(
            f"  {i:02d}. {facts.name_es} | en={facts.name_en!r} | "
            f"cat={facts.category.value} | origin={facts.origin.value} | "
            f"fn={facts.function_tag or '-'} | INS={facts.codex_ins_code or '-'} | "
            f"conf={facts.confidence:.2f} | sources={facts.sources}"
        )
        if facts.allergens or facts.contains or facts.derived_from:
            print(
                "      "
                f"allergens={sorted(facts.allergens)} "
                f"contains={sorted(facts.contains)} "
                f"derived={sorted(facts.derived_from)}"
            )

    print("\nFASE 3 - DECLARACION LEGAL")
    print(f"  contains: {sorted(result.declaration.contains)}")
    print(f"  may_contain: {sorted(result.declaration.may_contain)}")
    print(f"  positive_claims: {sorted(result.declaration.positive_claims)}")

    print("\nFASE 5/6 - VEREDICTOS")
    all_ok = True
    for restriction, verdict in result.restrictions.items():
        expected = case["expected"].get(restriction)
        ok = expected == verdict.apto
        all_ok = all_ok and ok
        print(
            f"  {restriction}: {'APTO' if verdict.apto else 'NO APTO'} | "
            f"expected={'APTO' if expected else 'NO APTO'} | ok={ok} | "
            f"fuente={verdict.fuente} | conf={verdict.confidence:.2f} | "
            f"trigger={verdict.ingrediente_disparador or '-'} | motivo={verdict.motivo}"
        )

    stats = result.stats
    print("\nSTATS")
    print(
        f"  ingredients={stats.total_ingredients} | flavorings={stats.total_flavorings} | "
        f"legal={stats.resolved_by_legal} | codex={stats.resolved_by_codex} | "
        f"off={stats.resolved_by_off} | kb={stats.resolved_by_kb} | "
        f"llm={stats.resolved_by_llm} | policy={stats.resolved_by_policy} | "
        f"gemini_calls={stats.gemini_calls} | "
        f"unresolved={stats.unresolved} | "
        f"time_ms={stats.processing_time_ms:.0f}"
    )
    print(f"  overall_confidence={result.overall_confidence:.2f} | user_verdict={result.user_verdict}")
    print(f"\nRESULTADO: {'OK' if all_ok else 'FAIL'}")
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Trace de un producto Dataset por pipeline.")
    parser.add_argument("products", nargs="+", help="Ids tipo foto17, foto28, foto41")
    parser.add_argument("--mode", choices=["text", "image"], default="text")
    parser.add_argument("--skip-init", action="store_true")
    args = parser.parse_args()

    async def run_all() -> int:
        ok = True
        for product_id in args.products:
            ok = await trace_product(product_id, args.mode, args.skip_init) and ok
        return 0 if ok else 1

    return asyncio.run(run_all())


if __name__ == "__main__":
    raise SystemExit(main())
