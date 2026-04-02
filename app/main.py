#app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import auth, analyze, history, user, product
from app.database.connection import init_database
from app.utils.error_handlers import register_error_handlers
from app.utils.initialization import initialize_system
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NutriGuide API V2",
    description="API de análisis de ingredientes alimentarios con pipeline multi-fuente: "
                "Gemini Vision OCR, traducción MarianMT, Open Food Facts, PubChem, "
                "y motor de consenso ponderado. 4 restricciones dietéticas.",
    version="2.0.0"
)

logger.info("Inicializando base de datos...")
init_database()

try:
    initialize_system()
    logger.info("Sistema inicializado exitosamente")
except Exception as e:
    logger.error(f"Error inicializando sistema: {e}")
    logger.info("La aplicación continuará, pero algunos servicios pueden no estar disponibles")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(analyze.router)
app.include_router(history.router)
app.include_router(user.router)
app.include_router(product.router)

register_error_handlers(app)


@app.get("/")
async def root():
    return {
        "message": "NutriGuide API V2 — Pipeline Multi-Fuente",
        "version": "2.0.0",
        "pipeline": [
            "Fase 1: OCR con Gemini Vision",
            "Fase 2: Normalización de ingredientes",
            "Fase 3: Traducción ES→EN (MarianMT local)",
            "Fase 4: Clasificación 5 Tiers (Determinista → KB → OFF → PubChem → Gemini)",
            "Fase 5: Análisis de alérgenos",
            "Fase 6: Motor de consenso ponderado",
            "Fase 7: Persistencia + aprendizaje",
        ],
        "restrictions": ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"],
        "endpoints": {
            "análisis": "/analysis/",
            "documentación": "/docs",
        }
    }


@app.get("/health")
async def health_check():
    try:
        from app.utils.initialization import verify_system_health
        health_status = verify_system_health()
        return {
            "status": "healthy" if health_status.get("healthy", False) else "degraded",
            "details": health_status,
        }
    except Exception as e:
        return {"status": "error", "details": {"error": str(e)}}
