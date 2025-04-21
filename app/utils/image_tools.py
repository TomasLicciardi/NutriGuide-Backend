# app/utils/image_tools.py
from PIL import Image
import io

def comprimir_imagen(file_bytes, calidad=50, max_dim=800):
    imagen = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    if max(imagen.size) > max_dim:
        imagen.thumbnail((max_dim, max_dim))
    buffer = io.BytesIO()
    imagen.save(buffer, format='JPEG', quality=calidad)
    buffer.seek(0)
    return Image.open(buffer)
