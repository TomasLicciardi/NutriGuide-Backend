from pydantic import BaseModel, EmailStr

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str
    restrictions: list[str] = []

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
