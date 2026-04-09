# SLR-1. Session Lifecycle Resilience

> **Metadata**
>
> - **Date**: 2026-04-09
> - **Author**: GPT-5
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Project**: prototype-description-service
> - **Task ID**: SLR-1
> - **Target Branch**: `feature/slr-1-session-lifecycle-resilience`
> - **Review Coverage Target**: 2

---

## Objective

Eliminate the double-owned SQLAlchemy session lifecycle in the recognition HTTP layer and add the missing safety rails around tenant context cleanup, timeout configuration, and diagnostic logging. When this task is complete, request-scoped sessions have one clear owner, timeout behavior is configurable, and the service has deterministic proof for the failure mode documented in the assessment.

## Problem Statement

The current recognition HTTP dependencies wrap `db.session.get_session()` with a second commit/rollback/close layer, which creates the `InFailedSQLTransactionError` failure class documented in the assessment. The same surface also duplicates tenant context setup, suppresses cleanup errors, and lacks the timeout/cache configuration hooks needed to bound failed-transaction damage and diagnose connection behavior honestly.

## Constraints

- Scope is limited to `apps/prototype-description-service/`.
- The FastAPI dependency contract remains `AsyncIterator[AsyncSession | None]` for optional-session consumers and `AsyncIterator[AsyncSession]` for required-session consumers.
- `db.session.get_session()` stays available for non-HTTP callers; this task only removes the HTTP wrapper pattern.
- Greenfield policy applies: no compatibility shims or follow-on migrations for internal config/schema drift.
- Proof must be deterministic and repo-owned; manual echo-log inspection cannot be the close gate.

## Workflow Principles

- One request-scoped session has one lifecycle owner.
- Tenant context and cleanup belong to the dependency boundary, not scattered router helpers.
- Timeout/configuration changes land with the tests and docs that prove them.

## Terminology

- **Single-owner session lifecycle**: A dependency pattern where one function creates, commits or rolls back, and closes the `AsyncSession`.
- **Request-path cleanup**: The explicit `clear_tenant_context()` call in the HTTP dependency after request handling.
- **Observability session**: The best-effort DB session used by health and diagnostic surfaces that should degrade without taking down business requests.

## Current State Analysis

- `recognition/interface_adapters/http/deps/session.py` still wraps `db.session.get_session()` with `async for` and a second lifecycle layer.
- `recognition/interface_adapters/http/routers/analyze.py` still contains router-local tenant context setup logic adjacent to the dependency-managed path.
- `db/tenant_context.py` still uses exception suppression in `clear_tenant_context()` and an unguarded checkout listener.
- `db/settings.py` and `db/session.py` do not yet expose transaction timeout or statement-cache diagnostic settings.
- Existing API coverage lives in `recognition/tests/api/test_dependencies.py`, `test_api_analyze.py`, and `test_api_health.py`, but none of those files currently prove the single-owner lifecycle directly.

## Target Outcome

The HTTP dependency layer creates sessions directly from `async_session_factory`, owns the full lifecycle once, and logs enough timing/connection identity to diagnose degraded requests. Timeout and statement-cache settings are configurable through `db/settings.py`, and the close gate uses automated tests that prove the lifecycle flattening rather than manual log reading.

## Context Loading

- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Rules: `docs/agentic/rules/testing-python.md`
- Rules: `docs/agentic/rules/planning-review-guide.md`
- Spec: `docs/specs/session-lifecycle-resilience-spec.md`
- Assessment: `docs/assessment/infailed-sql-transaction-investigation-2026-04-09.md`
- Handoff/MCP state: `SESSION-LIFECYCLE-RESILIENCE`, including `SLR-PLAN-01`
- External docs via `ctx7` only if: SQLAlchemy async engine DSN/query-parameter behavior needs confirmation for the statement-cache toggle

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| -------- | ----- | ---------------- | --------------- | --------------------- | ------------ |
| HTTP session dependencies | Backend | `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | Internal lifecycle refactor only; dependency signatures stay stable | Yes — FastAPI call sites still depend on the same dependency types | `pytest recognition/tests/api/test_dependencies.py -q` |
| Analyze router tenant setup | Backend | `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` | Router stops duplicating dependency-owned tenant setup | No | `pytest recognition/tests/api/test_api_analyze.py -q` |
| DB runtime configuration | Backend | `apps/prototype-description-service/db/settings.py` | Add timeout/cache env settings and session setup hooks | No | unit/API regression tests |

## Proposed Solution

Flatten the three HTTP session dependencies onto direct `async_session_factory()` ownership, then remove the router-local tenant-context duplication that the flattened boundary makes obsolete. In the same task, harden cleanup and checkout logging, add timeout/cache configuration to `db/settings.py` and `db/session.py`, and land focused automated coverage that proves the new lifecycle and degraded-session behavior.

## Files and Surfaces to Change

| Surface | File | Change |
| ------- | ---- | ------ |
| Backend dependency | `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | Replace `_get_session()` wrapping with direct `async_session_factory()` ownership; add timeout, connection-id, and cleanup changes |
| Router | `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` | Remove duplicate `set_tenant_context()` call and import |
| DB settings | `apps/prototype-description-service/db/settings.py` | Add timeout and statement-cache diagnostic settings |
| DB session setup | `apps/prototype-description-service/db/session.py` | Thread new settings into engine/session construction |
| Tenant context helpers | `apps/prototype-description-service/db/tenant_context.py` | Replace suppressed cleanup failures with warnings and guard checkout reset |
| API tests | `apps/prototype-description-service/recognition/tests/api/test_dependencies.py` | Extend with lifecycle ownership coverage |
| API tests | `apps/prototype-description-service/recognition/tests/api/test_api_analyze.py` | Lock in router-level tenant setup removal |
| API tests | `apps/prototype-description-service/recognition/tests/api/test_api_health.py` | Preserve degraded health behavior |
| New regression tests | `apps/prototype-description-service/recognition/tests/unit/test_database_settings.py` | Add timeout/cache setting coverage |

## Related Files

| File | Note |
| ---- | ---- |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/services.py` | Uses `get_observability_session`; must stay aligned with the flattened dependency behavior |
| `apps/prototype-description-service/api/main.py` | Root health aggregation depends on recognition health behavior staying honest under degraded DB access |
| `docs/roadmaps/roadmap-pg18-upgrade.md` | Phase 0 names the application-level timeout work this task implements; server-level `transaction_timeout` remains a separate infrastructure item |
| `docs/agentic/adrs/ADR-006-session-circuit-breaker-and-pool-bulkheading.md` | Follow-on ADR for Tier 3 resilience work intentionally excluded from this task |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && python -m pytest recognition/tests/api/test_dependencies.py recognition/tests/api/test_api_analyze.py recognition/tests/api/test_api_health.py -q`
  - `cd apps/prototype-description-service && python -m pytest recognition/tests/integration/test_tenant_isolation.py -q`
  - `cd apps/prototype-description-service && python -m pytest recognition/tests/unit/test_database_settings.py -q`
- Runtime-parity / environment checks:
  - `cd apps/prototype-description-service && python -m pytest recognition/tests/ -q`
- Contract/fixture verification:
  - `rg -n "async for session in|session_iter|aclose|clear_tenant_context|set_tenant_context" apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`
- Manual verification:
  - Confirm a degraded `/recognition/health` response still returns a non-5xx response when the optional session dependency yields `None`

## Slice Delivery

### Slice 1: Flatten HTTP Session Ownership

**Spec items**: `SLR-001`

**Goal**: Remove the double-owned session lifecycle from the required, optional, and observability dependencies.

Changes:

- Refactor `get_session`, `get_optional_session`, and `get_observability_session` in `deps/session.py` to create sessions directly from `async_session_factory()`.
- Keep dependency signatures stable while removing `_get_session`, `session_iter`, and `aclose()` usage.
- Add or extend tests in `recognition/tests/api/test_dependencies.py` to prove one dependency-owned commit/rollback path and correct fallback behavior when the DB is unavailable.

Proof:

- `cd apps/prototype-description-service && python -m pytest recognition/tests/api/test_dependencies.py -q`
- `rg -n "session_iter|async for session in|aclose" apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py`

### Slice 2: Remove Duplicate Tenant Setup and Cleanup Drift

**Spec items**: `SLR-002`, `SLR-003`, `SLR-004`, `SLR-005`

**Goal**: Make the dependency boundary the sole owner of tenant context setup and HTTP cleanup behavior.

Changes:

- Remove the router-local `set_tenant_context()` call and import from `routers/analyze.py` while preserving `ensure_tenant_exists()`.
- Remove request-path `clear_tenant_context()` calls from the HTTP dependency layer and rely on the checkout listener for next-consumer cleanup.
- Replace `contextlib.suppress(Exception)` in `db/tenant_context.py::clear_tenant_context` with warning-level logging and guard the checkout listener with `try/except`.

Proof:

- `cd apps/prototype-description-service && python -m pytest recognition/tests/api/test_api_analyze.py recognition/tests/integration/test_tenant_isolation.py -q`
- `rg -n "set_tenant_context|clear_tenant_context|contextlib\\.suppress" apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py apps/prototype-description-service/db/tenant_context.py`

### Slice 3: Configure Timeouts, Connection Identity, and Diagnostic Settings

**Spec items**: `SLR-006`, `SLR-007`, `SLR-008`

**Goal**: Add the runtime knobs and observability needed to bound and diagnose failed transactions.

Changes:

- Add `DB_STATEMENT_TIMEOUT`, `DB_IDLE_IN_TXN_TIMEOUT`, and `DB_DISABLE_STMT_CACHE` handling in `db/settings.py`.
- Apply timeout settings in the session dependency after the probe succeeds and include connection identity in timing logs.
- Add or extend tests for settings parsing and ensure health/degraded behavior remains stable with the optional-session path.

Proof:

- `cd apps/prototype-description-service && python -m pytest recognition/tests/unit/test_database_settings.py recognition/tests/api/test_api_health.py -q`
- `cd apps/prototype-description-service && python -m pytest recognition/tests/ -q`

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [x] Confirmed whether external dependency context requires `ctx7`.
- [x] Recorded boundary ownership and compatibility expectations if any contract is touched.

### Checklist for Slice 1: Flatten HTTP Session Ownership

- [x] Refactor the three HTTP session dependencies to own session creation directly.
- [x] Add lifecycle ownership regression coverage in `test_dependencies.py`.
- [x] Capture proof that wrapper-generator patterns are gone.

### Checklist for Slice 2: Remove Duplicate Tenant Setup and Cleanup Drift

- [x] Remove router-local tenant context duplication and dependency cleanup drift.
- [x] Update cleanup/checkpoint helper behavior in `db/tenant_context.py`.
- [x] Capture analyze + tenant-isolation proof for the new ownership boundary.

### Checklist for Slice 3: Configure Timeouts, Connection Identity, and Diagnostic Settings

- [x] Add timeout/cache settings and thread them through runtime setup.
- [x] Add settings/logging coverage for connection identity and degraded behavior.
- [x] Capture targeted and full-suite verification evidence.

## Review Readiness

- [x] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [x] Runtime-parity checks are included where tests can mask real behavior.
- [x] Handoff decision records the change, verification, and any contract implications.

## Stretch Goals

- [x] Add a focused regression proving the observability dependency degrades without consuming the business request path when the probe fails.

## Success Criteria

- [x] HTTP session dependencies no longer wrap `db.session.get_session()` or call `session_iter.aclose()`.
- [x] Analyze routes rely on dependency-owned tenant setup only.
- [x] Timeout and statement-cache settings are configurable through `db/settings.py` and exercised by tests.
- [x] Close evidence is automated and deterministic rather than manual echo-log inspection.
