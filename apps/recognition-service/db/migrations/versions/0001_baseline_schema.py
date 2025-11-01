"""Baseline schema for recognition service persistence."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    is_postgres = dialect_name == "postgresql"

    uuid_type = sa.String(length=36)
    timestamp_default = sa.text("CURRENT_TIMESTAMP")

    if is_postgres:
        from sqlalchemy.dialects import postgresql

        uuid_type = postgresql.UUID(as_uuid=True)
        timestamp_default = sa.text("NOW()")
        op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
        op.execute('CREATE EXTENSION IF NOT EXISTS "citext";')
        op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
        op.execute('CREATE EXTENSION IF NOT EXISTS vector;')

    op.create_table(
        "tenants",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("plan_tier", sa.String(length=32), nullable=False, server_default="free"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=timestamp_default),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=timestamp_default),
    )

    op.create_index("idx_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "roster_entries",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=191), nullable=False),
        sa.Column("display_name", sa.String(length=255)),
        sa.Column("model", sa.String(length=128), nullable=False, server_default="insightface_w600k"),
        sa.Column("type", sa.String(length=32), nullable=False, server_default="person"),
        sa.Column("metadata", sa.Text, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("aggregate_embedding", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=timestamp_default),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=timestamp_default),
    )

    op.create_index("idx_roster_tenant", "roster_entries", ["tenant_id"])
    op.create_index("idx_roster_label", "roster_entries", ["tenant_id", "label"])
    op.create_index("idx_roster_tenant_model", "roster_entries", ["tenant_id", "model"])
    op.create_index("idx_roster_updated", "roster_entries", ["updated_at"])

    op.create_table(
        "reference_embeddings",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("roster_entry_id", uuid_type, sa.ForeignKey("roster_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("embedding", sa.Text, nullable=False),
        sa.Column("image_path", sa.String(length=512)),
        sa.Column("metadata", sa.Text, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=timestamp_default),
    )

    op.create_index("idx_ref_emb_roster", "reference_embeddings", ["roster_entry_id"])

    op.create_table(
        "augmented_embeddings",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("roster_entry_id", uuid_type, sa.ForeignKey("roster_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observation_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("embedding", sa.Text, nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="wordpress_confirm"),
        sa.Column("attachment_id", sa.BigInteger),
        sa.Column("bbox", sa.Text),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("quality_tier", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=timestamp_default),
    )

    op.create_index("idx_aug_emb_roster", "augmented_embeddings", ["roster_entry_id"])
    op.create_index("idx_aug_emb_observation", "augmented_embeddings", ["observation_id"], unique=True)
    op.create_index("idx_aug_emb_quality", "augmented_embeddings", ["quality_tier"])

    if is_postgres:
        op.execute("ALTER TABLE roster_entries ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE reference_embeddings ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE augmented_embeddings ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    op.drop_index("idx_aug_emb_quality", table_name="augmented_embeddings")
    op.drop_index("idx_aug_emb_observation", table_name="augmented_embeddings")
    op.drop_index("idx_aug_emb_roster", table_name="augmented_embeddings")
    op.drop_table("augmented_embeddings")

    op.drop_index("idx_ref_emb_roster", table_name="reference_embeddings")
    op.drop_table("reference_embeddings")

    op.drop_index("idx_roster_updated", table_name="roster_entries")
    op.drop_index("idx_roster_tenant_model", table_name="roster_entries")
    op.drop_index("idx_roster_label", table_name="roster_entries")
    op.drop_index("idx_roster_tenant", table_name="roster_entries")
    op.drop_table("roster_entries")

    op.drop_index("idx_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
