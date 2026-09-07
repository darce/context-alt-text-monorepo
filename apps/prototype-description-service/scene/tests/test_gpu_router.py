"""C3 GPU status and operator intent routes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth, require_write_access
from scene.interface_adapters.http.routers import gpu as gpu_routes

NOW = 1_786_125_000.0


@asynccontextmanager
async def _client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    auth: AuthContext | None = None,
) -> AsyncIterator[tuple[httpx.AsyncClient, Path, Path, Path]]:
    state_path = tmp_path / "gpu-state.json"
    load_path = tmp_path / "describe-load.json"
    intent_path = tmp_path / "gpu-intent.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(state_path))
    monkeypatch.setenv("ACX_DESCRIBE_LOAD_PATH", str(load_path))
    monkeypatch.setenv("ACX_GPU_INTENT_PATH", str(intent_path))
    monkeypatch.setattr(gpu_routes, "_now", lambda: NOW)

    app = FastAPI()
    app.include_router(gpu_routes.router, prefix="/scene")
    resolved_auth = auth or AuthContext(token="key", tenant_claim="tenant", enabled=True)

    async def _auth_override() -> AuthContext:
        return resolved_auth

    app.dependency_overrides[require_auth] = _auth_override
    app.dependency_overrides[require_write_access] = _auth_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, state_path, load_path, intent_path


def _write_snapshot(path: Path, *, age: float, state: str = "ready") -> None:
    path.write_text(
        json.dumps(
            {
                "state": state,
                "instance_id": "ocid1.instance.test",
                "written_at": NOW - age,
                "reason": None,
                "since": NOW - age - 10,
            }
        ),
        encoding="utf-8",
    )


def _write_load(path: Path, *, age: float, has_work: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "queue_depth": 1 if has_work else 0,
                "in_flight": 0,
                "batch_in_progress": False,
                "written_at": NOW - age,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_get_status_missing_snapshot_is_unknown_but_successful(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async with _client(monkeypatch, tmp_path) as (client, _state, _load, _intent):
        response = await client.get("/scene/gpu/status")

    assert response.status_code == 200
    body = response.json()
    assert body["gpu_state"]["state"] == "unknown"
    assert body["snapshot_age_seconds"] is None
    assert body["snapshot_fresh"] is False
    assert body["intent"] is None
    assert body["load"] == {"has_work": False, "written_at": None, "fresh": False}


@pytest.mark.asyncio
@pytest.mark.parametrize(("age", "fresh"), [(121.0, False), (30.0, True)])
async def test_get_status_reports_snapshot_age_and_freshness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, age: float, fresh: bool
) -> None:
    async with _client(monkeypatch, tmp_path) as (client, state_path, load_path, _intent):
        _write_snapshot(state_path, age=age)
        _write_load(load_path, age=age)
        response = await client.get("/scene/gpu/status")

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_age_seconds"] == age
    assert body["snapshot_fresh"] is fresh
    assert body["gpu_state"]["state"] == ("ready" if fresh else "unknown")
    assert body["load"]["has_work"] is True
    assert body["load"]["fresh"] is fresh


@pytest.mark.asyncio
async def test_get_status_nulls_invalid_additive_timestamps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async with _client(monkeypatch, tmp_path) as (client, state_path, _load, _intent):
        _write_snapshot(state_path, age=30.0)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload.update(
            {
                "intent_expires_at": "not-a-date",
                "lease_expires_at": "2026-09-06T23:00:00+01:00",
                "instance_running_since": "2026-09-06T22:00:00",
            }
        )
        state_path.write_text(json.dumps(payload), encoding="utf-8")

        response = await client.get("/scene/gpu/status")

    assert response.status_code == 200
    gpu_state = response.json()["gpu_state"]
    assert gpu_state["state"] == "ready"
    assert gpu_state["intent_expires_at"] is None
    assert gpu_state["lease_expires_at"] == "2026-09-06T22:00:00Z"
    assert gpu_state["instance_running_since"] is None


@pytest.mark.asyncio
async def test_get_status_drops_stale_snapshot_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async with _client(monkeypatch, tmp_path) as (client, state_path, _load, _intent):
        _write_snapshot(state_path, age=121.0)
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload.update(
            {
                "intent": "start",
                "intent_expires_at": "2026-09-06T23:00:00Z",
                "intent_status": "pending",
                "honoured_nonce": "stale-nonce",
                "lease_expires_at": "2026-09-06T23:00:00Z",
                "instance_running_since": "2026-09-06T22:00:00Z",
                "last_transition_reason": "operator",
            }
        )
        state_path.write_text(json.dumps(payload), encoding="utf-8")

        response = await client.get("/scene/gpu/status")

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_fresh"] is False
    assert body["gpu_state"] == {
        "state": "unknown",
        "instance_id": None,
        "written_at": None,
        "reason": None,
        "since": None,
        "intent": "auto",
        "intent_expires_at": None,
        "intent_status": "none",
        "honoured_nonce": None,
        "lease_expires_at": None,
        "instance_running_since": None,
        "last_transition_reason": "unknown",
    }


@pytest.mark.asyncio
async def test_get_status_treats_overflowing_intent_as_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async with _client(monkeypatch, tmp_path) as (client, _state, _load, intent_path):
        intent_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "action": "start",
                    "requested_at": "9999-12-31T23:59:59Z",
                    "expires_at": "9999-12-31T23:59:59Z",
                    "ttl_seconds": 60,
                    "requested_by": "operator",
                    "nonce": "8f8d2f40-39c0-4a91-8e4b-7e4d1e7b7d6a",
                }
            ),
            encoding="utf-8",
        )

        response = await client.get("/scene/gpu/status")

    assert response.status_code == 200
    assert response.json()["intent"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["start", "stop", "auto"])
async def test_post_intent_writes_file_and_returns_accepted_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, action: str
) -> None:
    async with _client(monkeypatch, tmp_path) as (client, _state, _load, intent_path):
        response = await client.post(
            "/scene/gpu/intent",
            json={"action": action, "ttl_seconds": 90, "requested_by": "operator"},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["intent"]["action"] == action
    assert body["intent"]["ttl_seconds"] == 90
    assert body["intent"]["requested_by"] == "operator"
    assert json.loads(intent_path.read_text(encoding="utf-8"))["action"] == action


@pytest.mark.asyncio
async def test_demo_tier_cannot_control_gpu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth = AuthContext(token="demo", tenant_claim="tenant", rate_limit_tier="demo", enabled=True)
    async with _client(monkeypatch, tmp_path, auth=auth) as (client, _state, _load, intent_path):
        response = await client.post("/scene/gpu/intent", json={"action": "start"})

    assert response.status_code == 403
    assert response.json()["detail"] == "gpu_control_forbidden"
    assert not intent_path.exists()


@pytest.mark.asyncio
async def test_unwritable_intent_directory_is_service_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async with _client(monkeypatch, tmp_path) as (client, _state, _load, _intent):
        def fail_write(*args, **kwargs):
            raise PermissionError("read-only intent directory")

        monkeypatch.setattr(gpu_routes, "write_gpu_intent", fail_write)
        response = await client.post("/scene/gpu/intent", json={"action": "stop"})

    assert response.status_code == 503
    assert response.json()["detail"] == "gpu_intent_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{"action": "restart"}, {"action": "start", "ttl_seconds": "60"}],
)
async def test_invalid_action_or_ttl_returns_422(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: dict[str, object]
) -> None:
    async with _client(monkeypatch, tmp_path) as (client, _state, _load, _intent):
        response = await client.post("/scene/gpu/intent", json=payload)

    assert response.status_code == 422
