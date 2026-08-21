"""
Explicaciones legibles para nombres técnicos de ingredientes.

Cuando un veredicto bloquea una restricción, queremos mostrar al usuario
*qué* ingrediente concreto la disparó y *por qué* (ej. "Albúmina" → "proteína
de la clara de huevo"). Esto da contexto educativo sin que el usuario tenga
que conocer terminología técnica.

Estrategia de lookup (en orden):
  1. Diccionario curado por substring sobre el nombre normalizado.
  2. description_es del IngredientFacts (si está en el KB).
  3. Fallback genérico derivado de los allergens canónicos.

El diccionario se mantiene corto y enfocado en nombres técnicos que un
usuario promedio NO reconocería como derivado de un alérgeno.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.ingredient_facts import IngredientFacts


# ═══════════════════════════════════════════════════════════════════════════
# Diccionario curado
# ═══════════════════════════════════════════════════════════════════════════
#
# Claves: substring sin acentos, minúsculas. El match es por "contains" sobre
# el nombre normalizado del ingrediente — así una sola entrada "caseina"
# cubre "Caseína", "Caseinato de sodio", "Caseinatos lácteos", etc.
#
# Solo entran nombres técnicos cuya conexión con el alérgeno NO es obvia.
# "Leche", "huevo", "almendra" no necesitan explicación.

_CURATED_EXPLANATIONS: dict[str, str] = {
    # ── Lácteos / derivados de leche ──
    "lactosuero": "suero líquido residual de la fabricación de quesos; deriva de la leche",
    "suero de leche": "líquido que queda al cuajar la leche; contiene lactosa",
    "suero lacteo": "derivado líquido de la leche",
    "caseina": "proteína principal de la leche",
    "caseinato": "sal de caseína (proteína láctea)",
    "lactoalbumina": "proteína del suero de leche",
    "lactoglobulina": "proteína del suero de leche",
    "lactitol": "edulcorante derivado de la lactosa",
    "ghee": "grasa pura de leche clarificada",
    "manteca": "grasa derivada de la leche",
    "mantequilla": "grasa derivada de la leche",
    "ricotta": "queso fresco italiano (lácteo)",
    "kefir": "leche fermentada",
    "cuajada": "leche coagulada",
    "nata": "componente graso de la leche",
    "buttermilk": "suero ácido de mantequilla (lácteo)",
    # cubre también "oleomargarina" por substring
    "margarina": "grasa untable de aceites vegetales; en Argentina suele incluir derivados lácteos (suero de leche)",

    # ── Huevo ──
    "albumina": "proteína de la clara de huevo",
    "ovoalbumina": "principal proteína de la clara de huevo",
    "ovomucina": "proteína de la clara de huevo",
    "globulina": "proteína de la clara de huevo",
    "lisozima": "enzima extraída de la clara de huevo",
    "lecitina de huevo": "emulsionante extraído de la yema",
    "yema": "componente del huevo",
    "clara": "componente del huevo",

    # ── Gluten / cereales con TACC ──
    "semola": "harina gruesa de trigo (contiene gluten)",
    "espelta": "variedad ancestral de trigo (contiene gluten)",
    "kamut": "variedad de trigo (contiene gluten)",
    "triticale": "híbrido de trigo y centeno (contiene gluten)",
    "malta": "cebada germinada (contiene gluten)",
    "extracto de malta": "derivado de cebada germinada (contiene gluten)",
    "couscous": "trigo sémola (contiene gluten)",
    "cuscus": "trigo sémola (contiene gluten)",
    "bulgur": "trigo partido (contiene gluten)",
    "seitan": "gluten puro de trigo",
    "farro": "variedad de trigo (contiene gluten)",

    # ── Frutos secos / maní (nombres menos comunes) ──
    "anacardo": "fruto seco (castaña de cajú)",
    "castana de caju": "fruto seco",
    "pinones": "fruto seco (semilla del pino)",
    "macadamia": "fruto seco",
    "pecan": "fruto seco",
    # El maní es una LEGUMBRE (no un fruto seco), pero el CAA lo declara como
    # alérgeno junto a los frutos secos. Explicación honesta para el usuario.
    "mani": "legumbre; se agrupa con los frutos secos por ser alérgeno de declaración obligatoria",

    # ── Origen animal no obvio ──
    "gelatina": "proteína extraída de huesos y piel animal",
    "colageno": "proteína animal de huesos y tejido conectivo",
    "elastina": "proteína animal del tejido conectivo",
    "queratina": "proteína animal (pelo, plumas, uñas)",
    "carmin": "colorante rojo extraído de la cochinilla (insecto)",
    "acido carminico": "colorante de origen animal (cochinilla)",
    "cochinilla": "colorante extraído de insectos",
    "e120": "colorante rojo de cochinilla (origen animal)",
    "shellac": "resina secretada por insectos (laca)",
    "goma laca": "resina secretada por insectos (laca), usada como agente de brillo",
    "e904": "resina de origen animal (laca)",
    "sebo": "grasa de origen animal",
    "manteca de cerdo": "grasa de cerdo",
    "grasa animal": "ingrediente de origen animal",
    "primer jugo": "jugo concentrado de carne bovina (origen animal)",
    "anchoa": "pez pequeño (origen animal)",
    "isinglass": "gelatina extraída de vejiga de pescado",

    # ── Sésamo (nombres no obvios) ──
    "tahini": "pasta de sésamo",
    "tahine": "pasta de sésamo",
    "ajonjoli": "semilla de sésamo",

    # ── Sulfitos (E220-E228) ──
    "metabisulfito": "conservante a base de sulfitos",
    "bisulfito": "conservante a base de sulfitos",
    "anhidrido sulfuroso": "conservante a base de sulfitos",

    # ── Soja (nombres técnicos) ──
    "lecitina de soja": "emulsionante derivado de la soja",
    "edamame": "vainas de soja jóvenes",
    "tempeh": "soja fermentada",

    # ── Lácteos adicionales (nombres técnicos) ──
    "grasa butirica": "grasa de la leche (materia grasa láctea)",
    "proteina de suero": "proteína del suero de la leche",
    "solidos de leche": "componentes sólidos de la leche",
    "suero dulce": "derivado líquido de la leche",

    # ── Origen animal no obvio (adicionales) ──
    "condroitina": "sustancia extraída del cartílago animal",
    "l-cisteina": "aminoácido usado en panadería, tradicionalmente de origen animal (pelo/plumas)",
    "cisteina": "aminoácido acondicionador de masa, tradicionalmente de origen animal",

    # ── Gluten (nombres técnicos adicionales) ──
    "gluten de trigo": "gluten puro extraído del trigo",
    "proteina de trigo": "proteína de trigo (contiene gluten)",
    "jarabe de malta": "jarabe de cebada germinada (contiene gluten)",
    "cebada malteada": "cebada germinada (contiene gluten)",

    # ── Frutos secos (nombres técnicos adicionales) ──
    "gianduja": "pasta de avellanas y cacao (contiene fruto seco)",
    "mazapan": "pasta de almendras (fruto seco)",
    "nuez de brasil": "fruto seco (castaña de pará)",
    "nuez de para": "fruto seco (castaña de pará)",
}


# ═══════════════════════════════════════════════════════════════════════════
# Fallbacks genéricos por allergen canónico
# ═══════════════════════════════════════════════════════════════════════════

_GENERIC_BY_ALLERGEN: dict[str, str] = {
    "gluten": "contiene gluten",
    "wheat": "derivado de trigo (contiene gluten)",
    "barley": "derivado de cebada (contiene gluten)",
    "rye": "derivado de centeno (contiene gluten)",
    "oats": "derivado de avena (puede contener gluten)",
    "milk": "derivado lácteo",
    "lactose": "contiene lactosa",
    "dairy": "derivado lácteo",
    "tree-nut": "fruto seco",
    "peanut": "derivado de maní",
    "soy": "derivado de soja",
    "egg": "derivado del huevo",
    "fish": "ingrediente de pescado",
    "shellfish": "ingrediente de marisco",
    "sesame": "derivado de sésamo",
    "sulfites": "contiene sulfitos",
    "honey": "miel (origen animal)",
}


# ═══════════════════════════════════════════════════════════════════════════
# API pública
# ═══════════════════════════════════════════════════════════════════════════


def _normalize(text: str) -> str:
    """Minúsculas + sin acentos, para match insensible a tildes."""
    text = text.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if unicodedata.category(c) != "Mn"
    )


def explain_ingredient(facts: "IngredientFacts") -> str:
    """
    Devuelve una explicación corta del ingrediente, optimizada para mostrar
    al usuario final junto al nombre técnico.

    Orden de preferencia:
      1. Diccionario curado (substring match sobre name_es normalizado).
      2. description_es del KB si está cargada.
      3. Texto genérico basado en el primer allergen canónico del ingrediente.
      4. Cadena vacía si no hay información (el caller decide qué hacer).
    """
    normalized = _normalize(facts.name_es)

    for key, explanation in _CURATED_EXPLANATIONS.items():
        if key in normalized:
            return explanation

    if facts.description_es:
        return facts.description_es.strip()

    for allergen in sorted(facts.allergens):
        if allergen in _GENERIC_BY_ALLERGEN:
            return _GENERIC_BY_ALLERGEN[allergen]

    # Último fallback: triggers de vegano que solo tienen origin=animal
    # (sin allergen tag), ej. "grasa bovina".
    if getattr(facts.origin, "value", None) == "animal":
        return "ingrediente de origen animal"

    # Nunca devolvemos cadena vacía: el contrato garantiza texto no vacío para
    # que la UI no muestre una tarjeta en blanco. El front tiene su propio
    # guard (defensa en profundidad), pero el backend es la fuente de verdad.
    return "sin información adicional disponible"
