"""
Smoke test / evaluación del pipeline contra el ground truth.

Ejecuta las Fases 2-6 del pipeline (parser → resolución legal →
enrichment → predicados → veredicto) sobre cada producto del dataset,
saltando la Fase 1 (Gemini Vision) — usamos los ingredientes y texto de
alérgenos transcritos manualmente como si vinieran del OCR.

NO contiene reglas hardcodeadas por ingrediente: todas las expectativas
vienen de Dataset/ground_truth.py, todas las reglas vienen del fact base
(IngredientFacts) y los predicados declarativos del pipeline v3.

Uso:
    python -m evaluation.evaluate_v3
    python -m evaluation.evaluate_v3 --product foto17_caldo
    python -m evaluation.evaluate_v3 --skip-init      # asume servicios ya cargados

Costo: $0 — no llama a Gemini. Sí carga MarianMT y sentence-transformers
una vez al inicio (~450MB de modelos pre-entrenados).
"""

import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

from Dataset.ground_truth import GROUND_TRUTH
from app.database.connection import get_db, init_database
from app.services.analysis_pipeline import (
    AnalysisPipeline,
    PipelineResult,
    analysis_pipeline,
)
from app.services.restriction_predicates import ALL_RESTRICTIONS
from app.utils.initialization import initialize_system
from evaluation.metrics import (
    EvaluationReport,
    ProductResult,
    RESTRICTION_DISPLAY,
    format_report,
)


def _ingredients_text(case: dict) -> str:
    """
    Reconstruye el texto crudo de la lista de ingredientes a partir del
    ground truth. El parser espera el formato de etiqueta argentina
    (separación por comas con prefijos de función opcionales tipo
    "función: ingrediente").
    """
    return ", ".join(case["ingredientes"])


async def _evaluate_one(
    product_id: str,
    case: dict,
    pipeline: AnalysisPipeline,
    db,
) -> tuple[PipelineResult, ProductResult]:
    ingredients_text = _ingredients_text(case)
    allergen_text = case.get("alergenos") or ""

    result = await pipeline.run_from_text(
        ingredients_text=ingredients_text,
        allergen_text=allergen_text,
        user_restrictions=list(ALL_RESTRICTIONS),
        db=db,
    )

    pr = ProductResult(product_id=product_id, product_name=case["nombre"])
    expected = case["expected"]
    all_ok = True

    for restriction in ALL_RESTRICTIONS:
        verdict = result.restrictions.get(restriction)
        if verdict is None:
            # Defensivo: si por alguna razón el pipeline no produjo veredicto
            # para una restricción solicitada, lo contamos como no-apto para
            # que cuente como falla en métricas.
            predicted_apto = False
            motivo = "veredicto no producido por el pipeline"
            fuente = "missing"
        else:
            predicted_apto = verdict.apto
            motivo = verdict.motivo
            fuente = verdict.fuente

        is_correct = predicted_apto == expected[restriction]
        pr.restriction_results[restriction] = {
            "expected": expected[restriction],
            "predicted": predicted_apto,
            "correct": is_correct,
            "motivo": motivo,
            "fuente": fuente,
        }

        if not is_correct:
            all_ok = False
            exp_str = "APTO" if expected[restriction] else "NO APTO"
            pred_str = "APTO" if predicted_apto else "NO APTO"
            danger = ""
            if not expected[restriction] and predicted_apto:
                danger = " [!] FALSO NEGATIVO (peligroso)"
            pr.errors.append(
                f"{RESTRICTION_DISPLAY[restriction]}: "
                f"esperado={exp_str}, obtenido={pred_str} "
                f"(motivo: {motivo}; fuente: {fuente}){danger}"
            )

    pr.all_correct = all_ok
    return result, pr


async def run_evaluation(only_product: str | None = None) -> EvaluationReport:
    report = EvaluationReport(mode="V3 pipeline (sin Gemini OCR)")
    pipeline = analysis_pipeline
    db = next(get_db())

    aggregated_stats = {
        "total_ingredients": 0,
        "total_flavorings": 0,
        "resolved_by_legal": 0,
        "resolved_by_codex": 0,
        "resolved_by_off": 0,
        "resolved_by_kb": 0,
        "resolved_by_gemini": 0,
        "resolved_by_llm": 0,
        "resolved_by_policy": 0,
        "unresolved": 0,
        "total_time_ms": 0.0,
    }

    cases = GROUND_TRUTH.items()
    if only_product:
        cases = [(only_product, GROUND_TRUTH[only_product])]

    total_start = time.time()
    for product_id, case in cases:
        if case.get("mala_calidad"):
            report.skipped_bad_quality += 1
            continue

        try:
            result, pr = await _evaluate_one(product_id, case, pipeline, db)
        except Exception as e:
            logger.exception(f"Excepción evaluando {product_id}")
            pr = ProductResult(product_id=product_id, product_name=case["nombre"])
            pr.all_correct = False
            pr.errors.append(f"EXCEPCIÓN: {type(e).__name__}: {e}")
            report.product_results.append(pr)
            report.total_products += 1
            continue

        report.total_products += 1
        report.product_results.append(pr)
        if pr.all_correct:
            report.products_correct += 1

        for restriction in ALL_RESTRICTIONS:
            r = pr.restriction_results[restriction]
            report.record(
                product_id=product_id,
                product_name=case["nombre"],
                restriction=restriction,
                predicted_apto=r["predicted"],
                expected_apto=r["expected"],
                motivo=r["motivo"],
            )

        aggregated_stats["total_ingredients"] += result.stats.total_ingredients
        aggregated_stats["total_flavorings"] += result.stats.total_flavorings
        aggregated_stats["resolved_by_legal"] += result.stats.resolved_by_legal
        aggregated_stats["resolved_by_codex"] += result.stats.resolved_by_codex
        aggregated_stats["resolved_by_off"] += result.stats.resolved_by_off
        aggregated_stats["resolved_by_kb"] += result.stats.resolved_by_kb
        aggregated_stats["resolved_by_gemini"] += result.stats.resolved_by_gemini
        aggregated_stats["resolved_by_llm"] += result.stats.resolved_by_llm
        aggregated_stats["resolved_by_policy"] += result.stats.resolved_by_policy
        aggregated_stats["unresolved"] += result.stats.unresolved
        aggregated_stats["total_time_ms"] += result.stats.processing_time_ms

    total_time = time.time() - total_start
    db.close()

    print(format_report(report))
    _print_pipeline_stats(aggregated_stats, total_time, report.total_products)

    return report


def _print_pipeline_stats(stats: dict, total_time: float, n_products: int) -> None:
    w = 80
    print("=" * w)
    print("  ESTADÍSTICAS DEL PIPELINE V3 (agregadas sobre dataset)")
    print("=" * w)

    n = stats["total_ingredients"]
    if n == 0:
        print("  (sin ingredientes procesados)")
        return

    def pct(x: int) -> str:
        return f"{x:>4} ({x / n:>5.1%})"

    print(f"  Productos evaluados:               {n_products}")
    print(f"  Ingredientes totales:              {n}")
    print(f"  Aromatizantes detectados:          {stats['total_flavorings']}")
    print()
    print(f"  Resolución por fuente (de {n} ingredientes):")
    print(f"    Declaración legal (cortocircuito): {pct(stats['resolved_by_legal'])}")
    print(f"    Codex INS:                         {pct(stats['resolved_by_codex'])}")
    print(f"    Open Food Facts taxonomy:          {pct(stats['resolved_by_off'])}")
    print(f"    Knowledge Base local:              {pct(stats['resolved_by_kb'])}")
    print(f"    Gemini pre-clasificación:          {pct(stats['resolved_by_gemini'])}")
    print(f"    Resuelto por LLM:                  {pct(stats['resolved_by_llm'])}")
    print(f"    Política CAA / reglas internas:    {pct(stats['resolved_by_policy'])}")
    print(f"    No resueltos:                      {pct(stats['unresolved'])}")
    print()
    print(f"  Tiempo total de pipeline:          {stats['total_time_ms']/1000:.2f}s")
    print(f"  Wall clock (incluye init/translate): {total_time:.2f}s")
    print(f"  Promedio por producto:             {stats['total_time_ms']/max(n_products,1):.0f}ms")
    print("=" * w)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evalúa el pipeline contra el ground truth (sin Gemini OCR).")
    parser.add_argument("--product", default=None, help="Evaluar un solo producto por id (e.g. foto17_caldo)")
    parser.add_argument("--skip-init", action="store_true", help="Saltar initialize_system (asume servicios ya cargados)")
    args = parser.parse_args()

    print("\n" + "#" * 80)
    print("#  NUTRIGUIDE — EVALUACIÓN PIPELINE V3 (FACT BASE / RULE BASE)")
    print("#" * 80)
    print()

    init_database()

    if not args.skip_init:
        print("  Inicializando servicios (MarianMT, embeddings, loaders, KB)...")
        try:
            initialize_system()
            print("  Servicios listos.\n")
        except Exception as e:
            print(f"  [!] initialize_system falló: {e}")
            print("      Continuando con servicios degradados.\n")

    report = asyncio.run(run_evaluation(only_product=args.product))

    total_fn = sum(cm.fn for cm in report.confusion_matrices.values())
    total_fp = sum(cm.fp for cm in report.confusion_matrices.values())

    print()
    print(f"  Productos 100% correctos:   {report.products_correct}/{report.total_products} ({report.product_accuracy:.1%})")
    print(f"  Accuracy global:            {report.overall_accuracy:.1%}")
    print(f"  Macro F1:                   {report.macro_f1:.1%}")
    print(f"  Macro recall:               {report.macro_recall:.1%}")
    print(f"  Falsos negativos (peligro): {total_fn}")
    print(f"  Falsos positivos (rechazo): {total_fp}")
    print()

    return 0 if total_fn == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
