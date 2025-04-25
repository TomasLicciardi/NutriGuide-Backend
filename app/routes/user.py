from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models.user import User
from app.utils.jwt import *
import json

router = APIRouter(prefix="/user", tags=["user"])  # Cambio a "user" en inglés

@router.get("/restrictions")
def obtener_restricciones(token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    usuario_id = extract_user_id(token)
    usuario = db.query(User).filter(User.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return {"restricciones": usuario.get_restrictions()}

@router.put("/restrictions")
async def actualizar_restricciones(
    request: Request,
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db)
):
    usuario_id = extract_user_id(token)
    usuario = db.query(User).filter_by(id=usuario_id).first()

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    data = await request.json()
    restricciones = data.get("restricciones", [])

    usuario.set_restrictions(restricciones)
    db.commit()

    return {"mensaje": "Restricciones actualizadas correctamente", "restricciones": restricciones}  # Mensaje en español
