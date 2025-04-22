from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth, analyze, historial, usuario
from app.core.init_db import init_database  

app = FastAPI(
    title="NutriGuide API",
    description="API para análisis de etiquetas alimenticias con Gemini y autenticación JWT.",
    version="1.0.0"
)

# Iniciar la base de datos si es necesario
init_database()

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(auth.router)
app.include_router(analyze.router)
app.include_router(historial.router)
app.include_router(usuario.router)
