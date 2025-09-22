# app/utils/initialization.py

"""
Script de inicialización para configurar el sistema RAG y la base de datos
"""

import logging
from sqlalchemy.orm import Session
from app.database.connection import get_db, init_database
from app.services.rag_service import rag_service
from app.models import RAGContextDocument

logger = logging.getLogger(__name__)

def initialize_system():
    """
    Inicializa completamente el sistema:
    1. Crea las tablas de la base de datos
    2. Inicializa la base de conocimiento RAG
    3. Genera embeddings para documentos existentes
    """
    try:
        logger.info("Iniciando inicialización del sistema...")
        
        # 1. Inicializar base de datos
        logger.info("Creando tablas de base de datos...")
        init_database()
        
        # 2. Obtener sesión de base de datos
        db = next(get_db())
        
        # 3. Inicializar base de conocimiento RAG
        logger.info("Inicializando base de conocimiento RAG...")
        rag_service.initialize_rag_knowledge_base(db)
        
        # 4. Verificar embeddings de documentos RAG existentes
        logger.info("Verificando embeddings de documentos RAG...")
        documents_without_embeddings = db.query(RAGContextDocument).filter(
            RAGContextDocument.embedding.is_(None)
        ).all()
        
        if documents_without_embeddings:
            logger.info(f"Generando embeddings para {len(documents_without_embeddings)} documentos...")
            from app.services.embedding_service import embedding_service
            
            for doc in documents_without_embeddings:
                try:
                    embedding_service.store_rag_document_embedding(doc, db)
                    logger.info(f"Embedding generado para documento: {doc.title}")
                except Exception as e:
                    logger.error(f"Error generando embedding para documento {doc.id}: {e}")
        
        db.close()
        logger.info("✅ Inicialización del sistema completada exitosamente")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error durante la inicialización del sistema: {e}")
        return False

def verify_system_health():
    """
    Verifica que el sistema esté funcionando correctamente
    """
    try:
        logger.info("Verificando salud del sistema...")
        
        db = next(get_db())
        
        # Verificar que existan documentos RAG
        rag_docs_count = db.query(RAGContextDocument).count()
        logger.info(f"Documentos RAG en base de datos: {rag_docs_count}")
        
        # Verificar que tengan embeddings
        docs_with_embeddings = db.query(RAGContextDocument).filter(
            RAGContextDocument.embedding.isnot(None)
        ).count()
        logger.info(f"Documentos RAG con embeddings: {docs_with_embeddings}")
        
        # Verificar configuración
        from app.config.image_analysis_config import RAG_CONFIG, SUPPORTED_RESTRICTIONS
        logger.info(f"Restricciones soportadas: {list(SUPPORTED_RESTRICTIONS.keys())}")
        logger.info(f"Modelo de embeddings: {RAG_CONFIG['embedding_model']}")
        
        db.close()
        
        health_status = {
            "rag_documents": rag_docs_count,
            "documents_with_embeddings": docs_with_embeddings,
            "embeddings_coverage": docs_with_embeddings / rag_docs_count if rag_docs_count > 0 else 0,
            "supported_restrictions": list(SUPPORTED_RESTRICTIONS.keys()),
            "healthy": rag_docs_count > 0 and docs_with_embeddings == rag_docs_count
        }
        
        if health_status["healthy"]:
            logger.info("✅ Sistema en buen estado")
        else:
            logger.warning("⚠️ Sistema requiere atención")
        
        return health_status
        
    except Exception as e:
        logger.error(f"❌ Error verificando salud del sistema: {e}")
        return {"healthy": False, "error": str(e)}

if __name__ == "__main__":
    # Configurar logging
    logging.basicConfig(level=logging.INFO)
    
    # Inicializar sistema
    success = initialize_system()
    
    if success:
        # Verificar salud
        health = verify_system_health()
        print(f"\n📊 Estado del sistema: {health}")
    else:
        print("❌ La inicialización falló")