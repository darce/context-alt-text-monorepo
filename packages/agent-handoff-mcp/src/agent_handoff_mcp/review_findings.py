"""Review findings domain module."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TypedDict

from ._shared import (
    BATCH_CLOSE_THRESHOLD,
    BATCH_CLOSE_WINDOW_SECONDS,
    MAX_REOPEN_REASON_LENGTH,
    MAX_RESOLUTION_NOTES_LENGTH,
    MAX_VERIFICATION_EVIDENCE_LENGTH,
    REOPEN_ESCALATION_THRESHOLD,
    REVIEW_FINDING_SEVERITIES,
    REVIEW_FINDING_STATUSES,
    ResolvedWriteContext,
    ReviewFindingDetails,
    WriteActor,
    _annotate_review_finding,
    _dedupe_review_findings,
    _envelope,
    _get_db_connection,
    _json_response,
    _normalize_optional_text,
    _normalize_review_mode,
    _paginated_query,
    _parse_review_finding_details,
    _parse_sqlite_datetime,
    _resolve_task_ref,
    _resolve_write_actor,
    _row_to_dict,
    _workspace_git_context,
    _workspace_root,
    _write_current_task_md_for_task,
)


def _write_current_task_md_for_active_context(conn: sqlite3.Connection, fallback_task_ref: str) -> None:
    """Regenerate CURRENT_TASK.md for the active task when one exists.

    Review findings are often recorded against non-active tasks during review
    passes. CURRENT_TASK.md should stay anchored to the active task and render
    cross-task findings in the aggregated sections rather than switching to the
    last task whose finding row was touched.
    """

    active_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
    render_task_ref = (
        str(active_row["task_ref"]) if active_row is not None and active_row["task_ref"] else fallback_task_ref
    )
    _write_current_task_md_for_task(conn, render_task_ref)


def _current_task_revision(conn: sqlite3.Connection, task_ref: str) -> int | None:
    row = conn.execute(
        "SELECT revision FROM handoff_state WHERE id = 1 AND task_ref = ?",
        (task_ref,),
    ).fetchone()
    return int(row["revision"]) if row is not None else None


def _classify_commit_relation(reference_sha: str | None, candidate_sha: str | None) -> str:
    """Delegate to _shared, but allow monkeypatching via core module namespace."""
    from . import core as _core  # noqa: PLC0415 – late import to avoid circular, enables monkeypatching

    return _core._classify_commit_relation(reference_sha, candidate_sha)


def _detect_git_write_context() -> tuple[str | None, str | None]:
    """Delegate to _shared, but allow monkeypatching via core module namespace."""
    from . import core as _core  # noqa: PLC0415

    return _core._detect_git_write_context()


def _check_reopen_escalation_guard(
    existing: sqlite3.Row,
    verification_evidence: str | None,
) -> dict | None:
    existing_reopen_count = int(existing["reopen_count"] or 0)
    if existing_reopen_count >= REOPEN_ESCALATION_THRESHOLD and verification_evidence is None:
        return {
            "ok": False,
            "error": (
                f"verification_evidence is required when fixing a finding that has been reopened "
                f"{existing_reopen_count} times (threshold: {REOPEN_ESCALATION_THRESHOLD}). "
                f"Provide code snippets, grep output, or diff output proving the fix exists."
            ),
            "false_fix_guard": {
                "finding_id": str(existing["finding_id"]),
                "reopen_count": existing_reopen_count,
                "threshold": REOPEN_ESCALATION_THRESHOLD,
                "guard": "reopen_escalation",
            },
        }
    return None


def _check_batch_close_guard(
    conn: sqlite3.Connection,
    task_ref: str,
    existing: sqlite3.Row,
) -> dict | None:
    recent_fixes = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM review_findings
        WHERE task_ref = ? AND status = 'fixed'
          AND resolved_at >= datetime('now', ?)
          AND id != ?
        """,
        (task_ref, f"-{BATCH_CLOSE_WINDOW_SECONDS} seconds", int(existing["id"])),
    ).fetchone()
    recent_count = int(recent_fixes["cnt"]) if recent_fixes else 0
    if recent_count >= BATCH_CLOSE_THRESHOLD:
        return {
            "ok": False,
            "error": (
                f"Batch-close guard: {recent_count} other findings were marked fixed in the "
                f"last {BATCH_CLOSE_WINDOW_SECONDS}s for this task. Provide verification_evidence "
                f"(code snippets, grep output, or diff proving the fix exists) to confirm each "
                f"closure is individually verified."
            ),
            "false_fix_guard": {
                "finding_id": str(existing["finding_id"]),
                "recent_fixes_in_window": recent_count,
                "window_seconds": BATCH_CLOSE_WINDOW_SECONDS,
                "threshold": BATCH_CLOSE_THRESHOLD,
                "guard": "batch_close",
            },
        }
    return None


def _check_commit_relation_guard(
    existing: sqlite3.Row,
    commit_sha: str | None,
    verified_commit_sha: str | None,
    branch: str | None,
    resolution_notes: str | None,
) -> dict | None:
    finding_commit_sha = _normalize_optional_text(existing["commit_sha"])
    current_commit_sha = _normalize_optional_text(commit_sha)
    commit_relation = _classify_commit_relation(finding_commit_sha, current_commit_sha)
    if commit_relation in {"ancestor", "diverged"}:
        return {
            "ok": False,
            "error": "A finding can only be marked fixed from the same commit or a newer descendant commit.",
            "commit_guard": {
                "finding_commit_sha": finding_commit_sha,
                "current_commit_sha": current_commit_sha,
                "current_branch": branch,
                "verified_commit_sha": verified_commit_sha,
                "relation": commit_relation,
            },
        }
    if commit_relation == "descendant":
        if resolution_notes is None:
            return {
                "ok": False,
                "error": "resolution_notes is required when fixing a finding from a newer descendant commit.",
                "commit_guard": {
                    "finding_commit_sha": finding_commit_sha,
                    "current_commit_sha": current_commit_sha,
                    "current_branch": branch,
                    "relation": commit_relation,
                    "requires_verified_commit_sha": True,
                },
            }
        if verified_commit_sha is None:
            return {
                "ok": False,
                "error": "verified_commit_sha is required when fixing a finding from a newer descendant commit.",
                "commit_guard": {
                    "finding_commit_sha": finding_commit_sha,
                    "current_commit_sha": current_commit_sha,
                    "current_branch": branch,
                    "relation": commit_relation,
                    "requires_verified_commit_sha": True,
                },
            }
        if current_commit_sha is not None and verified_commit_sha != current_commit_sha:
            return {
                "ok": False,
                "error": "verified_commit_sha must match the current workspace/actor commit when resolving from a newer descendant commit.",
                "commit_guard": {
                    "finding_commit_sha": finding_commit_sha,
                    "current_commit_sha": current_commit_sha,
                    "current_branch": branch,
                    "verified_commit_sha": verified_commit_sha,
                    "relation": commit_relation,
                },
            }
        verified_relation = _classify_commit_relation(finding_commit_sha, verified_commit_sha)
        if verified_relation not in {"same", "descendant"}:
            return {
                "ok": False,
                "error": "verified_commit_sha must be the finding commit or a descendant of it.",
                "commit_guard": {
                    "finding_commit_sha": finding_commit_sha,
                    "current_commit_sha": current_commit_sha,
                    "current_branch": branch,
                    "verified_commit_sha": verified_commit_sha,
                    "relation": commit_relation,
                    "verified_relation": verified_relation,
                },
            }
    return None


def record_review_finding(
    session: str,
    finding_id: str,
    severity: str,
    file_path: str,
    description: str,
    details: ReviewFindingDetails | None = None,
    actor: WriteActor | None = None,
    task_ref: str | None = None,
    review_mode: str | None = None,
) -> dict:
    if severity not in REVIEW_FINDING_SEVERITIES:
        return _envelope(
            ok=False,
            tool="record_review_finding",
            data={"error": f"Invalid severity. Valid: {', '.join(sorted(REVIEW_FINDING_SEVERITIES))}"},
            entity="finding",
        )
    try:
        normalized_review_mode = _normalize_review_mode(review_mode)
    except ValueError as exc:
        return _envelope(
            ok=False,
            tool="record_review_finding",
            data={"error": str(exc)},
            entity="finding",
        )
    line_start, line_end, fix = _parse_review_finding_details(details)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        ctx = _resolve_write_actor(conn, actor)
        existing = conn.execute(
            "SELECT status FROM review_findings WHERE task_ref = ? AND finding_id = ?", (resolved_task_ref, finding_id)
        ).fetchone()
        conn.execute(
            """
            INSERT INTO review_findings (
                task_ref, lane_id, finding_id, severity, file_path, line_start, line_end, description, fix, status, review_mode, session, agent, branch, commit_sha, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(task_ref, finding_id) DO UPDATE SET
                severity = excluded.severity,
                file_path = excluded.file_path,
                line_start = excluded.line_start,
                line_end = excluded.line_end,
                description = excluded.description,
                fix = excluded.fix,
                status = 'open',
                review_mode = COALESCE(excluded.review_mode, review_findings.review_mode),
                resolved_at = NULL,
                resolution_notes = NULL,
                reopen_count = CASE WHEN review_findings.status <> 'open' THEN COALESCE(review_findings.reopen_count, 0) + 1 ELSE COALESCE(review_findings.reopen_count, 0) END,
                last_reopen_reason = CASE WHEN review_findings.status <> 'open' THEN 'Re-recorded via review-record.' ELSE review_findings.last_reopen_reason END,
                last_reopened_at = CASE WHEN review_findings.status <> 'open' THEN datetime('now') ELSE review_findings.last_reopened_at END,
                updated_at = datetime('now'),
                session = excluded.session,
                lane_id = COALESCE(review_findings.lane_id, excluded.lane_id),
                agent = COALESCE(review_findings.agent, excluded.agent),
                branch = COALESCE(review_findings.branch, excluded.branch),
                commit_sha = COALESCE(review_findings.commit_sha, excluded.commit_sha)
            """,
            (
                resolved_task_ref,
                ctx.lane_id,
                finding_id,
                severity,
                file_path,
                line_start,
                line_end,
                description,
                fix,
                normalized_review_mode,
                session,
                ctx.agent,
                ctx.branch,
                ctx.commit_sha,
            ),
        )
        row = conn.execute(
            "SELECT * FROM review_findings WHERE task_ref = ? AND finding_id = ?", (resolved_task_ref, finding_id)
        ).fetchone()
        _write_current_task_md_for_active_context(conn, resolved_task_ref)
        data: dict[str, object] = {"finding": _row_to_dict(row)}
        if existing is not None and str(existing["status"]) != "open":
            data["reopened"] = True
        task_revision = _current_task_revision(conn, resolved_task_ref)
        return _envelope(
            ok=True,
            tool="record_review_finding",
            data=data,
            task_ref=resolved_task_ref,
            entity="finding",
            mutation={
                "entity": "finding",
                "operation": "upsert",
                "affected_ids": [finding_id],
                "task_revision": task_revision,
            },
        )


_BATCH_MAX_SIZE = 100


class BatchFindingItem(TypedDict, total=False):
    finding_id: str
    severity: str
    file_path: str
    description: str
    review_mode: str | None
    details: ReviewFindingDetails | None


def batch_record_review_findings(
    session: str,
    findings: list[BatchFindingItem],
    actor: WriteActor | None = None,
    task_ref: str | None = None,
) -> dict:
    """Record or reopen multiple review findings in a single atomic write."""
    if len(findings) > _BATCH_MAX_SIZE:
        return _envelope(
            ok=False,
            tool="batch_record_review_findings",
            data={"error": f"Batch exceeds maximum size of {_BATCH_MAX_SIZE} items."},
            entity="finding",
        )
    if not findings:
        return _envelope(
            ok=True,
            tool="batch_record_review_findings",
            data={"task_ref": task_ref or "unknown", "written": 0, "results": []},
            task_ref=task_ref,
            entity="finding",
        )

    # Pre-validate all items before opening the transaction.
    for i, item in enumerate(findings):
        fid = item.get("finding_id")
        if not fid:
            return _envelope(
                ok=False,
                tool="batch_record_review_findings",
                data={"error": f"Item {i} is missing finding_id."},
                entity="finding",
            )
        sev = item.get("severity")
        if sev not in REVIEW_FINDING_SEVERITIES:
            return _envelope(
                ok=False,
                tool="batch_record_review_findings",
                data={
                    "error": f"Item {i} (finding_id={fid!r}): Invalid severity. Valid: {', '.join(sorted(REVIEW_FINDING_SEVERITIES))}",
                },
                entity="finding",
            )
        if not item.get("file_path"):
            return _envelope(
                ok=False,
                tool="batch_record_review_findings",
                data={"error": f"Item {i} (finding_id={fid!r}): missing file_path."},
                entity="finding",
            )
        if not item.get("description"):
            return _envelope(
                ok=False,
                tool="batch_record_review_findings",
                data={"error": f"Item {i} (finding_id={fid!r}): missing description."},
                entity="finding",
            )
        try:
            _normalize_review_mode(item.get("review_mode"))
        except ValueError as exc:
            return _envelope(
                ok=False,
                tool="batch_record_review_findings",
                data={"error": f"Item {i} (finding_id={fid!r}): {exc}"},
                entity="finding",
            )

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        ctx = _resolve_write_actor(conn, actor)

        results: list[dict[str, object]] = []
        for item in findings:
            finding_id = item["finding_id"]
            severity = item["severity"]
            file_path = item["file_path"]
            description = item["description"]
            normalized_review_mode = _normalize_review_mode(item.get("review_mode"))
            line_start, line_end, fix = _parse_review_finding_details(item.get("details"))

            existing = conn.execute(
                "SELECT status FROM review_findings WHERE task_ref = ? AND finding_id = ?",
                (resolved_task_ref, finding_id),
            ).fetchone()

            conn.execute(
                """
                INSERT INTO review_findings (
                    task_ref, lane_id, finding_id, severity, file_path, line_start, line_end,
                    description, fix, status, review_mode, session, agent, branch, commit_sha,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(task_ref, finding_id) DO UPDATE SET
                    severity = excluded.severity,
                    file_path = excluded.file_path,
                    line_start = excluded.line_start,
                    line_end = excluded.line_end,
                    description = excluded.description,
                    fix = excluded.fix,
                    status = 'open',
                    review_mode = COALESCE(excluded.review_mode, review_findings.review_mode),
                    resolved_at = NULL,
                    resolution_notes = NULL,
                    reopen_count = CASE WHEN review_findings.status <> 'open'
                        THEN COALESCE(review_findings.reopen_count, 0) + 1
                        ELSE COALESCE(review_findings.reopen_count, 0) END,
                    last_reopen_reason = CASE WHEN review_findings.status <> 'open'
                        THEN 'Re-recorded via review-record.'
                        ELSE review_findings.last_reopen_reason END,
                    last_reopened_at = CASE WHEN review_findings.status <> 'open'
                        THEN datetime('now')
                        ELSE review_findings.last_reopened_at END,
                    updated_at = datetime('now'),
                    session = excluded.session,
                    lane_id = COALESCE(review_findings.lane_id, excluded.lane_id),
                    agent = COALESCE(review_findings.agent, excluded.agent),
                    branch = COALESCE(review_findings.branch, excluded.branch),
                    commit_sha = COALESCE(review_findings.commit_sha, excluded.commit_sha)
                """,
                (
                    resolved_task_ref,
                    ctx.lane_id,
                    finding_id,
                    severity,
                    file_path,
                    line_start,
                    line_end,
                    description,
                    fix,
                    normalized_review_mode,
                    session,
                    ctx.agent,
                    ctx.branch,
                    ctx.commit_sha,
                ),
            )

            item_result: dict[str, object] = {"finding_id": finding_id, "action": "inserted"}
            if existing is not None:
                if str(existing["status"]) != "open":
                    item_result["action"] = "updated"
                    item_result["reopened"] = True
                else:
                    item_result["action"] = "updated"
            results.append(item_result)

        _write_current_task_md_for_active_context(conn, resolved_task_ref)

    affected_ids = [item["finding_id"] for item in findings]
    with _get_db_connection() as conn:
        task_revision = _current_task_revision(conn, resolved_task_ref)
    return _envelope(
        ok=True,
        tool="batch_record_review_findings",
        data={
            "task_ref": resolved_task_ref,
            "written": len(findings),
            "results": results,
        },
        task_ref=resolved_task_ref,
        entity="finding",
        mutation={
            "entity": "finding",
            "operation": "batch_upsert",
            "affected_ids": affected_ids,
            "task_revision": task_revision,
        },
    )


def _apply_finding_update(
    conn: sqlite3.Connection,
    existing: sqlite3.Row,
    status: str,
    ctx: ResolvedWriteContext,
    session: str | None,
    resolved_task_ref: str,
    is_reopen_transition: bool,
    normalized_resolution_notes: str | None,
    normalized_reopen_reason: str | None,
    normalized_verified_commit_sha: str | None,
    normalized_verification_evidence: str | None,
) -> dict:
    """Execute the UPDATE and return the JSON response."""
    finding_commit_sha = _normalize_optional_text(existing["commit_sha"])
    current_commit_sha = _normalize_optional_text(ctx.commit_sha)
    commit_relation = _classify_commit_relation(finding_commit_sha, current_commit_sha)
    needs_descendant_ack = status == "fixed" and commit_relation == "descendant"
    target_db_id = int(existing["id"])
    reopen_transition_int = 1 if is_reopen_transition else 0
    conn.execute(
        """
        UPDATE review_findings
        SET status = ?, resolved_at = CASE WHEN ? IN ('fixed', 'wontfix') THEN datetime('now') ELSE NULL END,
            agent = COALESCE(agent, ?), branch = COALESCE(branch, ?), commit_sha = COALESCE(commit_sha, ?),
            lane_id = COALESCE(lane_id, ?),
            session = COALESCE(?, session),
            resolution_notes = CASE WHEN ? = 'open' THEN NULL WHEN ? IS NOT NULL THEN ? WHEN ? = 'fixed' THEN NULL ELSE resolution_notes END,
            reopen_count = CASE WHEN ? = 1 THEN COALESCE(reopen_count, 0) + 1 ELSE COALESCE(reopen_count, 0) END,
            last_reopen_reason = CASE WHEN ? = 1 THEN ? ELSE last_reopen_reason END,
            last_reopened_at = CASE WHEN ? = 1 THEN datetime('now') ELSE last_reopened_at END,
            verification_evidence = CASE WHEN ? = 'open' THEN NULL WHEN ? IS NOT NULL THEN ? ELSE verification_evidence END,
            updated_at = datetime('now')
        WHERE id = ? AND task_ref = ?
        """,
        (
            status,
            status,
            ctx.agent,
            ctx.branch,
            ctx.commit_sha,
            ctx.lane_id,
            session,
            status,
            normalized_resolution_notes,
            normalized_resolution_notes,
            status,
            reopen_transition_int,
            reopen_transition_int,
            normalized_reopen_reason,
            reopen_transition_int,
            status,
            normalized_verification_evidence,
            normalized_verification_evidence,
            target_db_id,
            resolved_task_ref,
        ),
    )
    row = conn.execute("SELECT * FROM review_findings WHERE id = ?", (target_db_id,)).fetchone()
    _write_current_task_md_for_active_context(conn, resolved_task_ref)
    data: dict[str, object] = {
        "finding": _row_to_dict(row),
        "commit_guard": {
            "finding_commit_sha": finding_commit_sha,
            "current_commit_sha": current_commit_sha,
            "current_branch": ctx.branch,
            "relation": commit_relation,
            "verified_commit_sha": normalized_verified_commit_sha,
            "required": needs_descendant_ack,
        },
    }
    if is_reopen_transition:
        data["reopened"] = True
        data["reopen_reason"] = normalized_reopen_reason
    if normalized_verification_evidence is not None:
        data["verification_evidence"] = normalized_verification_evidence
    finding_id_str = str(existing["finding_id"])
    task_revision = _current_task_revision(conn, resolved_task_ref)
    return _envelope(
        ok=True,
        tool="update_review_finding",
        data=data,
        task_ref=resolved_task_ref,
        entity="finding",
        mutation={
            "entity": "finding",
            "operation": "update",
            "affected_ids": [finding_id_str],
            "task_revision": task_revision,
        },
    )


def _validate_update_finding_input(
    status: str,
    finding_id: str | None,
    finding_db_id: int | None,
    normalized_finding_id: str | None,
    normalized_resolution_notes: str | None,
    normalized_reopen_reason: str | None,
    normalized_verified_commit_sha: str | None,
    normalized_verification_evidence: str | None,
) -> dict | None:
    """Return error dict if input is invalid, else None."""
    if (finding_id is None and finding_db_id is None) or (finding_id is not None and finding_db_id is not None):
        return {"ok": False, "error": "Pass exactly one of finding_id (preferred) or finding_db_id."}
    if status not in REVIEW_FINDING_STATUSES:
        return {"ok": False, "error": f"Invalid status. Valid: {', '.join(sorted(REVIEW_FINDING_STATUSES))}"}
    if normalized_finding_id == "":
        return {"ok": False, "error": "finding_id must not be empty."}
    if (
        normalized_verification_evidence is not None
        and len(normalized_verification_evidence) > MAX_VERIFICATION_EVIDENCE_LENGTH
    ):
        return {
            "ok": False,
            "error": f"verification_evidence must be <= {MAX_VERIFICATION_EVIDENCE_LENGTH} characters.",
        }
    if status != "fixed" and normalized_verification_evidence is not None:
        return {"ok": False, "error": "verification_evidence is only supported when status='fixed'."}
    if status in {"wontfix", "deferred"} and normalized_resolution_notes is None:
        return {"ok": False, "error": f"resolution_notes is required when status is '{status}'."}
    if status == "open" and normalized_resolution_notes is not None:
        return {
            "ok": False,
            "error": "resolution_notes is not supported for status='open'. Use reopen_reason when reopening.",
        }
    if normalized_resolution_notes is not None and len(normalized_resolution_notes) > MAX_RESOLUTION_NOTES_LENGTH:
        return {"ok": False, "error": f"resolution_notes must be <= {MAX_RESOLUTION_NOTES_LENGTH} characters."}
    if normalized_reopen_reason is not None and len(normalized_reopen_reason) > MAX_REOPEN_REASON_LENGTH:
        return {"ok": False, "error": f"reopen_reason must be <= {MAX_REOPEN_REASON_LENGTH} characters."}
    if status != "fixed" and normalized_verified_commit_sha is not None:
        return {"ok": False, "error": "verified_commit_sha is only supported when status='fixed'."}
    return None


def update_review_finding(
    status: str,
    finding_id: str | None = None,
    finding_db_id: int | None = None,
    resolution_notes: str | None = None,
    reopen_reason: str | None = None,
    task_ref: str | None = None,
    session: str | None = None,
    actor: WriteActor | None = None,
    verified_commit_sha: str | None = None,
    verification_evidence: str | None = None,
) -> dict:
    normalized_finding_id = finding_id.strip() if isinstance(finding_id, str) else None
    normalized_resolution_notes = _normalize_optional_text(resolution_notes)
    normalized_reopen_reason = _normalize_optional_text(reopen_reason)
    normalized_verified_commit_sha = _normalize_optional_text(verified_commit_sha)
    normalized_verification_evidence = _normalize_optional_text(verification_evidence)
    input_error = _validate_update_finding_input(
        status,
        finding_id,
        finding_db_id,
        normalized_finding_id,
        normalized_resolution_notes,
        normalized_reopen_reason,
        normalized_verified_commit_sha,
        normalized_verification_evidence,
    )
    if input_error is not None:
        return _envelope(
            ok=False,
            tool="update_review_finding",
            data={"error": input_error["error"]},
            entity="finding",
        )
    with _get_db_connection() as conn:
        ctx = _resolve_write_actor(conn, actor)
        if task_ref is None:
            # Global lookup: skip active-task fallback when no task_ref provided.
            if normalized_finding_id is not None:
                rows = conn.execute(
                    "SELECT * FROM review_findings WHERE finding_id = ?", (normalized_finding_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM review_findings WHERE id = ?", (finding_db_id,)).fetchall()
            if not rows:
                return _envelope(
                    ok=False,
                    tool="update_review_finding",
                    data={"error": "Finding not found."},
                    entity="finding",
                )
            if len(rows) > 1:
                candidate_scopes = sorted({str(r["task_ref"]) for r in rows})
                return _envelope(
                    ok=False,
                    tool="update_review_finding",
                    data={
                        "error": f"Ambiguous finding_id: {len(rows)} rows across task_refs {candidate_scopes}. Pass task_ref explicitly to disambiguate.",
                    },
                    entity="finding",
                )
            existing = rows[0]
            resolved_task_ref = str(existing["task_ref"])
        else:
            resolved_task_ref = _resolve_task_ref(conn, task_ref)
            existing = conn.execute(
                "SELECT * FROM review_findings WHERE finding_id = ? AND task_ref = ?"
                if normalized_finding_id is not None
                else "SELECT * FROM review_findings WHERE id = ? AND task_ref = ?",
                (normalized_finding_id, resolved_task_ref)
                if normalized_finding_id is not None
                else (finding_db_id, resolved_task_ref),
            ).fetchone()
            if existing is None:
                return _envelope(
                    ok=False,
                    tool="update_review_finding",
                    data={"error": "Finding not found for task."},
                    task_ref=resolved_task_ref,
                    entity="finding",
                )
        existing_status = str(existing["status"])
        is_reopen_transition = existing_status != "open" and status == "open"
        if is_reopen_transition and normalized_reopen_reason is None:
            return _envelope(
                ok=False,
                tool="update_review_finding",
                data={"error": "reopen_reason is required when reopening a finding."},
                task_ref=resolved_task_ref,
                entity="finding",
            )
        if not is_reopen_transition and normalized_reopen_reason is not None:
            return _envelope(
                ok=False,
                tool="update_review_finding",
                data={"error": "reopen_reason is only valid when transitioning a finding back to open."},
                task_ref=resolved_task_ref,
                entity="finding",
            )

        if status == "fixed":
            guard_error = _check_reopen_escalation_guard(existing, normalized_verification_evidence)
            if guard_error is not None:
                return _envelope(
                    ok=False,
                    tool="update_review_finding",
                    data={k: v for k, v in guard_error.items() if k != "ok"},
                    task_ref=resolved_task_ref,
                    entity="finding",
                )
        if status == "fixed" and normalized_verification_evidence is None:
            guard_error = _check_batch_close_guard(conn, resolved_task_ref, existing)
            if guard_error is not None:
                return _envelope(
                    ok=False,
                    tool="update_review_finding",
                    data={k: v for k, v in guard_error.items() if k != "ok"},
                    task_ref=resolved_task_ref,
                    entity="finding",
                )
        if status == "fixed":
            guard_error = _check_commit_relation_guard(
                existing, ctx.commit_sha, normalized_verified_commit_sha, ctx.branch, normalized_resolution_notes
            )
            if guard_error is not None:
                return _envelope(
                    ok=False,
                    tool="update_review_finding",
                    data={k: v for k, v in guard_error.items() if k != "ok"},
                    task_ref=resolved_task_ref,
                    entity="finding",
                )

        return _apply_finding_update(
            conn,
            existing,
            status,
            ctx,
            session,
            resolved_task_ref,
            is_reopen_transition,
            normalized_resolution_notes,
            normalized_reopen_reason,
            normalized_verified_commit_sha,
            normalized_verification_evidence,
        )


_FINDING_SUMMARY_FIELDS = ("description", "fix", "resolution_notes", "verification_evidence")
_FINDING_SUMMARY_TRUNCATE = 200


def list_review_findings(
    task_ref: str | None = None,
    status: str = "all",
    severity: str = "all",
    limit: int = 100,
    offset: int = 0,
    review_mode: str | None = None,
    finding_id: str | None = None,
    finding_db_id: int | None = None,
    detail: str = "full",
) -> dict:
    if detail not in ("full", "summary"):
        detail = "full"

    def _apply_finding_detail(finding: dict) -> dict:
        if detail != "summary":
            return finding
        out = dict(finding)
        for field in _FINDING_SUMMARY_FIELDS:
            value = out.get(field)
            if isinstance(value, str) and len(value) > _FINDING_SUMMARY_TRUNCATE:
                out[field] = value[:_FINDING_SUMMARY_TRUNCATE] + "..."
        return out

    if finding_id is not None or finding_db_id is not None:
        if finding_id is not None and finding_db_id is not None:
            return _envelope(
                ok=False,
                tool="list_review_findings",
                data={"error": "Pass exactly one of finding_id or finding_db_id, not both."},
                entity="finding",
            )
        with _get_db_connection() as conn:
            if task_ref is None:
                # Global lookup: skip active-task fallback when no task_ref provided.
                if finding_db_id is not None:
                    rows = conn.execute("SELECT * FROM review_findings WHERE id = ?", (finding_db_id,)).fetchall()
                else:
                    normalized_fid = finding_id.strip() if isinstance(finding_id, str) else None
                    if not normalized_fid:
                        return _envelope(
                            ok=False,
                            tool="list_review_findings",
                            data={"error": "finding_id must not be empty."},
                            entity="finding",
                        )
                    rows = conn.execute(
                        "SELECT * FROM review_findings WHERE finding_id = ?", (normalized_fid,)
                    ).fetchall()
                if not rows:
                    return _envelope(
                        ok=False,
                        tool="list_review_findings",
                        data={"error": "Finding not found."},
                        entity="finding",
                    )
                if len(rows) > 1:
                    candidate_scopes = sorted({str(r["task_ref"]) for r in rows})
                    return _envelope(
                        ok=False,
                        tool="list_review_findings",
                        data={
                            "error": f"Ambiguous finding_id: {len(rows)} rows across task_refs {candidate_scopes}. Pass task_ref explicitly to disambiguate.",
                        },
                        entity="finding",
                    )
                row = rows[0]
                resolved_task_ref = str(row["task_ref"])
            else:
                resolved_task_ref = _resolve_task_ref(conn, task_ref)
                if finding_db_id is not None:
                    row = conn.execute(
                        "SELECT * FROM review_findings WHERE id = ? AND task_ref = ?",
                        (finding_db_id, resolved_task_ref),
                    ).fetchone()
                else:
                    normalized_fid = finding_id.strip() if isinstance(finding_id, str) else None
                    if not normalized_fid:
                        return _envelope(
                            ok=False,
                            tool="list_review_findings",
                            data={"error": "finding_id must not be empty."},
                            task_ref=resolved_task_ref,
                            entity="finding",
                        )
                    row = conn.execute(
                        "SELECT * FROM review_findings WHERE finding_id = ? AND task_ref = ?",
                        (normalized_fid, resolved_task_ref),
                    ).fetchone()
                if row is None:
                    return _envelope(
                        ok=False,
                        tool="list_review_findings",
                        data={"error": "Finding not found for task."},
                        task_ref=resolved_task_ref,
                        entity="finding",
                    )
            workspace_git = _workspace_git_context()
            finding = _apply_finding_detail(
                _annotate_review_finding(
                    dict(row),
                    workspace_branch=workspace_git["branch"],
                    workspace_commit_sha=workspace_git["commit_sha"],
                )
            )
            return _envelope(
                ok=True,
                tool="list_review_findings",
                data={
                    "task_ref": resolved_task_ref,
                    "workspace_git": workspace_git,
                    "filters": {"finding_id": finding_id, "finding_db_id": finding_db_id},
                    "total_matching": 1,
                    "returned": 1,
                    "has_more": False,
                    "counts": {"status": {str(row["status"]): 1}, "severity": {str(row["severity"]): 1}},
                    "findings": [finding],
                },
                task_ref=resolved_task_ref,
                entity="finding",
            )
    valid_statuses = {"all", *REVIEW_FINDING_STATUSES}
    if status not in valid_statuses:
        return _envelope(
            ok=False,
            tool="list_review_findings",
            data={"error": f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}"},
            entity="finding",
        )
    valid_severities = {"all", *REVIEW_FINDING_SEVERITIES}
    if severity not in valid_severities:
        return _envelope(
            ok=False,
            tool="list_review_findings",
            data={"error": f"Invalid severity. Valid: {', '.join(sorted(valid_severities))}"},
            entity="finding",
        )
    try:
        normalized_review_mode = _normalize_review_mode(review_mode)
    except ValueError as exc:
        return _envelope(
            ok=False,
            tool="list_review_findings",
            data={"error": str(exc)},
            entity="finding",
        )
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        where_parts = ["task_ref = ?"]
        params: list[object] = [resolved_task_ref]
        if status != "all":
            where_parts.append("status = ?")
            params.append(status)
        if severity != "all":
            where_parts.append("severity = ?")
            params.append(severity)
        if normalized_review_mode == "branch":
            where_parts.append("(review_mode = 'branch' OR review_mode IS NULL)")
        elif normalized_review_mode in ("release_audit", "planning"):
            where_parts.append("review_mode = ?")
            params.append(normalized_review_mode)
        where_sql = " AND ".join(where_parts)
        findings_order = "CASE status WHEN 'open' THEN 0 WHEN 'deferred' THEN 1 WHEN 'fixed' THEN 2 WHEN 'wontfix' THEN 3 END, CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, COALESCE(updated_at, created_at) DESC, id DESC"
        total, raw_findings = _paginated_query(
            conn, "review_findings", where_sql, tuple(params), limit, offset, findings_order
        )
        status_counts = {key: 0 for key in sorted(REVIEW_FINDING_STATUSES)}
        for row in conn.execute(
            f"SELECT status, COUNT(*) AS count FROM review_findings WHERE {where_sql} GROUP BY status", tuple(params)
        ).fetchall():
            status_counts[str(row["status"])] = int(row["count"])
        severity_counts = {key: 0 for key in sorted(REVIEW_FINDING_SEVERITIES)}
        for row in conn.execute(
            f"SELECT severity, COUNT(*) AS count FROM review_findings WHERE {where_sql} GROUP BY severity",
            tuple(params),
        ).fetchall():
            severity_counts[str(row["severity"])] = int(row["count"])
    workspace_git = _workspace_git_context()
    findings = [
        _apply_finding_detail(
            _annotate_review_finding(
                row,
                workspace_branch=workspace_git["branch"],
                workspace_commit_sha=workspace_git["commit_sha"],
            )
        )
        for row in raw_findings
    ]
    return _envelope(
        ok=True,
        tool="list_review_findings",
        data={
            "task_ref": resolved_task_ref,
            "workspace_git": workspace_git,
            "filters": {
                "status": status,
                "severity": severity,
                "review_mode": normalized_review_mode,
                "limit": limit,
                "offset": offset,
            },
            "total_matching": total,
            "returned": len(findings),
            "has_more": (offset + len(findings)) < total,
            "counts": {"status": status_counts, "severity": severity_counts},
            "findings": findings,
        },
        task_ref=resolved_task_ref,
        entity="finding",
    )


def get_review_findings_summary(
    task_ref: str | None = None,
    top_n_open: int = 5,
    top_n_recent_updates: int = 3,
    review_mode: str | None = None,
) -> dict:
    top_n_open = max(1, top_n_open)
    top_n_recent_updates = max(1, top_n_recent_updates)
    try:
        normalized_review_mode = _normalize_review_mode(review_mode)
    except ValueError as exc:
        return _json_response({"ok": False, "error": str(exc)})
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        where_parts = ["task_ref = ?"]
        params: list[object] = [resolved_task_ref]
        if normalized_review_mode == "branch":
            where_parts.append("(review_mode = 'branch' OR review_mode IS NULL)")
        elif normalized_review_mode in ("release_audit", "planning"):
            where_parts.append("review_mode = ?")
            params.append(normalized_review_mode)
        where_sql = " AND ".join(where_parts)
        total_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM review_findings WHERE {where_sql}", tuple(params)
        ).fetchone()
        status_counts = {key: 0 for key in sorted(REVIEW_FINDING_STATUSES)}
        for row in conn.execute(
            f"SELECT status, COUNT(*) AS count FROM review_findings WHERE {where_sql} GROUP BY status", tuple(params)
        ).fetchall():
            status_counts[str(row["status"])] = int(row["count"])
        severity_counts = {key: 0 for key in sorted(REVIEW_FINDING_SEVERITIES)}
        for row in conn.execute(
            f"SELECT severity, COUNT(*) AS count FROM review_findings WHERE {where_sql} GROUP BY severity",
            tuple(params),
        ).fetchall():
            severity_counts[str(row["severity"])] = int(row["count"])
        raw_open_findings = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM review_findings WHERE {where_sql} AND status = 'open' ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, COALESCE(updated_at, created_at) DESC, id DESC LIMIT ?",
                (*params, top_n_open),
            ).fetchall()
        ]
        raw_recent_updates = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM review_findings WHERE {where_sql} ORDER BY COALESCE(updated_at, resolved_at, created_at) DESC, id DESC LIMIT ?",
                (*params, top_n_recent_updates),
            ).fetchall()
        ]
    workspace_git = _workspace_git_context()
    open_findings = [
        _annotate_review_finding(
            row, workspace_branch=workspace_git["branch"], workspace_commit_sha=workspace_git["commit_sha"]
        )
        for row in raw_open_findings
    ]
    recent_updates = [
        _annotate_review_finding(
            row, workspace_branch=workspace_git["branch"], workspace_commit_sha=workspace_git["commit_sha"]
        )
        for row in raw_recent_updates
    ]
    return _json_response(
        {
            "ok": True,
            "task_ref": resolved_task_ref,
            "workspace_git": workspace_git,
            "review_mode": normalized_review_mode,
            "counts": {
                "total": int(total_row["total"]) if total_row else 0,
                "status": status_counts,
                "severity": severity_counts,
            },
            "open_top": open_findings,
            "recent_updates": recent_updates,
            "limits": {"top_n_open": top_n_open, "top_n_recent_updates": top_n_recent_updates},
        }
    )


def _collect_review_findings_integrity(conn: sqlite3.Connection, task_ref: str, *, apply: bool = False) -> dict:
    duplicate_rows = conn.execute(
        """
        SELECT finding_id, COUNT(*) AS count
        FROM review_findings
        WHERE task_ref = ?
        GROUP BY finding_id
        HAVING COUNT(*) > 1
        ORDER BY count DESC, finding_id ASC
        """,
        (task_ref,),
    ).fetchall()
    duplicates = [{"finding_id": row["finding_id"], "count": int(row["count"])} for row in duplicate_rows]
    deduped_rows_removed = 0
    if apply and duplicates:
        deduped_rows_removed = _dedupe_review_findings(conn, task_ref)
        duplicate_rows = conn.execute(
            """
            SELECT finding_id, COUNT(*) AS count
            FROM review_findings
            WHERE task_ref = ?
            GROUP BY finding_id
            HAVING COUNT(*) > 1
            ORDER BY count DESC, finding_id ASC
            """,
            (task_ref,),
        ).fetchall()
        duplicates = [{"finding_id": row["finding_id"], "count": int(row["count"])} for row in duplicate_rows]
    open_count = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM review_findings WHERE task_ref = ? AND status = 'open'", (task_ref,)
        ).fetchone()["count"]
    )
    active_row = conn.execute("SELECT task_ref, status FROM handoff_state WHERE id = 1").fetchone()
    active_status = (
        str(active_row["status"]) if active_row is not None and str(active_row["task_ref"]) == task_ref else None
    )
    done_with_open_findings = bool(active_status == "done" and open_count > 0)
    stale_open_findings = []
    for row in conn.execute(
        "SELECT id, finding_id, file_path, created_at, updated_at FROM review_findings WHERE task_ref = ? AND status = 'open' ORDER BY COALESCE(updated_at, created_at) DESC, id DESC",
        (task_ref,),
    ).fetchall():
        raw_file_path = str(row["file_path"])
        path = Path(raw_file_path)
        if not path.is_absolute():
            path = _workspace_root() / raw_file_path
        if not path.exists():
            continue
        activity_dt = _parse_sqlite_datetime(row["updated_at"]) or _parse_sqlite_datetime(row["created_at"])
        if activity_dt is None:
            continue
        from datetime import UTC, datetime  # noqa: PLC0415

        file_modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if file_modified_at > activity_dt:
            stale_open_findings.append(
                {
                    "id": int(row["id"]),
                    "finding_id": str(row["finding_id"]),
                    "file_path": raw_file_path,
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]) if row["updated_at"] is not None else None,
                    "file_modified_at": file_modified_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
    missing_provenance = [
        {
            "id": int(row["id"]),
            "finding_id": str(row["finding_id"]),
            "agent": row["agent"],
            "branch": row["branch"],
            "commit_sha": row["commit_sha"],
        }
        for row in conn.execute(
            "SELECT id, finding_id, agent, branch, commit_sha FROM review_findings WHERE task_ref = ? AND (agent IS NULL OR TRIM(agent) = '' OR branch IS NULL OR TRIM(branch) = '') ORDER BY id DESC",
            (task_ref,),
        ).fetchall()
    ]
    reopen_metadata = [
        {
            "id": int(row["id"]),
            "finding_id": str(row["finding_id"]),
            "reopen_count": int(row["reopen_count"]),
            "last_reopen_reason": row["last_reopen_reason"],
            "last_reopened_at": row["last_reopened_at"],
        }
        for row in conn.execute(
            "SELECT id, finding_id, reopen_count, last_reopen_reason, last_reopened_at FROM review_findings WHERE task_ref = ? AND COALESCE(reopen_count, 0) > 0 AND (last_reopen_reason IS NULL OR TRIM(last_reopen_reason) = '' OR last_reopened_at IS NULL OR TRIM(last_reopened_at) = '') ORDER BY id DESC",
            (task_ref,),
        ).fetchall()
    ]
    healthy = (
        len(duplicates) == 0
        and not done_with_open_findings
        and len(stale_open_findings) == 0
        and len(missing_provenance) == 0
        and len(reopen_metadata) == 0
    )
    return {
        "healthy": healthy,
        "checks": {
            "duplicates": {"count": len(duplicates), "items": duplicates, "deduped_rows_removed": deduped_rows_removed},
            "done_with_open_findings": {
                "active_status": active_status,
                "open_count": open_count,
                "is_violation": done_with_open_findings,
            },
            "stale_open_findings": {"count": len(stale_open_findings), "items": stale_open_findings},
            "missing_provenance": {"count": len(missing_provenance), "items": missing_provenance},
            "reopen_metadata": {"count": len(reopen_metadata), "items": reopen_metadata},
        },
    }


def reconcile_review_findings(task_ref: str | None = None, apply: bool = False) -> dict:
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        report = _collect_review_findings_integrity(conn, resolved_task_ref, apply=apply)
        if (
            apply
            and int(report["checks"]["duplicates"]["deduped_rows_removed"]) > 0
            and report["checks"]["done_with_open_findings"]["active_status"] is not None
        ):
            _write_current_task_md_for_active_context(conn, resolved_task_ref)
    return _json_response(
        {"ok": True, "task_ref": resolved_task_ref, "healthy": report["healthy"], "checks": report["checks"]}
    )


# ---------------------------------------------------------------------------
# Review-run ledger
# ---------------------------------------------------------------------------

_REVIEW_RUN_VERDICTS: frozenset[str] = frozenset({"pass", "pass_with_findings", "fail", "conditional_pass"})
_REVIEW_RUN_SUBJECT_KINDS: frozenset[str] = frozenset({"task_plan", "epic", "branch", "adr", "roadmap", "other"})


def record_review_run(
    review_run_id: str,
    session: str,
    subject_path: str,
    subject_kind: str = "task_plan",
    review_mode: str = "planning",
    verdict: str | None = None,
    verdict_decision: str | None = None,
    task_ref: str | None = None,
    actor: WriteActor | None = None,
) -> dict:
    """Record a completed review pass in the review_runs ledger.

    ``review_run_id`` must be globally unique; the caller is responsible for
    constructing a stable id such as ``"<task_ref>-review-<n>"``.
    ``subject_path`` is the workspace-relative path of the artifact reviewed.
    ``verdict`` is optional at record time and can be updated later.
    """
    review_run_id = (review_run_id or "").strip()
    session = (session or "").strip()
    subject_path = (subject_path or "").strip()
    if not review_run_id:
        return _envelope(
            ok=False,
            tool="record_review_run",
            data={"error": "review_run_id is required."},
            entity="review_run",
        )
    if not session:
        return _envelope(
            ok=False,
            tool="record_review_run",
            data={"error": "session is required."},
            entity="review_run",
        )
    if not subject_path:
        return _envelope(
            ok=False,
            tool="record_review_run",
            data={"error": "subject_path is required."},
            entity="review_run",
        )
    if subject_kind not in _REVIEW_RUN_SUBJECT_KINDS:
        return _envelope(
            ok=False,
            tool="record_review_run",
            data={
                "error": f"Invalid subject_kind '{subject_kind}'. Valid: {', '.join(sorted(_REVIEW_RUN_SUBJECT_KINDS))}",
            },
            entity="review_run",
        )
    try:
        normalized_review_mode = _normalize_review_mode(review_mode)
    except ValueError as exc:
        return _envelope(
            ok=False,
            tool="record_review_run",
            data={"error": str(exc)},
            entity="review_run",
        )
    if verdict is not None and verdict not in _REVIEW_RUN_VERDICTS:
        return _envelope(
            ok=False,
            tool="record_review_run",
            data={"error": f"Invalid verdict '{verdict}'. Valid: {', '.join(sorted(_REVIEW_RUN_VERDICTS))}"},
            entity="review_run",
        )
    with _get_db_connection() as conn:
        resolved_actor = _resolve_write_actor(conn, actor)
        resolved_task_ref = task_ref
        if resolved_task_ref is None:
            active_row = conn.execute("SELECT task_ref FROM handoff_state WHERE id = 1").fetchone()
            if active_row is not None and active_row["task_ref"]:
                resolved_task_ref = str(active_row["task_ref"])
        existing = conn.execute("SELECT id FROM review_runs WHERE review_run_id = ?", (review_run_id,)).fetchone()
        if existing is not None:
            return _envelope(
                ok=False,
                tool="record_review_run",
                data={
                    "error": f"review_run_id '{review_run_id}' already exists (id={existing['id']}). Use a unique id for each run.",
                },
                task_ref=resolved_task_ref,
                entity="review_run",
            )
        conn.execute(
            """
            INSERT INTO review_runs (
                review_run_id, task_ref, subject_path, subject_kind, review_mode,
                verdict_decision, verdict, session, agent, model, model_label,
                branch, commit_sha
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_run_id,
                resolved_task_ref,
                subject_path,
                subject_kind,
                normalized_review_mode,
                verdict_decision,
                verdict,
                session,
                resolved_actor.agent,
                resolved_actor.model,
                resolved_actor.model_label,
                resolved_actor.branch,
                resolved_actor.commit_sha,
            ),
        )
        row = dict(conn.execute("SELECT * FROM review_runs WHERE review_run_id = ?", (review_run_id,)).fetchone())
        task_revision = _current_task_revision(conn, resolved_task_ref) if resolved_task_ref is not None else None
    return _envelope(
        ok=True,
        tool="record_review_run",
        data={"review_run": row},
        task_ref=resolved_task_ref,
        entity="review_run",
        mutation={
            "entity": "review_run",
            "operation": "insert",
            "affected_ids": [review_run_id],
            "task_revision": task_revision,
        },
    )


def list_review_runs(
    task_ref: str | None = None,
    subject_path: str | None = None,
    limit: int = 20,
    offset: int = 0,
    review_mode: str | None = None,
    verdict: str | None = None,
) -> dict:
    """List review-run ledger entries, optionally filtered by task_ref, subject_path,
    review_mode, or verdict.  At least one filter is recommended; an empty filter
    returns all runs ordered by recency."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    if verdict is not None and verdict not in _REVIEW_RUN_VERDICTS:
        return _envelope(
            ok=False,
            tool="list_review_runs",
            data={"error": f"Invalid verdict '{verdict}'. Valid: {', '.join(sorted(_REVIEW_RUN_VERDICTS))}"},
            entity="review_run",
        )
    normalized_review_mode: str | None = None
    if review_mode is not None:
        try:
            normalized_review_mode = _normalize_review_mode(review_mode)
        except ValueError as exc:
            return _envelope(
                ok=False,
                tool="list_review_runs",
                data={"error": str(exc)},
                entity="review_run",
            )
    with _get_db_connection() as conn:
        where_parts: list[str] = []
        params: list[object] = []
        if task_ref is not None:
            where_parts.append("task_ref = ?")
            params.append(task_ref)
        if subject_path is not None:
            where_parts.append("subject_path = ?")
            params.append(subject_path)
        if normalized_review_mode is not None:
            where_parts.append("review_mode = ?")
            params.append(normalized_review_mode)
        if verdict is not None:
            where_parts.append("verdict = ?")
            params.append(verdict)
        where_sql = " AND ".join(where_parts) if where_parts else "1=1"
        total, raw_runs = _paginated_query(
            conn, "review_runs", where_sql, tuple(params), limit, offset, "reviewed_at DESC, id DESC"
        )
    runs = raw_runs
    return _envelope(
        ok=True,
        tool="list_review_runs",
        data={
            "filters": {
                "task_ref": task_ref,
                "subject_path": subject_path,
                "review_mode": normalized_review_mode,
                "verdict": verdict,
                "limit": limit,
                "offset": offset,
            },
            "total_matching": total,
            "returned": len(runs),
            "has_more": (offset + len(runs)) < total,
            "runs": runs,
        },
        task_ref=task_ref,
        entity="review_run",
    )


def get_review_coverage(
    task_ref: str | None = None,
    subject_path: str | None = None,
) -> dict:
    """Return a review-coverage summary for a task or subject artifact.

    Provide ``task_ref``, ``subject_path``, or both.  When both are given,
    ``task_ref`` scopes the finding counts and ``subject_path`` scopes the
    run query.  When only ``subject_path`` is given, finding counts are
    derived from the matched run ids.
    """
    if task_ref is None and subject_path is None:
        return _envelope(
            ok=False,
            tool="get_review_coverage",
            data={"error": "Provide at least one of task_ref or subject_path."},
            entity="review_coverage",
        )
    with _get_db_connection() as conn:
        payload = _collect_review_coverage(conn, task_ref=task_ref, subject_path=subject_path)
    is_ok = bool(payload.get("ok", False))
    # Remove 'ok' from payload since _envelope handles it at the envelope level.
    data = {k: v for k, v in payload.items() if k != "ok"}
    return _envelope(
        ok=is_ok,
        tool="get_review_coverage",
        data=data,
        task_ref=task_ref,
        entity="review_coverage",
    )


def _collect_review_coverage(
    conn: sqlite3.Connection,
    *,
    task_ref: str | None = None,
    subject_path: str | None = None,
) -> dict[str, object]:
    if task_ref is None and subject_path is None:
        return {"ok": False, "error": "Provide at least one of task_ref or subject_path."}

    run_where_parts: list[str] = []
    run_params: list[object] = []
    if task_ref is not None:
        run_where_parts.append("task_ref = ?")
        run_params.append(task_ref)
    if subject_path is not None:
        run_where_parts.append("subject_path = ?")
        run_params.append(subject_path)
    run_where_sql = " AND ".join(run_where_parts)
    runs = [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM review_runs WHERE {run_where_sql} ORDER BY reviewed_at DESC, id DESC",
            tuple(run_params),
        ).fetchall()
    ]
    run_count = len(runs)
    latest_run = runs[0] if runs else None
    latest_verdict = latest_run["verdict"] if latest_run else None
    latest_review_run_id = latest_run["review_run_id"] if latest_run else None
    recent_run_ids = [r["review_run_id"] for r in runs[:5]]

    open_severity_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    reopened_count = 0
    if task_ref is not None:
        for row in conn.execute(
            "SELECT severity, COUNT(*) AS cnt FROM review_findings WHERE task_ref = ? AND status = 'open' GROUP BY severity",
            (task_ref,),
        ).fetchall():
            open_severity_counts[str(row["severity"])] = int(row["cnt"])
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM review_findings WHERE task_ref = ? AND reopen_count > 0",
            (task_ref,),
        ).fetchone()
        reopened_count = int(row["cnt"]) if row else 0
    elif runs:
        run_ids = [r["review_run_id"] for r in runs]
        placeholders = ",".join("?" * len(run_ids))
        for row in conn.execute(
            f"SELECT severity, COUNT(*) AS cnt FROM review_findings WHERE review_run_id IN ({placeholders}) AND status = 'open' GROUP BY severity",
            tuple(run_ids),
        ).fetchall():
            open_severity_counts[str(row["severity"])] = int(row["cnt"])
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM review_findings WHERE review_run_id IN ({placeholders}) AND reopen_count > 0",
            tuple(run_ids),
        ).fetchone()
        reopened_count = int(row["cnt"]) if row else 0

    return {
        "ok": True,
        "task_ref": task_ref,
        "subject_path": subject_path,
        "run_count": run_count,
        "latest_review_run_id": latest_review_run_id,
        "latest_verdict": latest_verdict,
        "recent_run_ids": recent_run_ids,
        "open_findings_by_severity": open_severity_counts,
        "reopened_findings_count": reopened_count,
    }
