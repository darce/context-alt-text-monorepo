#!/usr/bin/env python3
"""Inline Python implementation for scripts/task-finish.sh.

AHMCP-20 / Layer 1 of the heredoc-eradication bug class fix. Promoted
from a `python -c '...'` heredoc inside task-finish.sh to a standalone
module so bash quoting (especially apostrophes inside Python comments,
which is the AHMCP-17 bug) cannot break the script. The bug class is
unrepresentable here because there is no bash heredoc to quote.

Reads the following from the environment (set by task-finish.sh):
    REPO_ROOT       absolute path to the primary worktree (or any
                    worktree — RuntimeConfig.for_repo collapses to
                    primary)
    TASK            the task ref to archive

Configures the runtime against the primary worktree, sets task status
to "done" with the correct expected_revision (the AHMCP-17 fix that
mirrors the AHMCP-16 task-start.sh pattern), archives the task, and
regenerates CURRENT_TASK.md. Exits 0 on success; non-zero failures
print to stderr but the script does NOT abort the surrounding bash
flow — task-finish.sh treats the inline Python as best-effort because
the worktree teardown happens before the archive call.

This module is intentionally `_`-prefixed: it is invoked by task-finish.sh
and is not part of the public scripts/ surface.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from agent_handoff_mcp import (
    RuntimeConfig,
    archive_task_state,
    configure_runtime,
    generate_current_task_md,
    get_handoff_state,
    update_task_status,
)


def main() -> int:
    repo_root = Path(os.environ["REPO_ROOT"])
    runtime = RuntimeConfig.for_repo(repo_root)
    configure_runtime(runtime)

    task = os.environ["TASK"]
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_root)
    ).strip().decode()

    # Best-effort status -> done before archive (idempotent if already done).
    # AHMCP-16-FU-01: when the task being finished is the active row
    # (handoff_state.id=1), update_task_status delegates to set_handoff_state
    # which requires expected_revision for any update of an existing row.
    # Fetch the active row's revision via the identity-only sections
    # projection and pass it through. When the task is NOT the active row
    # (already cleared, or being archived from a snapshot context), the
    # active payload is None and we pass expected_revision=None — that
    # routes update_task_status to the archived-snapshot path which does
    # not enforce optimistic concurrency.
    identity = get_handoff_state(sections="identity")
    if isinstance(identity, str):
        identity = json.loads(identity)
    identity_data = identity.get("data") if isinstance(identity, dict) else None
    active_row = identity_data.get("active") if isinstance(identity_data, dict) else None
    expected_revision = (
        active_row.get("revision")
        if isinstance(active_row, dict) and active_row.get("task_ref") == task
        else None
    )

    try:
        state = update_task_status(
            task_ref=task,
            status="done",
            expected_revision=expected_revision,
        )
        if not state.get("ok"):
            print(f"\u26a0 update_task_status returned ok=False: {state}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - intentional best-effort
        print(f"\u26a0 update_task_status skipped: {exc}", file=sys.stderr)

    archived = archive_task_state(
        task_ref=task,
        archive_branch="main",
        archive_commit_sha=head_sha,
    )
    if not archived.get("ok"):
        print(f"\u26a0 archive_task_state returned ok=False: {archived}", file=sys.stderr)

    regen = generate_current_task_md()
    if not regen.get("ok"):
        print(f"\u26a0 generate_current_task_md returned ok=False: {regen}", file=sys.stderr)
    print("  OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
