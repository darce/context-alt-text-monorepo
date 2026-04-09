#!/usr/bin/env python3
"""Inline Python implementation for scripts/task-start.sh.

AHMCP-20 / Layer 1 of the heredoc-eradication bug class fix. Promoted
from a `python -c '...'` heredoc inside task-start.sh to a standalone
module so bash quoting (especially apostrophes inside Python comments,
which is the AHMCP-17 bug) cannot break the script. The bug class is
unrepresentable here because there is no bash heredoc to quote.

Reads the following from the environment (set by task-start.sh):
    REPO_ROOT       absolute path to the primary worktree (or any
                    worktree — RuntimeConfig.for_repo collapses to
                    primary)
    TASK            the task ref to register
    OBJECTIVE       the task objective string
    BRANCH          the feature branch task-start.sh just created
    WORKTREE_PATH   the linked worktree task-start.sh just linked

Configures the agent_handoff_mcp runtime against the primary worktree's
state directory, fetches the active row's revision via the identity-only
projection (the AHMCP-16 fix that lets the script work when an existing
handoff_state row is present), and updates the handoff state to point at
the new task. Exits 0 on success and 1 on any failure.

This module is intentionally `_`-prefixed: it is invoked by task-start.sh
and is not part of the public scripts/ surface.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from agent_handoff_mcp import (
    RuntimeConfig,
    configure_runtime,
    get_handoff_state,
    set_handoff_state,
)


def main() -> int:
    repo_root = Path(os.environ["REPO_ROOT"])
    runtime = RuntimeConfig.for_repo(repo_root)
    configure_runtime(runtime)

    # Fetch the current handoff_state revision before updating.
    # set_handoff_state requires expected_revision for any update of the
    # singleton id=1 row, and that row is non-null whenever any task has
    # ever been started — omitting expected_revision used to fail every
    # invocation after the first (AHMCP-16 fix). Treat the absence of an
    # active row as a genuine cold start and pass expected_revision=None.
    identity = get_handoff_state(sections="identity")
    if isinstance(identity, str):
        identity = json.loads(identity)
    identity_data = identity.get("data") if isinstance(identity, dict) else None
    active_row = identity_data.get("active") if isinstance(identity_data, dict) else None
    expected_revision = active_row.get("revision") if isinstance(active_row, dict) else None

    result = set_handoff_state(
        task_ref=os.environ["TASK"],
        objective=os.environ["OBJECTIVE"],
        status="in_progress",
        target_branch=os.environ["BRANCH"],
        target_worktree_path=os.environ["WORKTREE_PATH"],
        expected_revision=expected_revision,
    )
    parsed = json.loads(result) if isinstance(result, str) else result
    if not parsed.get("ok"):
        print(f"\u26a0 set_handoff_state failed: {parsed}", file=sys.stderr)
        return 1
    revision = parsed.get("data", {}).get("active", {}).get("revision", "?")
    print(f"  OK rev={revision}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
