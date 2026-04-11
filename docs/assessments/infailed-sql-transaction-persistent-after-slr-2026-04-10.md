# Assessment: Persistent InFailedSQLTransactionError After SLR Implementation

> **Metadata**
>
> - **Date**: 2026-04-10
> - **Author**: GPT-5.4
> - **Scope**: `apps/prototype-description-service`; auth dependency, shared `AsyncSession`, transaction failure containment
> - **Status**: Draft
>
> **Purpose:** Assessments surface problems and verify them against code.
> They are the entry point for the spec definition pipeline.
> An assessment inventories what is wrong, traces findings to code, and recommends
> directions without prescribing implementation details.
>
> **Pipeline position:** **Assessment** -> Spec -> [ADR] -> Task Plan -> Implementation.
>
> **Exit gate:** Every finding cites `file:line` in current code. Recommendations
> are prioritized. Deferred items are named explicitly. Owner review resolves
> disagreements before a spec is started.

---

## Prototype Description Service Persistent InFailedSQLTransaction Report

> The active defect is no longer best explained by the session-lifecycle bugs addressed in SLR-001 through SLR-008. The current code shows a narrower and more actionable failure mode: authentication performs both an API-key lookup and a `last_used_at` write inside the same request-scoped `AsyncSession` later reused by `analyze_media()`. Two auth-side exception paths continue after database failure without structural containment, allowing the first visible error to surface later as `InFailedSQLTransactionError` in business logic. The original assessment was directionally right about auth-layer poisoning, but too tactical in its recommendations and too narrow in its architectural framing.

**Related docs:**

- [infailed-sql-transaction-investigation-2026-04-09.md](infailed-sql-transaction-investigation-2026-04-09.md)
- [session-lifecycle-resilience-spec.md](../specs/session-lifecycle-resilience-spec.md)

## Executive Summary

The code now supports the claim that the surviving `InFailedSQLTransactionError` is an auth-path transaction-containment problem, not a leftover SLR lifecycle problem. `require_auth()` receives the same `get_optional_session()` instance later used by `analyze_media()`, and `_lookup_api_key()` performs both a read (`get_by_hash`) and a write (`touch`) on that shared session before control returns to the route handler. Because `get_optional_session()` only rolls back when an exception escapes the dependency yield/commit boundary, any auth-side exception that is caught and suppressed leaves the transaction in a failed state for later code.

The strongest verified defects are in `recognition/interface_adapters/http/deps/auth.py`. One branch catches a missing-table database error, sets `record = None`, and continues toward dev-key fallback. Another wraps `repo.touch(record)` in `suppress(Exception)` and still returns a valid auth context. Both branches can convert a primary database error into a later secondary `25P02` failure on the first business query.

The prior assessment's tactical fix set remains useful, but it is incomplete. The deeper issue is that the auth layer is an integration point sharing mutable transaction state with business logic, and the code combines a query with a telemetry side effect in one helper. That design makes rollback a fragile manual obligation at every future catch site. The missing structural directions are savepoint-based containment, command/query separation, decoupling `touch()` from the request critical path, and fail-fast handling for permanent schema faults such as a missing `api_keys` table.

Next step: write a focused spec for auth transaction isolation. Keep the scope local to `apps/prototype-description-service`, preserve the validated SLR work, and force an explicit design choice between savepoint containment inside the shared session and stronger isolation through a dedicated auth-session boundary.

## Findings

### F1. Auth and business logic share one request-scoped transaction

`analyze_media()` depends directly on `get_optional_session()` and also depends on `require_write_access`, which itself depends on `require_auth(session=Depends(get_optional_session))`. In FastAPI this means auth resolution and route logic operate on the same cached dependency instance, so a database failure in auth can poison the transaction later reused by business logic.

Current examples:

- `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py::analyze_media` (current lines 256-262) - the route takes both `auth=Depends(require_write_access)` and `session=Depends(get_optional_session)`.
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::require_auth` (current lines 97-155) - `require_auth()` receives that shared session and calls `_lookup_api_key(...)`.
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_optional_session` (current lines 149-218; rollback path at 199-204) - rollback only happens if an exception escapes the dependency's `yield`/`commit` block.

**Impact:** auth-path SQL failures can surface later as misleading `InFailedSQLTransactionError` failures in business code such as tenant lookup or tenant creation, obscuring the primary fault and weakening diagnosis.

### F2. `_lookup_api_key()` mixes query and modifier work while suppressing database failures

`_lookup_api_key()` both reads the API-key record and mutates it via `touch()` before returning. That makes auth success depend on a side effect that is not required to authenticate the request. Worse, both error-handling branches can continue without restoring transaction state.

Current examples:

- `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_lookup_api_key` (current lines 52-75) - `_lookup_api_key()` performs `repo.get_by_hash(hashed)`, catches some exceptions, then performs `repo.touch(record)` under `suppress(Exception)` before returning a record.
- `apps/prototype-description-service/recognition/infrastructure/repositories/api_key_repository.py::get_by_hash` / `::touch` (current lines 16-24) - `get_by_hash()` is a read, while `touch()` mutates `last_used_at` and calls `flush()` on the same session.

**Impact:** a nonessential telemetry write can invalidate the transaction needed by downstream request processing. This violates command-query separation and turns auth bookkeeping into a correctness risk for the whole request.

### F3. The dev-key fallback masks permanent auth-store faults instead of failing fast

The missing-table path in `_lookup_api_key()` does not treat schema drift as a hard runtime fault. It converts the exception into `record = None` and then falls through to the environment-provided dev-key path. Because auth is enabled by default, this creates a production footgun: a broken `api_keys` table can look like successful authentication for configured dev keys.

Current examples:

- `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_table_missing` (current lines 46-49) - `_table_missing()` matches on error-message text rather than a stronger schema-health check.
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_lookup_api_key` (current lines 63-80) - missing-table detection leads to `record = None`, after which the function still checks `settings.dev_api_keys`.
- `apps/prototype-description-service/recognition/config/security.py::SecuritySettings` (current lines 17-29) - `auth_enabled` defaults to `True` and `dev_api_keys` are read from environment state.

**Impact:** a permanent deployment/configuration fault can degrade into silent fallback behavior rather than immediate operator-visible failure, increasing the chance of hidden auth breakage in nonlocal environments.

### F4. Failure containment is manual in production even though savepoint support already exists in the stack

The production auth path relies on ad hoc `try`/`except` and `suppress(...)` blocks instead of a structural boundary around auth-side database work. That means every future catch site has to remember to restore transaction state. The codebase already uses `begin_nested()` in tests, showing the stack supports savepoint-based containment, but the runtime path does not use it.

Current examples:

- `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_lookup_api_key` (current lines 58-75) - runtime auth work is wrapped with manual exception handling, not a nested transaction boundary.
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_optional_session` (current lines 175-201 within the function body) - one session spans probe, tenant setup, auth work, and later route logic before commit.
- `apps/prototype-description-service/recognition/tests/conftest.py::db_session` (current lines 112-119) - tests already start nested transactions and automatically restart savepoints.
- `apps/prototype-description-service/recognition/tests/integration/test_rls_tenant_context_after_chunk_commit.py::postgres_rls_session` (current lines 148-157) - the integration test harness does the same with `begin_nested()`.

**Impact:** the current design is regression-prone. Tactical rollback fixes may patch today's sites, but the next suppressed DB exception in the same shared session can recreate the same class of failure.

## Prioritized Recommendations

### 1. Add targeted diagnostics to classify the active auth failure path

**Traces:** F1, F2, F3, F4  
**Priority:** P0

The current code proves that auth-side transaction poisoning is plausible, but it does not yet prove which runtime branch is active in the failing environment. The next spec should require explicit classification of auth-side database failures in `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_lookup_api_key` so operators can distinguish missing-schema faults, telemetry-write failures, and other lookup failures. This is not a substitute for structural containment; it narrows the decision with evidence instead of inference.

### 2. Isolate auth-side database faults structurally

**Traces:** F1, F2, F4  
**Priority:** P0

The next spec should make auth failure containment automatic rather than policy-based. The smallest verified direction is a savepoint (`begin_nested()`) around auth DB work inside the shared request session because the stack already demonstrates that pattern in tests. A dedicated auth-session boundary remains a valid fallback if planning review shows the savepoint path cannot satisfy correctness or ownership constraints.

### 3. Treat missing auth schema as a fail-fast condition

**Traces:** F1, F3  
**Priority:** P0

The spec should remove silent continuation for permanent auth-store faults. A missing `api_keys` table is a deployment or migration error, not a recoverable request-path condition. Startup validation, loud runtime health checks, or both are appropriate directions; silent dev-key fallback is not.

### 4. Separate API-key lookup from usage telemetry

**Traces:** F2, F4  
**Priority:** P1

Refactor the auth helper surface so the function that authenticates is a pure query and the `last_used_at` bookkeeping becomes a distinct command. That command should be allowed to fail independently, and the spec should decide whether it stays synchronous behind stronger isolation or moves onto a bounded asynchronous path. The `touch()` write should be treated as delayable telemetry, not as part of authentication correctness.

### 5. Expand diagnostics only after auth isolation is addressed

**Traces:** F1, F4  
**Priority:** P2

If the error persists after auth isolation changes, widen the investigation to secondary vectors such as SQLAlchemy hooks, session-state leakage, or lower-level driver behavior. Until then, keep statement-cache and server-side theories in a deferred bucket rather than the main line of inquiry.

## Code-Verified Critique

### What the assessment gets right

The original 2026-04-10 assessment correctly moved the center of gravity away from the SLR lifecycle work and onto the auth dependency. The shared-session explanation is supported directly by `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py::analyze_media`, `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::require_auth`, and `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_optional_session`.

It also correctly identified two concrete rollback holes in `_lookup_api_key()`: the `_table_missing(...)` branch and the suppressed `touch()` branch. Those are not abstract design concerns; they are present in current code and sufficient to explain a later `25P02`.

### Where the assessment overstates the problem

The current code does not yet prove which auth subpath is active in the failing environment. Both the missing-table path and the `touch()` failure path remain plausible from code inspection alone. The assessment should present that as a branching diagnosis, not as a settled runtime fact.

The original write-up was also too narrow in its remedy frame. "Add rollback at catch sites" is a valid immediate mitigation, but it is not the same as solving the design problem. The production path currently depends on perfect manual rollback discipline, while the test harness already demonstrates that nested-transaction containment is available in this stack.

One review concern needs qualification: async cancellation is an operational gap worth tracking, but it is not a code-verified primary cause in this specific auth helper. The service targets Python 3.12+ (`apps/prototype-description-service/pyproject.toml:5`), where `asyncio.CancelledError` is a `BaseException`, so the broad `except Exception` blocks in `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_lookup_api_key` do not directly swallow cancellation.

The assessment should therefore carry forward five concrete directions into the next planning stage: classify the active auth failure path with targeted diagnostics, prefer savepoint-based containment as the smallest structural fix, fail fast on permanent schema faults, split lookup from telemetry, and treat broader listener or session-leakage theories as explicitly deferred until auth isolation is proven insufficient.

## Priority Ordering

| Priority | Change | Impact | Effort | Trace |
| --- | --- | --- | --- | --- |
| **P0** | Classify active auth failure path with targeted diagnostics | Converts branch ambiguity into operator-visible evidence before structural changes land | Low | F1, F2, F3, F4 |
| **P0** | Structural isolation for auth DB work | Prevents auth failures from poisoning business transactions | Medium | F1, F2, F4 |
| **P0** | Fail-fast handling for missing `api_keys` schema | Prevents silent auth degradation and hidden deployment faults | Low-Medium | F3 |
| **P1** | Split lookup from `touch()` side effect | Removes telemetry write from auth correctness path | Medium | F2, F4 |
| **P2** | Secondary investigation into listeners/session leakage/cancellation cleanup | Improves fallback diagnosis if auth isolation is insufficient | Medium | F1, F4 |

## Deferred or Rejected Directions

- Do not reopen SLR-001 through SLR-008 as the primary root-cause fix path. Those changes addressed real lifecycle and resilience problems, but current code points elsewhere for this specific failure.
- Do not default immediately to a full external job queue for `touch()`. Start with the smaller spec decision: savepoint containment versus dedicated session versus bounded in-process async deferral.
- Do not promote statement-cache or PostgreSQL-server theories back to the top of the queue unless auth isolation changes fail to remove the error. If that happens, the next pass should inspect SQLAlchemy event listeners, session-state leakage, and async partial-failure cleanup before returning to lower-level server theories.

## Suggested Spec Direction

Write an app-local spec at `docs/specs/auth-transaction-isolation-spec.md`.

That spec should stay tightly scoped and tiered:

- **Tier 1**: runtime auth DB access in `recognition/interface_adapters/http/deps/auth.py`; targeted failure-path diagnostics; fail-fast handling for missing auth schema; savepoint-based containment requirements inside the shared request session.
- **Tier 2**: separation of lookup from `touch()` bookkeeping; explicit decision on whether telemetry stays synchronous behind isolation or moves to a bounded async path.
- **Tier 3, ADR-gated only if review cannot accept the Tier 1 containment direction**: whether the service must replace the shared-session-plus-savepoint design with a dedicated auth-session or connection boundary.

The spec should explicitly defer unrelated pool tuning, broader observability work, and external queue infrastructure unless the chosen design requires them.

## Next Step

- [x] Draft a spec at `docs/specs/auth-transaction-isolation-spec.md`
- [ ] Run planning review on the spec and resolve MCP findings before creating task plans
- [ ] If planning review rejects the Tier 1 savepoint direction, write an ADR comparing savepoint containment with a dedicated auth-session boundary
- [ ] Do not implement from this assessment alone; pass the spec review gate first

## References

- `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py`
- `apps/prototype-description-service/recognition/infrastructure/repositories/api_key_repository.py`
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py`
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`
- `apps/prototype-description-service/db/tenant_context.py`
- `apps/prototype-description-service/recognition/config/security.py`
- `apps/prototype-description-service/recognition/tests/conftest.py`
- `apps/prototype-description-service/recognition/tests/integration/test_rls_tenant_context_after_chunk_commit.py`
- `apps/prototype-description-service/pyproject.toml`
- `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt`
- `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt`
- `literature/extracted/refactoring/Using-Asyncio-in-Python-Understanding-Python-Hattingh.txt`
- `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt`
- `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt`
