"""Fail-closed boot verifier for the identity schema (E15-34 Slice 4).

Verifies the load-bearing invariant, not just names: every ``TENANT_TABLES``
member must have RLS enabled **and** forced with its ``tenant_isolation_*``
policy present, the centroid materialized view must actually be a matview
(``relkind='m'``) with the expected vector typmod, and every
``EXPECTED_SCHEMA_TABLES`` member must exist.

Exit codes distinguish who can fix the gap:

- ``0``  — schema verified.
- ``1``  — heal-repairable drift (missing table / RLS off / policy missing /
  matview absent / centroid typmod mismatch): re-running
  ``python -m scripts.sync_identity_schema`` converges it.
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
EMBEDDING_DIMENSION = identity_schema.EMBEDDING_DIMENSION
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
    column_gaps: dict[str, list[str]]
    non_additive_column_gaps: dict[str, list[str]]
    matview_relkind: str | None
    matview_centroid_typmod: int | None


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
    column_gaps: Mapping[str, Iterable[str]] | None = None,
    non_additive_column_gaps: Mapping[str, Iterable[str]] | None = None,
    matview_relkind: str | None = "m",
    matview_centroid_typmod: int | None = EMBEDDING_DIMENSION,
) -> SchemaStateReport:
    """Pure classification of collected schema facts.

    ``rls_state`` maps table -> (rowsecurity, forcerowsecurity); tables absent
    from the mapping count as RLS gaps. ``policy_names`` is the set of
    (tablename, policyname) pairs present. ``column_gaps`` maps an existing
    table to the ORM-declared columns absent from it (MAINT-TPR-01 / PA-03).
    ``non_additive_column_gaps`` is the subset of those columns ``heal()`` would
    *refuse* to add (a missing primary key, or a NOT NULL column with no server
    default) — heal RAISES on them, so they are operator-required, not
    heal-repairable (MAINT-TPR-BR-04). Passing ``None`` for any of these skips
    that check (unit-test / legacy callers); ``main()`` always collects them.
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

    # ORM-declared columns absent from an existing table (drift that leaves the
    # table + revision looking healthy while every SELECT of the column 500s).
    # Additive gaps are heal-repairable; non-additive gaps (missing PK, or NOT
    # NULL w/o server default) make heal RAISE, so they are operator-required.
    col_gaps: dict[str, list[str]] = {}
    if column_gaps is not None:
        for table_name, cols in column_gaps.items():
            missing_cols = sorted(cols)
            if missing_cols:
                col_gaps[table_name] = missing_cols

    na_col_gaps: dict[str, list[str]] = {}
    if non_additive_column_gaps is not None:
        for table_name, cols in non_additive_column_gaps.items():
            na_cols = sorted(cols)
            if na_cols:
                na_col_gaps[table_name] = na_cols

    matview_impostor = matview_relkind not in (None, "m")
    matview_missing = matview_relkind is None
    matview_centroid_typmod_gap = matview_relkind == "m" and matview_centroid_typmod != EMBEDDING_DIMENSION

    if not revision_matches or matview_impostor or table_impostors or na_col_gaps:
        exit_code = EXIT_OPERATOR_REQUIRED
    elif missing_tables or rls_gaps or policy_gaps or matview_missing or col_gaps or matview_centroid_typmod_gap:
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
        "column_gaps": col_gaps,
        "non_additive_column_gaps": na_col_gaps,
        "matview_relkind": matview_relkind,
        "matview_centroid_typmod": matview_centroid_typmod,
    }


def _expected_columns():
    """ORM ``Table`` objects per migration-owned table, from ``Base.metadata``.

    The live SELECTs are issued by the ORM, so the DB must carry every mapped
    column; importing ``db.models`` populates ``Base.metadata`` with each table.
    Returns the ``Table`` (not just names) so callers can read per-column
    nullability/server-default to decide additivity. Tables without an ORM model
    (raw-SQL refresh queue, matview) have no entry and are covered by the
    existence/relkind checks instead. A ratchet test asserts heal creates every
    ORM-declared column, guarding the ORM-vs-migration coupling (MAINT-TPR-BR-05).
    """
    import db.models  # noqa: F401 - import for metadata side effect
    from db.models.base_imports import Base

    expected_table_set = set(EXPECTED_TABLES)
    return {name: table for name, table in Base.metadata.tables.items() if name in expected_table_set}


def _collect_column_gaps(connection, expected) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(all missing columns, non-additive subset) per existing expected table.

    A wholly-absent table (no actual columns) is left to the ``missing_tables``
    check so a single drift is not double-reported. A missing column is
    non-additive — heal RAISES rather than adds it — when it is a primary key or
    NOT NULL with no server default (mirrors ``_ensure_columns``).
    """
    gaps: dict[str, list[str]] = {}
    non_additive: dict[str, list[str]] = {}
    for table_name, table in expected.items():
        actual = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = :t"
                ),
                {"t": table_name},
            )
        }
        if not actual:
            continue
        missing = [col for col in table.columns if col.name not in actual]
        if not missing:
            continue
        gaps[table_name] = sorted(col.name for col in missing)
        na = sorted(col.name for col in missing if col.primary_key or (not col.nullable and col.server_default is None))
        if na:
            non_additive[table_name] = na
    return gaps, non_additive


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
    matview_centroid_typmod = connection.execute(
        text(
            "SELECT a.atttypmod FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() "
            "AND c.relname = :name "
            "AND a.attname = 'centroid' AND NOT a.attisdropped"
        ),
        {"name": MATVIEW_NAME},
    ).scalar()

    column_gaps, non_additive_column_gaps = _collect_column_gaps(connection, _expected_columns())

    return _validate_schema_state(
        actual_tables=table_names,
        actual_revision=actual_revision,
        rls_state=rls_state,
        policy_names=policy_names,
        table_relkinds=table_relkinds,
        column_gaps=column_gaps,
        non_additive_column_gaps=non_additive_column_gaps,
        matview_relkind=matview_relkind,
        matview_centroid_typmod=matview_centroid_typmod,
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
        print(
            f"identity schema verified: revision={report['actual_revision']} "
            f"rls_ok={len(TENANT_TABLES)} matview=m centroid_typmod={report['matview_centroid_typmod']}"
        )
        return EXIT_OK

    print("identity schema verification failed", file=sys.stderr)
    print(
        f"expected_revision={report['expected_revision']} actual_revision={report['actual_revision']}",
        file=sys.stderr,
    )
    for key in ("missing_tables", "rls_gaps", "policy_gaps", "table_impostors"):
        if report[key]:
            print(f"{key}={','.join(report[key])}", file=sys.stderr)
    for table_name, cols in report["column_gaps"].items():
        na = report["non_additive_column_gaps"].get(table_name, [])
        suffix = f" (non-additive, operator-required: {','.join(na)})" if na else ""
        print(f"column_gaps: {table_name} missing {','.join(cols)}{suffix}", file=sys.stderr)
    if report["matview_relkind"] != "m":
        print(f"matview_relkind={report['matview_relkind']}", file=sys.stderr)
    if report["matview_relkind"] == "m" and report["matview_centroid_typmod"] != EMBEDDING_DIMENSION:
        print(
            f"matview_centroid_typmod={report['matview_centroid_typmod']} expected={EMBEDDING_DIMENSION}",
            file=sys.stderr,
        )
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
