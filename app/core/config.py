# app/core/config.py
from pydantic import BaseSettings

class Settings(BaseSettings):
    port: int
    database_path: str
    database_name: str
    jwt_secret_key: str
    jwt_access_token_expires: int
    mail_server: str
    mail_port: int
    mail_use_tls: bool
    mail_username: str
    mail_password: str
    mail_from: str
    gemini_api_key: str

    class Config:
        env_file = ".env"

settings = Settings()
