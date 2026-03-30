"""Core handoff module — thin re-export layer.

Domain logic lives in submodules: _shared, handoff_state, decisions,
review_findings, lanes, import_export.  This file keeps: plan cursor
functions, FTS search + search_handoff, compound tools (load_session,
close_slice), artifact tools, deprecated aliases, and re-exports needed
by api.py / __init__.py / tests.
"""
from __future__ import annotations

import json
import re
import sqlite3

from .runtime import get_runtime_config
from . import artifact_index as artifact_index

# Re-exports: _shared public types, constants, and utilities
from ._shared import (  # noqa: F401
    # Public types (required by __init__.py)
    WriteActor, ResolvedWriteContext, TokenUsage, PromptMetrics, ReviewFindingDetails,
    LaneMessagePayload, build_write_actor,
    # Schema constants
    HANDOFF_SCHEMA_SQL, HANDOFF_FTS_SCHEMA_SQL, DEFAULT_HANDOFF_LIMITS,
    # Status / set constants (accessed by tests and domain modules)
    HANDOFF_ACTIVE_STATUSES, BLOCKER_STATUSES, ACTION_STATUSES,
    REVIEW_FINDING_STATUSES, REVIEW_FINDING_SEVERITIES,
    REVIEW_MODES, REVIEW_KINDS, REVIEW_SCOPE_SOURCES,
    LANE_STATUSES, CLOSEABLE_LANE_STATUSES, REPORT_STATUSES,
    MESSAGE_STATUSES, LANE_MESSAGE_DIRECTIONS, PLAN_CURSOR_STATES,
    MANDATORY_SLICE_DECISION_HEADINGS,
    MAX_RESOLUTION_NOTES_LENGTH, MAX_REOPEN_REASON_LENGTH,
    MAX_VERIFICATION_EVIDENCE_LENGTH, BATCH_CLOSE_WINDOW_SECONDS,
    BATCH_CLOSE_THRESHOLD, REOPEN_ESCALATION_THRESHOLD,
    # DB + resolution utilities
    _get_db_connection, _normalize_optional_text, _json_response, _row_to_dict,
    _resolve_task_ref, _fetch_handoff_rows, _paginated_query, _count_task_rows,
    _summarize_test_result,
    # Git helpers (monkeypatched by tests via handoff_core.X)
    _detect_git_write_context, _classify_commit_relation, _workspace_git_context,
    _resolve_write_actor,
    # Tool invocation + snapshot helpers (required by api.py via core.X)
    _invoke_tool, _fetch_related_open_findings, _render_current_task_md,
    _write_current_task_md_from_state, _write_current_task_md_for_task,
    _collect_task_snapshot, _build_current_task_state_from_snapshot, _workspace_root,
    # Slice decision helpers + lane message normalizer (required by tests)
    is_slice_complete_decision, extract_slice_label, classify_decision_id, is_canonical_decision,
    _normalize_lane_message_payload,
)

# Re-exports: domain modules (all accessed via api.py as core.X)
from .handoff_state import set_handoff_state, get_handoff_state, _get_handoff_dashboard_view
from .decisions import (  # noqa: F401
    record_decision, update_next_actions, list_next_actions,
    record_test_result, report_blocker, _collect_task_provenance_integrity, handoff_close_check,
    audit_decision_ids,
)
from .review_findings import (  # noqa: F401
    _check_reopen_escalation_guard, _check_batch_close_guard, _check_commit_relation_guard,
    record_review_finding, batch_record_review_findings, update_review_finding, list_review_findings,
    get_review_findings_summary, _collect_review_findings_integrity, reconcile_review_findings,
    record_review_run, list_review_runs, get_review_coverage,
)
from .lanes import (  # noqa: F401
    _get_lane_row, upsert_worktree_lane, close_worktree_lane, list_worktree_lanes,
    record_turn_metric, list_turn_metrics, get_turn_metrics_summary,
    get_lane_activity, get_latest_slice_review_packet,
    record_worker_report, list_worker_reports,
    record_lane_message, record_lane_brief, update_lane_message,
    list_lane_messages, list_lane_briefs,
)
from .import_export import (  # noqa: F401
    export_handoff_state, _set_import_active_state, _import_snapshot,
    import_handoff_state, archive_task_state, switch_task,
)

# FTS search constants and search_handoff
_FTS5_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_VALID_RECORD_TYPES: frozenset[str] = frozenset({"decision", "finding", "blocker", "action"})

_RECORD_TYPE_FTS_MAP: dict[str, tuple[str, bool]] = {
    "decision": ("decisions_fts", False),
    "finding":  ("findings_fts",  True),
    "blocker":  ("blockers_fts",  True),
    "action":   ("actions_fts",   True),
}


def search_handoff(
    queries: list[str] | None = None,
    task_ref: str | None = None,
    lane_id: str | None = None,
    record_types: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Search canonical handoff records by keyword with optional scope filters."""
    if not queries:
        return _json_response({"ok": False, "error": "queries must be a non-empty list of search terms."})

    validated_types: list[str]
    if record_types is None:
        validated_types = sorted(_VALID_RECORD_TYPES)
    else:
        invalid = set(record_types) - _VALID_RECORD_TYPES
        if invalid:
            return _json_response({
                "ok": False,
                "error": f"Invalid record_types: {sorted(invalid)}. Valid: {sorted(_VALID_RECORD_TYPES)}.",
            })
        validated_types = list(dict.fromkeys(record_types))

    clamped_limit = max(1, min(int(limit), 200))
    fts_terms: list[str] = []
    for q in queries:
        stripped = _FTS5_CONTROL_RE.sub(" ", q).strip()
        if stripped:
            fts_terms.append('"' + stripped.replace('"', '""') + '"')
    if not fts_terms:
        return _json_response({"ok": False, "error": "All query strings are empty after stripping."})
    fts_query = " OR ".join(fts_terms)

    results: list[dict] = []
    with _get_db_connection() as conn:
        tables_exist = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('table','shadow') AND name = 'decisions_fts'",
        ).fetchone()[0] > 0
        if not tables_exist:
            return _json_response({
                "ok": False,
                "error": "Structured FTS index is unavailable (FTS5 not enabled). Run 'agent-handoff-mcp doctor' to verify.",
            })
        effective_task_ref: str | None = task_ref
        if effective_task_ref is None:
            _active = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
            effective_task_ref = str(_active["task_ref"]) if _active else None

        for rtype in validated_types:
            fts_table, has_status = _RECORD_TYPE_FTS_MAP[rtype]
            status_col = "status" if has_status else "NULL AS status"
            where_parts = [f"{fts_table} MATCH ?"]
            params: list[object] = [fts_query]
            if effective_task_ref:
                where_parts.append("task_ref = ?")
                params.append(effective_task_ref)
            if lane_id:
                where_parts.append("lane_id = ?")
                params.append(lane_id)
            where_sql = " AND ".join(where_parts)
            try:
                rows = conn.execute(
                    f"""
                    SELECT record_id, task_ref, lane_id, {status_col},
                           snippet({fts_table}, 0, '', '', '...', 12) AS snippet,
                           rank
                    FROM {fts_table}
                    WHERE {where_sql}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (*params, clamped_limit),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                return _json_response({"ok": False, "error": f"FTS5 query error: {exc}"})
            for row in rows:
                results.append({
                    "record_type": rtype,
                    "record_id": int(row["record_id"]),
                    "task_ref": row["task_ref"],
                    "lane_id": row["lane_id"],
                    "status": row["status"],
                    "snippet": (row["snippet"] or "").strip(),
                    "_rank": float(row["rank"] or 0.0),
                })

    results.sort(key=lambda r: r["_rank"])
    for r in results:
        r.pop("_rank")
    return _json_response({
        "ok": True,
        "results": results[:clamped_limit],
        "total": len(results),
        "query": fts_query,
        "record_types_searched": validated_types,
    })


# Plan cursor functions


def _evaluate_clean_slice_gate(
    conn: sqlite3.Connection,
    task_ref: str,
    lane_id: str | None,
    since: str | None,
) -> dict | None:
    """Check clean-slice preconditions. Returns error payload dict or None if clean."""
    open_high_query = ["SELECT COUNT(*) AS count FROM review_findings WHERE task_ref = ? AND status = 'open' AND severity = 'high'"]
    open_high_params: list[object] = [task_ref]
    if lane_id is not None:
        open_high_query.append("AND lane_id = ?")
        open_high_params.append(lane_id)
    open_high_count = int(conn.execute(" ".join(open_high_query), tuple(open_high_params)).fetchone()["count"])
    test_query = ["SELECT COUNT(*) AS count FROM verified_tests WHERE task_ref = ?"]
    test_params: list[object] = [task_ref]
    if since is not None:
        test_query.append("AND verified_at >= ?")
        test_params.append(since)
    fresh_test_count = int(conn.execute(" ".join(test_query), tuple(test_params)).fetchone()["count"])
    missing_gates: list[str] = []
    if open_high_count > 0:
        missing_gates.append("open_high_findings")
    if fresh_test_count == 0:
        missing_gates.append("missing_recent_test")
    if not missing_gates:
        return None
    return {
        "ok": False,
        "error": "require_clean_slice gate failed.",
        "missing_gates": missing_gates,
        "gate": {
            "require_clean_slice": True,
            "lane_scope": lane_id,
            "task_ref": task_ref,
            "open_high_count": open_high_count,
            "fresh_test_count": fresh_test_count,
            "tests_since": since,
        },
    }


def upsert_plan_cursor(
    plan_item_id: str,
    state: str,
    lane_id: str | None = None,
    mcp_action_id: int | None = None,
    worker_message_id: int | None = None,
    source_heading: str | None = None,
    summary: str | None = None,
    task_ref: str | None = None,
    require_clean_slice: bool = False,
) -> str:
    valid_states = {"dispatched", "completed", "skipped", "escalated"}
    normalized_plan_item_id = _normalize_optional_text(plan_item_id)
    normalized_lane_id = _normalize_optional_text(lane_id)
    normalized_heading = _normalize_optional_text(source_heading)
    normalized_summary = _normalize_optional_text(summary)
    if normalized_plan_item_id is None:
        return _json_response({"ok": False, "error": "plan_item_id is required."})
    if state not in valid_states:
        return _json_response({"ok": False, "error": f"Invalid state. Valid: {', '.join(sorted(valid_states))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        existing = conn.execute(
            "SELECT * FROM plan_cursors WHERE task_ref = ? AND plan_item_id = ?",
            (resolved_task_ref, normalized_plan_item_id),
        ).fetchone()
        if existing is None and normalized_summary is None:
            return _json_response({"ok": False, "error": "summary is required when creating a new plan cursor."})
        next_lane_id = (
            normalized_lane_id or _normalize_optional_text(existing["lane_id"])
        ) if existing is not None else normalized_lane_id
        if require_clean_slice:
            since_value = existing["updated_at"] if existing is not None else None
            gate_failure = _evaluate_clean_slice_gate(conn, resolved_task_ref, next_lane_id, since_value)
            if gate_failure is not None:
                return _json_response(gate_failure)
        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO plan_cursors (
                    task_ref, plan_item_id, state, lane_id, mcp_action_id, worker_message_id,
                    source_heading, summary, dispatch_count, dispatched_at, completed_at, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    CASE WHEN ? = 'dispatched' THEN 1 ELSE 0 END,
                    CASE WHEN ? = 'dispatched' THEN datetime('now') ELSE NULL END,
                    CASE WHEN ? = 'completed' THEN datetime('now') ELSE NULL END,
                    datetime('now'), datetime('now')
                )
                """,
                (resolved_task_ref, normalized_plan_item_id, state, normalized_lane_id,
                 mcp_action_id, worker_message_id, normalized_heading, normalized_summary,
                 state, state, state),
            )
            row = _row_to_dict(conn.execute("SELECT * FROM plan_cursors WHERE id = ?", (cur.lastrowid,)).fetchone())
            return _json_response({"ok": True, "cursor": row})
        next_summary = normalized_summary or str(existing["summary"])
        next_heading = normalized_heading or _normalize_optional_text(existing["source_heading"])
        next_action_id = mcp_action_id if mcp_action_id is not None else existing["mcp_action_id"]
        next_worker_message_id = worker_message_id if worker_message_id is not None else existing["worker_message_id"]
        dispatch_count = int(existing["dispatch_count"] or 0) + (1 if state == "dispatched" else 0)
        conn.execute(
            """
            UPDATE plan_cursors
            SET state = ?, lane_id = ?, mcp_action_id = ?, worker_message_id = ?,
                source_heading = ?, summary = ?, dispatch_count = ?,
                dispatched_at = CASE WHEN ? = 'dispatched' THEN datetime('now') ELSE dispatched_at END,
                completed_at = CASE WHEN ? = 'completed' THEN datetime('now') ELSE completed_at END,
                updated_at = datetime('now')
            WHERE task_ref = ? AND plan_item_id = ?
            """,
            (state, next_lane_id, next_action_id, next_worker_message_id, next_heading, next_summary,
             dispatch_count, state, state, resolved_task_ref, normalized_plan_item_id),
        )
        row = _row_to_dict(conn.execute(
            "SELECT * FROM plan_cursors WHERE task_ref = ? AND plan_item_id = ?",
            (resolved_task_ref, normalized_plan_item_id),
        ).fetchone())
        return _json_response({"ok": True, "cursor": row})


def get_plan_cursor(plan_item_id: str, task_ref: str | None = None) -> str:
    normalized_plan_item_id = _normalize_optional_text(plan_item_id)
    if normalized_plan_item_id is None:
        return _json_response({"ok": False, "error": "plan_item_id is required."})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        row = conn.execute(
            "SELECT * FROM plan_cursors WHERE task_ref = ? AND plan_item_id = ?",
            (resolved_task_ref, normalized_plan_item_id),
        ).fetchone()
        return _json_response({"ok": True, "task_ref": resolved_task_ref, "cursor": _row_to_dict(row)})


def list_plan_cursors(
    task_ref: str | None = None,
    state: str = "all",
    lane_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    valid_states = {"all", "dispatched", "completed", "skipped", "escalated"}
    if state not in valid_states:
        return _json_response({"ok": False, "error": f"Invalid state. Valid: {', '.join(sorted(valid_states))}"})
    limit = max(1, limit)
    offset = max(0, offset)
    normalized_lane_id = _normalize_optional_text(lane_id)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        if state != "all":
            where_sql += " AND state = ?"
            params.append(state)
        if normalized_lane_id is not None:
            where_sql += " AND lane_id = ?"
            params.append(normalized_lane_id)
        total, rows = _paginated_query(conn, "plan_cursors", where_sql, tuple(params), limit, offset, "updated_at DESC, id DESC")
        return _json_response({
            "ok": True,
            "task_ref": resolved_task_ref,
            "lane_id": normalized_lane_id,
            "state": state,
            "total_matching": total,
            "returned": len(rows),
            "has_more": offset + len(rows) < total,
            "cursors": rows,
        })


# Artifact tools (depend on artifact_index and config)
def record_artifact(
    source_kind: str,
    source_label: str,
    content: str,
    task_ref: str | None = None,
    lane_id: str | None = None,
    app_root: str | None = None,
    content_type: str = "text/plain",
    summary: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Index an artifact source in the sidecar artifact database."""
    config = get_runtime_config()
    sk = _normalize_optional_text(source_kind)
    sl = _normalize_optional_text(source_label)
    if sk is None:
        return _json_response({"ok": False, "error": "source_kind is required."})
    if sl is None:
        return _json_response({"ok": False, "error": "source_label is required."})
    if not content:
        return _json_response({"ok": False, "error": "content is required."})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
    try:
        result = artifact_index.upsert_source(
            task_ref=resolved_task_ref,
            lane_id=_normalize_optional_text(lane_id),
            app_root=_normalize_optional_text(app_root),
            source_kind=sk,
            source_label=sl,
            content_type=content_type or "text/plain",
            summary=_normalize_optional_text(summary),
            content=content,
            metadata=metadata,
            artifact_db_path=config.artifact_db_path,
        )
        return _json_response({"ok": True, **result})
    except RuntimeError as exc:
        return _json_response({"ok": False, "error": str(exc)})


def search_artifacts(
    queries: list[str] | None = None,
    task_ref: str | None = None,
    lane_id: str | None = None,
    app_root: str | None = None,
    source_kind: str | None = None,
    content_type: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> str:
    """Search indexed artifact chunks, or list sources when no queries given."""
    config = get_runtime_config()
    if not queries:
        resolved_task_ref: str | None = None
        if task_ref:
            with _get_db_connection() as conn:
                resolved_task_ref = _resolve_task_ref(conn, task_ref)
        try:
            rows = artifact_index.list_artifact_sources(
                task_ref=resolved_task_ref,
                lane_id=_normalize_optional_text(lane_id),
                app_root=_normalize_optional_text(app_root),
                source_kind=_normalize_optional_text(source_kind),
                limit=max(1, int(limit)),
                offset=max(0, int(offset)),
                artifact_db_path=config.artifact_db_path,
            )
            return _json_response({"ok": True, "mode": "sources", "total": len(rows), "sources": rows})
        except RuntimeError as exc:
            return _json_response({"ok": False, "error": str(exc)})
    if not isinstance(queries, list):
        return _json_response({"ok": False, "error": "queries must be a list of strings or null/empty for source listing."})
    scope: dict[str, str | None] = {}
    if task_ref:
        with _get_db_connection() as conn:
            scope["task_ref"] = _resolve_task_ref(conn, task_ref)
    else:
        scope["task_ref"] = None
    try:
        hits = artifact_index.search_artifacts(
            queries=queries,
            task_ref=scope["task_ref"],
            lane_id=_normalize_optional_text(lane_id),
            app_root=_normalize_optional_text(app_root),
            source_kind=_normalize_optional_text(source_kind),
            content_type=_normalize_optional_text(content_type),
            limit=max(1, int(limit)),
            artifact_db_path=config.artifact_db_path,
        )
        return _json_response({"ok": True, "mode": "search", "total": len(hits), "hits": hits})
    except RuntimeError as exc:
        return _json_response({"ok": False, "error": str(exc)})


def get_artifact(
    source_id: int | None = None,
    task_ref: str | None = None,
    source_label: str | None = None,
    include_terms: bool = False,
    top_n_terms: int = 10,
) -> str:
    """Return the full artifact source record, optionally with distinctive terms."""
    config = get_runtime_config()
    if source_id is None and not (task_ref and source_label):
        return _json_response({"ok": False, "error": "Provide source_id or both task_ref and source_label."})
    resolved_task_ref: str | None = None
    if task_ref:
        with _get_db_connection() as conn:
            resolved_task_ref = _resolve_task_ref(conn, task_ref)
    try:
        source = artifact_index.get_artifact_source(
            source_id=source_id,
            task_ref=resolved_task_ref,
            source_label=_normalize_optional_text(source_label),
            artifact_db_path=config.artifact_db_path,
        )
        if source is None:
            return _json_response({"ok": False, "error": "Artifact source not found."})
        payload: dict[str, object] = {"ok": True, "source": source}
        if include_terms:
            resolved_source_id = source["id"]
            terms = artifact_index.get_distinctive_terms(
                source_id=resolved_source_id,
                artifact_db_path=config.artifact_db_path,
                top_n=max(1, int(top_n_terms)),
            )
            payload["source_id"] = resolved_source_id
            payload["terms"] = terms
        return _json_response(payload)
    except RuntimeError as exc:
        return _json_response({"ok": False, "error": str(exc)})


def purge_artifacts(
    task_ref: str | None = None,
    lane_id: str | None = None,
    app_root: str | None = None,
    older_than_days: int | None = None,
) -> str:
    """Delete artifact sources and their FTS chunks."""
    config = get_runtime_config()
    resolved_task_ref: str | None = None
    if task_ref:
        with _get_db_connection() as conn:
            resolved_task_ref = _resolve_task_ref(conn, task_ref)
    if resolved_task_ref is None and lane_id is None and app_root is None and older_than_days is None:
        return _json_response({"ok": False, "error": "Provide task_ref, lane_id, app_root, older_than_days, or a combination."})
    try:
        result = artifact_index.purge_artifacts(
            task_ref=resolved_task_ref,
            lane_id=_normalize_optional_text(lane_id),
            app_root=_normalize_optional_text(app_root),
            older_than_days=older_than_days,
            artifact_db_path=config.artifact_db_path,
        )
        return _json_response(result)
    except RuntimeError as exc:
        return _json_response({"ok": False, "error": str(exc)})


# Compound tools (cross-module orchestration)
def load_session(task_ref: str | None = None) -> str:
    """Load session context: get_handoff_state + list_review_findings(open) in one call."""
    state_raw = get_handoff_state(task_ref=task_ref)
    state = json.loads(state_raw)
    if not state.get("ok"):
        return state_raw
    resolved_task_ref = state.get("task_ref")
    findings_raw = list_review_findings(task_ref=resolved_task_ref, status="open")
    findings = json.loads(findings_raw)
    return _json_response({
        "ok": True,
        "task_ref": resolved_task_ref,
        "state": state,
        "open_findings": findings.get("findings", []) if findings.get("ok") else [],
        "open_findings_count": findings.get("total_matching", 0) if findings.get("ok") else 0,
    })


def close_slice(
    session: str,
    decision: str,
    rationale: str | None = None,
    actor: WriteActor | None = None,
    expected_revision: int | None = None,
    task_ref: str | None = None,
    focus: str | None = None,
) -> str:
    """Close a slice: record_decision + set_handoff_state + generate CURRENT_TASK.md."""
    decision_raw = record_decision(session=session, decision=decision, rationale=rationale, actor=actor, task_ref=task_ref)
    decision_result = json.loads(decision_raw)
    if not decision_result.get("ok"):
        return decision_raw
    resolved_task_ref = decision_result.get("task_ref", task_ref)
    set_kwargs: dict[str, object] = {"task_ref": resolved_task_ref, "status": "in_progress"}
    if focus is not None:
        set_kwargs["focus"] = focus
    if expected_revision is not None:
        set_kwargs["expected_revision"] = expected_revision
    if actor is not None:
        set_kwargs["actor"] = actor
    state_raw = set_handoff_state(**set_kwargs)
    state_result = json.loads(state_raw)
    if not state_result.get("ok"):
        return _json_response({
            "ok": False,
            "task_ref": resolved_task_ref,
            "decision_recorded": True,
            "state_updated": False,
            "state_error": state_result.get("error"),
            "current_task_md_written": False,
        })
    _write_current_task_md_from_state(resolved_task_ref)
    return _json_response({
        "ok": True,
        "task_ref": resolved_task_ref,
        "decision_recorded": True,
        "state_updated": True,
        "state_error": None,
        "current_task_md_written": True,
    })


