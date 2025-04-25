from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models.user import User  
from app.utils.security import hash_password
from app.utils.jwt import create_access_token
from app.utils.mail import send_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
async def registrar_usuario(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    datos = await request.json()
    nombre_usuario = datos.get("usuario")
    correo = datos.get("mail")
    contrasena = datos.get("contrasena")
    restricciones = datos.get("restricciones", [])

    if not nombre_usuario or not correo or not contrasena:
        raise HTTPException(400, "Faltan campos obligatorios")

    if db.query(User).filter_by(email=correo).first():
        raise HTTPException(409, "El correo ya está registrado")

    usuario = User(
        username=nombre_usuario,
        email=correo,
        password=hash_password(contrasena),
    )
    usuario.set_restrictions(restricciones)

    db.add(usuario)
    db.commit()
    db.refresh(usuario)

    background_tasks.add_task(
        send_email,
        subject="¡Bienvenido a NutriGuide!",
        recipients=[correo],
        body=f"Hola {nombre_usuario},\n\nGracias por registrarte en NutriGuide 😊\n\n¡Disfruta!"
    )

    return {"mensaje": "Usuario registrado. Email de bienvenida enviado."}  # Mensaje en español

@router.post("/login")
async def iniciar_sesion(request: Request, db: Session = Depends(get_db)):
    datos = await request.json()
    correo = datos.get("mail")
    contrasena = datos.get("contrasena")

    if not correo or not contrasena:
        raise HTTPException(400, "Faltan campos obligatorios")

    usuario = db.query(User).filter_by(email=correo).first()
    if not usuario or not usuario.verify_password(contrasena):
        raise HTTPException(401, "Correo o contraseña incorrectos")

    token = create_access_token(data={"sub": str(usuario.id)})

    return {"access_token": token, "token_type": "bearer"}
