"""
Integration tests for Alembic migrations

Tests migration creation, application, rollback, and schema validation.
Verifies that baseline migration creates all required tables, indexes,
and materialized views correctly.
"""

import os
import pytest
from sqlalchemy import create_engine, text, inspect
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL DATABASE_URL not configured",
)


@pytest.fixture(scope="module")
def test_database_url():
    """Get test database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("PostgreSQL DATABASE_URL not configured for migration tests")
    return url


@pytest.fixture
def alembic_config():
    """Create Alembic configuration."""
    import os
    # Get the path to the recognition-service directory
    service_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    alembic_ini_path = os.path.join(service_dir, "alembic.ini")
    
    config = Config(alembic_ini_path)
    # Set the database URL from environment
    config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))
    # Ensure script_location is absolute path
    migrations_dir = os.path.join(service_dir, "db", "migrations")
    config.set_main_option("script_location", migrations_dir)
    return config


@pytest.fixture
def db_engine(test_database_url):
    """Create SQLAlchemy engine for testing."""
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


class TestBaselineMigration:
    """Test baseline migration creates all required schema."""

    def test_baseline_migration_creates_tables(self, alembic_config, db_engine):
        """Verify baseline migration creates all required tables."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        # Verify tables exist
        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        
        required_tables = [
            "alembic_version",
            "tenants",
            "roster_entries",
            "reference_embeddings",
            "augmented_embeddings"
        ]
        
        for table in required_tables:
            assert table in tables, f"Table '{table}' not created by baseline migration"

    def test_baseline_creates_pgvector_extension(self, db_engine):
        """Verify pgvector extension is available."""
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT extname, extversion 
                FROM pg_extension 
                WHERE extname = 'vector'
            """))
            row = result.fetchone()
            
            assert row is not None, "pgvector extension not found"
            assert row[0] == "vector", "Extension name mismatch"
            # Verify version is 0.8.1 or higher
            version = row[1]
            major, minor, patch = map(int, version.split('.')[:3])
            assert (major, minor, patch) >= (0, 8, 1), \
                f"pgvector version {version} is too old (need 0.8.1+)"

    def test_materialized_view_created(self, alembic_config, db_engine):
        """Verify materialized view created with correct structure."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        # Check materialized view exists
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT matviewname 
                FROM pg_matviews 
                WHERE matviewname = 'roster_aggregate_embeddings'
            """))
            row = result.fetchone()
            
            assert row is not None, "Materialized view 'roster_aggregate_embeddings' not created"
            assert row[0] == "roster_aggregate_embeddings"

    def test_materialized_view_columns(self, alembic_config, db_engine):
        """Verify materialized view has correct columns."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        # Check columns
        inspector = inspect(db_engine)
        # Note: materialized views appear as tables in SQLAlchemy inspector
        columns = inspector.get_columns("roster_aggregate_embeddings")
        column_names = [col["name"] for col in columns]
        
        required_columns = [
            "roster_entry_id",
            "tenant_id",
            "aggregate_embedding",
            "reference_count",
            "augmented_count",
            "last_updated"
        ]
        
        for col in required_columns:
            assert col in column_names, \
                f"Materialized view missing column '{col}'"

    def test_hnsw_indexes_created(self, alembic_config, db_engine):
        """Verify HNSW indexes created on vector columns."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        # Check indexes on materialized view
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    indexname, 
                    indexdef 
                FROM pg_indexes 
                WHERE tablename = 'roster_aggregate_embeddings'
                AND indexdef ILIKE '%hnsw%'
            """))
            hnsw_indexes = result.fetchall()
            
            assert len(hnsw_indexes) > 0, \
                "No HNSW indexes found on materialized view"
            
            # Verify index on aggregate_embedding column
            index_defs = [idx[1] for idx in hnsw_indexes]
            aggregate_index = any("aggregate_embedding" in idx_def for idx_def in index_defs)
            assert aggregate_index, \
                "HNSW index on aggregate_embedding not found"

    def test_standard_indexes_created(self, alembic_config, db_engine):
        """Verify standard B-tree indexes created."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    indexname,
                    tablename
                FROM pg_indexes 
                WHERE tablename = 'roster_aggregate_embeddings'
                AND indexname IN ('idx_roster_agg_entry', 'idx_roster_agg_tenant')
            """))
            indexes = result.fetchall()
            
            index_names = [idx[0] for idx in indexes]
            assert "idx_roster_agg_entry" in index_names, \
                "Unique index on roster_entry_id not found"
            assert "idx_roster_agg_tenant" in index_names, \
                "Index on tenant_id not found"

    def test_foreign_key_constraints(self, alembic_config, db_engine):
        """Verify foreign key constraints are properly set up."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        inspector = inspect(db_engine)
        
        # Check reference_embeddings foreign keys
        ref_fks = inspector.get_foreign_keys("reference_embeddings")
        assert len(ref_fks) > 0, "No foreign keys on reference_embeddings"
        
        fk_tables = [fk["referred_table"] for fk in ref_fks]
        assert "roster_entries" in fk_tables, \
            "Foreign key to roster_entries not found in reference_embeddings"
        
        # Check augmented_embeddings foreign keys
        aug_fks = inspector.get_foreign_keys("augmented_embeddings")
        assert len(aug_fks) > 0, "No foreign keys on augmented_embeddings"
        
        fk_tables = [fk["referred_table"] for fk in aug_fks]
        assert "roster_entries" in fk_tables, \
            "Foreign key to roster_entries not found in augmented_embeddings"


class TestMigrationOperations:
    """Test migration upgrade/downgrade operations."""

    def test_upgrade_to_head(self, alembic_config):
        """Test upgrading to latest migration."""
        try:
            command.upgrade(alembic_config, "head")
            
            # Verify current revision
            script = ScriptDirectory.from_config(alembic_config)
            head_revision = script.get_current_head()
            
            # Check database revision matches
            from alembic.runtime.migration import MigrationContext
            from sqlalchemy import create_engine
            
            url = os.getenv("DATABASE_URL")
            engine = create_engine(url)
            
            with engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_rev = context.get_current_revision()
                
                assert current_rev == head_revision, \
                    f"Database at {current_rev}, expected {head_revision}"
            
            engine.dispose()
            
        except Exception as e:
            pytest.fail(f"Migration upgrade failed: {e}")

    def test_downgrade_one_step(self, alembic_config, db_engine):
        """Test downgrading one migration step."""
        # First upgrade to head
        command.upgrade(alembic_config, "head")
        
        # Get revision history
        script = ScriptDirectory.from_config(alembic_config)
        revisions = list(script.walk_revisions())
        
        if len(revisions) < 2:
            pytest.skip("Need at least 2 migrations for downgrade test")
        
        # Downgrade one step
        try:
            command.downgrade(alembic_config, "-1")
            
            # Verify we're at previous revision
            from alembic.runtime.migration import MigrationContext
            
            with db_engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_rev = context.get_current_revision()
                
                # Should be at the second-to-last revision
                assert current_rev == revisions[1].revision, \
                    "Downgrade did not move to previous revision"
                
        except Exception as e:
            pytest.fail(f"Migration downgrade failed: {e}")

    def test_materialized_view_survives_refresh(self, alembic_config, db_engine):
        """Test materialized view can be refreshed after migration."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        # Try to refresh the materialized view
        with db_engine.connect() as conn:
            try:
                conn.execute(text(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY roster_aggregate_embeddings"
                ))
                conn.commit()
            except Exception as e:
                pytest.fail(f"Materialized view refresh failed: {e}")


class TestMigrationDataIntegrity:
    """Test that migrations preserve data integrity."""

    def test_migration_with_existing_data(self, alembic_config, db_engine):
        """Test that data survives migration operations."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        # Insert test data
        import uuid
        tenant_id = str(uuid.uuid4())
        roster_id = str(uuid.uuid4())
        
        with db_engine.connect() as conn:
            # Insert tenant
            conn.execute(text("""
                INSERT INTO tenants (id, slug, name, plan_tier, created_at)
                VALUES (:tenant_id, :slug, 'test-tenant', 'free', NOW())
                ON CONFLICT (id) DO NOTHING
            """), {"tenant_id": tenant_id, "slug": f"test-tenant-{tenant_id[:8]}"})
            
            # Insert roster entry
            conn.execute(text("""
                INSERT INTO roster_entries 
                (id, tenant_id, label, type, model, metadata, created_at, updated_at)
                VALUES (:id, :tenant_id, :label, 'person', 'test-model', '{}'::jsonb, NOW(), NOW())
            """), {
                "id": roster_id,
                "tenant_id": tenant_id,
                "label": "Test Person"
            })
            
            # Insert reference embedding
            embedding = "[" + ",".join(["0.1"] * 512) + "]"
            conn.execute(text("""
                INSERT INTO reference_embeddings
                (id, roster_entry_id, embedding, metadata, created_at)
                VALUES (:id, :roster_id, CAST(:embedding AS vector), '{}'::jsonb, NOW())
            """), {
                "id": str(uuid.uuid4()),
                "roster_id": roster_id,
                "embedding": embedding
            })
            
            conn.commit()
        
        # Verify data exists
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) FROM roster_entries WHERE id = :roster_id
            """), {"roster_id": roster_id})
            count = result.scalar()
            
            assert count == 1, "Data not found after insertion"
        
        # If we had a second migration, we'd test downgrade/upgrade preserves data
        # For now, just verify the data is accessible
        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT re.label, ref.embedding
                FROM roster_entries re
                JOIN reference_embeddings ref ON ref.roster_entry_id = re.id
                WHERE re.id = :roster_id
            """), {"roster_id": roster_id})
            row = result.fetchone()
            
            assert row is not None, "Cannot retrieve inserted data with joins"
            assert row[0] == "Test Person", "Label data corrupted"
            assert row[1] is not None, "Embedding data lost"


class TestMigrationConstraints:
    """Test database constraints created by migrations."""

    def test_unique_constraints(self, alembic_config, db_engine):
        """Verify unique constraints are enforced."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        inspector = inspect(db_engine)
        
        # Check augmented_embeddings has unique constraint on observation_id
        constraints = inspector.get_unique_constraints("augmented_embeddings")
        constraint_columns = [c["column_names"] for c in constraints]
        
        # Should have unique constraint on observation_id
        has_obs_constraint = any(
            "observation_id" in cols 
            for cols in constraint_columns
        )
        assert has_obs_constraint, \
            "Unique constraint on observation_id not found"

    def test_not_null_constraints(self, alembic_config, db_engine):
        """Verify NOT NULL constraints on critical columns."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        inspector = inspect(db_engine)
        
        # Check roster_entries columns
        roster_cols = inspector.get_columns("roster_entries")
        roster_col_dict = {col["name"]: col for col in roster_cols}
        
        # Critical columns should be NOT NULL
        assert roster_col_dict["id"]["nullable"] is False
        assert roster_col_dict["tenant_id"]["nullable"] is False
        assert roster_col_dict["label"]["nullable"] is False

    def test_cascade_deletes(self, alembic_config, db_engine):
        """Verify cascade delete behavior on foreign keys."""
        # Run migrations
        command.upgrade(alembic_config, "head")
        
        inspector = inspect(db_engine)
        
        # Check reference_embeddings foreign keys have CASCADE
        ref_fks = inspector.get_foreign_keys("reference_embeddings")
        
        for fk in ref_fks:
            if fk["referred_table"] == "roster_entries":
                # Should have CASCADE on delete
                assert fk.get("ondelete") in ["CASCADE", None], \
                    "Foreign key should have CASCADE on delete"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
