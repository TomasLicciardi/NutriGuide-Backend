# app/models/ocr_cache.py
"""
Caché de lecturas (OCR): misma imagen → misma transcripción, sin volver a
llamar a Gemini.

La clave es el SHA-256 de los bytes que manda la app. Si el usuario vuelve a
analizar exactamente la misma foto (por ejemplo, la misma imagen de la
galería), la Fase 1 se resuelve desde acá: cero costo, cero cuota y cero
dependencia de que Gemini esté disponible en ese momento. Las fases 2-6
(parser, declaración legal, fuentes, reglas, veredicto) corren igual.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database.connection import Base


class OcrCache(Base):
    __tablename__ = "ocr_cache"

    image_sha256 = Column(String(64), primary_key=True)
    ingredients_json = Column(Text, nullable=False)       # lista JSON de nombres, tal como los leyó Gemini
    allergen_warnings = Column(Text, nullable=True)       # texto de CONTIENE / PUEDE CONTENER
    model = Column(String, nullable=True)                 # modelo que hizo la lectura original
    hits = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, default=datetime.utcnow)
