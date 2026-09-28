"""
Integración con Active Directory y reglas de notificación por gestión.

No hay AD real en los tests: se inyecta `FakeDirectory` con
`set_directory_client()`, que implementa la misma interfaz que el cliente LDAP.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.integrations.active_directory import (
    DirectoryClient, DirectoryError, DirectoryGroup, DirectoryUser, set_directory_client,
)
from app.models.governance import AuditoriaSistema
from app.models.organization import Departamento, Persona, Usuario
from app.services.directory_sync import DirectorySyncService
from app.services.notification_rules import NotificationRulesService, RecipientResolver


def _u(v):
    return uuid.UUID(v) if isinstance(v, str) else v


class FakeDirectory(DirectoryClient):
    def __init__(self, users=(), groups=None, fail=False):
        self.users = list(users)
        self.groups = groups or {}
        self.fail = fail

    async def test_connection(self) -> int:
        if self.fail:
            raise DirectoryError("AD_BIND_FAILED")
        return len(self.users)

    async def list_users(self):
        if self.fail:
            raise DirectoryError("AD_BIND_FAILED")
        return self.users

    async def group_member_emails(self, group):
        if self.fail:
            raise DirectoryError("AD_SEARCH_FAILED")
        return self.groups.get(group, [])

    async def search_groups(self, query, limit=20):
        return [DirectoryGroup(nombre=g, dn=f"CN={g},DC=test") for g in self.groups if query.lower() in g.lower()]


def _ad_user(n, email, manager=None, enabled=True, dept="Tecnología", title="Analista"):
    return DirectoryUser(
        guid=f"00000000-0000-0000-0000-{n:012d}", dn=f"CN=U{n},OU=Users,DC=test",
        email=email, given_name="Juan Carlos", surname="Pérez Gómez", username=f"u{n}",
        department=dept, title=title, phone="555-0100", manager_dn=manager, enabled=enabled,
    )


@pytest.fixture(autouse=True)
def _reset_directory():
    yield
    set_directory_client(None)


@pytest_asyncio.fixture
async def with_manager(session, domain_seed):
    """bob es jefe de alice."""
    alice = await session.get(Persona, _u(domain_seed["alice"]))
    alice.PER_Jefe = _u(domain_seed["bob"])
    await session.commit()
    return domain_seed


# =========================================================================
# Resolución de destinatarios
# =========================================================================
@pytest.mark.asyncio
async def test_defaults_reproducen_comportamiento_historico(session, domain_seed, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "NOTIFY_ADMIN_EMAILS", "ops@x.com")
    pairs = await RecipientResolver(session, FakeDirectory()).resolve(
        "asignacion", to=["alice@test.local"],
    )
    assert pairs == [("alice@test.local", "afectado"), ("ops@x.com", "admins")]

    # offboarding: por defecto solo admins aunque haya afectado
    pairs = await RecipientResolver(session, FakeDirectory()).resolve(
        "offboarding", to=[], affected=["alice@test.local"],
    )
    assert pairs == [("ops@x.com", "admins")]


@pytest.mark.asyncio
async def test_regla_con_jefe_grupo_ad_y_extra(session, with_manager, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "NOTIFY_ADMIN_EMAILS", "")
    await NotificationRulesService(session).upsert_rule("offboarding", {
        "activa": True, "notificar_afectado": True, "notificar_jefe": True,
        "copiar_admins": False, "grupos_ad": ["RRHH"], "correos_extra": ["Nomina@X.com"],
    })
    fake = FakeDirectory(groups={"RRHH": ["rh1@x.com", "bob@test.local"]})
    pairs = dict(await RecipientResolver(session, fake).resolve(
        "offboarding", to=[], affected=["alice@test.local"],
    ))
    assert pairs == {
        "alice@test.local": "afectado",
        "bob@test.local": "jefe",  # deduplicado: gana el primer origen
        "rh1@x.com": "grupo:RRHH",
        "nomina@x.com": "extra",
    }


@pytest.mark.asyncio
async def test_regla_inactiva_no_envia(session, domain_seed):
    await NotificationRulesService(session).upsert_rule("asignacion", {
        "activa": False, "notificar_afectado": True, "notificar_jefe": False,
        "copiar_admins": True, "grupos_ad": [], "correos_extra": [],
    })
    assert await RecipientResolver(session, FakeDirectory()).resolve(
        "asignacion", to=["alice@test.local"],
    ) == []


@pytest.mark.asyncio
async def test_eventos_de_seguridad_ignoran_reglas(session, domain_seed, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "NOTIFY_ADMIN_EMAILS", "ops@x.com")
    pairs = await RecipientResolver(session, FakeDirectory()).resolve(
        "2fa_code", to=["alice@test.local"], cc_admins=False,
    )
    assert pairs == [("alice@test.local", "afectado")]


@pytest.mark.asyncio
async def test_ad_caido_no_rompe_resolucion(session, domain_seed, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "AD_ADMIN_GROUP", "TI-Admins")
    monkeypatch.setattr(cfg.settings, "NOTIFY_ADMIN_EMAILS", "ops@x.com")
    pairs = await RecipientResolver(session, FakeDirectory(fail=True)).resolve(
        "asignacion", to=["alice@test.local"],
    )
    assert [e for e, _ in pairs] == ["alice@test.local", "ops@x.com"]


@pytest.mark.asyncio
async def test_grupo_admin_de_ad(session, domain_seed, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "AD_ADMIN_GROUP", "TI-Admins")
    monkeypatch.setattr(cfg.settings, "NOTIFY_ADMIN_EMAILS", "")
    fake = FakeDirectory(groups={"TI-Admins": ["jefe.ti@x.com"]})
    pairs = await RecipientResolver(session, fake).resolve("stock_bajo", to=[])
    assert pairs == [("jefe.ti@x.com", "admins")]


# =========================================================================
# Sincronización
# =========================================================================
@pytest.mark.asyncio
async def test_sync_crea_vincula_y_asigna_jefe(session, domain_seed):
    fake = FakeDirectory(users=[
        _ad_user(1, "ALICE@test.local", manager="CN=U2,OU=Users,DC=test"),  # vincula por email
        _ad_user(2, "nuevo.jefe@test.local", dept="Dirección", title="Director"),  # alta
        _ad_user(3, None),  # sin email → error
    ])
    result = await DirectorySyncService(session, fake).sync()
    assert result["vinculados"] == 1
    assert result["creados"] == 1
    assert result["jefes_asignados"] == 1
    assert len(result["errores"]) == 1

    alice = await session.get(Persona, _u(domain_seed["alice"]))
    await session.refresh(alice)
    assert alice.PER_AD_GUID.endswith("000000000001")
    assert alice.PER_Primer_Nombre == "Juan" and alice.PER_Segundo_Nombre == "Carlos"
    assert alice.PER_Segundo_Apellido == "Gómez"
    jefe = (await session.execute(
        select(Persona).where(Persona.PER_Email_Corporativo == "nuevo.jefe@test.local")
    )).scalar_one()
    assert alice.PER_Jefe == jefe.PER_Persona
    dep = await session.get(Departamento, jefe.DEP_Departamento)
    assert dep.DEP_Nombre == "Dirección"

    audit = (await session.execute(
        select(AuditoriaSistema).where(AuditoriaSistema.AUD_Accion == "AD_SYNC")
    )).scalars().all()
    assert len(audit) == 1

    # Idempotente: una segunda pasada no cambia nada.
    again = await DirectorySyncService(session, fake).sync()
    assert (again["creados"], again["actualizados"], again["vinculados"], again["jefes_asignados"]) == (0, 0, 0, 0)


@pytest.mark.asyncio
async def test_sync_dry_run_no_persiste(session, domain_seed):
    fake = FakeDirectory(users=[_ad_user(9, "fantasma@test.local")])
    result = await DirectorySyncService(session, fake).sync(dry_run=True)
    assert result["creados"] == 1
    count = (await session.execute(
        select(Persona).where(Persona.PER_Email_Corporativo == "fantasma@test.local")
    )).scalars().all()
    assert count == []


@pytest.mark.asyncio
async def test_sync_desactiva_sin_activos_y_reporta_con_activos(client, auth_headers, session, domain_seed):
    # alice recibe un activo; bob no tiene nada
    r = await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={"ACT_Activo": domain_seed["act_1"], "PER_Persona": domain_seed["alice"],
              "ARE_Area": domain_seed["area"], "TMO_Tipo_Movimiento": domain_seed["tmo_asg"]},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    fake = FakeDirectory(users=[
        _ad_user(1, "alice@test.local", enabled=False),
        _ad_user(2, "bob@test.local", enabled=False),
    ])
    result = await DirectorySyncService(session, fake).sync()
    assert result["desactivados"] == 1
    assert [p["email"] for p in result["pendientes_con_activos"]] == ["alice@test.local"]

    session.expire_all()
    alice = await session.get(Persona, _u(domain_seed["alice"]))
    bob = await session.get(Persona, _u(domain_seed["bob"]))
    assert alice.PER_Estado is True
    assert bob.PER_Estado is False

    # Rehabilitado en AD → persona reactivada
    fake.users = [_ad_user(2, "bob@test.local", enabled=True)]
    result = await DirectorySyncService(session, fake).sync()
    assert result["reactivados"] == 1


@pytest.mark.asyncio
async def test_sync_desactiva_usuario_del_sistema(session, domain_seed):
    bob_id = _u(domain_seed["bob"])
    session.add(Usuario(USU_Username="bobuser", USU_Password_Hash="x", USU_Rol="CONSULTA", PER_Persona=bob_id))
    await session.commit()
    fake = FakeDirectory(users=[_ad_user(2, "bob@test.local")])
    await DirectorySyncService(session, fake).sync()
    fake.users = []  # desaparece de AD
    result = await DirectorySyncService(session, fake).sync()
    assert result["desactivados"] == 1
    session.expire_all()
    usu = (await session.execute(select(Usuario).where(Usuario.PER_Persona == bob_id))).scalar_one()
    assert usu.USU_Estado is False


@pytest.mark.asyncio
async def test_sync_ad_no_disponible(session, domain_seed):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await DirectorySyncService(session, FakeDirectory(fail=True)).sync()
    assert exc.value.status_code == 502


# =========================================================================
# API
# =========================================================================
@pytest.mark.asyncio
async def test_api_reglas_crud_y_vista_previa(client, auth_headers, with_manager, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "NOTIFY_ADMIN_EMAILS", "")
    r = await client.get("/api/v1/directorio/notificaciones/reglas", headers=auth_headers)
    assert r.status_code == 200
    reglas = {x["evento"]: x for x in r.json()}
    assert reglas["asignacion"]["notificar_afectado"] is True
    assert reglas["asignacion"]["personalizada"] is False

    body = {"activa": True, "notificar_afectado": True, "notificar_jefe": True,
            "copiar_admins": False, "grupos_ad": [], "correos_extra": ["extra@x.com"]}
    r = await client.put("/api/v1/directorio/notificaciones/reglas/asignacion", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["personalizada"] is True

    r = await client.get(
        f"/api/v1/directorio/notificaciones/vista-previa/asignacion?persona_id={with_manager['alice']}",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["detalle"] == [
        {"email": "alice@test.local", "origen": "afectado"},
        {"email": "bob@test.local", "origen": "jefe"},
        {"email": "extra@x.com", "origen": "extra"},
    ]

    r = await client.delete("/api/v1/directorio/notificaciones/reglas/asignacion", headers=auth_headers)
    assert r.status_code == 204
    r = await client.put("/api/v1/directorio/notificaciones/reglas/password_reset", json=body, headers=auth_headers)
    assert r.status_code == 404
    r = await client.put(
        "/api/v1/directorio/notificaciones/reglas/asignacion",
        json={**body, "correos_extra": ["no-es-email"]}, headers=auth_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_api_estado_y_sincronizar(client, auth_headers, domain_seed):
    r = await client.get("/api/v1/directorio/estado", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False and r.json()["last_sync"] is None

    r = await client.post("/api/v1/directorio/sincronizar", headers=auth_headers)
    assert r.status_code == 400  # AD deshabilitado

    set_directory_client(FakeDirectory(users=[_ad_user(5, "carla@test.local")], groups={"RRHH": []}))
    r = await client.post("/api/v1/directorio/sincronizar", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["creados"] == 1
    r = await client.get("/api/v1/directorio/estado", headers=auth_headers)
    assert r.json()["last_sync"]["creados"] == 1
    r = await client.post("/api/v1/directorio/probar", headers=auth_headers)
    assert r.json() == {"ok": True, "message": "OK", "usuarios_encontrados": 1}
    r = await client.get("/api/v1/directorio/grupos?q=rr", headers=auth_headers)
    assert r.json() == [{"nombre": "RRHH", "dn": "CN=RRHH,DC=test"}]


# =========================================================================
# Envío: la resolución de reglas se aplica al entregar desde la cola
# =========================================================================
@pytest.mark.asyncio
async def test_send_notification_usa_reglas(session, engine, with_manager, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.core import config as cfg, email as email_mod
    from app.services import email_outbox
    import app.db.session as db_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(cfg.settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(cfg.settings, "NOTIFY_ADMIN_EMAILS", "")
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    sent = []

    async def fake_send(to, subject, html, reply_to=None):
        sent.append(sorted(to))

    await NotificationRulesService(session).upsert_rule("asignacion", {
        "activa": True, "notificar_afectado": True, "notificar_jefe": True,
        "copiar_admins": True, "grupos_ad": [], "correos_extra": [],
    })
    await email_mod.send_notification(
        "asignacion", {"codigo": "LAP-001", "persona_nombre": "Alice"}, to=["alice@test.local"],
    )
    assert await email_outbox.process_due(factory, fake_send) == 1
    assert sent == [["alice@test.local", "bob@test.local"]]


def test_parseo_atributos_ldap():
    """objectGUID binario little-endian, userAccountControl y listas de atributos."""
    from app.integrations.active_directory import _to_user
    guid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    u = _to_user({
        "objectGUID": guid.bytes_le, "distinguishedName": "CN=Ana,DC=x",
        "mail": ["Ana@X.com"], "givenName": "Ana", "sn": "Ruiz",
        "userAccountControl": 514, "manager": "CN=Jefe,DC=x", "telephoneNumber": [],
        "mobile": "555",
    })
    assert u.guid == str(guid)
    assert u.email == "ana@x.com"
    assert u.enabled is False  # 514 = NORMAL_ACCOUNT | ACCOUNTDISABLE
    assert u.phone == "555"
    assert _to_user({"distinguishedName": "CN=x"}) is None
