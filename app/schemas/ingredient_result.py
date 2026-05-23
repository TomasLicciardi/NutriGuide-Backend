# app/schemas/ingredient_result.py
"""
Dataclass de resultado por ingrediente — usado por la Knowledge Base como
contrato de lectura. Mantenido como dataclass plano (no Pydantic) porque
es estructura interna del pipeline, no payload HTTP.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class IngredientResult:
    name: str
    name_normalized: str
    category: str  # "BASE" | "ADITIVO"
    origin: Optional[str] = None
    function_tag: Optional[str] = None
    description_es: Optional[str] = None
    is_tacc_safe: Optional[bool] = None
    is_lactose_safe: Optional[bool] = None
    is_nut_safe: Optional[bool] = None
    is_vegan_safe: Optional[bool] = None
    confidence: float = 0.0
    resolved_by: str = "unresolved"
    evidence: List[str] = field(default_factory=list)
