from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# URL de conexión a la base de datos
DATABASE_URL = f"sqlite:///{settings.DATABASE_PATH}/{settings.DATABASE_NAME}"

# Crear el motor de la base de datos
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Crear la sesión para interactuar con la base de datos
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para la definición de modelos
Base = declarative_base()

def get_db():
    """
    Esta función devuelve una sesión de la base de datos.
    Es usada en FastAPI para inyectar la sesión en los endpoints.
    """
    db = SessionLocal()
    try:
        yield db  # Devuelve la sesión activa para usarla en el endpoint
    finally:
        db.close()  # Asegura que la sesión se cierre cuando ya no se necesite
