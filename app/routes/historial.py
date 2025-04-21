# app/routes/historial.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.models import models
from app.database.connection import get_db
from app.utils.jwt_bearer import JWTBearer
from app.utils.jwt_decoder import extract_user_id

router = APIRouter(
    prefix="/historial",
    tags=["Historial"],
    dependencies=[Depends(JWTBearer())]
)

# Obtener historial completo del usuario
@router.get("/")
def obtener_historial(token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    usuario_id = extract_user_id(token)

    historial = db.query(models.Historial).filter_by(usuario_id=usuario_id).first()
    if not historial:
        raise HTTPException(status_code=404, detail="Historial no encontrado")

    productos = db.query(models.ProductoAnalizado).filter_by(historial_id=historial.id).all()
    return {
        "historial_id": historial.id,
        "usuario_id": historial.usuario_id,
        "productos_analizados": [
            {
                "id": p.id,
                "resultado": p.resultado_json,
                "fecha": p.fecha
            } for p in productos
        ]
    }

# Obtener un producto analizado específico
@router.get("/{id}")
def obtener_producto(id: int, token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    usuario_id = extract_user_id(token)

    producto = db.query(models.ProductoAnalizado).join(models.Historial).filter(
        models.ProductoAnalizado.id == id,
        models.Historial.usuario_id == usuario_id
    ).first()

    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return {
        "id": producto.id,
        "resultado": producto.resultado,
        "fecha": producto.fecha
    }
