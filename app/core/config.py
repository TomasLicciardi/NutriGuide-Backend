# app/core/config.py
from dotenv import load_dotenv
import os

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class Settings:
    PORT = os.getenv("PORT", "8000")
    DATABASE_PATH = os.getenv("DATABASE_PATH", "./data")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "nutriguide.db")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "changeme-in-production")
    JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", "3600"))
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True") == "True"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_FROM = os.getenv("MAIL_FROM", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    # Modelo Gemini para Fase 1 (OCR + clasificación). Hacerlo configurable
    # permite probar otros modelos (gemini-2.5-flash con RPM más holgado)
    # sin tocar código. La 2.0-flash-lite tiene limit:0 en el free tier según
    # el proyecto — por eso default es 2.5-flash-lite.
    GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash-lite")
    LLM_FALLBACK_ENABLED = _env_bool("LLM_FALLBACK_ENABLED", True)
    # Tier 4.4 — identificación química vía PubChem PUG-REST. Corre antes del
    # LLM fallback para resolver compuestos sin gastar cuota Gemini. Sin API key.
    PUBCHEM_ENABLED = _env_bool("PUBCHEM_ENABLED", True)

settings = Settings()
