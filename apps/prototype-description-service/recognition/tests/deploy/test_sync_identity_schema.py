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
