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

PROMPT_COMPLETO = """
Esta es una imagen de la etiqueta de un producto alimenticio.

Tu tarea es:
1. Extraer únicamente la lista de ingredientes en una sola línea, separados por comas.
2. Indicar si aparece una sección que diga "PUEDE CONTENER" o "CONTIENTE", y qué menciona.
3. Evaluar si contiene ingredientes NO APTOS para: celíacos, intolerantes a la lactosa, veganos y personas con alergia a frutos secos.

Devuelve el resultado en formato JSON con las claves:
- Ingredientes
- Puede contener
- Clasificación: con "apto" (true/false) y "razón" por cada categoría.
"""

async def analizar_imagen(file):
    contenido = await file.read()
    imagen = comprimir_imagen(contenido)

    respuesta = model.generate_content([PROMPT_COMPLETO, imagen])
    match = re.search(r"```json\n(.*?)```", respuesta.text, re.DOTALL)

    if match:
        return json.loads(match.group(1))
    else:
        return {"error": "No se pudo interpretar la respuesta de Gemini."}
