# Restore RLS Tenant Context After Chunk Commits

## Problem Statement

Every clustering job with more than `chunk_size` identities (virtually all non-trivial jobs) fails deterministically on the second chunk with `InsufficientPrivilegeError: new row violates row-level security policy for table "recognition_events"`. The per-chunk `session.commit()` introduced by finding 1164 clears `SET LOCAL` tenant context, so subsequent chunks run without RLS bypass and crash when SQLAlchemy autoflush attempts to INSERT observability events.

## Workflow Principles

- Tenant context must be treated as a transactional resource that requires explicit re-establishment after every commit boundary.
- Defense-in-depth: set context both at the handler entry and after each mid-loop commit.

## Terminology

- **`SET LOCAL`**: PostgreSQL transaction-scoped session variable. Cleared automatically on COMMIT or ROLLBACK.
- **Autoflush**: SQLAlchemy behavior where pending dirty objects are flushed (INSERT/UPDATE) before a query executes.
- **RLS bypass**: `SET LOCAL app.bypass_rls = 'true'`; allows worker sessions to write to tenant-isolated tables without matching `app.current_tenant`.
- **Chunk commit**: `await self._session.commit()` at orchestrator.py `_process_chunks`, introduced by finding 1164 for durable per-chunk checkpointing.

## Current State Analysis

- `set_tenant_context()` and `enable_rls_bypass()` both use `SET LOCAL`, which is transaction-scoped.
- `ensure_job_context()` in `worker/handlers/utils.py` calls both, but only before the job is marked `running`.
- The `running` status commit at `scan_worker.py` line 209 clears the `SET LOCAL` variables.
- The clustering handler (`clustering.py`) never re-establishes tenant context before calling the orchestrator.
- The orchestrator (`orchestrator.py`) never re-establishes tenant context after per-chunk commits.
- `GraphDiscovery._emit_graph_run_event()` adds a `RecognitionEvent` to the session via `RecognitionRunContext.add_event()` without flushing.
- On chunk 2+, a gate evaluation query in `block_repository.is_blocked()` triggers autoflush of the pending event, which fails RLS because `SET LOCAL` was cleared by the previous chunk commit.
- Chunk 1 survives because it has 0 gate evaluations (all identities produce new clusters via graph discovery; none enter the gate), so no autoflush is triggered mid-chunk.

## Proposed Solution

Three layers of fix, in priority order:

1. **Immediate**: In `orchestrator._process_chunks()`, call `set_tenant_context()` and `enable_rls_bypass()` immediately after every `await self._session.commit()`. The `tenant_id` parameter is already available in the method signature.

2. **Defense-in-depth**: In `clustering.py` handler, call `ensure_job_context(session=session, job=job)` before `cluster_service.cluster_unclustered_identities()` so the clustering transaction starts with known-good tenant context regardless of what the scan worker's earlier commit cleared.

3. **Testing**: Add a unit test that verifies `set_tenant_context` + `enable_rls_bypass` are called after each chunk commit, and that the clustering handler establishes context before delegation.

## Patterns to Follow

### Post-commit tenant context restoration

```python
# In orchestrator._process_chunks(), after the chunk commit
await self._session.commit()
# Restore tenant context cleared by COMMIT (SET LOCAL is transaction-scoped)
await set_tenant_context(self._session, uuid.UUID(tenant_id))
await enable_rls_bypass(self._session)
```

### Handler-level context assertion

```python
# In clustering.py handle(), before calling cluster_service
await ensure_job_context(session=session, job=job)
result = await cluster_service.cluster_unclustered_identities(...)
```

## Functions to Change

| File                                                               | Function                      | Change                                                                                                                                                                                                                                                   |
| ------------------------------------------------------------------ | ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `recognition/application/orchestration/clustering/orchestrator.py` | `_process_chunks`             | Add `set_tenant_context` + `enable_rls_bypass` calls after `await self._session.commit()` in `_process_chunks()`. Add `from db.tenant_context import enable_rls_bypass, set_tenant_context`. Use `uuid.UUID(tenant_id)` (`import uuid` already present). |
| `recognition/worker/handlers/clustering.py`                        | `ClusteringJobHandler.handle` | Add `await ensure_job_context(session=session, job=job)` before the `cluster_service.cluster_unclustered_identities()` call. `ensure_job_context` is already imported; no new import needed.                                                             |

## Stretch Goal: Files Changed

| File                                                       | Function / Target                                               | Change                                                                                                                                                |
| ---------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `recognition/observability/recognition_runs.py`            | `RecognitionRunContext`                                         | Added `buffer_events` flag, `_pending_events` list, and `flush_pending_events()` method to decouple observability writes from the clustering session. |
| `recognition/application/orchestration/cluster_service.py` | `cluster_unclustered_identities()`                              | Threaded `session_factory` parameter through to support flushing buffered events in a separate short-lived session.                                   |
| `recognition/interface_adapters/http/job_utils.py`         | `build_job_progress_response()`, `job_to_clustering_response()` | Both mappers now extract `current_chunk_size` from `job.payload` and include it in the response.                                                      |

## Related Files

| File                                                   | Note                                                                                                                                           |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `db/tenant_context.py`                                 | Defines `set_tenant_context()` and `enable_rls_bypass()`. Both use `SET LOCAL`. Not changed.                                                   |
| `recognition/worker/handlers/utils.py`                 | Defines `ensure_job_context()` which calls both tenant context functions. Not changed.                                                         |
| `recognition/worker/scan_worker.py`                    | Worker loop that calls `ensure_job_context()` before marking the job running, and commits after (clearing context). Not changed directly.      |
| `recognition/application/discovery/graph/discovery.py` | `_emit_graph_run_event()` adds events to the session that trigger the autoflush RLS failure. Not changed.                                      |
| `recognition/observability/recognition_runs.py`        | `RecognitionRunContext.add_event()` does `session.add(event)` without flush. Modified by stretch goal (see Stretch Goal: Files Changed above). |
| `db/migrations/versions/001_identity_schema.py`        | Contains RLS policy definitions for `recognition_events` and other tenant tables. Not changed.                                                 |

## Investigation Reports

- [recognition-clustering-crash-investigation-2026-03-24.md](recognition-clustering-crash-investigation-2026-03-24.md)
- [rls-tenant-context-lost-after-chunk-commit-investigation-2026-03-24.md](rls-tenant-context-lost-after-chunk-commit-investigation-2026-03-24.md)

---

# Consolidated Checklist

## Completed

- [x] Root cause identified: `SET LOCAL` cleared by per-chunk `session.commit()`
- [x] Investigation reports written

## Phase 0: Scaffolding

- [x] Add `from db.tenant_context import enable_rls_bypass, set_tenant_context` to `orchestrator.py` (not yet present; `import uuid` is already present so use `uuid.UUID` form)
- [x] Verify `ensure_job_context` is already imported in `clustering.py` (it is; no new import required)

## Phase 1: Restore tenant context after chunk commits

- [x] In `orchestrator._process_chunks()`, add `await set_tenant_context(self._session, UUID(tenant_id))` immediately after `await self._session.commit()` (line ~601)
- [x] In `orchestrator._process_chunks()`, add `await enable_rls_bypass(self._session)` immediately after the `set_tenant_context` call
- [x] In `clustering.py` `handle()`, add `await ensure_job_context(session=session, job=job)` before the `cluster_service.cluster_unclustered_identities()` call

## Phase 2: Tests

- [x] Add a Postgres-backed integration test that reproduces the exact failure path: create a `graph_run` event in the session, commit a chunk boundary, execute a later query that triggers autoflush, and assert the second chunk proceeds without `InsufficientPrivilegeError`. This test cannot use SQLite; it requires a real Postgres connection with RLS policies active.
- [x] Add a unit test verifying `ensure_job_context` is called in the clustering handler before `cluster_unclustered_identities`
- [x] Run full Python test suite; all tests pass (648 passed, 2 skipped as of 2026-03-24)

## Stretch Goals

- [x] Decouple observability writes from the clustering session: buffer `recognition_events` rows and persist them in a separate short-lived session so that an RLS or other DB error in observability cannot abort the clustering transaction

## Success Criteria

- [x] Multi-chunk clustering jobs (> chunk_size identities) no longer crash with `InsufficientPrivilegeError`
- [x] `set_tenant_context` and `enable_rls_bypass` are called after every `session.commit()` in the chunk processing loop
- [x] Defense-in-depth: clustering handler sets tenant context before orchestrator entry
- [x] All existing tests continue to pass
