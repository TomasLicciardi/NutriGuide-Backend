"""
Funciones relacionadas con la gestión de usuarios en la base de datos.
"""

from typing import Optional
from sqlalchemy.orm import Session
from app.models.user import User

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """
    Obtiene un usuario de la base de datos por su email.

    Args:
        db (Session): Sesión de la base de datos.
        email (str): Email del usuario.

    Returns:
        Optional[User]: Usuario encontrado o None si no existe.
    """
    return db.query(User).filter(User.email == email).first()

def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """
    Obtiene un usuario de la base de datos por su ID.

    Args:
        db (Session): Sesión de la base de datos.
        user_id (int): ID del usuario.

    Returns:
        Optional[User]: Usuario encontrado o None si no existe.
    """
    return db.query(User).filter(User.id == user_id).first()

def create_user(db: Session, user_data: dict) -> User:
    """
    Crea un nuevo usuario en la base de datos.

    Args:
        db (Session): Sesión de la base de datos.
        user_data (dict): Datos del usuario a crear.

    Returns:
        User: Usuario creado.
    """
    user = User(**user_data)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def update_user_restrictions(db: Session, user_id: int, restrictions: list) -> Optional[User]:
    """
    Actualiza las restricciones de un usuario en la base de datos.

    Args:
        db (Session): Sesión de la base de datos.
        user_id (int): ID del usuario.
        restrictions (list): Lista de restricciones a actualizar.

    Returns:
        Optional[User]: Usuario actualizado o None si no existe.
    """
    user = get_user_by_id(db, user_id)
    if user:
        user.set_restrictions(restrictions)
        db.commit()
        db.refresh(user)
    return user
