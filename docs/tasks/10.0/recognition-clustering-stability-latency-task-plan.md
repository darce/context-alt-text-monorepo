# Recognition Clustering Stability + Latency Recovery

## Problem Statement

Analyze batches currently degrade into a misleading and expensive failure mode: the scan can finish, but follow-up clustering can loop indefinitely, replaying the same work while the UI still looks like scanning is in progress. We need to stop infinite retries, make clustering progress durable and truthful across the API/UI, and remove the obvious N+1/query-chatter patterns that keep clean runs far slower than they should be.

## Success Criteria

- A 937-identity batch completes clustering without retry amplification (`retry_count` <= 2).
- No duplicate `cluster_member` rows after any clustering run (verified by integration test).
- Clean-run DB round-trips under 200 for 937 identities (down from ~6,400 measured baseline).
- Workbench shows `Clustering identities…` phase label within 2 seconds of scan completion.
- Failed clustering jobs expose `retry_count`, `current_stage`, and last checkpoint in the UI.
- All lane-required test suites pass with zero skips on the correctness scenarios.

## Workflow Principles

- **Correctness before optimization.** A clustering job must terminate exactly once as `completed` or `failed` before we tune latency.
- **Durable progress is the source of truth.** UI and SSE state must come from persisted job state, not transient in-memory worker state.
- **Fallback assignment paths must be mutually exclusive.** An identity can be suggested, assigned, or deferred, but it cannot be inserted into membership twice in one run.
- **Retry only transient failures.** Integrity violations and deterministic planner errors should fail fast, not requeue forever.
- **Batch, cache, and reuse.** Chunk processing should minimize repeated reads, repeated representative fetches, and per-identity round-trips.
- **Pipeline UX must name the real phase.** Once scan hands off to clustering, the workbench must explicitly show clustering progress in identities, retries, and failure state.

## Terminology

- **Pipeline job**: The user-facing analyze workflow composed of a scan job plus its auto-chained clustering follow-up.
- **Durable checkpoint**: Progress persisted to `identity_clustering_jobs` that survives worker restarts.
- **Fallback cluster**: A cluster created for identities that were not accepted into an existing cluster during the main gate/discovery flow.
- **Planner overlap**: A bug where the same identity is eligible for more than one persistence path in the same chunk.
- **Chatty assignment path**: The current per-identity persistence flow that performs multiple DB round-trips for membership, representatives, centroid updates, and curriculum state.
- **Retry amplification**: Runtime growth caused by replaying large chunks of already-attempted work after each failure.

## Pre-Implementation State Analysis

> The following describes the codebase state before Phases 1-4 were implemented. All issues listed here were addressed during implementation. This section is retained for archaeological reference only.

- [`orchestrator.py`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py) currently builds `still_unclustered` from `no_candidates + rejected + suggested`, persists fallback clusters, and then runs HAC against the unchanged list. This allows planner overlap and duplicate membership insertion.
- [`discovery_pipeline.py`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py) reruns HAC over every identity still flagged as unclustered, but it has no guard against identities already assigned earlier in the same chunk.
- [`member_repository.py`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/infrastructure/repositories/member_repository.py) uses raw inserts in `add_member()` and `bulk_add_members()`, while the safer `add_member_if_not_exists()` path already exists but is not used in the hot path.
- [`scan_worker.py`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/worker/scan_worker.py) marks clustering jobs `running` in the same session that later fails. A late flush error rolls back both job state and progress, so the job remains `pending 0/0` and is reclaimed again.
- [`clustering.py`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/worker/handlers/clustering.py) flushes progress in the same transaction as clustering writes. That makes late errors erase all durable progress.
- [`assignment_writer.py`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/persistence/assignment_writer.py) performs N+1 style reads and writes per accepted identity: fetch cluster, insert member, inspect representatives, recompute centroid, update cluster, get/set `curriculum_t`, and representative churn.
- [`prepare_cluster_caches()`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py#L28) rereads all clusters and representatives on every chunk instead of incrementally updating a job-local cache.
- [`analyze.py`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py) correctly resolves the pipeline job to the follow-up clustering job, but the response schema does not yet expose retry/checkpoint metadata needed for truthful UX.
- [`class-analysis-jobs-controller.php`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php) streams only the current minimal progress fields and does not preserve richer pipeline state for the workbench.
- [`jobStateMachineUtils.ts`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts), [`useJobStateMachine.ts`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts), and [`Panels.tsx`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx) still treat the scan surface as primary, show generic `Processing media…` / `Queued 0 items…` states too easily, and label progress as images even after clustering handoff.

## Proposed Solution

Implement this in four layers, in dependency order. First, make clustering termination deterministic: remove planner overlap, make membership writes idempotent, persist `failed` state after integrity errors with a clean session, and bound retries for deterministic failures. Second, add durable chunk checkpoints and job metadata so API/SSE consumers can see truthful clustering stage, retry count, last successful chunk, and current phase. Third, reduce clean-run latency by batching membership and curriculum updates, caching cluster state across chunks, and removing duplicate representative fetches. Fourth, update the WordPress proxy and React workbench to explicitly model the analyze pipeline as `scan -> clustering -> projection`, with identity-based progress, retry/failure messaging, and stable phase handoff.

## Patterns to Follow

### Chunk-Level Durable Failure Handling

```python
async def process_clustering_job(job_id: str) -> None:
    for chunk_idx, chunk in enumerate(chunks):
        async with session.begin_nested():  # savepoint per chunk
            result = await process_chunk(chunk, planner_state)
            await persist_chunk_checkpoint(
                job_id=job_id,
                chunk_idx=chunk_idx,
                processed=result.processed,
                total=result.total,
                current_stage=result.stage,
            )

    await mark_job_completed(job_id)


async def fail_job_with_fresh_session(job_id: str, exc: Exception, checkpoint: Checkpoint) -> None:
    await current_session.rollback()
    async with session_factory() as fresh_session:
        job = await load_job_for_update(fresh_session, job_id)
        job.status = "failed"
        job.error_message = str(exc)
        job.payload = {
            **(job.payload or {}),
            "retry_count": checkpoint.retry_count,
            "last_successful_processed_identities": checkpoint.processed,
            "current_stage": checkpoint.stage,
            "last_error_code": classify_error(exc),
        }
        await fresh_session.commit()
```

### Chunk-Scoped Batch Persistence

```python
accepted_rows = collect_accept_membership_rows(chunk_decisions)
await member_repo.bulk_add_members_if_not_exists(cluster_id, accepted_rows)

cluster_cache.apply_membership_delta(accepted_rows)
cluster_cache.apply_new_clusters(fallback_clusters)

await cluster_repo.bulk_update_identity_counts(cluster_cache.identity_count_deltas())
await cluster_repo.bulk_apply_curriculum_updates(cluster_cache.curriculum_updates())
```

### Pipeline-Truth Workbench Rendering

```tsx
const phase = derivePipelinePhase(scanStatus, localJobs, sseProgress);

if (phase === "clustering") {
  return {
    ctaLabel: __("Clustering identities…", "alt-context"),
    statusText: buildClusteringStatus(scanStatus, sseProgress),
    progressLabel: sprintf(
      __("Processed %d/%d identities", "alt-context"),
      clusteringProgress.completed,
      clusteringProgress.total,
    ),
    secondaryMeta: buildRetryAndStageMeta(scanStatus),
  };
}
```

### Planner Overlap Exclusion

```python
final_result = await self._graph_discovery.discover(still_unclustered, {})
assigned_by_discover = {
    m.id for members, _ in final_result.new_clusters for m in members
}
hac_eligible = [i for i in still_unclustered if i.id not in assigned_by_discover]
if hac_eligible:
    hac_created = await run_hac_refinement(
        still_unclustered=hac_eligible,
        tenant_id=str(tenant_id),
        job_id=job_id,
        constrained_hac=self._constrained_hac,
        hac_settings=self._hac_settings,
        assignment_writer=self._assignment_writer,
        clustering_logger=self._clustering_logger,
    )
```

## Functions to Change

| File                                                                                                        | Target                                               | Change                                                                                                                                                                               |
| ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `apps/prototype-description-service/db/models/jobs.py`                                                      | `IdentityClusteringJob`                              | Extend payload/columns support for durable checkpoint metadata such as retry count, current stage, and last successful processed identities if payload-only storage is insufficient. |
| `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py`       | `_process_chunks()` cache reload call                | Stop reloading cluster caches every chunk from scratch; introduce job-local cache priming and incremental updates.                                                                   |
| `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py`       | `_process_chunks()` `still_unclustered` construction | Replace `still_unclustered` construction with mutually exclusive planner outputs so identities already assigned to fallback clusters are excluded from HAC.                          |
| `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py`       | `_process_chunks()` graph fallback persistence block | Convert graph fallback persistence into a chunk-scoped, deduplicated persistence path that records assigned identity IDs for later guards.                                           |
| `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py`       | `_process_chunks()` `run_hac_refinement()` call      | Pass only truly unassigned identities into `run_hac_refinement()` and record stage/checkpoint metadata before and after HAC.                                                         |
| `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py` | `prepare_cluster_caches()`                           | Refactor into job-start priming plus incremental cache update helpers.                                                                                                               |
| `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py` | `run_hac_refinement()`                               | Add guards so HAC never persists members already assigned earlier in the same chunk or recorded in the current checkpoint.                                                           |
| `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py`               | `persist_assignment()`                               | Replace chatty per-identity assignment flow with chunk-friendly batching hooks where possible; thread representative data through instead of rereading it.                           |
| `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py`               | `_update_curriculum_t()`                             | Replace `get_curriculum_t()` + `set_curriculum_t()` read-modify-write with an atomic repository update path.                                                                         |
| `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py`               | `_should_add_representative()`                       | Remove duplicate representative fetches by reusing `existing_reps` when deciding whether to add a representative and when recomputing centroids.                                     |
| `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py`               | `recompute_centroid()`                               | Add `recompute_centroid_from_reps()` or equivalent so centroid recomputation can reuse already-fetched representative embeddings.                                                    |
| `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py`               | `persist_new_cluster()`                              | Make `persist_new_cluster()` dedupe identity IDs and use conflict-safe bulk membership persistence.                                                                                  |
| `apps/prototype-description-service/recognition/infrastructure/repositories/member_repository.py`           | `add_member()`                                       | Change single-member hot-path inserts to idempotent conflict-safe semantics or explicitly route clustering hot paths to `add_member_if_not_exists()`.                                |
| `apps/prototype-description-service/recognition/infrastructure/repositories/member_repository.py`           | `bulk_add_members()`                                 | Add `bulk_add_members_if_not_exists()` / `ON CONFLICT DO NOTHING` support and return created-vs-skipped counts for observability.                                                    |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`          | `get_curriculum_t()` / `set_curriculum_t()`          | Replace pairing with an atomic `update_curriculum_t_ema()` repository method.                                                                                                        |
| `apps/prototype-description-service/recognition/worker/handlers/clustering.py`                              | `ClusteringJobHandler.handle()`                      | Move progress persistence to chunk checkpoints and stop relying on one transaction to carry both work and status.                                                                    |
| `apps/prototype-description-service/recognition/worker/scan_worker.py`                                      | `_process_pending_clustering_jobs()`                 | Split claim/start/fail handling so deterministic clustering failures are rolled back and then persisted as `failed` in a fresh session, not left as reclaimable `pending`.           |
| `apps/prototype-description-service/recognition/worker/scan_worker.py`                                      | `_refresh_mv_if_needed()`                            | Debounce MV refresh across retries or skip refresh on immediate retry of the same clustering job.                                                                                    |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py`               | `JobProgressResponse` / `JobStatusResponse`          | Extend with retry/checkpoint/stage metadata needed by SSE, proxy, and UI.                                                                                                            |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`                 | `_resolve_pipeline_job()`                            | Keep pipeline job resolution, but enrich pipeline responses with clustering checkpoint, retry, and stage fields.                                                                     |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`                 | `stream_job_progress()`                              | Stream richer SSE payloads including stage, retry count, last successful chunk, and identity-vs-image semantics.                                                                     |
| `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php`                                  | `get_job_status()`                                   | Preserve new backend job metadata on status responses and expose it consistently through the WP proxy contract.                                                                      |
| `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php`                                  | `stream_job_progress()`                              | Forward richer SSE fields through the stream endpoint so React gets retry/stage/progress metadata without polling hacks.                                                             |
| `apps/prototype-wp-alt-context/js/admin/api/generated/recognition-job.ts`                                   | file-level generated types                           | Regenerate or update generated recognition job types to include retry/checkpoint/stage metadata and failed phase support.                                                            |
| `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts`                                      | `derivePipelinePhase()`                              | Rework phase derivation and status text so pipeline truth comes from clustering follow-up state, not merely local persisted scan jobs.                                               |
| `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts`                                        | `useJobStateMachine()` active job tracking           | Track and adopt backend-created follow-up clustering jobs as first-class active jobs in the workbench state machine.                                                                 |
| `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineEffects.ts`                                 | `backendHandledClustering` check                     | Adjust scan-to-clustering handoff logic so the UI does not remain scan-oriented when the backend has already chained clustering.                                                     |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx`                                         | `ScanActionPanel`                                    | Update CTA copy, phase labels, progress labels, and retry/failure meta so clustering is shown explicitly in identities rather than images.                                           |

## Related Files

| File                                                                                                                                                                                                 | Note                                                                                                                                                                                                                                                                                                                          |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`apps/prototype-description-service/logs/scan_worker.log`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/logs/scan_worker.log)                             | Source evidence for the `750/937` replay loop, repeated HAC on 14 identities, and log-volume growth.                                                                                                                                                                                                                          |
| [`docs/tasks/9.0/scan-clustering-retry-loop-investigation-2026-03-23.md`](/Users/daniel/Development/context-alt-text-monorepo/docs/tasks/9.0/scan-clustering-retry-loop-investigation-2026-03-23.md) | Investigation report and addendum that motivate this task plan.                                                                                                                                                                                                                                                               |
| `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`                                                                                                                   | Baseline clustering-job schema. Checkpoint metadata (`retry_count`, `current_stage`, `last_successful_processed_identities`, `last_error_code`) will be stored in the existing JSONB `payload` column. If dedicated columns are later needed for query indexing, edit this baseline migration directly per greenfield policy. |
| `apps/prototype-description-service/recognition/tests/unit/test_hac_refinement.py`                                                                                                                   | Natural home for regression coverage around planner overlap and HAC exclusion rules.                                                                                                                                                                                                                                          |
| `apps/prototype-description-service/recognition/tests/unit/test_clustering_job_handler.py`                                                                                                           | Natural home for failure-durability and retry-budget tests.                                                                                                                                                                                                                                                                   |
| `apps/prototype-description-service/recognition/tests/integration/test_member_repository.py`                                                                                                         | Natural home for `ON CONFLICT DO NOTHING` bulk membership behavior.                                                                                                                                                                                                                                                           |
| `apps/prototype-wp-alt-context/tests/Unit/AnalysisJobsControllerTest.php`                                                                                                                            | WP proxy status/stream contract coverage.                                                                                                                                                                                                                                                                                     |
| `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useJobStateMachine.test.ts`                                                                                                                  | Frontend pipeline-phase and follow-up clustering adoption coverage.                                                                                                                                                                                                                                                           |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx`                                                                                                            | Workbench UX copy and progress-display coverage.                                                                                                                                                                                                                                                                              |
| `docs/tasks/10.0/rls-tenant-context-restoration-after-chunk-commit-task-plan.md`                                                                                                                     | Sub-task spawned during Phase 2 implementation. Covers RLS bypass loss after chunk commits and observability write decoupling (stretch goal). See also findings 1171-1178.                                                                                                                                                    |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID          | Owned Paths                                                                                                                                                                                                                                                                                        | Upstream Dependencies              | Required Tests                                                                                                                                                                                                                                    |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend-domain` | `apps/prototype-description-service/db/**`, `apps/prototype-description-service/recognition/application/orchestration/clustering/**`, `apps/prototype-description-service/recognition/application/persistence/**`, `apps/prototype-description-service/recognition/infrastructure/repositories/**` | None                               | `cd apps/prototype-description-service && PYENV_VERSION=description-service pytest recognition/tests/unit/test_hac_refinement.py recognition/tests/integration/test_member_repository.py recognition/tests/integration/test_assignment_writer.py` |
| `backend-worker` | `apps/prototype-description-service/recognition/worker/**`                                                                                                                                                                                                                                         | `backend-domain`                   | `cd apps/prototype-description-service && PYENV_VERSION=description-service pytest recognition/tests/unit/test_clustering_job_handler.py recognition/tests/unit/test_background_tasks.py`                                                         |
| `backend-http`   | `apps/prototype-description-service/recognition/interface_adapters/http/**`, `packages/shared-contracts/**`                                                                                                                                                                                        | `backend-domain`, `backend-worker` | `cd apps/prototype-description-service && PYENV_VERSION=description-service pytest recognition/tests/unit/test_job_progress.py recognition/tests/api/test_api_clusters.py`                                                                        |
| `wp-proxy`       | `apps/prototype-wp-alt-context/src/api/**`, `apps/prototype-wp-alt-context/tests/Unit/**`                                                                                                                                                                                                          | `backend-http`                     | `cd apps/prototype-wp-alt-context && composer phpunit -- tests/Unit/AnalysisJobsControllerTest.php tests/Unit/ProxyRequestTest.php`                                                                                                               |
| `frontend`       | `apps/prototype-wp-alt-context/js/**`                                                                                                                                                                                                                                                              | `wp-proxy`                         | `cd apps/prototype-wp-alt-context && npm run test -- --run useJobStateMachine WorkbenchPage`                                                                                                                                                      |

### Merge Order

`backend-domain` -> `backend-worker` -> `backend-http` -> `wp-proxy` -> `frontend`

### Manifest

Initialize the lane manifest for this task:

```bash
make lane-manifest-init TASK=recognition-clustering-stability-latency LANE_IDS='backend-domain backend-worker backend-http wp-proxy frontend' TASK_PLAN=docs/tasks/10.0/recognition-clustering-stability-latency-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with `backend="codex-subagent"` so backend and frontend lanes can move independently while preserving the merge order above.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and `make lane-intake` from the orchestrator root if MCP worker lifecycle tools are unavailable.

---

# Consolidated Checklist

## Completed

- [x] Investigation report completed with retry-loop root cause, N+1 query analysis, and baseline clean-run latency estimate.

## Phase 0: Scaffolding

- [x] Add or extend clustering job metadata for retry count, current stage, and last successful processed identity checkpoint.
- [x] Add repository and service interfaces for conflict-safe bulk membership insertion and atomic curriculum updates.
- [x] Add test scaffolds covering planner overlap, durable failure persistence, checkpoint resume, and follow-up clustering UI handoff.
- [x] Update shared/API contracts for richer job progress payloads before proxy/frontend implementation.
- [x] Verify generated types and backend schemas compile cleanly.

## Phase 1: Termination and Correctness

- [x] Make fallback planner outputs mutually exclusive so identities already assigned by graph fallback are excluded from HAC.
- [x] Add chunk-level identity assignment guards so the same identity cannot be inserted twice in one chunk.
- [x] Switch clustering membership writes to conflict-safe semantics and log created-vs-skipped rows for diagnostics.
- [x] Fail deterministic integrity errors once, persist `failed` durably, and stop reclaiming the same job as `pending`.
- [x] Add regression tests reproducing the `suggested -> HAC duplicate membership` path.

## Phase 2: Durable Progress and Retry Semantics

- [x] Persist clustering job `running` state, chunk checkpoints, current stage, and retry count outside the main failure-prone transaction.
- [x] Introduce chunk-level savepoints or commits so late errors do not erase all earlier progress.
- [x] Bound retries for deterministic failures and reserve exponential backoff for transient infrastructure issues only.
- [x] Prevent MV refresh from rerunning on every immediate retry of the same job.
- [x] Add API/SSE fields for checkpoint progress, retry count, last error code, and stage name.

## Phase 3: Database Efficiency and Clean-Run Latency

- [x] Replace per-identity membership inserts with chunk-level bulk writes where semantics allow.
- [x] Cache cluster representatives and centroids in memory across chunks and update the cache incrementally.
- [x] Remove duplicate `get_all_representatives()` reads within accepted-assignment persistence.
- [x] Replace `get_curriculum_t()` + `set_curriculum_t()` with an atomic EMA update statement.
- [x] Add instrumentation for chunk latency, DB round-trips, representative churn, and centroid update cost so clean-run performance can be measured after correctness fixes.

## Phase 4: HTTP, Proxy, and Frontend Pipeline UX

- [x] Expose pipeline-truth status for `scan`, `clustering`, `retrying`, `failed`, and `awaiting_projection`.
- [x] Ensure the WP proxy preserves richer status and stream payloads without stripping new job fields.
- [x] Update workbench state derivation so backend-created follow-up clustering jobs become first-class tracked jobs.
- [x] Update status text and progress labels to show identities during clustering, not images.
- [x] Show retry count, stage name, and last successful checkpoint when clustering is retrying or failed.
- [x] Keep scan CTA/button copy aligned with the real pipeline phase so the UI never says `Scanning media…` while clustering is the active stage.

## Phase 5: Tests and Validation

- [x] Unit test planner overlap elimination and HAC exclusion behavior.
- [x] Integration test conflict-safe membership insertion and checkpointed chunk resume.
- [x] Worker test deterministic failure handling so jobs end as `failed`, not replayable `pending`.
- [x] API test enriched job status and stream payloads for chained clustering jobs.
- [x] WP proxy test forwarding of new job fields and SSE payload shape.
- [x] Frontend test scan-to-clustering handoff, retry display, failed-state display, and identity-based progress labels.
- [ ] Run a representative 500-image/900+ identity clustering benchmark after correctness fixes to establish a new clean-run baseline.
  > Verification requires a live environment with 900+ identities. Track as follow-up in the next integration testing cycle or create a dedicated benchmark task.

## Stretch Goals

- [x] Add adaptive chunk sizing based on observed DB and representative-update latency rather than a static policy.
- [x] Add chunk-level summary logging mode that drastically reduces per-identity log volume for large jobs.
- [x] Add a lightweight job timeline UI component showing scan completion, clustering start, retries, and projection sync milestones.

## Success Criteria

- [x] A deterministic integrity error in clustering results in one durable `failed` job with preserved checkpoint metadata, not an infinite replay loop.
- [x] The workbench explicitly shows when clustering is active, retrying, or failed, and reports identity-based progress rather than stale scan messaging.
- [x] Follow-up clustering jobs expose truthful `running` progress, retry count, and current stage through backend API, WP proxy, SSE, and React state.
- [ ] A clean run of a 900+ identity clustering job no longer pays the worst N+1 penalties documented in the investigation addendum.
- [ ] Worker logs and DB metrics show bounded retries, lower log volume, and no repeated `750/937` replay pattern for the same job.
