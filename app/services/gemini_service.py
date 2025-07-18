# app/services/gemini_service.py

import os
import re
import json
import logging
import google.generativeai as genai
from app.utils.image_tools import comprimir_imagen_inteligente, analizar_calidad_imagen
from app.config.image_analysis_config import VALIDATION_CONFIG, ERROR_MESSAGES
from dotenv import load_dotenv
from typing import Dict, List, Optional, Tuple
import time

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash-lite")

# Configuración para validación cruzada (desde config)
CONFIDENCE_THRESHOLD = VALIDATION_CONFIG["confidence_threshold"]
CRITICAL_CONFIDENCE_THRESHOLD = VALIDATION_CONFIG["minimum_confidence_for_critical"]
MAX_RETRIES = VALIDATION_CONFIG["max_retries"]
RETRY_DELAY = VALIDATION_CONFIG["retry_delay"]
CRITICAL_RESTRICTIONS = VALIDATION_CONFIG["critical_restrictions"]

BASE_PROMPT = """
Analiza la imagen de una etiqueta de producto alimenticio de forma precisa y estructurada. 

IMPORTANTE: Antes de realizar cualquier análisis, VERIFICA que la imagen sea de una etiqueta nutricional o de ingredientes de un producto alimenticio. Si la imagen NO es una etiqueta nutricional válida, devuelve el siguiente JSON:

```json
{
  "error": "invalid_image",
  "message": "La imagen no corresponde a una etiqueta nutricional válida. Por favor, tome una foto clara de la etiqueta de ingredientes del producto.",
  "confidence": 0.0
}
```

Si la imagen es borrosa, oscura o no se puede leer claramente, devuelve:

```json
{
  "error": "poor_quality",
  "message": "La imagen está borrosa o es difícil de leer. Por favor, tome una foto más clara con mejor iluminación.",
  "confidence": 0.0
}
```

Si NO puedes encontrar una sección de "Ingredientes" o información de alérgenos, devuelve:

```json
{
  "error": "no_ingredients",
  "message": "No se puede identificar la lista de ingredientes en la imagen. Por favor, tome una foto que muestre claramente la sección de ingredientes.",
  "confidence": 0.0
}
```

Si la imagen es válida y legible, sigue estas instrucciones exactamente:

1. Extrae la lista de ingredientes y escribe todos los ingredientes encontrados en una única línea, separados por comas. No incluyas encabezados como "Ingredientes:", ni puntos, ni información adicional.

2. Para la información de alérgenos:
   - Busca CUALQUIER sección que mencione alérgenos o trazas, como: "PUEDE CONTENER", "CONTIENE", "CONTIENE TRAZAS", "PUEDE CONTENER TRAZAS", etc.
   - Si encuentras CUALQUIERA de estas secciones, copia literalmente todo su contenido después del título.
   - IMPORTANTE: Tanto "CONTIENE" como "PUEDE CONTENER" deben tratarse exactamente igual - ambos indican información de alérgenos importante.
   - Solo devuelve null si NO existe ninguna sección de información de alérgenos en toda la etiqueta.
   - Si hay información de alérgenos, siempre inclúyela sin importar si dice "CONTIENE" o "PUEDE CONTENER".

3. Evalúa si el producto contiene ingredientes NO APTOS para ciertas restricciones alimenticias.

4. CALCULA un nivel de confianza (0.0 a 1.0) basado en:
   - Claridad del texto: 0.4 puntos máximo
   - Completitud de la información: 0.3 puntos máximo
   - Certeza en la clasificación: 0.3 puntos máximo

DEFINICIONES CRÍTICAS - LEE CUIDADOSAMENTE:

**VEGANO (vegano)**:
Los veganos NO pueden consumir NINGÚN producto de origen animal, sin importar si el animal está vivo o muerto.

- NO PUEDEN CONSUMIR (TODO lo de origen animal):
  * Carne de cualquier tipo (res, cerdo, cordero, etc.)
  * Aves (pollo, pavo, pato, etc.)
  * Pescados y mariscos (salmón, atún, camarones, etc.)
  * Productos lácteos (leche, queso, mantequilla, suero de leche, caseína, etc.)
  * Huevos y derivados (clara de huevo, yema de huevo, lecitina de huevo)
  * Miel y productos de abejas
  * Gelatina animal (obtenida de huesos y cartílagos)
  * Renina animal (enzima del estómago de terneros)
  * Extractos de carne o pescado
  * Grasa animal (sebo, manteca de cerdo)
  * Cochinilla (colorante E120 de insectos)
  * Cualquier derivado animal aunque provenga de animales vivos

- REGLA FUNDAMENTAL: Si contiene CUALQUIER ingrediente de origen animal (vivo o muerto), NO ES APTO para veganos
- EJEMPLO CLAVE: "Suero de leche" = NO APTO para vegano (es derivado lácteo)

**SIN GLUTEN (sin_gluten)**:
- NO PUEDEN CONSUMIR: 
  * Trigo y derivados (harina de trigo, gluten, sémola, bulgur)
  * Cebada y derivados (malta, extracto de malta, jarabe de malta)
  * Centeno y derivados
  * Avena (a menos que especifique "sin gluten" o "libre de gluten")
  * Triticale (híbrido de trigo y centeno)
  * Espelta, kamut, farro
  * Almidón modificado (si no especifica origen)

**SIN FRUTOS SECOS (sin_frutos_secos)**:
- NO PUEDEN CONSUMIR:
  * Frutos secos del árbol: almendras, nueces, avellanas, pistachos, anacardos, pecanas, macadamias, nueces de Brasil, piñones
  * Aceites de frutos secos
  * Harinas de frutos secos
  * Mantequillas de frutos secos (mantequilla de almendra, etc.)
  * NOTA: Los cacahuetes NO son frutos secos (son legumbres), pero pueden estar en restricciones personalizadas

**SIN LACTOSA (sin_lactosa)**:
- NO PUEDEN CONSUMIR:
  * Leche y derivados lácteos que contengan lactosa
  * Productos que contengan "lactosa" como ingrediente
  * NOTA: Algunos quesos maduros y productos "sin lactosa" SÍ son aptos

- Si el usuario proporciona una lista personalizada de restricciones, analiza **únicamente** esas.
- Si la lista está vacía, evalúa **todas** las restricciones predeterminadas.

Para cada restricción evaluada:
- Usa `"apto": true` si es apto.
- Usa `"apto": false` y proporciona una clave `"razon"` con una justificación **clara y breve** basada en los ingredientes.
- Si es apto, **NO** incluyas la clave `"razon"`.

Devuelve el resultado **en un único bloque de código JSON**, encerrado entre ```json y ```.

EJEMPLOS de cómo manejar información de alérgenos:
- Si ve "PUEDE CONTENER: Gluten, Soja" → "puede_contener": "Gluten, Soja"
- Si ve "CONTIENE: Leche, Huevo" → "puede_contener": "Leche, Huevo"
- Si ve "CONTIENE TRAZAS DE: Frutos secos" → "puede_contener": "Frutos secos"
- Si NO hay ninguna sección de alérgenos → "puede_contener": null

EJEMPLOS ESPECÍFICOS PARA ACLARAR CONCEPTOS:

1. Producto con "Suero de leche, Cacao, Azúcar":
   - vegano: { "apto": false, "razon": "Contiene suero de leche (derivado lácteo)" }
   - sin_lactosa: { "apto": false, "razon": "Contiene suero de leche (contiene lactosa)" }

2. Producto con "Caseína, Azúcar, Vainilla":
   - vegano: { "apto": false, "razon": "Contiene caseína (proteína láctea)" }
   - sin_lactosa: { "apto": true }

3. Producto con "Harina de trigo, Azúcar, Sal":
   - sin_gluten: { "apto": false, "razon": "Contiene harina de trigo" }
   - vegano: { "apto": true }

4. Producto con "Aceite de almendra, Azúcar, Vainilla":
   - sin_frutos_secos: { "apto": false, "razon": "Contiene aceite de almendra" }
   - vegano: { "apto": true }

5. Producto con "Gelatina, Azúcar, Colorante":
   - vegano: { "apto": false, "razon": "Contiene gelatina animal" }
   - sin_gluten: { "apto": true }

LISTA COMPLETA DE DERIVADOS LÁCTEOS NO APTOS PARA VEGANOS:
- Suero de leche, suero en polvo
- Caseína, caseinato de sodio/calcio
- Lactosa, galactosa
- Proteína de suero (whey protein)
- Lactoalbúmina, lactoglobulina
- Mantequilla, butter oil
- Crema, nata, cream
- Todos los tipos de queso y derivados

CASOS ESPECIALES Y ACLARACIONES:
- "Lecitina de soja" = APTO para veganos (es vegetal)
- "Lecitina de huevo" = NO APTO para veganos
- "Aceite vegetal" = APTO para veganos
- "Gelatina" (sin especificar) = ASUME que es animal, NO APTO para veganos
- "Vitamina D3" = Puede ser de origen animal, ser cauteloso
- "Ácido láctico" = Generalmente vegetal, APTO para veganos (a menos que especifique origen animal)

Ejemplo de formato:
```json
{
  "ingredientes": "agua, azúcar, jarabe de glucosa, colorante natural",
  "puede_contener": "SOJA Y DERIVADOS DE TRIGO",
  "clasificacion": {
    "vegano": { "apto": true },
    "sin_gluten": { "apto": false, "razon": "Puede contener derivados de trigo" },
    "sin_frutos_secos": { "apto": true },
    "sin_lactosa": { "apto": true }
  },
  "confidence": 0.90
}
"""

# Funciones auxiliares para validación y manejo de errores
def validar_respuesta_gemini(respuesta: str, restricciones: List[str] = None) -> Tuple[bool, Optional[Dict]]:
    """
    Valida la respuesta de Gemini y extrae el JSON.
    Retorna (es_valida, resultado_json)
    """
    try:
        # Buscar el JSON en la respuesta
        m = re.search(r"```json\n(.*?)```", respuesta, re.DOTALL)
        if not m:
            logger.warning("No se encontró JSON en la respuesta de Gemini")
            return False, None
        
        resultado = json.loads(m.group(1))
        
        # Verificar si es un error de validación
        if "error" in resultado:
            return False, resultado
        
        # Verificar estructura básica
        if "ingredientes" not in resultado:
            logger.warning("Respuesta sin ingredientes")
            return False, None
        
        # Verificar confianza si existe
        confidence = resultado.get('confidence', 0.5)
        
        # Validar confianza diferencial
        restricciones_para_validar = restricciones if restricciones else []
        confianza_valida, mensaje_confianza = validar_confianza_diferencial(
            resultado, restricciones_para_validar
        )
        
        if not confianza_valida:
            logger.warning(f"Confianza insuficiente: {mensaje_confianza}")
            return False, resultado
        
        return True, resultado
    
    except json.JSONDecodeError as e:
        logger.error(f"Error al parsear JSON: {e}")
        return False, None
    except Exception as e:
        logger.error(f"Error inesperado validando respuesta: {e}")
        return False, None

def manejar_error_gemini(error_type: str, mensaje: str = None) -> Dict:
    """
    Maneja diferentes tipos de errores de Gemini de forma estructurada.
    """
    return {
        "error": error_type,
        "message": mensaje or ERROR_MESSAGES.get(error_type, "Error desconocido"),
        "confidence": 0.0,
        "ingredientes": None,
        "puede_contener": None,
        "clasificacion": {}
    }

def validar_confianza_diferencial(resultado: Dict, restricciones: List[str]) -> Tuple[bool, str]:
    """
    Valida confianza con diferentes umbrales según criticidad de restricciones.
    Restricciones críticas (alergias severas) requieren mayor confianza.
    """
    confidence = resultado.get('confidence', 0.0)
    
    # Verificar si hay restricciones críticas
    tiene_restriccion_critica = any(
        restriccion in CRITICAL_RESTRICTIONS 
        for restriccion in restricciones
    )
    
    if tiene_restriccion_critica:
        umbral_requerido = CRITICAL_CONFIDENCE_THRESHOLD  # 90%
        tipo_restriccion = "crítica"
    else:
        umbral_requerido = CONFIDENCE_THRESHOLD  # 90%
        tipo_restriccion = "normal"
    
    es_valido = confidence >= umbral_requerido
    
    mensaje = f"Confianza {confidence:.1%} ({'✅' if es_valido else '❌'}) - Umbral {tipo_restriccion}: {umbral_requerido:.1%}"
    
    if not es_valido:
        logger.warning(f"Confianza insuficiente: {confidence:.2f} < {umbral_requerido:.2f} (restricción {tipo_restriccion})")
    
    return es_valido, mensaje

async def validacion_cruzada_gemini(imagen, prompt: str, restricciones: List[str] = None, max_intentos: int = 3) -> Dict:
    """
    Realiza validación cruzada con múltiples intentos para mejorar la precisión.
    """
    intentos = []
    
    for i in range(max_intentos):
        try:
            logger.info(f"Intento {i + 1} de análisis")
            
            # Hacer la solicitud a Gemini
            respuesta = model.generate_content([prompt, imagen])
            
            # Validar la respuesta
            es_valida, resultado = validar_respuesta_gemini(respuesta.text, restricciones)
            
            if es_valida:
                resultado['intentos_realizados'] = i + 1
                logger.info(f"Análisis exitoso en intento {i + 1}")
                return resultado
            
            # Si hay error específico, retornarlo inmediatamente
            if resultado and "error" in resultado:
                return resultado
            
            intentos.append(resultado)
            
            # Esperar antes del siguiente intento
            if i < max_intentos - 1:
                time.sleep(RETRY_DELAY)
                
        except Exception as e:
            logger.error(f"Error en intento {i + 1}: {str(e)}")
            if i == max_intentos - 1:
                return manejar_error_gemini("api_error", f"Error del servicio: {str(e)}")
            time.sleep(RETRY_DELAY)
    
    # Si llegamos aquí, todos los intentos fallaron
    return manejar_error_gemini("api_error", "No se pudo procesar la imagen después de múltiples intentos")

async def analizar_imagen(contenido: bytes, restricciones: list[str] | None = None):
    """
    Analiza una imagen de etiqueta nutricional con validación avanzada y manejo de errores.
    """
    try:
        # 1. Analizar calidad de la imagen
        logger.info("Analizando calidad de la imagen")
        calidad_info = analizar_calidad_imagen(contenido)
        
        if not calidad_info['es_valida']:
            logger.warning(f"Imagen rechazada por calidad: {calidad_info['razon']}")
            return manejar_error_gemini("poor_quality", calidad_info['razon'])
        
        # 2. Comprimir imagen de manera inteligente
        logger.info("Comprimiendo imagen de manera inteligente")
        imagen = comprimir_imagen_inteligente(contenido, tipo_analisis="etiqueta_nutricional")
        
        # 3. Preparar el prompt según las restricciones
        if not restricciones or len(restricciones) == 0:
            # Prompt simplificado para análisis básico
            prompt_simple = """
            Analiza la imagen de una etiqueta de producto alimenticio y extrae únicamente la información básica.

            IMPORTANTE: Antes de realizar cualquier análisis, VERIFICA que la imagen sea de una etiqueta nutricional válida. Si NO es una etiqueta nutricional, devuelve error "invalid_image".

            Si la imagen es borrosa o no se puede leer claramente, devuelve error "poor_quality".

            Si NO puedes encontrar una sección de "Ingredientes", devuelve error "no_ingredients".

            Si la imagen es válida y legible, sigue estas instrucciones:

            1. Extrae la lista de ingredientes y escribe todos los ingredientes encontrados en una única línea, separados por comas.
            
            2. Para la información de alérgenos:
               - Busca CUALQUIER sección que mencione alérgenos o trazas
               - Si encuentras información de alérgenos, inclúyela
               - Si NO hay información de alérgenos, devuelve null

            3. Calcula un nivel de confianza (0.0 a 1.0) basado en la claridad del texto.

            Devuelve el resultado en formato JSON:
            ```json
            {
              "ingredientes": "lista de ingredientes",
              "puede_contener": "información de alérgenos o null",
              "clasificacion": {},
              "confidence": 0.85
            }
            ```

            Para errores, usa este formato:
            ```json
            {
              "error": "tipo_error",
              "message": "mensaje descriptivo",
              "confidence": 0.0
            }
            ```
            """
            
            # Realizar análisis con validación cruzada
            logger.info("Realizando análisis básico con validación cruzada")
            resultado = await validacion_cruzada_gemini(imagen, prompt_simple, restricciones=[])
            
            # Asegurar que clasificación esté vacía para usuarios sin restricciones
            if "clasificacion" not in resultado:
                resultado['clasificacion'] = {}
            
            return resultado
        
        # 4. Análisis completo con restricciones
        prompt_completo = BASE_PROMPT
        prompt_completo += "\n\n**Solo evaluar estas restricciones:** " + ", ".join(restricciones) + "."
        prompt_completo += "\n\nINCLUYE un campo 'confidence' con el nivel de confianza del análisis (0.0 a 1.0)."
        
        logger.info(f"Realizando análisis completo para restricciones: {restricciones}")
        resultado = await validacion_cruzada_gemini(imagen, prompt_completo, restricciones)
        
        # 5. Limpiar resultado eliminando razones para productos aptos
        if "clasificacion" in resultado:
            clasificacion = resultado['clasificacion']
            for restriccion in clasificacion:
                if clasificacion[restriccion].get('apto', True):
                    clasificacion[restriccion] = {'apto': True}
        
        # 6. Validar confianza diferencial según restricciones críticas
        restricciones_eval = restricciones if restricciones else []
        es_confianza_valida, mensaje_confianza = validar_confianza_diferencial(resultado, restricciones_eval)
        
        if not es_confianza_valida:
            return manejar_error_gemini("low_confidence", mensaje_confianza)
        
        # 7. Logging del resultado
        confidence = resultado.get('confidence', 0.0)
        logger.info(f"Análisis completado con confianza: {confidence}")
        
        return resultado
        
    except Exception as e:
        logger.error(f"Error inesperado en analizar_imagen: {str(e)}")
        return manejar_error_gemini("api_error", f"Error interno: {str(e)}")
