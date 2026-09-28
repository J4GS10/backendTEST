"""
Tareas en segundo plano del proceso (arrancan en el lifespan de FastAPI).

- Worker de la cola de correos: uno por proceso; la cola admite varios
  consumidores (SKIP LOCKED), así que todos los workers de gunicorn drenan.
- Tareas periódicas (purga de seguridad, sincronización AD): con varios
  workers/réplicas se ejecutan UNA sola vez por intervalo gracias a un lock en
  Redis (SET NX EX). Sin Redis (dev), corren en cada proceso: son idempotentes.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import structlog


log = structlog.get_logger("scheduled_jobs")

PURGE_INTERVAL_SECONDS = 6 * 3600


async def run_periodic(name: str, interval_s: int, job: Callable[[], Awaitable[object]]) -> None:
    from app.core.cache import get_redis

    while True:
        await asyncio.sleep(interval_s)
        try:
            r = get_redis()
            if r is not None and not await r.set(f"lock:job:{name}", "1", nx=True, ex=max(interval_s - 5, 30)):
                continue
            result = await job()
            log.info("job.done", job=name, result=result if isinstance(result, dict) else None)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("job.failed", job=name, error=str(e)[:200])


async def purge_security_records() -> dict:
    from app.db.session import SessionLocal
    from app.services.governance import GovernanceService

    async with SessionLocal() as db:
        return await GovernanceService(db).purge_security_records()


async def security_housekeeping() -> dict:
    from app.db.session import SessionLocal
    from app.services.security_jobs import security_housekeeping as _run

    async with SessionLocal() as db:
        return await _run(db)


async def ad_sync_loop() -> None:
    """
    Sincronización periódica con el AD. El intervalo y la activación se leen de
    la config efectiva en cada vuelta: se pueden cambiar desde la UI sin
    reiniciar. Con varios workers, el lock de Redis evita ejecuciones dobles.
    """
    import time

    from app.core.cache import get_redis
    from app.services.directory_sync import sync_once
    from app.services.integration_config import get_config

    last = time.monotonic()
    while True:
        await asyncio.sleep(60)
        try:
            cfg = (await get_config()).ad
            interval = cfg.sync_interval_min * 60
            if not cfg.ready or interval <= 0 or time.monotonic() - last < interval:
                continue
            last = time.monotonic()
            r = get_redis()
            if r is not None and not await r.set("lock:job:ad_sync", "1", nx=True, ex=max(interval - 5, 30)):
                continue
            result = await sync_once()
            log.info("job.done", job="ad_sync", creados=result.get("creados"), desactivados=result.get("desactivados"))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("job.failed", job="ad_sync", error=str(e)[:200])


def start_background_jobs() -> list[asyncio.Task]:
    from app.services.email_outbox import worker_loop

    return [
        asyncio.create_task(run_periodic("purge_security", PURGE_INTERVAL_SECONDS, purge_security_records)),
        asyncio.create_task(run_periodic("security_housekeeping", PURGE_INTERVAL_SECONDS, security_housekeeping)),
        asyncio.create_task(worker_loop()),
        asyncio.create_task(ad_sync_loop()),
    ]


async def stop_background_jobs(tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
