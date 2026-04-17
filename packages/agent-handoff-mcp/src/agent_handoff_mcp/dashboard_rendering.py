"""DASHBOARD.txt rendering for agent_handoff_mcp.

Contains:
  - DashboardContext, DashboardSection, DashboardExtension types
  - Extension registry (register_dashboard_extension, clear_dashboard_extensions)
  - Needs-attention aggregation (_collect_needs_attention)
  - Core dashboard section renderers
  - generate_dashboard_md() — public entry point

Core sections always render before extension sections, regardless of order values.
Extension order field controls relative placement among extensions only.
"""

from __future__ import annotations

import sqlite3
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

from .runtime import get_runtime_config
from .shared_schema import _get_db_connection

# ---------------------------------------------------------------------------
# Public protocol types
# ---------------------------------------------------------------------------


class DashboardContext(TypedDict):
    """Pre-queried data passed to extensions so they never touch the DB directly."""

    worktree_lanes: list[dict]
    worker_reports: list[dict]
    turn_metrics: list[dict]


class DashboardSection(TypedDict):
    """A named content block contributed by a DashboardExtension.

    ``order`` controls relative placement among extension sections.
    Core sections always render before any extension section.
    """

    heading: str
    content: str
    order: int


DashboardExtension = Callable[[DashboardContext], list[DashboardSection]]

# ---------------------------------------------------------------------------
# Extension registry
# ---------------------------------------------------------------------------

_extensions: list[DashboardExtension] = []


def register_dashboard_extension(ext: DashboardExtension) -> None:
    """Register a dashboard extension callback.

    The callback receives a DashboardContext with pre-queried data and returns
    a list of DashboardSection dicts that are appended after core sections.
    Called at import time by extension providers (e.g. agent-orchestrator-mcp).
    """
    _extensions.append(ext)


def clear_dashboard_extensions() -> None:
    """Reset the extension registry.  Use in test fixtures to prevent leakage."""
    _extensions.clear()


# ---------------------------------------------------------------------------
# Needs-attention computation
# ---------------------------------------------------------------------------

_STALE_THRESHOLD_HOURS = 24


class _NeedsAttentionItem(TypedDict):
    task_ref: str
    kind: str  # "findings", "blocked", "stale"
    detail: str


def _collect_needs_attention(
    conn: sqlite3.Connection,
    dashboard_rows: list[dict],
    open_findings: dict[str, list[dict]],
) -> list[_NeedsAttentionItem]:
    """Aggregate items that warrant human attention.

    - Tasks with open high/medium findings
    - Tasks with open blockers (open_blockers > 0)
    - Non-archived tasks with no activity in >24 h
    """
    items: list[_NeedsAttentionItem] = []
    seen_tasks: set[str] = set()

    # --- Findings: high or medium severity ---
    for task_ref, findings in open_findings.items():
        high = sum(1 for f in findings if f.get("severity") == "high")
        medium = sum(1 for f in findings if f.get("severity") == "medium")
        if high or medium:
            parts = []
            if high:
                parts.append(f"{high} high")
            if medium:
                parts.append(f"{medium} medium")
            items.append(
                {
                    "task_ref": task_ref,
                    "kind": "findings",
                    "detail": f"{high + medium} open ({', '.join(parts)})",
                }
            )
            seen_tasks.add(task_ref)

    # --- Blocked tasks ---
    for row in dashboard_rows:
        if int(row.get("open_blockers", 0)) > 0:
            task_ref = str(row["task_ref"])
            n = int(row["open_blockers"])
            items.append(
                {
                    "task_ref": task_ref,
                    "kind": "blocked",
                    "detail": f"blocked: {n} open blocker{'s' if n > 1 else ''}",
                }
            )

    # --- Stale tasks (non-archived, no activity in >24 h) ---
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(hours=_STALE_THRESHOLD_HOURS)
    for row in dashboard_rows:
        if row.get("archived_at"):
            continue
        last_activity = row.get("last_activity")
        if not last_activity:
            continue
        try:
            ts = datetime.fromisoformat(last_activity.replace(" ", "T"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
        except ValueError:
            continue
        if ts < stale_cutoff:
            items.append(
                {
                    "task_ref": str(row["task_ref"]),
                    "kind": "stale",
                    "detail": f"stale: no activity since {ts.strftime('%Y-%m-%d %H:%M')} UTC",
                }
            )

    return items


# ---------------------------------------------------------------------------
# Core section renderers
# ---------------------------------------------------------------------------


def _render_needs_attention_section(items: list[_NeedsAttentionItem]) -> list[str]:
    lines: list[str] = ["", "NEEDS ATTENTION", "-" * 15]
    if not items:
        lines.append("  (all clear)")
        return lines
    for item in items:
        icon = "!" if item["kind"] != "stale" else "~"
        task_ref = item["task_ref"]
        detail = item["detail"]
        lines.append(f"  {icon} {task_ref:<20}  {detail}")
    return lines


def _render_all_tasks_section(dashboard_rows: list[dict], active_task_ref: str | None) -> list[str]:
    # Re-use the ASCII table renderer from current_task_rendering.
    from .current_task_rendering import (  # noqa: PLC0415
        DashboardTaskRow,
        _render_dashboard_section,
    )

    rows: list[DashboardTaskRow] = []
    for r in dashboard_rows:
        rows.append(
            {
                "task_ref": str(r.get("task_ref", "")),
                "status": str(r.get("status", "")),
                "last_activity": r.get("last_activity"),
                "open_blockers": int(r.get("open_blockers", 0)),
                "pending_actions": int(r.get("pending_actions", 0)),
                "open_findings": int(r.get("open_findings", 0)),
                "archived_at": r.get("archived_at"),
            }
        )
    return _render_dashboard_section(rows, active_task_ref)


def _render_open_findings_section(open_findings: dict[str, list[dict]]) -> list[str]:
    lines: list[str] = ["", "OPEN FINDINGS", "-" * 13]
    if not open_findings:
        lines.append("  (none)")
        return lines
    for task_ref, findings in sorted(open_findings.items()):
        lines.extend(["", f"  [{task_ref}]"])
        for f in findings:
            location = f"{f.get('file_path')}:{f.get('line_start')}" if f.get("line_start") else f.get("file_path", "")
            lines.append(
                f"  [{f.get('severity', '').upper()}] {f.get('finding_id')}: {location} -- {f.get('description', '')}"
            )
    return lines


def _render_deferred_findings_section(deferred_findings: dict[str, list[dict]]) -> list[str]:
    lines: list[str] = ["", "DEFERRED / WONTFIX", "-" * 18]
    if not deferred_findings:
        return []
    for task_ref, findings in sorted(deferred_findings.items()):
        lines.extend(["", f"  [{task_ref}]"])
        for f in findings:
            location = f"{f.get('file_path')}:{f.get('line_start')}" if f.get("line_start") else f.get("file_path", "")
            status_label = f.get("status", "deferred").upper()
            lines.append(
                f"  [{status_label}] [{f.get('severity', '').upper()}] {f.get('finding_id')}: {location} -- {f.get('description', '')}"
            )
    return lines


# ---------------------------------------------------------------------------
# New section: epic recent decisions
# ---------------------------------------------------------------------------


def _collect_epic_decisions(
    conn: sqlite3.Connection,
    active_task_refs: list[str],
    limit: int = 8,
) -> list[tuple[str, list[dict]]]:
    """Return recent decisions for each active epic represented by live rows.

    Each distinct epic inferred from the live task refs contributes one section.
    """
    from .current_task_rendering import _infer_epic_ref  # noqa: PLC0415

    sections: list[tuple[str, list[dict]]] = []
    seen_epics: set[str] = set()
    for task_ref in active_task_refs:
        epic_ref = _infer_epic_ref(task_ref)
        if not epic_ref or epic_ref in seen_epics:
            continue
        seen_epics.add(epic_ref)
        rows = conn.execute(
            "SELECT id, task_ref, decision, agent, created_at FROM decisions "
            "WHERE task_ref = ? OR task_ref LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (epic_ref, f"{epic_ref}-%", limit),
        ).fetchall()
        sections.append((epic_ref, [dict(r) for r in rows]))
    return sections


def _render_epic_decisions_section(epic_ref: str, decisions: list[dict]) -> list[str]:
    heading = f"RECENT DECISIONS ({epic_ref})"
    lines: list[str] = ["", heading, "-" * len(heading)]
    if not decisions:
        lines.append("  (none)")
        return lines
    col_ref = 8
    for d in decisions:
        task_ref = str(d.get("task_ref", ""))
        slug = str(d.get("decision", ""))
        created = str(d.get("created_at", ""))[:16]
        agent = d.get("agent") or ""
        agent_suffix = f" ({agent})" if agent else ""
        lines.append(f"  {task_ref:<{col_ref}}  [#{d.get('id')}] {slug}{agent_suffix}  {created}")
    return lines


def _render_epic_decisions_sections(epic_decision_groups: list[tuple[str, list[dict]]]) -> list[str]:
    lines: list[str] = []
    for epic_ref, decisions in epic_decision_groups:
        lines.extend(_render_epic_decisions_section(epic_ref, decisions))
    return lines


# ---------------------------------------------------------------------------
# New section: test status per task
# ---------------------------------------------------------------------------


def _collect_task_test_status(
    conn: sqlite3.Connection,
    active_task_refs: list[str] | None = None,
) -> dict[str, dict]:
    """Return per-task test summary across all live dashboard scopes.

    For epic-style task refs, include the full epic scope once. For non-epic
    refs, include that task directly. Never returns the full unbounded table.
    """
    from .current_task_rendering import _infer_epic_ref  # noqa: PLC0415

    summary: dict[str, dict] = {}
    seen_scopes: set[tuple[str, str]] = set()
    for task_ref in active_task_refs or []:
        epic_ref = _infer_epic_ref(task_ref)
        if epic_ref is not None:
            scope = ("epic", epic_ref)
            if scope in seen_scopes:
                continue
            seen_scopes.add(scope)
            rows = conn.execute(
                "SELECT task_ref, passed, verified_at FROM verified_tests"
                " WHERE task_ref = ? OR task_ref LIKE ?"
                " ORDER BY verified_at DESC",
                (epic_ref, f"{epic_ref}-%"),
            ).fetchall()
        else:
            scope = ("task", task_ref)
            if scope in seen_scopes:
                continue
            seen_scopes.add(scope)
            rows = conn.execute(
                "SELECT task_ref, passed, verified_at FROM verified_tests WHERE task_ref = ? ORDER BY verified_at DESC",
                (task_ref,),
            ).fetchall()
        for row in rows:
            ref = str(row["task_ref"])
            passed = bool(row["passed"])
            ts = str(row["verified_at"] or "")
            if ref not in summary:
                summary[ref] = {
                    "latest_passed": passed,
                    "latest_at": ts[:16],
                    "pass_count": 0,
                    "fail_count": 0,
                }
            if passed:
                summary[ref]["pass_count"] += 1
            else:
                summary[ref]["fail_count"] += 1
    return summary


def _render_test_status_section(status_by_task: dict[str, dict]) -> list[str]:
    lines: list[str] = ["", "TEST STATUS", "-" * 11]
    if not status_by_task:
        lines.append("  (no verified tests recorded)")
        return lines
    col_ref = 12
    for task_ref, s in sorted(status_by_task.items()):
        icon = "✓" if s["latest_passed"] else "✗"
        totals = f"pass={s['pass_count']} fail={s['fail_count']}"
        lines.append(f"  {task_ref:<{col_ref}}  {icon}  last: {s['latest_at']}  {totals}")
    return lines


# ---------------------------------------------------------------------------
# Context collection
# ---------------------------------------------------------------------------


def _collect_dashboard_context(conn: sqlite3.Connection, task_ref: str | None) -> DashboardContext:
    """Query pre-aggregated data to pass to extensions."""
    lanes = conn.execute("SELECT * FROM worktree_lanes ORDER BY updated_at DESC, id DESC LIMIT 20").fetchall()
    reports = conn.execute("SELECT * FROM worker_reports ORDER BY created_at DESC, id DESC LIMIT 20").fetchall()
    metrics = conn.execute("SELECT * FROM turn_metrics ORDER BY created_at DESC, id DESC LIMIT 20").fetchall()
    return {
        "worktree_lanes": [dict(r) for r in lanes],
        "worker_reports": [dict(r) for r in reports],
        "turn_metrics": [dict(r) for r in metrics],
    }


# ---------------------------------------------------------------------------
# Workflow integrity checks
# ---------------------------------------------------------------------------

_GIT_TIMEOUT = 5


def _collect_workflow_integrity(
    active_rows: list[dict],
) -> list[str]:
    """Derive workflow-integrity anomalies from all live dashboard rows.

    Returns a list of human-readable anomaly strings.  Empty list = clean.
    All git subprocess calls use a bounded timeout; on TimeoutExpired the
    caller receives a sentinel string instead of an exception.
    """
    anomalies: list[str] = []
    for active_row in active_rows:
        target_branch = active_row.get("target_branch")
        target_worktree_path = active_row.get("target_worktree_path")
        task_ref = str(active_row.get("task_ref") or "")
        if not target_branch:
            continue
        prefix = f"[{task_ref}] " if task_ref else ""

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", str(target_branch)],
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )
            if result.returncode != 0:
                anomalies.append(f"{prefix}missing branch: {target_branch} does not exist")
                continue

            merged = subprocess.run(
                ["git", "branch", "--merged", "main"],
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )
            merged_branches = [b.strip().lstrip("* ") for b in merged.stdout.splitlines()]
            if target_branch in merged_branches:
                anomalies.append(f"{prefix}undeleted merged branch: {target_branch} is fully merged to main")

            if target_worktree_path:
                wt_list = subprocess.run(
                    ["git", "worktree", "list", "--porcelain"],
                    capture_output=True,
                    text=True,
                    timeout=_GIT_TIMEOUT,
                )
                worktree_found = False
                for line in wt_list.stdout.splitlines():
                    if line.startswith("worktree ") and line[9:] == target_worktree_path:
                        worktree_found = True
                        break
                if not worktree_found:
                    anomalies.append(f"{prefix}missing worktree: {target_worktree_path} not found")

        except subprocess.TimeoutExpired:
            anomalies.append(f"{prefix}git check timed out (5s)")

    return anomalies


def _render_workflow_integrity_section(anomalies: list[str]) -> list[str]:
    """Render WORKFLOW INTEGRITY section.  Returns empty list when no anomalies."""
    if not anomalies:
        return []
    lines: list[str] = ["", "WORKFLOW INTEGRITY", "-" * 18]
    for a in anomalies:
        lines.append(f"  ! {a}")
    return lines


# ---------------------------------------------------------------------------
# Primary render function
# ---------------------------------------------------------------------------


def _render_dashboard_md(
    generated_at: str,
    dashboard_rows: list[dict],
    open_findings: dict[str, list[dict]],
    deferred_findings: dict[str, list[dict]],
    needs_attention: list[_NeedsAttentionItem],
    active_task_ref: str | None,
    extension_sections: list[DashboardSection],
    epic_decision_groups: list[tuple[str, list[dict]]] | None = None,
    task_test_status: dict[str, dict] | None = None,
    integrity_anomalies: list[str] | None = None,
) -> str:
    sep = "=" * 80
    lines: list[str] = [
        "DASHBOARD",
        sep,
        f"DO NOT EDIT: generated from .task-state/handoff.db at {generated_at}",
        sep,
    ]

    lines.extend(_render_needs_attention_section(needs_attention))
    lines.extend(_render_all_tasks_section(dashboard_rows, active_task_ref))

    if epic_decision_groups:
        lines.extend(_render_epic_decisions_sections(epic_decision_groups))

    # Active-task findings and integrity alerts render before TEST STATUS.
    lines.extend(_render_open_findings_section(open_findings))
    lines.extend(_render_workflow_integrity_section(integrity_anomalies or []))

    if task_test_status is not None:
        lines.extend(_render_test_status_section(task_test_status))

    deferred_lines = _render_deferred_findings_section(deferred_findings)
    if deferred_lines:
        lines.extend(deferred_lines)

    for section in sorted(extension_sections, key=lambda s: s["order"]):
        heading = section["heading"].upper()
        lines.extend(["", heading, "-" * len(heading)])
        lines.append(section["content"])

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_dashboard_md(write_file: bool = True) -> dict:
    """Generate DASHBOARD.txt from the live handoff DB.

    Core sections (Needs Attention, All Tasks, Open Findings, Deferred/Won't Fix)
    are always rendered.  Extension sections (registered via
    register_dashboard_extension) are appended after core sections, ordered by
    DashboardSection.order.

    Args:
        write_file: Write the markdown to the configured runtime dashboard path.

    Returns:
        A result dict with ``ok``, ``path``, ``written``, and ``markdown``.
    """
    from .current_task_rendering import (  # noqa: PLC0415
        _collect_all_deferred_findings,
        _collect_all_open_findings,
        _collect_dashboard_rows,
    )

    with _get_db_connection() as conn:
        active_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT task_ref, target_branch, target_worktree_path FROM handoff_state ORDER BY updated_at DESC, task_ref ASC"
            ).fetchall()
        ]
        active_task_refs = [str(row["task_ref"]) for row in active_rows if row.get("task_ref")]

        dashboard_rows = _collect_dashboard_rows(conn)
        open_findings = _collect_all_open_findings(conn, max_per_task=100)
        deferred_findings = _collect_all_deferred_findings(conn, max_per_task=100)
        needs_attention = _collect_needs_attention(conn, dashboard_rows, open_findings)
        ctx = _collect_dashboard_context(conn, None)
        epic_decision_groups = _collect_epic_decisions(conn, active_task_refs)
        task_test_status = _collect_task_test_status(conn, active_task_refs=active_task_refs)

    integrity_anomalies = _collect_workflow_integrity(active_rows)

    extension_sections: list[DashboardSection] = []
    for ext in _extensions:
        try:
            extension_sections.extend(ext(ctx))
        except Exception:
            pass

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    markdown = _render_dashboard_md(
        generated_at=generated_at,
        dashboard_rows=dashboard_rows,
        open_findings=open_findings,
        deferred_findings=deferred_findings,
        needs_attention=needs_attention,
        active_task_ref=None,
        extension_sections=extension_sections,
        epic_decision_groups=epic_decision_groups,
        task_test_status=task_test_status,
        integrity_anomalies=integrity_anomalies,
    )

    written = False
    dashboard_path: Path | None = None
    if write_file:
        cfg = get_runtime_config()
        dashboard_path = cfg.dashboard_path
        dashboard_path.write_text(markdown)
        written = True

    return {
        "ok": True,
        "path": str(dashboard_path) if dashboard_path else None,
        "written": written,
        "markdown": markdown if not write_file else None,
    }
