from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict, Any, Literal, List
from datetime import datetime
from enum import Enum

class ImageType(str, Enum):
    """Tipos de imagen soportados"""
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"
    GIF = "image/gif"

class ProcessingStatus(str, Enum):
    """Estados de procesamiento del producto"""
    PENDING = "pending"
    OCR_COMPLETE = "ocr_complete"
    CLASSIFICATION_COMPLETE = "classification_complete"
    ERROR = "error"

class RestrictionResultSchema(BaseModel):
    """Resultado de una restricción alimentaria"""
    apto: bool
    motivo: Optional[str] = None

class ClassificationSchema(BaseModel):
    """Clasificación completa de las cinco restricciones"""
    vegano: RestrictionResultSchema
    vegetariano: RestrictionResultSchema
    sin_gluten: RestrictionResultSchema
    sin_lactosa: RestrictionResultSchema
    sin_frutos_secos: RestrictionResultSchema

class IngredientSchema(BaseModel):
    """Esquema para un ingrediente"""
    id: int
    name: str
    original_name: str
    type: str  # "BASE" o "ADITIVO"
    confidence: float

class ProductAnalysisV2(BaseModel):
    """Resultado del análisis de un producto con nuevo formato"""
    # Resultados OCR
    extracted_ingredients: List[str]
    allergen_warnings: Optional[str] = None
    ocr_confidence: float
    
    # Resultados de clasificación
    classification: ClassificationSchema
    classification_confidence: float
    
    # Ingredientes procesados
    base_ingredients: List[IngredientSchema]
    additives: List[IngredientSchema]
    
    # Metadatos
    processing_status: ProcessingStatus
    overall_confidence: float

# Mantener compatibilidad con formato anterior
class Restriction(BaseModel):
    """Modelo para una restricción alimentaria (formato legacy)"""
    apto: bool
    razon: Optional[str] = None

class ProductAnalysis(BaseModel):
    """Resultado del análisis de un producto (formato legacy)"""
    ingredientes: str
    puede_contener: Optional[str] = None
    clasificacion: Dict[str, Restriction]

class ProductBase(BaseModel):
    """Modelo base para productos"""
    result_json: Optional[ProductAnalysis] = None
    is_suitable: Optional[bool] = None
    image_type: ImageType
    date: datetime = Field(default_factory=datetime.utcnow)
    
    # Nuevos campos para el flujo V2
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    analysis_v2: Optional[ProductAnalysisV2] = None

    class Config:
        from_attributes = True

class ProductCreate(ProductBase):
    """Modelo para crear un producto"""
    history_id: int

class ProductListItem(BaseModel):
    """Modelo para listar productos en el historial"""
    id: int
    date: datetime
    is_suitable: Optional[bool] = None
    processing_status: ProcessingStatus
    overall_confidence: Optional[float] = None

    class Config:
        from_attributes = True

class ProductDetail(BaseModel):
    """Modelo detallado de un producto"""
    id: int
    date: datetime
    is_suitable: Optional[bool] = None
    result_json: Optional[ProductAnalysis] = None
    analysis_v2: Optional[ProductAnalysisV2] = None
    image_type: ImageType
    image_url: str
    processing_status: ProcessingStatus

    class Config:
        from_attributes = True

class ProductAnalysisResponse(BaseModel):
    """Respuesta del análisis de un producto"""
    product_id: int
    is_suitable: Optional[bool] = None
    result_json: Optional[ProductAnalysis] = None
    analysis_v2: Optional[ProductAnalysisV2] = None
    message: str = "Análisis completado"

class ProductUserVerdict(BaseModel):
    """Veredicto personalizado basado en restricciones del usuario"""
    user_verdict: bool
    applicable_restrictions: List[str]
    violated_restrictions: List[RestrictionResultSchema] = []
    safe_restrictions: List[str] = []
    overall_confidence: float

class ImageResponse(BaseModel):
    """Respuesta para endpoints de imágenes"""
    url: str
    type: ImageType
