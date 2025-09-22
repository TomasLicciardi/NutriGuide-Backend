# app/models/ingredient.py
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Enum
from sqlalchemy.orm import relationship
from app.database.connection import Base
from datetime import datetime
import enum

class IngredientType(enum.Enum):
    BASE = "BASE"
    ADITIVO = "ADITIVO"

class Ingredient(Base):
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)  # Nombre normalizado del ingrediente
    original_name = Column(String, nullable=False)  # Nombre original detectado
    type = Column(Enum(IngredientType), nullable=False)  # BASE o ADITIVO
    embedding = Column(Text, nullable=True)  # JSON string del embedding
    confidence = Column(Float, default=1.0)  # Confianza en la clasificación
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    product_ingredients = relationship("ProductIngredient", back_populates="ingredient")