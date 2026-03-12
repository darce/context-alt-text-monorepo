---
name: worktree-orchestrator
description: Use when a task should be split across Git worktrees or multiple Codex sessions. Decompose work into bounded lanes, create/register worktrees, render worker briefs, enforce lane ownership, and coordinate review/merge order through agent-handoff-mcp.
---

# Worktree Orchestrator

Use this skill when one main agent needs to coordinate worker agents in sibling Git worktrees.

## What this skill owns

- deciding whether a task should be split into lanes
- creating worker worktrees on `codex/*` branches
- registering/updating shared MCP lanes
- rendering bounded worker briefs
- deciding merge order and integration checks
- keeping shared checklist and task truth centralized

## Preflight

1. Read [instructions.md](../../instructions.md), especially the multi-agent worktree section.
2. Confirm the active handoff task already exists in shared MCP state.
3. Split work only along stable seams:
   - path ownership
   - API contract ownership
   - test ownership
4. Keep shared plans, checklists, and cross-lane conclusions in the orchestrator lane unless explicitly delegated.

## Default lane split for this repo

- `backend-domain`: `apps/prototype-description-service/db/**`, `recognition/domain/**`, `recognition/infrastructure/**`
- `backend-http`: `apps/prototype-description-service/recognition/interface_adapters/http/**`
- `wp-proxy`: `apps/prototype-wp-alt-context/src/**`, `apps/prototype-wp-alt-context/tests/Unit/**`
- `frontend`: `apps/prototype-wp-alt-context/js/**`

## Standard workflow

### 1. Create the lane

Use the helper from the orchestrator root:

```bash
scripts/worktree-lane create \
  --orchestrator-root /abs/path/to/orchestrator \
  --lane-id backend-http \
  --branch codex/<task>-backend-http \
  --title "Backend HTTP" \
  --objective "Implement the retention router and HTTP schema slice."
```

This creates the sibling worktree and registers the lane in shared MCP state.

### 2. Render the worker brief

Use the brief template renderer:

```bash
scripts/worktree-lane brief \
  --orchestrator-root /abs/path/to/orchestrator \
  --task-ref <task-ref> \
  --lane-id backend-http \
  --branch codex/<task>-backend-http \
  --worktree-path /abs/path/to/worktree \
  --objective "Implement the retention router and HTTP schema slice." \
  --owned-path apps/prototype-description-service/recognition/interface_adapters/http/** \
  --required-doc docs/agentic/instructions.md \
  --required-doc docs/agentic/contracts/agent-handoff-mcp.md \
  --test-command "cd apps/prototype-description-service && pytest recognition/tests/api/test_retention_api.py" \
  --definition "Ready for orchestrator branch review with targeted tests passing."
```

Paste that brief into the worker session.

### 3. Monitor the lane

Use shared MCP state, not chat memory:

```bash
scripts/worktree-lane status \
  --orchestrator-root /abs/path/to/orchestrator \
  --lane-id backend-http \
  --worktree-path /abs/path/to/worktree
```

If the worker gets blocked on another domain, keep the lane in scope and reassign the blocker instead of letting the worker edit outside lane ownership.

### 4. Intake the lane

Workers should finish by setting the lane to `review`, submitting a merge-ready lane report, and optionally sending a lane message.

Review the worker branch before merge. Prefer:

```bash
git cherry-pick <worker-commit-sha>
```

Use selective file intake only when intentionally trimming scope:

```bash
git checkout codex/<task>-<lane> -- path/to/file
```

## Guardrails

- Do not assign two workers to the same owned path set.
- Do not let workers rewrite shared plan truth unless explicitly assigned.
- Reject out-of-scope files during intake.
- Keep the overall task `in_progress` while individual lanes move to `review`, `merged`, or `closed`.
- The orchestrator owns final MCP task updates and `CURRENT_TASK.md` generation.
