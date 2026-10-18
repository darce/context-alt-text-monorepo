"""Regression coverage for usage reservations across GPU readiness holds."""

import time
import uuid

from recognition.domain.portal_contracts import UsageTicket
from scene.application import gpu_state as gpu_state_mod
from scene.tests import test_describe_route as route_tests


class _ReplayAdmission:
    """Replay a released idempotency key without reacquiring its allowance."""

    def __init__(self) -> None:
        self.tickets: dict[str, UsageTicket] = {}
        self.statuses: dict[str, str] = {}

    async def reserve(
        self,
        tenant_id,
        *,
        idempotency_key,
        job_id,
        cost_units,
        operation_id=None,
        request_fingerprint=None,
        queue_bytes=0,
    ):
        del queue_bytes
        key = operation_id or idempotency_key
        existing = self.tickets.get(key)
        if existing is not None:
            assert existing.request_fingerprint == (request_fingerprint or "")
            return existing
        ticket = UsageTicket(
            uuid.uuid4(),
            tenant_id,
            idempotency_key,
            cost_units,
            operation_id=key,
            request_fingerprint=request_fingerprint or "",
            job_id=job_id,
            fence_token="fence-readiness-hold",
        )
        self.tickets[key] = ticket
        self.statuses[key] = "reserved"
        return ticket

    async def commit(self, ticket: UsageTicket) -> None:
        del ticket

    async def release(self, ticket: UsageTicket) -> None:
        del ticket

    async def commit_fenced(self, ticket: UsageTicket, *, fence_token: str) -> None:
        assert fence_token == ticket.fence_token
        key = str(ticket.operation_id)
        if self.statuses.get(key) == "reserved":
            self.statuses[key] = "committed"

    async def release_fenced(self, ticket: UsageTicket, *, fence_token: str) -> None:
        assert fence_token == ticket.fence_token
        self.statuses[str(ticket.operation_id)] = "released"


def test_gpu_readiness_hold_keeps_usage_reservation_for_identical_retry(monkeypatch, tmp_path):
    state_path, _, _, _ = route_tests._gpu_env(monkeypatch, tmp_path, state="stopped")
    adapter = route_tests._GpuAdapter()
    admission = _ReplayAdmission()
    monkeypatch.setattr(route_tests, "_PassAdmission", lambda: admission)

    with route_tests._client(adapter=adapter) as client:
        operation_id = "readiness-hold-retry-operation"
        held = route_tests._post(client, route_tests.TENANT_ID, extra_data={"operation_id": operation_id})
        assert held.status_code == 503, held.text
        assert held.json()["detail"]["operation_id"] == operation_id
        assert route_tests._lease_state(client, operation_id) == "active"

        gpu_state_mod.reset_gpu_state_observation_for_tests()
        route_tests._write_gpu_state(state_path, state="ready", now=time.time())
        retried = route_tests._post(client, route_tests.TENANT_ID, extra_data={"operation_id": operation_id})
        assert retried.status_code == 200, retried.text
        assert adapter.calls == 1

    assert admission.statuses[operation_id] == "committed"
