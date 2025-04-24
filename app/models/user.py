from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship
from app.database.connection import Base
import json

class User(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    restrictions = Column(Text, nullable=True)  # JSON string

    history = relationship("History", back_populates="user", uselist=False)

    def get_restrictions(self):
        return json.loads(self.restrictions) if self.restrictions else []

    def set_restrictions(self, restrictions_list):
        self.restrictions = json.dumps(restrictions_list)
