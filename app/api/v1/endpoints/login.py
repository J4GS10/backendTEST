from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core import security
from app.core.config import settings
from app.repositories.organization import UsuarioRepository
from app.schemas.organization import UsuarioResponse # Reutilizamos esquema de respuesta

router = APIRouter()

@router.post("/login/access-token")
async def login_access_token(
    db: AsyncSession = Depends(get_db), 
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    repo = UsuarioRepository(db)
    user = await repo.get_by_username(form_data.username)

    # 1. Verificar si existe
    if not user:
        raise HTTPException(status_code=400, detail="INCORRECT_USERNAME_OR_PASSWORD")
    
    # 2. Verificar Password
    if not security.verify_password(form_data.password, user.USU_Password_Hash):
        raise HTTPException(status_code=400, detail="INCORRECT_USERNAME_OR_PASSWORD")
        
    # 3. Verificar Estado (Kill Switch)
    if not user.USU_Estado:
        raise HTTPException(status_code=400, detail="INACTIVE_USER")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    return {
        "access_token": security.create_access_token(
            user.USU_Username, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }