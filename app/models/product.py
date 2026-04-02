# app/models/product.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, LargeBinary, Boolean, Float
from sqlalchemy.orm import relationship
from app.database.connection import Base
from datetime import datetime


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)

    image = Column(LargeBinary, nullable=True)
    image_type = Column(String, nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    history_id = Column(Integer, ForeignKey("histories.id"))

    # OCR
    ocr_result_json = Column(Text, nullable=True)
    extracted_ingredients = Column(Text, nullable=True)
    allergen_warnings = Column(Text, nullable=True)
    ocr_confidence = Column(Float, default=0.0)

    # 4 restricciones
    is_tacc_safe = Column(Boolean, nullable=True)
    tacc_reason = Column(Text, nullable=True)
    is_lactose_safe = Column(Boolean, nullable=True)
    lactose_reason = Column(Text, nullable=True)
    is_nut_safe = Column(Boolean, nullable=True)
    nut_reason = Column(Text, nullable=True)
    is_vegan_safe = Column(Boolean, nullable=True)
    vegan_reason = Column(Text, nullable=True)

    # Metadata
    overall_confidence = Column(Float, default=0.0)
    processing_time_ms = Column(Float, nullable=True)
    result_json = Column(Text, nullable=True)
    is_suitable = Column(Boolean, nullable=True)
    processing_status = Column(String, default="pending")
    error_message = Column(Text, nullable=True)

    # Relaciones
    history = relationship("History", back_populates="products")
    product_ingredients = relationship("ProductIngredient", back_populates="product")
