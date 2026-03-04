from pydantic import BaseModel
from typing import Dict, Any, List, Optional

class AnalysisRequest(BaseModel):
    image_base64: str

class RestrictionResult(BaseModel):
    apto: bool
    motivo: Optional[str] = None

class ClassificationResult(BaseModel):
    vegano: RestrictionResult
    vegetariano: RestrictionResult
    sin_gluten: RestrictionResult
    sin_lactosa: RestrictionResult
    sin_frutos_secos: RestrictionResult

class OCRResult(BaseModel):
    ingredientes_detectados: List[str]
    alergenos_advertencias: Optional[str] = None
    confidence: float

class AnalysisResultV2(BaseModel):
    """Resultado del nuevo flujo de análisis con dos fases"""
    ocr_result: OCRResult
    classification_result: ClassificationResult
    processing_status: str
    overall_confidence: float
    ingredients_classified: Dict[str, str]  # {ingrediente: "BASE"|"ADITIVO"}

class AnalysisResponse(BaseModel):
    """Respuesta compatible con el formato anterior"""
    verdict: bool  # Calculado basado en restricciones del usuario
    analysis: Dict[str, Any]  # Contiene el análisis completo
    warnings: str = None

class AnalysisResponseV2(BaseModel):
    """Nueva respuesta extendida con cinco restricciones"""
    user_verdict: bool  # Basado en restricciones activas del usuario
    classification: ClassificationResult  # Clasificación completa de cinco restricciones
    detected_ingredients: List[str]
    base_ingredients: List[str]  # Solo ingredientes BASE
    additives: List[str]  # Solo aditivos
    allergen_warnings: Optional[str] = None
    confidence: float
    processing_time: Optional[float] = None

class ErrorResponse(BaseModel):
    error: str
    message: str
    confidence: float = 0.0
