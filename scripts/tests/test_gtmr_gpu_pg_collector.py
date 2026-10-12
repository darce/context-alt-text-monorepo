"""G4 restricted-PostgreSQL collector: offline fake-driven authoring.

Owner: GTMR G4. Target module: ``scripts/collect_gpu_pg_evidence.py`` (not implemented here).
Scope: in-memory fakes only. No live database, DSN, credential, bootstrap, or GPU action.

Classification
--------------
* ``test_fake_*`` exercise only this module's fake. They pass now and show that the fake
  refuses writes, bypass GUCs, role escalation, read-write transactions, and foreign-tenant
  reads. A green collector result is only meaningful if the fake can go red.
* Every other test calls the proposed ``collect_pg_evidence``. While that module is absent
  they fail with ``FUTURE_API_PROPOSAL_ABSENT``. That is proposal coverage for the G4
  interface, not a causal defect in existing production code.

Proposed interface under test
-----------------------------
``collect_pg_evidence(*, connect, selection, deadline) -> mapping`` with keys
``section`` ("pg"), ``status`` ("observed" | "incomplete" | "invalid"), ``reason_code``,
``contradictions`` (list), ``missing_reasons`` (list), ``observations`` (mapping), and
``raw_artifacts`` (list of ``{relative_path, sha256, content: bytes}``).

* ``connect(*, session_label, dsn_ref, connect_timeout_s, statement_timeout_ms, lock_timeout_ms,
  overall_deadline_s)`` returns a session exposing ``query(sql, params) -> list[tuple]`` and ``close()``.
  The connect call receives only a DSN reference, never a DSN value.
* ``deadline.remaining_seconds() -> float``.
* Observation wrappers follow the existing consumer schema in
  ``apps/prototype-description-service/scripts/validate_fir_dev_runtime.py``:
  ``{"provenance": "database_catalog", "value": ...}``.

Status rule: any contradiction -> ``invalid``; any missing join -> ``incomplete``; otherwise ``observed``.

Observation keys asserted by the positive case (proposal names, semantics are the contract):
``identity`` (database_name, role), ``server_version``, ``extension_versions``, ``vector_column_inventory``
(discovery_complete + per-column dimension), ``role_flags`` (rolsuper, rolbypassrls), ``rls`` (per table
relrowsecurity/relforcerowsecurity), ``sessions`` (two distinct backend pid/start), ``isolation``
(own and foreign run rows), ``committed_rows`` (run, media, tier, model, generation), ``durability``
(independent session saw the committed rows). Every value is a ``database_catalog`` wrapper.
"""

from __future__ import annotations

import hashlib
import importlib.util
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

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|VACUUM|MERGE|REINDEX|CLUSTER)\b"
    r"|\bINTO\b|\bFOR\s+(UPDATE|SHARE|NO\s+KEY|KEY\s+SHARE)\b|\bSET\s+ROLE\b|\bSESSION\s+AUTHORIZATION\b|\bRESET\b",
    re.IGNORECASE,
)


class FakeReadOnlyViolation(Exception):  # noqa: N818 - mirrors psycopg ReadOnlySqlTransaction
    """Mirrors psycopg ReadOnlySqlTransaction for a write, bypass, or role escalation attempt."""


class FakeProbeRejected(Exception):  # noqa: N818 - probe the engine rejects, not a psycopg name
    """A catalog probe the target engine cannot answer, e.g. current_database() on SQLite."""


class QueryCanceled(Exception):  # noqa: N818 - mirrors psycopg.errors.QueryCanceled
    """Mirrors psycopg.errors.QueryCanceled for statement_timeout."""


def _default_runs() -> list[dict[str, Any]]:
    return [
        {"id": RUN_ID, "tenant_id": OWN_TENANT, "status": "completed", "media_ids": list(MEDIA_IDS), "committed": True},
        {
            "id": FOREIGN_RUN_ID,
            "tenant_id": FOREIGN_TENANT,
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
        "committed": True,
    }
    return [*own, foreign]


def _default_dims() -> dict[str, int]:
    return dict.fromkeys(VECTOR_KEYS, EXPECTED_DIM)


def _default_flags() -> dict[str, bool]:
    return dict.fromkeys(RLS_TABLES, True)


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
            return [(spec.database, spec.role, self.backend_pid, spec.server_version, self.backend_start, spec.schema)]
        if "PG_ROLES" in upper:
            return [(spec.rolsuper, spec.rolbypassrls)]
        if "PG_EXTENSION" in upper:
            return [] if spec.vector_version is None else [("vector", spec.vector_version)]
        if "PG_POLICIES" in upper:
            return [(table, f"tenant_isolation_{table}", "PERMISSIVE", "ALL") for table in RLS_TABLES]
        if "PG_ATTRIBUTE" in upper:
            return [(key.split(".")[-2], key.split(".")[-1], dim) for key, dim in spec.vector_dims.items()]
        if "PG_CLASS" in upper:
            return [(table, spec.rls_enabled[table], spec.rls_forced[table]) for table in RLS_TABLES]
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
                    {"model_id": row["model_id"]},
                )
                for row in spec.items
                if row["run_id"] in ids and self._visible("image_description_run_items", row)
            ]
        if "IMAGE_DESCRIPTION_RUNS" in upper:
            return [
                (row["id"], row["tenant_id"], row["status"], row["media_ids"])
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
    collect = _load_collector()
    cluster = FakeCluster(spec)
    result = collect(connect=cluster.connect, selection=dict(SELECTION), deadline=FakeDeadline(remaining_s))
    return result, cluster


def _wrap(value: Any) -> dict[str, Any]:
    return {"provenance": "database_catalog", "value": value}


def _codes(result: Mapping[str, Any]) -> set[str]:
    raw = [result.get("reason_code"), *result.get("contradictions", []), *result.get("missing_reasons", [])]
    return {code for code in raw if isinstance(code, str)}


def _assert_custody(result: Mapping[str, Any]) -> None:
    assert result["section"] == "pg"
    assert result["status"] in {"observed", "incomplete", "invalid"}
    assert isinstance(result["raw_artifacts"], list)
    for artifact in result["raw_artifacts"]:
        path = PurePosixPath(artifact["relative_path"])
        assert not path.is_absolute() and ".." not in path.parts and path.parts[0] == "pg", artifact["relative_path"]
        assert isinstance(artifact["content"], bytes)
        assert hashlib.sha256(artifact["content"]).hexdigest() == artifact["sha256"], artifact["relative_path"]


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


def test_fake_rls_hides_foreign_rows_from_own_tenant_session() -> None:
    cluster = FakeCluster(_positive_spec())
    session = cluster.connect(**_connect_kwargs(PRIMARY_SESSION))
    session.query("BEGIN READ ONLY")
    session.query("SELECT set_config('app.current_tenant', %(tenant)s, true)", {"tenant": OWN_TENANT})
    own = session.query("SELECT id, tenant_id FROM image_description_runs WHERE id = %(run_id)s", {"run_id": RUN_ID})
    foreign = session.query(
        "SELECT id, tenant_id FROM image_description_runs WHERE id = %(run_id)s", {"run_id": FOREIGN_RUN_ID}
    )
    assert [row[0] for row in own] == [RUN_ID]
    assert foreign == []
    assert cluster.violations == []


# ---- positive: consistent restricted sessions (proposal under test) ----


def test_positive_independent_restricted_sessions_observe_committed_pg_evidence() -> None:
    result, cluster = _run(_positive_spec())
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    assert result["status"] == "observed", (
        result["status"],
        result["reason_code"],
        result["contradictions"],
        result["missing_reasons"],
    )
    assert result["reason_code"] is None
    assert result["contradictions"] == []
    assert result["missing_reasons"] == []

    obs = result["observations"]
    assert obs["identity"]["database_name"] == _wrap(DATABASE)
    assert obs["identity"]["role"] == _wrap(ROLE)
    assert obs["server_version"] == _wrap("16.4")
    assert obs["extension_versions"] == _wrap({"vector": "0.7.4"})
    assert obs["role_flags"] == _wrap({"rolsuper": False, "rolbypassrls": False})
    inventory = obs["vector_column_inventory"]
    assert inventory["discovery_complete"] is True
    assert {(i["schema"], i["table"], i["column"], i["dimension"]) for i in inventory["value"]} == {
        ("public", "media_identities", "embedding", EXPECTED_DIM),
        ("public", "identity_cluster_representatives", "embedding", EXPECTED_DIM),
        ("public", "mv_identity_cluster_centroids", "centroid", EXPECTED_DIM),
    }
    for table in RLS_TABLES:
        assert obs["rls"]["value"][table] == {"relrowsecurity": True, "relforcerowsecurity": True}, table
    assert obs["isolation"]["value"] == {"own_tenant_run_rows": 1, "foreign_tenant_run_rows": 0}
    committed = obs["committed_rows"]["value"]
    assert committed["run_id"] == RUN_ID
    assert sorted(item["media_id"] for item in committed["items"]) == sorted(MEDIA_IDS)
    assert {item["tier"] for item in committed["items"]} == {"final_gpu"}
    assert {item["model_id"] for item in committed["items"]} == {PINNED_MODEL}
    assert {item["result_generation"] for item in committed["items"]} == {GENERATION}
    assert obs["durability"]["value"]["independent_session_saw_committed_rows"] is True


def test_positive_two_distinct_sessions_end_read_only_and_never_impersonate() -> None:
    result, cluster = _run(_positive_spec())
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    assert result["status"] == "observed"
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


# (change, expected status, expected codes). Contradictions are invalid. The missing durability join is
# incomplete. Neither may be downgraded to observed.
NEGATIVE_CASES = [
    pytest.param(lambda s: replace(s, database="alt_context_prod"), "invalid", (WRONG_DATABASE,), id="wrong-database"),
    pytest.param(lambda s: replace(s, engine="sqlite"), "invalid", (NOT_POSTGRESQL,), id="sqlite-engine"),
    pytest.param(lambda s: replace(s, rolsuper=True), "invalid", (SUPERUSER_ROLE,), id="superuser-role"),
    pytest.param(lambda s: replace(s, rolbypassrls=True), "invalid", (BYPASSRLS_ROLE,), id="bypassrls-role"),
    pytest.param(_force_off_items, "invalid", (RLS_NOT_FORCED,), id="force-rls-disabled-on-items"),
    pytest.param(_uncommitted, "incomplete", (NOT_VISIBLE_INDEPENDENT,), id="uncommitted-not-visible-to-independent"),
    pytest.param(
        lambda s: replace(s, leak_foreign_rows=True), "invalid", (FOREIGN_TENANT_VISIBLE,), id="foreign-tenant-visible"
    ),
    pytest.param(_mixed_dims, "invalid", (MIXED_EMBEDDING_SPACES,), id="mixed-embedding-spaces"),
    pytest.param(
        _mixed_output_models, "invalid", (MIXED_OUTPUT_MODELS, OUTPUT_MODEL_MISMATCH), id="mixed-output-models"
    ),
]


@pytest.mark.parametrize(("change", "expected_status", "expected_codes"), NEGATIVE_CASES)
def test_one_factor_negative_refuses_to_observe(
    change: Callable[[ClusterSpec], ClusterSpec], expected_status: str, expected_codes: tuple[str, ...]
) -> None:
    result, cluster = _run(change(_positive_spec()))
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    assert result["status"] == expected_status, (result["status"], sorted(_codes(result)))
    assert set(expected_codes) <= _codes(result), (expected_codes, sorted(_codes(result)))
    if expected_status == "incomplete":
        assert not result["contradictions"], "a missing join must not also be reported as a contradiction"
    else:
        assert result["contradictions"], "a contradiction must be reported as invalid, not as a missing join"


def test_shared_session_for_both_labels_is_refused_as_not_independent() -> None:
    result, cluster = _run(replace(_positive_spec(), shared_session=True))
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    assert len(cluster.sessions) == 1
    assert result["status"] == "incomplete"
    assert SESSION_NOT_INDEPENDENT in _codes(result)


def test_statement_timeout_is_incomplete_and_every_session_closes() -> None:
    result, cluster = _run(replace(_positive_spec(), cancel_items=True))
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    assert result["status"] == "incomplete"
    assert STATEMENT_TIMEOUT in _codes(result)


def test_exhausted_overall_deadline_connects_nothing() -> None:
    result, cluster = _run(_positive_spec(), remaining_s=0.0)
    _assert_custody(result)
    _assert_bounded_read_only(cluster)
    assert cluster.connect_calls == []
    assert result["status"] == "incomplete"
    assert DEADLINE_EXHAUSTED in _codes(result)
    assert result["raw_artifacts"] == []
