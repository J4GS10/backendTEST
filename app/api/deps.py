from typing import Generator, Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.organization import Usuario
from app.repositories.organization import UsuarioRepository

# OAuth2 define que el token viene del endpoint /login
reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(reusable_oauth2)
) -> Usuario:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = payload.get("sub")
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="COULD_NOT_VALIDATE_CREDENTIALS",
        )
    
    repo = UsuarioRepository(db)
    # Asumimos que el "sub" del token es el Username
    user = await repo.get_by_username(username=token_data)
    
    if not user:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")
    
    if not user.USU_Estado:
        raise HTTPException(status_code=400, detail="INACTIVE_USER") # Kill Switch activado
        
    return user

# Dependencia para roles (RBAC)
class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: Usuario = Depends(get_current_user)):
        if user.USU_Rol not in self.allowed_roles:
            raise HTTPException(
                status_code=401, 
                detail="NOT_ENOUGH_PERMISSIONS"
            )