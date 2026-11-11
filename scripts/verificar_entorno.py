"""Verifica que una máquina esté lista para correr NutriGuide en la defensa.

Uso (desde backend/):
    python scripts/verificar_entorno.py            # chequeos locales (10 s)
    python scripts/verificar_entorno.py --online   # además prueba Gemini (1 llamada)

Pensado para la notebook de respaldo: corre esto antes de dar por buena la
copia. Cada línea dice OK o FALTA y qué hacer.
"""
import importlib
import os
import socket
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PROYECTO = RAIZ.parent
ok_total = True


def linea(estado, texto, ayuda=""):
    global ok_total
    marca = "  OK   " if estado else "  FALTA"
    if not estado:
        ok_total = False
    print(f"{marca} {texto}" + (f"\n         -> {ayuda}" if (ayuda and not estado) else ""))


print(f"\nNutriGuide — verificación de entorno en {RAIZ}\n")

# Python
v = sys.version_info
linea(v >= (3, 11), f"Python {v.major}.{v.minor}.{v.micro}", "Instalar Python 3.11 o superior")

# Dependencias
mods = {
    "fastapi": "fastapi", "uvicorn": "uvicorn", "sqlalchemy": "SQLAlchemy",
    "pydantic": "pydantic", "torch": "torch", "transformers": "transformers",
    "sentencepiece": "sentencepiece", "google.generativeai": "google-generativeai",
    "PIL": "pillow", "httpx": "httpx", "jose": "python-jose", "passlib": "passlib",
    "yaml": "PyYAML", "dotenv": "python-dotenv", "multipart": "python-multipart",
    "pytest": "pytest",
}
faltan = []
for mod, paquete in mods.items():
    try:
        importlib.import_module(mod)
    except Exception:
        faltan.append(paquete)
linea(not faltan, f"dependencias del backend ({len(mods) - len(faltan)}/{len(mods)})",
      f"pip install -r requirements.lock.txt   (faltan: {', '.join(faltan)})")

for mod, paquete in {"jinja2": "jinja2", "itsdangerous": "itsdangerous", "bcrypt": "bcrypt"}.items():
    try:
        importlib.import_module(mod)
        falta_admin = False
    except Exception:
        falta_admin = True
        break
linea(not falta_admin, "dependencias del panel de administración",
      "pip install -r ../admin/requirements.txt")

# .env y clave
env = RAIZ / ".env"
linea(env.exists(), ".env presente", "Copiar backend/.env desde la PC de escritorio (no está en git)")
clave = ""
if env.exists():
    for l in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if l.startswith("GEMINI_API_KEY="):
            clave = l.split("=", 1)[1].strip()
linea(clave.startswith("AQ.") and len(clave) > 30, "GEMINI_API_KEY cargada en .env",
      "Pegar la clave del proyecto 'Gemini API' (AQ.Ab8RN6LS...qg9w) en backend/.env")

# Base de datos
db_path, db_name = RAIZ, "nutriguide.db"
if env.exists():
    for l in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if l.startswith("DATABASE_PATH="):
            db_path = Path(l.split("=", 1)[1].strip().strip('"'))
        if l.startswith("DATABASE_NAME="):
            db_name = l.split("=", 1)[1].strip().strip('"')
db = Path(db_path) / db_name
linea(db.exists(), f"base de datos {db} ({db.stat().st_size // 1024} KB)" if db.exists() else f"base de datos {db}",
      "Copiar backend/nutriguide.db desde la PC de escritorio y revisar DATABASE_PATH en .env "
      "(en la notebook la ruta C:\\Users\\Usuario\\... probablemente cambie)")

# Datos locales
for f in ["app/data/off_taxonomy.sqlite", "app/data/kb_seed.yaml", "app/data/ins_codes.yaml",
          "app/data/canonicalization_rules.yaml"]:
    linea((RAIZ / f).exists(), f, "Está en git; hacer git pull en backend/")

# MarianMT en caché
hf = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub" / "models--Helsinki-NLP--opus-mt-es-en"
linea(hf.exists(), f"MarianMT en caché ({hf})",
      "Copiar la carpeta ~/.cache/huggingface/hub/models--Helsinki-NLP--opus-mt-es-en desde la PC "
      "(600 MB) o dejar que se descargue en el primer arranque (necesita internet, ~2 min)")

# Imágenes de la demo
demo = PROYECTO / "demo_final"
n_demo = len(list(demo.glob("*.jpg"))) if demo.exists() else 0
linea(n_demo >= 5, f"imágenes de la demo en {demo} ({n_demo})", "git pull del repo de la raíz (NutriGuide-Tesis)")

# Puerto
s = socket.socket()
try:
    s.bind(("0.0.0.0", 8000))
    libre = True
except OSError:
    libre = False
finally:
    s.close()
linea(libre, "puerto 8000 libre", "Hay otro backend corriendo; cerrarlo o usar --port 8001")

# Gemini (opcional)
if "--online" in sys.argv:
    try:
        from dotenv import load_dotenv
        import google.generativeai as genai
        load_dotenv(env)
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        sys.path.insert(0, str(RAIZ))
        from app.services.gemini_service import _model_chain
        for m in _model_chain():
            try:
                genai.GenerativeModel(m).generate_content("hola", request_options={"retry": None})
                linea(True, f"Gemini {m} responde")
            except Exception as e:
                linea(False, f"Gemini {m}: {type(e).__name__}", "Ver PLAN_CONTINGENCIA.md §4")
    except Exception as e:
        linea(False, f"no se pudo probar Gemini: {e}")

print()
print("ENTORNO LISTO" if ok_total else "FALTAN COSAS — resolver las líneas marcadas y volver a correr")
sys.exit(0 if ok_total else 1)
