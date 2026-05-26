"""Dependencias FastAPI compartidas: auth, RBAC, paginación."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError, ExpiredSignatureError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_delete, cache_get, cache_set
from app.core.config import settings
from app.db.session import get_db
from app.models.organization import Usuario
from app.repositories.governance import GovernanceRepository
from app.repositories.organization import UsuarioRepository

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def _decode_token(token: str, expected_type: Literal["access", "refresh"] = "access") -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="TOKEN_EXPIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="COULD_NOT_VALIDATE_CREDENTIALS",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TOKEN_TYPE",
        )

    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="COULD_NOT_VALIDATE_CREDENTIALS",
        )
    return payload


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(reusable_oauth2),
) -> Usuario:
    """
    Resuelve y valida el usuario del token JWT. Aplica caché en Redis
    cuando está disponible: el resultado se cachea por TTL corto (default 30s)
    bajo la clave 'auth:jti:{jti}'. La caché se invalida automáticamente:
      - por TTL,
      - cuando el JTI se revoca (logout) -> revocación grabada en BD,
      - cuando hay revocación global -> validamos contra is_user_globally_revoked
        siempre, incluso en cache hit (cuesta una query barata pero garantiza
        que un cambio de password invalide inmediatamente todos los tokens).
    """
    payload = _decode_token(token, expected_type="access")
    username = payload["sub"]
    jti = payload.get("jti")
    iat = payload.get("iat")

    gov_repo = GovernanceRepository(db)

    # 1. Revocación individual (logout) — chequeo barato si está cacheado el resultado.
    cache_key = f"auth:jti:{jti}" if jti else None
    cached = await cache_get(cache_key) if cache_key else None

    if cached and cached.get("revoked"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="TOKEN_REVOKED"
        )

    if not cached:
        if jti and await gov_repo.is_jti_revoked(jti):
            # Cachear el "revocado" para evitar query repetida en el TTL.
            if cache_key:
                await cache_set(cache_key, {"revoked": True}, settings.AUTH_CACHE_TTL_SECONDS)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="TOKEN_REVOKED"
            )

    # 2. Usuario — desde caché si lo tenemos, si no cargamos.
    user: Usuario | None = None
    if cached and cached.get("username"):
        repo = UsuarioRepository(db)
        user = await repo.get_by_username(username=cached["username"])
    else:
        repo = UsuarioRepository(db)
        user = await repo.get_by_username(username=username)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="COULD_NOT_VALIDATE_CREDENTIALS"
        )

    if not user.USU_Estado:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="INACTIVE_USER")

    # 3. Revocación global SIEMPRE se valida (no se cachea como "ok"), para que un
    #    cambio de password o offboarding tenga efecto inmediato.
    if iat:
        issued_at = datetime.fromtimestamp(iat, tz=timezone.utc).replace(tzinfo=None)
        if await gov_repo.is_user_globally_revoked(user.USU_Usuario, issued_at):
            # Marcar revocado en caché para próximos hits del mismo jti.
            if cache_key:
                await cache_set(cache_key, {"revoked": True}, settings.AUTH_CACHE_TTL_SECONDS)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="TOKEN_REVOKED"
            )

    # Cachear "válido" si no estaba.
    if cache_key and not cached:
        await cache_set(
            cache_key,
            {"revoked": False, "username": user.USU_Username},
            settings.AUTH_CACHE_TTL_SECONDS,
        )

    return user


async def invalidate_auth_cache(*jtis: str) -> None:
    """Útil al hacer logout: borra entradas específicas para no esperar TTL."""
    keys = [f"auth:jti:{j}" for j in jtis if j]
    if keys:
        await cache_delete(*keys)


CurrentUser = Annotated[Usuario, Depends(get_current_user)]


class RoleChecker:
    """
    Dependencia que valida que el usuario tenga uno de los roles permitidos.

    Uso:
        require_admin = RoleChecker(["SUPER_ADMIN", "ADMIN_TI"])
        @router.post("/...", dependencies=[Depends(require_admin)])
    """

    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = set(allowed_roles)

    def __call__(self, user: Usuario = Depends(get_current_user)) -> Usuario:
        if user.USU_Rol not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="NOT_ENOUGH_PERMISSIONS",
            )
        return user


# Atajos comunes
require_super_admin = RoleChecker(["SUPER_ADMIN"])
require_admin = RoleChecker(["SUPER_ADMIN", "ADMIN_TI"])
require_operativo = RoleChecker(["SUPER_ADMIN", "ADMIN_TI", "TECNICO"])
# Cualquier autenticado: usar Depends(get_current_user) directamente.


# =========================================================================
# PAGINACIÓN
# =========================================================================
class PaginationParams:
    """Cota superior fija de paginación para evitar abusos."""

    def __init__(
        self,
        skip: int = Query(0, ge=0, description="Items a omitir"),
        limit: int = Query(50, ge=1, le=settings.PAGINATION_MAX_LIMIT, description="Items a retornar"),
    ):
        self.skip = skip
        self.limit = limit


# =========================================================================
# CONTEXTO DE REQUEST (para auditoría)
# =========================================================================
def get_client_ip(request: Request) -> str | None:
    # Respetar X-Forwarded-For si viene detrás de un proxy/lb confiable.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def get_user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:255] if ua else None
