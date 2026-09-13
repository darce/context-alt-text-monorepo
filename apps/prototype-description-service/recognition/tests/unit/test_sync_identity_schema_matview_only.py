"""Centroid repair stays inside the canonical matview transaction; no database IO."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sync_identity_schema as sync
from scripts import verify_identity_schema as verify


class Engine:
    def __init__(self):
        self.conn = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), execute=Mock())
        self.events = []

    @contextmanager
    def begin(self):
        self.events.append("begin")
        try:
            yield self.conn
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")


def test_repair_delegates_only_to_matview(monkeypatch):
    migration = verify.identity_schema
    conn = Engine().conn
    monkeypatch.setattr("alembic.migration.MigrationContext.configure", lambda connection: connection)
    monkeypatch.setattr("alembic.operations.Operations", lambda context: context)
    narrow = Mock()
    monkeypatch.setattr(migration, "ensure_matview", narrow)
    for name in (
        "ensure_tables",
        "ensure_identity_vector_typmods",
        "ensure_rls",
        "ensure_refresh_queue",
        "ensure_triggers",
        "heal",
    ):
        monkeypatch.setattr(migration, name, Mock(side_effect=AssertionError(name)))
    migration.repair_centroids_matview(conn)
    narrow.assert_called_once_with(conn)
    conn.execute.assert_not_called()


def test_sync_lock_and_transaction(monkeypatch):
    engine = Engine()

    def repair(conn):
        assert engine.events == ["begin"]
        assert "pg_advisory_xact_lock" in str(conn.execute.call_args.args[0])
        assert conn.execute.call_args.args[1] == {"key": sync._ADVISORY_LOCK_KEY}

    monkeypatch.setattr(sync.importlib, "import_module", lambda _: SimpleNamespace(repair_centroids_matview=repair))
    sync.sync_centroids_matview(engine)
    assert engine.events == ["begin", "commit"]


@pytest.mark.parametrize("args,selected", [([], "sync_schema"), (["--matview-only"], "sync_centroids_matview")])
def test_sync_dispatch(monkeypatch, args, selected):
    engine = SimpleNamespace(dispose=Mock())
    monkeypatch.setattr(sync, "create_engine", lambda _: engine)
    monkeypatch.setattr(sync, "get_database_settings", lambda: SimpleNamespace(postgres_sync_dsn="fake"))
    calls = {name: Mock() for name in ("sync_schema", "sync_centroids_matview")}
    for name, call in calls.items():
        monkeypatch.setattr(sync, name, call, raising=False)
    assert sync.main(args) == 0
    calls[selected].assert_called_once_with(engine)
    calls[next(name for name in calls if name != selected)].assert_not_called()
    engine.dispose.assert_called_once()


@pytest.mark.parametrize("code", [0, 1, 2])
def test_verifier_dispatch(monkeypatch, code):
    engine = Engine()
    engine.connect = engine.begin
    engine.dispose = Mock()
    monkeypatch.setattr(verify, "create_engine", lambda _: engine)
    monkeypatch.setattr(verify, "get_database_settings", lambda: SimpleNamespace(postgres_sync_dsn="fake"))
    monkeypatch.setattr(verify, "collect_and_validate", Mock(side_effect=AssertionError("full verifier")))
    monkeypatch.setattr(verify, "collect_matview_state", lambda *a, **kw: {"exit_code": code}, raising=False)
    assert verify.main(["--matview-only", "--expected-owner", "owner", "--expected-acl", "[]"]) == code


@pytest.mark.parametrize(
    "kind,typmod,index,owner,acl,code",
    [
        ("m", verify.EMBEDDING_DIMENSION, True, "owner", (), 0),
        (None, None, False, None, (), 1),
        ("r", None, False, "owner", (), 2),
        ("m", -1, True, "owner", (), 1),
        ("m", verify.EMBEDDING_DIMENSION, False, "owner", (), 1),
        ("m", verify.EMBEDDING_DIMENSION, True, "other", (), 2),
        ("m", verify.EMBEDDING_DIMENSION, True, "owner", (("reader", "SELECT", False),), 2),
    ],
)
def test_scoped_facts(monkeypatch, kind, typmod, index, owner, acl, code):
    conn = SimpleNamespace(
        execute=Mock(
            side_effect=[
                SimpleNamespace(one_or_none=lambda: (kind, owner) if kind else None),
                SimpleNamespace(scalar=lambda: index),
            ]
        )
    )
    monkeypatch.setattr(verify.identity_schema, "_matview_centroid_typmod", lambda _: typmod)
    monkeypatch.setattr(verify.identity_schema, "_matview_nonowner_grants", lambda _: acl)
    report = verify.collect_matview_state(conn, expected_owner="owner", expected_acl=[])
    assert report["exit_code"] == code
    assert report["scope"] == "matview-only"


@pytest.mark.parametrize("sqlstate,attempts", [("55P03", 3), ("42501", 1), ("57014", 1)])
def test_retry_budget_and_rollback(monkeypatch, sqlstate, attempts):
    from sqlalchemy.exc import DBAPIError

    engine = Engine()
    error = DBAPIError("repair", {}, SimpleNamespace(sqlstate=sqlstate))
    repair = Mock(side_effect=error)
    monkeypatch.setattr(sync.importlib, "import_module", lambda _: SimpleNamespace(repair_centroids_matview=repair))
    sleep = Mock()
    monkeypatch.setattr(sync.time, "sleep", sleep)
    with pytest.raises(DBAPIError):
        sync.sync_centroids_matview(engine)
    assert repair.call_count == attempts
    assert engine.events == ["begin", "rollback"] * attempts
    assert sleep.call_count == attempts - 1
    statements = [str(call.args[0]) for call in engine.conn.execute.call_args_list]
    assert "SET LOCAL lock_timeout = '5s'" in statements
    assert "SET LOCAL statement_timeout = '5min'" in statements
