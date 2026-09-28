"""
Gestión de identidades y accesos (IAM):
- rol ADMIN_SEGURIDAD y separación de funciones (sin acceso al inventario);
- jerarquía: nadie administra su propia cuenta; los roles protegidos solo los
  gestiona un SUPER_ADMIN;
- contraseña temporal con cambio obligatorio (sesión restringida);
- MFA obligatorio por rol (sesión restringida hasta enrolar);
- bloqueo por intentos fallidos también en el segundo factor.
"""
import time
import uuid

import pyotp
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import get_password_hash, validate_password_policy
from app.models.governance import AuditoriaSistema
from app.models.organization import Cargo, Departamento, Persona, Usuario

FORM = {"Content-Type": "application/x-www-form-urlencoded"}
PWD = "Segura#2026x"


async def _mk_user(session, username, role, *, mfa_secret=None, must_change=False):
    dep = (await session.execute(select(Departamento))).scalars().first()
    if dep is None:
        dep = Departamento(DEP_Nombre="IAM")
        session.add(dep)
        await session.flush()
    car = (await session.execute(select(Cargo))).scalars().first()
    if car is None:
        car = Cargo(CAR_Nombre="IAM")
        session.add(car)
        await session.flush()
    per = Persona(PER_Primer_Nombre=username.title(), PER_Primer_Apellido="Test",
                  PER_Email_Corporativo=f"{username}@empresa.local",
                  DEP_Departamento=dep.DEP_Departamento, CAR_Cargo=car.CAR_Cargo)
    session.add(per)
    await session.flush()
    from app.core.security import encrypt_field
    usu = Usuario(USU_Username=username, USU_Password_Hash=get_password_hash(PWD), USU_Rol=role,
                  PER_Persona=per.PER_Persona, USU_Debe_Cambiar_Password=must_change,
                  USU_2FA_Habilitado=bool(mfa_secret), USU_2FA_Metodo="TOTP" if mfa_secret else None,
                  USU_2FA_Secret=encrypt_field(mfa_secret) if mfa_secret else None)
    session.add(usu)
    await session.commit()
    return usu, per


async def _login(client, username, password=PWD):
    return (await client.post("/api/v1/login/access-token",
                              data={"username": username, "password": password}, headers=FORM)).json()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


async def _headers(client, username, password=PWD):
    body = await _login(client, username, password)
    assert body.get("access_token"), body
    return _h(body["access_token"])


# =========================================================================
# Rol ADMIN_SEGURIDAD y separación de funciones
# =========================================================================
@pytest.mark.asyncio
async def test_admin_seguridad_gestiona_usuarios_pero_no_inventario(client, session, sa_user):
    await _mk_user(session, "seguridad1", "ADMIN_SEGURIDAD")
    h = await _headers(client, "seguridad1")
    assert (await client.get("/api/v1/org/usuarios", headers=h)).status_code == 200
    assert (await client.get("/api/v1/org/usuarios/seguridad/resumen", headers=h)).status_code == 200
    assert (await client.get("/api/v1/gov/auditoria", headers=h)).status_code == 200
    # Sin acceso al inventario ni a la configuración del sistema.
    for url in ("/api/v1/core/activos", "/api/v1/stats/dashboard", "/api/v1/trazabilidad/movimientos",
                "/api/v1/export/activos.csv"):
        assert (await client.get(url, headers=h)).status_code == 403, url
    r = await client.put("/api/v1/gov/config", headers=h, json={"SYS_Nombre_Empresa": "X"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_ti_ya_no_gestiona_usuarios(client, session, sa_user):
    await _mk_user(session, "opsti", "ADMIN_TI")
    h = await _headers(client, "opsti")
    assert (await client.get("/api/v1/org/usuarios", headers=h)).status_code == 403
    assert (await client.get("/api/v1/core/activos", headers=h)).status_code == 200


@pytest.mark.asyncio
async def test_jerarquia_de_roles(client, session, sa_user, auth_headers):
    await _mk_user(session, "seg_a", "ADMIN_SEGURIDAD")
    par, _ = await _mk_user(session, "seg_b", "ADMIN_SEGURIDAD")
    tec, _ = await _mk_user(session, "tec_a", "TECNICO")
    _, per_libre = await _mk_user(session, "sin_rol_tmp", "CONSULTA")
    h = await _headers(client, "seg_a")

    # Puede crear roles operativos…
    p = Persona(PER_Primer_Nombre="Nuevo", PER_Primer_Apellido="Operador",
                PER_Email_Corporativo="nuevo.op@empresa.local",
                DEP_Departamento=per_libre.DEP_Departamento, CAR_Cargo=per_libre.CAR_Cargo)
    session.add(p)
    await session.commit()
    from tests.conftest import crear_sede
    sede = (await crear_sede(session, "Sede IAM"))["sede"]
    # El alcance global solo lo otorga un SUPER_ADMIN.
    glob = await client.post("/api/v1/org/usuarios", headers=h, json={
        "USU_Username": "nuevo_op", "USU_Password": "Kx7!Tmpr#Q26", "USU_Rol": "ADMIN_TI",
        "USU_Alcance_Global": True, "PER_Persona": str(p.PER_Persona)})
    assert glob.status_code == 403 and glob.json()["detail"] == "ONLY_SUPER_ADMIN_CAN_GRANT_GLOBAL_SCOPE"
    ok = await client.post("/api/v1/org/usuarios", headers=h, json={
        "USU_Username": "nuevo_op", "USU_Password": "Kx7!Tmpr#Q26", "USU_Rol": "ADMIN_TI",
        "sedes": [sede], "PER_Persona": str(p.PER_Persona)})
    assert ok.status_code == 201, ok.text
    assert [s["SED_Sede"] for s in ok.json()["sedes"]] == [sede]
    assert ok.json()["USU_Debe_Cambiar_Password"] is True
    # …pero no otorgar roles protegidos.
    for role in ("SUPER_ADMIN", "ADMIN_SEGURIDAD"):
        r = await client.patch(f"/api/v1/org/usuarios/{tec.USU_Usuario}", headers=h, json={"USU_Rol": role})
        assert r.status_code == 403 and r.json()["detail"] == "ONLY_SUPER_ADMIN_CAN_GRANT_ADMIN_ROLES"
    # No administra a un par ni al super admin.
    for target in (par.USU_Usuario, sa_user.USU_Usuario):
        for path in ("password/reset", "2fa/reset", "unlock", "sessions/revoke"):
            r = await client.post(f"/api/v1/org/usuarios/{target}/{path}", headers=h)
            assert r.status_code == 403, (path, r.text)
    # Ni a sí mismo por la vía administrativa.
    me = (await session.execute(select(Usuario).where(Usuario.USU_Username == "seg_a"))).scalar_one()
    r = await client.post(f"/api/v1/org/usuarios/{me.USU_Usuario}/password/reset", headers=h)
    assert r.json()["detail"] == "CANNOT_MODIFY_OWN_ACCOUNT"
    # El SUPER_ADMIN sí gestiona al administrador de seguridad.
    r = await client.post(f"/api/v1/org/usuarios/{par.USU_Usuario}/sessions/revoke", headers=auth_headers)
    assert r.status_code == 200


# =========================================================================
# Contraseña temporal con cambio obligatorio
# =========================================================================
@pytest.mark.asyncio
async def test_reset_password_temporal_y_cambio_obligatorio(client, session, sa_user):
    await _mk_user(session, "seg_r", "ADMIN_SEGURIDAD")
    tec, _ = await _mk_user(session, "tec_r", "TECNICO")
    h = await _headers(client, "seg_r")
    tec_session = await _headers(client, "tec_r")

    r = await client.post(f"/api/v1/org/usuarios/{tec.USU_Usuario}/password/reset", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    temporal = r.json()["temporary_password"]
    validate_password_policy(temporal, username="tec_r")  # cumple la política

    # La sesión previa del titular quedó cerrada y la contraseña anterior ya no sirve.
    assert (await client.get("/api/v1/core/activos", headers=tec_session)).status_code == 401
    assert "access_token" not in await _login(client, "tec_r")

    # Con la temporal entra, pero restringido: solo puede cambiarla.
    body = await _login(client, "tec_r", temporal)
    assert body["restriction"] == "PASSWORD_CHANGE_REQUIRED"
    restricted = _h(body["access_token"])
    assert (await client.get("/api/v1/core/activos", headers=restricted)).json()["detail"] == "PASSWORD_CHANGE_REQUIRED"
    assert (await client.get("/api/v1/me", headers=restricted)).status_code == 200
    ch = await client.post("/api/v1/me/password", headers=restricted,
                           json={"current_password": temporal, "new_password": "PropiaNueva#2026"})
    assert ch.status_code == 204, ch.text

    body = await _login(client, "tec_r", "PropiaNueva#2026")
    assert body["restriction"] is None
    assert (await client.get("/api/v1/core/activos", headers=_h(body["access_token"]))).status_code == 200

    audit = (await session.execute(select(AuditoriaSistema).where(
        AuditoriaSistema.AUD_Accion == "PASSWORD_RESET_BY_ADMIN"))).scalars().all()
    assert len(audit) == 1 and temporal not in str(audit[0].AUD_Snapshot_JSON)


@pytest.mark.asyncio
async def test_unlock_y_cierre_de_sesiones(client, session, sa_user, auth_headers):
    tec, _ = await _mk_user(session, "tec_l", "TECNICO")
    for _ in range(settings.ACCOUNT_LOCKOUT_THRESHOLD):
        await client.post("/api/v1/login/access-token", data={"username": "tec_l", "password": "mala"}, headers=FORM)
    r = await client.post("/api/v1/login/access-token", data={"username": "tec_l", "password": PWD}, headers=FORM)
    assert r.status_code == 429 and r.json()["detail"] == "ACCOUNT_LOCKED"

    resumen = (await client.get("/api/v1/org/usuarios/seguridad/resumen", headers=auth_headers)).json()
    assert resumen["bloqueados"] == 1

    assert (await client.post(f"/api/v1/org/usuarios/{tec.USU_Usuario}/unlock", headers=auth_headers)).status_code == 200
    h = await _headers(client, "tec_l")
    assert (await client.post(f"/api/v1/org/usuarios/{tec.USU_Usuario}/sessions/revoke",
                              headers=auth_headers)).status_code == 200
    assert (await client.get("/api/v1/core/activos", headers=h)).status_code == 401


# =========================================================================
# MFA obligatorio por rol
# =========================================================================
@pytest.mark.asyncio
async def test_mfa_obligatorio_restringe_hasta_enrolar(client, session, sa_user, monkeypatch):
    monkeypatch.setattr(settings, "TWO_FACTOR_REQUIRED_ROLES", "SUPER_ADMIN,ADMIN_SEGURIDAD,ADMIN_TI")
    await _mk_user(session, "ti_mfa", "ADMIN_TI")
    body = await _login(client, "ti_mfa")
    assert body["restriction"] == "MFA_ENROLLMENT_REQUIRED"
    h = _h(body["access_token"])
    assert (await client.get("/api/v1/core/activos", headers=h)).json()["detail"] == "MFA_ENROLLMENT_REQUIRED"

    secret = (await client.post("/api/v1/me/2fa/totp/setup", headers=h)).json()["secret"]
    act = await client.post("/api/v1/me/2fa/totp/activate", headers=h, json={"code": pyotp.TOTP(secret).now()})
    assert act.status_code == 200, act.text

    # El refresh recalcula las restricciones desde la BD: sesión completa.
    rf = await client.post("/api/v1/login/refresh")
    assert rf.status_code == 200, rf.text
    assert rf.json()["restriction"] is None
    assert (await client.get("/api/v1/core/activos", headers=_h(rf.json()["access_token"]))).status_code == 200


@pytest.mark.asyncio
async def test_codigos_2fa_fallidos_bloquean_la_cuenta(client, session, sa_user):
    secret = pyotp.random_base32()
    await _mk_user(session, "tec_2fa", "TECNICO", mfa_secret=secret)
    for i in range(settings.ACCOUNT_LOCKOUT_THRESHOLD):
        # Repetir la contraseña NO reinicia el contador del segundo factor.
        challenge = (await _login(client, "tec_2fa"))["challenge_token"]
        r = await client.post("/api/v1/login/2fa/verify", json={"challenge_token": challenge, "code": "000000"})
    assert r.status_code == 429 and r.json()["detail"] == "ACCOUNT_LOCKED"
    # Bloqueada: ni siquiera el código correcto entra.
    r = await client.post("/api/v1/login/access-token", data={"username": "tec_2fa", "password": PWD}, headers=FORM)
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_sso_no_queda_restringido(client, session, sa_user, monkeypatch):
    """Las cuentas SSO delegan contraseña y MFA en el proveedor de identidad."""
    from app.services.session_policy import session_claims
    monkeypatch.setattr(settings, "TWO_FACTOR_REQUIRED_ROLES", "ADMIN_TI")
    usu, _ = await _mk_user(session, "sso_ti", "ADMIN_TI", must_change=True)
    assert session_claims(usu, via_sso=True) == {"amr": "sso"}
    assert session_claims(usu) == {"pwd_change": True, "mfa_enroll": True}
