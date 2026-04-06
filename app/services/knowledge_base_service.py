# app/services/knowledge_base_service.py
"""
Knowledge Base local — Tier 2 del pipeline multi-fuente.

Usa la tabla `ingredients` de SQLite como cache de ingredientes previamente
clasificados. Crece con cada análisis: cuando un ingrediente se resuelve
por los Tiers 3+, se guarda aquí para futuras consultas instantáneas.

Mejoras v2.1:
  - Batch query en lugar de N consultas individuales (fix N+1)
  - Umbral mínimo de confianza para escritura (evita contaminación por Gemini)
"""

import logging
import unicodedata
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ingredient import Ingredient, IngredientType
from app.services.deterministic_classifier import IngredientResult
from app.config.image_analysis_config import KB_CONFIG

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()


class KnowledgeBaseService:
    """Tier 2: búsqueda y almacenamiento en la base de ingredientes local."""

    def lookup(self, name_es: str, db: Session) -> Optional[IngredientResult]:
        """Busca un ingrediente por nombre normalizado en español."""
        norm = _normalize(name_es)
        ingredient = (
            db.query(Ingredient)
            .filter(func.lower(Ingredient.name_es) == norm)
            .first()
        )
        if ingredient is None:
            return None

        if not self._is_fully_classified(ingredient):
            return None

        result = IngredientResult(
            name=name_es,
            name_normalized=norm,
            category=ingredient.type.value if ingredient.type else "BASE",
            is_tacc_safe=ingredient.is_tacc_safe,
            is_lactose_safe=ingredient.is_lactose_safe,
            is_nut_safe=ingredient.is_nut_safe,
            is_vegan_safe=ingredient.is_vegan_safe,
            confidence=ingredient.confidence or 0.93,
            resolved_by="knowledge_base",
            evidence=[f"Knowledge Base: '{ingredient.name_es}' (tier original: {ingredient.resolved_by})"],
        )
        return result

    def lookup_batch(self, names_es: List[str], db: Session) -> Dict[str, IngredientResult]:
        """
        Busca múltiples ingredientes en UNA sola query SQL.
        Reemplaza el loop de N consultas individuales.
        """
        if not names_es:
            return {}

        normalized_map = {_normalize(name): name for name in names_es}
        normalized_keys = list(normalized_map.keys())

        ingredients = (
            db.query(Ingredient)
            .filter(func.lower(Ingredient.name_es).in_(normalized_keys))
            .all()
        )

        found: Dict[str, IngredientResult] = {}
        for ingredient in ingredients:
            if not self._is_fully_classified(ingredient):
                continue

            norm = _normalize(ingredient.name_es)
            original_name = normalized_map.get(norm)
            if original_name is None:
                continue

            found[original_name] = IngredientResult(
                name=original_name,
                name_normalized=norm,
                category=ingredient.type.value if ingredient.type else "BASE",
                is_tacc_safe=ingredient.is_tacc_safe,
                is_lactose_safe=ingredient.is_lactose_safe,
                is_nut_safe=ingredient.is_nut_safe,
                is_vegan_safe=ingredient.is_vegan_safe,
                confidence=ingredient.confidence or 0.93,
                resolved_by="knowledge_base",
                evidence=[
                    f"Knowledge Base: '{ingredient.name_es}' "
                    f"(tier original: {ingredient.resolved_by})"
                ],
            )

        logger.info(f"KB batch: {len(found)}/{len(names_es)} encontrados (1 query)")
        return found

    def save_ingredient(
        self,
        db: Session,
        name_es: str,
        name_en: Optional[str],
        category: str,
        origin: Optional[str],
        function_tag: Optional[str],
        description_es: Optional[str],
        is_tacc_safe: Optional[bool],
        is_lactose_safe: Optional[bool],
        is_nut_safe: Optional[bool],
        is_vegan_safe: Optional[bool],
        confidence: float,
        resolved_by: str,
        off_taxonomy_id: Optional[str] = None,
    ) -> Ingredient:
        """
        Guarda o actualiza un ingrediente en la Knowledge Base.

        Protección contra contaminación: no guarda resultados con confianza
        inferior al umbral mínimo configurado (evita que alucinaciones de
        Gemini se propaguen como datos verificados).
        """
        norm = _normalize(name_es)
        min_confidence = KB_CONFIG["min_write_confidence"]

        existing = (
            db.query(Ingredient)
            .filter(func.lower(Ingredient.name_es) == norm)
            .first()
        )

        if existing:
            if confidence > (existing.confidence or 0) and confidence >= min_confidence:
                existing.name_en = name_en or existing.name_en
                existing.origin = origin or existing.origin
                existing.function_tag = function_tag or existing.function_tag
                existing.description_es = description_es or existing.description_es
                existing.is_tacc_safe = is_tacc_safe if is_tacc_safe is not None else existing.is_tacc_safe
                existing.is_lactose_safe = is_lactose_safe if is_lactose_safe is not None else existing.is_lactose_safe
                existing.is_nut_safe = is_nut_safe if is_nut_safe is not None else existing.is_nut_safe
                existing.is_vegan_safe = is_vegan_safe if is_vegan_safe is not None else existing.is_vegan_safe
                existing.confidence = confidence
                existing.resolved_by = resolved_by
                existing.off_taxonomy_id = off_taxonomy_id or existing.off_taxonomy_id
                db.flush()
                logger.debug(f"KB actualizada: '{norm}' (confianza {confidence:.2f})")
            return existing

        if confidence < min_confidence:
            logger.debug(
                f"KB skip: '{norm}' confianza {confidence:.2f} < "
                f"umbral {min_confidence} (resuelto por {resolved_by})"
            )
            ing_type = IngredientType.ADITIVO if category == "ADITIVO" else IngredientType.BASE
            placeholder = Ingredient(
                name_es=norm,
                name_en=name_en,
                type=ing_type,
                origin=origin,
                function_tag=function_tag,
                description_es=description_es,
                is_tacc_safe=is_tacc_safe,
                is_lactose_safe=is_lactose_safe,
                is_nut_safe=is_nut_safe,
                is_vegan_safe=is_vegan_safe,
                confidence=confidence,
                resolved_by=resolved_by,
                off_taxonomy_id=off_taxonomy_id,
            )
            db.add(placeholder)
            db.flush()
            return placeholder

        ing_type = IngredientType.ADITIVO if category == "ADITIVO" else IngredientType.BASE
        new_ing = Ingredient(
            name_es=norm,
            name_en=name_en,
            type=ing_type,
            origin=origin,
            function_tag=function_tag,
            description_es=description_es,
            is_tacc_safe=is_tacc_safe,
            is_lactose_safe=is_lactose_safe,
            is_nut_safe=is_nut_safe,
            is_vegan_safe=is_vegan_safe,
            confidence=confidence,
            resolved_by=resolved_by,
            off_taxonomy_id=off_taxonomy_id,
        )
        db.add(new_ing)
        db.flush()
        logger.info(f"KB nuevo ingrediente: '{norm}' por {resolved_by} (conf={confidence:.2f})")
        return new_ing

    @staticmethod
    def _is_fully_classified(ingredient: Ingredient) -> bool:
        return all([
            ingredient.is_tacc_safe is not None,
            ingredient.is_lactose_safe is not None,
            ingredient.is_nut_safe is not None,
            ingredient.is_vegan_safe is not None,
        ])

    @staticmethod
    def count(db: Session) -> int:
        return db.query(Ingredient).count()


knowledge_base_service = KnowledgeBaseService()
