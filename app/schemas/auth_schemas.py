from pydantic import BaseModel, EmailStr, Field

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str = Field(..., min_length=6, description="Mínimo 6 caracteres")
    restrictions: list[str] = []

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
