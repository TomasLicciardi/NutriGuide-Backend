# app/services/parser/ingredient_parser.py
"""
Parser estructural de listas de ingredientes argentinas.

Implementa el reconocimiento de patrones documentado en grammar.txt mediante
pattern matching tolerante (regex). El enfoque pragmático sobre Lark se
justifica por la variabilidad del OCR: caracteres faltantes, espacios extra,
mayúsculas/minúsculas mezcladas. La gramática formal queda como referencia
de la tesis; el parser real prioriza robustez.

Output: List[ParsedIngredient]
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.services.ingredient_facts import FlavoringType


# ═══════════════════════════════════════════════════════════════════════════
# Tipos de output
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ParsedIngredient:
    """Token tipado producido por el parser, antes del enrichment."""

    name: str
    raw_text: str

    function_tag: Optional[str] = None
    codex_ins_code: Optional[int] = None
    codex_ins_subcode: Optional[str] = None

    is_flavoring: bool = False
    flavoring_type: Optional[FlavoringType] = None
    target_sensory: Optional[str] = None

    is_ley_25630_block: bool = False
    sub_ingredients: List["ParsedIngredient"] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Vocabulario reconocido
# ═══════════════════════════════════════════════════════════════════════════


_FUNCTION_WORDS = {
    # Emulsionante / Emulsificante
    "emulsionante": "emulsionante",
    "emulsionantes": "emulsionante",
    "emulsificante": "emulsionante",
    "emulsificantes": "emulsionante",

    # Conservante / Conservador
    "conservante": "conservante",
    "conservantes": "conservante",
    "conservador": "conservante",
    "conservadores": "conservante",

    # Acidulante / Regulador de acidez
    "acidulante": "acidulante",
    "acidulantes": "acidulante",
    "regulador de acidez": "acidulante",
    "reguladores de acidez": "acidulante",

    # Antioxidante
    "antioxidante": "antioxidante",
    "antioxidantes": "antioxidante",

    # Estabilizante
    "estabilizante": "estabilizante",
    "estabilizantes": "estabilizante",

    # Espesante
    "espesante": "espesante",
    "espesantes": "espesante",

    # Edulcorante
    "edulcorante": "edulcorante",
    "edulcorantes": "edulcorante",
    "edulcorante no nutritivo": "edulcorante",
    "edulcorantes no nutritivos": "edulcorante",

    # Colorante
    "colorante": "colorante",
    "colorantes": "colorante",
    "colorante natural": "colorante",
    "colorantes naturales": "colorante",
    "colorante artificial": "colorante",
    "colorantes artificiales": "colorante",

    # Saborizante / Aromatizante
    "saborizante": "saborizante",
    "saborizantes": "saborizante",
    "aromatizante": "saborizante",
    "aromatizantes": "saborizante",

    # Otros
    "espumante": "espumante",
    "espumantes": "espumante",
    "humectante": "humectante",
    "humectantes": "humectante",
    "antiaglutinante": "antiaglutinante",
    "antiaglutinantes": "antiaglutinante",

    # Leudante
    "leudante": "leudante",
    "leudantes": "leudante",
    "leudante químico": "leudante",
    "leudantes químicos": "leudante",

    # Secuestrante
    "secuestrante": "secuestrante",
    "secuestrantes": "secuestrante",

    # Resaltador / Exaltador / Potenciador
    "resaltador": "resaltador",
    "resaltadores": "resaltador",
    "resaltador de sabor": "resaltador",
    "resaltadores de sabor": "resaltador",
    "exaltador": "resaltador",
    "exaltadores": "resaltador",
    "exaltador de sabor": "resaltador",
    "exaltadores de sabor": "resaltador",
    "potenciador": "resaltador",
    "potenciadores": "resaltador",
    "potenciador de sabor": "resaltador",
    "potenciadores de sabor": "resaltador",

    # Mejorador
    "mejorador": "mejorador",
    "mejoradores": "mejorador",
    "mejorador de la harina": "mejorador",
    "mejorador de harina": "mejorador",
    "mejoradores de harina": "mejorador",

    # Otros
    "endurecedor": "endurecedor",
    "endurecedores": "endurecedor",
    "gelificante": "gelificante",
    "gelificantes": "gelificante",
    "agente de recubrimiento": "recubrimiento",
    "agentes de recubrimiento": "recubrimiento",
    "gasificante": "gasificante",
    "gasificantes": "gasificante",
}

_ABBREVIATIONS = {
    "EMU": "emulsionante",
    "ACI": "acidulante",
    "ARO": "saborizante",
    "RAI": "leudante",
    "EST": "estabilizante",
    "COL": "colorante",
    "RES": "resaltador",
    "SEC": "secuestrante",
    "CON": "conservante",
    "ANT": "antioxidante",
    "HUM": "humectante",
    "GAS": "gasificante",
    "ESP": "espesante",
    "EDU": "edulcorante",
}

_FLAVORING_QUALIFIERS = {
    "natural e idéntico al natural": FlavoringType.NATURAL,
    "naturales e idénticos al natural": FlavoringType.NATURAL,
    "idéntico al natural": FlavoringType.IDENTICAL_TO_NATURAL,
    "idéntica al natural": FlavoringType.IDENTICAL_TO_NATURAL,
    "idénticos al natural": FlavoringType.IDENTICAL_TO_NATURAL,
    "idénticas al natural": FlavoringType.IDENTICAL_TO_NATURAL,
    "artificial": FlavoringType.ARTIFICIAL,
    "artificiales": FlavoringType.ARTIFICIAL,
    "natural": FlavoringType.NATURAL,
    "naturales": FlavoringType.NATURAL,
}


# ═══════════════════════════════════════════════════════════════════════════
# Patrones regex compilados
# ═══════════════════════════════════════════════════════════════════════════

_RE_INS = re.compile(
    r"\(?\s*(?:INS|E)\s*(\d{3,4})\s*([a-z]{1,4}|[ivx]+)?\s*\)?",
    re.IGNORECASE,
)

_RE_LEY_25630 = re.compile(
    r"\b(?:harina(?:\s+\w+)*\s+enriquecida|enriquecida)"
    r"[\s\(]*(?:según\s+)?ley\s*(?:n[º°]\s*)?25[\.\s]?630",
    re.IGNORECASE,
)

_FLAVORING_WORDS_PATTERN = r"(aromatizantes|aromatizante|saborizantes|saborizante|esencias|esencia)"
_QUALIFIERS_PATTERN = (
    r"(natural\s+e\s+idéntico\s+al\s+natural|naturales\s+e\s+idénticos\s+al\s+natural|"
    r"idéntico\s+al\s+natural|idéntica\s+al\s+natural|idénticos\s+al\s+natural|idénticas\s+al\s+natural|"
    r"artificiales|artificial|naturales|natural)"
)
_RE_FLAVORING = re.compile(
    rf"^\s*{_FLAVORING_WORDS_PATTERN}"
    rf"(?:\s+{_QUALIFIERS_PATTERN})?"
    rf"(?:\s+(?:a|de|sabor\s+a|sabor)\s+(.+))?$",
    re.IGNORECASE,
)

# Dosis entre paréntesis: "(15 mg/100 ml)", "(8 mg/100 ml)", "(0.5%)", "(200 ppm)".
# Aparecen al lado de aditivos para declarar concentración (CAA Cap. XVIII).
# No son sub-ingredientes ni metadata útil para el clasificador → se descartan.
_RE_DOSE_PAREN = re.compile(
    r"\(\s*\d+(?:[\.,]\d+)?\s*"
    r"(?:mg|µg|ug|mcg|g|kg|ml|l|%|ppm|ppb|iu|ui)"
    r"(?:\s*/\s*\d+(?:[\.,]\d+)?\s*\w+)?\s*\)",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _normalize_text(text: str) -> str:
    """Normaliza espacios y elimina caracteres invisibles, preserva acentos."""
    text = text.replace(" ", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _strip_accents(text: str) -> str:
    """Quita acentos para comparaciones case-insensitive."""
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def _split_top_level(text: str, separators: Tuple[str, ...] = (",", ";")) -> List[str]:
    """
    Divide el texto por separadores respetando paréntesis anidados.

    "a, b (c, d), e" → ["a", "b (c, d)", "e"]

    NOTA: deliberadamente NO se separa por " y " / " e ". Aunque a veces
    aparece como conector legítimo entre ingredientes (raro), también
    aparece en nombres compuestos comunes:
      - "aceite vegetal de palma y canola"
      - "aromatizante a crema y cebolla"
      - "manteca y aceite vegetal"
    El riesgo de romper estos casos supera el beneficio para etiquetas
    actuales. La separación por coma cubre el ~95% de los casos reales.
    """
    tokens: List[str] = []
    buffer: List[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            buffer.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buffer.append(ch)
        elif ch in separators and depth == 0:
            tok = "".join(buffer).strip()
            if tok:
                tokens.append(tok)
            buffer = []
        else:
            buffer.append(ch)
    tail = "".join(buffer).strip()
    if tail:
        tokens.append(tail)
    return tokens


def _extract_function_prefix(text: str) -> Tuple[Optional[str], str]:
    """
    Si el texto inicia con "FUNCIÓN: resto" o "ABBR: resto", retorna
    (function_canonical, resto). Si no matchea, retorna (None, text).

    Acepta minúsculas y mayúsculas: las etiquetas argentinas a veces usan
    "Emulsionante:" y a veces "emulsionante:".
    """
    m = re.match(r"^\s*([A-Za-záéíóúñÁÉÍÓÚÑ][\w\sáéíóúñÁÉÍÓÚÑ]*?)\s*:\s*(.+)$", text)
    if not m:
        return None, text

    raw_prefix = m.group(1).strip()
    rest = m.group(2).strip()

    # Las abreviaturas argentinas son siempre en mayúsculas (EMU, ACI, ARO...).
    if raw_prefix.upper() == raw_prefix and raw_prefix in _ABBREVIATIONS:
        return _ABBREVIATIONS[raw_prefix], rest

    norm = raw_prefix.lower()
    if norm in _FUNCTION_WORDS:
        return _FUNCTION_WORDS[norm], rest

    norm_no_acc = _strip_accents(norm)
    for k, v in _FUNCTION_WORDS.items():
        if _strip_accents(k) == norm_no_acc:
            return v, rest

    return None, text


def _balance_orphan_parens(text: str) -> str:
    """
    Si quedan paréntesis sin pareja después de extraer un código INS, los
    elimina conservando el resto. Es defensivo contra patrones tipo
    "X (INS 955) (15 mg/100 ml)" donde la extracción del INS deja paréntesis
    desbalanceados si se usa un strip ingenuo.
    """
    while text.count("(") != text.count(")"):
        if text.count("(") > text.count(")"):
            idx = text.rfind("(")
        else:
            idx = text.rfind(")")
        if idx == -1:
            break
        text = (text[:idx] + text[idx + 1 :]).strip()
    return text


def _strip_dose_parens(text: str) -> str:
    """
    Remueve anotaciones de dosis entre paréntesis ("(15 mg/100 ml)", "(0.5%)").
    Estas son metadata del aditivo, no sub-ingredientes.
    """
    return re.sub(r"\s+", " ", _RE_DOSE_PAREN.sub("", text)).strip()


def _extract_ins_code(text: str) -> Tuple[Optional[int], Optional[str], str]:
    """
    Si el texto contiene "(INS NNN[suf])" o similar, retorna
    (code, subcode, text_sin_código). Si no, (None, None, text).

    NO usa strip(" .,()") porque eso elimina indiscriminadamente paréntesis
    de cierre legítimos de OTRAS sub-expresiones (e.g., "(15 mg/100 ml)"
    sobreviviente). En su lugar, balancea explícitamente los paréntesis
    huérfanos que pudo dejar la extracción del INS.
    """
    m = _RE_INS.search(text)
    if not m:
        return None, None, text
    code = int(m.group(1))
    sub = m.group(2)
    cleaned = (text[: m.start()] + text[m.end():]).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;:")
    cleaned = _balance_orphan_parens(cleaned)
    return code, sub, cleaned


def _detect_ley_25630(text: str) -> bool:
    return bool(_RE_LEY_25630.search(text))


def _detect_flavoring(
    text: str,
) -> Optional[Tuple[FlavoringType, Optional[str]]]:
    """
    Si el texto matchea el patrón de aromatizante/saborizante, retorna
    (flavoring_type, target_sensory). El target puede ser None para
    casos genéricos sin descriptor sensorial.

    Soporta tres formas de declaración del target:
      1. "aromatizante <qual>? a/de/sabor a <target>" (conector explícito)
      2. "aromatizante <qual>? (<target1>, <target2>, ...)" (lista en paréntesis)
      3. "aromatizante <qual>?" (sin target — flavoring genérico)
    """
    head = re.match(rf"^\s*{_FLAVORING_WORDS_PATTERN}", text.strip(), re.IGNORECASE)
    if not head:
        return None

    # Forma 1: regex estricta con conector explícito (preserva comportamiento previo).
    m = _RE_FLAVORING.match(text.strip())
    if m:
        qualifier_str = m.group(2)
        target = m.group(3)
        if qualifier_str:
            qualifier_norm = re.sub(r"\s+", " ", qualifier_str.lower().strip())
            flavoring_type = _FLAVORING_QUALIFIERS.get(qualifier_norm, FlavoringType.UNSPECIFIED)
        else:
            flavoring_type = FlavoringType.UNSPECIFIED
        target_clean = target.strip().rstrip(".,;:") if target else None
        return flavoring_type, target_clean

    # Forma 2: target(s) entre paréntesis, sin conector "a/de/sabor".
    # "aromatizantes artificiales (frutilla, limón, naranja)"
    rest = text.strip()[head.end():].strip()
    flavoring_type = FlavoringType.UNSPECIFIED
    q_match = re.match(rf"^\s*{_QUALIFIERS_PATTERN}\s*", rest, re.IGNORECASE)
    if q_match:
        qualifier_norm = re.sub(r"\s+", " ", q_match.group(1).lower().strip())
        flavoring_type = _FLAVORING_QUALIFIERS.get(qualifier_norm, FlavoringType.UNSPECIFIED)
        rest = rest[q_match.end():].strip()

    paren_targets = re.match(r"^\(([^()]+)\)\s*\.?\s*$", rest)
    if paren_targets:
        target_clean = paren_targets.group(1).strip().rstrip(".,;:")
        return flavoring_type, target_clean

    # Forma 3: aromatizante genérico, sin target reconocible.
    return flavoring_type, None


# Función-words excluyendo saborizantes (los aromatizantes con paréntesis se
# manejan en _detect_flavoring porque su contenido son TARGETS sensoriales,
# no sub-ingredientes reales).
_NON_FLAVORING_FUNCTION_WORDS = {
    k: v for k, v in _FUNCTION_WORDS.items() if v != "saborizante"
}

# Construye los patrones una sola vez. Orden por longitud descendente para que
# el alternador regex matchee la frase más larga primero (e.g.
# "edulcorantes no nutritivos" antes que "edulcorante").
_NON_FLAV_FN_KEYS_SORTED = sorted(
    _NON_FLAVORING_FUNCTION_WORDS.keys(), key=len, reverse=True
)
_FN_KEYS_SORTED = sorted(_FUNCTION_WORDS.keys(), key=len, reverse=True)

_RE_FN_PAREN_BLOCK = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _NON_FLAV_FN_KEYS_SORTED) + r")"
    r"\s*\(([^()]+)\)",
    re.IGNORECASE,
)

_RE_Y_BEFORE_FN = re.compile(
    r"\s+(?:y|e)\s+"
    r"(?=(?:" + "|".join(re.escape(k) for k in _FN_KEYS_SORTED) + r")\s*[:(])",
    re.IGNORECASE,
)


def _rewrite_paren_function_blocks(text: str) -> str:
    """
    Reescribe la forma "FUNCIÓN (ing1, ing2)" como "FUNCIÓN: ing1, FUNCIÓN: ing2"
    para que el flujo de prefijo-por-dos-puntos del parser principal se aplique
    uniformemente. Solo aplica para funciones NO-saborizantes (los paréntesis
    de aromatizantes son targets sensoriales).

    Ejemplo:
      "colorantes (caramelo, rocú)" → "colorante: caramelo, colorante: rocú"
      "antioxidante (lecitina de soja)" → "antioxidante: lecitina de soja"
    """
    def repl(m: re.Match) -> str:
        fn_word = m.group(1).lower()
        canonical = _NON_FLAVORING_FUNCTION_WORDS.get(fn_word)
        if not canonical:
            # Match por insensitivity al acento — buscamos en versión sin acento.
            target_no_acc = _strip_accents(fn_word)
            for k, v in _NON_FLAVORING_FUNCTION_WORDS.items():
                if _strip_accents(k) == target_no_acc:
                    canonical = v
                    break
        if not canonical:
            return m.group(0)
        sub_text = m.group(2).strip()
        subs = _split_top_level(sub_text)
        return ", ".join(f"{canonical}: {sub}" for sub in subs if sub)

    return _RE_FN_PAREN_BLOCK.sub(repl, text)


def _rewrite_y_to_comma_before_function(text: str) -> str:
    """
    Reemplaza " y "/" e " por ", " cuando va seguido de una palabra-función
    reconocida (con `:` o `(` después). Esto desambigua patrones como
    "...rocú y acidulante: ácido cítrico" → "...rocú, acidulante: ácido cítrico"
    sin romper conjunciones legítimas como "palma y canola" o "crema y cebolla".
    """
    return _RE_Y_BEFORE_FN.sub(", ", text)


_FLAVORING_CONTINUATION_PREFIXES = (
    "identico al natural",
    "identica al natural",
    "identicos al natural",
    "identicas al natural",
    "artificial",
    "artificiales",
    "natural",
    "naturales",
)


def _is_flavoring_head(text: str) -> bool:
    return bool(re.match(rf"^\s*{_FLAVORING_WORDS_PATTERN}\b", text, re.IGNORECASE))


def _is_flavoring_continuation(text: str) -> bool:
    normalized = _strip_accents(text.lower().strip())
    return any(normalized.startswith(prefix) for prefix in _FLAVORING_CONTINUATION_PREFIXES)


def _merge_flavoring_qualifier_continuations(tokens: List[str]) -> List[str]:
    """
    Las etiquetas a veces declaran calificadores de saborizante separados por
    coma: "saborizante natural, idéntico al natural y artificial". Esa coma no
    separa ingredientes; completa el mismo saborizante.
    """
    merged: List[str] = []
    for token in tokens:
        token_norm = _normalize_text(token)
        if merged and _is_flavoring_head(merged[-1]) and _is_flavoring_continuation(token_norm):
            merged[-1] = f"{merged[-1]}, {token_norm}"
            continue
        merged.append(token)
    return merged


def _split_sub_ingredients(text: str) -> Tuple[str, List[str]]:
    """
    Si el texto tiene paréntesis con sub-ingredientes (no INS code), separa.
    Retorna (texto_sin_paréntesis, lista_de_sub_tokens).
    """
    if "(" not in text or ")" not in text:
        return text, []

    if _RE_INS.search(text):
        return text, []

    m = re.search(r"\(([^()]+)\)", text)
    if not m:
        return text, []

    sub_text = m.group(1)
    main = (text[: m.start()] + text[m.end():]).strip()
    main = re.sub(r"\s+", " ", main).strip(" .,")

    subs = _split_top_level(sub_text)
    return main, subs


# ═══════════════════════════════════════════════════════════════════════════
# Parser principal
# ═══════════════════════════════════════════════════════════════════════════


def _parse_token(
    raw: str, inherited_function: Optional[str]
) -> Optional[ParsedIngredient]:
    """Parsea un token individual (un ingrediente)."""
    raw_normalized = _normalize_text(raw)
    if not raw_normalized:
        return None

    extracted_function, body = _extract_function_prefix(raw_normalized)
    function_tag = extracted_function or inherited_function

    if _detect_ley_25630(body):
        return ParsedIngredient(
            name="harina de trigo enriquecida ley 25.630",
            raw_text=raw_normalized,
            is_ley_25630_block=True,
            function_tag=function_tag,
        )

    flavoring_match = _detect_flavoring(body)
    if flavoring_match is not None:
        flavoring_type, target = flavoring_match
        return ParsedIngredient(
            name=body.lower().strip(),
            raw_text=raw_normalized,
            function_tag="saborizante",
            is_flavoring=True,
            flavoring_type=flavoring_type,
            target_sensory=target,
        )

    ins_code, ins_sub, cleaned = _extract_ins_code(body)
    cleaned = _strip_dose_parens(cleaned)
    if ins_code is not None and not cleaned.strip():
        cleaned = f"INS {ins_code}{ins_sub or ''}"

    main_name, sub_texts = _split_sub_ingredients(cleaned)

    sub_parsed: List[ParsedIngredient] = []
    for sub_raw in sub_texts:
        sub = _parse_token(sub_raw, inherited_function=None)
        if sub is not None:
            sub_parsed.append(sub)

    return ParsedIngredient(
        name=main_name.lower().strip(),
        raw_text=raw_normalized,
        function_tag=function_tag,
        codex_ins_code=ins_code,
        codex_ins_subcode=ins_sub,
        sub_ingredients=sub_parsed,
    )


def parse_ingredient_list(text: str) -> List[ParsedIngredient]:
    """
    Parsea el texto crudo de una lista de ingredientes argentina.

    Implementa la herencia condicional de función: cuando un token define una
    función (ej. "leudantes químicos: X"), los siguientes tokens **con código
    INS** heredan esa función. La herencia se rompe en cuanto aparece un
    token sin INS (probablemente un ingrediente base no relacionado) o un
    nuevo prefijo de función.

    Razonamiento: en etiquetas argentinas el patrón típico es
        "función: aditivo1 (INS X), aditivo2 (INS Y), próximo_ingrediente"
    donde aditivo2 hereda la función pero próximo_ingrediente NO.
    """
    if not text:
        return []

    text = _normalize_text(text).rstrip(".")

    if text.lower().startswith("ingredientes:"):
        text = text[len("ingredientes:"):].strip()

    # Preprocesamiento: canoniza dos formas no-coloncomma a la forma "fn: x, fn: y"
    # antes del split principal, para que el resto del parser tenga un solo
    # camino de manejo de funciones.
    text = _rewrite_paren_function_blocks(text)
    text = _rewrite_y_to_comma_before_function(text)

    raw_tokens = _merge_flavoring_qualifier_continuations(_split_top_level(text))

    results: List[ParsedIngredient] = []
    inherited_function: Optional[str] = None

    for raw in raw_tokens:
        raw_norm = _normalize_text(raw)
        explicit_function, _ = _extract_function_prefix(raw_norm)

        # Determinar si este token es candidato a heredar función:
        # solo si NO tiene su propio prefijo Y tiene código INS visible.
        candidate_for_inheritance = (
            explicit_function is None
            and _RE_INS.search(raw_norm) is not None
        )

        function_to_apply = (
            inherited_function if candidate_for_inheritance else None
        )

        parsed = _parse_token(raw, inherited_function=function_to_apply)
        if parsed is None:
            continue
        results.append(parsed)

        # Si este token tenía prefijo explícito y no es aromatizante,
        # establece el contexto de herencia para los siguientes.
        # Si no tenía prefijo Y no heredó, resetea la herencia
        # (rompe la cadena al encontrar un ingrediente "no relacionado").
        if explicit_function is not None and not parsed.is_flavoring:
            inherited_function = explicit_function
        elif not candidate_for_inheritance and explicit_function is None:
            inherited_function = None

    return results
