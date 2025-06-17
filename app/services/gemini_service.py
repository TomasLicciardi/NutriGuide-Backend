# app/services/gemini_service.py

import os
import re
import json
import google.generativeai as genai
from app.utils.image_tools import comprimir_imagen
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash-lite")

BASE_PROMPT = """
Analiza la imagen de una etiqueta de producto alimenticio de forma precisa y estructurada. 

Sigue estas instrucciones exactamente:

1. Extrae la lista de ingredientes y escribe todos los ingredientes encontrados en una única línea, separados por comas. No incluyas encabezados como "Ingredientes:", ni puntos, ni información adicional.

2. Para la información de alérgenos:
   - Busca CUALQUIER sección que mencione alérgenos o trazas, como: "PUEDE CONTENER", "CONTIENE", "CONTIENE TRAZAS", "PUEDE CONTENER TRAZAS", etc.
   - Si encuentras CUALQUIERA de estas secciones, copia literalmente todo su contenido después del título.
   - IMPORTANTE: Tanto "CONTIENE" como "PUEDE CONTENER" deben tratarse exactamente igual - ambos indican información de alérgenos importante.
   - Solo devuelve null si NO existe ninguna sección de información de alérgenos en toda la etiqueta.
   - Si hay información de alérgenos, siempre inclúyela sin importar si dice "CONTIENE" o "PUEDE CONTENER".

3. Evalúa si el producto contiene ingredientes NO APTOS para ciertas restricciones alimenticias.

DEFINICIONES CRÍTICAS - LEE CUIDADOSAMENTE:

**VEGETARIANO (vegetariano)**: 
Los vegetarianos pueden consumir productos derivados de animales VIVOS, pero NO productos que requieran la muerte del animal.

- NO PUEDEN CONSUMIR (productos que requieren muerte del animal):
  * Carne de cualquier tipo (res, cerdo, cordero, etc.)
  * Aves (pollo, pavo, pato, etc.)
  * Pescados y mariscos (salmón, atún, camarones, etc.)
  * Gelatina animal (obtenida de huesos y cartílagos)
  * Renina animal (enzima del estómago de terneros)
  * Extractos de carne o pescado
  * Grasa animal (sebo, manteca de cerdo)
  * Cochinilla (colorante E120 de insectos)

- SÍ PUEDEN CONSUMIR (derivados de animales VIVOS):
  * TODOS los productos lácteos: leche, yogurt, queso, mantequilla, crema, nata
  * TODOS los derivados lácteos: suero de leche, lactosa, caseína, caseinato, proteína de suero
  * Huevos y derivados: clara de huevo, yema de huevo, lecitina de huevo
  * Miel y productos de abejas

- REGLA FUNDAMENTAL: Si el ingrediente proviene de un animal VIVO (sin dañarlo), ES APTO para vegetarianos
- EJEMPLO CLAVE: "Suero de leche" = APTO para vegetariano (es un derivado lácteo)

**VEGANO (vegano)**:
Los veganos NO pueden consumir NINGÚN producto de origen animal, sin importar si el animal está vivo o muerto.

- NO PUEDEN CONSUMIR (TODO lo de origen animal):
  * Todo lo que los vegetarianos no pueden consumir (carnes, pescados, etc.)
  * ADEMÁS: todos los productos lácteos (leche, queso, mantequilla, suero de leche, caseína, etc.)
  * Huevos y derivados
  * Miel y productos de abejas
  * Cualquier derivado animal aunque provenga de animales vivos

- REGLA FUNDAMENTAL: Si contiene CUALQUIER ingrediente de origen animal (vivo o muerto), NO ES APTO para veganos
- EJEMPLO CLAVE: "Suero de leche" = NO APTO para vegano (aunque provenga de animal vivo)

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
   - vegetariano: { "apto": true } - El suero de leche es un DERIVADO lácteo de animal vivo
   - vegano: { "apto": false, "razon": "Contiene suero de leche (derivado lácteo)" }

2. Producto con "Caseína, Azúcar, Vainilla":
   - vegetariano: { "apto": true } - La caseína es una proteína láctea de animal vivo
   - vegano: { "apto": false, "razon": "Contiene caseína (proteína láctea)" }

3. Producto con "Lecitina de huevo, Harina, Azúcar":
   - vegetariano: { "apto": true } - La lecitina de huevo proviene de animal vivo
   - vegano: { "apto": false, "razon": "Contiene lecitina de huevo" }

4. Producto con "Gelatina, Azúcar, Colorante":
   - vegetariano: { "apto": false, "razon": "Contiene gelatina animal" } - La gelatina requiere muerte del animal
   - vegano: { "apto": false, "razon": "Contiene gelatina animal" }

5. Producto con "Lactosa, Cacao, Azúcar":
   - vegetariano: { "apto": true } - La lactosa es azúcar de la leche (derivado lácteo)
   - vegano: { "apto": false, "razon": "Contiene lactosa (derivado lácteo)" }

LISTA COMPLETA DE DERIVADOS LÁCTEOS APTOS PARA VEGETARIANOS (pero NO para veganos):
- Suero de leche, suero en polvo
- Caseína, caseinato de sodio/calcio
- Lactosa, galactosa
- Proteína de suero (whey protein)
- Lactoalbúmina, lactoglobulina
- Mantequilla, butter oil
- Crema, nata, cream
- Todos los tipos de queso y derivados

CASOS ESPECIALES Y ACLARACIONES:
- "Lecitina de soja" = APTO para vegetarianos y veganos (es vegetal)
- "Lecitina de huevo" = APTO para vegetarianos, NO APTO para veganos
- "Aceite vegetal" = APTO para vegetarianos y veganos
- "Gelatina" (sin especificar) = ASUME que es animal, NO APTO para vegetarianos ni veganos
- "Vitamina D3" = Puede ser de origen animal, ser cauteloso
- "Ácido láctico" = Generalmente vegetal, APTO para ambos (a menos que especifique origen animal)

Ejemplo de formato:
```json
{
  "ingredientes": "agua, azúcar, jarabe de glucosa, colorante natural",
  "puede_contener": "SOJA Y DERIVADOS DE TRIGO",
  "clasificacion": {
    "vegano": { "apto": false, "razon": "Contiene caseinato de sodio" },
    "vegetariano": { "apto": true },
    "celiaco": { "apto": true }
  }
}
"""

async def analizar_imagen(contenido: bytes, restricciones: list[str] | None = None):
    # 1. Preprocesa la imagen
    imagen = comprimir_imagen(contenido)

    # 2. Si no hay restricciones, devolver análisis básico sin evaluación de restricciones
    if not restricciones or len(restricciones) == 0:
        # Usar un prompt simplificado solo para extraer ingredientes
        prompt_simple = """
        Analiza la imagen de una etiqueta de producto alimenticio y extrae únicamente la información básica.

        Sigue estas instrucciones exactamente:

        1. Extrae la lista de ingredientes y escribe todos los ingredientes encontrados en una única línea, separados por comas. No incluyas encabezados como "Ingredientes:", ni puntos, ni información adicional.
        
        2. Para la información de alérgenos:
           - Busca CUALQUIER sección que mencione alérgenos o trazas, como: "PUEDE CONTENER", "CONTIENE", "CONTIENE TRAZAS", "PUEDE CONTENER TRAZAS", etc.
           - Si encuentras CUALQUIERA de estas secciones, copia literalmente todo su contenido después del título.
           - IMPORTANTE: Tanto "CONTIENE" como "PUEDE CONTENER" deben tratarse exactamente igual - ambos indican información de alérgenos importante.
           - Solo devuelve null si NO existe ninguna sección de información de alérgenos en toda la etiqueta.
           - Si hay información de alérgenos, siempre inclúyela sin importar si dice "CONTIENE" o "PUEDE CONTENER".

        Devuelve el resultado **en un único bloque de código JSON**, encerrado entre ```json y ```.

        EJEMPLOS de cómo manejar información de alérgenos:
        - Si ve "PUEDE CONTENER: Gluten, Soja" → "puede_contener": "Gluten, Soja"
        - Si ve "CONTIENE: Leche, Huevo" → "puede_contener": "Leche, Huevo"
        - Si ve "CONTIENE TRAZAS DE: Frutos secos" → "puede_contener": "Frutos secos"
        - Si NO hay ninguna sección de alérgenos → "puede_contener": null

        Ejemplo de formato:
        ```json
        {
          "ingredientes": "agua, azúcar, jarabe de glucosa, colorante natural",
          "puede_contener": "SOJA Y DERIVADOS DE TRIGO",
          "clasificacion": {}
        }
        ```
        """
        
        # Llamada al modelo multimodal con prompt simplificado
        respuesta = model.generate_content([prompt_simple, imagen])
        
        # Extrae el JSON de entre los ```json
        m = re.search(r"```json\n(.*?)```", respuesta.text, re.DOTALL)
        if not m:
            # Si no se puede extraer JSON, devolver estructura básica
            return {
                "ingredientes": "No se pudieron extraer los ingredientes",
                "puede_contener": None,
                "clasificacion": {}
            }
        
        try:
            resultado = json.loads(m.group(1))
            # Asegurar que clasificacion esté vacía para usuarios sin restricciones
            resultado['clasificacion'] = {}
            return resultado
        except json.JSONDecodeError:
            return {
                "ingredientes": "Error al procesar la imagen",
                "puede_contener": None,
                "clasificacion": {}
            }

    # 3. Si hay restricciones, usar el prompt completo
    prompt = BASE_PROMPT
    prompt += "\n\n**Solo evaluar estas restricciones:** " + ", ".join(restricciones) + "."

    # 4. Llamada al modelo multimodal
    respuesta = model.generate_content([prompt, imagen])

    # 5. Extrae el JSON de entre los ```json
    m = re.search(r"```json\n(.*?)```", respuesta.text, re.DOTALL)
    if not m:
        return {"error": "No se pudo interpretar la respuesta de Gemini."}
    
    resultado = json.loads(m.group(1))
    
    # 6. Limpia el resultado eliminando razones cuando el producto es apto
    clasificacion = resultado.get('clasificacion', {})
    for restriccion in clasificacion:
        if clasificacion[restriccion].get('apto', True):
            # Si es apto, eliminar la razón si existe
            clasificacion[restriccion] = {'apto': True}
    
    return resultado
