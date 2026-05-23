# app/services/analysis_pipeline.py
"""
Analysis Pipeline — orquestador del flujo de análisis.

6 fases:
  1. OCR con Gemini Vision (1 sola llamada — reutiliza gemini_service)
  2. Parser estructural argentino (parser/) → ParsedIngredient + ProductLegalDeclaration
  3. Resolución por declaración legal (autoridad #1)
  4. Enrichment paralelo (enrichment_service) → IngredientFacts
  5. Evaluación de predicados declarativos (restriction_predicates)
  6. Veredicto + persistencia

Diseño "fact base / rule base" — los predicados operan sobre IngredientFacts
con trazabilidad de fuente por tag.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.services.gemini_service import gemini_service, OCRResult
from app.services.translation_service import translation_service
from app.services.parser import (
    parse_allergen_declaration,
    parse_ingredient_list,
    ParsedIngredient,
)
from app.services.enrichment_service import enrichment_service
from app.services.restriction_predicates import (
    ALL_RESTRICTIONS,
    PredicateResult,
    evaluate_restriction,
)
from app.services.ingredient_facts import (
    ANIMAL_SOURCES,
    DAIRY_SOURCES,
    GLUTEN_SOURCES,
    IngredientFacts,
    NUT_SOURCES,
    ProductLegalDeclaration,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Mapeo restricción → set de alérgenos (para resolución legal)
# ═══════════════════════════════════════════════════════════════════════════

_RESTRICTION_ALLERGEN_SETS = {
    "sin_tacc": GLUTEN_SOURCES,
    "sin_lactosa": DAIRY_SOURCES,
    "sin_frutos_secos": NUT_SOURCES,
    "vegano": ANIMAL_SOURCES,
}


# ═══════════════════════════════════════════════════════════════════════════
# Resultados estructurados
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class PipelineStats:
    total_ingredients: int = 0
    total_flavorings: int = 0
    resolved_by_legal: int = 0
    resolved_by_codex: int = 0
    resolved_by_off: int = 0
    resolved_by_kb: int = 0
    resolved_by_gemini: int = 0
    resolved_by_llm: int = 0
    resolved_by_policy: int = 0
    unresolved: int = 0
    gemini_calls: int = 1
    processing_time_ms: float = 0.0


@dataclass
class RestrictionVerdict:
    apto: bool
    motivo: Optional[str] = None
    fuente: str = "ingredient_analysis"  # legal_declaration | ingredient_analysis | flavoring_policy
    confidence: float = 1.0
    ingrediente_disparador: Optional[str] = None


@dataclass
class PipelineResult:
    success: bool
    user_verdict: bool = True
    restrictions: Dict[str, RestrictionVerdict] = field(default_factory=dict)
    ingredient_facts: List[IngredientFacts] = field(default_factory=list)
    declaration: Optional[ProductLegalDeclaration] = None
    ocr_result: Optional[OCRResult] = None
    overall_confidence: float = 0.0
    stats: PipelineStats = field(default_factory=PipelineStats)
    error: Optional[str] = None
    error_type: Optional[str] = None
    status_code: int = 200


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════════════


class AnalysisPipeline:

    async def run(
        self,
        image_data: bytes,
        image_type: str,
        user_restrictions: List[str],
        db: Session,
    ) -> PipelineResult:
        """
        Entry-point de producción: imagen → veredicto.
        Ejecuta Fase 1 (Gemini OCR) y delega Fases 2-6 a `run_from_text`.
        """
        start_time = time.time()

        # ── FASE 1: OCR ──
        logger.info("FASE 1: OCR con Gemini Vision")
        ocr_result = await gemini_service.extract_and_classify(image_data, image_type)
        if not ocr_result.success:
            status = 400 if ocr_result.error in ("poor_quality", "invalid_image") else 500
            return PipelineResult(
                success=False,
                error=ocr_result.message or "Error en OCR",
                error_type=ocr_result.error,
                status_code=status,
            )

        ingredients_text = ", ".join(ocr_result.ingredients)
        allergen_text = ocr_result.allergen_warnings or ""

        result = await self.run_from_text(
            ingredients_text=ingredients_text,
            allergen_text=allergen_text,
            user_restrictions=user_restrictions,
            db=db,
            gemini_classifications=ocr_result.classifications,
            start_time=start_time,
        )
        result.ocr_result = ocr_result
        result.stats.gemini_calls = 1
        return result

    async def run_from_text(
        self,
        ingredients_text: str,
        allergen_text: str,
        user_restrictions: List[str],
        db: Session,
        gemini_classifications: Optional[Dict] = None,
        start_time: Optional[float] = None,
    ) -> PipelineResult:
        """
        Entry-point de Fases 2-6 sin depender de Gemini OCR.

        Diseñado para reuso desde:
          - el endpoint de producción `run()`, después de obtener el OCR.
          - el harness de evaluación, alimentando texto del ground truth.
          - tests de integración que quieran inyectar texto crudo.

        `gemini_classifications` es opcional: si no se pasa, el enrichment
        opera con menos evidencia pero sigue produciendo veredictos válidos
        a partir de Codex INS, OFF, KB y políticas CAA.
        """
        if start_time is None:
            start_time = time.time()
        # gemini_calls=0 por default. El entry-point `run()` lo sube a 1 al
        # ejecutar la Fase 1 paga; el harness de evaluación lo deja en 0.
        stats = PipelineStats(gemini_calls=0)

        # ── FASE 2: Parser estructural ──
        logger.info("FASE 2: Parser estructural argentino")
        parsed_list: List[ParsedIngredient] = parse_ingredient_list(ingredients_text)
        declaration = parse_allergen_declaration(allergen_text or "")
        logger.info(
            f"Parser: {len(parsed_list)} ingredientes, "
            f"{sum(1 for p in parsed_list if p.is_flavoring)} aromatizantes, "
            f"declaración: contains={declaration.contains}, "
            f"may_contain={declaration.may_contain}"
        )

        stats.total_ingredients = len(parsed_list)
        stats.total_flavorings = sum(1 for p in parsed_list if p.is_flavoring)

        # ── FASE 3: Resolución por declaración legal ──
        logger.info("FASE 3: Resolución por declaración legal")
        legal_verdicts: Dict[str, RestrictionVerdict] = {}
        for restriction in user_restrictions:
            verdict = self._resolve_by_legal_declaration(restriction, declaration)
            if verdict is not None:
                legal_verdicts[restriction] = verdict
                stats.resolved_by_legal += 1
        logger.info(f"Resueltos por declaración legal: {list(legal_verdicts.keys())}")

        # ── FASE 4: Enrichment paralelo ──
        logger.info("FASE 4: Enrichment paralelo")
        ingredient_names_es = [p.name for p in parsed_list]
        ingredient_names_en = await translation_service.translate_batch_async(ingredient_names_es)
        translation_pairs = list(zip(ingredient_names_es, ingredient_names_en))

        ingredient_facts = await enrichment_service.enrich_batch(
            parsed=parsed_list,
            db=db,
            gemini_classifications=gemini_classifications,
            translation_pairs=translation_pairs,
        )

        # ── FASE 4.5: LLM batch fallback ──
        # Una sola llamada Gemini para todos los ingredientes que cayeron a
        # tier 5 en esta imagen. Respeta el flag LLM_FALLBACK_ENABLED y persiste
        # al KB lo que supere el threshold (futuras imágenes lo resuelven sin LLM).
        n_llm_resolved = await enrichment_service.apply_llm_batch_fallback(
            facts_list=ingredient_facts,
            parsed_list=parsed_list,
            db=db,
        )
        if n_llm_resolved:
            logger.info(f"FASE 4.5: LLM batch resolvió {n_llm_resolved} ingrediente(s)")

        # Stats se calcula DESPUÉS del batch para que resolved_by_llm refleje
        # las ingredientes que el tier 5 levantó.
        self._tally_enrichment_stats(ingredient_facts, stats)

        # ── FASE 5: Evaluación de predicados ──
        logger.info("FASE 5: Evaluación de predicados")
        for restriction in user_restrictions:
            if restriction in legal_verdicts:
                continue
            verdict = self._evaluate_predicate_for_product(restriction, ingredient_facts)
            legal_verdicts[restriction] = verdict

        # ── FASE 6: Veredicto + confianza ──
        user_verdict = all(v.apto for v in legal_verdicts.values())
        confidences = [v.confidence for v in legal_verdicts.values() if v.confidence > 0]
        overall_confidence = min(confidences) if confidences else 0.0

        stats.processing_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"PIPELINE COMPLETADO en {stats.processing_time_ms/1000:.2f}s — "
            f"user_verdict={user_verdict}, conf={overall_confidence:.2f}"
        )

        return PipelineResult(
            success=True,
            user_verdict=user_verdict,
            restrictions=legal_verdicts,
            ingredient_facts=ingredient_facts,
            declaration=declaration,
            ocr_result=None,
            overall_confidence=overall_confidence,
            stats=stats,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════════════

    def _resolve_by_legal_declaration(
        self,
        restriction: str,
        declaration: ProductLegalDeclaration,
    ) -> Optional[RestrictionVerdict]:
        """
        Aplica la autoridad de la declaración legal sobre una restricción.
        Política: tanto CONTIENE como PUEDE CONTENER bloquean (conservador).
        """
        if declaration.declares_positive(restriction):
            return RestrictionVerdict(
                apto=True,
                motivo=f"Declaración positiva del fabricante: {restriction}",
                fuente="legal_declaration",
                confidence=0.99,
            )

        allergen_set = _RESTRICTION_ALLERGEN_SETS.get(restriction)
        if allergen_set is None:
            return None

        if declaration.declares_in_contains(allergen_set):
            matched = declaration.matched_allergens(allergen_set)
            return RestrictionVerdict(
                apto=False,
                motivo=f"Declaración legal CONTIENE: {', '.join(sorted(matched))}",
                fuente="legal_declaration",
                confidence=0.99,
            )
        if declaration.declares_any(allergen_set):
            matched = declaration.matched_allergens(allergen_set)
            return RestrictionVerdict(
                apto=False,
                motivo=f"Declaración legal PUEDE CONTENER: {', '.join(sorted(matched))}",
                fuente="legal_declaration",
                confidence=0.95,
            )
        return None

    def _evaluate_predicate_for_product(
        self,
        restriction: str,
        ingredient_facts: List[IngredientFacts],
    ) -> RestrictionVerdict:
        """
        Aplica el predicado de la restricción a cada ingrediente.
        El producto es apto si todos los ingredientes pasan.
        """
        confidences: List[float] = []
        for f in ingredient_facts:
            result: PredicateResult = evaluate_restriction(restriction, f)
            confidences.append(result.confidence)
            if not result.apto:
                return RestrictionVerdict(
                    apto=False,
                    motivo=f"{f.name_es}: {result.motivo}",
                    fuente="ingredient_analysis",
                    confidence=result.confidence,
                    ingrediente_disparador=f.name_es,
                )
        min_conf = min(confidences) if confidences else 0.0
        return RestrictionVerdict(
            apto=True,
            fuente="ingredient_analysis",
            confidence=min_conf,
        )

    @staticmethod
    def _tally_enrichment_stats(
        facts_list: List[IngredientFacts], stats: PipelineStats
    ) -> None:
        for f in facts_list:
            if "codex_ins" in f.sources:
                stats.resolved_by_codex += 1
            elif "off_taxonomy" in f.sources:
                stats.resolved_by_off += 1
            elif "kb_cache" in f.sources:
                stats.resolved_by_kb += 1
            elif "gemini" in f.sources:
                stats.resolved_by_gemini += 1
            elif "llm_fallback" in f.sources:
                stats.resolved_by_llm += 1
            elif "policy_caa" in f.sources:
                stats.resolved_by_policy += 1
            else:
                stats.unresolved += 1

    # ═══════════════════════════════════════════════════════════════════════
    # Persistencia
    # ═══════════════════════════════════════════════════════════════════════

    async def persist_results(
        self,
        db: Session,
        pipeline_result: "PipelineResult",
        history_id: int,
        image_data: bytes,
        image_type: str,
    ) -> int:
        """
        Persiste el producto, sus ingredientes y actualiza la KB.
        Retorna el ID del producto creado.
        """
        from app.models import Product, ProductIngredient
        from app.services.knowledge_base_service import knowledge_base_service

        ocr = pipeline_result.ocr_result
        restrictions = pipeline_result.restrictions
        facts_list = pipeline_result.ingredient_facts
        declaration = pipeline_result.declaration
        stats = pipeline_result.stats

        def _restriction_field(name: str, attr: str):
            v = restrictions.get(name)
            if v is None:
                return None
            return getattr(v, attr)

        result_payload = {
            "user_verdict": pipeline_result.user_verdict,
            "restrictions": {
                r: {
                    "apto": v.apto,
                    "motivo": v.motivo,
                    "fuente": v.fuente,
                    "confidence": v.confidence,
                    "ingrediente_disparador": v.ingrediente_disparador,
                }
                for r, v in restrictions.items()
            },
            "ingredients": [
                {
                    "name_es": f.name_es,
                    "name_en": f.name_en,
                    "category": f.category.value,
                    "origin": f.origin.value,
                    "function_tag": f.function_tag,
                    "codex_ins_code": f.codex_ins_code,
                    "is_flavoring": f.is_flavoring(),
                    "flavoring_type": f.flavoring_type.value if f.flavoring_type else None,
                    "target_sensory": f.target_sensory,
                    "allergens": sorted(f.allergens),
                    "contains": sorted(f.contains),
                    "derived_from": sorted(f.derived_from),
                    "confidence": f.confidence,
                    "sources": f.sources,
                    "description_es": f.description_es,
                }
                for f in facts_list
            ],
            "declaration": {
                "contains": sorted(declaration.contains) if declaration else [],
                "may_contain": sorted(declaration.may_contain) if declaration else [],
                "positive_claims": sorted(declaration.positive_claims) if declaration else [],
                "raw_text": declaration.raw_text if declaration else None,
            },
            "overall_confidence": pipeline_result.overall_confidence,
        }

        nuevo_producto = Product(
            history_id=history_id,
            image=image_data,
            image_type=image_type,
            ocr_result_json=json.dumps({
                "ingredients": ocr.ingredients if ocr else [],
                "allergen_warnings": ocr.allergen_warnings if ocr else "",
                "confidence": ocr.confidence if ocr else 0.0,
            }),
            extracted_ingredients=json.dumps(ocr.ingredients if ocr else []),
            allergen_warnings=(declaration.raw_text if declaration else None) or (ocr.allergen_warnings if ocr else None),
            ocr_confidence=ocr.confidence if ocr else 0.0,
            is_tacc_safe=_restriction_field("sin_tacc", "apto"),
            tacc_reason=_restriction_field("sin_tacc", "motivo"),
            is_lactose_safe=_restriction_field("sin_lactosa", "apto"),
            lactose_reason=_restriction_field("sin_lactosa", "motivo"),
            is_nut_safe=_restriction_field("sin_frutos_secos", "apto"),
            nut_reason=_restriction_field("sin_frutos_secos", "motivo"),
            is_vegan_safe=_restriction_field("vegano", "apto"),
            vegan_reason=_restriction_field("vegano", "motivo"),
            overall_confidence=pipeline_result.overall_confidence,
            processing_time_ms=stats.processing_time_ms,
            result_json=json.dumps(result_payload),
            is_suitable=pipeline_result.user_verdict,
            processing_status="completed",
        )
        db.add(nuevo_producto)
        db.flush()

        for f in facts_list:
            kb_safety = self._kb_safety_from_facts(f)
            try:
                kb_ing = knowledge_base_service.save_ingredient(
                    db=db,
                    name_es=f.name_es,
                    name_en=f.name_en,
                    category="ADITIVO" if f.category.value == "ADITIVO" else "BASE",
                    origin=f.origin.value if f.origin else None,
                    function_tag=f.function_tag,
                    description_es=f.description_es,
                    is_tacc_safe=kb_safety["is_tacc_safe"],
                    is_lactose_safe=kb_safety["is_lactose_safe"],
                    is_nut_safe=kb_safety["is_nut_safe"],
                    is_vegan_safe=kb_safety["is_vegan_safe"],
                    confidence=f.confidence,
                    resolved_by=f.sources[0] if f.sources else "unresolved",
                )
            except Exception as e:
                logger.warning(f"No se pudo persistir KB para '{f.name_es}': {e}")
                kb_ing = None

            pi = ProductIngredient(
                product_id=nuevo_producto.id,
                ingredient_id=kb_ing.id if kb_ing else None,
                detected_name=f.name_es,
                name_en=f.name_en,
                is_base_ingredient=(f.category.value == "BASE"),
                resolved_by=f.sources[0] if f.sources else "unresolved",
                confidence=f.confidence,
                evidence_json=json.dumps([
                    {"source": p.source, "evidence": p.evidence, "confidence": p.confidence}
                    for entries in f.tag_provenance.values() for p in entries
                ]),
            )
            db.add(pi)

        db.commit()
        return nuevo_producto.id

    @staticmethod
    def _kb_safety_from_facts(f: IngredientFacts) -> Dict[str, Optional[bool]]:
        gluten_derived = {"wheat", "barley", "rye", "oats"}
        dairy_derived = {"milk", "dairy"}
        is_tacc_safe = not (
            bool(f.allergens & GLUTEN_SOURCES) or bool(f.derived_from & gluten_derived)
        )
        is_lactose_safe = not (
            bool(f.allergens & DAIRY_SOURCES) or bool(f.derived_from & dairy_derived)
        )
        is_nut_safe = not bool(f.allergens & NUT_SOURCES)
        from app.services.ingredient_facts import Origin
        is_vegan_safe = not (
            bool(f.allergens & ANIMAL_SOURCES) or f.origin == Origin.ANIMAL
        )
        return {
            "is_tacc_safe": is_tacc_safe,
            "is_lactose_safe": is_lactose_safe,
            "is_nut_safe": is_nut_safe,
            "is_vegan_safe": is_vegan_safe,
        }


analysis_pipeline = AnalysisPipeline()
