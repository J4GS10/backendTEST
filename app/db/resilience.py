"""Sondas acotadas para reconectar al endpoint estable del writer."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class DatabaseProbe:
    available: bool
    attempts: int
    error: str | None = None


async def probe_database(
    target_engine: AsyncEngine,
    *,
    retries: int,
    timeout_seconds: float,
    retry_delay_seconds: float,
) -> DatabaseProbe:
    """
    Prueba una conexión nueva y recicla el pool ante fallo.

    Esta política se limita a health/readiness. Las transacciones de negocio no
    se reintentan automáticamente porque podrían haber aplicado cambios.
    """
    attempts = max(1, retries + 1)
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with asyncio.timeout(timeout_seconds):
                async with target_engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
            return DatabaseProbe(available=True, attempts=attempt)
        except Exception as exc:  # noqa: BLE001 - la sonda debe fallar cerrada
            last_error = f"{type(exc).__name__}: {exc}"
            await target_engine.dispose()
            if attempt < attempts and retry_delay_seconds > 0:
                await asyncio.sleep(retry_delay_seconds)
    return DatabaseProbe(available=False, attempts=attempts, error=last_error)

