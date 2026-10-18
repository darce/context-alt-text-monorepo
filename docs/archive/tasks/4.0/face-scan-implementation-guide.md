# Recognition Scan + Clustering Implementation Guide (4.0 Architecture)

> **Reference**: This guide expands on [`face-scan-cluster-plan.md`](face-scan-cluster-plan.md) with concrete implementation details from the archived recognition service, now aligned with the new recognition nomenclature.

## Overview

This document provides detailed implementation guidance for building the recognition scan and clustering pipeline in the 4.0 prototype architecture, eliminating the need for data migrations or backward compatibility.

## Architecture Principles

### Clean Slate Approach

- **Fresh schema**: Treat 4.0 as a rewrite—no data migrations from the archived service, only seed data.
- **Alembic-first**: Ship a baseline migration that enables pgvector and creates the face tables so every dev/test env stays in sync.
- **Multi-tenant from day 1**: All tables include `tenant_id` and join back to `tenants` for referential integrity.
- **Production-ready patterns**: Mirror the recognition-service layering so it is easy to add queues, RLS, and roster enrichment later.

### Technology Stack

**Backend (Python/FastAPI)**:

- InsightFace dual-head pipeline (identity + context features) that emits 1024-dimension embeddings
- PostgreSQL with pgvector extension for similarity search
- SQLAlchemy 2.0+ with async support
- Alembic for schema management

**Frontend (React/TypeScript)**:

- TanStack Query for async state management
- Radix UI primitives for accessible UI components
- WebSocket or polling for job status updates

---

## Part 1: Database Schema (PostgreSQL + pgvector)

### Tables

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Tenant isolation table (optional - can use WordPress site_url as tenant_id)
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_url VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Media faces table - stores detected faces with embeddings
CREATE TABLE media_faces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- WordPress attachment reference
    media_id INTEGER NOT NULL,
    media_url TEXT NOT NULL,

    -- Face detection metadata
    bbox_x INTEGER NOT NULL,
    bbox_y INTEGER NOT NULL,
    bbox_width INTEGER NOT NULL,
    bbox_height INTEGER NOT NULL,
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),

    -- InsightFace embedding (1024-dimensional composite vector)
    embedding VECTOR(1024) NOT NULL,

    -- Lifecycle flags
    is_deleted BOOLEAN DEFAULT FALSE,

    -- Audit trail
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by_user_id INTEGER,

    -- Composite index for tenant isolation
    CONSTRAINT unique_media_face UNIQUE(tenant_id, media_id, bbox_x, bbox_y)
);

-- Indexes for performance
CREATE INDEX idx_media_faces_tenant ON media_faces(tenant_id) WHERE NOT is_deleted;
CREATE INDEX idx_media_faces_embedding ON media_faces USING ivfflat (embedding vector_cosine_ops);

-- Face clusters table - groups similar faces
CREATE TABLE face_clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Cluster metadata
    label VARCHAR(255),
    representative_face_id UUID REFERENCES media_faces(id) ON DELETE SET NULL,
    face_count INTEGER DEFAULT 0,

    -- Roster linkage (null = unknown person)
    roster_id UUID,

    -- Clustering parameters (for audit/reproducibility)
    similarity_threshold FLOAT,
    clustering_algorithm VARCHAR(50) DEFAULT 'cosine_similarity',

    -- Audit trail
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by_user_id INTEGER,

    CONSTRAINT unique_tenant_label UNIQUE(tenant_id, label)
);

-- Indexes
CREATE INDEX idx_face_clusters_tenant ON face_clusters(tenant_id);
CREATE INDEX idx_face_clusters_roster ON face_clusters(roster_id) WHERE roster_id IS NOT NULL;

-- Cluster membership table (many-to-many between clusters and media faces)
CREATE TABLE cluster_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cluster_id UUID NOT NULL REFERENCES face_clusters(id) ON DELETE CASCADE,
    face_id UUID NOT NULL REFERENCES media_faces(id) ON DELETE CASCADE,
    similarity FLOAT NOT NULL CHECK (similarity >= 0 AND similarity <= 1),
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by_user_id INTEGER,
    CONSTRAINT unique_cluster_member UNIQUE(cluster_id, face_id),
    CONSTRAINT unique_face_membership UNIQUE(tenant_id, face_id)
);

CREATE INDEX idx_cluster_members_cluster ON cluster_members(cluster_id);
CREATE INDEX idx_cluster_members_face ON cluster_members(face_id);

-- Scan jobs table - captures synchronous telemetry (and future async offload)
CREATE TABLE face_scan_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Job metadata
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    media_ids INTEGER[] NOT NULL,
    total_media INTEGER NOT NULL,
    processed_media INTEGER DEFAULT 0,
    faces_detected INTEGER DEFAULT 0,

    -- Error tracking
    error_message TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_by_user_id INTEGER
);

-- Indexes
CREATE INDEX idx_scan_jobs_tenant ON face_scan_jobs(tenant_id);
CREATE INDEX idx_scan_jobs_status ON face_scan_jobs(status) WHERE status IN ('pending', 'running');
```

### SQLAlchemy Models

```python
# apps/prototype-description-service/db/models.py

from sqlalchemy import Column, Integer, String, Float, Boolean, Text, ARRAY, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
import uuid
from datetime import datetime

Base = declarative_base()

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_url = Column(String(255), unique=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    media_faces = relationship("MediaFace", back_populates="tenant", cascade="all, delete-orphan")
    face_clusters = relationship("FaceCluster", back_populates="tenant", cascade="all, delete-orphan")


class MediaFace(Base):
    __tablename__ = "media_faces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    # WordPress attachment reference
    media_id = Column(Integer, nullable=False)
    media_url = Column(Text, nullable=False)

    # Face detection
    bbox_x = Column(Integer, nullable=False)
    bbox_y = Column(Integer, nullable=False)
    bbox_width = Column(Integer, nullable=False)
    bbox_height = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=False)

    # InsightFace embedding (1024-dimensional)
    embedding = Column(Vector(1024), nullable=False)

    # Lifecycle flags
    is_deleted = Column(Boolean, default=False)

    # Audit
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(Integer)

    # Relationships
    tenant = relationship("Tenant", back_populates="media_faces")
    cluster_members = relationship(
        "ClusterMember",
        back_populates="face",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )


class FaceCluster(Base):
    __tablename__ = "face_clusters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    # Cluster metadata
    label = Column(String(255))
    representative_face_id = Column(UUID(as_uuid=True), ForeignKey("media_faces.id", ondelete="SET NULL"))
    face_count = Column(Integer, default=0)

    # Roster linkage
    roster_id = Column(UUID(as_uuid=True))

    # Clustering parameters
    similarity_threshold = Column(Float)
    clustering_algorithm = Column(String(50), default="cosine_similarity")

    # Audit
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(Integer)

    # Relationships
    tenant = relationship("Tenant", back_populates="face_clusters")
    representative_face = relationship("MediaFace", foreign_keys=[representative_face_id])
    members = relationship(
        "ClusterMember",
        back_populates="cluster",
        cascade="all, delete-orphan"
    )


class ClusterMember(Base):
    __tablename__ = "cluster_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("face_clusters.id", ondelete="CASCADE"), nullable=False)
    face_id = Column(UUID(as_uuid=True), ForeignKey("media_faces.id", ondelete="CASCADE"), nullable=False)
    similarity = Column(Float, nullable=False)
    assigned_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    created_by_user_id = Column(Integer)

    cluster = relationship("FaceCluster", back_populates="members")
    face = relationship("MediaFace", back_populates="cluster_members")


class FaceScanJob(Base):
    __tablename__ = "face_scan_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    # Job state
    status = Column(String(20), nullable=False, default="pending")
    media_ids = Column(ARRAY(Integer), nullable=False)
    total_media = Column(Integer, nullable=False)
    processed_media = Column(Integer, default=0)
    faces_detected = Column(Integer, default=0)

    # Error tracking
    error_message = Column(Text)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    started_at = Column(TIMESTAMP(timezone=True))
    completed_at = Column(TIMESTAMP(timezone=True))
    created_by_user_id = Column(Integer)

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="valid_status"),
    )
```

### Alembic Migration

```python
# apps/prototype-description-service/db/migrations/versions/001_face_scan_schema.py

"""Face scan and clustering schema

Revision ID: 001_face_scan
Revises:
Create Date: 2025-11-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = '001_face_scan'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create tenants table
    op.create_table(
        'tenants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('site_url', sa.String(255), unique=True, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())
    )

    # Create face_clusters table (before media_faces due to FK)
    op.create_table(
        'face_clusters',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(255)),
        sa.Column('representative_face_id', postgresql.UUID(as_uuid=True)),
        sa.Column('face_count', sa.Integer, server_default='0'),
        sa.Column('roster_id', postgresql.UUID(as_uuid=True)),
        sa.Column('similarity_threshold', sa.Float),
        sa.Column('clustering_algorithm', sa.String(50), server_default='cosine_similarity'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by_user_id', sa.Integer),
        sa.UniqueConstraint('tenant_id', 'label', name='unique_tenant_label')
    )

    # Create media_faces table
    op.create_table(
        'media_faces',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('media_id', sa.Integer, nullable=False),
        sa.Column('media_url', sa.Text, nullable=False),
        sa.Column('bbox_x', sa.Integer, nullable=False),
        sa.Column('bbox_y', sa.Integer, nullable=False),
        sa.Column('bbox_width', sa.Integer, nullable=False),
        sa.Column('bbox_height', sa.Integer, nullable=False),
        sa.Column('confidence', sa.Float, nullable=False),
        sa.Column('embedding', Vector(1024), nullable=False),
        sa.Column('is_deleted', sa.Boolean, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by_user_id', sa.Integer),
        sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name='confidence_range'),
        sa.UniqueConstraint('tenant_id', 'media_id', 'bbox_x', 'bbox_y', name='unique_media_face')
    )

    # Add FK from face_clusters.representative_face_id to media_faces.id
    op.create_foreign_key(
        'fk_face_clusters_representative_face',
        'face_clusters', 'media_faces',
        ['representative_face_id'], ['id'],
        ondelete='SET NULL'
    )

    # Create cluster_members table to support many-to-many relationships
    op.create_table(
        'cluster_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('cluster_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('face_clusters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('face_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('media_faces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('similarity', sa.Float, nullable=False),
        sa.Column('assigned_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('created_by_user_id', sa.Integer),
        sa.UniqueConstraint('cluster_id', 'face_id', name='unique_cluster_member'),
        sa.UniqueConstraint('tenant_id', 'face_id', name='unique_face_membership')
    )

    # Create indexes
    op.create_index('idx_media_faces_tenant', 'media_faces', ['tenant_id'], postgresql_where=sa.text('NOT is_deleted'))
    op.create_index('idx_media_faces_embedding', 'media_faces', ['embedding'], postgresql_using='ivfflat', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('idx_face_clusters_tenant', 'face_clusters', ['tenant_id'])
    op.create_index('idx_face_clusters_roster', 'face_clusters', ['roster_id'], postgresql_where=sa.text('roster_id IS NOT NULL'))
    op.create_index('idx_cluster_members_cluster', 'cluster_members', ['cluster_id'])
    op.create_index('idx_cluster_members_face', 'cluster_members', ['face_id'])

    # Create face_scan_jobs table
    op.create_table(
        'face_scan_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('media_ids', postgresql.ARRAY(sa.Integer), nullable=False),
        sa.Column('total_media', sa.Integer, nullable=False),
        sa.Column('processed_media', sa.Integer, server_default='0'),
        sa.Column('faces_detected', sa.Integer, server_default='0'),
        sa.Column('error_message', sa.Text),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('created_by_user_id', sa.Integer),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name='valid_status')
    )

    op.create_index('idx_scan_jobs_tenant', 'face_scan_jobs', ['tenant_id'])
    op.create_index('idx_scan_jobs_status', 'face_scan_jobs', ['status'], postgresql_where=sa.text("status IN ('pending', 'running')"))


def downgrade() -> None:
    op.drop_table('face_scan_jobs')
    op.drop_table('cluster_members')
    op.drop_table('media_faces')
    op.drop_table('face_clusters')
    op.drop_table('tenants')
    op.execute('DROP EXTENSION IF EXISTS vector')
```

---

## Part 2: InsightFace Integration

### Model Configuration

```yaml
# apps/prototype-description-service/config/settings.yaml

insightface:
  model_name: "buffalo_l" # Standard InsightFace model
  device: "auto" # auto-detect GPU/CPU
  cache_dir: "~/.insightface/models" # Model weights cache
  providers: [] # Empty = auto-detect (CUDA/CoreML/CPU)
  det_thresh: 0.5 # Detection threshold (0.3 = more sensitive)
  det_size: [640, 640] # Detection input size

recognition:
  default_threshold: 0.45 # Similarity threshold for matching
  max_faces_per_image: 999 # No practical limit
  embedding_dimension: 1024 # concatenated identity + context vectors
  max_candidates: 10 # Top N matches to return

clustering:
  similarity_threshold: 0.6 # Cosine similarity for grouping
  min_cluster_size: 2 # Minimum faces per cluster
  max_cluster_size: 1000 # Safety limit per cluster
```

### Face Detection Service

```python
# apps/prototype-description-service/recognition/application/face_scan_service.py

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from PIL import Image
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from recognition.infrastructure.embedding_provider import FaceEmbeddingProvider
from db.models import MediaFace, FaceScanJob

logger = logging.getLogger(__name__)


class FaceScanService:
    """
    Service for scanning media items and extracting face embeddings.

    This service:
    1. Fetches media from WordPress via signed URL
    2. Detects faces using InsightFace
    3. Extracts 1024-dimensional embeddings (identity + context)
    4. Persists to media_faces table with tenant isolation
    """

    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: FaceEmbeddingProvider,
        tenant_id: UUID
    ):
        self.session = session
        self.adapter = embedding_provider
        self.tenant_id = tenant_id

    async def scan_media(
        self,
        media_id: int,
        media_url: str,
        user_id: Optional[int] = None
    ) -> List[MediaFace]:
        """
        Scan a single media item for faces.

        Args:
            media_id: WordPress attachment ID
            media_url: Secure URL to fetch the image
            user_id: WordPress user ID for audit trail

        Returns:
            List of MediaFace records (not yet committed)
        """
        logger.info(f"Scanning media {media_id} from {media_url}")

        try:
            # Fetch image from WordPress
            image = await self._fetch_image(media_url)

            # Detect faces and extract embeddings
            face_embeddings = await self.adapter.analyze(image)

            if not face_embeddings:
                logger.info(f"No faces detected in media {media_id}")
                return []

            # Create database records
            media_faces = []
            for face_embedding in face_embeddings:
                detection = face_embedding.detection
                bbox = detection.bbox  # (x_min, y_min, x_max, y_max)

                media_face = MediaFace(
                    tenant_id=self.tenant_id,
                    media_id=media_id,
                    media_url=media_url,
                    bbox_x=bbox[0],
                    bbox_y=bbox[1],
                    bbox_width=bbox[2] - bbox[0],
                    bbox_height=bbox[3] - bbox[1],
                    confidence=detection.confidence,
                    embedding=face_embedding.embedding.tolist(),
                    created_by_user_id=user_id
                )

                media_faces.append(media_face)

            logger.info(f"✅ Detected {len(media_faces)} faces in media {media_id}")
            return media_faces

        except Exception as e:
            logger.error(f"❌ Failed to scan media {media_id}: {e}")
            raise

    async def scan_batch(
        self,
        media_items: List[Dict[str, Any]],
        job_id: UUID,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Scan multiple media items in-line while updating the job row for telemetry.

        Args:
            media_items: List of {media_id, media_url} dicts
            job_id: Face scan job UUID for progress tracking
            user_id: WordPress user ID

        Returns:
            Summary dict with total_faces, processed_media, errors
        """
        total_faces = 0
        processed = 0
        errors = []

        # Update job status to running
        job = await self.session.get(FaceScanJob, job_id)
        if job:
            job.status = "running"
            job.started_at = datetime.utcnow()
            await self.session.commit()

        for item in media_items:
            try:
                faces = await self.scan_media(
                    media_id=item["media_id"],
                    media_url=item["media_url"],
                    user_id=user_id
                )

                # Add faces to session
                self.session.add_all(faces)
                total_faces += len(faces)
                processed += 1

                # Update job progress
                if job:
                    job.processed_media = processed
                    job.faces_detected = total_faces
                    await self.session.commit()

            except Exception as e:
                error_msg = f"Media {item['media_id']}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

        # Finalize job
        if job:
            job.status = "completed" if not errors else "failed"
            job.completed_at = datetime.utcnow()
            if errors:
                job.error_message = "\n".join(errors)
            await self.session.commit()

        return {
            "total_faces": total_faces,
            "processed_media": processed,
            "total_media": len(media_items),
            "errors": errors
        }

    async def _fetch_image(self, url: str) -> Image.Image:
        """Fetch image from URL and return PIL Image."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()

            from io import BytesIO
            image_bytes = BytesIO(response.content)
            return Image.open(image_bytes).convert("RGB")
```

### Embedding Provider (InsightFace + context features)

```python
# apps/prototype-description-service/recognition/infrastructure/embedding_provider.py

import logging
from typing import Dict, List, Optional

import numpy as np
from PIL import Image
import cv2
import insightface
from insightface.app import FaceAnalysis

from recognition.domain.entities import FaceDetection, FaceEmbedding
from recognition.config import get_settings

logger = logging.getLogger(__name__)


class FaceEmbeddingProvider:
    """Wrap InsightFace and derive 1024-d embeddings (identity + context)."""

    def __init__(self):
        self.settings = get_settings()
        self._app: Optional[FaceAnalysis] = None
        self._model_loaded = False

    async def _ensure_model_loaded(self):
        if self._model_loaded:
            return

        logger.info(f"Loading InsightFace model: {self.settings.insightface.model_name}")
        self._app = FaceAnalysis(
            name=self.settings.insightface.model_name,
            root=self.settings.insightface.cache_dir,
            providers=self._get_providers()
        )
        self._app.prepare(
            ctx_id=0,
            det_size=tuple(self.settings.insightface.det_size),
            det_thresh=self.settings.insightface.det_thresh
        )

        self._model_loaded = True
        logger.info("✅ InsightFace model loaded")

    def _get_providers(self) -> List[str]:
        if self.settings.insightface.providers:
            return self.settings.insightface.providers

        device = self.settings.insightface.device
        if device == "cuda":
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if device == "mps":
            return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def _pil_to_cv2(self, pil_image: Image.Image) -> np.ndarray:
        rgb_array = np.array(pil_image)
        return cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)

    async def analyze(self, image: Image.Image) -> List[FaceEmbedding]:
        await self._ensure_model_loaded()
        cv2_image = self._pil_to_cv2(image)
        faces = self._app.get(cv2_image)

        results: List[FaceEmbedding] = []
        for face in faces:
            bbox = face.bbox.astype(int)
            x_min, y_min, x_max, y_max = bbox

            detection = FaceDetection(
                bbox=(x_min, y_min, x_max, y_max),
                confidence=float(face.det_score),
                landmarks=face.kps if hasattr(face, "kps") else None
            )

            identity_vec = face.normed_embedding
            context_vec = self._context_vector(face, image)
            composite = np.concatenate([identity_vec, context_vec])

            results.append(
                FaceEmbedding(
                    embedding=composite,
                    detection=detection
                )
            )

        logger.info(f"🔍 Detected {len(results)} faces")
        return results

    def _context_vector(self, face, image: Image.Image) -> np.ndarray:
        """
        Derive 512 context dims from bbox stats and optional demographics.

        This method tries to pull age/gender from InsightFace if the model exposes them.
        If not available, falls back to defaults (age=0.0, gender=0.5).

        Context vector composition:
        - bbox stats (width, height, area)
        - detection confidence
        - age (if available, else 0.0)
        - gender (if available, else 0.5)
        - Padded to 512 dimensions
        """
        bbox = face.bbox.astype(int)
        width = max(1, bbox[2] - bbox[0])
        height = max(1, bbox[3] - bbox[1])
        area = width * height

        # Extract demographics if available
        age = float(getattr(face, "age", 0.0))
        gender = float(getattr(face, "gender", 0.5))

        stats = np.array([
            width,
            height,
            area,
            face.det_score,
            age,
            gender
        ], dtype=np.float32)

        norm = np.linalg.norm(stats)
        if norm:
            stats = stats / norm

        # Pad/truncate to 512 dims — replace with trainable projection later.
        return np.pad(stats, (0, 512 - stats.shape[0]))[:512]

    def analyze_with_telemetry(
        self,
        image: Image.Image
    ) -> Tuple[List[FaceEmbedding], Dict[str, Any]]:
        """
        Analyze image and return faces with context quality telemetry.

        Use this method to evaluate if context features are being populated
        and decide whether to keep 1024-D embeddings or reduce to 512-D.

        Returns:
            (faces, telemetry) where telemetry includes:
            - face_count: Number of faces detected
            - age_present_count: Faces with non-default age
            - gender_present_count: Faces with non-default gender
            - age_present_ratio: Proportion with age data
            - gender_present_ratio: Proportion with gender data
            - avg_bbox_area: Average face bbox area
            - avg_det_score: Average detection confidence
            - avg_context_norm: Average L2 norm of context vectors
        """
        import asyncio
        faces = asyncio.run(self.analyze(image))

        if not faces:
            return faces, {"face_count": 0}

        age_present = 0
        gender_present = 0
        bbox_areas = []
        det_scores = []
        context_norms = []

        cv2_image = self._pil_to_cv2(image)
        raw_faces = self._app.get(cv2_image)

        for face in raw_faces:
            age = float(getattr(face, "age", 0.0))
            gender = float(getattr(face, "gender", 0.5))

            if age != 0.0:
                age_present += 1
            if gender != 0.5:
                gender_present += 1

            bbox = face.bbox.astype(int)
            bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            bbox_areas.append(bbox_area)
            det_scores.append(float(face.det_score))

            # Compute context vector norm
            context_vec = self._context_vector(face, image)
            context_norms.append(np.linalg.norm(context_vec))

        telemetry = {
            "face_count": len(faces),
            "age_present_count": age_present,
            "gender_present_count": gender_present,
            "age_present_ratio": age_present / len(faces),
            "gender_present_ratio": gender_present / len(faces),
            "avg_bbox_area": np.mean(bbox_areas),
            "avg_det_score": np.mean(det_scores),
            "avg_context_norm": np.mean(context_norms),
        }

        # Warning if all defaults
        if age_present == 0 and gender_present == 0:
            logger.warning(
                f"⚠️ Context features using defaults for all {len(faces)} faces. "
                f"Model may not provide age/gender. Consider reducing to 512-D embeddings."
            )

        return faces, telemetry

    def model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self.settings.insightface.model_name,
            "device": self.settings.insightface.device,
            "embedding_dimension": 1024,
            "identity_dimension": 512,
            "context_dimension": 512,
            "detection_threshold": self.settings.insightface.det_thresh,
            "context_features": ["bbox_stats", "det_score", "age?", "gender?"]
        }
```

---

## Part 3: Face Clustering Service

### Clustering Algorithm

```python
# apps/prototype-description-service/recognition/application/face_clustering_service.py

import logging
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists

from db.models import MediaFace, FaceCluster, ClusterMember

logger = logging.getLogger(__name__)


class FaceClusteringService:
    """Cluster similar faces using pgvector cosine distance + cluster_members."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        similarity_threshold: float = 0.6
    ):
        self.session = session
        self.tenant_id = tenant_id
        self.threshold = similarity_threshold

    async def cluster_faces(self) -> List[FaceCluster]:
        logger.info(f"Starting face clustering for tenant {self.tenant_id}")

        unclustered_faces = await self._get_unclustered_faces()
        if not unclustered_faces:
            logger.info("No unclustered faces found")
            return []

        processed_ids = set()
        clusters_created: List[FaceCluster] = []

        for seed_face in unclustered_faces:
            if seed_face.id in processed_ids:
                continue

            candidates = await self._find_similar_faces(seed_face, self.threshold)
            if len(candidates) < 2:
                processed_ids.add(seed_face.id)
                continue

            cluster = await self._create_cluster(candidates)
            clusters_created.append(cluster)

            for face, _ in candidates:
                processed_ids.add(face.id)

        logger.info(f"✅ Created {len(clusters_created)} clusters")
        return clusters_created

    async def _get_unclustered_faces(self) -> List[MediaFace]:
        """Fetch faces that are not in cluster_members yet."""
        membership_exists = (
            select(1)
            .where(
                ClusterMember.tenant_id == self.tenant_id,
                ClusterMember.face_id == MediaFace.id
            )
            .exists()
        )

        stmt = (
            select(MediaFace)
            .where(
                MediaFace.tenant_id == self.tenant_id,
                MediaFace.is_deleted.is_(False),
                ~membership_exists
            )
            .order_by(MediaFace.created_at)
        )

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def _find_similar_faces(
        self,
        query_face: MediaFace,
        threshold: float
    ) -> List[Tuple[MediaFace, float]]:
        """Return faces plus similarity score using pgvector distance."""
        max_distance = 1 - threshold
        distance_expr = MediaFace.embedding.cosine_distance(query_face.embedding).label("distance")

        membership_exists = (
            select(1)
            .where(
                ClusterMember.tenant_id == self.tenant_id,
                ClusterMember.face_id == MediaFace.id
            )
            .exists()
        )

        stmt = (
            select(MediaFace, distance_expr)
            .where(
                MediaFace.tenant_id == self.tenant_id,
                MediaFace.is_deleted.is_(False),
                ~membership_exists,
                distance_expr < max_distance
            )
            .order_by(distance_expr)
            .limit(100)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        faces_with_scores: List[Tuple[MediaFace, float]] = []
        for face, distance in rows:
            similarity = max(0.0, 1 - float(distance))
            faces_with_scores.append((face, similarity))

        return faces_with_scores

    async def _create_cluster(
        self,
        faces_with_scores: List[Tuple[MediaFace, float]]
    ) -> FaceCluster:
        representative = max(faces_with_scores, key=lambda pair: pair[0].confidence)[0]

        cluster = FaceCluster(
            tenant_id=self.tenant_id,
            label=f"cluster-{uuid4().hex[:8]}",
            representative_face_id=representative.id,
            face_count=len(faces_with_scores),
            similarity_threshold=self.threshold,
            clustering_algorithm="pgvector-cosine"
        )

        self.session.add(cluster)
        await self.session.flush()

        for face, similarity in faces_with_scores:
            member = ClusterMember(
                tenant_id=self.tenant_id,
                cluster_id=cluster.id,
                face_id=face.id,
                similarity=similarity,
                created_by_user_id=face.created_by_user_id
            )
            self.session.add(member)

        await self.session.commit()
        logger.info(f"Created cluster {cluster.id} with {len(faces_with_scores)} faces")
        return cluster

    async def get_cluster_summary(self, cluster_id: UUID) -> Dict[str, Any]:
        cluster = await self.session.get(FaceCluster, cluster_id)
        if not cluster:
            raise ValueError(f"Cluster {cluster_id} not found")

        stmt = (
            select(ClusterMember, MediaFace)
            .join(MediaFace, ClusterMember.face_id == MediaFace.id)
            .where(ClusterMember.cluster_id == cluster_id)
            .order_by(ClusterMember.similarity.desc())
            .limit(10)
        )

        result = await self.session.execute(stmt)
        sample_rows = result.all()
        member_id_rows = await self.session.execute(
            select(ClusterMember.face_id).where(ClusterMember.cluster_id == cluster_id)
        )
        member_ids = [str(row[0]) for row in member_id_rows]

        return {
            "id": str(cluster.id),
            "label": cluster.label,
            "face_count": cluster.face_count,
            "member_ids": member_ids,
            "representative_face": {
                "media_id": cluster.representative_face.media_id if cluster.representative_face else None,
                "bbox": {
                    "x": cluster.representative_face.bbox_x if cluster.representative_face else 0,
                    "y": cluster.representative_face.bbox_y if cluster.representative_face else 0,
                    "width": cluster.representative_face.bbox_width if cluster.representative_face else 0,
                    "height": cluster.representative_face.bbox_height if cluster.representative_face else 0
                }
            },
            "sample_faces": [
                {
                    "id": str(face.id),
                    "media_id": face.media_id,
                    "similarity": member.similarity,
                    "bbox": {
                        "x": face.bbox_x,
                        "y": face.bbox_y,
                        "width": face.bbox_width,
                        "height": face.bbox_height
                    },
                    "confidence": face.confidence
                }
        for member, face in sample_rows
            ]
        }
```

### Cluster UX

The Roster UI now renders recognition cluster cards that show up to four padded, cropped faces per cluster and open a right-side drawer with every member thumbnail normalized to the same canvas size; users can drag/drop faces within `RosterPage.tsx` (Radix DnD/react-beautiful-dnd) to consolidate stray detections or drop false positives before mapping a cluster to a roster identity. Add a Workbench “View clusters” action that deep links to `?page=alt-context-roster&tab=clusters` so reviewers can jump straight to the editing surface after a job completes. The deep link ships via `ConfirmPanel`’s “Open clusters in roster” button (`apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx`), which reuses `rosterClustersUrl()`.

---

## Part 4: FastAPI Endpoints

### REST API Routes

```python
# apps/prototype-description-service/recognition/interface_adapters/http/recognition_router.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID

from db.session import get_session
from db.models import FaceScanJob
from recognition.application.face_scan_service import FaceScanService
from recognition.application.face_clustering_service import FaceClusteringService
from recognition.infrastructure.embedding_provider import FaceEmbeddingProvider

router = APIRouter(prefix="/recognition", tags=["recognition"])


# Request/Response Models
class MediaItem(BaseModel):
    media_id: int
    media_url: str


class ScanRequest(BaseModel):
    tenant_id: UUID
    media_items: List[MediaItem] = Field(..., min_items=1, max_items=100)
    user_id: Optional[int] = None


class ScanResponse(BaseModel):
    job_id: UUID
    status: str
    total_media: int


class ClusterRequest(BaseModel):
    tenant_id: UUID
    similarity_threshold: Optional[float] = 0.6


class ClusterResponse(BaseModel):
    clusters_created: int
    total_faces_clustered: int


class ClusterSummaryResponse(BaseModel):
    id: str
    label: str
    face_count: int
    member_ids: List[str]
    representative_face: dict
    sample_faces: List[dict]


# Dependencies
def get_embedding_provider() -> FaceEmbeddingProvider:
    return FaceEmbeddingProvider()


@router.post("/scan", response_model=ScanResponse)
async def scan_faces(
    request: ScanRequest,
    session: AsyncSession = Depends(get_session),
    provider: FaceEmbeddingProvider = Depends(get_embedding_provider)
):
    """Scan media items synchronously and still return a job id for telemetry."""
    job = FaceScanJob(
        tenant_id=request.tenant_id,
        status="running",
        media_ids=[item.media_id for item in request.media_items],
        total_media=len(request.media_items),
        created_by_user_id=request.user_id
    )

    session.add(job)
    await session.commit()
    await session.refresh(job)

    service = FaceScanService(session, provider, request.tenant_id)
    await service.scan_batch(
        media_items=[item.dict() for item in request.media_items],
        job_id=job.id,
        user_id=request.user_id
    )

    await session.refresh(job)
    return ScanResponse(
        job_id=job.id,
        status=job.status,
        total_media=job.total_media
    )


@router.get("/scan/{job_id}")
async def get_scan_status(
    job_id: UUID,
    session: AsyncSession = Depends(get_session)
):
    """Get scan job status and progress."""
    job = await session.get(FaceScanJob, job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": str(job.id),
        "status": job.status,
        "total_media": job.total_media,
        "processed_media": job.processed_media,
        "faces_detected": job.faces_detected,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None
    }


@router.post("/cluster", response_model=ClusterResponse)
async def cluster_faces(
    request: ClusterRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    Cluster similar faces using pgvector cosine similarity.

    Groups unclustered faces above the similarity threshold.
    """
    service = FaceClusteringService(
        session=session,
        tenant_id=request.tenant_id,
        similarity_threshold=request.similarity_threshold
    )

    clusters = await service.cluster_faces()

    total_faces = sum(cluster.face_count for cluster in clusters)

    return ClusterResponse(
        clusters_created=len(clusters),
        total_faces_clustered=total_faces
    )


@router.get("/clusters", response_model=List[ClusterSummaryResponse])
async def list_clusters(
    tenant_id: UUID,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session)
):
    """List clusters for tenant with pagination."""
    from sqlalchemy import select
    from db.models import FaceCluster

    stmt = (
        select(FaceCluster)
        .where(FaceCluster.tenant_id == tenant_id)
        .order_by(FaceCluster.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(stmt)
    clusters = result.scalars().all()

    service = FaceClusteringService(session, tenant_id)
    summaries = []

    for cluster in clusters:
        summary = await service.get_cluster_summary(cluster.id)
        summaries.append(ClusterSummaryResponse(**summary))

    return summaries


@router.get("/clusters/{cluster_id}", response_model=ClusterSummaryResponse)
async def get_cluster(
    cluster_id: UUID,
    session: AsyncSession = Depends(get_session)
):
    """Get detailed cluster information."""
    from db.models import FaceCluster

    cluster = await session.get(FaceCluster, cluster_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    service = FaceClusteringService(session, cluster.tenant_id)
    summary = await service.get_cluster_summary(cluster_id)

    return ClusterSummaryResponse(**summary)
```

> **Contract docs**: mirror each payload above into `docs/architecture/contracts/workbench/recognition-analyze.json` and `recognition-clusters.json` so the Workbench SPA and WordPress proxy compile-time types stay aligned with the backend.

---

## Part 5: WordPress Integration

### WordPress REST Proxy Endpoints

```php
// apps/prototype-wp-alt-context/src/api/class-recognition-proxy-controller.php

<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_REST_Request;
use WP_REST_Response;
use WP_Error;

/**
 * REST controller for recognition operations.
 *
 * Proxies requests to prototype description service.
 */
class RecognitionProxyController
{
    private string $recognition_base_url;
    private string $api_key;

    public function __construct()
    {
        $this->recognition_base_url = get_option('alt_context_recognition_url', 'http://localhost:8000');
        $this->api_key = get_option('alt_context_recognition_api_key', '');
    }

    public function register_routes(): void
    {
        register_rest_route('alt-context/v1', '/workbench/recognition/analyze', [
            'methods' => 'POST',
            'callback' => [$this, 'scan_faces'],
            'permission_callback' => [$this, 'check_permissions'],
            'args' => [
                'media_ids' => [
                    'required' => true,
                    'type' => 'array',
                    'items' => ['type' => 'integer'],
                    'validate_callback' => function ($media_ids) {
                        return count($media_ids) > 0 && count($media_ids) <= 100;
                    }
                ]
            ]
        ]);

        register_rest_route('alt-context/v1', '/workbench/recognition/jobs/(?P<job_id>[a-f0-9-]+)', [
            'methods' => 'GET',
            'callback' => [$this, 'get_scan_status'],
            'permission_callback' => [$this, 'check_permissions']
        ]);

        register_rest_route('alt-context/v1', '/workbench/recognition/cluster', [
            'methods' => 'POST',
            'callback' => [$this, 'cluster_faces'],
            'permission_callback' => [$this, 'check_permissions']
        ]);

        register_rest_route('alt-context/v1', '/workbench/recognition/clusters', [
            'methods' => 'GET',
            'callback' => [$this, 'list_clusters'],
            'permission_callback' => [$this, 'check_permissions']
        ]);
    }

    public function check_permissions(): bool
    {
        return current_user_can('manage_options');
    }

    public function scan_faces(WP_REST_Request $request): WP_REST_Response|WP_Error
    {
        $media_ids = $request->get_param('media_ids');

        // Build media items with secure URLs
        $media_items = [];
        foreach ($media_ids as $media_id) {
            $url = wp_get_attachment_url($media_id);
            if (!$url) {
                continue;
            }

            $media_items[] = [
                'media_id' => $media_id,
                'media_url' => $url
            ];
        }

        if (empty($media_items)) {
            return new WP_Error('no_valid_media', 'No valid media items found', ['status' => 400]);
        }

        // Call recognition service
        $response = wp_remote_post(
            $this->recognition_base_url . '/recognition/analyze',
            [
                'headers' => [
                    'Content-Type' => 'application/json',
                    'X-API-Key' => $this->api_key
                ],
                'body' => json_encode([
                    'tenant_id' => $this->get_tenant_id(),
                    'media_items' => $media_items,
                    'user_id' => get_current_user_id()
                ]),
                'timeout' => 60
            ]
        );

        if (is_wp_error($response)) {
            return $response;
        }

        $body = json_decode(wp_remote_retrieve_body($response), true);

        return new WP_REST_Response($body, wp_remote_retrieve_response_code($response));
    }

    public function get_scan_status(WP_REST_Request $request): WP_REST_Response|WP_Error
    {
        $job_id = $request->get_param('job_id');

        $response = wp_remote_get(
            $this->recognition_base_url . "/recognition/jobs/{$job_id}",
            [
                'headers' => [
                    'X-API-Key' => $this->api_key
                ],
                'timeout' => 30
            ]
        );

        if (is_wp_error($response)) {
            return $response;
        }

        $body = json_decode(wp_remote_retrieve_body($response), true);

        return new WP_REST_Response($body, wp_remote_retrieve_response_code($response));
    }

    public function cluster_faces(WP_REST_Request $request): WP_REST_Response|WP_Error
    {
        $threshold = $request->get_param('similarity_threshold') ?? 0.6;

        $response = wp_remote_post(
            $this->recognition_base_url . '/recognition/cluster',
            [
                'headers' => [
                    'Content-Type' => 'application/json',
                    'X-API-Key' => $this->api_key
                ],
                'body' => json_encode([
                    'tenant_id' => $this->get_tenant_id(),
                    'similarity_threshold' => $threshold
                ]),
                'timeout' => 120
            ]
        );

        if (is_wp_error($response)) {
            return $response;
        }

        $body = json_decode(wp_remote_retrieve_body($response), true);

        return new WP_REST_Response($body, wp_remote_retrieve_response_code($response));
    }

    public function list_clusters(WP_REST_Request $request): WP_REST_Response|WP_Error
    {
        $limit = $request->get_param('limit') ?? 50;
        $offset = $request->get_param('offset') ?? 0;

        $url = add_query_arg(
            [
                'tenant_id' => $this->get_tenant_id(),
                'limit' => $limit,
                'offset' => $offset
            ],
            $this->recognition_base_url . '/recognition/clusters'
        );

        $response = wp_remote_get(
            $url,
            [
                'headers' => [
                    'X-API-Key' => $this->api_key
                ],
                'timeout' => 30
            ]
        );

        if (is_wp_error($response)) {
            return $response;
        }

        $body = json_decode(wp_remote_retrieve_body($response), true);

        return new WP_REST_Response($body, wp_remote_retrieve_response_code($response));
    }

    private function get_tenant_id(): string
    {
        // Use site URL as tenant identifier
        $site_url = get_site_url();
        return md5($site_url); // Or store UUID in options
    }
}
```

### React Query Hooks

```typescript
// apps/prototype-wp-alt-context/js/hooks/useRecognitionHooks.ts

import { useMutation, useQuery } from "@tanstack/react-query";
import { fetchApi } from "@/admin/utils/http";
import { getDashboardConfig } from "@/admin/dashboardData";

interface ScanRequest {
  mediaIds: number[];
}

interface ScanResponse {
  job_id: string;
  status: string;
  total_media: number;
}

interface ScanStatus {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  total_media: number;
  processed_media: number;
  faces_detected: number;
  error_message?: string;
  created_at: string;
  completed_at?: string;
}

export const useScanFaces = () => {
  const config = getDashboardConfig();
  const endpoint = `${config.endpoints.workbench}/recognition/analyze`;
  const restNonce = config.restNonce;

  return useMutation({
    mutationFn: async (request: ScanRequest): Promise<ScanResponse> => {
      return await fetchApi<ScanResponse>(endpoint, {
        method: "POST",
        restNonce,
        body: JSON.stringify({
          media_ids: request.mediaIds,
        }),
      });
    },
  });
};

export const useScanStatus = (
  jobId: string | null,
  enabled: boolean = true
) => {
  const config = getDashboardConfig();
  const endpoint = jobId
    ? `${config.endpoints.workbench}/recognition/jobs/${jobId}`
    : null;
  const restNonce = config.restNonce;

  return useQuery({
    queryKey: ["recognition-status", jobId],
    queryFn: async (): Promise<ScanStatus> => {
      if (!endpoint) throw new Error("No job ID");

      return await fetchApi<ScanStatus>(endpoint, {
        method: "GET",
        restNonce,
      });
    },
    enabled: enabled && !!jobId,
    refetchInterval: (data) => {
      // Poll while job is running
      if (data?.status === "pending" || data?.status === "running") {
        return 2000; // Poll every 2 seconds
      }
      return false; // Stop polling when done
    },
  });
};

export const useClusterFaces = () => {
  const config = getDashboardConfig();
  const endpoint = `${config.endpoints.workbench}/recognition/cluster`;
  const restNonce = config.restNonce;

  return useMutation({
    mutationFn: async (threshold: number = 0.6) => {
      return await fetchApi(endpoint, {
        method: "POST",
        restNonce,
        body: JSON.stringify({
          similarity_threshold: threshold,
        }),
      });
    },
  });
};
```

---

## Part 6: Roster Clusters UI

### Roster UX Overview

The Roster page provides a dedicated interface for reviewing and managing face clusters detected by the recognition service. The Clusters tab displays a grid of cluster cards, each showing representative faces to help reviewers identify patterns. Selecting a cluster opens a detail drawer with normalized thumbnails and management actions.

### Cluster Grid Component

```typescript
// apps/prototype-wp-alt-context/js/components/roster/ClusterGrid.tsx

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchApi } from "@/admin/utils/http";
import { getDashboardConfig } from "@/admin/dashboardData";
import { ClusterCard } from "./ClusterCard";

interface Cluster {
  id: string;
  label: string;
  face_count: number;
  representative_face: {
    media_id: number;
    bbox: { x: number; y: number; width: number; height: number };
  };
  sample_faces: Array<{
    id: string;
    media_id: number;
    bbox: { x: number; y: number; width: number; height: number };
    confidence: number;
  }>;
}

interface ClusterGridProps {
  onClusterSelect: (clusterId: string) => void;
}

export const ClusterGrid: React.FC<ClusterGridProps> = ({
  onClusterSelect,
}) => {
  const config = getDashboardConfig();
  const endpoint = `${config.endpoints.workbench}/recognition/clusters`;

  const { data: clusters, isLoading } = useQuery({
    queryKey: ["recognition-clusters"],
    queryFn: async (): Promise<Cluster[]> => {
      return await fetchApi(endpoint, {
        method: "GET",
        restNonce: config.restNonce,
      });
    },
  });

  if (isLoading) {
    return <div className="cat-cluster-grid__loading">Loading clusters...</div>;
  }

  if (!clusters || clusters.length === 0) {
    return (
      <div className="cat-cluster-grid__empty">
        <p>No clusters found. Scan media to detect faces.</p>
      </div>
    );
  }

  return (
    <div className="cat-cluster-grid">
      {clusters.map((cluster) => (
        <ClusterCard
          key={cluster.id}
          cluster={cluster}
          onClick={() => onClusterSelect(cluster.id)}
        />
      ))}
    </div>
  );
};
```

### Cluster Card Component

```typescript
// apps/prototype-wp-alt-context/js/components/roster/ClusterCard.tsx

import React from "react";
import { FaceThumbnail } from "./FaceThumbnail";

interface ClusterCardProps {
  cluster: {
    id: string;
    label: string;
    face_count: number;
    sample_faces: Array<{
      id: string;
      media_id: number;
      bbox: { x: number; y: number; width: number; height: number };
    }>;
  };
  onClick: () => void;
}

export const ClusterCard: React.FC<ClusterCardProps> = ({
  cluster,
  onClick,
}) => {
  // Show up to 4 faces for quick visual comparison
  const displayFaces = cluster.sample_faces.slice(0, 4);

  return (
    <div className="cat-cluster-card" onClick={onClick}>
      <div className="cat-cluster-card__thumbnails">
        {displayFaces.map((face) => (
          <FaceThumbnail
            key={face.id}
            mediaId={face.media_id}
            bbox={face.bbox}
            size="small"
            padding={0.01} // 1% padding around bbox
          />
        ))}
      </div>
      <div className="cat-cluster-card__footer">
        <span className="cat-cluster-card__label">{cluster.label}</span>
        <span className="cat-cluster-card__count">
          {cluster.face_count} {cluster.face_count === 1 ? "face" : "faces"}
        </span>
      </div>
    </div>
  );
};
```

### Face Thumbnail Component

```typescript
// apps/prototype-wp-alt-context/js/components/roster/FaceThumbnail.tsx

import React from "react";

interface FaceThumbnailProps {
  mediaId: number;
  bbox: { x: number; y: number; width: number; height: number };
  size: "small" | "normalized";
  padding?: number; // Percentage of bbox to add as padding (e.g., 0.01 = 1%)
  onClick?: () => void;
}

export const FaceThumbnail: React.FC<FaceThumbnailProps> = ({
  mediaId,
  bbox,
  size,
  padding = 0.01,
  onClick,
}) => {
  // Calculate padded bbox
  const paddingX = bbox.width * padding;
  const paddingY = bbox.height * padding;

  const paddedBbox = {
    x: Math.max(0, bbox.x - paddingX),
    y: Math.max(0, bbox.y - paddingY),
    width: bbox.width + 2 * paddingX,
    height: bbox.height + 2 * paddingY,
  };

  // For normalized size, use consistent canvas (128×128)
  const canvasSize = size === "normalized" ? 128 : undefined;

  // Build thumbnail URL with crop parameters
  const thumbnailUrl = buildThumbnailUrl(mediaId, paddedBbox, canvasSize);

  const className = `cat-face-thumbnail cat-face-thumbnail--${size}`;

  return (
    <div className={className} onClick={onClick}>
      <img
        src={thumbnailUrl}
        alt={`Face from media ${mediaId}`}
        loading="lazy"
      />
    </div>
  );
};

function buildThumbnailUrl(
  mediaId: number,
  bbox: { x: number; y: number; width: number; height: number },
  canvasSize?: number
): string {
  // WordPress REST API endpoint for cropped thumbnails
  const params = new URLSearchParams({
    crop_x: bbox.x.toString(),
    crop_y: bbox.y.toString(),
    crop_width: bbox.width.toString(),
    crop_height: bbox.height.toString(),
  });

  if (canvasSize) {
    params.append("canvas_width", canvasSize.toString());
    params.append("canvas_height", canvasSize.toString());
  }

  return `/wp-json/alt-context/v1/media/${mediaId}/crop?${params}`;
}
```

### Cluster Detail Drawer

```typescript
// apps/prototype-wp-alt-context/js/components/roster/ClusterDetailDrawer.tsx

import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { fetchApi } from "@/admin/utils/http";
import { getDashboardConfig } from "@/admin/dashboardData";
import { FaceThumbnail } from "./FaceThumbnail";
import { useToast } from "@/contexts/ToastContext";

interface ClusterDetailDrawerProps {
  clusterId: string | null;
  onClose: () => void;
}

interface ClusterDetail {
  id: string;
  label: string;
  face_count: number;
  similarity_threshold: number;
  sample_faces: Array<{
    id: string;
    media_id: number;
    bbox: { x: number; y: number; width: number; height: number };
    confidence: number;
  }>;
}

export const ClusterDetailDrawer: React.FC<ClusterDetailDrawerProps> = ({
  clusterId,
  onClose,
}) => {
  const config = getDashboardConfig();
  const queryClient = useQueryClient();
  const { addToast } = useToast();

  const { data: cluster, isLoading } = useQuery({
    queryKey: ["recognition-cluster", clusterId],
    queryFn: async (): Promise<ClusterDetail> => {
      const endpoint = `${config.endpoints.workbench}/recognition/clusters/${clusterId}`;
      return await fetchApi(endpoint, {
        method: "GET",
        restNonce: config.restNonce,
      });
    },
    enabled: !!clusterId,
  });

  const rescanMutation = useMutation({
    mutationFn: async () => {
      const endpoint = `${config.endpoints.workbench}/recognition/analyze`;
      return await fetchApi(endpoint, {
        method: "POST",
        restNonce: config.restNonce,
        body: JSON.stringify({
          cluster_id: clusterId,
          sensitivity: "high",
        }),
      });
    },
    onSuccess: () => {
      addToast({
        type: "success",
        message: "Rescan initiated with sensitive settings",
      });
      queryClient.invalidateQueries({ queryKey: ["recognition-clusters"] });
    },
  });

  const commitMutation = useMutation({
    mutationFn: async (rosterEntryId: string) => {
      const endpoint = `${config.endpoints.roster}/clusters/${clusterId}/commit`;
      return await fetchApi(endpoint, {
        method: "POST",
        restNonce: config.restNonce,
        body: JSON.stringify({
          roster_entry_id: rosterEntryId,
        }),
      });
    },
    onSuccess: () => {
      addToast({
        type: "success",
        message: "Cluster committed to roster entry",
      });
      queryClient.invalidateQueries({ queryKey: ["recognition-clusters"] });
      onClose();
    },
  });

  const handleThumbnailClick = (mediaId: number) => {
    // Open WordPress attachment edit screen
    window.open(`/wp-admin/post.php?post=${mediaId}&action=edit`, "_blank");
  };

  if (!clusterId) return null;

  return (
    <Sheet open={!!clusterId} onOpenChange={onClose}>
      <SheetContent side="right" className="cat-cluster-drawer">
        <SheetHeader>
          <SheetTitle>
            {cluster?.label || "Cluster Details"}
            {cluster && (
              <span className="cat-cluster-drawer__count">
                {cluster.face_count} faces
              </span>
            )}
          </SheetTitle>
        </SheetHeader>

        {isLoading && <div>Loading cluster details...</div>}

        {cluster && (
          <>
            <div className="cat-cluster-drawer__metadata">
              <div className="cat-cluster-drawer__meta-item">
                <span className="cat-cluster-drawer__meta-label">
                  Similarity Threshold:
                </span>
                <span className="cat-cluster-drawer__meta-value">
                  {(cluster.similarity_threshold * 100).toFixed(0)}%
                </span>
              </div>
            </div>

            <div className="cat-cluster-drawer__faces">
              {cluster.sample_faces.map((face) => (
                <FaceThumbnail
                  key={face.id}
                  mediaId={face.media_id}
                  bbox={face.bbox}
                  size="normalized"
                  onClick={() => handleThumbnailClick(face.media_id)}
                />
              ))}
            </div>

            <div className="cat-cluster-drawer__actions">
              <Button
                variant="outline"
                onClick={() => rescanMutation.mutate()}
                disabled={rescanMutation.isPending}
              >
                Rescan with Sensitive Settings
              </Button>
              <Button
                onClick={() => {
                  // TODO: Open roster entry picker dialog
                  const rosterEntryId = "placeholder-id";
                  commitMutation.mutate(rosterEntryId);
                }}
                disabled={commitMutation.isPending}
              >
                Commit to Roster Entry
              </Button>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
};
```

### Roster Page Integration

```typescript
// apps/prototype-wp-alt-context/js/components/roster/RosterPage.tsx

import React, { useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ClusterGrid } from "./ClusterGrid";
import { ClusterDetailDrawer } from "./ClusterDetailDrawer";
import { RosterEntriesList } from "./RosterEntriesList";

export const RosterPage: React.FC = () => {
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(
    null
  );

  return (
    <div className="cat-roster-page">
      <Tabs defaultValue="entries">
        <TabsList>
          <TabsTrigger value="entries">Entries</TabsTrigger>
          <TabsTrigger value="clusters">Clusters</TabsTrigger>
        </TabsList>

        <TabsContent value="entries">
          <RosterEntriesList />
        </TabsContent>

        <TabsContent value="clusters">
          <ClusterGrid onClusterSelect={setSelectedClusterId} />
        </TabsContent>
      </Tabs>

      <ClusterDetailDrawer
        clusterId={selectedClusterId}
        onClose={() => setSelectedClusterId(null)}
      />
    </div>
  );
};
```

### Styles (SCSS)

```scss
// apps/prototype-wp-alt-context/src/styles/components/_cluster-grid.scss

.cat-cluster-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1rem;
  padding: 1rem;

  &__loading,
  &__empty {
    grid-column: 1 / -1;
    text-align: center;
    padding: 2rem;
    color: var(--color-text-secondary);
  }
}

.cat-cluster-card {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 0.75rem;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--color-primary);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  }

  &__thumbnails {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }

  &__footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  &__label {
    font-weight: 500;
    font-size: 0.875rem;
  }

  &__count {
    font-size: 0.75rem;
    color: var(--color-text-secondary);
  }
}

.cat-face-thumbnail {
  position: relative;
  overflow: hidden;
  border-radius: 4px;
  background: var(--color-background-alt);

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  &--small {
    aspect-ratio: 1;
  }

  &--normalized {
    width: 128px;
    height: 128px;
    cursor: pointer;
    transition: transform 0.2s ease;

    &:hover {
      transform: scale(1.05);
    }
  }
}

.cat-cluster-drawer {
  width: 400px;

  &__count {
    margin-left: 0.5rem;
    font-size: 0.875rem;
    color: var(--color-text-secondary);
    font-weight: normal;
  }

  &__metadata {
    padding: 1rem 0;
    border-bottom: 1px solid var(--color-border);
  }

  &__meta-item {
    display: flex;
    justify-content: space-between;
    margin-bottom: 0.5rem;
  }

  &__meta-label {
    font-size: 0.875rem;
    color: var(--color-text-secondary);
  }

  &__meta-value {
    font-weight: 500;
  }

  &__faces {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.75rem;
    padding: 1rem 0;
    max-height: 60vh;
    overflow-y: auto;
  }

  &__actions {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding-top: 1rem;
    border-top: 1px solid var(--color-border);
  }
}
```

### WordPress Media Crop Endpoint

```php
// apps/prototype-wp-alt-context/src/api/class-media-crop-controller.php

<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_REST_Request;
use WP_REST_Response;
use WP_Error;

/**
 * REST controller for cropping media thumbnails.
 */
class MediaCropController
{
    public function register_routes(): void
    {
        register_rest_route('alt-context/v1', '/media/(?P<id>\d+)/crop', [
            'methods' => 'GET',
            'callback' => [$this, 'get_cropped_thumbnail'],
            'permission_callback' => [$this, 'check_permissions'],
            'args' => [
                'id' => [
                    'required' => true,
                    'type' => 'integer',
                    'sanitize_callback' => 'absint'
                ],
                'crop_x' => [
                    'required' => true,
                    'type' => 'number',
                    'sanitize_callback' => 'floatval'
                ],
                'crop_y' => [
                    'required' => true,
                    'type' => 'number',
                    'sanitize_callback' => 'floatval'
                ],
                'crop_width' => [
                    'required' => true,
                    'type' => 'number',
                    'sanitize_callback' => 'floatval'
                ],
                'crop_height' => [
                    'required' => true,
                    'type' => 'number',
                    'sanitize_callback' => 'floatval'
                ],
                'canvas_width' => [
                    'required' => false,
                    'type' => 'integer',
                    'default' => null,
                    'sanitize_callback' => 'absint'
                ],
                'canvas_height' => [
                    'required' => false,
                    'type' => 'integer',
                    'default' => null,
                    'sanitize_callback' => 'absint'
                ]
            ]
        ]);
    }

    public function check_permissions(): bool
    {
        return current_user_can('manage_options');
    }

    public function get_cropped_thumbnail(WP_REST_Request $request): WP_REST_Response|WP_Error
    {
        $media_id = $request->get_param('id');
        $crop_x = $request->get_param('crop_x');
        $crop_y = $request->get_param('crop_y');
        $crop_width = $request->get_param('crop_width');
        $crop_height = $request->get_param('crop_height');
        $canvas_width = $request->get_param('canvas_width');
        $canvas_height = $request->get_param('canvas_height');

        // Get original image path
        $file_path = get_attached_file($media_id);
        if (!$file_path || !file_exists($file_path)) {
            return new WP_Error('file_not_found', 'Media file not found', ['status' => 404]);
        }

        // Load image
        $image = wp_get_image_editor($file_path);
        if (is_wp_error($image)) {
            return $image;
        }

        // Crop to face bbox
        $image->crop($crop_x, $crop_y, $crop_width, $crop_height);

        // Optionally resize to normalized canvas
        if ($canvas_width && $canvas_height) {
            $image->resize($canvas_width, $canvas_height, false);
        }

        // Stream image
        $image->stream('image/jpeg', 85);
        exit;
    }
}
```

---

## Part 7: Implementation Phases

### Phase 1: Database Foundation (completed)

**Deliverables**:

- [x] PostgreSQL database with pgvector extension
- [x] SQLAlchemy models with tenant isolation
- [x] Alembic migration for schema
- [ ] Docker compose with PostgreSQL container (still pending)
- [x] Database session management with async support

**Acceptance Criteria**:

- Tables created with proper indexes
- pgvector extension enabled
- Migration runs without errors
- Can insert/query test data
- Tenant isolation enforced at query level

### Phase 2: InsightFace Integration (completed)

**Deliverables**:

- [x] EmbeddingProvider with lazy loading
- [x] Face detection with bbox extraction
- [x] 1024-dimensional embedding extraction
- [x] Pydantic settings for model configuration
- [x] Unit tests for adapter

**Acceptance Criteria**:

- Model loads on first use
- Detects faces in test images
- Embeddings are 1024-dimensional normalized vectors (512 identity + 512 context)
- Detection threshold configurable
- Handles images without faces gracefully

### Phase 3: Recognition Analyze Service (completed)

**Deliverables**:

- [x] FaceScanService with single/batch scanning
- [x] Image fetching from WordPress URLs
- [x] MediaFace persistence with tenant_id
- [x] FaceScanJob tracking with progress
- [x] FastAPI `/recognition/analyze` endpoint

**Acceptance Criteria**:

- Can scan single media item
- Batch scanning updates job progress
- Faces persisted to database
- Job status queryable
- Errors logged and returned

### Phase 4: Recognition Clustering (completed)

**Deliverables**:

- [x] FaceClusteringService with pgvector similarity search
- [x] Cluster creation with representative faces
- [x] Cluster summary generation
- [x] FastAPI `/recognition/cluster` and `/recognition/clusters` endpoints

**Acceptance Criteria**:

- Groups similar faces into clusters
- Respects minimum cluster size
- Representative face selected correctly
- Cluster summaries include sample faces
- Handles empty result set

### Phase 5: WordPress REST Proxy (completed)

**Deliverables**:

- [x] RecognitionProxyController with proxy endpoints
- [x] Authentication/authorization checks
- [x] Secure URL generation for media
- [x] Error handling and logging

**Acceptance Criteria**:

- Only admins can trigger scans
- Media URLs are accessible by service
- Errors propagated to frontend
- API key validation

### Phase 6: React UI Integration (completed, extended)

**Deliverables**:

- [x] useScanFaces mutation hook
- [x] useScanStatus polling hook
- [x] useClusterFaces mutation hook
- [x] WorkbenchPage scan workflow (selection → confirmation panel)
- [x] Job progress indicator and persistence + Recent jobs panel (newly added)
- [x] Roster page cluster gallery with thumbnails (newly added)

**Acceptance Criteria**:

- Users can select media and trigger scan
- Progress shown during scan
- Toast notifications on success/error
- Cluster results displayed after clustering

### Phase 7: Roster Integration (4-5 days)

-**Deliverables**:

- [x] RosterPage with Entries and Clusters tabs
- [x] Entries tab: List known identities with name, tags, linked clusters; rows pull from `/acx/v1/roster/entries`
- [x] Clusters tab: Grid of recognition clusters with up to 4 cropped face thumbnails per card (see `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterGrid.tsx`)
- [x] Face cropping with ~1% padding around bbox for expression comparison via the canvas-backed `FaceThumbnail` component
- [x] Cluster detail drawer (right-anchored) with normalized thumbnails (128×128 canvas) and live data fetched from `/recognition/clusters/{cluster_id}`
- [x] Thumbnail links to the originating media item (attachment edit screen) for quick context
- [x] Drag-and-drop face assignment between clusters plus a discard drop zone
- [x] "Rescan with sensitive settings" button (calls `/recognition/analyze` with `sensitivity=high` on the drawer selection)
- [x] "Commit cluster to roster entry" button (maps cluster → identity via `rosterClusters` REST proxy)

**Acceptance Criteria**:

**Clusters Tab Grid**:

- Clusters displayed in responsive grid layout
- Each cluster card shows up to 4 representative face thumbnails
- Thumbnails use cropped regions from original media with 1% bbox padding
- Card displays cluster label and total face count
- Clicking card opens detail drawer

**Cluster Detail Drawer**:

- Drawer anchors to right side of screen (`ClusterDrawerPanel.tsx`)
- Fetches the selected cluster detail via `useRecognitionCluster` and renders every returned face with a normalized 128×128 thumbnail so scale stays consistent
- Each thumbnail links directly to the WordPress attachment edit screen for deeper review
- Drawer shows live drag / drop affordances (including a discard target) and wraps the two workflow buttons: rescan with sensitive settings and commit to roster entry

**Roster Entry Assignment**:

- Can assign cluster to an existing roster entry or create a new entry inline
- Successful commits invalidate both the `recognition-clusters` and `roster-entries` queries so the grid reflects the change without a refresh

---

## Security Considerations

### Multi-Tenant Isolation

1. **Database-level enforcement**: ALL queries MUST filter by `tenant_id`
2. **API key per tenant**: WordPress stores unique API key for service auth
3. **JWT tokens**: Consider JWT with tenant claim for stateless auth
4. **Row-level security**: PostgreSQL RLS policies for additional protection

### WordPress Integration

1. **Capability checks**: Only `manage_options` admins can trigger scans
2. **Nonce validation**: Protect all REST endpoints with nonces
3. **URL signing**: Consider signed URLs for media access
4. **Rate limiting**: Prevent abuse of scan endpoints

---

## Performance Optimization

### Database Indexes

1. **ivfflat index** on embeddings for fast similarity search
2. **Composite indexes** for tenant + cluster queries
3. **Partial indexes** for active (non-deleted) records

### Caching Strategy

1. **Cluster summaries**: Cache for 5 minutes
2. **Scan job status**: Cache while job is running
3. **InsightFace model**: Keep loaded in memory

### Async Processing

1. **Synchronous-first**: `/faces/scan` runs inline today; the job table + status endpoint simply capture telemetry and make the async cut-over trivial.
2. **Job queue**: When batches exceed inline limits, drop Celery/RQ workers behind the same job table without changing contracts.
3. **WebSocket updates**: After async jobs land, replace polling with WS push for the Batch tab.

---

## Testing Strategy

### Unit Tests

- EmbeddingProvider: Detection, 1024-d embedding extraction
- FaceScanService: Single/batch scanning
- FaceClusteringService: Similarity search, clustering

### Integration Tests

- Database: CRUD operations with pgvector
- API: End-to-end scan + cluster flow
- WordPress: Proxy endpoints with mock service

### E2E Tests (Playwright)

- User selects media → Scan → View clusters
- Assign cluster to roster entry
- Verify alt text uses roster data

---

## Monitoring & Observability

### Metrics

- Scan jobs: pending, running, completed, failed
- Faces detected per image (distribution)
- Clustering time and cluster sizes
- pgvector query latency

### Logging

- Structured JSON logs with tenant_id, job_id
- Error tracking with stack traces
- Audit trail for cluster assignments

### Alerts

- Failed scans exceeding threshold
- Database connection issues
- Model loading failures

---

## Appendix: Domain Entities

```python
# apps/prototype-description-service/recognition/domain/entities.py

from dataclasses import dataclass
from typing import Tuple, Optional
import numpy as np


@dataclass
class FaceDetection:
    """Detected face with bounding box and confidence."""
    bbox: Tuple[int, int, int, int]  # (x_min, y_min, x_max, y_max)
    confidence: float
    landmarks: Optional[np.ndarray] = None  # 5-point landmarks

    def area(self) -> float:
        """Calculate bounding box area."""
        x_min, y_min, x_max, y_max = self.bbox
        return max(0, x_max - x_min) * max(0, y_max - y_min)


@dataclass
class FaceEmbedding:
    """Face embedding with associated detection."""
    embedding: np.ndarray  # 1024-dimensional (identity + context)
    detection: FaceDetection

    def to_list(self) -> list:
        """Convert embedding to list for serialization."""
        return self.embedding.tolist()
```

---

## References

- [InsightFace Documentation](https://github.com/deepinsight/insightface)
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [Archived Recognition Service Code](../../../apps/archived-recognition-service)
