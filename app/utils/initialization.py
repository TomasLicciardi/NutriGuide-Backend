# app/utils/initialization.py
"""
Inicialización del sistema NutriGuide.

Carga al startup:
  1. MarianMT (traducción ES→EN, local)
  2. Loaders de referencia (Codex INS, OFF taxonomy, canonicalization)
  3. Knowledge Base seed (ingredientes curados desde kb_seed.yaml)
"""

import logging

logger = logging.getLogger(__name__)


def initialize_system():
    """
    Inicializa el sistema:
      1. Modelo de traducción MarianMT
      2. Loaders de referencia (Codex INS, OFF taxonomy, canonicalization)
      3. Seed de la Knowledge Base
    """
    try:
        logger.info("Iniciando inicialización del sistema...")

        # 1. MarianMT
        logger.info("Cargando modelo de traducción MarianMT...")
        from app.services.translation_service import translation_service
        test = translation_service.translate("agua")
        logger.info(f"Modelo de traducción OK (test: 'agua' → '{test}')")

        # 2. Loaders de referencia
        try:
            from app.services.canonicalization_service import canonicalization_service
            from app.services.loaders import codex_ins_loader, off_taxonomy_loader
            canonical_count = canonicalization_service.initialize()
            ins_count = codex_ins_loader.initialize()
            off_count = off_taxonomy_loader.initialize()
            logger.info(
                f"Loaders: Canonicalization={canonical_count} reglas, "
                f"Codex INS={ins_count} códigos, "
                f"OFF taxonomy cache={off_count} entradas"
            )
        except Exception as e:
            logger.warning(f"Algún loader falló: {e}. Pipeline funcionará con cobertura reducida.")

        # 3. Knowledge Base — seed + verificación
        logger.info("Verificando Knowledge Base...")
        from app.database.connection import get_db
        from app.services.knowledge_base_service import knowledge_base_service
        from app.data.seeder import seed_knowledge_base
        db = next(get_db())
        seed_knowledge_base(db)
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
        from app.services.loaders import codex_ins_loader, off_taxonomy_loader
        from app.services.canonicalization_service import canonicalization_service

        db = next(get_db())
        kb_count = knowledge_base_service.count(db)
        db.close()

        translation_cache = translation_service.get_cache_size()

        health_status = {
            "knowledge_base_ingredients": kb_count,
            "translation_cache_size": translation_cache,
            "codex_ins_loaded": codex_ins_loader.is_initialized,
            "off_taxonomy_loaded": off_taxonomy_loader.is_initialized,
            "canonicalization_loaded": canonicalization_service._initialized,
            "restrictions": ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"],
            "pipeline_phases": [
                "Fase 1: OCR + clasificación con Gemini Vision",
                "Fase 2: Parser estructural argentino",
                "Fase 3: Resolución por declaración legal",
                "Fase 4: Enrichment paralelo (Codex INS + OFF + KB + Gemini)",
                "Fase 4.5: LLM batch fallback (opcional)",
                "Fase 5: Predicados declarativos por restricción",
                "Fase 6: Veredicto + persistencia",
            ],
            "gemini_calls_per_analysis": "1 (OCR) + opcional 1 (batch fallback)",
            "healthy": True,
        }

        logger.info("Sistema en buen estado")
        return health_status

    except Exception as e:
        logger.error(f"Error verificando salud del sistema: {e}")
        return {"healthy": False, "error": str(e)}
