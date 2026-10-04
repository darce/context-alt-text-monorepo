"""Scratch Postgres proof that operator-scope recovery RLS drift cannot pass verify.

Mutates policy/RLS on a non-privileged scratch DB, calls the real verifier, then
restores. IDENTITY_PG_REQUIRED=1 fails instead of skip. No production env.
"""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy import text

from scripts.verify_identity_schema import EXIT_HEAL_REPAIRABLE, EXIT_OK, collect_and_validate

pytestmark = pytest.mark.pg

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")
BYPASS_RLS_EXPR = MIGRATION.BYPASS_RLS_EXPR
OPERATOR_SCOPE_TABLES = MIGRATION.OPERATOR_SCOPE_TABLES
CURSOR = "billing_reconciliation_cursor"
LEASE = "billing_known_item_lease"


def _stamp_revision(conn) -> None:
    conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(64) PRIMARY KEY)"))
    conn.execute(text("DELETE FROM alembic_version"))
    conn.execute(text("INSERT INTO alembic_version VALUES (:rev)"), {"rev": MIGRATION.revision})


def _restore_operator_rls(conn, table: str) -> None:
    conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    conn.execute(text(f"DROP POLICY IF EXISTS operator_scope_{table} ON {table}"))
    conn.execute(
        text(
            f"CREATE POLICY operator_scope_{table} ON {table} FOR ALL "
            f"USING ({BYPASS_RLS_EXPR}) WITH CHECK ({BYPASS_RLS_EXPR})"
        )
    )


def _assert_nonprivileged(conn) -> None:
    role, rolsuper, rolbypassrls = conn.execute(
        text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
    ).one()
    assert rolsuper is False, f"role {role!r} is superuser; RLS evidence would be vacuous"
    assert rolbypassrls is False, f"role {role!r} has BYPASSRLS; RLS evidence would be vacuous"


@pytest.fixture
def healed_conn(pg_empty_engine):
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        _stamp_revision(conn)
    with pg_empty_engine.connect() as conn:
        _assert_nonprivileged(conn)
        report = collect_and_validate(conn)
    assert report["ok"] is True, report
    return pg_empty_engine


def test_generated_operator_scope_policy_passes_real_verifier(healed_conn) -> None:
    with healed_conn.connect() as conn:
        report = collect_and_validate(conn)
        rows = conn.execute(
            text(
                "SELECT tablename, policyname, qual, with_check FROM pg_policies "
                "WHERE schemaname = current_schema() AND policyname LIKE 'operator_scope_%'"
            )
        ).fetchall()
    assert report["exit_code"] == EXIT_OK
    names = {row[0] for row in rows}
    assert set(OPERATOR_SCOPE_TABLES) <= names
    assert LEASE in names
    assert all("app.bypass_rls" in (row[2] or "") for row in rows)
    assert all(" OR true" not in (row[2] or "").lower() for row in rows)


def test_missing_operator_scope_policy_fails_then_restore(healed_conn) -> None:
    try:
        with healed_conn.begin() as conn:
            conn.execute(text(f"DROP POLICY operator_scope_{CURSOR} ON {CURSOR}"))
        with healed_conn.connect() as conn:
            report = collect_and_validate(conn)
        assert report["exit_code"] == EXIT_HEAL_REPAIRABLE
        assert CURSOR in report["policy_gaps"]
        assert report["ok"] is False
    finally:
        with healed_conn.begin() as conn:
            _restore_operator_rls(conn, CURSOR)
        with healed_conn.connect() as conn:
            assert collect_and_validate(conn)["ok"] is True


def test_disabled_operator_rls_fails_then_restore(healed_conn) -> None:
    try:
        with healed_conn.begin() as conn:
            conn.execute(text(f"ALTER TABLE {CURSOR} DISABLE ROW LEVEL SECURITY"))
        with healed_conn.connect() as conn:
            report = collect_and_validate(conn)
        assert report["exit_code"] == EXIT_HEAL_REPAIRABLE
        assert CURSOR in report["rls_gaps"]
    finally:
        with healed_conn.begin() as conn:
            _restore_operator_rls(conn, CURSOR)
        with healed_conn.connect() as conn:
            assert collect_and_validate(conn)["ok"] is True


def test_unforced_operator_rls_fails_then_restore(healed_conn) -> None:
    try:
        with healed_conn.begin() as conn:
            conn.execute(text(f"ALTER TABLE {CURSOR} NO FORCE ROW LEVEL SECURITY"))
        with healed_conn.connect() as conn:
            report = collect_and_validate(conn)
        assert report["exit_code"] == EXIT_HEAL_REPAIRABLE
        assert CURSOR in report["rls_gaps"]
    finally:
        with healed_conn.begin() as conn:
            _restore_operator_rls(conn, CURSOR)
        with healed_conn.connect() as conn:
            assert collect_and_validate(conn)["ok"] is True


def test_permissive_or_true_operator_policy_fails_then_restore(healed_conn) -> None:
    try:
        with healed_conn.begin() as conn:
            conn.execute(text(f"DROP POLICY operator_scope_{CURSOR} ON {CURSOR}"))
            conn.execute(
                text(
                    f"CREATE POLICY operator_scope_{CURSOR} ON {CURSOR} FOR ALL "
                    f"USING (({BYPASS_RLS_EXPR}) OR true) "
                    f"WITH CHECK (({BYPASS_RLS_EXPR}) OR true)"
                )
            )
        with healed_conn.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT qual FROM pg_policies WHERE schemaname = current_schema() "
                    "AND tablename = :table AND policyname = :policy"
                ),
                {"table": CURSOR, "policy": f"operator_scope_{CURSOR}"},
            ).scalar_one()
            report = collect_and_validate(conn)
        assert "app.bypass_rls" in stored
        assert report["exit_code"] == EXIT_HEAL_REPAIRABLE
        assert CURSOR in report["policy_gaps"]
        assert report["ok"] is False
    finally:
        with healed_conn.begin() as conn:
            _restore_operator_rls(conn, CURSOR)
        with healed_conn.connect() as conn:
            assert collect_and_validate(conn)["ok"] is True


def test_known_item_lease_operator_scope_is_verified(healed_conn) -> None:
    assert LEASE in OPERATOR_SCOPE_TABLES
    try:
        with healed_conn.begin() as conn:
            conn.execute(text(f"DROP POLICY operator_scope_{LEASE} ON {LEASE}"))
        with healed_conn.connect() as conn:
            report = collect_and_validate(conn)
        assert report["exit_code"] == EXIT_HEAL_REPAIRABLE
        assert LEASE in report["policy_gaps"]
    finally:
        with healed_conn.begin() as conn:
            _restore_operator_rls(conn, LEASE)
        with healed_conn.connect() as conn:
            assert collect_and_validate(conn)["ok"] is True
