# app/routes/analyze.py
"""
Pipeline multi-fuente de análisis de ingredientes — NutriGuide v2.

7 Fases:
  1. OCR con Gemini Vision
  2. Normalización de ingredientes
  3. Traducción ES→EN con MarianMT local
  4. Clasificación con 5 Tiers (1-2 instant, 3-4-5 en paralelo)
  5. Análisis de texto de alérgenos
  6. Motor de consenso
  7. Persistencia + aprendizaje (Knowledge Base)
"""

import asyncio
import json
import time
import logging
from typing import Dict, List

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models import Product, Ingredient, ProductIngredient
from app.utils.jwt import JWTBearer, extract_user_id
from app.schemas.product_schemas import ImageType
from app.schemas.analysis_schemas import (
    AnalysisResponseV2, IngredientDetail, RestrictionResult, ErrorResponse,
)
from app.resources.history import get_history_by_user_id, create_history_for_user
from app.resources.user import get_user_by_id

from app.services.gemini_service import gemini_service
from app.services.translation_service import translation_service
from app.services.deterministic_classifier import classifier
from app.services.knowledge_base_service import knowledge_base_service
from app.services.openfoodfacts_service import openfoodfacts_service
from app.services.pubchem_service import pubchem_service
from app.services.consensus_engine import consensus_engine, IngredientVerdict
from app.utils.allergen_parser import parse_allergen_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/", response_model=AnalysisResponseV2)
async def analizar_producto(
    file: UploadFile = File(...),
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db),
):
    start_time = time.time()
    usuario_id = extract_user_id(token)

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
    logger.info("FASE 1: OCR con Gemini Vision")
    try:
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
                ).model_dump(),
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en OCR: {e}")

    ingredientes_es = ocr_result["ingredients"]
    allergen_text = ocr_result.get("allergen_warnings") or ""
    logger.info(f"OCR: {len(ingredientes_es)} ingredientes detectados")

    # ══════════════════════════════════════════════════════════════════════
    # FASE 2: Normalización (ya viene normalizado del OCR)
    # ══════════════════════════════════════════════════════════════════════
    logger.info("FASE 2: Normalización")

    # ══════════════════════════════════════════════════════════════════════
    # FASE 3: Traducción ES→EN
    # ══════════════════════════════════════════════════════════════════════
    logger.info("FASE 3: Traducción ES→EN con MarianMT")
    ingredientes_en = translation_service.translate_batch(ingredientes_es)
    pairs = list(zip(ingredientes_es, ingredientes_en))
    logger.info(f"Traducción: {len(pairs)} pares generados")

    # ══════════════════════════════════════════════════════════════════════
    # FASE 4: Clasificación con 5 Tiers
    # ══════════════════════════════════════════════════════════════════════

    # -- Tier 1: Determinista (instantáneo) --
    logger.info("FASE 4 - Tier 1: Clasificación determinista")
    tier1 = classifier.classify_batch(ingredientes_es)

    # -- Tier 2: Knowledge Base (instantáneo) --
    unresolved_after_t1 = tier1.unresolved
    logger.info(f"FASE 4 - Tier 2: Knowledge Base ({len(unresolved_after_t1)} pendientes)")
    tier2_results = knowledge_base_service.lookup_batch(unresolved_after_t1, db)
    unresolved_after_t2 = [n for n in unresolved_after_t1 if n not in tier2_results]
    logger.info(f"Tier 2: {len(tier2_results)} resueltos, {len(unresolved_after_t2)} pendientes")

    # -- Tiers 3-4-5: escalonado (OFF primero, luego PubChem+Gemini solo para lo que OFF no resolvió) --
    tier3_results: Dict = {}
    tier4_results: Dict = {}
    tier5_results: Dict = {}

    if unresolved_after_t2:
        unresolved_en = [
            en for es, en in pairs if es in unresolved_after_t2
        ]
        unresolved_pairs_map = {
            en: es for es, en in pairs if es in unresolved_after_t2
        }

        # Tier 3: Open Food Facts (rápido, una sola llamada batch)
        logger.info(f"FASE 4 - Tier 3 OFF: {len(unresolved_en)} ingredientes")
        try:
            tier3_results = await openfoodfacts_service.analyze_ingredients(unresolved_en)
        except Exception as e:
            logger.error(f"Tier 3 (OFF) falló: {e}")
            tier3_results = {}

        # Filtrar: solo ingredientes que OFF NO reconoció van a Tiers 4-5
        off_unresolved_en = [
            name_en for name_en in unresolved_en
            if name_en not in tier3_results or not tier3_results[name_en].in_taxonomy
        ]

        if off_unresolved_en:
            off_unresolved_pairs = [
                {"name_es": unresolved_pairs_map[en], "name_en": en}
                for en in off_unresolved_en
            ]
            logger.info(f"FASE 4 - Tiers 4-5 en paralelo: {len(off_unresolved_en)} ingredientes sin taxonomía OFF")

            t4_raw, t5_raw = await asyncio.gather(
                pubchem_service.identify_compounds(off_unresolved_en),
                gemini_service.classify_unknown_ingredients(off_unresolved_pairs),
                return_exceptions=True,
            )

            if not isinstance(t4_raw, Exception):
                tier4_results = t4_raw
            else:
                logger.error(f"Tier 4 (PubChem) falló: {t4_raw}")

            if not isinstance(t5_raw, Exception):
                tier5_results = t5_raw
            else:
                logger.error(f"Tier 5 (Gemini) falló: {t5_raw}")
        else:
            logger.info("Todos los ingredientes resueltos por OFF — Tiers 4-5 omitidos")

    # ══════════════════════════════════════════════════════════════════════
    # FASE 5: Análisis de texto de alérgenos (ya se hizo en paralelo conceptual)
    # ══════════════════════════════════════════════════════════════════════
    logger.info("FASE 5: Análisis de texto de alérgenos")
    allergen_result = parse_allergen_text(allergen_text)

    # ══════════════════════════════════════════════════════════════════════
    # FASE 6: Motor de consenso
    # ══════════════════════════════════════════════════════════════════════
    logger.info("FASE 6: Motor de consenso")
    ingredient_verdicts: List[IngredientVerdict] = []

    for name_es, name_en in pairs:
        t1_r = tier1.resolved.get(name_es)
        t2_r = tier2_results.get(name_es)
        t3_r = tier3_results.get(name_en)
        t4_r = tier4_results.get(name_en)
        t5_r = tier5_results.get(name_en)

        verdict = consensus_engine.merge_tier_results(
            name_es=name_es,
            name_en=name_en,
            tier1_result=t1_r,
            tier2_result=t2_r,
            tier3_result=t3_r,
            tier4_result=t4_r,
            tier5_result=t5_r,
        )
        ingredient_verdicts.append(verdict)

    product_verdict = consensus_engine.build_product_verdict(
        ingredient_verdicts, allergen_result, restricciones_usuario,
    )

    # ══════════════════════════════════════════════════════════════════════
    # FASE 7: Persistir + aprender
    # ══════════════════════════════════════════════════════════════════════
    logger.info("FASE 7: Persistencia y aprendizaje")
    try:
        processing_time = time.time() - start_time

        nuevo_producto = Product(
            history_id=historial.id,
            image=image_data,
            image_type=image_type.value,
            ocr_result_json=json.dumps(ocr_result),
            extracted_ingredients=json.dumps(ingredientes_es),
            allergen_warnings=allergen_text,
            ocr_confidence=ocr_result.get("confidence", 0.0),
            is_tacc_safe=product_verdict.restrictions["sin_tacc"]["apto"],
            tacc_reason=product_verdict.restrictions["sin_tacc"].get("motivo"),
            is_lactose_safe=product_verdict.restrictions["sin_lactosa"]["apto"],
            lactose_reason=product_verdict.restrictions["sin_lactosa"].get("motivo"),
            is_nut_safe=product_verdict.restrictions["sin_frutos_secos"]["apto"],
            nut_reason=product_verdict.restrictions["sin_frutos_secos"].get("motivo"),
            is_vegan_safe=product_verdict.restrictions["vegano"]["apto"],
            vegan_reason=product_verdict.restrictions["vegano"].get("motivo"),
            overall_confidence=product_verdict.overall_confidence,
            processing_time_ms=processing_time * 1000,
            result_json=json.dumps({
                "restrictions": product_verdict.restrictions,
                "ingredients": [
                    {
                        "name_es": v.name_es, "name_en": v.name_en,
                        "category": v.category, "origin": v.origin,
                        "resolved_by": v.resolved_by, "confidence": v.confidence,
                    }
                    for v in ingredient_verdicts
                ],
            }),
            is_suitable=product_verdict.user_verdict,
            processing_status="completed",
        )
        db.add(nuevo_producto)
        db.flush()

        # Guardar ingredientes en ProductIngredient + actualizar Knowledge Base
        for v in ingredient_verdicts:
            kb_ing = knowledge_base_service.save_ingredient(
                db=db,
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
            )

            pi = ProductIngredient(
                product_id=nuevo_producto.id,
                ingredient_id=kb_ing.id,
                detected_name=v.name_es,
                name_en=v.name_en,
                is_base_ingredient=(v.category == "BASE"),
                resolved_by=v.resolved_by,
                confidence=v.confidence,
                evidence_json=json.dumps(v.evidence),
            )
            db.add(pi)

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error guardando en BD: {e}")
        raise HTTPException(status_code=500, detail=f"Error almacenando en BD: {e}")

    # ══════════════════════════════════════════════════════════════════════
    # Respuesta
    # ══════════════════════════════════════════════════════════════════════
    processing_time = time.time() - start_time
    logger.info(f"ANÁLISIS COMPLETADO en {processing_time:.2f}s — {len(ingredient_verdicts)} ingredientes")

    return AnalysisResponseV2(
        user_verdict=product_verdict.user_verdict,
        restrictions={
            r: RestrictionResult(apto=d["apto"], motivo=d.get("motivo"))
            for r, d in product_verdict.restrictions.items()
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
            for v in ingredient_verdicts
        ],
        allergen_warnings=allergen_text or None,
        overall_confidence=product_verdict.overall_confidence,
        processing_time=processing_time,
        stats={
            "total_ingredients": len(ingredient_verdicts),
            "by_deterministic": tier1.stats.get("by_keyword", 0) + tier1.stats.get("by_ins", 0) + tier1.stats.get("by_safe", 0),
            "by_knowledge_base": len(tier2_results),
            "by_api": len(tier3_results) + len(tier4_results),
            "by_gemini": len(tier5_results),
            "unresolved": sum(1 for v in ingredient_verdicts if v.resolved_by == "unresolved"),
        },
    )
