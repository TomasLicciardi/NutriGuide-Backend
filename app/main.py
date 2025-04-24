from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import auth, analyze, history, user
from app.database.connection import init_database

app = FastAPI(
    title="NutriGuide API",
    description="API for food label analysis with Gemini and JWT authentication.",
    version="1.0.0"
)

# Initialize the database if needed
init_database()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(analyze.router)
app.include_router(history.router)
app.include_router(user.router)
