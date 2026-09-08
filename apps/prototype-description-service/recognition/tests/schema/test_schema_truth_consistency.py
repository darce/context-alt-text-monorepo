"""E15-34 Slice 1: truth-consistency ratchet between the three schema truths.

Truth A: migration DDL in ``db/migrations/versions/001_identity_schema.py``
(``TENANT_TABLES``, ``EXPECTED_SCHEMA_TABLES``, ``RAW_SQL_TABLES``).
Truth B: ORM ``Base.metadata``.
Truth C: the ``EXPECTED_SCHEMA_TABLES`` list the boot verifier consumes.

No database: pure set-relation assertions, so any new divergence fails CI
immediately. Known divergence is held in the explicit allowlists below; each
entry names the slice that removes it. Assertion (c) is anchored to real heal
coverage since Slice 3: ``heal()`` provably creates every
``EXPECTED_SCHEMA_TABLES`` member (PG test
``test_heal_from_empty_db_converges_to_full_schema_with_rls``), so membership
in that list IS the heal-creatable contract, no longer a proxy.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import pathlib

import db.models  # noqa: F401  (registers every ORM table on Base.metadata)
from db.base import Base
from recognition.application.health import IDENTITY_VECTOR_COLUMNS as HEALTH_VECTOR_COLUMNS

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")

# Tenant-id-bearing ORM tables intentionally NOT under RLS, or not yet under
# RLS. Keys are table names; values are the rationale shown on failure.
RLS_EXEMPT_ALLOWLIST = {
    "api_keys": "pre-tenant-context lookup path; RLS would break key resolution (documented in E15-34 scope Not-Doing)",
    "demo_instances": "slug-lookup registry for demo router; cross-tenant by design (launch-plan §5 / DS-3)",
    "mv_identity_cluster_centroids": "materialized view; Postgres does not support RLS on matviews",
}

# ORM tables written by runtime code that the migration/verifier must own.
RUNTIME_WRITTEN_ORM_TABLES = {"assignment_decisions", "clustering_job_reports"}

# Runtime-written tables temporarily absent from EXPECTED_SCHEMA_TABLES.
# Slice 5 emptied this: runtime-written tables are all migration-owned now.
MIGRATION_GAP_ALLOWLIST: dict[str, str] = {}


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
    # (c) runtime-written ORM tables must be heal-creatable (EXPECTED
    # membership, anchored by the Slice-3 PG heal test) or in the shrinking
    # gap allowlist.
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


# ORM tables intentionally absent from the verifier contract (with rationale).
EXPECTED_EXEMPT_ORM_TABLES = {
    "mv_identity_cluster_centroids": "materialized view: created by ensure_matview, not a table",
}


def test_every_orm_table_is_in_the_verifier_contract_or_exempt() -> None:
    # (d) ORM -> migration direction: a new ORM table missing from
    # EXPECTED_SCHEMA_TABLES (and so from heal/verify coverage) fails CI.
    expected = set(MIGRATION.EXPECTED_SCHEMA_TABLES)
    offenders = set(Base.metadata.tables) - expected - set(EXPECTED_EXEMPT_ORM_TABLES)
    assert not offenders, (
        f"ORM tables outside the verifier contract (add to EXPECTED_SCHEMA_TABLES "
        f"+ ensure_tables, or exempt with rationale): {sorted(offenders)}"
    )


def _load_verifier():
    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "verify_identity_schema.py"
    spec = importlib.util.spec_from_file_location("verify_identity_schema_truth", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identity_vector_column_contract_is_shared_across_heal_verify_health() -> None:
    # VLMHEAL-1-REV-A-08: ensure_matview's centroid probe, the verifier column
    # contract, and health.IDENTITY_VECTOR_COLUMNS must stay equal. Observation
    # that would refute the finding: any of the three drifts from the others.
    verifier = _load_verifier()
    assert tuple(MIGRATION.IDENTITY_VECTOR_COLUMNS) == tuple(HEALTH_VECTOR_COLUMNS)
    assert tuple(verifier.IDENTITY_VECTOR_COLUMNS) == tuple(HEALTH_VECTOR_COLUMNS)
    assert verifier.IDENTITY_VECTOR_COLUMNS is HEALTH_VECTOR_COLUMNS

    centroid_pair = ("mv_identity_cluster_centroids", "centroid")
    assert centroid_pair in HEALTH_VECTOR_COLUMNS
    probe_src = inspect.getsource(MIGRATION._matview_centroid_typmod)
    assert "mv_identity_cluster_centroids" in probe_src
    assert "centroid" in probe_src
    assert "typname" in probe_src
    assert "vector" in probe_src
    verifier_src = inspect.getsource(verifier._collect_vector_typmods)
    assert "IDENTITY_VECTOR_COLUMNS" in verifier_src


def test_tenant_and_raw_sql_tables_are_subsets_of_expected() -> None:
    # (e) internal consistency of the migration's own constants.
    expected = set(MIGRATION.EXPECTED_SCHEMA_TABLES)
    assert set(MIGRATION.TENANT_TABLES) <= expected, sorted(set(MIGRATION.TENANT_TABLES) - expected)
    assert set(MIGRATION.RAW_SQL_TABLES) <= expected, sorted(set(MIGRATION.RAW_SQL_TABLES) - expected)
