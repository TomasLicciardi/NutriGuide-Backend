# app/routes/auth.py
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models.user import User  
from app.utils.security import hash_password
from app.utils.jwt import create_access_token
from app.utils.mail import send_email   
from pydantic import BaseModel, EmailStr
from typing import Optional, List

router = APIRouter(prefix="/auth", tags=["auth"])

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    restrictions: Optional[List[str]] = None

@router.post("/register")
async def register(
    data: UserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    if db.query(User).filter_by(email=data.email).first():
        raise HTTPException(409, "El email ya existe")

    user = User(
        username=data.username,
        email=data.email,
        password=hash_password(data.password),
        restrictions=data.restrictions or []
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Enviar mail en background
    background_tasks.add_task(
        send_email,
        subject="¡Bienvenido a NutriGuide!",
        recipients=[user.email],
        body=f"Hola {user.username},\n\nGracias por registrarte en NutriGuide 😊\n\n¡Disfruta!"
    )

    return {"message": "Usuario registrado. Email de bienvenida enviado."}
