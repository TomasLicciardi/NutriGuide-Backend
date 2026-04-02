from pydantic import BaseModel, EmailStr, validator
from typing import Optional, List

# Restricciones soportadas por el sistema
SUPPORTED_RESTRICTIONS = ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"]

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class UserLogin(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    restrictions: Optional[List[str]] = []

    class Config:
        from_attributes = True

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class UserRestrictionsUpdate(BaseModel):
    restrictions: List[str]
    
    @validator('restrictions')
    def validate_restrictions(cls, v):
        if not v:
            return v
        
        # Validar que todas las restricciones sean soportadas
        for restriction in v:
            if restriction not in SUPPORTED_RESTRICTIONS:
                raise ValueError(f"Restricción '{restriction}' no soportada. Restricciones válidas: {SUPPORTED_RESTRICTIONS}")
        
        return list(set(v))  # Eliminar duplicados

class UserRestrictionsResponse(BaseModel):
    active_restrictions: List[str]
    all_supported_restrictions: List[str] = SUPPORTED_RESTRICTIONS

class MessageResponse(BaseModel):
    message: str
