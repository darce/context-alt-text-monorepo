"""G4 restricted-PostgreSQL collector: offline fake-driven authoring.

Owner: GTMR G4. Target module: ``scripts/collect_gpu_pg_evidence.py``.
Scope: in-memory fakes only. No live database, DSN, credential, bootstrap, or GPU action.

Classification
--------------
* ``test_fake_*`` exercise only this module's fake. They pass now and show that the fake
  refuses writes, bypass changes, role escalation, read-write transactions, and foreign-tenant
  reads. A green collector result is only meaningful if the fake can go red.
* Collector tests exercise the frozen Section mapping ABI and measured fixture facts.
  Offline results do not establish live PostgreSQL behavior or runtime readiness.

Frozen interface under test
-----------------------------
``collect_pg_evidence(*, connect, selection, deadline) -> mapping`` with keys
``section`` (mapping of status, observations list, missing_reasons and contradictions),
``artifacts`` (list), and ``raw_artifacts`` (path-to-bytes mapping).

* ``connect(*, session_label, dsn_ref, connect_timeout_s, statement_timeout_ms, lock_timeout_ms,
  overall_deadline_s)`` returns a session exposing ``query(sql, params) -> list[tuple]`` and ``close()``.
  The connect call receives only a DSN reference, never a DSN value.
* ``deadline.remaining_seconds() -> float``.
* Observations are keyed by ``observation_id`` with the frozen data keys for their kind.

Status rule: any contradiction -> ``contradicted``; any missing join -> ``incomplete``;
otherwise ``complete``. Server version and output status/tier/model remain in raw receipts.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECTOR_PATH = REPO_ROOT / "scripts" / "collect_gpu_pg_evidence.py"
FUTURE_ABSENT = (
    "FUTURE_API_PROPOSAL_ABSENT: scripts/collect_gpu_pg_evidence.py::collect_pg_evidence is not implemented. "
    "Classified as proposal coverage for the G4 interface, not a causal defect in existing production."
)

PRIMARY_SESSION = "primary-restricted-reader"
INDEPENDENT_SESSION = "independent-restricted-verifier"
CONNECT_KWARGS = (
    "session_label",
    "dsn_ref",
    "connect_timeout_s",
    "statement_timeout_ms",
    "lock_timeout_ms",
    "overall_deadline_s",
)
# Proposal bounds. The collector may choose smaller values but never unbounded ones.
BOUNDS: dict[str, float] = {
    "connect_timeout_s": 10.0,
    "statement_timeout_ms": 30_000,
    "lock_timeout_ms": 5_000,
    "overall_deadline_s": 300.0,
}
BEGIN_READ_ONLY = frozenset({"BEGIN READ ONLY", "START TRANSACTION READ ONLY"})

# Proposal refusal codes.
WRONG_DATABASE = "wrong_database"
NOT_POSTGRESQL = "identity_probe_rejected"
SUPERUSER_ROLE = "superuser_role"
BYPASSRLS_ROLE = "bypassrls_role"
RLS_NOT_FORCED = "rls_not_forced"
NOT_VISIBLE_INDEPENDENT = "not_visible_on_independent_session"
FOREIGN_TENANT_VISIBLE = "foreign_tenant_visible"
MIXED_EMBEDDING_SPACES = "mixed_embedding_spaces"
MIXED_OUTPUT_MODELS = "mixed_output_models"
OUTPUT_MODEL_MISMATCH = "output_model_mismatch"
SESSION_NOT_INDEPENDENT = "session_independence_unproven"
STATEMENT_TIMEOUT = "statement_timeout"
DEADLINE_EXHAUSTED = "deadline_exhausted"

# Fixture pins. Operator-selected policy, never producer truth.
ENV = "dev"
DATABASE = "alt_context_dev"
ROLE = "acx_dev"
SCHEMA = "public"
OWN_TENANT = "11111111-1111-4111-8111-111111111111"
FOREIGN_TENANT = "22222222-2222-4222-8222-222222222222"
RUN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FOREIGN_RUN_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
MEDIA_IDS = (101, 102)
GENERATION = 3
PINNED_MODEL = "example-org/burst-model@rev-pinned"
OTHER_MODEL = "example-org/other-model@rev-other"
EXPECTED_DIM = 512
SELECTION: dict[str, Any] = {
    "environment": ENV,
    "expected_database": DATABASE,
    "expected_role": ROLE,
    "expected_schema": SCHEMA,
    "tenant_id": OWN_TENANT,
    "run_id": RUN_ID,
    "foreign_run_id": FOREIGN_RUN_ID,
    "media_ids": list(MEDIA_IDS),
    "result_generation": GENERATION,
    "expected_model_id": PINNED_MODEL,
    "expected_vector_dimension": EXPECTED_DIM,
    "dsn_ref": "restricted-dev-pg-ref",
}

# Identity columns of the existing vector inventory (validate_fir_dev_runtime EXPECTED_VECTOR_COLUMNS).
VECTOR_KEYS = (
    "public.media_identities.embedding",
    "public.identity_cluster_representatives.embedding",
    "public.mv_identity_cluster_centroids.centroid",
)
RLS_TABLES = ("image_description_runs", "image_description_run_items")
# ABI v1 demand and embedding tables. Native sources: db/models/scene.py DescribeOperation (describe_operations,
# tenant-scoped, PK tenant_id+operation_id) and db/models/identity.py MediaIdentity.embedding_model (media_identities).
DEMAND_TABLE = "describe_operations"
IDENTITY_TABLE = "media_identities"
PROBED_TABLES = (*RLS_TABLES, DEMAND_TABLE, IDENTITY_TABLE, "identity_cluster_representatives")
OWN_OP = "op-own-0001"
FOREIGN_OP = "op-foreign-0002"
OWN_DIGEST = hashlib.sha256(b"fixture-own-request-body").hexdigest()
FOREIGN_DIGEST = hashlib.sha256(b"fixture-foreign-request-body").hexdigest()
OWN_MODEL_SPACE = "fixture-embed-own-v1"
FOREIGN_MODEL_SPACE = "fixture-embed-foreign-v2"
# pg_policies rendering of db/migrations/versions/001_identity_schema.py tenant_isolation_* (USING == WITH CHECK).
POLICY_EXPR = (
    "((tenant_id = NULLIF(current_setting('app.current_tenant'::text, true), ''::text)::uuid) "
    "OR (COALESCE(NULLIF(current_setting('app.bypass_rls'::text, true), ''::text), 'false'::text)::boolean))"
)

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|VACUUM|MERGE|REINDEX|CLUSTER)\b"
    r"|\bINTO\b|\bFOR\s+(UPDATE|SHARE|NO\s+KEY|KEY\s+SHARE)\b|\bSET\s+ROLE\b|\bSESSION\s+AUTHORIZATION\b|\bRESET\b",
    re.IGNORECASE,
)


class FakeReadOnlyViolation(Exception):  # noqa: N818 - mirrors psycopg ReadOnlySqlTransaction
    """Mirrors psycopg ReadOnlySqlTransaction for a write, bypass, or role escalation attempt."""

    sqlstate = "25006"  # read_only_sql_transaction


class FakeProbeRejected(Exception):  # noqa: N818 - probe the engine rejects, not a psycopg name
    """A catalog probe the target engine cannot answer, e.g. current_database() on SQLite."""

    sqlstate = "42883"  # undefined_function


class QueryCanceled(Exception):  # noqa: N818 - mirrors psycopg.errors.QueryCanceled
    """Mirrors psycopg.errors.QueryCanceled for statement_timeout."""

    sqlstate = "57014"  # query_canceled


def _default_runs() -> list[dict[str, Any]]:
    return [
        {
            "id": RUN_ID,
            "tenant_id": OWN_TENANT,
            "operation_id": OWN_OP,
            "status": "completed",
            "media_ids": list(MEDIA_IDS),
            "committed": True,
        },
        {
            "id": FOREIGN_RUN_ID,
            "tenant_id": FOREIGN_TENANT,
            "operation_id": FOREIGN_OP,
            "status": "completed",
            "media_ids": [555],
            "committed": True,
        },
    ]


def _default_items() -> list[dict[str, Any]]:
    own = [
        {
            "run_id": RUN_ID,
            "tenant_id": OWN_TENANT,
            "media_id": media_id,
            "status": "completed",
            "tier": "final_gpu",
            "result_generation": GENERATION,
            "model_id": PINNED_MODEL,
            "caption": f"fixture caption for media {media_id}",
            "committed": True,
        }
        for media_id in MEDIA_IDS
    ]
    foreign = {
        "run_id": FOREIGN_RUN_ID,
        "tenant_id": FOREIGN_TENANT,
        "media_id": 555,
        "status": "completed",
        "tier": "final_gpu",
        "result_generation": 1,
        "model_id": OTHER_MODEL,
        "caption": "foreign fixture caption",
        "committed": True,
    }
    return [*own, foreign]


def _default_dims() -> dict[str, int]:
    return dict.fromkeys(VECTOR_KEYS, EXPECTED_DIM)


def _default_flags() -> dict[str, bool]:
    return dict.fromkeys(PROBED_TABLES, True)


def _default_operations() -> list[dict[str, Any]]:
    return [
        {"operation_id": OWN_OP, "tenant_id": OWN_TENANT, "request_digest": OWN_DIGEST, "committed": True},
        {"operation_id": FOREIGN_OP, "tenant_id": FOREIGN_TENANT, "request_digest": FOREIGN_DIGEST, "committed": True},
    ]


def _default_embedding_rows() -> list[dict[str, Any]]:
    return [
        {"table": IDENTITY_TABLE, "tenant_id": OWN_TENANT, "model": OWN_MODEL_SPACE, "committed": True},
        {"table": IDENTITY_TABLE, "tenant_id": FOREIGN_TENANT, "model": FOREIGN_MODEL_SPACE, "committed": True},
    ]


def _caption_sha(caption: str | None) -> str | None:
    return None if caption is None else hashlib.sha256(caption.encode("utf-8")).hexdigest()


@dataclass
class ClusterSpec:
    """Server-side truth the fake answers from. One factor is changed per negative case."""

    engine: str = "postgresql"
    database: str = DATABASE
    role: str = ROLE
    schema: str = SCHEMA
    server_version: str = "16.4"
    rolsuper: bool = False
    rolbypassrls: bool = False
    vector_version: str | None = "0.7.4"
    vector_dims: dict[str, int] = field(default_factory=_default_dims)
    rls_enabled: dict[str, bool] = field(default_factory=_default_flags)
    rls_forced: dict[str, bool] = field(default_factory=_default_flags)
    runs: list[dict[str, Any]] = field(default_factory=_default_runs)
    items: list[dict[str, Any]] = field(default_factory=_default_items)
    uncommitted_visible_to: frozenset[str] = frozenset()
    shared_session: bool = False
    leak_foreign_rows: bool = False
    cancel_items: bool = False
    operations: list[dict[str, Any]] = field(default_factory=_default_operations)
    embedding_rows: list[dict[str, Any]] = field(default_factory=_default_embedding_rows)


def _positive_spec() -> ClusterSpec:
    return ClusterSpec()


class FakeDeadline:
    def __init__(self, remaining: float) -> None:
        self._remaining = remaining

    def remaining_seconds(self) -> float:
        return self._remaining


class FakeCluster:
    """In-memory PostgreSQL stand-in. Records every connect, statement, tenant GUC, and violation."""

    def __init__(self, spec: ClusterSpec) -> None:
        self.spec = spec
        self.connect_calls: list[dict[str, Any]] = []
        self.sessions: list[FakeSession] = []
        self.violations: list[str] = []
        self.tenant_sets: list[str | None] = []
        self._shared: FakeSession | None = None

    def violation(self, message: str) -> None:
        self.violations.append(message)

    def connect(self, **kwargs: Any) -> FakeSession:
        self.connect_calls.append(dict(kwargs))
        self._check_connect(kwargs)
        if self.spec.shared_session:
            if self._shared is None:
                self._shared = self._open(kwargs.get("session_label", ""), index=0)
            return self._shared
        return self._open(kwargs.get("session_label", ""), index=len(self.sessions))

    def _open(self, label: str, *, index: int) -> FakeSession:
        session = FakeSession(self, label, backend_pid=4100 + index, backend_start=f"2026-10-12T00:0{index}:00Z")
        self.sessions.append(session)
        return session

    def _check_connect(self, kwargs: Mapping[str, Any]) -> None:
        missing = [key for key in CONNECT_KWARGS if key not in kwargs]
        if missing:
            self.violation(f"connect missing required bounds or labels: {missing}")
        for key, cap in BOUNDS.items():
            value = kwargs.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                self.violation(f"non-finite {key}={value!r}")
            elif not 0 < value <= cap:
                self.violation(f"unbounded {key}={value!r} (cap {cap})")
        if kwargs.get("session_label") not in {PRIMARY_SESSION, INDEPENDENT_SESSION}:
            self.violation(f"unexpected session_label={kwargs.get('session_label')!r}")
        for key, value in kwargs.items():
            if isinstance(value, str) and ("://" in value or "password" in value.lower()):
                self.violation(f"secret-shaped value passed to connect as {key}")


class FakeSession:
    def __init__(self, cluster: FakeCluster, label: str, *, backend_pid: int, backend_start: str) -> None:
        self.cluster = cluster
        self.label = label
        self.backend_pid = backend_pid
        self.backend_start = backend_start
        self.statements: list[str] = []
        self.began = False
        self.ended = False
        self.closed = False
        self.current_tenant: str | None = None

    def close(self) -> None:
        self.closed = True

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> list[tuple[Any, ...]]:
        norm = " ".join(sql.split())
        upper = norm.upper()
        params = dict(params or {})
        self.statements.append(norm)
        if self.closed:
            self.cluster.violation(f"query after close: {norm}")
            raise FakeReadOnlyViolation("connection is closed")
        if upper in BEGIN_READ_ONLY:
            self.began = True
            self.ended = False
            return []
        if upper.startswith(("BEGIN", "START TRANSACTION")):
            self.cluster.violation(f"read-write transaction requested: {norm}")
            raise FakeReadOnlyViolation("transaction must be READ ONLY")
        if not self.began:
            self.cluster.violation(f"statement before BEGIN READ ONLY: {norm}")
            raise FakeReadOnlyViolation("no read-only transaction is open")
        if upper in {"ROLLBACK", "COMMIT"}:
            self.ended = True
            return []
        if self.ended:
            self.cluster.violation(f"statement after transaction end: {norm}")
            raise FakeReadOnlyViolation("transaction has ended")
        if re.fullmatch(r"SELECT CURRENT_SETTING\s*\(\s*'APP\.BYPASS_RLS'\s*,\s*TRUE\s*\)", upper):
            return [(None,)]
        if re.fullmatch(r"SELECT CURRENT_SETTING\s*\(\s*'APP\.CURRENT_TENANT'\s*,\s*TRUE\s*\)", upper):
            return [(self.current_tenant,)]
        timeout_set = re.fullmatch(
            r"SELECT SET_CONFIG\s*\(\s*'STATEMENT_TIMEOUT'\s*,\s*'([0-9]+)'\s*,\s*TRUE\s*\)", upper
        )
        if timeout_set:
            return [(timeout_set.group(1),)]
        if "APP.BYPASS_RLS" in upper:
            self.cluster.violation(f"bypass GUC attempted: {norm}")
            raise FakeReadOnlyViolation("bypass GUC is not permitted")
        if _FORBIDDEN.search(norm):
            self.cluster.violation(f"forbidden statement: {norm}")
            raise FakeReadOnlyViolation("cannot execute statement in a read-only transaction")
        if "APP.CURRENT_TENANT" in upper:
            tenant = _tenant_from(norm, params)
            self.current_tenant = tenant
            self.cluster.tenant_sets.append(tenant)
            return [] if upper.startswith("SET LOCAL") else [(tenant,)]
        if upper.startswith("SET "):
            self.cluster.violation(f"unsanctioned SET: {norm}")
            raise FakeReadOnlyViolation("only tenant-context SET LOCAL is sanctioned")
        if not upper.startswith("SELECT"):
            self.cluster.violation(f"non-SELECT statement: {norm}")
            raise FakeReadOnlyViolation("only SELECT is permitted")
        return self._select(upper, params)

    def _visible(self, table: str, row: Mapping[str, Any]) -> bool:
        spec = self.cluster.spec
        if not row["committed"] and self.label not in spec.uncommitted_visible_to:
            return False
        if spec.rolsuper or spec.rolbypassrls or spec.leak_foreign_rows or not spec.rls_enabled[table]:
            return True
        return row["tenant_id"] == self.current_tenant

    def _select(self, upper: str, params: Mapping[str, Any]) -> list[tuple[Any, ...]]:
        spec = self.cluster.spec
        ids = {str(value) for value in params.values()}
        if "CURRENT_DATABASE" in upper:
            if spec.engine != "postgresql":
                raise FakeProbeRejected("no such function: current_database")
            # (current_database, current_user, session_user, pg_backend_pid, server_version, backend_start, current_schema)
            return [
                (
                    spec.database,
                    spec.role,
                    spec.role,
                    self.backend_pid,
                    spec.server_version,
                    self.backend_start,
                    spec.schema,
                )
            ]
        if "TRANSACTION_READ_ONLY" in upper:
            # Reflects the open transaction: BEGIN READ ONLY makes it 'on' until it ends.
            return [("on" if self.began and not self.ended else "off",)]
        if "PG_HAS_ROLE" in upper:
            return [(spec.role, True)]
        if "PG_ROLES" in upper:
            return [(spec.rolsuper, spec.rolbypassrls)]
        if re.search(r"\bFROM\s+PG_INDEX\b", upper):
            return [
                (key.split(".")[-2], key.split(".")[-1], "ivfflat", "vector_cosine_ops", True, None, None)
                for key in spec.vector_dims
            ]
        if re.search(r"\bFROM\s+PG_TYPE\b", upper) and "PG_DEPEND" in upper:
            return [(SCHEMA, "vector", "vector")]
        if "PG_ATTRIBUTE" in upper:
            return [
                (key.split(".")[0], key.split(".")[-2], key.split(".")[-1], "vector", dim)
                for key, dim in spec.vector_dims.items()
            ]
        if "PG_EXTENSION" in upper:
            return [] if spec.vector_version is None else [("vector", spec.vector_version)]
        if "PG_POLICIES" in upper:
            return [
                (table, f"tenant_isolation_{table}", "ALL", ["public"], "PERMISSIVE", POLICY_EXPR, POLICY_EXPR)
                for table in PROBED_TABLES
            ]
        if "PG_CLASS" in upper:
            return [(table, spec.rls_enabled[table], spec.rls_forced[table]) for table in PROBED_TABLES]
        if "DESCRIBE_OPERATIONS" in upper:
            return [
                (row["operation_id"], row["request_digest"])
                for row in spec.operations
                if row["operation_id"] in ids and self._visible(DEMAND_TABLE, row)
            ]
        if "EMBEDDING_MODEL" in upper:
            models = sorted(
                {
                    row["model"]
                    for row in spec.embedding_rows
                    if row["table"].upper() in upper and self._visible(row["table"], row)
                }
            )
            return [(model,) for model in models]
        if "IMAGE_DESCRIPTION_RUN_ITEMS" in upper:
            if spec.cancel_items:
                raise QueryCanceled("canceling statement due to statement timeout")
            return [
                (
                    row["run_id"],
                    row["media_id"],
                    row["status"],
                    row["tier"],
                    row["result_generation"],
                    row["model_id"],  # provenance ->> 'model_id': the claim only, never the whole provenance
                    _caption_sha(row.get("caption")),
                )
                for row in spec.items
                if row["run_id"] in ids and self._visible("image_description_run_items", row)
            ]
        if "IMAGE_DESCRIPTION_RUNS" in upper:
            return [
                (row["id"], row["tenant_id"], row["operation_id"])
                for row in spec.runs
                if row["id"] in ids and self._visible("image_description_runs", row)
            ]
        self.cluster.violation(f"unrecognized SELECT shape: {upper[:100]}")
        raise FakeProbeRejected("unrecognized catalog shape")


def _tenant_from(sql: str, params: Mapping[str, Any]) -> str | None:
    for value in params.values():
        if isinstance(value, str) and _UUID.fullmatch(value):
            return value
    found = _UUID.findall(sql)
    return found[0] if found else None


def _connect_kwargs(label: str) -> dict[str, Any]:
    return {
        "session_label": label,
        "dsn_ref": SELECTION["dsn_ref"],
        "connect_timeout_s": 5.0,
        "statement_timeout_ms": 5_000,
        "lock_timeout_ms": 1_000,
        "overall_deadline_s": 60.0,
    }


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_collector() -> Callable[..., Mapping[str, Any]]:
    if not COLLECTOR_PATH.is_file():
        pytest.fail(FUTURE_ABSENT, pytrace=False)
    module = _load_module("gtmr_gpu_pg_collector", COLLECTOR_PATH)
    collect = getattr(module, "collect_pg_evidence", None)
    if not callable(collect):
        pytest.fail(f"FUTURE_API_PROPOSAL_ABSENT: {COLLECTOR_PATH.name} has no collect_pg_evidence", pytrace=False)
    return collect


def _run(spec: ClusterSpec, *, remaining_s: float = 600.0) -> tuple[Mapping[str, Any], FakeCluster]:
    return _run_abi(spec, remaining_s=remaining_s)


def _codes(result: Mapping[str, Any]) -> set[str]:
    missing, contradictions = _abi_codes(result)
    return missing | contradictions


def _assert_custody(result: Mapping[str, Any]) -> None:
    _assert_abi_envelope(result)


def _assert_bounded_read_only(cluster: FakeCluster) -> None:
    assert cluster.violations == [], cluster.violations
    assert set(cluster.tenant_sets) <= {OWN_TENANT}, cluster.tenant_sets
    for session in cluster.sessions:
        assert session.closed, f"session {session.label} left open"
        assert session.statements and session.statements[0].upper() in BEGIN_READ_ONLY, session.label


# ---- fake self-checks: pass now, no collector required (prove the fake can go red) ----

FORBIDDEN_STATEMENTS = (
    "CREATE TABLE gtmr_probe (id integer)",
    "INSERT INTO image_description_runs (id) VALUES ('00000000-0000-0000-0000-000000000000')",
    "SET LOCAL app.bypass_rls = 'true'",
    "SET app.bypass_rls = 'true'",
    "SET ROLE postgres",
    "SELECT id FROM image_description_runs FOR UPDATE",
)


@pytest.mark.parametrize("sql", FORBIDDEN_STATEMENTS)
def test_fake_session_refuses_writes_bypass_and_role_escalation(sql: str) -> None:
    cluster = FakeCluster(_positive_spec())
    session = cluster.connect(**_connect_kwargs(PRIMARY_SESSION))
    session.query("BEGIN READ ONLY")
    with pytest.raises(FakeReadOnlyViolation):
        session.query(sql)
    assert cluster.violations, sql


def test_fake_session_refuses_read_write_begin() -> None:
    cluster = FakeCluster(_positive_spec())
    session = cluster.connect(**_connect_kwargs(PRIMARY_SESSION))
    with pytest.raises(FakeReadOnlyViolation):
        session.query("BEGIN")
    assert cluster.violations


@pytest.mark.parametrize("spaced", [False, True])
def test_fake_serves_coordinator_probes_by_pattern_without_changing_claims(spaced: bool) -> None:
    cluster = FakeCluster(_positive_spec())
    session = cluster.connect(**_connect_kwargs(PRIMARY_SESSION))
    session.query("BEGIN READ ONLY")

    def query(sql: str, params: Mapping[str, Any] | None = None) -> list[tuple[Any, ...]]:
        if spaced:
            sql = sql.upper().replace("(", "( ").replace(",", " , ").replace(")", " )")
        return session.query(sql, params)

    assert query("SELECT current_setting('app.bypass_rls', true)") == [(None,)]
    assert query("SELECT current_setting('app.current_tenant', true)") == [(None,)]
    assert cluster.tenant_sets == []
    session.query(f"SET LOCAL app.current_tenant = '{OWN_TENANT}'")
    assert query("SELECT current_setting('app.current_tenant', true)") == [(OWN_TENANT,)]
    assert cluster.tenant_sets == [OWN_TENANT], "reading a claim must not reset the selected tenant"
    assert query("SELECT set_config('statement_timeout', '2500', true)") == [("2500",)]
    assert query(
        "SELECT r.id, r.tenant_id, r.operation_id FROM image_description_runs r WHERE r.id = %(run_id)s",
        {"run_id": RUN_ID},
    ) == [(RUN_ID, OWN_TENANT, OWN_OP)]
    assert query(
        "SELECT c.relname, a.attname, am.amname, op.opcname, i.indisvalid, "
        "pg_get_expr(i.indpred, i.indrelid), pg_get_expr(i.indexprs, i.indrelid) "
        "FROM pg_index i JOIN pg_am am ON true"
    ) == [
        (key.split(".")[-2], key.split(".")[-1], "ivfflat", "vector_cosine_ops", True, None, None)
        for key in VECTOR_KEYS
    ]
    assert query("SELECT n.nspname, t.typname, e.extname FROM pg_type t JOIN pg_depend d ON true") == [
        (SCHEMA, "vector", "vector")
    ]
    assert cluster.violations == []


def test_fake_rls_hides_foreign_rows_from_own_tenant_session() -> None:
    cluster = FakeCluster(_positive_spec())
    session = cluster.connect(**_connect_kwargs(PRIMARY_SESSION))
    session.query("BEGIN READ ONLY")
    session.query("SELECT set_config('app.current_tenant', %(tenant)s, true)", {"tenant": OWN_TENANT})
    own = session.query(
        "SELECT id, tenant_id, operation_id FROM image_description_runs WHERE id = %(run_id)s", {"run_id": RUN_ID}
    )
    foreign = session.query(
        "SELECT id, tenant_id, operation_id FROM image_description_runs WHERE id = %(run_id)s",
        {"run_id": FOREIGN_RUN_ID},
    )
    assert own == [(RUN_ID, OWN_TENANT, OWN_OP)]
    assert foreign == []
    assert cluster.violations == []


# ---- positive: consistent restricted sessions under the frozen ABI ----


def test_positive_independent_restricted_sessions_observe_committed_pg_evidence() -> None:
    result, cluster = _run(_positive_spec())
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    section = result["section"]
    assert section["status"] == "incomplete"
    assert section["contradictions"] == []
    assert _abi_codes(result)[0] == {FOREIGN_UNWITNESSED, FIRST_REVISION_UNPERSISTED, EMBEDDING_MODELS_UNAVAILABLE}
    obs = {o["observation_id"]: o["data"] for o in section["observations"]}
    for label in (PRIMARY_SESSION, INDEPENDENT_SESSION):
        data = obs[f"pg:connection:{label}"]
        assert data["database"] == DATABASE
        assert data["current_user"] == ROLE and data["session_user"] == ROLE
        assert data["rolsuper"] is False and data["rolbypassrls"] is False
        assert data["app_bypass_rls"] is False
        assert data["tenant_context"] == OWN_TENANT
    catalog = obs["pg:catalog:primary"]
    assert catalog["extension_name"] == "vector" and catalog["extension_version"] == "0.7.4"
    assert {(v["schema"], v["table"], v["column"], v["atttypmod"]) for v in catalog["vectors"]} == {
        ("public", "media_identities", "embedding", EXPECTED_DIM),
        ("public", "identity_cluster_representatives", "embedding", EXPECTED_DIM),
        ("public", "mv_identity_cluster_centroids", "centroid", EXPECTED_DIM),
    }
    assert {r["table"] for r in catalog["rls"]} == set(PROBED_TABLES)
    assert all(r["enabled"] is True and r["forced"] is True for r in catalog["rls"])
    for label in (PRIMARY_SESSION, INDEPENDENT_SESSION):
        visibility = [obs[f"pg:visibility:{label}:media-{media_id}"] for media_id in MEDIA_IDS]
        assert {data["media_id"] for data in visibility} == set(MEDIA_IDS)
        for data in visibility:
            assert data["run_id"] == RUN_ID and data["tenant_id"] == OWN_TENANT
            assert data["operation_id"] == OWN_OP and data["request_digest"] == OWN_DIGEST
            assert data["own_output_rows"] == 1 and data["foreign_output_rows"] == 0
            assert data["own_demand_rows"] == 1 and data["foreign_demand_rows"] == 0
            assert data["result_generation"] == GENERATION
            assert data["caption_sha256"] == _caption_sha(f"fixture caption for media {data['media_id']}")
        receipt = json.loads(result["raw_artifacts"][f"raw/pg/{label}.json"])
        queries = {q["query_id"]: q for q in receipt["queries"]}
        assert queries["identity"]["rows"][0][4] == "16.4"
        assert queries["run-own"]["rows"] == [[RUN_ID, OWN_TENANT, OWN_OP]]
        assert {tuple(row[2:6]) for row in queries["output-own"]["rows"]} == {
            ("completed", "final_gpu", GENERATION, PINNED_MODEL)
        }
        assert queries["app-bypass"]["rows"] == [[None]]


def test_positive_two_distinct_sessions_end_read_only_and_never_impersonate() -> None:
    result, cluster = _run(_positive_spec())
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    assert result["section"]["status"] == "incomplete"
    assert [session.label for session in cluster.sessions] == [PRIMARY_SESSION, INDEPENDENT_SESSION]
    assert len({session.backend_pid for session in cluster.sessions}) == 2
    assert len({session.backend_start for session in cluster.sessions}) == 2
    assert all(session.ended for session in cluster.sessions), "each read-only transaction must end before close"
    assert set(cluster.tenant_sets) == {OWN_TENANT}, "tenant context may only be the selected own tenant"
    assert all(set(call) >= set(CONNECT_KWARGS) for call in cluster.connect_calls)
    assert all(call["dsn_ref"] == SELECTION["dsn_ref"] for call in cluster.connect_calls)


# ---- one-factor negatives: each differs from the positive by exactly one factor ----


def _uncommitted(spec: ClusterSpec) -> ClusterSpec:
    runs = [{**row, "committed": row["committed"] and row["id"] != RUN_ID} for row in spec.runs]
    items = [{**row, "committed": row["committed"] and row["run_id"] != RUN_ID} for row in spec.items]
    return replace(spec, runs=runs, items=items, uncommitted_visible_to=frozenset({PRIMARY_SESSION}))


def _mixed_dims(spec: ClusterSpec) -> ClusterSpec:
    dims = dict(spec.vector_dims)
    dims["public.identity_cluster_representatives.embedding"] = 128
    return replace(spec, vector_dims=dims)


def _mixed_output_models(spec: ClusterSpec) -> ClusterSpec:
    items = [{**row, "model_id": OTHER_MODEL} if row["media_id"] == MEDIA_IDS[1] else row for row in spec.items]
    return replace(spec, items=items)


def _force_off_items(spec: ClusterSpec) -> ClusterSpec:
    return replace(spec, rls_forced={**spec.rls_forced, "image_description_run_items": False})


# (change, expected status, expected codes). Missing visibility is incomplete; measured conflicts contradict.
NEGATIVE_CASES = [
    pytest.param(
        lambda s: replace(s, database="alt_context_prod"), "contradicted", (WRONG_DATABASE,), id="wrong-database"
    ),
    pytest.param(lambda s: replace(s, engine="sqlite"), "contradicted", (NOT_POSTGRESQL,), id="sqlite-engine"),
    pytest.param(lambda s: replace(s, rolsuper=True), "contradicted", (SUPERUSER_ROLE,), id="superuser-role"),
    pytest.param(lambda s: replace(s, rolbypassrls=True), "contradicted", (BYPASSRLS_ROLE,), id="bypassrls-role"),
    pytest.param(_force_off_items, "contradicted", (RLS_NOT_FORCED,), id="force-rls-disabled-on-items"),
    pytest.param(_uncommitted, "incomplete", (NOT_VISIBLE_INDEPENDENT,), id="uncommitted-not-visible-to-independent"),
    pytest.param(
        lambda s: replace(s, leak_foreign_rows=True),
        "contradicted",
        (FOREIGN_TENANT_VISIBLE,),
        id="foreign-tenant-visible",
    ),
    pytest.param(_mixed_dims, "contradicted", (MIXED_EMBEDDING_SPACES,), id="mixed-embedding-spaces"),
    pytest.param(
        _mixed_output_models, "contradicted", (MIXED_OUTPUT_MODELS, OUTPUT_MODEL_MISMATCH), id="mixed-output-models"
    ),
]


@pytest.mark.parametrize(("change", "expected_status", "expected_codes"), NEGATIVE_CASES)
def test_one_factor_negative_refuses_to_observe(
    change: Callable[[ClusterSpec], ClusterSpec], expected_status: str, expected_codes: tuple[str, ...]
) -> None:
    result, cluster = _run(change(_positive_spec()))
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    section = result["section"]
    assert section["status"] == expected_status, (section["status"], sorted(_codes(result)))
    assert set(expected_codes) <= _codes(result), (expected_codes, sorted(_codes(result)))
    if expected_status == "incomplete":
        assert not section["contradictions"], "a missing join must not also be reported as a contradiction"
    else:
        assert section["contradictions"], "a contradiction must be reported as contradicted, not as a missing join"


def test_shared_session_for_both_labels_is_refused_as_not_independent() -> None:
    result, cluster = _run(replace(_positive_spec(), shared_session=True))
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    assert len(cluster.sessions) == 1
    assert result["section"]["status"] == "incomplete"
    assert SESSION_NOT_INDEPENDENT in _codes(result)


def test_statement_timeout_is_incomplete_and_every_session_closes() -> None:
    result, cluster = _run(replace(_positive_spec(), cancel_items=True))
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    assert result["section"]["status"] == "incomplete"
    assert STATEMENT_TIMEOUT in _codes(result)


def test_exhausted_overall_deadline_connects_nothing() -> None:
    result, cluster = _run(_positive_spec(), remaining_s=0.0)
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    assert cluster.connect_calls == []
    assert result["section"]["status"] == "incomplete"
    assert DEADLINE_EXHAUSTED in _codes(result)
    assert result["raw_artifacts"] == {} and result["artifacts"] == []


# ======================================================================================================
# Frozen ABI v1 section ``pg``. All collector selectors assert the frozen envelope
# {section: {status, observations, missing_reasons, contradictions}, artifacts, raw_artifacts: dict}.
# Explicit gaps are named, not hidden: foreign existence needs an independent witness,
# non-media embedding models are unobserved, and first_counting_revision is not
# persisted by the native producer (scene/tests/test_gtmr_demand_load_joins.py::test_red_committed_operation...).
# ======================================================================================================

ABI_SELECTION: dict[str, Any] = {**SELECTION, "operation_id": OWN_OP, "foreign_operation_id": FOREIGN_OP}
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

APP_BYPASS_UNPROBED = "app_bypass_rls_unprobed"
FOREIGN_UNWITNESSED = "foreign_existence_unwitnessed"
FIRST_REVISION_UNPERSISTED = "first_counting_revision_unpersisted"
EMBEDDING_MODELS_UNAVAILABLE = "embedding_models_unavailable"
MIXED_EMBEDDING_MODELS = "mixed_embedding_models"
VECTOR_DIMENSION_MISMATCH = "vector_dimension_mismatch"
ROW_BUDGET_EXCEEDED = "row_budget_exceeded"
SELECTION_FIELD_MISSING = "selection_field_missing"
SELECTION_FIELD_INVALID = "selection_field_invalid"
BYPASSRLS_ROLE_CODE = "bypassrls_role"
SUPERUSER_ROLE_CODE = "superuser_role"
RLS_NOT_FORCED_CODE = "rls_not_forced"
FOREIGN_VISIBLE_CODE = "foreign_tenant_visible"


def _run_abi(
    spec: ClusterSpec, *, selection: Mapping[str, Any] | None = None, remaining_s: float = 600.0
) -> tuple[Mapping[str, Any], FakeCluster]:
    collect = _load_collector()
    cluster = FakeCluster(spec)
    chosen = dict(ABI_SELECTION if selection is None else selection)
    result = collect(connect=cluster.connect, selection=chosen, deadline=FakeDeadline(remaining_s))
    _assert_abi_envelope(result)
    return result, cluster


def _abi_codes(result: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    section = result["section"]
    assert isinstance(section, Mapping)
    return ({i["code"] for i in section["missing_reasons"]}, {i["code"] for i in section["contradictions"]})


def _observations(result: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    return [o["data"] for o in result["section"]["observations"] if o["kind"] == kind]


def _assert_abi_envelope(result: Mapping[str, Any]) -> None:
    """Frozen ABI v1 invariants for section ``pg``. Shape only; semantic oracles live in the tests."""
    assert set(result) == {"section", "artifacts", "raw_artifacts"}
    section = result["section"]
    assert isinstance(section, Mapping)
    assert set(section) == {"status", "observations", "missing_reasons", "contradictions"}
    assert section["status"] in ABI_STATUSES
    assert isinstance(section["observations"], list)
    assert isinstance(section["missing_reasons"], list) and isinstance(section["contradictions"], list)
    assert isinstance(result["artifacts"], list)
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
    # Frozen ABI: every null measurement needs a missing reason in the same section, scoped to its connection
    # (or to the catalog). A null without a reason is an unexplained gap that G1 must not accept.
    missing_fields = [issue["field"] for issue in section["missing_reasons"]]
    for obs in section["observations"]:
        nulls = [key for key, value in obs["data"].items() if value is None]
        if nulls:
            scope = obs["data"].get("connection_id")
            assert any(scope in name or name.startswith("catalog.") for name in missing_fields), (
                obs["observation_id"],
                nulls,
            )
    # Contradictions take precedence over missing reasons.
    if section["contradictions"]:
        assert section["status"] == "contradicted"
    elif section["missing_reasons"]:
        assert section["status"] == "incomplete"
    else:
        assert section["status"] == "complete"


# ---- fake self-checks for the probes the collector depends on (pass now; no collector required) ----


def test_fake_reports_identity_and_read_only_state_of_its_own_transaction() -> None:
    cluster = FakeCluster(_positive_spec())
    session = cluster.connect(**_connect_kwargs(PRIMARY_SESSION))
    session.query("BEGIN READ ONLY")
    row = session.query("SELECT current_database(), current_user, session_user, pg_backend_pid()")[0]
    assert row[0] == DATABASE and row[1] == ROLE and row[2] == ROLE and row[3] == session.backend_pid
    assert session.query("SELECT current_setting('transaction_read_only')") == [("on",)]
    session.query("ROLLBACK")
    with pytest.raises(FakeReadOnlyViolation):
        session.query("SELECT current_setting('transaction_read_only')")
    assert cluster.violations, "a statement after the transaction ended is not a read-only probe"


def test_fake_scopes_demand_and_embedding_rows_to_the_selected_tenant() -> None:
    cluster = FakeCluster(_positive_spec())
    session = cluster.connect(**_connect_kwargs(INDEPENDENT_SESSION))
    session.query("BEGIN READ ONLY")
    session.query(f"SET LOCAL app.current_tenant = '{OWN_TENANT}'")
    own = session.query(
        "SELECT d.operation_id, d.request_digest FROM describe_operations d WHERE d.operation_id = %(operation_id)s",
        {"operation_id": OWN_OP},
    )
    foreign = session.query(
        "SELECT d.operation_id, d.request_digest FROM describe_operations d WHERE d.operation_id = %(operation_id)s",
        {"operation_id": FOREIGN_OP},
    )
    models = session.query("SELECT DISTINCT m.embedding_model FROM media_identities m ORDER BY m.embedding_model")
    assert own == [(OWN_OP, OWN_DIGEST)]
    assert foreign == []
    assert models == [(OWN_MODEL_SPACE,)], "foreign tenant's embedding space must not be visible"
    assert cluster.violations == []


# ---- ABI selectors: independent connections, bypass, foreign witness, uncommitted rows, mixed spaces ----


def test_pg_collector_uses_independent_read_only_connections() -> None:
    result, cluster = _run_abi(_positive_spec())
    _assert_abi_envelope(result)
    _assert_bounded_read_only(cluster)
    assert [s.label for s in cluster.sessions] == [PRIMARY_SESSION, INDEPENDENT_SESSION]
    assert len({s.backend_pid for s in cluster.sessions}) == 2, "backend PIDs must prove connection independence"
    assert len({s.backend_start for s in cluster.sessions}) == 2
    assert all(s.ended for s in cluster.sessions), "each read-only transaction must end before close"
    assert all(set(call) == set(CONNECT_KWARGS) for call in cluster.connect_calls)
    assert all(call["dsn_ref"] == SELECTION["dsn_ref"] for call in cluster.connect_calls)
    for key, cap in BOUNDS.items():
        assert all(0 < call[key] <= cap for call in cluster.connect_calls), key
    assert set(cluster.tenant_sets) == {OWN_TENANT}, "tenant selection is only the selected own tenant"
    connections = {c["connection_id"]: c for c in _observations(result, "connection")}
    assert set(connections) == {PRIMARY_SESSION, INDEPENDENT_SESSION}
    for session in cluster.sessions:
        data = connections[session.label]
        assert data["backend_pid"] == session.backend_pid
        assert data["database"] == DATABASE
        assert data["current_user"] == ROLE and data["session_user"] == ROLE
        assert data["transaction_read_only"] is True
        assert data["tenant_context"] == OWN_TENANT
        assert data["rolsuper"] is False and data["rolbypassrls"] is False
    assert set(result["raw_artifacts"]) == {
        "raw/pg/primary-restricted-reader.json",
        "raw/pg/independent-restricted-verifier.json",
    }


def test_pg_collector_positive_is_incomplete_with_only_the_named_gaps() -> None:
    result, cluster = _run_abi(_positive_spec())
    _assert_abi_envelope(result)
    _assert_bounded_read_only(cluster)
    missing, contradictions = _abi_codes(result)
    assert contradictions == set(), result["section"]["contradictions"]
    assert result["section"]["status"] == "incomplete", "no positive path can be complete under the frozen ABI gaps"
    assert missing == {
        FOREIGN_UNWITNESSED,
        FIRST_REVISION_UNPERSISTED,
        EMBEDDING_MODELS_UNAVAILABLE,
    }
    catalog = _observations(result, "catalog")[0]
    assert {row["table"] for row in catalog["rls"]} == set(PROBED_TABLES)
    visibility = _observations(result, "visibility")
    for connection in (PRIMARY_SESSION, INDEPENDENT_SESSION):
        rows = [d for d in visibility if d["connection_id"] == connection]
        assert {d["media_id"] for d in rows} == set(MEDIA_IDS)
        for data in rows:
            assert data["own_output_rows"] == 1 and data["own_demand_rows"] == 1
            assert data["result_generation"] == GENERATION
            assert data["request_digest"] == OWN_DIGEST
            assert H64.fullmatch(data["caption_sha256"]), data
            assert data["first_counting_revision"] is None


def test_pg_collector_scopes_embedding_models_to_the_own_tenant() -> None:
    result, cluster = _run_abi(_positive_spec())
    _assert_bounded_read_only(cluster)
    vectors = {(v["table"], v["column"]): v for c in _observations(result, "catalog") for v in c["vectors"]}
    assert vectors[("media_identities", "embedding")]["embedding_models"] == [OWN_MODEL_SPACE]
    assert vectors[("media_identities", "embedding")]["atttypmod"] == EXPECTED_DIM
    assert vectors[("mv_identity_cluster_centroids", "centroid")]["embedding_models"] is None


@pytest.mark.parametrize(
    ("change", "code"),
    [
        pytest.param(lambda s: replace(s, rolbypassrls=True), BYPASSRLS_ROLE_CODE, id="role-bypassrls"),
        pytest.param(lambda s: replace(s, rolsuper=True), SUPERUSER_ROLE_CODE, id="role-superuser"),
        pytest.param(lambda s: replace(s, leak_foreign_rows=True), FOREIGN_VISIBLE_CODE, id="effective-rls-bypass"),
        pytest.param(
            lambda s: replace(s, rls_enabled={**s.rls_enabled, "image_description_run_items": False}),
            FOREIGN_VISIBLE_CODE,
            id="effective-rls-bypass-output-only",
        ),
        pytest.param(_force_off_items, RLS_NOT_FORCED_CODE, id="table-owner-not-forced"),
    ],
)
def test_pg_collector_rejects_app_bypass_rls(change: Callable[[ClusterSpec], ClusterSpec], code: str) -> None:
    result, cluster = _run_abi(change(_positive_spec()))
    _assert_abi_envelope(result)
    _assert_bounded_read_only(cluster)
    missing, contradictions = _abi_codes(result)
    assert result["section"]["status"] == "contradicted", (sorted(missing), sorted(contradictions))
    assert code in contradictions
    assert APP_BYPASS_UNPROBED not in missing
    for data in _observations(result, "connection"):
        assert data["app_bypass_rls"] is False
        receipt = json.loads(result["raw_artifacts"][f"raw/pg/{data['connection_id']}.json"])
        assert any(q["query_id"] == "app-bypass" and q["rows"] == [[None]] for q in receipt["queries"])


def _without_foreign_rows(spec: ClusterSpec) -> ClusterSpec:
    return replace(
        spec,
        operations=[row for row in spec.operations if row["tenant_id"] != FOREIGN_TENANT],
        items=[row for row in spec.items if row["run_id"] != FOREIGN_RUN_ID],
    )


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda s: s, id="foreign-rows-exist-but-rls-hidden"),
        pytest.param(_without_foreign_rows, id="no-foreign-rows-at-all"),
    ],
)
def test_pg_collector_requires_foreign_existence_witness(change: Callable[[ClusterSpec], ClusterSpec]) -> None:
    result, cluster = _run_abi(change(_positive_spec()))
    _assert_abi_envelope(result)
    _assert_bounded_read_only(cluster)
    missing, contradictions = _abi_codes(result)
    assert contradictions == set(), "zero foreign rows are unwitnessed, not a contradiction"
    assert result["section"]["status"] == "incomplete"
    assert FOREIGN_UNWITNESSED in missing, "zero foreign rows without a foreign existence witness prove nothing"
    visibility = _observations(result, "visibility")
    assert visibility
    for data in visibility:
        assert data["foreign_witness_refs"] == []
        assert data["foreign_output_rows"] == 0 and data["foreign_demand_rows"] == 0


def _uncommitted_abi(spec: ClusterSpec) -> ClusterSpec:
    base = _uncommitted(spec)
    operations = [{**row, "committed": row["committed"] and row["operation_id"] != OWN_OP} for row in spec.operations]
    return replace(base, operations=operations)


def test_pg_collector_refuses_uncommitted_visibility() -> None:
    result, cluster = _run_abi(_uncommitted_abi(_positive_spec()))
    _assert_abi_envelope(result)
    _assert_bounded_read_only(cluster)
    missing, contradictions = _abi_codes(result)
    assert result["section"]["status"] == "incomplete"
    assert contradictions == set()
    assert NOT_VISIBLE_INDEPENDENT in missing
    # An absent committed row leaves result_generation and caption_sha256 null: each null has a named reason.
    assert {"output_row_not_visible", "demand_row_not_visible"} <= missing
    by_connection: dict[str, list[dict[str, Any]]] = {}
    for data in _observations(result, "visibility"):
        by_connection.setdefault(data["connection_id"], []).append(data)
    assert by_connection.get(INDEPENDENT_SESSION), "the independent verifier must report"
    for data in by_connection[INDEPENDENT_SESSION]:
        assert data["own_output_rows"] == 0 and data["own_demand_rows"] == 0, "uncommitted rows are not committed"
    for data in by_connection.get(PRIMARY_SESSION, []):
        assert data["own_output_rows"] == 1, "primary-only visibility is observed, never counted as committed"


def _mixed_models(spec: ClusterSpec) -> ClusterSpec:
    extra = {"table": IDENTITY_TABLE, "tenant_id": OWN_TENANT, "model": "fixture-embed-own-v2", "committed": True}
    return replace(spec, embedding_rows=[*spec.embedding_rows, extra])


@pytest.mark.parametrize(
    ("change", "codes"),
    [
        pytest.param(_mixed_dims, (MIXED_EMBEDDING_SPACES, VECTOR_DIMENSION_MISMATCH), id="vector-dimension-mismatch"),
        pytest.param(_mixed_models, (MIXED_EMBEDDING_MODELS, MIXED_EMBEDDING_SPACES), id="two-models-in-own-space"),
    ],
)
def test_pg_collector_rejects_mixed_embedding_spaces(
    change: Callable[[ClusterSpec], ClusterSpec], codes: tuple[str, ...]
) -> None:
    result, cluster = _run_abi(change(_positive_spec()))
    _assert_abi_envelope(result)
    _assert_bounded_read_only(cluster)
    _, contradictions = _abi_codes(result)
    assert result["section"]["status"] == "contradicted"
    assert set(codes) <= contradictions, sorted(contradictions)


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        pytest.param(lambda s: {k: v for k, v in s.items() if k != "run_id"}, "run_id", id="missing-run-id"),
        pytest.param(lambda s: {**s, "dsn_ref": "postgresql://user:pw@host/db"}, "dsn_ref", id="dsn-shaped-ref"),
        pytest.param(lambda s: {**s, "tenant_id": "not-a-uuid"}, "tenant_id", id="malformed-tenant"),
    ],
)
def test_pg_collector_rejects_malformed_selection_without_connecting(
    mutate: Callable[[dict[str, Any]], dict[str, Any]], field: str
) -> None:
    collect = _load_collector()
    cluster = FakeCluster(_positive_spec())
    result = collect(connect=cluster.connect, selection=mutate(dict(ABI_SELECTION)), deadline=FakeDeadline(600.0))
    _assert_abi_envelope(result)
    assert cluster.connect_calls == [], "a selection that is not a capture instruction must not open sessions"
    assert result["section"]["status"] == "incomplete"
    assert field in {issue["field"] for issue in result["section"]["missing_reasons"]}
    assert result["raw_artifacts"] == {} and result["artifacts"] == []


def test_pg_collector_exhausted_deadline_connects_nothing_abi() -> None:
    result, cluster = _run_abi(_positive_spec(), remaining_s=0.0)
    _assert_abi_envelope(result)
    assert cluster.connect_calls == []
    assert result["section"]["status"] == "incomplete"
    assert DEADLINE_EXHAUSTED in _abi_codes(result)[0]
    assert result["artifacts"] == [] and result["raw_artifacts"] == {}


def test_pg_collector_statement_timeout_is_incomplete_and_every_session_closes_abi() -> None:
    result, cluster = _run_abi(replace(_positive_spec(), cancel_items=True))
    _assert_abi_envelope(result)
    _assert_bounded_read_only(cluster)
    assert all(s.ended and s.closed for s in cluster.sessions)
    assert result["section"]["status"] == "incomplete"
    assert STATEMENT_TIMEOUT in _abi_codes(result)[0]


def test_pg_collector_shared_session_is_refused_as_not_independent_abi() -> None:
    result, cluster = _run_abi(replace(_positive_spec(), shared_session=True))
    _assert_abi_envelope(result)
    _assert_bounded_read_only(cluster)
    assert len(cluster.sessions) == 1
    assert result["section"]["status"] == "incomplete"
    assert SESSION_NOT_INDEPENDENT in _abi_codes(result)[0]


def test_pg_collector_bounds_row_budget_and_reports_truncation() -> None:
    flood = [
        {
            "run_id": RUN_ID,
            "tenant_id": OWN_TENANT,
            "media_id": 2_000 + index,
            "status": "completed",
            "tier": "final_gpu",
            "result_generation": GENERATION,
            "model_id": PINNED_MODEL,
            "caption": None,
            "committed": True,
        }
        for index in range(250)
    ]
    result, cluster = _run_abi(replace(_positive_spec(), items=[*_default_items(), *flood]))
    _assert_abi_envelope(result)
    _assert_bounded_read_only(cluster)
    missing, contradictions = _abi_codes(result)
    assert ROW_BUDGET_EXCEEDED in missing, "proven truncation is incomplete, never a silent partial read"
    assert contradictions == set()
    assert result["section"]["status"] == "incomplete"


def test_pg_collector_never_serializes_dsn_or_credentials() -> None:
    result, _ = _run_abi(_positive_spec())
    blob = b"".join(result["raw_artifacts"].values())
    assert b"://" not in blob
    assert b"password" not in blob.lower()
    assert b"Authorization" not in blob
    assert SELECTION["dsn_ref"].encode("utf-8") in blob, "the DSN reference (not the DSN) is recorded"
