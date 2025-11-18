"""Identity schema baseline replacing the old face tables with identity tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "001_identity_schema"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIMENSION = 1024
SAFE_TENANT_EXPR = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"

TENANT_TABLES = [
    "media_identities",
    "identity_clusters",
    "identity_members",
    "identity_scan_jobs",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("DROP TABLE IF EXISTS identity_scan_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS identity_members CASCADE")
    op.execute("DROP TABLE IF EXISTS identity_clusters CASCADE")
    op.execute("DROP TABLE IF EXISTS media_identities CASCADE")
    op.execute("DROP TABLE IF EXISTS tenants CASCADE")

    op.create_table(
        "tenants",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("site_url", sa.String(length=255), nullable=False, unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
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
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("media_url", sa.Text(), nullable=False),
        sa.Column("bbox_x", sa.Integer(), nullable=False),
        sa.Column("bbox_y", sa.Integer(), nullable=False),
        sa.Column("bbox_width", sa.Integer(), nullable=False),
        sa.Column("bbox_height", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.UniqueConstraint("tenant_id", "media_id", "bbox_x", "bbox_y", name="unique_media_identity"),
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
        sa.Column("label", sa.String(length=255)),
        sa.Column(
            "representative_identity_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_identities.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "identity_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("roster_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.Column("similarity_threshold", sa.Float()),
        sa.Column(
            "clustering_algorithm",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'cosine_similarity'"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.UniqueConstraint("tenant_id", "label", name="unique_tenant_identity_label"),
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

    op.create_index(
        "idx_media_identities_tenant",
        "media_identities",
        ["tenant_id"],
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
        "idx_identity_clusters_roster",
        "identity_clusters",
        ["roster_id"],
        postgresql_where=sa.text("roster_id IS NOT NULL"),
    )
    op.create_index("idx_identity_members_cluster", "identity_members", ["cluster_id"])
    op.create_index("idx_identity_members_identity", "identity_members", ["identity_id"])
    op.create_index("idx_identity_scan_jobs_tenant", "identity_scan_jobs", ["tenant_id"])
    op.create_index(
        "idx_identity_scan_jobs_status",
        "identity_scan_jobs",
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
        "idx_media_identities_tenant_media",
        "media_identities",
        ["tenant_id", "media_id"],
    )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            FOR ALL
            USING (tenant_id = {SAFE_TENANT_EXPR})
            WITH CHECK (tenant_id = {SAFE_TENANT_EXPR})
            """
        )


def downgrade() -> None:
    op.drop_index("idx_identity_scan_jobs_status", table_name="identity_scan_jobs")
    op.drop_index("idx_identity_scan_jobs_tenant", table_name="identity_scan_jobs")
    op.drop_index("idx_identity_members_identity", table_name="identity_members")
    op.drop_index("idx_identity_members_cluster", table_name="identity_members")
    op.drop_index("idx_identity_clusters_roster", table_name="identity_clusters")
    op.drop_index("idx_identity_clusters_tenant", table_name="identity_clusters")
    op.drop_index("idx_media_identities_embedding", table_name="media_identities")
    op.drop_index("idx_media_identities_tenant", table_name="media_identities")
    op.drop_index("idx_media_identities_tenant_media", table_name="media_identities")
    op.drop_index("idx_media_identities_tenant_id", table_name="media_identities")
    op.drop_index("idx_identity_scan_jobs_tenant_id", table_name="identity_scan_jobs")
    op.drop_index("idx_identity_members_tenant_id", table_name="identity_members")
    op.drop_index("idx_identity_clusters_tenant_id", table_name="identity_clusters")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("identity_scan_jobs")
    op.drop_table("identity_members")
    op.drop_table("identity_clusters")
    op.drop_table("media_identities")
