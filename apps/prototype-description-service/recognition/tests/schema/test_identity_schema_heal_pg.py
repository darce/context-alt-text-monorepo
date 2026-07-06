"""E15-34 Slice 3: heal() convergence, idempotence, and lock serialization.

``heal(connection)`` composes the same idempotent ``ensure_*`` helpers as
``upgrade()``, so healing from any partial state — including an empty
database — converges to the full schema **with RLS**. Regressions covered:
E15-33-BR2-01 (raw-SQL queue table heal-creatable), BR2-02 (heal-created
tenant tables carry RLS), BR2-10 (advisory-lock serialization exercised
against real Postgres).
"""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy import text

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")

pytestmark = pytest.mark.pg


def _table_names(engine) -> set[str]:
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))}


def _rls_state(engine) -> dict[str, tuple[bool, bool]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname='public' AND c.relname = ANY(:tables)"
            ),
            {"tables": list(MIGRATION.TENANT_TABLES)},
        ).fetchall()
    return {name: (enabled, forced) for name, enabled, forced in rows}


def test_heal_from_empty_db_converges_to_full_schema_with_rls(pg_empty_engine) -> None:
    # BR2-01 + BR2-02: from a bare database heal creates every expected table
    # (including the raw-SQL refresh queue) and tenant tables get enabled+forced RLS.
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    missing = set(MIGRATION.EXPECTED_SCHEMA_TABLES) - _table_names(pg_empty_engine)
    assert not missing, f"heal left tables missing: {sorted(missing)}"

    state = _rls_state(pg_empty_engine)
    weak = {t: f for t, f in state.items() if f != (True, True)}
    assert not weak and set(state) == set(MIGRATION.TENANT_TABLES), (
        f"heal-created tenant tables without enabled+forced RLS: {weak}"
    )

    with pg_empty_engine.connect() as conn:
        relkind = conn.execute(
            text(
                "SELECT c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname='mv_identity_cluster_centroids'"
            )
        ).scalar()
    assert relkind == "m"


def test_heal_twice_is_a_noop(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    before = _table_names(pg_empty_engine)
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)  # must not raise or emit duplicate-object errors
    assert _table_names(pg_empty_engine) == before


def test_heal_recreates_dropped_refresh_queue(pg_empty_engine) -> None:
    # BR2-01 regression: the exact E15-29 drift shape — stamped DB missing the
    # raw-SQL table — must be repaired by heal.
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.begin() as conn:
        conn.execute(text("DROP TABLE identity_cluster_refresh_queue"))
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    assert "identity_cluster_refresh_queue" in _table_names(pg_empty_engine)


def test_heal_restores_dropped_rls_policy(pg_empty_engine) -> None:
    # BR2-02 drift direction: a tenant table that lost its policy is re-covered.
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.begin() as conn:
        conn.execute(text("DROP POLICY tenant_isolation_export_jobs ON export_jobs"))
        conn.execute(text("ALTER TABLE export_jobs DISABLE ROW LEVEL SECURITY"))
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    state = _rls_state(pg_empty_engine)
    assert state["export_jobs"] == (True, True)
    with pg_empty_engine.connect() as conn:
        has_policy = conn.execute(
            text(
                "SELECT 1 FROM pg_policies WHERE schemaname='public' "
                "AND tablename='export_jobs' AND policyname='tenant_isolation_export_jobs'"
            )
        ).first()
    assert has_policy


def test_concurrent_sync_entrypoints_serialize_on_advisory_lock(pg_empty_engine) -> None:
    # BR2-10: two concurrent sync_schema() runs against the same empty DB must
    # both succeed (the loser waits on pg_advisory_xact_lock, then no-ops).
    from concurrent.futures import ThreadPoolExecutor

    from scripts.sync_identity_schema import sync_schema

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sync_schema(pg_empty_engine), range(2)))

    assert all(isinstance(r, list) for r in results)
    missing = set(MIGRATION.EXPECTED_SCHEMA_TABLES) - _table_names(pg_empty_engine)
    assert not missing, f"concurrent heal left tables missing: {sorted(missing)}"


def test_verifier_detects_dropped_policy_then_heal_repairs(pg_empty_engine) -> None:
    # Slice 4 E2E: dropped policy -> verifier exit 1 naming the table; heal ->
    # verifier OK. (Revision check passes because heal-only DBs have no
    # alembic_version — stamp it manually to isolate the RLS drift.)
    from scripts.verify_identity_schema import EXIT_HEAL_REPAIRABLE, collect_and_validate

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        conn.execute(text("CREATE TABLE alembic_version (version_num varchar(64) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES (:rev)"), {"rev": MIGRATION.revision})

    with pg_empty_engine.connect() as conn:
        assert collect_and_validate(conn)["ok"] is True

    with pg_empty_engine.begin() as conn:
        conn.execute(text("DROP POLICY tenant_isolation_export_jobs ON export_jobs"))

    with pg_empty_engine.connect() as conn:
        report = collect_and_validate(conn)
    assert report["exit_code"] == EXIT_HEAL_REPAIRABLE
    assert report["policy_gaps"] == ["export_jobs"]

    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
    with pg_empty_engine.connect() as conn:
        assert collect_and_validate(conn)["ok"] is True
