# app/core/init_db.py
import os
from sqlalchemy import inspect
from app.core.config import settings
from app.database.connection import engine, Base

def init_database():
    db_path = os.path.join(settings.DATABASE_PATH, settings.DATABASE_NAME)

    # Si el archivo no existe, se crea (vacío)
    if not os.path.exists(db_path):
        open(db_path, 'a').close()

    # Verifica si ya hay tablas
    inspector = inspect(engine)
    if not inspector.get_table_names():
        print("🔧 Creando tablas en la base de datos...")
        Base.metadata.create_all(bind=engine)
        print("✅ Tablas creadas.")
    else:
        print("📦 Las tablas ya existen. No se necesita crear nada.")
