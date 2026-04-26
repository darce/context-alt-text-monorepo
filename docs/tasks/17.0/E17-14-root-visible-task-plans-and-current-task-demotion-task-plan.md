# E17-14. Root-Visible Task Plans and CURRENT_TASK Demotion

- **Date**: 2026-04-25
- **Author**: GitHub Copilot (GPT-5.4)
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-14`
- **Review Coverage Target**: 2

## Objective

Make every active task plan discoverable from the monorepo root without switching the root worktree away from `main`, while removing the remaining workflow assumption that `CURRENT_TASK.json` must always be regenerated and kept in sync.

## Problem Statement

The current handoff workflow stores `target_worktree_path` for active tasks, but it does not persist a structured task-plan path that the root workspace can use to surface planning artifacts living in sibling worktrees. As a result, the operator can have the correct active task in MCP and still be unable to discover or open the plan from the root workspace without manual context switching. The friction is compounded by older helper paths and docs that still treat `CURRENT_TASK.json` as a standing machine-state artifact even though the newer workflow guidance already positions it as on-demand.

## Constraints

- The root worktree must remain on `main`; this task must not rely on checking feature branches out in the root workspace.
- The canonical implementation boundary for handoff runtime changes is the external `darce/mcp-agent-handoff` repo; this monorepo only carries the consumer-facing plan, adoption, and verification surfaces.
- Avoid background mirroring or continuous file copying. Operator visibility should come from structured state and explicit read/open flows, not repeated artifact regeneration.
- `DASHBOARD.txt` remains the operator-facing live surface after state-changing writes. `CURRENT_TASK.json` may remain as an explicit export surface, but not as a required always-current singleton.
- Task-plan visibility must work for multiple active tasks and must not rely on parsing freeform prose from `focus`.

## Workflow Principles

- Keep the source of truth singular: `.task-state/handoff.db` owns task state; rendered files are derived views only.
- Surface task plans by metadata plus explicit path resolution, not by copying task-plan files into root.
- Separate package implementation from consumer verification: external repo changes land first, monorepo adoption and cleanup follow.
- Prefer one operator-visible root artifact over multiple mirrors.

## Terminology

- **Root-visible task plan**: an active task plan that can be discovered and opened from the monorepo root workspace without switching the root worktree to the task branch.
- **Task-plan metadata**: structured handoff fields such as `task_plan_path`, resolved absolute plan path, and existence state.
- **On-demand current-task render**: an explicit `render_handoff(kind='current_task', ...)` call used only when a task-scoped machine snapshot is needed.

## Current State Analysis

- Active handoff state already carries `target_branch` and `target_worktree_path`, which is enough to locate a task worktree but not enough to render or open its plan deterministically.
- The current plan path often survives only as prose inside `focus`, which is not a stable contract surface for renderers, close checks, or operator tooling.
- `.vscode/mcp.json`, helper scripts, and several docs still pass or describe `CURRENT_TASK.json` as if it were a default always-on artifact.
- Newer workflow guidance already says `DASHBOARD.txt` is the always-current operator view and `CURRENT_TASK.json` is on-demand, but the package contract and helper scripts have not fully converged on that model.

## Target Outcome

The root workspace exposes a durable operator surface listing every active task plan with its owning task ref, target branch, worktree path, repo-relative plan path, and resolved absolute plan path. The external `mcp-agent-handoff` package owns the state-model and dashboard changes that make this possible. This monorepo consumes the new package version, verifies the behavior from the root workspace, and removes local docs/helper assumptions that `CURRENT_TASK.json` must be regenerated after every relevant workflow step.

## Context Loading

- Rules: [docs/agentic/instructions.md](../../agentic/instructions.md), [docs/agentic/rules/development-workflow.md](../../agentic/rules/development-workflow.md), [docs/agentic/rules/planning-review-guide.md](../../agentic/rules/planning-review-guide.md)
- Constitution: [docs/agentic/constitution.md](../../agentic/constitution.md)
- Related plans: [docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md](./E17-7-handoff-evolution-and-portable-workflow-task-plan.md), [docs/tasks/17.0/E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md](./E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md), [docs/tasks/17.0/E17-13-hoisted-surface-cleanup-task-plan.md](./E17-13-hoisted-surface-cleanup-task-plan.md)
- Contracts: [docs/agentic/contracts/agent-handoff-mcp.md](../../agentic/contracts/agent-handoff-mcp.md), [docs/agentic/contracts/harness-protocol.yaml](../../agentic/contracts/harness-protocol.yaml)
- Consumer setup: [docs/agentic/consumer-setup.md](../../agentic/consumer-setup.md)
- Handoff/MCP state: active task refs, target worktree paths, and current dashboard rendering behavior

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Handoff task state | `darce/mcp-agent-handoff` | active rows expose worktree metadata but no structured task-plan metadata | add structured `task_plan_path` plus resolved plan-path fields | yes; existing task-state reads must remain valid | external package tests + root consumer smoke |
| Dashboard operator surface | `darce/mcp-agent-handoff` | `DASHBOARD.txt` shows active tasks but not a complete active-task-plan index | add active task-plan visibility section and/or columns | yes; ASCII operator view must remain stable | dashboard render tests + root manual smoke |
| Current-task renderer | `darce/mcp-agent-handoff` | `CURRENT_TASK.json` still appears in default package contract and some helper flows | demote to on-demand-only render semantics | yes; explicit exports still work | external package tests + root verification |
| Consumer runtime config | monorepo root | `.vscode/mcp.json` and helpers pass `--current-task-path` unconditionally | relax local assumptions once external package behavior lands | yes; root MCP startup must continue | root startup smoke + doctor |
| Planning/workflow docs | monorepo root | live docs still mix on-demand and always-current guidance | converge docs on root-visible plans + on-demand `CURRENT_TASK.json` | yes; workflow instructions stay coherent | grep audit + planning review |

## Proposed Solution

Introduce structured task-plan metadata in the external handoff package, resolve it against `target_worktree_path`, and render all active task plans into the root operator surface. Then update this monorepo to consume that package behavior, verify it from the root workspace, and remove local workflow language and helper assumptions that still require `CURRENT_TASK.json` to be kept current continuously.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Planning artifact | `docs/tasks/17.0/E17-14-root-visible-task-plans-and-current-task-demotion-task-plan.md` | Root reviewable plan for the full change |
| External package | `darce/mcp-agent-handoff` runtime, renderers, and tests | Add task-plan metadata + dashboard visibility + current-task demotion |
| Consumer config | `.vscode/mcp.json` | Update only if the new package surface makes `--current-task-path` optional or unnecessary |
| Consumer docs | `docs/agentic/consumer-setup.md`, `docs/agentic/instructions.md`, `CLAUDE.md` | Align docs with on-demand current-task rendering and root-visible task plans |
| Consumer helpers | `Makefile`, `mk/handoff.mk`, `scripts/_task_finish_inline.py`, related guards/review helpers | Remove stale `CURRENT_TASK.json` assumptions where safe |

## Related Files

| File | Note |
| --- | --- |
| `docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md` | Already records deferred `CURRENT_TASK.json` demotion work |
| `docs/tasks/17.0/E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md` | Captures multi-active-task implications for current-task rendering |
| `docs/tasks/17.0/E17-13-hoisted-surface-cleanup-task-plan.md` | Defines the external repo ownership boundary |
| `docs/agentic/contracts/agent-handoff-mcp.md` | Current package contract that still treats `CURRENT_TASK.json` as a default artifact |
| `docs/agentic/consumer-setup.md` | Consumer update and doctor workflow |
| `.vscode/mcp.json` | Root MCP launcher config |

## Verification Strategy

- Deterministic tests:
  - external `mcp-agent-handoff` unit/integration coverage for task-state metadata, dashboard rendering, and current-task render-on-demand behavior
  - root-repo targeted checks for updated helper/docs expectations once consumer changes land
- Runtime-parity / environment checks:
  - install the reviewed external `mcp-agent-handoff` ref into the `description-service` environment
  - restart/reload the root MCP server and verify root discovery of active task plans
- Contract/fixture verification:
  - verify `get_handoff_state` and dashboard output expose the new task-plan metadata without breaking existing fields
  - verify explicit `render_handoff(kind='current_task')` still returns a parseable task snapshot when requested
- Manual verification:
  - from the monorepo root workspace, inspect the operator surface and open an active task plan living in a sibling worktree without switching the root checkout

## Slice Delivery

### Slice 1: External Handoff Metadata and Renderer Changes

**Goal**: Make active task plans first-class, root-visible state in the external `mcp-agent-handoff` package.

Changes:

- Add structured task-plan metadata to active handoff state, including repo-relative `task_plan_path` and resolved path fields derived from `target_worktree_path`.
- Define one canonical write path for `task_plan_path` so it is set intentionally during task start or the first planning-artifact registration step, rather than inferred later from freeform `focus` text.
- Extend the dashboard/query surfaces to expose all active task plans from the consumer root without requiring mirrored copies of plan files.
- Demote `CURRENT_TASK.json` from implicit always-current regeneration to explicit on-demand rendering, preserving it only as an optional task-scoped export surface.

Proof:

- External package tests cover task-plan metadata reads/writes, dashboard rendering of active task plans, and successful on-demand current-task rendering.
- External package changelog/contract updates document the new behavior.

### Slice 2: Consumer Root Verification from This Monorepo

**Goal**: Prove the root workspace can consume the new external package behavior without switching the root worktree.

Changes:

- Upgrade the root repo's `description-service` environment to the reviewed external `mcp-agent-handoff` ref.
- Verify the root MCP server starts cleanly and exposes active task plans from sibling worktrees.
- Capture the root-side proof path and operator workflow in this monorepo's consumer-facing docs or task notes.

Proof:

- Root-level external-package verification succeeds against the reviewed external ref.
- Manual/operator smoke confirms a root-visible active task-plan surface and successful open/read flow.

### Slice 3: Cleanup of CURRENT_TASK Assumptions in Local Docs and Helpers

**Goal**: Remove stale root-repo assumptions that `CURRENT_TASK.json` must always be present, current, or part of every close/verification path.

Changes:

- Update local docs, prompts, and helper scripts to treat `DASHBOARD.txt` as the always-current operator surface and `CURRENT_TASK.json` as on-demand.
- Remove or relax helper checks that fail merely because `CURRENT_TASK.json` was not regenerated on unrelated workflow paths.
- Preserve any explicit current-task export command only where a task-scoped machine snapshot is genuinely required.

Proof:

- Root-repo targeted checks pass with the new semantics.
- Grep/doc audit confirms stale always-current language is removed or narrowed to explicit on-demand cases.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed external runtime changes belong in `darce/mcp-agent-handoff`, while this monorepo owns consumer-facing planning, adoption, and verification.
- [ ] Recorded boundary ownership and compatibility expectations for the external package, dashboard surface, and local helper/docs cleanup.

### Checklist for Slice 1: External Handoff Metadata and Renderer Changes

- [ ] `darce/mcp-agent-handoff` persists structured `task_plan_path` metadata rather than relying on freeform `focus` text.
- [ ] Dashboard/query surfaces expose all active task plans from the consumer root.
- [ ] `CURRENT_TASK.json` is demoted to explicit on-demand rendering without breaking explicit export use cases.
- [ ] External package tests and contracts cover the new behavior.

### Checklist for Slice 2: Consumer Root Verification from This Monorepo

- [ ] Root repo installs or references the reviewed external package version.
- [ ] Root MCP startup and operator flow are verified against the new task-plan visibility surface.
- [ ] Consumer-facing verification steps are captured in the monorepo artifact or adjacent docs.

### Checklist for Slice 3: Cleanup of CURRENT_TASK Assumptions in Local Docs and Helpers

- [ ] Local docs and prompts no longer describe `CURRENT_TASK.json` as always-current by default.
- [ ] Local helper scripts/configs no longer require constant `CURRENT_TASK.json` regeneration where it is not needed.
- [ ] Remaining explicit current-task render paths are intentional and documented.

## Review Readiness

- [ ] The task-plan metadata contract is explicit enough that implementation does not need to infer it from prose.
- [ ] The plan does not depend on file mirroring, root branch switching, or background artifact churn.
- [ ] External-package work, root consumer verification, and local cleanup are separated into reviewable slices with proof.

## Stretch Goals

- [ ] Add an explicit operator command or MCP query for resolving and opening a task plan by `task_ref` from the root workspace.

## Success Criteria

- [ ] The root workspace can discover every active task plan without checking the root worktree out to the task branch.
- [ ] The operator can open or inspect an active task plan from the root workspace with no mirrored plan files.
- [ ] The external handoff package no longer treats `CURRENT_TASK.json` as an always-current required artifact.
- [ ] This monorepo's docs and helpers no longer depend on continuous `CURRENT_TASK.json` regeneration.
