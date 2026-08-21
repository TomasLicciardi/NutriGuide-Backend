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
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

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
    Origin,
    ProductLegalDeclaration,
    allergens_es,
)
from app.services.ingredient_explanations import explain_ingredient

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
# Cross-check OCR ↔ ingredientes
# ═══════════════════════════════════════════════════════════════════════════
#
# Mapeo alérgeno canónico → raíces que cuentan como evidencia en la lista de
# ingredientes. Usado para detectar declaraciones legales no corroboradas
# (caso típico: OCR alucina "CONTIENE GLUTEN" cuando ningún ingrediente lo
# justifica). El match es por substring sobre texto sin acentos.
#
# Política: solo se aplica a `contains`. "PUEDE CONTENER" indica contaminación
# cruzada por línea de producción compartida y NO requiere sustento en
# ingredientes — un cross-check ahí daría falsos positivos sistemáticos.

_ALLERGEN_INGREDIENT_KEYWORDS: Dict[str, Set[str]] = {
    "gluten":    {"trigo", "wheat", "cebada", "barley", "centeno", "rye",
                  "avena", "oat", "malta", "malt", "harina", "flour",
                  "semola", "semolina", "espelta", "spelt", "kamut", "triticale"},
    "wheat":     {"trigo", "wheat", "harina", "semola", "semolina"},
    "barley":    {"cebada", "barley", "malta", "malt"},
    "rye":       {"centeno", "rye"},
    "oats":      {"avena", "oat", "oats"},
    "milk":      {"leche", "milk", "lacteo", "lactico", "queso", "cheese",
                  "suero", "whey", "caseina", "casein", "manteca",
                  "mantequilla", "butter", "crema", "cream", "yogur",
                  "yogurt", "kefir", "ricotta", "nata", "buttermilk"},
    "lactose":   {"leche", "milk", "lactosa", "lactose", "suero", "queso",
                  "lacteo"},
    "dairy":     {"leche", "milk", "lacteo", "queso", "manteca", "crema",
                  "cream", "yogur", "yogurt", "ricotta", "nata", "caseina",
                  "caseinato", "suero", "lactosuero", "lactosa"},
    "peanut":    {"mani", "peanut", "cacahuete", "cacahuate", "groundnut"},
    "tree-nut":  {"almendra", "almond", "nuez", "walnut", "avellana",
                  "hazelnut", "pistacho", "pistachio", "castana", "cashew",
                  "anacardo", "macadamia", "pecan", "brasil", "brazil",
                  "pinon", "pine nut"},
    "soy":       {"soja", "soy", "soya", "edamame", "tofu", "tempeh"},
    "egg":       {"huevo", "egg", "albumina", "albumin", "yema", "yolk",
                  "ovoalbumina"},
    "fish":      {"pescado", "fish", "atun", "tuna", "merluza", "hake",
                  "salmon", "anchoa", "anchovy", "sardina", "sardine",
                  "bacalao", "cod"},
    "shellfish": {"marisco", "shellfish", "camaron", "shrimp", "langostino",
                  "langostina", "cangrejo", "crab", "langosta", "lobster",
                  "mejillon", "mussel", "almeja", "clam", "ostra", "oyster",
                  "calamar", "squid"},
    "sesame":    {"sesamo", "sesame", "ajonjoli", "tahini", "tahine"},
    "sulfites":  {"sulfito", "sulfite", "metabisulfito", "metabisulfite",
                  "bisulfito", "bisulfite", "anhidrido sulfuroso",
                  "sulphur dioxide"},
    "honey":     {"miel", "honey"},
}


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if unicodedata.category(c) != "Mn"
    )


# Confianzas reducidas cuando una declaración no está corroborada por ningún
# ingrediente de la lista. No descartamos la declaración (puede ser contaminación
# cruzada legítima por línea compartida) pero bajamos la confianza del veredicto
# y exponemos un warning auditable.
_CONF_LEGAL_CONTAINS_SUPPORTED = 0.99
_CONF_LEGAL_CONTAINS_UNSUPPORTED = 0.70


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
    resolved_by_pubchem: int = 0
    resolved_by_gemini: int = 0
    resolved_by_llm: int = 0
    resolved_by_policy: int = 0
    unresolved: int = 0
    gemini_calls: int = 1
    processing_time_ms: float = 0.0


@dataclass
class TriggerIngredient:
    """
    Ingrediente concreto de la etiqueta que justifica el bloqueo de una
    restricción. Sirve para explicar al usuario *qué* nombre técnico
    encontrado en la lista es el responsable y *qué significa*.
    """
    name: str               # nombre como aparece en la etiqueta ("Albúmina")
    explanation: str        # explicación legible ("proteína de la clara de huevo")
    allergen: str           # alérgeno en español que disparó el match ("huevo")


@dataclass
class RestrictionVerdict:
    apto: bool
    motivo: Optional[str] = None
    fuente: str = "ingredient_analysis"  # legal_declaration | ingredient_analysis | flavoring_policy
    confidence: float = 1.0
    ingrediente_disparador: Optional[str] = None
    trigger_ingredients: List[TriggerIngredient] = field(default_factory=list)


@dataclass
class PipelineResult:
    success: bool
    user_verdict: bool = True
    restrictions: Dict[str, RestrictionVerdict] = field(default_factory=dict)
    ingredient_facts: List[IngredientFacts] = field(default_factory=list)
    declaration: Optional[ProductLegalDeclaration] = None
    declaration_warnings: List[str] = field(default_factory=list)
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
            # Mapeo de error_type → HTTP status:
            #   - poor_quality / invalid_image  → 400 (problema del input del usuario)
            #   - quota_exhausted_daily         → 429 (Too Many Requests, semántica correcta;
            #                                          permite que el frontend muestre el
            #                                          modal de "Límite de solicitudes")
            #   - resto (timeout, parse_failed) → 500
            if ocr_result.error in ("poor_quality", "invalid_image"):
                status = 400
            elif ocr_result.error == "quota_exhausted_daily":
                status = 429
            else:
                status = 500
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
        result.stats.gemini_calls += 1  # +1 por el OCR (run_from_text ya contó el LLM batch)
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

        # ── FASE 2.5: Cross-check OCR ↔ ingredientes ──
        # Detecta alérgenos declarados en CONTIENE que no tienen ningún
        # ingrediente que los justifique (típica alucinación del OCR LLM).
        unsupported_contains = self._cross_check_declaration(parsed_list, declaration)
        declaration_warnings: List[str] = []
        if unsupported_contains:
            warning = (
                f"La etiqueta declara contener {allergens_es(unsupported_contains)}, "
                f"pero ningún ingrediente de la lista lo confirma."
            )
            declaration_warnings.append(warning)
            logger.warning(
                f"Cross-check: declaración no corroborada {sorted(unsupported_contains)}"
            )

        # ── FASE 3: Resolución por declaración legal ──
        logger.info("FASE 3: Resolución por declaración legal")
        legal_verdicts: Dict[str, RestrictionVerdict] = {}
        for restriction in user_restrictions:
            verdict = self._resolve_by_legal_declaration(
                restriction, declaration, unsupported_contains
            )
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

        # ── FASE 4.4: PubChem fallback (compuestos químicos no resueltos) ──
        # Corre antes del LLM: cada compuesto que PubChem identifica es una
        # clasificación que Gemini ya no hace → ahorro de cuota. Sin API key.
        n_pubchem_resolved = await enrichment_service.apply_pubchem_fallback(
            facts_list=ingredient_facts,
            parsed_list=parsed_list,
            db=db,
        )
        if n_pubchem_resolved:
            logger.info(f"FASE 4.4: PubChem resolvió {n_pubchem_resolved} ingrediente(s)")

        # ── FASE 4.5: LLM batch fallback ──
        # Una sola llamada Gemini para todos los ingredientes que cayeron a
        # tier 5 en esta imagen. Respeta el flag LLM_FALLBACK_ENABLED y persiste
        # al KB lo que supere el threshold (futuras imágenes lo resuelven sin LLM).
        # Contabilizamos la llamada del LLM batch ANTES de ejecutarla: después,
        # los ingredientes resueltos ya no matchean el predicado y el conteo daría 0.
        if enrichment_service.will_call_llm(ingredient_facts):
            stats.gemini_calls += 1
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

        # ── FASE 5.5: Trigger ingredients ──
        # Para cada restricción bloqueada, listamos los ingredientes concretos
        # de la etiqueta que la justifican, con su explicación legible.
        # Esto da contexto educativo al usuario (qué nombre técnico = qué).
        for restriction, verdict in legal_verdicts.items():
            if verdict.apto:
                continue
            verdict.trigger_ingredients = self._find_trigger_ingredients(
                restriction, ingredient_facts
            )

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
            declaration_warnings=declaration_warnings,
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
        unsupported_contains: Set[str],
    ) -> Optional[RestrictionVerdict]:
        """
        Aplica la autoridad de la declaración legal sobre una restricción.
        Política: tanto CONTIENE como PUEDE CONTENER bloquean (conservador).

        Si los alérgenos que disparan el match están en `unsupported_contains`
        (declaración no corroborada por ningún ingrediente visible), la
        confianza del veredicto se reduce y el motivo lo aclara. Sigue
        bloqueando porque la declaración puede ser contaminación cruzada
        legítima.
        """
        if declaration.declares_positive(restriction):
            return RestrictionVerdict(
                apto=True,
                motivo=f"Declaración positiva del fabricante: {restriction}",
                fuente="legal_declaration",
                confidence=_CONF_LEGAL_CONTAINS_SUPPORTED,
            )

        allergen_set = _RESTRICTION_ALLERGEN_SETS.get(restriction)
        if allergen_set is None:
            return None

        if declaration.declares_in_contains(allergen_set):
            matched = declaration.matched_allergens(allergen_set) & declaration.contains
            all_unsupported = bool(matched) and matched.issubset(unsupported_contains)
            confidence = (
                _CONF_LEGAL_CONTAINS_UNSUPPORTED if all_unsupported
                else _CONF_LEGAL_CONTAINS_SUPPORTED
            )
            note = (
                " (declaración no corroborada por ingredientes visibles)"
                if all_unsupported else ""
            )
            return RestrictionVerdict(
                apto=False,
                motivo=f"Declaración legal CONTIENE: {allergens_es(matched)}{note}",
                fuente="legal_declaration",
                confidence=confidence,
            )
        if declaration.declares_any(allergen_set):
            matched = declaration.matched_allergens(allergen_set)
            return RestrictionVerdict(
                apto=False,
                motivo=f"Declaración legal PUEDE CONTENER: {allergens_es(matched)}",
                fuente="legal_declaration",
                confidence=0.95,
            )
        return None

    @staticmethod
    def _cross_check_declaration(
        parsed_list: List[ParsedIngredient],
        declaration: ProductLegalDeclaration,
    ) -> Set[str]:
        """
        Verifica si cada alérgeno declarado en CONTIENE tiene al menos un
        ingrediente que lo justifique. Retorna el set de alérgenos NO
        corroborados.

        Solo aplica a `contains` — los "PUEDE CONTENER" indican contaminación
        cruzada y no es esperable que el alérgeno aparezca en la lista.
        """
        if not declaration.contains:
            return set()

        ingredient_text = _strip_accents(
            " ".join(p.name or "" for p in parsed_list).lower()
        )

        unsupported: Set[str] = set()
        for allergen in declaration.contains:
            keywords = _ALLERGEN_INGREDIENT_KEYWORDS.get(allergen)
            if not keywords:
                # Alérgeno sin keywords definidas — no podemos verificar,
                # asumimos corroborado (no penalizamos).
                continue
            supported = any(
                _strip_accents(kw.lower()) in ingredient_text for kw in keywords
            )
            if not supported:
                unsupported.add(allergen)
        return unsupported

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
    def _find_trigger_ingredients(
        restriction: str,
        ingredient_facts: List[IngredientFacts],
    ) -> List[TriggerIngredient]:
        """
        Devuelve la lista de ingredientes de la etiqueta que justifican el
        bloqueo de una restricción. Útil para mostrarle al usuario *qué*
        nombre técnico encontrado en la lista es el responsable.

        Cobertura — replica la lógica del predicado:
          - Allergens del ingrediente que intersectan el allergen_set de la
            restricción.
          - Para "vegano": también incluye ingredientes con origin=ANIMAL
            aunque no tengan allergen tag específico (ej. "miel" cuando solo
            está tagueada como animal sin honey-allergen).
        """
        allergen_set = _RESTRICTION_ALLERGEN_SETS.get(restriction)
        if not allergen_set:
            return []

        seen_names: Set[str] = set()
        triggers: List[TriggerIngredient] = []
        for facts in ingredient_facts:
            matched = facts.allergens & allergen_set
            # Etiqueta visible al usuario — siempre en español.
            allergen_label = allergens_es(matched) if matched else None

            if not matched and restriction == "vegano" and facts.origin == Origin.ANIMAL:
                allergen_label = "origen animal"
            elif not matched:
                continue

            key = facts.name_es.strip().lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            triggers.append(TriggerIngredient(
                name=facts.name_es.strip(),
                explanation=explain_ingredient(facts),
                allergen=allergen_label or "",
            ))
        return triggers

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
            elif "pubchem" in f.sources:
                stats.resolved_by_pubchem += 1
            elif "gemini" in f.sources:
                stats.resolved_by_gemini += 1
            elif "llm_fallback" in f.sources:
                stats.resolved_by_llm += 1
            elif "policy_caa" in f.sources or "contextual_override" in f.sources:
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
                    "trigger_ingredients": [
                        {
                            "name": t.name,
                            "explanation": t.explanation,
                            "allergen": t.allergen,
                        }
                        for t in v.trigger_ingredients
                    ],
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
