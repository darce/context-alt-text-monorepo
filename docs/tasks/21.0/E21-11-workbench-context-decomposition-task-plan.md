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

Decompose the 60-field `WorkbenchContextValue` god context into four per-concern providers behind selector hooks (sr-008), collapse 10 of `ScanActionPanel`'s 12 loose props into one `ScanRunViewModel` (the `onCancelScan`/`onRetryStream` callbacks stay loose props), and replace the remaining pipeline-phase presentation switches with a single enum-keyed phase→presentation strategy map (sr-007, [REF-02]). Behavior-preserving, visitor-invisible (epic Phase 5 / roadmap P5-A + P5-B).

## Problem Statement

`WorkbenchContextValue` (`js/admin/pages/workbench/WorkbenchContext.tsx:57-131`) exposes **60 fields** spanning seven commented concerns (Navigation, Job History, Selection, Filters & Media Queue, State Machine, Cluster Panels, Config/Env) through one context. Every consumer re-renders on any change, the provider's `useMemo` carries a 57-entry dependency array (`WorkbenchContext.tsx:395-453`), and any UI regroup must touch the god object — WBUX-1 §"God context" diagnosis, still live on `main`. Consumers destructure up to 20 fields at once (`ScanTabContent.tsx:35-56`), violating sr-008. Separately, pipeline-phase presentation is shotgun-surgery territory ([REF-19] information leakage): adding or renaming a phase touches `buildStatusText` (`js/admin/hooks/jobStateMachineProgress.ts:19`), `buildMilestones` (`js/admin/pages/workbench/JobTimeline.tsx:99`), and `formatSyncJobPhase` (`js/admin/pages/workbench/syncPresentation.ts:524`) — three independent switch/branch chains over the same two phase unions.

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
- **`ScanRunViewModel`**: typed object bundling the live-run presentation fields `ScanActionPanel` needs (status text, progress, batch run, stall/eta, error, sync flag). It also absorbs the two derivations currently inlined at the call site: the active-progress ternary (`clusterProgress` when `currentPhase` is `'clustering'|'projecting'` and cluster progress exists, else `scanProgress` — `ScanTabContent.tsx:104-108`) and `isSynced = !isPrimary && !!latestJobId` (`ScanTabContent.tsx:113`).
- **Phase strategy map**: an enum-keyed `Record<Phase, PresentationEntry>` module replacing per-call-site switches ([REF-02], sr-007).
- **`PresentationEntry`**: the per-phase value in each record — a static `label: string` (milestone/phase copy) **plus parametrized status builders** for count-bearing copy, e.g. `type PhaseStatusBuilder = (p: { completed: number; total: number; facesFound?: number }) => string`. The map owns every phase-derived user-facing string: both `'detecting'` variants (with and without `faces_found`, currently `jobStateMachineProgress.ts:61-72`), the `'queued'` count line (`:58-60`), and the `'awaiting_projection'` copy (`:36-38`). Dynamic counts arrive only through builder params — never via string literals at the call site.
- **Two phase domains** (both stay): the generated `JobProgress['phase']` union (`js/admin/api/generated/recognition-job.ts:6`) is canonical for backend-reported phases; `PipelinePhase` (`js/admin/hooks/jobStateMachineUtils.ts:4`) is the client state machine's union. `phasePresentation.ts` keys one record per union. The overlapping `'clustering'` member gets a consistent label because both records' entries reference the same shared vocabulary constant (`SYNC_VOCABULARY.clusteringHeadline` / `SYNC_VOCABULARY.phaseClustering`, `syncPresentation.ts:96-…`) rather than duplicating strings. The exhaustiveness test covers **both** records via `satisfies Record<Union, PresentationEntry>` on each.

## Current State Analysis

Verified on `feature/e21-11` (forked from `main` 2026-07-14) with `grep -n`:

- `WorkbenchContextValue` = **60 fields** (`WorkbenchContext.tsx:57-131`, counted by interface members), grouped by comments into 7 concerns: Navigation (6), Job History (8), Selection (5), Filters & Media Queue (11), State Machine (21, incl. `handleSelectJobFromHistory`), Cluster Panels (7), Config/Env (2).
- **7 production consumers** of `useWorkbenchContext` (field counts destructured): `WorkbenchPage.tsx:38-53` (14, incl. `detailTruncationNotice` at `:52`), `workbench/ScanTabContent.tsx:35-56` (20, incl. `isScanRunning`/`isCancellingScan`/`statusText`/`jobId` at `:36-39` and `hasIdentities` at `:50`), `workbench/ConfirmTabContent.tsx:8-22` (14), `workbench/MediaSelection.tsx:34-47` (13), `workbench/MediaAnalyzeCta.tsx:7` (6), `workbench/MediaSummaryBar.tsx:15` (3), `workbench/AdvancedDrawer.tsx:14` (2). **2 test mocks** stub the hook wholesale: `admin/__tests__/banned-vocabulary.test.tsx:293-294`, `workbench/__tests__/MediaAnalyzeCta.test.tsx:28`.
- Provider composition inputs already exist as hooks: `useRecognitionJobHistory`, `useMediaSelectionState`, `useWorkbenchFilters`, `useWorkbenchMedia`, `useJobStateMachine` — the provider glues them and re-broadcasts everything as one value.
- Cross-concern edges (the split constraints): state-machine callbacks write job history and messages (`WorkbenchContext.tsx:259-288`); `handleSelectJobFromHistory` (`:290-296`) couples history selection to `setAdvancedOpen` (navigation); `hasIdentities` (`:391`) derives from `mediaQuery` items; the media-page clamp effect (`:210-236`) couples filters to query results. Everything else is concern-local.
- `ScanActionPanel` takes **12 individual props** (`workbench/Panels.tsx:11-24`), all sourced from the same context in `ScanTabContent.tsx:97-114` (roadmap's "14 props" predates the WBUX-3 CTA extraction to `MediaAnalyzeCta`). **10 of the 12 collapse** into `ScanRunViewModel`; `onCancelScan`/`onRetryStream` stay loose callback props. The call site also computes two derivations the view model must carry: the `clusterProgress`-vs-`scanProgress` ternary (`ScanTabContent.tsx:104-108`) and `isSynced` (`:113`).
- Phase unions: `PipelinePhase = 'idle'|'scanning'|'clustering'|'projecting'` (`js/admin/hooks/jobStateMachineUtils.ts:4`); `JobProgress['phase'] = 'queued'|'detecting'|'clustering'|'retrying'|'awaiting_projection'|'failed'|'complete'` (`js/admin/api/generated/recognition-job.ts:6`). Remaining switch sites over them: `buildStatusText` (`jobStateMachineProgress.ts:19-…`, cognitive-complexity hotspot 24), `buildMilestones` (`JobTimeline.tsx:99-…`, hotspot 26), `formatSyncJobPhase` (`syncPresentation.ts:524-544`). `Panels.tsx:301` already delegates to `formatSyncJobPhase`; `SyncStatusIndicator.tsx:31-62` branches on E21-1's `SYNC_PRESENTATION_*` enums (in scope only if the map subsumes its tone mapping cheaply — default: leave it).
- **Behavioral phase comparisons (out of S3 scope)** — these sites branch on phase to drive *behavior* (job-id resolution, cleanup effects, progress selection, stall gating), not to render strings, and legitimately remain after S3: `jobStateMachineUtils.ts:38` + `:71-76` (job-id resolution / phase derivation), `jobStateMachineProgress.ts:110,125,153,185,191` (progress-selection and completion guards outside `buildStatusText`); **inside `buildStatusText` itself the cross-signal precedence comparisons also stay** — the `clusterPending || sseProgress?.phase === 'clustering'` ordering (`jobStateMachineProgress.ts:29`), the dual-source `sseProgress?.phase === 'awaiting_projection' || scanStatus?.progress?.phase === 'awaiting_projection'` check (`:36`), the `batchRunStatus` submitted/failed/terminal count branches (`:40-56`), the terminal `sseStatus` handling (`isScanSuccessStatus` / `'failed'`, `:74-78`), and the `scanStatus.message` fallbacks (`:80-93`) — these select *which signal wins*, not what the string says; S3 replaces only their string-producing bodies with `PresentationEntry` lookups/builders. Also behavioral: `useJobStateMachineEffects.ts:80,155` (backend-clustering detection, terminal-cleanup effect), `useJobStateMachineDerivedState.ts:100` (stall gating on `'idle'`), `useRecognitionHooks.ts:34` (`isAwaitingProjection` poll gate), `JobTimeline.tsx:29,70,92,110,120-130,155` (milestone-progression booleans; only its label strings move to the map), `Panels.tsx:10` (`isClusteringActive`; the Retry-count line's gating still uses it — the processed line + progress aria-label now read `JOB_PHASE_PRESENTATION` directly), `syncPresentation.ts:240,262,272` (E21-1's canonical `buildSyncPresentation`, per Constraints), and the S2-relocated active-progress ternary `JobPipelineContext.tsx:149` (formerly `MediaAnalyzeCta.tsx:10` + `ScanTabContent.tsx:105`; a move, not a phase-presentation conversion). The widened gate's `case 'queued'` alternation also matches the **`SyncHealth`** union switches — `syncPresentation.ts:373,422` (`getSyncPresentation`/`getSyncPresentationSummary`) and `degradedModeBannerLogic.ts:31` (`getDashboardSyncHealthSummary`) — those are health-derived, not phase-derived, and are out of scope for the phase map. Verified with `grep -n` on `feature/e21-11` 2026-07-14 (post-review-fold sweep); re-verify before relying on line anchors.
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
2. `WorkbenchMediaContext` (17 fields, exposed as **three cohesive typed objects** so no consumer destructure exceeds 8 fields even in S1, sr-008): `selection` = { `selection`, `selectedMedia`, `toggleRow`, `toggleAll`, `isPageFullySelected` } (5); `filters` = { `searchQuery`, `statusFilter`, `currentPage`, `perPage`, `handleSearchChange`, `handleStatusChange`, `setCurrentPage`, `setPerPage` } (8); `mediaQueue` = { `mediaQuery`, `statusMessage`, `detailTruncationNotice`, `hasIdentities` } (4). Field names per `WorkbenchContext.tsx:57-131` concern comments. Owns the page-clamp and `knownTotalPages` effects and the `statusMessage`/`detailTruncationNotice` memos.
3. `JobPipelineContext`: job history (8) + state machine (21) + `scanError`/`setScanError` + `clusterMessage`/`setClusterMessage`; exposes grouped objects — `scanRun: ScanRunViewModel`, `history: JobHistoryModel`, and flat actions (`scan`, `cancelScan`, `cluster`, retries) — not 33 loose fields (sr-008). `handleSelectJobFromHistory` composes `selectJob` with `useWorkbenchNav().setAdvancedOpen` (provider nested inside nav).
4. `ClusterPanelContext` (2 fields): `clusterPanel` + `dispatchClusterPanel` (reducer moves whole, `WorkbenchContext.tsx:32-55`).

Nesting order in `WorkbenchProvider`: Nav → Media → JobPipeline → ClusterPanel (only pipeline reads an outer context). Each provider memoizes its own value, shrinking re-render blast radius per concern. Then one `phasePresentation.ts` strategy-map module ([REF-02], sr-007) keyed on `JobProgress['phase']` and `PipelinePhase`, consumed by the three switch sites. `ScanActionPanel` prop collapse rides the pipeline provider's `ScanRunViewModel`. Trade-off accepted ([ARCH-06]): four files + one composition file instead of one file — structure bought for per-concern re-renders and testability ([REF-17]).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `js/admin/pages/workbench/WorkbenchMediaContext.tsx` (new) | provider + `useWorkbenchMediaContext` exposing grouped `selection`/`filters`/`mediaQueue` objects (see Proposed Solution 2); clamp effects, `statusMessage`, `detailTruncationNotice`, `hasIdentities` |
| frontend | `js/admin/pages/workbench/WorkbenchNavContext.tsx` (new) | provider + `useWorkbenchNav`: tab/overlay/advanced params, config env, `?tab=confirm` shim, `TAB_IDS`/`ADVANCED_PARAM` constants |
| frontend | `js/admin/pages/workbench/JobPipelineContext.tsx` (new) | provider + `useJobPipeline`: `useRecognitionJobHistory` + `useJobStateMachine` glue, callbacks, `ScanRunViewModel`, run messages |
| frontend | `js/admin/pages/workbench/ClusterPanelContext.tsx` (new) | provider + `useClusterPanel`: reducer + state |
| frontend | `js/admin/pages/workbench/WorkbenchContext.tsx` | shrinks to `WorkbenchProvider` composition + re-exports; `WorkbenchContextValue`/`useWorkbenchContext` deleted by S2 |
| frontend | `js/admin/pages/WorkbenchPage.tsx:38-53` | S1: swap only `detailTruncationNotice` (`:52`) to `useWorkbenchMediaContext().mediaQueue`; S2: consume `useWorkbenchNav` + `useJobPipeline` for the remaining 13 fields |
| frontend | `js/admin/pages/workbench/ScanTabContent.tsx:35-56,97-114` | S1: swap only `hasIdentities` (`:50`) to `useWorkbenchMediaContext().mediaQueue`; S2: consume `useJobPipeline`/`useClusterPanel` for the remaining 19 fields; pass `scanRun` to `ScanActionPanel` |
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
  - grep gate after S3: `grep -rnE "[Pp]hase(\?)? === '|case '(queued|detecting|clustering|retrying|awaiting_projection|failed|complete|idle|scanning|projecting)'" js/admin --include='*.ts*' | grep -v -e phasePresentation -e __tests__` (case alternation enumerates every member of both phase unions — `JobProgress['phase']` and `PipelinePhase`) — every remaining hit must be a *behavioral* phase comparison on the out-of-scope list in Current State Analysis (or its S2-relocated equivalent inside the pipeline provider). Gate contract: phase comparisons may remain for **precedence** (`buildStatusText` keeps its cross-signal ordering per the out-of-scope list), but any phase-derived user-facing **string literal** inside a comparison's body is a violation — move the string into `phasePresentation.ts` and call the entry's builder. The location grep alone cannot distinguish precedence from presentation (the current `buildStatusText` body *would* survive it), so the gate's second step inspects each surviving hit's case/ternary/return body for string literals (`__(`/`sprintf(` inside the branch); a literal-bearing body fails the gate.
- Runtime-parity / manual:
  - Workbench loads with scan → cluster flow visually unchanged (spot-check on local WP); `?tab=confirm` still redirects to scan + open drawer

## Slice Delivery

### Slice 1: Media provider extraction (characterized)

**Goal**: `WorkbenchMediaContext` owns selection/filters/queue behind `useWorkbenchMediaContext`, with all existing tests green.

Changes:

- New `WorkbenchMediaContext.tsx` (provider + hook + `WorkbenchMediaContextValue` with grouped `selection`/`filters`/`mediaQueue` objects per Proposed Solution 2, 17 fields incl. `hasIdentities`); clamp/`knownTotalPages` effects and `statusMessage`/`detailTruncationNotice` memos move whole.
- `WorkbenchProvider` nests the new provider; the 17 fields are deleted from `WorkbenchContextValue` (no dual surface).
- Migrate the media-only consumers wholesale: `MediaSelection.tsx:34-47`, `MediaSummaryBar.tsx:15`, and the media slice of `MediaAnalyzeCta.tsx` (`selectedMedia`).
- Mock fan-out for the two wholesale stubs: in **both** test files, add a `vi.mock` of the new `WorkbenchMediaContext` module *alongside* the existing `WorkbenchContext` module mock — the hook returns the grouped stub (`{ selection, filters, mediaQueue }`) and the provider is a children passthrough. `banned-vocabulary.test.tsx` (mock at `:219-296`) moves the 17 media fields out of its `useWorkbenchContext` stub into the new mock, keeping the `WorkbenchProvider` passthrough at `:293`; `MediaAnalyzeCta.test.tsx` (mock at `:27-29`) moves `selectedMedia` into a media-module mock and keeps its remaining fields (`isScanRunning`, `scanProgress`, `clusterProgress`, `currentPhase`, `scan`) on the `WorkbenchContext` mock until S2.
- **Partial migration of two S2-scheduled consumers** (required for S1 to typecheck — they destructure moved fields): `ScanTabContent.tsx` swaps `hasIdentities` (`:50`) to `useWorkbenchMediaContext().mediaQueue.hasIdentities`; `WorkbenchPage.tsx` swaps `detailTruncationNotice` (`:52`) to `useWorkbenchMediaContext().mediaQueue.detailTruncationNotice`. Each imports the media hook for just that field in S1; their remaining `useWorkbenchContext()` destructures are untouched until S2.
- **Transitional state after S1** (intentional, one slice only): `WorkbenchContext.tsx` still exports `WorkbenchContextValue`/`useWorkbenchContext` with the 43 non-media fields, and `ScanTabContent`/`WorkbenchPage`/`MediaAnalyzeCta` consume both hooks side by side. The two wholesale test stubs mirror this: each file carries two module mocks side by side (43-field monolith stub + grouped media stub), so the transitional boundary is genuinely green under test, not just under typecheck. The tree compiles and the full vitest suite is green at the S1 boundary; S2 deletes the monolith and fans the mocks out.

Proof:

- `node_modules/.bin/vitest run` + `npm run typecheck` green at the S1 commit; `grep -n "selectedMedia\|mediaQuery\|hasIdentities\|detailTruncationNotice" js/admin/pages/workbench/WorkbenchContext.tsx` empty.

### Slice 2: Pipeline, nav, cluster-panel providers + composition

**Goal**: monolithic `WorkbenchContextValue`/`useWorkbenchContext` deleted; four providers compose; `ScanActionPanel` takes `ScanRunViewModel`.

Changes:

- New `JobPipelineContext.tsx` (history + state machine + callbacks + `scanError`/`clusterMessage`; grouped exposure: `scanRun: ScanRunViewModel`, `history`, actions), `WorkbenchNavContext.tsx` (nav + config + `?tab=confirm` shim), `ClusterPanelContext.tsx` (reducer).
- `WorkbenchContext.tsx` → composition-only `WorkbenchProvider` (Nav → Media → JobPipeline → ClusterPanel) + constant re-exports; `useWorkbenchContext` removed.
- Migrate the remaining monolith fields of `WorkbenchPage.tsx` (13) and `ScanTabContent.tsx` (19, media field already swapped in S1), plus `ConfirmTabContent.tsx` (if still present), `AdvancedDrawer.tsx`, remainder of `MediaAnalyzeCta.tsx`; `Panels.tsx` `ScanActionPanelProps` 12 props → `{ scanRun: ScanRunViewModel; onCancelScan?; onRetryStream? }` (the two callbacks stay loose); `ScanRunViewModel` absorbs the active-progress ternary and `isSynced` derivation from `ScanTabContent.tsx:104-113`; update `Panels.test.tsx` fixtures.
- Test-mock fan-out completes: the page-sweep suite (`banned-vocabulary.test.tsx`) replaces the monolith stub with **one `vi.mock` per provider module — four total** (nav, media, pipeline, cluster-panel; media's landed in S1). Chosen over mounting the real composed providers with data-layer mocks: the sweep only asserts stable copy on screen, so module mocks keep it decoupled from provider wiring and cheap to maintain. The narrow-slice suite (`MediaAnalyzeCta.test.tsx`) points its remaining fields (`isScanRunning`, `scanProgress`, `clusterProgress`, `currentPhase`, `scan`) at the pipeline-module mock and drops the `WorkbenchContext` mock.

Proof:

- Full vitest + typecheck + eslint green; `grep -rn "useWorkbenchContext" js/admin` returns nothing; no consumer destructures >8 fields from any single hook (sr-008 spot-check in review).

### Slice 3: Phase→presentation strategy map + sweep

**Goal**: one module owns phase presentation; the three switch sites read from it; docs map updated.

Changes:

- New `phasePresentation.ts`: **two** records — one keyed on `JobProgress['phase']`, one on `PipelinePhase` (see Terminology: two phase domains) — each typed with `satisfies Record<Union, PresentationEntry>` so exhaustiveness is compile-checked for both; entries built from `SYNC_VOCABULARY` (shared `'clustering'` label); unit test asserting exhaustiveness over both unions (sr-005 assertion helper for unreachable branch).
- Refactor the three sites to map reads; existing tests (`JobTimeline.test.tsx`, `syncPresentation.test.ts`) pin outputs unchanged ([TEST-03]):
  - `buildStatusText` (`jobStateMachineProgress.ts:20`) keeps its cross-signal precedence skeleton verbatim — clustering ordering (`:29`), dual-source awaiting_projection check (`:36`), batch-run count branches (`:40-56`), terminal `sseStatus` handling (`:74-78`), `scanStatus.message` fallbacks (`:80-93`); that is behavior, not presentation, and is not converted to map dispatch. Every string-producing branch body becomes a `PresentationEntry` lookup or `PhaseStatusBuilder` call: both `'detecting'` variants, the `'queued'` count line, and the `'awaiting_projection'` copy move into `phasePresentation.ts`.
  - `buildMilestones` (`JobTimeline.tsx:99`): milestone label strings read from the `PipelinePhase` record; progression booleans stay.
  - `formatSyncJobPhase` (`syncPresentation.ts:524`) **keeps the wide `(phase: string): string` signature and the unknown-phase passthrough** (default arm at `:540-541`) — the exported contract is exercised by `syncPresentation.test.ts:202-205` and the sole production caller narrows at its own seam (`Panels.tsx:301`). Implement as `PHASE_PRESENTATION[phase as JobProgress['phase']]?.label ?? phase`. Narrowing the export surface is out of scope.
- Consumer sweep: run the widened grep gate from Verification Strategy; confirm every leftover hit is on the behavioral out-of-scope list in Current State Analysis (re-verify each line anchor first — E21-3/E21-5/E21-7 touch the same files). Behavioral phase comparisons are not converted. Update `docs/workbay/maps/frontend.md:27` with the provider + map layout.

Proof:

- Full vitest + typecheck + eslint green; grep gate from Verification Strategy passes; `git diff --stat js/admin/api/generated/` empty.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried live via `review_findings(review={"operation":"list","status":"open","task_ref":"E21-11"})`.

## Context and Ownership

- [ ] Loaded frontend guidelines, testing-typescript rules, WBUX-1 S6, and roadmap P5-A/P5-B before editing.
- [ ] Confirmed no generated-type or backend-contract surface is modified.

### Checklist for Slice 1: Media provider extraction

- [x] `WorkbenchMediaContext.tsx` created with grouped `selection`/`filters`/`mediaQueue` shape; 17 fields moved and deleted from the monolith.
- [x] `MediaSelection`/`MediaSummaryBar`/`MediaAnalyzeCta` (media slice) migrated; both test mocks updated.
- [x] Partial S1 swaps landed: `ScanTabContent` (`hasIdentities`) and `WorkbenchPage` (`detailTruncationNotice`) read the media hook; monolith compiles with 43 remaining fields.
- [ ] vitest + typecheck + eslint evidence recorded as `test_result` on current HEAD SHA.

### Checklist for Slice 2: Pipeline, nav, cluster-panel providers + composition

- [x] `JobPipelineContext.tsx` / `WorkbenchNavContext.tsx` / `ClusterPanelContext.tsx` created; `useWorkbenchContext` deleted repo-wide.
- [x] `ScanActionPanel` consumes `ScanRunViewModel`; `Panels.test.tsx` fixtures updated.
- [x] All seven consumers migrated (or E21-3 deletion of `ConfirmTabContent` acknowledged); full suite evidence recorded.

### Checklist for Slice 3: Phase strategy map + sweep

- [x] `phasePresentation.ts` with exhaustiveness test; three switch sites converted.
- [x] Grep gate for stray phase switches passes; `docs/workbay/maps/frontend.md` updated.
- [x] Full suite evidence recorded; slice-complete decision logged.

## Review Readiness

- [ ] No boundary-touching implementation left without matching doc/fixture evidence (generated types untouched, URL-param behavior pinned by integration test).
- [ ] Runtime-parity spot-check (Workbench flow + `?tab=confirm` shim) noted in handoff, since unit tests can mask provider-nesting mistakes.
- [ ] Handoff decision records the decomposition shape, provider nesting order, and trade-offs ([ARCH-07]).

## Stretch Goals

- [ ] Fold `SyncStatusIndicator.tsx:31-62` tone/status branches into the strategy map if it falls out for free.
- [ ] Per-provider render-count test (React Profiler) demonstrating the reduced re-render blast radius.

## Success Criteria

- [ ] `useWorkbenchContext` no longer exists; four selector hooks cover all seven former concerns; no single hook destructure exceeds 8 fields at any call site (sr-008).
- [ ] `ScanActionPanel` receives one `ScanRunViewModel` (carrying the active-progress and `isSynced` derivations) plus the two loose callbacks, replacing 10 of its 12 loose props.
- [ ] Changing phase **presentation** (labels, milestones, status text) for a hypothetical new phase requires editing only `phasePresentation.ts` (plus the owning union) — verified by the widened grep gate. Behavioral phase comparisons (the out-of-scope list in Current State Analysis) are explicitly exempt and still require their own edits for new-phase *behavior*.
- [ ] `vitest run`, `npm run typecheck`, and eslint on touched files pass; rendered Workbench output unchanged.
