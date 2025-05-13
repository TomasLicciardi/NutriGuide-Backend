from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from app.schemas.product_schemas import ProductListItem, ProductDetail

class HistoryBase(BaseModel):
    user_id: int

    class Config:
        from_attributes = True

class HistoryResponse(BaseModel):
    historial_id: int
    usuario_id: int
    productos: List[ProductListItem]

    class Config:
        from_attributes = True

class ProductDetailResponse(BaseModel):
    id: int
    date: datetime
    is_suitable: bool
    result_json: dict
    image_type: str
    image_url: str

    class Config:
        from_attributes = True

class DeleteResponse(BaseModel):
    mensaje: str
