# Task Plan

> **Metadata**
>
> - **Date**: 2026-03-29 17:27 EDT
> - **Author**: Codex
> - **Owning Epic**: [../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md](../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: E12

---

> **Status**: Deferred — not in scope for the current branch (`feature/12.0-mcp-updates`). No implementation started as of 2026-03-30. All other E12 tasks (E12-1 through E12-6) are complete; this task is queued for a future epic cycle.

---

# E12-7. Epic Operator Overview Surface

## Objective

Introduce a separate generated operator overview for epic-scale work so multi-task progress can be scanned without overloading `CURRENT_TASK.md`. Keep `CURRENT_TASK.md` as the single-task resume surface while adding an ASCII-first multi-track view for epic progression, blockers, findings, and freshness signals.

## Problem Statement

`CURRENT_TASK.md` is intentionally derived from one task snapshot at a time, which makes it good for resuming focused work but poor for scanning an entire epic. Operators currently have to choose between constantly switching the active task so the file stays locally accurate, or letting the file drift into a pseudo-epic summary that weakens handoff semantics and close-check expectations.

## Constraints

- `CURRENT_TASK.md` must remain the single-task generated mirror described in `development-workflow.md` and enforced by handoff close checks.
- The new overview must be generated from MCP handoff state and planning metadata; it must not become a hand-edited tracker.
- ASCII/Markdown output must remain readable in plain terminals and code-review diffs without requiring dashboard UI dependencies.

## Workflow Principles

- Preserve one clear source of truth per scope: task state in MCP, `CURRENT_TASK.md` for the active task, and a separate generated file for epic/operator scanning.
- Prefer explicit metadata for tracks and dependencies over inference from prose when rendering flow diagrams.
- Make the overview useful for operators first: current status, blockers, stale proof, open findings, and “what should I switch to next” should outrank decorative output.

## Terminology

- **Active-task mirror**: The existing `CURRENT_TASK.md` file generated for one task at a time.
- **Epic overview**: A generated multi-task Markdown artifact that summarizes one epic’s tracks, task health, and progression.
- **Track**: A named sequence of related tasks within an epic, such as `code`, `docs`, or `ops`.
- **Flow view**: An ASCII dependency/progression sketch showing task ordering and branch points across tracks.

## Current State Analysis

- `CURRENT_TASK.md` is explicitly treated as derived single-task output in [docs/agentic/rules/development-workflow.md](../../agentic/rules/development-workflow.md).
- `get_handoff_state(view="dashboard")` already exposes cross-task summary counts, but only as a compact JSON/dashboard aggregation rather than a human-readable epic overview.
- The existing dashboard view in [handoff_state.py](../../../packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py) lists recent tasks with counts, but it does not model tracks, dependencies, or operator-facing narrative status.
- `generate_current_task_md` already proves the repo accepts generated Markdown mirrors, but its contract and close-check semantics are intentionally tied to one task.
- The current task-plan template does not provide structured track/dependency metadata that an epic overview renderer could consume reliably.

## Target Outcome

Operators can keep `CURRENT_TASK.md` narrow and accurate while also generating a separate epic-scoped overview such as `CURRENT_EPIC.md` or `EPIC_OVERVIEW.md`. That overview renders an ASCII-first flow section plus a compact health table for every task in the epic, clearly marks the active task, highlights blockers/open findings/stale verification, and supports multiple concurrent tracks without weakening task-level handoff rules.

## Context Loading

- Rules: [../../agentic/rules/development-workflow.md](../../agentic/rules/development-workflow.md), [../../agentic/rules/planning-review-guide.md](../../agentic/rules/planning-review-guide.md)
- Contracts: [../../agentic/contracts/agent-handoff-mcp.md](../../agentic/contracts/agent-handoff-mcp.md)
- Handoff/MCP state: `get_handoff_state(view="dashboard")`, `handoff_close_check(...)`, and recent E12 decisions/findings
- External docs via `ctx7` only if: terminal-friendly ASCII layout guidance is needed from a specific library or dependency; otherwise none

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `CURRENT_TASK.md` semantics | agentic-tooling | [../../agentic/rules/development-workflow.md](../../agentic/rules/development-workflow.md) | none; remains single-task only | yes — preserve existing close-check meaning | handoff close check + markdown tests |
| Handoff MCP generated surfaces | agentic-tooling | [../../agentic/contracts/agent-handoff-mcp.md](../../agentic/contracts/agent-handoff-mcp.md) | additive generator/query support for epic overview | yes — additive only | contract doc + pytest |
| Task-plan metadata shape | agentic-tooling | [../../agentic/templates/TASK_PLAN.template.md](../../agentic/templates/TASK_PLAN.template.md) | add optional machine-readable epic track/dependency metadata | yes — existing plans remain valid without backfill | template update + renderer fallback tests |

## Proposed Solution

Add a second generated overview surface rather than widening `CURRENT_TASK.md`. The feature should introduce a small epic-overview renderer that consumes MCP handoff state plus lightweight task-plan metadata, emits terminal-friendly Markdown with ASCII flow sections and health tables, and leaves task-level handoff/close-check behavior unchanged. The renderer should degrade gracefully when older task plans lack the new metadata by falling back to task-ref ordering and simple status grouping.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| docs | `docs/agentic/templates/TASK_PLAN.template.md` | Add optional `Track` / `Depends On` / overview metadata guidance |
| docs | `docs/agentic/rules/development-workflow.md` | Clarify `CURRENT_TASK.md` vs epic overview responsibilities |
| docs | `docs/agentic/contracts/agent-handoff-mcp.md` | Document the new epic overview generator/query surface |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py` | Add epic overview query helpers over cross-task handoff state |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` or new module | Add Markdown/ASCII epic overview renderer |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Register additive epic overview tool(s) |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` | Add CLI fallback entry for overview generation |
| tests | `packages/agent-handoff-mcp/tests/test_handoff_state.py` or new targeted test file | Add renderer/query/contract coverage |

## Related Files

| File | Note |
| --- | --- |
| `CURRENT_TASK.md` | Existing single-task generated mirror must stay narrow |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py` | Already owns dashboard-style cross-task aggregation |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` | Existing markdown render helpers may host shared formatting utilities |
| `docs/tasks/12.0/12.1/E12-6-agent-handoff-mcp-internal-refactoring-task-plan.md` | Recent handoff/overview refactors provide adjacent context |

## Verification Strategy

- Deterministic tests:
  - `python -m pytest packages/agent-handoff-mcp/tests/ -x -q`
- Runtime-parity / environment checks:
  - `python -m agent_handoff_mcp --workspace-root . doctor`
  - `python -m agent_handoff_mcp --workspace-root . dashboard`
- Contract/fixture verification:
  - Assert `CURRENT_TASK.md` close-check behavior is unchanged after adding the epic overview surface
  - Assert the epic overview renderer works with both metadata-rich and metadata-poor task plans
- Manual verification:
  - Generate the epic overview for `E12` and confirm multiple tracks, active-task marker, blockers/findings, and freshness indicators are readable in plain text

## Slice Delivery

### Slice 1: Separate Scope Semantics

**Goal**: Define the operator-overview scope without weakening `CURRENT_TASK.md`.

Changes:

- Document that `CURRENT_TASK.md` remains the active-task mirror and introduce a separate epic overview concept.
- Add optional machine-readable task-plan metadata for `Track` and `Depends On`, with renderer fallbacks for older plans.
- Update the task-plan template and workflow docs in the same slice.

Proof:

- Docs clearly distinguish active-task vs epic-overview responsibilities.
- Template examples show how to declare tracks/dependencies without requiring all historical plans to backfill.

### Slice 2: Epic Overview Query + Renderer

**Goal**: Build the cross-task data query and ASCII-first Markdown renderer.

Changes:

- Add epic-scoped query helpers that aggregate task status, blockers, open findings, pending actions, last verification, and latest decision for all tasks in one epic.
- Add an overview renderer that emits:
  - header summary
  - ASCII flow/tracks section
  - operator health table
  - explicit active-task marker
- Keep `CURRENT_TASK.md` rendering untouched.

Proof:

- Pytest covers both metadata-driven and fallback ordering cases.
- Sample rendered overview includes multiple tasks/tracks and remains readable in plain Markdown.

### Slice 3: MCP + CLI Surface

**Goal**: Expose the overview through the same generated-surface workflow as other handoff views.

Changes:

- Add an additive MCP generator/query surface such as `generate_epic_overview_md(...)` and, if needed, `get_handoff_state(view="epic_overview")` or similar.
- Add a CLI fallback command for generating/writing the overview file.
- Document output path conventions such as `CURRENT_EPIC.md` or `EPIC_OVERVIEW.md`.

Proof:

- `doctor` still reports unchanged core tool counts unless the contract intentionally adds a new generator and the doc is updated in the same slice.
- CLI can render the overview for `E12` without changing active-task semantics.

### Slice 4: Operator Polish

**Goal**: Make the overview actionable for real epic operations rather than just informative.

Changes:

- Add freshness/status cues for stale verification, open blockers/findings, and tasks that are `done` in handoff but still out of sync in generated mirrors.
- Add “next-switch candidates” or equivalent operator hints based on open work and recent activity.
- Verify the overview stays compact enough for terminal-first use.

Proof:

- Rendered overview highlights stale or blocked tasks without needing dashboard UI dependencies.
- Manual check shows the operator can identify the active task and the next likely switch target at a glance.

---

# Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff/dashboard state before editing.
- [ ] Confirmed the feature preserves `CURRENT_TASK.md` as a single-task generated mirror.
- [ ] Recorded additive contract and template impacts for the new epic overview surface.

## Slice 1: Separate Scope Semantics

- [ ] `CURRENT_TASK.md` vs epic overview responsibilities are documented clearly.
- [ ] Optional task-plan metadata for tracks/dependencies is defined.
- [ ] Template and workflow docs are updated in the same slice.

## Slice 2: Epic Overview Query + Renderer

- [ ] Cross-task epic aggregation query exists and is test-covered.
- [ ] ASCII/Markdown renderer shows tracks, flow, health, and active-task marker.
- [ ] Renderer degrades gracefully when older task plans lack new metadata.

## Slice 3: MCP + CLI Surface

- [ ] Additive MCP/CLI surface is documented and wired.
- [ ] Output file/path conventions are explicit.
- [ ] Existing `CURRENT_TASK.md` and close-check behavior stay unchanged.

## Slice 4: Operator Polish

- [ ] Stale verification, blockers, findings, and sync issues are visible in the overview.
- [ ] The view remains readable in plain terminals.
- [ ] Handoff decision records the final operator-overview semantics and verification.

## Review Readiness

- [ ] No boundary-touching overview behavior is left undocumented.
- [ ] Tests prove both metadata-rich and fallback rendering paths.
- [ ] The new surface improves epic scanning without weakening task-level resume/close flows.

## Stretch Goals

- [ ] Add a compact “track heatmap” or sparkline-style summary line for long epics.
- [ ] Add optional lane-aware sub-rows when a task uses multi-worktree orchestration.

## Success Criteria

- [ ] Operators can keep `CURRENT_TASK.md` scoped to one active task while also viewing a generated multi-task epic overview.
- [ ] The epic overview renders at least one ASCII flow/tracks section plus a task health summary in plain Markdown.
- [ ] Existing handoff close checks and `CURRENT_TASK.md` sync expectations remain intact.
