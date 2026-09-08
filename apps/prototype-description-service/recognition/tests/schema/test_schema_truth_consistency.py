"""E15-34 Slice 1: truth-consistency ratchet between the three schema truths.

Truth A: migration DDL in ``db/migrations/versions/001_identity_schema.py``
(``TENANT_TABLES``, ``EXPECTED_SCHEMA_TABLES``, ``RAW_SQL_TABLES``).
Truth B: ORM ``Base.metadata``.
Truth C: the ``EXPECTED_SCHEMA_TABLES`` list the boot verifier consumes.

No database: pure set-relation assertions, so any new divergence fails CI
immediately. Known divergence is held in the explicit allowlists below; each
entry names the slice that removes it. Assertion (c) is anchored to real heal
coverage since Slice 3: ``heal()`` provably creates every
``EXPECTED_SCHEMA_TABLES`` member (PG test
``test_heal_from_empty_db_converges_to_full_schema_with_rls``), so membership
in that list IS the heal-creatable contract, no longer a proxy.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import pathlib
import re

import db.models  # noqa: F401  (registers every ORM table on Base.metadata)
from db.base import Base
from recognition.application.health import IDENTITY_VECTOR_COLUMNS as HEALTH_VECTOR_COLUMNS

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")

# Tenant-id-bearing ORM tables intentionally NOT under RLS, or not yet under
# RLS. Keys are table names; values are the rationale shown on failure.
RLS_EXEMPT_ALLOWLIST = {
    "api_keys": "pre-tenant-context lookup path; RLS would break key resolution (documented in E15-34 scope Not-Doing)",
    "demo_instances": "slug-lookup registry for demo router; cross-tenant by design (launch-plan §5 / DS-3)",
    "mv_identity_cluster_centroids": "materialized view; Postgres does not support RLS on matviews",
}

# ORM tables written by runtime code that the migration/verifier must own.
RUNTIME_WRITTEN_ORM_TABLES = {"assignment_decisions", "clustering_job_reports"}

# Runtime-written tables temporarily absent from EXPECTED_SCHEMA_TABLES.
# Slice 5 emptied this: runtime-written tables are all migration-owned now.
MIGRATION_GAP_ALLOWLIST: dict[str, str] = {}


def test_every_tenant_id_orm_table_is_rls_governed_or_allowlisted() -> None:
    # (a) tenant_id column => TENANT_TABLES membership or documented exemption.
    tenant_tables = set(MIGRATION.TENANT_TABLES)
    offenders = {
        name: "add to TENANT_TABLES or RLS_EXEMPT_ALLOWLIST with rationale"
        for name, table in Base.metadata.tables.items()
        if "tenant_id" in table.columns and name not in tenant_tables and name not in RLS_EXEMPT_ALLOWLIST
    }
    assert not offenders, f"tenant_id tables outside RLS governance: {offenders}"


def test_every_expected_table_is_orm_creatable_or_raw_sql() -> None:
    # (b) verifier contract ⊆ (ORM metadata ∪ migration raw-SQL tables), so a
    # heal built on either surface can always satisfy the verifier.
    orm_tables = set(Base.metadata.tables)
    raw_sql = set(MIGRATION.RAW_SQL_TABLES)
    missing = set(MIGRATION.EXPECTED_SCHEMA_TABLES) - orm_tables - raw_sql
    assert not missing, f"EXPECTED_SCHEMA_TABLES entries with no ORM model and not in RAW_SQL_TABLES: {sorted(missing)}"


def test_raw_sql_tables_have_no_orm_shadow() -> None:
    # RAW_SQL_TABLES exists precisely because these tables have no ORM model;
    # an ORM model appearing for one means the constant (or model) is stale.
    shadowed = set(MIGRATION.RAW_SQL_TABLES) & set(Base.metadata.tables)
    assert not shadowed, f"RAW_SQL_TABLES entries now shadowed by ORM models: {sorted(shadowed)}"


def test_runtime_written_tables_are_migration_owned_or_allowlisted() -> None:
    # (c) runtime-written ORM tables must be heal-creatable (EXPECTED
    # membership, anchored by the Slice-3 PG heal test) or in the shrinking
    # gap allowlist.
    expected = set(MIGRATION.EXPECTED_SCHEMA_TABLES)
    offenders = RUNTIME_WRITTEN_ORM_TABLES - expected - set(MIGRATION_GAP_ALLOWLIST)
    assert not offenders, (
        f"runtime-written tables with no migration ownership and no allowlist entry: {sorted(offenders)}"
    )


def test_runtime_written_tables_exist_in_orm() -> None:
    # Guard the ratchet's own input: the RUNTIME_WRITTEN_ORM_TABLES names must
    # stay real ORM tables, else assertion (c) silently checks nothing.
    missing = RUNTIME_WRITTEN_ORM_TABLES - set(Base.metadata.tables)
    assert not missing, f"RUNTIME_WRITTEN_ORM_TABLES entries not in Base.metadata: {sorted(missing)}"


# ORM tables intentionally absent from the verifier contract (with rationale).
EXPECTED_EXEMPT_ORM_TABLES = {
    "mv_identity_cluster_centroids": "materialized view: created by ensure_matview, not a table",
}


def test_every_orm_table_is_in_the_verifier_contract_or_exempt() -> None:
    # (d) ORM -> migration direction: a new ORM table missing from
    # EXPECTED_SCHEMA_TABLES (and so from heal/verify coverage) fails CI.
    expected = set(MIGRATION.EXPECTED_SCHEMA_TABLES)
    offenders = set(Base.metadata.tables) - expected - set(EXPECTED_EXEMPT_ORM_TABLES)
    assert not offenders, (
        f"ORM tables outside the verifier contract (add to EXPECTED_SCHEMA_TABLES "
        f"+ ensure_tables, or exempt with rationale): {sorted(offenders)}"
    )


def _load_verifier():
    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "verify_identity_schema.py"
    spec = importlib.util.spec_from_file_location("verify_identity_schema_truth", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identity_vector_column_contract_is_shared_across_heal_verify_health() -> None:
    # VLMHEAL-1-REV-A-08: ensure_matview's centroid probe, the verifier column
    # contract, and health.IDENTITY_VECTOR_COLUMNS must stay equal. Observation
    # that would refute the finding: any of the three drifts from the others.
    verifier = _load_verifier()
    assert tuple(MIGRATION.IDENTITY_VECTOR_COLUMNS) == tuple(HEALTH_VECTOR_COLUMNS)
    assert tuple(verifier.IDENTITY_VECTOR_COLUMNS) == tuple(HEALTH_VECTOR_COLUMNS)
    assert verifier.IDENTITY_VECTOR_COLUMNS is HEALTH_VECTOR_COLUMNS

    centroid_pair = ("mv_identity_cluster_centroids", "centroid")
    assert centroid_pair in HEALTH_VECTOR_COLUMNS
    probe_src = inspect.getsource(MIGRATION._matview_centroid_typmod)
    assert "mv_identity_cluster_centroids" in probe_src
    assert "centroid" in probe_src
    assert "typname" in probe_src
    assert "vector" in probe_src
    verifier_src = inspect.getsource(verifier._collect_vector_typmods)
    assert "IDENTITY_VECTOR_COLUMNS" in verifier_src


def test_tenant_and_raw_sql_tables_are_subsets_of_expected() -> None:
    # (e) internal consistency of the migration's own constants.
    expected = set(MIGRATION.EXPECTED_SCHEMA_TABLES)
    assert set(MIGRATION.TENANT_TABLES) <= expected, sorted(set(MIGRATION.TENANT_TABLES) - expected)
    assert set(MIGRATION.RAW_SQL_TABLES) <= expected, sorted(set(MIGRATION.RAW_SQL_TABLES) - expected)


_SQL_COMMENT = re.compile(r"--[^\n]*")
_CTE_NAME = re.compile(r"(?:WITH|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", re.IGNORECASE)
_FROM_JOIN_HEAD = re.compile(r"\b(?:FROM|JOIN)\b", re.IGNORECASE)
_FROM_JOIN_STOP = re.compile(r"\b(?:WHERE|JOIN|GROUP|ORDER|ON|UNION|LIMIT)\b|\)", re.IGNORECASE)
_RELATION_IDENT = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z_][A-Za-z0-9_]*)")
_FUNC_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_PREFLIGHT_TABLE = re.compile(
    r"has_table_privilege\(\s*current_user\s*,\s*'([A-Za-z_][A-Za-z0-9_]*)'",
    re.IGNORECASE,
)
_PREFLIGHT_FUNC = re.compile(r"p\.proname\s*=\s*'([A-Za-z_][A-Za-z0-9_]*)'", re.IGNORECASE)
_PY_COMMENT = re.compile(r"#[^\n]*")
_ADJACENT_STRINGS = re.compile(r'"([^"]*)"\s+"([^"]*)"')
_CREATE_MATVIEW_BODY = re.compile(r"CREATE MATERIALIZED VIEW.*?(?=\"\"\")", re.IGNORECASE | re.DOTALL)
_OPERATOR_FUNCS = {
    "<=>": "vector_cosine_distance",
    "<->": "l2_distance",
    "<#>": "vector_negative_inner_product",
}
# SQL keywords / builtins that appear as name( in the CREATE body but are not
# privilege-bearing catalog objects the preflight must GRANT EXECUTE on.
_SQL_NON_CATALOG_FUNCS = {
    "all",
    "and",
    "any",
    "array",
    "array_agg",
    "as",
    "asc",
    "avg",
    "between",
    "bool_and",
    "bool_or",
    "by",
    "case",
    "cast",
    "coalesce",
    "count",
    "create",
    "cross",
    "date_trunc",
    "desc",
    "distinct",
    "else",
    "end",
    "exists",
    "extract",
    "false",
    "from",
    "full",
    "greatest",
    "group",
    "having",
    "ilike",
    "in",
    "index",
    "inner",
    "into",
    "is",
    "join",
    "lateral",
    "least",
    "left",
    "length",
    "like",
    "lower",
    "materialized",
    "max",
    "min",
    "natural",
    "not",
    "now",
    "null",
    "nullif",
    "nulls",
    "on",
    "only",
    "or",
    "order",
    "outer",
    "over",
    "position",
    "rank",
    "right",
    "round",
    "row_number",
    "select",
    "set",
    "some",
    "substring",
    "sum",
    "table",
    "then",
    "trim",
    "true",
    "union",
    "unique",
    "upper",
    "using",
    "values",
    "vector",
    "view",
    "when",
    "where",
    "window",
    "with",
}


def _from_join_relations(sql: str) -> set[str]:
    names: set[str] = set()
    for head in _FROM_JOIN_HEAD.finditer(sql):
        rest = sql[head.end() :]
        stop = _FROM_JOIN_STOP.search(rest)
        clause = rest[: stop.start()] if stop else rest
        for item in clause.split(","):
            ident = _RELATION_IDENT.search(item)
            if ident:
                names.add(ident.group(1).lower())
    return names


def _body_funcs(sql: str) -> set[str]:
    names = {name.lower() for name in _FUNC_CALL.findall(sql) if name.lower() not in _SQL_NON_CATALOG_FUNCS}
    names |= {func for operator, func in _OPERATOR_FUNCS.items() if operator in sql}
    return names


def _comment_stripped_preflight_src(src: str) -> str:
    stripped = _PY_COMMENT.sub("", src)
    while True:
        joined, n = _ADJACENT_STRINGS.subn(r'"\1\2"', stripped)
        if n == 0:
            return joined
        stripped = joined


def _matview_create_sql(src: str | None = None) -> str:
    text = inspect.getsource(MIGRATION.ensure_matview) if src is None else src
    return "\n".join(_SQL_COMMENT.sub("", match.group(0)) for match in _CREATE_MATVIEW_BODY.finditer(text))


def test_from_join_captures_comma_joined_relations_and_operator_funcs() -> None:
    body = "SELECT 1 FROM a, b JOIN c ON a.id = c.id WHERE a.v <=> b.v"
    assert _from_join_relations(body) == {"a", "b", "c"}
    assert _body_funcs(body) == {"vector_cosine_distance"}
    assert _from_join_relations("SELECT 1 FROM public.identity_members im") == {"identity_members"}


def test_matview_create_sql_joins_every_create_body() -> None:
    src = '''
    op.execute("""
        CREATE MATERIALIZED VIEW first_view AS SELECT 1
        """)
    op.execute("""
        CREATE MATERIALIZED VIEW second_view AS SELECT 2
        """)
    '''
    joined = _matview_create_sql(src)
    assert "CREATE MATERIALIZED VIEW first_view" in joined
    assert "CREATE MATERIALIZED VIEW second_view" in joined


def test_matview_create_privilege_gaps_match_create_body_relations_and_functions() -> None:
    # C-01: _matview_create_privilege_gaps is a curated list far from the CREATE
    # MATERIALIZED VIEW body it must mirror. Observation that would refute the
    # finding: FROM/JOIN relations and non-builtin function calls in the CREATE
    # body equal the has_table_privilege / proname probes in the preflight.
    create_sql = _matview_create_sql()
    cte_names = {name.lower() for name in _CTE_NAME.findall(create_sql)}
    create_relations = _from_join_relations(create_sql) - cte_names
    body_funcs = _body_funcs(create_sql)

    preflight_src = _comment_stripped_preflight_src(inspect.getsource(MIGRATION._matview_create_privilege_gaps))
    preflight_tables = {name.lower() for name in _PREFLIGHT_TABLE.findall(preflight_src)}
    preflight_functions = {name.lower() for name in _PREFLIGHT_FUNC.findall(preflight_src)}

    assert create_relations, "parser found no FROM/JOIN tables in the CREATE MATERIALIZED VIEW body"
    assert body_funcs, "parser found no catalog functions in the CREATE MATERIALIZED VIEW body"
    assert preflight_tables, (
        "_comment_stripped_preflight_src produced no has_table_privilege tables from "
        "_matview_create_privilege_gaps; a string reflow likely split a probe"
    )
    assert create_relations == preflight_tables, (
        "CREATE MATERIALIZED VIEW FROM/JOIN tables must equal _matview_create_privilege_gaps "
        f"has_table_privilege probes: create={sorted(create_relations)} "
        f"preflight={sorted(preflight_tables)}"
    )
    assert body_funcs == preflight_functions, (
        "extend _SQL_NON_CATALOG_FUNCS only for pg_catalog builtins; user functions need a preflight probe"
        f": create={sorted(body_funcs)} preflight={sorted(preflight_functions)}"
    )


def test_verifier_reuses_migration_matview_create_privilege_gaps() -> None:
    # Duplicate SQL in verify vs heal makes collect_and_validate return
    # EXIT_HEAL_REPAIRABLE while heal() raises — docker-entrypoint crash-loop.
    verifier = _load_verifier()
    src = inspect.getsource(verifier._collect_matview_create_privilege_gaps)
    assert "_matview_create_privilege_gaps" in src
    assert "has_table_privilege" not in src
    assert verifier._collect_matview_create_privilege_gaps.__doc__
