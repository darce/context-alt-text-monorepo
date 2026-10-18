# E15-9. API Key Usage Telemetry Deferral

> **Metadata**
>
> - **Date**: 2026-04-11
> - **Author**: GPT-5.4
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-9
> - **Target Branch**: `feature/e15-9-api-key-usage-telemetry-deferral`
> - **Review Coverage Target**: 2

---

## Objective

Implement the Tier 2 telemetry path from the auth transaction isolation spec so API-key usage bookkeeping runs after the response and cannot alter authentication correctness or request-transaction health. When this task is complete, `last_used_at` updates are best-effort background work with dedicated session ownership and bounded failure behavior.

## Problem Statement

ATI-002 removes `touch()` from the auth correctness path, but the service still needs a concrete replacement for usage telemetry. Leaving that replacement underspecified would either reintroduce a synchronous write into the request session or strand `last_used_at` updates indefinitely. The planning review explicitly rejected another request-path write and required one clear design choice: post-response `BackgroundTasks` with a dedicated session.

## Constraints

- Scope is limited to the telemetry path for API-key usage inside `apps/prototype-description-service/`.
- This task depends on E15-8 landing first; it must not reintroduce inline writes into the auth lookup path.
- No external queue or new infrastructure is introduced here; the solution stays in-process and app-local.
- The background task must open its own session or unit of work rather than reusing the request-scoped session.
- Telemetry failure remains observable but non-fatal to authentication.
- The plan must choose a concrete repository write shape for post-response telemetry; the existing `touch(api_key)` API is not sufficient when the enqueue boundary only has `api_key_id`.

## Workflow Principles

- Authentication correctness and telemetry are separate responsibilities.
- Post-response work must have its own ownership boundary.
- Latency added to every authenticated request needs stronger justification than telemetry has.

## Terminology

- **Telemetry deferral**: Recording API-key usage after the response rather than before auth returns.
- **Dedicated telemetry session**: A short-lived session created inside the background task rather than inherited from the request.
- **Best-effort bookkeeping**: A side-effect that logs failure and exits without changing the user-visible auth result.

## Current State Analysis

- The repository already exposes `touch()` for `last_used_at` updates, but Tier 1 intentionally removes it from auth success.
- FastAPI `BackgroundTasks` is the chosen app-local execution path in the spec, but the concrete wiring, session ownership, and failure logging are not yet defined in code.
- The auth dependency still needs a stable place to enqueue the telemetry task once lookup succeeds.

## Target Outcome

Successful API-key authentication schedules a background telemetry task that updates `last_used_at` with its own session, logs any failure, and never changes the response returned to the caller. The request-critical auth path stays pure and low-latency, while usage telemetry remains available as best-effort operational data.

## Context Loading

- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Rules: `docs/agentic/rules/testing-python.md`
- Spec: `docs/specs/auth-transaction-isolation-spec.md`
- Predecessor task plan: `docs/tasks/15.0/E15-8-auth-transaction-isolation-core-task-plan.md`
- Handoff/MCP state: `ASMT-REVIEW-1` or the follow-on implementation task created from this plan

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| -------- | ----- | ---------------- | --------------- | --------------------- | ------------ |
| Auth dependency surface | Backend | Auth lookup returns success without inline telemetry after E15-8 | Successful auth schedules a background bookkeeping task | Yes | `pytest recognition/tests/api/test_authentication.py -q` |
| API-key usage bookkeeping | Backend | `touch()` exists as a repository write helper | `touch()` is invoked only from the background telemetry path with dedicated session ownership | No external compatibility requirement | auth telemetry regression tests |

## Proposed Solution

1. Inject or access FastAPI `BackgroundTasks` at the auth dependency boundary.
2. Add a targeted repository write helper such as `touch_by_id(api_key_id: str)` that performs the `last_used_at` update without requiring a pre-loaded ORM record; this keeps the background path lightweight and dedicated-session friendly.
3. Schedule a background function that opens a dedicated session and invokes that targeted update helper.
4. Log telemetry-task failures with enough context for operations without surfacing them as auth failures.
5. Keep the dependency test seam explicit: direct-call tests of `require_auth()` must pass a `BackgroundTasks` instance or use an optional/no-op enqueue parameter rather than relying on the old signature shape.
6. Add regression tests that prove auth success survives telemetry failure and that the task does not reuse the request session.

## Files and Surfaces to Change

| Surface | File | Change |
| ------- | ---- | ------ |
| Backend auth dependency | `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py` | Enqueue the telemetry background task after successful lookup |
| Repository or helper layer | `apps/prototype-description-service/recognition/infrastructure/repositories/api_key_repository.py` | Add a targeted `touch_by_id(...)`-style helper for the dedicated-session telemetry update path |
| API tests | `apps/prototype-description-service/recognition/tests/api/test_authentication.py` | Add regression coverage for background telemetry success and failure semantics |

## Related Files

| File | Note |
| ---- | ---- |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | Request-session ownership must remain separate from telemetry work |
| `docs/tasks/15.0/E15-8-auth-transaction-isolation-core-task-plan.md` | Must land first so auth success is already pure-query |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && VIRTUAL_ENV= uv run --locked --extra dev python -m pytest recognition/tests/api/test_authentication.py -q`
- Contract and failure-mode verification:
  - Verify telemetry failure does not alter auth success or request status codes.
  - Verify the telemetry path does not reuse the request-scoped session.
  - Verify the background task updates `last_used_at` through the chosen targeted write helper rather than requiring a pre-loaded ORM instance.
  - Verify any direct-call `require_auth()` tests inject `BackgroundTasks` (or exercise the optional/no-op path) so the signature change is intentional and covered.

## Slice Delivery

### Slice 1: Background Task Wiring

**Spec items**: `ATI-004`

**Goal**: Move API-key usage bookkeeping onto a post-response background path.

Changes:

- Enqueue `record_api_key_use(...)` via `BackgroundTasks` after successful auth lookup.
- Add the targeted `touch_by_id(...)` repository helper used by the background path.
- Ensure the background function opens its own session and performs the `last_used_at` update there.

Proof:

- `cd apps/prototype-description-service && VIRTUAL_ENV= uv run --locked --extra dev python -m pytest recognition/tests/api/test_authentication.py -q`

### Slice 2: Failure Semantics and Observability

**Spec items**: `ATI-004`

**Goal**: Keep telemetry best-effort and visible to operators without coupling it back to auth correctness.

Changes:

- Log background telemetry failures with API-key context suitable for diagnosis.
- Add regression coverage forcing telemetry failure while asserting auth still succeeds.

Proof:

- `cd apps/prototype-description-service && VIRTUAL_ENV= uv run --locked --extra dev python -m pytest recognition/tests/api/test_authentication.py -q`

## Consolidated Checklist

## Context and Ownership

- [x] Load the spec and predecessor task plan before implementing telemetry work.
- [x] Keep request-session ownership and telemetry-session ownership separate.
- [x] Use an id-based repository write helper for telemetry so the background task does not depend on a pre-loaded ORM record from the request path.

### Checklist for Slice 1: Background Task Wiring

- [x] Add the background-task enqueue point after successful auth lookup.
- [x] Add the targeted `touch_by_id(...)` repository helper (or equivalent explicit id-based update path).
- [x] Ensure the telemetry task creates its own session boundary.

### Checklist for Slice 2: Failure Semantics and Observability

- [x] Log telemetry failures without altering auth correctness.
- [x] Add deterministic regression coverage for telemetry failure.
- [x] Update any direct-call `require_auth()` tests to pass `BackgroundTasks` or cover the optional/no-op enqueue seam explicitly.

## Review Readiness

- [x] No synchronous telemetry write remains in the request session.
- [x] Auth success remains unchanged when telemetry fails.
- [x] Handoff records the chosen background-task semantics and verification evidence.

## Success Criteria

- [x] `last_used_at` updates happen after the response through a background task.
- [x] Telemetry work uses a dedicated session rather than the request-scoped session.
- [x] Telemetry failure is observable but never user-visible as an auth failure.
