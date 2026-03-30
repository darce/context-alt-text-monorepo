"""Handoff state domain module.

Contains set_handoff_state, get_handoff_state, and dashboard view.
"""
from __future__ import annotations

from ._shared import (
    DEFAULT_HANDOFF_LIMITS,
    HANDOFF_ACTIVE_STATUSES,
    _fetch_handoff_rows,
    _get_db_connection,
    _json_response,
    _normalize_optional_text,
    _resolve_current_lane_row,
    _resolve_task_ref,
    _resolve_write_actor,
    _row_to_dict,
    _write_current_task_md_for_task,
    WriteActor,
)


def set_handoff_state(
    task_ref: str,
    objective: str | None = None,
    focus: str | None = None,
    status: str = "in_progress",
    expected_revision: int | None = None,
    actor: WriteActor | None = None,
) -> str:
    if status not in HANDOFF_ACTIVE_STATUSES:
        return _json_response({"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(HANDOFF_ACTIVE_STATUSES))}"})
    with _get_db_connection() as conn:
        ctx = _resolve_write_actor(conn, actor)
        current = conn.execute("SELECT revision, objective, focus FROM handoff_state WHERE id = 1").fetchone()
        if current is None:
            if objective is None:
                return _json_response({"ok": False, "error": "objective is required when creating a new handoff state."})
            conn.execute(
                """
                INSERT INTO handoff_state (
                    id, task_ref, objective, focus, status, revision, updated_at, updated_by, updated_branch, updated_commit_sha
                ) VALUES (1, ?, ?, ?, ?, 0, datetime('now'), ?, ?, ?)
                """,
                (task_ref, objective, focus, status, ctx.agent, ctx.branch, ctx.commit_sha),
            )
            return _json_response({"ok": True, "inserted": True, "active": _row_to_dict(conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone())})
        if expected_revision is None:
            return _json_response({"ok": False, "error": "expected_revision is required for updates.", "current_revision": int(current["revision"])})
        resolved_objective = objective if objective is not None else str(current["objective"])
        resolved_focus = focus if focus is not None else (_normalize_optional_text(current["focus"]) if current["focus"] else None)
        updated = conn.execute(
            """
            UPDATE handoff_state
            SET task_ref = ?, objective = ?, focus = ?, status = ?, revision = revision + 1, updated_at = datetime('now'),
                updated_by = ?, updated_branch = ?, updated_commit_sha = ?
            WHERE id = 1 AND revision = ?
            """,
            (task_ref, resolved_objective, resolved_focus, status, ctx.agent, ctx.branch, ctx.commit_sha, expected_revision),
        )
        if updated.rowcount == 0:
            latest = conn.execute("SELECT revision FROM handoff_state WHERE id = 1").fetchone()
            return _json_response({"ok": False, "error": "Revision conflict.", "expected_revision": expected_revision, "current_revision": int(latest["revision"]) if latest else None})
        return _json_response({"ok": True, "updated": True, "active": _row_to_dict(conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone())})


def get_handoff_state(
    task_ref: str | None = None,
    top_n_blockers: int = DEFAULT_HANDOFF_LIMITS["blockers"],
    top_n_actions: int = DEFAULT_HANDOFF_LIMITS["actions"],
    top_n_decisions: int = DEFAULT_HANDOFF_LIMITS["decisions"],
    top_n_tests: int = DEFAULT_HANDOFF_LIMITS["tests"],
    top_n_findings: int = DEFAULT_HANDOFF_LIMITS["findings"],
    verbose: bool = False,
    view: str = "task",
    include_archived: bool = True,
) -> str:
    if view == "dashboard":
        return _get_handoff_dashboard_view(limit=top_n_findings if top_n_findings != DEFAULT_HANDOFF_LIMITS["findings"] else 20, include_archived=include_archived)
    top_n_blockers = max(1, top_n_blockers)
    top_n_actions = max(1, top_n_actions)
    top_n_decisions = max(1, top_n_decisions)
    top_n_tests = max(1, top_n_tests)
    top_n_findings = max(1, top_n_findings)
    with _get_db_connection() as conn:
        active_row = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
        if active_row is None and task_ref is None:
            return _json_response({"ok": True, "active": None, "message": "No active handoff state."})
        resolved_task_ref = task_ref or str(active_row["task_ref"])
        active = _row_to_dict(active_row) if active_row is not None else None
        if active is not None and resolved_task_ref != active["task_ref"]:
            active = None
        current_lane_row = _resolve_current_lane_row(conn, resolved_task_ref)
        current_lane = _row_to_dict(current_lane_row)
        query_limit = (lambda size: size if not verbose else 10000)
        lane_messages_where_sql = "task_ref = ? AND status = 'open'"
        lane_messages_params: tuple[object, ...] = (resolved_task_ref,)
        if current_lane_row is not None:
            lane_messages_where_sql += " AND lane_id = ?"
            lane_messages_params = (resolved_task_ref, str(current_lane_row["lane_id"]))
        return _json_response(
            {
                "ok": True,
                "limits": {"blockers": top_n_blockers, "actions": top_n_actions, "decisions": top_n_decisions, "tests": top_n_tests, "findings": top_n_findings},
                "task_ref": resolved_task_ref,
                "active": active,
                "current_lane": current_lane,
                "blockers_open": _fetch_handoff_rows(conn, table="blockers", where_sql="task_ref = ? AND status = 'open'", order_sql="created_at DESC", limit=query_limit(top_n_blockers), params=(resolved_task_ref,)),
                "actions_pending": _fetch_handoff_rows(conn, table="next_actions", where_sql="task_ref = ? AND status = 'pending'", order_sql="priority ASC, created_at ASC", limit=query_limit(top_n_actions), params=(resolved_task_ref,)),
                "decisions_recent": _fetch_handoff_rows(conn, table="decisions", where_sql="task_ref = ?", order_sql="created_at DESC", limit=query_limit(top_n_decisions), params=(resolved_task_ref,)),
                "tests_recent": _fetch_handoff_rows(conn, table="verified_tests", where_sql="task_ref = ?", order_sql="verified_at DESC", limit=query_limit(top_n_tests), params=(resolved_task_ref,)),
                "findings_open": _fetch_handoff_rows(conn, table="review_findings", where_sql="task_ref = ? AND status = 'open'", order_sql="CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, created_at DESC", limit=query_limit(top_n_findings), params=(resolved_task_ref,)),
                "worktree_lanes": _fetch_handoff_rows(conn, table="worktree_lanes", where_sql="task_ref = ?", order_sql="updated_at DESC, id DESC", limit=50, params=(resolved_task_ref,)),
                "worker_reports_recent": _fetch_handoff_rows(conn, table="worker_reports", where_sql="task_ref = ?", order_sql="created_at DESC, id DESC", limit=query_limit(top_n_tests), params=(resolved_task_ref,)),
                "lane_messages_open": _fetch_handoff_rows(conn, table="lane_messages", where_sql=lane_messages_where_sql, order_sql="updated_at DESC, id DESC", limit=50, params=lane_messages_params),
            }
        )


def _get_handoff_dashboard_view(limit: int = 20, include_archived: bool = True) -> str:
    limit = max(1, limit)
    archive_union = "UNION ALL SELECT task_ref, archived_at AS updated_at FROM task_archives" if include_archived else ""
    archived_filter = "" if include_archived else "WHERE archived.archived_at IS NULL"
    with _get_db_connection() as conn:
        rows = conn.execute(
            """
            WITH activity AS (
                SELECT task_ref, created_at AS updated_at FROM decisions
                UNION ALL
                SELECT task_ref, created_at AS updated_at FROM blockers
                UNION ALL
                SELECT task_ref, updated_at FROM next_actions
                UNION ALL
                SELECT task_ref, verified_at AS updated_at FROM verified_tests
                UNION ALL
                SELECT task_ref, COALESCE(updated_at, resolved_at, created_at) AS updated_at FROM review_findings
                UNION ALL
                SELECT task_ref, updated_at FROM worktree_lanes
                UNION ALL
                SELECT task_ref, created_at AS updated_at FROM worker_reports
                UNION ALL
                SELECT task_ref, updated_at FROM lane_messages
                """ + archive_union + """
            ),
            candidates AS (
                SELECT task_ref, MAX(updated_at) AS last_activity
                FROM activity
                GROUP BY task_ref
                ORDER BY MAX(updated_at) DESC
                LIMIT ?
            ),
            blocker_counts AS (
                SELECT task_ref, COUNT(*) AS open_blockers
                FROM blockers
                WHERE status = 'open'
                GROUP BY task_ref
            ),
            action_counts AS (
                SELECT task_ref, COUNT(*) AS pending_actions
                FROM next_actions
                WHERE status = 'pending'
                GROUP BY task_ref
            ),
            finding_counts AS (
                SELECT task_ref, COUNT(*) AS open_findings
                FROM review_findings
                WHERE status = 'open'
                GROUP BY task_ref
            ),
            archived AS (
                SELECT task_ref, archived_at
                FROM task_archives
            )
            SELECT
                candidates.task_ref,
                candidates.last_activity,
                COALESCE(blocker_counts.open_blockers, 0) AS open_blockers,
                COALESCE(action_counts.pending_actions, 0) AS pending_actions,
                COALESCE(finding_counts.open_findings, 0) AS open_findings,
                archived.archived_at
            FROM candidates
            LEFT JOIN blocker_counts ON blocker_counts.task_ref = candidates.task_ref
            LEFT JOIN action_counts ON action_counts.task_ref = candidates.task_ref
            LEFT JOIN finding_counts ON finding_counts.task_ref = candidates.task_ref
            LEFT JOIN archived ON archived.task_ref = candidates.task_ref
            """ + archived_filter + """
            ORDER BY candidates.last_activity DESC
            """,
            (limit,),
        ).fetchall()
        active = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
        return _json_response({"ok": True, "view": "dashboard", "active": _row_to_dict(active), "tasks": [dict(row) for row in rows]})
