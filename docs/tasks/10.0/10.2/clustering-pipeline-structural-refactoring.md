# Clustering Pipeline Structural Refactoring

## Problem Statement

The clustering pipeline's structural patterns allowed four silent RLS failures to ship undetected. The root causes are: silent empty results as the default contract, invisible transaction lifecycle (SET LOCAL cleared by commit), duplicated logic, a 16-parameter constructor, a 1,374-line god class, and hardcoded magic values with no unified config surface. These smells make the pipeline harder to debug, test, and extend safely.

## Workflow Principles

- **Phase 1 items are behavioral additions, not refactors.** Assertion guards that raise on 0-row paths, `_coerce_tenant()` raising `ValueError`, and new warning logs at previously silent decision points intentionally change runtime behavior to surface bugs. Fowler's "preserve existing behavior" rule does not apply to them.
- **Phases 2-4 are structural refactors** that must preserve external behavior exactly (extract helper, parameterized query, TenantSession wrapper, split flag argument). Tests must pass before and after each.
- **Phases 5-8 are optional maintainability improvements** (parameter objects, duplicate extraction, magic values, repository split). They are not required to close this task and carry no incident urgency.
- Each item is independently mergeable; do not bundle unrelated changes.
- Prioritize by debugging impact: behavioral safety additions (Phase 1) first, structural cleanup second.

## Terminology

- **Silent failure**: A code path that returns an empty result (0 rows, empty list, `None`) without logging or raising when the caller expected data. Indistinguishable from "legitimately empty."
- **TenantSession**: Proposed wrapper around `AsyncSession` that tracks whether RLS context is valid and raises on queries after context invalidation.
- **Parameter Object**: A typed dataclass grouping related constructor parameters (Fowler p. 140).

## Current State Analysis

- `ClusterService.__init__()` takes 16 parameters; violates sr-008. Hard to wire correctly in `build_cluster_service()`.
- `cluster_repository.py` is 1,374 lines with 50+ methods spanning CRUD, representatives, snapshots, MV refresh, and domain conversion.
- `tenant_context.py` repeats the same try/except `InFailedSQLTransactionError` recovery pattern 4 times across 3 functions.
- `set_tenant_context()` uses f-string SQL interpolation with manual escaping instead of parameterized `set_config()`.
- `cluster_unclustered_identities(commit=True)` flag argument hides two fundamentally different transaction modes.
- `cluster_merge.py::post_merge_retry_matching()` contains duplicate identity evaluation blocks at lines 67-92 and 149-182.
- Hardcoded magic values (polling intervals, thresholds, batch sizes) are scattered across 8 files with no unified config surface.
- Key "nothing happened" paths have no logging; 0-row results are indistinguishable from bugs.

## Proposed Solution

Ten independent refactorings (RF-1 through RF-10) ordered by debugging impact. Each is self-contained and can be implemented, tested, and merged independently. The first four (RF-1, RF-2, RF-9, RF-10) address the structural conditions that allowed the RLS bugs to ship undetected. The remaining six are maintainability improvements.

## Patterns to Follow

### Rowcount assertion after known-ID operations (RF-1)

```python
result = await session.execute(
    sa_update(Model).where(Model.id == known_id).values(...)
)
assert result.rowcount >= 1, (
    f"UPDATE {Model.__name__} id={known_id} affected 0 rows; "
    "RLS context may be missing"
)
```

### TenantSession wrapper (RF-2)

```python
class TenantSession:
    """Wraps AsyncSession to track RLS context lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._context_valid = False

    async def set_context(self, tenant_id: UUID) -> None:
        await set_tenant_context(self._session, tenant_id)
        self._context_valid = True

    async def commit(self) -> None:
        await self._session.commit()
        self._context_valid = False  # SET LOCAL cleared by COMMIT

    async def ensure_context(self, tenant_id: UUID) -> None:
        if not self._context_valid:
            await self.set_context(tenant_id)

    def guard(self) -> None:
        if not self._context_valid:
            raise ContextLostError("Query attempted on session with invalidated RLS context")
```

### Parameter Object grouping (RF-3)

```python
@dataclass(frozen=True)
class DiscoveryServices:
    representative: RepresentativeDiscovery
    centroid: CentroidDiscovery
    graph: GraphDiscovery

@dataclass(frozen=True)
class SuggestionServices:
    suggestion: SuggestionServiceProtocol
    refresh: SuggestionRefreshServiceProtocol | None = None
    merge: MergeSuggestionServiceProtocol | None = None
```

### Extracted try/except recovery helper (RF-7)

```python
async def _execute_with_failed_txn_recovery(
    session: AsyncSession, sql: str
) -> None:
    try:
        await session.execute(text(sql))
    except DBAPIError as e:
        if e.orig and isinstance(e.orig.__cause__, InFailedSQLTransactionError):
            await session.rollback()
            await session.execute(text(sql))
        else:
            raise
```

### Parameterized set_config (RF-8)

```python
await session.execute(
    text("SELECT set_config('app.current_tenant', :tenant, true)"),
    {"tenant": str(tenant_id)},
)
```

## Functions to Change

| File | Function | Change |
| --- | --- | --- |
| `recognition/infrastructure/repositories/cluster_repository.py` | `refresh_centroids_view_concurrent` | RF-10: Add before/after row count logging |
| `recognition/infrastructure/repositories/cluster_repository.py` | (class split) | RF-4: Extract `ClusterRepresentativeRepository`, `ClusterSnapshotRepository`, `CentroidViewRepository` |
| `recognition/worker/handlers/clustering.py` | `progress_callback` | RF-1: Assert `rowcount >= 1` after UPDATE |
| `recognition/domain/services/purge_service.py` | `_purge_rows` | RF-1: Log per-model delete count; warn if all-zero for tenant with known data |
| `recognition/domain/services/purge_service.py` | `ScheduledDisposalWorker.run_once` | RF-10: Log per-tenant purge summary |
| `recognition/application/orchestration/cluster_service.py` | `ClusterService.__init__` | RF-3: Replace 16 params with `DiscoveryServices`, `SuggestionServices`, `ObservabilityServices` parameter objects |
| `recognition/application/orchestration/clustering/orchestrator.py` | `cluster_unclustered_identities` | RF-9: Split into `_transactional()` and `_autocommit()` entry points |
| `recognition/application/orchestration/clustering/orchestrator.py` | `_coerce_tenant` | RF-1: Raise `ValueError` instead of returning `None` |
| `recognition/application/orchestration/cluster_merge.py` | `post_merge_retry_matching` | RF-5: Extract `_evaluate_identity_against_cluster()` shared function |
| `db/tenant_context.py` | `set_tenant_context` | RF-7: Extract `_execute_with_failed_txn_recovery()` helper; RF-8: Use `set_config()` instead of f-string |
| `db/tenant_context.py` | `enable_rls_bypass` | RF-7: Use extracted helper |
| `db/tenant_context.py` | `disable_rls_bypass` | RF-7: Use extracted helper |
| `recognition/interface_adapters/http/deps/services.py` | `build_cluster_service` | RF-3: Construct parameter objects instead of passing 16 args |
| `recognition/worker/scan_worker.py` | `ScanWorkerConfig` | RF-6: Consolidate magic values; document rationale for defaults |
| `recognition/application/orchestration/clustering/orchestrator.py` | `_process_chunks` | RF-6: Replace `total_identities <= 100` with named setting; RF-10: Log "0 candidates" paths |
| `recognition/application/orchestration/cluster_merge.py` | function-level defaults | RF-6: Move `max_unclustered=200`, `min_similarity=0.95` to settings |

## Related Files

| File | Note |
| --- | --- |
| `recognition/application/orchestration/incremental_clustering.py` | Facade re-exporting `cluster_unclustered_identities`; update imports after RF-9 split |
| `recognition/interface_adapters/http/routers/clusters.py` | HTTP sync endpoint; update to call `_autocommit` variant after RF-9 |
| `recognition/worker/handlers/clustering.py` | Worker handler; update to call `_transactional` variant after RF-9 |
| `recognition/application/settings/clustering.py` | `HACSettings` dataclass; extend or create sibling for pipeline-wide settings (RF-6) |
| `docs/tasks/10.0/10.1/projection-stall-direct-db-investigation-2026-03-24.md` | Investigation report with full RF-1 through RF-10 analysis |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `backend-domain` | `apps/prototype-description-service/db/tenant_context.py`, `apps/prototype-description-service/recognition/domain/**`, `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`, `apps/prototype-description-service/recognition/application/orchestration/**`, `apps/prototype-description-service/recognition/worker/**` | None | `PYENV_VERSION=description-service pytest recognition/tests/unit/ -q` |
| `backend-http` | `apps/prototype-description-service/recognition/interface_adapters/http/**` | `backend-domain` (parameter object types, split function names) | `PYENV_VERSION=description-service pytest recognition/tests/unit/ -q` |

### Merge Order

1. `backend-domain` (all refactorings except HTTP wiring)
2. `backend-http` (update `build_cluster_service`, update router calls)

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [ ] Create `DiscoveryServices`, `SuggestionServices`, `ObservabilityServices` dataclasses in `recognition/application/orchestration/protocols.py` (or new `service_groups.py`)
- [ ] Create `TenantSession` class in `db/tenant_session.py` with type stubs
- [ ] Create `_execute_with_failed_txn_recovery()` stub in `db/tenant_context.py`
- [ ] Create test file `recognition/tests/unit/test_tenant_session.py`
- [ ] Verify scaffolds compile: `mypy .`

## Phase 1: Assertion Guards and Observability (RF-1, RF-10)

- [ ] **RF-1**: In `progress_callback`, assert `result.rowcount >= 1` after the checkpoint UPDATE
- [ ] **RF-1**: In `_purge_rows`, log `deleted_count` per model; warn if all models return 0 for a tenant with known data
- [ ] **RF-1**: In `_coerce_tenant()`, raise `ValueError` instead of returning `None`; update callers in `IncrementalClusteringRunner.run()` to catch and log
- [ ] **RF-1**: In `post_merge_retry_matching()`, add `logger.debug` when skipping identity with `None` embedding
- [ ] **RF-10**: In `refresh_centroids_view_concurrent()`, log `(before_count, after_count, duration_ms)` after each refresh
- [ ] **RF-10**: In `ScheduledDisposalWorker.run_once()`, log per-tenant purge summary (models touched, rows deleted)
- [ ] **RF-10**: In suggestion backfill, log when 0 candidates are found (distinguish "no work" from "filtered")

## Phase 2: tenant_context.py Cleanup (RF-7, RF-8)

- [ ] **RF-7**: Extract `_execute_with_failed_txn_recovery(session, sql)` helper function
- [ ] **RF-7**: Refactor `set_tenant_context`, `enable_rls_bypass`, `disable_rls_bypass` to use the extracted helper
- [ ] **RF-8**: Replace f-string `SET LOCAL app.current_tenant = '{tenant_value}'` with `set_config('app.current_tenant', :tenant, true)` parameterized query
- [ ] **RF-8**: Replace f-string in bypass env-var branch similarly

## Phase 3: TenantSession Wrapper (RF-2)

- [ ] Implement `TenantSession` class wrapping `AsyncSession` with context tracking
- [ ] Add `commit()` that invalidates tracked context state
- [ ] Add `ensure_context(tenant_id)` that re-establishes if invalidated
- [ ] Add `guard()` assertion for queries on invalidated sessions
- [ ] Adopt `TenantSession` in orchestrator chunk-commit path (replace manual `set_tenant_context` + `enable_rls_bypass` restoration)
- [ ] Adopt `TenantSession` in `_finalize_job` commit path

## Phase 4: Remove Flag Argument (RF-9)

- [ ] Split `cluster_unclustered_identities()` into `cluster_unclustered_identities_transactional()` (no mid-function commit) and `cluster_unclustered_identities_autocommit()` (commits after each phase with context restoration)
- [ ] Update `IncrementalClusteringRunner.__init__` to remove `commit` flag; create two runner subclasses or two factory functions
- [ ] Update `ClusterService.cluster_unclustered_identities()` facade to delegate to the correct variant
- [ ] Update `ClusteringJobHandler.handle()` to call `_transactional` variant
- [ ] Update HTTP sync endpoint to call `_autocommit` variant
- [ ] Update `incremental_clustering.py` facade exports

## Phase 5: Tests

- [ ] Unit test: `TenantSession.commit()` invalidates context flag
- [ ] Unit test: `TenantSession.guard()` raises `ContextLostError` when context invalid
- [ ] Unit test: `TenantSession.ensure_context()` re-establishes after invalidation
- [ ] Unit test: `_execute_with_failed_txn_recovery` handles both success and `InFailedSQLTransactionError` paths
- [ ] Unit test: `set_tenant_context` uses parameterized `set_config()` (no f-string SQL)
- [ ] Unit test: `_evaluate_identity_against_cluster` returns correct evaluation for accept/reject/suggest
- [ ] Unit test: `_evaluate_identity_against_cluster` returns `None` for identity with missing embedding
- [ ] Verify all existing tests still pass after each phase

## Stretch Goals (Maintainability — not incident-driven)

- [ ] **RF-3**: Create `DiscoveryServices`, `SuggestionServices`, `ObservabilityServices` dataclasses; refactor `ClusterService.__init__()` to accept 3 grouped objects instead of 16 params; update `build_cluster_service()` in `services.py`
- [ ] **RF-4**: Extract `ClusterRepresentativeRepository`, `ClusterSnapshotRepository`, `CentroidViewRepository` from `cluster_repository.py`; update all import sites; verify no circular imports
- [ ] **RF-5**: Extract `_evaluate_identity_against_cluster()` from both duplicate blocks in `post_merge_retry_matching()`; add unit test for the extracted function
- [ ] **RF-6**: Create `ClusteringPipelineSettings` extending or alongside `HACSettings`; consolidate `verbose_decision_threshold`, `max_unclustered_retry`, `min_unclustered_similarity`, `fallback_rep_limit`, `purge_batch_size`; wire from environment with documented defaults
- [ ] RF-4 extended: Extract `_to_domain()` into a standalone `ClusterDomainAssembler`
- [ ] Introduce `Result[T, E]` monad for `coerce_uuid` and similar fallible conversions
- [ ] Add SQLite dialect proxy in `tenant_context.py` to replace `is_sqlite()` checks (RF-7 extension)

## Success Criteria

- [ ] Assertion guards added to `progress_callback`, `_coerce_tenant`, and `_purge_rows`
- [ ] `refresh_centroids_view_concurrent()` logs before/after row counts and duration on every execution
- [ ] `tenant_context.py` has zero f-string SQL interpolation
- [ ] `tenant_context.py` try/except recovery appears exactly once (extracted helper)
- [ ] `TenantSession` wrapper adopted in orchestrator chunk-commit and `_finalize_job` paths
- [ ] `cluster_unclustered_identities` has no `commit` boolean flag
- [ ] All existing tests pass (648 Python)
