# Recognition Service 502 Remediation Plan

## Problem Statement

After scan/clustering completion, the recognition backend exhausts its DB connection pool (15 max slots), causing generic 500 responses that WordPress surfaces as `502`s or silently degrades into empty `200` payloads. Independently, the suggestion pipeline produces nothing for greenfield tenants with no confirmed labels, compounding the empty-state user experience.

**Scope boundary:** This plan addresses pool-exhaustion-induced 503s and the greenfield suggestion bootstrapping gap. Non-503 upstream failures (e.g., route-specific 500s, network errors) continue to degrade into `data_source: unavailable` empty envelopes intentionally; changing that behavior is out of scope for this task and would require a separate design pass on per-route failure semantics.

## Workflow Principles

- Bug fixes first; structural refactors second. All refactors must demonstrate incident-class improvement, not just code cleanliness.
- New error semantics (`503 database_unavailable`, new `data_source` variants) must be defined as canonical enums/constants and documented in contracts in the same scope as the code change.
- Greenfield policy: prefer clean rewrites over backward-compatibility shims.
- Boundary adapters must not invent ambiguous metadata (rg-015). Error provenance comes from the layer that knows it.

## Terminology

- **Pool exhaustion**: All 15 logical DB connection slots (10 base + 5 overflow) are checked out; new `SELECT 1` probes or session acquisitions block for up to 30s then raise `TimeoutError`.
- **Empty-state masking**: WordPress proxy controllers converting backend 500s into `200` responses with empty payloads, making pool exhaustion indistinguishable from "no data exists."
- **Tenant-context setup**: The sequence of `RESET app.bypass_rls` + `SET LOCAL app.current_tenant` SQL statements issued on every checked-out connection for RLS enforcement.
- **Post-scan read policy**: The `REQUEST_CLASS_POST_SCAN_READ` proxy policy (10s timeout, 1 attempt, no circuit breaker) used by suggestions, media-identities, and name-suggestions routes.

## Current State Analysis

- `db/session.py` creates a shared async engine with `pool_size=10`, `max_overflow=5`, `pool_timeout=30`. Total capacity: 15 connections.
- `deps/session.py::get_optional_session()` does `SELECT 1` + full tenant-context setup before yielding. Under saturation, this "best-effort" probe still requires a real connection.
- `routers/analyze.py::get_job_status()` repeats `ensure_tenant_exists()` + `set_tenant_context()` after `get_optional_session()` already did it; 6+ SQL round-trips per poll instead of 3.
- `exception_handlers.py::generic_exception_handler()` returns raw `exc.__class__.__name__` and `str(exc)` in 500 responses, leaking pool topology (size, overflow, timeout).
- `clustering.py::run_background_surface_suggestions()` is bounded by `asyncio.timeout(30)` but shares the HTTP engine pool. The 30s timeout overlaps exactly with `pool_timeout=30`.
- `refresh_service.py::backfill_for_new_unlabeled_clusters()` returns early when `get_confirmed_labeled()` is empty. The confirmed-label filter excludes synthetic `cluster-*` labels, so only explicit user renaming bootstraps the pipeline.
- `class-suggestions-controller.php` degrades proxy failures (5 call sites) into empty HTTP 200 envelopes.
- `class-media-identities-controller.php` degrades proxy failures into `{ identities_by_media: [], data_source: 'unavailable' }` at HTTP 200.
- D777 added `data_source: backend_proxy | unavailable` distinctions on read paths; D780 added `projection_not_ready` (409) on mutation paths. The remaining gap: read controllers still mask backend 500s via `is_proxy_unavailable()`.

## Proposed Solution

Split remediation into three phases:

1. **Bug fixes** (Phase 1): Address the direct causes and symptoms of the 502 incident; pool exhaustion handling, information disclosure, duplicate tenant setup, and error masking.
2. **Product-contract fixes** (Phase 2): Fix the suggestion bootstrapping gap and the empty-state-masking semantics that make incidents hard to diagnose from the UI.
3. **Structural refactors** (Phase 3): Decompose the tightly coupled code paths that made this incident class likely. These are the refactoring-evaluation items that directly improve this incident class.

## Patterns to Follow

### Structured error response (replace generic_exception_handler leak)

```python
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = str(uuid.uuid4())
    logger.error(
        "unhandled_exception",
        trace_id=trace_id,
        error_class=exc.__class__.__name__,
        message=str(exc),
        path=str(request.url),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "trace_id": trace_id,
            "path": str(request.url),
        },
    )
```

### Pool-exhaustion-specific 503

```python
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

async def pool_exhaustion_handler(request: Request, exc: PoolTimeoutError) -> JSONResponse:
    trace_id = str(uuid.uuid4())
    pool_stats = get_pool_stats()
    logger.error(
        "pool_exhaustion",
        trace_id=trace_id,
        path=str(request.url),
        pool_checked_out=pool_stats["checked_out"],
        pool_size=pool_stats["pool_size"],
    )
    return JSONResponse(
        status_code=503,
        content={
            "error": "database_unavailable",
            "trace_id": trace_id,
            "path": str(request.url),
        },
        headers={"Retry-After": "5"},
    )
```

### Deduplicated tenant context in get_job_status

```python
@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    session: AsyncSession | None = Depends(get_optional_session),
    # ...
):
    # get_optional_session already set tenant context; do NOT repeat
    if session is not None:
        # session is already tenant-aware; query directly
        persisted = await job_persistence_service.get_job(session, job_id)
```

### WP proxy: propagate 503 as structured error instead of empty 200

```php
protected function is_proxy_unavailable( $response ): bool {
    return is_wp_error( $response ) || $response->get_status() >= 500;
}

// New: distinguish 503 from other 5xx
protected function is_backend_overloaded( $response ): bool {
    return ! is_wp_error( $response ) && $response->get_status() === 503;
}
```

## Functions to Change

### Phase 1: Bug Fixes

| File | Function/Symbol | Change |
| --- | --- | --- |
| `apps/prototype-description-service/recognition/interface_adapters/http/exception_handlers.py` | `generic_exception_handler` (L50) | Stop returning `exc.__class__.__name__` and `str(exc)` in response body. Return opaque `internal_server_error` with `trace_id` only. Keep detailed logging server-side. |
| `apps/prototype-description-service/recognition/interface_adapters/http/exception_handlers.py` | (new) `pool_exhaustion_handler` | Add a dedicated handler for `sqlalchemy.exc.TimeoutError` that returns `503 database_unavailable` with `Retry-After` header. Log pool stats at error level. |
| `apps/prototype-description-service/recognition/interface_adapters/http/app.py` | `create_app` or exception handler registration | Register `pool_exhaustion_handler` for `sqlalchemy.exc.TimeoutError` before the generic handler. |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` | `get_job_status` (L223) | Remove duplicate `ensure_tenant_exists()` + `set_tenant_context()` calls; `get_optional_session` already set tenant context on the yielded session. |
| `apps/prototype-description-service/db/settings.py` | `DatabaseSettings` (L22) | Increase dev defaults: `pool_size=20`, `max_overflow=10`. Keep env-var override capability. |
| `apps/prototype-description-service/recognition/application/tasks/clustering.py` | `run_background_surface_suggestions` (L49) | Add a semaphore or bounded concurrency wrapper so background suggestion tasks cannot consume more than N pool slots concurrently (suggest N=3). |

### Phase 2: Product-Contract Fixes

| File | Function/Symbol | Change |
| --- | --- | --- |
| `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py` | `backfill_for_new_unlabeled_clusters` (L691) | When `get_confirmed_labeled()` is empty, generate self-referential suggestions (each unlabeled cluster as its own review item) instead of returning early. This bootstraps the review pipeline for greenfield tenants. |
| `apps/prototype-wp-alt-context/src/api/class-suggestions-controller.php` | 5 call sites using `is_proxy_unavailable` (L203, L229, L250, L344, L404) | When backend returns 503 specifically, return error envelope `{ error: 'backend_overloaded', retry_after: N }` with HTTP 503 instead of empty 200. Keep existing 500-class degradation for non-503 5xx. |
| `apps/prototype-wp-alt-context/src/api/class-media-identities-controller.php` | `is_proxy_unavailable` handling (L104) | Same pattern: 503 from backend propagates as structured 503 error; other 5xx continues existing `data_source: unavailable` degradation. |
| `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | `is_proxy_unavailable` (L212) | Add `is_backend_overloaded()` method that checks specifically for HTTP 503. Subclasses can use this to distinguish pool exhaustion from other upstream failures. |
| `docs/agentic/contracts/clustering-api.md` | Contract documentation | Document `503 backend_overloaded` as a new response type for proxy endpoints. Document updated empty-state semantics: `data_source: unavailable` means non-503 5xx; 503 propagates as-is. |
| `docs/agentic/contracts/recognition-clustering.md` | `/recognition/jobs/{job_id}` response section | Update to document `503 database_unavailable` as a possible response when pool is exhausted. Note that the response no longer leaks raw exception details. |
| `docs/agentic/contracts/clustering-api.md` | `GET /recognition/jobs/{job_id}` section | Update job-status response documentation to reflect that tenant-context setup happens exactly once (in the session dependency) and that 503 is a valid upstream response. |

### Phase 3: Structural Refactors

| File | Function/Symbol | Change |
| --- | --- | --- |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` | `analyze_media` | Split into `_prepare_tenant_context()`, `_prepare_media_items()`, and `_schedule_analysis()` phases. Each phase has distinct error classification (session/tenant vs request-parsing vs queue/background). |
| `apps/prototype-description-service/db/tenant_context.py` | `set_tenant_context` (L45) | Extract a `TenantContext` value object that carries `tenant_id` + `rls_configured` flag. Session dependencies yield `TenantContext` instead of raw `tenant_id` strings, making double-setup impossible by construction. |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | `get_session`, `get_optional_session` | Refactor to yield `(session, TenantContext)` tuples. Callers get tenant info from the tuple instead of re-querying. |
| `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | Full class | Extract a composed `ProxyPolicy` service that encapsulates retry config, timeout, circuit-breaker policy, and failure-degradation rules per route class. Replace inheritance-based dispatch with policy injection. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` | `SyncStatusIndicator` | Extract `useSyncStatusPresentation()` hook that canonicalizes backend-unavailable, projection-pending, projection-failed, and no-review-items into a single typed discriminated union for all consuming surfaces. |
| `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts` | Full file | Split into `jobSelectors.ts` (state queries), `jobDerivation.ts` (computed state), and `jobFormatting.ts` (UI labels). |
| `apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts` | Full file | Extract `useSSEConnection()`, `usePollingFallback()`, and `useBroadcastSync()` sub-hooks so each transport concern is testable independently. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/db/session.py` | Engine creation and pool config; pool_stats query. Read during Phase 1 pool tuning. |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/health.py` | Existing `/health/pool` endpoint. Phase 1 may wire pool stats into failure responses. |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | `get_confirmed_labeled` implementation (L836). Phase 2 may relax the `cluster-*` filter. |
| `apps/prototype-description-service/recognition/domain/repositories.py` | `get_confirmed_labeled` protocol (L214). Must stay in sync with implementation changes. |
| `docs/agentic/contracts/clustering-api.md` | Must be updated in Phase 2 (P5) when 503 propagation and envelope semantics change. |
| `docs/agentic/contracts/recognition-clustering.md` | Must be updated in Phase 1/2 when backend job-status 503 response and tenant-context deduplication change response behavior. |
| `docs/tasks/10.0/10.3/recognition-service-502-audit-2026-03-26.md` | Source audit document. |
| `docs/tasks/tech-debt/refactoring-evaluation.md` | Backend refactoring evaluation referenced by Phase 3. |
| `docs/tasks/tech-debt/refactoring-typescript-evaluation.md` | Frontend refactoring evaluation referenced by Phase 3. |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `backend-domain` | `apps/prototype-description-service/db/**`, `apps/prototype-description-service/recognition/application/**`, `apps/prototype-description-service/recognition/domain/**`, `apps/prototype-description-service/recognition/infrastructure/**` | None | `PYENV_VERSION=description-service pytest recognition/tests/unit/ -q` |
| `backend-http` | `apps/prototype-description-service/recognition/interface_adapters/http/**` | `backend-domain` | `PYENV_VERSION=description-service pytest recognition/tests/unit/ -q` |
| `wp-proxy` | `apps/prototype-wp-alt-context/src/**`, `apps/prototype-wp-alt-context/tests/Unit/**` | `backend-http` (contract only) | `cd apps/prototype-wp-alt-context && composer phpunit` |
| `frontend` | `apps/prototype-wp-alt-context/js/**` | `wp-proxy` (contract only) | `cd apps/prototype-wp-alt-context && npm run test -- --run` |

### Merge Order

1. `backend-domain` (pool settings, TenantContext value object, suggestion bootstrapping, background concurrency bounds)
2. `backend-http` (exception handlers, 503 handler, tenant dedup in get_job_status, analyze_media split, session dep refactor)
3. `wp-proxy` (is_backend_overloaded, 503 propagation, ProxyPolicy extraction, contract doc updates)
4. `frontend` (useSyncStatusPresentation, jobStateMachineUtils split, useJobProgressStream decomposition)

### Manifest

```bash
make lane-manifest-init TASK=recognition-502-remediation LANE_IDS='backend-domain backend-http wp-proxy frontend' TASK_PLAN=docs/tasks/10.0/10.3/recognition-502-remediation-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools (`worker_start_all`, `worker_status`, `worker_stop`) with `backend="codex-subagent"`. The orchestrator daemon dispatches work, intakes merge-ready lanes, and refreshes downstream dependents automatically.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and `make lane-intake` from the orchestrator root.

---

# Consolidated Checklist

## Phase 1: Bug Fixes

> Direct fixes for the 502 incident. Each item addresses a concrete failure path.

- [ ] **B1.** Mask internal details in `generic_exception_handler`: return opaque `internal_server_error` + `trace_id`. Keep `exc.__class__.__name__` and `str(exc)` in server-side logs only.
- [ ] **B2.** Add `pool_exhaustion_handler` for `sqlalchemy.exc.TimeoutError`: return `503 database_unavailable` with `Retry-After: 5` header. Log pool stats (`get_pool_stats()`) at error level.
- [ ] **B3.** Register `pool_exhaustion_handler` in app exception handler setup before the generic handler.
- [ ] **B4.** Remove duplicate `ensure_tenant_exists()` + `set_tenant_context()` in `get_job_status()`. The session from `get_optional_session` is already tenant-aware.
- [ ] **B5.** Increase dev pool defaults in `DatabaseSettings`: `pool_size=20`, `max_overflow=10` (30 total). Keep env-var overrides.
- [ ] **B6.** Add bounded concurrency for `run_background_surface_suggestions`: use `asyncio.Semaphore(3)` so background suggestion work cannot consume more than 3 pool slots concurrently.
- [ ] **B7.** Write unit tests for `pool_exhaustion_handler` (verifies 503 response, no leaked internals).
- [ ] **B8.** Write unit test verifying `generic_exception_handler` no longer returns raw exception class/message.
- [ ] **B9.** Write unit test for `get_job_status` confirming tenant context is set exactly once per request.
- [ ] **B10.** Update `docs/agentic/contracts/recognition-clustering.md`: document `503 database_unavailable` as a valid response from `/recognition/jobs/{job_id}` and note that generic 500 responses no longer leak exception details.

## Phase 2: Product-Contract Fixes

> Fix the product semantics that make incidents hard to diagnose from the UI.

- [ ] **P1.** Add `is_backend_overloaded()` to `AbstractRecognitionProxyController` (checks HTTP 503 specifically).
- [ ] **P2.** In `SuggestionsController`: when `is_backend_overloaded()` is true, return `{ error: 'backend_overloaded', retry_after: N }` with HTTP 503 instead of empty 200.
- [ ] **P3.** In `MediaIdentitiesController`: same 503-propagation pattern as P2.
- [ ] **P4.** Rework `backfill_for_new_unlabeled_clusters()`: when `get_confirmed_labeled()` is empty, generate self-referential suggestions (each unlabeled cluster as its own review item with `reason=bootstrap`) instead of returning early.
- [ ] **P5.** Update `clustering-api.md` contract: document 503 `backend_overloaded` as a valid proxy response type for all proxy endpoints. Update `GET /recognition/jobs/{job_id}` section to reflect 503 as a valid upstream response. Document that `data_source: unavailable` applies only to non-503 5xx degradation.
- [ ] **P6.** Write PHP unit tests for `is_backend_overloaded()` and 503-propagation in SuggestionsController.
- [ ] **P7.** Write Python unit tests for greenfield suggestion bootstrapping (backfill with zero confirmed labels produces self-referential suggestions).

## Phase 3: Structural Refactors

> Code decomposition that makes this incident class less likely and easier to debug. Each item maps to a finding in the refactoring evaluations.

- [ ] **R1.** Split `analyze_media()` into `_prepare_tenant_context()`, `_prepare_media_items()`, `_schedule_analysis()`.
- [ ] **R2.** Extract `TenantContext` value object; refactor `get_session`/`get_optional_session` to yield `(session, TenantContext)` tuples.
- [ ] **R3.** Extract `ProxyPolicy` service from `AbstractRecognitionProxyController`; replace inheritance dispatch with policy injection.
- [ ] **R4.** Extract `useSyncStatusPresentation()` hook with a typed discriminated union for sync/projection/availability states.
- [ ] **R5.** Split `jobStateMachineUtils.ts` into `jobSelectors.ts`, `jobDerivation.ts`, `jobFormatting.ts`.
- [ ] **R6.** Extract `useSSEConnection()`, `usePollingFallback()`, `useBroadcastSync()` from `useJobProgressStream`.
- [ ] **R7.** Centralize status enums/constants for projection states, sync health, data-source semantics across TypeScript surfaces.
- [ ] **R8.** Write/update tests for all refactored functions (maintain existing coverage).

## Stretch Goals

- [ ] Surface pool utilization in the WordPress admin debug panel by proxying `/health/pool` through a new admin-only REST endpoint.
- [ ] Add structured latency instrumentation (p50/p95/p99) for pool checkout wait and handler execution time.
- [ ] Add adaptive timeout tuning for the post-scan read policy based on recent pool utilization.

## Success Criteria

- [ ] Pool-exhaustion failures return `503 database_unavailable` with `trace_id`; no raw exception details in any HTTP response.
- [ ] Job-status polling executes tenant-context SQL exactly once per request (verified by test).
- [ ] Background suggestion tasks are bounded to 3 concurrent pool slots (verified by test).
- [ ] Backend 503 propagates through WordPress proxy as a structured 503 error, not as an empty 200.
- [ ] Non-503 upstream failures (route-specific 500s, network errors) continue to degrade into `data_source: unavailable` empty envelopes intentionally (existing behavior preserved).
- [ ] Greenfield tenants with zero confirmed labels receive self-referential review suggestions after clustering.
- [ ] Contract docs (`clustering-api.md`, `recognition-clustering.md`) updated to reflect 503 response type and masked-error changes.
- [ ] All existing tests continue to pass after each phase.
