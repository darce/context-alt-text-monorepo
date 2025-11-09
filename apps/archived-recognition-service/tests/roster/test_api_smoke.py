"""Smoke and regression tests for the roster FastAPI router."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


MODEL = "adaface_ir101"


@pytest.fixture()
def sample_entry_payload() -> dict[str, Any]:
    """Return a canonical payload for roster POST requests."""
    return {
        "name": "test_person",
        "embedding": [0.1] * 512,
        "metadata": {"role": "tester"},
    }


def test_health_check(api_client: TestClient) -> None:
    response = api_client.get("/api/v0/roster/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "healthy"
    assert "version" in payload
    assert MODEL in payload["models"]


def test_add_and_get_roster_entry(api_client: TestClient, sample_entry_payload: dict[str, Any]) -> None:
    create = api_client.post(f"/api/v0/roster/{MODEL}/upsert", json=sample_entry_payload)
    assert create.status_code == 200

    created = create.json()["entry"]
    assert created["name"] == sample_entry_payload["name"]
    assert created["unique_id"]
    unique_id = created["unique_id"]

    show = api_client.get(f"/api/v0/roster/{MODEL}/{unique_id}")
    assert show.status_code == 200
    record = show.json()["entry"]
    assert record["name"] == sample_entry_payload["name"]


def test_get_roster_entries_and_stats(api_client: TestClient, sample_entry_payload: dict[str, Any]) -> None:
    api_client.post(f"/api/v0/roster/{MODEL}/upsert", json=sample_entry_payload)

    listing = api_client.get(f"/api/v0/roster/{MODEL}", params={"include_embeddings": True})
    assert listing.status_code == 200

    data = listing.json()
    assert data["count"] == 1
    assert data["entries"][0]["aggregate_embedding"] is not None

    stats = api_client.get(f"/api/v0/roster/{MODEL}/stats")
    assert stats.status_code == 200
    stats_payload = stats.json()
    assert stats_payload["entry_count"] == 1
    assert stats_payload["success"] is True


def test_update_and_clear_roster(api_client: TestClient, sample_entry_payload: dict[str, Any]) -> None:
    create = api_client.post(f"/api/v0/roster/{MODEL}/upsert", json=sample_entry_payload)
    unique_id = create.json()["entry"]["unique_id"]

    update_payload = {
        "embedding": [0.2] * 512,
        "metadata": {"role": "tester", "updated": True},
    }
    update = api_client.put(f"/api/v0/roster/{MODEL}/{unique_id}", json=update_payload)
    assert update.status_code == 200
    assert update.json()["entry"]["image_count"] == 2

    clear = api_client.delete(f"/api/v0/roster/{MODEL}/clear")
    assert clear.status_code == 200
    listing = api_client.get(f"/api/v0/roster/{MODEL}")
    assert listing.json()["count"] == 0


def test_bulk_add_and_delete(api_client: TestClient) -> None:
    bulk_payload = {
        "entries": [
            {"name": "person1", "embedding": [0.1] * 512},
            {"name": "person2", "embedding": [0.2] * 512},
        ]
    }

    bulk = api_client.post(f"/api/v0/roster/{MODEL}/bulk", json=bulk_payload)
    assert bulk.status_code == 200
    body = bulk.json()
    assert body["stats"]["successful"] == 2

    # Delete one of the entries
    roster = api_client.get(f"/api/v0/roster/{MODEL}")
    first_id = roster.json()["entries"][0]["unique_id"]

    delete = api_client.delete(f"/api/v0/roster/{MODEL}/{first_id}")
    assert delete.status_code == 200
    assert delete.json()["deleted_id"] == first_id


def test_invalid_model_returns_error(api_client: TestClient, sample_entry_payload: dict[str, Any]) -> None:
    response = api_client.post("/api/v0/roster/invalid_model/upsert", json=sample_entry_payload)
    assert response.status_code == 400


def test_request_validation_errors(api_client: TestClient) -> None:
    missing_fields = api_client.post(
        f"/api/v0/roster/{MODEL}/upsert",
        json={"embedding": [0.1] * 512},
    )
    assert missing_fields.status_code == 422

    invalid_embedding = api_client.post(
        f"/api/v0/roster/{MODEL}/upsert",
        json={"name": "no-vector", "embedding": []},
    )
    assert invalid_embedding.status_code == 422
