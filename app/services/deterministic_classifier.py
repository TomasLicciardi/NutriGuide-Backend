# app/services/deterministic_classifier.py
"""
Clasificador determinista de ingredientes — Tier 1 del pipeline multi-fuente.

4 restricciones: sin_tacc, sin_lactosa, sin_frutos_secos, vegano.

Solo resuelve lo que puede afirmar con certeza absoluta:
  - Keywords directas (trigo, leche, almendra, carne...)
  - Safe compounds (evitar falsos positivos: ácido láctico, nuez moscada...)
  - Códigos INS/E con origen conocido
  - Ingredientes universalmente seguros (agua, sal, azúcar...)

Todo lo demás se delega a los Tiers 2-5 del pipeline.
"""

import re
import unicodedata
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

ALL_RESTRICTIONS = ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"]


# ═══════════════════════════════════════════════════════════════════════════════
# Keywords por restricción
# ═══════════════════════════════════════════════════════════════════════════════

RESTRICTION_KEYWORDS: Dict[str, List[str]] = {
    "sin_tacc": [
        "trigo", "avena", "cebada", "centeno",
        "gluten", "tacc",
        "malta", "semolina", "semola", "espelta", "kamut",
        "triticale", "farro", "cuscus", "bulgur", "seitan",
        "harina 000", "harina 0000",
    ],
    "sin_lactosa": [
        "leche", "lactosa", "queso", "yogur", "yogurt",
        "mantequilla", "manteca",
        "crema", "nata",
        "suero", "caseinato", "caseina", "lactosuero",
        "requeson", "ricota", "dulce de leche",
        "proteina de leche", "proteinas lacteas",
        "solidos de leche", "grasa de leche",
    ],
    "sin_frutos_secos": [
        "almendra", "nuez", "avellana", "pistacho",
        "anacardo", "macadamia", "pecan", "castana",
        "mani", "cacahuate", "cacahuete",
        "fruto seco", "frutos secos",
    ],
    "vegano": [
        # Lácteos
        "leche", "lactosa", "queso", "yogur", "yogurt",
        "mantequilla", "manteca",
        "crema", "nata",
        "suero", "caseinato", "caseina", "lactosuero",
        "requeson", "ricota", "dulce de leche",
        "proteina de leche", "proteinas lacteas",
        "solidos de leche", "grasa de leche",
        # Huevo
        "huevo", "albumina", "ovoalbumina", "yema", "lisozima",
        # Carne / pescado
        "carne", "pollo", "cerdo", "vacuno", "vacuna", "bovino", "bovina",
        "porcino", "porcina", "ovino", "ovina", "cordero", "pavo",
        "aviar", "primer jugo",
        "jamon", "salchicha", "embutido", "panceta", "tocino",
        "charqui", "bondiola", "chorizo", "morcilla",
        "pescado", "atun", "salmon", "anchoa", "sardina",
        "bacalao", "merluza", "trucha", "surimi",
        "marisco", "camaron", "langosta", "mejillon",
        "calamar", "pulpo",
        # Otros animales
        "miel", "propoleo", "jalea real", "cera de abeja",
        "gelatina",
        "carmin", "cochinilla",
        "grasa animal", "sebo",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Safe compounds — evitar falsos positivos
# ═══════════════════════════════════════════════════════════════════════════════

SAFE_COMPOUNDS: Dict[str, List[str]] = {
    "sin_tacc": [
        "maltodextrina",
        "dextrina",
    ],
    "sin_lactosa": [
        "leche de coco", "leche de almendra", "leche de soja",
        "leche de avena", "leche de arroz", "leche vegetal",
        "manteca de cacao", "manteca de mani",
        "crema de cacao", "crema de mani", "crema de leche de coco",
        "acido lactico", "lactato",
    ],
    "vegano": [
        "leche de coco", "leche de almendra", "leche de soja",
        "leche de avena", "leche de arroz", "leche vegetal",
        "manteca de cacao", "manteca de mani",
        "crema de cacao", "crema de mani", "crema de leche de coco",
        "acido lactico", "lactato",
        "gelatina vegetal", "gelatina de agar", "agar agar",
    ],
    "sin_frutos_secos": [
        "nuez moscada",
        "moscada",
    ],
}

UNSAFE_OVERRIDES: Dict[str, List[str]] = {
    "sin_tacc": [
        "maltodextrina de trigo",
        "dextrina de trigo",
        "almidon de trigo",
        "almidon modificado de trigo",
        "gluten de trigo",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Códigos INS/E que afectan restricciones
# ═══════════════════════════════════════════════════════════════════════════════

INS_AFFECTS: Dict[int, Dict[str, str]] = {
    120: {"vegano": "carmín/cochinilla (origen insecto)"},
    441: {"vegano": "gelatina (origen animal)"},
    542: {"vegano": "fosfato de hueso (origen animal)"},
    901: {"vegano": "cera de abejas"},
    904: {"vegano": "shellac/goma laca (origen insecto)"},
    966: {"sin_lactosa": "lactitol (derivado de lactosa)"},
}

_SAFE_INS_RANGES = [
    (200, 283), (300, 341), (400, 499),
    (500, 580), (620, 635), (950, 969),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Ingredientes universalmente seguros
# ═══════════════════════════════════════════════════════════════════════════════

ESSENTIAL_SAFE: frozenset = frozenset([
    "agua", "sal", "azucar", "aceite", "aceite de girasol",
    "aceite de oliva", "aceite vegetal", "aceite de palma",
    "aceite de soja", "aceite de maiz",
    "maiz", "arroz", "vinagre", "almidon de maiz",
    "fecula de maiz", "almidon modificado",
])


# ═══════════════════════════════════════════════════════════════════════════════
# Clasificación BASE / ADITIVO
# ═══════════════════════════════════════════════════════════════════════════════

_ADDITIVE_KEYWORDS = [
    "emulsificante", "emulsionante", "estabilizante", "conservador",
    "conservante", "acidulante", "antioxidante", "aromatizante",
    "colorante", "espesante", "regulador de acidez", "potenciador",
    "resaltador", "edulcorante", "gelificante", "humectante",
    "antiaglutinante", "mejorador", "leudante", "secuestrante",
    "gasificante", "saborizante",
]

_ADDITIVE_CHEMICAL_PATTERNS = [
    "acido ", "goma ", "sulfato", "fosfato", "nitrato",
    "carbonato", "cloruro", "oxido", "hidrolizado",
    "bicarbonato", "citrato", "benzoato", "sorbato",
    "propionato", "glutamato", "inosinato", "guanilato",
    "tocoferol", "lecitina", "pectina", "carragenina",
    "alginato", "maltodextrina", "dextrina",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class IngredientResult:
    name: str
    name_normalized: str
    category: str  # "BASE" | "ADITIVO"
    is_tacc_safe: Optional[bool] = None
    is_lactose_safe: Optional[bool] = None
    is_nut_safe: Optional[bool] = None
    is_vegan_safe: Optional[bool] = None
    confidence: float = 0.0
    resolved_by: str = "unresolved"
    evidence: List[str] = field(default_factory=list)


@dataclass
class Tier1Result:
    """Resultado completo del Tier 1 para todos los ingredientes."""
    resolved: Dict[str, IngredientResult] = field(default_factory=dict)
    unresolved: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=lambda: {
        "total": 0, "by_keyword": 0, "by_ins": 0, "by_safe": 0, "unresolved": 0,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Clasificador
# ═══════════════════════════════════════════════════════════════════════════════

class DeterministicClassifier:

    @staticmethod
    def normalize(text: str) -> str:
        nfkd = unicodedata.normalize("NFD", text)
        return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()

    @staticmethod
    def _extract_ins_code(text_normalized: str) -> Optional[int]:
        m = re.search(r"\bins\s*(\d{3,4})\b", text_normalized)
        if m:
            return int(m.group(1))
        m = re.match(r"^e(\d{3,4})[a-z]?$", text_normalized)
        if m:
            return int(m.group(1))
        return None

    def _classify_category(self, norm: str) -> str:
        if self._extract_ins_code(norm) is not None:
            return "ADITIVO"
        if any(kw in norm for kw in _ADDITIVE_KEYWORDS):
            return "ADITIVO"
        if any(p in norm for p in _ADDITIVE_CHEMICAL_PATTERNS):
            return "ADITIVO"
        return "BASE"

    def classify_ingredient(self, ingredient_name: str) -> IngredientResult:
        """Clasifica un ingrediente individual con reglas deterministas."""
        norm = self.normalize(ingredient_name)
        category = self._classify_category(norm)

        result = IngredientResult(
            name=ingredient_name,
            name_normalized=norm,
            category=category,
        )

        # --- Código INS/E ---
        ins_code = self._extract_ins_code(norm)
        if ins_code is not None:
            result.is_tacc_safe = True
            result.is_lactose_safe = True
            result.is_nut_safe = True
            result.is_vegan_safe = True

            if ins_code in INS_AFFECTS:
                for restriction, reason in INS_AFFECTS[ins_code].items():
                    self._set_unsafe(result, restriction, reason)

            if any(lo <= ins_code <= hi for lo, hi in _SAFE_INS_RANGES) or ins_code in INS_AFFECTS:
                result.confidence = 0.97
                result.resolved_by = "deterministic_ins"
                result.evidence.append(f"Código INS {ins_code} identificado")
                return result

        # --- Keywords + safe compounds ---
        any_keyword_matched = False
        for restriction in ALL_RESTRICTIONS:
            # Unsafe overrides primero
            for pattern in UNSAFE_OVERRIDES.get(restriction, []):
                if pattern in norm:
                    self._set_unsafe(result, restriction, pattern)
                    any_keyword_matched = True
                    break
            if self._restriction_is_set(result, restriction) and not self._is_safe(result, restriction):
                continue

            # Safe compounds
            is_safe_compound = False
            for safe in SAFE_COMPOUNDS.get(restriction, []):
                if safe in norm:
                    is_safe_compound = True
                    any_keyword_matched = True
                    break
            if is_safe_compound:
                self._set_safe(result, restriction)
                continue

            # Keywords de restricción
            for keyword in RESTRICTION_KEYWORDS.get(restriction, []):
                if keyword in norm:
                    self._set_unsafe(result, restriction, keyword)
                    any_keyword_matched = True
                    break

        if any_keyword_matched:
            for r in ALL_RESTRICTIONS:
                if not self._restriction_is_set(result, r):
                    self._set_safe(result, r)
            result.confidence = 0.95
            result.resolved_by = "deterministic_keyword"
            return result

        # --- Ingredientes universalmente seguros ---
        if norm in ESSENTIAL_SAFE:
            result.is_tacc_safe = True
            result.is_lactose_safe = True
            result.is_nut_safe = True
            result.is_vegan_safe = True
            result.confidence = 0.95
            result.resolved_by = "deterministic_safe"
            result.evidence.append(f"Ingrediente esencial seguro: '{norm}'")
            return result

        for safe in ESSENTIAL_SAFE:
            if safe in norm and len(safe) >= 4:
                result.is_tacc_safe = True
                result.is_lactose_safe = True
                result.is_nut_safe = True
                result.is_vegan_safe = True
                result.confidence = 0.90
                result.resolved_by = "deterministic_safe"
                result.evidence.append(f"Contiene ingrediente seguro: '{safe}'")
                return result

        # --- No resuelto ---
        return result

    def classify_batch(self, ingredients: List[str]) -> Tier1Result:
        """Clasifica un lote de ingredientes, separando resueltos de no-resueltos."""
        tier1 = Tier1Result()
        tier1.stats["total"] = len(ingredients)

        for name in ingredients:
            r = self.classify_ingredient(name)
            if r.resolved_by != "unresolved":
                tier1.resolved[name] = r
                if "ins" in r.resolved_by:
                    tier1.stats["by_ins"] += 1
                elif "safe" in r.resolved_by:
                    tier1.stats["by_safe"] += 1
                else:
                    tier1.stats["by_keyword"] += 1
            else:
                tier1.unresolved.append(name)
                tier1.stats["unresolved"] += 1

        logger.info(
            f"Tier 1: {tier1.stats['total']} ingredientes → "
            f"{len(tier1.resolved)} resueltos, {len(tier1.unresolved)} pendientes"
        )
        return tier1

    # --- Helpers internos ---

    @staticmethod
    def _set_unsafe(result: IngredientResult, restriction: str, reason: str):
        setattr(result, _RESTRICTION_FIELD[restriction], False)
        result.evidence.append(f"Determinista: '{reason}' → no apto {restriction}")

    @staticmethod
    def _set_safe(result: IngredientResult, restriction: str):
        if getattr(result, _RESTRICTION_FIELD[restriction]) is None:
            setattr(result, _RESTRICTION_FIELD[restriction], True)

    @staticmethod
    def _restriction_is_set(result: IngredientResult, restriction: str) -> bool:
        return getattr(result, _RESTRICTION_FIELD[restriction]) is not None

    @staticmethod
    def _is_safe(result: IngredientResult, restriction: str) -> bool:
        return getattr(result, _RESTRICTION_FIELD[restriction]) is True


_RESTRICTION_FIELD = {
    "sin_tacc": "is_tacc_safe",
    "sin_lactosa": "is_lactose_safe",
    "sin_frutos_secos": "is_nut_safe",
    "vegano": "is_vegan_safe",
}


classifier = DeterministicClassifier()
