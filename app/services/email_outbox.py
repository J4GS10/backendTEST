"""
Cola persistente de correos (outbox) + worker.

Flujo:
  send_notification() ──INSERT──▶ SYS_EMAIL_OUTBOX (PENDIENTE)
                                        │
  worker (1 por proceso) ◀── claim ─────┘  SELECT … FOR UPDATE SKIP LOCKED
     │  resuelve reglas (jefe, grupos AD) en el 1er intento y las fija
     │  envía 1 vez por SMTP
     ├── OK    → ENVIADO
     └── error → PENDIENTE con backoff (1m, 5m, 15m, 1h, 3h, 6h)
                 tras OUTBOX_MAX_ATTEMPTS → FALLIDO (reintentable desde la API)

Garantías:
- Varios procesos/réplicas drenan la cola sin enviar dos veces el mismo
  correo: el claim fija un *lease* (EOB_Proximo_Intento = ahora + lease) en
  una transacción corta con SKIP LOCKED.
- Si un proceso muere a mitad de envío, el lease vence y otro lo reintenta.
  Entrega at-least-once: un duplicado es posible solo si el proceso muere
  entre la aceptación del SMTP y el UPDATE a ENVIADO.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.governance import EmailOutbox

log = structlog.get_logger("email_outbox")

BACKOFF_SECONDS = [60, 300, 900, 3600, 3 * 3600, 6 * 3600]
LEASE_SECONDS = 300
BATCH_SIZE = 20

PENDIENTE, ENVIADO, FALLIDO = "PENDIENTE", "ENVIADO", "FALLIDO"

_wakeup = asyncio.Event()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session_factory() -> async_sessionmaker:
    from app.db import session as db_session
    return db_session.SessionLocal


async def enqueue(
    *,
    template: str,
    subject: str,
    html: str,
    to: list[str],
    affected: list[str] | None,
    cc_admins: bool,
    resolve: bool,
    reply_to: str | None,
) -> uuid.UUID:
    """Inserta el correo en la cola (transacción propia) y despierta al worker."""
    async with _session_factory()() as db:
        row = EmailOutbox(
            EOB_Plantilla=template, EOB_Asunto=subject[:255], EOB_Html=html,
            EOB_Para=list(to), EOB_Afectados=list(affected) if affected is not None else None,
            EOB_Cc_Admins=cc_admins, EOB_Resolver=resolve,
            EOB_Reply_To=(reply_to or None) and reply_to[:150],
            EOB_Estado=PENDIENTE, EOB_Intentos=0, EOB_Proximo_Intento=_now(),
        )
        db.add(row)
        await db.commit()
        _wakeup.set()
        return row.EOB_Id


async def _claim(db: AsyncSession) -> list[EmailOutbox]:
    now = _now()
    rows = (await db.execute(
        select(EmailOutbox)
        .where(EmailOutbox.EOB_Estado == PENDIENTE, EmailOutbox.EOB_Proximo_Intento <= now)
        .order_by(EmailOutbox.EOB_Proximo_Intento)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )).scalars().all()
    for r in rows:
        r.EOB_Proximo_Intento = now + timedelta(seconds=LEASE_SECONDS)
        r.EOB_Intentos += 1
    await db.commit()
    return list(rows)


async def _deliver(db: AsyncSession, row: EmailOutbox, sender: Callable) -> None:
    from app.core.email import MailAuthError, _admin_recipients
    from app.services.integration_config import BREAKER_MINUTES
    from app.services.notification_rules import RecipientResolver

    try:
        if row.EOB_Resolver:
            pairs = await RecipientResolver(db).resolve(
                row.EOB_Plantilla, to=row.EOB_Para, affected=row.EOB_Afectados,
                cc_admins=row.EOB_Cc_Admins,
            )
            # Fijar destinatarios: los reintentos no vuelven a consultar AD/reglas.
            row.EOB_Para = [e for e, _ in pairs]
            row.EOB_Resolver = False
        recipients = list(row.EOB_Para or [])
        if not recipients:
            row.EOB_Estado = ENVIADO
            row.EOB_Ultimo_Error = "SIN_DESTINATARIOS"
            row.EOB_Enviado_En = _now()
            await db.commit()
            return
        await sender(recipients, row.EOB_Asunto, row.EOB_Html, row.EOB_Reply_To)
    except MailAuthError as e:
        # Clave rechazada: no es culpa del correo. No consume intento; espera a
        # que se reanude (cortacircuitos) para no bloquear la cuenta de servicio.
        row.EOB_Intentos = max(0, row.EOB_Intentos - 1)
        row.EOB_Ultimo_Error = f"{e.code}: {e.message[:300]}"
        row.EOB_Proximo_Intento = _now() + timedelta(minutes=BREAKER_MINUTES)
        await db.commit()
        return
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {str(e)[:400]}"
        if row.EOB_Resolver:
            # Falló la resolución (BD/AD): se reintenta con los destinatarios
            # históricos para no perder el aviso.
            row.EOB_Para = list({x for x in [*row.EOB_Para, *(_admin_recipients() if row.EOB_Cc_Admins else [])] if x})
            row.EOB_Resolver = False
        row.EOB_Ultimo_Error = error
        if row.EOB_Intentos >= settings.OUTBOX_MAX_ATTEMPTS:
            row.EOB_Estado = FALLIDO
            log.error("email_outbox.failed", id=str(row.EOB_Id), plantilla=row.EOB_Plantilla, error=error)
        else:
            delay = BACKOFF_SECONDS[min(row.EOB_Intentos - 1, len(BACKOFF_SECONDS) - 1)]
            row.EOB_Proximo_Intento = _now() + timedelta(seconds=delay)
            log.warning("email_outbox.retry", id=str(row.EOB_Id), intento=row.EOB_Intentos, en_s=delay, error=error)
        await db.commit()
        return
    row.EOB_Estado = ENVIADO
    row.EOB_Enviado_En = _now()
    row.EOB_Ultimo_Error = None
    await db.commit()


async def process_due(
    session_factory: async_sessionmaker | None = None,
    sender: Callable | None = None,
) -> int:
    """Procesa un lote de correos vencidos. Devuelve cuántos intentó."""
    from app.core.email import _smtp_send_once

    from app.services.integration_config import breaker_until

    factory = session_factory or _session_factory()
    sender = sender or _smtp_send_once
    if await breaker_until("smtp"):
        return 0  # autenticación en pausa: los correos esperan en la cola
    async with factory() as db:
        rows = await _claim(db)
    for row in rows:
        async with factory() as db:
            fresh = await db.get(EmailOutbox, row.EOB_Id)
            if fresh is not None and fresh.EOB_Estado == PENDIENTE:
                await _deliver(db, fresh, sender)
    return len(rows)


async def worker_loop() -> None:
    """
    Loop del worker (lifespan). Despierta al encolar o cada OUTBOX_POLL_SECONDS.
    Corre siempre: el correo puede activarse desde la UI sin reiniciar.
    """
    from app.services.integration_config import get_config

    log.info("email_outbox.worker_started")
    while True:
        try:
            while (await get_config()).mail.ready and await process_due() == BATCH_SIZE:
                pass  # hay más trabajo: seguir drenando
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("email_outbox.worker_error", error=str(e)[:200])
        _wakeup.clear()
        try:
            await asyncio.wait_for(_wakeup.wait(), timeout=settings.OUTBOX_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


# =========================================================================
# Consulta / operación (API de administración)
# =========================================================================
async def summary(db: AsyncSession) -> dict[str, Any]:
    counts = dict((await db.execute(
        select(EmailOutbox.EOB_Estado, func.count()).group_by(EmailOutbox.EOB_Estado)
    )).all())
    fallidos = (await db.execute(
        select(EmailOutbox).where(EmailOutbox.EOB_Estado == FALLIDO)
        .order_by(EmailOutbox.EOB_Creado_En.desc()).limit(50)
    )).scalars().all()
    oldest = (await db.execute(
        select(func.min(EmailOutbox.EOB_Creado_En)).where(EmailOutbox.EOB_Estado == PENDIENTE)
    )).scalar_one_or_none()
    return {
        "pendientes": counts.get(PENDIENTE, 0),
        "enviados": counts.get(ENVIADO, 0),
        "fallidos": counts.get(FALLIDO, 0),
        "pendiente_mas_antiguo": oldest.isoformat() if oldest else None,
        "ultimos_fallidos": [
            {
                "id": str(r.EOB_Id), "plantilla": r.EOB_Plantilla, "asunto": r.EOB_Asunto,
                "destinatarios": r.EOB_Para, "intentos": r.EOB_Intentos,
                "error": r.EOB_Ultimo_Error, "creado_en": r.EOB_Creado_En.isoformat() if r.EOB_Creado_En else None,
            }
            for r in fallidos
        ],
    }


async def retry_failed(db: AsyncSession, outbox_id: uuid.UUID | None = None) -> int:
    """Devuelve a PENDIENTE un correo FALLIDO (o todos) para reintentarlo ya."""
    q = update(EmailOutbox).where(EmailOutbox.EOB_Estado == FALLIDO)
    if outbox_id is not None:
        q = q.where(EmailOutbox.EOB_Id == outbox_id)
    res = await db.execute(q.values(EOB_Estado=PENDIENTE, EOB_Intentos=0, EOB_Proximo_Intento=_now()))
    await db.commit()
    _wakeup.set()
    return res.rowcount or 0
