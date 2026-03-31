"""Lanes domain module.

Contains worktree lane management, turn metrics, worker reports, and lane messages.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from agent_handoff_mcp.current_task_rendering import _write_current_task_md_for_task
from agent_handoff_mcp.shared_archival import _build_archival_lane_activity_summary
from agent_handoff_mcp.shared_db_utils import _fetch_handoff_rows, _paginated_query
from agent_handoff_mcp.shared_primitives import (
    CLOSEABLE_LANE_STATUSES,
    LANE_MESSAGE_DIRECTIONS,
    LANE_STATUSES,
    MESSAGE_STATUSES,
    REPORT_STATUSES,
    REVIEW_KINDS,
    PromptMetrics,
    TokenUsage,
    _decode_lane_message_row_dict,
    _decode_turn_metric_row_dict,
    _json_response,
    _normalize_lane_message_payload,
    _normalize_optional_text,
    _resolve_current_lane_row,
    _resolve_task_ref,
    _row_to_dict,
    _workspace_root,
)
from agent_handoff_mcp.shared_schema import _get_db_connection
from agent_handoff_mcp.shared_write_context import WriteActor, _resolve_write_actor


def _get_lane_row(conn: sqlite3.Connection, task_ref: str, lane_id: str) -> sqlite3.Row | None:
    result: sqlite3.Row | None = conn.execute(
        "SELECT * FROM worktree_lanes WHERE task_ref = ? AND lane_id = ?",
        (task_ref, lane_id),
    ).fetchone()
    return result


def upsert_worktree_lane(
    lane_id: str,
    worktree_path: str,
    branch: str,
    title: str | None = None,
    objective: str | None = None,
    owner_agent: str | None = None,
    model: str | None = None,
    backend: str | None = None,
    reasoning_effort: str | None = None,
    status: str = "planned",
    notes: str | None = None,
    task_ref: str | None = None,
) -> str:
    valid_statuses = LANE_STATUSES
    normalized_lane_id = _normalize_optional_text(lane_id)
    normalized_path = _normalize_optional_text(worktree_path)
    normalized_branch = _normalize_optional_text(branch)
    if normalized_lane_id is None:
        return _json_response({"ok": False, "error": "lane_id is required."})
    if normalized_path is None:
        return _json_response({"ok": False, "error": "worktree_path is required."})
    if normalized_branch is None:
        return _json_response({"ok": False, "error": "branch is required."})
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        conn.execute(
            """
            INSERT INTO worktree_lanes (
                task_ref, lane_id, title, objective, worktree_path, branch,
                owner_agent, model, backend, reasoning_effort, status, notes,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(task_ref, lane_id) DO UPDATE SET
                title = excluded.title,
                objective = excluded.objective,
                worktree_path = excluded.worktree_path,
                branch = excluded.branch,
                owner_agent = excluded.owner_agent,
                model = COALESCE(excluded.model, worktree_lanes.model),
                backend = COALESCE(excluded.backend, worktree_lanes.backend),
                reasoning_effort = COALESCE(excluded.reasoning_effort, worktree_lanes.reasoning_effort),
                status = excluded.status,
                notes = excluded.notes,
                updated_at = datetime('now')
            """,
            (
                resolved_task_ref,
                normalized_lane_id,
                title,
                objective,
                normalized_path,
                normalized_branch,
                owner_agent,
                model,
                backend,
                reasoning_effort,
                status,
                notes,
            ),
        )
        row = _get_lane_row(conn, resolved_task_ref, normalized_lane_id)
        _write_current_task_md_for_task(conn, resolved_task_ref)
        return _json_response({"ok": True, "lane": _row_to_dict(row)})


def close_worktree_lane(
    lane_id: str,
    status: str = "closed",
    notes: str | None = None,
    task_ref: str | None = None,
) -> str:
    """Transition a worktree lane to closed or merged status in the handoff database."""
    valid_close_statuses = CLOSEABLE_LANE_STATUSES
    normalized_lane_id = _normalize_optional_text(lane_id)
    if normalized_lane_id is None:
        return _json_response({"ok": False, "error": "lane_id is required."})
    if status not in valid_close_statuses:
        return _json_response(
            {"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_close_statuses))}"}
        )
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        existing = _get_lane_row(conn, resolved_task_ref, normalized_lane_id)
        if existing is None:
            return _json_response(
                {"ok": False, "error": f"Lane '{normalized_lane_id}' not found for task '{resolved_task_ref}'."}
            )
        conn.execute(
            """
            UPDATE worktree_lanes
            SET status = ?,
                notes = COALESCE(?, notes),
                updated_at = datetime('now')
            WHERE task_ref = ? AND lane_id = ?
            """,
            (status, notes, resolved_task_ref, normalized_lane_id),
        )
        row = _get_lane_row(conn, resolved_task_ref, normalized_lane_id)
        _write_current_task_md_for_task(conn, resolved_task_ref)
        return _json_response({"ok": True, "lane": _row_to_dict(row)})


def list_worktree_lanes(task_ref: str | None = None, status: str = "all", limit: int = 100, offset: int = 0) -> str:
    limit = max(1, limit)
    offset = max(0, offset)
    valid_statuses = {"all", *LANE_STATUSES}
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        if status != "all":
            where_sql += " AND status = ?"
            params.append(status)
        total = int(
            conn.execute(f"SELECT COUNT(*) AS count FROM worktree_lanes WHERE {where_sql}", tuple(params)).fetchone()[
                "count"
            ]
        )
        rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM worktree_lanes WHERE {where_sql} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        ]
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "status": status,
                "total_matching": total,
                "returned": len(rows),
                "has_more": offset + len(rows) < total,
                "lanes": rows,
            }
        )


def record_turn_metric(
    session: str,
    phase: str,
    backend: str,
    cycle: int | None = None,
    lane_id: str | None = None,
    model: str | None = None,
    thread_id: str | None = None,
    turn_id: str | None = None,
    token_usage: TokenUsage | None = None,
    prompt_metrics: PromptMetrics | None = None,
    attribution: dict[str, Any] | None = None,
    section_sizes: dict[str, Any] | None = None,
    raw_usage: dict[str, Any] | None = None,
    actor: WriteActor | None = None,
    task_ref: str | None = None,
) -> str:
    if _normalize_optional_text(session) is None:
        return _json_response({"ok": False, "error": "session is required."})
    normalized_phase = _normalize_optional_text(phase)
    if normalized_phase is None:
        return _json_response({"ok": False, "error": "phase is required."})
    normalized_backend = _normalize_optional_text(backend)
    if normalized_backend is None:
        return _json_response({"ok": False, "error": "backend is required."})
    resolved_usage_source = token_usage.usage_source if token_usage else None
    resolved_prompt_token_source = prompt_metrics.prompt_token_source if prompt_metrics else None
    valid_sources = {"observed", "tokenizer_estimate", "char_estimate"}
    if resolved_usage_source is not None and resolved_usage_source not in valid_sources:
        return _json_response({"ok": False, "error": "Invalid usage_source."})
    if resolved_prompt_token_source is not None and resolved_prompt_token_source not in valid_sources:
        return _json_response({"ok": False, "error": "Invalid prompt_token_source."})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        ctx = _resolve_write_actor(conn, actor)
        resolved_lane_id = _normalize_optional_text(lane_id) or ctx.lane_id
        cur = conn.execute(
            """
            INSERT INTO turn_metrics (
                task_ref, lane_id, session, cycle, phase, backend, model, thread_id, turn_id,
                input_tokens, output_tokens, cached_input_tokens, reasoning_output_tokens,
                total_tokens, usage_source, model_context_window, prompt_tokens, prompt_chars,
                prompt_token_source, utilization_ratio, domain_signal_ratio, pressure_level,
                attribution_json, section_sizes_json, raw_usage_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                resolved_task_ref,
                resolved_lane_id,
                session,
                cycle,
                normalized_phase,
                normalized_backend,
                _normalize_optional_text(model),
                _normalize_optional_text(thread_id),
                _normalize_optional_text(turn_id),
                token_usage.input_tokens if token_usage else None,
                token_usage.output_tokens if token_usage else None,
                token_usage.cached_input_tokens if token_usage else None,
                token_usage.reasoning_output_tokens if token_usage else None,
                token_usage.total_tokens if token_usage else None,
                resolved_usage_source,
                prompt_metrics.model_context_window if prompt_metrics else None,
                prompt_metrics.prompt_tokens if prompt_metrics else None,
                prompt_metrics.prompt_chars if prompt_metrics else None,
                resolved_prompt_token_source,
                prompt_metrics.utilization_ratio if prompt_metrics else None,
                prompt_metrics.domain_signal_ratio if prompt_metrics else None,
                _normalize_optional_text(prompt_metrics.pressure_level if prompt_metrics else None),
                json.dumps(attribution or {}, sort_keys=True),
                json.dumps(section_sizes or {}, sort_keys=True),
                json.dumps(raw_usage, sort_keys=True) if raw_usage is not None else None,
            ),
        )
        row = conn.execute("SELECT * FROM turn_metrics WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "turn_metric": _decode_turn_metric_row_dict(_row_to_dict(row) or {}),
            }
        )


def list_turn_metrics(
    task_ref: str | None = None,
    lane_id: str | None = None,
    backend: str | None = None,
    model: str | None = None,
    phase: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    limit = max(1, limit)
    offset = max(0, offset)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        for field_name, value in (
            ("lane_id", _normalize_optional_text(lane_id)),
            ("backend", _normalize_optional_text(backend)),
            ("model", _normalize_optional_text(model)),
            ("phase", _normalize_optional_text(phase)),
        ):
            if value is None:
                continue
            where_sql += f" AND {field_name} = ?"
            params.append(value)
        total, rows = _paginated_query(
            conn,
            "turn_metrics",
            where_sql,
            tuple(params),
            limit,
            offset,
            "created_at DESC, id DESC",
            _decode_turn_metric_row_dict,
        )
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "lane_id": _normalize_optional_text(lane_id),
                "backend": _normalize_optional_text(backend),
                "model": _normalize_optional_text(model),
                "phase": _normalize_optional_text(phase),
                "total_matching": total,
                "returned": len(rows),
                "has_more": offset + len(rows) < total,
                "turn_metrics": rows,
            }
        )


def get_turn_metrics_summary(
    task_ref: str | None = None,
    lane_id: str | None = None,
) -> str:
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        normalized_lane_id = _normalize_optional_text(lane_id)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        if normalized_lane_id is not None:
            where_sql += " AND lane_id = ?"
            params.append(normalized_lane_id)

        rows = conn.execute(
            f"""
            SELECT usage_source, prompt_token_source, pressure_level, backend, model, lane_id,
                   total_tokens, prompt_tokens, input_tokens
            FROM turn_metrics
            WHERE {where_sql}
            """,
            tuple(params),
        ).fetchall()
        total_turns = len(rows)
        usage_counts = {"observed": 0, "tokenizer_estimate": 0, "char_estimate": 0}
        prompt_counts = {"observed": 0, "tokenizer_estimate": 0, "char_estimate": 0}
        pressure_counts: dict[str, int] = {}
        tokens_by_lane: dict[str, int] = {}
        tokens_by_backend_model: dict[str, int] = {}
        prompt_tokens_total = 0
        total_tokens_total = 0
        comparable_turns = 0
        exact_preflight_turns = 0
        estimated_preflight_turns = 0
        drift_sum = 0
        abs_drift_sum = 0
        max_abs_drift = 0

        for row in rows:
            usage = row["usage_source"]
            prompt_source = row["prompt_token_source"]
            pressure_level = row["pressure_level"] or "unknown"
            lane_key = str(row["lane_id"] or "unscoped")
            backend_model_key = f"{row['backend']}::{row['model'] or 'default'}"
            if isinstance(usage, str) and usage in usage_counts:
                usage_counts[usage] += 1
            if isinstance(prompt_source, str) and prompt_source in prompt_counts:
                prompt_counts[prompt_source] += 1
            pressure_counts[str(pressure_level)] = pressure_counts.get(str(pressure_level), 0) + 1
            total_tokens_value = int(row["total_tokens"] or 0)
            prompt_tokens_value = int(row["prompt_tokens"] or 0)
            input_tokens_value = row["input_tokens"]
            total_tokens_total += total_tokens_value
            prompt_tokens_total += prompt_tokens_value
            tokens_by_lane[lane_key] = tokens_by_lane.get(lane_key, 0) + total_tokens_value
            tokens_by_backend_model[backend_model_key] = (
                tokens_by_backend_model.get(backend_model_key, 0) + total_tokens_value
            )
            if prompt_tokens_value > 0 and input_tokens_value is not None:
                comparable_turns += 1
                drift = int(input_tokens_value) - prompt_tokens_value
                drift_sum += drift
                abs_drift = abs(drift)
                abs_drift_sum += abs_drift
                if abs_drift > max_abs_drift:
                    max_abs_drift = abs_drift
                if prompt_source == "observed":
                    exact_preflight_turns += 1
                elif isinstance(prompt_source, str):
                    estimated_preflight_turns += 1

        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "lane_id": normalized_lane_id,
                "summary": {
                    "total_turns": total_turns,
                    "usage_source_counts": usage_counts,
                    "prompt_token_source_counts": prompt_counts,
                    "pressure_level_counts": pressure_counts,
                    "total_tokens": total_tokens_total,
                    "prompt_tokens": prompt_tokens_total,
                    "by_lane_total_tokens": tokens_by_lane,
                    "by_backend_model_total_tokens": tokens_by_backend_model,
                    "preflight_observed_drift": {
                        "comparable_turns": comparable_turns,
                        "exact_preflight_turns": exact_preflight_turns,
                        "estimated_preflight_turns": estimated_preflight_turns,
                        "net_token_drift": drift_sum,
                        "mean_signed_token_drift": (
                            round(drift_sum / comparable_turns, 3) if comparable_turns else None
                        ),
                        "mean_absolute_token_drift": (
                            round(abs_drift_sum / comparable_turns, 3) if comparable_turns else None
                        ),
                        "max_absolute_token_drift": max_abs_drift if comparable_turns else None,
                    },
                },
            }
        )


def get_lane_activity(
    lane_id: str,
    task_ref: str | None = None,
    limit_decisions: int = 20,
    limit_tests: int = 20,
    limit_blockers: int = 20,
    limit_actions: int = 20,
    limit_findings: int = 20,
    format: str = "full",
) -> str:
    normalized_lane_id = _normalize_optional_text(lane_id)
    if normalized_lane_id is None:
        return _json_response({"ok": False, "error": "lane_id is required."})
    if format not in {"full", "archival"}:
        return _json_response({"ok": False, "error": "Invalid format. Valid: archival, full."})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        lane = _get_lane_row(conn, resolved_task_ref, normalized_lane_id)
        if lane is None:
            return _json_response({"ok": False, "error": "Lane not found for task_ref."})
        if format == "archival":
            return _json_response(
                {
                    "ok": True,
                    "task_ref": resolved_task_ref,
                    "format": format,
                    "lane": dict(lane),
                    "summary": _build_archival_lane_activity_summary(
                        conn,
                        task_ref=resolved_task_ref,
                        lane_id=normalized_lane_id,
                    ),
                }
            )
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "format": format,
                "lane": dict(lane),
                "decisions": _fetch_handoff_rows(
                    conn,
                    table="decisions",
                    where_sql="task_ref = ? AND lane_id = ?",
                    order_sql="created_at DESC, id DESC",
                    limit=max(1, limit_decisions),
                    params=(resolved_task_ref, normalized_lane_id),
                ),
                "tests": _fetch_handoff_rows(
                    conn,
                    table="verified_tests",
                    where_sql="task_ref = ? AND lane_id = ?",
                    order_sql="verified_at DESC, id DESC",
                    limit=max(1, limit_tests),
                    params=(resolved_task_ref, normalized_lane_id),
                ),
                "blockers": _fetch_handoff_rows(
                    conn,
                    table="blockers",
                    where_sql="task_ref = ? AND lane_id = ?",
                    order_sql="created_at DESC, id DESC",
                    limit=max(1, limit_blockers),
                    params=(resolved_task_ref, normalized_lane_id),
                ),
                "actions": _fetch_handoff_rows(
                    conn,
                    table="next_actions",
                    where_sql="task_ref = ? AND lane_id = ?",
                    order_sql="updated_at DESC, id DESC",
                    limit=max(1, limit_actions),
                    params=(resolved_task_ref, normalized_lane_id),
                ),
                "findings": _fetch_handoff_rows(
                    conn,
                    table="review_findings",
                    where_sql="task_ref = ? AND lane_id = ?",
                    order_sql="COALESCE(updated_at, created_at) DESC, id DESC",
                    limit=max(1, limit_findings),
                    params=(resolved_task_ref, normalized_lane_id),
                ),
                "reports": _fetch_handoff_rows(
                    conn,
                    table="worker_reports",
                    where_sql="task_ref = ? AND lane_id = ?",
                    order_sql="created_at DESC, id DESC",
                    limit=20,
                    params=(resolved_task_ref, normalized_lane_id),
                ),
                "messages": _fetch_handoff_rows(
                    conn,
                    table="lane_messages",
                    where_sql="task_ref = ? AND lane_id = ?",
                    order_sql="updated_at DESC, id DESC",
                    limit=20,
                    params=(resolved_task_ref, normalized_lane_id),
                ),
            }
        )


def get_latest_slice_review_packet(
    task_ref: str | None = None,
    lane_id: str | None = None,
    review_kind: str | None = None,
) -> str:
    normalized_lane_id = _normalize_optional_text(lane_id)
    normalized_review_kind = _normalize_optional_text(review_kind)
    if normalized_review_kind is not None and normalized_review_kind not in REVIEW_KINDS:
        valid_review_kinds = ", ".join(sorted(REVIEW_KINDS))
        return _json_response({"ok": False, "error": f"Invalid review_kind. Valid: {valid_review_kinds}."})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        from .orchestration.slice_review_packet import get_latest_slice_review_packet_data  # noqa: PLC0415

        packet = get_latest_slice_review_packet_data(
            conn,
            workspace_root=_workspace_root(),
            task_ref=resolved_task_ref,
            lane_id=normalized_lane_id,
            review_kind=normalized_review_kind,
        )
        if packet is None:
            return _json_response(
                {
                    "ok": False,
                    "error": "No matching slice review packet found.",
                    "task_ref": resolved_task_ref,
                    "lane_id": normalized_lane_id,
                    "review_kind": normalized_review_kind,
                }
            )
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "lane_id": normalized_lane_id,
                "review_kind": normalized_review_kind or packet["review_kind"],
                "packet": packet,
            }
        )


def record_worker_report(
    lane_id: str,
    session: str,
    summary: str,
    changed_files: list[str] | None = None,
    test_commands: list[str] | None = None,
    blockers: list[str] | None = None,
    merge_ready: bool = False,
    status: str = "submitted",
    task_ref: str | None = None,
    actor: WriteActor | None = None,
) -> str:
    valid_statuses = REPORT_STATUSES
    normalized_lane_id = _normalize_optional_text(lane_id)
    if normalized_lane_id is None:
        return _json_response({"ok": False, "error": "lane_id is required."})
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        if _get_lane_row(conn, resolved_task_ref, normalized_lane_id) is None:
            return _json_response({"ok": False, "error": "Lane not found for task_ref."})
        ctx = _resolve_write_actor(conn, actor)
        cur = conn.execute(
            """
            INSERT INTO worker_reports (
                task_ref, lane_id, session, summary, changed_files_json, test_commands_json, blockers_json,
                merge_ready, status, agent, branch, commit_sha, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                resolved_task_ref,
                normalized_lane_id,
                session,
                summary,
                json.dumps(changed_files or []),
                json.dumps(test_commands or []),
                json.dumps(blockers or []),
                1 if merge_ready else 0,
                status,
                ctx.agent,
                ctx.branch,
                ctx.commit_sha,
            ),
        )
        row = _row_to_dict(conn.execute("SELECT * FROM worker_reports WHERE id = ?", (cur.lastrowid,)).fetchone())
        _write_current_task_md_for_task(conn, resolved_task_ref)
        return _json_response({"ok": True, "report": row})


def list_worker_reports(
    task_ref: str | None = None, lane_id: str | None = None, limit: int = 20, offset: int = 0
) -> str:
    limit = max(1, limit)
    offset = max(0, offset)
    normalized_lane_id = _normalize_optional_text(lane_id)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        if normalized_lane_id is not None:
            where_sql += " AND lane_id = ?"
            params.append(normalized_lane_id)
        total, rows = _paginated_query(
            conn, "worker_reports", where_sql, tuple(params), limit, offset, "created_at DESC, id DESC"
        )
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "lane_id": normalized_lane_id,
                "total_matching": total,
                "returned": len(rows),
                "has_more": offset + len(rows) < total,
                "reports": rows,
            }
        )


def record_lane_message(
    lane_id: str,
    session: str,
    direction: str,
    message: str,
    subject: str | None = None,
    status: str = "open",
    payload: dict[str, object] | None = None,
    task_ref: str | None = None,
    actor: WriteActor | None = None,
) -> str:
    valid_directions = LANE_MESSAGE_DIRECTIONS
    valid_statuses = MESSAGE_STATUSES
    normalized_lane_id = _normalize_optional_text(lane_id)
    if normalized_lane_id is None:
        return _json_response({"ok": False, "error": "lane_id is required."})
    if direction not in valid_directions:
        return _json_response(
            {"ok": False, "error": f"Invalid direction. Valid: {', '.join(sorted(valid_directions))}"}
        )
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    normalized_payload, payload_error = _normalize_lane_message_payload(payload)
    if payload_error is not None:
        return _json_response({"ok": False, "error": payload_error})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        if _get_lane_row(conn, resolved_task_ref, normalized_lane_id) is None:
            return _json_response({"ok": False, "error": "Lane not found for task_ref."})
        ctx = _resolve_write_actor(conn, actor)
        cur = conn.execute(
            """
            INSERT INTO lane_messages (task_ref, lane_id, session, direction, subject, message, status, payload_json, agent, branch, commit_sha, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                resolved_task_ref,
                normalized_lane_id,
                session,
                direction,
                subject,
                message,
                status,
                json.dumps(normalized_payload, sort_keys=True) if normalized_payload is not None else None,
                ctx.agent,
                ctx.branch,
                ctx.commit_sha,
            ),
        )
        row = _row_to_dict(conn.execute("SELECT * FROM lane_messages WHERE id = ?", (cur.lastrowid,)).fetchone())
        if row is not None:
            row = _decode_lane_message_row_dict(row)
        _write_current_task_md_for_task(conn, resolved_task_ref)
        return _json_response({"ok": True, "message": row})


def record_lane_brief(
    lane_id: str,
    session: str,
    source_lane: str,
    reason: str,
    summary: str,
    message: str | None = None,
    required_actions: list[str] | None = None,
    artifacts: list[str] | None = None,
    status: str = "open",
    task_ref: str | None = None,
    actor: WriteActor | None = None,
) -> str:
    normalized_reason = _normalize_optional_text(reason)
    normalized_summary = _normalize_optional_text(summary)
    normalized_source_lane = _normalize_optional_text(source_lane)
    if normalized_reason is None:
        return _json_response({"ok": False, "error": "reason is required."})
    if normalized_summary is None:
        return _json_response({"ok": False, "error": "summary is required."})
    if normalized_source_lane is None:
        return _json_response({"ok": False, "error": "source_lane is required."})
    brief_payload: dict[str, object] = {
        "source_lane": normalized_source_lane,
        "reason": normalized_reason,
        "summary": normalized_summary,
    }
    if required_actions:
        brief_payload["required_actions"] = [
            item for item in required_actions if isinstance(item, str) and item.strip()
        ]
    if artifacts:
        brief_payload["artifacts"] = [item for item in artifacts if isinstance(item, str) and item.strip()]
    return record_lane_message(
        lane_id=lane_id,
        session=session,
        direction="orchestrator_to_worker",
        subject=f"brief:{normalized_reason}",
        message=(message or normalized_summary),
        status=status,
        payload=brief_payload,
        task_ref=task_ref,
        actor=actor,
    )


def update_lane_message(
    message_id: int,
    status: str,
    task_ref: str | None = None,
    actor: WriteActor | None = None,
) -> str:
    valid_statuses = MESSAGE_STATUSES
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        row = conn.execute(
            "SELECT * FROM lane_messages WHERE id = ? AND task_ref = ?", (message_id, resolved_task_ref)
        ).fetchone()
        if row is None:
            return _json_response({"ok": False, "error": "Message not found for task_ref."})
        ctx = _resolve_write_actor(conn, actor)
        conn.execute(
            "UPDATE lane_messages SET status = ?, agent = COALESCE(agent, ?), branch = COALESCE(branch, ?), commit_sha = COALESCE(commit_sha, ?), updated_at = datetime('now') WHERE id = ? AND task_ref = ?",
            (status, ctx.agent, ctx.branch, ctx.commit_sha, message_id, resolved_task_ref),
        )
        updated = _row_to_dict(conn.execute("SELECT * FROM lane_messages WHERE id = ?", (message_id,)).fetchone())
        _write_current_task_md_for_task(conn, resolved_task_ref)
        return _json_response({"ok": True, "message": updated})


def list_lane_messages(
    task_ref: str | None = None,
    lane_id: str | None = None,
    status: str = "all",
    limit: int = 20,
    offset: int = 0,
    direction: str | None = None,
    subject_prefix: str | None = None,
) -> str:
    """List lane messages with optional scope and content filters.

    ``direction`` restricts to a specific message direction (e.g. ``"orchestrator_to_worker"``).
    ``subject_prefix`` restricts to messages whose subject starts with the given prefix
    (e.g. ``"brief:"``), making this function capable of subsuming ``list_lane_briefs``.
    """
    valid_statuses = {"all", *MESSAGE_STATUSES}
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    limit = max(1, limit)
    offset = max(0, offset)
    normalized_lane_id = _normalize_optional_text(lane_id)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        inferred_lane = None
        if normalized_lane_id is None:
            inferred_lane_row = _resolve_current_lane_row(conn, resolved_task_ref)
            if inferred_lane_row is not None:
                normalized_lane_id = str(inferred_lane_row["lane_id"])
                inferred_lane = _row_to_dict(inferred_lane_row)
        params: list[object] = [resolved_task_ref]
        where_sql = "task_ref = ?"
        if normalized_lane_id is not None:
            where_sql += " AND lane_id = ?"
            params.append(normalized_lane_id)
        if direction is not None:
            where_sql += " AND direction = ?"
            params.append(direction)
        if subject_prefix is not None:
            where_sql += " AND subject LIKE ?"
            params.append(f"{subject_prefix}%")
        if status != "all":
            where_sql += " AND status = ?"
            params.append(status)
        total, rows = _paginated_query(
            conn,
            "lane_messages",
            where_sql,
            tuple(params),
            limit,
            offset,
            "updated_at DESC, id DESC",
            _decode_lane_message_row_dict,
        )
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "lane_id": normalized_lane_id,
                "current_lane": inferred_lane,
                "status": status,
                "total_matching": total,
                "returned": len(rows),
                "has_more": offset + len(rows) < total,
                "messages": rows,
            }
        )


def list_lane_briefs(
    task_ref: str | None = None, lane_id: str | None = None, status: str = "open", limit: int = 20, offset: int = 0
) -> str:
    valid_statuses = {"all", *MESSAGE_STATUSES}
    if status not in valid_statuses:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"})
    limit = max(1, limit)
    offset = max(0, offset)
    normalized_lane_id = _normalize_optional_text(lane_id)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        params: list[object] = [resolved_task_ref, "orchestrator_to_worker", "brief:%"]
        where_sql = "task_ref = ? AND direction = ? AND subject LIKE ?"
        if normalized_lane_id is not None:
            where_sql += " AND lane_id = ?"
            params.append(normalized_lane_id)
        if status != "all":
            where_sql += " AND status = ?"
            params.append(status)
        total, rows = _paginated_query(
            conn,
            "lane_messages",
            where_sql,
            tuple(params),
            limit,
            offset,
            "updated_at DESC, id DESC",
            _decode_lane_message_row_dict,
        )
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "lane_id": normalized_lane_id,
                "status": status,
                "total_matching": total,
                "returned": len(rows),
                "has_more": offset + len(rows) < total,
                "briefs": rows,
            }
        )


# ---------------------------------------------------------------------------
# Plan cursor CRUD (moved from agent-handoff-mcp/core.py in E12-9 Slice 1)
# ---------------------------------------------------------------------------


def _evaluate_clean_slice_gate(
    conn: "sqlite3.Connection",
    task_ref: str,
    lane_id: str | None,
    since: str | None,
) -> dict | None:
    """Check clean-slice preconditions. Returns error payload dict or None if clean."""
    open_high_query = [
        "SELECT COUNT(*) AS count FROM review_findings WHERE task_ref = ? AND status = 'open' AND severity = 'high'"
    ]
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
            (normalized_lane_id or _normalize_optional_text(existing["lane_id"]))
            if existing is not None
            else normalized_lane_id
        )
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
                (
                    resolved_task_ref,
                    normalized_plan_item_id,
                    state,
                    normalized_lane_id,
                    mcp_action_id,
                    worker_message_id,
                    normalized_heading,
                    normalized_summary,
                    state,
                    state,
                    state,
                ),
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
            (
                state,
                next_lane_id,
                next_action_id,
                next_worker_message_id,
                next_heading,
                next_summary,
                dispatch_count,
                state,
                state,
                resolved_task_ref,
                normalized_plan_item_id,
            ),
        )
        row = _row_to_dict(
            conn.execute(
                "SELECT * FROM plan_cursors WHERE task_ref = ? AND plan_item_id = ?",
                (resolved_task_ref, normalized_plan_item_id),
            ).fetchone()
        )
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
        total, rows = _paginated_query(
            conn, "plan_cursors", where_sql, tuple(params), limit, offset, "updated_at DESC, id DESC"
        )
        return _json_response(
            {
                "ok": True,
                "task_ref": resolved_task_ref,
                "lane_id": normalized_lane_id,
                "state": state,
                "total_matching": total,
                "returned": len(rows),
                "has_more": offset + len(rows) < total,
                "cursors": rows,
            }
        )
