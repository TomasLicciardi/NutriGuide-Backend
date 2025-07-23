from passlib.context import CryptContext

# Configurar bcrypt con menos rounds para mejor rendimiento
pwd_context = CryptContext(
    schemes=["bcrypt"], 
    deprecated="auto",
    bcrypt__rounds=10  # Reducir de 12 (default) a 10 para mejor rendimiento
)

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)
