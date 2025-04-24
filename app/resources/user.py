from sqlalchemy.orm import Session
from app.models.user import User

def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()

def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()

def create_user(db: Session, user_data: dict) -> User:
    user = User(**user_data)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def update_user_restrictions(db: Session, user_id: int, restrictions: list) -> User | None:
    user = get_user_by_id(db, user_id)
    if user:
        user.set_restrictions(restrictions)
        db.commit()
        db.refresh(user)
    return user
