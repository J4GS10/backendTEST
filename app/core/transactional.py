"""
Decorador @transactional para métodos de service.

Reemplaza el patrón:
    async def create_x(...):
        ...
        try:
            await self.db.commit()
        except IntegrityError as e:
            await self.db.rollback()
            raise HTTPException(409, "INTEGRITY_CONSTRAINT_VIOLATED") from e

Por:
    @transactional
    async def create_x(self, ...):
        ...
        return obj

Beneficios:
- Imposible olvidar commit/rollback.
- Imposible olvidar manejo de IntegrityError -> 409.
- Soporte para HTTPException explícitas (se propagan tal cual).
- Re-raise de excepciones inesperadas como 500 (con log estructurado).

Requisitos:
- El método debe ser método de instancia con `self.db: AsyncSession`.
- El método debe ser asíncrono.
"""
from __future__ import annotations

import functools
from typing import Any, Awaitable, Callable, TypeVar

import structlog
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger("transactional")

T = TypeVar("T")


async def commit_or_409(db: AsyncSession, *, where: str = "") -> None:
    """
    Helper compartido: hace `db.commit()` y traduce IntegrityError -> 409.
    Usar desde services antiguos que aún no migran a @transactional, para
    garantizar un único punto de manejo de errores de integridad.
    """
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        log.warning(
            "commit_or_409.integrity",
            where=where,
            error=str(e.orig) if hasattr(e, "orig") else str(e),
        )
        raise HTTPException(
            status_code=409, detail="INTEGRITY_CONSTRAINT_VIOLATED"
        ) from e


def transactional(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """
    Decora un método de service: commit al final, rollback + 409 en IntegrityError.
    HTTPException explícitas se propagan; cualquier otra excepción produce rollback
    y se re-lanza para que el handler global la convierta en 500.
    """

    @functools.wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> T:
        try:
            result = await func(self, *args, **kwargs)
        except HTTPException:
            # Validación de negocio (404/400/409 explícito por el service).
            await self.db.rollback()
            raise
        except IntegrityError as e:
            await self.db.rollback()
            log.warning(
                "transactional.integrity_error",
                service=self.__class__.__name__,
                method=func.__name__,
                error=str(e.orig) if hasattr(e, "orig") else str(e),
            )
            raise HTTPException(
                status_code=409, detail="INTEGRITY_CONSTRAINT_VIOLATED"
            ) from e
        except Exception as e:
            await self.db.rollback()
            log.error(
                "transactional.unexpected_error",
                service=self.__class__.__name__,
                method=func.__name__,
                exc_type=type(e).__name__,
                error=str(e),
            )
            raise

        try:
            await self.db.commit()
        except IntegrityError as e:
            await self.db.rollback()
            log.warning(
                "transactional.commit_integrity_error",
                service=self.__class__.__name__,
                method=func.__name__,
                error=str(e.orig) if hasattr(e, "orig") else str(e),
            )
            raise HTTPException(
                status_code=409, detail="INTEGRITY_CONSTRAINT_VIOLATED"
            ) from e
        return result

    return wrapper
