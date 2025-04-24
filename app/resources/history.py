from sqlalchemy.orm import Session
from app.models.history import History

def get_history_by_user_id(db: Session, user_id: int) -> History | None:
    return db.query(History).filter(History.user_id == user_id).first()

def create_history_for_user(db: Session, user_id: int) -> History:
    history = History(user_id=user_id)
    db.add(history)
    db.commit()
    db.refresh(history)
    return history
