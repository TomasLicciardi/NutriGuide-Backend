# app/utils/initialization.py
"""
Inicialización del sistema NutriGuide v2.1.

Carga modelos locales al startup:
  1. MarianMT (traducción ES→EN)
  2. Sentence-Transformers (embedding classifier)
  3. Verificación de Knowledge Base
"""

import logging

logger = logging.getLogger(__name__)


def initialize_system():
    """
    Inicializa el sistema:
    1. Carga el modelo de traducción MarianMT
    2. Carga el modelo de embeddings sentence-transformers
    3. Verifica la Knowledge Base
    """
    try:
        logger.info("Iniciando inicialización del sistema...")

        # 1. MarianMT
        logger.info("Cargando modelo de traducción MarianMT...")
        from app.services.translation_service import translation_service
        test = translation_service.translate("agua")
        logger.info(f"Modelo de traducción OK (test: 'agua' → '{test}')")

        # 2. Embedding Classifier (sentence-transformers)
        logger.info("Cargando modelo de embeddings...")
        try:
            from app.services.embedding_classifier import embedding_classifier
            embedding_classifier.initialize()
            logger.info("Embedding classifier OK")
        except ImportError as e:
            logger.warning(
                f"sentence-transformers no instalado: {e}. "
                f"El Tier 3 (embedding) estará deshabilitado. "
                f"Instalar con: pip install sentence-transformers"
            )
        except Exception as e:
            logger.warning(f"Error inicializando embedding classifier: {e}. Tier 3 deshabilitado.")

        # 3. Knowledge Base
        logger.info("Verificando Knowledge Base...")
        from app.database.connection import get_db
        from app.services.knowledge_base_service import knowledge_base_service
        db = next(get_db())
        count = knowledge_base_service.count(db)
        logger.info(f"Knowledge Base: {count} ingredientes registrados")

        # Enriquecer embeddings con KB si está disponible
        try:
            from app.services.embedding_classifier import embedding_classifier
            if embedding_classifier.is_initialized:
                embedding_classifier.refresh_from_kb(db)
                logger.info("Embedding classifier enriquecido con Knowledge Base")
        except Exception:
            pass

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

        embedding_status = "disabled"
        try:
            from app.services.embedding_classifier import embedding_classifier
            if embedding_classifier.is_initialized:
                embedding_status = f"active ({len(embedding_classifier._reference_entries)} refs)"
        except Exception:
            pass

        health_status = {
            "knowledge_base_ingredients": kb_count,
            "translation_cache_size": translation_cache,
            "embedding_classifier": embedding_status,
            "restrictions": ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"],
            "pipeline_tiers": [
                "Tier 1: Deterministic (local rules)",
                "Tier 2: Knowledge Base (local DB)",
                "Tier 3: Embedding Classifier (local ML)",
                "Tier 4: Open Food Facts (external API)",
                "Tier 5: PubChem (external API)",
                "Gemini: from OCR call (no extra API call)",
            ],
            "gemini_calls_per_analysis": 1,
            "healthy": True,
        }

        logger.info("Sistema en buen estado")
        return health_status

    except Exception as e:
        logger.error(f"Error verificando salud del sistema: {e}")
        return {"healthy": False, "error": str(e)}
