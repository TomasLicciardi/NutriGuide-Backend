# NutriGuide Backend — imagen Docker
#
# Estrategia:
#   - python:3.11-slim como base (más estable que 3.12/3.13 para torch + transformers)
#   - Instala deps del requirements.txt
#   - PRE-DESCARGA el modelo MarianMT durante el build → contenedor arranca rápido
#   - La DB SQLite vive en /app/data (montar volumen para persistencia)
#   - Configuración por variables de entorno (.env o K8s ConfigMap/Secret)

FROM python:3.11-slim

# Dependencias del sistema para Pillow, bcrypt, torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalación de dependencias Python (capa cacheable)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-descarga del modelo MarianMT (~312 MB) durante el build.
# Esto evita que el contenedor tarde 1-2 min descargándolo en el primer arranque
# de cada pod en K8s. La imagen pesa más (~1.5 GB total) pero arranca rápido.
RUN python -c "from transformers import MarianMTModel, MarianTokenizer; \
    MarianMTModel.from_pretrained('Helsinki-NLP/opus-mt-es-en'); \
    MarianTokenizer.from_pretrained('Helsinki-NLP/opus-mt-es-en'); \
    print('MarianMT pre-descargado OK')"

# Código de la aplicación
COPY app/ ./app/
COPY data/ ./data/
COPY scripts/ ./scripts/

# Directorio para la BD SQLite (se monta como volumen)
RUN mkdir -p /app/data

# Variables de entorno con defaults razonables para contenedor
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/app/data \
    DATABASE_NAME=nutriguide.db \
    PORT=8000

EXPOSE 8000

# Healthcheck para K8s liveness/readiness
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
