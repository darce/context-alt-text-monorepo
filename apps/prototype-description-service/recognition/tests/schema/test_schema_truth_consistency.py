"""E15-34 Slice 1: truth-consistency ratchet between the three schema truths.

Truth A: migration DDL in ``db/migrations/versions/001_identity_schema.py``
(``TENANT_TABLES``, ``EXPECTED_SCHEMA_TABLES``, ``RAW_SQL_TABLES``).
Truth B: ORM ``Base.metadata``.
Truth C: the ``EXPECTED_SCHEMA_TABLES`` list the boot verifier consumes.

No database: pure set-relation assertions, so any new divergence fails CI
immediately. Known divergence is held in the explicit allowlists below; each
entry names the slice that removes it. NOTE: assertion (c) uses
``EXPECTED_SCHEMA_TABLES`` membership as a *proxy* for migration-DDL coverage
until Slice 3 ships the ``ensure_*`` helpers and tightens it to
"creatable by ``heal()``".
"""

from __future__ import annotations

import importlib

import db.models  # noqa: F401  (registers every ORM table on Base.metadata)
from db.base import Base

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")

# Tenant-id-bearing ORM tables intentionally NOT under RLS, or not yet under
# RLS. Keys are table names; values are the rationale shown on failure.
RLS_EXEMPT_ALLOWLIST = {
    "api_keys": "pre-tenant-context lookup path; RLS would break key resolution (documented in E15-34 scope Not-Doing)",
    "mv_identity_cluster_centroids": "materialized view; Postgres does not support RLS on matviews",
    "assignment_decisions": "removed in Slice 5",
    "clustering_job_reports": "removed in Slice 5",
}

# ORM tables written by runtime code that the migration/verifier must own.
RUNTIME_WRITTEN_ORM_TABLES = {"assignment_decisions", "clustering_job_reports"}

# Runtime-written tables temporarily absent from EXPECTED_SCHEMA_TABLES.
MIGRATION_GAP_ALLOWLIST = {
    "assignment_decisions": "removed in Slice 5",
    "clustering_job_reports": "removed in Slice 5",
}


def test_every_tenant_id_orm_table_is_rls_governed_or_allowlisted() -> None:
    # (a) tenant_id column => TENANT_TABLES membership or documented exemption.
    tenant_tables = set(MIGRATION.TENANT_TABLES)
    offenders = {
        name: "add to TENANT_TABLES or RLS_EXEMPT_ALLOWLIST with rationale"
        for name, table in Base.metadata.tables.items()
        if "tenant_id" in table.columns and name not in tenant_tables and name not in RLS_EXEMPT_ALLOWLIST
    }
    assert not offenders, f"tenant_id tables outside RLS governance: {offenders}"


def test_every_expected_table_is_orm_creatable_or_raw_sql() -> None:
    # (b) verifier contract ⊆ (ORM metadata ∪ migration raw-SQL tables), so a
    # heal built on either surface can always satisfy the verifier.
    orm_tables = set(Base.metadata.tables)
    raw_sql = set(MIGRATION.RAW_SQL_TABLES)
    missing = set(MIGRATION.EXPECTED_SCHEMA_TABLES) - orm_tables - raw_sql
    assert not missing, f"EXPECTED_SCHEMA_TABLES entries with no ORM model and not in RAW_SQL_TABLES: {sorted(missing)}"


def test_raw_sql_tables_have_no_orm_shadow() -> None:
    # RAW_SQL_TABLES exists precisely because these tables have no ORM model;
    # an ORM model appearing for one means the constant (or model) is stale.
    shadowed = set(MIGRATION.RAW_SQL_TABLES) & set(Base.metadata.tables)
    assert not shadowed, f"RAW_SQL_TABLES entries now shadowed by ORM models: {sorted(shadowed)}"


def test_runtime_written_tables_are_migration_owned_or_allowlisted() -> None:
    # (c) proxy until Slice 3: runtime-written ORM tables must be in the
    # verifier contract (=> migration-owned) or in the shrinking gap allowlist.
    expected = set(MIGRATION.EXPECTED_SCHEMA_TABLES)
    offenders = RUNTIME_WRITTEN_ORM_TABLES - expected - set(MIGRATION_GAP_ALLOWLIST)
    assert not offenders, (
        f"runtime-written tables with no migration ownership and no allowlist entry: {sorted(offenders)}"
    )


def test_runtime_written_tables_exist_in_orm() -> None:
    # Guard the ratchet's own input: the RUNTIME_WRITTEN_ORM_TABLES names must
    # stay real ORM tables, else assertion (c) silently checks nothing.
    missing = RUNTIME_WRITTEN_ORM_TABLES - set(Base.metadata.tables)
    assert not missing, f"RUNTIME_WRITTEN_ORM_TABLES entries not in Base.metadata: {sorted(missing)}"
