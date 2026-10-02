"""Deadline coverage for operator entitlement tenant-context setup."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from recognition.interface_adapters.http.deps import operator_authorization as operator_authorization_module
from recognition.interface_adapters.http.deps.operator_authorization import (
    OPERATOR_UNAVAILABLE_DETAIL,
    authorize_operator_control,
    get_clustering_operator_entitlement_repository,
)

TENANT_ID = "11111111-1111-1111-1111-111111111111"


class _Session:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.close_calls = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class _EntitlementRepository:
    def __init__(self, session: _Session) -> None:
        self.session = session
        now = datetime.now(tz=UTC)
        self.row = SimpleNamespace(
            tenant_id=TENANT_ID,
            status="paid_active",
            period_start=now - timedelta(days=1),
            period_end=now + timedelta(days=1),
        )
        self.get_calls = 0

    async def get(self, tenant_id: Any, *, for_update: bool = False) -> Any:
        del tenant_id, for_update
        self.get_calls += 1
        return self.row


async def _stall_until_cancelled(started: asyncio.Event, never: asyncio.Event) -> None:
    started.set()
    await never.wait()


@pytest.mark.asyncio
async def test_authorization_tenant_context_timeout_is_unavailable_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    repository = _EntitlementRepository(session)
    started = asyncio.Event()
    never = asyncio.Event()

    async def _set_tenant_context(_session: Any, _tenant_id: Any) -> None:
        await _stall_until_cancelled(started, never)

    monkeypatch.setattr(operator_authorization_module, "_READ_TIMEOUT_S", 0.01)
    monkeypatch.setattr(operator_authorization_module, "set_tenant_context", _set_tenant_context)
    auth = SimpleNamespace(enabled=True, tenant_claim=TENANT_ID, is_admin=False)

    authorization = asyncio.create_task(
        authorize_operator_control(auth, session=session, repository=repository)
    )
    await asyncio.wait_for(started.wait(), timeout=0.2)
    with pytest.raises(HTTPException) as exc_info:
        await asyncio.wait_for(authorization, timeout=0.2)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == OPERATOR_UNAVAILABLE_DETAIL
    assert session.rollback_calls == 1
    assert repository.get_calls == 0


@pytest.mark.asyncio
async def test_clustering_repository_tenant_context_timeout_is_unavailable_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    started = asyncio.Event()
    never = asyncio.Event()

    async def _set_tenant_context(_session: Any, _tenant_id: Any) -> None:
        await _stall_until_cancelled(started, never)

    monkeypatch.setattr(operator_authorization_module, "_READ_TIMEOUT_S", 0.01)
    monkeypatch.setattr(operator_authorization_module, "clustering_async_session_factory", lambda: session)
    monkeypatch.setattr(operator_authorization_module, "set_tenant_context", _set_tenant_context)
    monkeypatch.setattr(
        operator_authorization_module,
        "_repository_from_session",
        lambda _session: pytest.fail("repository construction should follow tenant context"),
    )

    repository = await get_clustering_operator_entitlement_repository()
    lookup = asyncio.create_task(repository.get(TENANT_ID))
    await asyncio.wait_for(started.wait(), timeout=0.2)
    with pytest.raises(HTTPException) as exc_info:
        await asyncio.wait_for(lookup, timeout=0.2)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == OPERATOR_UNAVAILABLE_DETAIL
    assert session.rollback_calls == 1
    assert session.close_calls == 1
