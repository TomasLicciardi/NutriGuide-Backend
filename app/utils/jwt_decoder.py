# app/utils/jwt_decoder.py
from app.utils.jwt_tools import decode_token

def extract_user_id(token: str) -> str:
    """
    Decodifica el token y saca el campo 'sub' (user_id).
    """
    payload = decode_token(token)
    return payload.get("sub")
