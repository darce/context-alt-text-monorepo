"""
Round-trip Import Tests

Tests for importing data and verifying data integrity.
"""

import pytest
import tempfile
import os
from pathlib import Path

from roster.domain import RosterService, RosterEntry, RosterImage
from roster.adapters import FileRosterStorageAdapter, EmbeddingStorageAdapter, DataValidationAdapter
from roster.config import reload_config


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Set environment variable for test
        os.environ["ROSTER_DATA_DIR"] = temp_dir
        # Reload config to pick up new path
        reload_config()
        yield temp_dir
        # Clean up environment
        if "ROSTER_DATA_DIR" in os.environ:
            del os.environ["ROSTER_DATA_DIR"]


@pytest.fixture
def roster_service(temp_data_dir):
    """Create roster service for testing."""
    roster_storage = FileRosterStorageAdapter()
    embedding_storage = EmbeddingStorageAdapter()
    data_validator = DataValidationAdapter()
    
    return RosterService(
        roster_storage=roster_storage,
        embedding_storage=embedding_storage,
        data_validator=data_validator
    )


def test_round_trip_single_entry(roster_service):
    """Test adding and retrieving a single entry."""
    model = "adaface_ir101"
    name = "test_person"
    embedding = [0.1] * 512
    metadata = {"test": "data"}
    
    # Add entry
    result = roster_service.add_entry(name, embedding, model, metadata)
    assert result is not None
    assert result.name == name
    assert result.aggregate_embedding == embedding
    
    # Retrieve entry
    retrieved = roster_service.get_entry(result.unique_id, model)
    assert retrieved is not None
    assert retrieved.name == name
    assert retrieved.unique_id == result.unique_id
    assert retrieved.aggregate_embedding == embedding
    assert retrieved.metadata == metadata


def test_round_trip_multiple_entries(roster_service):
    """Test adding and retrieving multiple entries."""
    model = "adaface_ir101"
    entries_data = [
        {"name": "person1", "embedding": [0.1] * 512, "metadata": {"id": 1}},
        {"name": "person2", "embedding": [0.2] * 512, "metadata": {"id": 2}},
        {"name": "person3", "embedding": [0.3] * 512, "metadata": {"id": 3}}
    ]
    
    # Add entries
    added_entries = []
    for entry_data in entries_data:
        result = roster_service.add_entry(
            entry_data["name"],
            entry_data["embedding"], 
            model,
            entry_data["metadata"]
        )
        assert result is not None
        added_entries.append(result)
    
    # Retrieve all entries
    all_entries = roster_service.get_entries(model)
    assert len(all_entries) == 3
    
    # Verify each entry
    for original, retrieved in zip(added_entries, all_entries):
        assert retrieved.name == original.name
        assert retrieved.unique_id == original.unique_id
        assert retrieved.aggregate_embedding == original.aggregate_embedding


def test_round_trip_bulk_import(roster_service):
    """Test bulk import functionality."""
    model = "adaface_ir101"
    entries_data = [
        {"name": f"person_{i}", "embedding": [float(i+1)/10] * 512, "metadata": {"batch": "test"}}
        for i in range(10)
    ]
    
    # Bulk add
    successful_names = roster_service.add_entries_bulk(entries_data, model)
    assert len(successful_names) == 10
    
    # Verify all entries were added
    all_entries = roster_service.get_entries(model)
    assert len(all_entries) == 10
    
    # Verify each entry
    for i, entry in enumerate(all_entries):
        assert entry.name == f"person_{i}"
        assert entry.metadata["batch"] == "test"


def test_round_trip_with_multiple_reference_images(roster_service):
    """Test entry with multiple reference images."""
    model = "adaface_ir101"
    name = "multi_ref_person"
    
    # Add first reference
    embedding1 = [0.1] * 512
    result1 = roster_service.add_entry(name, embedding1, model)
    assert result1 is not None
    
    # Add second reference (should update existing entry)
    embedding2 = [0.2] * 512
    result2 = roster_service.add_entry(name, embedding2, model)
    assert result2 is not None
    assert result2.unique_id == result1.unique_id  # Same person
    assert result2.image_count == 2
    
    # Verify aggregate embedding is computed
    assert result2.aggregate_embedding is not None
    assert len(result2.aggregate_embedding) == 512
    
    # Retrieve and verify
    retrieved = roster_service.get_entry(result2.unique_id, model)
    assert retrieved.image_count == 2
    assert len(retrieved.reference_images) == 2


def test_round_trip_update_entry(roster_service):
    """Test updating an existing entry."""
    model = "adaface_ir101"
    name = "update_test_person"
    original_embedding = [0.1] * 512
    original_metadata = {"version": 1}
    
    # Add entry
    result = roster_service.add_entry(name, original_embedding, model, original_metadata)
    assert result is not None
    original_id = result.unique_id
    
    # Update entry
    new_embedding = [0.2] * 512
    new_metadata = {"version": 2}
    success = roster_service.update_entry(
        original_id, model, new_embedding, new_metadata
    )
    assert success
    
    # Verify update
    updated = roster_service.get_entry(original_id, model)
    assert updated is not None
    assert updated.unique_id == original_id
    assert updated.image_count == 2  # Original + new reference
    assert updated.metadata["version"] == 2


def test_round_trip_delete_entry(roster_service):
    """Test deleting an entry."""
    model = "adaface_ir101"
    name = "delete_test_person"
    embedding = [0.1] * 512
    
    # Add entry
    result = roster_service.add_entry(name, embedding, model)
    assert result is not None
    entry_id = result.unique_id
    
    # Verify it exists
    retrieved = roster_service.get_entry(entry_id, model)
    assert retrieved is not None
    
    # Delete entry
    success = roster_service.delete_entry(entry_id, model)
    assert success
    
    # Verify it's gone
    deleted = roster_service.get_entry(entry_id, model)
    assert deleted is None


def test_round_trip_clear_roster(roster_service):
    """Test clearing entire roster."""
    model = "adaface_ir101"
    
    # Add some entries
    for i in range(5):
        roster_service.add_entry(f"person_{i}", [float(i+1)] * 512, model)
    
    # Verify entries exist
    entries = roster_service.get_entries(model)
    assert len(entries) == 5
    
    # Clear roster
    success = roster_service.clear_roster(model)
    assert success
    
    # Verify roster is empty
    entries = roster_service.get_entries(model)
    assert len(entries) == 0


def test_round_trip_persistence(roster_service, temp_data_dir):
    """Test data persistence across service restarts."""
    model = "adaface_ir101"
    name = "persistence_test"
    embedding = [0.1] * 512
    metadata = {"persistent": True}
    
    # Add entry
    result = roster_service.add_entry(name, embedding, model, metadata)
    assert result is not None
    entry_id = result.unique_id
    
    # Create new service instance (simulating restart)
    new_roster_storage = FileRosterStorageAdapter()
    new_embedding_storage = EmbeddingStorageAdapter()
    new_data_validator = DataValidationAdapter()
    
    new_roster_service = RosterService(
        roster_storage=new_roster_storage,
        embedding_storage=new_embedding_storage,
        data_validator=new_data_validator
    )
    
    # Verify data persisted
    retrieved = new_roster_service.get_entry(entry_id, model)
    assert retrieved is not None
    assert retrieved.name == name
    assert retrieved.unique_id == entry_id
    assert retrieved.metadata["persistent"] is True
