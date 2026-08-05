import os
from datetime import datetime, timedelta
from jose import jwt, JWTError, ExpiredSignatureError
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "mi_clave_secreta")
ALGORITHM = "HS256"
EXPIRES_IN = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 3600))  # Vuelve a usar el valor de .env o 3600s por defecto

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(seconds=EXPIRES_IN)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except ExpiredSignatureError:
        raise HTTPException(status_code=403, detail="El token ha expirado")
    except JWTError:
        raise HTTPException(status_code=403, detail="Token inválido")

def extract_user_id(token: str) -> str:
    payload = decode_token(token)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=403, detail="Token inválido")
    return sub


def extract_is_admin(token: str) -> bool:
    """True si el token fue emitido para un usuario con flag is_admin."""
    payload = decode_token(token)
    return bool(payload.get("is_admin", False))


class JWTBearer(HTTPBearer):
    async def __call__(self, request: Request):
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if not credentials:
            raise HTTPException(status_code=403, detail="Credenciales no encontradas")

        token = credentials.credentials
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=403, detail="Token inválido")
        return token


class AdminJWTBearer(JWTBearer):
    """Igual que JWTBearer pero rechaza tokens sin is_admin=true."""
    async def __call__(self, request: Request):
        token = await super().__call__(request)
        if not extract_is_admin(token):
            raise HTTPException(
                status_code=403,
                detail="Esta acción requiere permisos de administrador",
            )
        return token
