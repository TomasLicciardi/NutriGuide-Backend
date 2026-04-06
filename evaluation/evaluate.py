"""
Evaluación formal de NutriGuide contra el ground truth.

Modos de evaluación:
  1. tier1_only:       Solo clasificador determinista (sin texto de alérgenos)
  2. tier1_allergens:  Tier 1 + parser de alérgenos (lo que corre offline)
  3. tier1_ablation:   Tier 1 descompuesto (INS, keywords, safe, unresolved)

Genera métricas de precisión, recall, F1 y matrices de confusión
que son requeridas para la defensa de tesis.

Uso:
  python -m evaluation.evaluate
"""

import sys
import os
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Dataset.ground_truth import GROUND_TRUTH
from app.services.deterministic_classifier import (
    DeterministicClassifier, IngredientResult, ALL_RESTRICTIONS,
)
from app.utils.allergen_parser import parse_allergen_text, AllergenParseResult, POSITIVE_DECLARATION_MAP
from app.services.consensus_engine import (
    ConsensusEngine, IngredientVerdict, ProductVerdict,
    MEDICAL_RESTRICTIONS, _RESTRICTION_FIELD,
)
from evaluation.metrics import (
    EvaluationReport, ProductResult, ConfusionMatrix,
    format_report, format_comparison,
    ALL_RESTRICTIONS as METRIC_RESTRICTIONS,
    RESTRICTION_DISPLAY,
)

classifier = DeterministicClassifier()
consensus = ConsensusEngine()


def _tier1_to_verdict(r: IngredientResult) -> IngredientVerdict:
    """Convierte un IngredientResult de Tier 1 a IngredientVerdict."""
    return IngredientVerdict(
        name_es=r.name,
        name_en="",
        category=r.category,
        is_tacc_safe=r.is_tacc_safe,
        is_lactose_safe=r.is_lactose_safe,
        is_nut_safe=r.is_nut_safe,
        is_vegan_safe=r.is_vegan_safe,
        confidence=r.confidence,
        resolved_by=r.resolved_by,
        evidence=r.evidence[:],
    )


def _build_verdict_from_tier1(
    ingredients: List[str],
    allergen_text: str,
    use_allergens: bool = True,
) -> ProductVerdict:
    """Ejecuta Tier 1 + opcionalmente alérgenos y construye el veredicto."""
    tier1 = classifier.classify_batch(ingredients)

    verdicts: List[IngredientVerdict] = []
    for name in ingredients:
        if name in tier1.resolved:
            verdicts.append(_tier1_to_verdict(tier1.resolved[name]))
        else:
            r = classifier.classify_ingredient(name)
            verdicts.append(_tier1_to_verdict(r))

    if use_allergens:
        allergen_result = parse_allergen_text(allergen_text)
    else:
        allergen_result = AllergenParseResult()

    return consensus.build_product_verdict(verdicts, allergen_result, [])


def evaluate_mode(
    mode: str,
    use_allergens: bool,
) -> EvaluationReport:
    """Evalúa todos los productos del ground truth en un modo dado."""
    report = EvaluationReport(mode=mode)

    for product_id, data in GROUND_TRUTH.items():
        if data.get("mala_calidad"):
            report.skipped_bad_quality += 1
            continue

        ingredients = data["ingredientes"]
        allergen_text = data.get("alergenos", "")
        expected = data["expected"]

        verdict = _build_verdict_from_tier1(
            ingredients, allergen_text, use_allergens=use_allergens,
        )

        report.total_products += 1
        pr = ProductResult(product_id=product_id, product_name=data["nombre"])

        all_ok = True
        for restriction in ALL_RESTRICTIONS:
            expected_apto = expected[restriction]
            predicted_apto = verdict.restrictions[restriction]["apto"]
            motivo = verdict.restrictions[restriction].get("motivo")

            report.record(product_id, data["nombre"],
                          restriction, predicted_apto, expected_apto, motivo)

            is_correct = predicted_apto == expected_apto
            pr.restriction_results[restriction] = {
                "expected": expected_apto,
                "predicted": predicted_apto,
                "correct": is_correct,
                "motivo": motivo,
            }

            if not is_correct:
                all_ok = False
                exp_str = "APTO" if expected_apto else "NO APTO"
                pred_str = "APTO" if predicted_apto else "NO APTO"

                danger = ""
                if not expected_apto and predicted_apto:
                    danger = " [!] PELIGROSO: falso negativo"

                err = (f"{RESTRICTION_DISPLAY[restriction]}: "
                       f"esperado={exp_str}, obtenido={pred_str}"
                       f" (motivo: {motivo}){danger}")
                pr.errors.append(err)

        pr.all_correct = all_ok
        if all_ok:
            report.products_correct += 1
        report.product_results.append(pr)

    return report


def evaluate_tier1_components() -> Dict[str, EvaluationReport]:
    """Evalúa cada componente del Tier 1 por separado (ablation intra-tier)."""
    components = {
        "tier1_ins_only": "Solo códigos INS/E",
        "tier1_keywords_only": "Solo keywords",
        "tier1_safe_only": "Solo ingredientes seguros",
    }

    reports = {}
    for component_key, component_name in components.items():
        report = EvaluationReport(mode=component_name)

        for product_id, data in GROUND_TRUTH.items():
            if data.get("mala_calidad"):
                report.skipped_bad_quality += 1
                continue

            ingredients = data["ingredientes"]
            expected = data["expected"]
            report.total_products += 1

            verdicts: List[IngredientVerdict] = []
            for name in ingredients:
                r = classifier.classify_ingredient(name)

                include = False
                if component_key == "tier1_ins_only" and "ins" in r.resolved_by:
                    include = True
                elif component_key == "tier1_keywords_only" and "keyword" in r.resolved_by:
                    include = True
                elif component_key == "tier1_safe_only" and "safe" in r.resolved_by:
                    include = True

                if include:
                    verdicts.append(_tier1_to_verdict(r))
                else:
                    verdicts.append(IngredientVerdict(
                        name_es=name, name_en="", category=r.category,
                    ))

            allergen_result = AllergenParseResult()
            pv = consensus.build_product_verdict(verdicts, allergen_result, [])

            pr = ProductResult(product_id=product_id, product_name=data["nombre"])
            all_ok = True
            for restriction in ALL_RESTRICTIONS:
                expected_apto = expected[restriction]
                predicted_apto = pv.restrictions[restriction]["apto"]
                report.record(product_id, data["nombre"],
                              restriction, predicted_apto, expected_apto)
                if predicted_apto != expected_apto:
                    all_ok = False

            pr.all_correct = all_ok
            if all_ok:
                report.products_correct += 1
            report.product_results.append(pr)

        reports[component_key] = report

    return reports


def evaluate_tier1_resolution_stats():
    """Estadísticas de resolución del Tier 1 sobre el ground truth."""
    total_ingredients = 0
    resolved_ins = 0
    resolved_keyword = 0
    resolved_safe = 0
    unresolved = 0
    unique_ingredients = set()
    unique_unresolved = set()

    for product_id, data in GROUND_TRUTH.items():
        if data.get("mala_calidad"):
            continue
        for name in data["ingredientes"]:
            total_ingredients += 1
            unique_ingredients.add(classifier.normalize(name))
            r = classifier.classify_ingredient(name)
            if "ins" in r.resolved_by:
                resolved_ins += 1
            elif "keyword" in r.resolved_by:
                resolved_keyword += 1
            elif "safe" in r.resolved_by:
                resolved_safe += 1
            else:
                unresolved += 1
                unique_unresolved.add(classifier.normalize(name))

    total_resolved = resolved_ins + resolved_keyword + resolved_safe
    lines = []
    w = 80
    lines.append("")
    lines.append("=" * w)
    lines.append("  ESTADISTICAS DE RESOLUCION -- TIER 1 DETERMINISTA")
    lines.append("=" * w)
    lines.append(f"  Total ingredientes analizados:    {total_ingredients}")
    lines.append(f"  Ingredientes unicos:              {len(unique_ingredients)}")
    lines.append("")
    lines.append(f"  Resueltos por INS/E:              {resolved_ins:>4} ({resolved_ins/total_ingredients:.1%})")
    lines.append(f"  Resueltos por keywords:           {resolved_keyword:>4} ({resolved_keyword/total_ingredients:.1%})")
    lines.append(f"  Resueltos por safe list:          {resolved_safe:>4} ({resolved_safe/total_ingredients:.1%})")
    lines.append(f"  ---------------------------------------")
    lines.append(f"  Total resueltos:                  {total_resolved:>4} ({total_resolved/total_ingredients:.1%})")
    lines.append(f"  No resueltos (necesitan Tier 2+): {unresolved:>4} ({unresolved/total_ingredients:.1%})")
    lines.append("")

    if unique_unresolved:
        lines.append(f"  Ingredientes unicos no resueltos ({len(unique_unresolved)}):")
        for u in sorted(unique_unresolved):
            lines.append(f"    • {u}")

    lines.append("=" * w)
    return "\n".join(lines)


def export_csv(reports: List[EvaluationReport], filepath: str):
    """Exporta resultados a CSV para análisis externo o inclusión en la tesis."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("Modo,Restriccion,Accuracy,Precision,Recall,F1,FNR,TP,FP,TN,FN\n")
        for report in reports:
            for r in ALL_RESTRICTIONS:
                cm = report.confusion_matrices[r]
                display = RESTRICTION_DISPLAY[r]
                f.write(
                    f"{report.mode},{display},"
                    f"{cm.accuracy:.4f},{cm.precision:.4f},"
                    f"{cm.recall:.4f},{cm.f1:.4f},"
                    f"{cm.false_negative_rate:.4f},"
                    f"{cm.tp},{cm.fp},{cm.tn},{cm.fn}\n"
                )


def main():
    print("\n" + "#" * 80)
    print("#" + " " * 15 + "NUTRIGUIDE -- EVALUACION FORMAL PARA TESIS" + " " * 20 + "#")
    print("#" * 80)

    report_tier1 = evaluate_mode("Tier 1 (determinista)", use_allergens=False)
    print(format_report(report_tier1))

    report_tier1_allergens = evaluate_mode("Tier 1 + Alergenos", use_allergens=True)
    print(format_report(report_tier1_allergens))

    print(evaluate_tier1_resolution_stats())

    component_reports = evaluate_tier1_components()
    all_reports = [
        report_tier1,
        report_tier1_allergens,
    ] + list(component_reports.values())

    print(format_comparison([report_tier1, report_tier1_allergens] + list(component_reports.values())))

    # ─── Exportar CSV ───
    csv_path = os.path.join(os.path.dirname(__file__), "resultados.csv")
    export_csv(all_reports, csv_path)
    print(f"\n  Resultados exportados a: {csv_path}")

    print("\n" + "#" * 80)
    print("#" + " " * 22 + "RESUMEN EJECUTIVO" + " " * 39 + "#")
    print("#" * 80)

    best = report_tier1_allergens
    print(f"""
  Modo mas completo evaluado: {best.mode}
  -----------------------------------------
  Productos evaluados:        {best.total_products}
  Productos 100%% correctos:   {best.products_correct}/{best.total_products} ({best.product_accuracy:.1%})
  Accuracy global:            {best.overall_accuracy:.1%}
  Macro F1-Score:             {best.macro_f1:.1%}
  Macro Recall:               {best.macro_recall:.1%}
  Falsos negativos totales:   {sum(cm.fn for cm in best.confusion_matrices.values())}
""")

    total_fn = sum(cm.fn for cm in best.confusion_matrices.values())
    if total_fn == 0:
        print("  [OK] SEGURIDAD: Cero falsos negativos. Ningun producto inseguro")
        print("       fue clasificado como seguro para el usuario.")
    else:
        print(f"  [!!] ATENCION: {total_fn} falsos negativos detectados.")
        print("       Estos son errores de seguridad que deben corregirse.")

    print("\n" + "#" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
