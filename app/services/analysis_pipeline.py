# app/services/analysis_pipeline.py
"""
Pipeline Orchestrator — Coordina las 7 fases del análisis multi-fuente.

Fases:
  1. OCR + Clasificación con Gemini Vision (1 sola llamada)
  2. Normalización
  3. Traducción ES→EN con MarianMT local (async)
  4. Clasificación multi-tier:
     - Tier 1: Determinista (local, reglas)
     - Tier 2: Knowledge Base (local, DB)
     - Tier 3: Embedding Classifier (local, ML)
     - Tier 4: Open Food Facts (externo, batch)
     - Tier 5: PubChem (externo, solo lo que OFF no resolvió)
     (Gemini ya clasificó todo en la Fase 1 — se usa en consenso)
  5. Análisis de texto de alérgenos
  6. Motor de consenso ponderado
  7. Persistencia + aprendizaje (Knowledge Base)

Mejoras v2.1:
  - Gemini reducido de 2 a 1 sola llamada (OCR + clasificación unificados)
  - Nuevo Tier 3 con modelo local de embeddings (sentence-transformers)
  - Traducción async (no bloquea event loop)
  - KB batch query + protección contra contaminación
"""

import asyncio
import json
import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.services.gemini_service import gemini_service, OCRResult
from app.services.translation_service import translation_service
from app.services.deterministic_classifier import classifier
from app.services.knowledge_base_service import knowledge_base_service
from app.services.embedding_classifier import embedding_classifier
from app.services.openfoodfacts_service import openfoodfacts_service
from app.services.pubchem_service import pubchem_service
from app.services.consensus_engine import consensus_engine, IngredientVerdict, ProductVerdict
from app.utils.allergen_parser import parse_allergen_text

logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    total_ingredients: int = 0
    by_deterministic: int = 0
    by_knowledge_base: int = 0
    by_embedding: int = 0
    by_openfoodfacts: int = 0
    by_pubchem: int = 0
    by_gemini: int = 0
    unresolved: int = 0
    gemini_calls: int = 0
    processing_time_ms: float = 0.0


@dataclass
class PipelineResult:
    success: bool
    product_verdict: Optional[ProductVerdict] = None
    ingredient_verdicts: List[IngredientVerdict] = field(default_factory=list)
    ocr_result: Optional[OCRResult] = None
    pairs: List[tuple] = field(default_factory=list)
    stats: Optional[PipelineStats] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    status_code: int = 200


class AnalysisPipeline:
    """Orquestador del pipeline de análisis multi-fuente."""

    async def run(
        self,
        image_data: bytes,
        image_type: str,
        user_restrictions: List[str],
        db: Session,
    ) -> PipelineResult:
        """Ejecuta el pipeline completo de análisis."""
        start_time = time.time()
        stats = PipelineStats(gemini_calls=1)

        # ══ FASE 1: OCR + Clasificación (1 sola llamada Gemini) ══
        logger.info("FASE 1: OCR + Clasificación con Gemini Vision")
        ocr_result = await gemini_service.extract_and_classify(image_data, image_type)

        if not ocr_result.success:
            status = 400 if ocr_result.error in ("poor_quality", "invalid_image") else 500
            return PipelineResult(
                success=False,
                error=ocr_result.message or "Error en OCR",
                error_type=ocr_result.error,
                status_code=status,
            )

        ingredientes_es = ocr_result.ingredients
        gemini_classifications = ocr_result.classifications
        allergen_text = ocr_result.allergen_warnings or ""
        logger.info(
            f"OCR: {len(ingredientes_es)} ingredientes, "
            f"{len(gemini_classifications)} clasificados por Gemini"
        )

        # ══ FASE 2: Normalización (ya viene del OCR) ══
        logger.info("FASE 2: Normalización")

        # ══ FASE 3: Traducción ES→EN (async, no bloquea event loop) ══
        logger.info("FASE 3: Traducción ES→EN con MarianMT")
        ingredientes_en = await translation_service.translate_batch_async(ingredientes_es)
        pairs = list(zip(ingredientes_es, ingredientes_en))
        logger.info(f"Traducción: {len(pairs)} pares generados")

        # ══ FASE 4: Clasificación multi-tier ══
        logger.info("FASE 4: Clasificación multi-tier")

        # Tier 1: Determinista (instantáneo)
        logger.info("  Tier 1: Clasificación determinista")
        tier1 = classifier.classify_batch(ingredientes_es)
        stats.by_deterministic = len(tier1.resolved)

        # Tier 2: Knowledge Base (instantáneo, 1 query SQL)
        unresolved_after_t1 = tier1.unresolved
        logger.info(f"  Tier 2: Knowledge Base ({len(unresolved_after_t1)} pendientes)")
        tier2_results = knowledge_base_service.lookup_batch(unresolved_after_t1, db)
        unresolved_after_t2 = [n for n in unresolved_after_t1 if n not in tier2_results]
        stats.by_knowledge_base = len(tier2_results)
        logger.info(f"  Tier 2: {len(tier2_results)} resueltos, {len(unresolved_after_t2)} pendientes")

        # Tier 3: Embedding Classifier (local, ML)
        tier3_embedding_results: Dict = {}
        if unresolved_after_t2 and embedding_classifier.is_initialized:
            logger.info(f"  Tier 3: Embedding Classifier ({len(unresolved_after_t2)} pendientes)")
            embedding_classifier.refresh_from_kb(db)
            tier3_embedding_results = embedding_classifier.classify_batch(unresolved_after_t2)
            stats.by_embedding = len(tier3_embedding_results)
            logger.info(f"  Tier 3: {len(tier3_embedding_results)} resueltos")

        unresolved_after_t3 = [
            n for n in unresolved_after_t2 if n not in tier3_embedding_results
        ]

        # Tiers 4-5: APIs externas (solo para lo que los tiers locales no resolvieron)
        tier4_off_results: Dict = {}
        tier5_pubchem_results: Dict = {}

        if unresolved_after_t3:
            unresolved_en = [en for es, en in pairs if es in unresolved_after_t3]
            unresolved_pairs_map = {en: es for es, en in pairs if es in unresolved_after_t3}

            # Tier 4: Open Food Facts
            logger.info(f"  Tier 4: Open Food Facts ({len(unresolved_en)} ingredientes)")
            try:
                tier4_off_results = await openfoodfacts_service.analyze_ingredients(unresolved_en)
                stats.by_openfoodfacts = sum(
                    1 for r in tier4_off_results.values() if r.in_taxonomy
                )
            except Exception as e:
                logger.error(f"  Tier 4 (OFF) falló: {e}")

            # Tier 5: PubChem — solo para lo que OFF no reconoció
            off_unresolved_en = [
                name_en for name_en in unresolved_en
                if name_en not in tier4_off_results
                or not tier4_off_results[name_en].in_taxonomy
            ]

            if off_unresolved_en:
                logger.info(f"  Tier 5: PubChem ({len(off_unresolved_en)} sin taxonomía OFF)")
                try:
                    tier5_pubchem_results = await pubchem_service.identify_compounds(
                        off_unresolved_en
                    )
                    stats.by_pubchem = sum(
                        1 for r in tier5_pubchem_results.values() if r.found
                    )
                except Exception as e:
                    logger.error(f"  Tier 5 (PubChem) falló: {e}")
            else:
                logger.info("  Todos resueltos por OFF — PubChem omitido")

        # ══ FASE 5: Análisis de texto de alérgenos ══
        logger.info("FASE 5: Análisis de texto de alérgenos")
        allergen_result = parse_allergen_text(allergen_text)

        # ══ FASE 6: Motor de consenso ══
        logger.info("FASE 6: Motor de consenso")
        ingredient_verdicts: List[IngredientVerdict] = []

        for name_es, name_en in pairs:
            t1_r = tier1.resolved.get(name_es)
            t2_r = tier2_results.get(name_es)
            t3_emb_r = tier3_embedding_results.get(name_es)
            t4_r = tier4_off_results.get(name_en)
            t5_r = tier5_pubchem_results.get(name_en)
            gemini_r = gemini_classifications.get(name_es)

            verdict = consensus_engine.merge_tier_results(
                name_es=name_es,
                name_en=name_en,
                tier1_result=t1_r,
                tier2_result=t2_r,
                tier3_embedding_result=t3_emb_r,
                tier4_result=t4_r,
                tier5_result=t5_r,
                gemini_result=gemini_r,
            )
            ingredient_verdicts.append(verdict)

        product_verdict = consensus_engine.build_product_verdict(
            ingredient_verdicts, allergen_result, user_restrictions,
        )

        stats.total_ingredients = len(ingredient_verdicts)
        stats.by_gemini = sum(
            1 for v in ingredient_verdicts if v.resolved_by == "gemini"
        )
        stats.unresolved = sum(
            1 for v in ingredient_verdicts if v.resolved_by == "unresolved"
        )
        stats.processing_time_ms = (time.time() - start_time) * 1000

        processing_time = time.time() - start_time
        logger.info(
            f"PIPELINE COMPLETADO en {processing_time:.2f}s — "
            f"{len(ingredient_verdicts)} ingredientes, "
            f"{stats.gemini_calls} llamada(s) Gemini"
        )

        return PipelineResult(
            success=True,
            product_verdict=product_verdict,
            ingredient_verdicts=ingredient_verdicts,
            ocr_result=ocr_result,
            pairs=pairs,
            stats=stats,
        )

    async def persist_results(
        self,
        db: Session,
        pipeline_result: PipelineResult,
        history_id: int,
        image_data: bytes,
        image_type: str,
    ) -> int:
        """
        Fase 7: Persiste el producto y actualiza la Knowledge Base.
        Retorna el ID del producto creado.
        """
        from app.models import Product, ProductIngredient

        ocr_result = pipeline_result.ocr_result
        product_verdict = pipeline_result.product_verdict
        ingredient_verdicts = pipeline_result.ingredient_verdicts
        stats = pipeline_result.stats

        nuevo_producto = Product(
            history_id=history_id,
            image=image_data,
            image_type=image_type,
            ocr_result_json=json.dumps({
                "ingredients": ocr_result.ingredients,
                "allergen_warnings": ocr_result.allergen_warnings,
                "confidence": ocr_result.confidence,
            }),
            extracted_ingredients=json.dumps(ocr_result.ingredients),
            allergen_warnings=ocr_result.allergen_warnings,
            ocr_confidence=ocr_result.confidence,
            is_tacc_safe=product_verdict.restrictions["sin_tacc"]["apto"],
            tacc_reason=product_verdict.restrictions["sin_tacc"].get("motivo"),
            is_lactose_safe=product_verdict.restrictions["sin_lactosa"]["apto"],
            lactose_reason=product_verdict.restrictions["sin_lactosa"].get("motivo"),
            is_nut_safe=product_verdict.restrictions["sin_frutos_secos"]["apto"],
            nut_reason=product_verdict.restrictions["sin_frutos_secos"].get("motivo"),
            is_vegan_safe=product_verdict.restrictions["vegano"]["apto"],
            vegan_reason=product_verdict.restrictions["vegano"].get("motivo"),
            overall_confidence=product_verdict.overall_confidence,
            processing_time_ms=stats.processing_time_ms,
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
        return nuevo_producto.id


analysis_pipeline = AnalysisPipeline()
