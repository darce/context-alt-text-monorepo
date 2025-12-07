"""API tests for diagnostics endpoints (Phase 5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from recognition.interface_adapters.http import dependencies


def test_diagnostics_returns_empty_list_by_default(api_client) -> None:
    store = dependencies.get_decision_store()
    store.clear()

    resp = api_client.get("/recognition/diagnostics/decisions")

    assert resp.status_code == 200
    assert resp.json() == []


def test_diagnostics_returns_logged_decisions(api_client) -> None:
    store = dependencies.get_decision_store()
    store.clear()
    store.add({"id": str(uuid.uuid4()), "decision": "accept"})

    resp = api_client.get("/recognition/diagnostics/decisions")

    assert resp.status_code == 200
    body = resp.json()
    assert body and body[0]["decision"] == "accept"


def test_diagnostics_filters_and_paginates_decisions(api_client) -> None:
    store = dependencies.get_decision_store()
    store.clear()
    now = datetime.now(tz=UTC)

    store.add(
        {
            "id": "1",
            "tenant_id": "tenant-a",
            "decision": "accept",
            "cluster_id": "cluster-1",
            "timestamp": (now - timedelta(days=2)).isoformat(),
        }
    )
    store.add(
        {
            "id": "2",
            "tenant_id": "tenant-b",
            "decision": "reject",
            "cluster_id": "cluster-2",
            "timestamp": (now - timedelta(days=1)).isoformat(),
        }
    )
    store.add(
        {
            "id": "3",
            "tenant_id": "tenant-a",
            "decision": "reject",
            "cluster_id": "cluster-1",
            "timestamp": now.isoformat(),
        }
    )

    resp = api_client.get(
        "/recognition/diagnostics/decisions",
        params={
            "tenant_id": "tenant-a",
            "outcome": "reject",
            "cluster_id": "cluster-1",
            "start_at": (now - timedelta(hours=12)).isoformat(),
            "limit": 1,
            "offset": 0,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "3"
