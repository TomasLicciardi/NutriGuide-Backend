# app/services/embedding_service.py

import os
import json
import logging
import numpy as np
import google.generativeai as genai
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models import Ingredient, RAGContextDocument

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class EmbeddingService:
    def __init__(self):
        self.model_name = "text-embedding-004"
        
    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Genera embedding para un texto usando text-embedding-004
        """
        try:
            result = genai.embed_content(
                model=f"models/{self.model_name}",
                content=text,
                task_type="retrieval_document"
            )
            return result['embedding']
        except Exception as e:
            logger.error(f"Error generando embedding: {e}")
            return None
    
    def generate_query_embedding(self, query: str) -> Optional[List[float]]:
        """
        Genera embedding para una consulta usando text-embedding-004
        """
        try:
            result = genai.embed_content(
                model=f"models/{self.model_name}",
                content=query,
                task_type="retrieval_query"
            )
            return result['embedding']
        except Exception as e:
            logger.error(f"Error generando embedding de consulta: {e}")
            return None

    def generate_embedding_sync(self, text: str) -> Optional[List[float]]:
        """
        Genera embedding síncrono para un texto.
        Usar en contextos no-async (inicialización, store functions).
        """
        try:
            result = genai.embed_content(
                model=f"models/{self.model_name}",
                content=text,
                task_type="retrieval_document"
            )
            return result['embedding']
        except Exception as e:
            logger.error(f"Error generando embedding síncronamente: {e}")
            return None

    def cosine_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """
        Calcula la similitud coseno entre dos embeddings
        """
        try:
            vec1 = np.array(embedding1)
            vec2 = np.array(embedding2)
            
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            return dot_product / (norm1 * norm2)
        except Exception as e:
            logger.error(f"Error calculando similitud coseno: {e}")
            return 0.0
    
    def find_similar_ingredients(self, ingredient_name: str, db: Session, threshold: float = 0.8) -> List[Tuple[Ingredient, float]]:
        """
        Encuentra ingredientes similares basado en embeddings
        """
        try:
            # Generar embedding para el ingrediente de consulta
            query_embedding = self.generate_query_embedding(ingredient_name)
            if not query_embedding:
                return []
            
            # Obtener todos los ingredientes con embeddings
            ingredients = db.query(Ingredient).filter(Ingredient.embedding.isnot(None)).all()
            
            similar_ingredients = []
            for ingredient in ingredients:
                try:
                    stored_embedding = json.loads(ingredient.embedding)
                    similarity = self.cosine_similarity(query_embedding, stored_embedding)
                    
                    if similarity >= threshold:
                        similar_ingredients.append((ingredient, similarity))
                except Exception as e:
                    logger.warning(f"Error procesando embedding del ingrediente {ingredient.id}: {e}")
                    continue
            
            # Ordenar por similitud descendente
            similar_ingredients.sort(key=lambda x: x[1], reverse=True)
            return similar_ingredients
            
        except Exception as e:
            logger.error(f"Error buscando ingredientes similares: {e}")
            return []
    
    def find_relevant_rag_documents(self, query: str, db: Session, top_k: int = 5) -> List[Tuple[RAGContextDocument, float]]:
        """
        Encuentra documentos RAG relevantes para una consulta
        """
        try:
            # Generar embedding para la consulta
            query_embedding = self.generate_query_embedding(query)
            if not query_embedding:
                return []
            
            # Obtener todos los documentos RAG con embeddings
            documents = db.query(RAGContextDocument).filter(RAGContextDocument.embedding.isnot(None)).all()
            
            relevant_docs = []
            for doc in documents:
                try:
                    stored_embedding = json.loads(doc.embedding)
                    similarity = self.cosine_similarity(query_embedding, stored_embedding)
                    relevant_docs.append((doc, similarity))
                except Exception as e:
                    logger.warning(f"Error procesando embedding del documento {doc.id}: {e}")
                    continue
            
            # Ordenar por similitud descendente y tomar los top_k
            relevant_docs.sort(key=lambda x: x[1], reverse=True)
            return relevant_docs[:top_k]
            
        except Exception as e:
            logger.error(f"Error buscando documentos RAG relevantes: {e}")
            return []
    
    def store_ingredient_embedding(self, ingredient: Ingredient, db: Session) -> bool:
        """
        Genera y almacena el embedding de un ingrediente
        """
        try:
            # Crear texto descriptivo para el embedding
            text_for_embedding = f"{ingredient.name} {ingredient.original_name} {ingredient.type.value}"

            embedding = self.generate_embedding_sync(text_for_embedding)
            if embedding:
                ingredient.embedding = json.dumps(embedding)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Error almacenando embedding del ingrediente {ingredient.id}: {e}")
            return False

    def store_rag_document_embedding(self, document: RAGContextDocument, db: Session) -> bool:
        """
        Genera y almacena el embedding de un documento RAG
        """
        try:
            # Usar título y contenido para generar el embedding
            text_for_embedding = f"{document.title} {document.content}"

            embedding = self.generate_embedding_sync(text_for_embedding)
            if embedding:
                document.embedding = json.dumps(embedding)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Error almacenando embedding del documento RAG {document.id}: {e}")
            return False

# Instancia global del servicio
embedding_service = EmbeddingService()