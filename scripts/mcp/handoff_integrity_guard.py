#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

from workbay_handoff_mcp import (
    RuntimeConfig,
    archive_task_state,
    configure_runtime,
    get_handoff_state,
    handoff_close_check,
    import_handoff_state,
    render_handoff,
    review_findings,
    set_handoff_state,
    update_task_status,
)


def _error(payload: dict) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return str(data.get("error") or payload.get("error") or payload)


def _require_ok(payload: dict, label: str) -> dict:
    if not payload.get("ok"):
        raise RuntimeError(f"{label} failed: {_error(payload)}")
    return payload


def _require_not_ok(payload: dict, label: str) -> dict:
    if payload.get("ok"):
        raise RuntimeError(f"{label} unexpectedly succeeded: {payload}")
    return payload


def _close_data(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _active_revision(payload: dict) -> int:
    active = payload.get("active")
    if not isinstance(active, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            active = data.get("active")
    if not isinstance(active, dict):
        raise RuntimeError(f"Could not read active state from payload: {payload}")
    revision = int(active.get("revision", -1))
    if revision < 0:
        raise RuntimeError(f"Could not read revision from payload: {payload}")
    return revision


def _open_findings(payload: dict) -> list[dict]:
    findings = payload.get("findings")
    if findings is None and isinstance(payload.get("data"), dict):
        findings = payload["data"].get("findings")
    if not isinstance(findings, list):
        raise RuntimeError(f"Could not read findings from payload: {payload}")
    return findings


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="handoff-integrity-") as temp_dir:
        temp_root = Path(temp_dir)
        configure_runtime(RuntimeConfig.for_workspace(temp_root))

        task_ref = f"ci-handoff-{uuid.uuid4().hex[:8]}"
        session = "ci-handoff-guard"
        finding_id = "CI-H-1"

        _require_ok(
            set_handoff_state(task_ref=task_ref, objective="CI handoff integrity guard", status="in_progress"),
            "set handoff state",
        )
        _require_ok(
            review_findings(
                review={
                    "operation": "record",
                    "task_ref": task_ref,
                    "session": session,
                    "finding_id": finding_id,
                    "severity": "low",
                    "file_path": "scripts/mcp/handoff_integrity_guard.py",
                    "description": "CI guard lifecycle smoke finding",
                }
            ),
            "record review finding",
        )
        _require_ok(
            review_findings(
                review={
                    "operation": "update",
                    "task_ref": task_ref,
                    "finding_id": finding_id,
                    "status": "fixed",
                    "session": session,
                }
            ),
            "mark finding fixed",
        )

        missing_notes = _require_not_ok(
            review_findings(
                review={
                    "operation": "update",
                    "task_ref": task_ref,
                    "finding_id": finding_id,
                    "status": "deferred",
                    "session": session,
                }
            ),
            "defer finding without notes",
        )
        if "resolution_notes" not in _error(missing_notes):
            raise RuntimeError(f"Deferred-without-notes failure missing explanation: {missing_notes}")

        _require_ok(
            review_findings(
                review={
                    "operation": "update",
                    "task_ref": task_ref,
                    "finding_id": finding_id,
                    "status": "deferred",
                    "resolution_notes": "Deferred for CI parser smoke validation.",
                    "session": session,
                }
            ),
            "defer finding with notes",
        )

        missing_wontfix_notes = _require_not_ok(
            review_findings(
                review={
                    "operation": "update",
                    "task_ref": task_ref,
                    "finding_id": finding_id,
                    "status": "wontfix",
                    "session": session,
                }
            ),
            "wontfix finding without notes",
        )
        if "resolution_notes" not in _error(missing_wontfix_notes):
            raise RuntimeError(f"Wontfix-without-notes failure missing explanation: {missing_wontfix_notes}")

        _require_ok(
            review_findings(
                review={
                    "operation": "update",
                    "task_ref": task_ref,
                    "finding_id": finding_id,
                    "status": "wontfix",
                    "resolution_notes": "Wontfix for CI parser smoke validation.",
                    "session": session,
                }
            ),
            "wontfix finding with notes",
        )

        missing_reopen_reason = _require_not_ok(
            review_findings(
                review={
                    "operation": "update",
                    "task_ref": task_ref,
                    "finding_id": finding_id,
                    "status": "open",
                    "session": session,
                }
            ),
            "reopen finding without reason",
        )
        if "reopen_reason" not in _error(missing_reopen_reason):
            raise RuntimeError(f"Reopen-without-reason failure missing explanation: {missing_reopen_reason}")

        _require_ok(
            review_findings(
                review={
                    "operation": "update",
                    "task_ref": task_ref,
                    "finding_id": finding_id,
                    "status": "open",
                    "reopen_reason": "Reopened after deferred status while CI lifecycle continues.",
                    "session": session,
                }
            ),
            "reopen finding with reason",
        )

        open_findings = _require_ok(
            review_findings(
                review={
                    "operation": "list",
                    "task_ref": task_ref,
                    "status": "open",
                }
            ),
            "list open findings",
        )
        finding_row = (_open_findings(open_findings) or [None])[0]
        if not finding_row:
            raise RuntimeError(f"Expected open finding row after reopen, got: {open_findings}")
        if int(finding_row.get("reopen_count") or 0) < 1:
            raise RuntimeError(f"Expected reopen_count >= 1 after reopen, got: {finding_row}")
        if not finding_row.get("last_reopen_reason"):
            raise RuntimeError(f"Expected last_reopen_reason after reopen, got: {finding_row}")

        not_ready = _require_not_ok(
            handoff_close_check(task_ref=task_ref, enforce=True),
            "close check while finding remains open",
        )
        if _close_data(not_ready).get("ready_to_close", True):
            raise RuntimeError(f"Close check should fail while finding is open: {not_ready}")

        _require_ok(
            review_findings(
                review={
                    "operation": "update",
                    "task_ref": task_ref,
                    "finding_id": finding_id,
                    "status": "fixed",
                    "session": session,
                }
            ),
            "mark finding fixed after reopen",
        )

        state = _require_ok(get_handoff_state(task_ref=task_ref), "get handoff state")
        revision = _active_revision(state)
        _require_ok(
            update_task_status(task_ref=task_ref, status="done", expected_revision=revision),
            "mark task done",
        )
        _require_ok(render_handoff(kind="current_task", task_ref=task_ref), "render current task")

        ready = _require_ok(handoff_close_check(task_ref=task_ref, enforce=True), "close check after cleanup")
        if _close_data(ready).get("ready_to_close") is not True:
            raise RuntimeError(f"Expected close check to pass, got: {ready}")

        destructive_task_ref = f"ci-destructive-{uuid.uuid4().hex[:8]}"
        destructive_finding_id = "CI-H-CLEAR-1"
        _require_ok(
            set_handoff_state(
                task_ref=destructive_task_ref,
                objective="CI destructive clear safeguards",
                status="in_progress",
            ),
            "set destructive clear task",
        )
        _require_ok(
            review_findings(
                review={
                    "operation": "record",
                    "task_ref": destructive_task_ref,
                    "session": session,
                    "finding_id": destructive_finding_id,
                    "severity": "low",
                    "file_path": "scripts/mcp/handoff_integrity_guard.py",
                    "description": "CI destructive clear safeguard finding",
                }
            ),
            "record destructive clear finding",
        )

        destructive_payload_path = temp_root / "destructive-clear-payload.json"
        destructive_payload_path.write_text(
            json.dumps(
                {
                    "export_version": 1,
                    "task_ref": destructive_task_ref,
                    "snapshot": {
                        "task_ref": destructive_task_ref,
                        "active": {
                            "task_ref": destructive_task_ref,
                            "objective": "CI destructive clear safeguards",
                            "status": "in_progress",
                        },
                        "blockers": [],
                        "next_actions": [],
                        "decisions": [],
                        "verified_tests": [],
                        "review_findings": [],
                        "worktree_lanes": [],
                        "worker_reports": [],
                        "lane_messages": [],
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        blocked_replace = _require_not_ok(
            import_handoff_state(input_path=str(destructive_payload_path), mode="replace_task"),
            "replace_task import without destructive clear ack",
        )
        if "allow_destructive_clear" not in _error(blocked_replace):
            raise RuntimeError(f"Expected replace_task failure to mention allow_destructive_clear: {blocked_replace}")

        blocked_prune = _require_not_ok(
            archive_task_state(task_ref=destructive_task_ref, prune_working_rows=True),
            "archive prune without destructive clear ack",
        )
        if "allow_destructive_clear" not in _error(blocked_prune):
            raise RuntimeError(f"Expected prune failure to mention allow_destructive_clear: {blocked_prune}")

        finding_still_present = _require_ok(
            review_findings(
                review={
                    "operation": "list",
                    "task_ref": destructive_task_ref,
                    "status": "open",
                }
            ),
            "list destructive clear findings before ack",
        )
        if len(_open_findings(finding_still_present)) != 1:
            raise RuntimeError(
                f"Expected finding to remain after blocked destructive operations, got: {finding_still_present}"
            )

        _require_ok(
            import_handoff_state(
                input_path=str(destructive_payload_path),
                mode="replace_task",
                allow_destructive_clear=True,
            ),
            "replace_task import with destructive clear ack",
        )
        finding_cleared_after_ack = _require_ok(
            review_findings(
                review={
                    "operation": "list",
                    "task_ref": destructive_task_ref,
                    "status": "open",
                }
            ),
            "list destructive clear findings after ack",
        )
        if _open_findings(finding_cleared_after_ack):
            raise RuntimeError(
                f"Expected acknowledged destructive replace to clear finding rows, got: {finding_cleared_after_ack}"
            )

    print("handoff-integrity-guard: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())