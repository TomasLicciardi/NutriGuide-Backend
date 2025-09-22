# app/services/gemini_service.py
"""
Servicio Gemini unificado para NutriGuide
- Extracción OCR de ingredientes
- Clasificación con embeddings y RAG
- Sistema híbrido local + Gemini
"""

import os
import re
import json
import logging
import io
import asyncio
import google.generativeai as genai
from PIL import Image
from app.utils.image_tools import comprimir_imagen_inteligente, analizar_calidad_imagen
from app.config.image_analysis_config import VALIDATION_CONFIG, ERROR_MESSAGES
from dotenv import load_dotenv
from typing import Dict, List, Optional, Tuple
import time
from sqlalchemy.orm import Session
from app.services.rag_service import rag_service

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash-lite")

class GeminiService:
    def __init__(self):
        self.supported_restrictions = [
            "vegano", "vegetariano", "sin_gluten", "sin_lactosa", "sin_frutos_secos"
        ]
    
    async def extract_ingredients_ocr(self, image_content: bytes, image_type: str) -> Dict:
        """
        PRIMERA PETICIÓN A GEMINI: Extracción de ingredientes (OCR)
        """
        try:
            logger.info("🔍 Iniciando extracción OCR de ingredientes con Gemini")
            
            # 1. Validar calidad de imagen
            logger.info("Validando calidad de imagen...")
            calidad_resultado = analizar_calidad_imagen(image_content)
            if not calidad_resultado["es_valida"]:
                return self._create_error_response("poor_quality", calidad_resultado["mensaje"])
            
            # 2. Comprimir imagen
            logger.info("Comprimiendo imagen...")
            imagen_pil = comprimir_imagen_inteligente(image_content, image_type)
            if not imagen_pil:
                return self._create_error_response("compression_failed", "No se pudo procesar la imagen")
            
            # 3. Convertir PIL a bytes para Gemini (optimizado)
            logger.info("Convirtiendo imagen a bytes...")
            imagen_buffer = io.BytesIO()
            imagen_pil.save(imagen_buffer, format='JPEG', quality=60, optimize=True)
            imagen_bytes = imagen_buffer.getvalue()
            
            # Si la imagen es muy grande, reducir más
            if len(imagen_bytes) > 50000:  # 50KB
                imagen_buffer = io.BytesIO()
                if max(imagen_pil.size) > 600:
                    imagen_pil.thumbnail((600, 600), Image.Resampling.LANCZOS)
                imagen_pil.save(imagen_buffer, format='JPEG', quality=50, optimize=True)
                imagen_bytes = imagen_buffer.getvalue()
            
            logger.info(f"Imagen procesada, tamaño: {len(imagen_bytes)} bytes")
            
            # 4. Construir prompt OCR
            prompt = self._get_ocr_prompt()
            
            # 5. Enviar a Gemini con manejo de errores
            logger.info("🤖 Enviando request a Gemini OCR...")
            
            max_retries = 2
            timeouts = [10, 20]  # Timeouts progresivos
            
            for attempt in range(max_retries):
                try:
                    timeout = timeouts[attempt]
                    logger.info(f"Intento {attempt + 1}/{max_retries} con timeout de {timeout}s")
                    
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            model.generate_content,
                            [prompt, {"mime_type": "image/jpeg", "data": imagen_bytes}]
                        ),
                        timeout=timeout
                    )
                    logger.info("✅ Respuesta OCR recibida de Gemini")
                    break
                    
                except asyncio.TimeoutError:
                    logger.error(f"❌ TIMEOUT DE GEMINI en intento {attempt + 1}/{max_retries} - {timeout}s")
                    if attempt == max_retries - 1:
                        return self._create_error_response("timeout", "Timeout en extracción de ingredientes")
                    
                except Exception as gemini_error:
                    logger.error(f"❌ ERROR DE GEMINI en intento {attempt + 1}: {type(gemini_error).__name__}: {gemini_error}")
                    if attempt == max_retries - 1:
                        return self._create_error_response("api_error", f"Error en API de Gemini: {str(gemini_error)}")
            
            # 6. Parsear respuesta
            logger.info("Parseando respuesta OCR...")
            result = self._parse_ocr_response(response.text)
            
            if not result.get("success"):
                logger.error("❌ FALLO EL PARSING DE GEMINI")
                logger.error(f"Respuesta de Gemini: {response.text[:500]}...")
                return self._create_error_response("parse_failed", "No se pudo interpretar la respuesta de Gemini")
            
            logger.info(f"✅ OCR exitoso: {len(result.get('ingredients', []))} ingredientes detectados")
            return result
            
        except Exception as e:
            logger.error(f"❌ ERROR GENERAL EN EXTRACCIÓN OCR: {type(e).__name__}: {e}")
            return self._create_error_response("general_error", f"Error general en OCR: {str(e)}")
    
    async def classify_ingredients_with_embeddings_and_rag(self, ingredients: List[str], allergen_warnings: str, db: Session) -> Dict:
        """
        FLUJO PRINCIPAL DE CLASIFICACIÓN:
        1. Usar embeddings DB para clasificar cada ingrediente (BASE/ADITIVO)
        2. Solo ingredientes BASE → SEGUNDA PETICIÓN a Gemini con RAG
        3. Combinar resultados y devolver clasificación final
        """
        try:
            logger.info(f"🔍 Iniciando clasificación de {len(ingredients)} ingredientes")
            
            # PASO 1: Clasificar cada ingrediente individualmente
            classified_ingredients = []
            base_ingredients = []
            
            from app.services.embedding_service import EmbeddingService
            embedding_service = EmbeddingService()
            
            for ingredient_name in ingredients:
                ingredient_data = await self._classify_ingredient_by_embeddings(
                    ingredient_name, db, embedding_service
                )
                classified_ingredients.append(ingredient_data)
                
                if ingredient_data["type"] == "BASE":
                    base_ingredients.append(ingredient_data)
            
            logger.info(f"✅ Clasificados: {len(classified_ingredients)} total, {len(base_ingredients)} BASE")
            
            # PASO 2: Solo ingredientes BASE → RAG + SEGUNDA PETICIÓN A GEMINI
            if base_ingredients:
                logger.info("🤖 Clasificando ingredientes BASE con Gemini + RAG...")
                base_names = [ing["name"] for ing in base_ingredients]
                
                # Obtener contexto RAG
                rag_context = await rag_service.get_classification_context(base_names, db)
                
                # SEGUNDA PETICIÓN A GEMINI
                final_classification = await self._classify_base_ingredients_with_rag(
                    base_names, allergen_warnings, rag_context
                )
                
                if final_classification.get("success"):
                    logger.info("✅ Clasificación RAG exitosa")
                    result = final_classification
                else:
                    logger.warning("⚠️ Fallo Gemini RAG, usando clasificación local")
                    result = self._classify_local_fast(base_names, allergen_warnings)
            else:
                logger.info("ℹ️ No hay ingredientes BASE, clasificación básica")
                result = self._classify_additives_only(allergen_warnings)
            
            # PASO 3: Agregar metadata
            result["classified_ingredients"] = classified_ingredients
            result["base_ingredients_count"] = len(base_ingredients)
            result["total_ingredients_count"] = len(classified_ingredients)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error en clasificación: {e}")
            # Fallback a clasificación local básica
            return self._classify_local_fast(ingredients, allergen_warnings)
    
    async def _classify_ingredient_by_embeddings(self, ingredient_name: str, db: Session, embedding_service) -> Dict:
        """
        Clasifica un ingrediente usando embeddings de la DB
        """
        try:
            from app.models.ingredient import Ingredient, IngredientType
            from sqlalchemy import func
            
            # Buscar ingredientes similares en DB
            similar_ingredient = db.query(Ingredient).filter(
                func.lower(Ingredient.name).contains(ingredient_name.lower())
            ).first()
            
            if similar_ingredient:
                logger.info(f"✅ Encontrado en DB: {ingredient_name} → {similar_ingredient.type.value}")
                return {
                    "name": ingredient_name,
                    "type": similar_ingredient.type.value,
                    "confidence": 0.9,
                    "source": "database"
                }
            else:
                # Clasificación heurística si no está en DB
                is_additive = any(keyword in ingredient_name.lower() for keyword in 
                                 ['emulsificante', 'emulsionante', 'aromatizante', 'colorante', 
                                  'vitamina', 'mineral', 'lecitina', 'estabilizante', 'conservante',
                                  'antioxidante', 'edulcorante', 'espesante'])
                
                ingredient_type = "ADITIVO" if is_additive else "BASE"
                
                # Guardar en DB para futuras consultas
                embedding = await embedding_service.generate_embedding(ingredient_name)
                
                new_ingredient = Ingredient(
                    name=ingredient_name.lower().strip(),
                    original_name=ingredient_name,
                    type=IngredientType.ADITIVO if is_additive else IngredientType.BASE,
                    embedding=str(embedding) if embedding else None,
                    confidence=0.8
                )
                db.add(new_ingredient)
                db.flush()
                
                logger.info(f"💾 Nuevo ingrediente: {ingredient_name} → {ingredient_type}")
                
                return {
                    "name": ingredient_name,
                    "type": ingredient_type,
                    "confidence": 0.8,
                    "source": "heuristic"
                }
                
        except Exception as e:
            logger.error(f"❌ Error clasificando {ingredient_name}: {e}")
            return {
                "name": ingredient_name,
                "type": "BASE",  # Asumir BASE por seguridad
                "confidence": 0.5,
                "source": "fallback"
            }
    
    async def _classify_base_ingredients_with_rag(self, base_ingredients: List[str], allergen_warnings: str, rag_context: str) -> Dict:
        """
        SEGUNDA PETICIÓN A GEMINI: Clasificar ingredientes BASE con contexto RAG
        """
        try:
            logger.info(f"🤖 Segunda petición Gemini: {len(base_ingredients)} ingredientes BASE")
            
            prompt = self._get_rag_classification_prompt(base_ingredients, allergen_warnings, rag_context)
            
            response = await asyncio.wait_for(
                asyncio.to_thread(model.generate_content, prompt),
                timeout=25  # Timeout más largo para RAG
            )
            
            result = self._parse_classification_response(response.text)
            if result.get("success"):
                logger.info("✅ Clasificación RAG completada")
            return result
            
        except asyncio.TimeoutError:
            logger.error("❌ Timeout en clasificación RAG")
            return {"success": False, "error": "timeout"}
        except Exception as e:
            logger.error(f"❌ Error en clasificación RAG: {e}")
            return {"success": False, "error": str(e)}
    
    def _get_ocr_prompt(self) -> str:
        """
        Prompt para extracción OCR de ingredientes
        """
        return """
Extrae la información de esta etiqueta de producto alimenticio:

1. INGREDIENTES: Lista completa de ingredientes en orden
2. ADVERTENCIAS: Texto de "CONTIENE", "PUEDE CONTENER", etc.

IMPORTANTE: 
- Separa cada ingrediente individualmente
- Incluye todas las advertencias de alérgenos
- Mantén los nombres originales de ingredientes

Responde en JSON:
{
  "ingredientes_detectados": ["ingrediente1", "ingrediente2", "ingrediente3"],
  "alerenos_advertencias": "texto completo de advertencias o null",
  "confidence": 0.95
}
"""
    
    def _get_rag_classification_prompt(self, base_ingredients: List[str], allergen_warnings: str, rag_context: str) -> str:
        """
        Prompt para clasificación RAG de ingredientes BASE
        """
        ingredients_text = ", ".join(base_ingredients)
        allergen_text = allergen_warnings if allergen_warnings else "Sin advertencias"
        
        return f"""
Clasifica estos INGREDIENTES BASE para restricciones dietéticas usando el contexto RAG.

INGREDIENTES BASE: {ingredients_text}
ADVERTENCIAS: {allergen_text}

CONTEXTO RAG:
{rag_context}

EVALÚA CADA RESTRICCIÓN:
- vegano: ¿Sin productos animales? (leche, huevo, carne, miel)
- vegetariano: ¿Sin carne/pescado? (lácteos OK)  
- sin_gluten: ¿Sin gluten/trigo?
- sin_lactosa: ¿Sin lácteos?
- sin_frutos_secos: ¿Sin frutos secos?

INSTRUCCIONES CRÍTICAS:
- CONSISTENCIA: Si dices "apto": true, la razón debe ser positiva o null
- CONSISTENCIA: Si dices "apto": false, la razón debe mencionar el ingrediente problemático
- Si es APTO: razon puede ser null o "Sin [problema] detectado" 
- Si NO es APTO: razon debe ser "Contiene [ingrediente específico]"
- NO hagas listas de ingredientes
- SÉ DIRECTO Y PRECISO

EJEMPLOS CORRECTOS:
- vegano APTO: {{"apto": true, "razon": null}} 
- vegano NO APTO: {{"apto": false, "razon": "Contiene leche"}}
- gluten APTO: {{"apto": true, "razon": null}}
- gluten NO APTO: {{"apto": false, "razon": "Contiene trigo"}}

JSON RESPUESTA:
{{
  "vegano": {{"apto": true/false, "razon": null o "Contiene [ingrediente]"}},
  "vegetariano": {{"apto": true/false, "razon": null o "Contiene [ingrediente]"}},
  "sin_gluten": {{"apto": true/false, "razon": null o "Contiene [ingrediente]"}},
  "sin_lactosa": {{"apto": true/false, "razon": null o "Contiene [ingrediente]"}},
  "sin_frutos_secos": {{"apto": true/false, "razon": null o "Contiene [ingrediente]"}},
  "confidence": 0.95
}}
"""
    
    def _parse_ocr_response(self, response_text: str) -> Dict:
        """
        Parsea respuesta OCR de Gemini
        """
        try:
            # Buscar JSON en la respuesta
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                result = json.loads(response_text)
            
            # Validar estructura
            if not isinstance(result.get("ingredientes_detectados"), list):
                raise ValueError("ingredientes_detectados debe ser una lista")
            
            return {
                "success": True,
                "ingredients": result["ingredientes_detectados"],
                "allergen_warnings": result.get("alerenos_advertencias"),
                "confidence": result.get("confidence", 0.5)
            }
            
        except Exception as e:
            logger.error(f"Error parseando OCR: {e}")
            return {"success": False, "error": "parse_failed"}
    
    def _parse_classification_response(self, response_text: str) -> Dict:
        """
        Parsea respuesta de clasificación RAG
        """
        try:
            logger.info(f"🔍 Parseando respuesta de Gemini: {response_text[:200]}...")
            
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                result = json.loads(response_text)
            
            logger.info(f"✅ JSON parseado exitosamente: {result}")
            
            # Normalizar estructura - mapea "razon" a "motivo"
            restrictions = {}
            for restriction in self.supported_restrictions:
                if restriction in result:
                    # Tomar razon del resultado y mapear a motivo
                    motivo = result[restriction].get("razon", "Sin motivo especificado")
                    apto = bool(result[restriction].get("apto", False))
                    
                    # Validar que motivo no sea None antes de procesar
                    if motivo is None:
                        motivo = None
                    elif isinstance(motivo, str):
                        # Lógica de motivos corregida:
                        if apto:
                            # Si es APTO y dice "sin X detectado" → motivo = null
                            if any(phrase in motivo.lower() for phrase in ["sin", "detectado", "no contiene"]):
                                motivo = None
                        else:
                            # Si NO es APTO pero dice "sin X detectado" → contradicción, corregir
                            if any(phrase in motivo.lower() for phrase in ["sin", "detectado", "no contiene"]):
                                # Cambiar a apto = True ya que no hay problema detectado
                                apto = True
                                motivo = None
                    else:
                        motivo = None  # Fallback si motivo no es string ni None
                    
                    restrictions[restriction] = {
                        "apto": apto,
                        "motivo": motivo
                    }
                else:
                    restrictions[restriction] = {"apto": True, "motivo": None}
            
            return {
                "success": True,
                "restrictions": restrictions,
                "confidence": result.get("confidence", 0.5)
            }
            
        except Exception as e:
            logger.error(f"Error parseando clasificación: {e}")
            return {"success": False, "error": "parse_failed"}
    
    def _classify_local_fast(self, ingredients: List[str], allergen_warnings: str) -> Dict:
        """
        Clasificación local rápida y precisa (fallback)
        """
        all_text = " ".join(ingredients).lower() + " " + (allergen_warnings or "").lower()
        
        # Buscar productos animales
        animal_products = ["huevo", "leche", "carne", "pollo", "pescado", "miel", "gelatina", 
                          "caseinato", "suero", "lactosa", "queso", "mantequilla", "yogur"]
        vegano_blocked = any(product in all_text for product in animal_products)
        
        # Solo carne y pescado para vegetarianos
        meat_fish = ["carne", "pollo", "pescado", "cerdo", "res", "cordero", "atún", "salmón"]
        vegetariano_blocked = any(meat in all_text for meat in meat_fish)
        
        # Gluten
        gluten_sources = ["trigo", "cebada", "centeno", "avena", "gluten", "malta", "sémola"]
        gluten_blocked = any(source in all_text for source in gluten_sources)
        
        # Lácteos
        dairy_products = ["leche", "lactosa", "queso", "mantequilla", "yogur", "suero", "caseinato"]
        lactosa_blocked = any(dairy in all_text for dairy in dairy_products)
        
        # Frutos secos
        nuts = ["almendra", "nuez", "avellana", "pistacho", "anacardo", "macadamia", "pecana"]
        nuts_blocked = any(nut in all_text for nut in nuts)
        
        return {
            "success": True,
            "restrictions": {
                "vegano": {
                    "apto": not vegano_blocked,
                    "motivo": "Contiene productos animales" if vegano_blocked else None
                },
                "vegetariano": {
                    "apto": not vegetariano_blocked,
                    "motivo": "Contiene carne/pescado" if vegetariano_blocked else None
                },
                "sin_gluten": {
                    "apto": not gluten_blocked,
                    "motivo": "Contiene gluten" if gluten_blocked else None
                },
                "sin_lactosa": {
                    "apto": not lactosa_blocked,
                    "motivo": "Contiene lácteos" if lactosa_blocked else None
                },
                "sin_frutos_secos": {
                    "apto": not nuts_blocked,
                    "motivo": "Contiene frutos secos" if nuts_blocked else None
                }
            },
            "confidence": 0.8,
            "method": "local_classification"
        }
    
    def _classify_additives_only(self, allergen_warnings: str) -> Dict:
        """
        Clasificación cuando solo hay aditivos
        """
        return {
            "success": True,
            "restrictions": {
                "vegano": {"apto": True, "motivo": None},
                "vegetariano": {"apto": True, "motivo": None},
                "sin_gluten": {"apto": True, "motivo": None},
                "sin_lactosa": {"apto": True, "motivo": None},
                "sin_frutos_secos": {"apto": True, "motivo": None}
            },
            "confidence": 0.7,
            "method": "additives_only"
        }
    
    def _create_error_response(self, error_type: str, message: str) -> Dict:
        """
        Crea respuesta de error estandarizada
        """
        return {
            "success": False,
            "error": error_type,
            "message": message,
            "confidence": 0.0
        }

# Instancia global del servicio
gemini_service = GeminiService()