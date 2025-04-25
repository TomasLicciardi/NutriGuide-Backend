from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.services.gemini_service import analizar_imagen
from app.database.connection import get_db
from app.models import History, Product, User
from app.utils.jwt import JWTBearer, extract_user_id
import json

router = APIRouter(prefix="/analysis", tags=["analysis"])  # Cambio a "analysis" en inglés


@router.post("/")
async def analizar_producto(
    file: UploadFile = File(...),
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db)
):
    # Obtener ID del usuario desde el token
    usuario_id = extract_user_id(token)

    # Verificar si el historial existe, si no lo crea
    historial = db.query(History).filter_by(user_id=usuario_id).first()
    if not historial:
        historial = History(user_id=usuario_id)
        db.add(historial)
        db.commit()
        db.refresh(historial)

    # Obtener restricciones del usuario
    usuario = db.query(User).filter_by(id=usuario_id).first()
    restricciones = usuario.get_restrictions() if usuario else []

    # Analizar imagen usando restricciones personalizadas
    resultado = await analizar_imagen(file, restricciones=restricciones)

    # Guardar análisis en la base de datos
    nuevo_producto = Product(
        name=file.filename,
        result_json=json.dumps(resultado),
        history_id=historial.id
    )
    db.add(nuevo_producto)
    db.commit()
    db.refresh(nuevo_producto)

    return JSONResponse(content={
        "mensaje": "Análisis completado y guardado.",  # Mensaje en español
        "producto_id": nuevo_producto.id,
        "resultado": resultado
    })
