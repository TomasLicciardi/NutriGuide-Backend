from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict, Any, Literal
from datetime import datetime
from enum import Enum

class ImageType(str, Enum):
    """Tipos de imagen soportados"""
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"
    GIF = "image/gif"

class Restriction(BaseModel):
    """Modelo para una restricción alimentaria"""
    apto: bool
    razon: Optional[str] = None

class ProductAnalysis(BaseModel):
    """Resultado del análisis de un producto"""
    ingredientes: str
    puede_contener: Optional[str] = None
    clasificacion: Dict[str, Restriction]

class ProductBase(BaseModel):
    """Modelo base para productos"""
    result_json: ProductAnalysis
    is_suitable: bool
    image_type: ImageType
    date: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True

class ProductCreate(ProductBase):
    """Modelo para crear un producto"""
    history_id: int

class ProductListItem(BaseModel):
    """Modelo para listar productos en el historial"""
    id: int
    date: datetime
    is_suitable: bool

    class Config:
        from_attributes = True

class ProductDetail(BaseModel):
    """Modelo detallado de un producto"""
    id: int
    date: datetime
    is_suitable: bool
    result_json: ProductAnalysis
    image_type: ImageType
    image_url: str

    class Config:
        from_attributes = True

class ProductAnalysisResponse(BaseModel):
    """Respuesta del análisis de un producto"""
    product_id: int
    is_suitable: bool
    result_json: ProductAnalysis
    message: str = "Análisis completado"

class ImageResponse(BaseModel):
    """Respuesta para endpoints de imágenes"""
    url: str
    type: ImageType
