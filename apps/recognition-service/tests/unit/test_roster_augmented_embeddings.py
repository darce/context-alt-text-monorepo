"""Unit tests for augmented embedding handling in the roster domain."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Dict, List, Optional

import pytest

from roster.domain.entities import RosterEntry, RosterImage
from roster.domain.interfaces import (
    DataValidationPort,
    EmbeddingStoragePort,
    RosterStoragePort,
)
from roster.domain.roster_service import RosterService


def _vector(val_a: float, val_b: float) -> List[float]:
    return [val_a, val_b]


class InMemoryRosterStorage(RosterStoragePort):
    """Simple in-memory storage adapter for testing."""

    def __init__(self) -> None:
        self._entries: Dict[str, Dict[str, RosterEntry]] = defaultdict(dict)

    def save_roster_entry(self, entry: RosterEntry, model: str) -> bool:
        self._entries.setdefault(model, {})
        self._entries[model][entry.unique_id] = deepcopy(entry)
        return True

    def load_roster_entries(self, model: str) -> List[RosterEntry]:
        entries = self._entries.get(model, {})
        return [deepcopy(entry) for entry in entries.values()]

    def get_roster_entry(self, unique_id: str, model: str) -> Optional[RosterEntry]:
        entry = self._entries.get(model, {}).get(unique_id)
        return deepcopy(entry) if entry else None

    def delete_roster_entry(self, unique_id: str, model: str) -> bool:
        model_entries = self._entries.get(model, {})
        if unique_id in model_entries:
            del model_entries[unique_id]
            return True
        return False

    def roster_exists(self, model: str) -> bool:
        return model in self._entries and bool(self._entries[model])

    def clear_roster(self, model: str) -> bool:
        if model in self._entries:
            self._entries[model] = {}
            return True
        return False

    def get_storage_info(self, model: str) -> Dict[str, Any]:
        return {"model": model, "entry_count": len(self._entries.get(model, {}))}


class TrackingEmbeddingStorage(EmbeddingStoragePort):
    """Embedding storage port that tracks saves for assertions."""

    def __init__(self) -> None:
        self.saved_models: List[str] = []
        self.saved_payloads: Dict[str, List[Dict[str, Any]]] = {}

    def save_embeddings(self, entries: List[RosterEntry], model: str) -> bool:
        self.saved_models.append(model)
        self.saved_payloads[model] = [entry.to_dict() for entry in entries]
        return True

    def load_embeddings(self, model: str) -> List[Dict[str, Any]]:
        return self.saved_payloads.get(model, [])


class AcceptingValidator(DataValidationPort):
    """Validator that accepts all data."""

    def __init__(self) -> None:
        self.validation_config = {"max_bulk_import_size": 1000}

    def validate_roster_entry(self, entry_data: Dict[str, Any]) -> List[str]:
        return []

    def validate_embedding(self, embedding: List[float], model: str) -> List[str]:
        return []

    def validate_bulk_import(self, import_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"errors": [], "warnings": []}


@pytest.fixture()
def roster_dependencies() -> Dict[str, Any]:
    storage = InMemoryRosterStorage()
    embeddings = TrackingEmbeddingStorage()
    validator = AcceptingValidator()
    service = RosterService(
        roster_storage=storage,
        data_validator=validator,
        embedding_storage=embeddings
    )
    return {"service": service, "storage": storage, "embeddings": embeddings}


def test_add_augmented_embedding_updates_weighted_aggregate(
    roster_dependencies: Dict[str, Any]
) -> None:
    model = "insightface_w600k"
    storage: InMemoryRosterStorage = roster_dependencies["storage"]
    service: RosterService = roster_dependencies["service"]
    embeddings: TrackingEmbeddingStorage = roster_dependencies["embeddings"]

    entry = RosterEntry(
        name="alice",
        reference_images=[RosterImage(embedding=_vector(1.0, 0.0))],
    )
    storage.save_roster_entry(entry, model)

    result = service.add_augmented_embedding(
        unique_id=entry.unique_id,
        model=model,
        embedding=_vector(0.0, 1.0),
        source="wordpress_confirm",
        observation_id="obs-1",
        metadata={
            "attachment_id": 42,
            "bbox": {"x": 10, "y": 20, "w": 30, "h": 40},
            "confidence": 0.70,
        },
    )
    assert result is True

    stored = storage.get_roster_entry(entry.unique_id, model)
    assert stored is not None
    augmented = stored.metadata.get("augmented_embeddings")
    assert isinstance(augmented, list)
    assert len(augmented) == 1
    record = augmented[0]
    assert record["observation_id"] == "obs-1"
    assert record["quality_tier"] == "medium"
    assert record["source"] == "wordpress_confirm"
    assert record["attachment_id"] == 42
    assert record["bbox"] == {"x": 10, "y": 20, "w": 30, "h": 40}
    assert record["confidence"] == pytest.approx(0.70, rel=1e-6)
    assert isinstance(record["created_at"], str)

    expected_weight = 1.0 + 0.8
    expected_vector = [
        pytest.approx((1.0 * 1.0 + 0.0 * 0.8) / expected_weight, rel=1e-6),
        pytest.approx((0.0 * 1.0 + 1.0 * 0.8) / expected_weight, rel=1e-6),
    ]
    assert stored.aggregate_embedding[0] == expected_vector[0]
    assert stored.aggregate_embedding[1] == expected_vector[1]
    assert embeddings.saved_models[-1] == model


def test_duplicate_observation_does_not_append_embedding(
    roster_dependencies: Dict[str, Any]
) -> None:
    model = "insightface_w600k"
    storage: InMemoryRosterStorage = roster_dependencies["storage"]
    service: RosterService = roster_dependencies["service"]
    embeddings: TrackingEmbeddingStorage = roster_dependencies["embeddings"]

    entry = RosterEntry(
        name="bruno",
        reference_images=[RosterImage(embedding=_vector(1.0, 0.0))],
    )
    storage.save_roster_entry(entry, model)

    first_result = service.add_augmented_embedding(
        unique_id=entry.unique_id,
        model=model,
        embedding=_vector(0.0, 1.0),
        source="wordpress_confirm",
        observation_id="dup-1",
        metadata={"confidence": 0.92},
    )
    assert first_result is True
    assert embeddings.saved_models[-1] == model

    second_result = service.add_augmented_embedding(
        unique_id=entry.unique_id,
        model=model,
        embedding=_vector(0.3, 0.7),
        source="wordpress_confirm",
        observation_id="dup-1",
        metadata={"confidence": 0.55},
    )
    assert second_result is False
    # No additional save should be recorded on duplicate attempt.
    assert embeddings.saved_models.count(model) == 1

    stored = storage.get_roster_entry(entry.unique_id, model)
    assert stored is not None
    augmented = stored.metadata.get("augmented_embeddings")
    assert isinstance(augmented, list)
    assert len(augmented) == 1
    assert augmented[0]["quality_tier"] == "high"

    expected = [pytest.approx(0.5, rel=1e-6), pytest.approx(0.5, rel=1e-6)]
    assert stored.aggregate_embedding[0] == expected[0]
    assert stored.aggregate_embedding[1] == expected[1]
