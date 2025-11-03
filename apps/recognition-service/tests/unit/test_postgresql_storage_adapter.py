"""
Unit tests for PostgreSQL Storage Adapter

Tests the PostgreSQL storage adapter with pgvector similarity search.
Uses test database isolation for clean test execution.
"""

import os
import uuid
from datetime import datetime
from typing import List

import pytest

from roster.adapters.postgresql_storage_adapter import PostgreSQLStorageAdapter
from roster.domain.entities import RosterEntry, RosterImage


pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL DATABASE_URL not configured",
)


@pytest.fixture(scope="module")
def test_database_url():
    """Get test database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("PostgreSQL DATABASE_URL not configured for adapter tests")
    return url


@pytest.fixture(scope="module")
def test_tenant_id():
    """Generate a valid UUID for test tenant."""
    return str(uuid.uuid4())


@pytest.fixture
def adapter(test_database_url, test_tenant_id):
    """Create PostgreSQL storage adapter for testing."""
    adapter = PostgreSQLStorageAdapter(
        database_url=test_database_url,
        tenant_id=test_tenant_id,
        pool_size=2,
        max_overflow=5
    )
    yield adapter
    # Cleanup after test
    adapter.clear_roster("test_model")
    adapter.close()


@pytest.fixture
def sample_entry():
    """Create a sample roster entry for testing."""
    return RosterEntry(
        unique_id="test-person-001",
        name="Test Person",
        display_name="Test Person (Test)",
        reference_images=[
            RosterImage(
                embedding=[0.1] * 512,
                metadata={"quality": "high", "source": "test"},
                image_path="/test/image1.jpg"
            ),
            RosterImage(
                embedding=[0.2] * 512,
                metadata={"quality": "medium", "source": "test"},
                image_path="/test/image2.jpg"
            )
        ],
        metadata={"role": "test_subject", "department": "testing"}
    )


def test_save_and_load_roster_entry(adapter, sample_entry):
    """Test saving and loading a roster entry."""
    # Save
    result = adapter.save_roster_entry(sample_entry, "test_model")
    assert result is True, "Failed to save roster entry"
    
    # Load
    loaded_entry = adapter.get_roster_entry(sample_entry.unique_id, "test_model")
    assert loaded_entry is not None, "Failed to load roster entry"
    assert loaded_entry.unique_id == sample_entry.unique_id
    assert loaded_entry.name == sample_entry.name
    assert loaded_entry.display_name == sample_entry.display_name
    assert len(loaded_entry.reference_images) == 2
    assert loaded_entry.metadata.get("role") == "test_subject"


def test_load_all_roster_entries(adapter, sample_entry):
    """Test loading all roster entries."""
    # Save multiple entries
    adapter.save_roster_entry(sample_entry, "test_model")
    
    entry2 = RosterEntry(
        unique_id="test-person-002",
        name="Test Person 2",
        display_name="Test Person 2",
        reference_images=[
            RosterImage(
                embedding=[0.3] * 512,
                metadata={},
                image_path="/test/image3.jpg"
            )
        ]
    )
    adapter.save_roster_entry(entry2, "test_model")
    
    # Load all
    entries = adapter.load_roster_entries("test_model")
    assert len(entries) == 2, f"Expected 2 entries, got {len(entries)}"
    assert any(e.unique_id == sample_entry.unique_id for e in entries)
    assert any(e.unique_id == entry2.unique_id for e in entries)


def test_update_roster_entry(adapter, sample_entry):
    """Test updating an existing roster entry."""
    # Save initial
    adapter.save_roster_entry(sample_entry, "test_model")
    
    # Modify and save again
    sample_entry.name = "Updated Name"
    sample_entry.metadata["updated"] = True
    result = adapter.save_roster_entry(sample_entry, "test_model")
    assert result is True
    
    # Load and verify
    loaded_entry = adapter.get_roster_entry(sample_entry.unique_id, "test_model")
    assert loaded_entry.name == "Updated Name"
    assert loaded_entry.metadata.get("updated") is True


def test_delete_roster_entry(adapter, sample_entry):
    """Test deleting a roster entry."""
    # Save
    adapter.save_roster_entry(sample_entry, "test_model")
    
    # Delete
    result = adapter.delete_roster_entry(sample_entry.unique_id, "test_model")
    assert result is True
    
    # Verify deletion
    loaded_entry = adapter.get_roster_entry(sample_entry.unique_id, "test_model")
    assert loaded_entry is None


def test_roster_exists(adapter, sample_entry):
    """Test checking if roster exists."""
    # Empty roster
    assert adapter.roster_exists("test_model") is False
    
    # Add entry
    adapter.save_roster_entry(sample_entry, "test_model")
    assert adapter.roster_exists("test_model") is True


def test_clear_roster(adapter, sample_entry):
    """Test clearing all roster entries."""
    # Add entries
    adapter.save_roster_entry(sample_entry, "test_model")
    
    entry2 = RosterEntry(
        unique_id="test-person-003",
        name="Test Person 3",
        display_name="Test Person 3",
        reference_images=[
            RosterImage(embedding=[0.4] * 512, metadata={})
        ]
    )
    adapter.save_roster_entry(entry2, "test_model")
    
    # Clear
    result = adapter.clear_roster("test_model")
    assert result is True
    
    # Verify
    entries = adapter.load_roster_entries("test_model")
    assert len(entries) == 0


def test_get_storage_info(adapter, sample_entry, test_tenant_id):
    """Test getting storage information."""
    adapter.save_roster_entry(sample_entry, "test_model")
    
    info = adapter.get_storage_info("test_model")
    assert info["backend"] == "postgresql"
    assert info["tenant_id"] == test_tenant_id  # Use the actual tenant_id from fixture
    assert info["model"] == "test_model"

    stats = info.get("roster_stats", {})
    assert stats.get("entry_count", 0) >= 1

    details = info.get("backend_details", {})
    assert details.get("pgvector_enabled") is True
    assert "connection_pool" in details


def test_pgvector_similarity_search(adapter):
    """Test pgvector similarity search."""
    # Create entries with known embeddings
    entry1 = RosterEntry(
        unique_id="search-test-001",
        name="Person A",
        display_name="Person A",
        reference_images=[
            RosterImage(embedding=[1.0, 0.0, 0.0] + [0.0] * 509, metadata={})
        ]
    )
    
    entry2 = RosterEntry(
        unique_id="search-test-002",
        name="Person B",
        display_name="Person B",
        reference_images=[
            RosterImage(embedding=[0.9, 0.1, 0.0] + [0.0] * 509, metadata={})
        ]
    )
    
    entry3 = RosterEntry(
        unique_id="search-test-003",
        name="Person C",
        display_name="Person C",
        reference_images=[
            RosterImage(embedding=[0.0, 0.0, 1.0] + [0.0] * 509, metadata={})
        ]
    )
    
    # Save entries
    adapter.save_roster_entry(entry1, "test_model")
    adapter.save_roster_entry(entry2, "test_model")
    adapter.save_roster_entry(entry3, "test_model")
    
    # Refresh materialized view so entries are searchable
    adapter.refresh_aggregate_view()
    
    # Search for similar to entry1
    query_embedding = [1.0, 0.0, 0.0] + [0.0] * 509
    results = adapter.search_similar(
        query_embedding=query_embedding,
        model="test_model",
        top_k=3,
        threshold=0.5
    )
    
    assert len(results) > 0, "Should find at least one match"
    
    # First result should be most similar (entry1)
    best_match, best_score = results[0]
    assert best_match.unique_id == "search-test-001"
    assert best_score > 0.9, f"Expected high similarity, got {best_score}"
    
    # Second result should be entry2 (closer than entry3)
    if len(results) > 1:
        second_match, second_score = results[1]
        assert second_match.unique_id == "search-test-002"
        assert second_score < best_score


def test_multi_tenant_isolation(test_database_url):
    """Test that different tenants are isolated."""
    # Generate proper UUID tenant IDs
    tenant1_id = str(uuid.uuid4())
    tenant2_id = str(uuid.uuid4())
    
    adapter1 = PostgreSQLStorageAdapter(
        database_url=test_database_url,
        tenant_id=tenant1_id
    )
    adapter2 = PostgreSQLStorageAdapter(
        database_url=test_database_url,
        tenant_id=tenant2_id
    )
    
    try:
        # Add entry to tenant 1
        entry1 = RosterEntry(
            unique_id="isolation-test-001",
            name="Tenant 1 Person",
            display_name="Tenant 1 Person",
            reference_images=[
                RosterImage(embedding=[0.1] * 512, metadata={})
            ]
        )
        adapter1.save_roster_entry(entry1, "test_model")
        
        # Verify tenant 1 can see it
        entries1 = adapter1.load_roster_entries("test_model")
        assert len(entries1) == 1
        
        # Verify tenant 2 cannot see it
        entries2 = adapter2.load_roster_entries("test_model")
        assert len(entries2) == 0, "Tenant 2 should not see tenant 1's data"
        
    finally:
        adapter1.clear_roster("test_model")
        adapter2.clear_roster("test_model")
        adapter1.close()
        adapter2.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
