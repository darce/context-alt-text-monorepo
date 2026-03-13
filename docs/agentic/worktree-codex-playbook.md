# Worktree Codex Playbook

Use this playbook when opening a fresh Codex instance against a Phase 5 worker lane.

## Goal

Start Codex in the correct worktree, on the correct branch, with the correct lane inbox and handoff commands available.

## Terminology

- orchestrator root: `/Users/daniel/Development/context-alt-text-monorepo`
- worker worktree examples:
  - `/Users/daniel/Development/context-alt-text-monorepo-p5-backend-domain`
  - `/Users/daniel/Development/context-alt-text-monorepo-p5-backend-http`
  - `/Users/daniel/Development/context-alt-text-monorepo-p5-wp-proxy`
  - `/Users/daniel/Development/context-alt-text-monorepo-p5-frontend`

## Phase 5 lane map

- `backend-domain` -> branch `codex/p5-backend-domain`
- `backend-http` -> branch `codex/p5-backend-http`
- `wp-proxy` -> branch `codex/p5-wp-proxy`
- `frontend` -> branch `codex/p5-frontend`

## Best operator flow

From the orchestrator root:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
make lane-open TASK=phase-5-retention-export-and-audit-controls LANE=frontend ENTER_SHELL=1
```

What this does:

- verifies or creates the lane registration in MCP
- prints the lane brief
- proves the target worktree branch with `git status -sb`
- opens an interactive shell in the worker worktree
- ensures later `make lane-refresh` runs will pull committed orchestrator branch updates into that lane cleanly

After the subshell opens, verify:

```bash
pwd
git branch --show-current
git status -sb
make lane-inbox
```

Expected result for the frontend example:

- `pwd` -> `/Users/daniel/Development/context-alt-text-monorepo-p5-frontend`
- `git branch --show-current` -> `codex/p5-frontend`

## If you do not want ENTER_SHELL=1

Use a two-step flow:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
make lane-open TASK=phase-5-retention-export-and-audit-controls LANE=frontend
cd "$(make lane-path TASK=phase-5-retention-export-and-audit-controls LANE=frontend)"
git branch --show-current
make lane-inbox
```

Important:

- `make lane-open` cannot change the current shell's directory or branch.
- It prepares the worktree and prints the next command.
- You must either `cd` into the returned path or use `ENTER_SHELL=1`.

## Recommended fresh Codex startup sequence

In Terminal:

```bash
open -n -a Codex
```

In the new Codex window, point the workspace at the worker worktree path, then run:

```bash
pwd
git branch --show-current
make lane-inbox
```

The worker should not start coding before `make lane-inbox` shows the open orchestrator dispatch.
If root workflow tooling changed since the lane was opened, run `make lane-refresh` once before trusting the local lane commands.

## Worker loop

Once inside the worker worktree:

```bash
make lane-inbox
make lane-refresh
```

What `make lane-refresh` does here:

- syncs the lane branch against the current orchestrator branch
- auto-stashes dirty lane state before the refresh
- updates the lane from committed orchestrator branch state so commands like `make lane-inbox` and `make lane-handoff` stay in sync with root

Implement only inside the lane-owned paths, then finish with:

```bash
make lane-handoff
```

## Orchestrator loop

From the orchestrator root:

Send work:

```bash
make lane-dispatch TASK=phase-5-retention-export-and-audit-controls LANE=frontend MESSAGE="Finish the assigned slice."
```

Review-driven work:

```bash
make handoff-dispatch TASK=phase-5-retention-export-and-audit-controls
```

Use that after recording or updating MCP handoff state from the orchestrator root. It routes unassigned open review findings, blockers, and next actions to the owning lane and sends MCP lane messages so the worker sees the queue in `make lane-inbox`.

Review and intake:

```bash
make lane-commits TASK=phase-5-retention-export-and-audit-controls LANE=frontend
make lane-intake TASK=phase-5-retention-export-and-audit-controls LANE=frontend
```

## Recovery checks

If you think the worker is in the wrong place:

```bash
pwd
git branch --show-current
git status -sb
```

If the branch is wrong, return to the orchestrator root and refresh the lane:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
make lane-refresh TASK=phase-5-retention-export-and-audit-controls LANE=frontend
```

Then reopen the worker shell with `ENTER_SHELL=1`.
If the issue was missing lane commands rather than the wrong branch, `make lane-refresh` is still the fix after the orchestrator has committed the tooling update on root.

## Minimal commands by role

Orchestrator:

```bash
make lane-dispatch TASK=phase-5-retention-export-and-audit-controls LANE=<lane> MESSAGE="..."
make handoff-dispatch TASK=phase-5-retention-export-and-audit-controls
make lane-intake TASK=phase-5-retention-export-and-audit-controls LANE=<lane>
```

Worker:

```bash
make lane-inbox
make lane-handoff
```
