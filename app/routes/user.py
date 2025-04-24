from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models.user import User
from app.utils.jwt import *
from pydantic import BaseModel
from typing import List
import json

router = APIRouter(prefix="/usuario", tags=["usuario"])

@router.get("/restricciones")
def obtener_restricciones(token: str = Depends(JWTBearer()), db: Session = Depends(get_db)):
    usuario_id = extract_user_id(token)
    usuario = db.query(User).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    restricciones = json.loads(usuario.restricciones) if usuario.restricciones else []
    return {"restricciones": restricciones}

class RestriccionesUpdate(BaseModel):
    restricciones: List[str]

@router.put("/restricciones")
def actualizar_restricciones(
    data: RestriccionesUpdate,
    token: str = Depends(JWTBearer()),
    db: Session = Depends(get_db)
):
    usuario_id = extract_user_id(token)
    usuario = db.query(Usuario).filter_by(id=usuario_id).first()

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    usuario.restricciones = json.dumps(data.restricciones)
    db.commit()

    return {"mensaje": "Restricciones actualizadas correctamente", "restricciones": data.restricciones}
