---
name: worktree-worker
description: Use when implementing a delegated slice inside a worktree lane. Self-query lane scope from shared MCP state, stay inside owned paths, run lane-local tests, and hand back merge-ready reports/messages to the orchestrator.
---

# Worktree Worker

Use this skill when you are the worker agent assigned to a bounded worktree lane.

## What this skill owns

- reading lane scope from shared MCP state
- staying inside owned paths
- implementing only the delegated slice
- running lane-local verification
- handing the slice back cleanly for orchestrator review

## Start-up checklist

1. Read [instructions.md](../../instructions.md), especially the multi-agent worktree section.
2. Poll the lane inbox before changing code:

```bash
make lane-inbox
```

If you are operating outside the Makefile wrapper, query the shared lane state directly:

```bash
scripts/worktree-lane status \
  --orchestrator-root /abs/path/to/orchestrator \
  --lane-id <lane-id> \
  --worktree-path /abs/path/to/current-worktree
```

3. Confirm your changed-file budget matches the lane's owned paths.
4. If lane ownership is unclear or missing, stop and ask the orchestrator to create or update the lane instead of guessing.

Treat lane-stamped open review findings, blockers, and pending next actions shown in lane activity as part of your actionable inbox. The orchestrator may have routed them from root with `make handoff-dispatch`.

## Implementation rules

- Edit only files inside your lane's owned paths.
- If another domain must change, record a blocker or lane message for the orchestrator.
- Do not update shared plans, checklists, or sibling-lane files unless the brief explicitly says so.
- Use targeted tests for your lane only.

## Before handoff

1. Check your diff stays in scope:

```bash
git diff --name-only
```

2. Commit on the worktree branch itself.
3. Submit the lane handback:

```bash
scripts/worktree-lane report \
  --orchestrator-root /abs/path/to/orchestrator \
  --task-ref <task-ref> \
  --lane-id <lane-id> \
  --session <session-name> \
  --summary "Slice implemented and ready for orchestrator review." \
  --test-command "cd ... && pytest ..." \
  --merge-ready \
  --message "This slice is ready for review."
```

This records the lane report in shared MCP state, captures changed files from the current worktree diff, and optionally sends a worker-to-orchestrator message.

Merge-ready and blocked reports now auto-open a worker-to-orchestrator handoff message even if you do not pass `--message`. Use that path whenever the lane is done or needs more guidance from root.

## Guardrails

- Do not mark the whole task complete.
- Use lane status progression:
  - `active` while coding
  - `review` when the slice is committed and ready
  - `merged` only after the orchestrator has taken it
  - `closed` when the lane is fully done
- Keep blockers factual and lane-local.
