"""DASHBOARD.md rendering for agent_handoff_mcp.

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
    kind: str   # "findings", "blocked", "stale"
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
            items.append({
                "task_ref": task_ref,
                "kind": "findings",
                "detail": f"{high + medium} open ({', '.join(parts)})",
            })
            seen_tasks.add(task_ref)

    # Also surface active-task open findings by pulling them directly
    active_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
    if active_row:
        active_ref = str(active_row["task_ref"])
        if active_ref not in seen_tasks:
            rows = conn.execute(
                "SELECT severity FROM review_findings WHERE task_ref = ? AND status = 'open'",
                (active_ref,),
            ).fetchall()
            high = sum(1 for r in rows if r["severity"] == "high")
            medium = sum(1 for r in rows if r["severity"] == "medium")
            if high or medium:
                parts = []
                if high:
                    parts.append(f"{high} high")
                if medium:
                    parts.append(f"{medium} medium")
                items.append({
                    "task_ref": active_ref,
                    "kind": "findings",
                    "detail": f"{high + medium} open ({', '.join(parts)})",
                })
                seen_tasks.add(active_ref)

    # --- Blocked tasks ---
    for row in dashboard_rows:
        if int(row.get("open_blockers", 0)) > 0:
            task_ref = str(row["task_ref"])
            n = int(row["open_blockers"])
            items.append({
                "task_ref": task_ref,
                "kind": "blocked",
                "detail": f"blocked: {n} open blocker{'s' if n > 1 else ''}",
            })

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
            items.append({
                "task_ref": str(row["task_ref"]),
                "kind": "stale",
                "detail": f"stale: no activity since {ts.strftime('%Y-%m-%d %H:%M')} UTC",
            })

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
        rows.append({
            "task_ref": str(r.get("task_ref", "")),
            "status": str(r.get("status", "")),
            "last_activity": r.get("last_activity"),
            "open_blockers": int(r.get("open_blockers", 0)),
            "pending_actions": int(r.get("pending_actions", 0)),
            "open_findings": int(r.get("open_findings", 0)),
            "archived_at": r.get("archived_at"),
        })
    return _render_dashboard_section(rows, active_task_ref)


def _render_open_findings_section(open_findings: dict[str, list[dict]]) -> list[str]:
    lines: list[str] = ["", "OPEN FINDINGS", "-" * 13]
    if not open_findings:
        lines.append("  (none)")
        return lines
    for task_ref, findings in sorted(open_findings.items()):
        lines.extend(["", f"  [{task_ref}]"])
        for f in findings:
            location = (
                f"{f.get('file_path')}:{f.get('line_start')}"
                if f.get("line_start")
                else f.get("file_path", "")
            )
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
            location = (
                f"{f.get('file_path')}:{f.get('line_start')}"
                if f.get("line_start")
                else f.get("file_path", "")
            )
            status_label = f.get("status", "deferred").upper()
            lines.append(
                f"  [{status_label}] [{f.get('severity', '').upper()}] {f.get('finding_id')}: {location} -- {f.get('description', '')}"
            )
    return lines


# ---------------------------------------------------------------------------
# Context collection
# ---------------------------------------------------------------------------


def _collect_dashboard_context(conn: sqlite3.Connection, task_ref: str | None) -> DashboardContext:
    """Query pre-aggregated data to pass to extensions."""
    lanes = conn.execute(
        "SELECT * FROM worktree_lanes ORDER BY updated_at DESC, id DESC LIMIT 20"
    ).fetchall()
    reports = conn.execute(
        "SELECT * FROM worker_reports ORDER BY created_at DESC, id DESC LIMIT 20"
    ).fetchall()
    metrics = conn.execute(
        "SELECT * FROM turn_metrics ORDER BY created_at DESC, id DESC LIMIT 20"
    ).fetchall()
    return {
        "worktree_lanes": [dict(r) for r in lanes],
        "worker_reports": [dict(r) for r in reports],
        "turn_metrics": [dict(r) for r in metrics],
    }


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
    lines.extend(_render_open_findings_section(open_findings))
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
    """Generate DASHBOARD.md from the live handoff DB.

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
        active_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
        active_task_ref = str(active_row["task_ref"]) if active_row and active_row["task_ref"] else None

        dashboard_rows = _collect_dashboard_rows(conn)
        open_findings = _collect_all_open_findings(conn, max_per_task=100)
        deferred_findings = _collect_all_deferred_findings(conn, max_per_task=100)
        needs_attention = _collect_needs_attention(conn, dashboard_rows, open_findings)
        ctx = _collect_dashboard_context(conn, active_task_ref)

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
        active_task_ref=active_task_ref,
        extension_sections=extension_sections,
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
