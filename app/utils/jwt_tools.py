from datetime import datetime, timedelta
from jose import jwt
import os

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"
EXPIRES_IN = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 3600))

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(seconds=EXPIRES_IN)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expirado")
    except jwt.JWTError:
        raise ValueError("Token inválido")