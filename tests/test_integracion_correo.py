"""
Cuenta de servicio genérica (correo + AD) configurable desde la UI:
prioridad UI > entorno, secretos cifrados y nunca expuestos, pruebas con
valores sin guardar, transporte Graph y cortacircuitos de autenticación.
"""
import json

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import config as cfg_mod
from app.core import email as email_mod
from app.core import security
from app.models.governance import AuditoriaSistema, EmailOutbox, IntegracionCorreo
from app.services import email_outbox, integration_config as ic

URL = "/api/v1/directorio/integracion"

SMTP_BODY = {
    "modo": "CORREO", "proveedor": "SMTP",
    "cuenta_email": "inventario@empresa.com", "cuenta_password": "Cl4ve-Servicio!",
    "nombre_remitente": "Inventario TI",
    "smtp_host": "mail.empresa.local", "smtp_puerto": 587, "smtp_seguridad": "STARTTLS",
}


@pytest.fixture
def fernet_key(monkeypatch):
    monkeypatch.setattr(cfg_mod.settings, "FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(security, "_fernet", None)
    yield
    security._fernet = None


# =========================================================================
# API: lectura / guardado
# =========================================================================
@pytest.mark.asyncio
async def test_sin_configurar_usa_entorno_y_no_expone_secretos(client, auth_headers, monkeypatch):
    monkeypatch.setattr(cfg_mod.settings, "SMTP_PASSWORD", "secreto-env")
    r = await client.get(URL, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["origen"] == "entorno"
    assert body["password_configurada"] is True
    assert "secreto-env" not in r.text
    assert not any(k in body for k in ("cuenta_password", "graph_client_secret", "ad_bind_password"))


@pytest.mark.asyncio
async def test_guardar_cifra_clave_y_la_config_prevalece(client, auth_headers, session, fernet_key):
    r = await client.put(URL, json=SMTP_BODY, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["origen"] == "interfaz" and body["password_configurada"] is True
    assert "Cl4ve-Servicio!" not in r.text

    row = await session.get(IntegracionCorreo, 1)
    assert row.INT_Cuenta_Password_Enc and "Cl4ve-Servicio!" not in row.INT_Cuenta_Password_Enc
    assert security.decrypt_field(row.INT_Cuenta_Password_Enc) == "Cl4ve-Servicio!"

    # La config efectiva ahora sale de la UI (no de SMTP_HOST del entorno).
    eff = await ic.get_config(session)
    assert eff.source == "interfaz"
    assert (eff.mail.host, eff.mail.username, eff.mail.password) == (
        "mail.empresa.local", "inventario@empresa.com", "Cl4ve-Servicio!")
    assert eff.mail.from_email == "inventario@empresa.com"

    # La auditoría registra el cambio pero nunca el secreto.
    audit = (await session.execute(
        select(AuditoriaSistema).where(AuditoriaSistema.AUD_Entidad_Afectada == "SYS_INTEGRACION_CORREO")
    )).scalars().all()
    assert len(audit) == 1
    snap = json.dumps(audit[0].AUD_Snapshot_JSON)
    assert "Cl4ve-Servicio!" not in snap and "cuenta_password" in audit[0].AUD_Snapshot_JSON["secretos_modificados"]


@pytest.mark.asyncio
async def test_secreto_omitido_se_conserva_y_vacio_se_borra(client, auth_headers, session):
    await client.put(URL, json=SMTP_BODY, headers=auth_headers)
    sin_clave = {k: v for k, v in SMTP_BODY.items() if k != "cuenta_password"}
    r = await client.put(URL, json={**sin_clave, "smtp_puerto": 25}, headers=auth_headers)
    assert r.json()["password_configurada"] is True and r.json()["smtp_puerto"] == 25
    r = await client.put(URL, json={**sin_clave, "cuenta_password": ""}, headers=auth_headers)
    assert r.json()["password_configurada"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("cambio,error", [
    ({"smtp_host": None}, "SMTP_HOST_REQUERIDO"),
    ({"cuenta_email": None}, "CUENTA_EMAIL_REQUERIDA"),
    ({"proveedor": "GRAPH"}, "GRAPH_TENANT_Y_CLIENT_REQUERIDOS"),
    ({"modo": "CORREO_AD"}, "AD_SERVIDOR_Y_BASE_DN_REQUERIDOS"),
    ({"modo": "CORREO_AD", "ad_servidor": "dc01", "ad_base_dn": "DC=x"}, "AD_SERVIDOR_DEBE_SER_LDAP_O_LDAPS"),
    ({"smtp_puerto": 70000}, None),
])
async def test_validaciones(client, auth_headers, cambio, error):
    r = await client.put(URL, json={**SMTP_BODY, **cambio}, headers=auth_headers)
    assert r.status_code == 422
    if error:
        assert error in r.text


@pytest.mark.asyncio
async def test_modo_ad_usa_la_misma_cuenta_de_servicio(client, auth_headers, session):
    body = {**SMTP_BODY, "modo": "CORREO_AD", "ad_servidor": "ldaps://dc01.empresa.local",
            "ad_base_dn": "OU=Usuarios,DC=empresa,DC=local", "ad_usar_cuenta_servicio": True}
    assert (await client.put(URL, json=body, headers=auth_headers)).status_code == 200
    eff = await ic.get_config(session)
    assert eff.ad.ready
    assert (eff.ad.bind_user, eff.ad.bind_password) == ("inventario@empresa.com", "Cl4ve-Servicio!")

    # Cuenta distinta para el AD
    body.update(ad_usar_cuenta_servicio=False, ad_bind_usuario="EMPRESA\\svc_ldap", ad_bind_password="otra")
    await client.put(URL, json=body, headers=auth_headers)
    eff = await ic.get_config(session)
    assert (eff.ad.bind_user, eff.ad.bind_password) == ("EMPRESA\\svc_ldap", "otra")
    # Login SMTP con usuario distinto del email
    body["cuenta_usuario"] = "EMPRESA\\svc_inventario"
    await client.put(URL, json=body, headers=auth_headers)
    eff = await ic.get_config(session)
    assert eff.mail.username == "EMPRESA\\svc_inventario" and eff.mail.from_email == "inventario@empresa.com"


@pytest.mark.asyncio
async def test_desactivado_silencia_aunque_el_entorno_tenga_smtp(client, auth_headers, session, monkeypatch):
    monkeypatch.setattr(cfg_mod.settings, "SMTP_HOST", "smtp.env")
    assert (await ic.get_config(session)).mail.ready
    await client.put(URL, json={"modo": "DESACTIVADO"}, headers=auth_headers)
    assert not (await ic.get_config(session)).mail.ready


# =========================================================================
# Pruebas desde la UI (valores sin guardar)
# =========================================================================
@pytest.mark.asyncio
async def test_probar_correo_con_valores_sin_guardar(client, auth_headers, monkeypatch):
    seen = {}

    async def fake_smtp(cfg, to, subject, html, reply_to):
        seen.update(host=cfg.host, user=cfg.username, pwd=cfg.password, to=to)
    monkeypatch.setattr(email_mod, "_smtp_deliver", fake_smtp)
    r = await client.post(f"{URL}/probar-correo", json={"config": SMTP_BODY, "destinatario": "yo@empresa.com"},
                          headers=auth_headers)
    assert r.json()["ok"] is True
    assert seen == {"host": "mail.empresa.local", "user": "inventario@empresa.com",
                    "pwd": "Cl4ve-Servicio!", "to": ["yo@empresa.com"]}


@pytest.mark.asyncio
async def test_probar_correo_clave_incorrecta_no_bloquea(client, auth_headers, monkeypatch):
    async def bad_auth(*a, **k):
        raise email_mod.MailAuthError("535 5.7.3 Authentication unsuccessful")
    monkeypatch.setattr(email_mod, "_smtp_deliver", bad_auth)
    r = await client.post(f"{URL}/probar-correo", json={"config": SMTP_BODY, "destinatario": "yo@empresa.com"},
                          headers=auth_headers)
    assert r.json()["codigo"] == "AUTH_FAILED"
    # Una prueba manual no activa el cortacircuitos.
    assert await ic.breaker_until("smtp") is None


@pytest.mark.asyncio
async def test_probar_ad(client, auth_headers, monkeypatch):
    from app.integrations import active_directory as ad

    async def fake_ok(self):
        assert self.cfg.bind_user == "inventario@empresa.com" and self.use_breaker is False
        return 42
    monkeypatch.setattr(ad.LdapDirectoryClient, "test_connection", fake_ok)
    body = {**SMTP_BODY, "modo": "CORREO_AD", "ad_servidor": "ldaps://dc01", "ad_base_dn": "DC=empresa"}
    r = await client.post(f"{URL}/probar-ad", json={"config": body}, headers=auth_headers)
    assert r.json() == {"ok": True, "codigo": "OK", "mensaje": "Conexión correcta", "usuarios_encontrados": 42}

    async def fake_auth(self):
        raise ad.DirectoryAuthError("AD_AUTH_FAILED: LDAPInvalidCredentialsResult")
    monkeypatch.setattr(ad.LdapDirectoryClient, "test_connection", fake_auth)
    r = await client.post(f"{URL}/probar-ad", json={"config": body}, headers=auth_headers)
    assert r.json()["codigo"] == "AUTH_FAILED"


# =========================================================================
# Cortacircuitos de autenticación
# =========================================================================
@pytest.mark.asyncio
async def test_clave_mala_pausa_la_cola_sin_gastar_intentos(engine, sa_user, monkeypatch, client, auth_headers):
    import app.db.session as db_session
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    monkeypatch.setattr(cfg_mod.settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(cfg_mod.settings, "NOTIFY_ADMIN_EMAILS", "ops@x.com")
    calls = []

    async def bad_auth(*a, **k):
        calls.append(1)
        raise email_mod.MailAuthError("535 bad credentials")
    monkeypatch.setattr(email_mod, "_smtp_deliver", bad_auth)

    for i in range(3):
        await email_mod.send_notification("stock_bajo", {"codigo": f"T-{i}"}, to=())
    await email_outbox.process_due(factory)
    # Solo UN intento con la clave mala; el resto espera (protege la cuenta del bloqueo del AD).
    assert len(calls) == 1
    assert await ic.breaker_until("smtp") is not None
    async with factory() as db:
        rows = (await db.execute(select(EmailOutbox))).scalars().all()
    assert all(r.EOB_Estado == "PENDIENTE" for r in rows)
    assert sum(r.EOB_Intentos for r in rows) == 0  # el fallo de credenciales no consume intentos
    assert await email_outbox.process_due(factory) == 0

    r = await client.get(URL, headers=auth_headers)
    assert r.json()["bloqueo"]["smtp_hasta"] is not None
    assert (await client.post(f"{URL}/desbloquear", headers=auth_headers)).status_code == 204
    assert await ic.breaker_until("smtp") is None


@pytest.mark.asyncio
async def test_ldap_clave_mala_activa_cortacircuitos():
    from app.integrations.active_directory import DirectoryAuthError, LdapDirectoryClient
    client = LdapDirectoryClient(ic.AdConfig(enabled=True, servers=("ldaps://dc",), base_dn="DC=x", bind_user="u"))
    binds = []

    def failing_paged(*a):
        binds.append(1)
        raise DirectoryAuthError("AD_AUTH_FAILED")
    client._paged = failing_paged
    with pytest.raises(DirectoryAuthError):
        await client.list_users()
    with pytest.raises(DirectoryAuthError, match="AD_AUTH_PAUSED"):
        await client.list_users()
    assert len(binds) == 1  # el segundo intento ni siquiera hizo bind


# =========================================================================
# Microsoft Graph
# =========================================================================
def _graph_cfg():
    return ic.MailConfig(enabled=True, provider="GRAPH", from_email="inventario@empresa.com",
                         graph_tenant_id="tenant", graph_client_id="app", graph_client_secret="s3cr3t")


def _mock_httpx(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    email_mod._graph_token.clear()


@pytest.mark.asyncio
async def test_graph_envia_con_token_de_aplicacion(monkeypatch):
    sent = {}

    def handler(request: httpx.Request):
        if "login.microsoftonline.com/tenant/oauth2/v2.0/token" in str(request.url):
            assert b"client_secret=s3cr3t" in request.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        sent["url"] = str(request.url)
        sent["auth"] = request.headers["authorization"]
        sent["body"] = json.loads(request.content)
        return httpx.Response(202)
    _mock_httpx(monkeypatch, handler)
    await email_mod.deliver_with_config(_graph_cfg(), ["a@x.com"], "Asunto", "<p>hola</p>", "r@x.com")
    assert sent["url"] == "https://graph.microsoft.com/v1.0/users/inventario@empresa.com/sendMail"
    assert sent["auth"] == "Bearer tok"
    msg = sent["body"]["message"]
    assert msg["toRecipients"] == [{"emailAddress": {"address": "a@x.com"}}]
    assert msg["body"]["contentType"] == "HTML" and sent["body"]["saveToSentItems"] is False


@pytest.mark.asyncio
async def test_graph_sin_permiso_es_error_de_autenticacion(monkeypatch):
    def handler(request):
        if "token" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}})
    _mock_httpx(monkeypatch, handler)
    with pytest.raises(email_mod.MailAuthError):
        await email_mod.deliver_with_config(_graph_cfg(), ["a@x.com"], "s", "h", use_breaker=False)


@pytest.mark.asyncio
async def test_graph_secreto_invalido(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "invalid_client", "error_description": "AADSTS7000215"})
    _mock_httpx(monkeypatch, handler)
    with pytest.raises(email_mod.MailAuthError, match="AADSTS7000215"):
        await email_mod.deliver_with_config(_graph_cfg(), ["a@x.com"], "s", "h", use_breaker=False)


# =========================================================================
# Dominios internos de AD (.local)
# =========================================================================
@pytest.mark.asyncio
async def test_cuenta_de_servicio_en_dominio_local(client, auth_headers):
    """EmailStr rechaza .local; un AD interno típico usa svc@empresa.local."""
    r = await client.put(URL, json={**SMTP_BODY, "cuenta_email": "Inventario@Empresa.LOCAL"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["cuenta_email"] == "Inventario@empresa.local"


@pytest.mark.asyncio
async def test_persona_con_correo_local_se_puede_crear_y_editar(client, auth_headers, domain_seed, session):
    from app.models.organization import Persona
    alice = await session.get(Persona, __import__("uuid").UUID(domain_seed["alice"]))
    body = {"PER_Primer_Nombre": "Ana", "PER_Primer_Apellido": "Ruiz",
            "PER_Email_Corporativo": "ana.ruiz@empresa.local",
            "DEP_Departamento": alice.DEP_Departamento, "CAR_Cargo": alice.CAR_Cargo}
    r = await client.post("/api/v1/org/personas", json=body, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["PER_Persona"]
    r = await client.patch(f"/api/v1/org/personas/{pid}", json={"PER_Telefono": "555"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    for bad in ("sin-arroba", "a@b", "a b@empresa.local"):
        r = await client.post("/api/v1/org/personas", json={**body, "PER_Email_Corporativo": bad}, headers=auth_headers)
        assert r.status_code == 422, bad
