"""Endpoints de autenticación: login, refresh, logout, me."""
from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.deps import CurrentUserSelfService, get_client_ip, get_user_agent, invalidate_auth_cache
from app.services.session_policy import restriction_error, session_claims
from app.core import security
from app.core.config import settings
from app.core.limiter import limiter
from app.db.session import get_db
from app.repositories.governance import GovernanceRepository
from app.repositories.organization import UsuarioRepository
from app.services.sso import SSOService

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
        # Sin max_age → cookie de sesión: el navegador la descarta al cerrarse.
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400 if settings.REFRESH_COOKIE_PERSISTENT else None,
        httponly=True,
        secure=settings.IS_PRODUCTION,  # exige HTTPS en prod; en dev/tests permite http
        samesite="strict",
        path=_REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE, path=_REFRESH_COOKIE_PATH)


def _token_response(user, claims: dict) -> dict:
    """Respuesta de login/refresh. `restriction` indica un paso de seguridad pendiente."""
    return {
        "access_token": security.create_access_token(user.USU_Username, user.USU_Rol, extra=claims),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "restriction": restriction_error(claims),
    }


def _now() -> datetime:
    """Naive UTC (compatible con columnas DateTime sin tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _persona_nombre(user) -> str:
    per = user.persona
    return f"{per.PER_Primer_Nombre} {per.PER_Primer_Apellido}" if per else user.USU_Username


async def _start_session(
    db: AsyncSession, user, request: Request, response: Response, claims: dict, metodo: str,
) -> dict:
    """
    Registra la sesión (SYS_SESION), emite el refresh con su `sid` en cookie
    HttpOnly y confirma la transacción. Si el dispositivo es nuevo para la
    cuenta, lo audita y avisa al titular por correo. Devuelve los claims del
    access token.
    """
    from app.services import sessions

    ip, ua = get_client_ip(request), get_user_agent(request)
    sesion, dispositivo_nuevo = await sessions.open_session(
        db, usuario_id=user.USU_Usuario, ip=ip, user_agent=ua, metodo=metodo,
    )
    claims = {**claims, "sid": str(sesion.SES_Sesion)}
    refresh_token = security.create_refresh_token(user.USU_Username, user.USU_Rol, extra=claims)
    sesion.SES_Refresh_Jti = sessions.token_jti(refresh_token)
    if dispositivo_nuevo:
        await GovernanceRepository(db).create_audit_log(
            accion="LOGIN_NEW_DEVICE", entidad="INV_USUARIO",
            snapshot={"username": user.USU_Username, "dispositivo": sesion.SES_Dispositivo},
            usuario_id=user.USU_Usuario, ip_origen=ip, user_agent=ua,
        )
    await db.commit()
    _set_refresh_cookie(response, refresh_token)

    if dispositivo_nuevo and settings.NEW_DEVICE_ALERT_ENABLED:
        try:
            from app.core.email import notify_security_event
            await notify_security_event(
                "nuevo_dispositivo",
                persona_nombre=_persona_nombre(user),
                username=user.USU_Username,
                to_email=user.persona.PER_Email_Corporativo if user.persona else None,
                dispositivo=sesion.SES_Dispositivo,
                ip=ip or "",
            )
        except Exception:  # noqa: BLE001 — el aviso es best-effort
            pass
    return claims


@router.get("/login/sso/providers")
async def list_sso_providers(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    service = SSOService(db)
    return {"enabled": settings.SSO_ENABLED, "providers": service.configured_providers()}


@router.get("/login/sso/{provider}/authorize")
@limiter.limit("20/minute")
async def sso_authorize(
    provider: str,
    request: Request,
    return_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    url = SSOService(db).build_authorization_url(provider, return_to=return_to)
    return {"authorization_url": url}


@router.get("/login/sso/{provider}/callback")
@limiter.limit("20/minute")
async def sso_callback(
    provider: str,
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if error:
        raise HTTPException(status_code=401, detail="SSO_PROVIDER_ERROR")
    if not code or not state:
        raise HTTPException(status_code=400, detail="SSO_CALLBACK_MISSING_CODE_OR_STATE")

    user, return_to = await SSOService(db).authenticate_callback(
        provider,
        code=code,
        state=state,
        ip=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    separator = "&" if "#" in return_to else "#"
    redirect_url = f"{return_to}{separator}sso=ok"
    response = RedirectResponse(redirect_url, status_code=303)
    user = await UsuarioRepository(db).get_by_id(user.USU_Usuario)
    await _start_session(db, user, request, response, session_claims(user, via_sso=True), "sso")
    return response


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
    if not user.USU_Password_Hash or not security.verify_password(form_data.password, user.USU_Password_Hash):
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
                "reason": (
                    "account_locked_now"
                    if locked
                    else "password_login_disabled" if not user.USU_Password_Hash else "bad_password"
                ),
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

    # Contraseña correcta: rehash si toca. El contador de intentos fallidos se
    # limpia SOLO al completar el login: con 2FA, reiniciarlo aquí permitiría
    # repetir la contraseña para seguir probando códigos del segundo factor.
    if security.needs_password_rehash(user.USU_Password_Hash):
        user.USU_Password_Hash = security.get_password_hash(form_data.password)
    if not user.USU_2FA_Habilitado:
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
    # El refresh token va solo en cookie HttpOnly: nunca en el JSON, para que
    # un XSS no pueda leerlo de la respuesta.
    claims = await _start_session(db, user, request, response, session_claims(user), "password")
    return _token_response(user, claims)


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

    now = _now()
    if user.USU_Bloqueado_Hasta and user.USU_Bloqueado_Hasta > now:
        raise HTTPException(status_code=429, detail="ACCOUNT_LOCKED")

    if not await TwoFactorService(db).verify_login(user, code):
        # Los códigos fallidos cuentan para el bloqueo de la cuenta igual que
        # las contraseñas: sin esto, 6 dígitos se podían probar sin límite
        # (repartiendo intentos entre IPs y reutilizando el challenge).
        user.USU_Intentos_Fallidos = (user.USU_Intentos_Fallidos or 0) + 1
        locked = user.USU_Intentos_Fallidos >= settings.ACCOUNT_LOCKOUT_THRESHOLD
        if locked:
            user.USU_Bloqueado_Hasta = now + timedelta(minutes=settings.ACCOUNT_LOCKOUT_MINUTES)
        await gov_repo.create_audit_log(
            accion="LOGIN_FAILED", entidad="INV_USUARIO",
            snapshot={"username": user.USU_Username,
                      "reason": "account_locked_now" if locked else "bad_2fa_code",
                      "intentos": user.USU_Intentos_Fallidos},
            usuario_id=user.USU_Usuario, ip_origen=ip, user_agent=ua,
        )
        await db.commit()
        raise HTTPException(status_code=429 if locked else 400, detail="ACCOUNT_LOCKED" if locked else "INVALID_2FA_CODE")

    user.USU_Intentos_Fallidos = 0
    user.USU_Bloqueado_Hasta = None
    user.USU_Ultimo_Login = now
    await gov_repo.create_audit_log(
        accion="LOGIN_SUCCESS", entidad="INV_USUARIO",
        snapshot={"username": user.USU_Username, "rol": user.USU_Rol, "2fa": user.USU_2FA_Metodo},
        usuario_id=user.USU_Usuario, ip_origen=ip, user_agent=ua,
    )
    claims = await _start_session(db, user, request, response, session_claims(user), "2fa")
    return _token_response(user, claims)


def _exp(payload: dict) -> datetime:
    return datetime.fromtimestamp(payload["exp"], tz=timezone.utc).replace(tzinfo=None)


def _decode_lenient(token: str, expected_type: str) -> dict | None:
    """
    Decodifica verificando FIRMA y tipo pero no expiración: al cerrar sesión
    queremos revocar incluso un access token ya vencido. None si es inválido.
    """
    from jose import JWTError, jwt as _jwt
    try:
        payload = _jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
            options={"verify_exp": False},
        )
    except JWTError:
        return None
    if payload.get("type") != expected_type or not payload.get("jti") or not payload.get("sub"):
        return None
    return payload


@router.post("/login/refresh")
@limiter.limit(settings.RATE_LIMIT_REFRESH)
async def refresh_access_token(
    request: Request,
    response: Response,
    refresh_token: str | None = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Emite un nuevo access_token a partir de un refresh_token válido, ROTANDO
    el refresh token (el jti usado se revoca de forma atómica).

    Seguridad:
    - Rotación atómica: dos requests concurrentes con el mismo refresh → solo
      uno gana; el otro recibe 401 (nunca un 500 ni dos sesiones).
    - Detección de reuso: presentar un refresh ya rotado hace más de
      REFRESH_REUSE_GRACE_SECONDS indica robo del token → se revocan TODAS las
      sesiones del usuario y se audita REFRESH_TOKEN_REUSE.
    - Sesión absoluta: el claim `auth_time` (login original) se conserva al
      rotar; pasado SESSION_ABSOLUTE_MAX_HOURS se exige login de nuevo.

    Fuente del refresh token: primero el body (clientes API), luego la cookie
    HttpOnly `rtk` (navegador). El nuevo refresh solo se entrega en cookie.
    """
    token = refresh_token or request.cookies.get(_REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="MISSING_REFRESH_TOKEN")
    payload = deps._decode_token(token, expected_type="refresh")
    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=401, detail="COULD_NOT_VALIDATE_CREDENTIALS")

    gov_repo = GovernanceRepository(db)
    repo = UsuarioRepository(db)
    user = await repo.get_by_username(payload["sub"])
    if not user or not user.USU_Estado:
        raise HTTPException(status_code=401, detail="USER_INACTIVE_OR_NOT_FOUND")

    now = _now()
    auth_time = int(payload.get("auth_time") or payload.get("iat") or 0)
    if auth_time and now.replace(tzinfo=timezone.utc).timestamp() - auth_time > settings.SESSION_ABSOLUTE_MAX_HOURS * 3600 + 60:
        raise HTTPException(status_code=401, detail="SESSION_EXPIRED")

    issued_at = security.token_issued_at(payload)
    if issued_at and await gov_repo.is_user_globally_revoked(user.USU_Usuario, issued_at):
        raise HTTPException(status_code=401, detail="TOKEN_REVOKED")

    # Sesión cerrada individualmente (o expirada): el refresh deja de valer.
    from app.services import sessions
    sid = payload.get("sid")
    sesion = await sessions.get_session(db, sid) if sid else None
    if sid and (not sessions.is_active(sesion) or sesion.USU_Usuario != user.USU_Usuario):
        raise HTTPException(status_code=401, detail="TOKEN_REVOKED")

    # Rotación atómica: si otro request ya revocó este jti, perdimos la carrera
    # o el token fue robado y reusado.
    if not await gov_repo.revoke_jti_once(jti, "refresh", _exp(payload), user.USU_Usuario):
        prev = await gov_repo.get_revocation(jti)
        revoked_at = prev.TRV_Fecha_Revocacion if prev else now
        if (now - revoked_at).total_seconds() > settings.REFRESH_REUSE_GRACE_SECONDS:
            await gov_repo.revoke_all_user_tokens(
                user.USU_Usuario, expira=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS + 1),
            )
            await gov_repo.create_audit_log(
                accion="REFRESH_TOKEN_REUSE", entidad="INV_USUARIO",
                snapshot={"username": user.USU_Username, "jti": jti},
                usuario_id=user.USU_Usuario,
                ip_origen=get_client_ip(request), user_agent=get_user_agent(request),
            )
            await db.commit()
        raise HTTPException(status_code=401, detail="TOKEN_REVOKED")

    via_sso = payload.get("amr") == "sso"
    if sesion is None:
        # Token emitido antes de existir el registro de sesiones: se registra ahora.
        sesion, _ = await sessions.open_session(
            db, usuario_id=user.USU_Usuario, ip=get_client_ip(request),
            user_agent=get_user_agent(request), metodo="sso" if via_sso else "password",
        )

    # Las restricciones se recalculan desde la BD: desaparecen en cuanto el
    # usuario cambia su contraseña temporal o enrola su MFA.
    claims = {**session_claims(user, via_sso=via_sso), "sid": str(sesion.SES_Sesion)}
    nuevo_refresh = security.create_refresh_token(
        user.USU_Username, user.USU_Rol, auth_time=auth_time or None, extra=claims,
    )
    await sessions.touch_session(
        db, sesion, refresh_jti=sessions.token_jti(nuevo_refresh), ip=get_client_ip(request),
    )
    await db.commit()
    _set_refresh_cookie(response, nuevo_refresh)
    return _token_response(user, claims)


@router.post("/login/logout", status_code=204)
@limiter.limit("20/minute")
async def logout(
    request: Request,
    response: Response,
    refresh_token: str | None = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Cierra la sesión actual: revoca el refresh token (body o cookie HttpOnly)
    y el access token del header, y limpia la cookie.

    NO exige un access token vigente: el cierre por inactividad ocurre cuando
    el access ya expiró, y aun así el refresh (la credencial de larga vida)
    DEBE revocarse. Cada token se valida por firma antes de revocarlo. Es
    idempotente: siempre responde 204.
    """
    _clear_refresh_cookie(response)
    gov_repo = GovernanceRepository(db)
    repo = UsuarioRepository(db)
    revoked: list[str] = []
    usuario = None

    candidates: list[tuple[str, str]] = []
    token = refresh_token or request.cookies.get(_REFRESH_COOKIE)
    if token:
        candidates.append((token, "refresh"))
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        candidates.append((auth_header.split(None, 1)[1], "access"))

    for raw, tipo in candidates:
        payload = _decode_lenient(raw, tipo)
        if payload is None:
            continue
        if usuario is None:
            usuario = await repo.get_by_username(payload["sub"])
        if usuario is None or usuario.USU_Username != payload["sub"]:
            continue  # tokens de usuarios distintos: se ignora el segundo
        exp = _exp(payload)
        if exp > _now() and await gov_repo.revoke_jti_once(payload["jti"], tipo, exp, usuario.USU_Usuario):
            revoked.append(payload["jti"])
        if payload.get("sid"):
            from app.services import sessions
            sesion = await sessions.get_session(db, payload["sid"])
            if sesion is not None and sesion.USU_Usuario == usuario.USU_Usuario:
                await sessions.close_session(db, sesion, "logout")

    if usuario is not None:
        await gov_repo.create_audit_log(
            accion="LOGOUT",
            entidad="INV_USUARIO",
            snapshot={"username": usuario.USU_Username, "tokens_revocados": len(revoked)},
            usuario_id=usuario.USU_Usuario,
            ip_origen=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
    await db.commit()
    if revoked:
        await invalidate_auth_cache(*revoked)


@router.post("/login/logout-all", status_code=204)
@limiter.limit("5/minute")
async def logout_all(
    current_user: CurrentUserSelfService,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Cierra TODAS las sesiones del usuario en todos los dispositivos."""
    gov_repo = GovernanceRepository(db)
    await gov_repo.revoke_all_user_tokens(
        current_user.USU_Usuario,
        expira=_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS + 1),
    )
    await gov_repo.create_audit_log(
        accion="LOGOUT_ALL", entidad="INV_USUARIO",
        snapshot={"username": current_user.USU_Username},
        usuario_id=current_user.USU_Usuario,
        ip_origen=get_client_ip(request), user_agent=get_user_agent(request),
    )
    await db.commit()
    _clear_refresh_cookie(response)


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

    from app.services import password_history
    password_history.validate_new_password(user, new_password)
    await password_history.ensure_not_reused(db, user, new_password)

    await password_history.remember_current(db, user)
    user.USU_Password_Hash = security.get_password_hash(new_password)
    user.USU_Password_Cambiada_En = _now()
    user.USU_Debe_Cambiar_Password = False
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
async def me(current_user: CurrentUserSelfService):
    """Información del usuario autenticado, incluido su alcance de datos."""
    from app.core.data_scope import user_is_global
    return {
        "username": current_user.USU_Username,
        "role": current_user.USU_Rol,
        "active": current_user.USU_Estado,
        "person_id": str(current_user.PER_Persona),
        "scope": {
            "global": user_is_global(current_user),
            "sedes": [
                {"id": s.SED_Sede, "nombre": s.SED_Nombre} for s in (current_user.sedes or [])
            ],
        },
    }


def _current_sid(request: Request) -> str | None:
    auth_header = request.headers.get("authorization") or ""
    if not auth_header.lower().startswith("bearer "):
        return None
    payload = _decode_lenient(auth_header.split(None, 1)[1], "access")
    return payload.get("sid") if payload else None


@router.get("/me/sessions")
async def my_sessions(
    request: Request, current_user: CurrentUserSelfService, db: AsyncSession = Depends(get_db),
):
    """Sesiones activas de la cuenta (la actual marcada con `actual`)."""
    from app.services import sessions
    current = _current_sid(request)
    return [
        sessions.serialize(s, current_sid=current)
        for s in await sessions.list_sessions(db, current_user.USU_Usuario)
    ]


@router.delete("/me/sessions/{session_id}", status_code=204)
@limiter.limit("20/minute")
async def close_my_session(
    session_id: str, request: Request, current_user: CurrentUserSelfService,
    db: AsyncSession = Depends(get_db),
):
    """Cierra una sesión propia (p. ej. un equipo perdido o no reconocido)."""
    from app.services import sessions
    sesion = await sessions.get_session(db, session_id)
    if sesion is None or sesion.USU_Usuario != current_user.USU_Usuario:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    if await sessions.close_session(db, sesion, "cerrada_por_titular"):
        await GovernanceRepository(db).create_audit_log(
            accion="SESSION_CLOSED", entidad="SYS_SESION",
            snapshot={"username": current_user.USU_Username, "sesion": session_id,
                      "dispositivo": sesion.SES_Dispositivo, "por": "titular"},
            usuario_id=current_user.USU_Usuario,
            ip_origen=get_client_ip(request), user_agent=get_user_agent(request),
        )
    await db.commit()


@router.post("/me/password", status_code=204)
@limiter.limit("5/minute")
async def change_my_password(
    request: Request,
    current_user: CurrentUserSelfService,
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

    # 2. Aplicar política (incluye listas de bloqueo y datos personales)
    from app.services import password_history
    password_history.validate_new_password(current_user, new_password)

    # 3. No se acepta la contraseña actual ni una de las últimas N
    await password_history.ensure_not_reused(db, current_user, new_password)

    # 4. Actualizar hash + marca timestamp (la anterior pasa al historial)
    await password_history.remember_current(db, current_user)
    current_user.USU_Password_Hash = security.get_password_hash(new_password)
    current_user.USU_Password_Cambiada_En = _now()
    current_user.USU_Debe_Cambiar_Password = False  # la temporal quedó reemplazada

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
