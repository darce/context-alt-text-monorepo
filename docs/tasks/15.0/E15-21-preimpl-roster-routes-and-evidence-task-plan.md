# E15-21. Preimplementation Roster Routes and Evidence

> **Metadata**
>
> - **Date**: 2026-05-06 16:10 EST
> - **Author**: Codex
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-21
> - **Target Branch**: `feature/e15-21-preimpl-roster-routes-and-evidence`
> - **Review Coverage Target**: 2
> - **Start Command**: `make task-start TASK=E15-21 OBJECTIVE="Implement PREIMPL roster route and evidence gates"`

---

## Objective

Implement PREIMPL-007 and the roster-UI guardrails from PREIMPL-002/PREIMPL-009 in [docs/specs/e15-app-refactoring-preimplementation-spec.md](../../specs/e15-app-refactoring-preimplementation-spec.md). When complete, the Roster route model can parse person, queue, face, and cluster links without pretending the person workspace exists before RCL-004 projection data lands.

## Problem Statement

The current Roster page centers Entries and Clusters tabs, while E15-17 wants a person-first review workspace. The PREIMPL spec requires route parsing to land before UI expansion, but rendering must wait for the RCL-004 enriched roster-entry projection. Without that gate, the UI could ship an empty shell that implies person review exists while source-backed data is absent.

This plan supersedes [E15-17](E15-17-roster-person-review-scrub-workspace-task-plan.md) as the canonical PREIMPL roster UI implementation track. Before Slice 1 code edits, record the superseding handoff decision for E15-21, run `update_task_status(task_ref='E15-17', status='superseded')`, and archive E15-17 only after its existing branch/worktree is confirmed closed.

## Constraints

- RCL-004 enriched roster-entry projection must exist before person workspace rendering.
- ADR-009/RCL-004 projection semantics remain upstream; this task does not redefine them.
- Clusters remain reachable as evidence/debug routes during migration.
- Do not introduce new similarity-score semantics before E15-13 and [RCL-009](../../specs/recognition-roster-curation-loop-spec.md#rcl-009-add-enhanced-score-evidence-after-refresh-contracts-land) supply those fields.
- Do not import external marketing scrubber code; build roster-local accessible controls.

## Workflow Principles

- Person is the operator's primary identity model after curation; clusters are evidence/topology.
- Routes can parse before data exists, but product UI must not imply unavailable capabilities.
- Every enabled action must map to an existing API/action contract.
- Compatibility routes are temporary migration paths, not places to add new primary behavior.

## Terminology

- **Person route**: `#/roster?person={person_uuid}` and optional `face={identity_id}` selector.
- **Queue route**: `#/roster?queue={queue_id}` for projection-backed review queues.
- **Cluster evidence route**: `#/roster?cluster={cluster_id}` for assigned or unresolved cluster evidence.
- **Workspace availability gate**: Runtime condition that RCL-004 projection fields exist before the person workspace renders as default.

## Current State Analysis

- `RosterPage.tsx` defaults to Entries/Clusters tabs.
- `ClusterDrawerPanel.tsx` presents cluster identity details as primary context.
- The enriched projection schema is not yet available in `packages/shared-contracts/schemas/roster-entry.schema.json`.
- RSU UI shapes contain fields that must be treated as UI consumption of RCL-004, not an independent contract.

## Target Outcome

Roster route parsing supports queue, person, face, and cluster selectors. The current Entries/Clusters routes remain reachable until RCL-004 data exists. Once projection data lands, assigned clusters link to a person workspace by `person_uuid`, unresolved clusters stay in evidence mode, and raw cluster grid behavior stops expanding as the primary identity model.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/frontend-guidelines.md`
- Rules: `docs/agentic/rules/testing-typescript.md`
- Constitution: `docs/agentic/constitution.md`
- Spec: `docs/specs/e15-app-refactoring-preimplementation-spec.md`
- Spec: `docs/specs/roster-management-person-review-scrub-ui-spec.md`
- Spec: `docs/specs/recognition-roster-curation-loop-spec.md`
- Related task: `docs/tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md`
- Prerequisite task: `docs/tasks/15.0/E15-19-preimpl-roster-refresh-projection-foundation-task-plan.md`
- Handoff/MCP state: active task `E15-21`, E15-19/RCL-004 decisions, roster UI planning findings
- External docs via `ctx7` only if: React routing/testing behavior blocks a concrete implementation decision.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Roster route state | frontend | tab query params and cluster drawer links | parse queue/person/face/cluster selectors | existing routes remain reachable | Vitest route tests |
| RCL-004 projection -> UI | shared contracts + plugin + frontend | count-only or absent enriched fields | consume fields only after projection gate | yes; rendering waits on contract | schema/codegen + Vitest |
| Cluster drawer -> person workspace | frontend | cluster identity drawer | assigned clusters link by `person_uuid` | additive route behavior | component tests |
| Scrubber actions | frontend + plugin REST | existing curation/suggestion endpoints | controls enabled only when API/action row exists | no fabricated actions | Vitest + API contract tests where changed |

## Proposed Solution

Land route parsing and compatibility behavior first, then add workspace availability gates. After E15-19 lands RCL-004 projection data, consume the projection for person rows and cluster evidence. Keep cluster evidence mode for unresolved/topology review and avoid new score semantics.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| roster shell | `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx` | Add route parsing and workspace availability gate |
| roster API/types | `apps/prototype-wp-alt-context/js/admin/api/rosterApi.ts` | Consume generated RCL-004 projection types when available |
| entries/person UI | `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx` | Transition table-only entry to person workspace consumer |
| cluster evidence | `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx` | Link assigned clusters to person route; keep unresolved mode |
| roster components | `apps/prototype-wp-alt-context/js/admin/pages/roster/` | Queue strip, person list shell, evidence mode |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/roster/**/__tests__` | Route, gate, evidence, and compatibility tests |

## Related Files

| File | Note |
| --- | --- |
| `packages/shared-contracts/schemas/roster-entry.schema.json` | RCL-004 projection source |
| `apps/prototype-wp-alt-context/src/api/class-api.php` | Roster projection API owner, implemented by E15-19/E15-13 |
| `docs/tasks/15.0/E15-19-preimpl-roster-refresh-projection-foundation-task-plan.md` | Upstream contract/projection prerequisite |
| `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md` | Original RCL implementation plan |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/roster`
- Runtime-parity / environment checks:
  - Open `http://localhost:10010/wp-admin/admin.php?page=alt-context-roster#/roster` with and without RCL-004 projection data.
- Contract/fixture verification:
  - Shared roster-entry schema/codegen checks from E15-19/E15-13 are green before enriched fields are rendered.
- Manual verification:
  - Deep links for queue, person, person+face, and cluster evidence behave as specified.

## Slice Delivery

### Slice 1: Route Parser and Compatibility Gate

**Goal**: Parse future roster routes without changing the default product surface prematurely.

Changes:

- Add deterministic parsing for queue, person, face, and cluster params.
- Keep Entries/Clusters compatibility paths reachable.
- Add workspace availability gate that blocks default person workspace rendering without RCL-004 fields.

Proof:

- Vitest covers default, queue, person, face, cluster, and compatibility routes with projection absent.

### Slice 2: Projection-Aware Person Workspace Shell

**Goal**: Render person workspace shell only when canonical projection fields exist.

Changes:

- Block Slice 2 start until E15-19 Slice 3 records a `close_slice` decision proving the RCL-004 projection contract landed.
- Verify the generated `roster-entry` projection types are present before workspace rendering work starts.
- Consume RCL-004 generated types once available.
- Render person rows with representative evidence, counts, queue memberships, and projection status.
- Keep empty states honest when projection is refreshing/stale/failed.

Proof:

- The E15-19 Slice 3 `close_slice` decision exists, the generated `roster-entry` projection types are present, and Vitest covers projection-present, projection-refreshing, projection-stale, and projection-absent states.

### Slice 3: Cluster Evidence Migration

**Goal**: Turn clusters into evidence instead of primary identities.

Changes:

- Link assigned clusters to `person_uuid` route.
- Keep unresolved clusters in evidence/queue mode.
- Explain merged/superseded topology when fields exist.

Proof:

- Vitest covers assigned, unresolved, singleton proposal, merged, and superseded cluster states.

### Slice 4: Scrubber Readiness Guard

**Goal**: Prepare face-review controls without outrunning API/action contracts.

Changes:

- Keep controls disabled/hidden until action contracts exist.
- Avoid new score semantics unless [RCL-009](../../specs/recognition-roster-curation-loop-spec.md#rcl-009-add-enhanced-score-evidence-after-refresh-contracts-land) fields are present.
- Preserve keyboard and aspect-correct layout requirements in tests.

Proof:

- Vitest covers disabled/available action states and no layout-shift regressions at component level.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded PREIMPL spec, RSU spec, RCL spec, E15-17 related plan, and handoff state.
- [ ] Recorded the disposition of E15-17 (superseded by E15-21 with a handoff decision id) before Slice 1 implementation starts.
- [ ] Confirmed RCL-004 projection fields exist before rendering enriched workspace.
- [ ] Recorded any boundary changes if UI needs fields/actions beyond RCL-004.

### Checklist for Slice 1: Route Parser and Compatibility Gate

- [ ] Queue/person/face/cluster routes parse deterministically.
- [ ] Entries/Clusters routes remain reachable.
- [ ] Projection-absent gate tests pass.

### Checklist for Slice 2: Projection-Aware Person Workspace Shell

- [ ] E15-19 Slice 3 is closed before Slice 2 starts.
- [ ] Generated `roster-entry` projection types are present before enriched workspace rendering begins.
- [ ] Person rows render only from canonical projection fields.
- [ ] Projection status/freshness states render honestly.
- [ ] Empty states do not imply unavailable data exists.

### Checklist for Slice 3: Cluster Evidence Migration

- [ ] Assigned clusters link to person route by `person_uuid`.
- [ ] Unresolved clusters remain in evidence mode.
- [ ] Merged/superseded states explain topology when available.

### Checklist for Slice 4: Scrubber Readiness Guard

- [ ] Controls map only to available API/action contracts.
- [ ] New similarity semantics remain deferred unless [RCL-009](../../specs/recognition-roster-curation-loop-spec.md#rcl-009-add-enhanced-score-evidence-after-refresh-contracts-land) fields exist.
- [ ] Keyboard/aspect/layout tests pass.

## Review Readiness

- [ ] No UI field or action is consumed before its owning projection/API contract exists.
- [ ] Runtime roster check covers projection-present and projection-absent states when possible.
- [ ] Handoff decision records route model, projection gate, and verification.

## Stretch Goals

- [ ] Add a compact developer-only route debug helper if it does not render in production UI.

## Success Criteria

- [ ] Roster routes parse person, queue, face, and cluster selectors deterministically.
- [ ] Person workspace rendering waits for RCL-004 projection data.
- [ ] Clusters are evidence routes after projection exists, not the expanding primary identity model.
