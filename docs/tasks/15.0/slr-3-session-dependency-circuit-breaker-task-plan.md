# SLR-3. Session Dependency Circuit Breaker

> **Metadata**
>
> - **Date**: 2026-04-09
> - **Author**: GPT-5
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Project**: prototype-description-service
> - **Task ID**: SLR-3
> - **Target Branch**: `feature/slr-3-session-dependency-circuit-breaker`
> - **Review Coverage Target**: 2

---

## Objective

Add a deterministic, repo-local circuit breaker to the recognition HTTP session dependency boundary so repeated database probe failures fail fast instead of re-consuming the same degraded path on every request. When this task is complete, the service tracks open, half-open, and closed breaker state in one place and surfaces breaker-open degradation honestly through the HTTP dependency and health flow.

## Problem Statement

SLR-1 fixed the double-owned session lifecycle and added timeout/configuration guards, but the service still probes the database independently on every request even during a sustained outage. Under repeated failures that means:

- request traffic keeps paying the probe cost
- degraded requests keep re-entering the same failing code path
- health behavior cannot distinguish "DB is currently unreachable" from "the service has intentionally opened the breaker and is fast-failing"

ADR-006 resolves the open architecture questions and says the breaker belongs in the HTTP dependency boundary, uses a small in-repo state machine, and stores state on FastAPI `app.state`.

## Constraints

- Scope is limited to `apps/prototype-description-service/`.
- The FastAPI dependency signatures remain stable for call sites that depend on `get_session`, `get_optional_session`, and `get_observability_session`.
- Breaker state must be deterministic and testable with fake clocks or explicit dependency injection.
- No third-party breaker library is introduced; use a local implementation.
- This task does not split the observability engine/pool yet; that belongs to SLR-4.

## Workflow Principles

- Keep the breaker policy beside the dependency path it governs.
- One owner for resilience state: the breaker lives on `app.state`, not as a per-request object.
- Fast-fail behavior must be explicit in tests and health responses, not inferred from logs.

## Terminology

- **Breaker open**: Fast-fail mode after the failure threshold is hit.
- **Half-open**: Recovery probe state where one trial request may re-check the dependency.
- **Business dependency**: The request-path DB dependency used by normal API traffic and by health reporting.

## Current State Analysis

- `recognition/interface_adapters/http/deps/session.py` still treats every probe failure as an isolated event.
- `api/main.py` does not initialize shared breaker state on `app.state`.
- `recognition/interface_adapters/http/routers/health.py` can report degraded DB access, but it does not expose breaker-open semantics.
- `db/settings.py` does not yet expose the breaker thresholds or timing knobs chosen in ADR-006.

## Target Outcome

Repeated DB probe failures transition the request dependency into open-breaker fast-fail mode after a bounded threshold. The breaker recovers via a half-open trial after the configured cool-down, and health responses can distinguish breaker-open degradation from ordinary DB failure.

## Context Loading

- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Rules: `docs/agentic/rules/testing-python.md`
- Spec: `docs/specs/session-lifecycle-resilience-spec.md`
- ADR: `docs/agentic/adrs/ADR-006-session-circuit-breaker-and-pool-bulkheading.md`
- Prior task: `docs/tasks/15.0/slr-1-session-lifecycle-resilience-task-plan.md`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| -------- | ----- | ---------------- | --------------- | --------------------- | ------------ |
| Session dependency resilience | Backend | `get_optional_session()` probes directly on each request | Add breaker-aware fast-fail state before the probe path | Yes — dependency signatures stay stable | targeted API/unit tests |
| App lifecycle state | Backend | no breaker state on app startup | initialize/reset breaker state on app construction | No | app wiring tests |
| Health semantics | Backend | degraded DB vs connected only | distinguish breaker-open degradation in health reporting | Yes — preserve non-5xx degraded behavior | health tests |

## Proposed Solution

Implement a small breaker module with explicit clock injection and state transitions, initialize it on FastAPI `app.state`, and teach the session dependency layer to consult it before probing. Probe failures record breaker failures; successful half-open probes close the breaker. Health surfaces should report breaker-open state without attempting the full request-path DB probe repeatedly.

## Files and Surfaces to Change

| Surface | File | Change |
| ------- | ---- | ------ |
| Breaker implementation | `apps/prototype-description-service/recognition/interface_adapters/http/deps/circuit_breaker.py` | New local breaker state machine and state container |
| Session dependency | `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | Integrate breaker checks, failure recording, and half-open success reset |
| App wiring | `apps/prototype-description-service/api/main.py` | Initialize breaker state on app startup / factory construction |
| Settings | `apps/prototype-description-service/db/settings.py` | Add `DB_BREAKER_FAILURE_THRESHOLD`, `DB_BREAKER_WINDOW_SECONDS`, `DB_BREAKER_HALF_OPEN_AFTER_SECONDS` |
| Health behavior | `apps/prototype-description-service/recognition/interface_adapters/http/routers/health.py` | Surface breaker-open degraded status without hiding DB state |
| Tests | `apps/prototype-description-service/recognition/tests/api/test_api_health.py` | Extend for breaker-open behavior |
| Tests | `apps/prototype-description-service/recognition/tests/api/test_dependencies.py` | Add fast-fail and half-open recovery coverage |
| Tests | `apps/prototype-description-service/recognition/tests/unit/test_database_settings.py` | Add breaker settings coverage |
| Tests | `apps/prototype-description-service/recognition/tests/unit/test_session_circuit_breaker.py` | New state-machine unit tests |

## Related Files

| File | Note |
| ---- | ---- |
| `apps/prototype-description-service/db/session.py` | Remains the business engine/session factory source while the breaker governs access |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/services.py` | Must stay aligned with any breaker-aware observability behavior until SLR-4 lands |
| `docs/agentic/adrs/ADR-006-session-circuit-breaker-and-pool-bulkheading.md` | Source of truth for breaker ownership and defaults |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && python -m pytest recognition/tests/unit/test_session_circuit_breaker.py recognition/tests/api/test_dependencies.py recognition/tests/api/test_api_health.py recognition/tests/unit/test_database_settings.py -q`
- Runtime-parity:
  - `cd apps/prototype-description-service && python -m pytest recognition/tests -q`
- Contract checks:
  - verify breaker settings exist in `db/settings.py`
  - verify health responses expose breaker-open degradation without returning 5xx for the normal degraded path

## Slice Delivery

### Slice 1: Breaker State Machine and Settings

**Goal**: Create the local breaker implementation and expose the ADR-backed settings.

Changes:

- Add the local breaker module with open, half-open, and closed transitions.
- Add breaker threshold/timing settings in `db/settings.py`.
- Add deterministic unit tests for failure counting and recovery.

Proof:

- `pytest recognition/tests/unit/test_session_circuit_breaker.py recognition/tests/unit/test_database_settings.py -q`

### Slice 2: Dependency Integration

**Goal**: Make the HTTP session dependency consult and update breaker state.

Changes:

- Initialize breaker state on app construction.
- Fast-fail optional-session requests while the breaker is open.
- Reset the breaker after a successful half-open probe.

Proof:

- `pytest recognition/tests/api/test_dependencies.py -q`

### Slice 3: Breaker-Aware Health Semantics

**Goal**: Report breaker-open degradation honestly through health.

Changes:

- Extend health responses to expose breaker-open state.
- Keep degraded behavior non-5xx and deterministic.

Proof:

- `pytest recognition/tests/api/test_api_health.py -q`
- `pytest recognition/tests -q`

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the spec, ADR, and SLR-1 outcome before editing.
- [ ] Confirmed the breaker stays in the dependency boundary and on `app.state`.
- [ ] Scoped out observability-pool splitting to SLR-4.

### Checklist for Slice 1: Breaker State Machine and Settings

- [ ] Add the local breaker implementation.
- [ ] Add ADR-backed breaker settings.
- [ ] Add deterministic breaker unit tests.

### Checklist for Slice 2: Dependency Integration

- [ ] Integrate breaker checks into the session dependency.
- [ ] Initialize breaker state in app wiring.
- [ ] Add dependency-path fast-fail and recovery tests.

### Checklist for Slice 3: Breaker-Aware Health Semantics

- [ ] Surface breaker-open degradation in health behavior.
- [ ] Preserve non-5xx degraded semantics.
- [ ] Capture targeted and full-suite verification evidence.

## Review Readiness

- [ ] Breaker state ownership is explicit and test-backed.
- [ ] No health-behavior change lands without matching contract evidence.
- [ ] Handoff records fresh verification on the branch commit.

## Stretch Goals

- [ ] Add a small metrics/logging hook for breaker state transitions if it can be done without broad observability contract churn.

## Success Criteria

- [ ] Repeated DB probe failures open the breaker after the configured threshold.
- [ ] A half-open recovery probe can close the breaker on success.
- [ ] Health responses can distinguish breaker-open degradation from ordinary DB connectivity failure.
