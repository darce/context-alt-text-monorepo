"""Record and merge operations for review findings."""

from __future__ import annotations

import json
import sqlite3
from typing import TypedDict, cast

from .enums import FindingStatus
from .shared_primitives import (
    REVIEW_FINDING_SEVERITIES,
    ReviewFindingDetails,
    _envelope,
    _parse_review_finding_details,
    _resolve_task_ref,
    _row_to_dict,
)
from .shared_schema import _get_db_connection
from .shared_write_context import WriteActor, _resolve_write_actor, collect_target_context_warnings
from .review_findings_support import (
    _auto_merge_session,
    _current_task_revision,
    _current_task_revision_for,
    _normalize_source_task_refs,
    _validate_review_mode_or_envelope,
    _write_current_task_md_for_active_context,
    cast_details,
)

_BATCH_MAX_SIZE = 100


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
    normalized_review_mode, error = _validate_review_mode_or_envelope(
        review_mode,
        tool="record_review_finding",
    )
    if error is not None:
        return error

    line_start, line_end, fix = _parse_review_finding_details(details)
    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        ctx = _resolve_write_actor(conn, actor)
        warnings = collect_target_context_warnings(conn, ctx, task_ref=resolved_task_ref)
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
        if existing is not None and str(existing["status"]) != FindingStatus.OPEN.value:
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
            warnings=warnings or None,
        )


class BatchFindingItem(TypedDict, total=False):
    finding_id: str
    severity: str
    file_path: str
    description: str
    review_mode: str | None
    details: ReviewFindingDetails | None
    merged_from_json: str | None


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

    for index, item in enumerate(findings):
        finding_id = item.get("finding_id")
        if not finding_id:
            return _envelope(
                ok=False,
                tool="batch_record_review_findings",
                data={"error": f"Item {index} is missing finding_id."},
                entity="finding",
            )
        severity = item.get("severity")
        if severity not in REVIEW_FINDING_SEVERITIES:
            return _envelope(
                ok=False,
                tool="batch_record_review_findings",
                data={
                    "error": f"Item {index} (finding_id={finding_id!r}): Invalid severity. Valid: {', '.join(sorted(REVIEW_FINDING_SEVERITIES))}",
                },
                entity="finding",
            )
        if not item.get("file_path"):
            return _envelope(
                ok=False,
                tool="batch_record_review_findings",
                data={"error": f"Item {index} (finding_id={finding_id!r}): missing file_path."},
                entity="finding",
            )
        if not item.get("description"):
            return _envelope(
                ok=False,
                tool="batch_record_review_findings",
                data={"error": f"Item {index} (finding_id={finding_id!r}): missing description."},
                entity="finding",
            )
        _, error = _validate_review_mode_or_envelope(
            item.get("review_mode"),
            tool="batch_record_review_findings",
        )
        if error is not None:
            return _envelope(
                ok=False,
                tool="batch_record_review_findings",
                data={"error": f"Item {index} (finding_id={finding_id!r}): {error['data']['error']}"},
                entity="finding",
            )

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        ctx = _resolve_write_actor(conn, actor)
        warnings = collect_target_context_warnings(conn, ctx, task_ref=resolved_task_ref)

        results: list[dict[str, object]] = []
        for item in findings:
            finding_id = item["finding_id"]
            severity = item["severity"]
            file_path = item["file_path"]
            description = item["description"]
            normalized_review_mode, _ = _validate_review_mode_or_envelope(
                item.get("review_mode"),
                tool="batch_record_review_findings",
            )
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
                    merged_from_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
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
                    commit_sha = COALESCE(review_findings.commit_sha, excluded.commit_sha),
                    merged_from_json = COALESCE(excluded.merged_from_json, review_findings.merged_from_json)
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
                    item.get("merged_from_json"),
                ),
            )

            item_result: dict[str, object] = {"finding_id": finding_id, "action": "inserted"}
            if existing is not None:
                item_result["action"] = "updated"
                if str(existing["status"]) != FindingStatus.OPEN.value:
                    item_result["reopened"] = True
            results.append(item_result)

        _write_current_task_md_for_active_context(conn, resolved_task_ref)
        task_revision = _current_task_revision(conn, resolved_task_ref)

    affected_ids = [item["finding_id"] for item in findings]
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
        warnings=warnings or None,
    )


def merge_review_findings(
    session: str | None,
    source_task_refs: list[str],
    target_task_ref: str,
    actor: WriteActor | None = None,
) -> dict:
    """Merge source task_refs' review findings into a coordinator target task_ref."""
    clean_sources = _normalize_source_task_refs(source_task_refs)
    if not clean_sources:
        return _envelope(
            ok=False,
            tool="merge_review_findings",
            data={"error": "source_task_refs must be a non-empty list of task_ref strings."},
            entity="finding",
        )
    if not isinstance(target_task_ref, str) or not target_task_ref.strip():
        return _envelope(
            ok=False,
            tool="merge_review_findings",
            data={"error": "target_task_ref must be a non-empty string."},
            entity="finding",
        )
    target = target_task_ref.strip()
    if target in set(clean_sources):
        return _envelope(
            ok=False,
            tool="merge_review_findings",
            data={"error": "target_task_ref must not appear in source_task_refs."},
            entity="finding",
        )
    effective_session = session.strip() if isinstance(session, str) and session.strip() else _auto_merge_session(target)

    placeholders = ",".join(["?"] * len(clean_sources))
    with _get_db_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT task_ref, session, finding_id, severity, file_path,
                   line_start, line_end, description, fix, review_mode
            FROM review_findings
            WHERE task_ref IN ({placeholders})
            ORDER BY task_ref, id
            """,
            tuple(clean_sources),
        ).fetchall()

    if not rows:
        return _envelope(
            ok=False,
            tool="merge_review_findings",
            data={
                "error": "no findings available to merge from the given source_task_refs.",
                "source_task_refs": clean_sources,
            },
            entity="finding",
        )

    items: list[BatchFindingItem] = []
    for row in rows:
        source_triple = {
            "task_ref": str(row["task_ref"]),
            "session": str(row["session"]),
            "finding_id": str(row["finding_id"]),
        }
        details_payload: ReviewFindingDetails | None = None
        if row["line_start"] is not None or row["line_end"] is not None or row["fix"] is not None:
            details_payload = cast_details(line_start=row["line_start"], line_end=row["line_end"], fix=row["fix"])
        items.append(
            {
                "finding_id": str(row["finding_id"]),
                "severity": str(row["severity"]),
                "file_path": str(row["file_path"]),
                "description": str(row["description"]),
                "review_mode": str(row["review_mode"]) if row["review_mode"] else None,
                "details": details_payload,
                "merged_from_json": json.dumps(source_triple, sort_keys=True),
            }
        )

    result = batch_record_review_findings(
        session=effective_session,
        findings=items,
        actor=actor,
        task_ref=target,
    )
    if not isinstance(result, dict) or not result.get("ok"):
        return result

    envelope_data = result.get("data", result)
    return _envelope(
        ok=True,
        tool="merge_review_findings",
        data={
            "task_ref": target,
            "session": effective_session,
            "source_task_refs": clean_sources,
            "written": envelope_data.get("written", len(items)),
            "results": envelope_data.get("results", []),
        },
        task_ref=target,
        entity="finding",
        mutation={
            "entity": "finding",
            "operation": "merge",
            "affected_ids": [item["finding_id"] for item in items],
            "task_revision": _current_task_revision_for(target),
        },
        warnings=result.get("warnings"),
    )