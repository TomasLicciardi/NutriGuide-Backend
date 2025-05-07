"""
Rutas relacionadas con la autenticación de usuarios (registro e inicio de sesión).
"""

# app/routes/auth.py

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.utils.security import hash_password
from app.utils.jwt import create_access_token, JWTBearer
from app.utils.mail import send_email
from app.resources.user import get_user_by_email, create_user

router = APIRouter(prefix="/auth", tags=["auth"])

# --- Registro de usuario ---
@router.post("/register")
async def registrar_usuario(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Registra un nuevo usuario en la base de datos.

    Args:
        request (Request): Solicitud HTTP con los datos del usuario.
        background_tasks (BackgroundTasks): Tareas en segundo plano para enviar emails.
        db (Session): Sesión de la base de datos.

    Returns:
        dict: Mensaje de confirmación del registro.
    """
    datos = await request.json()
    email = datos.get("email")  # Cambiado de mail a email

    # Reemplazar consulta directa con get_user_by_email
    if get_user_by_email(db, email):
        raise HTTPException(status_code=409, detail="El correo ya está registrado.")

    # Crear usuario usando create_user
    usuario = create_user(db, {
        "username": datos.get("usuario"),
        "email": email,
        "password": hash_password(datos.get("contrasena")),
    })
    usuario.set_restrictions(datos.get("restricciones", []))
    db.commit()

    background_tasks.add_task(
        send_email,
        subject="¡Bienvenido a NutriGuide!",
        recipients=[email],
        body=f"Hola {usuario.username},\n\nGracias por registrarte en NutriGuide 😊\n\n¡Disfruta!"
    )

    return {"mensaje": "Usuario registrado. Email de bienvenida enviado."}


# --- Inicio de sesión (login) ---
@router.post("/login")
async def iniciar_sesion(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Inicia sesión de un usuario y genera un token de acceso.

    Args:
        request (Request): Solicitud HTTP con las credenciales del usuario.
        db (Session): Sesión de la base de datos.

    Returns:
        dict: Token de acceso y tipo de token.
    """
    datos = await request.json()
    email = datos.get("email")  # Cambiado de mail a email
    contrasena = datos.get("contrasena")

    # Reemplazar consulta directa con get_user_by_email
    usuario = get_user_by_email(db, email)
    if not usuario or not usuario.verify_password(contrasena):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")

    token = create_access_token(data={"sub": str(usuario.id)})

    return {"access_token": token, "token_type": "bearer"}
