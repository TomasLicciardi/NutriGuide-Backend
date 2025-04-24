import os
from datetime import datetime, timedelta
from jose import jwt, JWTError, ExpiredSignatureError
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Configuración
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"
EXPIRES_IN = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 3600))

# Crear token
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(seconds=EXPIRES_IN)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Decodificar token
def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise ValueError("Token expirado")
    except JWTError:
        raise ValueError("Token inválido")

# Extraer user_id
def extract_user_id(token: str) -> str:
    payload = decode_token(token)
    return payload.get("sub")

# Clase para seguridad con JWT en rutas protegidas
class JWTBearer(HTTPBearer):
    async def __call__(self, request: Request):
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if not credentials:
            raise HTTPException(status_code=403, detail="Credenciales no encontradas")
        try:
            decode_token(credentials.credentials)
        except Exception:
            raise HTTPException(status_code=403, detail="Token inválido")
        return credentials.credentials
