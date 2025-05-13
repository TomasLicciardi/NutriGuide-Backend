from pydantic import BaseModel, EmailStr

class UserLogin(BaseModel):
    email: EmailStr
    contrasena: str

class UserRegister(BaseModel):
    usuario: str
    email: EmailStr
    contrasena: str
    restricciones: list[str] = []

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
