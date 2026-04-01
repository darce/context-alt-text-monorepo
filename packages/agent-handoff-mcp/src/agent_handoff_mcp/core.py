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

from . import artifact_index as artifact_index

# Re-exports: _shared public types, constants, and utilities
from ._shared import (  # noqa: F401
    ACTION_STATUSES,
    BATCH_CLOSE_THRESHOLD,
    BATCH_CLOSE_WINDOW_SECONDS,
    BLOCKER_STATUSES,
    CLOSEABLE_LANE_STATUSES,
    DEFAULT_HANDOFF_LIMITS,
    # Status / set constants (accessed by tests and domain modules)
    HANDOFF_ACTIVE_STATUSES,
    HANDOFF_FTS_SCHEMA_SQL,
    # Schema constants
    HANDOFF_SCHEMA_SQL,
    LANE_MESSAGE_DIRECTIONS,
    LANE_STATUSES,
    MANDATORY_SLICE_DECISION_HEADINGS,
    MAX_REOPEN_REASON_LENGTH,
    MAX_RESOLUTION_NOTES_LENGTH,
    MAX_VERIFICATION_EVIDENCE_LENGTH,
    MESSAGE_STATUSES,
    PLAN_CURSOR_STATES,
    REOPEN_ESCALATION_THRESHOLD,
    REPORT_STATUSES,
    REVIEW_FINDING_SEVERITIES,
    REVIEW_FINDING_STATUSES,
    REVIEW_KINDS,
    REVIEW_MODES,
    REVIEW_SCOPE_SOURCES,
    LaneMessagePayload,
    PromptMetrics,
    ResolvedWriteContext,
    ReviewFindingDetails,
    TokenUsage,
    # Public types (required by __init__.py)
    WriteActor,
    _build_current_task_state_from_snapshot,
    _classify_commit_relation,
    _collect_all_deferred_findings,
    _collect_all_open_findings,
    _collect_dashboard_rows,
    _collect_task_snapshot,
    _count_task_rows,
    # Git helpers (monkeypatched by tests via handoff_core.X)
    _detect_git_write_context,
    _fetch_handoff_rows,
    _fetch_related_open_findings,
    # DB + resolution utilities
    _get_db_connection,
    # Tool invocation + snapshot helpers (required by api.py via core.X)
    _invoke_tool,
    _json_response,
    _normalize_lane_message_payload,
    _normalize_optional_text,
    _paginated_query,
    _render_current_task_md,
    _resolve_task_ref,
    _resolve_write_actor,
    _row_to_dict,
    _summarize_test_result,
    _workspace_git_context,
    _workspace_root,
    _write_current_task_md_for_task,
    _write_current_task_md_from_state,
    build_write_actor,
    classify_decision_id,
    extract_slice_label,
    is_canonical_decision,
    # Slice decision helpers + lane message normalizer (required by tests)
    is_slice_complete_decision,
)
from .decisions import (  # noqa: F401
    _collect_task_provenance_integrity,
    audit_decision_ids,
    handoff_close_check,
    list_next_actions,
    record_decision,
    record_test_result,
    report_blocker,
    update_next_actions,
)

# Re-exports: domain modules (all accessed via api.py as core.X)
from .handoff_state import get_handoff_state, set_handoff_state
from .import_export import (  # noqa: F401
    _import_snapshot,
    _set_import_active_state,
    archive_task_state,
    export_handoff_state,
    import_handoff_state,
    switch_task,
)
from .review_findings import (  # noqa: F401
    _check_batch_close_guard,
    _check_commit_relation_guard,
    _check_reopen_escalation_guard,
    _collect_review_findings_integrity,
    batch_record_review_findings,
    get_review_coverage,
    get_review_findings_summary,
    list_review_findings,
    list_review_runs,
    reconcile_review_findings,
    record_review_finding,
    record_review_run,
    update_review_finding,
)
from .runtime import get_runtime_config

# FTS search constants and search_handoff
_FTS5_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_VALID_RECORD_TYPES: frozenset[str] = frozenset({"decision", "finding", "blocker", "action"})

_RECORD_TYPE_FTS_MAP: dict[str, tuple[str, bool]] = {
    "decision": ("decisions_fts", False),
    "finding": ("findings_fts", True),
    "blocker": ("blockers_fts", True),
    "action": ("actions_fts", True),
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
            return _json_response(
                {
                    "ok": False,
                    "error": f"Invalid record_types: {sorted(invalid)}. Valid: {sorted(_VALID_RECORD_TYPES)}.",
                }
            )
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
        tables_exist = (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('table','shadow') AND name = 'decisions_fts'",
            ).fetchone()[0]
            > 0
        )
        if not tables_exist:
            return _json_response(
                {
                    "ok": False,
                    "error": "Structured FTS index is unavailable (FTS5 not enabled). Run 'agent-handoff-mcp doctor' to verify.",
                }
            )
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
                results.append(
                    {
                        "record_type": rtype,
                        "record_id": int(row["record_id"]),
                        "task_ref": row["task_ref"],
                        "lane_id": row["lane_id"],
                        "status": row["status"],
                        "snippet": (row["snippet"] or "").strip(),
                        "_rank": float(row["rank"] or 0.0),
                    }
                )

    results.sort(key=lambda r: r["_rank"])
    for r in results:
        r.pop("_rank")
    return _json_response(
        {
            "ok": True,
            "results": results[:clamped_limit],
            "total": len(results),
            "query": fts_query,
            "record_types_searched": validated_types,
        }
    )


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
        return _json_response(
            {"ok": False, "error": "Provide task_ref, lane_id, app_root, older_than_days, or a combination."}
        )
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
def load_session(
    task_ref: str | None = None,
    sections: str | None = None,
    detail: str = "full",
) -> str:
    """Load session context: get_handoff_state + list_review_findings(open) in one call.

    Passes ``sections`` and ``detail`` through to ``get_handoff_state`` and
    ``detail`` through to ``list_review_findings`` so callers can reduce
    payload size without making two separate calls.
    """
    state_raw = get_handoff_state(task_ref=task_ref, sections=sections, detail=detail)
    state = json.loads(state_raw)
    if not state.get("ok"):
        return state_raw
    resolved_task_ref = state.get("task_ref")
    findings_raw = list_review_findings(task_ref=resolved_task_ref, status="open", detail=detail)
    findings = json.loads(findings_raw)
    return _json_response(
        {
            "ok": True,
            "task_ref": resolved_task_ref,
            "state": state,
            "open_findings": findings.get("findings", []) if findings.get("ok") else [],
            "open_findings_count": findings.get("total_matching", 0) if findings.get("ok") else 0,
        }
    )


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
    decision_raw = record_decision(
        session=session, decision=decision, rationale=rationale, actor=actor, task_ref=task_ref
    )
    decision_result = json.loads(decision_raw)
    if not decision_result.get("ok"):
        return decision_raw
    resolved_task_ref = str(decision_result.get("task_ref", task_ref))
    state_raw = set_handoff_state(
        task_ref=resolved_task_ref,
        focus=focus,
        status="in_progress",
        expected_revision=expected_revision,
        actor=actor,
    )
    state_result = json.loads(state_raw)
    if not state_result.get("ok"):
        return _json_response(
            {
                "ok": False,
                "task_ref": resolved_task_ref,
                "decision_recorded": True,
                "state_updated": False,
                "state_error": state_result.get("error"),
                "current_task_md_written": False,
            }
        )
    _write_current_task_md_from_state(resolved_task_ref)
    return _json_response(
        {
            "ok": True,
            "task_ref": resolved_task_ref,
            "decision_recorded": True,
            "state_updated": True,
            "state_error": None,
            "current_task_md_written": True,
        }
    )
