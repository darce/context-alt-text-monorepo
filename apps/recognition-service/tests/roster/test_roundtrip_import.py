"""Round-trip persistence tests for the roster domain service."""

from __future__ import annotations

from typing import Any

import pytest

from roster.adapters import (
    DataValidationAdapter,
    EmbeddingStorageAdapter,
    FileRosterStorageAdapter,
)
from roster.domain import RosterService
from roster.config import reload_config


@pytest.fixture()
def roster_service(roster_data_dir: str) -> RosterService:
    """Create a roster service wired to filesystem adapters."""
    # Ensure configuration picks up the temp directory fixture
    reload_config()
    return RosterService(
        roster_storage=FileRosterStorageAdapter(),
        embedding_storage=EmbeddingStorageAdapter(),
        data_validator=DataValidationAdapter(),
    )


def _make_embedding(seed: float) -> list[float]:
    return [seed] * 512


def test_round_trip_single_entry(roster_service: RosterService) -> None:
    model = "adaface_ir101"
    person = roster_service.add_entry("alice", _make_embedding(0.1), model, {"team": "alpha"})
    assert person is not None

    fetched = roster_service.get_entry(person.unique_id, model)
    assert fetched is not None
    assert fetched.name == "alice"
    assert fetched.metadata["team"] == "alpha"
    assert fetched.aggregate_embedding == _make_embedding(0.1)


def test_round_trip_multiple_entries(roster_service: RosterService) -> None:
    model = "adaface_ir101"
    for idx in range(3):
        roster_service.add_entry(f"person{idx}", _make_embedding(0.2 + idx / 10), model, {"idx": idx})

    entries = roster_service.get_entries(model)
    assert len(entries) == 3
    assert sorted(entry.metadata["idx"] for entry in entries) == [0, 1, 2]


def test_round_trip_bulk_import(roster_service: RosterService) -> None:
    model = "adaface_ir101"
    payload = [
        {"name": f"bulk_{idx}", "embedding": _make_embedding(0.3 + idx / 10), "metadata": {"batch": 1}}
        for idx in range(5)
    ]

    added = roster_service.add_entries_bulk(payload, model)
    assert len(added) == 5

    roster = roster_service.get_entries(model)
    assert len(roster) == 5
    assert {entry.name for entry in roster} == set(added)


def test_round_trip_update_entry(roster_service: RosterService) -> None:
    model = "adaface_ir101"
    created = roster_service.add_entry("charlie", _make_embedding(0.5), model)
    assert created is not None

    success = roster_service.update_entry(
        created.unique_id,
        model,
        embedding=_make_embedding(0.6),
        metadata={"role": "lead"},
    )
    assert success is True

    updated = roster_service.get_entry(created.unique_id, model)
    assert updated is not None
    assert updated.image_count == 2
    assert updated.metadata["role"] == "lead"


def test_round_trip_delete_entry(roster_service: RosterService) -> None:
    model = "adaface_ir101"
    person = roster_service.add_entry("delta", _make_embedding(0.4), model)
    assert person is not None

    deleted = roster_service.delete_entry(person.unique_id, model)
    assert deleted is True
    assert roster_service.get_entry(person.unique_id, model) is None


def test_round_trip_clear_roster(roster_service: RosterService) -> None:
    model = "adaface_ir101"
    for idx in range(2):
        roster_service.add_entry(f"clear_{idx}", _make_embedding(0.7 + idx / 10), model)

    assert roster_service.get_entry_count(model) == 2
    roster_service.clear_roster(model)
    assert roster_service.get_entry_count(model) == 0


def test_round_trip_persistence_across_instances(
    roster_service: RosterService,
    roster_data_dir: str,
) -> None:
    model = "adaface_ir101"
    entry = roster_service.add_entry("echo", _make_embedding(0.9), model, {"persist": True})
    assert entry is not None

    # New service reading the same data directory should see the entry
    reload_config()
    next_service = RosterService(
        roster_storage=FileRosterStorageAdapter(),
        embedding_storage=EmbeddingStorageAdapter(),
        data_validator=DataValidationAdapter(),
    )

    retrieved = next_service.get_entry(entry.unique_id, model)
    assert retrieved is not None
    assert retrieved.metadata["persist"] is True


def test_bulk_import_rejects_invalid_entries(roster_service: RosterService) -> None:
    model = "adaface_ir101"
    payload: list[dict[str, Any]] = [
        {"name": "valid", "embedding": _make_embedding(0.1)},
        {"name": "", "embedding": _make_embedding(0.2)},
        {"name": "missing_embedding"},
    ]

    added = roster_service.add_entries_bulk(payload, model)
    assert added == ["valid"]


def test_add_entry_rejects_invalid_embedding(roster_service: RosterService) -> None:
    model = "adaface_ir101"
    result = roster_service.add_entry("invalid", [], model)
    assert result is None
    assert roster_service.get_entry_count(model) == 0
