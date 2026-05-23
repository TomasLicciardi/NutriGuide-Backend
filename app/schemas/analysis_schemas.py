# app/schemas/analysis_schemas.py
"""
Schemas Pydantic para el endpoint /analysis/.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class RestrictionResponse(BaseModel):
    apto: bool
    motivo: Optional[str] = None
    fuente: str = Field(..., description="legal_declaration | ingredient_analysis | flavoring_policy")
    confidence: float
    ingrediente_disparador: Optional[str] = None


class IngredientResponse(BaseModel):
    name_es: str
    name_en: Optional[str] = None
    category: str
    origin: str
    function_tag: Optional[str] = None

    codex_ins_code: Optional[int] = None
    codex_ins_subcode: Optional[str] = None

    is_flavoring: bool = False
    flavoring_type: Optional[str] = None
    target_sensory: Optional[str] = None

    allergens: List[str] = Field(default_factory=list)
    contains: List[str] = Field(default_factory=list)
    derived_from: List[str] = Field(default_factory=list)

    confidence: float
    sources: List[str] = Field(default_factory=list)
    description_es: Optional[str] = None


class LegalDeclarationResponse(BaseModel):
    contains: List[str] = Field(default_factory=list)
    may_contain: List[str] = Field(default_factory=list)
    positive_claims: List[str] = Field(default_factory=list)
    raw_text: Optional[str] = None


class StatsResponse(BaseModel):
    total_ingredients: int
    total_flavorings: int
    resolved_by_legal: int
    resolved_by_codex: int
    resolved_by_off: int
    resolved_by_kb: int
    resolved_by_gemini: int
    resolved_by_llm: int = 0
    resolved_by_policy: int = 0
    unresolved: int
    gemini_calls: int
    processing_time_ms: float


class AnalysisResponse(BaseModel):
    user_verdict: bool
    restrictions: Dict[str, RestrictionResponse]
    ingredients: List[IngredientResponse]
    declaration: LegalDeclarationResponse
    overall_confidence: float
    stats: StatsResponse


class ErrorResponse(BaseModel):
    error: str
    message: str
