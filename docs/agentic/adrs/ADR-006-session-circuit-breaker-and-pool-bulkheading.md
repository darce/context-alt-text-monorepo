# ADR-006: Session Circuit Breaker and Observability Pool Bulkheading

## Status

Accepted

## Date

2026-04-09

## Author

GPT-5 high

## Context

The session lifecycle resilience spec marks two follow-on resilience items as Tier 3: `SLR-CB` (circuit breaker on the session dependency) and `SLR-BH` (observability pool bulkheading). Both items are blocked because they change how the recognition service handles degraded database access under load, and the choice affects dependency ownership, health reporting, and the DB engine topology.

The assessment at `docs/assessment/infailed-sql-transaction-investigation-2026-04-09.md` shows the immediate bug is a double-owned SQLAlchemy lifecycle, but it also leaves two broader resilience questions open:

- how aggressively HTTP dependencies should fail fast after repeated DB probe failures
- whether observability and diagnostic reads should continue sharing the same connection pool as business requests

### Constraints from prior review

- The HTTP session dependency contract stays stable for FastAPI call sites.
- Greenfield policy applies; choose the cleanest design rather than preserving a shared-pool workaround.
- The resilience layer must be testable from the repo with deterministic failure injection.
- Observability and health surfaces should degrade honestly without taking more capacity from the business request path during a DB incident.

## Current State Inventory

`apps/prototype-description-service/db/session.py` exposes a single global `AsyncEngine`, one `async_session_factory`, and pool stats for the whole service. `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` currently gives both request traffic and observability traffic sessions from that same engine. `apps/prototype-description-service/recognition/interface_adapters/http/deps/services.py` uses `get_observability_session()` for diagnostic repositories, and `apps/prototype-description-service/recognition/interface_adapters/http/routers/health.py` plus `apps/prototype-description-service/recognition/interface_adapters/http/exception_handlers.py` depend on that shared state to report degraded health and pool behavior.

Today there is no circuit breaker state in the dependency layer. Every request attempts the probe path independently, even when the DB is clearly unavailable, and observability reads compete for the same pool slots as normal request traffic.

### Downstream surfaces that must migrate together

- `apps/prototype-description-service/db/session.py` — engine/session factory topology and pool settings
- `apps/prototype-description-service/db/session.py::get_pool_stats()` — must report both business-pool and observability-pool stats after the split, either via a nested return shape or an explicit pool selector
- `apps/prototype-description-service/db/settings.py` — new env vars for breaker thresholds and observability pool sizing
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` — breaker checks and separate observability session factory
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/services.py` — observability repository wiring
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/health.py` — degraded health semantics under breaker-open conditions
- `apps/prototype-description-service/recognition/interface_adapters/http/exception_handlers.py` — pool stats and degraded error payload behavior
- `apps/prototype-description-service/recognition/tests/api/test_api_health.py` and follow-on dependency tests — regression coverage for open-breaker and bulkhead behavior

## Decision

Use a lightweight in-process circuit breaker in the HTTP dependency layer and split observability traffic onto a dedicated `AsyncEngine` with its own small pool.

### Chosen design rules

1. **Circuit state lives in the dependency boundary.** The breaker wraps the DB probe path in `deps/session.py`, not the repository layer. It tracks repeated failures over a short rolling window and fails fast for optional or observability dependencies while the breaker is open.
2. **Use a repo-local implementation, not a breaker library.** The service needs a narrow state machine with explicit open, half-open, and closed transitions and test-friendly clocks. A small in-repo breaker keeps the semantics obvious and avoids third-party policy drift.
3. **Observability gets a separate engine and pool.** `get_observability_session()` uses a dedicated engine/sessionmaker built from the same DSN but with independent pool sizing and timeouts. This is the actual bulkhead; logical partitioning inside one pool is rejected.
4. **Business traffic remains the authoritative path.** `health_check` stays on the breaker-gated business dependency (`get_optional_session`). When the breaker is open, health reports degraded status via fast-fail without consuming additional pool connections. Pool-inspection surfaces such as `/health/pool` must evolve to report both engines after the split.
5. **Breaker state must outlive individual requests.** The breaker state lives on FastAPI `app.state` and is read by the session dependency, rather than as a per-request object. This keeps the lifecycle explicit, test-friendly, and resettable through app construction or dependency overrides.

### Configuration defaults

- `failure_threshold=3` consecutive probe failures before opening the breaker
- `window_seconds=30` for failure accumulation
- `half_open_after_seconds=10` before a single trial probe is allowed
- `observability_pool_size=2` with `observability_max_overflow=0`
- `observability_pool_timeout=5` seconds so diagnostics fail quickly under pressure

These are starting values, not hard-coded constants. The implementation task should surface them as environment-backed settings in `db/settings.py`.

### Target outcome

Repeated DB probe failures transition the request dependency into fail-fast mode within a bounded threshold, and observability requests no longer consume the business request pool during the same outage window. Health responses remain honest about degraded DB access and breaker state.

## Why This Decision

### Real isolation beats policy-only isolation

A separate engine with a tiny pool is the only way to guarantee that diagnostic reads cannot consume the same checked-out connections as analyze or clustering requests. Pool partitioning by convention would still leave one shared exhaustion surface.

### The dependency layer owns the failure mode

The probe, degrade-to-`None`, and optional-session semantics already live in `deps/session.py`. Putting the breaker there keeps the failure policy beside the current lifecycle logic and avoids leaking resilience state into repositories or routers.

### A small local breaker is easier to verify

The needed behavior is narrow: count failures, open after threshold, allow one half-open probe, and reset on success. A local implementation is easy to unit test with fake clocks and dependency injection, while external libraries would add policy and lifecycle surface area the service does not otherwise need.

## Alternatives Considered

### 1. Use `pybreaker` or `tenacity`

Rejected.

Those libraries solve a broader retry or breaker problem than this service has today. They add configuration and lifecycle surface area, and they do not remove the need to decide where the breaker state lives or how health and optional-session paths should degrade. The narrower in-repo breaker is easier to review and align with the existing dependency contract.

### 2. Keep one shared engine and reserve a few pool slots by convention

Rejected.

One shared SQLAlchemy pool cannot guarantee capacity isolation. During a degraded or poisoned-transaction incident, observability probes and health checks would still compete with business requests for the same checked-out connections.

### 3. Put the breaker in the repository layer

Rejected.

The degraded behavior is decided before repositories are even constructed for optional-session and observability callers. Moving breaker logic lower would duplicate policy across call paths and leave the HTTP dependency boundary without a single source of truth.

## Consequences

### Positive

- Degraded DB incidents fail faster and with clearer state transitions.
- Health and diagnostic traffic stop contending with business requests for the same pool.
- The resilience policy becomes explicit and testable in one boundary.

### Negative

- The service now manages two engines instead of one.
- Breaker thresholds and observability pool sizes become new runtime configuration to document.
- Health and exception payloads must distinguish DB-down from breaker-open conditions.

### Guardrails for the follow-on implementation task

- Keep the existing FastAPI dependency signatures stable.
- Do not add a generic resilience abstraction layer beyond what the session dependency needs.
- The observability engine must use independent pool settings; reusing the same pool with labels is not acceptable.
- Breaker state transitions must have deterministic unit tests and degraded API-path tests in the same task.

## References

- Spec: [docs/specs/session-lifecycle-resilience-spec.md](../../specs/session-lifecycle-resilience-spec.md)
- Assessment: [docs/assessment/infailed-sql-transaction-investigation-2026-04-09.md](../../assessment/infailed-sql-transaction-investigation-2026-04-09.md)
- Implementation task plans:
  - [docs/tasks/15.0/slr-3-session-dependency-circuit-breaker-task-plan.md](../../tasks/15.0/slr-3-session-dependency-circuit-breaker-task-plan.md)
  - [docs/tasks/15.0/slr-4-observability-pool-bulkhead-task-plan.md](../../tasks/15.0/slr-4-observability-pool-bulkhead-task-plan.md)
- Related: [docs/roadmaps/roadmap-pg18-upgrade.md](../../roadmaps/roadmap-pg18-upgrade.md)
