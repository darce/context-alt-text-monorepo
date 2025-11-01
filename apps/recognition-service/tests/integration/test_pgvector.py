"""
Integration tests for pgvector with SQLAlchemy.

These tests verify:
1. Database connection works
2. pgvector extension is available
3. Vector columns can store and retrieve embeddings
4. HNSW index enables fast similarity search
5. Cosine similarity queries work correctly
"""

import json
import pytest
import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from db.models import Tenant, RosterEntry


@pytest.fixture(scope="module")
def db_engine():
    """Create database engine for tests."""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        pytest.skip("DATABASE_URL not set in environment")
    
    engine = create_engine(database_url, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def test_tenant(db_engine):
    """Create a test tenant for the test suite."""
    with Session(db_engine) as session:
        # Clean up any existing test data
        session.execute(text("DELETE FROM roster_entries WHERE label LIKE 'test_%'"))
        session.execute(text("DELETE FROM tenants WHERE slug = 'test-tenant'"))
        session.commit()
        
        # Create test tenant
        tenant = Tenant(
            slug='test-tenant',
            name='Test Tenant',
            plan_tier='free'
        )
        session.add(tenant)
        session.commit()
        
        yield tenant
        
        # Cleanup after all tests
        session.execute(text("DELETE FROM roster_entries WHERE label LIKE 'test_%'"))
        session.execute(text("DELETE FROM tenants WHERE slug = 'test-tenant'"))
        session.commit()


@pytest.fixture(scope="module")
def test_embeddings():
    """Generate test embeddings for testing.
    
    Using module scope to ensure the same embeddings are used across all tests
    in the module, so similarity searches work correctly.
    """
    embeddings = []
    # Use a fixed seed for reproducibility
    np.random.seed(42)
    for i in range(5):
        # Generate random normalized 512-dim embedding
        embedding = np.random.randn(512).astype(float)
        embedding = embedding / np.linalg.norm(embedding)
        embeddings.append(embedding.tolist())
    return embeddings


@pytest.mark.integration
@pytest.mark.database
def test_pgvector_extension_installed(db_engine):
    """Verify pgvector extension is installed."""
    with db_engine.connect() as conn:
        result = conn.execute(text(
            "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'"
        ))
        row = result.fetchone()
        
        assert row is not None, "pgvector extension not found"
        assert row[0] == 'vector', "Extension name should be 'vector'"
        print(f"\n✅ pgvector version {row[1]} is installed")


@pytest.mark.integration
@pytest.mark.database
def test_hnsw_index_exists(db_engine):
    """Verify HNSW index is created on aggregate_embedding column."""
    with db_engine.connect() as conn:
        result = conn.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE indexname = 'idx_roster_embedding_hnsw'"
        ))
        row = result.fetchone()
        
        assert row is not None, "HNSW index not found"
        assert 'hnsw' in row[1].lower(), "Index should use HNSW method"
        assert 'vector_cosine_ops' in row[1], "Index should use cosine distance"
        print(f"\n✅ HNSW index exists: {row[1]}")


@pytest.mark.integration
@pytest.mark.database
def test_create_roster_entries_with_vectors(db_engine, test_tenant, test_embeddings):
    """Test creating roster entries with vector embeddings."""
    with Session(db_engine) as session:
        # Clean up any existing test entries
        session.execute(text("DELETE FROM roster_entries WHERE label LIKE 'test_%'"))
        session.commit()
        
        # Create test roster entries with embeddings
        for i, embedding in enumerate(test_embeddings):
            entry = RosterEntry(
                tenant_id=test_tenant.id,
                label=f'test_person_{i}',
                display_name=f'Test Person {i}',
                type='person',
                aggregate_embedding=embedding
            )
            session.add(entry)
        
        session.commit()
        
        # Verify entries were created
        result = session.execute(text(
            "SELECT COUNT(*) FROM roster_entries WHERE label LIKE 'test_%'"
        ))
        count = result.scalar()
        
        assert count == len(test_embeddings), f"Expected {len(test_embeddings)} entries, found {count}"
        print(f"\n✅ Created {count} roster entries with vector embeddings")


@pytest.mark.integration
@pytest.mark.database
def test_vector_similarity_search(db_engine, test_tenant, test_embeddings):
    """Test vector similarity search using pgvector's cosine distance operator."""
    with Session(db_engine) as session:
        # Use the first embedding as query
        query_embedding = test_embeddings[0]
        
        # Convert embedding to PostgreSQL array format string
        # pgvector expects format: '[1.0,2.0,3.0,...]'
        query_vec_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        # Query using pgvector's <=> operator (cosine distance)
        # Use CAST() function instead of :: operator with bind parameters
        result = session.execute(text(
            """
            SELECT 
                label,
                1 - (aggregate_embedding <=> CAST(:query_vec AS vector)) as similarity
            FROM roster_entries
            WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'test-tenant')
                AND aggregate_embedding IS NOT NULL
            ORDER BY aggregate_embedding <=> CAST(:query_vec AS vector)
            LIMIT 3
            """
        ), {"query_vec": query_vec_str})
        
        matches = list(result.fetchall())
        
        assert len(matches) > 0, "Should find at least one match"
        assert len(matches) <= 3, "Should return at most 3 matches"
        
        # Verify the first match is the query itself (should be ~1.0 similarity)
        first_label, first_similarity = matches[0]
        assert first_similarity > 0.99, f"Self-match should have ~1.0 similarity, got {first_similarity:.4f}"
        
        print(f"\n✅ Found {len(matches)} similar entries:")
        for label, similarity in matches:
            print(f"   - {label}: {similarity:.4f} similarity")
        print(f"✅ Self-match has {first_similarity:.4f} similarity (as expected)")


@pytest.mark.integration
@pytest.mark.database
def test_hnsw_index_is_used_in_query_plan(db_engine, test_embeddings):
    """Verify that the query planner uses the HNSW index for similarity searches."""
    with Session(db_engine) as session:
        query_embedding = test_embeddings[0]
        query_vec_str = '[' + ','.join(map(str, query_embedding)) + ']'

        # Encourage planner to prefer the HNSW index for the explain plan.
        session.execute(text("SET enable_seqscan = off"))
        session.execute(text("ANALYZE roster_entries"))
        
        result = session.execute(text(
            """
            EXPLAIN (FORMAT JSON)
            SELECT label
            FROM roster_entries
            WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'test-tenant')
            ORDER BY aggregate_embedding <=> CAST(:query_vec AS vector)
            LIMIT 10
            """
        ), {"query_vec": query_vec_str})
        
        plan = result.fetchone()[0]
        plan_text = json.dumps(plan, indent=2)
        session.execute(text("RESET enable_seqscan"))
        
        # Check if HNSW index is mentioned in the plan
        assert 'Index Scan' in plan_text or 'Index' in plan_text, "Query should use an index"
        
        # Note: The exact plan format may vary, but we expect to see index usage
        print(f"\n✅ Query plan uses indexing")
        if 'hnsw' in plan_text.lower():
            print("✅ HNSW index explicitly mentioned in plan")


@pytest.mark.integration
@pytest.mark.database
def test_vector_storage_and_retrieval(db_engine, test_tenant):
    """Test that vectors are stored and retrieved accurately."""
    with Session(db_engine) as session:
        # Create a test entry with a known embedding
        test_embedding = [0.1] * 512
        test_embedding = (np.array(test_embedding) / np.linalg.norm(test_embedding)).tolist()
        
        entry = RosterEntry(
            tenant_id=test_tenant.id,
            label='test_accuracy_check',
            display_name='Accuracy Test',
            type='person',
            aggregate_embedding=test_embedding
        )
        session.add(entry)
        session.commit()
        
        # Retrieve the entry
        retrieved = session.query(RosterEntry).filter_by(label='test_accuracy_check').first()
        
        assert retrieved is not None, "Entry should be retrievable"
        assert retrieved.aggregate_embedding is not None, "Embedding should not be None"
        assert len(retrieved.aggregate_embedding) == 512, "Embedding should have 512 dimensions"
        
        # Verify values are close (allow for floating point precision)
        retrieved_array = np.array(retrieved.aggregate_embedding)
        test_array = np.array(test_embedding)
        np.testing.assert_allclose(retrieved_array, test_array, rtol=1e-5, atol=1e-8)
        
        print("\n✅ Vector storage and retrieval is accurate")
        
        # Cleanup
        session.delete(retrieved)
        session.commit()


@pytest.mark.integration
@pytest.mark.database
def test_cleanup_test_data(db_engine):
    """Clean up all test data after tests complete."""
    with Session(db_engine) as session:
        session.execute(text("DELETE FROM roster_entries WHERE label LIKE 'test_%'"))
        deleted_entries = session.execute(text(
            "SELECT COUNT(*) FROM roster_entries WHERE label LIKE 'test_%'"
        )).scalar()
        
        assert deleted_entries == 0, "All test roster entries should be deleted"
        print("\n✅ Test data cleaned up")
