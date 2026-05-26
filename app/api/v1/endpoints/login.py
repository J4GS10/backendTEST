"""Endpoints de autenticación: login, refresh, logout, me."""
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.deps import CurrentUser, invalidate_auth_cache
from app.core import security
from app.core.config import settings
from app.core.limiter import limiter
from app.db.session import get_db
from app.repositories.governance import GovernanceRepository
from app.repositories.organization import UsuarioRepository

router = APIRouter()


def _now() -> datetime:
    """Naive UTC (compatible con columnas DateTime sin tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/login/access-token")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login_access_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """OAuth2-compatible token login. Aplica account lockout."""
    repo = UsuarioRepository(db)
    user = await repo.get_by_username(form_data.username)

    # Mensaje genérico para no leak qué usuarios existen.
    if not user:
        raise HTTPException(status_code=400, detail="INCORRECT_USERNAME_OR_PASSWORD")

    now = _now()

    # ¿Cuenta bloqueada por intentos previos?
    if user.USU_Bloqueado_Hasta and user.USU_Bloqueado_Hasta > now:
        # Mensaje genérico pero distinguible
        raise HTTPException(status_code=429, detail="ACCOUNT_LOCKED")

    # Verificar contraseña
    if not security.verify_password(form_data.password, user.USU_Password_Hash):
        user.USU_Intentos_Fallidos = (user.USU_Intentos_Fallidos or 0) + 1
        if user.USU_Intentos_Fallidos >= settings.ACCOUNT_LOCKOUT_THRESHOLD:
            user.USU_Bloqueado_Hasta = now + timedelta(
                minutes=settings.ACCOUNT_LOCKOUT_MINUTES
            )
        await db.commit()
        raise HTTPException(status_code=400, detail="INCORRECT_USERNAME_OR_PASSWORD")

    if not user.USU_Estado:
        raise HTTPException(status_code=400, detail="INACTIVE_USER")

    # Login exitoso: limpiar contador y rehash si toca.
    if security.needs_password_rehash(user.USU_Password_Hash):
        user.USU_Password_Hash = security.get_password_hash(form_data.password)
    user.USU_Intentos_Fallidos = 0
    user.USU_Bloqueado_Hasta = None
    user.USU_Ultimo_Login = now
    await db.commit()

    return {
        "access_token": security.create_access_token(user.USU_Username, user.USU_Rol),
        "refresh_token": security.create_refresh_token(user.USU_Username, user.USU_Rol),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/login/refresh")
@limiter.limit("10/minute")
async def refresh_access_token(
    request: Request,
    refresh_token: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """Emite un nuevo access_token a partir de un refresh_token válido y no revocado."""
    payload = deps._decode_token(refresh_token, expected_type="refresh")

    gov_repo = GovernanceRepository(db)
    jti = payload.get("jti")
    if jti and await gov_repo.is_jti_revoked(jti):
        raise HTTPException(status_code=401, detail="TOKEN_REVOKED")

    repo = UsuarioRepository(db)
    user = await repo.get_by_username(payload["sub"])
    if not user or not user.USU_Estado:
        raise HTTPException(status_code=401, detail="USER_INACTIVE_OR_NOT_FOUND")

    # Revocación global posterior (cambio de password, p.ej.)
    iat = payload.get("iat")
    if iat:
        issued_at = datetime.fromtimestamp(iat, tz=timezone.utc).replace(tzinfo=None)
        if await gov_repo.is_user_globally_revoked(user.USU_Usuario, issued_at):
            raise HTTPException(status_code=401, detail="TOKEN_REVOKED")

    return {
        "access_token": security.create_access_token(user.USU_Username, user.USU_Rol),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/login/logout", status_code=204)
@limiter.limit("10/minute")
async def logout(
    current_user: CurrentUser,
    request: Request,
    refresh_token: str | None = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoca:
      - El access token actual (vía su jti).
      - El refresh token enviado (si se proporciona).
    """
    gov_repo = GovernanceRepository(db)
    jtis_to_purge: list[str] = []

    # Revocar access token actual (lo tenemos en el header)
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        access = auth_header.split(None, 1)[1]
        try:
            payload = deps._decode_token(access, expected_type="access")
            await gov_repo.revoke_jti(
                jti=payload["jti"],
                tipo="access",
                expira=datetime.fromtimestamp(payload["exp"], tz=timezone.utc).replace(tzinfo=None),
                usuario_id=current_user.USU_Usuario,
            )
            jtis_to_purge.append(payload["jti"])
        except HTTPException:
            pass

    # Revocar refresh token si llegó
    if refresh_token:
        try:
            payload = deps._decode_token(refresh_token, expected_type="refresh")
            await gov_repo.revoke_jti(
                jti=payload["jti"],
                tipo="refresh",
                expira=datetime.fromtimestamp(payload["exp"], tz=timezone.utc).replace(tzinfo=None),
                usuario_id=current_user.USU_Usuario,
            )
        except HTTPException:
            pass

    await db.commit()
    # Purgar caché para que el siguiente request use BD (devolverá 401).
    if jtis_to_purge:
        await invalidate_auth_cache(*jtis_to_purge)


@router.get("/me")
async def me(current_user: CurrentUser):
    """Información del usuario autenticado."""
    return {
        "username": current_user.USU_Username,
        "role": current_user.USU_Rol,
        "active": current_user.USU_Estado,
        "person_id": str(current_user.PER_Persona),
    }


@router.post("/me/password", status_code=204)
@limiter.limit("5/minute")
async def change_my_password(
    request: Request,
    current_user: CurrentUser,
    current_password: str = Body(..., embed=True, min_length=1),
    new_password: str = Body(..., embed=True, min_length=8),
    db: AsyncSession = Depends(get_db),
):
    """
    Cambia la contraseña del usuario autenticado.
    - Re-valida la contraseña actual antes de aceptar el cambio.
    - Aplica la política de contraseñas configurada.
    - Revoca TODOS los tokens del usuario (incluido el actual) → debe re-login.
    """
    # 1. Re-validar contraseña actual. Si falla, sumar al contador de fallos
    # del usuario y aplicar lockout (igual que /login/access-token), para que
    # un atacante con un token robado no pueda iterar passwords libremente.
    if not security.verify_password(current_password, current_user.USU_Password_Hash):
        current_user.USU_Intentos_Fallidos = (current_user.USU_Intentos_Fallidos or 0) + 1
        if current_user.USU_Intentos_Fallidos >= settings.ACCOUNT_LOCKOUT_THRESHOLD:
            current_user.USU_Bloqueado_Hasta = _now() + timedelta(
                minutes=settings.ACCOUNT_LOCKOUT_MINUTES
            )
        await db.commit()
        raise HTTPException(status_code=400, detail="INCORRECT_CURRENT_PASSWORD")

    # 2. Aplicar política
    try:
        security.validate_password_policy(new_password, username=current_user.USU_Username)
    except security.PasswordPolicyError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 3. Reutilizar la misma password no es aceptable
    if security.verify_password(new_password, current_user.USU_Password_Hash):
        raise HTTPException(status_code=400, detail="PASSWORD_SAME_AS_OLD")

    # 4. Actualizar hash + marca timestamp
    current_user.USU_Password_Hash = security.get_password_hash(new_password)
    current_user.USU_Password_Cambiada_En = _now()

    # 5. Revocar todos los tokens emitidos a este usuario (incluye refresh)
    gov_repo = GovernanceRepository(db)
    far_future = _now().replace(year=_now().year + 1)
    await gov_repo.revoke_all_user_tokens(current_user.USU_Usuario, expira=far_future)
    await gov_repo.create_audit_log(
        accion="PASSWORD_CHANGE",
        entidad="INV_USUARIO",
        snapshot={"username": current_user.USU_Username, "self_service": True},
        usuario_id=current_user.USU_Usuario,
        ip_origen=request.client.host if request.client else None,
    )

    await db.commit()
