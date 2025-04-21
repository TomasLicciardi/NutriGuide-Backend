# app/routes/analisis.py
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from app.services.gemini_service import analizar_imagen

router = APIRouter(prefix="/analisis", tags=["analisis"])

@router.post("/")
async def analizar_producto(file: UploadFile = File(...)):
    resultado = await analizar_imagen(file)
    return JSONResponse(content=resultado)
