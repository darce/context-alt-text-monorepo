"""Identity-schema self-heal for the container entrypoint (E15-34 Slice 3).

Runs at boot **after** ``alembic upgrade head`` and **before** the fail-closed
``verify_identity_schema``. Because the greenfield schema lives in a single
in-place ``001_identity_schema.py`` under a constant revision id, ``alembic
upgrade head`` is a no-op on an already-stamped DB and new schema objects
never appear. This entrypoint closes that gap by delegating to the
migration's own idempotent ``heal()`` (the same ``ensure_*`` units
``upgrade()`` composes), so healing converges to the full schema — tables,
RLS policies, refresh queue, triggers, materialized view — from any partial
state. No ORM ``create_all`` anywhere: the migration is the single source of
truth (replaces the E15-33 interim heal; findings E15-33-BR2-01/02/04).
"""

from __future__ import annotations

import argparse
import importlib
import logging
import random
import sys
import time

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from db.settings import get_database_settings

logger = logging.getLogger("sync_identity_schema")

# Stable advisory-lock key so concurrent boots serialize on the same lock.
_ADVISORY_LOCK_KEY = 0xAC33051D

_MIGRATION_MODULE = "db.migrations.versions.001_identity_schema"


def sync_schema(engine: Engine) -> list[str]:
    """Heal any missing schema object on ``engine`` via the migration's ``heal()``.

    Returns the sorted names of tables that were created (computed inside the
    locked transaction, so a boot that lost the advisory-lock race never
    reports the winner's work). The api and worker containers share the
    entrypoint and can boot concurrently against a fresh/drifted DB; a
    Postgres transaction-scoped advisory lock serializes the heal.
    """
    migration = importlib.import_module(_MIGRATION_MODULE)
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        before = {
            row[0] for row in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))
        }
        migration.heal(conn)
        after = {
            row[0] for row in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))
        }
        created = sorted(after - before)
    if created:
        logger.info("identity schema heal created tables: %s", ", ".join(created))
    else:
        logger.info("identity schema heal: no missing tables")
    return created


# Only lock-not-available (55P03) is retried, in a fresh transaction.
_MATVIEW_LOCK_ATTEMPTS = 3


def sync_centroids_matview(engine: Engine) -> None:
    """Repair the matview atomically under the boot healer's lock and deadlines."""
    migration = importlib.import_module(_MIGRATION_MODULE)
    for attempt in range(_MATVIEW_LOCK_ATTEMPTS):
        try:
            with engine.begin() as conn:
                if conn.dialect.name != "postgresql":
                    raise ValueError("matview-only repair requires PostgreSQL")
                conn.execute(text("SET LOCAL lock_timeout = '5s'"))
                conn.execute(text("SET LOCAL statement_timeout = '5min'"))
                conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
                migration.repair_centroids_matview(conn)
            return
        except DBAPIError as exc:
            code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            if code != "55P03" or attempt + 1 == _MATVIEW_LOCK_ATTEMPTS:
                raise
            time.sleep(0.25 * (2**attempt) + random.uniform(0, 0.25))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matview-only", action="store_true", help="Repair only the centroid materialized view")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = create_engine(get_database_settings().postgres_sync_dsn)
    try:
        if args.matview_only:
            sync_centroids_matview(engine)
        else:
            sync_schema(engine)
    except Exception as exc:  # fail closed at the entrypoint — no worse than verify failing
        logger.exception("identity schema heal failed: %s", exc)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
