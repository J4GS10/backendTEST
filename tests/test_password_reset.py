"""Tests del restablecimiento de contraseña por email y del invariante de super admin."""
import pytest


@pytest.fixture
def capture_emails(monkeypatch):
    """Intercepta send_notification para capturar el contexto (incluye el token)."""
    sent = []

    async def fake_send(template_name, ctx, to=(), cc_admins=True, **kw):
        sent.append({"template": template_name, "ctx": ctx, "to": list(to), "cc_admins": cc_admins})

    monkeypatch.setattr("app.core.email.send_notification", fake_send)
    return sent


@pytest.mark.asyncio
async def test_reset_flow_completo(client, sa_user, capture_emails):
    # 1. Solicitar reset por username -> 202 (respuesta genérica)
    r = await client.post("/api/v1/login/password-reset/request", json={"identifier": "sa"})
    assert r.status_code == 202

    # 2. El email se envió SOLO al correo del usuario, no a admins.
    assert len(capture_emails) == 1
    ev = capture_emails[0]
    assert ev["template"] == "password_reset"
    assert ev["cc_admins"] is False
    assert ev["to"] == ["admin@test.local"]
    token = ev["ctx"]["token"]
    assert token and len(token) > 20

    # 3. Confirmar con el token -> 204
    c = await client.post("/api/v1/login/password-reset/confirm",
                          json={"token": token, "new_password": "NuevaClave#2026"})
    assert c.status_code == 204, c.text

    # 4. Login con la nueva contraseña -> 200; con la vieja -> 400.
    ok = await client.post("/api/v1/login/access-token",
                           data={"username": "sa", "password": "NuevaClave#2026"},
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert ok.status_code == 200, ok.text
    bad = await client.post("/api/v1/login/access-token",
                            data={"username": "sa", "password": "TestPassw0rd!"},
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_reset_anti_enumeracion(client, sa_user, capture_emails):
    """Cuenta inexistente: misma respuesta 202 y NO se envía email."""
    r = await client.post("/api/v1/login/password-reset/request",
                          json={"identifier": "no_existe_jamas"})
    assert r.status_code == 202
    assert len(capture_emails) == 0


@pytest.mark.asyncio
async def test_reset_token_invalido(client, sa_user):
    r = await client.post("/api/v1/login/password-reset/confirm",
                          json={"token": "token_basura_que_no_existe", "new_password": "NuevaClave#2026"})
    assert r.status_code == 400
    assert r.json()["detail"] == "INVALID_OR_EXPIRED_RESET_TOKEN"


@pytest.mark.asyncio
async def test_reset_token_un_solo_uso(client, sa_user, capture_emails):
    await client.post("/api/v1/login/password-reset/request", json={"identifier": "sa"})
    token = capture_emails[0]["ctx"]["token"]
    a = await client.post("/api/v1/login/password-reset/confirm",
                          json={"token": token, "new_password": "NuevaClave#2026"})
    assert a.status_code == 204
    # Reusar el mismo token -> 400 (ya usado).
    b = await client.post("/api/v1/login/password-reset/confirm",
                          json={"token": token, "new_password": "OtraClave#2026"})
    assert b.status_code == 400


@pytest.mark.asyncio
async def test_reset_solicitar_invalida_token_anterior(client, sa_user, capture_emails):
    """Pedir un segundo reset invalida el primer token (1 activo a la vez)."""
    await client.post("/api/v1/login/password-reset/request", json={"identifier": "sa"})
    token1 = capture_emails[0]["ctx"]["token"]
    await client.post("/api/v1/login/password-reset/request", json={"identifier": "sa"})
    token2 = capture_emails[1]["ctx"]["token"]
    assert token1 != token2
    # El primer token ya no sirve.
    r1 = await client.post("/api/v1/login/password-reset/confirm",
                           json={"token": token1, "new_password": "NuevaClave#2026"})
    assert r1.status_code == 400
    # El segundo sí.
    r2 = await client.post("/api/v1/login/password-reset/confirm",
                           json={"token": token2, "new_password": "NuevaClave#2026"})
    assert r2.status_code == 204


# =====================================================================
# #1 — Aviso de seguridad al usuario cuando su contraseña cambia
# =====================================================================
@pytest.mark.asyncio
async def test_reset_confirm_avisa_al_usuario(client, sa_user, capture_emails):
    await client.post("/api/v1/login/password-reset/request", json={"identifier": "sa"})
    token = capture_emails[0]["ctx"]["token"]
    r = await client.post("/api/v1/login/password-reset/confirm",
                          json={"token": token, "new_password": "NuevaClave#2026"})
    assert r.status_code == 204
    # Tras el reset hay un email "password_changed" al correo del usuario (no admins).
    avisos = [e for e in capture_emails if e["template"] == "password_changed"]
    assert len(avisos) == 1
    assert avisos[0]["to"] == ["admin@test.local"]
    assert avisos[0]["cc_admins"] is False
    assert avisos[0]["ctx"]["metodo"] == "Restablecimiento por email"


@pytest.mark.asyncio
async def test_cambio_password_autoservicio_avisa(client, auth_headers, sa_user, capture_emails):
    r = await client.post("/api/v1/me/password", headers=auth_headers,
                          json={"current_password": "TestPassw0rd!", "new_password": "NuevaClave#2026"})
    assert r.status_code == 204, r.text
    avisos = [e for e in capture_emails if e["template"] == "password_changed"]
    assert len(avisos) == 1
    assert avisos[0]["ctx"]["metodo"] == "Autoservicio (cambio manual)"


@pytest.mark.asyncio
async def test_cambio_password_por_admin_avisa_al_dueno(client, auth_headers, domain_seed, session, capture_emails):
    """Un admin cambia la clave de otro usuario -> se avisa al DUEÑO."""
    import uuid
    from sqlalchemy import select
    from app.models.organization import Persona
    alice = (await session.execute(
        select(Persona).where(Persona.PER_Persona == uuid.UUID(domain_seed["alice"])))).scalar_one()
    p = Persona(PER_Primer_Nombre="Avi", PER_Primer_Apellido="Sado",
                PER_Email_Corporativo="avi@example.com",
                DEP_Departamento=alice.DEP_Departamento, CAR_Cargo=alice.CAR_Cargo)
    session.add(p); await session.commit()
    cr = await client.post("/api/v1/org/usuarios", headers=auth_headers, json={
        "USU_Username": "avi_user", "USU_Password": "Inicial#2026",
        "USU_Rol": "TECNICO", "PER_Persona": str(p.PER_Persona)})
    uid = cr.json()["USU_Usuario"]
    capture_emails.clear()
    r = await client.patch(f"/api/v1/org/usuarios/{uid}", headers=auth_headers,
                           json={"USU_Password": "Cambiada#2026"})
    assert r.status_code == 200, r.text
    avisos = [e for e in capture_emails if e["template"] == "password_changed"]
    assert len(avisos) == 1
    assert avisos[0]["to"] == ["avi@example.com"]
    assert avisos[0]["ctx"]["metodo"] == "Cambio por administrador"


# =====================================================================
# #2 — Throttle por cuenta de solicitudes de reset (anti-bombardeo)
# =====================================================================
@pytest.mark.asyncio
async def test_reset_throttle_por_cuenta(client, sa_user, capture_emails, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "PASSWORD_RESET_REQUEST_COOLDOWN_MINUTES", 5)
    # 1ª solicitud: envía email.
    r1 = await client.post("/api/v1/login/password-reset/request", json={"identifier": "sa"})
    assert r1.status_code == 202
    # 2ª solicitud inmediata: misma respuesta 202 pero NO envía otro email.
    r2 = await client.post("/api/v1/login/password-reset/request", json={"identifier": "sa"})
    assert r2.status_code == 202
    resets = [e for e in capture_emails if e["template"] == "password_reset"]
    assert len(resets) == 1  # throttled: solo un correo


# =====================================================================
# INVARIANTE: el sistema nunca se queda sin un SUPER_ADMIN activo
# =====================================================================
@pytest.mark.asyncio
async def test_no_se_puede_desactivar_el_ultimo_super_admin(client, auth_headers, sa_user, session):
    import uuid
    from sqlalchemy import select
    from app.models.organization import Usuario
    sa = (await session.execute(select(Usuario).where(Usuario.USU_Username == "sa"))).scalar_one()
    sid = str(sa.USU_Usuario)

    # Desactivar (DELETE lógico) al único super admin -> 400.
    d = await client.delete(f"/api/v1/org/usuarios/{sid}", headers=auth_headers)
    assert d.status_code == 400
    assert d.json()["detail"] == "CANNOT_DISABLE_LAST_SUPER_ADMIN"

    # Degradar de rol al único super admin -> 400.
    p = await client.patch(f"/api/v1/org/usuarios/{sid}", headers=auth_headers,
                           json={"USU_Rol": "TECNICO"})
    assert p.status_code == 400
    assert p.json()["detail"] == "CANNOT_DISABLE_LAST_SUPER_ADMIN"

    # Sigue activo y SUPER_ADMIN.
    await session.refresh(sa)
    assert sa.USU_Estado is True and sa.USU_Rol == "SUPER_ADMIN"
