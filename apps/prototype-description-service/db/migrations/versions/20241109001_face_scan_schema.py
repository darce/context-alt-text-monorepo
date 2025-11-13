"""Face scan and clustering baseline schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "001_face_scan"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIMENSION = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tenants",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("site_url", sa.String(length=255), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    op.create_table(
        "media_faces",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("media_url", sa.Text(), nullable=False),
        sa.Column("bbox_x", sa.Integer(), nullable=False),
        sa.Column("bbox_y", sa.Integer(), nullable=False),
        sa.Column("bbox_width", sa.Integer(), nullable=False),
        sa.Column("bbox_height", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="confidence_range"
        ),
        sa.UniqueConstraint(
            "tenant_id", "media_id", "bbox_x", "bbox_y", name="unique_media_face"
        ),
    )

    op.create_table(
        "face_clusters",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=255)),
        sa.Column(
            "representative_face_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_faces.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "face_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("roster_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.Column("similarity_threshold", sa.Float()),
        sa.Column(
            "clustering_algorithm",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'cosine_similarity'"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.UniqueConstraint("tenant_id", "label", name="unique_tenant_label"),
    )

    op.create_table(
        "cluster_members",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cluster_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("face_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "face_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_faces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.CheckConstraint(
            "similarity >= 0 AND similarity <= 1", name="similarity_range"
        ),
        sa.UniqueConstraint(
            "cluster_id", "face_id", name="unique_cluster_member"
        ),
        sa.UniqueConstraint(
            "tenant_id", "face_id", name="unique_face_membership"
        ),
    )

    op.create_table(
        "face_scan_jobs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("media_ids", sa.ARRAY(sa.Integer()), nullable=False),
        sa.Column("total_media", sa.Integer(), nullable=False),
        sa.Column(
            "processed_media",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "faces_detected",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="valid_status",
        ),
    )

    op.create_index(
        "idx_media_faces_tenant",
        "media_faces",
        ["tenant_id"],
        postgresql_where=sa.text("NOT is_deleted"),
    )
    op.create_index(
        "idx_media_faces_embedding",
        "media_faces",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "idx_face_clusters_tenant",
        "face_clusters",
        ["tenant_id"],
    )
    op.create_index(
        "idx_face_clusters_roster",
        "face_clusters",
        ["roster_id"],
        postgresql_where=sa.text("roster_id IS NOT NULL"),
    )
    op.create_index(
        "idx_cluster_members_cluster",
        "cluster_members",
        ["cluster_id"],
    )
    op.create_index(
        "idx_cluster_members_face",
        "cluster_members",
        ["face_id"],
    )
    op.create_index(
        "idx_scan_jobs_tenant",
        "face_scan_jobs",
        ["tenant_id"],
    )
    op.create_index(
        "idx_scan_jobs_status",
        "face_scan_jobs",
        ["status"],
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("idx_scan_jobs_status", table_name="face_scan_jobs")
    op.drop_index("idx_scan_jobs_tenant", table_name="face_scan_jobs")
    op.drop_table("face_scan_jobs")

    op.drop_index("idx_cluster_members_face", table_name="cluster_members")
    op.drop_index("idx_cluster_members_cluster", table_name="cluster_members")
    op.drop_table("cluster_members")

    op.drop_index("idx_face_clusters_roster", table_name="face_clusters")
    op.drop_index("idx_face_clusters_tenant", table_name="face_clusters")
    op.drop_table("face_clusters")

    op.drop_index("idx_media_faces_embedding", table_name="media_faces")
    op.drop_index("idx_media_faces_tenant", table_name="media_faces")
    op.drop_table("media_faces")

    op.drop_table("tenants")

    op.execute("DROP EXTENSION IF EXISTS vector")
