# app/models/ingredient.py
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, Enum
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
    name_es = Column(String, nullable=False, unique=True, index=True)
    name_en = Column(String, nullable=True)
    type = Column(Enum(IngredientType), nullable=False, default=IngredientType.BASE)
    origin = Column(String, nullable=True)          # animal/vegetal/sintetico/mineral/desconocido
    function_tag = Column(String, nullable=True)     # conservante/colorante/emulsionante/...
    description_es = Column(String, nullable=True)

    is_tacc_safe = Column(Boolean, nullable=True)
    is_lactose_safe = Column(Boolean, nullable=True)
    is_nut_safe = Column(Boolean, nullable=True)
    is_vegan_safe = Column(Boolean, nullable=True)

    confidence = Column(Float, default=0.0)
    resolved_by = Column(String, nullable=True)      # deterministic/knowledge_base/openfoodfacts/pubchem/gemini
    off_taxonomy_id = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product_ingredients = relationship("ProductIngredient", back_populates="ingredient")
