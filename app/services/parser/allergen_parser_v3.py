# app/services/parser/allergen_parser_v3.py
"""
Parser del texto de alérgenos — pipeline v3.

Extrae de la sección "CONTIENE / PUEDE CONTENER / declaraciones positivas"
una ProductLegalDeclaration con sets canónicos de alérgenos.

Esta es la fuente de mayor autoridad del sistema (CAA Cap. XVIII Art. 1383
establece la responsabilidad legal del fabricante por estas declaraciones).

NO confundir con app.utils.allergen_parser (parser del sistema viejo).
"""

import re
import unicodedata
from typing import Set

from app.services.ingredient_facts import (
    ALLERGEN_BARLEY,
    ALLERGEN_DAIRY,
    ALLERGEN_EGG,
    ALLERGEN_FISH,
    ALLERGEN_GLUTEN,
    ALLERGEN_HONEY,
    ALLERGEN_LACTOSE,
    ALLERGEN_MILK,
    ALLERGEN_OATS,
    ALLERGEN_PEANUT,
    ALLERGEN_RYE,
    ALLERGEN_SESAME,
    ALLERGEN_SHELLFISH,
    ALLERGEN_SOY,
    ALLERGEN_SULFITES,
    ALLERGEN_TREE_NUT,
    ALLERGEN_WHEAT,
    ProductLegalDeclaration,
)


# ═══════════════════════════════════════════════════════════════════════════
# Mapeo texto literal → tag canónico
# ═══════════════════════════════════════════════════════════════════════════

# Las claves se comparan sin acentos y en minúsculas.
_ALLERGEN_KEYWORDS = {
    # Gluten / cereales
    "gluten": ALLERGEN_GLUTEN,
    "trigo": ALLERGEN_WHEAT,
    "derivados de trigo": ALLERGEN_WHEAT,
    "derivado de trigo": ALLERGEN_WHEAT,
    "harina de trigo": ALLERGEN_WHEAT,
    "cebada": ALLERGEN_BARLEY,
    "derivados de cebada": ALLERGEN_BARLEY,
    "centeno": ALLERGEN_RYE,
    "derivados de centeno": ALLERGEN_RYE,
    "avena": ALLERGEN_OATS,
    "derivados de avena": ALLERGEN_OATS,

    # Lácteos
    "leche": ALLERGEN_MILK,
    "derivados de leche": ALLERGEN_MILK,
    "derivado de leche": ALLERGEN_MILK,
    "lactosa": ALLERGEN_LACTOSE,
    "lacteos": ALLERGEN_DAIRY,
    "lácteos": ALLERGEN_DAIRY,
    "suero": ALLERGEN_DAIRY,
    "caseina": ALLERGEN_DAIRY,
    "caseína": ALLERGEN_DAIRY,

    # Frutos secos
    "frutos secos": ALLERGEN_TREE_NUT,
    "frutos secos de cascara": ALLERGEN_TREE_NUT,
    "frutos secos de cáscara": ALLERGEN_TREE_NUT,
    "almendra": ALLERGEN_TREE_NUT,
    "almendras": ALLERGEN_TREE_NUT,
    "nuez": ALLERGEN_TREE_NUT,
    "nueces": ALLERGEN_TREE_NUT,
    "avellana": ALLERGEN_TREE_NUT,
    "avellanas": ALLERGEN_TREE_NUT,
    "castaña": ALLERGEN_TREE_NUT,
    "castañas": ALLERGEN_TREE_NUT,
    "castaña de caju": ALLERGEN_TREE_NUT,
    "castañas de caju": ALLERGEN_TREE_NUT,
    "castaña de cajú": ALLERGEN_TREE_NUT,
    "castañas de cajú": ALLERGEN_TREE_NUT,
    "pistacho": ALLERGEN_TREE_NUT,
    "pistachos": ALLERGEN_TREE_NUT,
    "pecan": ALLERGEN_TREE_NUT,
    "pecán": ALLERGEN_TREE_NUT,
    "macadamia": ALLERGEN_TREE_NUT,
    "mani": ALLERGEN_PEANUT,
    "maní": ALLERGEN_PEANUT,
    "cacahuete": ALLERGEN_PEANUT,

    # Soja
    "soja": ALLERGEN_SOY,
    "soya": ALLERGEN_SOY,
    "derivados de soja": ALLERGEN_SOY,
    "derivado de soja": ALLERGEN_SOY,

    # Huevo
    "huevo": ALLERGEN_EGG,
    "huevos": ALLERGEN_EGG,
    "derivados de huevo": ALLERGEN_EGG,

    # Pescado / mariscos
    "pescado": ALLERGEN_FISH,
    "pescados": ALLERGEN_FISH,
    "mariscos": ALLERGEN_SHELLFISH,
    "crustaceos": ALLERGEN_SHELLFISH,
    "crustáceos": ALLERGEN_SHELLFISH,
    "moluscos": ALLERGEN_SHELLFISH,

    # Sésamo
    "sesamo": ALLERGEN_SESAME,
    "sésamo": ALLERGEN_SESAME,
    "ajonjoli": ALLERGEN_SESAME,
    "ajonjolí": ALLERGEN_SESAME,

    # Sulfitos
    "sulfitos": ALLERGEN_SULFITES,
    "metabisulfitos": ALLERGEN_SULFITES,
    "anhidrido sulfuroso": ALLERGEN_SULFITES,
    "anhídrido sulfuroso": ALLERGEN_SULFITES,

    # Apio
    "apio": "celery",

    # Mostaza
    "mostaza": "mustard",

    # Miel (relevante para vegano)
    "miel": ALLERGEN_HONEY,

    # Tartrazina (no es alérgeno crítico, pero se declara)
    "tartrazina": "tartrazine",
    "fenilalanina": "phenylalanine",
}


# ═══════════════════════════════════════════════════════════════════════════
# Declaraciones positivas
# ═══════════════════════════════════════════════════════════════════════════

_POSITIVE_PATTERNS = {
    "sin_tacc": [
        re.compile(r"\bsin\s+t\.?a\.?c\.?c\.?\b", re.IGNORECASE),
        re.compile(r"\bsin\s+gluten\b", re.IGNORECASE),
        re.compile(r"\blibre\s+de\s+gluten\b", re.IGNORECASE),
        re.compile(r"\bgluten[\s-]*free\b", re.IGNORECASE),
        re.compile(r"\bno\s+contiene\s+t\.?a\.?c\.?c\.?\b", re.IGNORECASE),
        re.compile(r"\bno\s+contiene\s+gluten\b", re.IGNORECASE),
        re.compile(r"\bapto\s+(?:para\s+)?cel[ií]acos?\b", re.IGNORECASE),
    ],
    "sin_lactosa": [
        re.compile(r"\bsin\s+lactosa\b", re.IGNORECASE),
        re.compile(r"\bdeslactosado\b", re.IGNORECASE),
        re.compile(r"\b0\s*%?\s*lactosa\b", re.IGNORECASE),
        re.compile(r"\bno\s+contiene\s+lactosa\b", re.IGNORECASE),
        re.compile(r"\blibre\s+de\s+lactosa\b", re.IGNORECASE),
        re.compile(r"\blactose[\s-]*free\b", re.IGNORECASE),
    ],
    "sin_frutos_secos": [
        re.compile(r"\bsin\s+frutos\s+secos\b", re.IGNORECASE),
        re.compile(r"\blibre\s+de\s+frutos\s+secos\b", re.IGNORECASE),
        re.compile(r"\bno\s+contiene\s+frutos\s+secos\b", re.IGNORECASE),
        re.compile(r"\bsin\s+nueces\b", re.IGNORECASE),
        re.compile(r"\bsin\s+man[ií]\b", re.IGNORECASE),
        re.compile(r"\bno\s+contiene\s+man[ií]\b", re.IGNORECASE),
        re.compile(r"\bnut[\s-]*free\b", re.IGNORECASE),
        re.compile(r"\bpeanut[\s-]*free\b", re.IGNORECASE),
    ],
    "vegano": [
        re.compile(r"\bvegano\b", re.IGNORECASE),
        re.compile(r"\bvegana\b", re.IGNORECASE),
        re.compile(r"\bapto\s+(?:para\s+)?veganos?\b", re.IGNORECASE),
        re.compile(r"\b100\s*%?\s*vegetal\b", re.IGNORECASE),
        re.compile(r"\b100\s*%?\s*plant[\s-]*based\b", re.IGNORECASE),
        re.compile(r"\bsin\s+ingredientes\s+(?:de\s+)?origen\s+animal\b", re.IGNORECASE),
        re.compile(r"\bno\s+contiene\s+ingredientes\s+(?:de\s+)?origen\s+animal\b", re.IGNORECASE),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# Patrones de bloque CONTIENE / PUEDE CONTENER
# ═══════════════════════════════════════════════════════════════════════════

_RE_CONTAINS_BLOCK = re.compile(
    r"\bcontiene\s*:?\s*([^.]+?)(?=\s*(?:puede\s+contener|fenilcetonúricos|para\s+|elaborado|libre\s+de|sin\s+|$|\.))",
    re.IGNORECASE,
)
_RE_MAY_CONTAIN_BLOCK = re.compile(
    r"\bpuede(?:n)?\s+contener\s*:?\s*([^.]+?)(?=\s*(?:contiene|fenilcetonúricos|para\s+|elaborado|libre\s+de|sin\s+|$|\.))",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════════════
_RE_SHARED_LINE_BLOCK = re.compile(
    r"\belaborad[oa]s?\s+en\s+lineas?\s+que\s+"
    r"(?:tambien\s+)?procesa(?:n)?\s+([^.]+)",
    re.IGNORECASE,
)


# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def _normalize_for_lookup(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _extract_allergen_tokens(block_text: str) -> Set[str]:
    """
    De un bloque tipo "TRIGO Y SOJA, AVENA" extrae el set de tags canónicos.
    """
    text = block_text.replace(".", " ").replace(",", " , ")
    text = re.sub(r"\s+y\s+", " , ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+e\s+", " , ", text, flags=re.IGNORECASE)

    raw_tokens = [t.strip(" .,;:") for t in text.split(",")]

    found: Set[str] = set()

    for raw in raw_tokens:
        if not raw:
            continue
        norm = _normalize_for_lookup(raw)
        norm_no_acc = _strip_accents(norm)

        if norm in _ALLERGEN_KEYWORDS:
            found.add(_ALLERGEN_KEYWORDS[norm])
            continue

        for keyword, tag in _ALLERGEN_KEYWORDS.items():
            if _strip_accents(keyword) == norm_no_acc:
                found.add(tag)
                break
        else:
            for keyword, tag in _ALLERGEN_KEYWORDS.items():
                kw_no_acc = _strip_accents(keyword)
                if kw_no_acc and kw_no_acc in norm_no_acc:
                    found.add(tag)
                    break

    return found


def _expand_to_implied_allergens(allergens: Set[str]) -> Set[str]:
    """
    Expande tags implícitos. Ej: si declara WHEAT, también implica GLUTEN.
    """
    expanded = set(allergens)
    if any(a in expanded for a in (ALLERGEN_WHEAT, ALLERGEN_BARLEY, ALLERGEN_RYE, ALLERGEN_OATS)):
        expanded.add(ALLERGEN_GLUTEN)
    if ALLERGEN_MILK in expanded or ALLERGEN_DAIRY in expanded or ALLERGEN_LACTOSE in expanded:
        expanded.update({ALLERGEN_MILK, ALLERGEN_LACTOSE, ALLERGEN_DAIRY})
    return expanded


# ═══════════════════════════════════════════════════════════════════════════
# Parser principal
# ═══════════════════════════════════════════════════════════════════════════


def parse_allergen_declaration(text: str) -> ProductLegalDeclaration:
    """Parsea el texto literal de alérgenos en una ProductLegalDeclaration."""
    declaration = ProductLegalDeclaration(raw_text=text or "")

    if not text:
        return declaration

    text_norm = re.sub(r"\s+", " ", text.strip())

    # Detectar claims positivas PRIMERO sobre el texto original. Patterns como
    # "NO CONTIENE TACC" o "LIBRE DE LACTOSA" se buscan acá; al hacerlo antes
    # del blanqueo del paso siguiente preservamos sus matches.
    for restriction, patterns in _POSITIVE_PATTERNS.items():
        for pat in patterns:
            if pat.search(text_norm):
                declaration.positive_claims.add(restriction)
                break

    # Neutralizar "NO CONTIENE X" antes de buscar bloques CONTIENE para evitar
    # que el regex `_RE_CONTAINS_BLOCK` matchee la palabra "contiene" cuando
    # está negada. Sin esto, "NO CONTIENE TACC" se interpretaría como "CONTIENE
    # TACC" (falso positivo grave).
    text_for_blocks = re.sub(
        r"\bno\s+contiene\b", "exento de", text_norm, flags=re.IGNORECASE
    )
    text_for_blocks_no_acc = _strip_accents(text_for_blocks)

    contains_set: Set[str] = set()
    for m in _RE_CONTAINS_BLOCK.finditer(text_for_blocks):
        block = m.group(1)
        contains_set |= _extract_allergen_tokens(block)

    may_contain_set: Set[str] = set()
    for m in _RE_MAY_CONTAIN_BLOCK.finditer(text_for_blocks):
        block = m.group(1)
        may_contain_set |= _extract_allergen_tokens(block)
    for m in _RE_SHARED_LINE_BLOCK.finditer(text_for_blocks_no_acc):
        block = m.group(1)
        may_contain_set |= _extract_allergen_tokens(block)

    declaration.contains = _expand_to_implied_allergens(contains_set)
    declaration.may_contain = _expand_to_implied_allergens(may_contain_set) - declaration.contains

    return declaration
