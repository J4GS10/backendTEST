"""Atomic reservation for ``Idempotency-Key`` protected commands."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Awaitable, Callable, Optional, TypeVar

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.errors import utcnow_naive as _utcnow_naive
from app.db.session import get_db
from app.models.governance import IdempotencyKey

IDEMPOTENCY_TTL_HOURS = 24
IDEMPOTENCY_PENDING = "PENDING"
IDEMPOTENCY_COMPLETED = "COMPLETED"
IDEMPOTENCY_FAILED = "FAILED"
T = TypeVar("T")


@dataclass
class _IdempotencyGuard:
    key: Optional[str]
    endpoint: str
    body_hash: str
    user_id: Any
    db: AsyncSession

    async def execute(
        self, operation: Callable[[], Awaitable[T]], *, status_code: int
    ) -> T | dict:
        """Reserve the key, run the command, and cache only a committed result."""
        cached = await self.lookup()
        if cached is not None:
            return cached
        try:
            result = await operation()
        except Exception:
            await self.fail()
            raise
        await self.store(result, status_code=status_code)
        return result

    async def lookup(self) -> Optional[dict]:
        """Reserve a new key or return its completed response."""
        if not self.key:
            return None
        rec = await self._get_record()
        if rec is None:
            return await self._reserve()

        self._validate_owner_and_request(rec)
        if rec.IDK_Creada_En < _utcnow_naive() - timedelta(hours=IDEMPOTENCY_TTL_HOURS):
            await self.db.execute(
                delete(IdempotencyKey).where(IdempotencyKey.IDK_Key == self.key)
            )
            await self.db.commit()
            return await self._reserve()

        if rec.IDK_Estado == IDEMPOTENCY_COMPLETED:
            return rec.IDK_Response_Body or {}
        if rec.IDK_Estado == IDEMPOTENCY_FAILED:
            rec.IDK_Estado = IDEMPOTENCY_PENDING
            rec.IDK_Response_Status = 202
            rec.IDK_Response_Body = None
            rec.IDK_Creada_En = _utcnow_naive()
            await self.db.commit()
            return None
        raise HTTPException(409, "IDEMPOTENCY_REQUEST_IN_PROGRESS")

    async def store(self, body: Any, status_code: int = 200) -> None:
        """Complete an existing reservation after the service transaction commits."""
        if not self.key:
            return
        rec = await self._get_record()
        if rec is None:
            raise RuntimeError("IDEMPOTENCY_RESERVATION_NOT_FOUND")
        self._validate_owner_and_request(rec)
        rec.IDK_Estado = IDEMPOTENCY_COMPLETED
        rec.IDK_Response_Status = status_code
        rec.IDK_Response_Body = _to_jsonable(body)
        rec.IDK_Creada_En = _utcnow_naive()
        await self.db.commit()

    async def fail(self) -> None:
        """Release a reservation when the business command rolls back."""
        if not self.key:
            return
        rec = await self._get_record()
        if rec is None:
            return
        self._validate_owner_and_request(rec)
        if rec.IDK_Estado == IDEMPOTENCY_PENDING:
            await self.db.delete(rec)
            await self.db.commit()

    async def _get_record(self) -> Optional[IdempotencyKey]:
        result = await self.db.execute(
            select(IdempotencyKey).where(IdempotencyKey.IDK_Key == self.key)
        )
        return result.scalar_one_or_none()

    async def _reserve(self) -> Optional[dict]:
        assert self.key is not None
        self.db.add(
            IdempotencyKey(
                IDK_Key=self.key,
                IDK_Endpoint=self.endpoint,
                IDK_Usuario=self.user_id,
                IDK_Request_Hash=self.body_hash,
                IDK_Estado=IDEMPOTENCY_PENDING,
                IDK_Response_Status=202,
                IDK_Response_Body=None,
            )
        )
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            # A concurrent caller won the insert. Re-read its state instead of
            # executing the business command a second time.
            return await self.lookup()
        return None

    def _validate_owner_and_request(self, rec: IdempotencyKey) -> None:
        if str(rec.IDK_Usuario) != str(self.user_id) or rec.IDK_Endpoint != self.endpoint:
            raise HTTPException(409, "IDEMPOTENCY_KEY_CONFLICT_DIFFERENT_OWNER")
        if rec.IDK_Request_Hash != self.body_hash:
            raise HTTPException(409, "IDEMPOTENCY_KEY_CONFLICT_DIFFERENT_BODY")


def _to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return _json_safe(obj.model_dump())
    if hasattr(obj, "__table__"):
        return _json_safe({column.name: getattr(obj, column.name) for column in obj.__table__.columns})
    return _json_safe(obj)


def _json_safe(obj: Any) -> Any:
    from app.repositories.governance import _make_json_safe

    return _make_json_safe(obj)


_IDEMPOTENCY_KEY_RE = __import__("re").compile(r"^[A-Za-z0-9_\-]{16,128}$")


async def idempotency_guard(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=128),
) -> _IdempotencyGuard:
    if idempotency_key is not None and not _IDEMPOTENCY_KEY_RE.match(idempotency_key):
        raise HTTPException(
            status_code=400,
            detail="INVALID_IDEMPOTENCY_KEY (must match ^[A-Za-z0-9_-]{16,128}$)",
        )
    body_bytes = await request.body()
    return _IdempotencyGuard(
        key=idempotency_key,
        endpoint=str(request.url.path),
        body_hash=hashlib.sha256(body_bytes).hexdigest() if body_bytes else "empty",
        user_id=current_user.USU_Usuario,
        db=db,
    )
