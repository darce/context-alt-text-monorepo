# Scope: Workbench clustering UI latency, monotonic progress, and projection refresh

> **Date:** 2026-05-12  
> **Status:** scoped issue after code/literature assessment  
> **Surface:** `Analyze selected media` in the Workbench scan tab, follow-up clustering, LocalWP projection, and naming queue refresh  
> **Requested symptom:** slow after sending images for analysis; counts are not monotonic; progress does not reflect reality; clusterings appear suddenly or only after page refresh.  
> **Scope skill note:** this is a bug/performance assessment traced to concrete code, so the question-first intake path is skipped. Attempted MCP decision logging was unavailable in that session; the repo runtime contract is repo-local `.task-state/`, not `/.task-state`.

## Intake boundary

The issue is not "make clustering generally better." The scoped issue is: after the operator clicks `Analyze selected media`, the Workbench must present one coherent, monotonic pipeline from image submission through scan, clustering, projection, and cluster-review availability.

The MVP should make the UI truthful and fast enough locally without undoing the BR-21 backend stability work in [e15-3a-br21-clustering-stability-scope.md](./e15-3a-br21-clustering-stability-scope.md). The existing BR-21 route-boundary bulkhead and fail-fast job admission remain valid; this scope is the UX/projection/progress contract around that backend.

## Literature basis

- Latency must be treated as cause-to-visible-effect, not just backend runtime; Enberg explicitly frames latency around the user's observed effect and measurement as a distribution (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:55`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:401`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:402`).
- The Workbench is now a composite data system: backend jobs, WordPress batch-run state, SSE, and local projection. DDIA's cache/index warning applies directly: the application owns keeping derived data current and making guarantees visible to clients (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:884`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:902`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:906`).
- A slow response can be worse than no response because blocked resources reduce capacity and hide failure mode (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:1925`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:1929`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:1932`).
- Refactor in small controlled steps, because this touches scan submission, SSE, WordPress projection, and React Query state (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:293`, `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:295`, `literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:331`, `literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:417`).
- Do not rely on "refresh fixes it" behavior. The TypeScript refactoring text calls out browser refresh masking slow/clunky state as a quality smell (`literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:409`).
- The UI must reduce ambiguity: the important state is not every raw job counter, but which pipeline stage is active and what will make clusters visible. Refactoring UI's hierarchy guidance supports treating supporting labels as secondary to the main state (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:614`, `literature/extracted/refactoring/Refactoring-UI.txt:639`).

## Root cause assessment

### RC-1: Submission is serial and capped at five images per request

`scanFacesBatched()` chunks selected media and sends each batch in a `for ... await` loop (`apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts:64`, `apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts:85`, `apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts:87`). `getEffectiveBatchSize()` then caps batches at `MULTIPART_MAX_IMAGES = 5` despite config text saying batch limits were effectively disabled (`apps/prototype-wp-alt-context/js/admin/api/recognition/scanBatchHelpers.ts:3`, `apps/prototype-wp-alt-context/js/admin/api/recognition/scanBatchHelpers.ts:5`, `apps/prototype-wp-alt-context/js/admin/api/config.ts:28`).

This makes local throughput sensitive to request count: 100 images means 20 serial WordPress REST submissions before the scan worker or clustering progress can feel real. That explains much of "used to be faster locally" after the transport/projection architecture changed.

### RC-2: The UI synthesizes progress from competing sources

The Workbench combines active local jobs, selected history job, batch-run aggregate polling, job-status polling, and SSE (`apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts:74`, `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts:79`, `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts:98`). `buildScanProgress()` prioritizes batch-run status when present, but falls back to latest-job SSE aggregation otherwise (`apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineProgress.ts:113`, `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineProgress.ts:131`, `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineProgress.ts:138`).

That fallback assumes earlier submitted jobs are complete based on array position, not observed terminal status. The Workbench therefore has no single authoritative monotonic counter during the window before batch-run polling catches up.

### RC-3: The visible count mixes different denominators

`ScanActionPanel` renders the main progress from `progress.completed`, while the batch-run text renders `batchRunStatus.completed_total` only (`apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:123`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx:143`). Elsewhere, status text correctly computes processed total as completed + failed + cancelled (`apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineProgress.ts:50`). This makes a partial-failure or stale-observation run look like the count moved backward or disagrees with the bar.

`BatchRunRepository` also only records child job status, not per-job processed-media progress (`apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php:114`, `apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php:139`, `apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php:377`). Its aggregate is coarse by design: accepted/completed/failed/cancelled media counts are derived from terminal child-job states (`apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php:385`, `apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php:393`).

### RC-4: Projection is a synchronous read-path side effect

Clusters become visible in the Workbench only after LocalWP projection has caught up. But the job-status read path can trigger that projection synchronously. `get_job_status()` calls `maybe_trigger_projection_sync()` after reading backend status (`apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:426`, `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:458`). The SSE loop does the same before emitting the progress/done payload (`apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:524`, `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:596`).

This is the biggest clarity bug: the UI is waiting for a read request to mutate the local projection before it can truthfully show "clusters ready." If projection is slow, the stream appears stalled; if projection succeeds after a different request or refresh, clusters appear suddenly.

### RC-5: Cluster review queries are stale for the most important moment

`TopClustersSection` uses a one-minute `staleTime` and only refetches on mount (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx:48`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx:51`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx:55`). The pipeline invalidates `queryKeys.clusters.all` on several success paths, including projection sync (`apps/prototype-wp-alt-context/js/admin/hooks/useSyncTrigger.ts:23`, `apps/prototype-wp-alt-context/js/admin/hooks/useSyncTrigger.ts:26`), but the refresh is indirect and competes with the synchronous read-path projection in RC-4.

The user-facing result is plausible: a job completes, the naming queue still says no people, and a page refresh finally remounts/refetches the queue.

### RC-6: Backend clustering progress is chunk-based but not explicitly exposed as a UI contract

The clustering orchestrator does durable per-chunk commits and updates processed identity counts after each chunk (`apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py:443`, `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py:580`, `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py:591`). That is good backend behavior, but the frontend treats clustering progress as whichever job the SSE stream currently resolves through `deriveLatestJobId()` (`apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts:54`, `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts:60`).

For backend auto-chained clustering, the frontend may not have a local clustering job entry. It relies on the scan job status resolving to the follow-up clustering job (`apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py:62`, `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py:71`, `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts:27`). This is clever, but too implicit for a progress UI.

## MVP scope

Build a single, monotonic Workbench pipeline projection for one user-triggered run:

1. Submission: selected media queued/submitted, with bounded concurrency.
2. Scan: images processed and faces found.
3. Clustering: identities processed and clusters created.
4. Projection: LocalWP mirror syncing/ready/failed.
5. Review availability: naming queue refetched and visibly populated or explicitly empty.

The UI may still use existing APIs in the first slice, but the state selector must expose one pipeline model to components:

```ts
type WorkbenchPipelineSnapshot = {
  runId: string;
  phase: 'submitting' | 'scanning' | 'clustering' | 'projecting' | 'ready' | 'failed';
  scan: { completed: number; total: number; facesFound?: number };
  clustering: { completed: number; total: number; clustersCreated?: number };
  projection: { status: 'idle' | 'syncing' | 'ready' | 'failed'; snapshotVersion?: number };
  monotonicDisplayVersion: number;
};
```

This model must never derive a lower displayed count than it has previously emitted for the same run.

## Proposed slices

### S1: Frontend monotonic state selector

- Extract a `useWorkbenchPipelineSnapshot()` selector or pure builder from `useJobStateMachineDerivedState`.
- Make batch-run status the scan aggregate authority when a `batchRunId` exists.
- Track `maxDisplayedScanCompleted` and `maxDisplayedClusterCompleted` per run in state, not in persistent storage.
- Fix `ScanActionPanel` batch-run text to use processed total consistently.
- Add tests for mixed success/failure, stale SSE fallback, and multi-batch out-of-order completion.

### S2: Submission throughput without request storming

- Replace serial `for ... await` batch submission with bounded concurrency, default 2 or 3.
- Keep `MULTIPART_MAX_IMAGES = 5` unless the server-side multipart cap is changed; do not fake a larger batch size in config.
- Update batch-run failure recording so failed submissions preserve run-level monotonic totals.
- Add a test proving 20 images submit in 4 batches with max concurrency N and stable result ordering.

### S3: Decouple projection from read-path SSE/status

- Stop doing full local projection inside the SSE/status read path before emitting `done`.
- Emit `awaiting_projection` immediately when backend clustering completes with a positive `snapshot_version`.
- Move projection trigger into an explicit command path that reports `syncing`, `ready`, or `failed`.
- Keep the current inline projection payload optimization, but invoke it from the projection command rather than from passive reads.
- Add PHP tests that `stream_job_progress()` emits the completion/awaiting-projection event without blocking on projector work.

### S4: Force review-surface refresh on projection ready

- On projection success, use `refetchQueries` for `clusters.topUnlabeled(tenantId)`, `suggestions.pending()`, and `media.identities()` rather than only broad invalidation.
- While `phase` is `projecting`, set `TopClustersSection` stale time to zero or pass a `refreshNonce` so it refetches once when projection reaches ready.
- Add a Workbench integration test: scan completes -> clustering completes -> projection ready -> top clusters appear without page refresh.

### S5: Durable pipeline status endpoint

- Extend the WordPress batch-run status or add a pipeline status endpoint that combines child scan jobs, follow-up clustering job id/status, projection status, snapshot version, and review availability.
- Record per-child scan progress, not only terminal status, if the UI needs image-level progress during multi-batch runs.
- Make this endpoint the single Workbench polling fallback when SSE is unavailable.

## Success criteria

1. Clicking `Analyze selected media` on 20+ selected images shows a monotonic count from submission through scan completion; no visible count decreases for the same run.
2. Clustering progress appears as its own phase with identity counts when the backend follow-up job starts, including auto-chained clustering where the frontend did not create a local cluster job.
3. When backend clustering finishes with `snapshot_version > 0`, the UI immediately shows `Syncing results...`, then `Projected results ready for review` or an actionable projection error.
4. Top unlabeled clusters or an explicit empty state appear after projection completion without page refresh.
5. Local submission latency improves measurably for multi-batch runs by bounded concurrency; collect before/after p50/p95 for selected counts 5, 20, and 100.
6. SSE never blocks on local projection before emitting the backend job completion/projection-needed event.

## Not doing

- Do not undo the BR-21 clustering admission bulkhead, circuit breaker, or tenant-lock fail-fast work.
- Do not retune clustering thresholds or recognition quality in this UI/projection scope.
- Do not make the UI claim clusters are available before LocalWP projection confirms them.
- Do not increase multipart batch size above five unless the server transport limit is changed and tested.
- Do not replace SSE with a new realtime transport; use a pipeline status fallback first.
- Do not make page refresh part of the happy path.

## Verification plan

- Frontend unit tests for `jobStateMachineProgress` or the new pipeline selector:
  - out-of-order batch completion cannot decrease displayed scan count;
  - completed + failed + cancelled are rendered as processed consistently;
  - backend auto-chained clustering resolves to clustering phase without a local cluster job.
- Frontend integration test around `WorkbenchPage`:
  - mock scan jobs, batch-run status, clustering status, projection success, and top-unlabeled cluster response;
  - assert the `Analyze selected media` panel moves through scan -> clustering -> projecting -> ready;
  - assert top clusters render without remount/refresh.
- PHPUnit tests:
  - `stream_job_progress()` does not call projection synchronously before emitting the completion/projection-needed payload;
  - projection command path can consume `projection_payload` and set sync result.
- Local smoke evidence:
  - selected image counts 5, 20, 100;
  - record submission duration, scan completion duration, clustering duration, projection duration, and first top-cluster paint.

## Implementation note

The fastest safe path is S1 + S4 first if the operator needs immediate UI clarity, then S2 for local speed. S3 is the structural fix for "appears only after refresh" and should land before treating this as closed. S5 is the durable contract that prevents this state machine from growing more implicit on the next workflow.
