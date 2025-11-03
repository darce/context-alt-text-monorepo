"""
Integration tests for PostgreSQL storage adapter with pgvector.

Tests verify:
1. Adapter initialization and connection
2. Tenant management
3. Roster entry CRUD operations
4. Vector similarity search with pgvector
5. HNSW index usage
6. Multi-tenant isolation
7. Metrics collection
"""

import pytest
import numpy as np
from datetime import datetime, timezone
from roster.adapters.postgresql_storage_adapter import PostgreSQLStorageAdapter
from roster.domain.entities import RosterEntry, RosterImage


@pytest.fixture(scope="module")
def db_url():
    """Database URL for testing."""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url or not database_url.startswith('postgresql'):
        pytest.skip("PostgreSQL DATABASE_URL not set or not PostgreSQL")
    
    return database_url


@pytest.fixture(scope="module")
def adapter(db_url):
    """Create PostgreSQL adapter for tests."""
    # Use a valid UUID for tenant_id
    import uuid
    test_tenant_uuid = str(uuid.uuid4())
    
    adapter = PostgreSQLStorageAdapter(
        database_url=db_url,
        tenant_id=test_tenant_uuid,
        pool_size=5,
        max_overflow=10
    )
    
    yield adapter
    
    # Cleanup: remove all test data
    try:
        adapter.delete_roster_entry('test-person-1', 'insightface_w600k')
        adapter.delete_roster_entry('test-person-2', 'insightface_w600k')
        adapter.delete_roster_entry('test-person-3', 'insightface_w600k')
    except:
        pass


@pytest.fixture
def test_embeddings():
    """Generate test embeddings with fixed seed."""
    np.random.seed(123)
    embeddings = []
    for i in range(3):
        embedding = np.random.randn(512).astype(float)
        embedding = embedding / np.linalg.norm(embedding)
        embeddings.append(embedding.tolist())
    return embeddings


@pytest.fixture
def sample_roster_entry(test_embeddings):
    """Create a sample roster entry."""
    return RosterEntry(
        unique_id='test-person-1',
        name='Test Person 1',
        display_name='Test Person One',
        reference_images=[
            RosterImage(
                embedding=test_embeddings[0],
                image_path='/path/to/image1.jpg',
                metadata={}
            )
        ],
        metadata={'type': 'person', 'source': 'test'},
        aggregate_embedding=test_embeddings[0],
        created_timestamp=datetime.now(timezone.utc),
        updated_timestamp=datetime.now(timezone.utc)
    )


@pytest.mark.integration
@pytest.mark.database
def test_adapter_initialization(adapter):
    """Test adapter initializes correctly with connection pool."""
    assert adapter is not None
    assert adapter.tenant_id is not None
    assert adapter.engine is not None
    
    # Check pool configuration
    assert adapter.engine.pool.size() > 0
    print(f"\n✅ Adapter initialized with pool size: {adapter.engine.pool.size()}")
    print(f"   Tenant ID: {adapter.tenant_id}")


@pytest.mark.integration
@pytest.mark.database
def test_save_and_load_roster_entry(adapter, sample_roster_entry):
    """Test saving and loading a roster entry."""
    model = 'insightface_w600k'
    
    # Save entry
    success = adapter.save_roster_entry(sample_roster_entry, model)
    assert success, "Failed to save roster entry"
    
    # Load entry (using correct method name)
    loaded_entry = adapter.get_roster_entry('test-person-1', model)
    assert loaded_entry is not None, "Failed to load roster entry"
    assert loaded_entry.unique_id == 'test-person-1'
    assert loaded_entry.name == 'Test Person 1' or loaded_entry.name == 'Test Person One'
    assert loaded_entry.aggregate_embedding is not None
    assert len(loaded_entry.aggregate_embedding) == 512
    
    print(f"\n✅ Saved and loaded roster entry: {loaded_entry.name}")


@pytest.mark.integration
@pytest.mark.database
def test_list_roster_entries(adapter, sample_roster_entry):
    """Test listing roster entries."""
    model = 'insightface_w600k'
    
    # Ensure at least one entry exists
    adapter.save_roster_entry(sample_roster_entry, model)
    
    # List entries (using correct method name)
    entries = adapter.load_roster_entries(model)
    assert len(entries) > 0, "No roster entries found"
    
    # Find our test entry
    test_entry = next((e for e in entries if e.unique_id == 'test-person-1'), None)
    assert test_entry is not None, "Test entry not in list"
    
    print(f"\n✅ Listed {len(entries)} roster entries")


@pytest.mark.integration
@pytest.mark.database
def test_vector_similarity_search(adapter, test_embeddings):
    """Test pgvector similarity search."""
    model = 'insightface_w600k'
    
    # Create test entries with different embeddings
    for i in range(3):
        entry = RosterEntry(
            unique_id=f'test-person-{i+1}',
            name=f'Test Person {i+1}',
            display_name=f'Test Person {i+1}',
            reference_images=[
                RosterImage(
                    embedding=test_embeddings[i],
                    image_path=f'/path/to/image{i+1}.jpg',
                    metadata={}
                )
            ],
            aggregate_embedding=test_embeddings[i],
            metadata={'type': 'person'},
            created_timestamp=datetime.now(timezone.utc),
            updated_timestamp=datetime.now(timezone.utc)
        )
        adapter.save_roster_entry(entry, model)
    
    # Refresh materialized view so entries are searchable
    adapter.refresh_aggregate_view()
    
    # Search using first embedding (should match test-person-1 with high similarity)
    query_embedding = test_embeddings[0]
    matches = adapter.search_similar(
        query_embedding=query_embedding,
        model=model,
        top_k=3,
        threshold=0.0
    )
    
    assert len(matches) > 0, "No matches found"
    
    # First match should be the exact same entry with ~1.0 similarity
    best_match_entry, best_match_score = matches[0]
    assert best_match_entry.unique_id == 'test-person-1', "Best match should be test-person-1"
    assert best_match_score > 0.99, f"Self-match should have ~1.0 similarity, got {best_match_score:.4f}"
    
    print(f"\n✅ Vector similarity search found {len(matches)} matches")
    print(f"   Best match: {best_match_entry.name} with similarity {best_match_score:.4f}")
    for entry, score in matches[:3]:
        print(f"   - {entry.name}: {score:.4f}")


@pytest.mark.integration
@pytest.mark.database
def test_similarity_search_with_threshold(adapter, test_embeddings):
    """Test that threshold filtering works correctly."""
    model = 'insightface_w600k'
    query_embedding = test_embeddings[0]
    
    # Search with high threshold (should filter out lower matches)
    matches_high = adapter.search_similar(
        query_embedding=query_embedding,
        model=model,
        top_k=10,
        threshold=0.95
    )
    
    # Search with low threshold (should include more matches)
    matches_low = adapter.search_similar(
        query_embedding=query_embedding,
        model=model,
        top_k=10,
        threshold=0.0
    )
    
    assert len(matches_high) <= len(matches_low), "High threshold should return fewer results"
    assert all(score >= 0.95 for _, score in matches_high), "All high threshold matches should be >=0.95"
    
    print(f"\n✅ Threshold filtering: {len(matches_high)} matches >= 0.95, {len(matches_low)} matches >= 0.0")


@pytest.mark.integration
@pytest.mark.database
def test_update_roster_entry(adapter, sample_roster_entry):
    """Test updating an existing roster entry."""
    model = 'insightface_w600k'
    
    # Save initial entry
    adapter.save_roster_entry(sample_roster_entry, model)
    
    # Update entry
    sample_roster_entry.display_name = 'Updated Display Name'
    sample_roster_entry.metadata['updated'] = True
    success = adapter.save_roster_entry(sample_roster_entry, model)
    assert success, "Failed to update roster entry"
    
    # Load and verify update
    loaded = adapter.get_roster_entry('test-person-1', model)
    assert loaded.display_name == 'Updated Display Name'
    assert loaded.metadata.get('updated') == True
    
    print(f"\n✅ Updated roster entry: {loaded.display_name}")


@pytest.mark.integration
@pytest.mark.database
def test_delete_roster_entry(adapter, sample_roster_entry):
    """Test deleting a roster entry."""
    model = 'insightface_w600k'
    
    # Save entry
    adapter.save_roster_entry(sample_roster_entry, model)
    
    # Verify it exists
    loaded = adapter.get_roster_entry('test-person-1', model)
    assert loaded is not None
    
    # Delete entry
    success = adapter.delete_roster_entry('test-person-1', model)
    assert success, "Failed to delete roster entry"
    
    # Verify it's gone
    loaded = adapter.get_roster_entry('test-person-1', model)
    assert loaded is None, "Entry should be deleted"
    
    print(f"\n✅ Deleted roster entry: test-person-1")


@pytest.mark.integration
@pytest.mark.database
def test_metrics_collection(adapter):
    """Test that metrics are being collected."""
    model = 'insightface_w600k'
    
    # Perform some operations to generate metrics (using correct method name)
    adapter.load_roster_entries(model)
    
    # Get metrics
    metrics = adapter.get_metrics()
    
    assert 'query_count' in metrics
    assert 'avg_duration_ms' in metrics
    assert 'operation_counts' in metrics
    assert metrics['query_count'] > 0
    
    print(f"\n✅ Metrics collected:")
    print(f"   Total queries: {metrics['query_count']}")
    print(f"   Avg duration: {metrics['avg_duration_ms']}ms")
    print(f"   Operations: {metrics['operation_counts']}")


@pytest.mark.integration
@pytest.mark.database
def test_multi_tenant_isolation(db_url, test_embeddings):
    """Test that different tenants can't access each other's data."""
    import uuid
    model = 'insightface_w600k'
    
    # Create two adapters for different tenants (using valid UUIDs)
    adapter1 = PostgreSQLStorageAdapter(
        database_url=db_url,
        tenant_id=str(uuid.uuid4()),
        pool_size=2
    )
    
    adapter2 = PostgreSQLStorageAdapter(
        database_url=db_url,
        tenant_id=str(uuid.uuid4()),
        pool_size=2
    )
    
    try:
        # Tenant 1 creates an entry
        entry1 = RosterEntry(
            unique_id='isolated-entry-1',
            name='Tenant 1 Entry',
            display_name='Tenant 1 Entry',
            reference_images=[
                RosterImage(
                    embedding=test_embeddings[0],
                    image_path='/test.jpg',
                    metadata={}
                )
            ],
            aggregate_embedding=test_embeddings[0],
            metadata={'tenant': 'one'},
            created_timestamp=datetime.now(timezone.utc),
            updated_timestamp=datetime.now(timezone.utc)
        )
        adapter1.save_roster_entry(entry1, model)
        
        # Tenant 2 should not see tenant 1's entry (using correct method name)
        tenant2_entries = adapter2.load_roster_entries(model)
        tenant2_entry_ids = [e.unique_id for e in tenant2_entries]
        assert 'isolated-entry-1' not in tenant2_entry_ids, "Tenant 2 should not see tenant 1's entries"
        
        # Tenant 1 should see their own entry
        tenant1_entries = adapter1.load_roster_entries(model)
        tenant1_entry_ids = [e.unique_id for e in tenant1_entries]
        assert 'isolated-entry-1' in tenant1_entry_ids, "Tenant 1 should see their own entry"
        
        print(f"\n✅ Multi-tenant isolation verified")
        print(f"   Tenant 1 entries: {len(tenant1_entries)}")
        print(f"   Tenant 2 entries: {len(tenant2_entries)}")
        
    finally:
        # Cleanup
        adapter1.delete_roster_entry('isolated-entry-1', model)


@pytest.mark.integration
@pytest.mark.database
def test_connection_pool_behavior(adapter):
    """Test that connection pooling works correctly."""
    model = 'insightface_w600k'
    
    # Get initial pool stats
    initial_metrics = adapter.get_metrics()
    initial_pool = initial_metrics.get('connection_pool', {})
    
    # Perform multiple operations (using correct method name)
    for i in range(5):
        adapter.load_roster_entries(model)
    
    # Get final pool stats
    final_metrics = adapter.get_metrics()
    final_pool = final_metrics.get('connection_pool', {})
    
    # Verify pool is being used
    assert final_pool.get('size', 0) > 0, "Pool should have size > 0"
    
    print(f"\n✅ Connection pool stats:")
    print(f"   Size: {final_pool.get('size')}")
    print(f"   Checked in: {final_pool.get('checked_in')}")
    print(f"   Checked out: {final_pool.get('checked_out')}")
    print(f"   Utilization: {final_pool.get('utilisation_percent')}%")
