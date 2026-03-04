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
    """
    Mapa de aditivos DE ORIGEN ANIMAL que aparecen frecuentemente en productos
    argentinos procesados. Clave: substring normalizado (sin acentos, minúsculas).
    Valor: lista de restricciones que VIOLA ese aditivo.

    Propósito: safety net que corrige posibles alucinaciones de Gemini.
    Si Gemini dice 'vegano: true' pero hay carmín/caseinato en la lista,
    este mapa fuerza la corrección antes de devolver la respuesta.
    """
    _KNOWN_ANIMAL_ADDITIVES: Dict[str, List[str]] = {
        # ── Colorantes de insecto ── (carmín E120/INS 120)
        "carmin":             ["vegano"],
        "carmine":            ["vegano"],
        "cochinilla":         ["vegano"],
        "e 120":              ["vegano"],
        "e120":               ["vegano"],
        "ins 120":            ["vegano"],
        "ins120":             ["vegano"],
        # ── Gelatina de origen animal ──
        "gelatina":           ["vegano", "vegetariano"],
        # ── Cera de abejas ──
        "cera de abeja":      ["vegano"],
        # ── Lácteos en forma de aditivos ──
        "caseinato":          ["vegano", "sin_lactosa"],
        "caseina":            ["vegano", "sin_lactosa"],
        "lactosuero":         ["vegano", "sin_lactosa"],
        "suero de leche":     ["vegano", "sin_lactosa"],
        "proteinas de leche": ["vegano", "sin_lactosa"],
        # ── Derivados de huevo ──
        "lecitina de huevo":  ["vegano"],
        "albumina de huevo":  ["vegano"],
        "ovoalbumina":        ["vegano"],
        # ── Almidones/harinas de trigo (en aditivos) ──
        "almidon de trigo":   ["sin_gluten"],
        "harina de trigo":    ["sin_gluten"],
        "maltodextrina de trigo": ["sin_gluten"],
        "gluten de trigo":    ["sin_gluten"],
        # ── Aceites de frutos secos ──
        "aceite de mani":     ["sin_frutos_secos"],
        "aceite de almendras":["sin_frutos_secos"],
        "aceite de avellanas":["sin_frutos_secos"],
    }

    # ── Rangos INS seguros: definitivamente sintéticos, sin origen animal ──
    # No incluye 100-199 (colorantes) porque hay que analizar origen caso a caso.
    # No incluye almidones modificados (1400-1442) porque el origen puede ser trigo.
    _ANIMAL_INS_CODES: frozenset = frozenset([120, 441, 542, 904])

    @staticmethod
    def _is_safe_synthetic_ins(code: int) -> bool:
        """True si el código INS/E es de un aditivo sintético sin origen animal."""
        ANIMAL = {120, 441, 542, 904}
        if code in ANIMAL:
            return False
        return (
            200 <= code <= 239 or   # Preservantes: sorbatos, benzoatos, sulfitos
            280 <= code <= 283 or   # Propionatos
            300 <= code <= 321 or   # Antioxidantes: vitamina C, tocoferoles, BHA, BHT, TBHQ
            330 <= code <= 341 or   # Acidulantes: ácido cítrico, tartárico, fosfórico
            450 <= code <= 452 or   # Fosfatos poliméricos
            500 <= code <= 511 or   # Carbonatos/bicarbonatos/sales minerales
            551 <= code <= 580 or   # Silicatos y minerales
            620 <= code <= 635 or   # Potenciadores de sabor: glutamato, inosinato
            950 <= code <= 969      # Edulcorantes sintéticos/vegetales: aspartamo, sucralosa, stevia
        )

    # Keywords de aditivos sintéticos seguros (sin origen animal)
    _SAFE_SYNTHETIC_KEYWORDS: frozenset = frozenset([
        "sorbato", "benzoato", "propionato", "nisina",
        "acido sorbico", "acido benzoico", "acido propionico",
        "acido citrico", "citrato de sodio", "citrato de potasio", "citrato de calcio",
        "acido tartarico", "tartrato", "acido malico", "acido lactico",
        "acido fosforico", "fosfato monosodico", "fosfato disodico", "fosfato trisodico",
        "acido ascorbico", "ascorbato de sodio", "ascorbato de calcio",
        "tocoferol", "bha", "bht", "tbhq",
        "bicarbonato de sodio", "bicarbonato de calcio", "bicarbonato de amonio",
        "carbonato de sodio", "carbonato de calcio", "carbonato de potasio",
        "dioxido de carbono", "nitrogeno gaseoso",
        "goma xantica", "goma guar", "goma arabiga", "goma garrofin", "goma tara",
        "carragenina", "carragenano", "alginato", "pectina",
        "dioxido de silicio", "silicato de magnesio",
        "glutamato monosodico", "glutamato de sodio",
        "inosinato de disodio", "guanilato de disodio", "ribonucleotido disodico",
        "acesulfame", "aspartamo", "ciclamato", "sacarina", "sucralosa", "stevia",
        "esteviol", "maltitol", "xilitol", "sorbitol", "manitol",
    ])

    def _prescreen_ingredients(self, ingredients: List[str]) -> Tuple[List[str], List[str]]:
        """
        Separa ingredientes ANTES de enviarlos a Gemini:

        - need_gemini: ingredientes BASE, colorantes con posible origen animal,
          y cualquier cosa no claramente sintética. Gemini los analiza.

        - safe_synthetics: aditivos sintéticos con certeza (rangos INS seguros
          o keywords conocidos). No se envían a Gemini → menos tokens, cero
          riesgo de alucinación en ingredientes inocuos.

        CONSERVADOR: ante la duda, el ingrediente va a need_gemini.
        """
        import re
        need_gemini: List[str] = []
        safe_synthetics: List[str] = []

        for ingredient in ingredients:
            norm = self._normalize_text(ingredient)

            # Nunca marcar seguro si coincide con aditivo animal conocido
            if any(k in norm for k in self._KNOWN_ANIMAL_ADDITIVES):
                need_gemini.append(ingredient)
                continue

            # Código INS explícito → verificar si está en rango seguro
            ins_match = re.search(r'\bins\s*(\d{3,4})\b', norm)
            if ins_match:
                code = int(ins_match.group(1))
                if self._is_safe_synthetic_ins(code):
                    safe_synthetics.append(ingredient)
                else:
                    need_gemini.append(ingredient)  # colorante u otro ambiguo
                continue

            # Código E europeo → misma lógica
            e_match = re.match(r'^e(\d{3,4})[a-z]?$', norm)
            if e_match:
                code = int(e_match.group(1))
                if self._is_safe_synthetic_ins(code):
                    safe_synthetics.append(ingredient)
                else:
                    need_gemini.append(ingredient)
                continue

            # Keyword de sintético conocido
            if any(kw in norm for kw in self._SAFE_SYNTHETIC_KEYWORDS):
                safe_synthetics.append(ingredient)
                continue

            # Por defecto: necesita Gemini
            need_gemini.append(ingredient)

        return need_gemini, safe_synthetics

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
        1. Clasificar cada ingrediente como BASE/ADITIVO (para display)
        2. TODOS los ingredientes → SEGUNDA PETICIÓN a Gemini con RAG
           (porque algunos aditivos afectan restricciones: lecitina de huevo,
            caseinato de sodio, carmín/cochinilla, etc.)
        3. Combinar resultados y devolver clasificación final
        """
        try:
            logger.info(f"🔍 Iniciando clasificación de {len(ingredients)} ingredientes")
            
            # PASO 1: Clasificar cada ingrediente individualmente (BASE/ADITIVO para display)
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

            # PASO 2: Pre-screening — separar sintéticos seguros de los que necesitan Gemini
            # Esto reduce el prompt y elimina alucinaciones en aditivos inocuos (INS 200-321, etc.)
            all_ingredient_names = [ing["name"] for ing in classified_ingredients]
            ingredients_for_gemini, safe_synthetics = self._prescreen_ingredients(all_ingredient_names)

            if safe_synthetics:
                logger.info(f"⚡ {len(safe_synthetics)} sintéticos seguros omitidos en Gemini: {safe_synthetics[:5]}")

            if ingredients_for_gemini:
                logger.info(f"🤖 Enviando {len(ingredients_for_gemini)}/{len(all_ingredient_names)} ingredientes a Gemini+RAG...")

                # Contexto RAG con todos los ingredientes (incluyendo sintéticos para embeddings)
                rag_context = await rag_service.get_classification_context(all_ingredient_names, db)

                # Gemini solo analiza los ingredientes que realmente necesita ver
                final_classification = await self._classify_base_ingredients_with_rag(
                    ingredients_for_gemini, allergen_warnings, rag_context
                )

                if final_classification.get("success"):
                    logger.info("✅ Clasificación RAG exitosa")
                    result = final_classification
                else:
                    logger.warning("⚠️ Fallo Gemini RAG, usando clasificación local")
                    result = self._classify_local_fast(all_ingredient_names, allergen_warnings)
            else:
                # Todos los ingredientes son sintéticos seguros → solo verificar advertencias
                logger.info("ℹ️ Solo sintéticos seguros → clasificación local por advertencias")
                result = self._classify_additives_only(allergen_warnings)

            # PASO 3: Safety net — corregir posibles alucinaciones de Gemini
            # para aditivos de origen animal bien conocidos
            result = self._apply_known_facts_override(result, all_ingredient_names, allergen_warnings)

            # PASO 4: Agregar metadata
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
        Clasifica un ingrediente usando la DB y embeddings semánticos:
        1. Búsqueda exacta en DB (rápido)
        2. Similitud semántica por embeddings
        3. Heurística como fallback + guarda en DB con json.dumps
        """
        try:
            from app.models.ingredient import Ingredient, IngredientType
            from sqlalchemy import func

            name_lower = ingredient_name.lower().strip()

            # 1. Buscar coincidencia exacta en DB
            exact_match = db.query(Ingredient).filter(
                func.lower(Ingredient.name) == name_lower
            ).first()

            if not exact_match:
                # Búsqueda parcial como segundo intento rápido
                exact_match = db.query(Ingredient).filter(
                    func.lower(Ingredient.name).contains(name_lower)
                ).first()

            if exact_match:
                logger.info(f"✅ Encontrado en DB: {ingredient_name} → {exact_match.type.value}")
                return {
                    "name": ingredient_name,
                    "type": exact_match.type.value,
                    "confidence": 0.9,
                    "source": "database"
                }

            # 2. Buscar por similitud semántica con embeddings
            similar_by_embedding = embedding_service.find_similar_ingredients(
                ingredient_name, db, threshold=0.82
            )
            if similar_by_embedding:
                best_match, similarity = similar_by_embedding[0]
                logger.info(f"🧠 Similitud semántica: {ingredient_name} → {best_match.type.value} (sim={similarity:.2f})")
                return {
                    "name": ingredient_name,
                    "type": best_match.type.value,
                    "confidence": round(similarity, 2),
                    "source": "embedding_similarity"
                }

            # 3. Clasificación heurística como fallback
            import re
            is_additive = any(keyword in name_lower for keyword in
                             ['emulsificante', 'emulsionante', 'aromatizante', 'colorante',
                              'vitamina', 'mineral', 'lecitina', 'estabilizante', 'conservante',
                              'antioxidante', 'edulcorante', 'espesante', 'acidulante',
                              'regulador', 'potenciador', 'conservador'])

            if re.match(r'^e\d{3,4}[a-z]*$', name_lower):
                is_additive = True

            ingredient_type = "ADITIVO" if is_additive else "BASE"

            # Guardar en DB con embedding para futuras consultas (json.dumps no str())
            embedding = await embedding_service.generate_embedding(ingredient_name)
            new_ingredient = Ingredient(
                name=name_lower,
                original_name=ingredient_name,
                type=IngredientType.ADITIVO if is_additive else IngredientType.BASE,
                embedding=json.dumps(embedding) if embedding else None,
                confidence=0.75
            )
            db.add(new_ingredient)
            db.flush()

            logger.info(f"💾 Nuevo ingrediente guardado: {ingredient_name} → {ingredient_type}")
            return {
                "name": ingredient_name,
                "type": ingredient_type,
                "confidence": 0.75,
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
        Prompt OCR optimizado para etiquetas de productos alimenticios
        argentinos y latinoamericanos.
        """
        return """Analiza esta etiqueta de producto alimenticio (Argentina/Latinoamérica).

EXTRAE:
1. LISTA DE INGREDIENTES: Cada ingrediente/aditivo por separado.

REGLAS CRÍTICAS PARA ETIQUETAS ARGENTINAS:
- Abreviaturas funcionales → extraer solo el ingrediente que sigue:
  EMU: lecitina de soja → "lecitina de soja"
  ACI: ácido cítrico (INS 330) → "ácido cítrico"
  ARO: sabor a vainilla → "sabor a vainilla"
  CON: sorbato de potasio → "sorbato de potasio"
  COL: caramelo IV → "caramelo IV"
  EST: goma xántica → "goma xántica"
  RES: glutamato monosódico → "glutamato monosódico"
  SEC: EDTA disódico → "EDTA disódico"

- Enriquecimiento por ley (Ley 25.630): extraer SOLO el ingrediente base, NO los contenidos entre paréntesis con mg/kg.
  "harina de trigo enriquecida ley 25.630 (sulfato ferroso: 30mg/kg, niacina...)" → extraer "harina de trigo enriquecida"

- Sub-ingredientes entre paréntesis SÍ se extraen por separado:
  "sazonador (sal, azúcar, glutamato monosódico)" → extraer "sazonador", "sal", "azúcar", "glutamato monosódico"

- Códigos INS o E: incluirlos tal como aparecen (son aditivos técnicos):
  "lecitina de soja (INS 322)" → extraer "lecitina de soja"
  "bicarbonato de sodio (INS 500ii)" → extraer "bicarbonato de sodio"

- Ingredientes con origen especificado: mantener la descripción completa:
  "aceite vegetal de palma y canola (TBHQ)" → extraer "aceite vegetal de palma y canola", "TBHQ"

2. ADVERTENCIAS DE ALÉRGENOS: Texto completo de CONTIENE, PUEDE CONTENER, SIN TACC, LIBRE DE GLUTEN, etc.

Si la imagen NO es una etiqueta alimentaria o no se pueden leer ingredientes, responde con listas vacías.

RESPONDE ÚNICAMENTE EN JSON VÁLIDO (sin texto extra):
{
  "ingredientes_detectados": ["ingrediente1", "ingrediente2", "aditivo1"],
  "alergenos_advertencias": "CONTIENE: GLUTEN. PUEDE CONTENER: SOJA." o null,
  "confidence": 0.95
}
"""
    
    def _get_rag_classification_prompt(self, base_ingredients: List[str], allergen_warnings: str, rag_context: str) -> str:
        """
        Prompt de clasificación de restricciones para etiquetas argentinas/latinoamericanas.
        Recibe TODOS los ingredientes (BASE + ADITIVOS relevantes).
        """
        ingredients_text = ", ".join(base_ingredients)
        allergen_text = allergen_warnings if allergen_warnings else "Sin advertencias"

        return f"""Clasifica estos ingredientes de un producto argentino/latinoamericano para 5 restricciones dietéticas.

INGREDIENTES: {ingredients_text}
ADVERTENCIAS DE ALÉRGENOS: {allergen_text}

CONTEXTO DE CONOCIMIENTO:
{rag_context}

REGLAS ESPECÍFICAS PARA ARGENTINA:
- TACC = Trigo, Avena, Cebada, Centeno → "CONTIENE TACC" o "SIN TACC" afecta sin_gluten
- Caseinato de sodio / caseinato de calcio = derivado lácteo → afecta vegano y sin_lactosa
- Suero de leche / lactosuero = derivado lácteo → afecta vegano y sin_lactosa
- Carmín / Cochinilla / E120 = colorante de insecto → NO es vegano
- Lecitina de soja = OK para veganos (no es animal)
- Lecitina de huevo = NO es vegano
- TBHQ / BHA / BHT = antioxidantes sintéticos, no afectan restricciones dietéticas
- Sulfitos = aditivos conservantes, no afectan las 5 restricciones
- Carne bovina / vacuno / bovino = carne → afecta vegano y vegetariano
- Atún / anchoa / sardina / merluza = pescado → afecta vegano y vegetariano
- Las advertencias "PUEDE CONTENER" son tan importantes como "CONTIENE" para alergias
- Si NO reconoces el origen exacto de un aditivo (código INS, E, o nombre químico raro) → marca APTO. La mayoría de los aditivos son sintéticos o de origen vegetal y no afectan las 5 restricciones.
- INS 471 / E471 (monoglicéridos y diglicéridos): en Argentina se usa origen vegetal → APTO para veganos salvo que la etiqueta especifique "animal"
- ANTE LA DUDA sobre si un aditivo es animal → APTO (no falles una restricción sin certeza)

EVALÚA CADA RESTRICCIÓN:
- vegano: ¿Sin NINGÚN producto animal? (leche, huevo, carne, pescado, miel, carmín/cochinilla)
- vegetariano: ¿Sin carne ni pescado? (lácteos y huevos SÍ son aptos)
- sin_gluten: ¿Sin TACC? (trigo, avena, cebada, centeno, gluten, semolina, malta)
- sin_lactosa: ¿Sin lácteos? (leche, suero, caseinato, caseína, lactosa, queso, mantequilla)
- sin_frutos_secos: ¿Sin frutos secos? (almendra, nuez, avellana, pistacho, anacardo, maní/cacahuate, macadamia)

INSTRUCCIONES CRÍTICAS:
- Si dices "apto": true → razon debe ser null
- Si dices "apto": false → razon debe decir exactamente "Contiene [ingrediente específico]"
- Si hay "PUEDE CONTENER X" en advertencias y el usuario tiene alergia a X → apto: false

RESPONDE ÚNICAMENTE EN JSON VÁLIDO:
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
                "allergen_warnings": result.get("alergenos_advertencias"),
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
    
    def _normalize_text(self, text: str) -> str:
        """
        Normaliza texto eliminando acentos y convirtiendo a minúsculas.
        Necesario porque el OCR puede devolver "atun" o "atún" indistintamente.
        """
        import unicodedata
        return ''.join(
            c for c in unicodedata.normalize('NFD', text)
            if unicodedata.category(c) != 'Mn'
        ).lower()

    def _classify_local_fast(self, ingredients: List[str], allergen_warnings: str) -> Dict:
        """
        Clasificación local de fallback. Cubre términos argentinos y normaliza acentos.
        """
        # Normalizar todo el texto (sin acentos) para comparación robusta
        all_text = self._normalize_text(" ".join(ingredients) + " " + (allergen_warnings or ""))

        # ─── VEGANO ──────────────────────────────────────────────────────────
        # Sin ningún producto de origen animal
        animal_products = [
            # Lácteos
            "leche", "lactosa", "queso", "mantequilla", "manteca", "yogur", "yogurt",
            "crema", "nata", "suero", "caseinato", "caseina", "lactosuero", "lacteo",
            # Huevo
            "huevo", "albumina", "ovalbumina", "yema", "clara",
            # Carnes
            "carne", "pollo", "cerdo", "res", "vacuno", "bovino", "porcino", "ovino",
            "cordero", "pavo", "ave", "jamon", "embutido", "salchicha",
            # Pescado y mariscos
            "pescado", "atun", "salmon", "anchoa", "sardina", "bacalao", "merluza",
            "marisco", "camaron", "langosta", "mejillon",
            # Otros animales
            "miel", "gelatina", "carmin", "cochinilla", "e120", "ins 120", "ins120",
        ]
        vegano_blocked = any(p in all_text for p in animal_products)
        vegano_reason = next((f"Contiene {p}" for p in animal_products if p in all_text), None) if vegano_blocked else None

        # ─── VEGETARIANO ─────────────────────────────────────────────────────
        # Solo sin carne y pescado (lácteos y huevos SÍ son aptos)
        meat_fish = [
            "carne", "pollo", "cerdo", "res", "vacuno", "bovino", "porcino", "ovino",
            "cordero", "pavo", "ave", "jamon", "embutido", "salchicha",
            "pescado", "atun", "salmon", "anchoa", "sardina", "bacalao", "merluza",
            "marisco", "camaron", "langosta",
        ]
        vegetariano_blocked = any(m in all_text for m in meat_fish)
        vegetariano_reason = next((f"Contiene {m}" for m in meat_fish if m in all_text), None) if vegetariano_blocked else None

        # ─── SIN GLUTEN / SIN TACC ───────────────────────────────────────────
        gluten_sources = [
            "trigo", "cebada", "centeno", "avena", "gluten", "malta",
            "semola", "semolina", "espelta", "kamut", "farro", "triticale",
            "tacc",  # término argentino para Trigo/Avena/Cebada/Centeno
        ]
        gluten_blocked = any(g in all_text for g in gluten_sources)
        gluten_reason = next((f"Contiene {g}" for g in gluten_sources if g in all_text), None) if gluten_blocked else None

        # ─── SIN LACTOSA ─────────────────────────────────────────────────────
        dairy_products = [
            "leche", "lactosa", "queso", "mantequilla", "manteca", "yogur", "yogurt",
            "crema", "nata", "suero", "caseinato", "caseina", "lactosuero", "lacteo",
        ]
        lactosa_blocked = any(d in all_text for d in dairy_products)
        lactosa_reason = next((f"Contiene {d}" for d in dairy_products if d in all_text), None) if lactosa_blocked else None

        # ─── SIN FRUTOS SECOS ────────────────────────────────────────────────
        # Incluye maní/cacahuate (técnicamente legumbre pero tratada como fruto seco en alergias)
        nuts = [
            "almendra", "nuez", "avellana", "pistacho", "anacardo", "macadamia",
            "pecan", "castana", "mani", "cacahuate", "cacahuete",
        ]
        nuts_blocked = any(n in all_text for n in nuts)
        nuts_reason = next((f"Contiene {n}" for n in nuts if n in all_text), None) if nuts_blocked else None

        return {
            "success": True,
            "restrictions": {
                "vegano":          {"apto": not vegano_blocked,       "motivo": vegano_reason},
                "vegetariano":     {"apto": not vegetariano_blocked,  "motivo": vegetariano_reason},
                "sin_gluten":      {"apto": not gluten_blocked,       "motivo": gluten_reason},
                "sin_lactosa":     {"apto": not lactosa_blocked,      "motivo": lactosa_reason},
                "sin_frutos_secos":{"apto": not nuts_blocked,         "motivo": nuts_reason},
            },
            "confidence": 0.82,
            "method": "local_classification"
        }
    
    def _classify_additives_only(self, allergen_warnings: str) -> Dict:
        """
        Clasificación cuando solo hay aditivos.
        Aún así revisa advertencias de alérgenos, que son críticas.
        """
        # Incluso sin ingredientes base, las advertencias de alérgenos son importantes
        if allergen_warnings and allergen_warnings.strip():
            logger.info("⚠️ Solo aditivos pero hay advertencias de alérgenos, analizando...")
            result = self._classify_local_fast([], allergen_warnings)
            result["method"] = "additives_with_allergen_check"
            return result

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
    
    def _apply_known_facts_override(self, result: Dict, ingredients: List[str], allergen_warnings: str) -> Dict:
        """
        Safety net post-clasificación: corrige posibles alucinaciones de Gemini
        para los aditivos de origen animal listados en _KNOWN_ANIMAL_ADDITIVES.

        Si Gemini marcó 'vegano: true' pero la lista contiene 'carmin', 'caseinato', etc.,
        este método fuerza la corrección antes de devolver la respuesta al cliente.

        También cubre el fallback local (_classify_local_fast), por lo que actúa
        como doble red de seguridad para cualquier camino de ejecución.
        """
        if not result.get("success"):
            return result  # No tocar resultados de error

        all_text = self._normalize_text(" ".join(ingredients) + " " + (allergen_warnings or ""))
        restrictions = result.get("restrictions", {})
        overrides_applied = []

        for additive_key, affected_restrictions in self._KNOWN_ANIMAL_ADDITIVES.items():
            if additive_key in all_text:
                for restriction in affected_restrictions:
                    if restriction in restrictions:
                        current = restrictions[restriction]
                        # Solo corregir si Gemini dijo incorrectamente "apto: true"
                        if current.get("apto") is True:
                            restrictions[restriction] = {
                                "apto": False,
                                "motivo": f"Contiene {additive_key} (origen animal)"
                            }
                            overrides_applied.append(f"{restriction}←{additive_key}")

        if overrides_applied:
            logger.warning(f"🔒 Overrides aplicados por aditivos conocidos: {overrides_applied}")

        result["restrictions"] = restrictions
        return result

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