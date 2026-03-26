# Recognition Service 502 Remediation Plan

## Problem Statement

After scan/clustering completion, the recognition backend exhausts its DB connection pool (15 max slots), causing generic 500 responses that WordPress surfaces as `502`s or silently degrades into empty `200` payloads. Independently, the suggestion pipeline produces nothing for greenfield tenants with no confirmed labels, compounding the empty-state user experience.

**Scope boundary:** This plan addresses pool-exhaustion-induced 503s and the greenfield suggestion bootstrapping gap. Non-503 upstream failures (e.g., route-specific 500s, network errors) continue to degrade into `data_source: unavailable` empty envelopes intentionally; changing that behavior is out of scope for this task and would require a separate design pass on per-route failure semantics.

## Workflow Principles

- Bug fixes first; structural refactors second. All refactors must demonstrate incident-class improvement, not just code cleanliness.
- New error semantics (`503 database_unavailable`, new `data_source` variants) must be defined as canonical enums/constants and documented in contracts in the same scope as the code change.
- Greenfield policy: prefer clean rewrites over backward-compatibility shims.
- Boundary adapters must not invent ambiguous metadata (rg-015). Error provenance comes from the layer that knows it.
- WordPress-style PHP runtime classes introduced under `src/` must have a deterministic load path (`require_once` from the owning runtime entrypoint or PSR-4-compliant filename) and a runtime parity verification step. PHPUnit alone is not sufficient here (rg-016).

## Terminology

- **Pool exhaustion**: All 15 logical DB connection slots (10 base + 5 overflow) are checked out; new `SELECT 1` probes or session acquisitions block for up to 30s then raise `TimeoutError`.
- **Empty-state masking**: WordPress proxy controllers converting backend 500s into `200` responses with empty payloads, making pool exhaustion indistinguishable from "no data exists."
- **Tenant-context setup**: The sequence of `RESET app.bypass_rls` + `SET LOCAL app.current_tenant` SQL statements issued on every checked-out connection for RLS enforcement.
- **Post-scan read policy**: The `REQUEST_CLASS_POST_SCAN_READ` proxy policy (10s timeout, 1 attempt, no circuit breaker) used by suggestions, media-identities, and name-suggestions routes.

## Current State Analysis

**Already fixed (verified 2026-03-26):**

- `exception_handlers.py::generic_exception_handler()` already returns opaque `internal_server_error` + `trace_id` (no leaked exception details).
- `exception_handlers.py::pool_exhaustion_handler()` already exists; returns `503 database_unavailable` with `Retry-After: 5` and logs pool stats.
- `exception_handlers.py::integrity_exception_handler()` fallback now returns opaque `integrity_error` + `trace_id` instead of leaking raw constraint details.
- Internal error payload construction is now centralized in a shared opaque-response helper inside `exception_handlers.py`, reducing drift between generic, pool, and integrity failure paths.
- `exception_handlers.py::register_exception_handlers()` already registers `PoolTimeoutError` before `Exception`.
- `routers/analyze.py::get_job_status()` no longer has duplicate `ensure_tenant_exists()` + `set_tenant_context()` calls; it uses the session from `get_optional_session` directly.
- `db/settings.py::get_database_settings()` now uses higher default pool fallbacks (`20` size / `10` overflow) while preserving env-var overrides.
- `clustering.py::run_background_surface_suggestions()` now uses a shared semaphore to cap concurrent surfacing tasks.
- `refresh_service.py::backfill_for_new_unlabeled_clusters()` now bootstraps self-referential suggestions when `get_confirmed_labeled()` is empty.
- `class-suggestions-controller.php` and `class-media-identities-controller.php` now preserve backend `503` as explicit WP `503 backend_overloaded` responses instead of degrading them into empty `200` payloads.
- `class-abstract-recognition-proxy-controller.php` now explicitly loads `class-recognition-proxy-policy.php`, and `ProxyRequestTest` includes a runtime-style autoload parity check for that dependency.
- `docs/agentic/contracts/recognition-clustering.md` already documents `503 database_unavailable` for `/recognition/jobs/{job_id}`.

**Still outstanding:**

 - `db/session.py` still uses one shared async engine for HTTP request work and background surfacing/backfill work. Default capacity is now `20 + 10 overflow` with `pool_timeout=30`, but the shared-pool architecture remains.
- `deps/session.py::get_optional_session()` does `SELECT 1` + full tenant-context setup before yielding. Under saturation, this "best-effort" probe still requires a real connection.
- `clustering.py::run_background_surface_suggestions()` is bounded by `asyncio.timeout(30)` and now concurrency-capped, but it still shares the HTTP engine pool.
- `apps/prototype-wp-alt-context/src/api/class-recognition-proxy-policy.php` now owns request-policy resolution, but the abstract proxy controller still lazily instantiates that service instead of accepting explicit injection. Failure-degradation ownership is still partly embedded in the controller base.
- `RecognitionProxyPolicy` currently relies on a WordPress-style `class-*.php` filename and therefore needs explicit runtime loading discipline. The immediate include is fixed, but the remaining extraction work still needs to make runtime loading deterministic by construction instead of depending on Composer classmap freshness.
- `class-recognition-controller.php` eagerly instantiates proxy-backed controllers inside `__construct()`, so a proxy-composition failure can take down unrelated routes like `analyze` and `jobs` before any route-specific logic runs.
- `routers/analyze.py::analyze_media()` is now split into `_prepare_media_items()`, `_prepare_tenant_context()`, and `_schedule_analysis()`, so request validation, tenant/session setup, and job scheduling have distinct failure seams.
- `deps/session.py` and `routers/analyze.py` now emit structured timing samples for session setup/probe time and analyze-handler execution time; percentile aggregation and adaptive tuning remain stretch work.

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

| File                                                                                           | Function/Symbol                                | Change                                                                                                                                                                                               |
| ---------------------------------------------------------------------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/recognition/interface_adapters/http/exception_handlers.py` | `generic_exception_handler` (L53)              | ~~Already done.~~ Returns opaque `internal_server_error` + `trace_id`. No code change needed.                                                                                                        |
| `apps/prototype-description-service/recognition/interface_adapters/http/exception_handlers.py` | `pool_exhaustion_handler` (L68)                | ~~Already done.~~ Returns `503 database_unavailable` with `Retry-After: 5` and logs pool stats. No code change needed.                                                                               |
| `apps/prototype-description-service/recognition/interface_adapters/http/exception_handlers.py` | `integrity_exception_handler` fallback (~L130) | ~~Already done.~~ Fallback now returns opaque `integrity_error` + `trace_id` and uses the shared opaque-response helper. No code change needed. |
| `apps/prototype-description-service/recognition/interface_adapters/http/exception_handlers.py` | `register_exception_handlers` (L139)           | ~~Already done.~~ `PoolTimeoutError` registered before `Exception`. No code change needed.                                                                                                           |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`    | `get_job_status` (L222)                        | ~~Already done.~~ No duplicate `ensure_tenant_exists()` + `set_tenant_context()` calls remain. No code change needed.                                                                                |
| `apps/prototype-description-service/db/settings.py`                                            | `get_database_settings` (~L100)                | ~~Already done.~~ Env-var fallback defaults now use `DB_POOL_SIZE=20` and `DB_MAX_OVERFLOW=10`. No code change needed.                                                                              |
| `apps/prototype-description-service/recognition/application/tasks/clustering.py`               | `run_background_surface_suggestions` (L49)     | ~~Already done.~~ Shared semaphore now bounds concurrent background surfacing tasks. No code change needed.                                                                                           |

### Phase 2: Product-Contract Fixes

| File                                                                                        | Function/Symbol                                                          | Change                                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py` | `backfill_for_new_unlabeled_clusters` (L691)                             | When `get_confirmed_labeled()` is empty, generate self-referential suggestions (each unlabeled cluster as its own review item) instead of returning early. This bootstraps the review pipeline for greenfield tenants. |
| `apps/prototype-wp-alt-context/src/api/class-suggestions-controller.php`                    | 5 call sites using `is_proxy_unavailable` (L203, L229, L250, L344, L404) | When backend returns 503 specifically, return error envelope `{ error: 'backend_overloaded', retry_after: N }` with HTTP 503 instead of empty 200. Keep existing 500-class degradation for non-503 5xx.                |
| `apps/prototype-wp-alt-context/src/api/class-media-identities-controller.php`               | `is_proxy_unavailable` handling (L104)                                   | Same pattern: 503 from backend propagates as structured 503 error; other 5xx continues existing `data_source: unavailable` degradation.                                                                                |
| `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php`     | `is_proxy_unavailable` (L212)                                            | Add `is_backend_overloaded()` method that checks specifically for HTTP 503. Subclasses can use this to distinguish pool exhaustion from other upstream failures.                                                       |
| `docs/agentic/contracts/clustering-api.md`                                                  | Contract documentation                                                   | Document `503 backend_overloaded` as a new response type for proxy endpoints. Document updated empty-state semantics: `data_source: unavailable` means non-503 5xx; 503 propagates as-is.                              |
| `docs/agentic/contracts/recognition-clustering.md`                                          | `/recognition/jobs/{job_id}` response section                            | Update to document `503 database_unavailable` as a possible response when pool is exhausted. Note that the response no longer leaks raw exception details.                                                             |
| `docs/agentic/contracts/clustering-api.md`                                                  | `GET /recognition/jobs/{job_id}` section                                 | Update job-status response documentation to reflect that tenant-context setup happens exactly once (in the session dependency) and that 503 is a valid upstream response.                                              |

### Phase 3: Structural Refactors

| File                                                                                        | Function/Symbol                       | Change                                                                                                                                                                                                                  |
| ------------------------------------------------------------------------------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` | `analyze_media`                       | Split into `_prepare_tenant_context()`, `_prepare_media_items()`, and `_schedule_analysis()` phases. Each phase has distinct error classification (session/tenant vs request-parsing vs queue/background).              |
| `apps/prototype-description-service/db/tenant_context.py`                                   | `set_tenant_context` (L45)            | Extract a `TenantContext` value object that carries `tenant_id` + `rls_configured` flag. Session dependencies yield `TenantContext` instead of raw `tenant_id` strings, making double-setup impossible by construction. |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py`    | `get_session`, `get_optional_session` | Refactor to yield `(session, TenantContext)` tuples. Callers get tenant info from the tuple instead of re-querying.                                                                                                     |
| `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php`     | Full class                            | Finish the `RecognitionProxyPolicy` extraction by moving the remaining failure-degradation ownership out of the abstract controller, replacing lazy construction with explicit policy injection, and keeping runtime loading deterministic without relying on Composer classmap freshness. |
| `apps/prototype-wp-alt-context/src/api/class-recognition-proxy-policy.php`                  | Full class                            | Extend the extracted policy service so route-class policy, degradation rules, and overload handling are owned outside the abstract controller seam. If it remains a WordPress-style `class-*.php` file, keep an explicit runtime include from the owning entrypoint; otherwise rename to a PSR-4-compliant path. |
| `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`                    | `__construct`, `register_routes`      | Reduce proxy-composition blast radius so analysis-job routes can remain available even if proxy-backed controller construction fails. Prefer lazy/controller-local construction or another guarded composition seam instead of eagerly instantiating every proxy-backed controller up front. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx`            | `SyncStatusIndicator`                 | Extract `useSyncStatusPresentation()` hook that canonicalizes backend-unavailable, projection-pending, projection-failed, and no-review-items into a single typed discriminated union for all consuming surfaces.       |
| `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts`                      | Full file                             | Split into `jobSelectors.ts` (state queries), `jobDerivation.ts` (computed state), and `jobFormatting.ts` (UI labels).                                                                                                  |
| `apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts`                      | Full file                             | Extract `useSSEConnection()`, `usePollingFallback()`, and `useBroadcastSync()` sub-hooks so each transport concern is testable independently.                                                                           |

## Related Files

| File                                                                                               | Note                                                                                                                         |
| -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/db/session.py`                                                 | Engine creation and pool config; pool_stats query. Read during Phase 1 pool tuning.                                          |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/health.py`         | Existing `/health/pool` endpoint. Phase 1 may wire pool stats into failure responses.                                        |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | `get_confirmed_labeled` implementation (L836). Phase 2 may relax the `cluster-*` filter.                                     |
| `apps/prototype-description-service/recognition/domain/repositories.py`                            | `get_confirmed_labeled` protocol (L214). Must stay in sync with implementation changes.                                      |
| `docs/agentic/contracts/clustering-api.md`                                                         | Must be updated in Phase 2 (P5) when 503 propagation and envelope semantics change.                                          |
| `docs/agentic/contracts/recognition-clustering.md`                                                 | Must be updated in Phase 1/2 when backend job-status 503 response and tenant-context deduplication change response behavior. |
| `docs/tasks/10.0/10.3/recognition-service-502-audit-2026-03-26.md`                                 | Source audit document.                                                                                                       |
| `docs/tasks/tech-debt/refactoring-evaluation.md`                                                   | Backend refactoring evaluation referenced by Phase 3.                                                                        |
| `docs/tasks/tech-debt/refactoring-typescript-evaluation.md`                                        | Frontend refactoring evaluation referenced by Phase 3.                                                                       |
| `apps/prototype-wp-alt-context/tests/bootstrap.php`                                                | PHPUnit fallback autoloader can hide runtime-loading regressions; keep runtime parity tests alongside PHPUnit coverage.      |
| `apps/prototype-wp-alt-context/composer.json`                                                      | `classmap` autoload can make WordPress-style runtime class loading depend on local `composer dump-autoload` freshness.      |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID          | Owned Paths                                                                                                                                                                                                                                 | Upstream Dependencies          | Required Tests                                                        |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | --------------------------------------------------------------------- |
| `backend-domain` | `apps/prototype-description-service/db/**`, `apps/prototype-description-service/recognition/application/**`, `apps/prototype-description-service/recognition/domain/**`, `apps/prototype-description-service/recognition/infrastructure/**` | None                           | `PYENV_VERSION=description-service pytest recognition/tests/unit/ -q` |
| `backend-http`   | `apps/prototype-description-service/recognition/interface_adapters/http/**`                                                                                                                                                                 | `backend-domain`               | `PYENV_VERSION=description-service pytest recognition/tests/unit/ -q` |
| `wp-proxy`       | `apps/prototype-wp-alt-context/src/**`, `apps/prototype-wp-alt-context/tests/Unit/**`                                                                                                                                                       | `backend-http` (contract only) | `cd apps/prototype-wp-alt-context && composer phpunit` plus a runtime-style `php -r` autoload/bootstrap parity check for new WordPress-style classes |
| `frontend`       | `apps/prototype-wp-alt-context/js/**`                                                                                                                                                                                                       | `wp-proxy` (contract only)     | `cd apps/prototype-wp-alt-context && npm run test -- --run`           |

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

- [x] **B1.** ~~Mask internal details in `generic_exception_handler`.~~ Already implemented; returns opaque `internal_server_error` + `trace_id`.
- [x] **B2.** ~~Add `pool_exhaustion_handler` for `sqlalchemy.exc.TimeoutError`.~~ Already implemented; returns `503 database_unavailable` with `Retry-After: 5`.
- [x] **B3.** ~~Register `pool_exhaustion_handler` before the generic handler.~~ Already done in `register_exception_handlers`.
- [x] **B4.** ~~Remove duplicate `ensure_tenant_exists()` + `set_tenant_context()` in `get_job_status()`.~~ Already fixed; no duplicate calls remain.
- [x] **B5.** ~~Increase dev pool defaults in `get_database_settings()`.~~ Implemented with env-var fallbacks `20` / `10`, keeping overrides intact.
- [x] **B6.** ~~Add bounded concurrency for `run_background_surface_suggestions`.~~ Implemented with a shared `asyncio.Semaphore(3)`.
- [x] **B7.** ~~Write unit tests for `pool_exhaustion_handler`.~~ Covered by focused API tests.
- [x] **B8.** ~~Write unit test verifying `generic_exception_handler` no longer returns raw exception class/message.~~ Covered by focused API tests.
- [x] **B8b.** ~~Mask internal details in `integrity_exception_handler` fallback.~~ Implemented and covered by focused API tests. _(Added per P1-LEAK review finding.)_
- [x] **B9.** ~~Write unit test for `get_job_status` confirming tenant context is set exactly once per request.~~ Covered by focused API tests.
- [x] **B10.** ~~Update `recognition-clustering.md` to document `503 database_unavailable`.~~ Already documented at L58.

## Phase 2: Product-Contract Fixes

> Fix the product semantics that make incidents hard to diagnose from the UI.

- [x] **P1.** Added `is_backend_overloaded()` to `AbstractRecognitionProxyController` (checks HTTP 503 specifically) and preserved upstream headers through `proxy_request()`.
- [x] **P2.** `SuggestionsController` now returns `{ error: 'backend_overloaded', retry_after: N }` with HTTP 503 for backend overload while keeping non-503 degradation unchanged.
- [x] **P3.** `MediaIdentitiesController` now follows the same 503-propagation pattern as `SuggestionsController`.
- [x] **P4.** `backfill_for_new_unlabeled_clusters()` now bootstraps self-referential suggestions when there are no confirmed labels, using `source=bootstrap`.
- [x] **P5.** `clustering-api.md` now documents proxy `503 backend_overloaded` semantics and clarifies that `data_source: unavailable` applies only to non-503 degradation.
- [x] **P6.** Added PHP unit tests for `is_backend_overloaded()` and 503 propagation in `SuggestionsController` and `MediaIdentitiesController`.
- [x] **P7.** Added Python unit tests for greenfield suggestion bootstrapping.

## Phase 3: Structural Refactors

> Code decomposition that makes this incident class less likely and easier to debug. Each item maps to a finding in the refactoring evaluations.

- [x] **R1.** `analyze_media()` is now split into `_prepare_tenant_context()`, `_prepare_media_items()`, and `_schedule_analysis()`, isolating request parsing, tenant/session setup, and job scheduling.
- [ ] **R2.** Extract `TenantContext` value object; refactor `get_session`/`get_optional_session` to yield `(session, TenantContext)` tuples.
- [ ] **R3.** Finish the `RecognitionProxyPolicy` extraction from `AbstractRecognitionProxyController`; request-policy resolution now lives in the service, but remaining degradation ownership, explicit injection, and deterministic runtime loading still need to move there.
- [ ] **R3b.** Reduce proxy-controller composition blast radius in `RecognitionController` so non-proxy routes such as `analyze` and job polling are not taken down by proxy-specific composition failures.
- [ ] **R4.** Extract `useSyncStatusPresentation()` hook with a typed discriminated union for sync/projection/availability states.
- [ ] **R5.** Split `jobStateMachineUtils.ts` into `jobSelectors.ts`, `jobDerivation.ts`, `jobFormatting.ts`.
- [ ] **R6.** Extract `useSSEConnection()`, `usePollingFallback()`, `useBroadcastSync()` from `useJobProgressStream`.
- [ ] **R7.** Centralize status enums/constants for projection states, sync health, data-source semantics across TypeScript surfaces.
- [ ] **R8.** Write/update tests for all refactored functions (maintain existing coverage).

## Stretch Goals

- [ ] Surface pool utilization in the WordPress admin debug panel by proxying `/health/pool` through a new admin-only REST endpoint.
- [ ] Add percentile aggregation (p50/p95/p99) on top of the new structured latency timing samples for pool checkout wait and handler execution time.
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
