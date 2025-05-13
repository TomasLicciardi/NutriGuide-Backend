from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal
from datetime import datetime
from enum import Enum

class ImageType(str, Enum):
    """Tipos de imagen soportados"""
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"
    GIF = "image/gif"

class ProductBase(BaseModel):
    result_json: Dict[str, Any]
    is_suitable: bool
    image_type: ImageType
    date: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True

class ProductCreate(ProductBase):
    history_id: int

class ProductListItem(BaseModel):
    id: int
    date: datetime
    is_suitable: bool

    class Config:
        from_attributes = True

class ProductDetail(BaseModel):
    id: int
    date: datetime
    is_suitable: bool
    result_json: Dict[str, Any]
    image_type: ImageType
    ingredients: Optional[str] = None
    warnings: Optional[str] = None

    class Config:
        from_attributes = True

class ProductAnalysisResponse(BaseModel):
    product_id: int
    is_suitable: bool
    result_json: Dict[str, Any]
    message: str = "Análisis completado"
