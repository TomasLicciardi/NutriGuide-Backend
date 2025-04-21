from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models.models import Usuario
from app.utils.security import hash_password, verify_password
from app.utils.jwt_tools import create_access_token
from pydantic import BaseModel, EmailStr

router = APIRouter(prefix="/auth", tags=["auth"])

# --- Esquemas de entrada ---
class UsuarioRegistro(BaseModel):
    usuario: str
    mail: EmailStr
    contrasena: str

class UsuarioLogin(BaseModel):
    mail: EmailStr
    contrasena: str

# --- Registro de usuario ---
@router.post("/register")
def register(data: UsuarioRegistro, db: Session = Depends(get_db)):
    existe = db.query(Usuario).filter(Usuario.mail == data.mail).first()
    if existe:
        raise HTTPException(status_code=409, detail="El mail ya está registrado.")

    nuevo_usuario = Usuario(
        usuario=data.usuario,
        mail=data.mail,
        contrasena=hash_password(data.contrasena)
    )
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)

    return {"mensaje": "Usuario registrado correctamente", "usuario": nuevo_usuario.usuario}

# --- Login ---
@router.post("/login")
def login(data: UsuarioLogin, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.mail == data.mail).first()
    if not usuario or not verify_password(data.contrasena, usuario.contrasena):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token = create_access_token(data={"sub": str(usuario.id)})

    return {
        "id": usuario.id,
        "usuario": usuario.usuario,
        "mail": usuario.mail,
        "access_token": token
    }
