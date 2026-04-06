# app/services/embedding_classifier.py
"""
Clasificador semántico basado en embeddings — Tier 3 del pipeline multi-fuente.

Usa un modelo local de sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
para calcular similitud semántica entre ingredientes desconocidos y un corpus
de referencia curado (ingredientes con clasificación conocida).

El corpus se construye a partir de:
  1. Ingredientes universalmente seguros (ESSENTIAL_SAFE)
  2. Keywords de restricciones (RESTRICTION_KEYWORDS)
  3. Safe compounds (excepciones de falsos positivos)
  4. Knowledge Base local (ingredientes previamente verificados)

Ventajas sobre string matching (Tier 1):
  - Captura sinónimos y variaciones ("jarabe de fructosa" ~ "fructosa")
  - Entiende contexto semántico ("proteína vegetal" ~ "proteína de soja")
  - Robusto ante errores de OCR o variaciones regionales
"""

import logging
import threading
import unicodedata
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_lock = threading.Lock()


@dataclass
class ReferenceEntry:
    name: str
    is_tacc_safe: Optional[bool]
    is_lactose_safe: Optional[bool]
    is_nut_safe: Optional[bool]
    is_vegan_safe: Optional[bool]
    source: str


@dataclass
class EmbeddingResult:
    name: str
    matched_reference: str
    similarity: float
    category: str = "BASE"
    is_tacc_safe: Optional[bool] = None
    is_lactose_safe: Optional[bool] = None
    is_nut_safe: Optional[bool] = None
    is_vegan_safe: Optional[bool] = None
    confidence: float = 0.0
    resolved_by: str = "embedding"
    evidence: List[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()


class EmbeddingClassifier:
    """Clasificador semántico local basado en sentence-transformers."""

    def __init__(self):
        self._model = None
        self._reference_entries: List[ReferenceEntry] = []
        self._reference_embeddings: Optional[np.ndarray] = None
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def initialize(self):
        """Carga el modelo y construye embeddings de referencia desde datos curados."""
        with _lock:
            if self._initialized:
                return

            from app.config.image_analysis_config import EMBEDDING_CONFIG

            model_name = EMBEDDING_CONFIG["model_name"]
            logger.info(f"Cargando modelo de embeddings: {model_name}")

            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(model_name)

            self._build_curated_references()
            self._compute_reference_embeddings()
            self._initialized = True
            logger.info(
                f"Embedding classifier listo: {len(self._reference_entries)} "
                f"ingredientes de referencia"
            )

    def refresh_from_kb(self, db: Session):
        """Enriquece el corpus de referencia con entradas de alta confianza de la KB."""
        if not self._initialized:
            return

        from app.models.ingredient import Ingredient
        from app.config.image_analysis_config import KB_CONFIG

        min_conf = KB_CONFIG["min_confidence_for_override"]
        kb_ingredients = (
            db.query(Ingredient)
            .filter(
                Ingredient.confidence >= min_conf,
                Ingredient.is_tacc_safe.isnot(None),
                Ingredient.is_lactose_safe.isnot(None),
                Ingredient.is_nut_safe.isnot(None),
                Ingredient.is_vegan_safe.isnot(None),
            )
            .all()
        )

        existing_names = {e.name for e in self._reference_entries}
        new_entries = []
        for ing in kb_ingredients:
            name = _normalize(ing.name_es)
            if name not in existing_names:
                new_entries.append(ReferenceEntry(
                    name=name,
                    is_tacc_safe=ing.is_tacc_safe,
                    is_lactose_safe=ing.is_lactose_safe,
                    is_nut_safe=ing.is_nut_safe,
                    is_vegan_safe=ing.is_vegan_safe,
                    source=f"kb:{ing.resolved_by}",
                ))

        if new_entries:
            self._reference_entries.extend(new_entries)
            self._compute_reference_embeddings()
            logger.info(f"Embedding classifier: +{len(new_entries)} refs desde KB "
                        f"(total: {len(self._reference_entries)})")

    def classify_batch(
        self, ingredients_es: List[str]
    ) -> Dict[str, EmbeddingResult]:
        """
        Clasifica ingredientes por similitud semántica con el corpus de referencia.
        Solo retorna resultados por encima del umbral de similitud.
        """
        if not self._initialized or not ingredients_es:
            return {}

        from app.config.image_analysis_config import EMBEDDING_CONFIG, TIER_WEIGHTS

        threshold = EMBEDDING_CONFIG["similarity_threshold"]
        max_candidates = EMBEDDING_CONFIG["max_candidates"]
        tier_weight = TIER_WEIGHTS["embedding"]

        normalized = [_normalize(name) for name in ingredients_es]
        input_embeddings = self._model.encode(normalized, normalize_embeddings=True)

        similarities = input_embeddings @ self._reference_embeddings.T

        results: Dict[str, EmbeddingResult] = {}

        for i, name_es in enumerate(ingredients_es):
            top_indices = np.argsort(similarities[i])[::-1][:max_candidates]
            best_idx = top_indices[0]
            best_sim = float(similarities[i][best_idx])

            if best_sim < threshold:
                continue

            ref = self._reference_entries[best_idx]

            top_matches = [
                (self._reference_entries[idx].name, float(similarities[i][idx]))
                for idx in top_indices
                if float(similarities[i][idx]) >= threshold
            ]

            verdict = self._build_consensus_from_neighbors(
                top_indices, similarities[i], threshold
            )

            result = EmbeddingResult(
                name=name_es,
                matched_reference=ref.name,
                similarity=best_sim,
                is_tacc_safe=verdict["is_tacc_safe"],
                is_lactose_safe=verdict["is_lactose_safe"],
                is_nut_safe=verdict["is_nut_safe"],
                is_vegan_safe=verdict["is_vegan_safe"],
                confidence=tier_weight * best_sim,
                evidence=[
                    f"Embedding: sim={best_sim:.3f} con '{ref.name}' ({ref.source})",
                    f"Top matches: {top_matches}",
                ],
            )
            results[name_es] = result

        logger.info(
            f"Embedding classifier: {len(results)}/{len(ingredients_es)} "
            f"ingredientes resueltos (threshold={threshold})"
        )
        return results

    def _build_consensus_from_neighbors(
        self,
        top_indices: np.ndarray,
        similarities_row: np.ndarray,
        threshold: float,
    ) -> Dict[str, Optional[bool]]:
        """
        Construye consenso ponderado por similitud entre los K vecinos más cercanos.
        Si los vecinos discrepan, prevalece el voto ponderado por similitud.
        """
        fields = ["is_tacc_safe", "is_lactose_safe", "is_nut_safe", "is_vegan_safe"]
        result: Dict[str, Optional[bool]] = {}

        for field_name in fields:
            weighted_true = 0.0
            weighted_false = 0.0
            total_weight = 0.0

            for idx in top_indices:
                sim = float(similarities_row[idx])
                if sim < threshold:
                    break
                ref = self._reference_entries[int(idx)]
                val = getattr(ref, field_name)
                if val is None:
                    continue
                total_weight += sim
                if val:
                    weighted_true += sim
                else:
                    weighted_false += sim

            if total_weight == 0:
                result[field_name] = None
            else:
                result[field_name] = weighted_true >= weighted_false

        return result

    def _build_curated_references(self):
        """Construye corpus de referencia desde las listas curadas del clasificador determinista."""
        from app.services.deterministic_classifier import (
            ESSENTIAL_SAFE, RESTRICTION_KEYWORDS, SAFE_COMPOUNDS,
        )

        entries: List[ReferenceEntry] = []
        seen: set = set()

        for name in ESSENTIAL_SAFE:
            norm = _normalize(name)
            if norm not in seen:
                entries.append(ReferenceEntry(
                    name=norm,
                    is_tacc_safe=True,
                    is_lactose_safe=True,
                    is_nut_safe=True,
                    is_vegan_safe=True,
                    source="curated:safe",
                ))
                seen.add(norm)

        restriction_field_map = {
            "sin_tacc": "is_tacc_safe",
            "sin_lactosa": "is_lactose_safe",
            "sin_frutos_secos": "is_nut_safe",
            "vegano": "is_vegan_safe",
        }

        for restriction, keywords in RESTRICTION_KEYWORDS.items():
            for kw in keywords:
                norm = _normalize(kw)
                if norm in seen:
                    continue
                entry = ReferenceEntry(
                    name=norm,
                    is_tacc_safe=True,
                    is_lactose_safe=True,
                    is_nut_safe=True,
                    is_vegan_safe=True,
                    source=f"curated:keyword_{restriction}",
                )
                setattr(entry, restriction_field_map[restriction], False)
                if restriction == "sin_lactosa":
                    entry.is_vegan_safe = False
                entries.append(entry)
                seen.add(norm)

        for restriction, safe_list in SAFE_COMPOUNDS.items():
            for name in safe_list:
                norm = _normalize(name)
                if norm in seen:
                    continue
                entry = ReferenceEntry(
                    name=norm,
                    is_tacc_safe=True,
                    is_lactose_safe=True,
                    is_nut_safe=True,
                    is_vegan_safe=True,
                    source=f"curated:safe_compound",
                )
                entries.append(entry)
                seen.add(norm)

        self._reference_entries = entries

    def _compute_reference_embeddings(self):
        """Calcula embeddings normalizados para todo el corpus de referencia."""
        names = [e.name for e in self._reference_entries]
        self._reference_embeddings = self._model.encode(
            names, normalize_embeddings=True, show_progress_bar=False
        )
        logger.info(f"Embeddings calculados: {self._reference_embeddings.shape}")


embedding_classifier = EmbeddingClassifier()
