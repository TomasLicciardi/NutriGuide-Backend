# app/models/user.py
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.connection import Base
from app.utils.security import verify_password
import json

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    restrictions = Column(Text, default="[]")
    reset_token = Column(String, nullable=True)          # token temporal para recuperar contraseña
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # uselist=False correcto: History es un contenedor único por usuario (unique=True en user_id)
    history = relationship("History", back_populates="user", uselist=False)

    def get_restrictions(self):
        return json.loads(self.restrictions) if self.restrictions else []

    def set_restrictions(self, restrictions_list):
        self.restrictions = json.dumps(restrictions_list)

    def verify_password(self, password: str) -> bool:
        return verify_password(password, self.password)
