"""
Módulo de seguridad: sesiones activas, aviso de dispositivo nuevo, historial y
listas de bloqueo de contraseñas, desactivación de cuentas inactivas y
retención de la bitácora.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import PasswordPolicyError, validate_password_policy
from app.models.governance import AuditoriaSistema, Sesion
from app.models.organization import Usuario

FORM = {"Content-Type": "application/x-www-form-urlencoded"}
SA_PWD = "TestPassw0rd!"
UA_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
UA_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def capture_emails(monkeypatch):
    sent = []

    async def fake_send(template_name, ctx, to=(), cc_admins=True, **kw):
        sent.append({"template": template_name, "ctx": ctx, "to": list(to), "cc_admins": cc_admins})

    monkeypatch.setattr("app.core.email.send_notification", fake_send)
    return sent


async def _login(client, ua=UA_WIN, password=SA_PWD):
    r = await client.post("/api/v1/login/access-token", data={"username": "sa", "password": password},
                          headers={**FORM, "User-Agent": ua})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Sesiones
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_listar_y_cerrar_una_sesion(client, sa_user):
    h1 = await _login(client, UA_WIN)
    client.cookies.clear()
    h2 = await _login(client, UA_MAC)

    sesiones = (await client.get("/api/v1/me/sessions", headers=h2)).json()
    assert len(sesiones) == 2
    actual = [s for s in sesiones if s["actual"]]
    assert len(actual) == 1 and actual[0]["dispositivo"] == "Safari · macOS"
    otra = next(s for s in sesiones if not s["actual"])

    assert (await client.delete(f"/api/v1/me/sessions/{otra['id']}", headers=h2)).status_code == 204
    # El access de la sesión cerrada deja de valer de inmediato; la otra sigue.
    assert (await client.get("/api/v1/me", headers=h1)).status_code == 401
    assert (await client.get("/api/v1/me", headers=h2)).status_code == 200
    assert len((await client.get("/api/v1/me/sessions", headers=h2)).json()) == 1


@pytest.mark.asyncio
async def test_no_se_cierra_sesion_ajena(client, sa_user, session):
    h = await _login(client)
    otra = Sesion(USU_Usuario=sa_user.USU_Usuario, SES_Expira=_now() + timedelta(hours=1))
    session.add(otra)
    await session.commit()
    import uuid
    assert (await client.delete(f"/api/v1/me/sessions/{uuid.uuid4()}", headers=h)).status_code == 404


@pytest.mark.asyncio
async def test_aviso_de_dispositivo_nuevo(client, sa_user, session, capture_emails):
    await _login(client, UA_WIN)          # primer inicio: no hay con qué comparar
    await _login(client, UA_WIN)          # mismo dispositivo
    assert not [e for e in capture_emails if e["template"] == "nuevo_dispositivo"]
    await _login(client, UA_MAC)          # dispositivo nuevo
    avisos = [e for e in capture_emails if e["template"] == "nuevo_dispositivo"]
    assert len(avisos) == 1
    assert avisos[0]["to"] == ["admin@test.local"] and avisos[0]["cc_admins"] is False
    assert avisos[0]["ctx"]["dispositivo"] == "Safari · macOS"
    eventos = (await session.execute(
        select(AuditoriaSistema).where(AuditoriaSistema.AUD_Accion == "LOGIN_NEW_DEVICE"))).scalars().all()
    assert len(eventos) == 1


@pytest.mark.asyncio
async def test_panel_de_sesiones_para_seguridad(client, sa_user, auth_headers):
    todas = (await client.get("/api/v1/org/usuarios/seguridad/sesiones", headers=auth_headers)).json()
    assert todas and todas[0]["username"] == "sa"
    resumen = (await client.get("/api/v1/org/usuarios/seguridad/resumen", headers=auth_headers)).json()
    assert resumen["sesiones_activas"] >= 1
    assert resumen["politica"]["password_historial"] == 5


# ---------------------------------------------------------------------------
# Contraseñas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pwd,code", [
    ("Verano2026!", "too_common"),
    ("P@ssw0rd2026", "too_common"),
    ("Lombardi#2026x", "contains_blocked_word"),
    ("Kx7!aaaa#Qz", "repeated_chars"),
    ("Kx7!1234#Qz", "sequential_chars"),
    ("Kx7!qwer#Qz9", "sequential_chars"),
])
def test_lista_de_bloqueo(pwd, code):
    with pytest.raises(PasswordPolicyError) as exc:
        validate_password_policy(pwd, username="usuario")
    assert code in str(exc.value)


def test_datos_personales_y_contrasena_valida():
    with pytest.raises(PasswordPolicyError) as exc:
        validate_password_policy("Martinez#Kx7Q", username="jm", personal_data=["Juan", "Martinez"])
    assert "contains_personal_data" in str(exc.value)
    validate_password_policy("Kx7!Rotacion#Q", username="jm", personal_data=["Juan", "Martinez"])


@pytest.mark.asyncio
async def test_historial_impide_reutilizar(client, sa_user):
    h = await _login(client)
    anteriores = [SA_PWD, "Kx7!Primera#Q", "Kx7!Segunda#Q"]
    for actual, nueva in zip(anteriores, anteriores[1:]):
        r = await client.post("/api/v1/me/password", headers=h,
                              json={"current_password": actual, "new_password": nueva})
        assert r.status_code == 204, r.text
        h = await _login(client, password=nueva)
    # La actual y las anteriores no se aceptan.
    r = await client.post("/api/v1/me/password", headers=h,
                          json={"current_password": "Kx7!Segunda#Q", "new_password": "Kx7!Segunda#Q"})
    assert r.json()["detail"] == "PASSWORD_SAME_AS_OLD"
    r = await client.post("/api/v1/me/password", headers=h,
                          json={"current_password": "Kx7!Segunda#Q", "new_password": "Kx7!Primera#Q"})
    assert r.status_code == 400 and r.json()["detail"] == "PASSWORD_REUSED:5"
    r = await client.post("/api/v1/me/password", headers=h,
                          json={"current_password": "Kx7!Segunda#Q", "new_password": "Kx7!Tercera#Q"})
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_contrasena_con_nombre_del_titular(client, sa_user):
    h = await _login(client)
    r = await client.post("/api/v1/me/password", headers=h,
                          json={"current_password": SA_PWD, "new_password": "System#Kx7Q9"})
    assert r.status_code == 400 and "contains_personal_data" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Tareas periódicas
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_desactiva_cuentas_inactivas_menos_el_ultimo_super_admin(session, sa_user, capture_emails):
    from app.core.security import get_password_hash
    from app.models.organization import Persona
    from app.services.security_jobs import disable_inactive_accounts

    per = Persona(PER_Primer_Nombre="Ina", PER_Primer_Apellido="Ctivo", PER_Email_Corporativo="ina@test.local",
                  DEP_Departamento=(await session.get(Persona, sa_user.PER_Persona)).DEP_Departamento,
                  CAR_Cargo=(await session.get(Persona, sa_user.PER_Persona)).CAR_Cargo)
    session.add(per)
    await session.flush()
    viejo = _now() - timedelta(days=400)
    session.add(Usuario(USU_Username="inactivo", USU_Password_Hash=get_password_hash("Kx7!Inact#Q"),
                        USU_Rol="CONSULTA", PER_Persona=per.PER_Persona, USU_Ultimo_Login=viejo,
                        USU_Alcance_Global=True))
    sa = await session.get(Usuario, sa_user.USU_Usuario)
    sa.USU_Ultimo_Login = viejo
    await session.commit()

    desactivados = await disable_inactive_accounts(session)
    assert desactivados == ["inactivo"]  # el único SUPER_ADMIN se conserva
    session.expire_all()
    assert (await session.execute(select(Usuario.USU_Estado).where(Usuario.USU_Username == "inactivo"))).scalar_one() is False
    assert (await session.execute(select(Usuario.USU_Estado).where(Usuario.USU_Username == "sa"))).scalar_one() is True
    assert [e["template"] for e in capture_emails] == ["cuenta_desactivada_inactividad"]


@pytest.mark.asyncio
async def test_retencion_de_auditoria(session, sa_user, monkeypatch):
    from app.services.security_jobs import apply_audit_retention

    viejo = _now() - timedelta(days=800)
    session.add_all([
        AuditoriaSistema(AUD_Accion="UPDATE", AUD_Entidad_Afectada="INV_ACTIVO", AUD_Fecha_Hora=viejo),
        AuditoriaSistema(AUD_Accion="UPDATE", AUD_Entidad_Afectada="INV_ACTIVO"),
    ])
    await session.commit()
    monkeypatch.setattr("app.core.config.settings.AUDIT_RETENTION_DAYS", 30)  # se aplica el mínimo: 365
    assert await apply_audit_retention(session) == 1
    acciones = (await session.execute(select(AuditoriaSistema.AUD_Accion))).scalars().all()
    assert "AUDIT_RETENTION_PURGE" in acciones and acciones.count("UPDATE") == 1
