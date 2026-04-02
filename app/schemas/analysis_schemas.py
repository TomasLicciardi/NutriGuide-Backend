from pydantic import BaseModel
from typing import Dict, List, Optional


class RestrictionResult(BaseModel):
    apto: bool
    motivo: Optional[str] = None


class IngredientDetail(BaseModel):
    name_es: str
    name_en: str
    category: str
    origin: Optional[str] = None
    function_tag: Optional[str] = None
    description_es: Optional[str] = None
    is_tacc_safe: Optional[bool] = None
    is_lactose_safe: Optional[bool] = None
    is_nut_safe: Optional[bool] = None
    is_vegan_safe: Optional[bool] = None
    confidence: float = 0.0
    resolved_by: str = "unresolved"
    evidence: List[str] = []


class AnalysisResponseV2(BaseModel):
    user_verdict: bool
    restrictions: Dict[str, RestrictionResult]
    ingredients: List[IngredientDetail]
    allergen_warnings: Optional[str] = None
    overall_confidence: float
    processing_time: Optional[float] = None
    stats: Optional[Dict[str, int]] = None


class ErrorResponse(BaseModel):
    error: str
    message: str
    confidence: float = 0.0
