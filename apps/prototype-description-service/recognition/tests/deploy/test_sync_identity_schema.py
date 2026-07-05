"""E15-33 Slice 1: entrypoint identity-schema self-heal is additive + idempotent.

The self-heal runs at container boot between ``alembic upgrade head`` and the
fail-closed ``verify_identity_schema`` so an in-place *new-table* addition to
``001_identity_schema.py`` reaches an already-stamped DB without a new alembic
revision. Scope boundary: it creates missing *tables* only — never columns,
indexes, or constraints on pre-existing tables (see E15-33 Slice 1).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

import db.models  # noqa: F401  (import registers every ORM table on Base.metadata)
from db.base import Base
from db.models.tenant import Tenant
from scripts.sync_identity_schema import sync_schema


def _engine(tmp_path: Path):
    # File-based sqlite so inspect()'s fresh connections observe the same DB.
    return create_engine(f"sqlite:///{tmp_path / 'identity.db'}")


def test_sync_creates_missing_table_and_preserves_existing_rows(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    try:
        # Seed a DB that is stamped-but-drifted: all tables minus exactly one.
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(Tenant(site_url="http://seed.test"))
            session.commit()
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE image_descriptions"))
        assert "image_descriptions" not in inspect(engine).get_table_names()

        created = sync_schema(engine)

        assert "image_descriptions" in created
        assert "image_descriptions" in inspect(engine).get_table_names()
        # Additive: the pre-existing row is untouched.
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT site_url FROM tenants")).fetchall()
        assert rows == [("http://seed.test",)]
    finally:
        engine.dispose()


def test_sync_is_noop_when_schema_in_sync(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    try:
        Base.metadata.create_all(engine)
        # First run over an already-complete schema creates nothing...
        assert sync_schema(engine) == []
        # ...and a second run is likewise a clean no-op (idempotent).
        assert sync_schema(engine) == []
    finally:
        engine.dispose()


def test_sync_after_a_real_creation_is_a_noop(tmp_path: Path) -> None:
    # Idempotence over the actual self-heal path: create → heal → re-heal is empty.
    engine = _engine(tmp_path)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE image_descriptions"))
        assert "image_descriptions" in sync_schema(engine)
        tables_after_heal = set(inspect(engine).get_table_names())
        # A second heal right after a real creation must create nothing.
        assert sync_schema(engine) == []
        assert set(inspect(engine).get_table_names()) == tables_after_heal
    finally:
        engine.dispose()


def test_sync_does_not_add_columns_to_existing_table(tmp_path: Path) -> None:
    # Scope boundary: create_all(checkfirst=True) is table-granular — it never
    # alters a pre-existing table, so a drifted/missing column is NOT added.
    engine = _engine(tmp_path)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE tenants (id TEXT PRIMARY KEY)"))
            conn.execute(text("INSERT INTO tenants (id) VALUES ('t1')"))

        created = sync_schema(engine)

        assert "tenants" not in created, "pre-existing table must not be recreated"
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(tenants)")).fetchall()]
            rows = conn.execute(text("SELECT id FROM tenants")).fetchall()
        assert cols == ["id"], "self-heal must not add columns to an existing table"
        assert rows == [("t1",)]
    finally:
        engine.dispose()


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
    # Fail-closed: non-zero exit so the container entrypoint aborts before verify.
    assert mod.main() == 1
    assert engine.disposed is True  # disposed via finally even on failure
