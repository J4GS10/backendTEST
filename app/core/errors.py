"""Manejo de errores internos sin filtrar detalles al cliente."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

log = structlog.get_logger("service")


def utcnow_naive() -> datetime:
    """
    UTC naive (compatible con columnas DateTime sin tz). Reemplaza
    `datetime.utcnow()`, deprecado en Python 3.12+. Usar este helper
    en lugar de utcnow() en todo código nuevo / refactor.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def internal_error(exc: Exception, code: str = "INTERNAL_ERROR") -> HTTPException:
    """
    Registra el error REAL en el log estructurado (para diagnóstico) y devuelve
    una HTTPException 500 con un mensaje GENÉRICO, sin exponer internals
    (nombres de tablas, constraints, mensajes del driver) al cliente.

    Uso:
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e)

    Consistencia: una violación de integridad (FK/UNIQUE/CHECK) que llegue
    aquí se traduce SIEMPRE a 409, nunca a 500 — así ningún service que use
    este helper expone un 500 ante un conflicto de datos esperable.
    """
    if isinstance(exc, IntegrityError):
        log.warning(
            "service.integrity_error",
            code=code,
            error=str(exc.orig) if hasattr(exc, "orig") else str(exc),
        )
        return HTTPException(status_code=409, detail="INTEGRITY_CONSTRAINT_VIOLATED")
    log.error("service.internal_error", code=code, error=str(exc), exc_type=type(exc).__name__)
    return HTTPException(status_code=500, detail=code)
