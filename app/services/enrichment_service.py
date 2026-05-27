# app/services/enrichment_service.py
"""
Enrichment Service — Fase 4 del pipeline v3.

Convierte ParsedIngredient en IngredientFacts consultando todas las fuentes
en paralelo y fusionando resultados con provenance trackeado.

Fuentes consultadas (en paralelo, por ingrediente):
  1. KB cache local (resultados de análisis previos)
  2. Codex INS DB (si tiene código INS)
  3. OFF taxonomy (búsqueda por nombre en inglés)
  4. PubChem (fallback para químicos no reconocidos)
  5. Pre-clasificación de Gemini (del OCR original)
  6. Política CAA explícita (para aromatizantes)

La fusión sigue confianza decreciente: cada tag conserva el valor de la
fuente más confiable que lo aportó.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config.image_analysis_config import KB_CONFIG
from app.core.config import settings
from app.services.llm_fallback_service import LLMClassification, llm_fallback_service
from app.services.ingredient_facts import (
    ANIMAL_SOURCES,
    DAIRY_SOURCES,
    FlavoringType,
    GLUTEN_SOURCES,
    HIGH_RISK_FLAVORING_TARGETS,
    IngredientCategory,
    IngredientFacts,
    NUT_SOURCES,
    Origin,
    TagProvenance,
)
from app.services.canonicalization_service import canonicalization_service
from app.services.contextual_overrides import apply_override, resolve_ambiguous_term
from app.services.parser import ParsedIngredient
from app.services.loaders import codex_ins_loader, off_taxonomy_loader

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Confianzas por fuente (jerarquía de autoridad)
# ═══════════════════════════════════════════════════════════════════════════

_CONFIDENCE_BY_SOURCE = {
    "codex_ins":           0.94,
    "off_taxonomy":        0.85,
    "kb_cache":            0.93,
    "pubchem":             0.75,
    "gemini":              0.65,
    "llm_fallback":        0.70,
    "policy_caa":          0.92,
    "parser":              0.80,
    "zero_shot":           0.70,
    "legal_declaration":   0.99,
    "contextual_override": 0.92,
}


# ═══════════════════════════════════════════════════════════════════════════
# Servicio de enrichment
# ═══════════════════════════════════════════════════════════════════════════


def _map_origin(raw_origin: Optional[str]) -> Origin:
    if not raw_origin:
        return Origin.UNKNOWN
    value = raw_origin.lower().strip()
    return {
        "vegetal": Origin.PLANT,
        "plant": Origin.PLANT,
        "animal": Origin.ANIMAL,
        "sintetico": Origin.SYNTHETIC,
        "synthetic": Origin.SYNTHETIC,
        "mineral": Origin.MINERAL,
        "natural_extract": Origin.NATURAL_EXTRACT,
        "desconocido": Origin.UNKNOWN,
        "unknown": Origin.UNKNOWN,
    }.get(value, Origin.UNKNOWN)


def _is_unusable_translation(value: Optional[str]) -> bool:
    if not value:
        return True
    normalized = value.strip().lower().strip(".")
    return normalized in {
        "",
        "i'm sorry",
        "sorry",
        "lo siento",
        "disculpa",
    }


class EnrichmentService:
    """Construye IngredientFacts consultando fuentes en paralelo."""

    async def enrich_batch(
        self,
        parsed: List[ParsedIngredient],
        db: Session,
        gemini_classifications: Optional[Dict[str, "GeminiIngredientClassification"]] = None,
        translation_pairs: Optional[List[Tuple[str, str]]] = None,
    ) -> List[IngredientFacts]:
        """
        Enriquece una lista de ParsedIngredient en paralelo.

        gemini_classifications: pre-clasificación opcional de Gemini desde
                                el OCR (peso bajo, fallback).
        translation_pairs: pares (es, en) para lookup en OFF (en inglés).
        """
        if not parsed:
            return []

        gemini_classifications = gemini_classifications or {}
        translation_map = dict(translation_pairs or [])
        ctx_names = [p.name for p in parsed]

        coros = [
            self.enrich_one(
                p,
                db,
                gemini_class=gemini_classifications.get(p.name) or gemini_classifications.get(p.raw_text),
                name_en=translation_map.get(p.name),
                context=ctx_names,
            )
            for p in parsed
        ]

        results = await asyncio.gather(*coros, return_exceptions=True)

        enriched: List[IngredientFacts] = []
        for p, r in zip(parsed, results):
            if isinstance(r, Exception):
                logger.warning(f"Enrichment falló para '{p.name}': {r}")
                enriched.append(self._minimal_facts(p))
            else:
                enriched.append(r)

        return enriched

    async def enrich_one(
        self,
        parsed: ParsedIngredient,
        db: Session,
        gemini_class=None,
        name_en: Optional[str] = None,
        context: Optional[List[str]] = None,
    ) -> IngredientFacts:
        """Construye un IngredientFacts para un ingrediente."""
        canonical = canonicalization_service.canonicalize(parsed)
        lookup_name_es = canonical.canonical_name_es or parsed.name
        lookup_name_en = canonical.canonical_name_en or name_en
        if parsed.codex_ins_code is not None and _is_unusable_translation(lookup_name_en):
            lookup_name_en = parsed.name or f"INS {parsed.codex_ins_code}{parsed.codex_ins_subcode or ''}"

        facts = IngredientFacts(
            name_es=parsed.name,
            name_en=lookup_name_en,
        )
        if parsed.codex_ins_code is not None:
            facts.codex_ins_code = parsed.codex_ins_code
            facts.codex_ins_subcode = parsed.codex_ins_subcode
            facts.category = IngredientCategory.ADITIVO

        if canonical.changed:
            prov = TagProvenance(
                source="canonicalization",
                confidence=canonical.confidence,
                evidence="; ".join(canonical.evidence),
            )
            facts._record_provenance(f"canonical:{lookup_name_es}", prov)

        if parsed.is_flavoring:
            self._apply_flavoring_policy(facts, parsed)
            return facts

        if parsed.is_ley_25630_block:
            self._apply_ley_25630_policy(facts)

        # Override contextual para términos ambiguos (ej: "burro" en yerba
        # mate). Se aplica ANTES de KB/Codex/OFF: si dispara, es autoritativo
        # y se salta el lookup externo que mete el falso positivo.
        override = resolve_ambiguous_term(parsed.name, context)
        if override is not None:
            apply_override(facts, override)
            logger.info(
                f"Contextual override: '{parsed.name}' -> "
                f"{override.canonical_name_es} (matched: {override.matched_context_terms})"
            )
            return facts

        if parsed.function_tag:
            facts.function_tag = parsed.function_tag
            facts.category = (
                IngredientCategory.ADITIVO
                if parsed.function_tag != "base"
                else IngredientCategory.BASE
            )

        codex_task = self._lookup_codex(parsed)
        kb_task = self._lookup_kb_candidates(canonical.candidates_es, db)
        off_task = self._lookup_off_candidates(
            [n for n in (lookup_name_en, name_en, lookup_name_es, parsed.name) if n]
        )

        codex_result, kb_result, off_result = await asyncio.gather(
            codex_task, kb_task, off_task, return_exceptions=True
        )

        if isinstance(codex_result, Exception):
            codex_result = None
        if isinstance(kb_result, Exception):
            kb_result = None
        if isinstance(off_result, Exception):
            off_result = None

        if kb_result is not None:
            self._apply_kb_facts(facts, kb_result)
        if codex_result is not None:
            self._apply_codex_entry(facts, codex_result)
        if off_result is not None:
            self._apply_off_entry(facts, off_result)
        if gemini_class is not None:
            self._apply_gemini_classification(facts, gemini_class)

        if facts.confidence == 0.0:
            facts.confidence = self._compute_confidence(facts)

        if facts.category == IngredientCategory.UNKNOWN:
            facts.category = (
                IngredientCategory.ADITIVO
                if (facts.codex_ins_code or facts.function_tag)
                else IngredientCategory.BASE
            )

        # IMPORTANTE: el tier 5 LLM ya NO se invoca per-ingrediente acá.
        # El orquestador del pipeline (analysis_pipeline) llama a
        # apply_llm_batch_fallback() después de procesar todos los ingredientes
        # del producto, así un solo análisis = una sola llamada Gemini para
        # los N ingredientes que cayeron a tier 5. Ver razonamiento en el
        # método apply_llm_batch_fallback más abajo.
        return facts

    async def apply_llm_batch_fallback(
        self,
        facts_list: List[IngredientFacts],
        parsed_list: List[ParsedIngredient],
        db: Session,
    ) -> int:
        """
        Tier 5 a nivel de imagen — UNA llamada Gemini para todos los
        ingredientes del producto que quedaron sin origen tras tiers 1-4.

        Por qué batch y no per-ingrediente:
          - El usuario toma 1 foto que tiene M ingredientes; con cuota free
            tier de Gemini (~20 RPM), llamar por cada uno agota la cuota muy
            rápido cuando hay varias fotos seguidas.
          - Una llamada con todos los unresolved consume 1 unidad de RPM
            independiente de M, y el LLM puede usar el contexto cruzado entre
            ingredientes para mejor desambiguación.

        Modifica `facts_list` in-place para los ingredientes que el LLM
        resolvió con confianza ≥ threshold y los persiste al KB.
        Retorna la cantidad de ingredientes resueltos.
        """
        if not settings.LLM_FALLBACK_ENABLED or not facts_list:
            return 0

        indices = [i for i, f in enumerate(facts_list) if self._should_use_llm_fallback(f)]
        if not indices:
            return 0

        items: List[Tuple[str, Optional[str]]] = [
            (facts_list[i].name_es, facts_list[i].name_en) for i in indices
        ]
        # Contexto = todos los ingredientes parseados, separados por coma.
        context_str = ", ".join(p.name for p in parsed_list if p.name)

        results = await llm_fallback_service.classify_batch(items, context_str)

        threshold = max(0.70, float(KB_CONFIG["min_write_confidence"]))
        applied = 0
        for idx, result in zip(indices, results):
            if result is None or result.confidence < threshold:
                continue
            self._apply_llm_classification(facts_list[idx], result)
            await self._save_to_kb(facts_list[idx], result, db)
            applied += 1
        return applied

    # ═══════════════════════════════════════════════════════════════════════
    # Aplicación de fuentes individuales
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _should_use_llm_fallback(facts: IngredientFacts) -> bool:
        """True si el ingrediente caeria en default-unsafe sin otro dato."""
        if not settings.LLM_FALLBACK_ENABLED:
            return False
        if facts.is_flavoring():
            return False
        if facts.category not in (IngredientCategory.BASE, IngredientCategory.UNKNOWN):
            return False
        return facts.origin == Origin.UNKNOWN

    @staticmethod
    def _context_string(name_es: str, context: Optional[List[str]]) -> str:
        if not context:
            return ""
        normalized_current = (name_es or "").strip().lower()
        others = [
            name
            for name in context
            if name and name.strip().lower() != normalized_current
        ]
        return ", ".join(others)

    def _apply_llm_classification(
        self,
        facts: IngredientFacts,
        llm_result: LLMClassification,
    ) -> None:
        prov = TagProvenance(
            source="llm_fallback",
            confidence=llm_result.confidence,
            evidence=llm_result.reasoning,
        )

        facts.category = llm_result.category
        facts.origin = llm_result.origin
        facts.function_tag = llm_result.function_tag or facts.function_tag
        facts.description_es = llm_result.description_es or facts.description_es
        facts.confidence = max(facts.confidence, llm_result.confidence)

        facts._record_provenance("source:llm_fallback", prov)
        facts._record_provenance(f"category:{llm_result.category.value}", prov)
        facts._record_provenance(f"origin:{llm_result.origin.value}", prov)
        if llm_result.function_tag:
            facts._record_provenance(f"function:{llm_result.function_tag}", prov)

        for allergen in llm_result.allergens:
            facts.add_allergen(allergen, prov)
        for substance in llm_result.contains:
            facts.add_contains(substance, prov)
        for source in llm_result.derived_from:
            facts.add_derived_from(source, prov)

    async def _save_to_kb(
        self,
        facts: IngredientFacts,
        llm_result: LLMClassification,
        db: Session,
    ) -> None:
        threshold = max(0.70, float(KB_CONFIG["min_write_confidence"]))
        if llm_result.confidence < threshold:
            return

        try:
            from app.services.knowledge_base_service import knowledge_base_service

            safety = self._kb_safety_flags(facts)
            category = "ADITIVO" if facts.category == IngredientCategory.ADITIVO else "BASE"
            knowledge_base_service.save_ingredient(
                db=db,
                name_es=facts.name_es,
                name_en=facts.name_en,
                category=category,
                origin=facts.origin.value if facts.origin else None,
                function_tag=facts.function_tag,
                description_es=facts.description_es,
                is_tacc_safe=safety["is_tacc_safe"],
                is_lactose_safe=safety["is_lactose_safe"],
                is_nut_safe=safety["is_nut_safe"],
                is_vegan_safe=safety["is_vegan_safe"],
                confidence=llm_result.confidence,
                resolved_by="llm_fallback",
                provenance="llm_fallback",
            )
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(
                f"No se pudo persistir fallback LLM para '{facts.name_es}': "
                f"{type(e).__name__}: {e}"
            )

    @staticmethod
    def _kb_safety_flags(facts: IngredientFacts) -> Dict[str, bool]:
        gluten_sources = {"wheat", "barley", "rye", "oats"}
        dairy_sources = {"milk", "dairy"}

        is_tacc_safe = not (
            facts.allergens_intersect(GLUTEN_SOURCES)
            or facts.derived_from_any(gluten_sources)
        )
        is_lactose_safe = not (
            facts.allergens_intersect(DAIRY_SOURCES)
            or facts.derived_from_any(dairy_sources)
        )
        is_nut_safe = not facts.allergens_intersect(NUT_SOURCES)
        is_vegan_safe = not (
            facts.origin == Origin.ANIMAL
            or facts.allergens_intersect(ANIMAL_SOURCES)
        )
        return {
            "is_tacc_safe": is_tacc_safe,
            "is_lactose_safe": is_lactose_safe,
            "is_nut_safe": is_nut_safe,
            "is_vegan_safe": is_vegan_safe,
        }

    def _apply_flavoring_policy(self, facts: IngredientFacts, parsed: ParsedIngredient) -> None:
        """
        Aromatizantes: política basada en CAA Cap. XVIII Art. 1383.
        El target_sensory NO se trata como ingrediente; los predicados lo manejan.
        """
        facts.category = IngredientCategory.FLAVORING
        facts.function_tag = "saborizante"
        facts.flavoring_type = parsed.flavoring_type or FlavoringType.UNSPECIFIED
        facts.target_sensory = parsed.target_sensory

        if facts.flavoring_type in (FlavoringType.ARTIFICIAL, FlavoringType.IDENTICAL_TO_NATURAL):
            facts.origin = Origin.SYNTHETIC
            confidence = _CONFIDENCE_BY_SOURCE["policy_caa"]
            evidence = (
                f"CAA Cap. XVIII: aromatizante {facts.flavoring_type.value} "
                f"(target sensorial: {facts.target_sensory or 'genérico'}) "
                f"clasificado como sintético"
            )
        elif facts.flavoring_type == FlavoringType.NATURAL:
            facts.origin = Origin.NATURAL_EXTRACT
            confidence = 0.78
            evidence = (
                f"CAA Cap. XVIII: aromatizante natural "
                f"(target: {facts.target_sensory or 'genérico'})"
            )
        else:
            facts.origin = Origin.UNKNOWN
            confidence = 0.6
            evidence = "Aromatizante sin calificador explícito"

        facts.confidence = confidence
        prov = TagProvenance(source="policy_caa", confidence=confidence, evidence=evidence)
        facts._record_provenance(f"origin:{facts.origin.value}", prov)

        if facts.target_sensory and facts.target_sensory.lower() in HIGH_RISK_FLAVORING_TARGETS:
            warning = TagProvenance(
                source="policy_caa",
                confidence=0.5,
                evidence=(
                    f"⚠ Target sensorial de alto riesgo ({facts.target_sensory}). "
                    f"Restricciones de frutos secos/maní requieren confirmación "
                    f"de la declaración legal del producto."
                ),
            )
            facts._record_provenance("flavoring:high_risk", warning)

    def _apply_ley_25630_policy(self, facts: IngredientFacts) -> None:
        """Bloque Ley 25.630 = harina de trigo enriquecida."""
        facts.category = IngredientCategory.BASE
        facts.origin = Origin.PLANT
        prov = TagProvenance(
            source="policy_caa",
            confidence=0.99,
            evidence="Bloque Ley 25.630: harina de trigo enriquecida (composición fija)",
        )
        facts.add_allergen("gluten", prov)
        facts.add_allergen("wheat", prov)
        facts.add_derived_from("wheat", prov)
        facts.confidence = 0.99

    async def _lookup_codex(self, parsed: ParsedIngredient):
        if parsed.codex_ins_code is None:
            return None
        return codex_ins_loader.lookup(parsed.codex_ins_code, parsed.codex_ins_subcode)

    async def _lookup_kb(self, name_es: str, db: Session):
        try:
            from app.services.knowledge_base_service import knowledge_base_service
            return knowledge_base_service.lookup(name_es, db)
        except Exception:
            return None

    async def _lookup_kb_candidates(self, names_es: List[str], db: Session):
        seen = set()
        for name in names_es:
            key = (name or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            result = await self._lookup_kb(name, db)
            if result is not None:
                return result
        return None

    async def _lookup_off(self, name: str):
        try:
            return await off_taxonomy_loader.lookup(name)
        except Exception:
            return None

    async def _lookup_off_candidates(self, names: List[str]):
        seen = set()
        for name in names:
            key = (name or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            result = await self._lookup_off(name)
            if result is not None and result.in_taxonomy:
                return result
        return None

    def _apply_codex_entry(self, facts: IngredientFacts, entry) -> None:
        if entry is None:
            return
        facts.codex_ins_code = entry.code
        facts.codex_ins_subcode = entry.subcode
        if entry.function_tag and not facts.function_tag:
            facts.function_tag = entry.function_tag
        if facts.origin == Origin.UNKNOWN and entry.origin != Origin.UNKNOWN:
            facts.origin = entry.origin
        facts.category = IngredientCategory.ADITIVO

        prov = entry.to_provenance()
        facts._record_provenance("source:codex_ins", prov)
        if entry.origin != Origin.UNKNOWN:
            facts._record_provenance(f"origin:{entry.origin.value}", prov)
        for a in entry.allergens:
            facts.add_allergen(a, prov)
        for c in entry.contains:
            facts.add_contains(c, prov)
        for d in entry.derived_from:
            facts.add_derived_from(d, prov)

        facts.confidence = max(facts.confidence, entry.confidence)

    def _apply_off_entry(self, facts: IngredientFacts, entry) -> None:
        if entry is None or not entry.in_taxonomy:
            return

        prov = entry.to_provenance()
        for a in entry.allergens:
            facts.add_allergen(a, prov)
        for d in entry.derived_from:
            facts.add_derived_from(d, prov)

        if facts.origin == Origin.UNKNOWN and entry.origin != Origin.UNKNOWN:
            facts.origin = entry.origin
            facts._record_provenance(f"origin:{entry.origin.value}", prov)

        facts.confidence = max(facts.confidence, entry.confidence)

    def _apply_kb_facts(self, facts: IngredientFacts, kb_entry) -> None:
        """KB del sistema viejo: Optional[IngredientResult]."""
        if kb_entry is None:
            return
        prov = TagProvenance(
            source="kb_cache",
            confidence=kb_entry.confidence or _CONFIDENCE_BY_SOURCE["kb_cache"],
            evidence=f"KB cache local (resuelto previamente por {kb_entry.resolved_by})",
        )
        facts._record_provenance("source:kb_cache", prov)

        if kb_entry.category:
            facts.category = (
                IngredientCategory.ADITIVO
                if kb_entry.category == "ADITIVO"
                else IngredientCategory.BASE
            )

        mapped_origin = _map_origin(getattr(kb_entry, "origin", None))
        if facts.origin == Origin.UNKNOWN and mapped_origin != Origin.UNKNOWN:
            facts.origin = mapped_origin
            facts._record_provenance(f"origin:{mapped_origin.value}", prov)

        if not facts.function_tag and getattr(kb_entry, "function_tag", None):
            facts.function_tag = kb_entry.function_tag

        if not facts.description_es and getattr(kb_entry, "description_es", None):
            facts.description_es = kb_entry.description_es

        if kb_entry.is_tacc_safe is False:
            for a in GLUTEN_SOURCES:
                facts.add_allergen(a, prov)
                break
        if kb_entry.is_lactose_safe is False:
            for a in DAIRY_SOURCES:
                facts.add_allergen(a, prov)
                break
        if kb_entry.is_nut_safe is False:
            for a in NUT_SOURCES:
                facts.add_allergen(a, prov)
                break
        if kb_entry.is_vegan_safe is False and facts.origin == Origin.UNKNOWN:
            facts.origin = Origin.ANIMAL
            facts._record_provenance("origin:animal", prov)

        facts.confidence = max(facts.confidence, kb_entry.confidence or 0.93)

    def _apply_gemini_classification(self, facts: IngredientFacts, gemini_class) -> None:
        """Pre-clasificación de Gemini: peso bajo, fallback."""
        if gemini_class is None:
            return
        prov = TagProvenance(
            source="gemini",
            confidence=_CONFIDENCE_BY_SOURCE["gemini"],
            evidence=f"Pre-clasificación Gemini (origin={gemini_class.origin}, fn={gemini_class.function_tag})",
        )

        if gemini_class.is_tacc_safe is False:
            facts.add_allergen("gluten", prov)
        if gemini_class.is_lactose_safe is False:
            facts.add_allergen("milk", prov)
        if gemini_class.is_nut_safe is False:
            facts.add_allergen("tree-nut", prov)
        if gemini_class.is_vegan_safe is False and facts.origin == Origin.UNKNOWN:
            facts.origin = Origin.ANIMAL
            facts._record_provenance("origin:animal", prov)

        if facts.origin == Origin.UNKNOWN and gemini_class.origin:
            origin_str = gemini_class.origin.lower()
            origin_map = {
                "vegetal": Origin.PLANT,
                "plant": Origin.PLANT,
                "animal": Origin.ANIMAL,
                "synthetic": Origin.SYNTHETIC,
                "sintetico": Origin.SYNTHETIC,
                "mineral": Origin.MINERAL,
            }
            mapped = origin_map.get(origin_str)
            if mapped:
                facts.origin = mapped
                facts._record_provenance(f"origin:{mapped.value}", prov)

        if not facts.function_tag and gemini_class.function_tag:
            facts.function_tag = gemini_class.function_tag

        if not facts.description_es and gemini_class.description_es:
            facts.description_es = gemini_class.description_es

        facts.confidence = max(facts.confidence, _CONFIDENCE_BY_SOURCE["gemini"])

    @staticmethod
    def _compute_confidence(facts: IngredientFacts) -> float:
        """Confianza por defecto si ninguna fuente la asignó."""
        if facts.sources:
            return 0.5
        return 0.0

    @staticmethod
    def _minimal_facts(parsed: ParsedIngredient) -> IngredientFacts:
        """Fallback minimal cuando todo el enrichment falla."""
        return IngredientFacts(
            name_es=parsed.name,
            category=IngredientCategory.UNKNOWN,
            origin=Origin.UNKNOWN,
            function_tag=parsed.function_tag,
            codex_ins_code=parsed.codex_ins_code,
            codex_ins_subcode=parsed.codex_ins_subcode,
            confidence=0.0,
        )


enrichment_service = EnrichmentService()
