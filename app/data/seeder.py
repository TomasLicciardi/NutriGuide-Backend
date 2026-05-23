# app/data/seeder.py
"""
Seeder de la Knowledge Base — Pre-carga ingredientes curados al startup.

Lee kb_seed.yaml y los inserta en la tabla `ingredients` si no existen.
Esto permite que la KB resuelva ingredientes comunes desde el primer
análisis, sin necesidad de hardcodearlos en código.

Diferencias clave con hardcoding:
  - Los datos viven en la BD, no en código
  - Pueden ser sobrescritos por el pipeline si encuentra mejor información
  - Son auditables (timestamps, resolved_by="seed")
"""

import logging
import unicodedata
from pathlib import Path
from typing import List

import yaml
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ingredient import Ingredient, IngredientType

logger = logging.getLogger(__name__)

_SEED_FILE = Path(__file__).parent / "kb_seed.yaml"


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()


def seed_knowledge_base(db: Session) -> dict:
    """
    Pre-carga la Knowledge Base con ingredientes curados desde kb_seed.yaml.

    Solo inserta ingredientes que no existen en la BD (no sobrescribe
    datos que el pipeline haya aprendido con mayor confianza).

    Retorna estadísticas de la operación.
    """
    if not _SEED_FILE.exists():
        logger.warning(f"Archivo de seed no encontrado: {_SEED_FILE}")
        return {"inserted": 0, "skipped": 0, "errors": 0}

    with open(_SEED_FILE, "r", encoding="utf-8") as f:
        seed_data: List[dict] = yaml.safe_load(f)

    if not seed_data or not isinstance(seed_data, list):
        logger.warning("kb_seed.yaml está vacío o mal formateado")
        return {"inserted": 0, "skipped": 0, "errors": 0}

    inserted = 0
    skipped = 0
    errors = 0
    seen_in_batch = set()

    for entry in seed_data:
        try:
            name_es = _normalize(entry["name_es"])

            if name_es in seen_in_batch:
                skipped += 1
                continue

            existing = (
                db.query(Ingredient)
                .filter(func.lower(Ingredient.name_es) == name_es)
                .first()
            )

            if existing:
                skipped += 1
                seen_in_batch.add(name_es)
                continue

            ing_type = (
                IngredientType.ADITIVO
                if entry.get("type") == "ADITIVO"
                else IngredientType.BASE
            )

            new_ing = Ingredient(
                name_es=name_es,
                name_en=entry.get("name_en"),
                type=ing_type,
                origin=entry.get("origin"),
                function_tag=entry.get("function_tag"),
                description_es=entry.get("description_es"),
                is_tacc_safe=entry.get("is_tacc_safe"),
                is_lactose_safe=entry.get("is_lactose_safe"),
                is_nut_safe=entry.get("is_nut_safe"),
                is_vegan_safe=entry.get("is_vegan_safe"),
                confidence=0.95,
                resolved_by="seed",
                provenance="seed",
            )
            db.add(new_ing)
            inserted += 1
            seen_in_batch.add(name_es)

        except Exception as e:
            logger.warning(f"Error procesando seed '{entry.get('name_es', '?')}': {e}")
            errors += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error en commit de KB seed: {e}")
        return {"inserted": inserted, "skipped": skipped, "errors": errors + 1}

    logger.info(
        f"KB Seed: {inserted} insertados, {skipped} ya existían, {errors} errores "
        f"(total en YAML: {len(seed_data)})"
    )
    return {"inserted": inserted, "skipped": skipped, "errors": errors}
