"""Identity schema baseline replacing the old face tables with identity tables."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from db.settings import get_database_settings

revision = "001_identity_schema"
down_revision = None
branch_labels = None
depends_on = None

# Sole root: PGVECTOR_DIM → DatabaseSettings.pgvector_dimension (no bare 512).
EMBEDDING_DIMENSION = int(get_database_settings().pgvector_dimension)
SAFE_TENANT_EXPR = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"
BYPASS_RLS_EXPR = "COALESCE(NULLIF(current_setting('app.bypass_rls', true), ''), 'false')::boolean"

# Must stay equal to recognition.application.health.IDENTITY_VECTOR_COLUMNS.
# /ready fails closed on every member; heal/verify must probe the same set.
IDENTITY_VECTOR_COLUMNS: tuple[tuple[str, str], ...] = (
    ("media_identities", "embedding"),
    ("identity_cluster_representatives", "embedding"),
    ("mv_identity_cluster_centroids", "centroid"),
)

TENANT_TABLES = [
    "media_identities",
    "identity_clusters",
    "identity_members",
    "identity_name_suppressions",
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
    "image_descriptions",
    "image_description_runs",
    "image_description_run_items",
    "clustering_job_reports",
    "assignment_decisions",
    "identity_atlas_runs",
    "identity_atlas_points",
    "identity_atlas_queue_dispositions",
]

# Tables this migration creates via raw SQL only — no ORM model exists for
# them, so any ORM-metadata-based mechanism (create_all heals, model-driven
# tooling) can never produce them. Consumed by the truth-consistency ratchet.
RAW_SQL_TABLES = [
    "identity_cluster_refresh_queue",
]

EXPECTED_SCHEMA_TABLES = [
    "tenants",
    "api_keys",
    "demo_instances",
    "worker_capabilities",
    "media_identities",
    "curation_replay_records",
    "identity_clusters",
    "identity_members",
    "identity_name_suppressions",
    "identity_cluster_representatives",
    "identity_scan_jobs",
    "identity_scan_job_items",
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
    "export_jobs",
    "identity_cluster_refresh_queue",
    "image_descriptions",
    "image_description_runs",
    "image_description_run_items",
    "clustering_job_reports",
    "assignment_decisions",
    "identity_atlas_runs",
    "identity_atlas_points",
    "identity_atlas_queue_dispositions",
]

DOWNGRADE_TABLE_ORDER = [
    "identity_atlas_queue_dispositions",
    "identity_atlas_points",
    "identity_atlas_runs",
    "assignment_decisions",
    "clustering_job_reports",
    "worker_capabilities",
    "image_description_run_items",
    "image_description_runs",
    "image_descriptions",
    "audit_events",
    "clustering_feedback",
    "export_jobs",
    "recognition_events",
    "identity_cluster_blocks",
    "name_suggestions",
    "cluster_merge_suggestions",
    "identity_suggestions",
    "identity_scan_job_items",
    "recognition_runs",
    "identity_cluster_representatives",
    "identity_name_suppressions",
    "identity_members",
    "curation_replay_records",
    "identity_scan_jobs",
    "identity_clustering_jobs",
    "identity_constraints",
    "identity_clusters",
    "media_identities",
    "demo_instances",
    "api_keys",
    "tenants",
]


# --------------------------------------------------------------------------
# E15-34: idempotent DDL helpers. `upgrade()` and the boot heal compose the
# same `ensure_*` units, so schema truth lives here alone. Every helper is
# safe to re-run against a partially-provisioned database.
# --------------------------------------------------------------------------


def _relkind(op, name: str) -> str | None:
    raw = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT c.relkind FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = :name"
            ),
            {"name": name},
        )
        .scalar()
    )
    if raw is None:
        return None
    # pg_class.relkind is a single-char code ('r', 'i', 'm', ...); coerce Any→str.
    return str(raw)


def _existing_columns(op, table_name: str) -> set[str]:
    return {
        row[0]
        for row in op.get_bind().execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t"
            ),
            {"t": table_name},
        )
    }


def _ensure_columns(op, table_name: str, *columns) -> None:
    """Additively add any declared column missing from an already-existing table.

    ``_ensure_table`` no-ops when the table exists, so an expand-first column
    added to the model after the table was first created never lands — every
    ORM path selecting it then 500s while the table and alembic revision still
    look healthy (MAINT-TPR-01 / PA-03: prod ``tenants.naming_agreement_enabled``).
    Additive-only: a missing primary key, or a missing NOT NULL column with no
    server default, is non-additive drift and raises for operator remediation
    rather than guessing a backfill value.
    """
    existing = _existing_columns(op, table_name)
    for column in columns:
        # `_ensure_table` is also passed table-level constructs (CheckConstraint,
        # ForeignKeyConstraint, Index); only real columns are additively healable.
        if not isinstance(column, sa.Column):
            continue
        if column.name in existing:
            continue
        if column.primary_key:
            raise RuntimeError(
                f"{table_name}.{column.name} (primary key) is missing from an "
                "existing table; non-additive drift, operator remediation required"
            )
        if not column.nullable and column.server_default is None:
            raise RuntimeError(
                f"{table_name}.{column.name} is NOT NULL without a server default; "
                "cannot add it additively to an existing table (operator remediation)"
            )
        op.add_column(table_name, column)


def _existing_constraint_names(op, table_name: str) -> set[str]:
    """Named table-level constraints currently present on ``table_name``."""
    return {
        str(row[0])
        for row in op.get_bind().execute(
            sa.text(
                "SELECT c.conname FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "JOIN pg_namespace n ON t.relnamespace = n.oid "
                "WHERE n.nspname = current_schema() AND t.relname = :t"
            ),
            {"t": table_name},
        )
    }


def _constraint_column_names(constraint) -> list[str]:
    """Column names of a UniqueConstraint, attached or still detached.

    A constraint built as ``sa.UniqueConstraint("a", "b", name=...)`` and passed
    straight to ``_ensure_table`` was never bound to a Table, so ``.columns`` is
    empty and the names live in ``_pending_colargs``. Read both so the DDL is
    generated from the declaration either way.
    """
    names = [str(column.name) for column in constraint.columns]
    if names:
        return names
    return [str(arg) for arg in getattr(constraint, "_pending_colargs", []) or []]


def _ensure_unique_constraint(op, table_name: str, constraint) -> bool:
    """Additively add one missing UNIQUE constraint to an already-existing table.

    GUIDEDFIX-2 [S02]: a UniqueConstraint newly declared on a table that already
    exists in a provisioned database can never land through ``create_table``,
    and ``_ensure_table_constraints`` would raise on every subsequent migrate.
    UNIQUE is the one table-level constraint that is genuinely additive: Postgres
    builds the backing index and fails loudly (23505) if live rows already
    violate it, so there is no value to guess and no silent half-heal.

    Returns True when the constraint is present after the call (or the dialect
    makes it a non-issue), False when the caller must report it as drift.
    """
    columns = _constraint_column_names(constraint)
    if not columns:
        return False
    bind = op.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "")
    if dialect and dialect != "postgresql":
        # SQLite has no ``ALTER TABLE ... ADD CONSTRAINT``. It also only ever
        # gets these tables from create_table / Base.metadata.create_all, which
        # emit the UNIQUE inline — so on SQLite the constraint is present by
        # construction and there is nothing to heal.
        return True
    quoted_table = f'"{table_name}"'
    quoted_name = f'"{constraint.name}"'
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    try:
        op.execute(f"ALTER TABLE {quoted_table} ADD CONSTRAINT {quoted_name} UNIQUE ({quoted_columns})")
    except sa.exc.DBAPIError as exc:
        if not _is_unique_violation(exc):
            raise
        raise RuntimeError(
            f"cannot add unique constraint {constraint.name} on {table_name} "
            f"({', '.join(columns)}): live rows violate uniqueness (SQLSTATE 23505). "
            "Operator action: delete or merge the duplicate rows, then re-run "
            "python -m scripts.sync_identity_schema."
        ) from exc
    return True


def _is_unique_violation(exc: BaseException) -> bool:
    """True when *exc* (or its ``orig``) is PostgreSQL SQLSTATE 23505."""
    candidates: list[BaseException] = [exc]
    orig = getattr(exc, "orig", None)
    if isinstance(orig, BaseException):
        candidates.append(orig)
    for candidate in candidates:
        sqlstate = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        if sqlstate is not None and str(sqlstate) == "23505":
            return True
        if type(candidate).__name__ in {"UniqueViolation", "UniqueViolationError"}:
            return True
    return False


def _ensure_table_constraints(op, table_name: str, *elements, heal_constraints: Sequence[str] = ()) -> None:
    """Fail loudly when an existing table is missing declared table-level constraints.

    ``_ensure_table`` cannot add UniqueConstraint / ForeignKeyConstraint /
    CheckConstraint to an already-created table via create_table, and indexes
    alone would leave a silent partial heal (new indexes land, composite FK
    and unique targets do not). Greenfield: refuse the mismatch so operators
    recreate or apply the constraints rather than running with a half-healed
    schema (FL30-B-01).

    ``heal_constraints`` opts named UNIQUE constraints out of that refusal: they
    are added additively via ``_ensure_unique_constraint`` instead. Opt-in by
    name so adding a constraint to an already-provisioned table is a deliberate
    declaration at the call site, not a blanket relaxation of the guard.
    """
    healable = {str(name) for name in heal_constraints}
    declared: dict[str, object] = {}
    for element in elements:
        if isinstance(element, (sa.UniqueConstraint, sa.ForeignKeyConstraint, sa.CheckConstraint)):
            name = getattr(element, "name", None)
            if name:
                declared[str(name)] = element
    if not declared:
        return
    unknown = sorted(healable - set(declared))
    if unknown:
        raise RuntimeError(f"{table_name}: heal_constraints names {unknown} that the table does not declare")
    existing = _existing_constraint_names(op, table_name)
    missing = sorted(name for name in declared if name not in existing)
    unhealed: list[str] = []
    for name in missing:
        element = declared[name]
        if (
            name in healable
            and isinstance(element, sa.UniqueConstraint)
            and _ensure_unique_constraint(op, table_name, element)
        ):
            continue
        unhealed.append(name)
    if unhealed:
        raise RuntimeError(
            f"{table_name} exists but is missing table-level constraints {unhealed}; "
            "silent partial healing is forbidden — drop and recreate the table or "
            "apply the constraints manually (operator action)"
        )


def _ensure_table(op, table_name: str, *columns, **kw) -> None:
    heal_constraints: Sequence[str] = kw.pop("heal_constraints", ())
    relkind = _relkind(op, table_name)
    if relkind is None:
        op.create_table(table_name, *columns, **kw)
    elif relkind not in ("r", "p"):
        # Loud impostor guard (mirrors ensure_matview): silently accepting a
        # view/matview/index under a table name yields an unrepairable state.
        raise RuntimeError(
            f"{table_name!r} exists with relkind {relkind!r} (expected a table); "
            "drop the impostor relation before healing (operator action)"
        )
    else:
        # Table exists: reconcile additive column drift so an expand-first
        # column added after first creation still lands (MAINT-TPR-01 / PA-03).
        _ensure_columns(op, table_name, *columns)
        # Table-level constraints are not additive via create_table; detect
        # and refuse silent partial heals (FL30-B-01 / FIR-9 composite FK),
        # except for UNIQUE constraints explicitly declared heal-additive.
        _ensure_table_constraints(op, table_name, *columns, heal_constraints=heal_constraints)


def _ensure_index(op, index_name: str, table_name: str, columns, **kw) -> None:
    relkind = _relkind(op, index_name)
    if relkind is None:
        op.create_index(index_name, table_name, columns, **kw)
    elif relkind not in ("i", "I"):
        raise RuntimeError(
            f"{index_name!r} exists with relkind {relkind!r} (expected an index); "
            "drop the impostor relation before healing (operator action)"
        )


def ensure_tables(op) -> None:
    """Create every migration-owned regular table (and its indexes) if missing."""
    _ensure_table(
        op,
        "tenants",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("site_url", sa.String(length=255), nullable=False, unique=True),
        # AP-7 / ADR-012 subset: customer contact + plan (nullable expand-first).
        sa.Column("primary_contact_email", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("plan", sa.String(length=50), nullable=True),
        sa.Column("next_person_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("naming_agreement_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
    _ensure_index(
        op,
        "uq_tenants_primary_contact_email",
        "tenants",
        ["primary_contact_email"],
        unique=True,
    )

    _ensure_table(
        op,
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
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # DS-3 / launch-plan §5: per-prospect demo registry. Looked up by opaque
    # slug (not tenant_id); raw API key is never stored — only a hash/ref.
    _ensure_table(
        op,
        "demo_instances",
        sa.Column("slug", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("api_key_ref", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("seed_bundle", sa.Text(), nullable=False, server_default=sa.text("'default'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("recognition_quota", sa.Integer(), nullable=False, server_default=sa.text("200")),
        sa.Column("recognition_used", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("branding_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _ensure_index(op, "idx_demo_instances_tenant", "demo_instances", ["tenant_id"])
    _ensure_index(op, "idx_demo_instances_expires", "demo_instances", ["expires_at"])
    _ensure_index(op, "idx_demo_instances_api_key_ref", "demo_instances", ["api_key_ref"])

    _ensure_table(
        op,
        "worker_capabilities",
        sa.Column("worker_kind", sa.String(length=64), primary_key=True),
        sa.Column("capability", sa.String(length=64), primary_key=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    _ensure_table(
        op,
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
        # Embedding provenance: required, no default (missing must fail closed — RLSE-05).
        sa.Column("embedding_model", sa.Text(), nullable=False),
        # InsightFace metadata (pose for quality/clustering; age/gender removed FIR-2 S4)
        sa.Column("pose_pitch", sa.Float(), nullable=True),
        sa.Column("pose_yaw", sa.Float(), nullable=True),
        sa.Column("pose_roll", sa.Float(), nullable=True),
        # FIR-6 S1 quality factors (face_pipeline scan only; NULL under insightface)
        sa.Column("sharpness", sa.Float(), nullable=True),
        sa.Column("embedding_norm", sa.Float(), nullable=True),
        sa.Column("occlusion_severity", sa.Float(), nullable=True),
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
    _ensure_table(
        op,
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
        sa.Column("backend_version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("conflict_code", sa.String(length=64), nullable=True),
        sa.Column("machine_payload_json", sa.Text(), nullable=True),
        sa.Column("refresh_status", sa.String(length=20), nullable=False, server_default=sa.text("'not_applicable'")),
        sa.Column("refresh_requested_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("refresh_completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "refresh_status IN ('not_applicable', 'queued', 'running', 'no_candidates', 'timed_out', 'completed', 'failed')",
            name="ck_curation_replay_refresh_status",
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_curation_replay_tenant_idempotency"),
    )

    _ensure_table(
        op,
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

    _ensure_table(
        op,
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

    _ensure_table(
        op,
        "identity_name_suppressions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("roster_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "roster_id", name="unique_name_suppression"),
    )

    _ensure_table(
        op,
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

    _ensure_table(
        op,
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

    _ensure_table(
        op,
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

    _ensure_table(
        op,
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
    _ensure_table(
        op,
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

    _ensure_table(
        op,
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
        sa.Column(
            "survivor_cluster_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_clusters.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.CheckConstraint(
            "survivor_cluster_id IS NULL OR survivor_cluster_id = cluster_a_id OR survivor_cluster_id = cluster_b_id",
            name="cluster_merge_survivor_in_pair",
        ),
        sa.UniqueConstraint(
            "cluster_a_id",
            "cluster_b_id",
            name="unique_cluster_merge_suggestion",
        ),
    )

    _ensure_table(
        op,
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

    _ensure_table(
        op,
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

    _ensure_table(
        op,
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
    _ensure_index(
        op,
        "idx_identity_constraints_lookup",
        "identity_constraints",
        ["tenant_id", "identity_a", "identity_b"],
    )

    # Canonical evaluation + regression harness (Phase 1 "runs + events")
    _ensure_table(
        op,
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

    _ensure_table(
        op,
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

    _ensure_table(
        op,
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

    _ensure_table(
        op,
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

    _ensure_index(
        op,
        "idx_media_identities_tenant",
        "media_identities",
        ["tenant_id"],
    )
    _ensure_index(
        op,
        "idx_media_identities_tenant_type",
        "media_identities",
        ["tenant_id", "identity_type"],
    )
    _ensure_index(
        op,
        "idx_media_identities_phash",
        "media_identities",
        ["tenant_id", "image_phash"],
        postgresql_where=sa.text("image_phash IS NOT NULL"),
    )
    _ensure_index(
        op,
        "idx_media_identities_embedding_model",
        "media_identities",
        ["embedding_model"],
        postgresql_where=sa.text("embedding_model IS NOT NULL"),
    )
    _ensure_index(
        op,
        "idx_media_identities_embedding",
        "media_identities",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    _ensure_index(op, "idx_identity_clusters_tenant", "identity_clusters", ["tenant_id"])
    _ensure_index(
        op,
        "idx_identity_clusters_tenant_type",
        "identity_clusters",
        ["tenant_id", "identity_type"],
    )
    _ensure_index(
        op,
        "idx_identity_clusters_roster",
        "identity_clusters",
        ["roster_id"],
        postgresql_where=sa.text("roster_id IS NOT NULL"),
    )
    _ensure_index(op, "idx_curation_replay_tenant", "curation_replay_records", ["tenant_id"])
    _ensure_index(op, "idx_identity_members_cluster", "identity_members", ["cluster_id"])
    _ensure_index(op, "idx_identity_members_identity", "identity_members", ["identity_id"])
    _ensure_index(op, "idx_identity_name_suppressions_tenant", "identity_name_suppressions", ["tenant_id"])
    _ensure_index(op, "idx_identity_scan_jobs_tenant", "identity_scan_jobs", ["tenant_id"])
    _ensure_index(
        op,
        "idx_identity_scan_jobs_status",
        "identity_scan_jobs",
        ["status"],
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    _ensure_index(op, "idx_scan_job_items_job", "identity_scan_job_items", ["job_id"])
    _ensure_index(
        op,
        "idx_scan_job_items_pending",
        "identity_scan_job_items",
        ["job_id", "status"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    _ensure_index(
        op,
        "idx_scan_job_items_stale",
        "identity_scan_job_items",
        ["status", "started_at"],
        postgresql_where=sa.text("status = 'processing'"),
    )
    _ensure_index(op, "idx_identity_clustering_jobs_tenant", "identity_clustering_jobs", ["tenant_id"])
    _ensure_index(
        op,
        "idx_identity_clustering_jobs_status",
        "identity_clustering_jobs",
        ["status"],
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    _ensure_index(
        op,
        "idx_media_identities_tenant_id",
        "media_identities",
        ["tenant_id", "id"],
    )
    _ensure_index(
        op,
        "idx_identity_clusters_tenant_id",
        "identity_clusters",
        ["tenant_id", "id"],
    )
    _ensure_index(
        op,
        "idx_identity_members_tenant_id",
        "identity_members",
        ["tenant_id", "id"],
    )
    _ensure_index(
        op,
        "idx_identity_scan_jobs_tenant_id",
        "identity_scan_jobs",
        ["tenant_id", "id"],
    )
    _ensure_index(
        op,
        "idx_scan_job_items_tenant_id",
        "identity_scan_job_items",
        ["tenant_id", "id"],
    )
    _ensure_index(
        op,
        "idx_media_identities_tenant_media",
        "media_identities",
        ["tenant_id", "media_id"],
    )
    _ensure_index(
        op,
        "idx_cluster_reps_tenant",
        "identity_cluster_representatives",
        ["tenant_id"],
    )
    _ensure_index(
        op,
        "idx_cluster_reps_cluster",
        "identity_cluster_representatives",
        ["cluster_id"],
    )
    _ensure_index(
        op,
        "idx_cluster_reps_embedding",
        "identity_cluster_representatives",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    _ensure_index(
        op,
        "idx_cluster_reps_diversity",
        "identity_cluster_representatives",
        ["cluster_id", "diversity_score"],
    )
    _ensure_index(
        op,
        "idx_cluster_reps_user_selected",
        "identity_cluster_representatives",
        ["cluster_id", "is_user_selected"],
        postgresql_where=sa.text("is_user_selected = true"),
    )
    _ensure_index(
        op,
        "idx_cluster_reps_provisional",
        "identity_cluster_representatives",
        ["cluster_id", "is_provisional"],
        postgresql_where=sa.text("is_provisional = true"),
    )
    _ensure_index(
        op,
        "idx_identity_suggestions_tenant",
        "identity_suggestions",
        ["tenant_id"],
    )
    _ensure_index(
        op,
        "idx_identity_suggestions_identity",
        "identity_suggestions",
        ["identity_id"],
    )
    _ensure_index(
        op,
        "idx_identity_suggestions_cluster",
        "identity_suggestions",
        ["suggested_cluster_id"],
    )
    # Partial index for pending suggestions ordered by priority then confidence
    _ensure_index(
        op,
        "idx_identity_suggestions_pending",
        "identity_suggestions",
        ["tenant_id", "priority", "confidence_score"],
        postgresql_where=sa.text("resolution = 'pending'"),
    )
    _ensure_index(
        op,
        "idx_identity_suggestions_tenant_id",
        "identity_suggestions",
        ["tenant_id", "id"],
    )
    _ensure_index(
        op,
        "idx_cluster_merge_suggestions_tenant",
        "cluster_merge_suggestions",
        ["tenant_id"],
    )
    _ensure_index(
        op,
        "idx_cluster_merge_suggestions_cluster_a",
        "cluster_merge_suggestions",
        ["cluster_a_id"],
    )
    _ensure_index(
        op,
        "idx_cluster_merge_suggestions_cluster_b",
        "cluster_merge_suggestions",
        ["cluster_b_id"],
    )
    _ensure_index(
        op,
        "idx_cluster_merge_suggestions_pending",
        "cluster_merge_suggestions",
        ["tenant_id", "confidence_score"],
        postgresql_where=sa.text("resolution = 'pending'"),
    )
    _ensure_index(
        op,
        "idx_name_suggestions_tenant",
        "name_suggestions",
        ["tenant_id"],
    )
    _ensure_index(
        op,
        "idx_name_suggestions_cluster",
        "name_suggestions",
        ["cluster_id"],
    )
    _ensure_index(
        op,
        "idx_name_suggestions_pending",
        "name_suggestions",
        ["tenant_id", "confidence_score"],
        postgresql_where=sa.text("resolution = 'pending'"),
    )
    _ensure_index(
        op,
        "idx_identity_cluster_blocks_identity",
        "identity_cluster_blocks",
        ["tenant_id", "identity_id"],
    )
    _ensure_index(
        op,
        "idx_identity_cluster_blocks_cluster",
        "identity_cluster_blocks",
        ["tenant_id", "blocked_cluster_id"],
    )

    _ensure_index(op, "idx_recognition_runs_tenant", "recognition_runs", ["tenant_id"])
    _ensure_index(op, "idx_recognition_runs_status", "recognition_runs", ["status"])
    _ensure_index(op, "idx_recognition_runs_scan_job", "recognition_runs", ["scan_job_id"])
    _ensure_index(op, "idx_recognition_runs_clustering_job", "recognition_runs", ["clustering_job_id"])
    _ensure_index(op, "idx_api_keys_tenant", "api_keys", ["tenant_id"])
    _ensure_index(op, "idx_api_keys_hash", "api_keys", ["api_key_hash"])

    _ensure_index(op, "idx_recognition_events_tenant", "recognition_events", ["tenant_id"])
    _ensure_index(op, "idx_recognition_events_run_time", "recognition_events", ["run_id", "timestamp"])
    _ensure_index(op, "idx_recognition_events_type", "recognition_events", ["event_type"])
    _ensure_index(op, "idx_recognition_events_identity", "recognition_events", ["identity_id"])
    _ensure_index(op, "idx_recognition_events_cluster", "recognition_events", ["cluster_id"])
    _ensure_index(op, "idx_clustering_feedback_tenant", "clustering_feedback", ["tenant_id"])
    _ensure_index(op, "idx_clustering_feedback_identity", "clustering_feedback", ["identity_id"])
    _ensure_index(op, "idx_clustering_feedback_cluster", "clustering_feedback", ["cluster_id"])
    _ensure_index(op, "idx_clustering_feedback_action", "clustering_feedback", ["user_action"])
    _ensure_index(op, "idx_audit_events_tenant_event", "audit_events", ["tenant_id", "event_type"])
    _ensure_index(op, "idx_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])

    _ensure_table(
        op,
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
    _ensure_index(op, "idx_export_jobs_tenant", "export_jobs", ["tenant_id"])

    _ensure_table(
        op,
        "image_descriptions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("image_hash", sa.String(length=64), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column("adapter", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("prompt_or_task_version", sa.String(length=64), nullable=False),
        sa.Column("visual_facts", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("alt_text_draft", sa.Text(), nullable=False),
        # ALTQ-1: optional long-form surface (dual-length prompting); nullable so
        # short-only adapters and pre-ALTQ-1 rows need no backfill.
        sa.Column("alt_text_long", sa.Text(), nullable=True),
        sa.Column("context_used", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("provider_disclosure", sa.dialects.postgresql.JSONB(), nullable=False),
        # E19-4a: caption phrase-grounding boxes persisted with the cached
        # description so cache hits produce the same named preview draft.
        sa.Column("phrase_boxes", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("retention_class", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "image_hash",
            "adapter",
            "model_id",
            "model_version",
            "prompt_or_task_version",
            "context_hash",
            name="uq_image_descriptions_cache_key",
        ),
    )
    _ensure_index(op, "idx_image_descriptions_tenant", "image_descriptions", ["tenant_id"])

    _ensure_table(
        op,
        "image_description_runs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # VLM-5: bulk multi-item vs single-image async supersede jobs.
        sa.Column("run_kind", sa.String(length=8), nullable=False, server_default=sa.text("'bulk'")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("phase", sa.String(length=32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("media_ids", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("completed_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("recognition_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # GUIDEDFIX-2: caller retry token, the canonical digest of the payload it
        # binds, and the generation budget disclosed at accept.
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_digest", sa.String(length=64), nullable=True),
        sa.Column("deadline_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'completed_with_errors', 'failed', 'cancelled')",
            name="valid_describe_run_status",
        ),
        sa.CheckConstraint(
            "phase IN ('queued', 'warming', 'describing', 'complete', 'failed', 'cancelled')",
            name="valid_describe_run_phase",
        ),
        sa.CheckConstraint("run_kind IN ('bulk', 'single')", name="valid_describe_run_kind"),
        # GUIDEDFIX-2: the describe-run accept reservation. NULLs are distinct, so
        # only token-carrying submits are deduped.
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_image_description_runs_idempotency_key"),
        # [S02] image_description_runs predates this constraint, so every
        # already-provisioned database reaches the table-exists branch with the
        # constraint absent. Declare it heal-additive: ALTER TABLE ... ADD
        # CONSTRAINT UNIQUE instead of a RuntimeError on every migrate.
        heal_constraints=("uq_image_description_runs_idempotency_key",),
    )
    _ensure_index(op, "idx_image_description_runs_tenant", "image_description_runs", ["tenant_id"])
    _ensure_index(
        op,
        "idx_image_description_runs_active",
        "image_description_runs",
        ["tenant_id", "status"],
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    # Load-snapshot active counts only — a tenant-less RLS-bypassed query (VLM-5).
    # The retention purge scans TERMINAL single runs and cannot use this index;
    # it has its own partial index below (VLM5-S1A-BR-04).
    _ensure_index(
        op,
        "idx_image_description_runs_single_active",
        "image_description_runs",
        ["status"],
        postgresql_where=sa.text("run_kind = 'single' AND status IN ('pending', 'running')"),
    )
    # Purge scan: terminal single runs older than retention, matched on completed_at
    # (purge_expired_single_runs, VLM-5 design (d)).
    _ensure_index(
        op,
        "idx_image_description_runs_single_terminal",
        "image_description_runs",
        ["completed_at"],
        postgresql_where=sa.text(
            "run_kind = 'single' AND status IN ('completed', 'completed_with_errors', 'failed', 'cancelled')"
        ),
    )

    _ensure_table(
        op,
        "image_description_run_items",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("image_description_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        # WBUX-3: raw submitted image bytes, cleared to NULL after describe.
        sa.Column("image_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("image_content_type", sa.String(length=255), nullable=True),
        sa.Column("alt_text_draft", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("provenance", sa.dialects.postgresql.JSONB(), nullable=True),
        # VLM-5: single-run supersede envelope fields (bulk items leave these null).
        sa.Column("visual_facts", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("tier", sa.String(length=32), nullable=True),
        sa.Column("result_generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "media_id", name="uq_image_description_run_item_media"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'skipped')",
            name="valid_describe_item_status",
        ),
    )
    _ensure_index(op, "idx_image_description_run_items_run", "image_description_run_items", ["run_id"])
    _ensure_index(
        op,
        "idx_image_description_run_items_queued",
        "image_description_run_items",
        ["run_id", "status"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    _ensure_index(
        op,
        "idx_image_description_run_items_stale",
        "image_description_run_items",
        ["status", "started_at"],
        postgresql_where=sa.text("status = 'running'"),
    )
    _ensure_index(
        op,
        "idx_image_description_run_items_tenant",
        "image_description_run_items",
        ["tenant_id", "id"],
    )

    # E15-34 Slice 5: observability tables adopted from db/models/observability.py
    # (previously ORM-only; written live by the recognition runtime).
    _ensure_table(
        op,
        "clustering_job_reports",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("total_identities", sa.Integer(), nullable=False),
        sa.Column("accept_count", sa.Integer(), nullable=False),
        sa.Column("suggest_count", sa.Integer(), nullable=False),
        sa.Column("reject_count", sa.Integer(), nullable=False),
        sa.Column("clusters_created", sa.Integer(), nullable=False),
        sa.Column("avg_similarity", sa.Float(), nullable=True),
        sa.Column("success_rate", sa.Float(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    _ensure_index(op, "idx_clustering_reports_tenant", "clustering_job_reports", ["tenant_id"])
    _ensure_index(op, "idx_clustering_reports_job", "clustering_job_reports", ["job_id"])

    _ensure_table(
        op,
        "assignment_decisions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("identity_id", sa.String(length=64), nullable=False),
        sa.Column("cluster_id", sa.String(length=64), nullable=True),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("algorithm", sa.String(length=50), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    _ensure_index(op, "idx_assignment_decisions_tenant", "assignment_decisions", ["tenant_id"])
    _ensure_index(op, "idx_assignment_decisions_cluster", "assignment_decisions", ["cluster_id"])
    _ensure_index(op, "idx_assignment_decisions_decision", "assignment_decisions", ["decision"])
    _ensure_index(op, "idx_assignment_decisions_timestamp", "assignment_decisions", ["timestamp"])

    # FIR-9: workbench curation atlas (batch projection of identity embeddings)
    _ensure_table(
        op,
        "identity_atlas_runs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("params", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('building', 'complete', 'failed')",
            name="valid_atlas_run_status",
        ),
    )
    _ensure_index(op, "idx_identity_atlas_runs_tenant", "identity_atlas_runs", ["tenant_id"])

    _ensure_table(
        op,
        "identity_atlas_points",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_atlas_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("queue_rank", sa.Integer(), nullable=False),
        sa.Column("uncertainty", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "identity_id", name="uq_identity_atlas_points_run_identity"),
        # Target for composite FK from dispositions: forces disposition.run_id
        # to match the referenced point's run_id (FIR-9 cross-run attach).
        sa.UniqueConstraint("id", "run_id", name="uq_identity_atlas_points_id_run"),
    )
    _ensure_index(
        op,
        "idx_identity_atlas_points_run_queue_rank",
        "identity_atlas_points",
        ["run_id", "queue_rank"],
    )
    _ensure_index(op, "idx_identity_atlas_points_tenant", "identity_atlas_points", ["tenant_id"])
    # Purge disposed scope filters points on (tenant_id, identity_id).
    _ensure_index(
        op,
        "idx_identity_atlas_points_tenant_identity",
        "identity_atlas_points",
        ["tenant_id", "identity_id"],
    )

    _ensure_table(
        op,
        "identity_atlas_queue_dispositions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("identity_atlas_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "point_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "point_id", name="uq_identity_atlas_dispositions_run_point"),
        # Composite FK: disposition.run_id must equal the point's run_id.
        sa.ForeignKeyConstraint(
            ["point_id", "run_id"],
            ["identity_atlas_points.id", "identity_atlas_points.run_id"],
            ondelete="CASCADE",
            name="fk_identity_atlas_dispositions_point_run",
        ),
        sa.CheckConstraint(
            "action IN ('reviewed', 'skipped')",
            name="valid_atlas_disposition_action",
        ),
    )
    _ensure_index(
        op,
        "idx_identity_atlas_queue_dispositions_tenant",
        "identity_atlas_queue_dispositions",
        ["tenant_id"],
    )
    # Point-delete CASCADE looks up dispositions by point_id.
    _ensure_index(
        op,
        "idx_identity_atlas_queue_dispositions_point",
        "identity_atlas_queue_dispositions",
        ["point_id"],
    )
    ensure_identity_vector_typmods(op)


def ensure_rls(op) -> None:
    """Enable+force RLS and (re)create the tenant-isolation policy per TENANT_TABLES."""
    bind = op.get_bind()
    for table in TENANT_TABLES:
        flags = bind.execute(
            sa.text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = :name"
            ),
            {"name": table},
        ).first()
        if flags is None:
            raise RuntimeError(f"ensure_rls: tenant table {table!r} does not exist; run ensure_tables first")
        if not flags[0]:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        if not flags[1]:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # Drop+recreate converges the policy BODY, not just its name — a
        # drifted/permissive expression (e.g. USING (true)) would otherwise
        # survive healing forever. Transactional DDL: no unprotected window.
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            FOR ALL
            USING (tenant_id = {SAFE_TENANT_EXPR} OR {BYPASS_RLS_EXPR})
            WITH CHECK (tenant_id = {SAFE_TENANT_EXPR} OR {BYPASS_RLS_EXPR})
            """
        )


def ensure_refresh_queue(op) -> None:
    """Create the raw-SQL centroid refresh queue table if missing."""
    _ensure_table(
        op,
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


def ensure_triggers(op) -> None:
    """(Re)create the centroid-dirty functions and triggers (CREATE OR REPLACE)."""
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
        CREATE OR REPLACE TRIGGER trg_mark_centroid_dirty_on_members
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
        CREATE OR REPLACE TRIGGER trg_mark_centroid_dirty_on_media
        AFTER UPDATE OR DELETE ON media_identities
        FOR EACH ROW
        EXECUTE FUNCTION mark_dirty_on_media_identities();
        """
    )


def _vector_column_typmod(op, table_name: str, column_name: str) -> int | None:
    """Return atttypmod only when the column's pg_type.typname is vector."""
    return (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT a.atttypmod FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_type t ON t.oid = a.atttypid "
                "WHERE n.nspname = current_schema() "
                "AND c.relname = :table_name "
                "AND a.attname = :column_name AND NOT a.attisdropped "
                "AND t.typname = 'vector'"
            ),
            {"table_name": table_name, "column_name": column_name},
        )
        .scalar()
    )


def _matview_centroid_typmod(op) -> int | None:
    # INT-01: join pg_type and require typname='vector'. A non-vector column
    # with a coincidental atttypmod must not look healthy.
    return (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT a.atttypmod FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_type t ON t.oid = a.atttypid "
                "WHERE n.nspname = current_schema() "
                "AND c.relname = 'mv_identity_cluster_centroids' "
                "AND a.attname = 'centroid' AND NOT a.attisdropped "
                "AND t.typname = 'vector'"
            )
        )
        .scalar()
    )


def ensure_identity_vector_typmods(op) -> None:
    """Fail closed on a wrong-typmod *table* vector column (not rebuildable)."""
    for table_name, column_name in IDENTITY_VECTOR_COLUMNS:
        if table_name == "mv_identity_cluster_centroids":
            continue
        if _relkind(op, table_name) not in ("r", "p"):
            continue
        observed = _vector_column_typmod(op, table_name, column_name)
        if observed != EMBEDDING_DIMENSION:
            raise RuntimeError(
                f"cannot repair {table_name}.{column_name}: observed vector typmod "
                f"{observed!r} (expected {EMBEDDING_DIMENSION} and pg_type.typname='vector'). "
                "Table columns cannot be dropped and rebuilt like derived matview data. "
                "Operator action: "
                f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
                f"TYPE vector({EMBEDDING_DIMENSION}) "
                f"USING {column_name}::vector({EMBEDDING_DIMENSION}); "
                "then re-run python -m scripts.sync_identity_schema."
            )


def _current_user_quoted(op) -> tuple[str, str]:
    row = op.get_bind().execute(sa.text("SELECT current_user, quote_ident(current_user)")).one()
    return str(row[0]), str(row[1])


def _quote_ident(op, ident: str) -> str:
    quoted = op.get_bind().execute(sa.text("SELECT quote_ident(:ident)"), {"ident": ident}).scalar()
    return str(quoted)


def _matview_owner_and_can_drop(op) -> tuple[str, bool]:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT pg_get_userbyid(c.relowner), "
                "pg_has_role(current_user, c.relowner, 'USAGE') "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() "
                "AND c.relname='mv_identity_cluster_centroids' "
                "AND c.relkind='m'"
            )
        )
        .one_or_none()
    )
    if row is None:
        raise RuntimeError(
            "cannot rebuild mv_identity_cluster_centroids: "
            "relation vanished mid-heal; re-run python -m scripts.sync_identity_schema"
        )
    owner, can_drop = row
    return str(owner), bool(can_drop)


def _matview_create_privilege_gaps(op) -> list[str]:
    # WHY: must match FROM/JOIN tables + functions in ensure_matview's CREATE MATERIALIZED VIEW body (C-01 ratchet).
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT current_schema(), "
                "has_schema_privilege(current_user, current_schema(), 'CREATE'), "
                "has_table_privilege(current_user, 'identity_clusters', 'SELECT'), "
                "has_table_privilege(current_user, 'identity_members', 'SELECT'), "
                "has_table_privilege(current_user, 'media_identities', 'SELECT'), "
                "EXISTS ("
                "  SELECT 1 FROM pg_proc p "
                "  WHERE p.proname = 'l2_normalize' "
                "    AND has_function_privilege(current_user, p.oid, 'EXECUTE')"
                ")"
            )
        )
        .one()
    )
    schema_name, schema_create, sel_clusters, sel_members, sel_media, exec_l2 = row
    gaps: list[str] = []
    if not schema_create:
        gaps.append(f"CREATE on schema {schema_name}")
    if not sel_clusters:
        gaps.append("SELECT on identity_clusters")
    if not sel_members:
        gaps.append("SELECT on identity_members")
    if not sel_media:
        gaps.append("SELECT on media_identities")
    if not exec_l2:
        gaps.append("EXECUTE on l2_normalize")
    return gaps


def _matview_nonowner_grants(op) -> tuple[tuple[str, str, bool], ...]:
    # NULL relacl is the default ACL (owner only). aclexplode rejects NULL and
    # also rejects a zero-dimensional empty aclitem array, so the LATERAL join
    # is gated on relacl IS NOT NULL and does not substitute an empty array.
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT "
                "CASE WHEN acl.grantee = 0 THEN 'public' "
                "ELSE pg_get_userbyid(acl.grantee) END AS grantee, "
                "acl.privilege_type, "
                "acl.is_grantable "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "LEFT JOIN LATERAL aclexplode(c.relacl) AS acl ON c.relacl IS NOT NULL "
                "WHERE n.nspname = current_schema() "
                "AND c.relname = 'mv_identity_cluster_centroids' "
                "AND c.relkind = 'm' "
                "AND acl.grantee IS NOT NULL "
                "AND acl.grantee IS DISTINCT FROM c.relowner"
            )
        )
        .all()
    )
    return tuple((str(grantee), str(privilege), bool(grantable)) for grantee, privilege, grantable in rows)


def _missing_matview_grant_roles(op, grants: tuple[tuple[str, str, bool], ...]) -> tuple[str, ...]:
    """Role names in *grants* that no longer exist in pg_roles (not ``public``)."""
    missing: list[str] = []
    seen: set[str] = set()
    bind = op.get_bind()
    for grantee, _privilege, _grantable in grants:
        if grantee in seen or grantee == "public":
            continue
        seen.add(grantee)
        exists = bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"),
            {"name": grantee},
        ).scalar()
        if not exists:
            missing.append(grantee)
    return tuple(missing)


def _restore_matview_owner_and_grants(
    op,
    *,
    current_role: str,
    owner: str,
    grants: tuple[tuple[str, str, bool], ...],
) -> None:
    for grantee, privilege, grantable in grants:
        option = " WITH GRANT OPTION" if grantable else ""
        try:
            quoted_grantee = _quote_ident(op, grantee)
            op.execute(f"GRANT {privilege} ON mv_identity_cluster_centroids TO {quoted_grantee}{option}")
        except sa.exc.DBAPIError as exc:
            raise RuntimeError(
                f"cannot restore GRANT {privilege} ON mv_identity_cluster_centroids TO {grantee}: "
                "the grant could not be replayed; the DROP+CREATE was not committed. "
                "Operator action: remove stale relacl or recreate the role."
            ) from exc
    if owner != current_role:
        try:
            quoted_owner = _quote_ident(op, owner)
            op.execute(f"ALTER MATERIALIZED VIEW mv_identity_cluster_centroids OWNER TO {quoted_owner}")
        except sa.exc.DBAPIError as exc:
            raise RuntimeError(
                f"cannot restore OWNER TO {owner} on mv_identity_cluster_centroids: "
                f"the materialized view was rebuilt but ownership could not be restored to {owner}; "
                "re-run python -m scripts.sync_identity_schema"
            ) from exc


def ensure_matview(op) -> None:
    """Create the centroid materialized view + indexes; fail loudly on a plain-table impostor.

    A matview whose ``centroid`` column lost its vector typmod (built before the
    outer cast existed) is derived data, so it is dropped and rebuilt here when
    the current role can drop it *and* recreate it with owner+grants restored.
    Otherwise the heal raises a named operator action before making any
    destructive change.
    """
    relkind = _relkind(op, "mv_identity_cluster_centroids")
    if relkind not in (None, "m"):
        raise RuntimeError(
            "mv_identity_cluster_centroids exists with relkind "
            f"{relkind!r} (expected materialized view); drop the impostor relation "
            "before healing (operator action, see E15-33-BR2-04)"
        )
    restore: tuple[str, str, tuple[tuple[str, str, bool], ...]] | None = None
    if relkind == "m":
        observed_typmod = _matview_centroid_typmod(op)
        if observed_typmod != EMBEDDING_DIMENSION:
            owner, can_drop = _matview_owner_and_can_drop(op)
            current_role, quoted_role = _current_user_quoted(op)
            if not can_drop:
                operator_sql = f"ALTER MATERIALIZED VIEW mv_identity_cluster_centroids OWNER TO {quoted_role};"
                raise RuntimeError(
                    "cannot rebuild mv_identity_cluster_centroids: "
                    f"observed centroid typmod {observed_typmod!r}; owner role is {owner!r}; "
                    f"current role is {current_role!r} and cannot DROP the relation. "
                    f"Run {operator_sql} then re-run python -m scripts.sync_identity_schema."
                )
            gaps = _matview_create_privilege_gaps(op)
            if gaps:
                raise RuntimeError(
                    "cannot rebuild mv_identity_cluster_centroids: "
                    f"observed centroid typmod {observed_typmod!r}; "
                    "current role lacks privileges required to recreate the view: "
                    f"{', '.join(gaps)}. Grant these privileges then re-run "
                    "python -m scripts.sync_identity_schema."
                )
            grants = _matview_nonowner_grants(op)
            missing_roles = _missing_matview_grant_roles(op, grants)
            if missing_roles:
                raise RuntimeError(
                    "cannot rebuild mv_identity_cluster_centroids: "
                    f"observed centroid typmod {observed_typmod!r}; "
                    "relacl names vanished roles "
                    f"{', '.join(missing_roles)} that cannot receive GRANT. "
                    "Operator action: REVOKE the stale grants or DROP the view as its owner."
                )
            restore = (current_role, owner, grants)
            op.execute("DROP MATERIALIZED VIEW mv_identity_cluster_centroids")
    # WHY: FROM/JOIN tables + functions here are preflighted by _matview_create_privilege_gaps (C-01 ratchet).
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_identity_cluster_centroids AS
        WITH member_rows AS (
            SELECT
                im.cluster_id,
                mi.tenant_id,
                mi.embedding,
                mi.embedding_model,
                mi.updated_at
            FROM identity_members im
            JOIN media_identities mi ON mi.id = im.identity_id
            WHERE mi.embedding IS NOT NULL
              AND mi.embedding_model IS NOT NULL
        ),
        -- FIR23-01: frame each cluster centroid to a single embedding_model
        -- (majority, lex-stable tie-break). Single-model data is a no-op;
        -- load-bearing when mixed models coexist.
        model_counts AS (
            SELECT
                cluster_id,
                embedding_model,
                COUNT(*) AS n
            FROM member_rows
            GROUP BY cluster_id, embedding_model
        ),
        chosen_model AS (
            SELECT DISTINCT ON (cluster_id)
                cluster_id,
                embedding_model
            FROM model_counts
            ORDER BY cluster_id, n DESC, embedding_model ASC
        ),
        normalized_embeddings AS (
            SELECT
                mr.cluster_id,
                mr.tenant_id,
                l2_normalize(mr.embedding)::vector({EMBEDDING_DIMENSION}) AS unit_embedding,
                mr.updated_at
            FROM member_rows mr
            JOIN chosen_model cm
              ON cm.cluster_id = mr.cluster_id
             AND cm.embedding_model = mr.embedding_model
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
            -- The outer cast is load-bearing: CASE with an untyped NULL arm
            -- drops the vector typmod, and /health + /ready fail closed on a
            -- matview column whose pg_attribute.atttypmod is -1.
            (CASE
                WHEN identity_count > 0 AND avg_embedding IS NOT NULL THEN
                    l2_normalize(avg_embedding)::vector({EMBEDDING_DIMENSION})
                ELSE NULL
            END)::vector({EMBEDDING_DIMENSION}) AS centroid,
            refreshed_at
        FROM cluster_embeddings
        WHERE identity_count >= 1;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS mv_cluster_centroids_cluster_id
        ON mv_identity_cluster_centroids (cluster_id);
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS mv_cluster_centroids_tenant_idx
        ON mv_identity_cluster_centroids (tenant_id);
        """
    )

    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS mv_cluster_centroids_vector_idx
        ON mv_identity_cluster_centroids
        USING ivfflat ((centroid::vector({EMBEDDING_DIMENSION})) vector_cosine_ops)
        WHERE centroid IS NOT NULL;
        """
    )
    if restore is not None:
        current_role, owner, grants = restore
        _restore_matview_owner_and_grants(op, current_role=current_role, owner=owner, grants=grants)


def heal(connection) -> None:
    """Boot-time reconciliation: converge any partial schema to the full one.

    Composes the exact `ensure_*` units `upgrade()` runs, on an existing
    connection (the sync entrypoint holds the advisory lock around this).
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ops = Operations(MigrationContext.configure(connection))
    connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    ensure_tables(ops)
    ensure_rls(ops)
    ensure_refresh_queue(ops)
    ensure_triggers(ops)
    ensure_matview(ops)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # NOTE: DROP statements removed - they were causing data loss when alembic version tracking
    # got corrupted. Use scripts/reset_dev_db.sh explicitly if you need a clean slate.
    # The migration is the baseline - if tables already exist, alembic won't re-run this.
    ensure_tables(op)
    ensure_rls(op)
    ensure_refresh_queue(op)
    ensure_triggers(op)
    ensure_matview(op)


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
    op.drop_index("idx_image_description_run_items_tenant", table_name="image_description_run_items")
    op.drop_index("idx_image_description_run_items_stale", table_name="image_description_run_items")
    op.drop_index("idx_image_description_run_items_queued", table_name="image_description_run_items")
    op.drop_index("idx_image_description_run_items_run", table_name="image_description_run_items")
    op.drop_index("idx_image_description_runs_active", table_name="image_description_runs")
    op.drop_index("idx_image_description_runs_tenant", table_name="image_description_runs")
    op.drop_index("idx_scan_job_items_tenant_id", table_name="identity_scan_job_items")
    op.drop_index("idx_scan_job_items_stale", table_name="identity_scan_job_items")
    op.drop_index("idx_scan_job_items_pending", table_name="identity_scan_job_items")
    op.drop_index("idx_scan_job_items_job", table_name="identity_scan_job_items")
    op.drop_index("idx_identity_scan_jobs_status", table_name="identity_scan_jobs")
    op.drop_index("idx_identity_scan_jobs_tenant", table_name="identity_scan_jobs")
    op.drop_index("idx_identity_members_identity", table_name="identity_members")
    op.drop_index("idx_identity_members_cluster", table_name="identity_members")
    op.drop_index("idx_identity_name_suppressions_tenant", table_name="identity_name_suppressions")
    op.drop_index("idx_identity_clusters_roster", table_name="identity_clusters")
    op.drop_index("idx_curation_replay_tenant", table_name="curation_replay_records")
    op.drop_index("idx_identity_clusters_tenant_type", table_name="identity_clusters")
    op.drop_index("idx_identity_clusters_tenant", table_name="identity_clusters")
    op.drop_index("idx_media_identities_embedding", table_name="media_identities")
    op.drop_index("idx_media_identities_embedding_model", table_name="media_identities")
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
    op.drop_index("idx_api_keys_hash", table_name="api_keys")
    op.drop_index("idx_api_keys_tenant", table_name="api_keys")
    op.drop_index("idx_demo_instances_api_key_ref", table_name="demo_instances")
    op.drop_index("idx_demo_instances_expires", table_name="demo_instances")
    op.drop_index("idx_demo_instances_tenant", table_name="demo_instances")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for table in DOWNGRADE_TABLE_ORDER:
        op.drop_table(table)
