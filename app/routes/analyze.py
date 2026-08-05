# app/routes/analyze.py
"""
Endpoint /analysis/ — pipeline de análisis multi-fuente.

Pipeline con separación fact base / rule base — los predicados
operan sobre IngredientFacts construidos con federación de fuentes.

Ruta thin (HTTP only); toda la lógica está en analysis_pipeline.
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.utils.jwt import JWTBearer, extract_user_id
from app.schemas.product_schemas import ImageType
from app.schemas.analysis_schemas import (
    AnalysisResponse,
    ErrorResponse,
    IngredientResponse,
    LegalDeclarationResponse,
    RestrictionResponse,
    StatsResponse,
    TriggerIngredientResponse,
)
from app.resources.user import get_user_by_id
from app.resources.history import get_history_by_user_id, create_history_for_user
from app.services.analysis_pipeline import analysis_pipeline
from app.services.ingredient_facts import IngredientFacts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/", response_model=AnalysisResponse)
async def analizar_producto(
    file: UploadFile = File(...),
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db),
):
    usuario_id = extract_user_id(token)
    usuario = get_user_by_id(db, usuario_id)
    restricciones_usuario = usuario.get_restrictions() if usuario else []

    historial = get_history_by_user_id(db, usuario_id)
    if not historial:
        historial = create_history_for_user(db, usuario_id)

    image_data = await file.read()
    content_type = file.content_type or "image/jpeg"
    try:
        image_type = ImageType(content_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de imagen no soportado. Permitidos: {', '.join(t.value for t in ImageType)}",
        )

    result = await analysis_pipeline.run(
        image_data=image_data,
        image_type=image_type.value,
        user_restrictions=restricciones_usuario,
        db=db,
    )

    if not result.success:
        raise HTTPException(
            status_code=result.status_code,
            detail=ErrorResponse(
                error=result.error_type or "unknown",
                message=result.error or "Error en análisis",
            ).model_dump(),
        )

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
        logger.error(f"Error guardando análisis en BD: {e}")
        raise HTTPException(status_code=500, detail=f"Error almacenando en BD: {e}")

    return AnalysisResponse(
        user_verdict=result.user_verdict,
        restrictions={
            r: RestrictionResponse(
                apto=v.apto,
                motivo=v.motivo,
                fuente=v.fuente,
                confidence=v.confidence,
                ingrediente_disparador=v.ingrediente_disparador,
                trigger_ingredients=[
                    TriggerIngredientResponse(
                        name=t.name,
                        explanation=t.explanation,
                        allergen=t.allergen,
                    )
                    for t in v.trigger_ingredients
                ],
            )
            for r, v in result.restrictions.items()
        },
        ingredients=[_facts_to_response(f) for f in result.ingredient_facts],
        declaration=LegalDeclarationResponse(
            contains=sorted(result.declaration.contains) if result.declaration else [],
            may_contain=sorted(result.declaration.may_contain) if result.declaration else [],
            positive_claims=sorted(result.declaration.positive_claims) if result.declaration else [],
            raw_text=result.declaration.raw_text if result.declaration else None,
            warnings=result.declaration_warnings,
        ),
        overall_confidence=result.overall_confidence,
        stats=StatsResponse(
            total_ingredients=result.stats.total_ingredients,
            total_flavorings=result.stats.total_flavorings,
            resolved_by_legal=result.stats.resolved_by_legal,
            resolved_by_codex=result.stats.resolved_by_codex,
            resolved_by_off=result.stats.resolved_by_off,
            resolved_by_kb=result.stats.resolved_by_kb,
            resolved_by_pubchem=result.stats.resolved_by_pubchem,
            resolved_by_gemini=result.stats.resolved_by_gemini,
            resolved_by_llm=result.stats.resolved_by_llm,
            resolved_by_policy=result.stats.resolved_by_policy,
            unresolved=result.stats.unresolved,
            gemini_calls=result.stats.gemini_calls,
            processing_time_ms=result.stats.processing_time_ms,
        ),
    )


def _facts_to_response(f: IngredientFacts) -> IngredientResponse:
    return IngredientResponse(
        name_es=f.name_es,
        name_en=f.name_en,
        category=f.category.value,
        origin=f.origin.value,
        function_tag=f.function_tag,
        codex_ins_code=f.codex_ins_code,
        codex_ins_subcode=f.codex_ins_subcode,
        is_flavoring=f.is_flavoring(),
        flavoring_type=f.flavoring_type.value if f.flavoring_type else None,
        target_sensory=f.target_sensory,
        allergens=sorted(f.allergens),
        contains=sorted(f.contains),
        derived_from=sorted(f.derived_from),
        confidence=f.confidence,
        sources=f.sources,
        description_es=f.description_es,
    )
