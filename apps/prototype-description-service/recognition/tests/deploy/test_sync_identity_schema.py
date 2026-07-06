"""Entrypoint contract for ``scripts.sync_identity_schema`` (E15-34 Slice 3).

The heal itself is Postgres-only (raw RLS/matview DDL) and is behaviorally
covered by ``recognition/tests/schema/test_identity_schema_heal_pg.py``.
This module unit-tests the entrypoint wiring: advisory lock taken before the
migration ``heal()`` runs, created-set computed inside the locked
transaction, and ``main()``'s fail-closed exit codes.
"""

from __future__ import annotations

import pytest


def test_postgres_boot_takes_advisory_lock_before_heal(monkeypatch) -> None:
    # PA-02 / BR2-10 wiring: on a postgresql connection, pg_advisory_xact_lock
    # must be issued inside the transaction BEFORE the migration heal runs.
    import scripts.sync_identity_schema as mod

    calls: list[str] = []

    class FakeDialect:
        name = "postgresql"

    class FakeResult:
        def __iter__(self):
            return iter([])

    class FakeConn:
        dialect = FakeDialect()

        def execute(self, stmt, params=None):
            stmt_text = str(stmt)
            if "pg_advisory_xact_lock" in stmt_text:
                assert params == {"key": mod._ADVISORY_LOCK_KEY}
                calls.append("lock")
            return FakeResult()

    class FakeBegin:
        def __enter__(self):
            return FakeConn()

        def __exit__(self, *exc):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    class FakeMigration:
        @staticmethod
        def heal(conn):
            calls.append("heal")

    monkeypatch.setattr(mod.importlib, "import_module", lambda name: FakeMigration)

    created = mod.sync_schema(FakeEngine())

    assert calls == ["lock", "heal"]
    assert created == []


def test_created_report_reflects_tables_heal_added(monkeypatch) -> None:
    # The created-set is the delta of pg_tables across heal() inside the same
    # locked transaction — a lock-race loser reports nothing.
    import scripts.sync_identity_schema as mod

    state = {"tables": [("tenants",)]}

    class FakeDialect:
        name = "postgresql"

    class FakeConn:
        dialect = FakeDialect()

        def execute(self, stmt, params=None):
            if "pg_advisory_xact_lock" in str(stmt):
                return []
            return list(state["tables"])

    class FakeBegin:
        def __enter__(self):
            return FakeConn()

        def __exit__(self, *exc):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    class FakeMigration:
        @staticmethod
        def heal(conn):
            state["tables"] = [("tenants",), ("export_jobs",)]

    monkeypatch.setattr(mod.importlib, "import_module", lambda name: FakeMigration)

    assert mod.sync_schema(FakeEngine()) == ["export_jobs"]


class _RecordingEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _patch_engine(monkeypatch) -> _RecordingEngine:
    import scripts.sync_identity_schema as mod

    engine = _RecordingEngine()
    monkeypatch.setattr(mod, "get_database_settings", lambda: type("S", (), {"postgres_sync_dsn": "sqlite://"})())
    monkeypatch.setattr(mod, "create_engine", lambda _dsn: engine)
    return engine


def test_main_returns_zero_and_disposes_on_success(monkeypatch) -> None:
    import scripts.sync_identity_schema as mod

    engine = _patch_engine(monkeypatch)
    monkeypatch.setattr(mod, "sync_schema", lambda _engine: [])
    assert mod.main() == 0
    assert engine.disposed is True


def test_main_fails_closed_and_disposes_on_error(monkeypatch) -> None:
    import scripts.sync_identity_schema as mod

    engine = _patch_engine(monkeypatch)

    def _boom(_engine):
        raise RuntimeError("DDL error")

    monkeypatch.setattr(mod, "sync_schema", _boom)
    assert mod.main() == 1
    assert engine.disposed is True


def test_no_create_all_anywhere() -> None:
    # E15-34 contract: the entrypoint must never re-derive schema from the ORM.
    import inspect as pyinspect

    import scripts.sync_identity_schema as mod

    source = pyinspect.getsource(mod)
    assert ".create_all(" not in source  # docstring mentions the banned API; calls do not
