# app/models/product.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, LargeBinary, Boolean
from sqlalchemy.orm import relationship
from app.database.connection import Base
from datetime import datetime

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    result_json = Column(Text, nullable=False)  # Contiene los detalles completos del análisis
    is_suitable = Column(Boolean, nullable=False)  # Indica si el producto es apto o no
    date = Column(DateTime, default=datetime.utcnow)
    history_id = Column(Integer, ForeignKey("histories.id"))
    image = Column(LargeBinary, nullable=True)
    image_type = Column(String, nullable=False)  # Para almacenar el tipo de imagen (png, jpeg, etc.)

    history = relationship("History", back_populates="products")
