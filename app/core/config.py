# app/core/config.py
from dotenv import load_dotenv
import os

load_dotenv()

class Settings:
    PORT = os.getenv("PORT")
    DATABASE_PATH = os.getenv("DATABASE_PATH")
    DATABASE_NAME = os.getenv("DATABASE_NAME")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES"))
    MAIL_SERVER = os.getenv("MAIL_SERVER")
    MAIL_PORT = int(os.getenv("MAIL_PORT"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS") == "True"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_FROM = os.getenv("MAIL_FROM")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

settings = Settings()
