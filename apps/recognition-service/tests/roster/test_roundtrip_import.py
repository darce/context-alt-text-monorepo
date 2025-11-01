"""Round-trip persistence tests for the roster domain service."""

from __future__ import annotations

import os
from typing import Any
import uuid
import numpy as np

import pytest
from dotenv import load_dotenv

from roster.adapters import DataValidationAdapter, PostgreSQLStorageAdapter
from roster.domain import RosterService


@pytest.fixture(scope="module")
def db_url():
    """Database URL for testing."""
    load_dotenv()
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url or not database_url.startswith('postgresql'):
        pytest.skip("PostgreSQL DATABASE_URL not set or not PostgreSQL")
    
    return database_url


@pytest.fixture()
def roster_service(db_url) -> RosterService:
    """Create a roster service backed by PostgreSQL for round-trip tests."""
    test_tenant_uuid = str(uuid.uuid4())
    roster_storage = PostgreSQLStorageAdapter(
        database_url=db_url,
        tenant_id=test_tenant_uuid
    )
    service = RosterService(
        roster_storage=roster_storage,
        data_validator=DataValidationAdapter(),
    )
    yield service
    # Cleanup
    try:
        service.clear_roster("adaface_ir101")
    except:
        pass
    roster_storage.close()


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
    # pgvector stores as float32, so we need approximate comparison
    assert np.allclose(fetched.aggregate_embedding, _make_embedding(0.1), rtol=1e-5)


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
    db_url: str
) -> None:
    model = "adaface_ir101"
    entry = roster_service.add_entry("echo", _make_embedding(0.9), model, {"persist": True})
    assert entry is not None

    # New service reading the same database should see the entry
    tenant_id = roster_service.roster_storage.tenant_id
    next_storage = PostgreSQLStorageAdapter(database_url=db_url, tenant_id=tenant_id)
    next_service = RosterService(
        roster_storage=next_storage,
        data_validator=DataValidationAdapter(),
    )

    retrieved = next_service.get_entry(entry.unique_id, model)
    assert retrieved is not None
    assert retrieved.metadata["persist"] is True
    next_storage.close()


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
