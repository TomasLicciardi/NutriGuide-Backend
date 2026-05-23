# app/main.py
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
    title="NutriGuide API",
    description=(
        "API de análisis de etiquetas alimentarias con pipeline multi-fuente: "
        "OCR Gemini Vision, parser estructural argentino, federación de fuentes "
        "(Codex INS + Open Food Facts + Knowledge Base local + Gemini fallback), "
        "y predicados declarativos por restricción dietética. "
        "Diseño fact base / rule base con trazabilidad por tag."
    ),
    version="3.0.0",
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
        "message": "NutriGuide API — Pipeline multi-fuente con fact base / rule base",
        "version": "3.0.0",
        "pipeline": [
            "Fase 1: OCR + clasificación con Gemini Vision (1 sola llamada paga)",
            "Fase 2: Parser estructural argentino (Lark) → ParsedIngredient + ProductLegalDeclaration",
            "Fase 3: Resolución por declaración legal (CONTIENE / PUEDE CONTENER / claims)",
            "Fase 4: Enrichment paralelo (Codex INS + OFF taxonomy + KB local + Gemini)",
            "Fase 4.5: LLM batch fallback (1 llamada Gemini agrupada para unresolved)",
            "Fase 5: Predicados declarativos por restricción sobre IngredientFacts",
            "Fase 6: Veredicto + persistencia + actualización de KB",
        ],
        "restrictions": ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"],
        "endpoints": {
            "análisis": "/analysis/",
            "documentación": "/docs",
            "salud": "/health",
        },
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
