# app/services/canonicalization_service.py
"""
Canonicalizacion de ingredientes antes del enrichment.

Convierte variantes de etiqueta ("harina de trigo 0000 enriquecida",
"caramelo III", "cloruro de sodio") en candidatos canonicos auditables.
Las reglas viven en YAML para evitar hardcodear casos dentro del codigo.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
import unicodedata
from typing import Any, Dict, List, Optional

import yaml

from app.services.parser import ParsedIngredient

_RULES_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "canonicalization_rules.yaml"
)


def normalize_name(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text or "")
    no_accents = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    normalized = no_accents.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.strip(" .,;:")
    return normalized


@dataclass
class CanonicalizationResult:
    original_name: str
    normalized_name: str
    canonical_name_es: str
    canonical_name_en: Optional[str] = None
    candidates_es: List[str] = field(default_factory=list)
    source: str = "identity"
    confidence: float = 1.0
    evidence: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.canonical_name_es != self.normalized_name


class CanonicalizationService:
    def __init__(self):
        self._aliases: Dict[str, dict] = {}
        self._patterns: List[dict] = []
        self._initialized = False

    def initialize(self) -> int:
        if self._initialized:
            return len(self._aliases) + len(self._patterns)

        if not _RULES_FILE.exists():
            self._initialized = True
            return 0

        with open(_RULES_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        aliases = data.get("aliases", {}) or {}
        self._aliases = {
            normalize_name(alias): spec
            for alias, spec in aliases.items()
            if isinstance(spec, dict) and spec.get("canonical")
        }

        self._patterns = []
        for spec in data.get("patterns", []) or []:
            if not isinstance(spec, dict) or not spec.get("pattern"):
                continue
            compiled = dict(spec)
            compiled["_compiled"] = re.compile(spec["pattern"], re.IGNORECASE)
            self._patterns.append(compiled)

        self._initialized = True
        return len(self._aliases) + len(self._patterns)

    def canonicalize(self, parsed: ParsedIngredient) -> CanonicalizationResult:
        if not self._initialized:
            self.initialize()

        original = parsed.name or ""
        normalized = normalize_name(original)

        result = CanonicalizationResult(
            original_name=original,
            normalized_name=normalized,
            canonical_name_es=normalized,
            candidates_es=[normalized],
        )

        alias = self._aliases.get(normalized)
        if alias:
            return self._from_spec(
                original=original,
                normalized=normalized,
                spec=alias,
                source="alias",
                match=None,
            )

        for spec in self._patterns:
            match = spec["_compiled"].match(normalized)
            if match:
                return self._from_spec(
                    original=original,
                    normalized=normalized,
                    spec=spec,
                    source=f"pattern:{spec.get('id', 'unknown')}",
                    match=match,
                )

        return result

    def _from_spec(
        self,
        original: str,
        normalized: str,
        spec: Dict[str, Any],
        source: str,
        match: Optional[re.Match],
    ) -> CanonicalizationResult:
        canonical = spec.get("canonical")
        if not canonical:
            canonical = self._render_template(spec.get("canonical_template", normalized), match)
        canonical = normalize_name(canonical)

        candidates = [canonical]
        for template in spec.get("candidate_templates", []) or []:
            candidate = normalize_name(self._render_template(template, match))
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        if normalized not in candidates:
            candidates.append(normalized)

        name_en = spec.get("name_en")
        if not name_en and spec.get("name_en_template"):
            name_en = self._render_template(spec["name_en_template"], match)

        reason = spec.get("reason", "canonicalizacion por regla de dominio")
        evidence = [f"{source}: '{original}' -> '{canonical}' ({reason})"]

        return CanonicalizationResult(
            original_name=original,
            normalized_name=normalized,
            canonical_name_es=canonical,
            canonical_name_en=name_en,
            candidates_es=candidates,
            source=source,
            confidence=float(spec.get("confidence", 0.95)),
            evidence=evidence,
        )

    @staticmethod
    def _render_template(template: str, match: Optional[re.Match]) -> str:
        if not match:
            return template
        rendered = template
        for i, group in enumerate(match.groups(), start=1):
            rendered = rendered.replace(f"{{{i}}}", group or "")
        return rendered


canonicalization_service = CanonicalizationService()

