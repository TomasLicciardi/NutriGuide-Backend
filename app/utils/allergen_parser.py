# app/utils/allergen_parser.py
"""
Parser de alérgenos con comprensión contextual para etiquetas argentinas/LATAM.

Resuelve falsos positivos como:
- "SIN TACC" detectado como que contiene gluten
- "NO CONTIENE LECHE" detectado como que contiene leche
- "Libre de gluten" detectado como que contiene gluten

Prioridades de parsing:
1. Declaraciones positivas (SIN TACC, LIBRE DE, NO CONTIENE) → seguro
2. CONTIENE X → presencia confirmada → no apto
3. PUEDE CONTENER X / ELABORADO EN LÍNEAS → contaminación cruzada → no apto (modo estricto)
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Mapeo de alérgenos a restricciones dietéticas
# ---------------------------------------------------------------------------
ALLERGEN_RESTRICTION_MAP: Dict[str, List[str]] = {
    # Fuentes de gluten (TACC en Argentina)
    "trigo": ["sin_gluten"],
    "avena": ["sin_gluten"],
    "cebada": ["sin_gluten"],
    "centeno": ["sin_gluten"],
    "gluten": ["sin_gluten"],
    "tacc": ["sin_gluten"],

    # Lácteos
    "leche": ["sin_lactosa", "vegano"],
    "lacteo": ["sin_lactosa", "vegano"],
    "lacteos": ["sin_lactosa", "vegano"],

    # Huevo
    "huevo": ["vegano"],
    "huevos": ["vegano"],

    # Pescados y mariscos
    "pescado": ["vegano", "vegetariano"],
    "mariscos": ["vegano", "vegetariano"],
    "crustaceos": ["vegano", "vegetariano"],
    "moluscos": ["vegano", "vegetariano"],

    # Frutos secos y maní
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

    # Informativos (no afectan las 5 restricciones)
    "soja": [],
    "soya": [],
    "sulfitos": [],
    "apio": [],
    "mostaza": [],
    "sesamo": [],
}

# Mapeo de declaraciones positivas a la restricción que certifican como segura
POSITIVE_DECLARATION_MAP: Dict[str, str] = {
    "sin_tacc": "sin_gluten",
    "libre_de_gluten": "sin_gluten",
    "sin_gluten": "sin_gluten",
    "apto_celiacos": "sin_gluten",
    "libre_de_lactosa": "sin_lactosa",
    "sin_lactosa": "sin_lactosa",
    "0_lactosa": "sin_lactosa",
}


@dataclass
class AllergenParseResult:
    """Resultado estructurado del parsing de texto de alérgenos."""
    contiene: List[str] = field(default_factory=list)
    puede_contener: List[str] = field(default_factory=list)
    declaraciones_positivas: List[str] = field(default_factory=list)
    restricciones_afectadas: Dict[str, dict] = field(default_factory=dict)
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Funciones internas
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Elimina acentos y convierte a minúsculas."""
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()


def _extract_positive_declarations(text: str) -> Tuple[List[str], str]:
    """
    Detecta declaraciones positivas (SIN TACC, Libre de gluten, etc.)
    y las elimina del texto para que no generen falsos positivos.
    """
    declarations: List[str] = []
    clean = text

    patterns = [
        (r"sin\s+t\.?\s*a\.?\s*c\.?\s*c\.?",  "sin_tacc"),
        (r"libre\s+de\s+gluten",                "libre_de_gluten"),
        (r"libre\s+de\s+lactosa",               "libre_de_lactosa"),
        (r"sin\s+gluten",                        "sin_gluten"),
        (r"sin\s+lactosa",                       "sin_lactosa"),
        (r"apto\s+(?:para\s+)?celiacos",         "apto_celiacos"),
        (r"0\s*%\s*lactosa",                     "0_lactosa"),
        (r"no\s+contiene\s+[\w\s,y]+",           "no_contiene"),
    ]

    for pattern, decl_type in patterns:
        match = re.search(pattern, clean)
        if match:
            declarations.append(decl_type)
            clean = clean[: match.start()] + " " + clean[match.end() :]

    return declarations, clean


def _parse_allergen_list(raw: str) -> List[str]:
    """
    Descompone un fragmento como 'DERIVADOS DE TRIGO Y DE SOJA' en ['trigo', 'soja'].
    """
    text = raw.strip()

    # "derivados de X" / "derivado de X" → X
    text = re.sub(r"derivados?\s+de\s+", "", text, flags=re.IGNORECASE)

    # Separar por coma, punto y coma, " y ", " e "
    parts = re.split(r"\s*[,;]\s*|\s+y\s+|\s+e\s+", text)

    result: List[str] = []
    for part in parts:
        part = re.sub(r"^de\s+", "", part.strip())
        part = part.strip(" .")
        if part and len(part) > 1:
            result.append(_normalize(part))
    return result


def _map_allergen_to_restrictions(allergen: str) -> List[str]:
    """Mapea un nombre de alérgeno normalizado a las restricciones que afecta."""
    if allergen in ALLERGEN_RESTRICTION_MAP:
        return ALLERGEN_RESTRICTION_MAP[allergen]

    for key, restrictions in ALLERGEN_RESTRICTION_MAP.items():
        if key in allergen or allergen in key:
            return restrictions

    return []


# ---------------------------------------------------------------------------
# Función pública principal
# ---------------------------------------------------------------------------

def parse_allergen_text(raw_text: str) -> AllergenParseResult:
    """
    Parsea el texto de alérgenos de una etiqueta argentina/LATAM.

    Maneja correctamente:
    - "CONTIENE X" → presencia confirmada
    - "PUEDE CONTENER X" → contaminación cruzada
    - "ELABORADO EN LÍNEAS QUE PROCESAN X" → contaminación cruzada
    - "SIN TACC" / "Libre de gluten" / "NO CONTIENE X" → declaración positiva
    - "PARA ARGENTINA: ..." → prefijos por país (se combinan todos)
    """
    result = AllergenParseResult(raw_text=raw_text or "")

    if not raw_text or not raw_text.strip():
        return result

    text = _normalize(raw_text)

    # 1. Extraer y remover declaraciones positivas
    result.declaraciones_positivas, clean = _extract_positive_declarations(text)

    # 2. Remover prefijos de país ("PARA ARGENTINA Y PARAGUAY: ...")
    clean = re.sub(r"para\s+[\w\s]+?:\s*", "", clean)

    # 3. Dividir en segmentos por punto, punto y coma, o guión rodeado de espacios
    segments = re.split(r"[.;]\s*|\s+-\s+", clean)

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        # PUEDE CONTENER / ELABORADO EN LÍNEAS
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

        # CONTIENE (pero no precedido por "PUEDE" ni "NO")
        elif "contiene" in segment:
            match = re.search(r"contiene\s*:?\s*(.+)", segment)
            if match:
                allergens = _parse_allergen_list(match.group(1))
                result.contiene.extend(allergens)

    # 4. Deduplicar preservando orden
    result.contiene = list(dict.fromkeys(result.contiene))
    result.puede_contener = list(dict.fromkeys(result.puede_contener))

    # 5. Mapear alérgenos a restricciones
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
