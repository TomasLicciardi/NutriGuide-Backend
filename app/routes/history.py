from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models import History, User, Product
from app.utils.jwt import *
import json

router = APIRouter(
    prefix="/history",  # Cambio a "history" en inglés
    tags=["History"],
    dependencies=[Depends(JWTBearer())]
)

# Obtener historial completo del usuario
@router.get("/")
def obtener_historial(token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    usuario_id = extract_user_id(token)

    historial = db.query(History).filter_by(user_id=usuario_id).first()  # Cambio a "user_id"
    if not historial:
        raise HTTPException(status_code=404, detail="Historial no encontrado")

    productos = db.query(Product).filter_by(history_id=historial.id).all()  # Cambio a "history_id"

    return {
        "historial_id": historial.id,
        "usuario_id": historial.user_id,  # Cambio a "user_id"
        "productos_analizados": [
            {
                "id": p.id,
                "resultado": json.loads(p.result_json),  # Cambio a "result_json"
                "fecha": p.date  # Cambio a "date"
            } for p in productos
        ]
    }

# Obtener un producto analizado específico
@router.get("/{id}")
def obtener_producto(id: int, token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    usuario_id = extract_user_id(token)

    producto = db.query(Product).join(History).filter(
        Product.id == id,
        History.user_id == usuario_id  # Cambio a "user_id"
    ).first()

    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return {
        "id": producto.id,
        "resultado": json.loads(producto.result_json),  # Cambio a "result_json"
        "fecha": producto.date  # Cambio a "date"
    }
