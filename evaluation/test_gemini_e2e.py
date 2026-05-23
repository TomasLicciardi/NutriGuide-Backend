"""
Test E2E con Gemini real sobre N imagenes random del Dataset/.

A diferencia de evaluate.py (que usa run_from_text y skipea OCR), este
script ejecuta el pipeline COMPLETO incluyendo Fase 1 (Gemini Vision).
Sirve para validar que el OCR + parser + federacion funciona end-to-end
sobre imagenes reales, y para medir cuanto gasta Gemini en una corrida.

Uso:
    python -m evaluation.test_gemini_e2e            # 2 imagenes random
    python -m evaluation.test_gemini_e2e --n 3      # 3 imagenes
    python -m evaluation.test_gemini_e2e --seed 42  # reproducible
"""

import argparse
import asyncio
import logging
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.WARNING)

from Dataset.ground_truth import GROUND_TRUTH
from app.database.connection import get_db, init_database
from app.services.analysis_pipeline import analysis_pipeline
from app.services.restriction_predicates import ALL_RESTRICTIONS
from app.utils.initialization import initialize_system

DATASET_DIR = Path(__file__).parent.parent / "Dataset"


def select_random_images(n: int, seed: int | None = None) -> list[tuple[str, Path, dict]]:
    """
    Selecciona n imagenes random del Dataset/ excluyendo las marcadas como
    mala_calidad en el ground truth. Retorna (product_id, jpeg_path, expected).
    """
    candidates = []
    for product_id, case in GROUND_TRUTH.items():
        if case.get("mala_calidad"):
            continue
        archivo = case.get("archivo")
        if not archivo:
            continue
        jpeg_path = DATASET_DIR / archivo
        if not jpeg_path.exists():
            continue
        candidates.append((product_id, jpeg_path, case))

    if seed is not None:
        random.seed(seed)
    return random.sample(candidates, min(n, len(candidates)))


async def run_one(product_id: str, jpeg_path: Path, expected: dict, db) -> None:
    print()
    print("#" * 80)
    print(f"#  {product_id}  --  {expected.get('nombre', '?')}")
    print(f"#  archivo: {jpeg_path.name}")
    print("#" * 80)

    with open(jpeg_path, "rb") as f:
        image_data = f.read()
    print(f"  Bytes leidos: {len(image_data):,}")

    t0 = time.time()
    result = await analysis_pipeline.run(
        image_data=image_data,
        image_type="image/jpeg",
        user_restrictions=list(ALL_RESTRICTIONS),
        db=db,
    )
    elapsed = (time.time() - t0) * 1000

    if not result.success:
        print(f"  [FAIL] {result.error_type}: {result.error}")
        return

    print()
    print(f"  --- OCR (Gemini Vision) ---")
    ocr = result.ocr_result
    if ocr:
        print(f"  Ingredientes detectados ({len(ocr.ingredients)}):")
        for ing in ocr.ingredients:
            print(f"    - {ing}")
        if ocr.allergen_warnings:
            print(f"  Texto de alergenos: {ocr.allergen_warnings[:200]}")
        print(f"  Confianza OCR: {ocr.confidence:.2f}")

    print()
    print(f"  --- Declaracion legal parseada ---")
    decl = result.declaration
    if decl:
        if decl.contains:
            print(f"  CONTIENE: {sorted(decl.contains)}")
        if decl.may_contain:
            print(f"  PUEDE CONTENER: {sorted(decl.may_contain)}")
        if decl.positive_claims:
            print(f"  Claims positivos: {sorted(decl.positive_claims)}")

    print()
    print(f"  --- Veredictos por restriccion ---")
    expected_map = expected.get("expected", {})
    for restriction in ALL_RESTRICTIONS:
        v = result.restrictions.get(restriction)
        if v is None:
            print(f"    {restriction:<22}  ??? (sin veredicto)")
            continue

        exp = expected_map.get(restriction)
        match = "OK" if (exp is None or exp == v.apto) else "MISMATCH"
        apto_str = "APTO" if v.apto else "NO APTO"
        exp_str = ("APTO" if exp else "NO APTO") if exp is not None else "?"
        marker = "[OK]" if match == "OK" else "[!!]"
        print(
            f"    {marker} {restriction:<22}  {apto_str:<7}  "
            f"(esperado: {exp_str}, fuente: {v.fuente}, conf: {v.confidence:.2f})"
        )
        if v.motivo:
            print(f"           motivo: {v.motivo}")

    print()
    print(f"  --- Stats del pipeline ---")
    s = result.stats
    print(f"  Total ingredientes:        {s.total_ingredients}")
    print(f"  Aromatizantes:             {s.total_flavorings}")
    print(f"  Resueltos por declaracion: {s.resolved_by_legal}")
    print(f"  Resueltos por Codex INS:   {s.resolved_by_codex}")
    print(f"  Resueltos por OFF:         {s.resolved_by_off}")
    print(f"  Resueltos por KB local:    {s.resolved_by_kb}")
    print(f"  Resueltos por Gemini cls:  {s.resolved_by_gemini}")
    print(f"  Resueltos por LLM batch:   {s.resolved_by_llm}")
    print(f"  Resueltos por politica:    {s.resolved_by_policy}")
    print(f"  No resueltos:              {s.unresolved}")
    print(f"  Llamadas Gemini:           {s.gemini_calls}")
    print(f"  Pipeline ms (interno):     {s.processing_time_ms:.0f}ms")
    print(f"  Wall clock (incluye init): {elapsed:.0f}ms")
    print(f"  Confianza global:          {result.overall_confidence:.2f}")


async def main(n: int, seed: int | None) -> int:
    print()
    print("#" * 80)
    print("#  NUTRIGUIDE -- TEST E2E CON GEMINI VISION REAL")
    print(f"#  N imagenes: {n}, seed: {seed}")
    print("#" * 80)

    init_database()
    print()
    print("  Inicializando sistema (loaders, KB)...")
    try:
        initialize_system()
        print("  Sistema listo.")
    except Exception as e:
        print(f"  [WARN] initialize_system fallo: {e}")

    selection = select_random_images(n, seed)
    if not selection:
        print("  [ERROR] No hay imagenes en el Dataset coincidiendo con el ground truth")
        return 1
    print(f"  Imagenes seleccionadas: {[p[0] for p in selection]}")

    db = next(get_db())
    total_t0 = time.time()
    total_gemini_calls = 0
    for product_id, jpeg_path, case in selection:
        await run_one(product_id, jpeg_path, case, db)
        # Cada run() consume al menos 1 llamada Gemini (Fase 1 OCR).
        total_gemini_calls += 1
    total_elapsed = time.time() - total_t0
    db.close()

    print()
    print("#" * 80)
    print(f"#  TOTAL: {len(selection)} imagenes en {total_elapsed:.2f}s "
          f"(~{total_elapsed/len(selection):.2f}s/imagen)")
    print(f"#  Llamadas Gemini estimadas: {total_gemini_calls}+ "
          f"(1 OCR por imagen, + posibles batch fallbacks)")
    print("#" * 80)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=2, help="cantidad de imagenes (default 2)")
    p.add_argument("--seed", type=int, default=None, help="random seed para reproducibilidad")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.n, args.seed)))
