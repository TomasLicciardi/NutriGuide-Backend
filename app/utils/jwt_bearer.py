# app/utils/jwt_bearer.py
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils.jwt_tools import decode_token

class JWTBearer(HTTPBearer):
    async def __call__(self, request: Request):
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if not credentials:
            raise HTTPException(status_code=403, detail="Credenciales no encontradas")
        try:
            # valida firma y expiración
            decode_token(credentials.credentials)
        except Exception:
            raise HTTPException(status_code=403, detail="Token inválido")
        return credentials.credentials
