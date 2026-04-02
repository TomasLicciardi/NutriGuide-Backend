# app/models/product_ingredient.py
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Float, Text
from sqlalchemy.orm import relationship
from app.database.connection import Base


class ProductIngredient(Base):
    __tablename__ = "product_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=True)
    detected_name = Column(String, nullable=False)
    name_en = Column(String, nullable=True)
    is_base_ingredient = Column(Boolean, default=True)
    resolved_by = Column(String, nullable=True)
    confidence = Column(Float, default=0.0)
    evidence_json = Column(Text, nullable=True)

    product = relationship("Product", back_populates="product_ingredients")
    ingredient = relationship("Ingredient", back_populates="product_ingredients")
