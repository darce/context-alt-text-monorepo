"""Handoff state domain module.

Contains set_handoff_state and get_handoff_state.
"""

from __future__ import annotations

from .shared_db_utils import _fetch_handoff_rows
from .shared_primitives import (
    DEFAULT_HANDOFF_LIMITS,
    HANDOFF_ACTIVE_STATUSES,
    RATIONALE_HARD_LIMIT_CHARS,
    RATIONALE_SOFT_LIMIT_CHARS,
    SLICE_COMPLETE_HARD_LIMIT_CHARS,
    SLICE_COMPLETE_REQUIRED_SECTIONS,
    _envelope,
    _get_handoff_row_for_task,
    _normalize_optional_text,
    _resolve_current_lane_row,
    _resolve_workspace_handoff_row,
    _row_to_dict,
    _workspace_root,
)

# Branches treated as the repo-root maintenance target. Maintenance tasks
# (task_ref starting with MAINT-) created on these branches default
# target_worktree_path to the configured workspace root so implicit
# workspace-path resolution can disambiguate the root worktree against
# concurrent feature-branch tasks after the E17-11 resolver hardening.
_MAIN_BRANCH_NAMES = frozenset({"main", "master"})


def _default_maint_target_worktree_path(
    task_ref: str,
    target_branch: str | None,
    target_worktree_path: str | None,
    actor_branch: str | None,
) -> str | None:
    """Return a defaulted target_worktree_path for main-scoped MAINT-* tasks.

    Applies only when: task_ref starts with 'MAINT-', no explicit path was
    passed, and either target_branch or the actor's branch is main/master.
    Explicit caller-supplied paths always win.
    """
    if target_worktree_path is not None:
        return target_worktree_path
    if not task_ref.startswith("MAINT-"):
        return None
    branch_candidates = {b for b in (target_branch, actor_branch) if b}
    if not branch_candidates or not (branch_candidates & _MAIN_BRANCH_NAMES):
        return None
    return str(_workspace_root())
from .shared_schema import _get_db_connection
from .shared_write_context import WriteActor, _resolve_write_actor, collect_target_context_warnings
from .slice_decision import extract_slice_label, is_slice_complete_decision


def set_handoff_state(
    task_ref: str,
    objective: str | None = None,
    focus: str | None = None,
    status: str = "in_progress",
    expected_revision: int | None = None,
    actor: WriteActor | None = None,
    target_branch: str | None = None,
    target_worktree_path: str | None = None,
) -> dict:
    _tool = "set_handoff_state"
    if status not in HANDOFF_ACTIVE_STATUSES:
        return _envelope(
            ok=False,
            tool=_tool,
            task_ref=task_ref,
            data={"error": f"Invalid status. Valid: {', '.join(sorted(HANDOFF_ACTIVE_STATUSES))}"},
        )
    with _get_db_connection() as conn:
        ctx = _resolve_write_actor(conn, actor)
        task_row = _get_handoff_row_for_task(conn, task_ref)
        if task_row is None:
            if objective is None:
                return _envelope(
                    ok=False,
                    tool=_tool,
                    task_ref=task_ref,
                    data={"error": "objective is required when creating a new handoff state."},
                )
            effective_target_worktree_path = _default_maint_target_worktree_path(
                task_ref=task_ref,
                target_branch=target_branch,
                target_worktree_path=target_worktree_path,
                actor_branch=ctx.branch,
            )
            conn.execute(
                """
                INSERT INTO handoff_state (
                    id, task_ref, objective, focus, status, target_branch, target_worktree_path,
                    revision, updated_at, updated_by, updated_branch, updated_commit_sha
                ) VALUES (NULL, ?, ?, ?, ?, ?, ?, 0, datetime('now'), ?, ?, ?)
                """,
                (
                    task_ref,
                    objective,
                    focus,
                    status,
                    target_branch,
                    effective_target_worktree_path,
                    ctx.agent,
                    ctx.branch,
                    ctx.commit_sha,
                ),
            )
            active = _row_to_dict(_get_handoff_row_for_task(conn, task_ref))
            return _envelope(
                ok=True,
                tool=_tool,
                task_ref=task_ref,
                data={"inserted": True, "active": active},
                mutation={"entity": "handoff_state", "operation": "insert", "task_revision": 0},
            )
        if expected_revision is None:
            return _envelope(
                ok=False,
                tool=_tool,
                task_ref=task_ref,
                data={
                    "error": (
                        "expected_revision is required for updates. "
                        "Fetch the active row first via get_handoff_state(sections='identity') "
                        "and pass its revision field as expected_revision."
                    ),
                    "current_revision": int(task_row["revision"]),
                },
            )
        resolved_objective = objective if objective is not None else str(task_row["objective"])
        resolved_focus = (
            focus if focus is not None else (_normalize_optional_text(task_row["focus"]) if task_row["focus"] else None)
        )
        resolved_target_branch = (
            target_branch
            if target_branch is not None
            else (_normalize_optional_text(task_row["target_branch"]) if task_row["target_branch"] else None)
        )
        resolved_target_worktree_path = (
            target_worktree_path
            if target_worktree_path is not None
            else (
                _normalize_optional_text(task_row["target_worktree_path"]) if task_row["target_worktree_path"] else None
            )
        )
        warnings = collect_target_context_warnings(
            conn,
            ctx,
            target_branch=resolved_target_branch,
            target_worktree_path=resolved_target_worktree_path,
            task_ref=task_ref,
        )
        updated = conn.execute(
            """
            UPDATE handoff_state
            SET objective = ?, focus = ?, status = ?,
                target_branch = ?, target_worktree_path = ?,
                revision = revision + 1, updated_at = datetime('now'),
                updated_by = ?, updated_branch = ?, updated_commit_sha = ?
            WHERE task_ref = ? AND revision = ?
            """,
            (
                resolved_objective,
                resolved_focus,
                status,
                resolved_target_branch,
                resolved_target_worktree_path,
                ctx.agent,
                ctx.branch,
                ctx.commit_sha,
                task_ref,
                expected_revision,
            ),
        )
        if updated.rowcount == 0:
            latest = conn.execute("SELECT revision FROM handoff_state WHERE task_ref = ?", (task_ref,)).fetchone()
            return _envelope(
                ok=False,
                tool=_tool,
                task_ref=task_ref,
                data={
                    "error": "Revision conflict.",
                    "expected_revision": expected_revision,
                    "current_revision": int(latest["revision"]) if latest else None,
                },
            )
        active = _row_to_dict(_get_handoff_row_for_task(conn, task_ref))
        if active is None:
            return _envelope(
                ok=False,
                tool=_tool,
                task_ref=task_ref,
                data={"error": "Active handoff state missing after update."},
            )
        return _envelope(
            ok=True,
            tool=_tool,
            task_ref=task_ref,
            data={"updated": True, "active": active},
            mutation={"entity": "handoff_state", "operation": "update", "task_revision": active.get("revision")},
            warnings=warnings or None,
        )


_VALID_SECTIONS = frozenset(
    {
        # 'active' and 'limits' are always included as cheap identity data
        # and are not selectable/excludable via the sections parameter.
        "current_lane",
        "blockers_open",
        "actions_pending",
        "decisions_recent",
        "slices_completed",
        "tests_recent",
        "findings_open",
        "worktree_lanes",
        "worker_reports_recent",
        "lane_messages_open",
    }
)

_VALID_DETAIL_LEVELS = frozenset({"full", "summary"})

_SUMMARY_TRUNCATE_LENGTH = 200


def _truncate_for_summary(row: dict, fields: tuple[str, ...]) -> dict:
    """Return a shallow copy with long text fields truncated."""
    out = dict(row)
    for field in fields:
        value = out.get(field)
        if isinstance(value, str) and len(value) > _SUMMARY_TRUNCATE_LENGTH:
            out[field] = value[:_SUMMARY_TRUNCATE_LENGTH] + "..."
    return out


_IDENTITY_TOKEN = "identity"


def _parse_sections(sections: str | None) -> frozenset[str] | None:
    """Parse a comma-separated sections string. Returns None for 'all'.

    The reserved token ``identity`` explicitly requests an identity-only
    response (active + limits only, no data sections). When ``identity``
    is present, all other tokens are ignored.

    Invalid section names are silently dropped. If no valid names remain
    after filtering, returns an empty frozenset (same identity-only shape).
    Callers that want all sections should pass sections=None (the default).
    """
    if sections is None:
        return None
    parts = frozenset(s.strip().lower() for s in sections.split(",") if s.strip())
    if _IDENTITY_TOKEN in parts:
        return frozenset()
    return parts & _VALID_SECTIONS


def get_handoff_state(
    task_ref: str | None = None,
    top_n_blockers: int = DEFAULT_HANDOFF_LIMITS["blockers"],
    top_n_actions: int = DEFAULT_HANDOFF_LIMITS["actions"],
    top_n_decisions: int = DEFAULT_HANDOFF_LIMITS["decisions"],
    top_n_slices: int = DEFAULT_HANDOFF_LIMITS["slices"],
    top_n_tests: int = DEFAULT_HANDOFF_LIMITS["tests"],
    top_n_findings: int = DEFAULT_HANDOFF_LIMITS["findings"],
    verbose: bool = False,
    include_archived: bool = True,
    sections: str | None = None,
    detail: str = "full",
) -> dict:
    if detail not in _VALID_DETAIL_LEVELS:
        detail = "full"
    requested_sections = _parse_sections(sections)
    top_n_blockers = max(1, top_n_blockers)
    top_n_actions = max(1, top_n_actions)
    top_n_decisions = max(1, top_n_decisions)
    top_n_slices = max(1, top_n_slices)
    top_n_tests = max(1, top_n_tests)
    top_n_findings = max(1, top_n_findings)

    def _want(section: str) -> bool:
        return requested_sections is None or section in requested_sections

    with _get_db_connection() as conn:
        if task_ref is None:
            any_row = conn.execute("SELECT 1 FROM handoff_state LIMIT 1").fetchone()
            if any_row is None:
                return _envelope(
                    ok=True, tool="get_handoff_state", data={"active": None, "message": "No active handoff state."}
                )
            try:
                resolved_row = _resolve_workspace_handoff_row(conn)
            except ValueError as exc:
                return _envelope(ok=False, tool="get_handoff_state", data={"error": str(exc)})
            if resolved_row is None:
                return _envelope(
                    ok=True, tool="get_handoff_state", data={"active": None, "message": "No active handoff state."}
                )
            resolved_task_ref = str(resolved_row["task_ref"])
            active_row = resolved_row
        else:
            resolved_task_ref = task_ref
            active_row = _get_handoff_row_for_task(conn, resolved_task_ref)
        active = _row_to_dict(active_row) if active_row is not None else None

        def query_limit(size: int) -> int:
            return size if not verbose else 10000

        def _apply_detail(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
            if detail == "summary":
                return [_truncate_for_summary(r, fields) for r in rows]
            return rows

        result: dict = {
            "ok": True,
            "task_ref": resolved_task_ref,
        }

        # Always include active and limits (cheap identity data)
        result["active"] = active
        result["limits"] = {
            "blockers": top_n_blockers,
            "actions": top_n_actions,
            "decisions": top_n_decisions,
            "slices": top_n_slices,
            "tests": top_n_tests,
            "findings": top_n_findings,
            "write": {
                "rationale_soft_chars": RATIONALE_SOFT_LIMIT_CHARS,
                "rationale_hard_chars": RATIONALE_HARD_LIMIT_CHARS,
                "slice_complete_hard_chars": SLICE_COMPLETE_HARD_LIMIT_CHARS,
                "slice_complete_required_sections": list(SLICE_COMPLETE_REQUIRED_SECTIONS),
            },
        }

        if _want("current_lane"):
            current_lane_row = _resolve_current_lane_row(conn, resolved_task_ref)
            result["current_lane"] = _row_to_dict(current_lane_row)
        else:
            current_lane_row = None

        if _want("blockers_open"):
            result["blockers_open"] = _fetch_handoff_rows(
                conn,
                table="blockers",
                where_sql="task_ref = ? AND status = 'open'",
                order_sql="created_at DESC",
                limit=query_limit(top_n_blockers),
                params=(resolved_task_ref,),
            )

        if _want("actions_pending"):
            result["actions_pending"] = _fetch_handoff_rows(
                conn,
                table="next_actions",
                where_sql="task_ref = ? AND status = 'pending'",
                order_sql="priority ASC, created_at ASC",
                limit=query_limit(top_n_actions),
                params=(resolved_task_ref,),
            )

        if _want("decisions_recent"):
            rows = _fetch_handoff_rows(
                conn,
                table="decisions",
                where_sql="task_ref = ?",
                order_sql="created_at DESC",
                limit=query_limit(top_n_decisions),
                params=(resolved_task_ref,),
            )
            result["decisions_recent"] = _apply_detail(rows, ("rationale",))

        if _want("slices_completed"):
            rows = _fetch_handoff_rows(
                conn,
                table="decisions",
                where_sql="task_ref = ? AND decision LIKE '%slice_complete%'",
                order_sql="created_at DESC",
                limit=query_limit(top_n_slices),
                params=(resolved_task_ref,),
            )
            slice_rows = []
            for row in rows:
                decision_id = str(row.get("decision") or "")
                if not is_slice_complete_decision(decision_id):
                    continue
                shaped = dict(row)
                shaped["slice_label"] = extract_slice_label(decision_id)
                slice_rows.append(shaped)
            result["slices_completed"] = _apply_detail(slice_rows, ("rationale",))

        if _want("tests_recent"):
            rows = _fetch_handoff_rows(
                conn,
                table="verified_tests",
                where_sql="task_ref = ?",
                order_sql="verified_at DESC",
                limit=query_limit(top_n_tests),
                params=(resolved_task_ref,),
            )
            result["tests_recent"] = _apply_detail(rows, ("command", "result"))

        if _want("findings_open"):
            rows = _fetch_handoff_rows(
                conn,
                table="review_findings",
                where_sql="task_ref = ? AND status = 'open'",
                order_sql="CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, created_at DESC",
                limit=query_limit(top_n_findings),
                params=(resolved_task_ref,),
            )
            result["findings_open"] = _apply_detail(
                rows, ("description", "fix", "resolution_notes", "verification_evidence")
            )

        if _want("worktree_lanes"):
            result["worktree_lanes"] = _fetch_handoff_rows(
                conn,
                table="worktree_lanes",
                where_sql="task_ref = ?",
                order_sql="updated_at DESC, id DESC",
                limit=50,
                params=(resolved_task_ref,),
            )

        if _want("worker_reports_recent"):
            result["worker_reports_recent"] = _fetch_handoff_rows(
                conn,
                table="worker_reports",
                where_sql="task_ref = ?",
                order_sql="created_at DESC, id DESC",
                limit=query_limit(top_n_tests),
                params=(resolved_task_ref,),
            )

        if _want("lane_messages_open"):
            # Always resolve lane for message scoping, even if current_lane
            # section was not requested.
            if current_lane_row is None:
                current_lane_row = _resolve_current_lane_row(conn, resolved_task_ref)
            lane_messages_where_sql = "task_ref = ? AND status = 'open'"
            lane_messages_params: tuple[object, ...] = (resolved_task_ref,)
            if current_lane_row is not None:
                lane_messages_where_sql += " AND lane_id = ?"
                lane_messages_params = (resolved_task_ref, str(current_lane_row["lane_id"]))
            result["lane_messages_open"] = _fetch_handoff_rows(
                conn,
                table="lane_messages",
                where_sql=lane_messages_where_sql,
                order_sql="updated_at DESC, id DESC",
                limit=50,
                params=lane_messages_params,
            )

        warnings = result.pop("warnings", []) or []
        task_ref_val = result.pop("task_ref", resolved_task_ref)
        result.pop("ok", None)
        return _envelope(
            ok=True,
            tool="get_handoff_state",
            data=result,
            task_ref=task_ref_val,
            warnings=warnings,
        )
