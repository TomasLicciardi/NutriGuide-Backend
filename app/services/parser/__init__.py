# app/services/parser/__init__.py
"""
Parser estructural argentino — Fase 2 del pipeline v3.

Convierte el texto crudo del OCR de Gemini en tokens tipados:
  - Ingredient (con función, INS code opcional)
  - FlavoringAdditive (aromatizante con target sensorial separado)
  - ProductLegalDeclaration (CONTIENE / PUEDE CONTENER / claims)

Diseñado para etiquetas argentinas. Reconoce:
  - Abreviaturas (EMU, ACI, ARO, RAI, EST, COL, RES, SEC, CON, ANT, HUM, GAS, ESP, EDU)
  - Bloque Ley 25.630 (harina enriquecida)
  - Códigos INS con sufijos (INS 500ii, INS 341iii)
  - Patrón aromatizante: (aromatizante|saborizante) [calificador] (a|de|sabor) TARGET
  - Función prefijada: "Acidulante: ácido cítrico"
  - Sub-ingredientes anidados con paréntesis

La gramática formal está documentada en grammar.txt (referencia para tesis).
"""

from app.services.parser.ingredient_parser import (
    ParsedIngredient,
    parse_ingredient_list,
)
from app.services.parser.allergen_parser_v3 import (
    parse_allergen_declaration,
)

__all__ = [
    "ParsedIngredient",
    "parse_ingredient_list",
    "parse_allergen_declaration",
]
