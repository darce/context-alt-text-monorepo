"""Integration tests for materialized view refresh (progressive learning)."""
import os
import pytest
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from roster.adapters.postgresql_storage_adapter import PostgreSQLStorageAdapter
from roster.domain.entities import RosterEntry, RosterImage


@pytest.fixture(scope='module')
def db_url():
    """Get DATABASE_URL from environment, skip tests if not available."""
    load_dotenv()
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url or not database_url.startswith('postgresql'):
        pytest.skip("PostgreSQL DATABASE_URL not set or not PostgreSQL")
    
    return database_url


@pytest.fixture
def adapter(db_url):
    """Create adapter for tests."""
    import uuid
    test_tenant_id = str(uuid.uuid4())
    
    adapter = PostgreSQLStorageAdapter(
        database_url=db_url,
        tenant_id=test_tenant_id
    )
    
    yield adapter
    
    # Cleanup: remove test data
    with adapter._session() as session:
        session.execute(
            text("DELETE FROM augmented_embeddings WHERE roster_entry_id IN (SELECT id FROM roster_entries WHERE tenant_id = :tenant_id)"),
            {"tenant_id": test_tenant_id}
        )
        session.execute(
            text("DELETE FROM reference_embeddings WHERE roster_entry_id IN (SELECT id FROM roster_entries WHERE tenant_id = :tenant_id)"),
            {"tenant_id": test_tenant_id}
        )
        session.execute(
            text("DELETE FROM roster_entries WHERE tenant_id = :tenant_id"),
            {"tenant_id": test_tenant_id}
        )
        session.commit()


def test_materialized_view_refresh_after_augmented_embedding(adapter, db_url):
    """Verify materialized view refreshes and includes augmented embeddings."""
    # Create a test roster entry with reference embedding
    entry = RosterEntry(
        unique_id="test-progressive-alice",
        name="Alice Test",
        display_name="Alice T.",
        reference_images=[
            RosterImage(
                embedding=[0.1] * 512,
                image_path=None,
                metadata={}
            )
        ],
        metadata={},
        aggregate_embedding=[0.1] * 512,
        created_timestamp=datetime.now(timezone.utc),
        updated_timestamp=datetime.now(timezone.utc)
    )
    
    # Save entry
    success = adapter.save_roster_entry(entry, "insightface_w600k")
    assert success, "Failed to save roster entry"
    
    # Add augmented embedding
    entry.add_augmented_embedding(
        embedding=[0.15] * 512,
        source="test",
        observation_id="test-obs-1",
        metadata={"confidence": 0.92, "quality_tier": "high"}
    )
    success = adapter.save_roster_entry(entry, "insightface_w600k")
    assert success, "Failed to save augmented embedding"
    
    # Refresh materialized view
    adapter.refresh_aggregate_view(roster_id=entry.unique_id)
    
    # Debug: Check what's in the tables
    engine = create_engine(db_url)
    with engine.connect() as conn:
        # Check roster_entries table (check all entries, not just by label)
        roster_entries = conn.execute(
            text("SELECT id, label, tenant_id FROM roster_entries ORDER BY created_at DESC LIMIT 5")
        ).fetchall()
        print(f"DEBUG: recent roster_entries = {roster_entries}")
        
        # Get the tenant_id from the adapter
        print(f"DEBUG: adapter tenant_id = {adapter.tenant_id}")
        
        # Check all entries in materialized view
        all_view_entries = conn.execute(
            text("SELECT roster_entry_id, reference_count, augmented_count FROM roster_aggregate_embeddings ORDER BY last_updated DESC LIMIT 5")
        ).fetchall()
        print(f"DEBUG: recent materialized view entries = {all_view_entries}")
    
    # Verify view contains entry with updated counts
    # Query by the actual roster entry UUID instead of label
    engine = create_engine(db_url)
    with engine.connect() as conn:
        # First get the roster entry ID we just created
        roster_id_result = conn.execute(
            text("SELECT id FROM roster_entries WHERE tenant_id = :tenant_id ORDER BY created_at DESC LIMIT 1"),
            {"tenant_id": str(adapter.tenant_id)}
        ).fetchone()
        
        assert roster_id_result is not None, f"Could not find roster entry for tenant {adapter.tenant_id}"
        roster_uuid = roster_id_result[0]
        print(f"DEBUG: Found roster UUID = {roster_uuid}")
        
        result = conn.execute(
            text("""
                SELECT rav.reference_count, rav.augmented_count, rav.aggregate_embedding
                FROM roster_aggregate_embeddings rav
                WHERE rav.roster_entry_id = :roster_id
            """),
            {"roster_id": str(roster_uuid)}
        ).fetchone()
        
        assert result is not None, "Entry not found in materialized view"
        assert result[0] == 1, f"Expected reference_count=1, got {result[0]}"
        assert result[1] == 1, f"Expected augmented_count=1, got {result[1]}"
        assert result[2] is not None, "aggregate_embedding should not be null"
        
        # Vector might be returned as string or list depending on driver
        aggregate_emb = result[2]
        if isinstance(aggregate_emb, str):
            # Parse JSON string to list
            import json
            aggregate_emb = json.loads(aggregate_emb)
        
        assert len(aggregate_emb) == 512, f"Expected 512-dim vector, got {len(aggregate_emb)}"
        print(f"✅ Test passed: Found entry with {result[0]} reference, {result[1]} augmented, 512-dim aggregate")


def test_full_materialized_view_refresh(adapter, db_url):
    """Verify full view refresh works without errors."""
    # This is a smoke test - just verify it doesn't crash
    adapter.refresh_aggregate_view(roster_id=None)
    
    # Verify view still queryable
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT COUNT(*) FROM roster_aggregate_embeddings")
        ).scalar()
        
        # Should not crash, count can be any non-negative number
        assert result >= 0, "View query failed"


def test_selective_refresh_with_multiple_augmented_embeddings(adapter, db_url):
    """Verify view correctly aggregates multiple augmented embeddings."""
    # Create entry with reference
    entry = RosterEntry(
        unique_id="test-multi-aug",
        name="Bob Multi",
        display_name="Bob M.",
        reference_images=[
            RosterImage(
                embedding=[0.2] * 512,
                image_path=None,
                metadata={}
            )
        ],
        metadata={},
        aggregate_embedding=[0.2] * 512,
        created_timestamp=datetime.now(timezone.utc),
        updated_timestamp=datetime.now(timezone.utc)
    )
    adapter.save_roster_entry(entry, "insightface_w600k")
    
    # Add multiple augmented embeddings with different quality tiers
    for i, quality in enumerate(["high", "medium", "low"]):
        entry.add_augmented_embedding(
            embedding=[0.2 + 0.01 * (i + 1)] * 512,
            source="test",
            observation_id=f"test-obs-{i}",
            metadata={"confidence": 0.9 - 0.1 * i, "quality_tier": quality}
        )
    
    adapter.save_roster_entry(entry, "insightface_w600k")
    
    # Refresh view
    adapter.refresh_aggregate_view(roster_id=entry.unique_id)
    
    # Verify counts
    engine = create_engine(db_url)
    with engine.connect() as conn:
        # Query by tenant_id and most recent entry instead of label
        roster_id_result = conn.execute(
            text("SELECT id FROM roster_entries WHERE tenant_id = :tenant_id ORDER BY created_at DESC LIMIT 1"),
            {"tenant_id": str(adapter.tenant_id)}
        ).fetchone()
        
        assert roster_id_result is not None, f"Could not find roster entry for tenant {adapter.tenant_id}"
        roster_uuid = roster_id_result[0]
        
        result = conn.execute(
            text("""
                SELECT rav.reference_count, rav.augmented_count
                FROM roster_aggregate_embeddings rav
                WHERE rav.roster_entry_id = :roster_id
            """),
            {"roster_id": str(roster_uuid)}
        ).fetchone()
        
        assert result is not None, f"Entry not found in materialized view"
        assert result[0] == 1, "Should have 1 reference embedding"
        assert result[1] == 3, "Should have 3 augmented embeddings"
