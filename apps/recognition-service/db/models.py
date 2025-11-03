"""
SQLAlchemy models for recognition service persistence schema.

**Database Requirements:**
- PostgreSQL 17+ with pgvector extension 0.8.1+
- Extensions: vector, uuid-ossp
- HNSW indexing for fast vector similarity search

This module defines the canonical schema for:
- Tenants (multi-tenancy with row-level security)
- Roster entries (people, pets, entities)
- Reference embeddings (canonical face representations)
- Augmented embeddings (progressive learning from confirmations)

SQLite and other databases are not supported due to pgvector dependency.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


def _uuid_default():
    """Generate UUID that works with both PostgreSQL UUID and String columns."""
    return uuid.uuid4()


class UUIDType(sa.types.TypeDecorator):
    """
    Platform-independent UUID type.
    
    Uses PostgreSQL's UUID type when available, otherwise uses String(36).
    Always stores and retrieves Python uuid.UUID objects.
    """
    
    impl = sa.String
    cache_ok = True
    __visit_name__ = "uuid_type"
    
    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PostgreSQLUUID(as_uuid=True))
        else:
            return dialect.type_descriptor(sa.String(36))
    
    def process_bind_param(self, value: Optional[Any], dialect) -> Optional[Any]:  # noqa: ANN001
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value if dialect.name == 'postgresql' else str(value)
        if isinstance(value, str):
            # Convert string to UUID
            return uuid.UUID(value) if dialect.name == 'postgresql' else value
        return value
    
    def process_result_value(self, value: Optional[Any], dialect) -> Optional[uuid.UUID]:  # noqa: ANN001
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        if isinstance(value, str):
            return uuid.UUID(value)
        return value


class JSONType(sa.types.TypeDecorator):
    """JSON storage that works across PostgreSQL and SQLite."""

    impl = sa.Text
    cache_ok = True
    __visit_name__ = "json_type"

    def load_dialect_impl(self, dialect):
        """Use native JSON types when available."""
        if dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(sa.Text())

    def process_bind_param(self, value: Optional[Any], dialect) -> Optional[Any]:  # noqa: ANN001
        if value is None:
            return None
        # PostgreSQL JSONB accepts dicts directly, SQLite needs JSON string
        if dialect.name == 'postgresql':
            return value
        return json.dumps(value)

    def process_result_value(self, value: Optional[Any], dialect) -> Optional[Any]:  # noqa: ANN001
        if value is None:
            return None
        # PostgreSQL JSONB returns dicts directly, SQLite returns JSON string
        if dialect.name == 'postgresql':
            return value
        return json.loads(value) if isinstance(value, str) else value


class VectorType(sa.types.TypeDecorator):
    """
    PostgreSQL pgvector VECTOR type for 512-dimensional embeddings.
    
    **Requirements:**
    - PostgreSQL 17+ with pgvector extension 0.8.1+
    - Extension must be installed: CREATE EXTENSION IF NOT EXISTS vector;
    - Supports HNSW and IVFFlat indexing for fast similarity search
    
    **Storage:**
    - Dimension: 512 (fixed, matches InsightFace W600K output)
    - Distance metric: Cosine similarity (vector_cosine_ops)
    - Index type: HNSW (m=16, ef_construction=64)
    
    **Usage:**
    ```python
    embedding = sa.Column(VectorType, nullable=False)
    
    # Create HNSW index for fast similarity search
    sa.Index(
        "idx_embedding_hnsw",
        MyModel.embedding,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64}
    )
    ```
    
    **Performance:**
    - HNSW provides sub-50ms p95 latency for 1K entries
    - Cosine distance: SELECT ... ORDER BY embedding <=> query_vector LIMIT k
    - Refer to apps/recognition-service/docs/performance/targets.md for benchmarks
    
    This project requires PostgreSQL only. SQLite and other databases
    are not supported due to native vector type and indexing requirements.
    """
    
    impl = sa.Text
    cache_ok = True
    __visit_name__ = "vector_type"
    
    def load_dialect_impl(self, dialect):
        if dialect.name != 'postgresql':
            raise ValueError(
                "Only PostgreSQL 17+ with pgvector 0.8.1+ is supported. "
                "This project requires native vector types and HNSW indexing. "
                "See docs/tasks/db-install-and-production-guide.md for setup instructions."
            )
        from pgvector.sqlalchemy import Vector
        return dialect.type_descriptor(Vector(512))
    
    def process_bind_param(self, value: Optional[Any], dialect) -> Optional[Any]:  # noqa: ANN001
        if value is None:
            return None
        # pgvector accepts Python lists directly
        return value if isinstance(value, list) else list(value)
    
    def process_result_value(self, value: Optional[Any], dialect) -> Optional[list]:  # noqa: ANN001
        if value is None:
            return None
        # pgvector returns Python lists
        return value if isinstance(value, list) else list(value)


class Tenant(Base):
    __tablename__ = "tenants"

    id = sa.Column(UUIDType, primary_key=True, default=_uuid_default)
    slug = sa.Column(sa.String(64), unique=True, nullable=False)
    name = sa.Column(sa.String(255), nullable=False)
    plan_tier = sa.Column(sa.String(32), nullable=False, default="free")
    created_at = sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RosterEntry(Base):
    __tablename__ = "roster_entries"

    id = sa.Column(UUIDType, primary_key=True, default=_uuid_default)
    tenant_id = sa.Column(UUIDType, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    label = sa.Column(sa.String(191), nullable=False)
    display_name = sa.Column(sa.String(255))
    model = sa.Column(sa.String(128), nullable=False, default="insightface_w600k", server_default="insightface_w600k")
    type = sa.Column(sa.String(32), nullable=False, default="person")
    # Use 'metadata' column name with 'meta' attribute to avoid SQLAlchemy reserved attribute
    meta = sa.Column("metadata", JSONType, nullable=False, default=dict)
    aggregate_embedding = sa.Column(VectorType)
    created_at = sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    reference_embeddings = relationship("ReferenceEmbedding", back_populates="roster_entry", cascade="all, delete-orphan")
    augmented_embeddings = relationship("AugmentedEmbedding", back_populates="roster_entry", cascade="all, delete-orphan")


# Regular B-tree index for tenant and model queries
sa.Index("ix_roster_entries_tenant_model", RosterEntry.tenant_id, RosterEntry.model)

# HNSW index for vector similarity search
# This uses pgvector's HNSW (Hierarchical Navigable Small World) algorithm
# for fast approximate nearest neighbor search with cosine distance
sa.Index(
    "idx_roster_embedding_hnsw",
    RosterEntry.aggregate_embedding,
    postgresql_using="hnsw",
    postgresql_ops={"aggregate_embedding": "vector_cosine_ops"},
    postgresql_with={"m": 16, "ef_construction": 64}
)


class ReferenceEmbedding(Base):
    __tablename__ = "reference_embeddings"

    id = sa.Column(UUIDType, primary_key=True, default=_uuid_default)
    roster_entry_id = sa.Column(UUIDType, sa.ForeignKey("roster_entries.id", ondelete="CASCADE"), nullable=False)
    embedding = sa.Column(VectorType, nullable=False)
    image_path = sa.Column(sa.String(512))
    # Use 'metadata' column name with 'meta' attribute to avoid SQLAlchemy reserved attribute
    meta = sa.Column("metadata", JSONType, nullable=False, default=dict)
    created_at = sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=func.now())
    
    # Relationship
    roster_entry = relationship("RosterEntry", back_populates="reference_embeddings")


class AugmentedEmbedding(Base):
    __tablename__ = "augmented_embeddings"

    id = sa.Column(UUIDType, primary_key=True, default=_uuid_default)
    roster_entry_id = sa.Column(UUIDType, sa.ForeignKey("roster_entries.id", ondelete="CASCADE"), nullable=False)
    observation_id = sa.Column(sa.String(64), unique=True, nullable=False)
    embedding = sa.Column(VectorType, nullable=False)
    source = sa.Column(sa.String(64), nullable=False, default="wordpress_confirm")
    attachment_id = sa.Column(sa.BigInteger)
    bbox = sa.Column(JSONType)
    confidence = sa.Column(sa.Float)
    quality_tier = sa.Column(sa.String(16), nullable=False, default="medium")
    created_at = sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=func.now())
    
    # Relationship
    roster_entry = relationship("RosterEntry", back_populates="augmented_embeddings")
