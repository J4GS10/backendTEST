"""
Soporte de cabecera 'Idempotency-Key' para POSTs críticos.

Uso en un endpoint:
    @router.post(...)
    async def crear_algo(..., idempotency=Depends(idempotency_guard)):
        if cached := idempotency.lookup():
            return cached  # respuesta original cacheada
        result = await ... # tu lógica normal
        await idempotency.store(result, status_code=201)
        return result

Comportamiento:
- Si no llega 'Idempotency-Key', se permite (operación normal).
- Si llega y existe el registro con MISMO endpoint + MISMO usuario + MISMO
  body hash: devolvemos la respuesta cacheada.
- Si existe con MISMA key pero distinto body hash: 409 IDEMPOTENCY_KEY_CONFLICT.
- TTL: 24h. Más antiguos se reutilizan (overwrite) y limpieza ocurre con job
  externo (o `DELETE WHERE creada < now() - interval '24h'`).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.errors import utcnow_naive as _utcnow_naive
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_db
from app.models.governance import IdempotencyKey


IDEMPOTENCY_TTL_HOURS = 24


@dataclass
class _IdempotencyGuard:
    key: Optional[str]
    endpoint: str
    body_hash: str
    user_id: Any
    db: AsyncSession
    _cached_record: Optional[IdempotencyKey] = None

    async def lookup(self) -> Optional[dict]:
        """Si hay key + match exacto, devuelve la respuesta original."""
        if not self.key:
            return None
        result = await self.db.execute(
            select(IdempotencyKey).where(IdempotencyKey.IDK_Key == self.key)
        )
        rec = result.scalar_one_or_none()
        if rec is None:
            return None

        # Sólo respetamos si es el MISMO usuario + MISMO endpoint
        if str(rec.IDK_Usuario) != str(self.user_id) or rec.IDK_Endpoint != self.endpoint:
            raise HTTPException(409, "IDEMPOTENCY_KEY_CONFLICT_DIFFERENT_OWNER")

        if rec.IDK_Request_Hash != self.body_hash:
            raise HTTPException(409, "IDEMPOTENCY_KEY_CONFLICT_DIFFERENT_BODY")

        # Caducidad
        if rec.IDK_Creada_En < _utcnow_naive() - timedelta(hours=IDEMPOTENCY_TTL_HOURS):
            return None

        self._cached_record = rec
        return rec.IDK_Response_Body or {}

    async def store(self, body: Any, status_code: int = 200) -> None:
        """Guarda la respuesta para futuras llamadas con la misma key."""
        if not self.key:
            return
        try:
            serializable = _to_jsonable(body)
        except Exception:
            # No bloqueamos el flujo principal si no podemos serializar.
            return

        existing = await self.db.execute(
            select(IdempotencyKey).where(IdempotencyKey.IDK_Key == self.key)
        )
        rec = existing.scalar_one_or_none()
        if rec:
            rec.IDK_Endpoint = self.endpoint
            rec.IDK_Usuario = self.user_id
            rec.IDK_Request_Hash = self.body_hash
            rec.IDK_Response_Status = status_code
            rec.IDK_Response_Body = serializable
            rec.IDK_Creada_En = _utcnow_naive()
        else:
            self.db.add(IdempotencyKey(
                IDK_Key=self.key,
                IDK_Endpoint=self.endpoint,
                IDK_Usuario=self.user_id,
                IDK_Request_Hash=self.body_hash,
                IDK_Response_Status=status_code,
                IDK_Response_Body=serializable,
            ))
        # COMMIT explícito: el endpoint ya commiteó su lógica de negocio
        # antes de llamar store(), así que aquí solo confirmamos el cache.
        await self.db.commit()


def _to_jsonable(obj):
    """Convierte ORM objects / Pydantic / dicts / primitivos a estructura JSON-safe."""
    # Pydantic
    if hasattr(obj, "model_dump"):
        return _json_safe(obj.model_dump())
    # SQLAlchemy ORM (best-effort): tomamos columnas mapeadas
    if hasattr(obj, "__table__"):
        return _json_safe({c.name: getattr(obj, c.name) for c in obj.__table__.columns})
    return _json_safe(obj)


def _json_safe(obj):
    """Mismo helper que en governance: vuelve cualquier valor JSON-friendly."""
    from app.repositories.governance import _make_json_safe
    return _make_json_safe(obj)


_IDEMPOTENCY_KEY_RE = __import__("re").compile(r"^[A-Za-z0-9_\-]{16,128}$")


async def idempotency_guard(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=128),
) -> _IdempotencyGuard:
    """
    Dependencia FastAPI. Inyecta un objeto `idempotency` que el endpoint
    puede usar para `lookup()` y `store(body)`.

    SECURITY: si llega el header, debe cumplir `^[A-Za-z0-9_-]{16,128}$`.
    Rechazamos cualquier otra cosa para evitar envenenamiento de la tabla
    SYS_IDEMPOTENCY_KEY con caracteres raros / strings cortos repetidos.
    """
    if idempotency_key is not None and not _IDEMPOTENCY_KEY_RE.match(idempotency_key):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="INVALID_IDEMPOTENCY_KEY (must match ^[A-Za-z0-9_-]{16,128}$)",
        )
    body_bytes = await request.body()
    body_hash = hashlib.sha256(body_bytes).hexdigest() if body_bytes else "empty"
    return _IdempotencyGuard(
        key=idempotency_key,
        endpoint=str(request.url.path),
        body_hash=body_hash,
        user_id=current_user.USU_Usuario,
        db=db,
    )
