"""Tests de 2FA: enrolamiento TOTP/Email, login en dos pasos, recovery, desactivar."""
import pyotp
import pytest

FORM = {"Content-Type": "application/x-www-form-urlencoded"}
SA_LOGIN = {"username": "sa", "password": "TestPassw0rd!"}


@pytest.fixture
def capture_emails(monkeypatch):
    sent = []

    async def fake_send(template_name, ctx, to=(), cc_admins=True, **kw):
        sent.append({"template": template_name, "ctx": ctx, "to": list(to)})

    monkeypatch.setattr("app.core.email.send_notification", fake_send)
    return sent


async def _login_step1(client):
    return (await client.post("/api/v1/login/access-token", data=SA_LOGIN, headers=FORM)).json()


@pytest.mark.asyncio
async def test_totp_enrolamiento_y_login(client, auth_headers, sa_user):
    st = await client.get("/api/v1/me/2fa", headers=auth_headers)
    assert st.json() == {"habilitado": False, "metodo": None, "requerido": True}  # SUPER_ADMIN

    setup = await client.post("/api/v1/me/2fa/totp/setup", headers=auth_headers)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["qr_data_uri"].startswith("data:image/png;base64,")

    act = await client.post("/api/v1/me/2fa/totp/activate", headers=auth_headers,
                            json={"code": pyotp.TOTP(secret).now()})
    assert act.status_code == 200, act.text
    assert len(act.json()["recovery_codes"]) == 8

    # Ahora el login pide 2FA en vez de entregar tokens.
    body = await _login_step1(client)
    assert body.get("requires_2fa") is True and body["method"] == "TOTP"
    assert "access_token" not in body
    challenge = body["challenge_token"]

    bad = await client.post("/api/v1/login/2fa/verify",
                            json={"challenge_token": challenge, "code": "000000"})
    assert bad.status_code == 400

    ok = await client.post("/api/v1/login/2fa/verify",
                           json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200 and "access_token" in ok.json()


@pytest.mark.asyncio
async def test_email_enrolamiento_y_login(client, auth_headers, sa_user, capture_emails):
    s = await client.post("/api/v1/me/2fa/email/setup", headers=auth_headers)
    assert s.status_code == 202
    code = [e for e in capture_emails if e["template"] == "2fa_code"][-1]["ctx"]["code"]
    act = await client.post("/api/v1/me/2fa/email/activate", headers=auth_headers, json={"code": code})
    assert act.status_code == 200, act.text

    capture_emails.clear()
    body = await _login_step1(client)
    assert body.get("requires_2fa") is True and body["method"] == "EMAIL"
    challenge = body["challenge_token"]
    login_code = [e for e in capture_emails if e["template"] == "2fa_code"][-1]["ctx"]["code"]
    # El correo del OTP va SOLO al usuario.
    assert capture_emails[-1]["to"] == ["admin@test.local"]

    vr = await client.post("/api/v1/login/2fa/verify",
                           json={"challenge_token": challenge, "code": login_code})
    assert vr.status_code == 200 and "access_token" in vr.json()


@pytest.mark.asyncio
async def test_codigo_de_recuperacion_un_solo_uso(client, auth_headers, sa_user):
    secret = (await client.post("/api/v1/me/2fa/totp/setup", headers=auth_headers)).json()["secret"]
    recovery = (await client.post("/api/v1/me/2fa/totp/activate", headers=auth_headers,
                                  json={"code": pyotp.TOTP(secret).now()})).json()["recovery_codes"]
    rc = recovery[0]

    ch1 = (await _login_step1(client))["challenge_token"]
    v1 = await client.post("/api/v1/login/2fa/verify", json={"challenge_token": ch1, "code": rc})
    assert v1.status_code == 200

    ch2 = (await _login_step1(client))["challenge_token"]
    v2 = await client.post("/api/v1/login/2fa/verify", json={"challenge_token": ch2, "code": rc})
    assert v2.status_code == 400  # ya usado


@pytest.mark.asyncio
async def test_disable_bloqueado_para_rol_obligatorio(client, auth_headers, sa_user):
    secret = (await client.post("/api/v1/me/2fa/totp/setup", headers=auth_headers)).json()["secret"]
    await client.post("/api/v1/me/2fa/totp/activate", headers=auth_headers,
                      json={"code": pyotp.TOTP(secret).now()})
    r = await client.post("/api/v1/me/2fa/disable", headers=auth_headers,
                          json={"password": "TestPassw0rd!"})
    assert r.status_code == 403
    assert r.json()["detail"] == "2FA_REQUIRED_FOR_THIS_ROLE"


@pytest.mark.asyncio
async def test_disable_exitoso_rol_no_obligatorio(client, auth_headers, sa_user, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "TWO_FACTOR_REQUIRED_ROLES", "")
    secret = (await client.post("/api/v1/me/2fa/totp/setup", headers=auth_headers)).json()["secret"]
    await client.post("/api/v1/me/2fa/totp/activate", headers=auth_headers,
                      json={"code": pyotp.TOTP(secret).now()})

    bad = await client.post("/api/v1/me/2fa/disable", headers=auth_headers, json={"password": "incorrecta"})
    assert bad.status_code == 400
    ok = await client.post("/api/v1/me/2fa/disable", headers=auth_headers, json={"password": "TestPassw0rd!"})
    assert ok.status_code == 204
    st = await client.get("/api/v1/me/2fa", headers=auth_headers)
    assert st.json()["habilitado"] is False


@pytest.mark.asyncio
async def test_admin_reset_2fa_de_usuario(client, auth_headers, sa_user):
    """Un SUPER_ADMIN puede resetear el 2FA de un usuario (aquí, de sí mismo)."""
    secret = (await client.post("/api/v1/me/2fa/totp/setup", headers=auth_headers)).json()["secret"]
    await client.post("/api/v1/me/2fa/totp/activate", headers=auth_headers,
                      json={"code": pyotp.TOTP(secret).now()})
    assert (await client.get("/api/v1/me/2fa", headers=auth_headers)).json()["habilitado"] is True

    r = await client.post(
        f"/api/v1/org/usuarios/{sa_user.USU_Usuario}/2fa/reset", headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    st = (await client.get("/api/v1/me/2fa", headers=auth_headers)).json()
    assert st["habilitado"] is False and st["metodo"] is None


@pytest.mark.asyncio
async def test_admin_reset_2fa_requiere_super_admin(client, session, sa_user):
    """Un usuario no SUPER_ADMIN no puede resetear el 2FA de otro (403)."""
    from app.core.security import get_password_hash
    from app.models.organization import Cargo, Departamento, Persona, Usuario

    dep = Departamento(DEP_Nombre="Soporte")
    car = Cargo(CAR_Nombre="Tecnico")
    session.add_all([dep, car])
    await session.flush()
    per = Persona(
        PER_Primer_Nombre="Tec", PER_Primer_Apellido="Uno",
        PER_Email_Corporativo="tec@test.local",
        DEP_Departamento=dep.DEP_Departamento, CAR_Cargo=car.CAR_Cargo,
    )
    session.add(per)
    await session.flush()
    session.add(Usuario(
        USU_Username="tec1", USU_Password_Hash=get_password_hash("TestPassw0rd!"),
        USU_Rol="TECNICO", PER_Persona=per.PER_Persona,
    ))
    await session.commit()

    tok = (await client.post(
        "/api/v1/login/access-token",
        data={"username": "tec1", "password": "TestPassw0rd!"}, headers=FORM,
    )).json()["access_token"]
    r = await client.post(
        f"/api/v1/org/usuarios/{sa_user.USU_Usuario}/2fa/reset",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_verify_sin_2fa_o_challenge_invalido(client, sa_user):
    r = await client.post("/api/v1/login/2fa/verify",
                          json={"challenge_token": "token.basura.invalido", "code": "123456"})
    assert r.status_code == 401
