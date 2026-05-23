"""
Construye un cache local indexado de la taxonomía de Open Food Facts.

Se corre una sola vez (o cuando se quiere refrescar la taxonomía). Descarga
o lee el archivo `ingredients.txt` de OFF, lo parsea, y persiste a SQLite con
tres tablas: entries, parents, synonyms. La herencia de propiedades por
parents NO se denormaliza acá — se resuelve en lookup con un CTE recursivo,
así el cache queda chico y trazable.

Uso:
    python -m scripts.build_off_cache
    python -m scripts.build_off_cache --source path/local.txt
    python -m scripts.build_off_cache --source URL --output data/off.sqlite

Por defecto baja el archivo del repo oficial de OFF y escribe el cache en
backend/data/off_taxonomy.sqlite.
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("build_off_cache")


_OFF_FOOD = "https://raw.githubusercontent.com/openfoodfacts/openfoodfacts-server/main/taxonomies/food"
_OFF_TOP = "https://raw.githubusercontent.com/openfoodfacts/openfoodfacts-server/main/taxonomies"

# Por defecto indexamos dos taxonomías de OFF en la misma DB:
#   - food/ingredients.txt → bases, derivados, mezclas
#   - additives.txt        → aditivos químicos con número E/INS (top-level)
# Ambas comparten formato, así que el mismo parser sirve para las dos.
DEFAULT_SOURCES = [
    f"{_OFF_FOOD}/ingredients.txt",
    f"{_OFF_TOP}/additives.txt",
]
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "off_taxonomy.sqlite"


# Propiedades que nos interesan de cada entry. El resto se descarta.
_TRACKED_PROPERTIES = {
    "vegan",
    "vegetarian",
    "from_palm_oil",
    "allergens",
    "additives_classes",
    "e_number",
    "description",
}

# Idiomas que indexamos para lookup. Si un entry tiene más, los ignoramos.
_TRACKED_LANGS = ("es", "en", "fr", "pt", "it")


# ════════════════════════════════════════════════════════════════════════════
# Parser de la taxonomía
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class RawEntry:
    """Entry crudo tal como aparece en ingredients.txt."""
    parents: List[str] = field(default_factory=list)
    names: Dict[str, List[str]] = field(default_factory=dict)
    properties: Dict[str, Dict[str, str]] = field(default_factory=dict)
    line_no: int = 0

    @property
    def first_lang(self) -> Optional[str]:
        return next(iter(self.names), None) if self.names else None

    @property
    def canonical_id(self) -> Optional[str]:
        lang = self.first_lang
        if not lang:
            return None
        first_name = self.names[lang][0]
        return f"{lang}:{_to_id_slug(first_name)}"


_RE_PARENT = re.compile(r"^<\s*([a-z]{2,3}):\s*(.+?)\s*$")
_RE_LANG_NAMES = re.compile(r"^([a-z]{2,3})\s*:\s*(.+?)\s*$")
_RE_PROP = re.compile(r"^([a-z_]+)\s*:\s*([a-z]{2,3})\s*:\s*(.*?)\s*$")


def _to_id_slug(name: str) -> str:
    """OFF usa lowercase + espacios → guiones. Acentos se conservan."""
    s = name.strip().lower()
    s = re.sub(r"\s+", "-", s)
    return s


def _normalize_lookup(text: str) -> str:
    """Normaliza para la tabla de synonyms: lower + sin acentos + sin signos."""
    nfkd = unicodedata.normalize("NFD", text or "")
    no_acc = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    s = no_acc.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" .,;:")
    return s


def _split_synonyms(value: str) -> List[str]:
    parts = [p.strip() for p in value.split(",")]
    return [p for p in parts if p]


def parse_taxonomy(text: str) -> List[RawEntry]:
    """
    Parser de ingredients.txt. Devuelve los entries en el orden del archivo.

    Reglas observadas en el formato OFF:
      - Líneas que empiezan con `#` son comentarios.
      - Líneas en blanco separan entries.
      - `synonyms:lang: ...` y `stopwords:lang: ...` a nivel top — fuera de
        cualquier entry — se descartan. Los reconocemos porque aparecen
        antes del primer `lang:` o `<` en un bloque.
      - Dentro de un entry:
          `< lang:slug` → declara un parent
          `lang: a, b, c` → primera vez para ese idioma fija canonical+sinónimos
          `prop:lang: valor` → propiedad del entry
    """
    entries: List[RawEntry] = []
    current: Optional[RawEntry] = None

    def flush():
        nonlocal current
        if current and (current.names or current.parents):
            if current.canonical_id:
                entries.append(current)
        current = None

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        if not line.strip():
            flush()
            continue
        if line.startswith("#"):
            continue

        # Top-level synonyms/stopwords se filtran porque aparecen fuera de
        # cualquier bloque de entry (no hay un `lang:` o `<` previo en su
        # bloque de líneas no-blancas).
        if current is None and (line.startswith("synonyms:") or line.startswith("stopwords:")):
            continue

        m = _RE_PARENT.match(line)
        if m:
            if current is None:
                current = RawEntry(line_no=line_no)
            current.parents.append(f"{m.group(1)}:{_to_id_slug(m.group(2))}")
            continue

        m = _RE_PROP.match(line)
        if m:
            prop, lang, value = m.group(1), m.group(2), m.group(3)
            if current is None:
                # Top-level prop sin entry — descarta.
                continue
            current.properties.setdefault(prop, {})[lang] = value
            continue

        m = _RE_LANG_NAMES.match(line)
        if m:
            lang, value = m.group(1), m.group(2)
            if current is None:
                current = RawEntry(line_no=line_no)
            if lang not in current.names:
                current.names[lang] = _split_synonyms(value)
            else:
                # Múltiples líneas del mismo idioma se acumulan.
                current.names[lang].extend(_split_synonyms(value))
            continue

        # Línea sin reconocer — la ignoramos pero loggeamos.
        logger.debug(f"línea {line_no} sin reconocer: {line!r}")

    flush()
    return entries


# ════════════════════════════════════════════════════════════════════════════
# SQLite — esquema + carga
# ════════════════════════════════════════════════════════════════════════════


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    canonical_es TEXT,
    canonical_en TEXT,
    canonical_fr TEXT,
    vegan TEXT,
    vegetarian TEXT,
    from_palm_oil TEXT,
    allergens TEXT,
    additives_classes TEXT,
    e_number TEXT,
    description_es TEXT,
    description_en TEXT
);

CREATE TABLE IF NOT EXISTS parents (
    child_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    PRIMARY KEY (child_id, parent_id)
);

CREATE TABLE IF NOT EXISTS synonyms (
    synonym TEXT NOT NULL,
    lang TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    PRIMARY KEY (synonym, lang, entry_id)
);

CREATE INDEX IF NOT EXISTS idx_synonyms_lookup ON synonyms(synonym);
CREATE INDEX IF NOT EXISTS idx_synonyms_lang ON synonyms(lang, synonym);
CREATE INDEX IF NOT EXISTS idx_parents_child ON parents(child_id);
"""


def write_sqlite(entries: List[RawEntry], output: Path, source: str) -> Tuple[int, int, int]:
    """
    Persiste los entries a SQLite. Devuelve (entries, parents, synonyms).
    `source` puede ser una URL/path única o varias separadas por '+' para
    que el meta refleje las fuentes que componen la DB.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    conn = sqlite3.connect(str(output))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.execute("INSERT INTO meta(key, value) VALUES('source', ?)", (source,))
        conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', '1')")

        n_entries = 0
        n_parents = 0
        n_synonyms = 0

        # Deduplicar por canonical_id (algunos archivos OFF tienen entries
        # repetidos por re-ediciones; nos quedamos con la primera).
        seen_ids: Set[str] = set()

        for entry in entries:
            eid = entry.canonical_id
            if not eid or eid in seen_ids:
                continue
            seen_ids.add(eid)

            canonical_es = entry.names.get("es", [None])[0]
            canonical_en = entry.names.get("en", [None])[0]
            canonical_fr = entry.names.get("fr", [None])[0]

            def prop(name: str, lang: str = "en") -> Optional[str]:
                return entry.properties.get(name, {}).get(lang)

            conn.execute(
                """
                INSERT INTO entries (
                    id, canonical_es, canonical_en, canonical_fr,
                    vegan, vegetarian, from_palm_oil,
                    allergens, additives_classes, e_number,
                    description_es, description_en
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    eid, canonical_es, canonical_en, canonical_fr,
                    prop("vegan"), prop("vegetarian"), prop("from_palm_oil"),
                    prop("allergens"), prop("additives_classes"), prop("e_number"),
                    prop("description", "es"), prop("description", "en"),
                ),
            )
            n_entries += 1

            for parent_id in entry.parents:
                conn.execute(
                    "INSERT OR IGNORE INTO parents(child_id, parent_id) VALUES (?,?)",
                    (eid, parent_id),
                )
                n_parents += 1

            for lang, syns in entry.names.items():
                if lang not in _TRACKED_LANGS:
                    continue
                for syn in syns:
                    norm = _normalize_lookup(syn)
                    if not norm:
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO synonyms(synonym, lang, entry_id) VALUES (?,?,?)",
                        (norm, lang, eid),
                    )
                    n_synonyms += 1

        conn.commit()
        return n_entries, n_parents, n_synonyms
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# Fuentes
# ════════════════════════════════════════════════════════════════════════════


def fetch_source(source: str) -> str:
    """Obtiene el texto del archivo de taxonomía. Source puede ser URL o path."""
    if source.startswith(("http://", "https://")):
        import httpx
        logger.info(f"Descargando {source}")
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            r = client.get(source)
            r.raise_for_status()
            return r.text
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"No encuentro la fuente: {source}")
    logger.info(f"Leyendo archivo local: {source}")
    return path.read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--source", action="append", default=None,
        help=(
            "URL o path de archivo OFF taxonomy. Se puede pasar varias veces "
            f"para fusionar fuentes. Default: {' + '.join(DEFAULT_SOURCES)}"
        ),
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help=f"Path destino del cache SQLite (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limita la cantidad de entries por fuente (debug)")
    args = parser.parse_args(argv)

    sources: List[str] = args.source if args.source else DEFAULT_SOURCES

    all_entries: List[RawEntry] = []
    for src in sources:
        try:
            text = fetch_source(src)
        except Exception as e:
            logger.error(f"Falló la obtención de '{src}': {e}")
            return 2
        logger.info(f"  Parseando {src} ({len(text)} bytes)")
        ents = parse_taxonomy(text)
        if args.limit:
            ents = ents[: args.limit]
        logger.info(f"    -> {len(ents)} entries")
        all_entries.extend(ents)

    logger.info(f"Total entries (todas las fuentes): {len(all_entries)}")

    output = Path(args.output)
    n_e, n_p, n_s = write_sqlite(all_entries, output, " + ".join(sources))
    logger.info(
        f"Cache escrito en {output}: "
        f"{n_e} entries, {n_p} parents, {n_s} synonyms"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
