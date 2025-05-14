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
2. Si en la etiqueta aparece una sección que diga "PUEDE CONTENER" o "CONTIENTE", copia literalmente su contenido. Si no aparece, devuelve null.
3. Evalúa si el producto contiene ingredientes NO APTOS para ciertas restricciones alimenticias.

- Si el usuario proporciona una lista personalizada de restricciones, analiza **únicamente** esas.
- Si la lista está vacía, evalúa **todas** las restricciones predeterminadas.

Para cada restricción evaluada:
- Usa `"apto": true` si es apto.
- Usa `"apto": false` y proporciona una clave `"razon"` con una justificación **clara y breve** basada en los ingredientes.
- Si es apto, **NO** incluyas la clave `"razon"`.

Devuelve el resultado **en un único bloque de código JSON**, encerrado entre ```json y ```.

Ejemplo de formato:
```json
{
  "ingredientes": "agua, azúcar, jarabe de glucosa, colorante natural",
  "puede_contener": "SOJA Y DERIVADOS DE TRIGO",
  "clasificacion": {
    "vegano": { "apto": false, "razon": "Contiene caseinato de sodio" },
    "celiaco": { "apto": true }
  }
}
"""

async def analizar_imagen(contenido: bytes, restricciones: list[str] | None = None):
    # 1. Preprocesa la imagen
    imagen = comprimir_imagen(contenido)

    # 2. Construye el prompt dinámico
    prompt = BASE_PROMPT
    if restricciones:
        prompt += "\n\n**Solo evaluar estas restricciones:** " + ", ".join(restricciones) + "."

    # 3. Llamada al modelo multimodal
    respuesta = model.generate_content([prompt, imagen])    # 4. Extrae el JSON de entre los ```json
    m = re.search(r"```json\n(.*?)```", respuesta.text, re.DOTALL)
    if not m:
        return {"error": "No se pudo interpretar la respuesta de Gemini."}
    
    resultado = json.loads(m.group(1))
    
    # 5. Limpia el resultado eliminando razones cuando el producto es apto
    clasificacion = resultado.get('clasificacion', {})
    for restriccion in clasificacion:
        if clasificacion[restriccion].get('apto', True):
            # Si es apto, eliminar la razón si existe
            clasificacion[restriccion] = {'apto': True}
    
    return resultado
