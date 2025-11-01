"""Add pgvector support for aggregate_embedding

Revision ID: cb51c82e11cc
Revises: 0001_baseline_schema
Create Date: 2025-10-31 21:30:16.245944

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'cb51c82e11cc'
down_revision = '0001_baseline_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Convert aggregate_embedding from TEXT to vector(512) and add HNSW index."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    
    if dialect_name == "postgresql":
        # Convert the column type from TEXT to vector(512)
        op.execute(
            "ALTER TABLE roster_entries "
            "ALTER COLUMN aggregate_embedding TYPE vector(512) "
            "USING aggregate_embedding::vector(512)"
        )
        
        # Create HNSW index for fast vector similarity search
        # m=16: number of connections per layer (balance between accuracy and speed)
        # ef_construction=64: size of dynamic candidate list during index construction
        op.execute(
            "CREATE INDEX idx_roster_embedding_hnsw ON roster_entries "
            "USING hnsw (aggregate_embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    """Revert vector column back to TEXT and drop HNSW index."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    
    if dialect_name == "postgresql":
        # Drop the HNSW index
        op.execute("DROP INDEX IF EXISTS idx_roster_embedding_hnsw")
        
        # Convert back to TEXT
        op.execute(
            "ALTER TABLE roster_entries "
            "ALTER COLUMN aggregate_embedding TYPE TEXT "
            "USING aggregate_embedding::TEXT"
        )
