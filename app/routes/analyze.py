# app/routes/analyze.py
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.services.gemini_service import analizar_imagen
from app.database.connection import get_db
from app.models.models import Historial, ProductoAnalizado
from app.utils.jwt_bearer import JWTBearer
from app.utils.jwt_decoder import extract_user_id
import json

router = APIRouter(prefix="/analisis", tags=["analisis"])

@router.post("/")
async def analizar_producto(
    file: UploadFile = File(...),
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db)
):
    # Extraer ID de usuario desde el token
    usuario_id = extract_user_id(token)

    # Verificar o crear historial del usuario
    historial = db.query(Historial).filter_by(usuario_id=usuario_id).first()
    if not historial:
        historial = Historial(usuario_id=usuario_id)
        db.add(historial)
        db.commit()
        db.refresh(historial)

    # Analizar imagen con Gemini
    resultado = await analizar_imagen(file)

    # Guardar el resultado del análisis
    nuevo_producto = ProductoAnalizado(
        historial_id=historial.id,
        resultado_json=json.dumps(resultado) 
    )
    db.add(nuevo_producto)
    db.commit()
    db.refresh(nuevo_producto)

    # Devolver el resultado al cliente
    return JSONResponse(content={
        "mensaje": "Análisis completado y guardado.",
        "producto_id": nuevo_producto.id,
        "resultado": resultado
    })
