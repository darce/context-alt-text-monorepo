"""G4 restricted-PostgreSQL findings: offline causal tests for ``scripts/collect_gpu_pg_evidence.py``.

Owner: GTMC c76 G4 RED lane. This module is the only file this lane may author. No existing test,
fixture, or source file is edited. The 14 superseded-ABI selectors in
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
from pathlib import Path
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
TENANT_DATA_SQL = frozenset({COL.DEMAND_SQL, COL.OUTPUT_SQL, COL.EMBEDDING_SQL})
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
    if qual == NATIVE_TENANT_QUAL:
        return (session_tenant is not None and row_tenant == session_tenant) or bypass
    return False  # unrecognised policy semantics fail closed in the fake


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
        self.vector_typmods: dict[tuple[str, str], int] = {pair: DIMENSION for pair in COL.VECTOR_COLUMNS}
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
        for pol in self._cluster.policies.get(table, []):
            if pol["cmd"] not in ("ALL", "SELECT") or pol["permissive"] != "PERMISSIVE":
                continue
            if "public" not in pol["roles"] and self.identity["role"] not in pol["roles"]:
                continue
            if _qual_true(pol["qual"], row_tenant, self.tenant, bool(self.identity["bypass"])):
                return True
        return False

    def query(self, sql: str, params: Any) -> list[tuple[Any, ...]]:
        cl = self._cluster
        params = dict(params or {})
        self.log.append(sql)
        cl.clock.now += float(cl.cost_hook(self.label, sql, params))
        if sql in cl.fail_on:
            raise FakeSqlError("fixture-induced statement failure", cl.fail_on[sql])
        if sql in ("BEGIN READ ONLY", "START TRANSACTION READ ONLY"):
            self.began = True
            self.read_only = bool(self.identity["honour_read_only"])
            return []
        if sql == "ROLLBACK":
            self.began = False
            self.read_only = False
            self.tenant = None
            return []
        tenant_set = _SET_TENANT_VALUE.fullmatch(sql)
        if tenant_set is not None:
            self.tenant = tenant_set.group(1)
            return []
        if _SET_TENANT_PREFIX.match(sql) or _SESSION_STMT.match(sql):
            raise FakeSqlError("session setting refused by the fixture contract")
        if _WRITE_STMT.match(sql):
            raise FakeSqlError("write refused in a restricted session", "25006")
        ident = self.identity
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
        if sql == COL.EXTENSION_SQL:
            return [("vector", cl.extension_version)] if cl.extension_installed else []
        if sql == COL.VECTOR_SQL:
            return [(ident["schema"], t, c, "vector", m) for (t, c), m in cl.vector_typmods.items()]
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
    return COL.collect_pg_evidence(connect=_connect_for(cluster), selection=sel, deadline=cluster.deadline)


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
    allowed = {"__future__", "collections.abc", "datetime", "hashlib", "json", "math", "re", "typing"}
    assert modules <= allowed, sorted(modules - allowed)


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
                assert sql.startswith("SET LOCAL app.current_tenant"), sql


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


def test_d2_native_tenant_policy_under_native_name_raises_no_policy_verdict() -> None:
    result = _run(FakeCluster())
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
    baseline = _run(FakeCluster())
    cluster = FakeCluster()
    item = cluster.rows["image_description_run_items"][0]
    item["status"] = "running"
    item["tier"] = "provisional_cpu"
    result = _run(cluster)
    assert (_verdict(result), _facts(result)) != (_verdict(baseline), _facts(baseline)), (
        "a running/provisional_cpu output row produced exactly the diagnostics of a completed final_gpu row"
    )


def test_d3_native_run_linked_to_unrelated_operation_is_not_copied_from_selection() -> None:
    baseline = _run(FakeCluster())
    cluster = FakeCluster()
    cluster.rows["image_description_runs"][0]["operation_id"] = OP_FOREIGN
    result = _run(cluster)
    observed_op = _facts(result)[f"pg:visibility:{PRIMARY}:media-101"]["operation_id"]
    new_issues = _issue_keys(result) - _issue_keys(baseline)
    assert observed_op != OP_OWN or new_issues, (
        "visibility reports the selected operation although the native run is linked to another operation"
    )


def test_d3_matching_native_run_link_introduces_no_new_contradiction() -> None:
    baseline = _run(FakeCluster())
    result = _run(FakeCluster())
    new_contra = {k for k in _issue_keys(result) - _issue_keys(baseline) if k[0] == "contradiction"}
    assert new_contra == set()


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


def test_d5_vector_index_identity_is_observed_by_the_primary_catalog() -> None:
    cluster = FakeCluster()
    _run(cluster)
    statements = _session(cluster, PRIMARY).log
    assert any("pg_index" in sql and "pg_am" in sql for sql in statements), (
        "no executed catalog statement observes vector index access method or opclass"
    )


def test_d5_extension_membership_of_the_vector_type_is_observed() -> None:
    cluster = FakeCluster()
    _run(cluster)
    assert any("pg_depend" in sql for sql in _session(cluster, PRIMARY).log), (
        "vector type namespace is not tied to extension membership"
    )


def test_d5_every_tenant_vector_base_table_is_under_rls_coverage() -> None:
    base = {table for table, _column in COL.VECTOR_COLUMNS if not table.startswith("mv_")}
    assert base <= set(COL.RLS_TABLES), sorted(base - set(COL.RLS_TABLES))


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
    assert {(v["table"], v["column"]): v["atttypmod"] for v in catalog["vectors"]} == {
        pair: DIMENSION for pair in COL.VECTOR_COLUMNS
    }
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
        COL.APP_BYPASS_UNPROBED,
        COL.FOREIGN_UNWITNESSED,
        COL.FIRST_REVISION_UNPERSISTED,
        COL.EMBEDDING_MODELS_UNAVAILABLE,
    } <= set(verdict["missing"])
