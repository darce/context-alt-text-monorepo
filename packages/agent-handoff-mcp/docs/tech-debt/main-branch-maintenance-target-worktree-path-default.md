# Default `target_worktree_path` for Main-Branch Maintenance Tasks

## Problem

E17-11 intentionally made task resolution fail closed: write callers now resolve task context by `task_ref` first, then by workspace-path lookup, and raise when neither yields a unique row. That fixed the old singleton-sentinel bug, but it exposed a workflow gap for repo-root maintenance on `main`.

Today the maintenance-task guidance still tells operators to create `MAINT-*` tasks like this:

- `scripts/hooks/guard-main-branch.sh` suggests `set_handoff_state(task_ref='MAINT-<slug>', objective='Describe the main-branch patch', status='in_progress')`
- `scripts/check-task-context.py` prints the same hint for dirty main-branch edits

Those examples omit `target_worktree_path`, even though the API and contract already support it. After E17-11, that omission means a `MAINT-*` task created from the repo root can coexist with feature-branch tasks but still be unresolvable by implicit workspace lookup, because the resolver has no registered root path to match.

Observed failure shape:

- root worktree on `main`
- active feature task exists in a linked worktree with `target_worktree_path` set
- new `MAINT-*` task is created on `main` without `target_worktree_path`
- subsequent implicit write-path resolution raises `Ambiguous active task` instead of selecting the maintenance task for the root worktree

## Why This Is a Real Gap

This is not a regression in E17-11's resolver. The resolver is doing the right thing: fail closed rather than guess. The gap is in the helper/guidance layer that still creates maintenance tasks without the metadata the stricter resolver now needs.

The public surface already supports the required data:

- `set_handoff_state(..., target_worktree_path=...)` in the handoff API
- the contract docs already describe `target_worktree_path` as the canonical worktree anchor for drift checks and workspace resolution

So the missing piece is not a schema or API change. It is a task-creation defaulting and documentation problem.

## Proposed Fix

Add a small follow-up helper change so **main-branch maintenance task creation defaults `target_worktree_path` to the current repo root when all of the following are true**:

1. `task_ref` starts with `MAINT-`
2. the target branch is `main` or `master`
3. the caller did not pass an explicit `target_worktree_path`

Concretely:

1. Introduce or reuse one helper/wrapper for maintenance-task registration so the default is centralized instead of duplicated in shell hints and ad-hoc examples.
2. Update `guard-main-branch.sh` and `check-task-context.py` hint text to show the root-path form, not the legacy minimal form.
3. Preserve explicit overrides: if a maintenance task intentionally targets some other path, the caller-supplied `target_worktree_path` wins.

This should be framed as a defaulting rule for **main-scoped maintenance tasks**, not as a blanket "always stamp the current repo root" policy for every task type.

## Why This Fix Is Correct

This fix matches the post-E17-11 contract:

- feature tasks still point at their linked worktrees
- maintenance tasks on `main` point at the root worktree
- implicit workspace resolution regains a unique row for repo-root maintenance operations
- explicit `task_ref` writes continue to work unchanged

It also avoids reintroducing any singleton/sentinel behavior. The resolver still uses per-row metadata; we are just ensuring maintenance rows actually carry the metadata needed for root-worktree disambiguation.

## Non-Fix Alternatives To Avoid

- Re-adding a fallback sentinel row: this would undo E17-11.
- Making ambiguity warning-only again: this would silently bind writes to the wrong task in multi-active flows.
- Special-casing `main` in the resolver to "prefer MAINT-*`: that would invent task-selection semantics instead of relying on explicit metadata.

## Proof Criteria

- Creating a `MAINT-*` task from the repo root on `main` without an explicit `target_worktree_path` stores the repo root automatically.
- A subsequent implicit write from the repo root resolves to that maintenance task even when feature-branch tasks exist in linked worktrees.
- Existing feature-task flows and explicit-path maintenance flows remain unchanged.
- Guidance surfaces no longer recommend the pathless `set_handoff_state(... status='in_progress')` maintenance example.

## Suggested Follow-Up Surface

- helper / wrapper used for maintenance-task registration
- `scripts/hooks/guard-main-branch.sh`
- `scripts/check-task-context.py`
- any startup / workflow docs that still show the pathless maintenance-task example
