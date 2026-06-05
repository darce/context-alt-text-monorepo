# E15-23. Workbench Live Findings Panel

> **Task Short ID**: E15-23  
> **Date**: 2026-06-05  
> **Author**: codex (planning draft)  
> **Status**: planned  
> **Target Branch**: `feature/e15-23-workbench-live-findings-panel`  
> **Owning Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 4  
> **Epic Short ID**: E15  
> **Source scope**: [workbench-clustering-ui-latency-refresh-scope.md](../../scopes/workbench-clustering-ui-latency-refresh-scope.md)  
> **Prior review context**: planning findings are tracked in MCP under `MAINT-workbench-findings-panel-plan-20260605`  
> **Predecessors**: `WB-MONOTONIC-S1` monotonic progress guard shipped; [E15-22](./E15-22-workbench-avatar-and-progress-readiness-task-plan.md) is required only for LocalWP/demo avatar proof, not for the frontend plan structure.

## Objective

Replace the current clunky suggestion accordion with a live Workbench findings panel that appears as soon as clustering/projection produces reviewable results. The panel must summarize what was found, make the next review action obvious, refresh dynamically without page reload, and keep detailed cluster labeling/review drawers intact.

## Problem Statement

The Workbench currently splits recognition feedback across progress widgets, a collapsible `SuggestionReviewPanel`, and in-row media identity lists. Cluster findings can appear stale until remount or page reload, and the review surface hides the most important action behind accordion-style disclosure and lower-priority bulk controls. Operators need one visible findings surface between pipeline progress and the media queue.

## Constraints

- Do not claim clusters are available before LocalWP projection reports ready.
- Do not build a separate review page in this task; keep the first usable workflow in the Workbench scan tab.
- Do not rewrite clustering quality, recognition thresholds, or backend proposal semantics.
- Keep `ClusterLabelingPanel` and `ClusterReviewPanel` as the detail surfaces for label/review actions.
- Use existing React Query keys and recognition APIs unless a test proves a missing contract.
- E15-24 is created or blocked only if E15-23 proof still requires reload, remount, or delayed passive read after projection-ready.

## Workflow Principles

- Feature first: the panel exists to answer "what did recognition find, and what should I do next?"
- Hierarchy first: one primary next action; summary counts and bulk controls are secondary.
- Dynamic truth: projection-ready must force visible findings data to refresh, not merely invalidate broad caches.
- No hidden happy path: empty, loading, unavailable, read-only, and error states must be explicit.

## Terminology

- **Live findings panel**: Workbench scan-tab surface rendered after `JobTimeline` and before `MediaSelection`, replacing the current top-level suggestion accordion.
- **Findings view model**: A typed frontend model that combines assignment suggestions, merge suggestions, name suggestions, top unlabeled clusters, loading/error state, and next action.
- **Next action**: The deterministic primary action selected from currently reviewable findings.
- **Projection-ready refresh**: A targeted React Query refetch when LocalWP projection reaches `ready`.

## Current State Analysis

- `ScanTabContent.tsx` renders `ScanActionPanel`, `JobTimeline`, then `SuggestionReviewPanel`, then `MediaSelection`.
- `SuggestionReviewPanel.tsx` owns assignment suggestions, merge suggestions, name suggestions, bulk accept, and top unlabeled clusters in one collapsible container.
- `useSuggestionReviewQueries.ts` fetches assignment, merge, name, and top-unlabeled data independently; merge/name have no refetch interval and top-unlabeled has a 60 second stale time.
- `useJobStateMachineEffects.ts` broadly invalidates cluster, suggestion, and media-identity caches on scan/cluster completion and projection sync, but it does not force all visible findings queues to refetch on projection-ready.
- `TopClustersSection.tsx`, `SuggestionCards.tsx`, and `CollapsibleMergeQueue.tsx` already provide usable content pieces that should be reused instead of rebuilt.

## Target Outcome

After a scan/clustering run, the Workbench shows a clear findings panel without reload. Operators see counts for review suggestions, merge candidates, suggested names, and unlabeled clusters; a representative face strip when available; and one primary action that opens the correct existing review or labeling surface.

## Context Loading

- Rules: `docs/workstate/rules/frontend-guidelines.md`, `docs/workstate/rules/testing-typescript.md`, `docs/workstate/rules/planning-review-guide.md`
- Source scope: `docs/scopes/workbench-clustering-ui-latency-refresh-scope.md`
- Prior plan task: `docs/tasks/15.0/WB-MONOTONIC-S1-workbench-pipeline-snapshot-task-plan.md`
- Workbench anchors: `apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useSuggestionReviewQueries.ts`, `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineEffects.ts`
- Handoff/MCP state: planning findings under `MAINT-workbench-findings-panel-plan-20260605`
- External docs via `ctx7`: load current TanStack Query, React Testing Library, and Vitest references before implementation slices that edit query refresh or tests; this planning review relies on local anchors.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Workbench findings data | frontend over existing WP REST/query keys | Assignment, merge, name, top-unlabeled, and media-identity queries are already separate | No API shape change expected; compose a frontend view model from existing responses | Yes, existing response contracts stay compatible | Vitest for `useWorkbenchFindings` and Workbench integration |
| Projection refresh | frontend state machine + React Query cache | Projection success broadly invalidates clusters/sync/media identities/suggestions | Targeted refetch for every visible findings queue and current-page identities when projection reaches ready | Yes, no backend contract widening | `useJobStateMachineEffects`/Workbench integration tests |
| Workbench UI composition | frontend component boundary | `SuggestionReviewPanel` is a collapsible all-in-one panel | New non-accordion live findings panel reuses existing card/queue/detail components | Yes, existing label/review drawers stay intact | Component tests and integration-lite test |

## Proposed Solution

Add a typed `useWorkbenchFindings` view-model hook, force projection-ready refresh of all visible findings queues, and replace the top-level suggestion accordion with a `WorkbenchFindingsPanel` rendered after `JobTimeline`. Refactor existing suggestion content into reusable sections so the panel can show the important queues directly while keeping detailed label/review drawers and mutation hooks.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx` | Render `WorkbenchFindingsPanel` after `JobTimeline` and before `MediaSelection`; preserve label/review drawer dispatch |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useWorkbenchFindings.ts` | New view model hook derived from suggestion/top-cluster queries |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/WorkbenchFindingsPanel.tsx` | New non-accordion panel with summary, representative previews, next action, and findings sections |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx` | Refactor into reusable content/sections or remove top-level accordion wrapper after the new panel owns the surface |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useSuggestionReviewQueries.ts` | Expose query objects/data needed by the new view model without duplicate fetches |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useSuggestionReviewData.ts` | Keep one shared query+mutation data surface; new view model and refactored panel sections route through or supersede it without duplicating fetch/mutation state |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx` | Allow compact panel embedding or extract reusable top-cluster list content |
| frontend | `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineEffects.ts` | Refetch all visible findings queues and current-page media identities when projection reaches ready |
| frontend | `apps/prototype-wp-alt-context/js/admin/api/queryKeys.ts` | Add query-key helper only if needed for current-page identity refetch targeting |
| styles | `apps/prototype-wp-alt-context/js/admin/styles/components/_workbench.scss` | Add panel styles using existing `--acx-*` tokens; remove sticky/accordion emphasis where obsolete |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx` | New component/view-model coverage |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx` | Prove projection-ready findings appear without reload/remount |
| tests | `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useJobStateMachineEffects.test.ts` | Prove projection-ready targeted refetch contract |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionCards.tsx` | Existing assignment suggestion cards and grouped-review behavior |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/CollapsibleMergeQueue.tsx` | Existing merge queue content; may become non-collapsible inside the panel |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClusterCard.tsx` | Existing top-cluster representative preview and actions |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncTrigger.ts` | Already invalidates broad query groups on sync success; avoid divergent refresh semantics |
| `docs/scopes/workbench-clustering-ui-latency-refresh-scope.md` | Root-cause and S4/S5 reference |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx`
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx`
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/hooks/__tests__/useJobStateMachineEffects.test.ts`
- Runtime-parity / environment checks:
  - LocalWP seeded-media scan proof only if E15-22 avatar proof is already available or demo gate requires it.
- Contract/fixture verification:
  - No shared schema update expected. If implementation adds or assumes a response field, update the shared schema/golden fixture in the same slice.
- Manual verification:
  - Workbench scan tab shows findings between `JobTimeline` and media queue after projection-ready; reload is not part of the happy path.

## Slice Delivery

### Slice 1: Findings View Model

**Goal**: Produce one typed frontend model for visible Workbench findings.

Changes:

- Add `useWorkbenchFindings` under `identity-clusters/`.
- Reuse `useSuggestionReviewQueries` and existing types for assignment, merge, name, and top-unlabeled data.
- Return summary counts, representative preview data, loading/error/unavailable flags, read-only state, and deterministic next action.
- Define next-action priority:
  1. assignment confirmation with the highest `reviewItems` score opens/targets the assignment suggestion row;
  2. pending merge suggestion opens/targets merge review;
  3. pending name suggestion opens/targets name suggestion action;
  4. top unlabeled cluster with highest `identity_count` opens label/review for that cluster;
  5. empty state disables the primary action and explains what will populate the panel.
- In read-only backend-proxy projection state, show findings as visible but disable curation actions with explicit copy.

Proof:

- `WorkbenchFindingsPanel` or hook tests cover counts, priority ordering, loading/error/empty, and read-only state.

### Slice 2: Projection-Ready Refresh

**Goal**: Findings refresh when projection becomes ready without waiting for page reload, remount, or a passive read.

Changes:

- In `useJobStateMachineEffects`, when projection sync succeeds and `projectionSyncState` transitions to `ready`, force targeted refetch for:
  - `queryKeys.suggestions.pending()`
  - `queryKeys.suggestions.mergePending()`
  - `queryKeys.suggestions.namePending()`
  - `queryKeys.clusters.topUnlabeled(tenantId)`
  - current-page media identities, either through exact `identitiesByIds(mediaIds)` when available or the narrowest existing `media.identities()` invalidation/refetch contract
- Keep broad invalidation in `useSyncTrigger` compatible with the new targeted refresh.
- Pass tenant/current-page identity context through the smallest necessary frontend boundary; do not add backend fields.

Proof:

- `useJobStateMachineEffects` tests assert every visible findings query is refetched on projection-ready.
- Workbench integration test asserts new findings data renders without remount.

### Slice 3: Live Findings Panel UI

**Goal**: Render a non-accordion findings panel in the scan tab with a clear information hierarchy.

Changes:

- Add `WorkbenchFindingsPanel` after `JobTimeline` and before `MediaSelection`.
- Show summary counts for assignment suggestions, merge candidates, name suggestions, and unlabeled clusters.
- Show representative face previews from top findings when available; use existing avatar/fallback components.
- Make one primary `Review next` action follow the view-model priority and open/target the correct row or existing label/review drawer.
- Keep secondary actions low-emphasis: review all visible suggestions, bulk accept, skip/dismiss where already supported.
- Hide or de-emphasize supporting controls when the panel is empty or unavailable.

Proof:

- Component tests cover populated, empty, loading, error, read-only, and mixed-queue states.
- Visual layout uses existing `--acx-*` spacing/color tokens and does not introduce a modal/overlay.

### Slice 4: Retire Accordion Flow

**Goal**: Remove the confusing top-level accordion while preserving existing curation behavior.

Changes:

- Refactor `SuggestionReviewPanel` into reusable content sections consumed by `WorkbenchFindingsPanel`, or replace it with the new panel where it is used in `ScanTabContent`.
- Merge queue content should not be hidden behind an unrelated accordion when it is the next action.
- Bulk accept remains available but secondary; it must not appear before the main review queues.
- Keep `ClusterLabelingPanel`, `ClusterReviewPanel`, existing mutation hooks, optimistic hiding, and query invalidation behavior.

Proof:

- Existing `SuggestionReviewPanel` tests are moved/updated to the new panel sections.
- No regression in accept/reject/name/merge/top-cluster mutation tests.

### Slice 5: Dynamic Proof and E15-24 Gate

**Goal**: Prove findings appear dynamically and decide whether the heavier projection read-path decoupling task is needed.

Changes:

- Add or extend Workbench integration coverage for: scan completes, clustering/projection reaches ready, targeted refetch returns findings, findings panel updates without reload/remount.
- If the test or LocalWP proof still requires reload, remount, manual cache clear, or delayed passive status read after projection-ready, create/block on `E15-24. Projection Read-Path Decoupling`.
- If E15-23 proof passes without those workarounds, record E15-24 as deferred follow-up with the evidence.
- Add LocalWP/manual screenshot proof only when E15 demo gating requires it; otherwise deterministic tests are the merge gate.

Proof:

- Integration test proves dynamic findings paint.
- Handoff decision records whether E15-24 is required or deferred, with evidence.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(BR-04 closed)` or "resolve handoff issue X"; finding status lives in MCP / `DASHBOARD.txt`.

## Context and Ownership

- [x] Loaded frontend rules, testing guide, source scope, existing Workbench components, and MCP planning findings before editing.
- [x] Confirmed no backend/shared-contract change is required; if implementation proves otherwise, contract/schema/fixture work lands in the same slice.
- [x] Confirmed E15-22 avatar proof availability before treating LocalWP screenshot proof as an E15-23 gate.

### Checklist for Slice 1: Findings View Model

- [x] `useWorkbenchFindings` combines assignment, merge, name, and top-unlabeled data.
- [x] Summary counts, representative preview data, and state flags are typed and covered.
- [x] Next-action priority and read-only behavior are deterministic and tested.

### Checklist for Slice 2: Projection-Ready Refresh

- [x] Projection-ready forces targeted refetch for assignment, merge, name, top-unlabeled, and current-page identities.
- [x] Refresh logic avoids broad-only invalidation as the dynamic-findings happy path.
- [x] Tests prove every visible findings queue refreshes without remount.

### Checklist for Slice 3: Live Findings Panel UI

- [x] `WorkbenchFindingsPanel` renders after `JobTimeline` and before `MediaSelection`.
- [x] Panel shows summary counts, representative previews, primary `Review next`, and secondary actions.
- [x] Empty/loading/error/read-only states are explicit and tested.

### Checklist for Slice 4: Retire Accordion Flow

- [x] Top-level suggestion accordion no longer owns the scan-tab findings workflow.
- [x] Assignment, merge, name, and top-cluster content are reusable panel sections.
- [x] Existing label/review drawers and curation mutations keep working.
- [x] Bulk accept is secondary and does not precede the main review queues.

### Checklist for Slice 5: Dynamic Proof and E15-24 Gate

- [x] Workbench integration test proves findings appear after projection-ready without reload/remount.
- [x] Handoff decision records E15-24 as required or deferred with evidence.
- [x] LocalWP/manual screenshot proof is captured only if demo gate requires it.

## Review Readiness

- [x] Expected post-implementation review path is ordinary branch review, with frontend UI/query-refresh focus; escalate to release-style audit only if LocalWP demo proof becomes an E15 public-demo gate.
- [x] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [x] Deterministic tests cover view-model priority, projection-ready refresh, and dynamic panel rendering.
- [ ] Runtime-parity proof is included if E15 demo gating depends on this surface.
- [x] Handoff decision records change, verification, and E15-24 decision.

## Stretch Goals

- [ ] Dedicated review page for long-running curation sessions.
- [ ] Filtered media-table badges linked to the selected finding.
- [ ] Durable pipeline status endpoint from the source scope S5.

## Success Criteria

- [x] The scan tab displays a live findings panel after `JobTimeline` and before the media queue.
- [x] Found clusters/suggestions appear dynamically after projection-ready without page reload, remount, manual cache clear, or delayed passive read.
- [x] The primary `Review next` action follows the documented priority order and opens/targets the correct existing review surface.
- [x] The old top-level accordion is removed or no longer controls the primary findings workflow.
- [x] E15-24 is either created/blocking with evidence or explicitly deferred with passing dynamic-proof evidence.
