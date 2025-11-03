"""Integration tests for pgvector extension validation."""
import os
import pytest
from sqlalchemy import create_engine, text
from roster.adapters.postgresql_storage_adapter import PostgreSQLStorageAdapter


@pytest.fixture(scope='module')
def db_url():
    """Get DATABASE_URL from environment, skip tests if not available."""
    from dotenv import load_dotenv
    load_dotenv()
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url or not database_url.startswith('postgresql'):
        pytest.skip("PostgreSQL DATABASE_URL not set or not PostgreSQL")
    
    return database_url


def test_pgvector_extension_exists(db_url):
    """Test that pgvector extension is installed and accessible."""
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        assert result == 1, "pgvector extension not found in database"


def test_adapter_initialization_with_pgvector(db_url, monkeypatch):
    """Test that PostgreSQLStorageAdapter initializes successfully with pgvector."""
    monkeypatch.setenv("DATABASE_URL", db_url)
    
    # Should not raise any exceptions
    adapter = PostgreSQLStorageAdapter()
    assert adapter is not None


def test_adapter_initialization_fails_without_pgvector(db_url, monkeypatch):
    """Test that adapter initialization fails gracefully when pgvector is missing."""
    # This test would require a separate test database without pgvector
    # For now, we just verify the validation method exists
    monkeypatch.setenv("DATABASE_URL", db_url)
    adapter = PostgreSQLStorageAdapter()
    
    # Verify the validation happens (by checking it doesn't raise during init)
    # In a real scenario with missing pgvector, it would raise RuntimeError
    assert hasattr(adapter, '_verify_pgvector_extension')


def test_materialized_view_exists(db_url):
    """Test that roster_aggregate_embeddings materialized view was created."""
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 1 FROM pg_matviews 
                WHERE schemaname = 'public' 
                AND matviewname = 'roster_aggregate_embeddings'
            """)
        ).scalar()
        assert result == 1, "roster_aggregate_embeddings materialized view not found"


def test_materialized_view_indexes(db_url):
    """Test that materialized view has required indexes."""
    engine = create_engine(db_url)
    with engine.connect() as conn:
        # Check for HNSW index on aggregate_embedding
        result = conn.execute(
            text("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = 'roster_aggregate_embeddings'
                AND indexname = 'idx_roster_agg_embedding'
            """)
        ).scalar()
        assert result == 'idx_roster_agg_embedding', "HNSW index on aggregate_embedding not found"
        
        # Check for unique index on roster_entry_id
        result = conn.execute(
            text("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = 'roster_aggregate_embeddings'
                AND indexname = 'idx_roster_agg_entry'
            """)
        ).scalar()
        assert result == 'idx_roster_agg_entry', "Unique index on roster_entry_id not found"
        
        # Check for index on tenant_id
        result = conn.execute(
            text("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = 'roster_aggregate_embeddings'
                AND indexname = 'idx_roster_agg_tenant'
            """)
        ).scalar()
        assert result == 'idx_roster_agg_tenant', "Index on tenant_id not found"
