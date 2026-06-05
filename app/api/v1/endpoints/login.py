"""Endpoints de autenticación: login, refresh, logout, me."""
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.deps import CurrentUser, get_client_ip, get_user_agent, invalidate_auth_cache
from app.core import security
from app.core.config import settings
from app.core.limiter import limiter
from app.db.session import get_db
from app.repositories.governance import GovernanceRepository
from app.repositories.organization import UsuarioRepository

router = APIRouter()

# Cookie HttpOnly para el refresh token. Al vivir en una cookie HttpOnly +
# Secure + SameSite=Strict, el refresh token NO es accesible desde JavaScript
# (inmune a exfiltración por XSS) y el navegador lo envía automáticamente solo
# a las rutas de login (mismo origen). El access token sigue en memoria del SPA.
_REFRESH_COOKIE = "rtk"
_REFRESH_COOKIE_PATH = f"{settings.API_V1_STR}/login"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        secure=settings.IS_PRODUCTION,  # exige HTTPS en prod; en dev/tests permite http
        samesite="strict",
        path=_REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE, path=_REFRESH_COOKIE_PATH)


def _now() -> datetime:
    """Naive UTC (compatible con columnas DateTime sin tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/login/access-token")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login_access_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """OAuth2-compatible token login. Aplica account lockout y auditoría."""
    repo = UsuarioRepository(db)
    gov_repo = GovernanceRepository(db)
    ip = get_client_ip(request)
    ua = get_user_agent(request)

    async def _audit_failed(reason: str, usuario_id=None) -> None:
        await gov_repo.create_audit_log(
            accion="LOGIN_FAILED",
            entidad="INV_USUARIO",
            snapshot={"username": (form_data.username or "")[:64], "reason": reason},
            usuario_id=usuario_id,
            ip_origen=ip,
            user_agent=ua,
        )
        await db.commit()

    user = await repo.get_by_username(form_data.username)

    # Usuario inexistente: gastamos el MISMO tiempo de CPU que un verify real
    # (hash dummy) para no filtrar la existencia de la cuenta por timing, y
    # devolvemos el mismo mensaje genérico.
    if not user:
        security.verify_password_dummy()
        await _audit_failed("user_not_found")
        raise HTTPException(status_code=400, detail="INCORRECT_USERNAME_OR_PASSWORD")

    now = _now()

    # ¿Cuenta bloqueada por intentos previos?
    if user.USU_Bloqueado_Hasta and user.USU_Bloqueado_Hasta > now:
        await _audit_failed("account_locked", usuario_id=user.USU_Usuario)
        raise HTTPException(status_code=429, detail="ACCOUNT_LOCKED")

    # Verificar contraseña
    if not security.verify_password(form_data.password, user.USU_Password_Hash):
        user.USU_Intentos_Fallidos = (user.USU_Intentos_Fallidos or 0) + 1
        locked = user.USU_Intentos_Fallidos >= settings.ACCOUNT_LOCKOUT_THRESHOLD
        if locked:
            user.USU_Bloqueado_Hasta = now + timedelta(
                minutes=settings.ACCOUNT_LOCKOUT_MINUTES
            )
        await gov_repo.create_audit_log(
            accion="LOGIN_FAILED",
            entidad="INV_USUARIO",
            snapshot={
                "username": user.USU_Username,
                "reason": "account_locked_now" if locked else "bad_password",
                "intentos": user.USU_Intentos_Fallidos,
            },
            usuario_id=user.USU_Usuario,
            ip_origen=ip,
            user_agent=ua,
        )
        await db.commit()
        raise HTTPException(status_code=400, detail="INCORRECT_USERNAME_OR_PASSWORD")

    if not user.USU_Estado:
        await _audit_failed("inactive_user", usuario_id=user.USU_Usuario)
        raise HTTPException(status_code=400, detail="INACTIVE_USER")

    # Contraseña correcta: limpiar lockout y rehash si toca (aplica con o sin 2FA).
    if security.needs_password_rehash(user.USU_Password_Hash):
        user.USU_Password_Hash = security.get_password_hash(form_data.password)
    user.USU_Intentos_Fallidos = 0
    user.USU_Bloqueado_Hasta = None

    # ---- 2FA: si está habilitado, NO se entregan tokens aún. Se emite un
    # "challenge" y se exige el 2º factor en /login/2fa/verify. ----
    if user.USU_2FA_Habilitado:
        await gov_repo.create_audit_log(
            accion="2FA_CHALLENGE", entidad="INV_USUARIO",
            snapshot={"username": user.USU_Username, "metodo": user.USU_2FA_Metodo},
            usuario_id=user.USU_Usuario, ip_origen=ip, user_agent=ua,
        )
        await db.commit()
        if user.USU_2FA_Metodo == "EMAIL":
            from app.services.twofactor import TwoFactorService
            await TwoFactorService(db).issue_email_login_otp(user)
        return {
            "requires_2fa": True,
            "method": user.USU_2FA_Metodo,
            "challenge_token": security.create_2fa_challenge_token(user.USU_Username),
        }

    # Login exitoso (sin 2FA).
    user.USU_Ultimo_Login = now
    await gov_repo.create_audit_log(
        accion="LOGIN_SUCCESS",
        entidad="INV_USUARIO",
        snapshot={"username": user.USU_Username, "rol": user.USU_Rol},
        usuario_id=user.USU_Usuario,
        ip_origen=ip,
        user_agent=ua,
    )
    await db.commit()

    refresh_token = security.create_refresh_token(user.USU_Username, user.USU_Rol)
    # Refresh token también en cookie HttpOnly (la fuente preferida para el SPA).
    _set_refresh_cookie(response, refresh_token)
    return {
        "access_token": security.create_access_token(user.USU_Username, user.USU_Rol),
        # Se mantiene en el body para clientes API/no-navegador; el SPA usa la cookie.
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/login/2fa/verify")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def verify_2fa(
    request: Request,
    response: Response,
    challenge_token: str = Body(..., embed=True, min_length=10),
    code: str = Body(..., embed=True, min_length=4, max_length=20),
    db: AsyncSession = Depends(get_db),
):
    """
    Segundo paso del login con 2FA: valida el código (TOTP/email) o un código de
    recuperación contra el 'challenge' emitido tras la contraseña. En éxito,
    entrega los tokens (igual que un login normal).
    """
    from app.services.twofactor import TwoFactorService
    ip = get_client_ip(request)
    ua = get_user_agent(request)
    gov_repo = GovernanceRepository(db)

    username = security.decode_2fa_challenge(challenge_token)
    if not username:
        raise HTTPException(status_code=401, detail="INVALID_OR_EXPIRED_2FA_CHALLENGE")

    repo = UsuarioRepository(db)
    user = await repo.get_by_username(username)
    if not user or not user.USU_Estado or not user.USU_2FA_Habilitado:
        raise HTTPException(status_code=401, detail="INVALID_OR_EXPIRED_2FA_CHALLENGE")

    if not await TwoFactorService(db).verify_login(user, code):
        await gov_repo.create_audit_log(
            accion="LOGIN_FAILED", entidad="INV_USUARIO",
            snapshot={"username": user.USU_Username, "reason": "bad_2fa_code"},
            usuario_id=user.USU_Usuario, ip_origen=ip, user_agent=ua,
        )
        await db.commit()
        raise HTTPException(status_code=400, detail="INVALID_2FA_CODE")

    user.USU_Ultimo_Login = _now()
    await gov_repo.create_audit_log(
        accion="LOGIN_SUCCESS", entidad="INV_USUARIO",
        snapshot={"username": user.USU_Username, "rol": user.USU_Rol, "2fa": user.USU_2FA_Metodo},
        usuario_id=user.USU_Usuario, ip_origen=ip, user_agent=ua,
    )
    await db.commit()

    refresh_token = security.create_refresh_token(user.USU_Username, user.USU_Rol)
    _set_refresh_cookie(response, refresh_token)
    return {
        "access_token": security.create_access_token(user.USU_Username, user.USU_Rol),
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/login/refresh")
@limiter.limit("10/minute")
async def refresh_access_token(
    request: Request,
    response: Response,
    refresh_token: str | None = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Emite un nuevo access_token a partir de un refresh_token válido y no
    revocado, ROTANDO el refresh token: el jti usado se revoca y se emite uno
    nuevo. Si el mismo refresh se reusa (token robado + token legítimo), el
    segundo intento choca con la revocación → 401 TOKEN_REVOKED (detección de
    reuso).

    Fuente del refresh token: primero el body (clientes API), luego la cookie
    HttpOnly `rtk` (navegador). El nuevo refresh se devuelve en el body Y se
    setea en la cookie rotada.
    """
    token = refresh_token or request.cookies.get(_REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="MISSING_REFRESH_TOKEN")
    payload = deps._decode_token(token, expected_type="refresh")

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

    # Rotación: revocar el refresh token que se acaba de usar.
    if jti:
        await gov_repo.revoke_jti(
            jti=jti,
            tipo="refresh",
            expira=datetime.fromtimestamp(payload["exp"], tz=timezone.utc).replace(tzinfo=None),
            usuario_id=user.USU_Usuario,
        )
        await db.commit()

    nuevo_refresh = security.create_refresh_token(user.USU_Username, user.USU_Rol)
    _set_refresh_cookie(response, nuevo_refresh)
    return {
        "access_token": security.create_access_token(user.USU_Username, user.USU_Rol),
        "refresh_token": nuevo_refresh,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/login/logout", status_code=204)
@limiter.limit("10/minute")
async def logout(
    current_user: CurrentUser,
    request: Request,
    response: Response,
    refresh_token: str | None = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoca el access token actual y el refresh token (del body o de la cookie
    HttpOnly), y limpia la cookie.
    """
    gov_repo = GovernanceRepository(db)
    jtis_to_purge: list[str] = []
    # El refresh puede venir en el body (API) o en la cookie (navegador).
    refresh_token = refresh_token or request.cookies.get(_REFRESH_COOKIE)
    _clear_refresh_cookie(response)

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

    await gov_repo.create_audit_log(
        accion="LOGOUT",
        entidad="INV_USUARIO",
        snapshot={"username": current_user.USU_Username, "tokens_revocados": len(jtis_to_purge)},
        usuario_id=current_user.USU_Usuario,
        ip_origen=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    await db.commit()
    # Purgar caché para que el siguiente request use BD (devolverá 401).
    if jtis_to_purge:
        await invalidate_auth_cache(*jtis_to_purge)


@router.post("/login/password-reset/request", status_code=202)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def request_password_reset(
    request: Request,
    identifier: str = Body(..., embed=True, min_length=1, max_length=150,
                           description="Username o correo corporativo"),
    db: AsyncSession = Depends(get_db),
):
    """
    Inicia el restablecimiento de contraseña. Por seguridad responde SIEMPRE lo
    mismo (anti-enumeración): no revela si la cuenta existe. Si existe, está
    activa y tiene correo, genera un token de un solo uso y lo envía ÚNICAMENTE
    al correo corporativo registrado — esa es la validación de que la solicitud
    corresponde al dueño del correo.
    """
    generic = {"message": "Si la cuenta existe, se enviaron instrucciones al correo registrado."}
    repo = UsuarioRepository(db)
    gov_repo = GovernanceRepository(db)

    user = await repo.get_by_username_or_email(identifier.strip())
    if not user or not user.USU_Estado or not user.persona or not user.persona.PER_Email_Corporativo:
        # Respuesta uniforme: no filtramos existencia/estado de la cuenta.
        return generic

    # Throttle POR CUENTA: si ya se solicitó un reset en la ventana de enfriamiento,
    # no emitimos otro correo (anti-bombardeo). Respuesta genérica igualmente.
    if await gov_repo.has_recent_reset_request(
        user.USU_Usuario, settings.PASSWORD_RESET_REQUEST_COOLDOWN_MINUTES
    ):
        return generic

    # Un solo token activo a la vez: invalidamos los pendientes.
    await gov_repo.invalidate_user_reset_tokens(user.USU_Usuario)
    token_plain, token_hash = security.generate_reset_token()
    expira = _now() + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)
    await gov_repo.create_reset_token(user.USU_Usuario, token_hash, expira)
    await gov_repo.create_audit_log(
        accion="PASSWORD_RESET_REQUEST", entidad="INV_USUARIO",
        snapshot={"username": user.USU_Username},
        usuario_id=user.USU_Usuario, ip_origen=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    await db.commit()

    # Email post-commit (fire-and-forget): SOLO al correo del usuario, sin CC admins.
    try:
        from app.core.email import send_notification
        reset_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/reset-password?token={token_plain}"
        await send_notification(
            "password_reset",
            {
                "persona_nombre": f"{user.persona.PER_Primer_Nombre} {user.persona.PER_Primer_Apellido}",
                "username": user.USU_Username,
                "token": token_plain,
                "reset_url": reset_url,
                "minutos": settings.PASSWORD_RESET_EXPIRE_MINUTES,
            },
            to=[user.persona.PER_Email_Corporativo],
            cc_admins=False,  # NUNCA copiar a admins: el token es secreto del usuario
        )
    except Exception:  # noqa: BLE001
        pass
    return generic


@router.post("/login/password-reset/confirm", status_code=204)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def confirm_password_reset(
    request: Request,
    token: str = Body(..., embed=True, min_length=8, max_length=200),
    new_password: str = Body(..., embed=True, min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """
    Completa el restablecimiento: valida el token (un solo uso, no expirado),
    aplica la política de contraseña, fija la nueva, marca el token como usado y
    revoca TODOS los tokens del usuario (debe re-loguear).
    """
    gov_repo = GovernanceRepository(db)
    token_hash = security.hash_reset_token(token.strip())
    prt = await gov_repo.get_valid_reset_token(token_hash)
    if not prt:
        raise HTTPException(status_code=400, detail="INVALID_OR_EXPIRED_RESET_TOKEN")

    repo = UsuarioRepository(db)
    user = await repo.get_by_id(prt.USU_Usuario)
    if not user or not user.USU_Estado:
        raise HTTPException(status_code=400, detail="INVALID_OR_EXPIRED_RESET_TOKEN")

    try:
        security.validate_password_policy(new_password, username=user.USU_Username)
    except security.PasswordPolicyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if security.verify_password(new_password, user.USU_Password_Hash):
        raise HTTPException(status_code=400, detail="PASSWORD_SAME_AS_OLD")

    user.USU_Password_Hash = security.get_password_hash(new_password)
    user.USU_Password_Cambiada_En = _now()
    # Resetear lockout: el dueño legítimo recupera el acceso.
    user.USU_Intentos_Fallidos = 0
    user.USU_Bloqueado_Hasta = None

    await gov_repo.mark_reset_token_used(prt.PRT_Id)
    far_future = _now().replace(year=_now().year + 1)
    await gov_repo.revoke_all_user_tokens(user.USU_Usuario, expira=far_future)
    await gov_repo.create_audit_log(
        accion="PASSWORD_RESET", entidad="INV_USUARIO",
        snapshot={"username": user.USU_Username, "via": "email_token"},
        usuario_id=user.USU_Usuario, ip_origen=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    await db.commit()

    # Aviso de seguridad al dueño de la cuenta de que su contraseña se restableció.
    try:
        from app.core.email import notify_password_changed
        per = user.persona
        await notify_password_changed(
            persona_nombre=(f"{per.PER_Primer_Nombre} {per.PER_Primer_Apellido}" if per else user.USU_Username),
            username=user.USU_Username,
            to_email=(per.PER_Email_Corporativo if per else None),
            metodo="Restablecimiento por email",
            ip=get_client_ip(request),
        )
    except Exception:  # noqa: BLE001
        pass


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
    # La longitud/robustez la valida `validate_password_policy` (única fuente de
    # verdad, configurable vía PASSWORD_MIN_LENGTH). Aquí solo exigimos no-vacío.
    new_password: str = Body(..., embed=True, min_length=1),
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
        ip_origen=get_client_ip(request),
        user_agent=get_user_agent(request),
    )

    await db.commit()

    # Aviso de seguridad al dueño de la cuenta (post-commit, fire-and-forget).
    try:
        from app.core.email import notify_password_changed
        per = current_user.persona
        await notify_password_changed(
            persona_nombre=(f"{per.PER_Primer_Nombre} {per.PER_Primer_Apellido}" if per else current_user.USU_Username),
            username=current_user.USU_Username,
            to_email=(per.PER_Email_Corporativo if per else None),
            metodo="Autoservicio (cambio manual)",
            ip=get_client_ip(request),
        )
    except Exception:  # noqa: BLE001
        pass
