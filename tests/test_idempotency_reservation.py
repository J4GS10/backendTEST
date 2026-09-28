"""Concurrency-safe idempotency reservation behaviour."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.idempotency import (
    IDEMPOTENCY_COMPLETED,
    IDEMPOTENCY_PENDING,
    _IdempotencyGuard,
)
from app.models.governance import IdempotencyKey


def _guard(session, user_id, key: str) -> _IdempotencyGuard:
    return _IdempotencyGuard(
        key=key,
        endpoint="/api/v1/test-command",
        body_hash="request-hash",
        user_id=user_id,
        db=session,
    )


@pytest.mark.asyncio
async def test_pending_reservation_blocks_duplicate_and_caches_completion(session, sa_user):
    key = "reservation-test-key-0001"
    first = _guard(session, sa_user.USU_Usuario, key)

    assert await first.lookup() is None
    reservation = await session.scalar(
        select(IdempotencyKey).where(IdempotencyKey.IDK_Key == key)
    )
    assert reservation is not None
    assert reservation.IDK_Estado == IDEMPOTENCY_PENDING

    with pytest.raises(HTTPException) as error:
        await _guard(session, sa_user.USU_Usuario, key).lookup()
    assert error.value.status_code == 409
    assert error.value.detail == "IDEMPOTENCY_REQUEST_IN_PROGRESS"

    await first.store({"created": True, "id": "abc"}, status_code=201)
    cached = await _guard(session, sa_user.USU_Usuario, key).lookup()
    assert cached == {"created": True, "id": "abc"}

    completed = await session.scalar(
        select(IdempotencyKey).where(IdempotencyKey.IDK_Key == key)
    )
    assert completed is not None
    assert completed.IDK_Estado == IDEMPOTENCY_COMPLETED
    assert completed.IDK_Response_Status == 201


@pytest.mark.asyncio
async def test_failed_command_releases_pending_reservation(session, sa_user):
    key = "reservation-test-key-0002"
    guard = _guard(session, sa_user.USU_Usuario, key)

    assert await guard.lookup() is None
    await guard.fail()

    assert await session.scalar(
        select(IdempotencyKey).where(IdempotencyKey.IDK_Key == key)
    ) is None
    assert await _guard(session, sa_user.USU_Usuario, key).lookup() is None
