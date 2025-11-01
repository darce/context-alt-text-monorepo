"""
Tests for POST /api/v0/roster/{unique_id}/augment endpoint.

Validates progressive learning functionality:
- Adding embeddings to existing roster entries with observation_id tracking
- Duplicate prevention (same observation_id)
- FAISS index reload scheduling after augmentation
"""

from __future__ import annotations

import time
from typing import Any
from unittest import mock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.main import router as api_router
from api.dependencies import get_roster_service


def create_test_client(roster_service):
    """Create FastAPI test client with injected roster service."""
    app = FastAPI()
    app.state.is_initializing = False
    app.state.initialization_complete = True
    app.include_router(api_router, prefix="/api/v0")
    app.dependency_overrides[get_roster_service] = lambda: roster_service
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_synced_observations():
    """Reset progressive-learning observation cache before each test."""
    from api.routes import roster

    roster._SYNCED_OBSERVATIONS.clear()
    yield
    roster._SYNCED_OBSERVATIONS.clear()


@pytest.fixture()
def empty_roster():
    """Mock roster service used to capture method calls."""
    mock_service = mock.Mock()
    roster_entries: dict[str, Any] = {}

    def mock_add_entry(name, embedding, model, metadata=None, image_path=None):
        entry = mock.Mock()
        entry.unique_id = name
        entry.name = name
        entry.display_name = metadata.get("display_name", name) if metadata else name
        entry.aggregate_embedding = embedding
        entry.metadata = metadata or {}
        entry.created_timestamp = time.time()
        entry.updated_timestamp = time.time()
        entry.image_count = 1
        entry.reference_images = []
        roster_entries[name] = entry
        return entry

    def mock_get_entry(unique_id, model):
        return roster_entries.get(unique_id)

    def mock_get_entries(model):
        return list(roster_entries.values())

    def mock_add_augmented_embedding(unique_id, model, embedding, source, observation_id, metadata=None):
        entry = roster_entries.get(unique_id)
        if not entry:
            return False

        augmented = entry.metadata.setdefault("augmented_embeddings", [])
        if any(item.get("observation_id") == observation_id for item in augmented):
            return False

        record = {"embedding": embedding, "source": source, "observation_id": observation_id}
        if metadata:
            record.update(metadata)
            entry.metadata.update(metadata)
        augmented.append(record)
        entry.updated_timestamp = time.time()
        return True

    mock_service.add_entry.side_effect = mock_add_entry
    mock_service.get_entry.side_effect = mock_get_entry
    mock_service.get_entries.side_effect = mock_get_entries
    mock_service.add_augmented_embedding.side_effect = mock_add_augmented_embedding

    return mock_service


class TestAugmentEndpoint:
    """Test suite for progressive-learning augmentation endpoint."""

    @staticmethod
    def _seed_entry(roster_service) -> None:
        base_embedding = np.random.rand(512).tolist()
        roster_service.add_entry("ana-rodriguez", base_embedding, "insightface_w600k")

    def test_augment_success(self, empty_roster):
        client = create_test_client(empty_roster)
        self._seed_entry(empty_roster)

        response = client.post(
            "/api/v0/roster/ana-rodriguez/augment",
            json={"observation_id": "obs-123", "embedding": np.random.rand(512).tolist()},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["roster_entry"]["unique_id"] == "ana-rodriguez"
        assert body["roster_entry"]["embedding_count"] >= 1
        assert "index_reloaded" in body
        assert body["idempotency_key"].startswith("augment:ana-rodriguez")

    def test_duplicate_observation_rejected(self, empty_roster):
        client = create_test_client(empty_roster)
        self._seed_entry(empty_roster)
        payload = {"observation_id": "obs-dup", "embedding": np.random.rand(512).tolist()}

        assert client.post("/api/v0/roster/ana-rodriguez/augment", json=payload).status_code == 200
        dup_response = client.post("/api/v0/roster/ana-rodriguez/augment", json=payload)
        assert dup_response.status_code == 409
        assert "already synced" in dup_response.json()["detail"].lower()

    def test_roster_not_found(self, empty_roster):
        client = create_test_client(empty_roster)
        response = client.post(
            "/api/v0/roster/missing-entry/augment",
            json={"observation_id": "obs-404", "embedding": np.random.rand(512).tolist()},
        )
        assert response.status_code == 404

    def test_invalid_embedding(self, empty_roster):
        client = create_test_client(empty_roster)
        self._seed_entry(empty_roster)

        response = client.post(
            "/api/v0/roster/ana-rodriguez/augment",
            json={"observation_id": "obs-invalid", "embedding": []},
        )
        assert response.status_code == 422

    def test_missing_fields(self, empty_roster):
        client = create_test_client(empty_roster)
        self._seed_entry(empty_roster)

        response = client.post(
            "/api/v0/roster/ana-rodriguez/augment",
            json={"embedding": np.random.rand(512).tolist()},
        )
        assert response.status_code == 422

        response = client.post(
            "/api/v0/roster/ana-rodriguez/augment",
            json={"observation_id": "obs-missing"},
        )
        assert response.status_code == 422

    def test_progressive_learning_invocations(self, empty_roster):
        client = create_test_client(empty_roster)
        self._seed_entry(empty_roster)

        embedding = np.random.rand(512).tolist()
        response = client.post(
            "/api/v0/roster/ana-rodriguez/augment",
            json={"observation_id": "obs-555", "embedding": embedding},
        )
        assert response.status_code == 200

        empty_roster.add_augmented_embedding.assert_called()
        call_args = empty_roster.add_augmented_embedding.call_args
        assert call_args.kwargs["unique_id"] == "ana-rodriguez"
        assert call_args.kwargs["embedding"] == embedding
        assert call_args.kwargs["observation_id"] == "obs-555"

    def test_metadata_forwarding(self, empty_roster):
        client = create_test_client(empty_roster)
        self._seed_entry(empty_roster)

        response = client.post(
            "/api/v0/roster/ana-rodriguez/augment",
            json={
                "observation_id": "obs-222",
                "embedding": np.random.rand(512).tolist(),
                "attachment_id": 42,
                "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                "confidence": 0.91,
            },
        )
        assert response.status_code == 200
        empty_roster.add_augmented_embedding.assert_called()
        metadata = empty_roster.add_augmented_embedding.call_args.kwargs["metadata"]
        assert metadata["attachment_id"] == 42
        assert metadata["confidence"] == 0.91

    def test_idempotency_key_returns_cached_response(self, empty_roster):
        client = create_test_client(empty_roster)
        self._seed_entry(empty_roster)

        payload = {
            "observation_id": "obs-idem",
            "embedding": np.random.rand(512).tolist(),
            "idempotency_key": "idem-123",
        }

        first = client.post("/api/v0/roster/ana-rodriguez/augment", json=payload)
        assert first.status_code == 200
        first_calls = empty_roster.add_augmented_embedding.call_count

        second = client.post("/api/v0/roster/ana-rodriguez/augment", json=payload)
        assert second.status_code == 200
        assert empty_roster.add_augmented_embedding.call_count == first_calls
        assert second.json()["success"] is True
