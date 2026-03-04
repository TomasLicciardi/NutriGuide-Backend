#app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import auth, analyze, history, user, product
from app.database.connection import init_database
from app.utils.error_handlers import register_error_handlers
from app.utils.initialization import initialize_system
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NutriGuide API V2",
    description="API for food label analysis with Gemini, RAG, and JWT authentication. Supports 5 dietary restrictions with intelligent ingredient classification.",
    version="2.0.0"
)

# Initialize the database and RAG system
logger.info("Inicializando base de datos y sistema RAG...")
init_database()

# Inicializar sistema RAG en background (no bloquear el startup)
try:
    initialize_system()
    logger.info("✅ Sistema RAG inicializado exitosamente")
except Exception as e:
    logger.error(f"⚠️ Error inicializando sistema RAG: {e}")
    logger.info("La aplicación continuará funcionando, pero el sistema RAG puede no estar disponible")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(analyze.router)
app.include_router(history.router)
app.include_router(user.router)
app.include_router(product.router)

# Registrar manejadores de errores
register_error_handlers(app)

@app.get("/")
async def root():
    return {
        "message": "NutriGuide API V2",
        "version": "2.0.0",
        "features": [
            "OCR con Gemini Vision",
            "RAG con embeddings semánticos", 
            "Clasificación de 5 restricciones dietéticas",
            "Separación automática BASE/ADITIVO",
            "Sistema de confianza diferencial",
            "Base de conocimiento especializada"
        ],
        "endpoints": {
            "análisis_v1": "/analysis/ (legacy)",
            "análisis_v2": "/analysis/v2 (nuevo flujo)",
            "documentación": "/docs"
        }
    }

@app.get("/health")
async def health_check():
    """Endpoint de verificación de salud del sistema"""
    try:
        from app.utils.initialization import verify_system_health
        health_status = verify_system_health()
        return {
            "status": "healthy" if health_status.get("healthy", False) else "degraded",
            "details": health_status
        }
    except Exception as e:
        return {
            "status": "error",
            "details": {"error": str(e)}
        }
