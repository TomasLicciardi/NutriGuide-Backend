"""
Rutas relacionadas con la gestión de usuarios.
"""

from fastapi import APIRouter, Request, HTTPException, Depends
from app.utils.jwt import JWTBearer, extract_user_id
from app.database.connection import get_db
from app.models.user import User
from sqlalchemy.orm import Session
from app.utils.security import verify_password, hash_password
from app.utils.jwt import create_access_token
from app.utils.mail import send_email
from app.resources.user import (
    get_user_by_id,
    get_user_by_email,
    create_user,
    update_user_restrictions,
)

router = APIRouter(prefix="/user", tags=["user"])

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
    db: Session = Depends(get_db),
):
    """
    Actualiza las restricciones de un usuario autenticado.

    Args:
        request (Request): Solicitud HTTP con las nuevas restricciones.
        token (str): Token JWT del usuario autenticado.
        db (Session): Sesión de la base de datos.

    Returns:
        dict: Mensaje de confirmación y restricciones actualizadas.
    """
    usuario_id = extract_user_id(token)
    usuario = get_user_by_id(db, usuario_id)

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    data = await request.json()
    restricciones = data.get("restricciones", [])

    usuario = update_user_restrictions(db, usuario_id, restricciones)
    if not usuario:
        raise HTTPException(status_code=500, detail="Error al actualizar restricciones")

    return {"mensaje": "Restricciones actualizadas correctamente", "restricciones": restricciones}

@router.put("/change-password", dependencies=[Depends(JWTBearer())])
async def change_password(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    current_password = body.get("current_password")
    new_password = body.get("new_password")

    if not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Se requieren ambas contraseñas")

    token = request.headers.get("Authorization").split(" ")[1]
    user_id = extract_user_id(token)

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if not verify_password(current_password, user.password):
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta")

    user.password = hash_password(new_password)
    db.commit()

    return {"mensaje": "Contraseña actualizada exitosamente"}

@router.post("/forgot-password")
async def forgot_password(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    email = data.get("email")

    if not email:
        raise HTTPException(status_code=400, detail="El email es requerido")

    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Crear token temporal para resetear contraseña
    reset_token = create_access_token({"sub": user.id})

    # Armar cuerpo del email
    body = f"""
Hola {user.username},

Recibimos una solicitud para recuperar tu contraseña en NutriGuide.

Tu token de recuperación es:

{reset_token}

Este token expira en 30 minutos.

Si no solicitaste este cambio, puedes ignorar este correo.

Saludos,
El equipo de NutriGuide
"""

    # Enviar correo
    await send_email(
        subject="Recuperación de contraseña - NutriGuide",
        recipients=[user.email],
        body=body
    )

    return {"mensaje": "Se envió un email con instrucciones para recuperar la contraseña"}

router.post("/reset-password")
async def reset_password(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    reset_token = data.get("reset_token")
    new_password = data.get("new_password")

    if not reset_token or not new_password:
        raise HTTPException(status_code=400, detail="Token y nueva contraseña son requeridos")

    try:
        user_id = extract_user_id(reset_token)
    except:
        raise HTTPException(status_code=400, detail="Token inválido o expirado")

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    user.password = hash_password(new_password)
    db.commit()

    return {"mensaje": "Contraseña restablecida correctamente"}

@router.get("/{user_id}")
async def obtener_usuario(user_id: int, db: Session = Depends(get_db)):
    """
    Obtiene los detalles de un usuario por su ID.

    Args:
        user_id (int): ID del usuario.
        db (Session): Sesión de la base de datos.

    Returns:
        User: Detalles del usuario encontrado.
    """
    usuario = get_user_by_id(db, user_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario

@router.post("/")
async def crear_usuario(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    usuario = create_user(db, data)
    return usuario