"""G4 restricted-PostgreSQL findings: offline causal tests for ``scripts/collect_gpu_pg_evidence.py``.

Owner: GTMC c79 G4 source-fix lane. Adjudicated corrections to the c76 findings module. The 14 superseded-ABI selectors in
``scripts/tests/test_gtmr_gpu_pg_collector.py`` are test-shape failures, not production defects, and
are not counted here.

Boundaries
----------
* Offline only. The injected ``connect`` returns an in-memory fake session that answers the
  collector's exact SQL constants and nothing else. The fake models RLS policy semantics for the
  expression shapes it recognises and fails closed on anything it does not recognise. No database
  driver is imported, no DSN is read, no database is touched. An autouse guard denies socket
  connects so accidental network use fails the test.
* Six causal RED groups (D1-D6). Each RED fails on the current tree for one named source defect.
  Each group has positive controls that pass on the current tree and pin the boundary a fix must
  keep.
* Produced facts (observation data) are asserted separately from the policy verdict (status and
  issue codes).
* Canon v0.25.6 rule IDs at use: RES-02 (bound every blocking call), EMB-01 (one embedding space per
  comparison), EMB-05 (pinned embedding/mapping versions), PROV-01 (observed input and model
  lineage), GRPH-32 (an edge exists only where a named field is joined), WEB-16 (no plaintext
  secrets in artifacts), TEST-15 (causal controls that prove the test can go red).
  Source: https://github.com/darce/heuristics-canon
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import re
import socket
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
COLLECTOR_PATH = REPO_ROOT / "scripts" / "collect_gpu_pg_evidence.py"


def _load_collector() -> ModuleType:
    assert COLLECTOR_PATH.is_file(), f"collector missing at {COLLECTOR_PATH}"
    spec = importlib.util.spec_from_file_location("gtmc_pg_findings_collector", COLLECTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COL = _load_collector()
PRIMARY = COL.PRIMARY_SESSION
INDEPENDENT = COL.INDEPENDENT_SESSION
CONNECT_KWARGS = frozenset(
    {"session_label", "dsn_ref", "connect_timeout_s", "statement_timeout_ms", "lock_timeout_ms", "overall_deadline_s"}
)

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
RUN_OWN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RUN_FOREIGN = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OP_OWN = "op-own-0001"
OP_FOREIGN = "op-foreign-0001"
DATABASE = "fixture_identity"
ROLE = "restricted_reader"
SCHEMA = "public"
EXT_VERSION = "0.8.0"
MODEL = "fixture-embed-model-v1"
OTHER_MODEL = "fixture-embed-model-v2"
DIMENSION = 768
GENERATION = 3
DIGEST_OWN = "a" * 64
DIGEST_FOREIGN = "b" * 64
CAPTION_101 = "caption for media 101"
DSN_REF = "gpu-pg-restricted-reader-ref"
FIXTURE_SECRET = "FIXTURE-DUMMY-SECRET"
NATIVE_TENANT_QUAL = (
    "((tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid) "
    "OR (COALESCE(NULLIF(current_setting('app.bypass_rls'::text, true), ''::text), 'false'::text)::boolean))"
)
BASE_SELECTION: dict[str, Any] = {
    "environment": "fixture-env",
    "expected_database": DATABASE,
    "expected_role": ROLE,
    "expected_schema": SCHEMA,
    "tenant_id": TENANT_A,
    "run_id": RUN_OWN,
    "foreign_run_id": RUN_FOREIGN,
    "media_ids": [101, 102],
    "result_generation": GENERATION,
    "expected_model_id": MODEL,
    "expected_vector_dimension": DIMENSION,
    "dsn_ref": DSN_REF,
    "operation_id": OP_OWN,
    "foreign_operation_id": OP_FOREIGN,
}
UNSAFE_IDENTITY_VARIANTS: dict[str, dict[str, dict[str, Any]]] = {
    "independent-foreign-schema": {INDEPENDENT: {"schema": "foreign_schema"}},
    "primary-session-user": {PRIMARY: {"session_user": "login_other"}},
    "primary-superuser": {PRIMARY: {"rolsuper": True}},
    "primary-bypassrls-role": {PRIMARY: {"rolbypassrls": True}},
    "independent-foreign-database": {INDEPENDENT: {"database": "foreign_fixture_db"}},
    "independent-foreign-current-user": {INDEPENDENT: {"role": "foreign_reader"}},
    "primary-read-write-transaction": {PRIMARY: {"honour_read_only": False}},
    "primary-app-bypass-rls-on": {PRIMARY: {"bypass": True}},
}
KEYWORD_DSN_REFS = (
    "host=192.0.2.10 dbname=fixture_identity user=restricted_reader",
    "dbname=fixture_identity user=restricted_reader sslmode=require",
    "hostaddr=192.0.2.10 port=5432 dbname=fixture_identity",
)
TENANT_DATA_SQL = frozenset({COL.DEMAND_SQL, COL.OUTPUT_SQL, COL.EMBEDDING_SQL, COL.RUN_SQL})
_SET_TENANT_PREFIX = re.compile(r"SET LOCAL app\.current_tenant\b")
_SET_TENANT_VALUE = re.compile(
    r"SET LOCAL app\.current_tenant = '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'"
)
_WRITE_STMT = re.compile(r"\s*(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|GRANT|TRUNCATE|COMMIT)\b", re.IGNORECASE)
_SESSION_STMT = re.compile(r"\s*(SET|RESET)\b", re.IGNORECASE)
_SELECT_STMT = re.compile(r"\s*SELECT\b", re.IGNORECASE)


# --------------------------------------------------------------------------------------------
# In-memory fake: answers the collector's exact SQL constants. Not PostgreSQL.
# --------------------------------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0


class FakeDeadline:
    """The only time source the collector may read: ``remaining_seconds()``."""

    def __init__(self, clock: FakeClock, budget_s: float) -> None:
        self._clock = clock
        self._budget = budget_s

    def remaining_seconds(self) -> float:
        return self._budget - self._clock.now


class FakeSqlError(Exception):
    def __init__(self, message: str, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _policy(name: str, qual: str, roles: tuple[str, ...] = ("public",), cmd: str = "ALL") -> dict[str, Any]:
    return {
        "name": name,
        "cmd": cmd,
        "roles": list(roles),
        "permissive": "PERMISSIVE",
        "qual": qual,
        "with_check": qual,
    }


def _item(tenant: str, run_id: str, media_id: int, caption: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant,
        "run_id": run_id,
        "media_id": media_id,
        "status": "completed",
        "tier": "final_gpu",
        "result_generation": GENERATION,
        "reported_model_id": MODEL,
        "caption": caption,
    }


def _default_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        "describe_operations": [
            {"tenant_id": TENANT_A, "operation_id": OP_OWN, "request_digest": DIGEST_OWN},
            {"tenant_id": TENANT_B, "operation_id": OP_FOREIGN, "request_digest": DIGEST_FOREIGN},
        ],
        "image_description_runs": [
            {"tenant_id": TENANT_A, "run_id": RUN_OWN, "operation_id": OP_OWN},
            {"tenant_id": TENANT_B, "run_id": RUN_FOREIGN, "operation_id": OP_FOREIGN},
        ],
        "image_description_run_items": [
            _item(TENANT_A, RUN_OWN, 101, CAPTION_101),
            _item(TENANT_A, RUN_OWN, 102, "caption for media 102"),
            _item(TENANT_B, RUN_FOREIGN, 201, "foreign caption for media 201"),
        ],
        "media_identities": [
            {"tenant_id": TENANT_A, "media_id": 101, "embedding_model": MODEL},
            {"tenant_id": TENANT_A, "media_id": 102, "embedding_model": MODEL},
            {"tenant_id": TENANT_B, "media_id": 201, "embedding_model": MODEL},
        ],
    }


def _view_key(table: str, row: dict[str, Any]) -> Any:
    if table == "image_description_run_items":
        return (row["run_id"], row["media_id"])
    if table == "describe_operations":
        return row["operation_id"]
    return None


def _qual_true(qual: str, row_tenant: str, session_tenant: str | None, bypass: bool) -> bool:
    if qual == "true":
        return True
    canonical = NATIVE_TENANT_QUAL.replace(
        "NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid",
        "(NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid",
    )
    if qual in (NATIVE_TENANT_QUAL, canonical):
        return (session_tenant is not None and row_tenant == session_tenant) or bypass
    return False  # unrecognised policy semantics fail closed in the fake


def _sql_predicate(expression: str, values: dict[str, Any]) -> bool:
    """Small semantic evaluator for catalog join predicates; unknown syntax is a fixture error.

    AND binds before OR. Equalities, IN, parentheses and regclass casts suffice for
    the catalog contract and equivalent rewrites. No SQL is executed.
    """
    tokens = re.findall(r"'[^']*'|::|[a-z_][a-z_0-9.]*|[=(),]", expression.lower())
    at = 0
    def operand():
        nonlocal at
        token = tokens[at]
        at += 1
        value = token[1:-1] if token.startswith("'") else values.get(token, token == "true")
        if at < len(tokens) and tokens[at] == "::":
            at += 2
        return value
    def atom():
        nonlocal at
        if tokens[at] == "(":
            at += 1
            result = disjunction()
            assert tokens[at] == ")"
            at += 1
            return result
        left = operand()
        if at < len(tokens) and tokens[at] == "=":
            at += 1
            return left == operand()
        if at < len(tokens) and tokens[at] == "in":
            at += 1
            assert tokens[at] == "("
            at += 1
            choices = [operand()]
            while tokens[at] == ",":
                at += 1
                choices.append(operand())
            assert tokens[at] == ")"
            at += 1
            return left in choices
        return left is True
    def conjunction():
        nonlocal at
        result = atom()
        while at < len(tokens) and tokens[at] == "and":
            at += 1
            other = atom()
            result = result and other
        return result
    def disjunction():
        nonlocal at
        result = conjunction()
        while at < len(tokens) and tokens[at] == "or":
            at += 1
            other = conjunction()
            result = result or other
        return result
    result = disjunction()
    assert at == len(tokens), (expression, tokens[at:])
    return result


def _catalog_join_matches(sql: str, row: tuple, type_oid: int) -> bool:
    values = {"d.objid": row[3], "a.atttypid": type_oid, "t.oid": type_oid,
              "d.deptype": row[4], "d.classid": row[5], "d.refclassid": row[6],
              "d.refobjid": 42, "e.oid": 42, "e.extname": row[2]}
    joins = re.findall(r"JOIN\s+(pg_depend|pg_extension)\s+\w+\s+ON\s+(.*?)(?=\s+JOIN|\s+WHERE|$)",
                       sql, re.I)
    return all(_sql_predicate(predicate, values) for _, predicate in joins)


class FakeCluster:
    def __init__(self, *, budget_s: float = 600.0) -> None:
        self.clock = FakeClock()
        self.deadline = FakeDeadline(self.clock, budget_s)
        self.database = DATABASE
        self.role = ROLE
        self.schema = SCHEMA
        self.extension_installed = True
        self.extension_version = EXT_VERSION
        self.overrides: dict[str, dict[str, Any]] = {}
        self.session_views: defaultdict[str, dict[tuple[str, Any], dict[str, Any]]] = defaultdict(dict)
        self.rows = _default_rows()
        self.policies: dict[str, list[dict[str, Any]]] = {
            table: [_policy(f"tenant_isolation_{table}", NATIVE_TENANT_QUAL)] for table in COL.RLS_TABLES
        }
        self.vector_typmods: dict[tuple[str, str], int] = dict.fromkeys(COL.VECTOR_COLUMNS, DIMENSION)
        self.indexes = [(t, c, "ivfflat", "vector_cosine_ops", True, None, None) for t, c in COL.VECTOR_COLUMNS]
        self.extension_types = [(SCHEMA, "vector", "vector", 9001, "e", "pg_type", "pg_extension")]
        self.vector_type_oids = dict.fromkeys(COL.VECTOR_COLUMNS, 9001)
        self.role_usage: dict[str, bool] = {ROLE: True, "reader_group": False}
        self.abort_on_error = False
        self.cost_hook = lambda label, sql, params: 0.0
        self.fail_on: dict[str, str] = {}
        self.output_rows_total: int | None = None
        self.pull_counters: list[list[int]] = []
        self.connect_calls: list[dict[str, Any]] = []
        self.sessions: list[FakeSession] = []

    def identity_for(self, label: str) -> dict[str, Any]:
        pid = {PRIMARY: 4101, INDEPENDENT: 4102}.get(label, 4199)
        base: dict[str, Any] = {
            "database": self.database,
            "role": self.role,
            "session_user": self.role,
            "schema": self.schema,
            "rolsuper": False,
            "rolbypassrls": False,
            "honour_read_only": True,
            "bypass": False,
            "pid": pid,
            "start": f"2026-10-13T00:00:0{pid % 10}Z",
        }
        base.update(self.overrides.get(label, {}))
        return base

    def view(self, label: str, table: str, row: dict[str, Any]) -> dict[str, Any]:
        key = _view_key(table, row)
        return self.session_views[label].get((table, key), {})


def _counting_rows(cluster: FakeCluster, total: int):
    counter = [0]
    cluster.pull_counters.append(counter)
    for i in range(total):
        counter[0] += 1
        yield (RUN_OWN, 100000 + i, "completed", "final_gpu", GENERATION, MODEL, "f" * 64)


class FakeSession:
    """Exposes exactly ``query(sql, params)`` and ``close()``, the collector's session contract."""

    def __init__(self, cluster: FakeCluster, label: str) -> None:
        self._cluster = cluster
        self.label = label
        self.identity = cluster.identity_for(label)
        self.log: list[str] = []
        self.began = False
        self.aborted = False
        self.read_only = False
        self.tenant: str | None = None
        self.closed = False

    def _visible(self, table: str) -> list[dict[str, Any]]:
        out = []
        for row in self._cluster.rows[table]:
            merged = {**row, **self._cluster.view(self.label, table, row)}
            if self._allowed(table, merged["tenant_id"]):
                out.append(merged)
        return out

    def _allowed(self, table: str, row_tenant: str) -> bool:
        permissive = []
        restrictive = []
        for pol in self._cluster.policies.get(table, []):
            if pol["cmd"] not in ("ALL", "SELECT"):
                continue
            if pol["roles"] is None or not any(
                role == "public" or self._cluster.role_usage.get(role) is True for role in pol["roles"]
            ):
                continue
            if pol["permissive"] not in ("PERMISSIVE", "RESTRICTIVE"):
                return False  # unknown applicability semantics fail closed
            allowed = _qual_true(pol["qual"], row_tenant, self.tenant, bool(self.identity["bypass"]))
            (permissive if pol["permissive"] == "PERMISSIVE" else restrictive).append(allowed)
        return any(permissive) and all(restrictive)

    def query(self, sql: str, params: Any) -> list[tuple[Any, ...]]:
        cl = self._cluster
        params = dict(params or {})
        self.log.append(sql)
        cl.clock.now += float(cl.cost_hook(self.label, sql, params))
        if self.aborted and sql != "ROLLBACK":
            raise FakeSqlError("transaction aborted", "25P02")
        if sql in cl.fail_on:
            self.aborted = cl.abort_on_error and self.began
            raise FakeSqlError("fixture-induced statement failure", cl.fail_on[sql])
        if sql in ("BEGIN READ ONLY", "START TRANSACTION READ ONLY"):
            self.began = True
            self.read_only = bool(self.identity["honour_read_only"])
            return []
        if sql == "ROLLBACK":
            self.began = False
            self.aborted = False
            self.read_only = False
            self.tenant = None
            return []
        tenant_set = _SET_TENANT_VALUE.fullmatch(sql)
        if tenant_set is not None:
            self.tenant = tenant_set.group(1)
            return []
        if re.fullmatch(r"SET LOCAL (statement_timeout|lock_timeout|idle_in_transaction_session_timeout) = .+", sql):
            return []
        if _SET_TENANT_PREFIX.match(sql) or _SESSION_STMT.match(sql):
            raise FakeSqlError("session setting refused by the fixture contract")
        if _WRITE_STMT.match(sql):
            raise FakeSqlError("write refused in a restricted session", "25006")
        ident = self.identity
        timeout_set = re.fullmatch(r"SELECT set_config\('statement_timeout', '([0-9]+)', true\)", sql)
        if timeout_set:
            return [(timeout_set.group(1),)]
        if sql == "SELECT current_setting('app.bypass_rls', true)":
            return (
                [(ident.get("raw_bypass", "on" if ident["bypass"] else None),)]
                if not ident.get("bypass_missing")
                else []
            )
        if sql == "SELECT current_setting('app.current_tenant', true)":
            return [] if ident.get("claim_missing") else [(ident.get("claim", self.tenant),)]
        if "FROM image_description_runs r" in sql:
            return [
                (r["run_id"], r["tenant_id"], r["operation_id"])
                for r in self._visible("image_description_runs")
                if r["run_id"] == params.get("run_id")
            ]
        if "FROM pg_index" in sql:
            # Model the selected validity value, so replacing the measured field with true is visible.
            projection = sql.split("FROM", 1)[0].lower()
            preserves_expression_keys = bool(re.search(r"LEFT\s+JOIN\s+pg_attribute\b", sql, re.I))
            return [(*row[:4], row[4] if "i.indisvalid" in projection else True, *row[5:])
                    for row in cl.indexes if row[1] is not None or preserves_expression_keys]
        if "FROM pg_type" in sql and "pg_depend" in sql:
            return [row[:3] for row in cl.extension_types if _catalog_join_matches(sql, row, row[3])]
        if sql == COL.IDENTITY_SQL:
            return [
                (
                    ident["database"],
                    ident["role"],
                    ident["session_user"],
                    ident["pid"],
                    "16.4",
                    ident["start"],
                    ident["schema"],
                )
            ]
        if sql == COL.TXN_READ_ONLY_SQL:
            return [("on" if self.read_only else "off",)]
        if sql == COL.ROLE_SQL:
            return [(bool(ident["rolsuper"]), bool(ident["rolbypassrls"]))]
        if sql == COL.ROLE_MEMBERSHIP_SQL:
            probe = re.search(r"pg_has_role\s*\(\s*current_user\s*,\s*r.oid\s*,\s*'([^']+)'\s*\)", sql, re.I)
            assert probe, "unsupported membership expression"
            usage = cl.role_usage if probe[1].upper() == "USAGE" else {ROLE: True, "reader_group": False}
            names = set(usage)
            if re.search(r"WHERE\s+r.rolname\s+IN", sql, re.I):
                names &= {r for t in params["tables"] for p in cl.policies[t] for r in p["roles"] or []}
            return [(role, usage[role]) for role in usage if role in names]
        if sql == COL.EXTENSION_SQL:
            return [("vector", cl.extension_version)] if cl.extension_installed else []
        if sql == COL.VECTOR_SQL:
            # Evaluate the selected width, including literal substitutions, rather
            # than returning the stored width regardless of the SQL projection.
            typmod_projection = sql.split("FROM", 1)[0].rsplit(",", 1)[1].strip()
            assert typmod_projection == "a.atttypmod" or re.fullmatch(r"[0-9]+", typmod_projection), (
                "unsupported vector typmod projection", typmod_projection
            )
            return [
                (ident["schema"], t, c, "vector",
                 m if typmod_projection == "a.atttypmod" else int(typmod_projection))
                for (t, c), m in cl.vector_typmods.items()
                if any(_catalog_join_matches(sql, row, cl.vector_type_oids[t, c]) for row in cl.extension_types)
            ]
        if sql == COL.RLS_SQL:
            return [(t, True, True) for t in params.get("tables", []) if t in cl.policies]
        if sql == COL.POLICY_SQL:
            return [
                (t, p["name"], p["cmd"], p["roles"], p["permissive"], p["qual"], p["with_check"])
                for t in params.get("tables", [])
                for p in cl.policies.get(t, [])
            ]
        if sql == COL.EMBEDDING_SQL:
            return [(m,) for m in sorted({row["embedding_model"] for row in self._visible("media_identities")})]
        if sql == COL.DEMAND_SQL:
            return [
                (row["operation_id"], row["request_digest"])
                for row in self._visible("describe_operations")
                if row["operation_id"] == params.get("operation_id")
            ]
        if sql == COL.OUTPUT_SQL:
            if cl.output_rows_total is not None and params.get("run_id") == RUN_OWN:
                return _counting_rows(cl, cl.output_rows_total)
            return [
                (
                    row["run_id"],
                    row["media_id"],
                    row["status"],
                    row["tier"],
                    row["result_generation"],
                    row["reported_model_id"],
                    _sha(row["caption"]),
                )
                for row in self._visible("image_description_run_items")
                if row["run_id"] == params.get("run_id")
            ]
        if _SELECT_STMT.match(sql):
            return []  # unrecognised read-only probes: zero rows, never tenant data
        raise FakeSqlError("statement outside the fixture contract")

    def close(self) -> None:
        self.closed = True


def _connect_for(cluster: FakeCluster):
    def connect(
        *,
        session_label: str,
        dsn_ref: str,
        connect_timeout_s: float,
        statement_timeout_ms: int,
        lock_timeout_ms: int,
        overall_deadline_s: float,
    ) -> FakeSession:
        cluster.connect_calls.append(
            {
                "session_label": session_label,
                "dsn_ref": dsn_ref,
                "connect_timeout_s": connect_timeout_s,
                "statement_timeout_ms": statement_timeout_ms,
                "lock_timeout_ms": lock_timeout_ms,
                "overall_deadline_s": overall_deadline_s,
            }
        )
        session = FakeSession(cluster, session_label)
        cluster.sessions.append(session)
        return session

    return connect


def _run(cluster: FakeCluster, selection: dict[str, Any] | None = None) -> dict[str, Any]:
    sel = copy.deepcopy(BASE_SELECTION) if selection is None else selection
    result = COL.collect_pg_evidence(connect=_connect_for(cluster), selection=sel, deadline=cluster.deadline)
    _assert_abi_envelope(result)
    return result


def _selection(**overrides: Any) -> dict[str, Any]:
    sel = copy.deepcopy(BASE_SELECTION)
    sel.update(overrides)
    return sel


# --------------------------------------------------------------------------------------------
# Result accessors. Facts and verdicts are read through separate helpers on purpose.
# --------------------------------------------------------------------------------------------


def _facts(result: dict[str, Any]) -> dict[str, Any]:
    return {obs["observation_id"]: obs["data"] for obs in result["section"]["observations"]}


def _catalog(result: dict[str, Any]) -> dict[str, Any]:
    return _facts(result)["pg:catalog:primary"]


def _verdict(result: dict[str, Any]) -> dict[str, Any]:
    section = result["section"]
    return {
        "status": section["status"],
        "missing": sorted({i["code"] for i in section["missing_reasons"]}),
        "contradictions": sorted({i["code"] for i in section["contradictions"]}),
    }


def _issues(result: dict[str, Any]) -> list[dict[str, Any]]:
    return list(result["section"]["missing_reasons"]) + list(result["section"]["contradictions"])


def _issue_keys(result: dict[str, Any]) -> set[tuple[str, str, str]]:
    section = result["section"]
    return {("missing", i["code"], i["field"]) for i in section["missing_reasons"]} | {
        ("contradiction", i["code"], i["field"]) for i in section["contradictions"]
    }


def _missing_codes(result: dict[str, Any]) -> set[str]:
    return {i["code"] for i in result["section"]["missing_reasons"]}


def _contra_codes(result: dict[str, Any]) -> set[str]:
    return {i["code"] for i in result["section"]["contradictions"]}


def _all_codes(result: dict[str, Any]) -> set[str]:
    return _missing_codes(result) | _contra_codes(result)


def _fields_under(result: dict[str, Any], bucket: str, prefix: str) -> list[str]:
    return [i["field"] for i in result["section"][bucket] if i["field"].startswith(prefix)]


def _bytes_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    raise TypeError(f"not serialisable: {type(value).__name__}")


def _blob(result: dict[str, Any]) -> str:
    return json.dumps(result, default=_bytes_text, sort_keys=True)


def _session(cluster: FakeCluster, label: str) -> FakeSession:
    return next(s for s in cluster.sessions if s.label == label)


def _is_tenant_data(sql: str) -> bool:
    return sql in TENANT_DATA_SQL or _SET_TENANT_PREFIX.match(sql) is not None


def _tenant_statements(cluster: FakeCluster) -> list[str]:
    return [sql for session in cluster.sessions for sql in session.log if _is_tenant_data(sql)]


def _connect_direct(cluster: FakeCluster, label: str) -> FakeSession:
    return _connect_for(cluster)(
        session_label=label,
        dsn_ref=DSN_REF,
        connect_timeout_s=1.0,
        statement_timeout_ms=1000,
        lock_timeout_ms=1000,
        overall_deadline_s=1.0,
    )


def _policy_issue_fields(result: dict[str, Any], table: str) -> list[str]:
    return _fields_under(result, "missing_reasons", f"catalog.rls.{table}.") + _fields_under(
        result, "contradictions", f"catalog.rls.{table}."
    )


# --------------------------------------------------------------------------------------------
# Offline guard and fake controls. These must pass on the current tree.
# --------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _deny_actual_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("actual network connect denied in offline findings tests")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def test_offline_guard_denies_socket_connect() -> None:
    with pytest.raises(AssertionError, match="denied"):
        socket.create_connection(("192.0.2.1", 5432), timeout=0.01)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO media_identities (tenant_id, media_id) VALUES ('x', 1)",
        "DELETE FROM describe_operations",
        "SET app.bypass_rls = 'on'",
        "SET LOCAL app.bypass_rls = 'on'",
        "SET ROLE postgres",
        "RESET app.current_tenant",
    ],
)
def test_fake_refuses_writes_bypass_and_role_changes(sql: str) -> None:
    cluster = FakeCluster()
    session = _connect_direct(cluster, PRIMARY)
    session.query("BEGIN READ ONLY", {})
    with pytest.raises(FakeSqlError):
        session.query(sql, {})


def test_fake_rls_is_default_deny_until_tenant_is_set_then_scopes_to_that_tenant() -> None:
    cluster = FakeCluster()
    session = _connect_direct(cluster, PRIMARY)
    session.query("BEGIN READ ONLY", {})
    assert session.query(COL.OUTPUT_SQL, {"run_id": RUN_OWN}) == []
    session.query(f"SET LOCAL app.current_tenant = '{TENANT_A}'", {})
    assert len(session.query(COL.OUTPUT_SQL, {"run_id": RUN_OWN})) == 2
    assert session.query(COL.OUTPUT_SQL, {"run_id": RUN_FOREIGN}) == []


def test_fake_bypass_session_sees_foreign_rows_so_bypass_is_observable_in_the_fixture() -> None:
    cluster = FakeCluster()
    cluster.overrides = {PRIMARY: {"bypass": True}}
    session = _connect_direct(cluster, PRIMARY)
    session.query("BEGIN READ ONLY", {})
    session.query(f"SET LOCAL app.current_tenant = '{TENANT_A}'", {})
    assert len(session.query(COL.OUTPUT_SQL, {"run_id": RUN_FOREIGN})) == 1


def test_collector_entry_point_has_exact_keyword_only_signature() -> None:
    params = inspect.signature(COL.collect_pg_evidence).parameters
    assert list(params) == ["connect", "selection", "deadline"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())


def test_collector_imports_no_database_driver_or_tenant_helper() -> None:
    tree = ast.parse(COLLECTOR_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    denied = {
        "psycopg",
        "asyncpg",
        "pg8000",
        "sqlalchemy",
        "sqlite3",
        "aiosqlite",
        "socket",
        "ssl",
        "http",
        "urllib",
        "requests",
        "db",
    }
    assert not {
        m
        for m in modules
        if m.split(".")[0] in denied or m.startswith(("psycopg", "http", "urllib")) or "tenant_context" in m
    }


def test_collector_drives_sessions_only_through_query_and_close() -> None:
    tree = ast.parse(COLLECTOR_PATH.read_text(encoding="utf-8"))
    called = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {"cursor", "execute", "executemany"}


def test_collector_connect_receives_exactly_the_frozen_keyword_set() -> None:
    cluster = FakeCluster()
    _run(cluster)
    assert cluster.connect_calls, "collector never connected in the positive fixture"
    for call in cluster.connect_calls:
        assert set(call) == CONNECT_KWARGS


def test_collector_never_sets_or_resets_bypass_or_role_in_positive_capture() -> None:
    cluster = FakeCluster()
    _run(cluster)
    for session in cluster.sessions:
        for sql in session.log:
            if re.match(r"\s*(SET|RESET)\b", sql, re.IGNORECASE):
                assert sql.startswith("SET LOCAL "), sql
                assert not re.search(r"bypass_rls|\bROLE\b|SESSION AUTHORIZATION|search_path", sql, re.I), sql


# --------------------------------------------------------------------------------------------
# D1 / P1: an unsafe or foreign session identity must be refused BEFORE any tenant-scoped read.
# Current defect: role, database, read-only and bypass facts are adjudicated only after the
# tenant SET and every data SELECT have already run on both sessions.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("variant", sorted(UNSAFE_IDENTITY_VARIANTS))
def test_d1_unsafe_session_identity_is_refused_before_any_tenant_read(variant: str) -> None:
    cluster = FakeCluster()
    cluster.overrides = copy.deepcopy(UNSAFE_IDENTITY_VARIANTS[variant])
    result = _run(cluster)
    leaked = _tenant_statements(cluster)
    assert leaked == [], f"{variant}: tenant-scoped statements ran after the unsafe identity was observable: {leaked}"
    assert _verdict(result)["status"] == "contradicted", variant


def test_d1_safe_identity_reaches_tenant_reads_on_both_sessions() -> None:
    cluster = FakeCluster()
    result = _run(cluster)
    for label in (PRIMARY, INDEPENDENT):
        assert any(_is_tenant_data(sql) for sql in _session(cluster, label).log), label
    assert _verdict(result)["status"] != "contradicted"


def test_d1_shared_backend_is_refused_before_any_tenant_read() -> None:
    cluster = FakeCluster()
    cluster.overrides = {INDEPENDENT: {"pid": 4101}}
    result = _run(cluster)
    assert _tenant_statements(cluster) == []
    assert COL.SESSION_NOT_INDEPENDENT in _missing_codes(result)


# --------------------------------------------------------------------------------------------
# D2 / P1: a policy name cannot stand in for its predicate. Current defect: only the name
# tenant_isolation_<table> is checked; USING(true) under the right name is accepted.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("table", COL.RLS_TABLES)
def test_d2_permissive_true_policy_under_native_name_is_a_catalog_contradiction(table: str) -> None:
    cluster = FakeCluster()
    cluster.policies[table] = [_policy(f"tenant_isolation_{table}", "true")]
    result = _run(cluster)
    assert _verdict(result)["status"] == "contradicted"
    assert _fields_under(result, "contradictions", f"catalog.rls.{table}."), (
        f"USING(true) under tenant_isolation_{table} produced no policy-level contradiction"
    )


def test_d2_unrecognised_predicate_under_native_name_is_not_accepted_by_name_alone() -> None:
    cluster = FakeCluster()
    cluster.policies["media_identities"] = [_policy("tenant_isolation_media_identities", "(tenant_id IS NOT NULL)")]
    result = _run(cluster)
    assert _policy_issue_fields(result, "media_identities"), (
        "an unrecognised predicate was accepted because the policy name matched"
    )


@pytest.mark.parametrize("canonical", [False, True])
def test_d2_native_tenant_policy_under_native_name_raises_no_policy_verdict(canonical: bool) -> None:
    cluster = FakeCluster()
    if canonical:
        qual = NATIVE_TENANT_QUAL.replace(
            "NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid",
            "(NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid",
        )
        for table in cluster.policies:
            cluster.policies[table] = [_policy(f"tenant_isolation_{table}", qual)]
    result = _run(cluster)
    assert _fields_under(result, "contradictions", "catalog.rls.") == []
    assert _fields_under(result, "missing_reasons", "catalog.rls.") == []


def test_d2_renamed_tenant_policy_is_still_contradicted_as_missing_tenant_policy() -> None:
    cluster = FakeCluster()
    cluster.policies["describe_operations"] = [_policy("describe_ops_scope", NATIVE_TENANT_QUAL)]
    result = _run(cluster)
    assert COL.TENANT_POLICY_MISSING in _contra_codes(result)
    assert _fields_under(result, "contradictions", "catalog.rls.describe_operations.policies")


# --------------------------------------------------------------------------------------------
# D3 / P1: causal operation/run/output binding and independent content agreement are unproven.
# Current defect: sessions are compared only by row counts; status/tier are never consumed;
# the visibility operation_id is copied from the selection, not read from a native link.
# --------------------------------------------------------------------------------------------


def test_d3_equal_counts_with_different_caption_digest_is_a_visibility_disagreement() -> None:
    cluster = FakeCluster()
    cluster.session_views[INDEPENDENT][("image_description_run_items", (RUN_OWN, 101))] = {
        "caption": "stale caption for media 101"
    }
    result = _run(cluster)
    facts = _facts(result)
    primary = facts[f"pg:visibility:{PRIMARY}:media-101"]
    independent = facts[f"pg:visibility:{INDEPENDENT}:media-101"]
    assert primary["own_output_rows"] == independent["own_output_rows"] == 1
    assert primary["caption_sha256"] != independent["caption_sha256"]
    assert COL.VISIBILITY_SESSION_DISAGREEMENT in _all_codes(result)


def test_d3_equal_counts_with_different_request_digest_is_a_visibility_disagreement() -> None:
    cluster = FakeCluster()
    cluster.session_views[INDEPENDENT][("describe_operations", OP_OWN)] = {"request_digest": "e" * 64}
    result = _run(cluster)
    facts = _facts(result)
    primary = facts[f"pg:visibility:{PRIMARY}:media-101"]
    independent = facts[f"pg:visibility:{INDEPENDENT}:media-101"]
    assert primary["own_demand_rows"] == independent["own_demand_rows"] == 1
    assert primary["request_digest"] != independent["request_digest"]
    assert COL.VISIBILITY_SESSION_DISAGREEMENT in _all_codes(result)


def test_d3_identical_sessions_produce_no_visibility_disagreement() -> None:
    result = _run(FakeCluster())
    assert COL.VISIBILITY_SESSION_DISAGREEMENT not in _all_codes(result)


def test_d3_running_provisional_row_is_not_verdict_equivalent_to_final_row() -> None:
    cluster = FakeCluster()
    cluster.rows["image_description_run_items"][0].update(status="running", tier="provisional_cpu")
    result = _run(cluster)
    assert any(
        i["code"] == "output_row_not_final" and re.match(r"visibility\..+\.101\.", i["field"]) for i in _issues(result)
    )


def test_d3_native_run_linked_to_unrelated_operation_is_not_copied_from_selection() -> None:
    cluster = FakeCluster()
    cluster.rows["image_description_runs"][0]["operation_id"] = OP_FOREIGN
    result = _run(cluster)
    assert _facts(result)[f"pg:visibility:{PRIMARY}:media-101"]["operation_id"] == OP_FOREIGN
    assert _fields_under(result, "contradictions", "visibility.")
    assert "run_operation_mismatch" in _contra_codes(result)


def test_d3_matching_native_run_link_introduces_no_new_contradiction() -> None:
    result = _run(FakeCluster())
    assert _facts(result)[f"pg:visibility:{PRIMARY}:media-101"]["operation_id"] == OP_OWN
    assert not [
        i
        for i in _issues(result)
        if i["field"].startswith("visibility.") and (i["field"].endswith("operation_id") or i["field"].endswith("run"))
    ]
    receipts = [json.loads(raw) for raw in result["raw_artifacts"].values()]
    assert all(
        any(q["query_id"] == "run-own" and q["rows"] == [[RUN_OWN, TENANT_A, OP_OWN]] for q in r["queries"])
        for r in receipts
    )


def test_d3_absent_run_link_is_missing() -> None:
    cluster = FakeCluster()
    cluster.rows["image_description_runs"] = []
    result = _run(cluster)
    assert _facts(result)[f"pg:visibility:{PRIMARY}:media-101"]["operation_id"] is None
    assert "run_row_not_visible" in _missing_codes(result)


def test_d3_unselected_operation_is_missing_not_run_mismatch() -> None:
    selection = copy.deepcopy(BASE_SELECTION)
    del selection["operation_id"]
    result = _run(FakeCluster(), selection)
    assert "run_operation_mismatch" not in _contra_codes(result)
    assert result["section"]["status"] == "incomplete"
    assert COL.OPERATION_ID_NOT_SELECTED in _missing_codes(result)
    for label in (PRIMARY, INDEPENDENT):
        assert _facts(result)[f"pg:visibility:{label}:media-101"]["operation_id"] == OP_OWN


# --------------------------------------------------------------------------------------------
# D4 / P1: one absolute deadline and row/byte budgets must bound every blocking step.
# Current defects: an expiry during the final query is not classified; rows are materialised
# before the 200-row check.
# --------------------------------------------------------------------------------------------


def test_d4_deadline_expiring_during_the_last_query_is_classified_not_silently_used() -> None:
    cluster = FakeCluster(budget_s=5.0)
    cluster.cost_hook = lambda label, sql, params: (
        10.0 if (label == INDEPENDENT and sql == COL.OUTPUT_SQL and params.get("run_id") == RUN_FOREIGN) else 0.0
    )
    result = _run(cluster)
    assert COL.DEADLINE_EXHAUSTED in _missing_codes(result)
    receipt = json.loads(result["raw_artifacts"][f"raw/pg/{INDEPENDENT}.json"])
    last_query = next(q for q in receipt["queries"] if q["query_id"] == "output-foreign")
    assert last_query["outcome"] == "deadline_exhausted" and last_query["rows"] == []


def test_d4_row_acquisition_is_capped_at_budget_plus_one() -> None:
    cluster = FakeCluster()
    cluster.output_rows_total = 10_000
    result = _run(cluster)
    assert cluster.pull_counters, "the oversized output generator was never consumed"
    assert max(counter[0] for counter in cluster.pull_counters) <= COL.MAX_ROWS_PER_QUERY + 1
    assert COL.ROW_BUDGET_EXCEEDED in _missing_codes(result)


@pytest.mark.parametrize(("total", "exceeded"), [(200, False), (201, True)])
def test_d4_row_budget_boundary_is_exact(total: int, exceeded: bool) -> None:
    cluster = FakeCluster()
    cluster.output_rows_total = total
    result = _run(cluster)
    assert (COL.ROW_BUDGET_EXCEEDED in _missing_codes(result)) is exceeded


def test_d4_oversized_receipt_is_not_persisted_and_no_artifact_cites_it() -> None:
    cluster = FakeCluster()
    cluster.rows["image_description_run_items"][0]["reported_model_id"] = "x" * 300_000
    result = _run(cluster)
    assert COL.BYTE_BUDGET_EXCEEDED in _missing_codes(result)
    assert {a["relative_path"] for a in result["artifacts"]} == set(result["raw_artifacts"])
    assert all(len(raw) <= COL.MAX_RECEIPT_BYTES for raw in result["raw_artifacts"].values())


def test_d4_connect_bounds_never_exceed_the_remaining_budget() -> None:
    cluster = FakeCluster(budget_s=5.0)
    _run(cluster)
    assert cluster.connect_calls
    for call in cluster.connect_calls:
        assert call["connect_timeout_s"] <= 5.0
        assert call["statement_timeout_ms"] <= 5000
        assert call["lock_timeout_ms"] <= 5000
        assert call["overall_deadline_s"] <= 5.0


def test_d4_exhausted_budget_connects_nothing_and_says_so() -> None:
    cluster = FakeCluster(budget_s=0.0)
    result = _run(cluster)
    assert cluster.connect_calls == []
    assert COL.DEADLINE_EXHAUSTED in _missing_codes(result)


def test_d4_unexpired_budget_reports_no_deadline_code() -> None:
    result = _run(FakeCluster(budget_s=600.0))
    assert COL.DEADLINE_EXHAUSTED not in _all_codes(result)


def test_d4_statement_cancel_rolls_back_and_closes_every_session() -> None:
    cluster = FakeCluster()
    cluster.fail_on[COL.VECTOR_SQL] = "57014"
    result = _run(cluster)
    assert COL.STATEMENT_TIMEOUT in _missing_codes(result)
    assert cluster.sessions and all(session.closed for session in cluster.sessions)
    for session in cluster.sessions:
        if session.began:
            assert "ROLLBACK" in session.log


# --------------------------------------------------------------------------------------------
# D5 / P2: extension, vector typmod, index, and model-space lineage must be observed, not implied.
# Current defects: no index access-method/opclass observation; no extension-membership join on
# the vector type; identity_cluster_representatives (a tenant table carrying an embedding) is
# missing from the RLS coverage list.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mutation", [None, "hnsw", "vector_l2_ops", "absent", "invalid", "predicate", "expression"])
def test_d5_vector_index_identity_is_observed_by_the_primary_catalog(mutation: str | None) -> None:
    cluster = FakeCluster()
    row = list(cluster.indexes[0])
    if mutation == "absent":
        cluster.indexes.pop(0)
    elif mutation:
        key, value = {
            "hnsw": (2, "hnsw"),
            "vector_l2_ops": (3, "vector_l2_ops"),
            "invalid": (4, False),
            "predicate": (5, "media_id > 0"),
            "expression": (6, "embedding + embedding"),
        }[mutation]
        row[key] = value
        cluster.indexes[0] = tuple(row)
    result = _run(cluster)
    fields = [i["field"] for i in _issues(result) if i["field"].startswith("catalog.indexes.")]
    assert bool(fields) is (mutation is not None)


@pytest.mark.parametrize("owned", [True, False])
def test_d5_extension_membership_of_the_vector_type_is_observed(owned: bool) -> None:
    cluster = FakeCluster()
    if not owned:
        cluster.extension_types = []
    result = _run(cluster)
    assert bool([i for i in _issues(result) if i["field"] == "catalog.extension_type"]) is (not owned)


def test_d5_every_tenant_vector_base_table_is_under_rls_coverage() -> None:
    result = _run(FakeCluster())
    base = {table for table, _column in COL.VECTOR_COLUMNS if not table.startswith("mv_")}
    assert base <= {r["table"] for r in _catalog(result)["rls"]}


def test_d5_vector_typmod_mismatch_is_contradicted_on_the_named_column() -> None:
    cluster = FakeCluster()
    cluster.vector_typmods[("media_identities", "embedding")] = DIMENSION - 1
    result = _run(cluster)
    assert COL.VECTOR_DIMENSION_MISMATCH in _contra_codes(result)
    assert _fields_under(result, "contradictions", "catalog.vectors.media_identities.embedding.")


def test_d5_mixed_embedding_models_in_one_tenant_are_contradicted() -> None:
    cluster = FakeCluster()
    cluster.rows["media_identities"][1]["embedding_model"] = OTHER_MODEL
    result = _run(cluster)
    assert COL.MIXED_EMBEDDING_MODELS in _contra_codes(result)
    assert COL.MIXED_EMBEDDING_SPACES in _contra_codes(result)


def test_d5_centroid_model_lineage_stays_missing_and_is_not_filled_from_configuration() -> None:
    result = _run(FakeCluster())
    centroid = next(v for v in _catalog(result)["vectors"] if v["table"] == "mv_identity_cluster_centroids")
    assert centroid["embedding_models"] is None
    assert _fields_under(
        result, "missing_reasons", "catalog.vectors.mv_identity_cluster_centroids.centroid.embedding_models"
    )


# --------------------------------------------------------------------------------------------
# D6 / P1: a keyword-form DSN is refused before connect, and the raw value never reaches
# receipts or the section. Current defect: only URI and 'password' substrings are refused.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("dsn_ref", KEYWORD_DSN_REFS)
def test_d6_keyword_dsn_is_refused_before_connect_and_never_persisted(dsn_ref: str) -> None:
    cluster = FakeCluster()
    result = _run(cluster, _selection(dsn_ref=dsn_ref))
    assert cluster.connect_calls == [], "a keyword-form DSN reached connect"
    assert any(i["code"] == COL.SELECTION_FIELD_INVALID and i["field"] == "dsn_ref" for i in _issues(result))
    assert dsn_ref not in _blob(result)


@pytest.mark.parametrize(
    "dsn_ref",
    [
        "postgresql://fixture.invalid/fixture_identity",
        f"host=192.0.2.10 dbname=fixture_identity password={FIXTURE_SECRET}",
    ],
)
def test_d6_uri_and_password_references_are_refused_before_connect(dsn_ref: str) -> None:
    cluster = FakeCluster()
    result = _run(cluster, _selection(dsn_ref=dsn_ref))
    assert cluster.connect_calls == []
    assert any(i["code"] == COL.SELECTION_FIELD_INVALID and i["field"] == "dsn_ref" for i in _issues(result))
    assert FIXTURE_SECRET not in _blob(result)


def test_d6_opaque_reference_connects_and_receipts_carry_only_the_reference_name() -> None:
    cluster = FakeCluster()
    result = _run(cluster)
    assert len(cluster.connect_calls) == 2
    assert all(call["dsn_ref"] == DSN_REF for call in cluster.connect_calls)
    blob = _blob(result)
    assert DSN_REF in blob
    for marker in ("host=", "dbname=", "postgresql://", "password", FIXTURE_SECRET):
        assert marker not in blob, marker


# --------------------------------------------------------------------------------------------
# Pinned produced facts, asserted separately from the policy verdict. Facts copied from the
# selection (tenant_context, operation_id, run_id) are deliberately not pinned as observations.
# --------------------------------------------------------------------------------------------


def test_positive_produced_facts_are_pinned_separately_from_the_policy_verdict() -> None:
    result = _run(FakeCluster())
    facts = _facts(result)
    primary = facts[f"pg:connection:{PRIMARY}"]
    assert {k: primary[k] for k in ("database", "current_user", "session_user", "backend_pid")} == {
        "database": DATABASE,
        "current_user": ROLE,
        "session_user": ROLE,
        "backend_pid": 4101,
    }
    assert (primary["rolsuper"], primary["rolbypassrls"], primary["transaction_read_only"]) == (False, False, True)
    assert facts[f"pg:connection:{INDEPENDENT}"]["backend_pid"] == 4102
    catalog = _catalog(result)
    assert catalog["extension_version"] == EXT_VERSION
    assert {(v["table"], v["column"]): v["atttypmod"] for v in catalog["vectors"]} == dict.fromkeys(
        COL.VECTOR_COLUMNS, DIMENSION
    )
    visibility = facts[f"pg:visibility:{PRIMARY}:media-101"]
    assert (
        visibility["own_output_rows"],
        visibility["own_demand_rows"],
        visibility["foreign_output_rows"],
        visibility["foreign_demand_rows"],
    ) == (1, 1, 0, 0)
    assert visibility["request_digest"] == DIGEST_OWN
    assert visibility["caption_sha256"] == _sha(CAPTION_101)
    assert visibility["result_generation"] == GENERATION
    verdict = _verdict(result)
    assert verdict["contradictions"] == []
    assert verdict["status"] == "incomplete"
    assert {
        COL.FOREIGN_UNWITNESSED,
        COL.FIRST_REVISION_UNPERSISTED,
        COL.EMBEDDING_MODELS_UNAVAILABLE,
    } <= set(verdict["missing"])


ABI_STATUSES = frozenset({"complete", "incomplete", "contradicted"})
ABI_KINDS = frozenset({"connection", "catalog", "visibility"})
ABI_DATA_KEYS: dict[str, frozenset[str]] = {
    "connection": frozenset(
        {
            "connection_id",
            "database",
            "current_user",
            "session_user",
            "backend_pid",
            "tenant_context",
            "app_bypass_rls",
            "rolsuper",
            "rolbypassrls",
            "transaction_read_only",
        }
    ),
    "catalog": frozenset({"connection_id", "extension_name", "extension_version", "vectors", "rls"}),
    "visibility": frozenset(
        {
            "connection_id",
            "tenant_id",
            "operation_id",
            "request_digest",
            "first_counting_revision",
            "run_id",
            "media_id",
            "result_generation",
            "caption_sha256",
            "own_demand_rows",
            "own_output_rows",
            "foreign_demand_rows",
            "foreign_output_rows",
            "foreign_witness_refs",
        }
    ),
}
ABI_OBSERVATION_KEYS = frozenset(
    {"observation_id", "kind", "observed_at", "artifact_relative_path", "artifact_sha256", "source_artifacts", "data"}
)
ABI_ISSUE_KEYS = frozenset({"code", "field", "detail", "artifact_refs"})
ABI_REF_KEYS = frozenset({"relative_path", "sha256", "locator"})
ABI_ARTIFACT_KEYS = frozenset(
    {"relative_path", "sha256", "command_argv", "exit_code", "capture_started_at", "capture_finished_at"}
)
RFC3339_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")
H64 = re.compile(r"[0-9a-f]{64}")


def _assert_abi_envelope(result: Mapping[str, Any]) -> None:
    """Frozen ABI v1 invariants for section ``pg``. Shape only; semantic oracles live in the tests."""
    assert set(result) == {"section", "artifacts", "raw_artifacts"}
    section = result["section"]
    assert set(section) == {"status", "observations", "missing_reasons", "contradictions"}
    assert section["status"] in ABI_STATUSES
    raw = result["raw_artifacts"]
    assert isinstance(raw, dict)
    listed = {artifact["relative_path"]: artifact for artifact in result["artifacts"]}
    assert set(listed) == set(raw), "every persisted raw file is listed and every listed artifact is persisted"
    assert len(listed) == len(result["artifacts"]), "duplicate artifact paths"
    for path, content in raw.items():
        pure = PurePosixPath(path)
        assert path.startswith("raw/pg/") and not pure.is_absolute() and ".." not in pure.parts, path
        assert "\x00" not in path
        assert isinstance(content, bytes)
        assert hashlib.sha256(content).hexdigest() == listed[path]["sha256"], path
    for artifact in result["artifacts"]:
        assert set(artifact) == ABI_ARTIFACT_KEYS
        assert artifact["command_argv"] == [] and artifact["exit_code"] is None, "direct driver queries"
        assert RFC3339_Z.fullmatch(artifact["capture_started_at"]), artifact
        assert RFC3339_Z.fullmatch(artifact["capture_finished_at"]), artifact
        assert H64.fullmatch(artifact["sha256"]), artifact
    ids = [obs["observation_id"] for obs in section["observations"]]
    assert len(ids) == len(set(ids)), "observation IDs are unique within the envelope"
    for obs in section["observations"]:
        assert set(obs) == ABI_OBSERVATION_KEYS
        assert obs["kind"] in ABI_KINDS, obs["kind"]
        assert obs["observed_at"] is None or RFC3339_Z.fullmatch(obs["observed_at"]), obs
        assert set(obs["data"]) == ABI_DATA_KEYS[obs["kind"]], (obs["kind"], sorted(obs["data"]))
        assert obs["artifact_relative_path"] in raw, "every fact has a primary raw reference"
        assert obs["artifact_sha256"] == listed[obs["artifact_relative_path"]]["sha256"]
        for ref in obs["source_artifacts"]:
            assert set(ref) == ABI_REF_KEYS
    for issue in [*section["missing_reasons"], *section["contradictions"]]:
        assert set(issue) == ABI_ISSUE_KEYS, issue
        assert isinstance(issue["code"], str) and isinstance(issue["field"], str) and isinstance(issue["detail"], str)
        for ref in issue["artifact_refs"]:
            assert set(ref) == ABI_REF_KEYS
    # F8: exact field/code pairs, never substring or unrelated catalog coverage.
    missing = {(i["field"], i["code"]) for i in section["missing_reasons"]}
    contradictions = {(i["field"], i["code"]) for i in section["contradictions"]}
    for obs in section["observations"]:
        data = obs["data"]
        label = data["connection_id"]
        for key, value in data.items():
            if value is not None:
                continue
            allowed = set()
            if obs["kind"] == "connection":
                field = f"connection.{label}.{key}"
                codes = {"tenant_context": COL.TENANT_CONTEXT_NOT_SELECTED,
                         "app_bypass_rls": COL.APP_BYPASS_UNPROBED}
                allowed.add((field, codes.get(key, COL.PROBE_NOT_RUN)))
                if key == "rolbypassrls":
                    allowed.add((f"connection.{label}.rolsuper", COL.PROBE_NOT_RUN))
            elif obs["kind"] == "catalog" and key == "extension_version":
                allowed.add(("catalog.extension_version", COL.VECTOR_EXTENSION_ABSENT))
            elif obs["kind"] == "visibility":
                root = f"visibility.{label}"
                media = f"{root}.{data['media_id']}"
                if key in ("tenant_id", "run_id", "operation_id"):
                    allowed.add((f"{root}.run", "run_row_not_visible"))
                    if key == "operation_id":
                        allowed.add((f"{root}.operation_id", "run_row_not_visible"))
                elif key == "first_counting_revision":
                    allowed.add((f"{media}.{key}", COL.FIRST_REVISION_UNPERSISTED))
                elif key == "request_digest":
                    allowed |= {(f"{root}.operation_id", COL.DEMAND_ROW_NOT_VISIBLE),
                                (f"{root}.operation_id", COL.OPERATION_ID_NOT_SELECTED)}
                    # A malformed observed digest is intentionally scrubbed to null.
                    if (f"{root}.request_digest", COL.REQUEST_DIGEST_MALFORMED) in contradictions:
                        continue
                elif key in ("caption_sha256", "result_generation"):
                    allowed.add((media, COL.OUTPUT_ROW_NOT_VISIBLE))
                    if key == "caption_sha256":
                        allowed.add((f"{media}.{key}", COL.CAPTION_SHA256_UNAVAILABLE))
                elif key == "own_demand_rows":
                    allowed.add((f"{root}.operation_id", COL.OPERATION_ID_NOT_SELECTED))
                elif key == "foreign_demand_rows":
                    allowed.add((f"{root}.foreign_operation_id", COL.FOREIGN_OPERATION_ID_NOT_SELECTED))
            assert allowed & missing, (obs["observation_id"], key, allowed)
        if obs["kind"] == "catalog":
            for vector in data["vectors"]:
                if vector["embedding_models"] is None:
                    field = f"catalog.vectors.{vector['table']}.{vector['column']}.embedding_models"
                    assert (field, COL.EMBEDDING_MODELS_UNAVAILABLE) in missing
    # Contradictions take precedence over missing reasons.
    if section["contradictions"]:
        assert section["status"] == "contradicted"
    elif section["missing_reasons"]:
        assert section["status"] == "incomplete"
    else:
        assert section["status"] == "complete"


# ---- fake self-checks for the probes the collector depends on (pass now; no collector required) ----


def test_bypass_false_requires_receipt() -> None:
    result = _run(FakeCluster())
    for label in (PRIMARY, INDEPENDENT):
        assert _facts(result)[f"pg:connection:{label}"]["app_bypass_rls"] is False
        receipt = json.loads(result["raw_artifacts"][f"raw/pg/{label}.json"])
        assert any(
            q["sql"] == "SELECT current_setting('app.bypass_rls', true)" and q["rows"] == [[None]]
            for q in receipt["queries"]
        )


@pytest.mark.parametrize("override", [{"claim_missing": True}, {"claim": TENANT_B}, {"bypass_missing": True}])
def test_d1_claims_are_observed_and_missing_claims_withhold_reads(override: dict[str, Any]) -> None:
    cluster = FakeCluster()
    cluster.overrides = {PRIMARY: override}
    result = _run(cluster)
    assert not any(sql in TENANT_DATA_SQL for session in cluster.sessions for sql in session.log)
    if "claim" in override:
        assert _facts(result)[f"pg:connection:{PRIMARY}"]["tenant_context"] == TENANT_B
        assert "tenant_context_mismatch" in _contra_codes(result)
    else:
        assert _missing_codes(result)
        if "claim_missing" in override:
            assert _facts(result)[f"pg:connection:{PRIMARY}"]["tenant_context"] is None
            assert COL.TENANT_CONTEXT_NOT_SELECTED in _missing_codes(result)


def test_d2_additional_permissive_policy_is_or_widening() -> None:
    cluster = FakeCluster()
    cluster.policies["media_identities"].append(_policy("extra", "true"))
    assert _fields_under(_run(cluster), "contradictions", "catalog.rls.media_identities.")


@pytest.mark.parametrize("dsn_ref", ["service=fixture", "passfile=fixture", " ref", "ref\n", "ref\t", "x" * 129])
def test_d6_only_opaque_reference_names(dsn_ref: str) -> None:
    cluster = FakeCluster()
    result = _run(cluster, _selection(dsn_ref=dsn_ref))
    assert not cluster.connect_calls
    assert dsn_ref not in _blob(result)


@pytest.mark.parametrize("cleanup", ["rollback", "close"])
def test_d4_cleanup_expiry_is_classified(cleanup: str, monkeypatch: pytest.MonkeyPatch) -> None:
    cluster = FakeCluster(budget_s=5)
    if cleanup == "rollback":
        cluster.cost_hook = lambda label, sql, params: 10 if sql == "ROLLBACK" else 0
    else:
        original = FakeSession.close

        def close(session: FakeSession) -> None:
            cluster.clock.now += 10
            original(session)

        monkeypatch.setattr(FakeSession, "close", close)
    result = _run(cluster)
    assert all(s.closed for s in cluster.sessions)
    assert any(i["code"] == COL.DEADLINE_EXHAUSTED and i["field"].startswith("cleanup.") for i in _issues(result))


def test_d4_statement_timeout_is_refreshed_to_remaining_budget() -> None:
    cluster = FakeCluster(budget_s=5)
    cluster.cost_hook = lambda label, sql, params: 0.01
    _run(cluster)
    bounds = [
        int(re.search(r"'([0-9]+)'", sql).group(1))
        for s in cluster.sessions
        for sql in s.log
        if "set_config('statement_timeout'" in sql
    ]
    assert bounds and max(bounds) <= 5000 and min(bounds) < max(bounds)
    for session in cluster.sessions:
        for index, sql in enumerate(session.log):
            if sql == "BEGIN READ ONLY" or "set_config('statement_timeout'" in sql:
                continue
            assert index > 0 and "set_config('statement_timeout'" in session.log[index - 1], sql


def test_d3_generation_disagreement_is_missing_not_session_contradiction() -> None:
    cluster = FakeCluster()
    cluster.session_views[INDEPENDENT][("image_description_run_items", (RUN_OWN, 101))] = {
        "result_generation": GENERATION + 1
    }
    result = _run(cluster)
    assert COL.VISIBILITY_SESSION_DISAGREEMENT in _missing_codes(result)
    assert COL.VISIBILITY_SESSION_DISAGREEMENT not in _contra_codes(result)


def test_d3_absent_operation_is_missing() -> None:
    cluster = FakeCluster()
    cluster.rows["describe_operations"] = []
    result = _run(cluster)
    assert COL.DEMAND_ROW_NOT_VISIBLE in _missing_codes(result)
    assert _facts(result)[f"pg:visibility:{PRIMARY}:media-101"]["request_digest"] is None


@pytest.mark.parametrize("drift", ["with_check", "reader_role", "restrictive"])
def test_d2_policy_dimensions_are_not_replaced_by_name(drift: str) -> None:
    cluster = FakeCluster()
    policy = cluster.policies["media_identities"][0]
    if drift == "with_check":
        policy["with_check"] = "true"
    elif drift == "reader_role":
        policy["roles"] = [ROLE]
        policy["qual"] = "true"
    else:
        policy["permissive"] = "RESTRICTIVE"
        policy["qual"] = "unknown"
    assert _policy_issue_fields(_run(cluster), "media_identities")


@pytest.mark.parametrize("claim", [None, "", "off", "false", "unrecognized"])
def test_d1_bypass_claim_is_measured_and_unknown_fails_closed(claim: str | None) -> None:
    cluster = FakeCluster()
    cluster.overrides = {PRIMARY: {"raw_bypass": claim}}
    result = _run(cluster)
    data = _facts(result)[f"pg:connection:{PRIMARY}"]
    if claim == "unrecognized":
        assert data["app_bypass_rls"] is None
        assert COL.APP_BYPASS_UNPROBED in _missing_codes(result)
        assert _tenant_statements(cluster) == []
    else:
        assert data["app_bypass_rls"] is False
        assert _tenant_statements(cluster)


def test_r80_f2_aborted_transaction_rolls_back_without_cleanup_refresh() -> None:
    cluster = FakeCluster()
    cluster.abort_on_error = True
    cluster.fail_on[COL.OUTPUT_SQL] = "57014"
    result = _run(cluster)
    assert COL.STATEMENT_TIMEOUT in _missing_codes(result)
    assert COL.SESSION_CLOSE_FAILED not in _missing_codes(result)
    primary = _session(cluster, PRIMARY)
    failed_at = primary.log.index(COL.OUTPUT_SQL)
    assert primary.log[failed_at + 1 :] == ["ROLLBACK"]
    for session in cluster.sessions:
        assert session.log.count("ROLLBACK") == 1
        assert session.closed and not session.began and not session.aborted


@pytest.mark.parametrize("failure", ["statement", "fetch"])
def test_r80_f2_failed_cleanup_refresh_still_attempts_rollback(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = FakeCluster()
    query = FakeSession.query

    def fail_cleanup(session: FakeSession, sql: str, params: Any):
        if "set_config('statement_timeout'" in sql and session.log.count(COL.OUTPUT_SQL) == 2:
            session.log.append(sql)
            session.aborted = True
            if failure == "statement":
                raise FakeSqlError("cleanup refresh rejected", "57014")

            def aborted_rows():
                raise FakeSqlError("cleanup refresh fetch rejected", "25P02")
                yield ()

            return aborted_rows()
        return query(session, sql, params)

    monkeypatch.setattr(FakeSession, "query", fail_cleanup)
    result = _run(cluster)
    for session in cluster.sessions:
        assert session.log[-1] == "ROLLBACK"
        assert session.closed and not session.began and not session.aborted
    assert COL.SESSION_CLOSE_FAILED not in _missing_codes(result)
    assert (COL.STATEMENT_TIMEOUT if failure == "statement" else COL.DRIVER_ERROR) in _missing_codes(result)


@pytest.mark.parametrize("inherited", [True, False])
def test_r80_f3_group_role_policy_uses_observed_membership(inherited: bool) -> None:
    cluster = FakeCluster()
    cluster.role_usage["reader_group"] = inherited
    policy = _policy("group_widening", "true")
    policy["roles"] = ["reader_group"]
    cluster.policies["media_identities"].append(policy)
    result = _run(cluster)
    fields = _fields_under(result, "contradictions", "catalog.rls.media_identities.policies.group_widening.")
    assert bool(fields) is inherited
    receipt = json.loads(result["raw_artifacts"][f"raw/pg/{PRIMARY}.json"])
    membership = next(q for q in receipt["queries"] if q["query_id"] == "role-membership")
    assert ["reader_group", inherited] in membership["rows"]


@pytest.mark.parametrize("roles", [None, [], ["unobserved_group"]])
def test_r80_f3_unknown_policy_roles_are_missing(roles: list[str] | None) -> None:
    cluster = FakeCluster()
    policy = _policy("unknown_target", "true")
    policy["roles"] = roles
    cluster.policies["media_identities"].append(policy)
    result = _run(cluster)
    assert any(
        issue["code"] == "policy_roles_unproven"
        and issue["field"] == "catalog.rls.media_identities.policies.unknown_target.roles"
        for issue in result["section"]["missing_reasons"]
    )
    assert result["section"]["status"] == "incomplete"


@pytest.mark.parametrize("probe_rows", [[], [(ROLE, True)]])
def test_r80_f3_unobserved_group_membership_is_missing(
    probe_rows: list[tuple[str, bool]], monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = FakeCluster()
    policy = _policy("unproven_group", "true")
    policy["roles"] = ["reader_group"]
    cluster.policies["media_identities"].append(policy)
    query = FakeSession.query

    def missing_membership(session: FakeSession, sql: str, params: Any):
        if sql == COL.ROLE_MEMBERSHIP_SQL:
            session.log.append(sql)
            return probe_rows
        return query(session, sql, params)

    monkeypatch.setattr(FakeSession, "query", missing_membership)
    result = _run(cluster)
    assert "policy_roles_unproven" in _missing_codes(result)
    assert "unsafe_policy_predicate" not in _contra_codes(result)


def test_r80_f4_extension_type_in_other_schema_is_accepted() -> None:
    cluster = FakeCluster()
    cluster.extension_types = [("extensions", "vector", "vector", 9001, "e", "pg_type", "pg_extension")]
    result = _run(cluster)
    assert not _fields_under(result, "missing_reasons", "catalog.extension_type")
    assert {(v["table"], v["column"]) for v in _catalog(result)["vectors"]} == set(COL.VECTOR_COLUMNS)
    assert result["section"]["status"] == "incomplete"


@pytest.mark.parametrize(
    "rogue", ["unowned", "other-extension", "nonmember-dependency", "wrong-object-class", "wrong-reference-class"]
)
def test_r80_f4_column_must_use_extension_owned_type_oid(rogue: str) -> None:
    cluster = FakeCluster()
    pair = COL.VECTOR_COLUMNS[0]
    cluster.vector_type_oids[pair] = 9002
    if rogue != "unowned":
        row = ["rogue", "vector", "vector", 9002, "e", "pg_type", "pg_extension"]
        key, value = {
            "other-extension": (2, "other_extension"),
            "nonmember-dependency": (4, "a"),
            "wrong-object-class": (5, "pg_class"),
            "wrong-reference-class": (6, "pg_class"),
        }[rogue]
        row[key] = value
        cluster.extension_types.append(tuple(row))
    result = _run(cluster)
    assert pair not in {(v["table"], v["column"]) for v in _catalog(result)["vectors"]}
    assert any(
        issue["code"] == COL.VECTOR_COLUMN_ABSENT and issue["field"] == f"catalog.vectors.{pair[0]}.{pair[1]}"
        for issue in result["section"]["missing_reasons"]
    )


# c82 bundled lows: causal source regressions and private-mutant oracle controls.
@pytest.mark.parametrize("sqlstate", ["57014", "XX000"])
def test_c82_lazy_fetch_error_is_classified_and_skips_refresh(sqlstate, monkeypatch):
    cluster = FakeCluster()
    query = FakeSession.query
    def lazy(session, sql, params):
        if sql == COL.OUTPUT_SQL:
            session.log.append(sql)
            def rows():
                session.aborted = True
                raise FakeSqlError("lazy failure", sqlstate)
                yield ()
            return rows()
        return query(session, sql, params)
    monkeypatch.setattr(FakeSession, "query", lazy)
    result = _run(cluster)
    assert (COL.STATEMENT_TIMEOUT if sqlstate == "57014" else COL.DRIVER_ERROR) in _missing_codes(result)
    primary = _session(cluster, PRIMARY)
    assert primary.log[primary.log.index(COL.OUTPUT_SQL) + 1:] == ["ROLLBACK"]
    receipt = json.loads(result["raw_artifacts"][f"raw/pg/{PRIMARY}.json"])
    assert next(q for q in receipt["queries"] if q["query_id"] == "output-own")["outcome"] == "error"


@pytest.mark.parametrize("probe", ["VECTOR_SQL", "POLICY_SQL", "ROLE_MEMBERSHIP_SQL", "RUN_SQL"])
def test_c82_wrong_arity_is_probe_rejected(probe, monkeypatch):
    query = FakeSession.query
    def malformed(session, sql, params):
        if sql == getattr(COL, probe):
            session.log.append(sql)
            return [("wrong-shape",)]
        return query(session, sql, params)
    monkeypatch.setattr(FakeSession, "query", malformed)
    cluster = FakeCluster()
    result = _run(cluster)
    assert COL.PROBE_REJECTED in _missing_codes(result)
    assert all(s.closed for s in cluster.sessions)


def test_c82_run_tenant_leak_is_observed_and_contradicted(monkeypatch):
    query = FakeSession.query
    def leak(session, sql, params):
        if sql == COL.RUN_SQL and params["run_id"] == RUN_OWN:
            session.log.append(sql)
            return [(RUN_OWN, TENANT_B, OP_OWN)]
        return query(session, sql, params)
    monkeypatch.setattr(FakeSession, "query", leak)
    result = _run(FakeCluster())
    assert "run_operation_mismatch" in _contra_codes(result)
    assert _facts(result)[f"pg:visibility:{PRIMARY}:media-101"]["tenant_id"] == TENANT_B


def test_c82_only_policy_named_roles_consume_membership_budget():
    cluster = FakeCluster()
    cluster.role_usage.update({f"irrelevant_{i}": False for i in range(250)})
    cluster.role_usage["reader_group"] = True
    policy = _policy("group_widening", "true")
    policy["roles"] = ["reader_group"]
    cluster.policies["media_identities"].append(policy)
    result = _run(cluster)
    assert COL.ROW_BUDGET_EXCEEDED not in _missing_codes(result)
    assert "unsafe_policy_predicate" in _contra_codes(result)
    receipt = json.loads(result["raw_artifacts"][f"raw/pg/{PRIMARY}.json"])
    rows = next(q for q in receipt["queries"] if q["query_id"] == "role-membership")["rows"]
    assert rows == [["reader_group", True]]


def test_c82_null_native_operation_link_is_missing():
    cluster = FakeCluster()
    cluster.rows["image_description_runs"][0]["operation_id"] = None
    result = _run(cluster)
    assert "run_operation_mismatch" not in _contra_codes(result)
    assert any(i["field"] == f"visibility.{PRIMARY}.operation_id" for i in result["section"]["missing_reasons"])


@pytest.mark.parametrize("kind", ["null-check", "restrictive-true"])
def test_c82_policy_inheritance_and_restrictive_true(kind):
    cluster = FakeCluster()
    if kind == "null-check":
        cluster.policies["media_identities"][0]["with_check"] = None
    else:
        policy = _policy("restrictive_noop", "true")
        policy["permissive"] = "RESTRICTIVE"
        cluster.policies["media_identities"].append(policy)
    result = _run(cluster)
    assert not _policy_issue_fields(result, "media_identities")


@pytest.mark.parametrize("rewrite,accepted", [("IN ('e')", True), ("= 'e' OR d.deptype = 'a'", False)])
def test_c82_dependency_predicate_semantics(rewrite, accepted, monkeypatch):
    monkeypatch.setattr(COL, "VECTOR_SQL", COL.VECTOR_SQL.replace("= 'e'", rewrite))
    cluster = FakeCluster()
    pair = COL.VECTOR_COLUMNS[0]
    cluster.vector_type_oids[pair] = 9002
    cluster.extension_types.append(("rogue", "vector", "vector", 9002, "a", "pg_type", "pg_extension"))
    result = _run(cluster)
    present = pair in {(v["table"], v["column"]) for v in _catalog(result)["vectors"]}
    # The equivalent query excludes the rogue; the broken OR admits it, proving fake semantics.
    assert present is (not accepted)


def _unit_capture(cluster=None):
    cluster = cluster or FakeCluster()
    capture = COL._Capture(PRIMARY, "fixture-reference", {})
    capture.session = FakeSession(cluster, PRIMARY)
    return cluster, capture, COL._Findings()


def test_c82_acquisition_deadline_stops_lazy_rows():
    cluster, capture, findings = _unit_capture(FakeCluster(budget_s=5))
    pulls = []
    def rows():
        for i in range(100):
            pulls.append(i)
            cluster.clock.now += 6
            yield (i,)
    capture.session.query = lambda sql, params: rows()
    with pytest.raises(COL._HaltError) as halt:
        COL._query(capture, cluster.deadline, findings, "slow", "SELECT fixture", {}, ("value",))
    assert halt.value.code == COL.DEADLINE_EXHAUSTED
    assert "during acquisition" in halt.value.detail
    assert pulls == [0]


@pytest.mark.parametrize("stage", ["rollback", "close"])
def test_c82_cleanup_deadline_is_classified_at_exact_stage(stage):
    cluster, capture, findings = _unit_capture(FakeCluster(budget_s=5))
    capture.began = True
    session = capture.session
    query, close = session.query, session.close
    def slow_query(sql, params):
        value = query(sql, params)
        if stage == "rollback" and sql == "ROLLBACK":
            cluster.clock.now += 6
        return value
    def slow_close():
        close()
        if stage == "close":
            cluster.clock.now += 6
    session.query, session.close = slow_query, slow_close
    COL._close_all({PRIMARY: capture}, findings, cluster.deadline)
    assert any(i["code"] == COL.DEADLINE_EXHAUSTED and i["field"] == f"cleanup.{PRIMARY}.{stage}"
               and i["detail"] == f"deadline exhausted during {stage}" for i in findings.missing)
    assert session.closed and session.log[-1] == "ROLLBACK"


def test_c82_row_bytes_stop_before_next_lazy_row():
    cluster, capture, findings = _unit_capture()
    pulls = []
    def rows():
        for i in range(10):
            pulls.append(i)
            yield ("x" * (COL.MAX_RECEIPT_BYTES + 1),)
    capture.session.query = lambda sql, params: rows()
    assert COL._query(capture, cluster.deadline, findings, "large", "SELECT fixture", {}, ("value",)) is None
    assert pulls == [0]
    assert capture.queries[-1]["outcome"] == "byte_budget_exceeded"


def test_c82_accumulated_receipt_bytes_reject_many_small_queries(monkeypatch):
    cluster, capture, findings = _unit_capture()
    monkeypatch.setattr(COL, "MAX_RECEIPT_BYTES", 2000)
    capture.session.query = lambda sql, params: [("small",)]
    results = [COL._query(capture, cluster.deadline, findings, f"small-{i}", "SELECT fixture", {}, ("value",))
               for i in range(10)]
    assert results[0] == [["small"]] and results[-1] is None
    assert any(i["code"] == COL.BYTE_BUDGET_EXCEEDED for i in findings.missing)
    assert capture.queries[-1]["rows"] == []
    kept = [q for q in capture.queries if q["outcome"] == "ok"]
    assert sum(len(json.dumps(q, ensure_ascii=False).encode()) for q in kept) <= COL.MAX_RECEIPT_BYTES


def test_c82_serialization_stops_encoder_at_byte_bound(monkeypatch):
    _, capture, findings = _unit_capture()
    capture.queries = [{"fixture": "value"}]
    pulls = []
    class Encoder:
        def __init__(self, **kwargs):
            pass
        def iterencode(self, value):
            for i in range(100):
                pulls.append(i)
                yield "x" * 100_000
    monkeypatch.setattr(COL.json, "JSONEncoder", Encoder)
    COL._serialize({PRIMARY: capture}, findings)
    assert len(pulls) == 3
    assert not capture.persisted
    assert any(i["code"] == COL.BYTE_BUDGET_EXCEEDED for i in findings.missing)


@pytest.mark.parametrize("replacement", ["catalog.unrelated", "substring", "other-media", "wrong-code"])
def test_c82_null_measurement_requires_exact_reason(replacement):
    result = _run(FakeCluster())
    field = f"visibility.{PRIMARY}.101.first_counting_revision"
    section = result["section"]
    section["missing_reasons"] = [i for i in section["missing_reasons"] if i["field"] != field]
    bogus = {"code": COL.FIRST_REVISION_UNPERSISTED, "field": field, "detail": "fixture", "artifact_refs": []}
    if replacement == "wrong-code":
        bogus["code"] = COL.PROBE_NOT_RUN
    else:
        bogus["field"] = {"catalog.unrelated": "catalog.unrelated", "substring": f"prefix.{field}.suffix",
                          "other-media": f"visibility.{PRIMARY}.999.first_counting_revision"}[replacement]
    section["missing_reasons"].append(bogus)
    with pytest.raises(AssertionError):
        _assert_abi_envelope(result)


def test_c82_catalog_null_reason_cannot_cover_another_measurement():
    cluster = FakeCluster()
    cluster.extension_installed = False
    result = _run(cluster)
    catalog = next(o for o in result["section"]["observations"] if o["kind"] == "catalog")
    catalog["data"]["extension_name"] = None
    with pytest.raises(AssertionError):
        _assert_abi_envelope(result)


def test_c82_run_rejects_corrupted_collector_envelope(monkeypatch):
    collect = COL.collect_pg_evidence

    def corrupt(**kwargs):
        result = collect(**kwargs)
        result["unexpected_envelope_field"] = True
        return result

    monkeypatch.setattr(COL, "collect_pg_evidence", corrupt)
    with pytest.raises(AssertionError):
        _run(FakeCluster())


@pytest.mark.parametrize("replacement", ["other-vector", "wrong-code"])
def test_c82_vector_null_model_requires_its_exact_missing_reason(replacement):
    result = _run(FakeCluster())
    field = "catalog.vectors.mv_identity_cluster_centroids.centroid.embedding_models"
    vector = next(v for v in _catalog(result)["vectors"]
                  if v["table"] == "mv_identity_cluster_centroids")
    assert vector["embedding_models"] is None
    section = result["section"]
    reason = next(i for i in section["missing_reasons"] if i["field"] == field)
    section["missing_reasons"].remove(reason)
    bogus = copy.deepcopy(reason)
    if replacement == "other-vector":
        bogus["field"] = "catalog.vectors.media_identities.embedding.embedding_models"
    else:
        bogus["code"] = COL.PROBE_NOT_RUN
    section["missing_reasons"].append(bogus)
    with pytest.raises(AssertionError):
        _assert_abi_envelope(result)


@pytest.mark.parametrize("measured_dimension", [384, 1024])
def test_c82_vector_dimension_is_measured_from_selected_typmod(measured_dimension):
    cluster = FakeCluster()
    cluster.vector_typmods[("media_identities", "embedding")] = measured_dimension
    result = _run(cluster)
    vector = next(v for v in _catalog(result)["vectors"] if v["table"] == "media_identities")
    assert vector["atttypmod"] == measured_dimension
    assert any(i["field"] == "catalog.vectors.media_identities.embedding.atttypmod"
               and i["code"] == COL.VECTOR_DIMENSION_MISMATCH
               for i in result["section"]["contradictions"])
