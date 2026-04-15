"""Core handoff module — thin re-export layer.

Domain logic lives in submodules: _shared, handoff_state, decisions,
review_findings, lanes, import_export.  This file keeps: plan cursor
functions, FTS search + search_handoff, compound tools (load_session,
close_slice), artifact tools, deprecated aliases, and re-exports needed
by api.py / __init__.py / tests.
"""

from __future__ import annotations

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
    _envelope,
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
    _render_current_task_json,
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
    get_archived_task,
    import_handoff_state,
    switch_task,
    update_task_status,
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
    repair_review_finding_provenance,
    update_review_finding,
)
from .runtime import get_runtime_config
from .touched_files import DEFAULT_TOUCHED_FILES_LIMIT, ChangeKind, get_touched_files, record_file_touch  # noqa: F401
from .verified_tests import get_verified_tests  # noqa: F401

# FTS search constants and search_handoff
_FTS5_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_VALID_RECORD_TYPES: frozenset[str] = frozenset({"decision", "finding", "blocker", "action", "verified_test"})

_RECORD_TYPE_FTS_MAP: dict[str, tuple[str, bool]] = {
    "decision": ("decisions_fts", False),
    "finding": ("findings_fts", True),
    "blocker": ("blockers_fts", True),
    "action": ("actions_fts", True),
    "verified_test": ("verified_tests_fts", False),
}

_VALID_DETAIL_LEVELS: frozenset[str] = frozenset({"full", "summary"})
_ARTIFACT_TEXT_SUMMARY_TRUNCATE = 200
_ARTIFACT_CHUNK_TITLE_SUMMARY_TRUNCATE = 120
_ARTIFACT_CHUNK_SUMMARY_LIMIT = 3
_HANDOFF_SEARCH_SUMMARY_TRUNCATE = 80

_VALID_ARTIFACT_HIT_FIELDS: frozenset[str] = frozenset(
    {
        "source_id",
        "source_label",
        "source_summary",
        "task_ref",
        "lane_id",
        "app_root",
        "source_kind",
        "content_type",
        "title",
        "snippet",
        "rank",
    }
)
_VALID_ARTIFACT_SOURCE_LIST_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "task_ref",
        "lane_id",
        "app_root",
        "source_kind",
        "source_label",
        "content_type",
        "content_hash",
        "metadata_json",
        "summary",
        "created_at",
        "updated_at",
    }
)
_VALID_ARTIFACT_GET_FIELDS: frozenset[str] = _VALID_ARTIFACT_SOURCE_LIST_FIELDS | frozenset(
    {"metadata", "chunk_count", "chunks"}
)
_VALID_HANDOFF_SEARCH_FIELDS: frozenset[str] = frozenset(
    {"record_type", "record_id", "task_ref", "lane_id", "status", "snippet"}
)

_ARTIFACT_HIT_IDENTITY_FIELDS: frozenset[str] = frozenset({"source_id", "source_label", "title", "snippet"})
_ARTIFACT_SOURCE_IDENTITY_FIELDS: frozenset[str] = frozenset(
    {"id", "task_ref", "source_label", "source_kind", "content_type"}
)
_ARTIFACT_GET_IDENTITY_FIELDS: frozenset[str] = frozenset(
    {"id", "task_ref", "source_label", "source_kind", "content_type", "chunk_count"}
)
_HANDOFF_SEARCH_IDENTITY_FIELDS: frozenset[str] = frozenset({"record_type", "record_id", "task_ref", "snippet"})


def _normalize_detail(detail: str) -> str:
    return detail if detail in _VALID_DETAIL_LEVELS else "full"


def _parse_projection_fields(fields: str | None, valid_fields: frozenset[str]) -> frozenset[str] | None:
    if fields is None:
        return None
    requested = frozenset(part.strip().lower() for part in fields.split(",") if part.strip())
    return requested & valid_fields


def _truncate_text(value: object, limit: int) -> object:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "..."
    return value


def _project_mapping(
    mapping: dict[str, object],
    requested_fields: frozenset[str] | None,
    identity_fields: frozenset[str],
) -> dict[str, object]:
    if requested_fields is None:
        allowed_fields: frozenset[str] | None = None
    else:
        allowed_fields = requested_fields or identity_fields
    return {key: value for key, value in mapping.items() if allowed_fields is None or key in allowed_fields}


def _summarize_artifact_hit(hit: dict[str, object]) -> dict[str, object]:
    summarized = dict(hit)
    summarized["source_summary"] = _truncate_text(summarized.get("source_summary"), _ARTIFACT_TEXT_SUMMARY_TRUNCATE)
    summarized["snippet"] = _truncate_text(summarized.get("snippet"), _ARTIFACT_TEXT_SUMMARY_TRUNCATE)
    return summarized


def _summarize_artifact_source(source: dict[str, object]) -> dict[str, object]:
    summarized = dict(source)
    summarized["summary"] = _truncate_text(summarized.get("summary"), _ARTIFACT_TEXT_SUMMARY_TRUNCATE)
    summarized["metadata_json"] = _truncate_text(summarized.get("metadata_json"), _ARTIFACT_TEXT_SUMMARY_TRUNCATE)
    chunks = summarized.get("chunks")
    if isinstance(chunks, list):
        chunk_preview: list[object] = []
        for chunk in chunks[:_ARTIFACT_CHUNK_SUMMARY_LIMIT]:
            if isinstance(chunk, dict):
                summarized_chunk = dict(chunk)
                summarized_chunk["title"] = _truncate_text(
                    summarized_chunk.get("title"),
                    _ARTIFACT_CHUNK_TITLE_SUMMARY_TRUNCATE,
                )
                summarized_chunk["body"] = _truncate_text(
                    summarized_chunk.get("body"),
                    _ARTIFACT_TEXT_SUMMARY_TRUNCATE,
                )
                chunk_preview.append(summarized_chunk)
            else:
                chunk_preview.append(chunk)
        summarized["chunks"] = chunk_preview
    return summarized


def search_handoff(
    queries: list[str] | None = None,
    task_ref: str | None = None,
    lane_id: str | None = None,
    record_types: list[str] | None = None,
    limit: int = 20,
    detail: str = "full",
    fields: str | None = None,
) -> dict:
    """Search canonical handoff records by keyword with optional scope filters."""
    if not queries:
        return _envelope(
            ok=False, tool="search_handoff", data={"error": "queries must be a non-empty list of search terms."}
        )
    detail = _normalize_detail(detail)
    requested_fields = _parse_projection_fields(fields, _VALID_HANDOFF_SEARCH_FIELDS)

    validated_types: list[str]
    if record_types is None:
        validated_types = sorted(_VALID_RECORD_TYPES)
    else:
        invalid = set(record_types) - _VALID_RECORD_TYPES
        if invalid:
            return _envelope(
                ok=False,
                tool="search_handoff",
                data={"error": f"Invalid record_types: {sorted(invalid)}. Valid: {sorted(_VALID_RECORD_TYPES)}."},
            )
        validated_types = list(dict.fromkeys(record_types))

    clamped_limit = max(1, min(int(limit), 200))
    fts_terms: list[str] = []
    for q in queries:
        stripped = _FTS5_CONTROL_RE.sub(" ", q).strip()
        if stripped:
            fts_terms.append('"' + stripped.replace('"', '""') + '"')
    if not fts_terms:
        return _envelope(
            ok=False, tool="search_handoff", data={"error": "All query strings are empty after stripping."}
        )
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
            return _envelope(
                ok=False,
                tool="search_handoff",
                data={
                    "error": "Structured FTS index is unavailable (FTS5 not enabled). Run 'agent-handoff-mcp doctor' to verify."
                },
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
                return _envelope(ok=False, tool="search_handoff", data={"error": f"FTS5 query error: {exc}"})
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
    shaped_results: list[dict[str, object]] = []
    for result in results[:clamped_limit]:
        shaped = dict(result)
        shaped.pop("_rank", None)
        if detail == "summary":
            shaped["snippet"] = _truncate_text(shaped.get("snippet"), _HANDOFF_SEARCH_SUMMARY_TRUNCATE)
        shaped_results.append(_project_mapping(shaped, requested_fields, _HANDOFF_SEARCH_IDENTITY_FIELDS))
    return _envelope(
        ok=True,
        tool="search_handoff",
        data={
            "results": shaped_results,
            "total": len(results),
            "query": fts_query,
            "record_types_searched": validated_types,
        },
        task_ref=effective_task_ref,
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
) -> dict:
    """Index an artifact source in the sidecar artifact database."""
    config = get_runtime_config()
    sk = _normalize_optional_text(source_kind)
    sl = _normalize_optional_text(source_label)
    if sk is None:
        return _envelope(ok=False, tool="record_artifact", data={"error": "source_kind is required."})
    if sl is None:
        return _envelope(ok=False, tool="record_artifact", data={"error": "source_label is required."})
    if not content:
        return _envelope(ok=False, tool="record_artifact", data={"error": "content is required."})
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
        return _envelope(
            ok=True,
            tool="record_artifact",
            data=result,
            task_ref=resolved_task_ref,
            mutation={"entity": "artifact_source", "operation": "upsert"},
        )
    except RuntimeError as exc:
        return _envelope(ok=False, tool="record_artifact", data={"error": str(exc)}, task_ref=resolved_task_ref)


def search_artifacts(
    queries: list[str] | None = None,
    task_ref: str | None = None,
    lane_id: str | None = None,
    app_root: str | None = None,
    source_kind: str | None = None,
    content_type: str | None = None,
    limit: int = 10,
    offset: int = 0,
    detail: str = "full",
    fields: str | None = None,
) -> dict:
    """Search indexed artifact chunks, or list sources when no queries given."""
    config = get_runtime_config()
    detail = _normalize_detail(detail)
    if not queries:
        requested_fields = _parse_projection_fields(fields, _VALID_ARTIFACT_SOURCE_LIST_FIELDS)
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
            shaped_rows = [
                _project_mapping(
                    _summarize_artifact_source(dict(row)) if detail == "summary" else dict(row),
                    requested_fields,
                    _ARTIFACT_SOURCE_IDENTITY_FIELDS,
                )
                for row in rows
            ]
            return _envelope(
                ok=True,
                tool="search_artifacts",
                data={"mode": "sources", "total": len(rows), "sources": shaped_rows},
                task_ref=resolved_task_ref,
            )
        except RuntimeError as exc:
            return _envelope(ok=False, tool="search_artifacts", data={"error": str(exc)}, task_ref=resolved_task_ref)
    requested_fields = _parse_projection_fields(fields, _VALID_ARTIFACT_HIT_FIELDS)
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
        shaped_hits = [
            _project_mapping(
                _summarize_artifact_hit(dict(hit)) if detail == "summary" else dict(hit),
                requested_fields,
                _ARTIFACT_HIT_IDENTITY_FIELDS,
            )
            for hit in hits
        ]
        return _envelope(
            ok=True,
            tool="search_artifacts",
            data={"mode": "search", "total": len(hits), "hits": shaped_hits},
            task_ref=scope["task_ref"],
        )
    except RuntimeError as exc:
        return _envelope(ok=False, tool="search_artifacts", data={"error": str(exc)}, task_ref=scope["task_ref"])


def get_artifact(
    source_id: int | None = None,
    task_ref: str | None = None,
    source_label: str | None = None,
    include_terms: bool = False,
    top_n_terms: int = 10,
    detail: str = "full",
    fields: str | None = None,
) -> dict:
    """Return the full artifact source record, optionally with distinctive terms."""
    config = get_runtime_config()
    detail = _normalize_detail(detail)
    requested_fields = _parse_projection_fields(fields, _VALID_ARTIFACT_GET_FIELDS)
    if source_id is None and not (task_ref and source_label):
        return _envelope(
            ok=False, tool="get_artifact", data={"error": "Provide source_id or both task_ref and source_label."}
        )
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
            return _envelope(
                ok=False, tool="get_artifact", data={"error": "Artifact source not found."}, task_ref=resolved_task_ref
            )
        shaped_source = _project_mapping(
            _summarize_artifact_source(dict(source)) if detail == "summary" else dict(source),
            requested_fields,
            _ARTIFACT_GET_IDENTITY_FIELDS,
        )
        data: dict[str, object] = {"source": shaped_source}
        if include_terms:
            resolved_source_id = source["id"]
            terms = artifact_index.get_distinctive_terms(
                source_id=resolved_source_id,
                artifact_db_path=config.artifact_db_path,
                top_n=max(1, int(top_n_terms)),
            )
            data["source_id"] = resolved_source_id
            data["terms"] = terms
        return _envelope(ok=True, tool="get_artifact", data=data, task_ref=resolved_task_ref)
    except RuntimeError as exc:
        return _envelope(ok=False, tool="get_artifact", data={"error": str(exc)}, task_ref=resolved_task_ref)


def purge_artifacts(
    task_ref: str | None = None,
    lane_id: str | None = None,
    app_root: str | None = None,
    older_than_days: int | None = None,
) -> dict:
    """Delete artifact sources and their FTS chunks."""
    config = get_runtime_config()
    resolved_task_ref: str | None = None
    if task_ref:
        with _get_db_connection() as conn:
            resolved_task_ref = _resolve_task_ref(conn, task_ref)
    if resolved_task_ref is None and lane_id is None and app_root is None and older_than_days is None:
        return _envelope(
            ok=False,
            tool="purge_artifacts",
            data={"error": "Provide task_ref, lane_id, app_root, older_than_days, or a combination."},
        )
    try:
        result = artifact_index.purge_artifacts(
            task_ref=resolved_task_ref,
            lane_id=_normalize_optional_text(lane_id),
            app_root=_normalize_optional_text(app_root),
            older_than_days=older_than_days,
            artifact_db_path=config.artifact_db_path,
        )
        return _envelope(
            ok=True,
            tool="purge_artifacts",
            data=result,
            task_ref=resolved_task_ref,
            mutation={"entity": "artifact_source", "operation": "delete"},
        )
    except RuntimeError as exc:
        return _envelope(ok=False, tool="purge_artifacts", data={"error": str(exc)}, task_ref=resolved_task_ref)


# Compound tools (cross-module orchestration)
def load_session(
    task_ref: str | None = None,
    sections: str | None = None,
    detail: str = "full",
    top_n_touched_files: int = DEFAULT_TOUCHED_FILES_LIMIT,
) -> dict:
    """Load session context: get_handoff_state + open findings + touched files.

    Passes ``sections`` and ``detail`` through to ``get_handoff_state`` and
    ``detail`` through to ``list_review_findings`` so callers can reduce
    payload size without making two separate calls.  The ``top_n_touched_files``
    parameter bounds the additive ``touched_files`` list (default 20).
    """
    state_envelope = get_handoff_state(task_ref=task_ref, sections=sections, detail=detail)
    if not state_envelope.get("ok"):
        return state_envelope
    state_data = state_envelope.get("data", {}) or {}
    resolved_task_ref = state_envelope.get("scope", {}).get("task_ref")
    findings_envelope = list_review_findings(task_ref=resolved_task_ref, status="open", detail=detail)
    findings_data = findings_envelope.get("data", {}) or {}
    findings_ok = bool(findings_envelope.get("ok"))
    touches_envelope = get_touched_files(task_ref=resolved_task_ref, limit=top_n_touched_files)
    touches_data = touches_envelope.get("data", {}) or {}
    touches_ok = bool(touches_envelope.get("ok"))
    return _envelope(
        ok=True,
        tool="load_session",
        data={
            "state": state_data,
            "open_findings": findings_data.get("findings", []) if findings_ok else [],
            "open_findings_count": findings_data.get("total_matching", 0) if findings_ok else 0,
            "touched_files": touches_data.get("touches", []) if touches_ok else [],
        },
        task_ref=resolved_task_ref,
    )


def close_slice(
    session: str,
    decision: str,
    rationale: str | None = None,
    actor: WriteActor | None = None,
    expected_revision: int | None = None,
    task_ref: str | None = None,
    focus: str | None = None,
    changed_files: list[str] | None = None,
) -> dict:
    """Record a slice-complete decision, keep the task in progress, and regenerate CURRENT_TASK.md."""
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        active_row = conn.execute(
            "SELECT revision FROM handoff_state WHERE id = 1 AND task_ref = ?",
            (resolved_task_ref,),
        ).fetchone()

    if active_row is not None:
        current_revision = int(active_row["revision"])
        if expected_revision is None:
            return _envelope(
                ok=False,
                tool="close_slice",
                data={
                    "error": (
                        "expected_revision is required for updates. "
                        "Fetch the active row first via get_handoff_state(sections='identity') "
                        "and pass its revision field as expected_revision."
                    ),
                    "state_error": (
                        "expected_revision is required for updates. "
                        "Fetch the active row first via get_handoff_state(sections='identity') "
                        "and pass its revision field as expected_revision."
                    ),
                    "decision_recorded": False,
                    "state_updated": False,
                    "current_revision": current_revision,
                    "current_task_md_written": False,
                },
                task_ref=resolved_task_ref,
            )
        if expected_revision != current_revision:
            return _envelope(
                ok=False,
                tool="close_slice",
                data={
                    "error": "Revision conflict.",
                    "state_error": "Revision conflict.",
                    "decision_recorded": False,
                    "state_updated": False,
                    "expected_revision": expected_revision,
                    "current_revision": current_revision,
                    "current_task_md_written": False,
                },
                task_ref=resolved_task_ref,
            )
    else:
        with _get_db_connection() as conn2:
            archived = conn2.execute(
                "SELECT 1 FROM task_archives WHERE task_ref = ?",
                (resolved_task_ref,),
            ).fetchone()
        if archived is not None:
            return _envelope(
                ok=False,
                tool="close_slice",
                data={
                    "error": "Cannot close a slice on an archived task. Switch to it first or use update_task_status.",
                    "state_error": "Cannot close a slice on an archived task. Switch to it first or use update_task_status.",
                    "decision_recorded": False,
                    "state_updated": False,
                    "current_task_md_written": False,
                },
                task_ref=resolved_task_ref,
            )

    decision_envelope = record_decision(
        session=session,
        decision=decision,
        rationale=rationale,
        actor=actor,
        task_ref=task_ref,
        changed_files=changed_files,
    )
    if not decision_envelope.get("ok"):
        return decision_envelope
    warnings: list[str] = []
    decision_warnings = decision_envelope.get("warnings")
    if isinstance(decision_warnings, list):
        warnings.extend(str(item) for item in decision_warnings if isinstance(item, str))
    decision_data = decision_envelope.get("data", {}) or {}
    decision_payload = decision_data.get("decision", {}) or {}
    resolved_task_ref = str(
        decision_envelope.get("scope", {}).get("task_ref") or decision_payload.get("task_ref") or task_ref
    )
    state_envelope = set_handoff_state(
        task_ref=resolved_task_ref,
        focus=focus,
        status="in_progress",
        expected_revision=expected_revision,
        actor=actor,
    )
    if not state_envelope.get("ok"):
        state_data = state_envelope.get("data", {}) or {}
        state_warnings = state_envelope.get("warnings")
        if isinstance(state_warnings, list):
            warnings.extend(str(item) for item in state_warnings if isinstance(item, str))
        return _envelope(
            ok=False,
            tool="close_slice",
            data={
                "error": state_data.get("error"),
                "state_error": state_data.get("error"),
                "decision_recorded": True,
                "state_updated": False,
                "current_task_md_written": False,
            },
            task_ref=resolved_task_ref,
            warnings=warnings or None,
        )
    state_data = state_envelope.get("data", {}) or {}
    active_block = state_data.get("active", {}) or {}
    state_warnings = state_envelope.get("warnings")
    if isinstance(state_warnings, list):
        warnings.extend(str(item) for item in state_warnings if isinstance(item, str))
    _write_current_task_md_from_state(resolved_task_ref)
    return _envelope(
        ok=True,
        tool="close_slice",
        data={
            "decision_recorded": True,
            "state_updated": True,
            "state_error": None,
            "current_task_md_written": True,
            "decision": decision_payload,
            "task_revision": active_block.get("revision"),
        },
        task_ref=resolved_task_ref,
        mutation={
            "entity": "decision",
            "operation": "close_slice",
            "task_revision": active_block.get("revision"),
        },
        artifacts=[{"type": "current_task_md", "path": "CURRENT_TASK.md", "written": True}],
        warnings=warnings or None,
    )
