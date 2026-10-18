# WB-MONOTONIC-S1. Workbench monotonic pipeline snapshot (S1)

> **Task Short ID**: WB-MONOTONIC-S1
> **Status**: in_progress
> **Source scope**: [docs/scopes/workbench-clustering-ui-latency-refresh-scope.md](../../scopes/workbench-clustering-ui-latency-refresh-scope.md) Slice S1
> **Predecessors**: BR-21 backend stability work (E15-3a); E15-22 thumb/avatar gate (merged).
> **Format Note**: Thin task plan. The detailed root-cause analysis and full slice catalogue already live in the scope doc; this plan only captures the WB-MONOTONIC-S1 implementation gates.

---

## Objective

Make the Workbench "Analyze selected media" pipeline counts monotonic and internally consistent for a single run, so that the displayed scan completed count never decreases between renders and the `ScanActionPanel` batch-run text matches its progress bar.

## MVP Exit Criteria

1. `ScanActionPanel` batch-run status text uses processed total (completed + failed + cancelled) consistently with the `<progress>` bar value.
2. A pure `enforceMonotonicProgress(prev, next)` helper guarantees displayed scan and clustering counts never regress for the same run, with unit-test coverage for mixed success/failure, stale SSE fallback, and multi-batch out-of-order completion.
3. A `useMonotonicScanProgress`/`useWorkbenchPipelineSnapshot` wrapper keyed by run id wires the helper into `useJobStateMachineDerivedState` so consumers see monotonic counts without changing existing component contracts.

## Non-Goals (explicit, deferred to follow-up slices)

- Submission throughput / bounded-concurrency batching — scope Slice S2.
- Decoupling projection from the SSE read path — scope Slice S3.
- Force-refresh of review surfaces on projection ready — scope Slice S4.
- New durable pipeline status endpoint — scope Slice S5.
- Extracting the full `WorkbenchPipelineSnapshot` shape into a single selector — deferred to WB-MONOTONIC-S1b once the monotonic guard lands; this slice keeps the existing surface and only adds the monotonic wrapper.

## Slice Plan

### Slice 1 — Monotonic guard + batch-run text fix

- Add a pure helper `enforceMonotonicProgress(prev, next)` in `jobStateMachineProgress.ts` that returns `next` with `completed`, `images_processed`, and `faces_found` clamped to be no smaller than `prev` (when both refer to the same run).
- Fix `ScanActionPanel` so the batch-run text under the progress bar uses `completed + failed + cancelled` (processed total) instead of `completed_total` alone, matching `buildScanProgress`'s denominator math.
- Extend `jobStateMachineProgress.test.ts` with: (a) batch-run completed regression is clamped; (b) SSE fallback completed regression is clamped; (c) faces_found regression is clamped; (d) zero `prev` is a no-op.

Exit: tests pass, the panel text and the progress bar agree on the same denominator for a partial-failure run.

### Slice 2 — Wire the guard into the derived-state hook

- Add a `useMonotonicScanProgress(rawProgress, runKey)` React hook backed by `useRef`, scoped per `runKey` (batch-run id, else scan job id, else cluster job id). Reset accumulator on `runKey` change.
- Call it inside `useJobStateMachineDerivedState` so `scanProgress` and `clusterProgress` returned to consumers are monotonic for the active run.
- Add a `useJobStateMachineDerivedState` test (or extend existing) proving that two consecutive renders with a regressing raw progress produce a monotonic `scanProgress` output.

Exit: derived hook returns monotonic counts; existing consumers unchanged.

## Deliverables

- Updated `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineProgress.ts` with the monotonic helper.
- Updated `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineDerivedState.ts` calling the wrapper.
- New `apps/prototype-wp-alt-context/js/admin/hooks/useMonotonicScanProgress.ts` (or co-located).
- Updated `apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx` batch-run text.
- Extended `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/jobStateMachineProgress.test.ts` with the monotonic cases.

## Risks

- **Cross-run leakage**: if `runKey` changes are missed, a new run would inherit the previous run's monotonic floor and lock counts high. Mitigation: explicit `useRef` reset on `runKey` change, asserted by a test that the floor resets when the key flips.
- **Batch-run terminal vs in-flight mismatch**: clamping a terminal batch-run completed total under a higher SSE-aggregation snapshot could mask a real backend regression. Mitigation: monotonic guard only applies inside a single run; terminal-state transitions are handled by the existing `buildCompletedScanSnapshot` path, not the guard.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status.

## Context and Ownership

- [x] Loaded the scope doc (`docs/scopes/workbench-clustering-ui-latency-refresh-scope.md`) and traced root causes RC-2, RC-3, RC-6 to the current `jobStateMachineProgress`, `useJobStateMachineDerivedState`, and `Panels.tsx` anchors before editing.
- [x] Confirmed no operator-only dependency: this slice is pure frontend logic + tests.
- [x] Kept task ownership clean: S2/S3/S4/S5 from the scope are explicitly deferred to follow-up tasks.

### Checklist for Slice 1: Monotonic guard + batch-run text fix

- [x] Add `enforceMonotonicProgress` helper to `jobStateMachineProgress.ts`.
- [x] Fix `ScanActionPanel` batch-run text to render processed total consistently with the progress bar.
- [x] Extend `jobStateMachineProgress.test.ts` with batch-run, SSE, and faces_found monotonic cases plus a zero-prev no-op case.

### Checklist for Slice 2: Wire the guard into the derived-state hook

- [x] Add `useMonotonicScanProgress(rawProgress, runKey)` hook.
- [x] Wire it through `useJobStateMachineDerivedState` for `scanProgress` and `clusterProgress`.
- [x] Add a derived-state test proving monotonicity across renders and reset on `runKey` change.

## Review Readiness

- [x] All hook tests pass under the workspace vitest runner.
- [x] No type errors in the touched files.
- [x] No regressions to the existing `buildScanProgress` clustering/projecting completion snapshot test.

## Success Criteria

- [x] `ScanActionPanel` batch-run text and progress bar agree on the same denominator for a partial-failure run.
- [x] Displayed scan and clustering counts cannot regress within the same run id even under out-of-order SSE/batch-run updates.

## Handoff

When done, set status to `done`, archive, and link the monotonic helper plus the wrapper hook from the scope doc's S1 row so the next follow-up (selector extraction → S1b, or scope Slice S2) can build on this baseline.
