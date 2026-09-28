"""
Ciclo de vida de sesiones: cierre de sesión, rotación del refresh token,
detección de reuso, inactividad y duración absoluta, cierre global.

Cada test reproduce un fallo real detectado en la auditoría de seguridad:
- el logout exigía un access vigente → al cerrar por inactividad (access ya
  vencido) el refresh token quedaba VÁLIDO en el servidor;
- dos refresh concurrentes con el mismo token → 500 por PK duplicada;
- el reuso de un refresh rotado no revocaba nada (sin detección de robo).
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import select

from app.core import security
from app.core.config import settings
from app.models.governance import AuditoriaSistema

LOGIN = "/api/v1/login/access-token"
REFRESH = "/api/v1/login/refresh"
LOGOUT = "/api/v1/login/logout"
LOGOUT_ALL = "/api/v1/login/logout-all"
ME = "/api/v1/me"


async def _login(client):
    r = await client.post(LOGIN, data={"username": "sa", "password": "TestPassw0rd!"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"], r.cookies.get("rtk")


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _expired_access(username="sa"):
    return security._create_token(username, "SUPER_ADMIN", "access", timedelta(seconds=-5))


@pytest.mark.asyncio
async def test_cookie_refresh_es_de_sesion_y_httponly(client, sa_user):
    r = await client.post(LOGIN, data={"username": "sa", "password": "TestPassw0rd!"})
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie
    assert "max-age" not in set_cookie  # se borra al cerrar el navegador
    assert "path=/api/v1/login" in set_cookie


@pytest.mark.asyncio
async def test_refresh_respeta_inactividad(client, sa_user):
    _, rtk = await _login(client)
    claims = jwt.get_unverified_claims(rtk)
    assert claims["exp"] - claims["iat"] <= settings.SESSION_IDLE_TIMEOUT_MINUTES * 60
    assert claims["auth_time"]


@pytest.mark.asyncio
async def test_logout_con_access_vencido_revoca_refresh(client, sa_user):
    """Cierre por inactividad: el access ya expiró; el refresh DEBE revocarse."""
    _, rtk = await _login(client)
    r = await client.post(LOGOUT, json={"refresh_token": rtk}, headers=_bearer(_expired_access()))
    assert r.status_code == 204
    r = await client.post(REFRESH, json={"refresh_token": rtk})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_solo_con_cookie(client, sa_user):
    """El SPA limpia la memoria antes de que salga el request: basta la cookie."""
    access, _ = await _login(client)  # la cookie rtk queda en el cliente
    r = await client.post(LOGOUT)
    assert r.status_code == 204
    assert (await client.post(REFRESH)).status_code == 401
    # Aunque el access no se envió, pertenece a la sesión cerrada (claim sid):
    # deja de valer de inmediato, no al expirar.
    assert (await client.get(ME, headers=_bearer(access))).status_code == 401


@pytest.mark.asyncio
async def test_logout_revoca_access_y_es_idempotente(client, sa_user):
    access, _ = await _login(client)
    assert (await client.post(LOGOUT, headers=_bearer(access))).status_code == 204
    assert (await client.get(ME, headers=_bearer(access))).status_code == 401
    assert (await client.post(LOGOUT, headers=_bearer(access))).status_code == 204
    assert (await client.post(LOGOUT, headers=_bearer("basura"))).status_code == 204


@pytest.mark.asyncio
async def test_logout_ignora_token_con_firma_invalida(client, sa_user):
    access, rtk = await _login(client)
    forged = jwt.encode(jwt.get_unverified_claims(rtk), "otra-clave-" * 4, algorithm="HS256")
    assert (await client.post(LOGOUT, json={"refresh_token": forged})).status_code == 204
    # El refresh legítimo sigue válido: el token falsificado no revocó nada.
    client.cookies.clear()
    assert (await client.post(REFRESH, json={"refresh_token": rtk})).status_code == 200


@pytest.mark.asyncio
async def test_refresh_concurrente_no_da_500(client, sa_user):
    _, rtk = await _login(client)
    client.cookies.clear()
    results = await asyncio.gather(*[
        client.post(REFRESH, json={"refresh_token": rtk}) for _ in range(4)
    ])
    codes = sorted(r.status_code for r in results)
    assert 500 not in codes
    assert codes.count(200) == 1, codes


@pytest.mark.asyncio
async def test_reuso_de_refresh_revoca_todas_las_sesiones(client, sa_user, session, monkeypatch):
    monkeypatch.setattr(settings, "REFRESH_REUSE_GRACE_SECONDS", -1)
    access, rtk = await _login(client)
    client.cookies.clear()
    r = await client.post(REFRESH, json={"refresh_token": rtk})
    assert r.status_code == 200
    rotated = r.cookies.get("rtk")
    new_access = r.json()["access_token"]
    client.cookies.clear()

    # Un atacante reusa el refresh viejo → se revoca TODO.
    assert (await client.post(REFRESH, json={"refresh_token": rtk})).status_code == 401
    assert (await client.post(REFRESH, json={"refresh_token": rotated})).status_code == 401
    assert (await client.get(ME, headers=_bearer(new_access))).status_code == 401
    audit = (await session.execute(
        select(AuditoriaSistema).where(AuditoriaSistema.AUD_Accion == "REFRESH_TOKEN_REUSE")
    )).scalars().all()
    assert len(audit) == 1
    # El usuario legítimo puede volver a entrar de inmediato.
    access2, _ = await _login(client)
    assert (await client.get(ME, headers=_bearer(access2))).status_code == 200


@pytest.mark.asyncio
async def test_reuso_dentro_de_gracia_no_revoca_todo(client, sa_user):
    """Carrera legítima (dos pestañas / respuesta perdida): 401 sin cerrar todo."""
    _, rtk = await _login(client)
    client.cookies.clear()
    r = await client.post(REFRESH, json={"refresh_token": rtk})
    rotated = r.cookies.get("rtk")
    client.cookies.clear()
    assert (await client.post(REFRESH, json={"refresh_token": rtk})).status_code == 401
    assert (await client.post(REFRESH, json={"refresh_token": rotated})).status_code == 200


@pytest.mark.asyncio
async def test_sesion_absoluta_expira(client, sa_user):
    old = int((datetime.now(timezone.utc) - timedelta(hours=settings.SESSION_ABSOLUTE_MAX_HOURS + 1)).timestamp())
    stale = security._create_token(
        "sa", "SUPER_ADMIN", "refresh", timedelta(minutes=10), extra={"auth_time": old},
    )
    r = await client.post(REFRESH, json={"refresh_token": stale})
    assert r.status_code == 401
    assert r.json()["detail"] == "SESSION_EXPIRED"


@pytest.mark.asyncio
async def test_rotacion_conserva_auth_time(client, sa_user):
    _, rtk = await _login(client)
    client.cookies.clear()
    r = await client.post(REFRESH, json={"refresh_token": rtk})
    assert jwt.get_unverified_claims(r.cookies.get("rtk"))["auth_time"] == jwt.get_unverified_claims(rtk)["auth_time"]


@pytest.mark.asyncio
async def test_logout_all_cierra_otros_dispositivos_y_permite_reingreso(client, sa_user):
    pc_access, pc_rtk = await _login(client)
    client.cookies.clear()
    movil_access, movil_rtk = await _login(client)

    assert (await client.post(LOGOUT_ALL, headers=_bearer(movil_access))).status_code == 204
    client.cookies.clear()
    assert (await client.get(ME, headers=_bearer(pc_access))).status_code == 401
    assert (await client.post(REFRESH, json={"refresh_token": pc_rtk})).status_code == 401
    assert (await client.post(REFRESH, json={"refresh_token": movil_rtk})).status_code == 401

    # Reingreso inmediato (mismo segundo): iat_ms evita falsos "revocado".
    access, _ = await _login(client)
    assert (await client.get(ME, headers=_bearer(access))).status_code == 200


def test_config_inactividad_menor_que_access():
    from app.core.config import Settings
    dev = Settings(SECRET_KEY="x" * 40, SESSION_IDLE_TIMEOUT_MINUTES=10, ACCESS_TOKEN_EXPIRE_MINUTES=15)
    assert dev.SESSION_IDLE_TIMEOUT_MINUTES == 30  # ajustado en desarrollo
    with pytest.raises(ValueError, match="SESSION_IDLE_TIMEOUT_MINUTES"):
        Settings(SECRET_KEY="x" * 40, SESSION_IDLE_TIMEOUT_MINUTES=10, ACCESS_TOKEN_EXPIRE_MINUTES=15,
                 ENVIRONMENT="production", FIELD_ENCRYPTION_KEY="k")
