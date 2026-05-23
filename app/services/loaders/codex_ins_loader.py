# app/services/loaders/codex_ins_loader.py
"""
Loader de la base de aditivos Codex Alimentarius INS.

Indexa en memoria una tabla de códigos INS con su clasificación oficial
(función, origen, restricciones aplicables).

Fuente: `app/data/ins_codes.yaml` — datos curados editables sin tocar
código. Diseñado para ser sustituido por la base oficial Codex CXG 36-1989
cuando esté disponible en JSON descargable, sin cambiar la API pública.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

import yaml

from app.services.ingredient_facts import (
    ALLERGEN_LACTOSE,
    ALLERGEN_MILK,
    ALLERGEN_WHEAT,
    DAIRY_SOURCES,
    GLUTEN_SOURCES,
    NUT_SOURCES,
    ANIMAL_SOURCES,
    Origin,
    TagProvenance,
)

logger = logging.getLogger(__name__)

_INS_DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "ins_codes.yaml"
_VALID_RESTRICTIONS = {"sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"}


def _load_ins_codes_yaml() -> Tuple[Dict[int, Dict[str, str]], FrozenSet[int], List[Tuple[int, int]]]:
    """
    Carga ins_codes.yaml y retorna:
      - affects: {código: {restricción: razón}}
      - safe_codes: frozenset de códigos explícitamente seguros
      - safe_ranges: lista de (inicio, fin) inclusivos
    """
    if not _INS_DATA_FILE.exists():
        logger.error(f"INS data file not found: {_INS_DATA_FILE}")
        return {}, frozenset(), []

    with open(_INS_DATA_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    affects_raw = data.get("affects", {}) or {}
    affects: Dict[int, Dict[str, str]] = {}
    for code, restrictions in affects_raw.items():
        code_int = int(code)
        for restriction in restrictions:
            if restriction not in _VALID_RESTRICTIONS:
                logger.warning(
                    f"ins_codes.yaml: restricción desconocida '{restriction}' "
                    f"en código {code_int} — ignorada"
                )
        affects[code_int] = {
            r: reason for r, reason in restrictions.items()
            if r in _VALID_RESTRICTIONS
        }

    safe_codes = frozenset(int(c) for c in (data.get("safe", []) or []))
    safe_ranges = [
        (int(r[0]), int(r[1])) for r in (data.get("safe_ranges", []) or [])
    ]
    return affects, safe_codes, safe_ranges


# ═══════════════════════════════════════════════════════════════════════════
# Mapeos auxiliares
# ═══════════════════════════════════════════════════════════════════════════

# Función predominante por rango de códigos INS (Codex Alimentarius)
# Estos rangos son convención oficial del Codex y permiten clasificar
# códigos no listados explícitamente.
_INS_FUNCTION_RANGES = [
    (100, 199, "colorante"),
    (200, 299, "conservante"),
    (300, 399, "antioxidante"),
    (400, 499, "estabilizante"),
    (500, 599, "regulador-anti aglutinante-leudante"),
    (600, 699, "resaltador"),
    (700, 799, "antibiotico"),
    (900, 999, "varios-recubrimiento-edulcorante"),
    (1000, 1599, "varios"),
]


def _function_for_code(code: int) -> Optional[str]:
    for lo, hi, fn in _INS_FUNCTION_RANGES:
        if lo <= code <= hi:
            return fn
    return None


# Mapeo restricción del sistema viejo → tags canónicos del nuevo
_RESTRICTION_TO_TAGS = {
    "sin_tacc": (GLUTEN_SOURCES, "contains"),
    "sin_lactosa": (DAIRY_SOURCES, "contains"),
    "sin_frutos_secos": (NUT_SOURCES, "contains"),
    "vegano": (ANIMAL_SOURCES, "contains"),
}


# ═══════════════════════════════════════════════════════════════════════════
# Resultado de un lookup
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CodexInsEntry:
    """Resultado del lookup de un código INS."""
    code: int
    subcode: Optional[str] = None
    function_tag: Optional[str] = None
    origin: Origin = Origin.UNKNOWN
    allergens: Set[str] = field(default_factory=set)
    contains: Set[str] = field(default_factory=set)
    derived_from: Set[str] = field(default_factory=set)
    confidence: float = 0.0
    evidence: str = ""

    def to_provenance(self) -> TagProvenance:
        return TagProvenance(
            source="codex_ins",
            confidence=self.confidence,
            evidence=self.evidence,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Loader
# ═══════════════════════════════════════════════════════════════════════════


class CodexInsLoader:
    """Indexa los códigos INS y permite consultas O(1)."""

    def __init__(self):
        self._affects: Dict[int, Dict[str, str]] = {}
        self._safe_codes: Set[int] = set()
        self._safe_ranges: List[tuple] = []
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def initialize(self) -> int:
        """
        Carga los datos desde la fuente actual (tier1_data/ins_codes.yaml).
        Retorna la cantidad de códigos indexados.
        """
        if self._initialized:
            return self._size()

        try:
            affects, safe_codes, safe_ranges = _load_ins_codes_yaml()
            self._affects = affects
            self._safe_codes = set(safe_codes)
            self._safe_ranges = list(safe_ranges)
            self._initialized = True

            n = self._size()
            logger.info(
                f"Codex INS loader: {n} códigos indexados "
                f"({len(self._affects)} con restricciones, "
                f"{len(self._safe_codes)} explícitamente seguros)"
            )
            return n

        except Exception as e:
            logger.error(f"Error cargando Codex INS: {e}")
            self._initialized = True
            return 0

    def _size(self) -> int:
        return len(self._affects) + len(self._safe_codes)

    def lookup(self, code: int, subcode: Optional[str] = None) -> Optional[CodexInsEntry]:
        """
        Busca un código INS. Retorna CodexInsEntry si lo conoce, None si no.
        """
        if not self._initialized:
            return None

        is_safe_explicit = code in self._safe_codes
        is_safe_range = any(lo <= code <= hi for lo, hi in self._safe_ranges)
        is_affected = code in self._affects

        if not (is_safe_explicit or is_safe_range or is_affected):
            return None

        function = _function_for_code(code)
        entry = CodexInsEntry(
            code=code,
            subcode=subcode,
            function_tag=function,
            confidence=0.94,
            evidence=f"Codex Alimentarius INS {code}{subcode or ''}",
        )

        # Inferir origen por rango (la mayoría de aditivos del Codex son
        # sintéticos o minerales; los que tienen origen animal/vegetal
        # están en el mapa _affects con razón explícita).
        if is_affected:
            for restriction, reason in self._affects[code].items():
                tag_set, _ = _RESTRICTION_TO_TAGS.get(restriction, (set(), None))

                if restriction == "sin_tacc":
                    entry.contains.add(ALLERGEN_WHEAT)
                elif restriction == "sin_lactosa":
                    entry.contains.add(ALLERGEN_MILK)
                elif restriction == "sin_frutos_secos":
                    entry.contains.update(NUT_SOURCES)
                elif restriction == "vegano":
                    entry.origin = Origin.ANIMAL
                    entry.derived_from.add("animal")

                entry.evidence += f" — afecta {restriction}: {reason}"
        else:
            # Default: aditivos sin afectación documentada se consideran
            # sintéticos o minerales (origen no animal por defecto).
            entry.origin = Origin.SYNTHETIC

        return entry


codex_ins_loader = CodexInsLoader()
