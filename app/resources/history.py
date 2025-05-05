"""
Funciones relacionadas con la gestión del historial en la base de datos.
"""

from typing import Optional
from sqlalchemy.orm import Session
from app.models.history import History

def get_history_by_user_id(db: Session, user_id: int) -> Optional[History]:
    """
    Obtiene el historial de un usuario por su ID.

    Args:
        db (Session): Sesión de la base de datos.
        user_id (int): ID del usuario.

    Returns:
        Optional[History]: Historial encontrado o None si no existe.
    """
    return db.query(History).filter(History.user_id == user_id).first()

def create_history_for_user(db: Session, user_id: int) -> History:
    """
    Crea un historial para un usuario.

    Args:
        db (Session): Sesión de la base de datos.
        user_id (int): ID del usuario.

    Returns:
        History: Historial creado.
    """
    history = History(user_id=user_id)
    db.add(history)
    db.commit()
    db.refresh(history)
    return history
