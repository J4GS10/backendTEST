from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

# Configuración de contexto de hashing (Bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(subject: str | Any, expires_delta: Optional[timedelta] = None) -> str:
    """
    Genera un JWT Token firmado con HS256.
    Incluye claims estándar: exp (expiración), iat (emitido en), sub (sujeto).
    """
    # Usamos UTC explícito para evitar problemas de zona horaria
    now = datetime.now(timezone.utc)
    
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "exp": expire,          
        "iat": now,             
        "sub": str(subject)     
    }
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica un password plano contra su hash de forma segura."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:

        return False

def get_password_hash(password: str) -> str:
    """Genera el hash seguro de una contraseña."""
    return pwd_context.hash(password)