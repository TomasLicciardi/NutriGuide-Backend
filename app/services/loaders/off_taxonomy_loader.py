# app/services/loaders/off_taxonomy_loader.py
"""
Loader de Open Food Facts ingredients taxonomy — backed por SQLite local.

El cache se construye offline con `scripts/build_off_cache.py` y se persiste
a `backend/data/off_taxonomy.sqlite`. Este loader expone un lookup por nombre
multilingüe (ES/EN/FR/PT/IT) con fallback por herencia de parents: si un
entry no declara una propiedad, sube por la cadena de parents hasta encontrar
la primera que la tenga.

Diseño:
  - Tabla `synonyms` indexada por (synonym, lang) para hits exactos rápidos.
  - Tabla `parents` con CTE recursivo para resolver herencia.
  - Sin llamada a API en runtime — la cobertura está toda en el SQLite.
    Si el ingrediente no está, devolvemos None y otra fuente del enrichment
    cascade lo levanta.

Compatibilidad: la firma `lookup(name)` y la dataclass `OffTaxonomyEntry`
se mantienen iguales que antes para no tocar enrichment_service.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from app.services.ingredient_facts import (
    ALLERGEN_DAIRY,
    ALLERGEN_EGG,
    ALLERGEN_FISH,
    ALLERGEN_GLUTEN,
    ALLERGEN_HONEY,
    ALLERGEN_LACTOSE,
    ALLERGEN_MILK,
    ALLERGEN_PEANUT,
    ALLERGEN_SESAME,
    ALLERGEN_SHELLFISH,
    ALLERGEN_SOY,
    ALLERGEN_TREE_NUT,
    ALLERGEN_WHEAT,
    Origin,
    TagProvenance,
)

logger = logging.getLogger(__name__)


_DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "off_taxonomy.sqlite"
)


# Mapeo OFF allergens tag (ej. "en:milk") → tag canónico nuestro.
# OFF declara un set acotado de allergens; cada uno mapea a 1+ tags nuestros.
_ALLERGEN_TAG_MAP = {
    "en:gluten": (ALLERGEN_GLUTEN,),
    "en:wheat": (ALLERGEN_WHEAT, ALLERGEN_GLUTEN),
    "en:milk": (ALLERGEN_MILK, ALLERGEN_DAIRY, ALLERGEN_LACTOSE),
    "en:eggs": (ALLERGEN_EGG,),
    "en:fish": (ALLERGEN_FISH,),
    "en:crustaceans": (ALLERGEN_SHELLFISH,),
    "en:molluscs": (ALLERGEN_SHELLFISH,),
    "en:peanuts": (ALLERGEN_PEANUT,),
    "en:nuts": (ALLERGEN_TREE_NUT,),
    "en:soybeans": (ALLERGEN_SOY,),
    "en:sesame-seeds": (ALLERGEN_SESAME,),
    "en:honey": (ALLERGEN_HONEY,),
}


# Mapeo de IDs canónicos OFF → tags de "derived_from". Es chico porque solo
# necesitamos las raíces botánicas/animales que importan a las restricciones.
# La herencia por parents extiende esto: cualquier hijo de en:wheat hereda
# el derived_from "wheat".
_DERIVED_FROM_BY_ID = {
    "en:wheat": "wheat",
    "en:barley": "barley",
    "en:rye": "rye",
    "en:oat": "oats",
    "en:milk": "milk",
    "en:dairy": "dairy",
    "en:peanut": "peanut",
    "en:tree-nut": "tree-nut",
    "en:soya": "soy",
    "en:soybean": "soy",
    "en:egg": "egg",
    "en:honey": "honey",
}


def _normalize_lookup(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text or "")
    no_acc = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    s = no_acc.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" .,;:")
    return s


@dataclass
class OffTaxonomyEntry:
    """Resultado del lookup de un ingrediente en OFF."""
    name_en: str
    taxonomy_id: Optional[str] = None
    in_taxonomy: bool = False
    origin: Origin = Origin.UNKNOWN
    allergens: Set[str] = field(default_factory=set)
    derived_from: Set[str] = field(default_factory=set)
    vegan: Optional[str] = None
    vegetarian: Optional[str] = None
    confidence: float = 0.0
    evidence: str = ""

    def to_provenance(self) -> TagProvenance:
        return TagProvenance(
            source="off_taxonomy",
            confidence=self.confidence,
            evidence=self.evidence,
        )


# ════════════════════════════════════════════════════════════════════════════
# Loader
# ════════════════════════════════════════════════════════════════════════════


class OffTaxonomyLoader:
    """Lookup de OFF taxonomy desde el SQLite local con herencia por parents."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path: Path = db_path or _DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized: bool = False
        self._entry_count: int = 0

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def initialize(self) -> int:
        """Abre el SQLite del cache. Retorna cantidad de entries indexados."""
        if self._initialized:
            return self._entry_count

        if not self._db_path.exists():
            logger.warning(
                f"OFF taxonomy SQLite no existe en {self._db_path}. "
                f"Construilo con: python -m scripts.build_off_cache"
            )
            self._initialized = True
            return 0

        self._conn = sqlite3.connect(
            f"file:{self._db_path}?mode=ro", uri=True, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM entries")
        self._entry_count = cur.fetchone()["n"]
        self._initialized = True
        logger.info(f"OFF taxonomy cache: {self._entry_count} entries cargados desde {self._db_path}")
        return self._entry_count

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._initialized = False

    # ════════════════════════════════════════════════════════════════════════
    # Lookup público — async para mantener firma con el resto del enrichment
    # ════════════════════════════════════════════════════════════════════════

    async def lookup(self, name: str) -> Optional[OffTaxonomyEntry]:
        return await asyncio.to_thread(self._lookup_sync, name)

    async def lookup_batch(self, names: List[str]) -> Dict[str, OffTaxonomyEntry]:
        results: Dict[str, OffTaxonomyEntry] = {}
        for name in names:
            entry = await self.lookup(name)
            if entry is not None and entry.in_taxonomy:
                results[name] = entry
        return results

    # ════════════════════════════════════════════════════════════════════════
    # Implementación
    # ════════════════════════════════════════════════════════════════════════

    def _lookup_sync(self, name: str) -> Optional[OffTaxonomyEntry]:
        if not self._initialized or self._conn is None:
            return None
        norm = _normalize_lookup(name)
        if not norm:
            return None

        # Estrategia: probar idiomas en orden de probabilidad para etiquetas
        # argentinas (ES > EN > FR/PT/IT). El primero que matchea gana.
        # Si no hay hit exacto, probamos variantes morfológicas (singular/plural)
        # antes de devolver None — son transformaciones genéricas de español
        # comunes en sinónimos de OFF (`castana de caju` ↔ `castanas de caju`).
        for candidate in self._morphological_variants(norm):
            entry_id = (
                self._find_synonym(candidate, "es")
                or self._find_synonym(candidate, "en")
                or self._find_synonym(candidate, "any")
            )
            if entry_id is not None:
                return self._build_entry_with_inheritance(entry_id, name)
        return None

    @staticmethod
    def _morphological_variants(norm: str) -> List[str]:
        """
        Genera variantes morfológicas para tolerar diferencias de número en
        sinónimos. No es exhaustivo (no hace lematización real), solo cubre
        los casos frecuentes ES en etiquetas: -s/-es y la primera palabra.
        Orden de prueba: original primero, después fallbacks.
        """
        variants: List[str] = [norm]
        seen: Set[str] = {norm}

        def add(v: str) -> None:
            if v and v not in seen:
                variants.append(v)
                seen.add(v)

        # Variante por la última palabra (suele ser el núcleo del nombre).
        words = norm.split(" ")
        if words:
            tail = words[-1]
            tail_alts: List[str] = []
            if tail.endswith("es") and len(tail) > 3:
                tail_alts.append(tail[:-2])         # "raices" -> "raic"
                tail_alts.append(tail[:-1])         # "raices" -> "raice"
            elif tail.endswith("s") and len(tail) > 3:
                tail_alts.append(tail[:-1])         # "castanas" -> "castana"
            else:
                tail_alts.append(tail + "s")        # "castana" -> "castanas"
                tail_alts.append(tail + "es")       # "color" -> "colores"
            for t in tail_alts:
                add(" ".join(words[:-1] + [t]))

        # Variante por la primera palabra (cubre "harinas integrales" → "harina ...").
        if words and len(words) > 1:
            head = words[0]
            head_alts: List[str] = []
            if head.endswith("s") and len(head) > 3:
                head_alts.append(head[:-1])
            else:
                head_alts.append(head + "s")
            for h in head_alts:
                add(" ".join([h] + words[1:]))

        return variants

    def _find_synonym(self, norm: str, lang: str) -> Optional[str]:
        if self._conn is None:
            return None
        if lang == "any":
            cur = self._conn.execute(
                "SELECT entry_id FROM synonyms WHERE synonym = ? LIMIT 1",
                (norm,),
            )
        else:
            cur = self._conn.execute(
                "SELECT entry_id FROM synonyms WHERE synonym = ? AND lang = ? LIMIT 1",
                (norm, lang),
            )
        row = cur.fetchone()
        return row["entry_id"] if row else None

    def _ancestor_chain(self, entry_id: str) -> List[sqlite3.Row]:
        """
        Devuelve el entry y sus ancestros ordenados por profundidad (0 = self).
        Usa CTE recursivo limitado a profundidad 30 por defensa.
        """
        assert self._conn is not None
        cur = self._conn.execute(
            """
            WITH RECURSIVE chain(id, depth) AS (
                SELECT ?, 0
                UNION ALL
                SELECT p.parent_id, c.depth + 1
                FROM parents p JOIN chain c ON p.child_id = c.id
                WHERE c.depth < 30
            )
            SELECT e.*, c.depth
            FROM chain c
            JOIN entries e ON e.id = c.id
            ORDER BY c.depth ASC
            """,
            (entry_id,),
        )
        return list(cur.fetchall())

    def _build_entry_with_inheritance(self, entry_id: str, query_name: str) -> OffTaxonomyEntry:
        chain = self._ancestor_chain(entry_id)
        if not chain:
            return OffTaxonomyEntry(name_en=query_name)

        # Resolución de propiedades: el primer non-null en la cadena gana.
        def resolve(field: str) -> Optional[str]:
            for row in chain:
                value = row[field]
                if value not in (None, ""):
                    return value
            return None

        head = chain[0]
        canonical_en = head["canonical_en"] or resolve("canonical_en")

        entry = OffTaxonomyEntry(
            name_en=canonical_en or query_name,
            taxonomy_id=entry_id,
            in_taxonomy=True,
            vegan=resolve("vegan"),
            vegetarian=resolve("vegetarian"),
            confidence=0.85,
        )

        # Allergens: unimos los del entry y sus ancestros (no es un valor
        # heredable único — un ingrediente puede tener allergens propios y
        # los del padre).
        allergen_tags: Set[str] = set()
        for row in chain:
            raw = row["allergens"]
            if not raw:
                continue
            for tag in (t.strip() for t in raw.split(",")):
                if not tag:
                    continue
                mapped = _ALLERGEN_TAG_MAP.get(tag.lower())
                if mapped:
                    allergen_tags.update(mapped)
        entry.allergens = allergen_tags

        # derived_from: si algún ancestro (incluido el self) coincide con un
        # ID raíz en _DERIVED_FROM_BY_ID, lo agregamos. Esto cubre transitivamente
        # ej. "manteca de cacao" → ancestro "cacao" → no aporta derived_from,
        # pero "harina de trigo" → ancestro "en:wheat" → derived_from "wheat".
        for row in chain:
            tag = _DERIVED_FROM_BY_ID.get(row["id"])
            if tag:
                entry.derived_from.add(tag)

        # Origen: vegan=yes → plant; vegan=no → animal (clásico de OFF).
        if entry.vegan == "yes":
            entry.origin = Origin.PLANT
        elif entry.vegan == "no":
            entry.origin = Origin.ANIMAL
        elif entry.vegetarian == "no":
            entry.origin = Origin.ANIMAL

        # Evidencia legible para provenance.
        depth = head["depth"]
        ancestor_summary = " ← ".join(row["id"] for row in chain[: min(4, len(chain))])
        entry.evidence = (
            f"OFF taxonomy: {entry_id} (vegan={entry.vegan}, "
            f"vegetarian={entry.vegetarian}, allergens={sorted(allergen_tags) or '∅'}, "
            f"chain={ancestor_summary})"
        )
        return entry


# Singleton — el resto del sistema lo importa desde acá.
off_taxonomy_loader = OffTaxonomyLoader()


# ────────────────────────────────────────────────────────────────────────────
# Helper exportado para tests legacy del prefix-matching.
# Lo dejamos como compat porque test_off_taxonomy_loader.py lo usa.
# ────────────────────────────────────────────────────────────────────────────


def _taxonomy_id_matches(taxonomy_id: str, prefix: str) -> bool:
    """Match por prefijo respetando bordes de '-'. Compat con el viejo loader."""
    return taxonomy_id == prefix or taxonomy_id.startswith(prefix + "-")
