# Task Plan — E21-11

> **Metadata**
>
> - **Date**: 2026-07-14 EST
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.1/public-mvp-ux-polish-epic.md](../../epics/v0.4.1/public-mvp-ux-polish-epic.md)
> - **Epic Short ID**: E21
> - **Task ID**: E21-11
> - **Target Branch**: `feature/e21-11`
> - **Review Coverage Target**: 2

---

## E21-11. Workbench Context Decomposition + Phase Strategy Map

## Objective

Decompose the 60-field `WorkbenchContextValue` god context into four per-concern providers behind selector hooks (sr-008), collapse `ScanActionPanel`'s 12 loose props into one `ScanRunViewModel`, and replace the remaining pipeline-phase switches with a single enum-keyed phase→presentation strategy map (sr-007, [REF-02]). Behavior-preserving, visitor-invisible (epic Phase 5 / roadmap P5-A + P5-B).

## Problem Statement

`WorkbenchContextValue` (`js/admin/pages/workbench/WorkbenchContext.tsx:57-131`) exposes **60 fields** spanning seven commented concerns (Navigation, Job History, Selection, Filters & Media Queue, State Machine, Cluster Panels, Config/Env) through one context. Every consumer re-renders on any change, the provider's `useMemo` carries a 57-entry dependency array (`WorkbenchContext.tsx:395-453`), and any UI regroup must touch the god object — WBUX-1 §"God context" diagnosis, still live on `main`. Consumers destructure up to 17 fields at once (`ScanTabContent.tsx:40-56`), violating sr-008. Separately, pipeline-phase presentation is shotgun-surgery territory ([REF-19] information leakage): adding or renaming a phase touches `buildStatusText` (`js/admin/hooks/jobStateMachineProgress.ts:19`), `buildMilestones` (`js/admin/pages/workbench/JobTimeline.tsx:99`), and `formatSyncJobPhase` (`js/admin/pages/workbench/syncPresentation.ts:524`) — three independent switch/branch chains over the same two phase unions.

## Constraints

- **Behavior-preserving refactor only** ([REF-05] two hats): no visual change, no new features, no e2e/visual re-baseline (E21-4 owns re-baselines). Existing unit + integration suites must pass unchanged in intent (mock plumbing may move).
- **No backend contract changes** (rg-015): `JobProgress['phase']` (`js/admin/api/generated/recognition-job.ts:6`) is generated from the service contract — consume it, never edit it.
- **Greenfield delete-over-flag**: moved fields are deleted from the old surface in the same slice; no dual-export compatibility shim.
- **E21-1's sync view-model is canonical and landed**: `buildSyncPresentation` + `SYNC_VOCABULARY` + `SYNC_PRESENTATION_*` enums (`syncPresentation.ts:19-96,278`) are not restructured — the strategy map consolidates the *remaining* phase switches onto the same vocabulary.
- **Coordination risk**: E21-3 (confirm-tab removal) and E21-5/E21-7 touch `ConfirmTabContent.tsx` / `ScanTabContent.tsx` / `WorkbenchContext.tsx`. Rebase early; if E21-3 deletes `ConfirmTabContent.tsx` first, drop its migration row rather than resurrecting it.
- **URL params stay the source of truth** for `tab`/`panel`/`advanced` (`useTabParam`, `useOverlayParam`, `ADVANCED_PARAM`); the `?tab=confirm` legacy shim (`WorkbenchContext.tsx:151-165`, owned by E21-10) moves verbatim into the navigation provider.

## Workflow Principles

- Partition along the seams the dependency graph already shows, not invented layers: cluster-panel state and nav/config state have almost no edges into the rest — cut there first ([GRPH-06] connected components); the dense job-history↔state-machine coupling (callbacks `onScanComplete`→`rememberJob`, `onJobNotFound`→`forgetJob`, `WorkbenchContext.tsx:259-288`) is a high-conductance region that must stay in one provider ([GRPH-16] sparsify at low-conductance cuts).
- Selector hooks are the interface; providers are the hidden depth ([REF-18] deep modules). A consumer imports `useJobPipeline()`, never a context object.
- Characterize before moving ([TEST-01], [TEST-03]): every consumer keeps its existing test green across the migration; test mocks are updated, not deleted.
- Group, don't scatter (sr-008): within the pipeline provider, expose 2-3 cohesive typed objects (`scanRun`, `history`, actions) instead of 30 loose fields.

## Terminology

- **Provider group**: one React context + provider + selector hook covering one concern (e.g. media queue).
- **`ScanRunViewModel`**: typed object bundling the live-run presentation fields `ScanActionPanel` needs (status text, progress, batch run, stall/eta, error, sync flag).
- **Phase strategy map**: an enum-keyed `Record<Phase, PresentationEntry>` module replacing per-call-site switches ([REF-02], sr-007).

## Current State Analysis

Verified on `feature/e21-11` (forked from `main` 2026-07-14) with `grep -n`:

- `WorkbenchContextValue` = **60 fields** (`WorkbenchContext.tsx:57-131`, counted by interface members), grouped by comments into 7 concerns: Navigation (6), Job History (8), Selection (5), Filters & Media Queue (11), State Machine (21, incl. `handleSelectJobFromHistory`), Cluster Panels (7), Config/Env (2).
- **7 production consumers** of `useWorkbenchContext` (field counts destructured): `WorkbenchPage.tsx:41-53` (13), `workbench/ScanTabContent.tsx:40-56` (17), `workbench/ConfirmTabContent.tsx:8-22` (14), `workbench/MediaSelection.tsx:34-47` (13), `workbench/MediaAnalyzeCta.tsx:7` (6), `workbench/MediaSummaryBar.tsx:15` (3), `workbench/AdvancedDrawer.tsx:14` (2). **2 test mocks** stub the hook wholesale: `admin/__tests__/banned-vocabulary.test.tsx:293-294`, `workbench/__tests__/MediaAnalyzeCta.test.tsx:28`.
- Provider composition inputs already exist as hooks: `useRecognitionJobHistory`, `useMediaSelectionState`, `useWorkbenchFilters`, `useWorkbenchMedia`, `useJobStateMachine` — the provider glues them and re-broadcasts everything as one value.
- Cross-concern edges (the split constraints): state-machine callbacks write job history and messages (`WorkbenchContext.tsx:259-288`); `handleSelectJobFromHistory` (`:290-296`) couples history selection to `setAdvancedOpen` (navigation); `hasIdentities` (`:391`) derives from `mediaQuery` items; the media-page clamp effect (`:210-236`) couples filters to query results. Everything else is concern-local.
- `ScanActionPanel` takes **12 individual props** (`workbench/Panels.tsx:11-24`), all sourced from the same context in `ScanTabContent.tsx:97-114` (roadmap's "14 props" predates the WBUX-3 CTA extraction to `MediaAnalyzeCta`).
- Phase unions: `PipelinePhase = 'idle'|'scanning'|'clustering'|'projecting'` (`js/admin/hooks/jobStateMachineUtils.ts:4`); `JobProgress['phase'] = 'queued'|'detecting'|'clustering'|'retrying'|'awaiting_projection'|'failed'|'complete'` (`js/admin/api/generated/recognition-job.ts:6`). Remaining switch sites over them: `buildStatusText` (`jobStateMachineProgress.ts:19-…`, cognitive-complexity hotspot 24), `buildMilestones` (`JobTimeline.tsx:99-…`, hotspot 26), `formatSyncJobPhase` (`syncPresentation.ts:524-544`). `Panels.tsx:301` already delegates to `formatSyncJobPhase`; `SyncStatusIndicator.tsx:31-62` branches on E21-1's `SYNC_PRESENTATION_*` enums (in scope only if the map subsumes its tone mapping cheaply — default: leave it).
- Tests: `workbench/__tests__/` covers `JobTimeline`, `Panels`, `syncPresentation`, `SyncStatusIndicator`, `MediaAnalyzeCta`, `WorkbenchPage(.integration)` — a real bug detector exists ([TEST-01] satisfied). No dedicated `WorkbenchContext` test.
- `node_modules` is absent in this worktree — run `npm ci` in `apps/prototype-wp-alt-context` before any verification.

## Target Outcome

`WorkbenchContext.tsx` becomes a thin composition file exporting `WorkbenchProvider` (nesting four providers) and re-exporting nav constants. Four sibling modules own the concerns: navigation+config, media (selection+filters+queue), job pipeline (history+state machine+run messages), cluster panel. Each exposes exactly one selector hook; consumers destructure ≤8 fields per hook or take a grouped object (sr-008). `ScanActionPanel` receives one `scanRun: ScanRunViewModel` prop plus its two callbacks. One `phasePresentation.ts` module owns phase→presentation records; `buildStatusText`, `buildMilestones`, and `formatSyncJobPhase` read from it, so adding a phase edits one file. Zero rendered-output change.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`
- Epic: `docs/epics/v0.4.1/public-mvp-ux-polish-epic.md` (Phase 5 row); roadmap P5-A/P5-B (`docs/roadmaps/public-mvp-ux-polish-roadmap-2026-07-04.md`)
- Grounding: WBUX-1 §"God context" + S6 (`docs/assessments/current/workbench-ui-refactor-assessment-2026-07-04.md:136-137,266`)
- Handoff/MCP: task ref `E21-11`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Recognition job progress schema | backend (generated types) | `js/admin/api/generated/recognition-job.ts` | none — read-only consumption | yes — never edit generated files | `npm run typecheck` |
| Workbench URL params (`?tab=`, `?panel=`, `?advanced=`, legacy `?tab=confirm`) | frontend (E21-10 owns shim lifecycle) | `WorkbenchContext.tsx:19-30,151-165` | none — logic relocates verbatim into nav provider | yes — deep links must keep resolving | `WorkbenchPage.integration.test.tsx` |
| Internal context API (`useWorkbenchContext`) | frontend | monolithic hook | **deleted**, replaced by 4 selector hooks | no — internal-only surface, greenfield | typecheck + full vitest run |

## Proposed Solution

Split by connected components of the field-dependency graph ([GRPH-06]), keeping the dense history↔state-machine region intact ([GRPH-16]):

1. `WorkbenchNavContext` (8 fields): `activeSection`/`setActiveSection`, `activeOverlay`/`setActiveOverlay`, `isAdvancedOpen`/`setAdvancedOpen`, `recognitionSource`, `effectiveTargetUrl`; owns `TAB_IDS`, `ADVANCED_PARAM`, the `?tab=confirm` shim effect.
2. `WorkbenchMediaContext` (17 fields): selection (5) + filters/queue (11) + `hasIdentities`; owns the page-clamp and `knownTotalPages` effects and the `statusMessage`/`detailTruncationNotice` memos.
3. `JobPipelineContext`: job history (8) + state machine (21) + `scanError`/`setScanError` + `clusterMessage`/`setClusterMessage`; exposes grouped objects — `scanRun: ScanRunViewModel`, `history: JobHistoryModel`, and flat actions (`scan`, `cancelScan`, `cluster`, retries) — not 33 loose fields (sr-008). `handleSelectJobFromHistory` composes `selectJob` with `useWorkbenchNav().setAdvancedOpen` (provider nested inside nav).
4. `ClusterPanelContext` (2 fields): `clusterPanel` + `dispatchClusterPanel` (reducer moves whole, `WorkbenchContext.tsx:32-55`).

Nesting order in `WorkbenchProvider`: Nav → Media → JobPipeline → ClusterPanel (only pipeline reads an outer context). Each provider memoizes its own value, shrinking re-render blast radius per concern. Then one `phasePresentation.ts` strategy-map module ([REF-02], sr-007) keyed on `JobProgress['phase']` and `PipelinePhase`, consumed by the three switch sites. `ScanActionPanel` prop collapse rides the pipeline provider's `ScanRunViewModel`. Trade-off accepted ([ARCH-06]): four files + one composition file instead of one file — structure bought for per-concern re-renders and testability ([REF-17]).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `js/admin/pages/workbench/WorkbenchMediaContext.tsx` (new) | provider + `useWorkbenchMediaContext`: selection, filters, `mediaQuery`, clamp effects, `statusMessage`, `detailTruncationNotice`, `hasIdentities` |
| frontend | `js/admin/pages/workbench/WorkbenchNavContext.tsx` (new) | provider + `useWorkbenchNav`: tab/overlay/advanced params, config env, `?tab=confirm` shim, `TAB_IDS`/`ADVANCED_PARAM` constants |
| frontend | `js/admin/pages/workbench/JobPipelineContext.tsx` (new) | provider + `useJobPipeline`: `useRecognitionJobHistory` + `useJobStateMachine` glue, callbacks, `ScanRunViewModel`, run messages |
| frontend | `js/admin/pages/workbench/ClusterPanelContext.tsx` (new) | provider + `useClusterPanel`: reducer + state |
| frontend | `js/admin/pages/workbench/WorkbenchContext.tsx` | shrinks to `WorkbenchProvider` composition + re-exports; `WorkbenchContextValue`/`useWorkbenchContext` deleted by S2 |
| frontend | `js/admin/pages/WorkbenchPage.tsx:41-53` | consume `useWorkbenchNav` + `useJobPipeline` (+ `detailTruncationNotice` from media hook) |
| frontend | `js/admin/pages/workbench/ScanTabContent.tsx:40-56,97-114` | consume `useJobPipeline`/`useClusterPanel`/`useWorkbenchMediaContext`; pass `scanRun` to `ScanActionPanel` |
| frontend | `js/admin/pages/workbench/ConfirmTabContent.tsx:8-22` | consume `useJobPipeline` (skip if E21-3 deletes the file first) |
| frontend | `js/admin/pages/workbench/MediaSelection.tsx:34-47`, `MediaSummaryBar.tsx:15`, `MediaAnalyzeCta.tsx:7`, `AdvancedDrawer.tsx:14` | swap to the matching selector hooks |
| frontend | `js/admin/pages/workbench/Panels.tsx:11-39` | `ScanActionPanelProps` 12 props → `{ scanRun: ScanRunViewModel; onCancelScan?; onRetryStream? }` |
| frontend | `js/admin/pages/workbench/phasePresentation.ts` (new) | enum-keyed phase→presentation records; label/milestone/status-text fragments built on `SYNC_VOCABULARY` |
| frontend | `js/admin/hooks/jobStateMachineProgress.ts:19`, `js/admin/pages/workbench/JobTimeline.tsx:99`, `js/admin/pages/workbench/syncPresentation.ts:524` | consume the strategy map; delete inline switch bodies |
| tests | `js/admin/__tests__/banned-vocabulary.test.tsx:293`, `workbench/__tests__/MediaAnalyzeCta.test.tsx:28`, `workbench/__tests__/Panels.test.tsx`, `workbench/__tests__/JobTimeline.test.tsx`, `workbench/__tests__/syncPresentation.test.ts` | re-point mocks/fixtures at the new hooks/props; assertions unchanged in intent |
| docs | `docs/workbay/maps/frontend.md:27` | replace the `WorkbenchContext` row with the four provider modules + `phasePresentation.ts` |

## Related Files

| File | Note |
| --- | --- |
| `js/admin/hooks/useJobStateMachine.ts`, `useJobStateMachineDerivedState.ts` | provider input; `buildStatusText` caller at `useJobStateMachineDerivedState.ts:44` |
| `js/admin/hooks/useWorkbenchMedia.ts`, `useWorkbenchFilters.ts`, `useMediaSelectionState.ts`, `useRecognitionJobHistory.ts` | unchanged concern hooks the providers wrap |
| `js/admin/pages/workbench/SyncStatusIndicator.tsx:31-62` | already consumes E21-1 enums; out of scope unless the map subsumes tone branches for free |
| `js/admin/pages/workbench/identity-clusters/WorkbenchFindingsPanel.tsx` | receives `dispatchClusterPanel` via props from `ScanTabContent` — prop seam unchanged |
| `docs/tasks/21.0/E21-3-confirm-tab-removal-task-plan.md` | overlapping surface; rebase checkpoint before S2 |

## Verification Strategy

- Deterministic tests (from `apps/prototype-wp-alt-context/`; run `npm ci` first — worktree has no `node_modules`):
  - `node_modules/.bin/vitest run`
  - `npm run typecheck`
  - `node_modules/.bin/eslint js/admin/pages/workbench js/admin/pages/WorkbenchPage.tsx js/admin/hooks/jobStateMachineProgress.ts`
- Contract/fixture verification:
  - `git diff --stat js/admin/api/generated/` is empty (generated types untouched)
  - grep gate after S3: `grep -rn "case 'detecting'\|case 'awaiting_projection'" js/admin --include='*.ts*' | grep -v phasePresentation` returns only test fixtures
- Runtime-parity / manual:
  - Workbench loads with scan → cluster flow visually unchanged (spot-check on local WP); `?tab=confirm` still redirects to scan + open drawer

## Slice Delivery

### Slice 1: Media provider extraction (characterized)

**Goal**: `WorkbenchMediaContext` owns selection/filters/queue behind `useWorkbenchMediaContext`, with all existing tests green.

Changes:

- New `WorkbenchMediaContext.tsx` (provider + hook + `WorkbenchMediaContextValue`, 17 fields incl. `hasIdentities`); clamp/`knownTotalPages` effects and `statusMessage`/`detailTruncationNotice` memos move whole.
- `WorkbenchProvider` nests the new provider; the 17 fields are deleted from `WorkbenchContextValue` (no dual surface).
- Migrate `MediaSelection.tsx`, `MediaSummaryBar.tsx`, and the media slice of `MediaAnalyzeCta.tsx` (`selectedMedia`); update `banned-vocabulary.test.tsx` + `MediaAnalyzeCta.test.tsx` mocks.

Proof:

- `node_modules/.bin/vitest run` + `npm run typecheck` green; `grep -n "selectedMedia\|mediaQuery" js/admin/pages/workbench/WorkbenchContext.tsx` empty.

### Slice 2: Pipeline, nav, cluster-panel providers + composition

**Goal**: monolithic `WorkbenchContextValue`/`useWorkbenchContext` deleted; four providers compose; `ScanActionPanel` takes `ScanRunViewModel`.

Changes:

- New `JobPipelineContext.tsx` (history + state machine + callbacks + `scanError`/`clusterMessage`; grouped exposure: `scanRun: ScanRunViewModel`, `history`, actions), `WorkbenchNavContext.tsx` (nav + config + `?tab=confirm` shim), `ClusterPanelContext.tsx` (reducer).
- `WorkbenchContext.tsx` → composition-only `WorkbenchProvider` (Nav → Media → JobPipeline → ClusterPanel) + constant re-exports; `useWorkbenchContext` removed.
- Migrate `WorkbenchPage.tsx`, `ScanTabContent.tsx`, `ConfirmTabContent.tsx` (if still present), `AdvancedDrawer.tsx`, remainder of `MediaAnalyzeCta.tsx`; `Panels.tsx` `ScanActionPanelProps` → `{ scanRun, onCancelScan?, onRetryStream? }`; update `Panels.test.tsx` fixtures.

Proof:

- Full vitest + typecheck + eslint green; `grep -rn "useWorkbenchContext" js/admin` returns nothing; no consumer destructures >8 fields from any single hook (sr-008 spot-check in review).

### Slice 3: Phase→presentation strategy map + sweep

**Goal**: one module owns phase presentation; the three switch sites read from it; docs map updated.

Changes:

- New `phasePresentation.ts`: records keyed on `JobProgress['phase']` and `PipelinePhase`, entries built from `SYNC_VOCABULARY`; unit test asserting exhaustiveness over both unions (sr-005 assertion helper for unreachable branch).
- Refactor `buildStatusText` (`jobStateMachineProgress.ts:19`), `buildMilestones` (`JobTimeline.tsx:99`), `formatSyncJobPhase` (`syncPresentation.ts:524`) to lookups; existing tests (`JobTimeline.test.tsx`, `syncPresentation.test.ts`) pin outputs unchanged ([TEST-03]).
- Consumer sweep: grep gate for stray phase-literal switches outside the map; update `docs/workbay/maps/frontend.md:27` with the provider + map layout.

Proof:

- Full vitest + typecheck + eslint green; grep gate from Verification Strategy passes; `git diff --stat js/admin/api/generated/` empty.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried live via `review_findings(review={"operation":"list","status":"open","task_ref":"E21-11"})`.

## Context and Ownership

- [ ] Loaded frontend guidelines, testing-typescript rules, WBUX-1 S6, and roadmap P5-A/P5-B before editing.
- [ ] Confirmed no generated-type or backend-contract surface is modified.

### Checklist for Slice 1: Media provider extraction

- [ ] `WorkbenchMediaContext.tsx` created; 17 fields moved and deleted from the monolith.
- [ ] `MediaSelection`/`MediaSummaryBar`/`MediaAnalyzeCta` (media slice) migrated; both test mocks updated.
- [ ] vitest + typecheck + eslint evidence recorded as `test_result` on current HEAD SHA.

### Checklist for Slice 2: Pipeline, nav, cluster-panel providers + composition

- [ ] `JobPipelineContext.tsx` / `WorkbenchNavContext.tsx` / `ClusterPanelContext.tsx` created; `useWorkbenchContext` deleted repo-wide.
- [ ] `ScanActionPanel` consumes `ScanRunViewModel`; `Panels.test.tsx` fixtures updated.
- [ ] All seven consumers migrated (or E21-3 deletion of `ConfirmTabContent` acknowledged); full suite evidence recorded.

### Checklist for Slice 3: Phase strategy map + sweep

- [ ] `phasePresentation.ts` with exhaustiveness test; three switch sites converted.
- [ ] Grep gate for stray phase switches passes; `docs/workbay/maps/frontend.md` updated.
- [ ] Full suite evidence recorded; slice-complete decision logged.

## Review Readiness

- [ ] No boundary-touching implementation left without matching doc/fixture evidence (generated types untouched, URL-param behavior pinned by integration test).
- [ ] Runtime-parity spot-check (Workbench flow + `?tab=confirm` shim) noted in handoff, since unit tests can mask provider-nesting mistakes.
- [ ] Handoff decision records the decomposition shape, provider nesting order, and trade-offs ([ARCH-07]).

## Stretch Goals

- [ ] Fold `SyncStatusIndicator.tsx:31-62` tone/status branches into the strategy map if it falls out for free.
- [ ] Per-provider render-count test (React Profiler) demonstrating the reduced re-render blast radius.

## Success Criteria

- [ ] `useWorkbenchContext` no longer exists; four selector hooks cover all seven former concerns; no single hook destructure exceeds 8 fields at any call site (sr-008).
- [ ] `ScanActionPanel` receives one `ScanRunViewModel` instead of 12 loose props.
- [ ] Adding a hypothetical pipeline phase requires editing only `phasePresentation.ts` (plus the owning union) — verified by the grep gate.
- [ ] `vitest run`, `npm run typecheck`, and eslint on touched files pass; rendered Workbench output unchanged.
