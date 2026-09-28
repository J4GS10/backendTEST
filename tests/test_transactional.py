"""Unit tests for the service transaction boundary."""
import pytest
from fastapi import HTTPException

from app.core.transactional import schedule_post_commit, transactional


class _FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _NestedService:
    def __init__(self):
        self.db = _FakeSession()
        self.events: list[str] = []

    @transactional
    async def inner(self):
        schedule_post_commit(self, lambda: self.events.append("hook"))

    @transactional
    async def outer(self):
        self.events.append("before")
        await self.inner()
        self.events.append("after")

    @transactional
    async def fails(self):
        schedule_post_commit(self, lambda: self.events.append("unexpected"))
        raise HTTPException(400, "BUSINESS_RULE_FAILED")


@pytest.mark.asyncio
async def test_nested_transaction_commits_once_and_runs_hook_after_commit():
    service = _NestedService()

    await service.outer()

    assert service.db.commits == 1
    assert service.db.rollbacks == 0
    assert service.events == ["before", "after", "hook"]


@pytest.mark.asyncio
async def test_rollback_discards_post_commit_hooks():
    service = _NestedService()

    with pytest.raises(HTTPException, match="BUSINESS_RULE_FAILED"):
        await service.fails()

    assert service.db.commits == 0
    assert service.db.rollbacks == 1
    assert service.events == []
