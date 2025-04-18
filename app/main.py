# main.py
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image
import google.generativeai as genai
import io
import os
import json
import re
from dotenv import load_dotenv

load_dotenv()  # Carga tu .env

# Configura la API Key de Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Carga el modelo
model = genai.GenerativeModel("gemini-2.0-flash-lite")

# FastAPI app
app = FastAPI()

# CORS (por si después necesitás usarlo desde el frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Comprimir imagen
def comprimir_imagen(file_bytes, calidad=50, max_dim=800):
    imagen = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    if max(imagen.size) > max_dim:
        imagen.thumbnail((max_dim, max_dim))
    buffer = io.BytesIO()
    imagen.save(buffer, format='JPEG', quality=calidad)
    buffer.seek(0)
    return Image.open(buffer)

# Prompt de Gemini
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

# Endpoint principal
@app.post("/analizar")
async def analizar_producto(file: UploadFile = File(...)):
    contenido = await file.read()
    imagen_comprimida = comprimir_imagen(contenido)

    respuesta = model.generate_content([PROMPT_COMPLETO, imagen_comprimida])
    json_str = re.search(r"```json\n(.*)```", respuesta.text, re.DOTALL)
    if json_str:
        data = json.loads(json_str.group(1))
        return JSONResponse(content=data)
    else:
        return JSONResponse(content={"error": "No se pudo interpretar la respuesta de Gemini."})
