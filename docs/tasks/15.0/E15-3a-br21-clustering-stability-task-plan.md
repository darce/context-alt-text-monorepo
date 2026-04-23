# E15-3a-BR-21. Clustering-jobs write-path stability (breaker + bulkhead + fail-fast)

> **Task Short ID**: E15-3a-BR-21
> **Status**: scoped -- awaiting `/planning-review`
> **Date**: 2026-04-23
> **Owning Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 3
> **Parent task**: [E15-3a LocalWP -> OCI Backend Round-Trip Verification](./E15-3a-localwp-oci-roundtrip-task-plan.md) finding `E15-3a-BR-21`
> **Backing scope**: [`docs/scopes/e15-3a-br21-clustering-stability-scope.md`](../../scopes/e15-3a-br21-clustering-stability-scope.md) v2
> **Backing assessment**: [`docs/assessments/e15-3a-br21-clustering-insert-statement-timeout-2026-04-23.md`](../../assessments/e15-3a-br21-clustering-insert-statement-timeout-2026-04-23.md)
> **Target Branch**: `feature/e15-3a`
> **Review Coverage Target**: 2

---

## Objective

Close `E15-3a-BR-21`: make `POST /recognition/clustering/jobs` fail fast (<1 s, backend-measured) when a zombie `idle in transaction` session holds the tenants row lock, and make recurrence detectable and bounded. When this task is complete, BR-21's `QueryCanceledError` at the 10 s cliff is replaced by an explicit `503 Retry-After` admission response, the clustering write path runs on an isolated pool, a cooldown breaker prevents convoy under sustained failure, and WordPress plugin callers see the 503 on first attempt instead of a 3x retry storm.

## Problem Statement

Evidence in the backing assessment §2-§3 shows that a `POST /recognition/clustering/jobs` request terminates with asyncpg `QueryCanceledError` on `INSERT INTO identity_clustering_jobs` at 10,014 ms -- exactly `db.settings.statement_timeout=10s`. Most-likely root cause: a prior request acquired `SELECT ... FOR UPDATE` on the tenants row in `recognition/interface_adapters/http/routers/clusters.py:209`, its task was canceled asyncio-side before the transaction rolled back, and the connection went into `idle in transaction` still holding the lock. Every subsequent request for that tenant waits 10 s on the lock, then dies. The 10 s `statement_timeout` is the Nygard fault-isolation boundary working as designed (it stops the bleed) -- the defect is in the surrounding layers that let the zombie exist and that consume the whole business pool while waiting.

Four layers must change to close this:

1. The clustering route must refuse to enter a transaction when a conflicting `pg_locks` row exists (admission-side fail-fast).
2. The tenants `SELECT ... FOR UPDATE` must run under a bounded per-statement timeout so the worst-case wait is 1 s, not 10 s.
3. The clustering write path must run on a dedicated small pool so saturation does not consume the business pool used by `/recognition/analyze`.
4. The WordPress mutation proxy must treat a backend `503 Retry-After` as the single authoritative response, not retry it 3x with exponential backoff.

## Non-Goals (explicit)

- Do not widen `statement_timeout` from 10 s globally. It is the fault-isolation boundary; widening it reintroduces the 2026-04-09 failure mode.
- Do not remove `SELECT ... FOR UPDATE` on tenants. The idempotent-job guarantee depends on it; this task bounds the wait, it does not remove the lock.
- Do not replace asyncpg or change the driver.
- Do not refactor `/recognition/analyze`; the bulkhead protects it without touching its code.
- Do not modify `get_session()` or any non-clustering router's session lifecycle. The new `get_clustering_session()` is additive. A broader `get_session()` audit is a follow-on.
- Do not build a global cross-endpoint circuit-breaker registry. BR-21 scope is the clustering-jobs write path only.
- Do not overhaul the plugin mutation-proxy retry engine. S5 narrows policy for `503 Retry-After` only.
- Do not gate merge on LocalWP end-to-end latency. The `<1 s` SLO is backend-measured (FastAPI entry -> response). LocalWP latency goes into the run log as evidence, not as a merge gate.
- Do not gate merge on a new operational runbook. The diagnostic SQL already lives in §6 of the backing assessment.

## Constraints

- Scope is limited to `apps/prototype-description-service/` for Python slices (S1-S4) and `apps/prototype-wp-alt-context/` for the PHP slice (S5).
- The new clustering-dedicated circuit breaker is **separate** from the existing session-dependency breaker in `recognition/interface_adapters/http/deps/circuit_breaker.py` (SLR-3). That breaker guards per-request DB probe failures at the dependency boundary; this one guards `QueryCanceledError` counts on the clustering write path specifically.
- The new `get_clustering_session()` dependency is **additive**. Every other router keeps its existing `get_session()` dependency semantics.
- Breaker state must be deterministic and testable with injected clocks; no third-party breaker library.
- The whole clustering-jobs handler unit-of-work (`SELECT ... FOR UPDATE` -> active-job lookup -> INSERT) must run inside one `async with session.begin():` block on one connection from the bulkheaded pool. Atomicity is non-negotiable; this is the PLAN-01 fix.
- **Safety-settings composition (PLAN-08, amended by PLAN-10).** `_apply_postgres_session_safety_settings` in `deps/session.py:42` already issues `SET LOCAL statement_timeout='10s'` and `SET LOCAL idle_in_transaction_session_timeout='30s'` at every session open. Because `SET LOCAL` triggers SQLAlchemy autobegin, calling the helper **inside** `get_clustering_session` would start a transaction before the route can claim ownership via `async with session.begin():`. The route-owned model in PLAN-04/PLAN-10 therefore moves the call site: `get_clustering_session` does **not** call the helper at session open (and does **not** issue any other `execute`); the route's `async with session.begin():` block calls `_apply_postgres_session_safety_settings(session)` as its **first** statement, then immediately captures `pg_backend_pid` and sets tenant context, then issues an additional `SET LOCAL statement_timeout='<clustering_tenant_lock_timeout_ms>ms'` immediately before `SELECT ... FOR UPDATE`, then restores `SET LOCAL statement_timeout='10s'` immediately after the SELECT so the active-job lookup and INSERT keep the default budget. The default safety envelope is identical to `get_session`; only the call site moves from the dependency to the route.
- **All three injected dependencies on `POST /recognition/clustering/jobs`** (`session`, `cluster_service_builder`, `job_service`) must resolve to the **same clustering session** inside the handler. The route currently mixes `session=Depends(get_session)` with `cluster_service_builder=Depends(get_cluster_service_builder)` (itself `Depends(get_session)`) and `job_service=Depends(get_persisted_cluster_job_service)` (itself `Depends(get_optional_session)`), and relies on FastAPI's DI cache to hand them the same session instance. Swapping only the route's explicit `session` to `get_clustering_session()` would put the active-job lookup and INSERT on a different session than the `SELECT FOR UPDATE`, breaking atomicity. This is the PLAN-04 fix.
- **Transaction ownership (PLAN-10).** `get_clustering_session` yields a freshly opened `AsyncSession` from `clustering_async_session_factory` and **must not** issue any `execute` (no safety SET LOCAL, no tenant context, no `SELECT pg_backend_pid()`) before yielding -- otherwise SQLAlchemy autobegin starts a transaction the route cannot claim. The dep's only responsibilities are: consult the clustering breaker (S3), open the session, yield, and `await session.close()` in `finally`. The route owns the transaction via `async with session.begin():` and is responsible for safety settings, tenant context, pg_backend_pid capture, the admission probe, and the full unit-of-work. Commit happens automatically on context exit; rollback on exception. This is the inverse of the dep-owned `get_session` model and is required for the PLAN-04 atomicity guarantee.
- **Service-factory autobegin path (PLAN-11).** The clustering-flavored job-service factory `get_persisted_cluster_job_service_clustering` **must not** call the shared `get_job_service()` helper in `deps/services.py:538-568`. That helper probes any real session with `await session.execute(text("SELECT 1"))` and, when `tenant_id` is present, calls `await set_tenant_context(session, ...)`; both statements trigger SQLAlchemy autobegin on the clustering session **before** FastAPI returns from dependency resolution, so the route would enter `async with session.begin():` on a session that already has an open transaction. The clustering-flavored factory therefore constructs `JobService` directly -- `JobService(repository=SqlAlchemyJobRepository(session), cluster_service=<awaited builder>, scan_service=None)` -- with no pre-yield `execute` and no pre-yield tenant-context call. Tenant context is set by the route inside the owned transaction (PLAN-10 ordering). This is an explicit divergence from `get_persisted_cluster_job_service` for the same reason `get_clustering_session` diverges from `get_session`: the clustering path is the one route in the codebase where the handler, not the dependency graph, owns the first transaction.
- **Cluster-service builder autobegin path (PLAN-12).** `build_cluster_service` in `deps/services.py:325-404` calls `await set_tenant_context(session, tenant_uuid)` (line 337) and `await ensure_tenant_exists(session, tenant_uuid)` (line 339) before returning the constructed `ClusterService`. The clustering-flavored job-service factory `get_persisted_cluster_job_service_clustering` therefore **must not pre-await `cluster_service_builder(tenant_id)`** during dep resolution to fill the `JobService.cluster_service` slot -- doing so would trigger that SQL on the clustering session before the route enters `async with session.begin():` and would defeat PLAN-10/PLAN-11. The factory passes `cluster_service=None` and the route is responsible for invoking the builder **inside** its own owned txn block, immediately after `_apply_postgres_session_safety_settings(session)` and `set_tenant_context(session, ...)` land, so the builder's internal `set_tenant_context`/`ensure_tenant_exists` statements join the route-owned txn rather than starting a new one. After awaiting the builder the route either re-assigns `job_service.cluster_service = cluster_service` or constructs the JobService inline; either pattern keeps every clustering-session SQL statement inside the route-owned txn boundary.
- **Breaker composition (PLAN-09).** `get_clustering_session` **does not** invoke the existing SLR-3 session-dependency breaker (`_get_session_dependency_breaker` in `deps/session.py:114`). The dedicated clustering pool and the clustering admission probe make the generic per-request probe-failure signal redundant with pool saturation, and stacking the two breakers would produce ambiguous open-state semantics. The clustering breaker introduced in S3 is the **sole** fail-fast surface for `POST /recognition/clustering/jobs`. Other routers keep the SLR-3 breaker behavior via their existing `get_session`/`get_optional_session`/`get_observability_session` dependencies.
- WP plugin changes must preserve retry behavior for transport errors, `502`, and `504`. Only `503` **with** a `Retry-After` header is newly non-retryable.
- Greenfield policy applies: no schema migrations, no data migrations, no back-compat shims.

## Workflow Principles

- Observability lands first so subsequent slices can prove their own behavior in logs.
- Fail-fast before isolation: S2 (admission timeout) unblocks the E15-3a Slice 2 roundtrip gate even before S3/S4 land.
- One concept, one owner: the clustering breaker and clustering pool live beside the clustering route path, not hidden in generic DB infrastructure.
- Tests assert timing, not just status codes. Fail-fast claims require a measured `<1,000 ms` assertion.

## Terminology

- **Clustering write path**: the `POST /recognition/clustering/jobs` handler in `clusters.py:171-217`, including the tenants `SELECT ... FOR UPDATE` on line 209 and the save-in-CLUSTERING repository call.
- **Zombie lock-holder**: a Postgres backend in state `idle in transaction` still holding a row lock because its driving request was canceled before commit/rollback.
- **Admission fail-fast**: refusing to enter a DB transaction based on a cheap pre-flight probe (`pg_locks`), returning `503 Retry-After` to the caller.
- **Clustering pool / bulkhead**: a dedicated `AsyncEngine` with `pool_size=2, max_overflow=1` used only by the clustering write path, so exhaustion there cannot starve the business pool.
- **Backend-measured latency**: wall-clock time from FastAPI request entry to response emission, as measured inside the app. Distinct from LocalWP end-to-end latency.

## Current State Analysis

- `recognition/interface_adapters/http/routers/clusters.py:171-217` performs the tenants `SELECT ... FOR UPDATE` (line 209), an active-job lookup, and an INSERT in the CLUSTERING save path. All three run under `get_session()` (shared business pool) and across multiple repository calls, not wrapped in a single `async with session.begin():`.
- `recognition/infrastructure/repositories/job_repository.py:42-64` performs the INSERT; line 61 is the `await self._session.flush()` that asyncpg cancels at 10 s.
- `db/session.py:31-59` already defines `engine`/`async_session_factory` for the business pool and `observability_engine`/`observability_async_session_factory` for the SLR-4 observability pool. The clustering pool will follow the same pattern.
- `db/settings.py` exposes `statement_timeout=10` (seconds) for the session-level default and the SLR-3/SLR-4 pool knobs. No clustering-specific knobs exist yet.
- `recognition/interface_adapters/http/deps/circuit_breaker.py` contains the SLR-3 session-dependency breaker (probes at checkout). It is **not** on the clustering write path.
- `apps/prototype-wp-alt-context/src/api/class-recognition-proxy-policy.php:51-52` defines the mutation policy `max_retries=3, base_delay_ms=500`. `class-abstract-recognition-proxy-controller.php:118-119` retries any `status >= 500` without inspecting `Retry-After`.
- WP proxy controller currently forwards `Retry-After` to the caller (per E15-3a Non-Goals), but only after the retry loop has already consumed 3 attempts.

## Target Outcome

1. A request to `POST /recognition/clustering/jobs` against a tenant whose row is held by a zombie `idle in transaction` session returns `503 Service Unavailable` with `Retry-After: 5` in `<1,000 ms` backend-measured.
2. Three consecutive `QueryCanceledError`s in a 30 s rolling window open the clustering breaker; subsequent requests get `503` in `<10 ms` without touching the DB, until the 30 s cooldown elapses and the breaker half-opens.
3. Saturating the clustering pool (2 slots + 1 overflow) does not block a concurrent `/health/detailed` or `/recognition/analyze` request on the business pool.
4. A WordPress plugin caller observing a backend `503 Retry-After` surfaces that response immediately on the first attempt; `502`/`504`/transport errors continue to retry under the existing mutation policy.
5. Every clustering-jobs request's structured log record contains `correlation_id` and `pg_backend_pid`, and admission-latency is exposed as a `/metrics` histogram.

## Context Loading

- Scope: `docs/scopes/e15-3a-br21-clustering-stability-scope.md` (v2)
- Assessment: `docs/assessments/e15-3a-br21-clustering-insert-statement-timeout-2026-04-23.md`
- Prior precedent: `docs/assessments/infailed-sql-transaction-investigation-2026-04-09.md`
- Related ADR: `docs/adrs/ADR-006-session-circuit-breaker-and-pool-bulkheading.md`
- Related tasks: `docs/tasks/15.0/slr-3-session-dependency-circuit-breaker-task-plan.md`, `docs/tasks/15.0/slr-4-observability-pool-bulkhead-task-plan.md`
- Rules: `docs/agentic/rules/backend-python-guidelines.md`, `docs/agentic/rules/testing-python.md`, `docs/agentic/rules/backend-php-guidelines.md`, `docs/agentic/rules/testing-php.md`
- Contracts: `docs/agentic/contracts/security.md` (Retry-After semantics), `docs/agentic/contracts/clustering-api.md`, `docs/agentic/contracts/recognition-clustering.md`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `POST /recognition/clustering/jobs` response codes | Backend | `202 Accepted` on success (async job); 5xx on DB cancel | Add `503 Retry-After: 5` for admission fail-fast and breaker-open | Yes -- 202 path unchanged | API + integration tests |
| `get_clustering_session()` dependency | Backend | does not exist | New FastAPI dep bound to dedicated `clustering_engine` | No -- additive | unit + integration tests |
| Clustering handler transaction boundary | Backend | multi-call session across `SELECT FOR UPDATE`, lookup, INSERT | Single `async with session.begin():` wrapping whole unit-of-work | Yes -- atomicity preserved | integration test on lock + insert |
| Clustering pool capacity | Infra | shared business pool | Dedicated `clustering_engine` with `pool_size=2, max_overflow=1` | No -- additive | pool-identity test + saturation test |
| Clustering settings | Backend | none | Add `clustering_pool_size`, `clustering_max_overflow`, `clustering_pool_timeout`, `clustering_breaker_*`, `clustering_tenant_lock_timeout_ms` in `db/settings.py` | No | settings unit test |
| WP mutation-proxy retry policy | Plugin | any `status >= 500` retries up to 3x | `503` with `Retry-After` is non-retryable; 502/504/transport still retry | Yes -- narrow the policy, do not remove | PHPUnit test |
| Structured log record for clustering requests | Backend | `correlation_id` present; `pg_backend_pid` absent | Add `pg_backend_pid` at session checkout | No -- additive field | log-snapshot test |
| `/metrics` | Backend | existing histograms | Add `clustering_admission_latency_ms` histogram | No -- additive metric | metrics scrape test |

## Proposed Solution

Five vertical slices, sequenced so each slice is independently reviewable and the E15-3a Slice 2 roundtrip gate unblocks as soon as S1+S2 land.

1. **S1 -- Observability floor.** The existing `session_dependency_timing` log record already emits a `conn_id` field, but `_resolve_connection_id()` in `deps/session.py:58` returns `hex(id(sync_connection))` -- a Python object identity, not the Postgres backend PID. S1 adds a **new distinct field** `pg_backend_pid` resolved via a one-shot `SELECT pg_backend_pid()` at session open, emitted **alongside** the existing `conn_id` in the same log record so a `pg_stat_activity` join is unambiguous. The existing `conn_id` field stays for now; a follow-on may deprecate it once structured logging consumers migrate. S1 also emits a `clustering_admission_latency_ms` Prometheus histogram around the clustering handler. This is the diagnostic surface every later slice's tests lean on.
2. **S2 -- Admission fail-fast.** Add a `pg_locks` pre-flight probe in `clusters.py` that returns `503 Retry-After: 5` when a conflicting lock row exists on the target tenants row. Wrap the `SELECT ... FOR UPDATE` in `SET LOCAL statement_timeout='1s'`. This converts BR-21's 10 s cliff into a 1 s fail-fast and is the minimum change that unblocks E15-3a Slice 2.
3. **S3 -- Clustering-dedicated circuit breaker.** New local breaker module, separate from the SLR-3 session-dependency breaker, counting `QueryCanceledError` on the clustering write path. Threshold: 3 failures / 30 s window. Open-state cooldown: 30 s. Half-open admits a single trial. State held on `app.state`. Deterministic clock injection.
4. **S4 -- Route-boundary bulkhead + owned transaction.** New `clustering_engine` with `pool_size=2, max_overflow=1` in `db/session.py`. New `get_clustering_session()` FastAPI dep in `deps/session.py` that opens the session, consults the clustering breaker, yields the session **without issuing any execute** (so the route can own the first transaction -- PLAN-10), and closes it in `finally`. Two new clustering-flavored service factories in `deps/services.py` -- `get_cluster_service_builder_clustering` and `get_persisted_cluster_job_service_clustering` -- each depending on `get_clustering_session` so FastAPI's DI cache hands the route a single clustering-session instance across `session`, `cluster_service_builder`, and `job_service`. The clustering-flavored job-service factory **bypasses the shared `get_job_service()` helper** (which would autobegin a txn via its `SELECT 1` probe and `set_tenant_context` call) and **does not pre-await `cluster_service_builder(tenant_id)`** during dep resolution (which would trigger `build_cluster_service`'s `set_tenant_context` + `ensure_tenant_exists` SQL on the clustering session). Instead it constructs `JobService(repository=SqlAlchemyJobRepository(session), cluster_service=None, scan_service=None)` directly with no pre-yield SQL; the route invokes the builder inside its own owned txn block and re-assigns the result (PLAN-11, PLAN-12). Clustering handler rewrites to use `async with session.begin():` wrapping safety settings, tenant context, pg_backend_pid capture, admission probe, the tenants `SELECT FOR UPDATE`, the active-job lookup, and the INSERT -- the full unit-of-work on one connection from the bulkheaded pool. Preserves atomicity across all three deps (PLAN-01, PLAN-04, PLAN-10), preserves `get_session()` and the existing service factories for other routers (PLAN-03).
5. **S5 -- WP mutation-proxy policy narrowing.** In `class-abstract-recognition-proxy-controller.php`, short-circuit the retry loop when the response is `503` **and** carries `Retry-After`. Keep retry behavior for 502, 504, and transport errors. Closes PLAN-02 contract mismatch so the backend SLO surfaces end-to-end.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Session-checkout log | `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | Add `_resolve_pg_backend_pid()` helper that runs `SELECT pg_backend_pid()` and emits a new `pg_backend_pid` field in `_log_session_dependency_timing`; existing `conn_id` (Python object id) left in place |
| Clustering metrics | `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Histogram `clustering_admission_latency_ms` around the handler |
| Admission probe | `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Pre-flight `pg_locks` SELECT before the `SELECT ... FOR UPDATE`; `SET LOCAL statement_timeout='1s'` |
| Clustering settings | `apps/prototype-description-service/db/settings.py` | Add `clustering_pool_size=2`, `clustering_max_overflow=1`, `clustering_pool_timeout`, `clustering_breaker_failure_threshold=3`, `clustering_breaker_window_seconds=30`, `clustering_breaker_cooldown_seconds=30`, `clustering_tenant_lock_timeout_ms=1000` |
| Clustering breaker | `apps/prototype-description-service/recognition/interface_adapters/http/deps/clustering_circuit_breaker.py` | New state machine (open/half-open/closed) with injectable clock |
| Clustering engine + session factory | `apps/prototype-description-service/db/session.py` | New `clustering_engine` + `clustering_async_session_factory` mirroring the observability pattern |
| Clustering session dep | `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | New `get_clustering_session()` async generator bound to `clustering_async_session_factory`; consults clustering breaker (S3), yields a bare session **without issuing any execute** so the route owns the first transaction (PLAN-10), `await session.close()` in `finally` |
| Clustering-flavored cluster service builder | `apps/prototype-description-service/recognition/interface_adapters/http/deps/services.py` | New `get_cluster_service_builder_clustering` depending on `get_clustering_session` (mirrors `get_cluster_service_builder` but on the clustering session); leaves the existing `get_cluster_service_builder` unchanged for non-clustering routes |
| Clustering-flavored job service | `apps/prototype-description-service/recognition/interface_adapters/http/deps/services.py` | New `get_persisted_cluster_job_service_clustering` depending on `get_clustering_session` and the new clustering service builder; **must NOT call the shared `get_job_service()` helper** (which issues `SELECT 1` + `set_tenant_context` and autobegins a txn) **and must NOT pre-await `cluster_service_builder(tenant_id)` during dep resolution** (which would trigger `build_cluster_service`'s `set_tenant_context` + `ensure_tenant_exists` SQL on the clustering session before the route's txn block opens). Constructs `JobService(repository=SqlAlchemyJobRepository(session), cluster_service=None, scan_service=None)` directly with no pre-yield SQL. The route is responsible for invoking the builder inside its own `async with session.begin():` block (PLAN-11, PLAN-12). Leaves the existing factory unchanged for non-clustering routes |
| App wiring | `apps/prototype-description-service/api/main.py` | Initialize clustering breaker state on `app.state` |
| Clustering handler | `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Swap all three deps (`session`, `cluster_service_builder`, `job_service`) to clustering-flavored variants; wrap handler body in `async with session.begin():` whose first statements are `_apply_postgres_session_safety_settings`, tenant context, `_resolve_pg_backend_pid` (PLAN-10), invoke `cluster_service = await cluster_service_builder(tenant_id)` and assign onto `job_service` (PLAN-12), then admission probe, then SET LOCAL <N>ms, SELECT FOR UPDATE, restore SET LOCAL 10s, lookup, INSERT |
| Clustering repository | `apps/prototype-description-service/recognition/infrastructure/repositories/job_repository.py` | No change required; the repository already takes a session. Confirm it does not call `commit()` internally. |
| Unit tests -- breaker | `apps/prototype-description-service/recognition/tests/unit/test_clustering_circuit_breaker.py` | New: state transitions, failure counting, cooldown, half-open admission |
| Unit tests -- settings | `apps/prototype-description-service/recognition/tests/unit/test_database_settings.py` | Extend for clustering knobs |
| Integration tests -- clustering admission | `apps/prototype-description-service/recognition/tests/api/test_clustering_admission.py` | New: real Postgres fixture with blocker txn; assert `503 Retry-After` in `<1,000 ms` |
| Integration tests -- pool isolation | `apps/prototype-description-service/recognition/tests/api/test_clustering_pool_isolation.py` | New: `engine is not clustering_engine`; saturation does not block `/health/detailed` |
| Integration tests -- unit of work atomicity | `apps/prototype-description-service/recognition/tests/api/test_clustering_transaction.py` | New: assert whole `SELECT FOR UPDATE -> lookup -> INSERT` runs on one connection inside one `session.begin()` |
| PHPUnit test -- proxy policy | `apps/prototype-wp-alt-context/tests/Unit/RecognitionProxyRetryPolicyTest.php` | Extend with `503 Retry-After` non-retry assertion; 502/504 still retry |
| PHP controller | `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | Short-circuit retry loop when status == 503 and `Retry-After` header present |
| PHP policy (if needed) | `apps/prototype-wp-alt-context/src/api/class-recognition-proxy-policy.php` | Surface helper `is_retryable_status(int $status, array $headers): bool` if the logic does not fit cleanly in the controller |

## Related Files

| File | Note |
| --- | --- |
| `docs/assessments/e15-3a-br21-clustering-insert-statement-timeout-2026-04-23.md` | Authoritative literature crosswalk, root-cause ranking, diagnostic SQL |
| `docs/scopes/e15-3a-br21-clustering-stability-scope.md` | Authoritative MVP scope (v2) |
| `docs/tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md` | Parent; Slice 2 gate depends on S1+S2 here |
| `docs/tasks/15.0/E15-3a-localwp-oci-run-log.md` | Will capture backend P50/P95 admission latency on merge |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/circuit_breaker.py` | SLR-3 session-dependency breaker (separate concern; do not conflate) |
| `apps/prototype-description-service/db/session.py` | Pattern for adding the clustering pool follows the existing `observability_engine` |

## Verification Strategy

- **Deterministic unit tests** (fast):
  - `cd apps/prototype-description-service && python -m pytest recognition/tests/unit/test_clustering_circuit_breaker.py recognition/tests/unit/test_database_settings.py -q`
- **Integration tests against real Postgres fixture**:
  - `cd apps/prototype-description-service && python -m pytest recognition/tests/api/test_clustering_admission.py recognition/tests/api/test_clustering_pool_isolation.py recognition/tests/api/test_clustering_transaction.py -q`
- **Full backend suite** (regression sweep before merge):
  - `cd apps/prototype-description-service && python -m pytest recognition/tests -q`
- **PHPUnit proxy policy**:
  - `cd apps/prototype-wp-alt-context && composer test -- --filter=RecognitionProxyRetryPolicyTest`
- **Full plugin gate** before PHP merge:
  - `cd apps/prototype-wp-alt-context && composer check`
- **Contract checks**:
  - Verify `clustering_engine is not engine` in a runtime smoke.
  - Verify `get_clustering_session` is the only dep wired into `POST /recognition/clustering/jobs` and no other router imports it.
  - Verify log lines from a clustering request contain both `correlation_id=` and `pg_backend_pid=` fields.
- **Latency assertion**: the admission integration test wraps its HTTP call in `time.perf_counter()` and asserts `elapsed_ms < 1_000`.

## Slice Delivery

### Slice 1: Observability floor (correlation_id + pg_backend_pid + admission histogram)

**Goal**: Make every clustering request diagnostically complete before changing behavior.

Changes:
- `deps/session.py` adds a `_resolve_pg_backend_pid()` helper that issues `SELECT pg_backend_pid()` against the live session and returns the integer. The helper is invoked from `get_session` at session open (alongside the existing safety-settings call site, since the dep already owns the txn) and threaded into `_log_session_dependency_timing` as a new `pg_backend_pid` field. The existing `conn_id` field (Python object id) is left in place for backwards compatibility. S4 reuses the **same helper** but invokes it from inside the route's `async with session.begin():` block on the clustering path so the dep can stay txn-free (PLAN-10).
- `clusters.py` records a Prometheus histogram `clustering_admission_latency_ms` around the handler body.

Proof:
- `pytest recognition/tests/unit/test_database_settings.py recognition/tests/api/test_dependencies.py -q` (no regression)
- A new log-snapshot test asserts both `correlation_id` and the new `pg_backend_pid` integer field appear in one record.

### Slice 2: Admission fail-fast (pg_locks probe + tenant-lock timeout)

**Goal**: Turn BR-21's 10 s cliff into a `<1 s` `503 Retry-After` on admission.

Changes:
- Add a cheap `SELECT 1 FROM pg_locks WHERE ...` pre-flight in `clusters.py` before entering the write unit-of-work.
- Wrap the tenants `SELECT ... FOR UPDATE` in a narrow `SET LOCAL statement_timeout='<clustering_tenant_lock_timeout_ms>ms'` issued inside the handler transaction **immediately before** the `SELECT ... FOR UPDATE`. Immediately after the SELECT, issue a matching `SET LOCAL statement_timeout='10s'` so the subsequent active-job lookup and INSERT keep the default safety budget (see Constraints / PLAN-08).
- On probe-positive or on `QueryCanceledError` from the `SELECT FOR UPDATE`, return `503` with `Retry-After: 5` and a `BR-21-fast-fail` log line.

Proof:
- New integration test `test_clustering_admission.py` opens a blocker `SELECT ... FOR UPDATE` in a background connection, then asserts the handler returns 503 with `Retry-After: 5` in `<1,000 ms`.
- E15-3a Slice 2 roundtrip gate can now proceed (verified manually in the run log).

### Slice 3: Clustering-dedicated circuit breaker

**Goal**: Prevent convoy: 3 `QueryCanceledError`s in 30 s opens the breaker; subsequent requests 503 in `<10 ms` without touching the DB.

Changes:
- New module `clustering_circuit_breaker.py` with `closed -> open -> half_open -> closed` state machine, failure counter with sliding window, injectable clock.
- Settings `clustering_breaker_failure_threshold`, `_window_seconds`, `_cooldown_seconds` in `db/settings.py`.
- App wiring initializes breaker on `app.state.clustering_breaker` at startup.
- Clustering handler consults the breaker before admission probe; records failure on `QueryCanceledError`; records success on `202`.

Proof:
- New `test_clustering_circuit_breaker.py` asserts transitions with a fake clock: 3 failures in window -> open; next call 503 in `<10 ms` and repository never called; cooldown elapses -> half-open; successful trial -> closed.

### Slice 4: Route-boundary bulkhead + owned transaction

**Goal**: Isolate clustering from the business pool; wrap the full unit-of-work in one `session.begin()` on one connection.

Changes:
- `db/session.py` adds `clustering_engine` + `clustering_async_session_factory` mirroring the observability pattern, with `pool_size=2, max_overflow=1`.
- `deps/session.py` adds `get_clustering_session()` that consults the clustering breaker (S3), opens a session from `clustering_async_session_factory`, **yields without issuing any `execute`** so the route owns the first transaction (PLAN-10), and `await session.close()` in `finally`. It does **not** call `_apply_postgres_session_safety_settings` at the dep level (deferred to the route block per PLAN-10) and does **not** invoke the SLR-3 `_get_session_dependency_breaker` (PLAN-09).
- `deps/services.py` adds `get_cluster_service_builder_clustering` and `get_persisted_cluster_job_service_clustering`, each depending on `get_clustering_session`. **`get_persisted_cluster_job_service_clustering` deliberately does NOT delegate to the shared `get_job_service()` helper** (which autobegins a txn via `session.execute(text("SELECT 1"))` + `set_tenant_context`) **and does NOT pre-await `cluster_service_builder(tenant_id)`** (which would trigger `build_cluster_service`'s `set_tenant_context` + `ensure_tenant_exists` SQL on the clustering session). It constructs `JobService(repository=SqlAlchemyJobRepository(session), cluster_service=None, scan_service=None)` directly (PLAN-11, PLAN-12). The existing `get_cluster_service_builder` and `get_persisted_cluster_job_service` are left untouched for every non-clustering router.
- `clusters.py` swaps **all three** clustering-route deps -- `session`, `cluster_service_builder`, and `job_service` -- to the clustering-flavored factories, and wraps the handler body in `async with session.begin():`. The block's first statements (in order) are: (1) `_apply_postgres_session_safety_settings(session)`, (2) `set_tenant_context(session, ...)`, (3) `_resolve_pg_backend_pid(session)` (PLAN-07/PLAN-10), (4) `cluster_service = await cluster_service_builder(tenant_id)` and `job_service.cluster_service = cluster_service` (PLAN-12 -- builder invocation deferred from dep resolution into the owned txn so its internal `set_tenant_context` + `ensure_tenant_exists` SQL lands inside the route's txn), (5) the `pg_locks` admission probe (S2), (6) `SET LOCAL statement_timeout=<N>ms` (S2), (7) `SELECT ... FOR UPDATE` (S2), (8) restore `SET LOCAL statement_timeout='10s'` (PLAN-08), (9) active-job lookup, and (10) INSERT. Commit happens automatically on context exit; rollback on exception.
- `job_repository.py` verified not to call `commit()` internally.

Proof:
- `test_clustering_pool_isolation.py` asserts `engine is not clustering_engine` and that saturating the clustering pool does not block `/health/detailed`.
- `test_clustering_transaction.py` asserts the full `SELECT FOR UPDATE -> lookup -> INSERT` runs inside one transaction on one connection (no cross-connection hand-off), **and** that the `AsyncSession` handed to `cluster_service_builder` and `job_service` inside the handler is the same instance handed to the route's `session` parameter (single clustering-session identity across deps).
- Full backend suite passes: `pytest recognition/tests -q`.

### Slice 5: WP mutation-proxy policy narrowing

**Goal**: Surface backend `503 Retry-After` on first attempt; preserve retry for 502/504/transport.

Changes:
- `class-abstract-recognition-proxy-controller.php` short-circuits the retry loop when the response status is `503` **and** a `Retry-After` header is present.
- Optionally extract `is_retryable_status(int $status, array $headers): bool` to `class-recognition-proxy-policy.php` if the controller-side branch grows beyond two lines.

Proof:
- New PHPUnit assertions in `tests/Unit/RecognitionProxyRetryPolicyTest.php`:
  - mocked backend `503 Retry-After: 5` surfaces on first attempt with no retry;
  - mocked `502` still retries 3x;
  - mocked `504` still retries 3x;
  - mocked transport error still retries 3x.
- Full plugin gate passes: `composer check`.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded scope v2 and backing assessment before editing.
- [ ] Confirmed the clustering breaker and the SLR-3 session-dependency breaker are separate modules with separate state.
- [ ] Confirmed `get_session()` is not modified for any non-clustering router.
- [ ] Confirmed atomicity of `SELECT FOR UPDATE -> lookup -> INSERT` under one `session.begin()` on one connection.
- [ ] Audited all deps injected into `POST /recognition/clustering/jobs` (`session`, `cluster_service_builder`, `job_service`) and confirmed each resolves to the clustering session via FastAPI DI cache.
- [ ] Confirmed `get_clustering_session` yields a bare session with no autobegun transaction so the route's `async with session.begin():` is the first transaction on that session (PLAN-10).
- [ ] Confirmed `get_persisted_cluster_job_service_clustering` does NOT call the shared `get_job_service()` helper (no `SELECT 1` probe, no `set_tenant_context`) so the clustering session is still bare when the route enters `async with session.begin():` (PLAN-11).
- [ ] Confirmed `get_persisted_cluster_job_service_clustering` does NOT pre-await `cluster_service_builder(tenant_id)` during dep resolution (no `build_cluster_service`-driven SQL on the clustering session); the route invokes the builder inside its own owned txn block (PLAN-12).

### Slice 1 -- Observability floor

- [ ] `deps/session.py` adds `_resolve_pg_backend_pid()` and emits new `pg_backend_pid` field alongside existing `conn_id` in `session_dependency_timing` log record.
- [ ] `clusters.py` records `clustering_admission_latency_ms` histogram.
- [ ] Log-snapshot test asserts both `correlation_id` and the new `pg_backend_pid` field (not `conn_id`) are present.

### Slice 2 -- Admission fail-fast

- [ ] `pg_locks` pre-flight probe added before write unit-of-work.
- [ ] Narrow `SET LOCAL statement_timeout='<clustering_tenant_lock_timeout_ms>ms'` issued immediately before `SELECT FOR UPDATE`, rolled back to `10s` immediately after the SELECT so INSERT keeps the default budget.
- [ ] `503 Retry-After: 5` returned on probe-positive or `QueryCanceledError`.
- [ ] Integration test asserts `<1,000 ms` backend-measured.

### Slice 3 -- Clustering circuit breaker

- [ ] New `clustering_circuit_breaker.py` with deterministic state machine and injectable clock.
- [ ] Settings `clustering_breaker_*` added.
- [ ] Breaker initialized on `app.state` at startup.
- [ ] Handler consults breaker on entry; records failure on `QueryCanceledError`; records success on `202`.
- [ ] Unit tests exercise closed -> open -> half-open -> closed with fake clock.
- [ ] Open-state fast-path returns `503` in `<10 ms` without calling repository.

### Slice 4 -- Bulkhead + owned transaction

- [ ] `clustering_engine` + `clustering_async_session_factory` added in `db/session.py`.
- [ ] `get_clustering_session()` dep added; yields a bare session **without issuing any execute** so the route owns the first transaction (PLAN-10); does NOT invoke SLR-3 `_get_session_dependency_breaker` (PLAN-09); does NOT call `_apply_postgres_session_safety_settings` at the dep level (PLAN-10).
- [ ] `get_cluster_service_builder_clustering` and `get_persisted_cluster_job_service_clustering` added in `deps/services.py`; existing non-clustering factories untouched. `get_persisted_cluster_job_service_clustering` does NOT call `get_job_service()` (no `SELECT 1`/`set_tenant_context`) AND does NOT pre-await `cluster_service_builder(tenant_id)` (no `build_cluster_service` SQL); it constructs `JobService(..., cluster_service=None, scan_service=None)` directly so the route owns the first transaction (PLAN-11, PLAN-12).
- [ ] `clusters.py` swaps all three deps on `POST /recognition/clustering/jobs` (`session`, `cluster_service_builder`, `job_service`) to the clustering-flavored factories.
- [ ] Handler wrapped in `async with session.begin():` covering full unit-of-work; the block's first statements (in order) are `_apply_postgres_session_safety_settings`, `set_tenant_context`, `_resolve_pg_backend_pid`, `await cluster_service_builder(tenant_id)` + reassign onto `job_service` (PLAN-12), `pg_locks` admission probe, narrow `SET LOCAL`, `SELECT FOR UPDATE`, restore `SET LOCAL 10s`, lookup, INSERT (PLAN-10/PLAN-12 ordering).
- [ ] Integration test asserts all three deps share the same `AsyncSession` instance inside the handler.
- [ ] `job_repository.py` verified not to commit internally.
- [ ] Pool-isolation integration test passes.
- [ ] Unit-of-work atomicity integration test passes.
- [ ] Full backend pytest suite passes.

### Slice 5 -- WP proxy policy

- [ ] `class-abstract-recognition-proxy-controller.php` short-circuits on `503 Retry-After`.
- [ ] Retry behavior preserved for 502, 504, transport errors.
- [ ] PHPUnit assertions cover all four cases.
- [ ] `composer check` passes.

## Review Readiness

- [ ] Clustering breaker and SLR-3 breaker are unambiguously separate in code and docs.
- [ ] Pool isolation proven by an `is not` engine assertion plus a saturation test.
- [ ] `<1 s` backend-measured latency assertion present in an integration test, not just a comment.
- [ ] WP retry-policy change is paired with a direct PHPUnit assertion, not a manual-run expectation.
- [ ] Handoff records fresh verification on the merged commit; `handoff_close_check(enforce=True)` passes; BR-21 and `E15-3a-PLAN-01..03` close `fixed` with `verified_commit_sha`.

## Stretch Goals

- [ ] Emit a structured `clustering_breaker_state_change` log/metric on every transition. Low cost if the breaker exposes a hook; skip if it forces a broader observability contract change.
- [ ] Extend the pool-isolation test to also prove saturation does not block `/recognition/analyze`.

## Success Criteria

- [ ] Integration test: zombie-lock + `POST /recognition/clustering/jobs` returns `503 Retry-After` in `<1,000 ms` backend-measured.
- [ ] Unit test: 3 `QueryCanceledError`s in 30 s open the breaker; next call returns `503` in `<10 ms` without calling the repository; cooldown elapses, half-open admits a trial.
- [ ] Integration test: `engine is not clustering_engine`; clustering-pool saturation does not block `/health/detailed`; full unit-of-work runs on one connection inside one `session.begin()`.
- [ ] PHPUnit test: backend `503 Retry-After` surfaces on first attempt; 502/504/transport still retry.
- [ ] E15-3a Slice 2 roundtrip gate captures a green clustering-jobs round trip from LocalWP.
- [ ] Every clustering-jobs request's log record contains both `correlation_id` and the new `pg_backend_pid` field (distinct from the existing Python-object-id `conn_id`), joinable against `pg_stat_activity`.
- [ ] `handoff_close_check(enforce=True)` passes on `feature/e15-3a` with zero open findings; BR-21 and `E15-3a-PLAN-01..03` closed `fixed` with `verified_commit_sha` pointing at the merge commit.

## Handoff

This task plan is derived from scope v2 and the backing assessment. Next action: submit to `/planning-review` before S1 begins. No additional scoping rounds are expected.
