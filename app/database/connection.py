#app/database/connection.py
import os
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# Construir la URL de conexión
DATABASE_URL = f"sqlite:///{settings.DATABASE_PATH}/{settings.DATABASE_NAME}"

# Crear el motor SQLAlchemy
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

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

    # Crear tablas si no existen
    inspector = inspect(engine)
    if not inspector.get_table_names():
        Base.metadata.create_all(bind=engine)
