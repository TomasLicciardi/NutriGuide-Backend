# app/models/product_ingredient.py
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Float, Text
from sqlalchemy.orm import relationship
from app.database.connection import Base

class ProductIngredient(Base):
    __tablename__ = "product_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)
    detected_name = Column(String, nullable=False)  # Nombre como apareció en la etiqueta
    is_base_ingredient = Column(Boolean, default=True)  # Si es ingrediente base o aditivo
    affects_classification = Column(Boolean, default=True)  # Si afecta la clasificación final
    source = Column(String, default="gemini_ocr")  # Fuente de detección
    confidence = Column(Float, default=1.0)  # Confianza en la detección
    notes = Column(Text, nullable=True)  # Notas adicionales
    
    # Relaciones
    product = relationship("Product", back_populates="product_ingredients")
    ingredient = relationship("Ingredient", back_populates="product_ingredients")