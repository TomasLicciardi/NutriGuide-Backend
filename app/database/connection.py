#app/database/connection.py
import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings

# Construir la URL de conexión
DATABASE_URL = f"sqlite:///{settings.DATABASE_PATH}/{settings.DATABASE_NAME}"

# Crear el motor SQLAlchemy
# timeout: el panel de administración escribe el mismo archivo desde otro
# proceso; 15 s de espera por el lock evita un "database is locked" espurio.
# NullPool: una conexión por sesión, sin pool. Con el QueuePool por defecto
# (5 + 10 conexiones) más de 15 análisis simultáneos agotan el pool y la
# espera por una conexión bloquea el event loop: ninguna sesión puede
# cerrarse y el servidor queda colgado. Abrir una conexión SQLite cuesta
# milisegundos, así que no hay nada que ganar con el pool.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15},
    poolclass=NullPool,
)

# Crear la sesión de base de datos
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative base para los modelos
Base = declarative_base()

def get_db():
    """
    Devuelve una sesión activa de la base de datos.
    Utilizado como dependencia en los endpoints.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_database():
    """
    Inicializa la base de datos:
    - Crea el archivo SQLite si no existe.
    - Crea las tablas si no existen aún.
    """
    db_path = os.path.join(settings.DATABASE_PATH, settings.DATABASE_NAME)

    # Crear archivo si no existe
    if not os.path.exists(db_path):
        open(db_path, 'a').close()

    # Importar modelos para que SQLAlchemy los registre
    from app.models import user, history, product, ingredient, product_ingredient

    # `create_all` es idempotente: crea solo las tablas que faltan, no toca
    # las existentes. Llamarlo siempre evita el caso donde existían `users`
    # e `ingredients` de un run viejo pero faltaba `history` (que rompía el
    # primer análisis de un usuario nuevo).
    Base.metadata.create_all(bind=engine)

    _ensure_ingredients_columns()
    _ensure_users_columns()


def _ensure_ingredients_columns():
    """Aplica migraciones chicas compatibles con SQLite ya creadas."""
    inspector = inspect(engine)
    if "ingredients" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("ingredients")}
    with engine.begin() as conn:
        if "provenance" not in columns:
            conn.execute(text("ALTER TABLE ingredients ADD COLUMN provenance VARCHAR"))


def _ensure_users_columns():
    """Agrega columnas faltantes a `users` (idempotente, compatible con SQLite)."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "is_admin" not in columns:
            # SQLite no soporta DEFAULT FALSE booleano nativamente; usamos 0/1.
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"
            ))
