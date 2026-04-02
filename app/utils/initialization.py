# app/utils/initialization.py
"""
Inicialización del sistema NutriGuide v2.
Carga modelo de traducción MarianMT y verifica Knowledge Base.
"""

import logging

logger = logging.getLogger(__name__)


def initialize_system():
    """
    Inicializa el sistema:
    1. Carga el modelo de traducción MarianMT
    2. Verifica la Knowledge Base
    """
    try:
        logger.info("Iniciando inicialización del sistema...")

        logger.info("Cargando modelo de traducción MarianMT...")
        from app.services.translation_service import translation_service
        test = translation_service.translate("agua")
        logger.info(f"Modelo de traducción OK (test: 'agua' → '{test}')")

        logger.info("Verificando Knowledge Base...")
        from app.database.connection import get_db
        from app.services.knowledge_base_service import knowledge_base_service
        db = next(get_db())
        count = knowledge_base_service.count(db)
        logger.info(f"Knowledge Base: {count} ingredientes registrados")
        db.close()

        logger.info("Inicialización del sistema completada")
        return True

    except Exception as e:
        logger.error(f"Error durante la inicialización: {e}")
        return False


def verify_system_health():
    """Verifica que el sistema esté funcionando correctamente."""
    try:
        from app.database.connection import get_db
        from app.services.knowledge_base_service import knowledge_base_service
        from app.services.translation_service import translation_service

        db = next(get_db())
        kb_count = knowledge_base_service.count(db)
        db.close()

        translation_cache = translation_service.get_cache_size()

        health_status = {
            "knowledge_base_ingredients": kb_count,
            "translation_cache_size": translation_cache,
            "restrictions": ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"],
            "pipeline_tiers": [
                "Tier 1: Deterministic",
                "Tier 2: Knowledge Base",
                "Tier 3: Open Food Facts",
                "Tier 4: PubChem",
                "Tier 5: Gemini Fallback",
            ],
            "healthy": True,
        }

        logger.info("Sistema en buen estado")
        return health_status

    except Exception as e:
        logger.error(f"Error verificando salud del sistema: {e}")
        return {"healthy": False, "error": str(e)}
