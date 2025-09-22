# app/services/rag_service_new.py
import json
import logging
from typing import List, Dict, Tuple, Optional
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import RAGContextDocument, Ingredient, IngredientType
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)

class RAGService:
    """
    Servicio RAG mejorado con clasificación inteligente y escalable
    """
    
    def __init__(self):
        self.ingredient_classifier = IntelligentIngredientClassifier()
    
    def initialize_rag_knowledge_base(self, db: Session):
        """
        Inicializa la base de conocimiento RAG con documentos generales y escalables
        """
        try:
            # Verificar si ya existe conocimiento
            existing_docs = db.query(RAGContextDocument).count()
            if existing_docs > 0:
                logger.info("Base de conocimiento RAG ya inicializada")
                return
            
            # Crear documentos predefinidos
            knowledge_documents = self._get_predefined_knowledge()
            
            for doc_data in knowledge_documents:
                document = RAGContextDocument(
                    title=doc_data["title"],
                    content=doc_data["content"],
                    document_type=doc_data["type"],
                    relevance=doc_data["relevance"]
                )
                
                db.add(document)
                db.flush()  # Para obtener el ID
                
                # Generar y almacenar embedding
                embedding_service.store_rag_document_embedding(document, db)
            
            db.commit()
            logger.info(f"Base de conocimiento RAG inicializada con {len(knowledge_documents)} documentos")
            
        except Exception as e:
            logger.error(f"Error inicializando base de conocimiento RAG: {e}")
            db.rollback()
    
    def get_relevant_context_for_classification(self, ingredients: List[str], db: Session) -> str:
        """
        Obtiene contexto RAG relevante para clasificación de restricciones (optimizado)
        """
        try:
            # Usar solo los primeros 3 ingredientes para acelerar la búsqueda
            key_ingredients = ingredients[:3]
            ingredients_query = " ".join(key_ingredients)
            
            # Buscar menos documentos para acelerar
            relevant_docs = embedding_service.find_relevant_rag_documents(
                ingredients_query, db, top_k=2
            )
            
            if not relevant_docs:
                # Contexto básico sin embedding search
                return self._get_basic_context()
            
            # Construir contexto más compacto
            context_parts = ["CONTEXTO RAG:\n"]
            for doc, similarity in relevant_docs:
                if similarity > 0.4:  # Umbral más alto para ser más selectivo
                    # Solo título y primera parte del contenido
                    content_preview = doc.content[:500] + "..." if len(doc.content) > 500 else doc.content
                    context_parts.append(f"**{doc.title}**: {content_preview}\n")
            
            return "\n".join(context_parts) if len(context_parts) > 1 else self._get_basic_context()
            
        except Exception as e:
            logger.error(f"Error obteniendo contexto RAG: {e}")
            return self._get_basic_context()
    
    async def get_classification_context(self, base_ingredients: List[str], db: Session) -> str:
        """
        Obtiene contexto RAG específico para clasificación de ingredientes BASE
        """
        return self.get_relevant_context_for_classification(base_ingredients, db)
    
    def _get_basic_context(self) -> str:
        """
        Contexto básico rápido sin embeddings
        """
        return """CONTEXTO RAG:
**Reglas básicas**: 
- Vegano: Sin productos animales (leche, huevo, carne, miel)
- Vegetariano: Sin carne/pescado, sí lácteos/huevos  
- Sin gluten: Sin trigo, cebada, centeno, avena
- Sin lactosa: Sin lácteos
- Sin frutos secos: Sin almendras, nueces, etc."""
    
    def classify_and_store_ingredients(self, ingredients_list: List[str], db: Session) -> List[Dict]:
        """
        Clasifica ingredientes como BASE/ADITIVO de forma rápida y eficiente
        """
        stored_ingredients = []
        
        # Búsqueda batch para acelerar
        existing_names = [ing.lower().strip() for ing in ingredients_list]
        existing_ingredients = db.query(Ingredient).filter(
            Ingredient.name.in_(existing_names)
        ).all()
        existing_dict = {ing.name: ing for ing in existing_ingredients}
        
        for ingredient_name in ingredients_list:
            name_key = ingredient_name.lower().strip()
            
            try:
                # Verificar si ya existe
                if name_key in existing_dict:
                    existing = existing_dict[name_key]
                    stored_ingredients.append({
                        "id": existing.id,
                        "name": existing.name,
                        "original_name": existing.original_name,
                        "type": existing.type.value,
                        "confidence": existing.confidence
                    })
                    continue
                
                # Clasificación rápida usando heurísticas simples
                ingredient_type, confidence = self._quick_classify_ingredient(ingredient_name)
                
                # Crear nuevo ingrediente
                new_ingredient = Ingredient(
                    name=name_key,
                    original_name=ingredient_name,
                    type=ingredient_type,
                    confidence=confidence
                )
                
                db.add(new_ingredient)
                db.flush()
                
                # Sin generar embeddings por ahora para acelerar
                # embedding_service.store_ingredient_embedding(new_ingredient, db)
                
                stored_ingredients.append({
                    "id": new_ingredient.id,
                    "name": new_ingredient.name,
                    "original_name": new_ingredient.original_name,
                    "type": new_ingredient.type.value,
                    "confidence": confidence
                })
                
            except Exception as e:
                logger.error(f"Error procesando ingrediente {ingredient_name}: {e}")
                # Fallback más rápido
                stored_ingredients.append({
                    "id": None,  # Sin ID para fallback
                    "name": name_key,
                    "original_name": ingredient_name,
                    "type": "BASE",
                    "confidence": 0.5
                })
        
        try:
            db.commit()
        except Exception as e:
            logger.error(f"Error guardando ingredientes: {e}")
            db.rollback()
        
        return stored_ingredients
    
    def _quick_classify_ingredient(self, ingredient_name: str) -> Tuple[IngredientType, float]:
        """
        Clasificación rápida usando heurísticas simples sin embeddings
        """
        ingredient_lower = ingredient_name.lower().strip()
        
        # Palabras clave para aditivos (clasificación rápida)
        additive_keywords = [
            'emulsificante', 'emulsionante', 'estabilizante', 'conservador', 'conservante',
            'acidulante', 'antioxidante', 'aromatizante', 'colorante', 'espesante',
            'regulador', 'potenciador', 'edulcorante', 'lecitina'
        ]
        
        # Verificar códigos E
        import re
        if re.match(r'^e\d{3,4}[a-z]*$', ingredient_lower):
            return IngredientType.ADITIVO, 0.95
        
        # Verificar palabras clave de aditivos
        for keyword in additive_keywords:
            if keyword in ingredient_lower:
                return IngredientType.ADITIVO, 0.9
        
        # Patrones específicos comunes
        if any(term in ingredient_lower for term in ['ácido', 'goma', 'sulfato', 'fosfato']):
            return IngredientType.ADITIVO, 0.85
        
        # Si contiene vitaminas/minerales pero es lista larga, probablemente aditivo
        if 'vitamina' in ingredient_lower and len(ingredient_lower) > 50:
            return IngredientType.ADITIVO, 0.8
        
        # Por defecto: BASE (más conservador y común)
        return IngredientType.BASE, 0.7
    
    def _get_predefined_knowledge(self) -> List[Dict]:
        """
        Documentos RAG generales y escalables - Principios aplicables a cualquier ingrediente
        """
        return [
            {
                "title": "Principios de Clasificación BASE vs ADITIVO",
                "content": """
INGREDIENTES BASE (afectan restricciones dietéticas):
- Fuentes de proteína: carnes, lácteos, huevos, legumbres, frutos secos
- Cereales y harinas: trigo, avena, arroz, maíz, cebada, centeno
- Grasas y aceites: mantequilla, aceites vegetales/animales, manteca
- Azúcares naturales: azúcar, miel, jarabe de agave, melaza
- Vegetales y frutas: frescos, deshidratados, concentrados, extractos
- Especias y hierbas naturales: sin procesamientos químicos

ADITIVOS TÉCNICOS (generalmente no afectan restricciones básicas):
- Códigos E seguidos de números (E300, E471, etc.)
- Conservantes, antioxidantes, estabilizantes
- Emulsificantes, espesantes, gelificantes  
- Colorantes artificiales, aromatizantes sintéticos
- Reguladores de pH, secuestrantes, acidulantes
- Edulcorantes artificiales (aspartamo, sucralosa)

CRITERIO PRINCIPAL: Si es reconocible como alimento = BASE, si es químico/técnico = ADITIVO
""",
                "type": "clasificacion",
                "relevance": 1.0
            },
            {
                "title": "Principios Generales - Restricción Vegana",
                "content": """
VEGANO = SIN productos de origen animal

CATEGORÍAS NO APTAS (buscar estas palabras clave):
- CARNES: carne, pollo, res, cerdo, cordero, pavo, embutidos
- PESCADOS: pescado, atún, salmón, anchoas, mariscos, camarón
- LÁCTEOS: leche, queso, mantequilla, crema, yogur, suero, caseína, caseinato
- HUEVOS: huevo, clara, yema, ovalbúmina, lecitina de huevo
- MIEL: miel, cera de abeja, propóleo, jalea real
- GELATINA: gelatina (sin especificar origen = animal)

CATEGORÍAS APTAS:
- Vegetales, frutas, cereales, legumbres
- Aceites vegetales, azúcares vegetales
- Aditivos sintéticos (no animales)

REGLA SIMPLE: Si el nombre contiene palabras de categorías no aptas = NO APTO
""",
                "type": "vegano",
                "relevance": 1.0
            },
            {
                "title": "Principios Generales - Restricción Vegetariana", 
                "content": """
VEGETARIANO = SIN carne/pescado, SÍ lácteos/huevos

CATEGORÍAS NO APTAS (buscar estas palabras clave):
- CARNES: carne, pollo, res, cerdo, cordero, pavo, embutidos
- PESCADOS: pescado, atún, salmón, anchoas, mariscos, camarón
- GELATINA ANIMAL: gelatina (sin especificar origen)

CATEGORÍAS APTAS:
- LÁCTEOS: leche, queso, mantequilla, yogur, suero, caseína, caseinato
- HUEVOS: huevo, clara, yema, ovalbúmina
- MIEL: miel y derivados de abeja
- VEGETALES: todos los ingredientes vegetales

DIFERENCIA CLAVE: Vegetarianos SÍ consumen productos animales SIN sacrificio (lácteos/huevos)
""",
                "type": "vegetariano",
                "relevance": 1.0
            },
            {
                "title": "Principios de Advertencias de Alérgenos",
                "content": """
INTERPRETACIÓN ESTÁNDAR:
"CONTIENE" = Ingrediente presente directamente
"PUEDE CONTENER" = Riesgo de contaminación cruzada en fábrica

APLICACIÓN POR TIPO DE RESTRICCIÓN:

ALERGIAS/INTOLERANCIAS ESTRICTAS:
- SIN GLUTEN: CONTIENE + PUEDE CONTENER = NO APTO
- SIN LACTOSA: CONTIENE + PUEDE CONTENER = NO APTO  
- SIN FRUTOS SECOS: CONTIENE + PUEDE CONTENER = NO APTO

RESTRICCIONES DIETÉTICAS:
- VEGANO: CONTIENE + PUEDE CONTENER productos animales = NO APTO
- VEGETARIANO: Solo si CONTIENE/PUEDE CONTENER carne/pescado = NO APTO

PRINCIPIO: Advertencias de precaución son tan importantes como ingredientes directos
""",
                "type": "advertencias",
                "relevance": 1.0
            },
            {
                "title": "Patrones de Reconocimiento de Ingredientes",
                "content": """
PALABRAS CLAVE POR CATEGORÍA:

LÁCTEOS: leche, lácteo, queso, mantequilla, yogur, crema, suero, caseína, caseinato, lacto

HUEVOS: huevo, ovo, clara, yema, ovalbúmina, lecitina de huevo

CARNES: carne, pollo, res, cerdo, cordero, pavo, embutido, jamón, salchicha

PESCADOS: pescado, atún, salmón, anchoa, marisco, camarón, langosta

GLUTEN: trigo, cebada, centeno, avena (sin certificar), malta, gluten, semolina

FRUTOS SECOS: almendra, nuez, avellana, pistacho, anacardo, macadamia, pecana

TÉCNICA: Buscar estas palabras en nombres complejos o compuestos
EJEMPLO: "proteína hidrolizada de suero" contiene "suero" = lácteo
""",
                "type": "patrones",
                "relevance": 0.9
            },
            {
                "title": "Casos Especiales y Excepciones Comunes",
                "content": """
INGREDIENTES AMBIGUOS:

LECITINA: 
- Lecitina de soja = VEGANO/VEGETARIANO ✓
- Lecitina de huevo = NO VEGANO ✗, VEGETARIANO ✓

GELATINA:
- Sin especificar origen = ANIMAL (asumir no apto vegano/vegetariano)
- Gelatina vegetal/agar = APTO para todos

VITAMINA D:
- D2 = generalmente vegetal
- D3 = frecuentemente animal (precaución veganos)

AZÚCAR:
- Azúcar blanco = puede usar hueso animal en procesamiento (estrictos veganos)
- Azúcar orgánico/moreno = generalmente vegano

PRINCIPIO: Ante la duda sobre origen, aplicar precaución según restricción
""",
                "type": "especiales",
                "relevance": 0.8
            }
        ]


class IntelligentIngredientClassifier:
    """
    Clasificador inteligente de ingredientes usando embeddings y RAG
    """
    
    def __init__(self):
        # Patrones básicos como fallback
        self.additive_keywords = [
            'estabilizante', 'conservador', 'acidulante', 'antioxidantes', 
            'aromatizantes', 'secuestrante', 'emulsificante', 'espesante',
            'colorante', 'edulcorante', 'regulador', 'potenciador'
        ]
    
    def classify_ingredient_intelligent(self, ingredient_name: str, db: Session) -> Tuple[IngredientType, float]:
        """
        Clasifica ingrediente usando sistema inteligente con embeddings y RAG
        """
        try:
            # 1. Buscar ingredientes similares ya clasificados
            similar_ingredients = embedding_service.find_similar_ingredients(
                ingredient_name, db, top_k=3
            )
            
            # Si hay alta similitud, usar esa clasificación
            if similar_ingredients:
                for ingredient, similarity in similar_ingredients:
                    if similarity > 0.85:  # Alta similitud
                        logger.info(f"Clasificación por similitud: {ingredient_name} -> {ingredient.type.value} (similitud: {similarity:.2f})")
                        return ingredient.type, similarity
            
            # 2. Usar contexto RAG para clasificar
            return self._classify_with_rag_context(ingredient_name, db)
            
        except Exception as e:
            logger.error(f"Error en clasificación inteligente: {e}")
            return self._fallback_classification(ingredient_name)
    
    def _classify_with_rag_context(self, ingredient_name: str, db: Session) -> Tuple[IngredientType, float]:
        """
        Clasifica usando contexto RAG
        """
        try:
            # Obtener contexto RAG para clasificación
            relevant_docs = embedding_service.find_relevant_rag_documents(
                f"clasificar ingrediente {ingredient_name} BASE ADITIVO", db, top_k=2
            )
            
            if not relevant_docs:
                return self._fallback_classification(ingredient_name)
            
            # Construir contexto
            context = "CONTEXTO PARA CLASIFICACIÓN:\n\n"
            for doc, similarity in relevant_docs:
                if similarity > 0.4:
                    context += f"{doc.content}\n\n"
            
            # Analizar usando heurísticas mejoradas con contexto
            return self._analyze_with_context(ingredient_name, context)
            
        except Exception as e:
            logger.error(f"Error en clasificación RAG: {e}")
            return self._fallback_classification(ingredient_name)
    
    def _analyze_with_context(self, ingredient_name: str, context: str) -> Tuple[IngredientType, float]:
        """
        Analiza ingrediente con contexto RAG usando heurísticas mejoradas
        """
        ingredient_lower = ingredient_name.lower().strip()
        
        # Verificar palabras clave de aditivos
        for keyword in self.additive_keywords:
            if keyword in ingredient_lower:
                return IngredientType.ADITIVO, 0.9
        
        # Verificar códigos E
        import re
        if re.match(r'^e\d{3,4}[a-z]*$', ingredient_lower):
            return IngredientType.ADITIVO, 0.95
        
        # Verificar patrones específicos basados en contexto
        if any(term in ingredient_lower for term in ['ácido', 'goma', 'sulfato', 'fosfato', 'nitrato']):
            return IngredientType.ADITIVO, 0.85
        
        # Verificar ingredientes base comunes
        base_patterns = ['harina', 'aceite', 'azúcar', 'sal', 'agua', 'leche', 'huevo', 'carne', 'pescado', 'tomate', 'cebolla', 'ajo']
        for pattern in base_patterns:
            if pattern in ingredient_lower:
                return IngredientType.BASE, 0.9
        
        # Por defecto, considerar como BASE (más conservador)
        return IngredientType.BASE, 0.6
    
    def _fallback_classification(self, ingredient_name: str) -> Tuple[IngredientType, float]:
        """
        Clasificación básica como fallback
        """
        ingredient_lower = ingredient_name.lower().strip()
        
        # Verificar palabras clave obvias de aditivos
        for keyword in self.additive_keywords:
            if keyword in ingredient_lower:
                return IngredientType.ADITIVO, 0.7
        
        # Por defecto BASE con baja confianza
        return IngredientType.BASE, 0.5


# Instancia global del servicio
rag_service = RAGService()