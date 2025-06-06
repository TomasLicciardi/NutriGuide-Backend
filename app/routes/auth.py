"""
Rutas relacionadas con la autenticación de usuarios (registro e inicio de sesión).
"""

# app/routes/auth.py

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.utils.security import hash_password
from app.utils.jwt import create_access_token
from app.resources.user import get_user_by_email, create_user
from app.schemas.auth_schemas import UserLogin, UserRegister, Token

router = APIRouter(prefix="/auth", tags=["auth"])

# --- Registro de usuario ---
@router.post("/register", response_model=dict)
async def registrar_usuario(
    user_data: UserRegister,
    db: Session = Depends(get_db)
):
    """
    Registra un nuevo usuario en la base de datos.

    Args:
        user_data (UserRegister): Datos del usuario validados por Pydantic.
        db (Session): Sesión de la base de datos.

    Returns:
        dict: Mensaje de confirmación del registro.
    """
    if get_user_by_email(db, user_data.email):
        raise HTTPException(status_code=409, detail="El correo ya está registrado.")

    nuevo_usuario = create_user(db, {
        "username": user_data.username,
        "email": user_data.email,
        "password": hash_password(user_data.password),
    })

    # Establecer restricciones alimentarias si se proporcionan
    if user_data.restrictions:
        nuevo_usuario.set_restrictions(user_data.restrictions)

    db.commit()

    return {"mensaje": "Usuario registrado exitosamente."}

# --- Inicio de sesión (login) ---
@router.post("/login", response_model=Token)
async def iniciar_sesion(
    user_data: UserLogin,
    db: Session = Depends(get_db)
):
    """
    Inicia sesión de un usuario y genera un token de acceso.

    Args:
        user_data (UserLogin): Datos de inicio de sesión validados por Pydantic.
        db (Session): Sesión de la base de datos.

    Returns:
        Token: Token de acceso y tipo de token.
    """
    usuario = get_user_by_email(db, user_data.email)

    if not usuario or not usuario.verify_password(user_data.password):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")

    token = create_access_token(data={"sub": str(usuario.id)})

    return Token(access_token=token, token_type="bearer")
