# app/models/rag_context.py
from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from app.database.connection import Base
from datetime import datetime

class RAGContextDocument(Base):
    __tablename__ = "rag_context_documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)  # Título del documento
    content = Column(Text, nullable=False)  # Contenido del documento
    document_type = Column(String, nullable=False)  # Tipo: "aditivos", "restricciones", "casos_especiales"
    embedding = Column(Text, nullable=True)  # JSON string del embedding del contenido
    relevance_score = Column(Float, default=1.0)  # Score de relevancia para ranking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)