"""
Módulo de métricas para evaluación de NutriGuide.

Calcula precision, recall, F1-score, accuracy y matrices de confusión
para cada restricción dietética.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


ALL_RESTRICTIONS = ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"]

RESTRICTION_DISPLAY = {
    "sin_tacc": "Sin TACC",
    "sin_lactosa": "Sin Lactosa",
    "sin_frutos_secos": "Sin Frutos Secos",
    "vegano": "Vegano",
}


@dataclass
class ConfusionMatrix:
    tp: int = 0  # Predicho NO APTO, real NO APTO (correcto)
    fp: int = 0  # Predicho NO APTO, real APTO (falso positivo)
    tn: int = 0  # Predicho APTO, real APTO (correcto)
    fn: int = 0  # Predicho APTO, real NO APTO (falso negativo - peligroso)

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        """De los que predijo como NO APTO, cuántos realmente lo eran."""
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        """De los realmente NO APTOS, cuántos detectó correctamente.
        Recall bajo = peligroso (deja pasar productos inseguros)."""
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def specificity(self) -> float:
        """De los realmente APTOS, cuántos identificó correctamente."""
        return self.tn / (self.tn + self.fp) if (self.tn + self.fp) else 0.0

    @property
    def false_negative_rate(self) -> float:
        """Tasa de falsos negativos: productos inseguros marcados como seguros."""
        return self.fn / (self.fn + self.tp) if (self.fn + self.tp) else 0.0


@dataclass
class ProductResult:
    product_id: str
    product_name: str
    restriction_results: Dict[str, dict] = field(default_factory=dict)
    all_correct: bool = True
    errors: List[str] = field(default_factory=list)


@dataclass
class EvaluationReport:
    """Reporte completo de evaluación."""
    mode: str  # "tier1_only", "tier1_allergens", "full_pipeline"
    total_products: int = 0
    products_correct: int = 0
    product_results: List[ProductResult] = field(default_factory=list)
    confusion_matrices: Dict[str, ConfusionMatrix] = field(default_factory=dict)
    skipped_bad_quality: int = 0

    def __post_init__(self):
        if not self.confusion_matrices:
            self.confusion_matrices = {r: ConfusionMatrix() for r in ALL_RESTRICTIONS}

    @property
    def product_accuracy(self) -> float:
        return self.products_correct / self.total_products if self.total_products else 0.0

    @property
    def overall_accuracy(self) -> float:
        total = sum(cm.total for cm in self.confusion_matrices.values())
        correct = sum(cm.tp + cm.tn for cm in self.confusion_matrices.values())
        return correct / total if total else 0.0

    @property
    def macro_f1(self) -> float:
        f1s = [cm.f1 for cm in self.confusion_matrices.values()]
        return sum(f1s) / len(f1s) if f1s else 0.0

    @property
    def macro_recall(self) -> float:
        recalls = [cm.recall for cm in self.confusion_matrices.values()]
        return sum(recalls) / len(recalls) if recalls else 0.0

    def record(self, product_id: str, product_name: str,
               restriction: str, predicted_apto: bool, expected_apto: bool,
               motivo: Optional[str] = None):
        cm = self.confusion_matrices[restriction]

        if not expected_apto and not predicted_apto:
            cm.tp += 1
        elif expected_apto and not predicted_apto:
            cm.fp += 1
        elif expected_apto and predicted_apto:
            cm.tn += 1
        elif not expected_apto and predicted_apto:
            cm.fn += 1


def format_report(report: EvaluationReport) -> str:
    """Formatea un reporte de evaluación como texto legible."""
    lines = []
    w = 80

    lines.append("=" * w)
    lines.append(f"  EVALUACION NUTRIGUIDE -- {report.mode.upper()}")
    lines.append(f"  Productos evaluados: {report.total_products} "
                 f"(excluidos por mala calidad: {report.skipped_bad_quality})")
    lines.append("=" * w)

    # Resultados por producto
    lines.append("")
    lines.append("-" * w)
    lines.append("  RESULTADOS POR PRODUCTO")
    lines.append("-" * w)

    for pr in report.product_results:
        status = "OK" if pr.all_correct else "FAIL"
        icon = "[OK]" if pr.all_correct else "[!!]"
        lines.append(f"  {icon} {pr.product_id}: {pr.product_name} -- {status}")
        for err in pr.errors:
            lines.append(f"      {err}")

    lines.append("")
    lines.append(f"  Productos 100% correctos: {report.products_correct}/{report.total_products} "
                 f"({report.product_accuracy:.1%})")

    lines.append("")
    lines.append("-" * w)
    lines.append("  METRICAS POR RESTRICCION")
    lines.append("-" * w)

    header = f"  {'Restriccion':<22} {'Acc':>6} {'Prec':>6} {'Rec':>6} {'F1':>6} {'FNR':>6}  {'TP':>3} {'FP':>3} {'TN':>3} {'FN':>3}"
    lines.append(header)
    lines.append("  " + "-" * (w - 4))

    for r in ALL_RESTRICTIONS:
        cm = report.confusion_matrices[r]
        display = RESTRICTION_DISPLAY.get(r, r)
        fnr = cm.false_negative_rate
        lines.append(
            f"  {display:<22} {cm.accuracy:>5.1%} {cm.precision:>5.1%} "
            f"{cm.recall:>5.1%} {cm.f1:>5.1%} {fnr:>5.1%}  "
            f"{cm.tp:>3} {cm.fp:>3} {cm.tn:>3} {cm.fn:>3}"
        )

    lines.append("  " + "-" * (w - 4))
    lines.append(f"  {'GLOBAL (macro)':<22} {report.overall_accuracy:>5.1%} "
                 f"{'':>6} {report.macro_recall:>5.1%} {report.macro_f1:>5.1%}")

    lines.append("")
    lines.append("-" * w)
    lines.append("  MATRICES DE CONFUSION (filas=real, cols=predicho)")
    lines.append("-" * w)

    for r in ALL_RESTRICTIONS:
        cm = report.confusion_matrices[r]
        display = RESTRICTION_DISPLAY.get(r, r)
        lines.append(f"\n  {display}:")
        lines.append(f"  {'':>20} {'Pred NO APTO':>14} {'Pred APTO':>14}")
        lines.append(f"  {'Real NO APTO':>20} {cm.tp:>14} {cm.fn:>14}")
        lines.append(f"  {'Real APTO':>20} {cm.fp:>14} {cm.tn:>14}")

    lines.append("")
    lines.append("-" * w)
    lines.append("  ANALISIS DE SEGURIDAD")
    lines.append("-" * w)

    total_fn = sum(cm.fn for cm in report.confusion_matrices.values())
    if total_fn == 0:
        lines.append("  [OK] CERO falsos negativos -- ningun producto inseguro fue marcado como seguro")
    else:
        lines.append(f"  [!!] {total_fn} FALSOS NEGATIVOS detectados (productos inseguros marcados como seguros)")
        lines.append("    Estos son los errores mas peligrosos para la salud del usuario:")
        for pr in report.product_results:
            for err in pr.errors:
                if "PELIGROSO" in err:
                    lines.append(f"      {pr.product_id}: {err}")

    lines.append("")
    lines.append("=" * w)

    return "\n".join(lines)


def format_comparison(reports: List[EvaluationReport]) -> str:
    """Genera tabla comparativa entre modos de evaluación (ablation study)."""
    lines = []
    w = 90

    lines.append("")
    lines.append("=" * w)
    lines.append("  ABLATION STUDY -- COMPARACION DE MODOS")
    lines.append("=" * w)

    header = (f"  {'Modo':<28} {'Acc Global':>10} {'Macro F1':>10} "
              f"{'Macro Rec':>10} {'Prod OK':>10} {'FN Total':>10}")
    lines.append(header)
    lines.append("  " + "-" * (w - 4))

    for r in reports:
        total_fn = sum(cm.fn for cm in r.confusion_matrices.values())
        lines.append(
            f"  {r.mode:<28} {r.overall_accuracy:>9.1%} {r.macro_f1:>9.1%} "
            f"{r.macro_recall:>9.1%} "
            f"{r.products_correct}/{r.total_products:>7} {total_fn:>10}"
        )

    lines.append("  " + "-" * (w - 4))

    lines.append("")
    lines.append("  Desglose por restriccion:")
    for restriction in ALL_RESTRICTIONS:
        display = RESTRICTION_DISPLAY.get(restriction, restriction)
        lines.append(f"\n  {display}:")
        sub_header = f"    {'Modo':<26} {'Acc':>6} {'Prec':>6} {'Rec':>6} {'F1':>6} {'FN':>4}"
        lines.append(sub_header)

        for r in reports:
            cm = r.confusion_matrices[restriction]
            lines.append(
                f"    {r.mode:<26} {cm.accuracy:>5.1%} {cm.precision:>5.1%} "
                f"{cm.recall:>5.1%} {cm.f1:>5.1%} {cm.fn:>4}"
            )

    lines.append("")
    lines.append("=" * w)
    return "\n".join(lines)
