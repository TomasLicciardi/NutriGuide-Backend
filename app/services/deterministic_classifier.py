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
        # Patrones argentinos expandidos
        "harina enriquecida",  # Siempre es de trigo en Argentina
        "extracto de malta",   # Malta = cebada
        "fideos",  # En Argentina, fideos = harina de trigo salvo indicación contraria
    ],
    "sin_lactosa": [
        "leche", "lactosa", "queso", "yogur", "yogurt",
        "mantequilla", "manteca",
        "crema", "nata",
        "suero", "caseinato", "caseina", "lactosuero",
        "requeson", "ricota", "dulce de leche",
        "proteina de leche", "proteinas lacteas",
        "solidos de leche", "grasa de leche",
        # Expandido para dataset argentino
        "cultivos lacticos", "cultivo lactico",  # Yogures, postres lácteos
        "suero de queso",
        "leche en polvo",
        "leche descremada",
        "leche entera",
    ],
    "sin_frutos_secos": [
        "almendra", "nuez", "avellana", "pistacho",
        "anacardo", "macadamia", "pecan", "castana",
        "mani", "cacahuate", "cacahuete",
        "fruto seco", "frutos secos",
        # Expandido
        "nueces",  # Plural
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
        "cultivos lacticos", "cultivo lactico",
        "suero de queso",
        "leche en polvo",
        "leche descremada",
        "leche entera",
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
        "miel", "propoleo", "jalea real",
        "cera de abeja", "cera de abejas",  # Con y sin plural
        "gelatina",
        "carmin", "cochinilla",
        "grasa animal", "sebo",
        "grasa bovina", "grasa vacuna",
        "colageno", "colageno hidrolizado",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Safe compounds — evitar falsos positivos
# ═══════════════════════════════════════════════════════════════════════════════

SAFE_COMPOUNDS: Dict[str, List[str]] = {
    "sin_tacc": [
        "maltodextrina",
        "dextrina",
        # Almidones que NO son de trigo (cuando se especifica origen)
        "almidon de maiz", "almidon de papa", "almidon de mandioca",
        "almidon de arroz", "almidon de tapioca",
        "fecula de maiz", "fecula de papa", "fecula de mandioca",
        "almidon modificado de maiz",
        # Harinas sin gluten
        "harina de maiz", "harina de arroz", "harina de mandioca",
    ],
    "sin_lactosa": [
        "leche de coco", "leche de almendra", "leche de soja",
        "leche de avena", "leche de arroz", "leche vegetal",
        "manteca de cacao", "manteca de mani",
        "crema de cacao", "crema de mani", "crema de leche de coco",
        "acido lactico", "lactato",
        # Compuestos con "lact" que NO son lactosa
        "estearoil lactilato",  # INS 481i — emulsionante sintético
        "lactilato de sodio",
    ],
    "vegano": [
        "leche de coco", "leche de almendra", "leche de soja",
        "leche de avena", "leche de arroz", "leche vegetal",
        "manteca de cacao", "manteca de mani",
        "crema de cacao", "crema de mani", "crema de leche de coco",
        "acido lactico", "lactato",
        "gelatina vegetal", "gelatina de agar", "agar agar",
        # Compuestos con "lact" que NO son de origen animal
        "estearoil lactilato",
        "lactilato de sodio",
        # Aceites/grasas de nombre engañoso
        "aceite de palma",  # Vegetal
        "aceite vegetal",
        "grasa vegetal",
        # Cera vegetal (no confundir con cera de abejas)
        "cera de carnauba",
    ],
    "sin_frutos_secos": [
        "nuez moscada",
        "moscada",
        # Coco NO es fruto seco (es drupa)
        "coco", "leche de coco", "aceite de coco",
    ],
}

UNSAFE_OVERRIDES: Dict[str, List[str]] = {
    "sin_tacc": [
        "maltodextrina de trigo",
        "dextrina de trigo",
        "almidon de trigo",
        "almidon modificado de trigo",
        "gluten de trigo",
        "fibra de trigo",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Códigos INS/E que afectan restricciones
# ═══════════════════════════════════════════════════════════════════════════════

INS_AFFECTS: Dict[int, Dict[str, str]] = {
    # Colorantes de origen animal
    120: {"vegano": "carmín/cochinilla (origen insecto)"},
    # Gelatina
    441: {"vegano": "gelatina (origen animal)"},
    # Derivados óseos
    542: {"vegano": "fosfato de hueso (origen animal)"},
    # Ceras animales
    901: {"vegano": "cera de abejas"},
    904: {"vegano": "shellac/goma laca (origen insecto)"},
    # Derivados de lactosa
    966: {"sin_lactosa": "lactitol (derivado de lactosa)"},
}

# Códigos INS que son SEGUROS para TODAS las restricciones
# (aditivos sintéticos/vegetales/minerales comunes en etiquetas ARG)
_SAFE_INS_CODES: frozenset = frozenset([
    # Conservantes
    200, 202, 211, 250, 251, 270, 282,
    # Antioxidantes
    300, 316, 320, 321,
    # Reguladores / acidulantes
    330, 331, 341,
    # Espesantes / estabilizantes / emulsionantes
    400, 407, 410, 412, 415, 422, 440, 452, 460, 461, 471, 481,
    # Leudantes / gasificantes / antiaglutinantes
    500, 503, 516, 536, 551,
    # Resaltadores de sabor
    621, 631, 627,
    # Colorantes vegetales/sintéticos comunes
    100, 101, 102, 110, 129, 133, 150, 160, 171,
    # Edulcorantes
    950, 951, 952, 955, 960,
    # Mejoradores
    920, 928,
    # Agentes de recubrimiento vegetales
    903,  # Cera de carnauba (vegetal)
    # Secuestrantes
    385,
])

_SAFE_INS_RANGES = [
    (200, 283), (300, 341), (400, 499),
    (500, 580), (620, 635), (950, 969),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Ingredientes universalmente seguros
# ═══════════════════════════════════════════════════════════════════════════════

ESSENTIAL_SAFE: frozenset = frozenset([
    # Bases
    "agua", "sal", "azucar", "vinagre",
    # Aceites vegetales
    "aceite", "aceite de girasol", "aceite de girasol alto oleico",
    "aceite de oliva", "aceite vegetal", "aceite de palma",
    "aceite de soja", "aceite de maiz", "aceite de canola",
    "aceite vegetal de palma", "aceite vegetal de palma y canola",
    "aceite vegetal fraccionado",
    # Cereales sin gluten
    "maiz", "arroz", "harina de maiz",
    # Almidones / féculas
    "almidon de maiz", "almidon de papa", "almidon de mandioca",
    "almidon modificado", "almidon modificado de maiz",
    "fecula de maiz", "fecula de papa", "fecula de mandioca",
    # Azúcares y edulcorantes
    "jarabe de glucosa", "jarabe de maiz", "jarabe de maiz de alta fructosa",
    "maltodextrina", "dextrosa", "fructosa",
    # Verduras y frutas
    "tomate", "cebolla", "ajo", "zanahoria", "zapallo",
    "perejil", "apio", "pimiento", "papa",
    "manzana", "naranja", "limon", "durazno", "frutilla",
    "pasas de uva", "fruta escurrida", "pulpa de durazno",
    "jugo de tomates", "tomate pelado", "extracto de tomate",
    "concentrado doble de tomate", "jugo concentrado de limon",
    "jugo concentrado de naranja",
    # Especias y hierbas (todas veganas, sin gluten, sin lactosa)
    "especias", "pimienta", "pimienta negra", "pimienta roja",
    "curcuma", "canela", "comino", "oregano", "tomillo",
    "romero", "laurel", "jengibre", "clavo de olor", "aji molido",
    "canela en polvo", "laurel en polvo", "ajo en polvo",
    "cebolla en polvo",
    # Cacao (sin leche)
    "cacao", "cacao en polvo", "cacao alcalinizado",
    # Fermentos y levaduras
    "levadura", "extracto de levadura",
    # Vinagres
    "vinagre de alcohol", "vinagre de vino", "vinagre de manzana",
    # Tubérculos y raíces
    "mandioca", "tapioca",
    # Otros ingredientes base comunes
    "poroto de soja", "proteina de soja", "proteina de maiz",
    "hidrolizado de proteina de maiz",
    "mostaza blanca", "semilla de apio",
    "cloruro de potasio", "cloruro de sodio",
    "vainilla", "oleomargarina",
    # ═══════════════════════════════════════════════════════════════
    # Aditivos alimentarios comunes — seguros para las 4 restricciones
    # Identificados por evaluación formal contra ground truth (n=44)
    # ═══════════════════════════════════════════════════════════════
    # Acidulantes / reguladores de acidez
    "acido citrico", "acido lactico", "acido fosforico",
    "acido sorbico", "acido ascorbico",
    # Conservantes
    "sorbato de potasio", "benzoato de sodio",
    "propionato de calcio", "nitrito de sodio", "nitrato de sodio",
    "eritorbato de sodio",
    # Leudantes / gasificantes
    "bicarbonato de sodio", "bicarbonato de amonio",
    "pirofosfato acido de sodio",
    # Espesantes / estabilizantes / gelificantes
    "goma xantica", "goma guar", "goma garrofin",
    "carragenina", "pectina", "polifosfatos",
    # Emulsionantes
    "lecitina de soja", "mono y digliceridos de acidos grasos",
    # Antioxidantes
    "bha", "bht", "tbhq",
    # Secuestrantes
    "edta disodico calcico",
    # Colorantes vegetales / sinteticos
    "tartrazina", "amarillo ocaso", "amarillo ocaso fcf",
    "azul brillante fcf", "rojo allura ac",
    "caramelo", "caramelo iii", "caramelo iv",
    "annatto", "rocu", "clorofila",
    "dioxido de titanio",
    # Edulcorantes
    "aspartamo", "acesulfame k", "sucralosa",
    "ciclamato de sodio", "glicosidos de esteviol",
    # Resaltadores de sabor
    "glutamato monosodico", "glutamato de sodio",
    "inosinato disodico", "inosinato de sodio",
    "guanilato disodico",
    # Antiaglutinantes
    "dioxido de silicio", "fosfato tricalcico",
    # Aromatizantes (genéricos — sin origen animal)
    "aromatizante", "aromatizantes", "aromatizantes naturales",
    "aromatizantes artificiales", "aromatizante humo",
    "aromatizante identico al natural",
    "aromatizante artificial a chocolate",
    "aromatizante natural a mostaza",
    "saborizante natural, identico al natural y artificial",
    # Vitaminas y minerales
    "vitamina a", "vitamina b1", "vitamina b2", "vitamina b6",
    "vitamina b9", "vitamina b12", "vitamina c", "vitamina d",
    "vitaminas y minerales", "acido folico",
    "tiamina", "riboflavina", "niacina", "nicotinamida",
    "fumarato ferroso", "sulfato ferroso", "sulfato de zinc",
    "oxido de zinc", "pirofosfato ferrico", "hierro", "zinc",
    "yodato de potasio",
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
        m = re.search(r"\bins\s*(\d{3,4})[a-z]*\b", text_normalized)
        if m:
            return int(m.group(1))
        m = re.match(r"^e(\d{3,4})[a-z]*$", text_normalized)
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

            if ins_code in _SAFE_INS_CODES or any(lo <= ins_code <= hi for lo, hi in _SAFE_INS_RANGES) or ins_code in INS_AFFECTS:
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
