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
    LLM_FALLBACK_ENABLED = _env_bool("LLM_FALLBACK_ENABLED", True)

settings = Settings()
