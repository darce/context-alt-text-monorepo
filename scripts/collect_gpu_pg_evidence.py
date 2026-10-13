"""G4 restricted-PostgreSQL evidence collector: frozen ABI v1, section ``pg``.

``collect_pg_evidence(*, connect, selection, deadline)`` returns::

    {"section": Section, "artifacts": [Artifact], "raw_artifacts": {relative_path: bytes}}

Boundaries
----------
* ``connect`` is injected. This module imports no database driver and never receives a DSN. It passes
  only ``dsn_ref`` (a reference name) plus bounded timeouts: ``session_label``, ``connect_timeout_s``,
  ``statement_timeout_ms``, ``lock_timeout_ms`` and ``overall_deadline_s``.
* Two independent restricted sessions run. Each opens ``BEGIN READ ONLY`` before anything else, reads with
  SELECT only, selects tenant context with the native statement ``SET LOCAL app.current_tenant = '<tenant>'``
  (apps/prototype-description-service/db/tenant_context.py, set_tenant_context), ends with ROLLBACK, and is
  closed on every path, including failures.
* Application bypass and tenant claims are probed. Missing claims withhold tenant reads.
* Raw captures are UTF-8 driver-result receipts: query IDs, SQL, parameters, declared column names and
  types, typed rows, and timing. They are returned in-process, must be persisted before JSON assembly, and
  are hashed over the exact returned bytes. Receipts never carry a DSN, password, or Authorization value.
* Selection values are capture instructions only. Every observed fact comes from a query result. A fact the
  restricted contract cannot observe is an explicit missing reason, never a value copied from selection.

Status: contradictions take precedence (``contradicted``), then missing reasons (``incomplete``), else
``complete``. Complete means the scoped PG capture is complete; it does not mean strict acceptance is ready.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

__all__ = ["collect_pg_evidence"]

SECTION = "pg"
RAW_DIR = "raw/pg"
PRIMARY_SESSION = "primary-restricted-reader"
INDEPENDENT_SESSION = "independent-restricted-verifier"
# Bounds mirror the restricted-session contract. The deadline may shrink each value; it never raises one.
CONNECT_CAPS: dict[str, float] = {
    "connect_timeout_s": 10.0,
    "statement_timeout_ms": 30_000,
    "lock_timeout_ms": 5_000,
    "overall_deadline_s": 300.0,
}
MAX_ROWS_PER_QUERY = 200
MAX_RECEIPT_BYTES = 262_144
# Identity vector inventory: recognition/application/health.py IDENTITY_VECTOR_COLUMNS.
VECTOR_COLUMNS: tuple[tuple[str, str], ...] = (
    ("media_identities", "embedding"),
    ("identity_cluster_representatives", "embedding"),
    ("mv_identity_cluster_centroids", "centroid"),
)
# Only media_identities carries embedding_model in the native schema (db/models/identity.py).
EMBEDDING_MODEL_TABLE = "media_identities"
RLS_TABLES = (
    "image_description_runs",
    "image_description_run_items",
    "describe_operations",
    "media_identities",
    "identity_cluster_representatives",
)
REQUIRED_SELECTION = (
    "environment",
    "expected_database",
    "expected_role",
    "expected_schema",
    "tenant_id",
    "run_id",
    "foreign_run_id",
    "media_ids",
    "result_generation",
    "expected_model_id",
    "expected_vector_dimension",
    "dsn_ref",
)
OPTIONAL_SELECTION = ("operation_id", "foreign_operation_id")

SQLSTATE_QUERY_CANCELED = "57014"
SQLSTATE_UNDEFINED_FUNCTION = "42883"
SQLSTATE_READ_ONLY = "25006"

# Contradictions: observed mismatches or contradictory facts.
WRONG_DATABASE = "wrong_database"
WRONG_ROLE = "wrong_role"
WRONG_SCHEMA = "wrong_schema"
NOT_POSTGRESQL = "identity_probe_rejected"
TRANSACTION_NOT_READ_ONLY = "transaction_not_read_only"
SUPERUSER_ROLE = "superuser_role"
BYPASSRLS_ROLE = "bypassrls_role"
RLS_NOT_ENABLED = "rls_not_enabled"
RLS_NOT_FORCED = "rls_not_forced"
TENANT_POLICY_MISSING = "tenant_policy_missing"
FOREIGN_TENANT_VISIBLE = "foreign_tenant_visible"
MIXED_EMBEDDING_SPACES = "mixed_embedding_spaces"
MIXED_EMBEDDING_MODELS = "mixed_embedding_models"
VECTOR_DIMENSION_MISMATCH = "vector_dimension_mismatch"
MIXED_OUTPUT_MODELS = "mixed_output_models"
OUTPUT_MODEL_MISMATCH = "output_model_mismatch"
RESULT_GENERATION_MISMATCH = "result_generation_mismatch"
REQUEST_DIGEST_MALFORMED = "request_digest_malformed"
# Missing reasons: facts not observed, joins absent, or captures stopped or truncated.
SELECTION_FIELD_MISSING = "selection_field_missing"
SELECTION_FIELD_INVALID = "selection_field_invalid"
DEADLINE_EXHAUSTED = "deadline_exhausted"
STATEMENT_TIMEOUT = "statement_timeout"
READ_ONLY_REFUSED = "read_only_refused"
PROBE_REJECTED = "probe_rejected"
DRIVER_ERROR = "driver_error"
ROW_BUDGET_EXCEEDED = "row_budget_exceeded"
BYTE_BUDGET_EXCEEDED = "byte_budget_exceeded"
SESSION_NOT_INDEPENDENT = "session_independence_unproven"
SESSION_CLOSE_FAILED = "session_close_failed"
APP_BYPASS_UNPROBED = "app_bypass_rls_unprobed"
FOREIGN_UNWITNESSED = "foreign_existence_unwitnessed"
FIRST_REVISION_UNPERSISTED = "first_counting_revision_unpersisted"
EMBEDDING_MODELS_UNAVAILABLE = "embedding_models_unavailable"
NOT_VISIBLE_INDEPENDENT = "not_visible_on_independent_session"
VISIBILITY_SESSION_DISAGREEMENT = "visibility_session_disagreement"
OPERATION_ID_NOT_SELECTED = "operation_id_not_selected"
FOREIGN_OPERATION_ID_NOT_SELECTED = "foreign_operation_id_not_selected"
VECTOR_EXTENSION_ABSENT = "vector_extension_absent"
VECTOR_COLUMN_ABSENT = "vector_column_absent"
RLS_TABLE_ABSENT = "rls_table_absent"
CAPTION_SHA256_UNAVAILABLE = "caption_sha256_unavailable"
OUTPUT_MODEL_UNOBSERVED = "output_model_unobserved"
PROBE_NOT_RUN = "probe_not_run"
TENANT_CONTEXT_NOT_SELECTED = "tenant_context_not_selected"
DEMAND_ROW_NOT_VISIBLE = "demand_row_not_visible"
OUTPUT_ROW_NOT_VISIBLE = "output_row_not_visible"

# Query contract. Column names and declared types are the query's contract, recorded as such in receipts.
BEGIN_READ_ONLY_SQL = "BEGIN READ ONLY"
END_READ_ONLY_SQL = "ROLLBACK"
IDENTITY_SQL = (
    "SELECT current_database(), current_user, session_user, pg_backend_pid(), current_setting('server_version'), "
    "(SELECT a.backend_start FROM pg_stat_activity a WHERE a.pid = pg_backend_pid()), current_schema()"
)
IDENTITY_COLUMNS = (
    "database",
    "current_user",
    "session_user",
    "backend_pid",
    "server_version",
    "backend_start",
    "schema",
)
IDENTITY_TYPES = ("name", "name", "name", "int4", "text", "timestamptz", "name")
TXN_READ_ONLY_SQL = "SELECT current_setting('transaction_read_only')"
APP_BYPASS_SQL = "SELECT current_setting('app.bypass_rls', true)"
TENANT_CLAIM_SQL = "SELECT current_setting('app.current_tenant', true)"
RUN_SQL = "SELECT r.id, r.tenant_id, r.operation_id FROM image_description_runs r WHERE r.id = %(run_id)s::uuid"
ROLE_SQL = "SELECT r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user"
ROLE_MEMBERSHIP_SQL = "SELECT r.rolname, pg_has_role(current_user, r.oid, 'USAGE') FROM pg_roles r"
EXTENSION_SQL = "SELECT e.extname, e.extversion FROM pg_extension e WHERE e.extname = 'vector'"
VECTOR_SQL = (
    "SELECT n.nspname, c.relname, a.attname, t.typname, a.atttypmod FROM pg_attribute a "
    "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_type t ON t.oid = a.atttypid "
    "JOIN pg_depend d ON d.objid = a.atttypid AND d.classid = 'pg_type'::regclass "
    "AND d.refclassid = 'pg_extension'::regclass AND d.deptype = 'e' "
    "JOIN pg_extension e ON e.oid = d.refobjid AND e.extname = 'vector' "
    "WHERE n.nspname = current_schema() "
    "AND NOT a.attisdropped AND t.typname = 'vector'"
)
RLS_SQL = (
    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = current_schema() "
    "AND c.relname = ANY(%(tables)s)"
)
POLICY_SQL = (
    "SELECT p.tablename, p.policyname, p.cmd, p.roles, p.permissive, p.qual, p.with_check "
    "FROM pg_policies p WHERE p.schemaname = current_schema() AND p.tablename = ANY(%(tables)s)"
)
INDEX_SQL = (
    "SELECT c.relname, a.attname, am.amname, op.opcname, i.indisvalid, "
    "pg_get_expr(i.indpred, i.indrelid), pg_get_expr(i.indexprs, i.indrelid) "
    "FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_class ix ON ix.oid = i.indexrelid JOIN pg_am am ON am.oid = ix.relam "
    "JOIN LATERAL unnest(i.indkey::smallint[], i.indclass::oid[]) AS k(attnum, opclass) ON true "
    "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum "
    "JOIN pg_opclass op ON op.oid = k.opclass WHERE n.nspname = current_schema()"
)
EXTENSION_TYPE_SQL = (
    "SELECT n.nspname, t.typname, e.extname FROM pg_type t "
    "JOIN pg_namespace n ON n.oid = t.typnamespace "
    "JOIN pg_depend d ON d.objid = t.oid AND d.classid = 'pg_type'::regclass "
    "AND d.refclassid = 'pg_extension'::regclass AND d.deptype = 'e' "
    "JOIN pg_extension e ON e.oid = d.refobjid WHERE t.typname = 'vector'"
)
SET_TENANT_TEMPLATE = "SET LOCAL app.current_tenant = '{tenant_id}'"
EMBEDDING_SQL = "SELECT DISTINCT m.embedding_model FROM media_identities m ORDER BY m.embedding_model"
DEMAND_SQL = (
    "SELECT d.operation_id, d.request_digest FROM describe_operations d WHERE d.operation_id = %(operation_id)s"
)
OUTPUT_SQL = (
    "SELECT i.run_id, i.media_id, i.status, i.tier, i.result_generation, i.provenance ->> 'model_id' AS reported_model_id, "
    "encode(sha256(convert_to(i.caption, 'UTF8')), 'hex') AS caption_sha256 "
    "FROM image_description_run_items i WHERE i.run_id = %(run_id)s::uuid"
)
OUTPUT_COLUMNS = ("run_id", "media_id", "status", "tier", "result_generation", "reported_model_id", "caption_sha256")
OUTPUT_TYPES = ("uuid", "int4", "text", "text", "int4", "text", "text")

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_H64 = re.compile(r"[0-9a-f]{64}")


def _now() -> str:
    """RFC3339 UTC with fractional seconds and a trailing Z (frozen ABI Time)."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    """Convert driver values to deterministic JSON values. Non-finite floats become strings."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(item) for item in value), key=str)
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _remaining(deadline: Any) -> float:
    """Seconds left on the one absolute deadline. Any unreadable or non-finite value is fail-closed (0)."""
    try:
        value = float(deadline.remaining_seconds())
    except Exception:  # noqa: BLE001 - fail closed on any deadline read error
        return 0.0
    return value if math.isfinite(value) else 0.0


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class _Capture:
    """One restricted session's driver receipt. ``queries`` is the receipt body, in execution order.

    A plain class, not a dataclass: the module may be loaded by path without being registered in
    ``sys.modules``, and dataclass processing of postponed annotations requires that registration.
    """

    def __init__(self, label: str, dsn_ref: str, bounds: dict[str, Any]) -> None:
        self.label = label
        self.dsn_ref = dsn_ref
        self.bounds = bounds
        self.session: Any = None
        self.began = False
        self.queries: list[dict[str, Any]] = []
        self.acquired_bytes = 0
        self.persisted = False
        self.path = ""
        self.sha256 = ""
        self.raw = b""

    def record(self, query_id: str) -> dict[str, Any] | None:
        for rec in reversed(self.queries):
            if rec["query_id"] == query_id:
                return rec
        return None

    def ran(self, query_id: str) -> bool:
        rec = self.record(query_id)
        return rec is not None and rec["outcome"] == "ok"

    def rows(self, query_id: str) -> list[list[Any]] | None:
        rec = self.record(query_id)
        if rec is None or rec["outcome"] != "ok":
            return None
        return rec["rows"]

    def index(self, query_id: str) -> int | None:
        for idx in range(len(self.queries) - 1, -1, -1):
            if self.queries[idx]["query_id"] == query_id:
                return idx
        return None

    def ref(self, query_id: str | None = None) -> dict[str, Any] | None:
        if not self.persisted:
            return None
        locator = None
        if query_id is not None:
            idx = self.index(query_id)
            if idx is not None:
                locator = f"/queries/{idx}"
        return {"relative_path": self.path, "sha256": self.sha256, "locator": locator}

    def finished_at(self, query_id: str) -> str | None:
        rec = self.record(query_id)
        return rec["finished_at"] if rec is not None else None


class _HaltError(Exception):
    """Stops the capture. Every halt is incomplete unless it is a contradiction."""

    def __init__(
        self,
        code: str,
        field_name: str,
        detail: str,
        *,
        contradiction: bool = False,
        ref: tuple[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.field_name = field_name
        self.detail = detail
        self.contradiction = contradiction
        self.ref = ref


class _Findings:
    """Accumulates observations and issues. Issues are de-duplicated; refs are resolved at assembly."""

    def __init__(self) -> None:
        self.observations: list[dict[str, Any]] = []
        self.missing: list[dict[str, Any]] = []
        self.contradictions: list[dict[str, Any]] = []
        self._seen: set[tuple[bool, str, str, str, tuple[str, str] | None]] = set()

    def _add(self, contradiction: bool, code: str, field_name: str, detail: str, ref: tuple[str, str] | None) -> None:
        key = (contradiction, code, field_name, detail, ref)
        if key in self._seen:
            return
        self._seen.add(key)
        bucket = self.contradictions if contradiction else self.missing
        bucket.append({"code": code, "field": field_name, "detail": detail, "ref": ref})

    def miss(self, code: str, field_name: str, detail: str, ref: tuple[str, str] | None = None) -> None:
        self._add(False, code, field_name, detail, ref)

    def contradict(self, code: str, field_name: str, detail: str, ref: tuple[str, str] | None = None) -> None:
        self._add(True, code, field_name, detail, ref)

    def absorb(self, halt: _HaltError) -> None:
        if halt.contradiction:
            self.contradict(halt.code, halt.field_name, halt.detail, halt.ref)
        else:
            self.miss(halt.code, halt.field_name, halt.detail, halt.ref)


def _read_selection(selection: Any, findings: _Findings) -> dict[str, Any] | None:
    """Validate capture instructions. Invalid instructions are missing evidence, never observations."""
    if not isinstance(selection, Mapping):
        findings.miss(SELECTION_FIELD_INVALID, "selection", "capture instructions must be a mapping")
        return None
    ok = True
    for name in REQUIRED_SELECTION:
        if name not in selection:
            findings.miss(SELECTION_FIELD_MISSING, name, "required capture instruction is absent")
            ok = False

    def bad(name: str, detail: str) -> None:
        nonlocal ok
        findings.miss(SELECTION_FIELD_INVALID, name, detail)
        ok = False

    for name in ("environment", "expected_database", "expected_role", "expected_schema", "expected_model_id"):
        value = selection.get(name)
        if name in selection and (not isinstance(value, str) or not value.strip()):
            bad(name, "must be a non-empty string")
    for name in ("tenant_id", "run_id", "foreign_run_id"):
        value = selection.get(name)
        if name in selection and not (isinstance(value, str) and _UUID.fullmatch(value)):
            bad(name, "must be a lowercase UUID string")
    media_ids = selection.get("media_ids")
    if "media_ids" in selection:
        if not isinstance(media_ids, (list, tuple)) or not media_ids:
            bad("media_ids", "must be a non-empty list")
        elif not all(_is_int(m) and m >= 1 for m in media_ids) or len(set(media_ids)) != len(media_ids):
            bad("media_ids", "must be unique positive integers")
    generation = selection.get("result_generation")
    if "result_generation" in selection and not (_is_int(generation) and generation >= 0):
        bad("result_generation", "must be a Counter (integer >= 0)")
    dimension = selection.get("expected_vector_dimension")
    if "expected_vector_dimension" in selection and not (_is_int(dimension) and dimension >= 1):
        bad("expected_vector_dimension", "must be a positive integer")
    dsn_ref = selection.get("dsn_ref")
    if "dsn_ref" in selection:
        if not isinstance(dsn_ref, str) or not dsn_ref.strip():
            bad("dsn_ref", "must be a non-empty reference name")
        elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", dsn_ref):
            bad("dsn_ref", "opaque identifier required")
    for name in OPTIONAL_SELECTION:
        if name in selection and not (isinstance(selection[name], str) and 1 <= len(selection[name]) <= 128):
            bad(name, "must be a 1..128 character operation identifier when present")
    if not ok:
        return None
    normalized = {name: selection[name] for name in REQUIRED_SELECTION}
    normalized.update({name: selection[name] for name in OPTIONAL_SELECTION if name in selection})
    normalized["media_ids"] = list(media_ids)
    return normalized


def _connect_kwargs(label: str, dsn_ref: str, deadline: Any) -> dict[str, Any]:
    remaining = _remaining(deadline)
    if remaining <= 0:
        raise _HaltError(DEADLINE_EXHAUSTED, f"session.{label}", "overall deadline exhausted before connect")
    millis = max(1, int(remaining * 1000))
    return {
        "session_label": label,
        "dsn_ref": dsn_ref,
        "connect_timeout_s": min(CONNECT_CAPS["connect_timeout_s"], remaining),
        "statement_timeout_ms": min(int(CONNECT_CAPS["statement_timeout_ms"]), millis),
        "lock_timeout_ms": min(int(CONNECT_CAPS["lock_timeout_ms"]), millis),
        "overall_deadline_s": min(CONNECT_CAPS["overall_deadline_s"], remaining),
    }


def _open(connect: Any, label: str, dsn_ref: str, deadline: Any, captures: dict[str, _Capture]) -> _Capture:
    kwargs = _connect_kwargs(label, dsn_ref, deadline)
    capture = _Capture(label=label, dsn_ref=dsn_ref, bounds={k: kwargs[k] for k in CONNECT_CAPS})
    captures[label] = capture
    try:
        session = connect(**kwargs)
    except Exception as exc:  # noqa: BLE001 - class name only; messages may echo connection material
        raise _HaltError(DRIVER_ERROR, f"session.{label}", f"connect failed: {type(exc).__name__}") from None
    capture.session = session
    return capture


def _record(
    query_id: str,
    sql: str,
    params: Mapping[str, Any],
    columns: tuple[str, ...],
    types: tuple[str, ...],
    started: str,
    finished: str,
    *,
    outcome: str,
    rows: list[list[Any]] | None = None,
    error_class: str | None = None,
    sqlstate: str | None = None,
) -> dict[str, Any]:
    body = rows or []
    return {
        "query_id": query_id,
        "sql": sql,
        "params": _jsonable(dict(params)),
        "column_names": list(columns),
        "column_types": list(types),
        "column_types_source": "declared_by_query_contract",
        "outcome": outcome,
        "row_count": len(body),
        "rows": _jsonable(body),
        "error_class": error_class,
        "sqlstate": sqlstate,
        "started_at": started,
        "finished_at": finished,
    }


def _query(
    capture: _Capture,
    deadline: Any,
    findings: _Findings,
    query_id: str,
    sql: str,
    params: Mapping[str, Any],
    columns: tuple[str, ...] = (),
    types: tuple[str, ...] = (),
    *,
    identity: bool = False,
    _refresh: bool = True,
) -> list[list[Any]] | None:
    ref = (capture.label, query_id)
    if _remaining(deadline) <= 0:
        raise _HaltError(DEADLINE_EXHAUSTED, f"query.{capture.label}.{query_id}", "deadline exhausted", ref=ref)
    started = _now()
    try:
        if capture.began and _refresh:
            ms = min(int(CONNECT_CAPS["statement_timeout_ms"]), max(1, int(_remaining(deadline) * 1000)))
            _query(
                capture,
                deadline,
                findings,
                query_id + "-timeout",
                f"SELECT set_config('statement_timeout', '{ms}', true)",
                {},
                ("statement_timeout",),
                ("text",),
                _refresh=False,
            )
        if _remaining(deadline) <= 0:
            raise _HaltError(
                DEADLINE_EXHAUSTED, f"query.{capture.label}.{query_id}", "deadline exhausted before statement", ref=ref
            )
        rows = capture.session.query(sql, dict(params))
    except _HaltError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by SQLSTATE; the message is not copied
        sqlstate = getattr(exc, "sqlstate", None)
        sqlstate = sqlstate if isinstance(sqlstate, str) else None
        capture.queries.append(
            _record(
                query_id,
                sql,
                params,
                columns,
                types,
                started,
                _now(),
                outcome="error",
                error_class=type(exc).__name__,
                sqlstate=sqlstate,
            )
        )
        where = f"query.{capture.label}.{query_id}"
        if sqlstate == SQLSTATE_QUERY_CANCELED:
            raise _HaltError(
                STATEMENT_TIMEOUT, where, "statement timeout; the capture stopped and sessions close", ref=ref
            )
        if sqlstate == SQLSTATE_READ_ONLY:
            raise _HaltError(
                READ_ONLY_REFUSED, where, "a read-only session refused a statement; capture stopped", ref=ref
            )
        if sqlstate == SQLSTATE_UNDEFINED_FUNCTION:
            if identity:
                raise _HaltError(
                    NOT_POSTGRESQL,
                    f"connection.{capture.label}",
                    "the target engine rejected the PostgreSQL identity probe",
                    contradiction=True,
                    ref=ref,
                )
            raise _HaltError(
                PROBE_REJECTED, where, "the target engine rejected a catalog probe; capture stopped", ref=ref
            )
        raise _HaltError(DRIVER_ERROR, where, f"driver error {type(exc).__name__}; capture stopped", ref=ref)
    finished = _now()
    if _remaining(deadline) <= 0:
        capture.queries.append(
            _record(query_id, sql, params, columns, types, started, finished, outcome="deadline_exhausted")
        )
        raise _HaltError(
            DEADLINE_EXHAUSTED, f"query.{capture.label}.{query_id}", "deadline exhausted after query", ref=ref
        )
    materialized = []
    acquired_bytes = capture.acquired_bytes
    for row in rows:
        converted = _jsonable(list(row))
        # iterencode avoids constructing a complete serialized receipt before the byte bound.
        for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(converted):
            acquired_bytes += len(chunk.encode("utf-8"))
            if acquired_bytes > MAX_RECEIPT_BYTES:
                capture.queries.append(
                    _record(query_id, sql, params, columns, types, started, finished, outcome="byte_budget_exceeded")
                )
                findings.miss(
                    BYTE_BUDGET_EXCEEDED, f"query.{capture.label}.{query_id}", "acquisition byte budget exceeded", ref
                )
                return None
        materialized.append(converted)
        if len(materialized) > MAX_ROWS_PER_QUERY:
            break
        if _remaining(deadline) <= 0:
            raise _HaltError(
                DEADLINE_EXHAUSTED,
                f"query.{capture.label}.{query_id}",
                "deadline exhausted during acquisition",
                ref=ref,
            )
    if len(materialized) > MAX_ROWS_PER_QUERY:
        capture.queries.append(
            _record(query_id, sql, params, columns, types, started, finished, outcome="row_budget_exceeded")
        )
        findings.miss(
            ROW_BUDGET_EXCEEDED,
            f"query.{capture.label}.{query_id}",
            f"{len(materialized)} rows exceed the {MAX_ROWS_PER_QUERY}-row budget; the result is not used",
            ref,
        )
        return None
    record = _record(query_id, sql, params, columns, types, started, finished, outcome="ok", rows=materialized)
    capture.acquired_bytes += sum(
        len(c.encode("utf-8")) for c in json.JSONEncoder(ensure_ascii=False).iterencode(record)
    )
    if capture.acquired_bytes > MAX_RECEIPT_BYTES:
        findings.miss(
            BYTE_BUDGET_EXCEEDED, f"query.{capture.label}.{query_id}", "receipt acquisition budget exceeded", ref
        )
        record = _record(query_id, sql, params, columns, types, started, finished, outcome="byte_budget_exceeded")
        capture.queries.append(record)
        return None
    capture.queries.append(record)
    return materialized


def _begin(capture: _Capture, deadline: Any, findings: _Findings) -> None:
    _query(capture, deadline, findings, "begin-read-only", BEGIN_READ_ONLY_SQL, {})
    capture.began = True


def _same_backend(first: _Capture, second: _Capture) -> bool:
    a = first.rows("identity")
    b = second.rows("identity")
    if not a or not b:
        return False
    return a[0][3] == b[0][3] or a[0][5] == b[0][5]


def _observe(
    connect: Any, sel: dict[str, Any], deadline: Any, findings: _Findings, captures: dict[str, _Capture]
) -> None:
    """Probe both sessions, gate authorization, then select and measure the tenant claim before reads."""
    tenant_sql = SET_TENANT_TEMPLATE.format(tenant_id=sel["tenant_id"])
    primary = _open(connect, PRIMARY_SESSION, sel["dsn_ref"], deadline, captures)
    _begin(primary, deadline, findings)
    _query(primary, deadline, findings, "identity", IDENTITY_SQL, {}, IDENTITY_COLUMNS, IDENTITY_TYPES, identity=True)
    independent = _open(connect, INDEPENDENT_SESSION, sel["dsn_ref"], deadline, captures)
    _begin(independent, deadline, findings)
    _query(
        independent, deadline, findings, "identity", IDENTITY_SQL, {}, IDENTITY_COLUMNS, IDENTITY_TYPES, identity=True
    )
    if _same_backend(primary, independent):
        raise _HaltError(
            SESSION_NOT_INDEPENDENT,
            "sessions",
            "primary and independent sessions report the same backend PID or start time",
            ref=(INDEPENDENT_SESSION, "identity"),
        )
    for capture in (primary, independent):
        _query(
            capture,
            deadline,
            findings,
            "transaction-read-only",
            TXN_READ_ONLY_SQL,
            {},
            ("transaction_read_only",),
            ("text",),
        )
        _query(capture, deadline, findings, "role-flags", ROLE_SQL, {}, ("rolsuper", "rolbypassrls"), ("bool", "bool"))
        _query(capture, deadline, findings, "app-bypass", APP_BYPASS_SQL, {}, ("app_bypass_rls",), ("text",))
    for capture in (primary, independent):
        ident, txn, roles, bypass = (
            capture.rows(q) for q in ("identity", "transaction-read-only", "role-flags", "app-bypass")
        )
        if not all((ident, txn, roles, bypass)):
            raise _HaltError(PROBE_NOT_RUN, f"connection.{capture.label}", "required authorization probe has no row")
        if _bypass_value(bypass[0][0]) is None:
            raise _HaltError(
                APP_BYPASS_UNPROBED, f"connection.{capture.label}.app_bypass_rls", "bypass claim not recognized"
            )
        checks = [
            (ident[0][0] != sel["expected_database"], WRONG_DATABASE),
            (ident[0][1] != sel["expected_role"] or ident[0][2] != sel["expected_role"], WRONG_ROLE),
            (ident[0][6] != sel["expected_schema"], WRONG_SCHEMA),
            (txn[0][0] != "on", TRANSACTION_NOT_READ_ONLY),
            (bool(roles[0][0]), SUPERUSER_ROLE),
            (bool(roles[0][1]), BYPASSRLS_ROLE),
            (_bypass_value(bypass[0][0]) is True, "app_bypass_rls_enabled"),
        ]
        for unsafe, code in checks:
            if unsafe:
                raise _HaltError(
                    code, f"connection.{capture.label}", "unsafe session authorization", contradiction=True
                )
    _query(
        primary,
        deadline,
        findings,
        "role-membership",
        ROLE_MEMBERSHIP_SQL,
        {},
        ("role", "usable"),
        ("name", "bool"),
    )
    _query(
        primary,
        deadline,
        findings,
        "indexes",
        INDEX_SQL,
        {},
        ("table", "column", "method", "opclass", "valid", "predicate", "expression"),
        ("name", "name", "name", "name", "bool", "text", "text"),
    )
    _query(
        primary,
        deadline,
        findings,
        "extension-type",
        EXTENSION_TYPE_SQL,
        {},
        ("schema", "type", "extension"),
        ("name", "name", "name"),
    )
    _query(primary, deadline, findings, "extension", EXTENSION_SQL, {}, ("extname", "extversion"), ("name", "text"))
    _query(
        primary,
        deadline,
        findings,
        "vector-columns",
        VECTOR_SQL,
        {},
        ("schema", "table", "column", "type_name", "atttypmod"),
        ("name", "name", "name", "name", "int4"),
    )
    _query(
        primary,
        deadline,
        findings,
        "rls-flags",
        RLS_SQL,
        {"tables": list(RLS_TABLES)},
        ("table", "enabled", "forced"),
        ("name", "bool", "bool"),
    )
    _query(
        primary,
        deadline,
        findings,
        "policies",
        POLICY_SQL,
        {"tables": list(RLS_TABLES)},
        ("table", "name", "command", "roles", "permissive", "qual", "with_check"),
        ("name", "name", "text", "name[]", "text", "text", "text"),
    )
    for capture in (primary, independent):
        _query(capture, deadline, findings, "set-tenant", tenant_sql, {})
        _query(capture, deadline, findings, "tenant-claim", TENANT_CLAIM_SQL, {}, ("tenant_context",), ("text",))
        claim = capture.rows("tenant-claim")
        if not claim or not claim[0][0]:
            raise _HaltError(
                TENANT_CONTEXT_NOT_SELECTED, f"connection.{capture.label}.tenant_context", "tenant claim missing"
            )
        if claim[0][0] != sel["tenant_id"]:
            raise _HaltError(
                "tenant_context_mismatch",
                f"connection.{capture.label}.tenant_context",
                "tenant claim differs",
                contradiction=True,
            )
    _query(primary, deadline, findings, "embedding-models", EMBEDDING_SQL, {}, ("embedding_model",), ("text",))
    for capture in (primary, independent):
        if "operation_id" in sel:
            _query(
                capture,
                deadline,
                findings,
                "demand-own",
                DEMAND_SQL,
                {"operation_id": sel["operation_id"]},
                ("operation_id", "request_digest"),
                ("text", "text"),
            )
        if "foreign_operation_id" in sel:
            _query(
                capture,
                deadline,
                findings,
                "demand-foreign",
                DEMAND_SQL,
                {"operation_id": sel["foreign_operation_id"]},
                ("operation_id", "request_digest"),
                ("text", "text"),
            )
        _query(
            capture,
            deadline,
            findings,
            "run-own",
            RUN_SQL,
            {"run_id": sel["run_id"]},
            ("run_id", "tenant_id", "operation_id"),
            ("uuid", "uuid", "text"),
        )
        _query(
            capture,
            deadline,
            findings,
            "output-own",
            OUTPUT_SQL,
            {"run_id": sel["run_id"]},
            OUTPUT_COLUMNS,
            OUTPUT_TYPES,
        )
        _query(
            capture,
            deadline,
            findings,
            "output-foreign",
            OUTPUT_SQL,
            {"run_id": sel["foreign_run_id"]},
            OUTPUT_COLUMNS,
            OUTPUT_TYPES,
        )


def _close_all(captures: dict[str, _Capture], findings: _Findings, deadline: Any) -> None:
    """Close every opened session exactly once: end a began read-only transaction, then close."""
    closed: set[int] = set()
    for capture in captures.values():
        session = capture.session
        if session is None or id(session) in closed:
            continue
        closed.add(id(session))
        owners = [c for c in captures.values() if c.session is session]
        began = next((c for c in owners if c.began), None)
        if began is not None:
            started = _now()
            try:
                remaining = _remaining(deadline)
                if remaining > 0 and not any(q["outcome"] == "error" for q in began.queries):
                    ms = min(int(CONNECT_CAPS["statement_timeout_ms"]), max(1, int(remaining * 1000)))
                    _query(
                        began,
                        deadline,
                        findings,
                        "cleanup-timeout",
                        f"SELECT set_config('statement_timeout', '{ms}', true)",
                        {},
                        ("statement_timeout",),
                        ("text",),
                        _refresh=False,
                    )
                elif remaining <= 0:
                    findings.miss(
                        DEADLINE_EXHAUSTED, f"cleanup.{began.label}.rollback", "deadline exhausted before cleanup"
                    )
            except _HaltError as halt:
                findings.absorb(halt)
            except Exception as exc:  # noqa: BLE001 - refresh failures must not prevent rollback
                findings.miss(
                    DRIVER_ERROR,
                    f"cleanup.{began.label}.timeout",
                    f"cleanup timeout probe failed: {type(exc).__name__}",
                    (began.label, "cleanup-timeout"),
                )
            try:
                session.query(END_READ_ONLY_SQL, {})
                if _remaining(deadline) <= 0:
                    findings.miss(
                        DEADLINE_EXHAUSTED, f"cleanup.{began.label}.rollback", "deadline exhausted during rollback"
                    )
                began.queries.append(
                    _record("end-read-only", END_READ_ONLY_SQL, {}, (), (), started, _now(), outcome="ok")
                )
            except Exception as exc:  # noqa: BLE001 - class name only
                began.queries.append(
                    _record(
                        "end-read-only",
                        END_READ_ONLY_SQL,
                        {},
                        (),
                        (),
                        started,
                        _now(),
                        outcome="error",
                        error_class=type(exc).__name__,
                    )
                )
                findings.miss(SESSION_CLOSE_FAILED, f"session.{began.label}", f"rollback failed: {type(exc).__name__}")
        try:
            session.close()
            if _remaining(deadline) <= 0:
                findings.miss(DEADLINE_EXHAUSTED, f"cleanup.{owners[0].label}.close", "deadline exhausted during close")
        except Exception as exc:  # noqa: BLE001 - class name only
            label = (began or owners[0]).label
            findings.miss(SESSION_CLOSE_FAILED, f"session.{label}", f"close failed: {type(exc).__name__}")


def _serialize(captures: dict[str, _Capture], findings: _Findings) -> None:
    """Build each receipt once. Over-budget receipts are not persisted, so nothing may cite them."""
    for label, capture in captures.items():
        if not capture.queries:
            continue
        receipt = {
            "schema": "gpu-pg-driver-receipt",
            "schema_version": 1,
            "session_label": label,
            "dsn_ref": capture.dsn_ref,
            "connect_bounds": capture.bounds,
            "queries": capture.queries,
        }
        chunks = bytearray()
        for chunk in json.JSONEncoder(
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).iterencode(receipt):
            encoded = chunk.encode("utf-8")
            if len(chunks) + len(encoded) + 1 > MAX_RECEIPT_BYTES:
                chunks = bytearray(b" " * (MAX_RECEIPT_BYTES + 1))
                break
            chunks.extend(encoded)
        raw = bytes(chunks) + b"\n"
        if len(raw) > MAX_RECEIPT_BYTES:
            findings.miss(
                BYTE_BUDGET_EXCEEDED,
                f"raw.{label}",
                f"receipt of {len(raw)} bytes exceeds the {MAX_RECEIPT_BYTES}-byte budget; not persisted",
            )
            continue
        capture.raw = raw
        capture.path = f"{RAW_DIR}/{label}.json"
        capture.sha256 = hashlib.sha256(raw).hexdigest()
        capture.persisted = True


def _bypass_value(value: Any) -> bool | None:
    if value is None or value == "":
        return False
    value = str(value).strip().lower()
    if value in ("on", "true", "1", "yes", "t"):
        return True
    if value in ("off", "false", "0", "no", "f"):
        return False
    return None


def _connection_observation(capture: _Capture, sel: dict[str, Any], findings: _Findings) -> dict[str, Any] | None:
    ident = capture.rows("identity")
    if not ident:
        return None
    database, current_user, session_user, backend_pid, _version, _started, schema = ident[0]
    ref = (capture.label, "identity")
    if database != sel["expected_database"]:
        findings.contradict(WRONG_DATABASE, f"connection.{capture.label}.database", f"observed {database!r}", ref)
    if current_user != sel["expected_role"]:
        findings.contradict(WRONG_ROLE, f"connection.{capture.label}.current_user", f"observed {current_user!r}", ref)
    if schema != sel["expected_schema"]:
        findings.contradict(WRONG_SCHEMA, f"connection.{capture.label}.schema", f"observed {schema!r}", ref)
    read_only: bool | None = None
    txn = capture.rows("transaction-read-only")
    if txn is None:
        findings.miss(
            PROBE_NOT_RUN,
            f"connection.{capture.label}.transaction_read_only",
            "read-only probe did not complete",
            (capture.label, "transaction-read-only"),
        )
    elif txn:
        read_only = txn[0][0] == "on"
        if not read_only:
            findings.contradict(
                TRANSACTION_NOT_READ_ONLY,
                f"connection.{capture.label}.transaction_read_only",
                "observed off",
                (capture.label, "transaction-read-only"),
            )
    rolsuper: bool | None = None
    rolbypassrls: bool | None = None
    roles = capture.rows("role-flags")
    if roles is None:
        findings.miss(
            PROBE_NOT_RUN,
            f"connection.{capture.label}.rolsuper",
            "role-flag probe did not complete",
            (capture.label, "role-flags"),
        )
    elif roles:
        rolsuper, rolbypassrls = roles[0]
        if rolsuper:
            findings.contradict(
                SUPERUSER_ROLE,
                f"connection.{capture.label}.rolsuper",
                "role is a superuser",
                (capture.label, "role-flags"),
            )
        if rolbypassrls:
            findings.contradict(
                BYPASSRLS_ROLE,
                f"connection.{capture.label}.rolbypassrls",
                "role bypasses RLS",
                (capture.label, "role-flags"),
            )
    bypass = capture.rows("app-bypass")
    app_bypass = None if not bypass else _bypass_value(bypass[0][0])
    if app_bypass is None:
        findings.miss(
            APP_BYPASS_UNPROBED,
            f"connection.{capture.label}.app_bypass_rls",
            "bypass probe unobserved",
            (capture.label, "app-bypass"),
        )
    claim = capture.rows("tenant-claim")
    tenant_context = claim[0][0] if claim and claim[0][0] else None
    if tenant_context is None:
        findings.miss(
            TENANT_CONTEXT_NOT_SELECTED,
            f"connection.{capture.label}.tenant_context",
            "tenant claim unobserved",
            (capture.label, "tenant-claim"),
        )
    return {
        "connection_id": capture.label,
        "database": database,
        "current_user": current_user,
        "session_user": session_user,
        "backend_pid": backend_pid,
        "tenant_context": tenant_context,
        "app_bypass_rls": app_bypass,
        "rolsuper": rolsuper,
        "rolbypassrls": rolbypassrls,
        "transaction_read_only": read_only,
    }


NATIVE_POLICY = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid OR COALESCE(NULLIF(current_setting('app.bypass_rls', true), ''), 'false')::boolean"


def _normalize_policy(value: Any) -> str:
    return re.sub(r"\s+|[()]|::(?:text|uuid|boolean)", "", str(value or "").lower())


def _catalog_observation(primary: _Capture, sel: dict[str, Any], findings: _Findings) -> dict[str, Any] | None:
    if not primary.ran("vector-columns") or not primary.ran("rls-flags") or not primary.ran("policies"):
        return None
    expected = sel["expected_vector_dimension"]
    version = None
    for name, extversion in primary.rows("extension") or []:
        if name == "vector":
            version = extversion
    if version is None:
        findings.miss(
            VECTOR_EXTENSION_ABSENT,
            "catalog.extension_version",
            "vector extension absent from pg_extension",
            (PRIMARY_SESSION, "extension"),
        )
    by_column = {
        (table, column): (schema, typname, typmod)
        for schema, table, column, typname, typmod in primary.rows("vector-columns") or []
    }
    models: list[str] | None = None
    if primary.ran("embedding-models"):
        models = sorted({row[0] for row in primary.rows("embedding-models") or []})
    vectors: list[dict[str, Any]] = []
    dimensions: list[int] = []
    for table, column in VECTOR_COLUMNS:
        field_name = f"catalog.vectors.{table}.{column}"
        if (table, column) not in by_column:
            findings.miss(
                VECTOR_COLUMN_ABSENT,
                field_name,
                "expected identity vector column is absent",
                (PRIMARY_SESSION, "vector-columns"),
            )
            continue
        schema, typname, typmod = by_column[(table, column)]
        dimensions.append(typmod)
        if typmod != expected:
            findings.contradict(
                VECTOR_DIMENSION_MISMATCH,
                f"{field_name}.atttypmod",
                f"observed {typmod} expected {expected}",
                (PRIMARY_SESSION, "vector-columns"),
            )
        if table == EMBEDDING_MODEL_TABLE:
            column_models = models
            if column_models is None:
                findings.miss(
                    EMBEDDING_MODELS_UNAVAILABLE,
                    f"{field_name}.embedding_models",
                    "embedding-model query did not complete",
                    (PRIMARY_SESSION, "embedding-models"),
                )
            elif len(column_models) > 1:
                findings.contradict(
                    MIXED_EMBEDDING_MODELS,
                    f"{field_name}.embedding_models",
                    f"own-tenant rows name {column_models}; one comparison must use one model",
                    (PRIMARY_SESSION, "embedding-models"),
                )
                findings.contradict(
                    MIXED_EMBEDDING_SPACES,
                    f"{field_name}.embedding_models",
                    "two embedding models in one vector space",
                    (PRIMARY_SESSION, "embedding-models"),
                )
        else:
            column_models = None
            findings.miss(
                EMBEDDING_MODELS_UNAVAILABLE,
                f"{field_name}.embedding_models",
                "no embedding_model column on this table in the native schema",
                (PRIMARY_SESSION, "vector-columns"),
            )
        vectors.append(
            {
                "schema": schema,
                "table": table,
                "column": column,
                "type_name": typname,
                "atttypmod": typmod,
                "embedding_models": column_models if table == EMBEDDING_MODEL_TABLE else None,
            }
        )
    if dimensions and (len(set(dimensions)) > 1 or any(d != expected for d in dimensions)):
        findings.contradict(
            MIXED_EMBEDDING_SPACES,
            "catalog.vectors",
            f"identity vector typmods {sorted(set(dimensions))} against expected {expected}",
            (PRIMARY_SESSION, "vector-columns"),
        )
    indexes = primary.rows("indexes") or []
    for table, column in VECTOR_COLUMNS:
        matched = [r for r in indexes if r[0:2] == [table, column]]
        field = f"catalog.indexes.{table}.{column}"
        if not matched:
            findings.miss("vector_index_absent", field, "no observed vector index", (PRIMARY_SESSION, "indexes"))
        elif not any(
            r[2:5] == ["ivfflat", "vector_cosine_ops", True] and r[5] is None and r[6] is None for r in matched
        ):
            findings.contradict(
                "vector_index_identity_mismatch",
                field,
                "index geometry or validity differs",
                (PRIMARY_SESSION, "indexes"),
            )
    if not any(r[1:] == ["vector", "vector"] for r in primary.rows("extension-type") or []):
        findings.miss(
            "vector_type_membership_unproven",
            "catalog.extension_type",
            "vector type is not observed extension-owned",
            (PRIMARY_SESSION, "extension-type"),
        )
    rls_flags = {name: (enabled, forced) for name, enabled, forced in primary.rows("rls-flags") or []}
    policy_rows = primary.rows("policies") or []
    membership_rows = primary.rows("role-membership")
    applicable_roles = {"public", sel["expected_role"]} | {
        role for role, usable in membership_rows or [] if usable is True
    }
    rls: list[dict[str, Any]] = []
    for table in RLS_TABLES:
        if table not in rls_flags:
            findings.miss(
                RLS_TABLE_ABSENT, f"catalog.rls.{table}", "table absent from pg_class", (PRIMARY_SESSION, "rls-flags")
            )
            continue
        enabled, forced = rls_flags[table]
        if not enabled:
            findings.contradict(
                RLS_NOT_ENABLED,
                f"catalog.rls.{table}.enabled",
                "row security is disabled",
                (PRIMARY_SESSION, "rls-flags"),
            )
        if not forced:
            findings.contradict(
                RLS_NOT_FORCED,
                f"catalog.rls.{table}.forced",
                "row security is not forced for the owner",
                (PRIMARY_SESSION, "rls-flags"),
            )
        policies = []
        for tablename, name, command, roles, permissive, qual, with_check in policy_rows:
            if tablename != table:
                continue
            policies.append(
                {
                    "name": name,
                    "command": command,
                    "roles": None if roles is None else [str(role) for role in roles],
                    "permissive": permissive == "PERMISSIVE" if permissive in ("PERMISSIVE", "RESTRICTIVE") else None,
                    "qual": qual,
                    "with_check": with_check,
                }
            )
        if not any(policy["name"] == f"tenant_isolation_{table}" for policy in policies):
            findings.contradict(
                TENANT_POLICY_MISSING,
                f"catalog.rls.{table}.policies",
                f"no tenant_isolation_{table} policy",
                (PRIMARY_SESSION, "policies"),
            )
        for policy in policies:
            if policy["command"] not in ("ALL", "SELECT"):
                continue
            role_field = f"catalog.rls.{table}.policies.{policy['name']}.roles"
            if policy["roles"] is None:
                findings.miss(
                    "policy_roles_unproven", role_field, "policy role targets unobserved", (PRIMARY_SESSION, "policies")
                )
                continue
            if not set(policy["roles"]) & applicable_roles:
                membership = dict(membership_rows or [])
                if not policy["roles"] or any(membership.get(role) is not False for role in policy["roles"]):
                    findings.miss(
                        "policy_roles_unproven",
                        role_field,
                        "policy role applicability unobserved",
                        (PRIMARY_SESSION, "role-membership"),
                    )
                continue
            for key in ("qual", "with_check"):
                if key == "with_check" and policy["command"] == "SELECT":
                    continue
                norm = _normalize_policy(policy[key])
                field = f"catalog.rls.{table}.policies.{policy['name']}.{key}"
                if policy["permissive"] and norm in ("true", ""):
                    findings.contradict(
                        "unsafe_policy_predicate",
                        field,
                        "permissive policy admits unrestricted rows",
                        (PRIMARY_SESSION, "policies"),
                    )
                elif norm != _normalize_policy(NATIVE_POLICY):
                    findings.miss(
                        "policy_semantics_unrecognised",
                        field,
                        "policy semantics not recognized",
                        (PRIMARY_SESSION, "policies"),
                    )
        rls.append(
            {
                "schema": sel["expected_schema"],
                "table": table,
                "enabled": bool(enabled),
                "forced": bool(forced),
                "policies": policies,
            }
        )
    return {
        "connection_id": PRIMARY_SESSION,
        "extension_name": "vector",
        "extension_version": version,
        "vectors": vectors,
        "rls": rls,
    }


def _visibility(capture: _Capture, sel: dict[str, Any], findings: _Findings) -> dict[int, dict[str, Any]] | None:
    """Per-media committed-visibility facts for one session. Foreign rows are counted, never copied."""
    if not capture.ran("output-own") or not capture.ran("output-foreign"):
        return None
    label = capture.label
    if "operation_id" in sel:
        demand_own = capture.rows("demand-own") or []
    else:
        demand_own = []
        findings.miss(
            OPERATION_ID_NOT_SELECTED,
            f"visibility.{label}.operation_id",
            "producer did not select the operation; demand join not attempted",
            (label, "output-own"),
        )
    if "foreign_operation_id" in sel:
        demand_foreign = capture.rows("demand-foreign") or []
    else:
        demand_foreign = []
        findings.miss(
            FOREIGN_OPERATION_ID_NOT_SELECTED,
            f"visibility.{label}.foreign_operation_id",
            "producer did not select a foreign operation; demand isolation not attempted",
            (label, "output-own"),
        )
    run_rows = capture.rows("run-own") or []
    run = run_rows[0] if run_rows else None
    if run is None:
        findings.miss(
            "run_row_not_visible", f"visibility.{label}.run", "native run link not visible", (label, "run-own")
        )
    elif run[:2] != [sel["run_id"], sel["tenant_id"]] or (
        "operation_id" in sel and run[2] != sel["operation_id"]
    ):
        findings.contradict(
            "run_operation_mismatch",
            f"visibility.{label}.operation_id",
            "native run link differs from selection",
            (label, "run-own"),
        )
    request_digest = demand_own[0][1] if demand_own else None
    if "operation_id" in sel and not demand_own:
        findings.miss(
            DEMAND_ROW_NOT_VISIBLE,
            f"visibility.{label}.operation_id",
            "no committed demand row for the selected operation is visible to this session",
            (label, "demand-own"),
        )
    if request_digest is not None and not _H64.fullmatch(str(request_digest)):
        findings.contradict(
            REQUEST_DIGEST_MALFORMED,
            f"visibility.{label}.request_digest",
            "not a lowercase 64-hex digest",
            (label, "demand-own"),
        )
        request_digest = None
    if demand_foreign:
        findings.contradict(
            FOREIGN_TENANT_VISIBLE,
            f"visibility.{label}.foreign_demand_rows",
            f"{len(demand_foreign)} foreign demand rows visible",
            (label, "demand-foreign"),
        )
    foreign_output = capture.rows("output-foreign") or []
    if foreign_output:
        findings.contradict(
            FOREIGN_TENANT_VISIBLE,
            f"visibility.{label}.foreign_output_rows",
            f"{len(foreign_output)} foreign output rows visible",
            (label, "output-foreign"),
        )
    findings.miss(
        FOREIGN_UNWITNESSED,
        f"connection.{label}.foreign_existence",
        "no foreign existence witness: zero visible foreign rows do not prove isolation",
        (label, "output-foreign"),
    )
    output_rows = capture.rows("output-own") or []
    for row in output_rows:
        if row[2] != "completed" or row[3] != "final_gpu":
            findings.miss(
                "output_row_not_final",
                f"visibility.{label}.{row[1]}.final",
                "output is not completed final_gpu",
                (label, "output-own"),
            )
        model = row[5]
        if model is None:
            findings.miss(
                OUTPUT_MODEL_UNOBSERVED,
                f"visibility.{label}.{row[1]}.reported_model_id",
                "output row carries no model_id claim",
                (label, "output-own"),
            )
        elif model != sel["expected_model_id"]:
            findings.contradict(
                OUTPUT_MODEL_MISMATCH,
                f"visibility.{label}.{row[1]}.reported_model_id",
                f"observed {model!r}",
                (label, "output-own"),
            )
    models = {row[5] for row in output_rows if row[5] is not None}
    if len(models) > 1:
        findings.contradict(
            MIXED_OUTPUT_MODELS,
            f"visibility.{label}.run.reported_model_id",
            f"run carries models {sorted(models)}",
            (label, "output-own"),
        )
    result: dict[int, dict[str, Any]] = {}
    for media_id in sel["media_ids"]:
        mine = [row for row in output_rows if row[1] == media_id]
        if not mine:
            findings.miss(
                OUTPUT_ROW_NOT_VISIBLE,
                f"visibility.{label}.{media_id}",
                "no committed output row for the selected media is visible to this session",
                (label, "output-own"),
            )
        result_generation = mine[0][4] if mine else None
        for row in mine:
            if row[4] != sel["result_generation"]:
                findings.contradict(
                    RESULT_GENERATION_MISMATCH,
                    f"visibility.{label}.{media_id}.result_generation",
                    f"observed {row[4]} expected {sel['result_generation']}",
                    (label, "output-own"),
                )
        caption_sha = mine[0][6] if mine else None
        if mine and caption_sha is None:
            findings.miss(
                CAPTION_SHA256_UNAVAILABLE,
                f"visibility.{label}.{media_id}.caption_sha256",
                "committed row has no caption to hash",
                (label, "output-own"),
            )
        findings.miss(
            FIRST_REVISION_UNPERSISTED,
            f"visibility.{label}.{media_id}.first_counting_revision",
            "no committed binding of the operation to its first counting revision exists in PG",
            (label, "demand-own") if "operation_id" in sel else None,
        )
        result[media_id] = {
            "connection_id": label,
            "tenant_id": run[1] if run else None,
            "operation_id": run[2] if run else None,
            "request_digest": request_digest,
            "first_counting_revision": None,
            "run_id": run[0] if run else None,
            "media_id": media_id,
            "result_generation": result_generation,
            "caption_sha256": caption_sha,
            "own_demand_rows": len(demand_own) if "operation_id" in sel else None,
            "own_output_rows": len(mine),
            "foreign_demand_rows": len(demand_foreign) if "foreign_operation_id" in sel else None,
            "foreign_output_rows": len(foreign_output),
            "foreign_witness_refs": [],
        }
    return result


def _analyse(sel: dict[str, Any], captures: dict[str, _Capture], findings: _Findings) -> None:
    """Derive observations and issues from persisted receipts only. A non-persisted receipt cites nothing."""
    primary = captures.get(PRIMARY_SESSION)
    independent = captures.get(INDEPENDENT_SESSION)
    for capture in (primary, independent):
        if capture is None or not capture.persisted:
            continue
        data = _connection_observation(capture, sel, findings)
        if data is not None:
            findings.observations.append(
                {
                    "observation_id": f"pg:connection:{capture.label}",
                    "kind": "connection",
                    "observed_at": capture.finished_at("identity"),
                    "artifact_relative_path": capture.path,
                    "artifact_sha256": capture.sha256,
                    "source_artifacts": [],
                    "data": data,
                }
            )
    if primary is not None and primary.persisted:
        catalog = _catalog_observation(primary, sel, findings)
        if catalog is not None:
            findings.observations.append(
                {
                    "observation_id": "pg:catalog:primary",
                    "kind": "catalog",
                    "observed_at": primary.finished_at("rls-flags"),
                    "artifact_relative_path": primary.path,
                    "artifact_sha256": primary.sha256,
                    "source_artifacts": [],
                    "data": catalog,
                }
            )
    per_session: dict[str, dict[int, dict[str, Any]]] = {}
    for capture in (primary, independent):
        if capture is None or not capture.persisted:
            continue
        visibility = _visibility(capture, sel, findings)
        if visibility is None:
            continue
        per_session[capture.label] = visibility
        for media_id, data in visibility.items():
            source = []
            if capture is independent and primary is not None and primary.persisted and primary.ran("output-own"):
                primary_ref = primary.ref("output-own")
                if primary_ref is not None:
                    source.append(primary_ref)
            findings.observations.append(
                {
                    "observation_id": f"pg:visibility:{capture.label}:media-{media_id}",
                    "kind": "visibility",
                    "observed_at": capture.finished_at("output-own"),
                    "artifact_relative_path": capture.path,
                    "artifact_sha256": capture.sha256,
                    "source_artifacts": source,
                    "data": data,
                }
            )
    independent_view = per_session.get(INDEPENDENT_SESSION, {})
    primary_view = per_session.get(PRIMARY_SESSION, {})
    for media_id, data in independent_view.items():
        if data["own_output_rows"] < 1 or (data["own_demand_rows"] is not None and data["own_demand_rows"] < 1):
            findings.miss(
                NOT_VISIBLE_INDEPENDENT,
                f"visibility.{INDEPENDENT_SESSION}.{media_id}",
                "committed demand or output row is not visible on the independent session",
                (INDEPENDENT_SESSION, "output-own"),
            )
        other = primary_view.get(media_id)
        if other is not None and (
            any(
                other[key] != data[key]
                for key in (
                    "own_output_rows",
                    "own_demand_rows",
                    "caption_sha256",
                    "request_digest",
                    "result_generation",
                )
            )
        ):
            findings.miss(
                VISIBILITY_SESSION_DISAGREEMENT,
                f"visibility.{media_id}",
                "primary and independent sessions disagree; only rows both sessions see count as committed",
                (PRIMARY_SESSION, "output-own"),
            )


def _issue(entry: dict[str, Any], captures: dict[str, _Capture]) -> dict[str, Any]:
    refs: list[dict[str, Any]] = []
    if entry["ref"] is not None:
        label, query_id = entry["ref"]
        capture = captures.get(label)
        ref = capture.ref(query_id) if capture is not None else None
        if ref is not None:
            refs.append(ref)
    return {"code": entry["code"], "field": entry["field"], "detail": entry["detail"], "artifact_refs": refs}


def _assemble(findings: _Findings, captures: dict[str, _Capture]) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    raw: dict[str, bytes] = {}
    for capture in captures.values():
        if not capture.persisted:
            continue
        queries = capture.queries
        raw[capture.path] = capture.raw
        artifacts.append(
            {
                "relative_path": capture.path,
                "sha256": capture.sha256,
                "command_argv": [],
                "exit_code": None,
                "capture_started_at": queries[0]["started_at"] if queries else None,
                "capture_finished_at": queries[-1]["finished_at"] if queries else None,
            }
        )
    artifacts.sort(key=lambda artifact: artifact["relative_path"])
    missing = [_issue(entry, captures) for entry in findings.missing]
    contradictions = [_issue(entry, captures) for entry in findings.contradictions]
    if contradictions:
        status = "contradicted"
    elif missing:
        status = "incomplete"
    else:
        status = "complete"
    return {
        "section": {
            "status": status,
            "observations": findings.observations,
            "missing_reasons": missing,
            "contradictions": contradictions,
        },
        "artifacts": artifacts,
        "raw_artifacts": dict(sorted(raw.items())),
    }


def collect_pg_evidence(*, connect: Any, selection: Any, deadline: Any) -> dict[str, Any]:
    """Collect restricted PostgreSQL evidence for section ``pg`` under one absolute deadline.

    ``connect(**kwargs)`` returns a session exposing ``query(sql, params) -> rows`` and ``close()``.
    ``deadline.remaining_seconds() -> float`` is the only time source. Returns the frozen ABI v1 envelope
    fragment ``{section, artifacts, raw_artifacts}``. The caller persists ``raw_artifacts`` before assembling
    the JSON envelope.
    """
    findings = _Findings()
    captures: dict[str, _Capture] = {}
    sel = _read_selection(selection, findings)
    if sel is not None:
        try:
            _observe(connect, sel, deadline, findings, captures)
        except _HaltError as halt:
            findings.absorb(halt)
        finally:
            _close_all(captures, findings, deadline)
        _serialize(captures, findings)
        _analyse(sel, captures, findings)
    return _assemble(findings, captures)
