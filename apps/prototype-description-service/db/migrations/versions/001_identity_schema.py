"""Identity schema baseline replacing the old face tables with identity tables."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "001_identity_schema"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIMENSION = 512
SAFE_TENANT_EXPR = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"
BYPASS_RLS_EXPR = "COALESCE(NULLIF(current_setting('app.bypass_rls', true), ''), 'false')::boolean"

TENANT_TABLES = [
    "media_identities",
    "identity_clusters",
    "identity_members",
    "identity_scan_jobs",
    "identity_scan_job_items",
    "identity_cluster_representatives",
    "identity_clustering_jobs",
    "identity_suggestions",
    "cluster_merge_suggestions",
    "name_suggestions",
    "identity_cluster_blocks",
    "identity_constraints",
    "recognition_runs",
    "recognition_events",
    "clustering_feedback",
    "audit_events",
    "curation_replay_records",
    "export_jobs",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # NOTE: DROP statements removed - they were causing data loss when alembic version tracking
    # got corrupted. Use scripts/reset_dev_db.sh explicitly if you need a clean slate.
    # The migration is the baseline - if tables already exist, alembic won't re-run this.

    op.create_table(
        "tenants",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("site_url", sa.String(length=255), nullable=False, unique=True),
        sa.Column("next_person_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("retention_mode", sa.String(length=30), nullable=False, server_default=sa.text("'retain_all'")),
        sa.Column("last_export_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_purge_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("retention_updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("api_key_hash", sa.String(length=128), nullable=False, unique=True),
        sa.Column("rate_limit_tier", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_table(
        "media_identities",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'face'"),
        ),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("media_url", sa.Text(), nullable=False),
        sa.Column("bbox_x", sa.Integer(), nullable=False),
        sa.Column("bbox_y", sa.Integer(), nullable=False),
        sa.Column("bbox_width", sa.Integer(), nullable=False),
        sa.Column("bbox_height", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
        # InsightFace metadata
        sa.Column("pose_pitch", sa.Float(), nullable=True),
        sa.Column("pose_yaw", sa.Float(), nullable=True),
        sa.Column("pose_roll", sa.Float(), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("gender", sa.Integer(), nullable=True),  # 0=female, 1=male
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("image_phash", sa.String(length=64), nullable=True),
        sa.Column("last_exported_snapshot_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("moved_by_merge_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disposed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint("abs(vector_norm(embedding) - 1.0) < 0.01", name="media_identity_embedding_unit_norm"),
        sa.CheckConstraint(
            "identity_type IN ('face', 'brand', 'pose', 'gait')",
            name="valid_identity_type",
        ),
        sa.UniqueConstraint("tenant_id", "media_id", "identity_type", "bbox_x", "bbox_y", name="unique_media_identity"),
    )
    op.create_table(
        "curation_replay_records",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("result_status", sa.String(length=20), nullable=False),
        sa.Column("backend_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("conflict_code", sa.String(length=64), nullable=True),
        sa.Column("machine_payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_curation_replay_tenant_idempotency"),
    )

    op.create_table(
        "identity_clusters",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'face'"),
        ),
        sa.Column("label", sa.String(length=255)),
        sa.Column(
            "representative_identity_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_identities.id", ondelete="SET NULL"),
        ),
        sa.Column("identity_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("roster_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.Column("similarity_threshold", sa.Float()),
        sa.Column("curriculum_t", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column(
            "curriculum_t_updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "clustering_algorithm",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'cosine_similarity'"),
        ),
        # User confirmation tracking for cold-start ground truth
        sa.Column("user_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confirmation_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("confirmation_source", sa.String(length=20)),  # label, merge, assignment, split, reject
        sa.Column("last_exported_snapshot_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disposed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.Column("dismissed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "identity_type IN ('face', 'brand', 'pose', 'gait')",
            name="cluster_valid_identity_type",
        ),
        sa.CheckConstraint(
            "confirmation_source IS NULL OR confirmation_source IN ('label', 'merge', 'assignment', 'split', 'reject')",
            name="valid_confirmation_source",
        ),
        sa.UniqueConstraint("tenant_id", "identity_type", "label", name="unique_tenant_identity_label"),
    )

    op.create_table(
        "identity_members",
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
            sa.ForeignKey("identity_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.CheckConstraint("similarity >= 0 AND similarity <= 1", name="similarity_range"),
        sa.UniqueConstraint("cluster_id", "identity_id", name="unique_identity_member"),
        sa.UniqueConstraint("tenant_id", "identity_id", name="unique_identity_membership"),
    )

    op.create_table(
        "identity_cluster_representatives",
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
            sa.ForeignKey("identity_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
        sa.Column("pose_pitch", sa.Float(), nullable=True),
        sa.Column("pose_yaw", sa.Float(), nullable=True),
        sa.Column("pose_roll", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("diversity_score", sa.Float(), nullable=True),
        sa.Column("is_user_selected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_provisional", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_exported_snapshot_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disposed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="quality_score_range"),
        sa.CheckConstraint("abs(vector_norm(embedding) - 1.0) < 0.01", name="cluster_rep_embedding_unit_norm"),
        sa.UniqueConstraint("cluster_id", "identity_id", name="unique_cluster_representative"),
    )

    op.create_table(
        "identity_scan_jobs",
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
            "identities_detected",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column("message", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("created_by_user_id", sa.Integer()),
    )

    op.create_table(
        "identity_scan_job_items",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_scan_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("media_url", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "identities_detected",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("correlation_source", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'skipped', 'cancelled')",
            name="valid_item_status",
        ),
    )

    op.create_table(
        "identity_clustering_jobs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'clustering'"),
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("progress", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_identities", sa.Integer(), nullable=True),
        sa.Column("processed_identities", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("message", sa.Text()),
        sa.Column("snapshot_version", sa.BigInteger(), nullable=True),
        sa.Column("source_job_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("projection_acknowledged_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="valid_status",
        ),
        sa.CheckConstraint(
            "job_type IN ('clustering', 'curation', 'split')",
            name="valid_job_type",
        ),
    )

    # Identity suggestions for borderline cluster matches (0.55-0.68 avg_member similarity)
    # These are surfaced to users for confirmation rather than being silently rejected.
    op.create_table(
        "identity_suggestions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "suggested_cluster_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Similarity scores
        sa.Column("representative_similarity", sa.Float(), nullable=False),
        sa.Column("avg_member_similarity", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        # Priority level: 1=CRITICAL (cold start), 2=HIGH, 3=NORMAL, 4=LOW
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("evidence_generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # Timestamps
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("refreshed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "source_job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_clustering_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(length=50), nullable=True),
        # Resolution status: 'pending', 'accepted', 'rejected', 'expired'
        sa.Column(
            "resolution",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        # Constraints
        sa.CheckConstraint(
            "representative_similarity >= 0 AND representative_similarity <= 1",
            name="representative_similarity_range",
        ),
        sa.CheckConstraint(
            "avg_member_similarity >= 0 AND avg_member_similarity <= 1",
            name="avg_member_similarity_range",
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="confidence_score_range",
        ),
        sa.CheckConstraint(
            "priority >= 1 AND priority <= 4",
            name="valid_priority",
        ),
        sa.CheckConstraint(
            "resolution IN ('pending', 'accepted', 'rejected', 'expired')",
            name="valid_resolution",
        ),
        sa.UniqueConstraint(
            "identity_id",
            "suggested_cluster_id",
            "evidence_generation",
            name="unique_identity_suggestion",
        ),
    )

    op.create_table(
        "cluster_merge_suggestions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cluster_a_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cluster_b_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("refreshed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "source_job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_clustering_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column(
            "resolution",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.CheckConstraint(
            "similarity >= 0 AND similarity <= 1",
            name="cluster_merge_similarity_range",
        ),
        sa.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="cluster_merge_confidence_score_range",
        ),
        sa.CheckConstraint(
            "resolution IN ('pending', 'accepted', 'rejected', 'expired')",
            name="cluster_merge_valid_resolution",
        ),
        sa.CheckConstraint("cluster_a_id < cluster_b_id", name="cluster_merge_canonical_order"),
        sa.UniqueConstraint(
            "cluster_a_id",
            "cluster_b_id",
            name="unique_cluster_merge_suggestion",
        ),
    )

    op.create_table(
        "name_suggestions",
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
            sa.ForeignKey("identity_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suggested_name", sa.String(length=255), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default=sa.text("'none'")),
        sa.Column(
            "source_job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_clustering_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_exported_snapshot_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disposed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="name_suggestion_confidence_score_range",
        ),
        sa.CheckConstraint(
            "source IN ('identity', 'roster', 'similar_cluster', 'none')",
            name="name_suggestion_valid_source",
        ),
        sa.CheckConstraint(
            "resolution IN ('pending', 'accepted', 'rejected', 'expired')",
            name="name_suggestion_valid_resolution",
        ),
    )

    op.create_table(
        "identity_cluster_blocks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "blocked_cluster_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "identity_id",
            "blocked_cluster_id",
            name="unique_identity_cluster_block",
        ),
    )

    op.create_table(
        "identity_constraints",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_a",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_b",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("constraint_type", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.UniqueConstraint("tenant_id", "identity_a", "identity_b", name="unique_identity_constraint"),
        sa.CheckConstraint("identity_a < identity_b", name="canonical_ordering"),
    )
    op.create_index(
        "idx_identity_constraints_lookup",
        "identity_constraints",
        ["tenant_id", "identity_a", "identity_b"],
    )

    # Canonical evaluation + regression harness (Phase 1 "runs + events")
    op.create_table(
        "recognition_runs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'running'")),
        sa.Column("source", sa.String(length=50)),
        sa.Column(
            "scan_job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_scan_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "clustering_job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_clustering_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column("git_sha", sa.String(length=64)),
        sa.Column(
            "settings_snapshot",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "dataset_selector",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_recognition_run_status",
        ),
    )

    op.create_table(
        "recognition_events",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recognition_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_identities.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "cluster_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_clusters.id", ondelete="SET NULL"),
        ),
        sa.Column("source_cluster_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.Column("target_cluster_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "clustering_feedback",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("identity_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cluster_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_type", sa.String(length=20)),
        sa.Column("similarity_at_decision", sa.Float()),
        sa.Column("user_action", sa.String(length=20)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("experiment_id", sa.String(length=64)),
        sa.Column("variant", sa.String(length=64)),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=50), nullable=False, server_default=sa.text("'tenant'")),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("result_status", sa.String(length=20), nullable=False, server_default=sa.text("'success'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index(
        "idx_media_identities_tenant",
        "media_identities",
        ["tenant_id"],
    )
    op.create_index(
        "idx_media_identities_tenant_type",
        "media_identities",
        ["tenant_id", "identity_type"],
    )
    op.create_index(
        "idx_media_identities_phash",
        "media_identities",
        ["tenant_id", "image_phash"],
        postgresql_where=sa.text("image_phash IS NOT NULL"),
    )
    op.create_index(
        "idx_media_identities_embedding",
        "media_identities",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("idx_identity_clusters_tenant", "identity_clusters", ["tenant_id"])
    op.create_index(
        "idx_identity_clusters_tenant_type",
        "identity_clusters",
        ["tenant_id", "identity_type"],
    )
    op.create_index(
        "idx_identity_clusters_roster",
        "identity_clusters",
        ["roster_id"],
        postgresql_where=sa.text("roster_id IS NOT NULL"),
    )
    op.create_index("idx_curation_replay_tenant", "curation_replay_records", ["tenant_id"])
    op.create_index("idx_identity_members_cluster", "identity_members", ["cluster_id"])
    op.create_index("idx_identity_members_identity", "identity_members", ["identity_id"])
    op.create_index("idx_identity_scan_jobs_tenant", "identity_scan_jobs", ["tenant_id"])
    op.create_index(
        "idx_identity_scan_jobs_status",
        "identity_scan_jobs",
        ["status"],
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_index("idx_scan_job_items_job", "identity_scan_job_items", ["job_id"])
    op.create_index(
        "idx_scan_job_items_pending",
        "identity_scan_job_items",
        ["job_id", "status"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "idx_scan_job_items_stale",
        "identity_scan_job_items",
        ["status", "started_at"],
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.create_index("idx_identity_clustering_jobs_tenant", "identity_clustering_jobs", ["tenant_id"])
    op.create_index(
        "idx_identity_clustering_jobs_status",
        "identity_clustering_jobs",
        ["status"],
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_index(
        "idx_media_identities_tenant_id",
        "media_identities",
        ["tenant_id", "id"],
    )
    op.create_index(
        "idx_identity_clusters_tenant_id",
        "identity_clusters",
        ["tenant_id", "id"],
    )
    op.create_index(
        "idx_identity_members_tenant_id",
        "identity_members",
        ["tenant_id", "id"],
    )
    op.create_index(
        "idx_identity_scan_jobs_tenant_id",
        "identity_scan_jobs",
        ["tenant_id", "id"],
    )
    op.create_index(
        "idx_scan_job_items_tenant_id",
        "identity_scan_job_items",
        ["tenant_id", "id"],
    )
    op.create_index(
        "idx_media_identities_tenant_media",
        "media_identities",
        ["tenant_id", "media_id"],
    )
    op.create_index(
        "idx_cluster_reps_tenant",
        "identity_cluster_representatives",
        ["tenant_id"],
    )
    op.create_index(
        "idx_cluster_reps_cluster",
        "identity_cluster_representatives",
        ["cluster_id"],
    )
    op.create_index(
        "idx_cluster_reps_embedding",
        "identity_cluster_representatives",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "idx_cluster_reps_diversity",
        "identity_cluster_representatives",
        ["cluster_id", "diversity_score"],
    )
    op.create_index(
        "idx_cluster_reps_user_selected",
        "identity_cluster_representatives",
        ["cluster_id", "is_user_selected"],
        postgresql_where=sa.text("is_user_selected = true"),
    )
    op.create_index(
        "idx_cluster_reps_provisional",
        "identity_cluster_representatives",
        ["cluster_id", "is_provisional"],
        postgresql_where=sa.text("is_provisional = true"),
    )
    op.create_index(
        "idx_identity_suggestions_tenant",
        "identity_suggestions",
        ["tenant_id"],
    )
    op.create_index(
        "idx_identity_suggestions_identity",
        "identity_suggestions",
        ["identity_id"],
    )
    op.create_index(
        "idx_identity_suggestions_cluster",
        "identity_suggestions",
        ["suggested_cluster_id"],
    )
    # Partial index for pending suggestions ordered by priority then confidence
    op.create_index(
        "idx_identity_suggestions_pending",
        "identity_suggestions",
        ["tenant_id", "priority", "confidence_score"],
        postgresql_where=sa.text("resolution = 'pending'"),
    )
    op.create_index(
        "idx_identity_suggestions_tenant_id",
        "identity_suggestions",
        ["tenant_id", "id"],
    )
    op.create_index(
        "idx_cluster_merge_suggestions_tenant",
        "cluster_merge_suggestions",
        ["tenant_id"],
    )
    op.create_index(
        "idx_cluster_merge_suggestions_cluster_a",
        "cluster_merge_suggestions",
        ["cluster_a_id"],
    )
    op.create_index(
        "idx_cluster_merge_suggestions_cluster_b",
        "cluster_merge_suggestions",
        ["cluster_b_id"],
    )
    op.create_index(
        "idx_cluster_merge_suggestions_pending",
        "cluster_merge_suggestions",
        ["tenant_id", "confidence_score"],
        postgresql_where=sa.text("resolution = 'pending'"),
    )
    op.create_index(
        "idx_name_suggestions_tenant",
        "name_suggestions",
        ["tenant_id"],
    )
    op.create_index(
        "idx_name_suggestions_cluster",
        "name_suggestions",
        ["cluster_id"],
    )
    op.create_index(
        "idx_name_suggestions_pending",
        "name_suggestions",
        ["tenant_id", "confidence_score"],
        postgresql_where=sa.text("resolution = 'pending'"),
    )
    op.create_index(
        "idx_identity_cluster_blocks_identity",
        "identity_cluster_blocks",
        ["tenant_id", "identity_id"],
    )
    op.create_index(
        "idx_identity_cluster_blocks_cluster",
        "identity_cluster_blocks",
        ["tenant_id", "blocked_cluster_id"],
    )

    op.create_index("idx_recognition_runs_tenant", "recognition_runs", ["tenant_id"])
    op.create_index("idx_recognition_runs_status", "recognition_runs", ["status"])
    op.create_index("idx_recognition_runs_scan_job", "recognition_runs", ["scan_job_id"])
    op.create_index("idx_recognition_runs_clustering_job", "recognition_runs", ["clustering_job_id"])
    op.create_index("idx_api_keys_tenant", "api_keys", ["tenant_id"])
    op.create_index("idx_api_keys_hash", "api_keys", ["api_key_hash"])

    op.create_index("idx_recognition_events_tenant", "recognition_events", ["tenant_id"])
    op.create_index("idx_recognition_events_run_time", "recognition_events", ["run_id", "timestamp"])
    op.create_index("idx_recognition_events_type", "recognition_events", ["event_type"])
    op.create_index("idx_recognition_events_identity", "recognition_events", ["identity_id"])
    op.create_index("idx_recognition_events_cluster", "recognition_events", ["cluster_id"])
    op.create_index("idx_clustering_feedback_tenant", "clustering_feedback", ["tenant_id"])
    op.create_index("idx_clustering_feedback_identity", "clustering_feedback", ["identity_id"])
    op.create_index("idx_clustering_feedback_cluster", "clustering_feedback", ["cluster_id"])
    op.create_index("idx_clustering_feedback_action", "clustering_feedback", ["user_action"])
    op.create_index("idx_audit_events_tenant_event", "audit_events", ["tenant_id", "event_type"])
    op.create_index("idx_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])

    op.create_table(
        "export_jobs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("data_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by_actor", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="valid_export_job_status",
        ),
    )
    op.create_index("idx_export_jobs_tenant", "export_jobs", ["tenant_id"])

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            FOR ALL
            USING (tenant_id = {SAFE_TENANT_EXPR} OR {BYPASS_RLS_EXPR})
            WITH CHECK (tenant_id = {SAFE_TENANT_EXPR} OR {BYPASS_RLS_EXPR})
            """
        )

    op.create_table(
        "identity_cluster_refresh_queue",
        sa.Column(
            "cluster_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_cluster_centroid_dirty(target_cluster uuid)
        RETURNS void AS $$
        BEGIN
            IF target_cluster IS NULL THEN
                RETURN;
            END IF;

            INSERT INTO identity_cluster_refresh_queue(cluster_id, updated_at)
            VALUES (target_cluster, now())
            ON CONFLICT (cluster_id)
            DO UPDATE SET updated_at = EXCLUDED.updated_at;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION mark_dirty_on_identity_members()
        RETURNS trigger AS $$
        BEGIN
            IF (TG_OP = 'INSERT') THEN
                PERFORM notify_cluster_centroid_dirty(NEW.cluster_id);
                RETURN NEW;
            ELSIF (TG_OP = 'UPDATE') THEN
                PERFORM notify_cluster_centroid_dirty(NEW.cluster_id);
                IF NEW.cluster_id IS DISTINCT FROM OLD.cluster_id THEN
                    PERFORM notify_cluster_centroid_dirty(OLD.cluster_id);
                END IF;
                RETURN NEW;
            ELSE
                PERFORM notify_cluster_centroid_dirty(OLD.cluster_id);
                RETURN OLD;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_mark_centroid_dirty_on_members
        AFTER INSERT OR UPDATE OR DELETE ON identity_members
        FOR EACH ROW
        EXECUTE FUNCTION mark_dirty_on_identity_members();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION mark_dirty_on_media_identities()
        RETURNS trigger AS $$
        DECLARE
            affected_identity uuid;
        BEGIN
            affected_identity := COALESCE(NEW.id, OLD.id);
            IF affected_identity IS NULL THEN
                IF (TG_OP = 'DELETE') THEN
                    RETURN OLD;
                ELSE
                    RETURN NEW;
                END IF;
            END IF;

            INSERT INTO identity_cluster_refresh_queue(cluster_id, updated_at)
            SELECT DISTINCT im.cluster_id, now()
            FROM identity_members im
            WHERE im.identity_id = affected_identity
            ON CONFLICT (cluster_id)
            DO UPDATE SET updated_at = EXCLUDED.updated_at;

            IF (TG_OP = 'DELETE') THEN
                RETURN OLD;
            ELSE
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_mark_centroid_dirty_on_media
        AFTER UPDATE OR DELETE ON media_identities
        FOR EACH ROW
        EXECUTE FUNCTION mark_dirty_on_media_identities();
        """
    )

    op.execute(
        f"""
        CREATE MATERIALIZED VIEW mv_identity_cluster_centroids AS
        WITH normalized_embeddings AS (
            SELECT
                im.cluster_id,
                mi.tenant_id,
                l2_normalize(mi.embedding)::vector({EMBEDDING_DIMENSION}) AS unit_embedding,
                mi.updated_at
            FROM identity_members im
            JOIN media_identities mi ON mi.id = im.identity_id
        ),
        cluster_embeddings AS (
            SELECT
                c.id AS cluster_id,
                c.tenant_id,
                COUNT(ne.unit_embedding) AS identity_count,
                AVG(ne.unit_embedding)::vector({EMBEDDING_DIMENSION}) AS avg_embedding,
                COALESCE(MAX(ne.updated_at), c.updated_at) AS refreshed_at
            FROM identity_clusters c
            JOIN normalized_embeddings ne ON ne.cluster_id = c.id
            GROUP BY c.id, c.tenant_id, c.updated_at
        )
        SELECT
            cluster_id,
            tenant_id,
            identity_count,
            CASE
                WHEN identity_count > 0 AND avg_embedding IS NOT NULL THEN
                    l2_normalize(avg_embedding)::vector({EMBEDDING_DIMENSION})
                ELSE NULL
            END AS centroid,
            refreshed_at
        FROM cluster_embeddings
        WHERE identity_count >= 1;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX mv_cluster_centroids_cluster_id
        ON mv_identity_cluster_centroids (cluster_id);
        """
    )

    op.execute(
        """
        CREATE INDEX mv_cluster_centroids_tenant_idx
        ON mv_identity_cluster_centroids (tenant_id);
        """
    )

    op.execute(
        f"""
        CREATE INDEX mv_cluster_centroids_vector_idx
        ON mv_identity_cluster_centroids
        USING ivfflat ((centroid::vector({EMBEDDING_DIMENSION})) vector_cosine_ops)
        WHERE centroid IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS mv_cluster_centroids_vector_idx")
    op.execute("DROP INDEX IF EXISTS mv_cluster_centroids_tenant_idx")
    op.execute("DROP INDEX IF EXISTS mv_cluster_centroids_cluster_id")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_identity_cluster_centroids")
    op.execute("DROP TRIGGER IF EXISTS trg_mark_centroid_dirty_on_media ON media_identities")
    op.execute("DROP FUNCTION IF EXISTS mark_dirty_on_media_identities")
    op.execute("DROP TRIGGER IF EXISTS trg_mark_centroid_dirty_on_members ON identity_members")
    op.execute("DROP FUNCTION IF EXISTS mark_dirty_on_identity_members")
    op.execute("DROP FUNCTION IF EXISTS notify_cluster_centroid_dirty")

    op.drop_table("identity_cluster_refresh_queue")
    op.drop_index("idx_scan_job_items_tenant_id", table_name="identity_scan_job_items")
    op.drop_index("idx_scan_job_items_stale", table_name="identity_scan_job_items")
    op.drop_index("idx_scan_job_items_pending", table_name="identity_scan_job_items")
    op.drop_index("idx_scan_job_items_job", table_name="identity_scan_job_items")
    op.drop_index("idx_identity_scan_jobs_status", table_name="identity_scan_jobs")
    op.drop_index("idx_identity_scan_jobs_tenant", table_name="identity_scan_jobs")
    op.drop_index("idx_identity_members_identity", table_name="identity_members")
    op.drop_index("idx_identity_members_cluster", table_name="identity_members")
    op.drop_index("idx_identity_clusters_roster", table_name="identity_clusters")
    op.drop_index("idx_curation_replay_tenant", table_name="curation_replay_records")
    op.drop_index("idx_identity_clusters_tenant_type", table_name="identity_clusters")
    op.drop_index("idx_identity_clusters_tenant", table_name="identity_clusters")
    op.drop_index("idx_media_identities_embedding", table_name="media_identities")
    op.drop_index("idx_media_identities_tenant_type", table_name="media_identities")
    op.drop_index("idx_media_identities_tenant", table_name="media_identities")
    op.drop_index("idx_media_identities_tenant_media", table_name="media_identities")
    op.drop_index("idx_media_identities_tenant_id", table_name="media_identities")
    op.drop_index("idx_identity_clustering_jobs_status", table_name="identity_clustering_jobs")
    op.drop_index("idx_identity_scan_jobs_tenant_id", table_name="identity_scan_jobs")
    op.drop_index("idx_identity_clustering_jobs_tenant", table_name="identity_clustering_jobs")
    op.drop_index("idx_identity_members_tenant_id", table_name="identity_members")
    op.drop_index("idx_identity_clusters_tenant_id", table_name="identity_clusters")
    op.drop_index("idx_cluster_reps_embedding", table_name="identity_cluster_representatives")
    op.drop_index("idx_cluster_reps_diversity", table_name="identity_cluster_representatives")
    op.drop_index("idx_cluster_reps_cluster", table_name="identity_cluster_representatives")
    op.drop_index("idx_cluster_reps_tenant", table_name="identity_cluster_representatives")
    op.drop_index("idx_identity_suggestions_tenant_id", table_name="identity_suggestions")
    op.drop_index("idx_identity_suggestions_pending", table_name="identity_suggestions")
    op.drop_index("idx_identity_suggestions_cluster", table_name="identity_suggestions")
    op.drop_index("idx_identity_suggestions_identity", table_name="identity_suggestions")
    op.drop_index("idx_identity_suggestions_tenant", table_name="identity_suggestions")
    op.drop_index("idx_cluster_merge_suggestions_pending", table_name="cluster_merge_suggestions")
    op.drop_index("idx_cluster_merge_suggestions_cluster_b", table_name="cluster_merge_suggestions")
    op.drop_index("idx_cluster_merge_suggestions_cluster_a", table_name="cluster_merge_suggestions")
    op.drop_index("idx_cluster_merge_suggestions_tenant", table_name="cluster_merge_suggestions")
    op.drop_index("idx_name_suggestions_pending", table_name="name_suggestions")
    op.drop_index("idx_name_suggestions_cluster", table_name="name_suggestions")
    op.drop_index("idx_name_suggestions_tenant", table_name="name_suggestions")
    op.drop_index("idx_identity_cluster_blocks_cluster", table_name="identity_cluster_blocks")
    op.drop_index("idx_identity_cluster_blocks_identity", table_name="identity_cluster_blocks")
    op.drop_index("idx_recognition_events_cluster", table_name="recognition_events")
    op.drop_index("idx_recognition_events_identity", table_name="recognition_events")
    op.drop_index("idx_recognition_events_type", table_name="recognition_events")
    op.drop_index("idx_recognition_events_run_time", table_name="recognition_events")
    op.drop_index("idx_recognition_events_tenant", table_name="recognition_events")
    op.drop_index("idx_clustering_feedback_action", table_name="clustering_feedback")
    op.drop_index("idx_clustering_feedback_cluster", table_name="clustering_feedback")
    op.drop_index("idx_clustering_feedback_identity", table_name="clustering_feedback")
    op.drop_index("idx_clustering_feedback_tenant", table_name="clustering_feedback")
    op.drop_index("idx_audit_events_tenant_created", table_name="audit_events")
    op.drop_index("idx_audit_events_tenant_event", table_name="audit_events")
    op.drop_index("idx_export_jobs_tenant", table_name="export_jobs")
    op.drop_index("idx_recognition_runs_scan_job", table_name="recognition_runs")
    op.drop_index("idx_recognition_runs_status", table_name="recognition_runs")
    op.drop_index("idx_recognition_runs_tenant", table_name="recognition_runs")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("audit_events")
    op.drop_table("clustering_feedback")
    op.drop_table("export_jobs")
    op.drop_table("recognition_events")
    op.drop_table("recognition_runs")
    op.drop_table("identity_cluster_blocks")
    op.drop_table("name_suggestions")
    op.drop_table("cluster_merge_suggestions")
    op.drop_table("identity_suggestions")
    op.drop_table("identity_scan_job_items")
    op.drop_table("identity_scan_jobs")
    op.drop_table("identity_cluster_representatives")
    op.drop_table("identity_clustering_jobs")
    op.drop_table("identity_members")
    op.drop_table("curation_replay_records")
    op.drop_table("identity_clusters")
    op.drop_table("media_identities")
