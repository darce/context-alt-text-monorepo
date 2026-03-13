# Worktree Codex Playbook

Use this playbook when opening a fresh Codex instance against any worker lane in this repo.

## Goal

Start Codex in the correct worktree, on the correct branch, with the correct lane inbox and handoff commands available.

## Terminology

- orchestrator root: the main repo checkout, usually `/Users/daniel/Development/context-alt-text-monorepo`
- worker worktree: a sibling checkout created for one lane
- task ref: the active MCP task, for example `phase-5-retention-export-and-audit-controls`
- lane id: the worker slice name, for example `backend-domain`, `backend-http`, `wp-proxy`, or `frontend`

## Current repo examples

Current worker worktree examples:

- `/Users/daniel/Development/context-alt-text-monorepo-p5-backend-domain`
- `/Users/daniel/Development/context-alt-text-monorepo-p5-backend-http`
- `/Users/daniel/Development/context-alt-text-monorepo-p5-wp-proxy`
- `/Users/daniel/Development/context-alt-text-monorepo-p5-frontend`

Current lane examples:

- `backend-domain` -> branch `codex/p5-backend-domain`
- `backend-http` -> branch `codex/p5-backend-http`
- `wp-proxy` -> branch `codex/p5-wp-proxy`
- `frontend` -> branch `codex/p5-frontend`

## Best operator flow

From the orchestrator root:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
make lane-open TASK=<task-ref> LANE=<lane>
```

What this does:

- verifies or creates the lane registration in MCP
- prints the lane brief
- proves the target worktree branch with `git status -sb`
- polls the lane inbox immediately so the worker sees open orchestrator messages before coding
- opens an interactive shell in the worker worktree by default
- ensures later `make lane-refresh` runs will pull committed orchestrator branch updates into that lane cleanly

After the subshell opens, verify:

```bash
pwd
git branch --show-current
git status -sb
make lane-inbox
```

Expected result for a frontend-style example:

- `pwd` -> `/Users/daniel/Development/context-alt-text-monorepo-p5-frontend`
- `git branch --show-current` -> `codex/p5-frontend`

## If you do not want the subshell

Use a two-step flow:

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
make lane-open TASK=<task-ref> LANE=<lane> ENTER_SHELL=0
cd "$(make lane-path TASK=<task-ref> LANE=<lane>)"
git branch --show-current
make lane-inbox
```

Important:

- `make lane-open` cannot change the current shell's directory or branch.
- By default it opens a child shell in the lane worktree.
- If you pass `ENTER_SHELL=0`, it prepares the worktree and prints the next command instead.

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
If root workflow tooling changed since the lane was opened, commit those root changes and then run `make lane-refresh` once before trusting the local lane commands.

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
make lane-dispatch TASK=<task-ref> LANE=<lane> MESSAGE="Finish the assigned slice."
```

Review-driven work:

```bash
make handoff-inbox TASK=<task-ref>
make handoff-dispatch TASK=<task-ref>
```

Use `make handoff-inbox` to listen for worker-to-orchestrator handoffs such as merge-ready reports and guidance requests. Use `make handoff-dispatch` after recording or updating MCP handoff state from the orchestrator root. It routes unassigned open review findings, blockers, and next actions to the owning lane and sends MCP lane messages so the worker sees the queue in `make lane-inbox`.

Review and intake:

```bash
make lane-commits TASK=<task-ref> LANE=<lane>
make lane-intake TASK=<task-ref> LANE=<lane>
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
make lane-refresh TASK=<task-ref> LANE=<lane>
```

Then reopen the worker shell with the default `make lane-open TASK=<task-ref> LANE=<lane>` behavior.
If the issue was missing lane commands rather than the wrong branch, `make lane-refresh` is still the fix after the orchestrator has committed the tooling update on root.

## Minimal commands by role

Orchestrator:

```bash
make lane-dispatch TASK=<task-ref> LANE=<lane> MESSAGE="..."
make handoff-dispatch TASK=<task-ref>
make lane-intake TASK=<task-ref> LANE=<lane>
```

Worker:

```bash
make lane-inbox
make lane-handoff
```

`make lane-handoff` now auto-initiates a worker-to-orchestrator handoff message when the lane is merge-ready. If the worker instead needs guidance, submit a blocked report and the same handoff message channel is used for the ask.
