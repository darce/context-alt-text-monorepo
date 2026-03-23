"""Service tests for ScheduledDisposalWorker."""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from recognition.domain.services.purge_service import ScheduledDisposalWorker


def _make_session_factory(tenant_ids: list[uuid.UUID]) -> MagicMock:
    """Build a fake async_sessionmaker that returns tenant IDs on the query session."""
    scalars_result = MagicMock()
    scalars_result.all.return_value = tenant_ids

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_result

    query_session = AsyncMock()
    query_session.__aenter__ = AsyncMock(return_value=query_session)
    query_session.__aexit__ = AsyncMock(return_value=False)
    query_session.execute = AsyncMock(return_value=execute_result)

    purge_session = AsyncMock()
    purge_session.__aenter__ = AsyncMock(return_value=purge_session)
    purge_session.__aexit__ = AsyncMock(return_value=False)

    sessions_issued = [0]

    def _factory():
        sessions_issued[0] += 1
        if sessions_issued[0] == 1:
            return query_session
        return purge_session

    return MagicMock(side_effect=_factory)


@pytest.mark.asyncio
async def test_run_once_calls_purge_for_each_dispose_after_ack_tenant() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    purge_results = [
        {"tenant_id": str(tenant_a), "deleted_counts": {"media_identities": 2}},
        {"tenant_id": str(tenant_b), "deleted_counts": {"media_identities": 5}},
    ]
    call_index = [0]

    async def _fake_purge(tenant_id: str, actor: str, scope: str = "disposed") -> dict:
        result = purge_results[call_index[0]]
        call_index[0] += 1
        return result

    with patch(
        "recognition.domain.services.purge_service.TenantPurgeService.purge_tenant_data",
        side_effect=_fake_purge,
    ):
        factory = _make_session_factory([tenant_a, tenant_b])
        worker = ScheduledDisposalWorker(session_factory=factory, actor="test_worker")
        result = await worker.run_once()

    assert result["tenants_processed"] == 2
    results_list = result["results"]
    assert isinstance(results_list, list)
    assert len(results_list) == 2


@pytest.mark.asyncio
async def test_run_once_skips_tenant_on_purge_error_and_continues() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    call_index = [0]

    async def _fake_purge(tenant_id: str, actor: str, scope: str = "disposed") -> dict:
        idx = call_index[0]
        call_index[0] += 1
        if idx == 0:
            raise RuntimeError("DB error for tenant A")
        return {"tenant_id": tenant_id, "deleted_counts": {"media_identities": 3}}

    with patch(
        "recognition.domain.services.purge_service.TenantPurgeService.purge_tenant_data",
        side_effect=_fake_purge,
    ):
        factory = _make_session_factory([tenant_a, tenant_b])
        worker = ScheduledDisposalWorker(session_factory=factory, actor="test_worker")
        result = await worker.run_once()

    # Only tenant_b succeeded; tenant_a was skipped after error
    assert result["tenants_processed"] == 1


@pytest.mark.asyncio
async def test_run_once_returns_zero_when_no_eligible_tenants() -> None:
    with patch(
        "recognition.domain.services.purge_service.TenantPurgeService.purge_tenant_data",
        new_callable=AsyncMock,
    ) as mock_purge:
        factory = _make_session_factory([])
        worker = ScheduledDisposalWorker(session_factory=factory, actor="test_worker")
        result = await worker.run_once()

    assert result["tenants_processed"] == 0
    mock_purge.assert_not_called()
