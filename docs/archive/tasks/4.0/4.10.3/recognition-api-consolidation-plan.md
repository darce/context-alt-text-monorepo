# Recognition API Consolidation & Multi-Tenant Batch Processing Plan (v4.10.3)

## Goals

- Make `/acx/v1/recognition/*` the single canonical WordPress REST API.
- Remove `/acx/v1/workbench/recognition/*` and any proxy redundancy.
- Split clustering/curation/split work into a dedicated worker for multi-tenant fairness.
- Enforce idempotency, per-tenant fairness, and predictable performance.

## Decisions

- Canonical API: `/acx/v1/recognition/*` (no workbench alias).
- Separate worker pools: scan worker handles scan queue only; cluster worker handles clustering, curation, split, and suggestion jobs.
- Idempotency via explicit request keys and unique constraints.
- Tenant fairness via round-robin scheduling at the queue layer.

## Recommended Multi-Tenant Model

### Options

1. Single mixed queue with weighted fairness
   - One queue table, one worker pool, job types interleaved with tenant-aware scheduling.
   - Simplest to operate, but clustering can still starve scans unless strict prioritization is enforced.

2. Separate queues + worker pools per job type (recommended)
   - Scan worker pool for analyze jobs only.
   - Cluster worker pool for clustering/curation/split/suggestion jobs.
   - Each pool uses tenant-aware scheduling within its own queue.
   - Clearer isolation and tuning, easier to scale independently.

3. Per-tenant queues
   - Highest isolation but highest operational overhead.
   - Better for very large multi-tenant scale, but overkill for greenfield.

### Recommendation

Option 2 provides the best balance of idempotency, performance, and maintainability:
- Prevents clustering from starving scans.
- Keeps queue logic readable and testable.
- Allows independent scaling and backpressure controls.

## Architecture Snapshot

- WordPress `RecognitionController` proxies all recognition endpoints.
- Scan worker: consumes scan queue items only.
- Cluster worker: consumes clustering/curation/split/suggestion jobs only.
- Job table includes `job_type`, `tenant_id`, `status`, `request_id`, and optional `source_scan_job_id`.
- SSE progress uses `/recognition/jobs/{job_id}/stream` (WordPress proxy polling + EventSource).

## Implementation Phases

### Phase 0: Scaffolding (MANDATORY)

- Define new worker entrypoint (`cluster_worker.py`) with stub handlers and docstrings.
- Introduce job type enums/interfaces for clustering, curation, and split operations.
- Stub scheduling strategy interface for tenant-aware selection.

### Phase 1: Canonical API Consolidation

- Remove `RecognitionProxyController` and workbench endpoints.
- Expand `RecognitionController` to cover all recognition routes.
- Update admin endpoint localization to expose only `/recognition/*`.
- Update frontend API calls and tests to use canonical endpoints.
- Update contracts and integration maps to reflect the new base path.

### Phase 2: Separate Cluster Worker

- Create `recognition/worker/cluster_worker.py` to process:
  - clustering jobs
  - curation jobs
  - split jobs
  - suggestion resolution jobs
- Remove clustering logic from `scan_worker.py`.
- Add worker startup in `scripts/start_prototype_local.sh` and `Makefile`.
- Update integration tests (`test_split_worker.py`, queue behavior) to target the new worker.

### Phase 3: Idempotency & Queue Fairness

- Add `request_id` to scan job records; enforce uniqueness per tenant.
- Add `source_scan_job_id` to clustering jobs; enforce uniqueness per tenant.
- Update job creation to upsert on `request_id` to avoid duplicates.
- Implement tenant round-robin selection using `FOR UPDATE SKIP LOCKED` + tenant cursor.

### Phase 4: Progress, Backpressure, and Observability

- Ensure scan progress commits per batch to unblock SSE.
- Add per-job timeout and retry policies with capped backoff.
- Emit structured logs for job lifecycle: created, started, progress, completed, failed.

## Testing Plan

- Backend: add API tests for new queue behavior and idempotency.
- Worker: integration tests for scan vs cluster worker isolation.
- Frontend: verify SSE progress displays in Workbench after canonical API migration.

## Open Questions

- Should curation and split jobs be separate job types or a shared cluster job type with a payload discriminator?
- Should cluster events use SSE or periodic polling for invalidation in the admin UI?

