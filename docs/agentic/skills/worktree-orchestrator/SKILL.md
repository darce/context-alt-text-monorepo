---
name: worktree-orchestrator
description: Use when a task should be split across Git worktrees or multiple Codex sessions. Decompose work into bounded lanes, create/register worktrees, render worker briefs, enforce lane ownership, and coordinate review/merge order through agent-handoff-mcp.
---

# Worktree Orchestrator

Use this skill when one main agent needs to coordinate worker agents in sibling Git worktrees.

## Trigger

Use this skill when a task should be split across stable seams such as owned paths, contract boundaries, or test packs, and one orchestrator agent needs to coordinate multiple worker lanes without losing shared task truth.

## What this skill owns

- deciding whether a task should be split into lanes
- creating worker worktrees on `codex/*` branches
- registering/updating shared MCP lanes
- rendering bounded worker briefs
- deciding merge order and integration checks
- keeping shared checklist and task truth centralized

## Canonical Policy

- Use [../../instructions.md](../../instructions.md) for startup, handoff, and `ctx7` policy.
- Use [../../rules/development-workflow.md](../../rules/development-workflow.md) for cross-boundary, slice, and review-readiness rules.
- Treat this skill as the orchestrator execution recipe; shared process policy remains in the linked canonical docs.

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

### 3. Dispatch and monitor the lane

Use shared MCP state, not chat memory:

```bash
make lane-dispatch TASK=<task-ref> LANE=backend-http MESSAGE="Implement the retention router and verify the lane-local checks."
make handoff-inbox TASK=<task-ref>
```

Then monitor the lane with:

```bash
scripts/worktree-lane status \
  --orchestrator-root /abs/path/to/orchestrator \
  --task-ref <task-ref> \
  --lane-id backend-http \
  --worktree-path /abs/path/to/worktree
```

If the worker gets blocked on another domain, keep the lane in scope and reassign the blocker instead of letting the worker edit outside lane ownership. The root-side `make handoff-inbox` poller is where those worker handoff/guidance messages surface.

When the orchestrator records review findings, blockers, or next actions in MCP from root, fan them back out with:

```bash
make handoff-dispatch TASK=<task-ref>
```

That stamps routeable unassigned open handoff items onto the correct lane and creates or reuses lane messages so workers pick them up in `make lane-inbox`.

Workers should also emit `worker_to_orchestrator` messages when they are merge-ready or blocked. Poll those from root with:

```bash
make handoff-inbox TASK=<task-ref>
```

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

## Handoff Evidence Checklist

- Before dispatching work to a lane, confirm the worker's contract surface exists and is current. Cite the contract path in the lane brief or dispatch message.
- Before accepting a lane handoff, verify the worker summary names changed contracts, test counts, and schema or runtime implications.
- When routing findings or blockers to a lane, include the contract path and at least one verification command so the worker does not have to rediscover the boundary from scratch.
- When a slice changes a boundary or creates a downstream dependency, require the worker to use one of:
  - [../../templates/DECISION_CONTRACT_CHANGE.template.md](../../templates/DECISION_CONTRACT_CHANGE.template.md)
  - [../../templates/DECISION_BREAKING_CHANGE.template.md](../../templates/DECISION_BREAKING_CHANGE.template.md)
  - [../../templates/DECISION_CROSS_LANE.template.md](../../templates/DECISION_CROSS_LANE.template.md)
- Keep policy details in the canonical sources: [../../instructions.md](../../instructions.md) for startup and loading rules, and [../../rules/development-workflow.md#cross-boundary-change-protocol](../../rules/development-workflow.md#cross-boundary-change-protocol) for boundary validation.

## Safety Constraints

- Do not assign two workers to the same owned path set.
- Do not let workers rewrite shared plan truth unless explicitly assigned.
- Reject out-of-scope files during intake.
- Keep the overall task `in_progress` while individual lanes move to `review`, `merged`, or `closed`.
- The orchestrator owns final MCP task updates and `CURRENT_TASK.md` generation.

## Recovery

- If lane ownership is ambiguous, stop and split the work again before dispatching.
- If a worker reports out-of-scope changes, reject intake and reroute the work rather than silently absorbing it.
- If a lane gets blocked on another domain, record the blocker and dispatch the dependent work instead of letting the worker cross boundaries.
- If orchestration state drifts from the shared MCP state, regenerate the shared human-readable surfaces only after the MCP write path is corrected.

## Convergence Criteria

- Each active lane has a bounded owned path set, a worker brief, and a clear verification target.
- Worker handoffs route back through MCP with merge-ready or blocker status instead of ad hoc chat-only summaries.
- Final task truth, shared checklist state, and `CURRENT_TASK.md` are consistent with the orchestrator’s MCP updates.
