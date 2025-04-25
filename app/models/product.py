# app/models/product.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.database.connection import Base
from datetime import datetime

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    result_json = Column(Text, nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    history_id = Column(Integer, ForeignKey("histories.id"))

    history = relationship("History", back_populates="products")
