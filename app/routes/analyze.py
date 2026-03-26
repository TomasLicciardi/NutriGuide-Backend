# app/routes/analyze.py
"""
Ruta unificada para el análisis de productos alimenticios.

FLUJO:
1. OCR con Gemini Vision → ingredientes + advertencias de alérgenos
2. Parser de alérgenos → estructura CONTIENE / PUEDE CONTENER / positivas
3. Clasificación determinista → restricciones afectadas por keywords
4. Ingredientes desconocidos → embeddings → Gemini fallback
5. Combinar todo + guardar en BD + respuesta
"""

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
import json
import time
import logging

from app.services.gemini_service import gemini_service
from app.services.deterministic_classifier import classifier
from app.utils.allergen_parser import parse_allergen_text
from app.database.connection import get_db
from app.models import History, Product, User, Ingredient, IngredientType, ProductIngredient
from app.utils.jwt import JWTBearer, extract_user_id
from app.schemas.product_schemas import ImageType
from app.schemas.analysis_schemas import AnalysisResponseV2, ErrorResponse
from app.resources.history import get_history_by_user_id, create_history_for_user
from app.resources.user import get_user_by_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoint principal
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/", response_model=AnalysisResponseV2)
async def analizar_producto(
    file: UploadFile = File(...),
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db),
):
    start_time = time.time()
    usuario_id = extract_user_id(token)

    # ── Setup: historial y restricciones del usuario ──
    historial = get_history_by_user_id(db, usuario_id)
    if not historial:
        historial = create_history_for_user(db, usuario_id)

    usuario = get_user_by_id(db, usuario_id)
    restricciones_usuario = usuario.get_restrictions() if usuario else []

    # ── Validar imagen ──
    image_data = await file.read()
    content_type = file.content_type or "image/jpeg"
    try:
        image_type = ImageType(content_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de imagen no soportado. Permitidos: {', '.join(t.value for t in ImageType)}",
        )

    # ══════════════════════════════════════════════════════════════════════
    # FASE 1: OCR con Gemini Vision
    # ══════════════════════════════════════════════════════════════════════
    try:
        logger.info("FASE 1: Extraccion OCR con Gemini")
        ocr_result = await gemini_service.extract_ingredients_ocr(image_data, image_type.value)

        if not ocr_result.get("success"):
            error_type = ocr_result.get("error", "unknown")
            status_code = 400 if error_type in ("poor_quality", "invalid_image") else 500
            raise HTTPException(
                status_code=status_code,
                detail=ErrorResponse(
                    error=error_type,
                    message=ocr_result.get("message", "Error en OCR"),
                    confidence=ocr_result.get("confidence", 0.0),
                ).dict(),
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en extraccion OCR: {e}")

    ingredientes_detectados = ocr_result["ingredients"]
    allergen_text = ocr_result.get("allergen_warnings") or ""

    # ══════════════════════════════════════════════════════════════════════
    # FASE 2: Parser de alérgenos con comprensión contextual
    # ══════════════════════════════════════════════════════════════════════
    logger.info("FASE 2: Parsing de alergenos")
    allergen_result = parse_allergen_text(allergen_text)
    logger.info(
        f"Alergenos: contiene={allergen_result.contiene}, "
        f"puede_contener={allergen_result.puede_contener}, "
        f"positivas={allergen_result.declaraciones_positivas}"
    )

    # ══════════════════════════════════════════════════════════════════════
    # FASE 3: Clasificación determinista
    # ══════════════════════════════════════════════════════════════════════
    logger.info(f"FASE 3: Clasificacion determinista de {len(ingredientes_detectados)} ingredientes")
    classification = classifier.classify_product(ingredientes_detectados, allergen_result)

    # ══════════════════════════════════════════════════════════════════════
    # FASE 4: Resolver ingredientes desconocidos (embeddings → Gemini)
    # ══════════════════════════════════════════════════════════════════════
    if classification.unknown_ingredients:
        logger.info(f"FASE 4: {len(classification.unknown_ingredients)} ingredientes desconocidos")
        await _resolve_unknown_ingredients(classification, db)
    else:
        logger.info("FASE 4: Sin ingredientes desconocidos, skip")

    # ══════════════════════════════════════════════════════════════════════
    # FASE 5: Guardar en BD
    # ══════════════════════════════════════════════════════════════════════
    try:
        logger.info("FASE 5: Guardando en base de datos")

        user_verdict = _calculate_user_verdict(classification.restrictions, restricciones_usuario)

        base_ingredients = [i for i in classification.classified_ingredients if i.tipo == "BASE"]
        additives = [i for i in classification.classified_ingredients if i.tipo == "ADITIVO"]

        final_result = {
            "user_verdict": user_verdict,
            "classification": {
                r: classification.restrictions[r] for r in classification.restrictions
            },
            "detected_ingredients": ingredientes_detectados,
            "base_ingredients": [i.name for i in base_ingredients],
            "additives": [i.name for i in additives],
            "allergen_warnings": allergen_text,
            "confidence": min(ocr_result["confidence"], classification.confidence),
        }

        nuevo_producto = Product(
            history_id=historial.id,
            image=image_data,
            image_type=image_type.value,
            # OCR
            ocr_result_json=json.dumps(ocr_result),
            extracted_ingredients=json.dumps(ingredientes_detectados),
            allergen_warnings=allergen_text,
            ocr_confidence=ocr_result["confidence"],
            # Clasificación
            classification_result_json=json.dumps(final_result),
            classification_confidence=classification.confidence,
            # Restricciones individuales
            is_vegan=classification.restrictions["vegano"]["apto"],
            vegan_reason=classification.restrictions["vegano"].get("motivo"),
            is_vegetarian=classification.restrictions["vegetariano"]["apto"],
            vegetarian_reason=classification.restrictions["vegetariano"].get("motivo"),
            is_gluten_free=classification.restrictions["sin_gluten"]["apto"],
            gluten_free_reason=classification.restrictions["sin_gluten"].get("motivo"),
            is_lactose_free=classification.restrictions["sin_lactosa"]["apto"],
            lactose_free_reason=classification.restrictions["sin_lactosa"].get("motivo"),
            is_nut_free=classification.restrictions["sin_frutos_secos"]["apto"],
            nut_free_reason=classification.restrictions["sin_frutos_secos"].get("motivo"),
            # Resultado completo
            result_json=json.dumps(final_result),
            is_suitable=user_verdict,
            processing_status="completed",
        )

        db.add(nuevo_producto)
        db.flush()

        # Guardar ingredientes en tabla ProductIngredient
        _save_product_ingredients(db, nuevo_producto.id, classification.classified_ingredients)

        db.commit()

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error almacenando en BD: {e}")

    # ══════════════════════════════════════════════════════════════════════
    # FASE 6: Respuesta
    # ══════════════════════════════════════════════════════════════════════
    processing_time = time.time() - start_time
    logger.info(
        f"ANALISIS COMPLETADO en {processing_time:.2f}s — "
        f"{len(base_ingredients)} BASE, {len(additives)} ADITIVOS, "
        f"metodo={classification.method}"
    )

    return AnalysisResponseV2(
        user_verdict=user_verdict,
        classification={
            r: {"apto": v["apto"], "motivo": v.get("motivo")}
            for r, v in classification.restrictions.items()
        },
        detected_ingredients=ingredientes_detectados,
        base_ingredients=[i.name for i in base_ingredients],
        additives=[i.name for i in additives],
        allergen_warnings=allergen_text or None,
        confidence=min(ocr_result["confidence"], classification.confidence),
        processing_time=processing_time,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Funciones auxiliares
# ═══════════════════════════════════════════════════════════════════════════════

async def _resolve_unknown_ingredients(classification, db: Session):
    """
    Resuelve ingredientes desconocidos en 3 niveles:
    Nivel 1: Embeddings (similitud semántica con ingredientes conocidos)
    Nivel 2: Gemini fallback (pregunta puntual por ingrediente)
    Nivel 3: Default seguro (no marcar como inseguro)
    """
    from app.services.embedding_service import EmbeddingService
    embedding_service = EmbeddingService()

    unknowns = list(classification.unknown_ingredients)

    for ingredient_name in unknowns:
        resolved = False

        # Nivel 1: Embeddings
        try:
            similar = embedding_service.find_similar_ingredients(ingredient_name, db, threshold=0.82)
            if similar:
                best_match, similarity = similar[0]
                logger.info(
                    f"Embedding match: '{ingredient_name}' -> "
                    f"'{best_match.name}' ({best_match.type.value}, sim={similarity:.2f})"
                )
                external = _ingredient_type_to_external(best_match, db)
                if external:
                    classifier.apply_external_classification(classification, ingredient_name, external)
                    resolved = True
        except Exception as e:
            logger.warning(f"Error en embedding para '{ingredient_name}': {e}")

        if resolved:
            continue

        # Nivel 2: Gemini fallback
        try:
            result = await gemini_service.classify_unknown_ingredient(ingredient_name)
            if result:
                logger.info(f"Gemini fallback para '{ingredient_name}': {result}")
                classifier.apply_external_classification(classification, ingredient_name, result)
                _save_learned_ingredient(db, ingredient_name, result, embedding_service)
                resolved = True
        except Exception as e:
            logger.warning(f"Error en Gemini fallback para '{ingredient_name}': {e}")

        # Nivel 3: Default seguro (no hacer nada, queda como unknown sin afectar restricciones)
        if not resolved:
            logger.info(f"Ingrediente no resuelto (default seguro): '{ingredient_name}'")
            if ingredient_name in classification.unknown_ingredients:
                classification.unknown_ingredients.remove(ingredient_name)


def _ingredient_type_to_external(ingredient: Ingredient, db: Session) -> Optional[Dict[str, bool]]:
    """Convierte un Ingredient de la DB a formato external_result para el classifier."""
    from app.services.deterministic_classifier import DeterministicClassifier
    dc = DeterministicClassifier()
    result = dc.classify_ingredient(ingredient.original_name or ingredient.name)

    if not result.restrictions_affected:
        return None

    external = {"dairy": False, "egg": False, "meat_fish": False,
                "honey_insect": False, "gluten": False, "nuts": False}

    restriction_to_category = {
        "sin_lactosa": "dairy",
        "sin_gluten": "gluten",
        "sin_frutos_secos": "nuts",
        "vegano": None,
        "vegetariano": None,
    }

    for restriction in result.restrictions_affected:
        cat = restriction_to_category.get(restriction)
        if cat:
            external[cat] = True

    return external if any(external.values()) else None


def _save_learned_ingredient(db: Session, name: str, gemini_result: Dict[str, bool], embedding_service):
    """Guarda un ingrediente resuelto por Gemini para futuras consultas."""
    try:
        from app.models import Ingredient, IngredientType
        from sqlalchemy import func
        import json as _json

        name_lower = name.lower().strip()
        existing = db.query(Ingredient).filter(func.lower(Ingredient.name) == name_lower).first()
        if existing:
            return

        is_additive = any(kw in name_lower for kw in [
            "emulsificante", "colorante", "conservante", "estabilizante",
            "aromatizante", "acidulante", "antioxidante",
        ])

        embedding = embedding_service.generate_embedding_sync(name)

        new_ing = Ingredient(
            name=name_lower,
            original_name=name,
            type=IngredientType.ADITIVO if is_additive else IngredientType.BASE,
            embedding=_json.dumps(embedding) if embedding else None,
            confidence=0.80,
        )
        db.add(new_ing)
        db.flush()
        logger.info(f"Ingrediente aprendido: '{name}' -> DB")
    except Exception as e:
        logger.warning(f"Error guardando ingrediente aprendido '{name}': {e}")


def _save_product_ingredients(db: Session, product_id: int, classified_ingredients):
    """Guarda los ingredientes clasificados en la tabla ProductIngredient."""
    from sqlalchemy import func

    for ing in classified_ingredients:
        name_lower = ing.name_normalized or ing.name.lower().strip()

        db_ingredient = db.query(Ingredient).filter(
            func.lower(Ingredient.name) == name_lower
        ).first()

        ingredient_id = db_ingredient.id if db_ingredient else None

        if ingredient_id is None:
            new_ing = Ingredient(
                name=name_lower,
                original_name=ing.name,
                type=IngredientType.ADITIVO if ing.tipo == "ADITIVO" else IngredientType.BASE,
                confidence=ing.confidence,
            )
            db.add(new_ing)
            db.flush()
            ingredient_id = new_ing.id

        pi = ProductIngredient(
            product_id=product_id,
            ingredient_id=ingredient_id,
            detected_name=ing.name,
            is_base_ingredient=(ing.tipo == "BASE"),
            affects_classification=bool(ing.restrictions_affected),
            source="deterministic",
            confidence=ing.confidence,
        )
        db.add(pi)


def _calculate_user_verdict(restrictions: dict, user_restrictions: list) -> bool:
    """Calcula veredicto final basado en las restricciones activas del usuario."""
    if not user_restrictions:
        return True

    mapping = {
        "sin_tacc": "sin_gluten",
        "celiacos": "sin_gluten",
        "lactose_free": "sin_lactosa",
        "nut_free": "sin_frutos_secos",
        "vegan": "vegano",
        "vegetarian": "vegetariano",
    }

    for restriction in user_restrictions:
        mapped = mapping.get(restriction, restriction)
        if mapped in restrictions:
            if not restrictions[mapped]["apto"]:
                return False

    return True
