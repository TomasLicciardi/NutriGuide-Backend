# app/models/models.py
from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database.connection import Base
from datetime import datetime
from sqlalchemy import DateTime

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    usuario = Column(String, nullable=False)
    mail = Column(String, unique=True, nullable=False)
    contrasena = Column(String, nullable=False)

    historial = relationship("Historial", back_populates="usuario", uselist=False)

class Historial(Base):
    __tablename__ = "historiales"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), unique=True)
    
    usuario = relationship("Usuario", back_populates="historial")
    productos = relationship("ProductoAnalizado", back_populates="historial")

class ProductoAnalizado(Base):
    __tablename__ = "productos_analizados"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=True)
    resultado_json = Column(Text, nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow)
    historial_id = Column(Integer, ForeignKey("historiales.id"))

    historial = relationship("Historial", back_populates="productos")
