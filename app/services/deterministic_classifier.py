# app/services/deterministic_classifier.py
"""
Clasificador determinista de ingredientes para restricciones dietéticas.

CAPA 1 del sistema híbrido de NutriGuide. Solo maneja lo que puede resolver
con certeza absoluta, sin IA. Todo lo demás se delega a la cadena inteligente
(DB → embeddings → RAG + Gemini → aprendizaje).

Lo que SÍ resuelve este módulo:
  - Códigos INS/E (datos factuales)
  - Keywords de restricción (leche, huevo, trigo, carne, etc.)
  - Safe compounds (evitar falsos positivos: nuez moscada, maltodextrina, etc.)
  - Base mínima (~15 ingredientes ultra-comunes: agua, sal, azúcar)

Lo que NO resuelve (se delega a la cadena inteligente):
  - Aditivos (colorantes, vitaminas, conservantes, emulsionantes)
  - Ingredientes base poco comunes (frutilla, cúrcuma, cacao, etc.)
  - Nombres técnicos (BHA, TBHQ, eritorbato, etc.)

Prioridades de clasificación del producto:
  1. Ingredientes (keywords) → NO APTO si matchea
  2. Declaraciones positivas (SIN TACC, etc.) → override a APTO
  3. Advertencias de alérgenos (CONTIENE / PUEDE CONTENER) → override final a NO APTO
"""

import re
import unicodedata
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from app.utils.allergen_parser import AllergenParseResult, POSITIVE_DECLARATION_MAP

logger = logging.getLogger(__name__)

ALL_RESTRICTIONS = ["vegano", "vegetariano", "sin_gluten", "sin_lactosa", "sin_frutos_secos"]


# ═══════════════════════════════════════════════════════════════════════════════
# CAPA 1 — Keywords por restricción
# ═══════════════════════════════════════════════════════════════════════════════
# Si un ingrediente normalizado contiene alguna de estas substrings,
# se marca como NO APTO para esa restricción.
# Estas son las ÚNICAS reglas hardcodeadas del sistema.
# ═══════════════════════════════════════════════════════════════════════════════

RESTRICTION_KEYWORDS: Dict[str, List[str]] = {
    "sin_gluten": [
        "trigo", "avena", "cebada", "centeno",
        "gluten", "tacc",
        "malta", "semolina", "semola", "espelta", "kamut",
        "triticale", "farro", "cuscus", "bulgur", "seitan",
        "harina 000",
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
        "leche", "lactosa", "queso", "yogur", "yogurt",
        "mantequilla", "manteca",
        "crema", "nata",
        "suero", "caseinato", "caseina", "lactosuero",
        "requeson", "ricota", "dulce de leche",
        "proteina de leche", "proteinas lacteas",
        "solidos de leche", "grasa de leche",
        "huevo", "albumina", "ovoalbumina", "yema",
        "carne", "pollo", "cerdo", "vacuno", "vacuna", "bovino", "bovina",
        "porcino", "porcina", "ovino", "ovina", "cordero", "pavo",
        "aviar", "primer jugo",
        "jamon", "salchicha", "embutido", "panceta", "tocino",
        "charqui", "bondiola", "chorizo", "morcilla",
        "pescado", "atun", "salmon", "anchoa", "sardina",
        "bacalao", "merluza", "trucha", "surimi",
        "marisco", "camaron", "langosta", "mejillon",
        "calamar", "pulpo",
        "miel", "propoleo", "jalea real", "cera de abeja",
        "gelatina",
        "carmin", "cochinilla",
        "grasa animal", "sebo",
    ],

    "vegetariano": [
        "carne", "pollo", "cerdo", "vacuno", "vacuna", "bovino", "bovina",
        "porcino", "porcina", "ovino", "ovina", "cordero", "pavo",
        "aviar", "primer jugo",
        "jamon", "salchicha", "embutido", "panceta", "tocino",
        "charqui", "bondiola", "chorizo", "morcilla",
        "pescado", "atun", "salmon", "anchoa", "sardina",
        "bacalao", "merluza", "trucha", "surimi",
        "marisco", "camaron", "langosta", "mejillon",
        "calamar", "pulpo",
        "gelatina",
        "grasa animal", "sebo",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# CAPA 2 — Compuestos seguros (evitan falsos positivos CRÍTICOS)
# ═══════════════════════════════════════════════════════════════════════════════

SAFE_COMPOUNDS: Dict[str, List[str]] = {
    "sin_gluten": [
        "maltodextrina",
        "dextrina",
    ],
    "sin_lactosa": [
        "leche de coco",  "leche de almendra", "leche de soja",
        "leche de avena", "leche de arroz",     "leche vegetal",
        "manteca de cacao", "manteca de mani",
        "crema de cacao",   "crema de mani",    "crema de leche de coco",
        "acido lactico",    "lactato",
    ],
    "vegano": [
        "leche de coco",  "leche de almendra", "leche de soja",
        "leche de avena", "leche de arroz",     "leche vegetal",
        "manteca de cacao", "manteca de mani",
        "crema de cacao",   "crema de mani",    "crema de leche de coco",
        "acido lactico",    "lactato",
        "gelatina vegetal", "gelatina de agar", "agar agar",
    ],
    "sin_frutos_secos": [
        "nuez moscada",
        "moscada",
    ],
    "vegetariano": [
        "gelatina vegetal", "gelatina de agar", "agar agar",
    ],
}

UNSAFE_OVERRIDES: Dict[str, List[str]] = {
    "sin_gluten": [
        "maltodextrina de trigo",
        "dextrina de trigo",
        "almidon de trigo",
        "almidon modificado de trigo",
        "gluten de trigo",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# CAPA 3 — Base de datos de códigos INS/E
# ═══════════════════════════════════════════════════════════════════════════════

INS_AFFECTS_RESTRICTIONS: Dict[int, Dict[str, str]] = {
    120:  {"vegano": "carmin/cochinilla (insecto)"},
    441:  {"vegano": "gelatina animal", "vegetariano": "gelatina animal"},
    542:  {"vegano": "fosfato de hueso", "vegetariano": "fosfato de hueso"},
    901:  {"vegano": "cera de abejas"},
    904:  {"vegano": "shellac/goma laca (insecto)"},
    966:  {"sin_lactosa": "lactitol (derivado de lactosa)"},
}

_SAFE_INS_RANGES = [
    (200, 283), (300, 341), (400, 499),
    (500, 580), (620, 635), (950, 969),
]


# ═══════════════════════════════════════════════════════════════════════════════
# CAPA 4 — Base mínima de ingredientes universales
# ═══════════════════════════════════════════════════════════════════════════════
# SOLO los ingredientes que aparecen en >80% de los productos y son
# obviamente seguros. Todo lo demás se resuelve por la cadena inteligente.
# ═══════════════════════════════════════════════════════════════════════════════

ESSENTIAL_SAFE: frozenset = frozenset([
    "agua", "sal", "azucar", "aceite", "aceite de girasol",
    "aceite de oliva", "aceite vegetal", "aceite de palma",
    "aceite de soja", "aceite de maiz",
    "maiz", "arroz", "vinagre",
])


# ═══════════════════════════════════════════════════════════════════════════════
# Clasificación BASE / ADITIVO (solo para display)
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
# Dataclasses de resultado
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class IngredientClassification:
    name: str
    name_normalized: str
    tipo: str                                  # "BASE" o "ADITIVO"
    restrictions_affected: Dict[str, str]      # {restriccion: keyword_que_triggereo}
    status: str = "known"                      # "known" | "unknown" | "needs_ai"
    confidence: float = 0.95
    resolved_by: str = "deterministic"         # "deterministic" | "db" | "embedding" | "rag_gemini" | "default"


@dataclass
class ProductClassification:
    success: bool = True
    restrictions: Dict[str, dict] = field(default_factory=dict)
    classified_ingredients: List[IngredientClassification] = field(default_factory=list)
    unknown_ingredients: List[str] = field(default_factory=list)
    confidence: float = 0.95
    method: str = "deterministic"
    stats: Dict[str, int] = field(default_factory=lambda: {
        "total": 0,
        "by_deterministic": 0,
        "by_ins_code": 0,
        "by_essential_safe": 0,
        "needs_ai": 0,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Clase principal
# ═══════════════════════════════════════════════════════════════════════════════

class DeterministicClassifier:

    @staticmethod
    def _normalize(text: str) -> str:
        nfkd = unicodedata.normalize("NFD", text)
        return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()

    @staticmethod
    def _extract_ins_code(text_normalized: str) -> Optional[int]:
        match = re.search(r"\bins\s*(\d{3,4})\b", text_normalized)
        if match:
            return int(match.group(1))
        match = re.match(r"^e(\d{3,4})[a-z]?$", text_normalized)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _is_ins_in_safe_range(code: int) -> bool:
        return any(lo <= code <= hi for lo, hi in _SAFE_INS_RANGES)

    def classify_base_or_additive(self, ingredient_normalized: str) -> str:
        if self._extract_ins_code(ingredient_normalized) is not None:
            return "ADITIVO"
        prefixes = ["emu", "aci", "aro", "con", "col", "est", "rai", "sec", "hum", "esp"]
        for prefix in prefixes:
            if ingredient_normalized.startswith(prefix + ":") or ingredient_normalized.startswith(prefix + " :"):
                return "ADITIVO"
        if any(kw in ingredient_normalized for kw in _ADDITIVE_KEYWORDS):
            return "ADITIVO"
        if any(p in ingredient_normalized for p in _ADDITIVE_CHEMICAL_PATTERNS):
            return "ADITIVO"
        return "BASE"

    # ── Clasificación de un ingrediente ──────────────────────────────────

    def classify_ingredient(self, ingredient_name: str) -> IngredientClassification:
        norm = self._normalize(ingredient_name)
        tipo = self.classify_base_or_additive(norm)
        affected: Dict[str, str] = {}

        # ── 1. Código INS/E → resolución inmediata ──
        ins_code = self._extract_ins_code(norm)
        if ins_code is not None:
            if ins_code in INS_AFFECTS_RESTRICTIONS:
                for restriction, reason in INS_AFFECTS_RESTRICTIONS[ins_code].items():
                    affected[restriction] = reason
            return IngredientClassification(
                name=ingredient_name, name_normalized=norm, tipo="ADITIVO",
                restrictions_affected=affected, status="known",
                confidence=0.97, resolved_by="ins_code",
            )

        # ── 2. Keywords de restricción + safe compounds ──
        keyword_matched = False
        for restriction in ALL_RESTRICTIONS:
            for pattern in UNSAFE_OVERRIDES.get(restriction, []):
                if pattern in norm:
                    affected[restriction] = pattern
                    keyword_matched = True
                    break
            if restriction in affected:
                continue

            is_safe_compound = False
            for safe in SAFE_COMPOUNDS.get(restriction, []):
                if safe in norm:
                    is_safe_compound = True
                    keyword_matched = True
                    break
            if is_safe_compound:
                continue

            for keyword in RESTRICTION_KEYWORDS.get(restriction, []):
                if keyword in norm:
                    affected[restriction] = keyword
                    keyword_matched = True
                    break

        if keyword_matched:
            return IngredientClassification(
                name=ingredient_name, name_normalized=norm, tipo=tipo,
                restrictions_affected=affected, status="known",
                confidence=0.95, resolved_by="deterministic",
            )

        # ── 3. Base mínima esencial (agua, sal, azúcar...) ──
        if norm in ESSENTIAL_SAFE:
            return IngredientClassification(
                name=ingredient_name, name_normalized=norm, tipo=tipo,
                restrictions_affected={}, status="known",
                confidence=0.95, resolved_by="essential_safe",
            )
        for safe in ESSENTIAL_SAFE:
            if safe in norm and len(safe) >= 4:
                return IngredientClassification(
                    name=ingredient_name, name_normalized=norm, tipo=tipo,
                    restrictions_affected={}, status="known",
                    confidence=0.90, resolved_by="essential_safe",
                )

        # ── 4. No resuelto → necesita cadena inteligente ──
        return IngredientClassification(
            name=ingredient_name, name_normalized=norm, tipo=tipo,
            restrictions_affected={}, status="needs_ai",
            confidence=0.5, resolved_by="pending",
        )

    # ── Clasificación completa de un producto ────────────────────────────

    def classify_product(
        self,
        ingredients: List[str],
        allergen_result: AllergenParseResult,
    ) -> ProductClassification:
        restrictions = {
            r: {"apto": True, "motivo": None} for r in ALL_RESTRICTIONS
        }

        classified: List[IngredientClassification] = []
        unknowns: List[str] = []
        stats = {"total": 0, "by_deterministic": 0, "by_ins_code": 0,
                 "by_essential_safe": 0, "needs_ai": 0}

        for ingredient in ingredients:
            result = self.classify_ingredient(ingredient)
            classified.append(result)
            stats["total"] += 1

            if result.status == "needs_ai":
                unknowns.append(ingredient)
                stats["needs_ai"] += 1
            elif result.resolved_by == "ins_code":
                stats["by_ins_code"] += 1
            elif result.resolved_by == "essential_safe":
                stats["by_essential_safe"] += 1
            else:
                stats["by_deterministic"] += 1

            for restriction, keyword in result.restrictions_affected.items():
                if restrictions[restriction]["apto"]:
                    restrictions[restriction] = {
                        "apto": False,
                        "motivo": f"Contiene {keyword}",
                    }

        for declaration in allergen_result.declaraciones_positivas:
            mapped = POSITIVE_DECLARATION_MAP.get(declaration)
            if mapped and mapped in restrictions:
                restrictions[mapped] = {"apto": True, "motivo": None}

        for restriction, data in allergen_result.restricciones_afectadas.items():
            if restriction in restrictions:
                restrictions[restriction] = {
                    "apto": False,
                    "motivo": data["fuente"],
                }

        confidence = 0.95 if not unknowns else max(0.70, 0.95 - len(unknowns) * 0.03)

        return ProductClassification(
            success=True,
            restrictions=restrictions,
            classified_ingredients=classified,
            unknown_ingredients=unknowns,
            confidence=confidence,
            method="hybrid" if unknowns else "deterministic",
            stats=stats,
        )

    def apply_external_classification(
        self,
        classification: ProductClassification,
        ingredient_name: str,
        external_result: Dict[str, bool],
    ) -> ProductClassification:
        mapping = {
            "dairy":        ["sin_lactosa", "vegano"],
            "egg":          ["vegano"],
            "meat_fish":    ["vegano", "vegetariano"],
            "honey_insect": ["vegano"],
            "gluten":       ["sin_gluten"],
            "nuts":         ["sin_frutos_secos"],
        }

        for category, is_present in external_result.items():
            if is_present and category in mapping:
                for restriction in mapping[category]:
                    if classification.restrictions[restriction]["apto"]:
                        classification.restrictions[restriction] = {
                            "apto": False,
                            "motivo": f"Contiene {ingredient_name} ({category})",
                        }

        if ingredient_name in classification.unknown_ingredients:
            classification.unknown_ingredients.remove(ingredient_name)

        return classification


classifier = DeterministicClassifier()
