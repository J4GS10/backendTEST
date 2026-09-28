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
- Soporte para hooks post-commit para side effects que no deben revertir la BD.
- Re-raise de excepciones inesperadas como 500 (con log estructurado).

Requisitos:
- El método debe ser método de instancia con `self.db: AsyncSession`.
- El método debe ser asíncrono.
"""
from __future__ import annotations

import inspect
import functools
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, TypeVar

import structlog
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger("transactional")

T = TypeVar("T")
_transaction_depth: ContextVar[int] = ContextVar("transaction_depth", default=0)
_post_commit_hooks: ContextVar[list[Callable[[], Any]] | None] = ContextVar(
    "post_commit_hooks", default=None
)


def schedule_post_commit(owner: Any, callback: Callable[[], Any]) -> None:
    """
    Registra una acción para ejecutarla solo después de un commit exitoso.

    Los servicios pueden usarlo para correos, notificaciones o logs externos
    que no deben revertir la transacción si fallan.
    """
    del owner  # Hooks belong to the current async transaction, not the service instance.
    hooks = _post_commit_hooks.get()
    if hooks is None:
        raise RuntimeError("POST_COMMIT_HOOK_OUTSIDE_TRANSACTION")
    hooks.append(callback)


async def _run_post_commit_hooks(
    hooks: list[Callable[[], Any]], *, service: str, method: str
) -> None:
    # Los efectos posteriores (correos, notificaciones, limpieza de archivos)
    # son tareas del sistema: no deben quedar limitados por el alcance por sede
    # del usuario (p. ej. resolver los correos de administradores de otra sede).
    from app.core.data_scope import system_scope

    for callback in hooks:
        try:
            with system_scope():
                result = callback()
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "transactional.post_commit_hook_failed",
                service=service,
                method=method,
                hook=getattr(callback, "__name__", callback.__class__.__name__),
                exc_type=type(exc).__name__,
                error=str(exc),
            )


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
        depth = _transaction_depth.get()
        depth_token = _transaction_depth.set(depth + 1)
        hooks_token = None
        if depth == 0:
            hooks_token = _post_commit_hooks.set([])

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
        else:
            if depth > 0:
                return result
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
            except Exception as e:
                await self.db.rollback()
                log.error(
                    "transactional.commit_failed",
                    service=self.__class__.__name__,
                    method=func.__name__,
                    exc_type=type(e).__name__,
                    error=str(e),
                )
                raise

            await _run_post_commit_hooks(
                _post_commit_hooks.get() or [],
                service=self.__class__.__name__,
                method=func.__name__,
            )
            return result
        finally:
            _transaction_depth.reset(depth_token)
            if hooks_token is not None:
                _post_commit_hooks.reset(hooks_token)

    return wrapper
