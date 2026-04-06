# app/routes/analyze.py
"""
Endpoint de análisis de productos — NutriGuide v2.1.

Delega toda la lógica al AnalysisPipeline orchestrator.
La ruta solo maneja HTTP concerns: validación de request, autenticación,
y formato de response.
"""

import logging
from typing import Dict, List

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.utils.jwt import JWTBearer, extract_user_id
from app.schemas.product_schemas import ImageType
from app.schemas.analysis_schemas import (
    AnalysisResponseV2, IngredientDetail, RestrictionResult, ErrorResponse,
)
from app.resources.history import get_history_by_user_id, create_history_for_user
from app.resources.user import get_user_by_id
from app.services.analysis_pipeline import analysis_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/", response_model=AnalysisResponseV2)
async def analizar_producto(
    file: UploadFile = File(...),
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db),
):
    usuario_id = extract_user_id(token)

    historial = get_history_by_user_id(db, usuario_id)
    if not historial:
        historial = create_history_for_user(db, usuario_id)

    usuario = get_user_by_id(db, usuario_id)
    restricciones_usuario = usuario.get_restrictions() if usuario else []

    image_data = await file.read()
    content_type = file.content_type or "image/jpeg"
    try:
        image_type = ImageType(content_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de imagen no soportado. Permitidos: {', '.join(t.value for t in ImageType)}",
        )

    # ── Pipeline completo ──
    result = await analysis_pipeline.run(
        image_data=image_data,
        image_type=image_type.value,
        user_restrictions=restricciones_usuario,
        db=db,
    )

    if not result.success:
        status_code = result.status_code
        raise HTTPException(
            status_code=status_code,
            detail=ErrorResponse(
                error=result.error_type or "unknown",
                message=result.error or "Error en análisis",
                confidence=0.0,
            ).model_dump(),
        )

    # ── Persistencia ──
    try:
        await analysis_pipeline.persist_results(
            db=db,
            pipeline_result=result,
            history_id=historial.id,
            image_data=image_data,
            image_type=image_type.value,
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error guardando en BD: {e}")
        raise HTTPException(status_code=500, detail=f"Error almacenando en BD: {e}")

    # ── Response ──
    stats = result.stats
    return AnalysisResponseV2(
        user_verdict=result.product_verdict.user_verdict,
        restrictions={
            r: RestrictionResult(apto=d["apto"], motivo=d.get("motivo"))
            for r, d in result.product_verdict.restrictions.items()
        },
        ingredients=[
            IngredientDetail(
                name_es=v.name_es,
                name_en=v.name_en,
                category=v.category,
                origin=v.origin,
                function_tag=v.function_tag,
                description_es=v.description_es,
                is_tacc_safe=v.is_tacc_safe,
                is_lactose_safe=v.is_lactose_safe,
                is_nut_safe=v.is_nut_safe,
                is_vegan_safe=v.is_vegan_safe,
                confidence=v.confidence,
                resolved_by=v.resolved_by,
                evidence=v.evidence,
            )
            for v in result.ingredient_verdicts
        ],
        allergen_warnings=result.ocr_result.allergen_warnings,
        overall_confidence=result.product_verdict.overall_confidence,
        processing_time=stats.processing_time_ms / 1000,
        stats={
            "total_ingredients": stats.total_ingredients,
            "by_deterministic": stats.by_deterministic,
            "by_knowledge_base": stats.by_knowledge_base,
            "by_embedding": stats.by_embedding,
            "by_openfoodfacts": stats.by_openfoodfacts,
            "by_pubchem": stats.by_pubchem,
            "by_gemini": stats.by_gemini,
            "unresolved": stats.unresolved,
            "gemini_api_calls": stats.gemini_calls,
        },
    )
