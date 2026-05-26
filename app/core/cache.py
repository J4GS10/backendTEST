"""
Cliente Redis compartido para caché de auth y otros valores de hot-path.

Si REDIS_URL no está definido, las funciones devuelven None/no-op y el
comportamiento es equivalente a "sin caché" (válido para dev/test).
"""
from __future__ import annotations

import json
from typing import Any, Optional

import structlog

from app.core.config import settings

log = structlog.get_logger("cache")

_redis_client: Optional[Any] = None


def get_redis():
    """
    Devuelve el cliente redis.asyncio.Redis, o None si REDIS_URL no está
    configurado o el módulo no está disponible.
    """
    global _redis_client
    # REDIS_URL puede ser None, "" o un string. Tratamos "" como deshabilitado.
    if not settings.REDIS_URL:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as redis_async  # type: ignore
    except ImportError:
        log.warning("cache.redis_not_installed")
        return None
    _redis_client = redis_async.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )
    return _redis_client


async def cache_get(key: str) -> Optional[dict]:
    r = get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        log.warning("cache.get_failed", key=key, error=str(e))
        return None


async def cache_set(key: str, value: dict, ttl_seconds: int) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        await r.set(key, json.dumps(value), ex=ttl_seconds)
    except Exception as e:  # noqa: BLE001
        log.warning("cache.set_failed", key=key, error=str(e))


async def cache_delete(*keys: str) -> None:
    r = get_redis()
    if r is None or not keys:
        return
    try:
        await r.delete(*keys)
    except Exception as e:  # noqa: BLE001
        log.warning("cache.delete_failed", error=str(e))
