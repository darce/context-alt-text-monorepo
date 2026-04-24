"""Post-migration sanity check for the baseline identity schema.

Fails fast when Alembic reports head but one or more baseline tables are
missing. This guards the "partial schema with alembic_version=head" failure
mode seen during production bootstrap.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterable

from sqlalchemy import create_engine, inspect, text

from db.settings import get_database_settings

identity_schema = importlib.import_module("db.migrations.versions.001_identity_schema")
EXPECTED_REVISION = identity_schema.revision
EXPECTED_TABLES = tuple(identity_schema.EXPECTED_SCHEMA_TABLES)


def _validate_schema_state(
    *,
    actual_tables: Iterable[str],
    actual_revision: str | None,
    expected_tables: Iterable[str] = EXPECTED_TABLES,
    expected_revision: str = EXPECTED_REVISION,
) -> dict[str, object]:
    actual_table_set = set(actual_tables)
    expected_table_set = set(expected_tables)
    missing_tables = sorted(expected_table_set - actual_table_set)
    unexpected_tables = sorted(actual_table_set - expected_table_set)
    revision_matches = actual_revision == expected_revision
    return {
        "ok": revision_matches and not missing_tables,
        "actual_revision": actual_revision,
        "expected_revision": expected_revision,
        "missing_tables": missing_tables,
        "unexpected_tables": unexpected_tables,
    }


def main() -> int:
    dsn = get_database_settings().postgres_sync_dsn
    engine = create_engine(dsn)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            table_names = inspector.get_table_names()
            if "alembic_version" in table_names:
                actual_revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
            else:
                actual_revision = None

        report = _validate_schema_state(actual_tables=table_names, actual_revision=actual_revision)
    finally:
        engine.dispose()

    if report["ok"]:
        print(f"identity schema verified: revision={report['actual_revision']} tables={len(table_names)}")
        return 0

    print("identity schema verification failed", file=sys.stderr)
    print(
        f"expected_revision={report['expected_revision']} actual_revision={report['actual_revision']}",
        file=sys.stderr,
    )
    missing_tables = report["missing_tables"]
    if missing_tables:
        print(f"missing_tables={','.join(missing_tables)}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
