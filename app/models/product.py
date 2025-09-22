# app/models/product.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, LargeBinary, Boolean, Float
from sqlalchemy.orm import relationship
from app.database.connection import Base
from datetime import datetime

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    
    # Datos de imagen y análisis básico
    image = Column(LargeBinary, nullable=True)
    image_type = Column(String, nullable=False)  # Para almacenar el tipo de imagen (png, jpeg, etc.)
    date = Column(DateTime, default=datetime.utcnow)
    history_id = Column(Integer, ForeignKey("histories.id"))
    
    # Resultados OCR (primer request a Gemini)
    ocr_result_json = Column(Text, nullable=True)  # Resultado completo del OCR
    extracted_ingredients = Column(Text, nullable=True)  # Lista de ingredientes extraídos
    allergen_warnings = Column(Text, nullable=True)  # "CONTIENE / PUEDE CONTENER"
    ocr_confidence = Column(Float, default=0.0)
    
    # Resultados de clasificación (segundo request a Gemini)
    classification_result_json = Column(Text, nullable=True)  # Resultado completo de clasificación
    
    # Clasificación por restricciones (las cinco restricciones soportadas)
    is_vegan = Column(Boolean, nullable=True)
    vegan_reason = Column(Text, nullable=True)
    is_vegetarian = Column(Boolean, nullable=True)  
    vegetarian_reason = Column(Text, nullable=True)
    is_gluten_free = Column(Boolean, nullable=True)
    gluten_free_reason = Column(Text, nullable=True)
    is_lactose_free = Column(Boolean, nullable=True)
    lactose_free_reason = Column(Text, nullable=True)
    is_nut_free = Column(Boolean, nullable=True)
    nut_free_reason = Column(Text, nullable=True)
    
    # Metadatos del análisis
    classification_confidence = Column(Float, default=0.0)
    processing_status = Column(String, default="pending")  # pending, ocr_complete, classification_complete, error
    error_message = Column(Text, nullable=True)
    
    # Compatibilidad con código anterior
    result_json = Column(Text, nullable=True)  # Mantener para compatibilidad
    is_suitable = Column(Boolean, nullable=True)  # Se calculará basado en restricciones del usuario
    
    # Relaciones
    history = relationship("History", back_populates="products")
    product_ingredients = relationship("ProductIngredient", back_populates="product")
