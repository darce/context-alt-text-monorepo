"""Fail-closed boot verifier for the identity schema (E15-34 Slice 4).

Verifies the load-bearing invariant, not just names: every ``TENANT_TABLES``
member must have RLS enabled **and** forced with its ``tenant_isolation_*``
policy present, the centroid materialized view must actually be a matview
(``relkind='m'``), and every ``EXPECTED_SCHEMA_TABLES`` member must exist.

Exit codes distinguish who can fix the gap:

- ``0``  — schema verified.
- ``1``  — heal-repairable drift (missing table / RLS off / policy missing /
  matview absent): re-running ``python -m scripts.sync_identity_schema``
  converges it.
- ``2``  — operator action required (alembic revision mismatch, or the
  matview name exists as a non-matview relation): healing cannot repair
  these; see docs/runbooks/prod-identity-rls-remediation.md.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterable, Mapping
from typing import TypedDict

from sqlalchemy import create_engine, inspect, text

from db.settings import get_database_settings

identity_schema = importlib.import_module("db.migrations.versions.001_identity_schema")
EXPECTED_REVISION = identity_schema.revision
EXPECTED_TABLES = tuple(identity_schema.EXPECTED_SCHEMA_TABLES)
TENANT_TABLES = tuple(identity_schema.TENANT_TABLES)
MATVIEW_NAME = "mv_identity_cluster_centroids"

EXIT_OK = 0
EXIT_HEAL_REPAIRABLE = 1
EXIT_OPERATOR_REQUIRED = 2
EXIT_INFRA = 3  # could not collect facts (DB unreachable etc.); retry, not schema drift


class SchemaStateReport(TypedDict):
    ok: bool
    exit_code: int
    actual_revision: str | None
    expected_revision: str
    missing_tables: list[str]
    unexpected_tables: list[str]
    rls_gaps: list[str]
    policy_gaps: list[str]
    table_impostors: list[str]
    matview_relkind: str | None


def _validate_schema_state(
    *,
    actual_tables: Iterable[str],
    actual_revision: str | None,
    expected_tables: Iterable[str] = EXPECTED_TABLES,
    expected_revision: str = EXPECTED_REVISION,
    tenant_tables: Iterable[str] = TENANT_TABLES,
    rls_state: Mapping[str, tuple[bool, bool]] | None = None,
    policy_names: Iterable[tuple[str, str]] | None = None,
    table_relkinds: Mapping[str, str] | None = None,
    matview_relkind: str | None = "m",
) -> SchemaStateReport:
    """Pure classification of collected schema facts.

    ``rls_state`` maps table -> (rowsecurity, forcerowsecurity); tables absent
    from the mapping count as RLS gaps. ``policy_names`` is the set of
    (tablename, policyname) pairs present. Passing ``None`` for either skips that check (unit-test /
    legacy callers); ``main()`` always collects both.
    """
    actual_table_set = set(actual_tables)
    expected_table_set = set(expected_tables)
    missing_tables = sorted(expected_table_set - actual_table_set)
    unexpected_tables = sorted(actual_table_set - expected_table_set)
    revision_matches = actual_revision == expected_revision

    rls_gaps: list[str] = []
    policy_gaps: list[str] = []
    if rls_state is not None:
        rls_gaps = sorted(t for t in tenant_tables if rls_state.get(t) != (True, True))
    if policy_names is not None:
        # (table, policy) pairs: a policy name on the WRONG table must not
        # satisfy another table's check (cross-table name collision).
        present = set(policy_names)
        policy_gaps = sorted(t for t in tenant_tables if (t, f"tenant_isolation_{t}") not in present)

    # An expected-table name occupied by a non-table relation is NOT
    # heal-repairable: the heal fails loudly on it; classify as operator.
    table_impostors: list[str] = []
    if table_relkinds is not None:
        table_impostors = sorted(
            name
            for name, kind in table_relkinds.items()
            if name in expected_table_set and name != "mv_identity_cluster_centroids" and kind not in ("r", "p")
        )

    matview_impostor = matview_relkind not in (None, "m")
    matview_missing = matview_relkind is None

    if not revision_matches or matview_impostor or table_impostors:
        exit_code = EXIT_OPERATOR_REQUIRED
    elif missing_tables or rls_gaps or policy_gaps or matview_missing:
        exit_code = EXIT_HEAL_REPAIRABLE
    else:
        exit_code = EXIT_OK

    return {
        "ok": exit_code == EXIT_OK,
        "exit_code": exit_code,
        "actual_revision": actual_revision,
        "expected_revision": expected_revision,
        "missing_tables": missing_tables,
        "unexpected_tables": unexpected_tables,
        "rls_gaps": rls_gaps,
        "policy_gaps": policy_gaps,
        "table_impostors": table_impostors,
        "matview_relkind": matview_relkind,
    }


def collect_and_validate(connection) -> SchemaStateReport:
    """Collect live schema facts on ``connection`` and classify them."""
    inspector = inspect(connection)
    table_names = inspector.get_table_names()
    actual_revision = None
    if "alembic_version" in table_names:
        actual_revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()

    rls_state = {
        name: (enabled, forced)
        for name, enabled, forced in connection.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = ANY(:tables)"
            ),
            {"tables": list(TENANT_TABLES)},
        )
    }
    policy_names = {
        (row[0], row[1])
        for row in connection.execute(
            text("SELECT tablename, policyname FROM pg_policies WHERE schemaname = current_schema()")
        )
    }
    table_relkinds = dict(
        connection.execute(
            text(
                "SELECT c.relname, c.relkind FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = ANY(:names)"
            ),
            {"names": list(EXPECTED_TABLES)},
        ).all()
    )
    matview_relkind = connection.execute(
        text(
            "SELECT c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relname = :name"
        ),
        {"name": MATVIEW_NAME},
    ).scalar()

    return _validate_schema_state(
        actual_tables=table_names,
        actual_revision=actual_revision,
        rls_state=rls_state,
        policy_names=policy_names,
        table_relkinds=table_relkinds,
        matview_relkind=matview_relkind,
    )


def main() -> int:
    dsn = get_database_settings().postgres_sync_dsn
    engine = create_engine(dsn)
    try:
        with engine.connect() as connection:
            report = collect_and_validate(connection)
    except Exception as exc:  # infra failure, not schema drift — distinct exit code
        print(f"identity schema verification could not run: {exc}", file=sys.stderr)
        return EXIT_INFRA
    finally:
        engine.dispose()

    if report["unexpected_tables"]:
        # advisory only: never affects the exit code, but surface the drift
        print(f"warning: unexpected_tables={','.join(report['unexpected_tables'])}", file=sys.stderr)

    if report["ok"]:
        print(f"identity schema verified: revision={report['actual_revision']} rls_ok={len(TENANT_TABLES)} matview=m")
        return EXIT_OK

    print("identity schema verification failed", file=sys.stderr)
    print(
        f"expected_revision={report['expected_revision']} actual_revision={report['actual_revision']}",
        file=sys.stderr,
    )
    for key in ("missing_tables", "rls_gaps", "policy_gaps", "table_impostors"):
        if report[key]:
            print(f"{key}={','.join(report[key])}", file=sys.stderr)
    if report["matview_relkind"] != "m":
        print(f"matview_relkind={report['matview_relkind']}", file=sys.stderr)
    if report["exit_code"] == EXIT_HEAL_REPAIRABLE:
        print(
            "heal-repairable: re-run `python -m scripts.sync_identity_schema`",
            file=sys.stderr,
        )
    else:
        print(
            "operator action required: see docs/runbooks/prod-identity-rls-remediation.md",
            file=sys.stderr,
        )
    return report["exit_code"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
