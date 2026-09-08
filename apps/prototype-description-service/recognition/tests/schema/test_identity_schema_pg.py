"""E15-34 Slice 2: Postgres-backed baseline for the identity schema.

Applies the real migration to an empty scratch database and asserts the
load-bearing invariants the sqlite substrate cannot see: RLS enabled+forced on
every ``TENANT_TABLES`` member, the matview's ``relkind='m'``, and the full
``EXPECTED_SCHEMA_TABLES`` contract. Skips cleanly when Postgres is
unreachable (fixture in ``recognition/tests/conftest.py``).
"""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy import text

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")

pytestmark = pytest.mark.pg


def test_upgrade_on_empty_db_creates_expected_tables(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        names = {row[0] for row in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))}
    missing = set(MIGRATION.EXPECTED_SCHEMA_TABLES) - names
    assert not missing, f"missing after upgrade(): {sorted(missing)}"


def test_upgrade_enables_and_forces_rls_on_tenant_tables(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname = ANY(:tables)"
            ),
            {"tables": list(MIGRATION.TENANT_TABLES)},
        ).fetchall()
    state = {name: (enabled, forced) for name, enabled, forced in rows}
    missing = set(MIGRATION.TENANT_TABLES) - set(state)
    assert not missing, f"tenant tables absent: {sorted(missing)}"
    weak = {name: flags for name, flags in state.items() if flags != (True, True)}
    assert not weak, f"tenant tables without enabled+forced RLS: {weak}"


def test_matview_has_materialized_relkind(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        relkind = conn.execute(
            text(
                "SELECT c.relkind FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname='mv_identity_cluster_centroids'"
            )
        ).scalar()
    assert relkind == "m", f"mv_identity_cluster_centroids relkind={relkind!r}, expected 'm'"


def test_matview_centroid_carries_vector_typmod(pg_migrated_engine) -> None:
    # /health and /ready read pg_attribute.atttypmod for this column and fail
    # closed on -1; a CASE with an untyped NULL arm silently produced exactly that.
    with pg_migrated_engine.connect() as conn:
        typmod = conn.execute(
            text(
                "SELECT a.atttypmod FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname='mv_identity_cluster_centroids' "
                "AND a.attname='centroid'"
            )
        ).scalar()
    assert typmod == MIGRATION.EMBEDDING_DIMENSION, (
        f"centroid typmod={typmod!r}, expected vector({MIGRATION.EMBEDDING_DIMENSION})"
    )
