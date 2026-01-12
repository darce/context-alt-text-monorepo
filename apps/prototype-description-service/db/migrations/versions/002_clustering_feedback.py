"""Add clustering feedback tracking table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002_clustering_feedback"
down_revision = "001_identity_schema"
branch_labels = None
depends_on = None

SAFE_TENANT_EXPR = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"
BYPASS_RLS_EXPR = "COALESCE(NULLIF(current_setting('app.bypass_rls', true), ''), 'false')::boolean"


def upgrade() -> None:
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

    op.create_index("idx_clustering_feedback_tenant", "clustering_feedback", ["tenant_id"])
    op.create_index("idx_clustering_feedback_identity", "clustering_feedback", ["identity_id"])
    op.create_index("idx_clustering_feedback_cluster", "clustering_feedback", ["cluster_id"])
    op.create_index("idx_clustering_feedback_action", "clustering_feedback", ["user_action"])

    op.execute("ALTER TABLE clustering_feedback ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clustering_feedback FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation_clustering_feedback ON clustering_feedback
        FOR ALL
        USING (tenant_id = {SAFE_TENANT_EXPR} OR {BYPASS_RLS_EXPR})
        WITH CHECK (tenant_id = {SAFE_TENANT_EXPR} OR {BYPASS_RLS_EXPR})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_clustering_feedback ON clustering_feedback")
    op.execute("ALTER TABLE clustering_feedback NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clustering_feedback DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_clustering_feedback_action", table_name="clustering_feedback")
    op.drop_index("idx_clustering_feedback_cluster", table_name="clustering_feedback")
    op.drop_index("idx_clustering_feedback_identity", table_name="clustering_feedback")
    op.drop_index("idx_clustering_feedback_tenant", table_name="clustering_feedback")
    op.drop_table("clustering_feedback")
