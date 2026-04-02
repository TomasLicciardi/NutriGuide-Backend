# app/utils/allergen_parser.py
"""
Parser de alérgenos para etiquetas argentinas/LATAM.
4 restricciones: sin_tacc, sin_lactosa, sin_frutos_secos, vegano.

Prioridades:
1. Declaraciones positivas (SIN TACC, LIBRE DE, NO CONTIENE) -> seguro
2. CONTIENE X -> presencia confirmada -> no apto
3. PUEDE CONTENER X / ELABORADO EN LÍNEAS -> contaminación cruzada -> no apto
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

ALLERGEN_RESTRICTION_MAP: Dict[str, List[str]] = {
    "trigo": ["sin_tacc"],
    "avena": ["sin_tacc"],
    "cebada": ["sin_tacc"],
    "centeno": ["sin_tacc"],
    "gluten": ["sin_tacc"],
    "tacc": ["sin_tacc"],

    "leche": ["sin_lactosa", "vegano"],
    "lacteo": ["sin_lactosa", "vegano"],
    "lacteos": ["sin_lactosa", "vegano"],

    "huevo": ["vegano"],
    "huevos": ["vegano"],

    "pescado": ["vegano"],
    "mariscos": ["vegano"],
    "crustaceos": ["vegano"],
    "moluscos": ["vegano"],

    "mani": ["sin_frutos_secos"],
    "cacahuate": ["sin_frutos_secos"],
    "cacahuete": ["sin_frutos_secos"],
    "almendra": ["sin_frutos_secos"],
    "almendras": ["sin_frutos_secos"],
    "nuez": ["sin_frutos_secos"],
    "nueces": ["sin_frutos_secos"],
    "avellana": ["sin_frutos_secos"],
    "avellanas": ["sin_frutos_secos"],
    "pistacho": ["sin_frutos_secos"],
    "pistachos": ["sin_frutos_secos"],
    "anacardo": ["sin_frutos_secos"],
    "anacardos": ["sin_frutos_secos"],
    "castana": ["sin_frutos_secos"],
    "castanas": ["sin_frutos_secos"],
    "frutos secos": ["sin_frutos_secos"],

    "soja": [],
    "soya": [],
    "sulfitos": [],
    "apio": [],
    "mostaza": [],
    "sesamo": [],
}

POSITIVE_DECLARATION_MAP: Dict[str, str] = {
    "sin_tacc": "sin_tacc",
    "libre_de_gluten": "sin_tacc",
    "sin_gluten": "sin_tacc",
    "apto_celiacos": "sin_tacc",
    "libre_de_lactosa": "sin_lactosa",
    "sin_lactosa": "sin_lactosa",
    "0_lactosa": "sin_lactosa",
}


@dataclass
class AllergenParseResult:
    contiene: List[str] = field(default_factory=list)
    puede_contener: List[str] = field(default_factory=list)
    declaraciones_positivas: List[str] = field(default_factory=list)
    restricciones_afectadas: Dict[str, dict] = field(default_factory=dict)
    raw_text: str = ""


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()


def _extract_positive_declarations(text: str) -> Tuple[List[str], str]:
    declarations: List[str] = []
    clean = text

    patterns = [
        (r"sin\s+t\.?\s*a\.?\s*c\.?\s*c\.?", "sin_tacc"),
        (r"libre\s+de\s+gluten",               "libre_de_gluten"),
        (r"libre\s+de\s+lactosa",              "libre_de_lactosa"),
        (r"sin\s+gluten",                       "sin_gluten"),
        (r"sin\s+lactosa",                      "sin_lactosa"),
        (r"apto\s+(?:para\s+)?celiacos",        "apto_celiacos"),
        (r"0\s*%\s*lactosa",                    "0_lactosa"),
        (r"no\s+contiene\s+[\w\s,y]+",          "no_contiene"),
    ]

    for pattern, decl_type in patterns:
        match = re.search(pattern, clean)
        if match:
            declarations.append(decl_type)
            clean = clean[:match.start()] + " " + clean[match.end():]

    return declarations, clean


def _parse_allergen_list(raw: str) -> List[str]:
    text = raw.strip()
    text = re.sub(r"derivados?\s+de\s+", "", text, flags=re.IGNORECASE)
    parts = re.split(r"\s*[,;]\s*|\s+y\s+|\s+e\s+", text)

    result: List[str] = []
    for part in parts:
        part = re.sub(r"^de\s+", "", part.strip())
        part = part.strip(" .")
        if part and len(part) > 1:
            result.append(_normalize(part))
    return result


def _map_allergen_to_restrictions(allergen: str) -> List[str]:
    if allergen in ALLERGEN_RESTRICTION_MAP:
        return ALLERGEN_RESTRICTION_MAP[allergen]
    for key, restrictions in ALLERGEN_RESTRICTION_MAP.items():
        if key in allergen or allergen in key:
            return restrictions
    return []


def parse_allergen_text(raw_text: str) -> AllergenParseResult:
    """Parsea el texto de alérgenos de una etiqueta argentina/LATAM."""
    result = AllergenParseResult(raw_text=raw_text or "")

    if not raw_text or not raw_text.strip():
        return result

    text = _normalize(raw_text)

    result.declaraciones_positivas, clean = _extract_positive_declarations(text)

    clean = re.sub(r"para\s+[\w\s]+?:\s*", "", clean)

    segments = re.split(r"[.;]\s*|\s+-\s+", clean)

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        if re.search(r"puede\s+contener|elaborado\s+en\s+lineas?|fabricado\s+en.*?procesa", segment):
            match = re.search(
                r"(?:puede\s+contener|"
                r"elaborado\s+en\s+lineas?\s+que\s+(?:tambien\s+)?procesan|"
                r"fabricado\s+en.*?(?:elabora|procesa))"
                r"\s*:?\s*(.+)",
                segment,
            )
            if match:
                allergens = _parse_allergen_list(match.group(1))
                result.puede_contener.extend(allergens)

        elif "contiene" in segment:
            match = re.search(r"contiene\s*:?\s*(.+)", segment)
            if match:
                allergens = _parse_allergen_list(match.group(1))
                result.contiene.extend(allergens)

    result.contiene = list(dict.fromkeys(result.contiene))
    result.puede_contener = list(dict.fromkeys(result.puede_contener))

    restrictions: Dict[str, dict] = {}

    for allergen in result.contiene:
        for restriction in _map_allergen_to_restrictions(allergen):
            if restriction not in restrictions:
                restrictions[restriction] = {
                    "afecta": True,
                    "fuente": f"Contiene {allergen}",
                    "tipo": "contiene",
                }

    for allergen in result.puede_contener:
        for restriction in _map_allergen_to_restrictions(allergen):
            if restriction not in restrictions:
                restrictions[restriction] = {
                    "afecta": True,
                    "fuente": f"Puede contener {allergen}",
                    "tipo": "puede_contener",
                }

    result.restricciones_afectadas = restrictions
    return result
