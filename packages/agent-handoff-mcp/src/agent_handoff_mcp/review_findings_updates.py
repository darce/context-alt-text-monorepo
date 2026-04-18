"""Update and provenance-repair operations for review findings."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from . import shared_write_context as _shared_write_context
from .enums import FindingStatus
from .shared_primitives import (
    BATCH_CLOSE_THRESHOLD,
    BATCH_CLOSE_WINDOW_SECONDS,
    MAX_REOPEN_REASON_LENGTH,
    MAX_RESOLUTION_NOTES_LENGTH,
    MAX_VERIFICATION_EVIDENCE_LENGTH,
    REOPEN_ESCALATION_THRESHOLD,
    REVIEW_FINDING_STATUSES,
    _envelope,
    _normalize_optional_text,
    _resolve_task_ref,
    _row_to_dict,
)
from .shared_schema import _get_db_connection
from .shared_write_context import (
    InvalidCommitShaError,
    ResolvedWriteContext,
    WriteActor,
    _resolve_write_actor,
    collect_target_context_warnings,
)
from .review_findings_support import (
    _canonical_repair_provenance_decision_id,
    _classify_commit_relation,
    _current_task_revision,
    _write_current_task_md_for_active_context,
)

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class FindingUpdateInput:
    status: FindingStatus
    resolution_notes: str | None
    reopen_reason: str | None
    verified_commit_sha: str | None
    verification_evidence: str | None
    is_reopen_transition: bool


@dataclass(frozen=True)
class FindingUpdateContext:
    conn: sqlite3.Connection
    existing: sqlite3.Row
    ctx: ResolvedWriteContext
    session: str | None
    task_ref: str
    warnings: list[str] | None = None


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


def _apply_finding_update(update_ctx: FindingUpdateContext, update_input: FindingUpdateInput) -> dict:
    finding_commit_sha = _normalize_optional_text(update_ctx.existing["commit_sha"])
    current_commit_sha = _normalize_optional_text(update_ctx.ctx.commit_sha)
    commit_relation = _classify_commit_relation(finding_commit_sha, current_commit_sha)
    needs_descendant_ack = (
        update_input.status == FindingStatus.FIXED and commit_relation == "descendant"
    )
    target_db_id = int(update_ctx.existing["id"])
    reopen_transition_int = 1 if update_input.is_reopen_transition else 0
    update_ctx.conn.execute(
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
            update_input.status.value,
            update_input.status.value,
            update_ctx.ctx.agent,
            update_ctx.ctx.branch,
            update_ctx.ctx.commit_sha,
            update_ctx.ctx.lane_id,
            update_ctx.session,
            update_input.status.value,
            update_input.resolution_notes,
            update_input.resolution_notes,
            update_input.status.value,
            reopen_transition_int,
            reopen_transition_int,
            update_input.reopen_reason,
            reopen_transition_int,
            update_input.status.value,
            update_input.verification_evidence,
            update_input.verification_evidence,
            target_db_id,
            update_ctx.task_ref,
        ),
    )
    row = update_ctx.conn.execute("SELECT * FROM review_findings WHERE id = ?", (target_db_id,)).fetchone()
    _write_current_task_md_for_active_context(update_ctx.conn, update_ctx.task_ref)
    data: dict[str, object] = {
        "finding": _row_to_dict(row),
        "commit_guard": {
            "finding_commit_sha": finding_commit_sha,
            "current_commit_sha": current_commit_sha,
            "current_branch": update_ctx.ctx.branch,
            "relation": commit_relation,
            "verified_commit_sha": update_input.verified_commit_sha,
            "required": needs_descendant_ack,
        },
    }
    if update_input.is_reopen_transition:
        data["reopened"] = True
        data["reopen_reason"] = update_input.reopen_reason
    if update_input.verification_evidence is not None:
        data["verification_evidence"] = update_input.verification_evidence
    finding_id_str = str(update_ctx.existing["finding_id"])
    task_revision = _current_task_revision(update_ctx.conn, update_ctx.task_ref)
    return _envelope(
        ok=True,
        tool="update_review_finding",
        data=data,
        task_ref=update_ctx.task_ref,
        entity="finding",
        mutation={
            "entity": "finding",
            "operation": "update",
            "affected_ids": [finding_id_str],
            "task_revision": task_revision,
        },
        warnings=update_ctx.warnings or None,
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
) -> tuple[FindingStatus | None, dict | None]:
    if (finding_id is None and finding_db_id is None) or (finding_id is not None and finding_db_id is not None):
        return None, {"ok": False, "error": "Pass exactly one of finding_id (preferred) or finding_db_id."}
    try:
        normalized_status = FindingStatus(status)
    except ValueError:
        return None, {
            "ok": False,
            "error": f"Invalid status. Valid: {', '.join(sorted(REVIEW_FINDING_STATUSES))}",
        }
    if normalized_finding_id == "":
        return None, {"ok": False, "error": "finding_id must not be empty."}
    if (
        normalized_verification_evidence is not None
        and len(normalized_verification_evidence) > MAX_VERIFICATION_EVIDENCE_LENGTH
    ):
        return None, {
            "ok": False,
            "error": f"verification_evidence must be <= {MAX_VERIFICATION_EVIDENCE_LENGTH} characters.",
        }
    if normalized_status is not FindingStatus.FIXED and normalized_verification_evidence is not None:
        return None, {"ok": False, "error": "verification_evidence is only supported when status='fixed'."}
    if normalized_status in {FindingStatus.WONTFIX, FindingStatus.DEFERRED} and normalized_resolution_notes is None:
        return None, {
            "ok": False,
            "error": f"resolution_notes is required when status is '{normalized_status.value}'.",
        }
    if normalized_status is FindingStatus.OPEN and normalized_resolution_notes is not None:
        return None, {
            "ok": False,
            "error": "resolution_notes is not supported for status='open'. Use reopen_reason when reopening.",
        }
    if normalized_resolution_notes is not None and len(normalized_resolution_notes) > MAX_RESOLUTION_NOTES_LENGTH:
        return None, {"ok": False, "error": f"resolution_notes must be <= {MAX_RESOLUTION_NOTES_LENGTH} characters."}
    if normalized_reopen_reason is not None and len(normalized_reopen_reason) > MAX_REOPEN_REASON_LENGTH:
        return None, {"ok": False, "error": f"reopen_reason must be <= {MAX_REOPEN_REASON_LENGTH} characters."}
    if normalized_status is not FindingStatus.FIXED and normalized_verified_commit_sha is not None:
        return None, {"ok": False, "error": "verified_commit_sha is only supported when status='fixed'."}
    return normalized_status, None


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
    try:
        normalized_verified_commit_sha = _shared_write_context._validate_and_expand_commit_sha(
            normalized_verified_commit_sha
        )
    except InvalidCommitShaError as exc:
        return _envelope(
            ok=False,
            tool="update_review_finding",
            data={"error": str(exc)},
            entity="finding",
        )
    normalized_verification_evidence = _normalize_optional_text(verification_evidence)
    normalized_status, input_error = _validate_update_finding_input(
        status,
        finding_id,
        finding_db_id,
        normalized_finding_id,
        normalized_resolution_notes,
        normalized_reopen_reason,
        normalized_verified_commit_sha,
        normalized_verification_evidence,
    )
    if input_error is not None or normalized_status is None:
        return _envelope(
            ok=False,
            tool="update_review_finding",
            data={"error": input_error["error"]},
            entity="finding",
        )

    with _get_db_connection() as conn:
        ctx = _resolve_write_actor(conn, actor)
        if task_ref is None:
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
                candidate_scopes = sorted({str(row["task_ref"]) for row in rows})
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

        warnings = list(collect_target_context_warnings(conn, ctx, task_ref=resolved_task_ref) or [])
        existing_status = FindingStatus(str(existing["status"]))
        is_reopen_transition = existing_status is not FindingStatus.OPEN and normalized_status is FindingStatus.OPEN
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

        if normalized_status is FindingStatus.FIXED:
            guard_error = _check_reopen_escalation_guard(existing, normalized_verification_evidence)
            if guard_error is not None:
                return _envelope(
                    ok=False,
                    tool="update_review_finding",
                    data={key: value for key, value in guard_error.items() if key != "ok"},
                    task_ref=resolved_task_ref,
                    entity="finding",
                )
            if normalized_verification_evidence is None:
                guard_error = _check_batch_close_guard(conn, resolved_task_ref, existing)
                if guard_error is not None:
                    return _envelope(
                        ok=False,
                        tool="update_review_finding",
                        data={key: value for key, value in guard_error.items() if key != "ok"},
                        task_ref=resolved_task_ref,
                        entity="finding",
                    )
            guard_error = _check_commit_relation_guard(
                existing,
                ctx.commit_sha,
                normalized_verified_commit_sha,
                ctx.branch,
                normalized_resolution_notes,
            )
            if guard_error is not None:
                return _envelope(
                    ok=False,
                    tool="update_review_finding",
                    data={key: value for key, value in guard_error.items() if key != "ok"},
                    task_ref=resolved_task_ref,
                    entity="finding",
                )

        return _apply_finding_update(
            FindingUpdateContext(
                conn=conn,
                existing=existing,
                ctx=ctx,
                session=session,
                task_ref=resolved_task_ref,
                warnings=warnings,
            ),
            FindingUpdateInput(
                status=normalized_status,
                resolution_notes=normalized_resolution_notes,
                reopen_reason=normalized_reopen_reason,
                verified_commit_sha=normalized_verified_commit_sha,
                verification_evidence=normalized_verification_evidence,
                is_reopen_transition=is_reopen_transition,
            ),
        )


def repair_review_finding_provenance(
    finding_id: str,
    expected_branch: str,
    expected_commit_sha: str,
    new_branch: str,
    new_commit_sha: str,
    reason: str,
    session: str,
    task_ref: str | None = None,
    actor: WriteActor | None = None,
) -> dict:
    normalized_finding_id = finding_id.strip() if isinstance(finding_id, str) else None
    if not normalized_finding_id:
        return _envelope(
            ok=False,
            tool="repair_review_finding_provenance",
            data={"error": "finding_id must not be empty."},
            entity="finding",
        )
    normalized_expected_branch = expected_branch.strip() if isinstance(expected_branch, str) else None
    normalized_expected_commit_sha = expected_commit_sha.strip() if isinstance(expected_commit_sha, str) else None
    normalized_new_branch = new_branch.strip() if isinstance(new_branch, str) else None
    normalized_new_commit_sha = new_commit_sha.strip() if isinstance(new_commit_sha, str) else None
    normalized_reason = reason.strip() if isinstance(reason, str) else None
    if not normalized_expected_branch:
        return _envelope(ok=False, tool="repair_review_finding_provenance", data={"error": "expected_branch must not be empty."}, entity="finding")
    if not normalized_expected_commit_sha:
        return _envelope(ok=False, tool="repair_review_finding_provenance", data={"error": "expected_commit_sha must not be empty."}, entity="finding")
    if not normalized_new_branch:
        return _envelope(ok=False, tool="repair_review_finding_provenance", data={"error": "new_branch must not be empty."}, entity="finding")
    if not normalized_new_commit_sha:
        return _envelope(ok=False, tool="repair_review_finding_provenance", data={"error": "new_commit_sha must not be empty."}, entity="finding")
    if not normalized_reason or len(normalized_reason) < 20:
        return _envelope(
            ok=False,
            tool="repair_review_finding_provenance",
            data={"error": "reason must be at least 20 characters; describe why the original attribution was wrong."},
            entity="finding",
        )

    try:
        expanded_new = _shared_write_context._validate_and_expand_commit_sha(normalized_new_commit_sha)
    except InvalidCommitShaError as exc:
        return _envelope(
            ok=False,
            tool="repair_review_finding_provenance",
            data={"error": str(exc)},
            entity="finding",
        )
    if expanded_new is None:
        return _envelope(
            ok=False,
            tool="repair_review_finding_provenance",
            data={"error": "new_commit_sha could not be resolved."},
            entity="finding",
        )
    normalized_new_commit_sha = expanded_new
    literal_expected_commit_sha = normalized_expected_commit_sha
    try:
        expanded_expected = _shared_write_context._validate_and_expand_commit_sha(normalized_expected_commit_sha)
        if expanded_expected is not None:
            normalized_expected_commit_sha = expanded_expected
    except InvalidCommitShaError as exc:
        _LOG.warning("repair_review_finding_provenance could not expand expected_commit_sha %s: %s", normalized_expected_commit_sha, exc)

    if (
        normalized_expected_branch == normalized_new_branch
        and normalized_expected_commit_sha == normalized_new_commit_sha
    ):
        return _envelope(
            ok=False,
            tool="repair_review_finding_provenance",
            data={"error": "expected and new branch+commit_sha are identical; nothing to repair."},
            entity="finding",
        )

    with _get_db_connection() as conn:
        if task_ref is None:
            rows = conn.execute(
                "SELECT * FROM review_findings WHERE finding_id = ?", (normalized_finding_id,)
            ).fetchall()
            if not rows:
                return _envelope(
                    ok=False,
                    tool="repair_review_finding_provenance",
                    data={"error": "Finding not found."},
                    entity="finding",
                )
            if len(rows) > 1:
                candidate_scopes = sorted({str(row["task_ref"]) for row in rows})
                return _envelope(
                    ok=False,
                    tool="repair_review_finding_provenance",
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
                "SELECT * FROM review_findings WHERE finding_id = ? AND task_ref = ?",
                (normalized_finding_id, resolved_task_ref),
            ).fetchone()
            if existing is None:
                return _envelope(
                    ok=False,
                    tool="repair_review_finding_provenance",
                    data={"error": "Finding not found for task."},
                    task_ref=resolved_task_ref,
                    entity="finding",
                )

        ctx = _resolve_write_actor(conn, actor)
        warnings = list(collect_target_context_warnings(conn, ctx, task_ref=resolved_task_ref) or [])

        existing_branch = _normalize_optional_text(existing["branch"])
        existing_commit_sha = _normalize_optional_text(existing["commit_sha"])
        if existing_branch != normalized_expected_branch:
            return _envelope(
                ok=False,
                tool="repair_review_finding_provenance",
                data={
                    "error": "expected_branch does not match the stored row.",
                    "expected_branch": normalized_expected_branch,
                    "actual_branch": existing_branch,
                },
                task_ref=resolved_task_ref,
                entity="finding",
            )

        existing_commit_sha_expanded = existing_commit_sha
        if existing_commit_sha:
            try:
                expanded_existing = _shared_write_context._validate_and_expand_commit_sha(existing_commit_sha)
                if expanded_existing is not None:
                    existing_commit_sha_expanded = expanded_existing
            except InvalidCommitShaError as exc:
                warnings.append(
                    f"stored commit_sha {existing_commit_sha!r} for finding {normalized_finding_id} could not be expanded during provenance repair: {exc}"
                )
                _LOG.warning(
                    "repair_review_finding_provenance could not expand stored commit_sha %s for %s: %s",
                    existing_commit_sha,
                    normalized_finding_id,
                    exc,
                )

        acceptable_existing = {existing_commit_sha, existing_commit_sha_expanded}
        acceptable_expected = {literal_expected_commit_sha, normalized_expected_commit_sha}
        if not (acceptable_expected & acceptable_existing):
            return _envelope(
                ok=False,
                tool="repair_review_finding_provenance",
                data={
                    "error": "expected_commit_sha does not match the stored row.",
                    "expected_commit_sha": normalized_expected_commit_sha,
                    "actual_commit_sha": existing_commit_sha,
                },
                task_ref=resolved_task_ref,
                entity="finding",
            )

        target_db_id = int(existing["id"])
        before = {
            "branch": existing_branch,
            "commit_sha": existing_commit_sha,
        }
        after = {
            "branch": normalized_new_branch,
            "commit_sha": normalized_new_commit_sha,
        }

        conn.execute(
            """
            UPDATE review_findings
            SET branch = ?,
                commit_sha = ?,
                updated_at = datetime('now')
            WHERE id = ? AND task_ref = ?
            """,
            (
                normalized_new_branch,
                normalized_new_commit_sha,
                target_db_id,
                resolved_task_ref,
            ),
        )

        audit_decision_id = _canonical_repair_provenance_decision_id(
            task_ref=resolved_task_ref,
            finding_id=normalized_finding_id,
            agent=ctx.agent,
        )
        audit_rationale = (
            f"Repaired source provenance on review finding `{normalized_finding_id}` "
            f"(row id={target_db_id}, task_ref={resolved_task_ref}).\n\n"
            f"**Before:** branch=`{before['branch']}`, commit_sha=`{before['commit_sha']}`\n"
            f"**After:**  branch=`{after['branch']}`,  commit_sha=`{after['commit_sha']}`\n\n"
            f"**Reason:** {normalized_reason}"
        )
        conn.execute(
            """
            INSERT INTO decisions (
                task_ref, session, decision, rationale, agent, branch, commit_sha, lane_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                resolved_task_ref,
                session,
                audit_decision_id,
                audit_rationale,
                ctx.agent,
                ctx.branch,
                ctx.commit_sha,
                ctx.lane_id,
            ),
        )
        audit_row_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        row = conn.execute("SELECT * FROM review_findings WHERE id = ?", (target_db_id,)).fetchone()
        _write_current_task_md_for_active_context(conn, resolved_task_ref)
        task_revision = _current_task_revision(conn, resolved_task_ref)

        return _envelope(
            ok=True,
            tool="repair_review_finding_provenance",
            data={
                "finding": _row_to_dict(row),
                "before": before,
                "after": after,
                "audit_decision_id": audit_decision_id,
                "audit_decision_db_id": audit_row_id,
            },
            task_ref=resolved_task_ref,
            entity="finding",
            mutation={
                "entity": "finding",
                "operation": "repair_provenance",
                "affected_ids": [normalized_finding_id],
                "task_revision": task_revision,
            },
            warnings=warnings or None,
        )