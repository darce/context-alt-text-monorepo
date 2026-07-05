"""Idempotent identity-schema self-heal for the container entrypoint.

Runs at boot **after** ``alembic upgrade head`` and **before** the fail-closed
``verify_identity_schema``. Because the greenfield schema lives in a single
in-place ``001_identity_schema.py`` under a constant revision id, ``alembic
upgrade head`` is a no-op on an already-stamped DB and new tables never appear.
This module closes that gap by additively creating any missing table on the
live DB, so an in-place *new-table* addition reaches prod without abandoning the
single-file schema model (E15-33 Slice 1; mirrors the manual E15-29 repair,
decision 1194).

Scope boundary: ``create_all(checkfirst=True)`` creates missing **tables** only.
It never alters or drops, and does **not** add columns, indexes, or constraints
to a pre-existing table. Column/index/constraint drift is out of scope here and
is not self-healed (nor caught by the table-granular ``verify_identity_schema``).
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import Engine, create_engine, inspect, text

import db.models  # noqa: F401  (import registers every ORM table on Base.metadata)
from db.base import Base
from db.settings import get_database_settings

logger = logging.getLogger("sync_identity_schema")

# Stable advisory-lock key so concurrent boots serialize on the same lock.
_ADVISORY_LOCK_KEY = 0xAC33051D


def sync_schema(engine: Engine) -> list[str]:
    """Additively create any missing table on ``engine``.

    Returns the sorted names of tables that were created. Additive only:
    ``create_all(checkfirst=True)`` skips existing tables and never alters or
    drops, so existing rows are untouched and a second call is a clean no-op.

    The api and worker containers share the entrypoint, so they can boot
    concurrently against a fresh/drifted DB; ``create_all(checkfirst=True)`` is
    check-then-create and not atomic across connections, so two racers could both
    issue ``CREATE TABLE`` and one would crash. A Postgres transaction-scoped
    advisory lock serializes the self-heal (no-op on sqlite in tests).
    """
    before = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        Base.metadata.create_all(conn, checkfirst=True)
    created = sorted(set(inspect(engine).get_table_names()) - before)
    if created:
        logger.info("identity schema self-heal created tables: %s", ", ".join(created))
    else:
        logger.info("identity schema self-heal: no missing tables")
    return created


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = create_engine(get_database_settings().postgres_sync_dsn)
    try:
        sync_schema(engine)
    except Exception:  # fail closed at the entrypoint — no worse than verify failing
        logger.exception("identity schema self-heal failed")
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
