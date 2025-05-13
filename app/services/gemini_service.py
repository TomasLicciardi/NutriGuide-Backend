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
Esta es una imagen de la etiqueta de un producto alimenticio.

Tu tarea es:
1. Extraer únicamente la lista de ingredientes en una sola línea, separados por comas.
2. Indicar si aparece una sección que diga "PUEDE CONTENER" o "CONTIENTE", y qué menciona ahí.
3. Evaluar si contiene ingredientes NO APTOS para las siguientes restricciones (solo las que se especifiquen más abajo):

   1. Celíacos (sin gluten)
   2. Intolerantes a la lactosa
   3. Veganos
   4. Vegetarianos
   5. Alérgicos a frutos secos
   6. Alérgicos a la soja
   7. Sin azúcar añadida (apto diabéticos)
   8. Bajo en sodio (sin sal añadida)
   9. Halal
   10. Sin ingredientes artificiales (colorantes, conservantes, saborizantes, etc.)
   11. Otros (especificar)

Si el usuario proporciona una **lista personalizada** de restricciones, **evalúa únicamente esas**.  
Si la lista está vacía, evalúa todas las ocho anteriores.

Devuelve el resultado en formato JSON con las claves:
- ingredientes: string
- puede_contener: string o null
- clasificacion: objeto donde cada restricción evaluada tenga:
    - `"apto": true|false`
    - `"razon": string (solo proporcionar si apto es false)`

La razón solo debe incluirse cuando el producto NO es apto para esa restricción específica.
"""

async def analizar_imagen(file, restricciones: list[str] | None = None):
    # 1. Preprocesa la imagen
    contenido = await file.read()
    imagen = comprimir_imagen(contenido)

    # 2. Construye el prompt dinámico
    prompt = BASE_PROMPT
    if restricciones:
        prompt += "\n\n**Solo evaluar estas restricciones:** " + ", ".join(restricciones) + "."

    # 3. Llamada al modelo multimodal
    respuesta = model.generate_content([prompt, imagen])

    # 4. Extrae el JSON de entre los ```json
    m = re.search(r"```json\n(.*?)```", respuesta.text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    return {"error": "No se pudo interpretar la respuesta de Gemini."}
