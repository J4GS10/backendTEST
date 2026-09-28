"""
Cola persistente de correos: encolado, entrega, reintentos con backoff,
FALLIDO tras el máximo, reintento manual y correos efímeros fuera de la cola.
"""
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import config as cfg
from app.core import email as email_mod
from app.models.governance import EmailOutbox
from app.services import email_outbox


@pytest_asyncio.fixture
async def outbox_env(engine, monkeypatch):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    import app.db.session as db_session
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    monkeypatch.setattr(cfg.settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(cfg.settings, "NOTIFY_ADMIN_EMAILS", "ops@x.com")
    return factory


class Sender:
    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.sent = []

    async def __call__(self, to, subject, html, reply_to=None):
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("smtp down")
        self.sent.append((sorted(to), subject))


async def _rows(factory):
    async with factory() as db:
        return (await db.execute(select(EmailOutbox))).scalars().all()


async def _make_due(factory):
    """Simula que pasó el tiempo de backoff."""
    async with factory() as db:
        for r in (await db.execute(select(EmailOutbox))).scalars():
            r.EOB_Proximo_Intento = r.EOB_Proximo_Intento - timedelta(days=1)
        await db.commit()


@pytest.mark.asyncio
async def test_encola_y_entrega(outbox_env, sa_user):
    await email_mod.send_notification("stock_bajo", {"codigo": "TON-1"}, to=())
    rows = await _rows(outbox_env)
    assert len(rows) == 1 and rows[0].EOB_Estado == "PENDIENTE"

    sender = Sender()
    assert await email_outbox.process_due(outbox_env, sender) == 1
    assert sender.sent == [(["ops@x.com"], "[Inventario] Stock bajo: TON-1")]
    row = (await _rows(outbox_env))[0]
    assert row.EOB_Estado == "ENVIADO" and row.EOB_Enviado_En is not None
    # Nada más por hacer.
    assert await email_outbox.process_due(outbox_env, sender) == 0


@pytest.mark.asyncio
async def test_smtp_caido_reintenta_con_backoff_y_luego_entrega(outbox_env, sa_user):
    await email_mod.send_notification("stock_bajo", {"codigo": "TON-1"}, to=())
    sender = Sender(fail_times=2)

    await email_outbox.process_due(outbox_env, sender)
    row = (await _rows(outbox_env))[0]
    assert row.EOB_Estado == "PENDIENTE" and row.EOB_Intentos == 1
    assert "smtp down" in row.EOB_Ultimo_Error
    # Backoff: no se reintenta inmediatamente.
    assert await email_outbox.process_due(outbox_env, sender) == 0

    await _make_due(outbox_env)
    await email_outbox.process_due(outbox_env, sender)
    await _make_due(outbox_env)
    await email_outbox.process_due(outbox_env, sender)
    row = (await _rows(outbox_env))[0]
    assert row.EOB_Estado == "ENVIADO" and row.EOB_Intentos == 3
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_fallido_tras_maximo_y_reintento_manual(outbox_env, sa_user, monkeypatch):
    monkeypatch.setattr(cfg.settings, "OUTBOX_MAX_ATTEMPTS", 2)
    await email_mod.send_notification("stock_bajo", {"codigo": "TON-1"}, to=())
    sender = Sender(fail_times=99)
    await email_outbox.process_due(outbox_env, sender)
    await _make_due(outbox_env)
    await email_outbox.process_due(outbox_env, sender)
    row = (await _rows(outbox_env))[0]
    assert row.EOB_Estado == "FALLIDO"

    async with outbox_env() as db:
        resumen = await email_outbox.summary(db)
        assert resumen["fallidos"] == 1 and resumen["ultimos_fallidos"][0]["intentos"] == 2
        assert await email_outbox.retry_failed(db) == 1
    ok = Sender()
    await email_outbox.process_due(outbox_env, ok)
    assert (await _rows(outbox_env))[0].EOB_Estado == "ENVIADO"


@pytest.mark.asyncio
async def test_lease_evita_doble_envio(outbox_env, sa_user):
    """Un correo reclamado por un worker no lo toma otro hasta que vence el lease."""
    await email_mod.send_notification("stock_bajo", {"codigo": "TON-1"}, to=())
    async with outbox_env() as db:
        claimed = await email_outbox._claim(db)
    assert len(claimed) == 1
    async with outbox_env() as db:
        assert await email_outbox._claim(db) == []


@pytest.mark.asyncio
async def test_correos_con_secretos_no_se_persisten(outbox_env, sa_user, monkeypatch):
    calls = []

    async def fake_direct(to, subject, html, reply_to=None, **kw):
        calls.append(to)
    monkeypatch.setattr(email_mod, "_send_via_smtp_with_retry", fake_direct)
    await email_mod.send_notification("2fa_code", {"code": "123456"}, to=["a@x.com"], cc_admins=False)
    for t in list(email_mod._background_tasks):
        await t
    assert calls == [["a@x.com"]]
    assert await _rows(outbox_env) == []


@pytest.mark.asyncio
async def test_sin_smtp_no_encola(engine, sa_user, monkeypatch):
    monkeypatch.setattr(cfg.settings, "SMTP_HOST", None)
    import app.db.session as db_session
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    await email_mod.send_notification("stock_bajo", {"codigo": "TON-1"}, to=())
    assert await _rows(factory) == []


@pytest.mark.asyncio
async def test_api_resumen_y_reintento(client, auth_headers, outbox_env):
    r = await client.get("/api/v1/gov/email-outbox", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["pendientes"] == 0
    r = await client.post("/api/v1/gov/email-outbox/reintentar", headers=auth_headers)
    assert r.json() == {"reencolados": 0}
