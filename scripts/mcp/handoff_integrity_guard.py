#!/usr/bin/env python3
"""Pre-merge guard for MCP handoff integrity behavior."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "scripts" / "mcp" / "unified_server.py"


def _run_cli(args: list[str], env: dict[str, str], expect_success: bool = True) -> dict:
    """Run the handoff CLI and parse JSON output."""
    proc = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload: dict = {}
    stdout = proc.stdout.strip()
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Non-JSON output for command {' '.join(args)}:\n{proc.stdout}\n{proc.stderr}"
            ) from exc

    if expect_success and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed unexpectedly ({' '.join(args)}):\n{proc.stdout}\n{proc.stderr}"
        )
    if not expect_success and proc.returncode == 0:
        raise RuntimeError(
            f"Command succeeded unexpectedly ({' '.join(args)}):\n{proc.stdout}\n{proc.stderr}"
        )
    return payload


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="handoff-integrity-") as temp_dir:
        temp_root = Path(temp_dir)
        env = os.environ.copy()
        env["MCP_HANDOFF_STATE_DIR"] = str(temp_root / ".task-state")
        env["MCP_HANDOFF_CURRENT_TASK_PATH"] = str(temp_root / "CURRENT_TASK.md")
        env["MCP_HANDOFF_EXPORTS_DIR"] = str(temp_root / ".task-state" / "exports")

        task_ref = f"ci-handoff-{uuid.uuid4().hex[:8]}"

        _run_cli(
            [
                "set",
                "--task_ref",
                task_ref,
                "--objective",
                "CI handoff integrity guard",
                "--status",
                "in_progress",
            ],
            env,
        )
        _run_cli(
            [
                "review-record",
                "--finding_id",
                "CI-H-1",
                "--file_path",
                "scripts/mcp/unified_server.py",
                "--description",
                "CI guard lifecycle smoke finding",
                "--severity",
                "low",
                "--session",
                "ci-handoff-guard",
            ],
            env,
        )
        _run_cli(
            [
                "review-update",
                "--finding_id",
                "CI-H-1",
                "--status",
                "fixed",
                "--session",
                "ci-handoff-guard",
            ],
            env,
        )

        missing_notes = _run_cli(
            [
                "review-update",
                "--finding_id",
                "CI-H-1",
                "--status",
                "deferred",
                "--session",
                "ci-handoff-guard",
            ],
            env,
            expect_success=False,
        )
        if missing_notes.get("ok", True) is not False:
            raise RuntimeError("Expected deferred update without notes to fail.")

        _run_cli(
            [
                "review-update",
                "--finding_id",
                "CI-H-1",
                "--status",
                "deferred",
                "--resolution_notes",
                "Deferred for CI parser smoke validation.",
                "--session",
                "ci-handoff-guard",
            ],
            env,
        )
        missing_reopen_reason = _run_cli(
            [
                "review-update",
                "--finding_id",
                "CI-H-1",
                "--status",
                "open",
                "--session",
                "ci-handoff-guard",
            ],
            env,
            expect_success=False,
        )
        if missing_reopen_reason.get("ok", True) is not False:
            raise RuntimeError("Expected reopen without reopen_reason to fail.")

        _run_cli(
            [
                "review-reopen",
                "--finding_id",
                "CI-H-1",
                "--reason",
                "Reopened after deferred status while CI lifecycle continues.",
                "--session",
                "ci-handoff-guard",
            ],
            env,
        )

        open_findings = _run_cli(
            [
                "review-list",
                "--task_ref",
                task_ref,
                "--status",
                "open",
            ],
            env,
        )
        finding_row = (open_findings.get("findings") or [None])[0]
        if not finding_row:
            raise RuntimeError(f"Expected open finding row after reopen, got: {open_findings}")
        if int(finding_row.get("reopen_count") or 0) < 1:
            raise RuntimeError(f"Expected reopen_count >= 1 after reopen, got: {finding_row}")
        if not finding_row.get("last_reopen_reason"):
            raise RuntimeError(f"Expected last_reopen_reason to be populated, got: {finding_row}")

        reconcile = _run_cli(["review-reconcile", "--task_ref", task_ref], env)
        if reconcile.get("healthy") is not True:
            raise RuntimeError(f"Expected reconcile to be healthy, got: {reconcile}")

        not_ready = _run_cli(
            ["handoff-close-check", "--task_ref", task_ref, "--enforce"],
            env,
            expect_success=False,
        )
        if not_ready.get("ready_to_close", True):
            raise RuntimeError("Close-check should fail while finding is still open.")

        _run_cli(
            [
                "review-update",
                "--finding_id",
                "CI-H-1",
                "--status",
                "fixed",
                "--session",
                "ci-handoff-guard",
            ],
            env,
        )

        state = _run_cli(["state", task_ref], env)
        active = state.get("active") or {}
        revision = int(active.get("revision", -1))
        if revision < 0:
            raise RuntimeError(f"Could not read active revision from state payload: {state}")

        _run_cli(
            [
                "set",
                "--task_ref",
                task_ref,
                "--objective",
                "CI handoff integrity guard",
                "--status",
                "done",
                "--expected_revision",
                str(revision),
            ],
            env,
        )
        _run_cli(["task", task_ref], env)

        ready = _run_cli(
            ["handoff-close-check", "--task_ref", task_ref, "--enforce"],
            env,
        )
        if ready.get("ready_to_close") is not True:
            raise RuntimeError(f"Expected close-check to pass, got: {ready}")

        destructive_task_ref = f"ci-destructive-{uuid.uuid4().hex[:8]}"
        active_state = _run_cli(["state"], env)
        active_revision = int((active_state.get("active") or {}).get("revision", -1))
        if active_revision < 0:
            raise RuntimeError(f"Could not read revision before destructive guard checks: {active_state}")

        _run_cli(
            [
                "set",
                "--task_ref",
                destructive_task_ref,
                "--objective",
                "CI destructive clear safeguards",
                "--status",
                "in_progress",
                "--expected_revision",
                str(active_revision),
            ],
            env,
        )
        _run_cli(
            [
                "review-record",
                "--finding_id",
                "CI-H-CLEAR-1",
                "--file_path",
                "scripts/mcp/unified_server.py",
                "--description",
                "CI destructive clear safeguard finding",
                "--severity",
                "low",
                "--session",
                "ci-handoff-guard",
            ],
            env,
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
                    },
                },
                indent=2,
            )
        )

        blocked_replace = _run_cli(
            [
                "import",
                "--input_path",
                str(destructive_payload_path),
                "--mode",
                "replace_task",
            ],
            env,
            expect_success=False,
        )
        if blocked_replace.get("ok", True) is not False:
            raise RuntimeError(f"Expected replace_task import without ack to fail, got: {blocked_replace}")
        if "allow_destructive_clear" not in (blocked_replace.get("error") or ""):
            raise RuntimeError(f"Expected replace_task failure to mention allow_destructive_clear, got: {blocked_replace}")

        blocked_prune = _run_cli(
            ["archive", "--task_ref", destructive_task_ref, "--prune-working-rows"],
            env,
            expect_success=False,
        )
        if blocked_prune.get("ok", True) is not False:
            raise RuntimeError(f"Expected prune archive without ack to fail, got: {blocked_prune}")
        if "allow_destructive_clear" not in (blocked_prune.get("error") or ""):
            raise RuntimeError(f"Expected prune failure to mention allow_destructive_clear, got: {blocked_prune}")

        finding_still_present = _run_cli(["review-summary", "--task_ref", destructive_task_ref], env)
        open_count_before_ack = int((finding_still_present.get("counts", {}).get("status", {}).get("open", 0)))
        if open_count_before_ack != 1:
            raise RuntimeError(
                "Expected finding to remain after blocked destructive operations, "
                f"got: {finding_still_present}"
            )

        _run_cli(
            [
                "import",
                "--input_path",
                str(destructive_payload_path),
                "--mode",
                "replace_task",
                "--allow-destructive-clear",
            ],
            env,
        )
        finding_cleared_after_ack = _run_cli(["review-summary", "--task_ref", destructive_task_ref], env)
        open_count_after_ack = int((finding_cleared_after_ack.get("counts", {}).get("status", {}).get("open", 0)))
        if open_count_after_ack != 0:
            raise RuntimeError(
                "Expected acknowledged destructive replace to clear finding rows, "
                f"got: {finding_cleared_after_ack}"
            )

    print("handoff-integrity-guard: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
