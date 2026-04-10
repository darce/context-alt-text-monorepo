# SLR-4. Observability Pool Bulkhead

> **Metadata**
>
> - **Date**: 2026-04-09
> - **Author**: GPT-5
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Project**: prototype-description-service
> - **Task ID**: SLR-4
> - **Target Branch**: `feature/slr-4-observability-pool-bulkhead`
> - **Status**: Completed; merged to `main` on 2026-04-10
> - **Review Coverage Target**: 2

---

## Objective

Split observability and diagnostic traffic onto a dedicated async engine and pool so health and diagnostic reads cannot consume the same connection capacity as business requests. When this task is complete, `get_observability_session()` is backed by a dedicated engine with its own pool limits and the service can report business-pool and observability-pool state separately.

## Problem Statement

ADR-006 rejects policy-only isolation inside one shared pool. After SLR-1 and SLR-3, request traffic may fail faster, but observability reads would still contend for the same engine unless the bulkhead is implemented concretely. Without the bulkhead:

- health and diagnostic queries can still consume business-pool slots
- pool stats cannot distinguish business pressure from diagnostic pressure
- degraded reporting remains coupled to the same exhaustion surface it is trying to describe

## Constraints

- Scope is limited to `apps/prototype-description-service/`.
- The observability bulkhead must use a dedicated `AsyncEngine` and separate pool settings, not labels on the existing pool.
- Business-session behavior from SLR-1 remains the default path and must not regress.
- Pool sizing and timeout settings must be environment-backed through `db/settings.py`.
- Health and diagnostics should degrade honestly when the observability pool itself is unavailable.
- After the pool split, `get_observability_session()` is decoupled from the business-pool circuit breaker introduced in SLR-3. Any observability-specific breaker policy is a separate follow-on concern.

## Workflow Principles

- Real isolation over convention: different engine, different pool.
- Preserve business-path semantics while making observability degradation explicit.
- Pool stats must become more informative, not less, after the split.

## Terminology

- **Business pool**: The main engine and pool used by request traffic.
- **Observability pool**: The dedicated engine and pool used for diagnostics and health-side reads.
- **Bulkhead**: The dedicated observability pool boundary that prevents diagnostics from consuming business capacity.

## Current State Analysis

- `db/session.py` currently exposes one engine and one `async_session_factory`.
- `get_observability_session()` in `deps/session.py` still uses the same factory as business requests.
- `get_pool_stats()` reports one pool, which is insufficient once the bulkhead exists.
- `recognition/interface_adapters/http/deps/services.py` and health behavior assume a single DB session source for diagnostics.

## Target Outcome

Observability traffic uses its own small engine/pool, business traffic uses the existing engine/pool, and pool-inspection or health surfaces can report both separately. Diagnostic failure no longer implies that the business pool had to spend capacity to learn it was degraded.

## Context Loading

- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Rules: `docs/agentic/rules/testing-python.md`
- Spec: `docs/specs/session-lifecycle-resilience-spec.md`
- ADR: `docs/adrs/ADR-006-session-circuit-breaker-and-pool-bulkheading.md`
- Prior task: `docs/tasks/15.0/slr-3-session-dependency-circuit-breaker-task-plan.md`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| -------- | ----- | ---------------- | --------------- | --------------------- | ------------ |
| DB session topology | Backend | one engine / one pool | add dedicated observability engine and factory | Yes — business factory remains intact | unit + API tests |
| Observability dependency | Backend | same factory as business requests | dedicated observability factory | Yes — optional/degraded semantics remain | dependency/health tests |
| Pool stats | Backend | single-pool stats shape | report business and observability pools explicitly | Yes — callers and tests must adapt | pool/health tests |

## Proposed Solution

Add a second async engine and sessionmaker in `db/session.py`, backed by environment-driven observability pool settings from `db/settings.py`. Rewire `get_observability_session()` to use that factory without consulting the business-pool breaker, update pool stats to report both pools clearly, and adjust observability/health consumers and tests to use the split topology.

## Files and Surfaces to Change

| Surface | File | Change |
| ------- | ---- | ------ |
| Settings | `apps/prototype-description-service/db/settings.py` | Add `DB_OBSERVABILITY_POOL_SIZE`, `DB_OBSERVABILITY_MAX_OVERFLOW`, `DB_OBSERVABILITY_POOL_TIMEOUT` |
| Session topology | `apps/prototype-description-service/db/session.py` | Add observability engine/sessionmaker and split pool stats |
| Session dependency | `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | Switch `get_observability_session()` to the dedicated factory |
| Service wiring | `apps/prototype-description-service/recognition/interface_adapters/http/deps/services.py` | Keep observability repositories aligned with the split session source |
| Health / diagnostics | `apps/prototype-description-service/recognition/interface_adapters/http/routers/health.py` | Report bulkhead-aware degraded behavior and dual-pool stats |
| Exception handling | `apps/prototype-description-service/recognition/interface_adapters/http/exception_handlers.py` | Keep degraded payloads aligned if pool stats shape changes |
| Tests | `apps/prototype-description-service/recognition/tests/api/test_api_health.py` | Extend for observability-pool degradation and stats |
| Tests | `apps/prototype-description-service/recognition/tests/unit/test_connection_pool.py` | Extend for split-pool stats |
| Tests | `apps/prototype-description-service/recognition/tests/unit/test_database_settings.py` | Add observability pool setting coverage |

## Related Files

| File | Note |
| ---- | ---- |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | SLR-3 may already add breaker semantics that health must keep consistent |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/services.py` | observability repositories and optional-session consumers must not silently regress |
| `docs/adrs/ADR-006-session-circuit-breaker-and-pool-bulkheading.md` | source of truth for bulkhead ownership and default pool sizing |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && python -m pytest recognition/tests/unit/test_connection_pool.py recognition/tests/unit/test_database_settings.py recognition/tests/api/test_api_health.py -q`
- Runtime-parity:
  - `cd apps/prototype-description-service && python -m pytest recognition/tests -q`
- Contract checks:
  - verify pool stats expose business and observability pools explicitly
  - verify observability dependency degrades without consuming business-path capacity in tests

## Slice Delivery

### Slice 1: Observability Pool Settings and Engine Topology

**Goal**: Add the observability pool settings and a dedicated engine/factory.

Changes:

- Add observability pool settings to `db/settings.py`.
- Add the dedicated observability engine/sessionmaker to `db/session.py`.
- Extend unit coverage for settings and pool stats.

Proof:

- `pytest recognition/tests/unit/test_connection_pool.py recognition/tests/unit/test_database_settings.py -q`

### Slice 2: Observability Dependency and Service Wiring

**Goal**: Move observability session consumers onto the dedicated pool.

Changes:

- Switch `get_observability_session()` to the observability sessionmaker.
- Keep service/repository wiring aligned with the split dependency source.
- Decouple observability-session behavior from the SLR-3 business breaker once the independent pool exists.

Proof:

- `pytest recognition/tests/api/test_dependencies.py recognition/tests/api/test_api_health.py -q`

### Slice 3: Dual-Pool Reporting and Regression Proof

**Goal**: Report the new pool shape clearly and preserve whole-package behavior.

Changes:

- Update pool-stats reporting and any dependent health/diagnostic payloads, including `exception_handlers.py` consumers.
- Verify the full recognition suite still passes with the split topology.

Proof:

- `pytest recognition/tests -q`

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the spec, ADR, and prior SLR task outcomes before editing.
- [x] Confirmed the bulkhead is a separate engine/pool, not a logical partition.
- [x] Scoped any breaker-state ownership changes out of this task unless strictly required for compatibility.

### Checklist for Slice 1: Observability Pool Settings and Engine Topology

- [x] Add observability pool settings.
- [x] Add a dedicated observability engine/sessionmaker.
- [x] Extend settings and pool unit tests.

### Checklist for Slice 2: Observability Dependency and Service Wiring

- [x] Switch observability dependency wiring to the dedicated factory.
- [x] Keep service/repository wiring aligned with the split source.
- [x] Prove degraded observability behavior with targeted tests.

### Checklist for Slice 3: Dual-Pool Reporting and Regression Proof

- [x] Update pool stats and any dependent payloads to show both pools clearly.
- [x] Preserve whole recognition-package behavior.
- [x] Record targeted and full-suite verification evidence in handoff.

## Review Readiness

- [x] The bulkhead uses a real separate engine/pool.
- [x] Pool stats and degraded behavior are explicit in tests.
- [x] Handoff records fresh verification on the branch commit.

## Stretch Goals

- [ ] Add a tiny helper or selector API for `get_pool_stats()` if it improves downstream readability without expanding scope too far.

## Success Criteria

- [x] `get_observability_session()` no longer uses the business session factory.
- [x] Business and observability pools are independently configurable.
- [x] Pool-inspection or health surfaces can distinguish business-pool and observability-pool state.
