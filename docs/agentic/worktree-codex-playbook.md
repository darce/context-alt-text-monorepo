# Worktree Codex Playbook

Use this playbook when operating multi-agent worktree lanes in this repo. Covers both orchestrator (human or lead agent) and worker (Codex or interactive agent) perspectives.

## Goal

Start workers in the correct worktree, on the correct branch, with the correct lane inbox and handoff commands available. Complete the full lifecycle from task decomposition through lane merge and close.

## Task Manifests

Each task that uses lane automation should define its orchestration config in `config/lane-orchestration/<task-ref>.json`.

That manifest is the source of truth for:

- lane ids and branch names
- worktree path templates
- owned paths and commit scope
- required docs and verification commands
- merge order and dispatch routing hints

To add lane automation for a new task, add a new manifest first. The root `Makefile`, `review_dispatch.py`, and the worker helpers read from that manifest instead of from task-specific hardcoded tables.

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

---

## Quick Reference

### Orchestrator one-liners (run from orchestrator root)

```bash
make lane-open TASK=<task> LANE=<lane>                         # Create/open a lane
make lane-dispatch TASK=<task> LANE=<lane> MESSAGE="..."       # Assign work
make handoff-inbox TASK=<task>                                 # Poll worker handoffs
make handoff-dispatch TASK=<task>                              # Route findings to lanes
make lane-commits TASK=<task> LANE=<lane>                      # Preview intake
make lane-intake TASK=<task> LANE=<lane>                       # Merge a lane
make lane-refresh TASK=<task> LANE=<lane>                      # Sync lane to root
make lane-list                                                 # List all lanes
make state                                                     # Full MCP state
make dashboard                                                 # MCP dashboard
```

### Worker one-liners (run from worker worktree)

```bash
make lane-inbox                                                # Poll assignments
make lane-prompt                                               # Render actionable prompt
make lane-check                                                # Run lane tests
make lane-handoff                                              # Commit + report + hand off
make lane-report STATUS=blocked MERGE_READY=0 SUMMARY="..." MESSAGE="..."  # Blocked report
```

All `lane-*` commands work from the repo root and from the app directories that ship forwarding Makefiles. The app-level Makefiles use a `lane-%:` pattern rule that auto-forwards any `lane-*` target to the root Makefile, so new lane targets never need to be registered in the app Makefiles.

---

## Recipes

### Recipe: Open a new lane

**Who:** Orchestrator. **When:** Starting a new worker slice.

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
make lane-open TASK=<task-ref> LANE=<lane>
```

What this does:

- verifies or creates the lane registration in MCP
- hard-fails if an existing worktree is on the wrong branch for that lane
- prints the lane brief (owned paths, test commands, non-goals)
- proves the target worktree branch with `git status -sb`
- polls the lane inbox immediately so the worker sees open orchestrator messages before coding
- opens an interactive shell in the worker worktree by default

After the subshell opens, verify:

```bash
pwd                       # should be the lane worktree path
git branch --show-current # should be the lane branch
make lane-inbox           # should show any open dispatches
```

To stay in the orchestrator root instead of opening a subshell:

```bash
make lane-open TASK=<task-ref> LANE=<lane> ENTER_SHELL=0
cd "$(make lane-path TASK=<task-ref> LANE=<lane>)"
```

### Recipe: Dispatch work to a lane

**Who:** Orchestrator. **When:** Assigning or reassigning work to a worker.

```bash
make lane-dispatch TASK=<task-ref> LANE=<lane> MESSAGE="Wire the retention router to the real services and verify pytest + mypy."
```

What this does:

1. Upserts the lane registration to `active` status.
2. Sends an open `orchestrator_to_worker` lane message.
3. Regenerates `CURRENT_TASK.md` so the dispatch is human-readable.

The worker sees it the next time they run `make lane-inbox`.

To preview without writing:

```bash
make lane-dispatch TASK=<task-ref> LANE=<lane> MESSAGE="..." DRY_RUN=1
```

### Recipe: Worker implements a slice

**Who:** Worker (agent or human). **When:** After receiving a dispatch.

```bash
# 1. Check what work is assigned
make lane-inbox

# 2. Read the detailed prompt (includes findings, actions, blockers)
make lane-prompt

# 3. Optionally sync with latest orchestrator changes
make lane-refresh

# 4. Implement changes within lane-owned paths only

# 5. Verify before handoff
make lane-check

# 6. Hand off (commits lane-owned files, submits merge-ready report)
make lane-handoff
```

Notes:

- `make lane-check` runs the lane's configured test commands (`LANE_TEST_CMD_1`, `LANE_TEST_CMD_2`) in the current worktree and records each result into MCP, so lane activity keeps a durable verification trail. Run it before `make lane-handoff` to catch failures early.
- `make lane-handoff` will refuse to proceed if there are no unique lane commits or if out-of-scope files are present.
- If you need a custom commit message: `make lane-handoff COMMIT_MSG="implement retention policy service"`.

### Recipe: Worker is blocked

**Who:** Worker (agent or human). **When:** Cannot proceed due to sandbox, permissions, missing dependencies, or unclear requirements.

```bash
make lane-report STATUS=blocked MERGE_READY=0 \
  SUMMARY="Cannot install Python deps in scratch worktree" \
  MESSAGE="Verified schema migration is correct. pytest cannot run because venv is missing. Recommend SKIP_TESTS=1 on intake or orchestrator runs tests manually."
```

What this does:

1. Submits a blocked worker report (no lane commit required).
2. Sends a `worker_to_orchestrator` lane message so the orchestrator sees it in `make handoff-inbox`.
3. Sets the lane status to `blocked`.

The orchestrator picks it up with `make handoff-inbox TASK=<task-ref>` and decides next steps.

### Recipe: Poll for worker handoffs

**Who:** Orchestrator. **When:** Waiting for workers to finish, or checking progress.

```bash
make handoff-inbox TASK=<task-ref>
```

Shows:

- Open `worker_to_orchestrator` lane messages (merge-ready handoffs, guidance requests).
- Latest worker reports with merge-ready or blocked status.

To filter to a specific lane:

```bash
make handoff-inbox TASK=<task-ref> LANE=backend-domain
```

### Recipe: Route review findings to lanes

**Who:** Orchestrator. **When:** After recording review findings in MCP from the orchestrator root.

```bash
# Step 1: Record findings using MCP tools (record_review_finding)
# Step 2: Route them to the correct worker lanes
make handoff-dispatch TASK=<task-ref>
```

What `handoff-dispatch` does:

1. Loads all open, unassigned review findings, blockers, and next actions from MCP.
2. Routes each to a lane based on file path patterns or text hints.
3. Stamps the lane assignment on each item.
4. Sends lane messages so workers see the queue in `make lane-inbox`.
5. Records a dispatch decision in MCP.

To preview without sending:

```bash
make handoff-dispatch TASK=<task-ref> DRY_RUN=1
```

Items that cannot be auto-routed (ambiguous or no file path) are listed as `unmatched` in the output. Route those manually with `make lane-dispatch`.

### Recipe: Preview lane commits before intake

**Who:** Orchestrator. **When:** A worker reports merge-ready.

```bash
# See what commits the lane has
make lane-commits TASK=<task-ref> LANE=backend-domain

# Dry-run intake to see the full plan
make lane-intake TASK=<task-ref> LANE=backend-domain DRY_RUN=1
```

The dry run shows:

- Latest worker report summary.
- Lane commits to cherry-pick.
- What would happen in the scratch worktree.

### Recipe: Intake (merge) a lane

**Who:** Orchestrator. **When:** Lane is verified and ready to merge.

```bash
make lane-intake TASK=<task-ref> LANE=backend-domain
```

What this does:

1. Verifies the orchestrator root is clean (no uncommitted changes).
2. Checks the latest lane report is merge-ready.
3. Lists the lane commits.
4. Creates a temporary scratch worktree from the current orchestrator HEAD.
5. Cherry-picks the lane commits into the scratch worktree.
6. Checks that all modified files are within the lane's allowed paths.
7. Runs the lane's test commands in the scratch worktree.
8. Fast-forward merges the scratch branch into the orchestrator branch.
9. Updates the lane status to `merged` in MCP.
10. Cleans up the scratch worktree.

If cherry-pick conflicts, intake aborts without touching the orchestrator root. Fix in the worker lane and resubmit.

If tests fail, intake aborts with an explicit message. Fix in the worker lane and resubmit.

To skip scratch-worktree tests (when deps cannot be installed in the scratch checkout):

```bash
make lane-intake TASK=<task-ref> LANE=backend-domain SKIP_TESTS=1
```

### Recipe: Refresh a lane after root changes

**Who:** Orchestrator or worker. **When:** The orchestrator branch has new commits the worker should pick up.

```bash
# From orchestrator root:
make lane-refresh TASK=<task-ref> LANE=backend-domain

# Or from the worker worktree (TASK and LANE auto-inferred):
make lane-refresh
```

What this does:

1. Verifies orchestrator workflow tooling is committed (refuses if dirty).
2. Auto-stashes any dirty lane state.
3. Fetches orchestrator branch into the lane.
4. If the lane has no unique commits: hard-reset to orchestrator HEAD.
5. If the lane has unique commits: rebase onto orchestrator HEAD.
6. If all lane commits are superseded (already integrated upstream): reset instead of rebase.
7. Auto-pops the stash to restore uncommitted work. If the pop conflicts, the stash is preserved and a warning is printed.

If rebase conflicts, the rebase is auto-aborted and the lane is left untouched. Resolve in the lane manually.

### Recipe: Reset a lane to a specific ref

**Who:** Orchestrator. **When:** The lane needs a hard reset (discards all lane work).

```bash
make lane-reset TASK=<task-ref> LANE=backend-domain REF=feature/6.0.2-retention-export
```

This is destructive. It runs `git reset --hard` and `git clean -fd` in the lane worktree.

### Recipe: Clean tooling drift from a lane

**Who:** Orchestrator. **When:** A lane has stale copied Makefiles or helper scripts.

```bash
make lane-clean TASK=<task-ref> LANE=backend-domain
```

Restores tooling files (`Makefile`, `scripts/worktree-lane`, templates) to their committed state without touching lane-owned product files.

### Recipe: Automated worker run (Codex CLI)

**Who:** Orchestrator. **When:** Running a worker non-interactively via `codex exec`.

```bash
make lane-run TASK=<task-ref> LANE=frontend
```

What this does:

1. Checks if the lane has actionable work (exits gracefully if not).
2. Generates a worker prompt from MCP lane activity.
3. Appends structured output instructions.
4. Runs `codex exec` in the lane worktree with an output schema.
5. On success: auto-records `make lane-commit` + `make lane-report` (merge-ready) or blocked report.
6. On failure: preserves the partial result file in `.task-state/exports/lane-run-failures/`.

To pass extra arguments to `codex exec`:

```bash
make lane-run TASK=<task-ref> LANE=frontend CODEX_ARGS='--model o3'
```

---

## Multi-Lane Merge Order

Merge lanes in dependency order to avoid cascading conflicts:

1. **backend-domain** (schema, domain services, infrastructure) -- no upstream dependencies
2. **backend-http** (API routers) -- depends on domain contracts from backend-domain
3. **wp-proxy** (PHP REST proxy) -- depends on backend HTTP contract
4. **frontend** (React UI) -- depends on wp-proxy contract

After merging each lane:

```bash
# Verify the merge
make check-all

# Refresh downstream lanes so they pick up upstream changes
make lane-refresh TASK=<task-ref> LANE=backend-http
```

---

## Fresh Codex Startup

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
Use `make lane-run` for non-interactive worker runs instead of trying to push a prompt into an already-running session.

---

## Troubleshooting

### Worker is on the wrong branch

```bash
cd /Users/daniel/Development/context-alt-text-monorepo
make lane-refresh TASK=<task-ref> LANE=<lane>
make lane-open TASK=<task-ref> LANE=<lane>
```

`make lane-open` now refuses to reuse an existing worktree if it is checked out on the wrong branch. Fix the branch drift first instead of letting work continue in the wrong lane.

### Lane-handoff refuses: "no unique lane commits"

The worker has not committed any lane-owned changes. Either:

- Run `make lane-commit` first (it stages only lane-owned paths).
- If the lane is genuinely blocked with no code changes, use `make lane-report STATUS=blocked MERGE_READY=0 SUMMARY="..." MESSAGE="..."` instead.

### Lane-commit refuses: "out-of-scope changes"

The worker edited files outside the lane's owned paths. Options:

- `git checkout -- <out-of-scope-file>` to discard unwanted changes.
- `git stash push -- <out-of-scope-file>` to save for later.
- Then retry `make lane-commit`.

### Lane-intake conflicts in scratch worktree

The orchestrator branch diverged from the lane. Fix:

```bash
make lane-refresh TASK=<task-ref> LANE=<lane>   # rebase lane onto current root
make lane-handoff                                # re-submit from worker worktree
make lane-intake TASK=<task-ref> LANE=<lane>     # retry from orchestrator root
```

### Lane-intake test failure

Tests failed in the scratch worktree. The orchestrator root was not modified. Fix the failing tests in the worker lane, then:

```bash
make lane-handoff                                # from worker worktree
make lane-intake TASK=<task-ref> LANE=<lane>     # from orchestrator root
```

If the test failure is environmental (missing deps in scratch checkout):

```bash
make lane-intake TASK=<task-ref> LANE=<lane> SKIP_TESTS=1
```

### Lane-refresh rebase conflicts

```bash
# The lane-refresh auto-aborted the rebase. Resolve manually:
cd "$(make lane-path TASK=<task-ref> LANE=<lane>)"
git rebase FETCH_HEAD
# ... resolve conflicts ...
git rebase --continue
```

### Orchestrator root is dirty before intake

```bash
git stash push -u -m "pre-intake stash"
make lane-intake TASK=<task-ref> LANE=<lane>
git stash pop
```

### MCP state seems stale

```bash
make state                    # full MCP state dump
make dashboard                # quick overview
make task                     # regenerate CURRENT_TASK.md
```

### Lane-refresh refuses: "orchestrator workflow tooling has uncommitted changes"

Commit the tooling changes on the orchestrator branch first, then retry:

```bash
git add Makefile scripts/worktree-lane docs/agentic/templates/
git commit -m "update pipeline tooling"
make lane-refresh TASK=<task-ref> LANE=<lane>
```
