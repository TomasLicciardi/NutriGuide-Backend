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
        Inicializa la base de conocimiento RAG. Si ya existe pero le faltan
        documentos (por actualizaciones del código), los agrega sin borrar los existentes.
        """
        try:
            knowledge_documents = self._get_predefined_knowledge()
            expected_count = len(knowledge_documents)

            existing_docs = db.query(RAGContextDocument).count()
            if existing_docs >= expected_count:
                logger.info("Base de conocimiento RAG ya inicializada")
                return

            # Obtener títulos ya existentes para no duplicar
            existing_titles = {
                row[0] for row in db.query(RAGContextDocument.title).all()
            }
            added = 0
            for doc_data in knowledge_documents:
                if doc_data["title"] in existing_titles:
                    continue  # Ya existe, saltar

                document = RAGContextDocument(
                    title=doc_data["title"],
                    content=doc_data["content"],
                    document_type=doc_data["type"],
                    relevance_score=doc_data["relevance"]
                )
                db.add(document)
                db.flush()
                embedding_service.store_rag_document_embedding(document, db)
                added += 1

            db.commit()
            if added > 0:
                logger.info(f"RAG: {added} documentos nuevos agregados (total esperado: {expected_count})")

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
        Clasificación rápida BASE/ADITIVO con soporte para etiquetas argentinas:
        - Códigos INS (Argentina) y E (Europa)
        - Abreviaturas funcionales argentinas (EMU:, ACI:, ARO:, etc.)
        - Keywords comunes en etiquetas LATAM
        """
        import re
        import unicodedata

        def normalize(text: str) -> str:
            return ''.join(
                c for c in unicodedata.normalize('NFD', text)
                if unicodedata.category(c) != 'Mn'
            ).lower().strip()

        ingredient_lower = normalize(ingredient_name)

        # ── Códigos INS (Argentina/LATAM) ───────────────────────────────────
        if re.match(r'^ins\s*\d{3,4}[a-z]*$', ingredient_lower):
            return IngredientType.ADITIVO, 0.97

        # ── Códigos E (Europa) ──────────────────────────────────────────────
        if re.match(r'^e\d{3,4}[a-z]*$', ingredient_lower):
            return IngredientType.ADITIVO, 0.95

        # ── Prefijos funcionales argentinos (EMU:, ACI:, ARO:, etc.) ────────
        # Indica que lo que sigue es un aditivo funcional
        arg_prefixes = ['emu', 'aci', 'aro', 'con', 'col', 'est', 'res', 'sec', 'hum', 'rai', 'esp']
        for prefix in arg_prefixes:
            if ingredient_lower.startswith(prefix + ':') or ingredient_lower.startswith(prefix + ' :'):
                return IngredientType.ADITIVO, 0.95

        # ── Palabras clave de función tecnológica ───────────────────────────
        additive_function_keywords = [
            'emulsificante', 'emulsionante', 'estabilizante', 'conservador', 'conservante',
            'acidulante', 'antioxidante', 'aromatizante', 'colorante', 'espesante',
            'regulador de acidez', 'potenciador de sabor', 'resaltador de sabor',
            'edulcorante', 'gelificante', 'humectante', 'antiaglutinante',
            'mejorador de harina', 'leudante', 'secuestrante', 'gasificante',
        ]
        for keyword in additive_function_keywords:
            if keyword in ingredient_lower:
                return IngredientType.ADITIVO, 0.92

        # ── Aditivos comunes por nombre ──────────────────────────────────────
        named_additives = [
            'lecitina', 'bicarbonato', 'tartrato', 'citrato', 'benzoato',
            'sorbato', 'propionato', 'sulfito', 'nitrito', 'nitrato',
            'glutamato', 'inosinato', 'guanilato', 'ribonucleotido',
            'carragenina', 'carragenano', 'alginato', 'pectina',
            'goma xantica', 'goma guar', 'goma arabiga', 'goma tara',
            'maltodextrina', 'dextrina', 'almidon modificado',
            'tbhq', 'bha', 'bht', 'edta', 'tocoferol',
            'acido citrico', 'acido lactico', 'acido acetico', 'acido ascorbico',
            'acido fosforico', 'acido sorbico', 'acido tartarico',
            'caramelo', 'annatto', 'curcuma',  # colorantes comunes
            'carmin', 'cochinilla',  # colorante animal (importante para veganos)
            'vanillina', 'vainillina',  # aromatizantes artificiales
            'fosfato', 'sulfato', 'carbonato', 'cloruro de sodio',
            'oxido de zinc', 'fumarato', 'niacinamida', 'riboflavina',
            'tiamina', 'acido folico', 'vitamina',  # vitaminas como aditivos
        ]
        for additive in named_additives:
            if additive in ingredient_lower:
                return IngredientType.ADITIVO, 0.88

        # ── Patrones químicos genéricos ──────────────────────────────────────
        chemical_patterns = ['acido ', 'goma ', 'sulfato', 'fosfato', 'nitrato',
                              'carbonato', 'cloruro', 'oxido', 'hidrolizado']
        if any(p in ingredient_lower for p in chemical_patterns):
            return IngredientType.ADITIVO, 0.83

        # ── Por defecto: BASE (más conservador) ─────────────────────────────
        return IngredientType.BASE, 0.70
    
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
            },
            {
                "title": "Colorantes en Etiquetas Argentinas (INS 100-199)",
                "content": """
COLORANTES EN ETIQUETAS ARGENTINAS POR ORIGEN:

ORIGEN VEGETAL O MINERAL → APTOS PARA VEGANOS:
- INS 100 / Curcumina: pigmento de cúrcuma (vegetal)
- INS 101 / Riboflavina: vitamina B2, sintética o de levadura
- INS 140 / Clorofila: pigmento vegetal verde
- INS 141 / Complejos cúpricos de clorofila: vegetal
- INS 150a,b,c,d / Caramelo: azúcar quemada (vegetal), APTO
- INS 160a / Beta-caroteno: zanahoria o síntesis, APTO
- INS 160b / Annatto, Achiote, Bixina, Norbixina: semillas de achiote, APTO
- INS 160c / Oleorresina de pimentón: pimiento, APTO
- INS 160d / Licopeno: tomate, APTO
- INS 161b / Luteína: caléndula, APTO
- INS 162 / Rojo de remolacha, Betanina: remolacha, APTO
- INS 163 / Antocianinas: frutas rojas/moradas, APTO
- INS 170 / Carbonato de calcio: mineral, APTO

ORIGEN SINTÉTICO → APTOS PARA TODAS LAS RESTRICCIONES:
- INS 102 / Tartrazina: amarillo artificial, APTO
- INS 110 / Amarillo Ocaso FCF, Amarillo N°6: naranja artificial, APTO
- INS 122 / Azorrubina, Carmoisina: rojo artificial, APTO
- INS 123 / Amaranto: rojo artificial, APTO
- INS 124 / Ponceau 4R: rojo artificial, APTO
- INS 127 / Eritrosina: rosa/rojo artificial, APTO
- INS 129 / Rojo Allura AC, Rojo N°40: rojo artificial, APTO
- INS 131 / Azul Patentado V: azul artificial, APTO
- INS 132 / Indigotina, Índigo Carmín: azul artificial, APTO
- INS 133 / Azul Brillante FCF, Azul N°1: azul artificial, APTO
- INS 142 / Verde Sólido FCF: verde artificial, APTO
- INS 151 / Negro Brillante BN: negro artificial, APTO

ORIGEN ANIMAL → NO APTOS PARA VEGANOS:
- INS 120 / Carmín, Ácido Carmínico, Cochinilla: insecto hembra (Dactylopius coccus)
  → NO VEGANO. Puede aparecer como: E120, rojo cochinilla, colorante natural rojo
- INS 441 / Gelatina: colágeno de huesos/piel animal → NO VEGANO, NO VEGETARIANO
- INS 904 / Shellac, Goma laca: secreción de insecto → NO VEGANO

REGLA: Si la etiqueta dice solo "colorante natural rojo" sin código → posible carmín → dudoso para veganos.
""",
                "type": "colorantes",
                "relevance": 0.95
            },
            {
                "title": "Aditivos Sintéticos Seguros para las 5 Restricciones",
                "content": """
ESTOS ADITIVOS SON SEGUROS PARA VEGANO, VEGETARIANO, SIN GLUTEN, SIN LACTOSA Y SIN FRUTOS SECOS:

PRESERVANTES (INS 200-283) — todos sintéticos:
- INS 200-203 / Ácido sórbico y Sorbatos
- INS 210-213 / Ácido benzoico y Benzoatos
- INS 220-228 / Dióxido de azufre y Sulfitos
- INS 234 / Nisina: péptido de fermentación bacteriana
- INS 280-283 / Ácido propiónico y Propionatos

ANTIOXIDANTES (INS 300-321) — sintéticos o vegetales:
- INS 300-304 / Ácido ascórbico (Vitamina C) y Ascorbatos
- INS 306-309 / Tocoferoles (Vitamina E)
- INS 319 / TBHQ, INS 320 / BHA, INS 321 / BHT

ACIDULANTES Y SALES (INS 330-341):
- INS 270 / Ácido láctico: fermentación industrial (no de lactosuero)
- INS 330-333 / Ácido cítrico y Citratos
- INS 334-337 / Ácido tartárico y Tartratos
- INS 338-341 / Ácido fosfórico y Fosfatos

EMULSIFICANTES DE ORIGEN VEGETAL:
- INS 400-407 / Alginatos y Carragenina: algas marinas
- INS 410 / Goma garrofín, INS 412 / Goma guar, INS 414 / Goma arábiga
- INS 415 / Goma xántica, INS 440 / Pectinas
- INS 471 / Monoglicéridos: en Argentina origen vegetal por defecto

SALES MINERALES (INS 500-580):
- INS 500-504 / Carbonatos/Bicarbonatos, INS 551-559 / Silicatos

POTENCIADORES (INS 620-635):
- INS 621 / Glutamato monosódico, INS 627/631/635 / Nucleótidos

EDULCORANTES (INS 950-969):
- INS 950 / Acesulfame K, INS 951 / Aspartamo, INS 955 / Sucralosa
- INS 960 / Stevia (esteviol), INS 965 / Maltitol, INS 967 / Xilitol

IMPORTANTE: Almidones modificados (INS 1400-1442) pueden ser de TRIGO.
- 'Almidón modificado de maíz/mandioca/papa' → APTO sin gluten
- 'Almidón modificado' sin especificar fuente → dudoso para sin_gluten
""",
                "type": "aditivos_sinteticos",
                "relevance": 0.95
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
                ingredient_name, db, threshold=0.85
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