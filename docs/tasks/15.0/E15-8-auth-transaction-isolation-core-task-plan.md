# E15-8. Auth Transaction Isolation Core

> **Metadata**
>
> - **Date**: 2026-04-11
> - **Author**: GPT-5.4
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-8
> - **Target Branch**: `feature/e15-8-auth-transaction-isolation-core`
> - **Review Coverage Target**: 2

---

## Objective

Implement the Tier 1 portion of the auth transaction isolation spec so auth lookup failures stop poisoning the request-scoped transaction. When this task is complete, API-key authentication is a pure query, permanent auth-store faults fail fast, and auth-side SQL errors are contained by a savepoint-backed nested transaction boundary.

## Problem Statement

The current auth path in `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py` reuses the same request-scoped `AsyncSession` later consumed by route business logic. That helper currently does three risky things in one place:

- looks up the API key on the shared session
- swallows some database failures and continues toward dev-key fallback
- mutates `last_used_at` on the same session before returning success

That combination creates the precise `InFailedSQLTransactionError` failure class documented in the assessment. A failed auth statement leaves the shared transaction aborted, but the code keeps going, so the first visible failure often appears later in route logic as `25P02` instead of at the auth boundary.

## Constraints

- Scope is limited to `apps/prototype-description-service/`.
- FastAPI route signatures must remain compatible with existing auth consumers.
- This task implements only ATI-001, ATI-002, and ATI-003; telemetry deferral moves to the follow-on task.
- No dedicated auth-session boundary is introduced here; ATI-005 remains ADR-gated.
- PostgreSQL-backed failure classification must prefer SQLSTATE values over message-text parsing.
- Savepoint containment must rely on exception propagation to the `begin_nested()` boundary; in-block exception suppression is not allowed.
- The existing `session is None` breaker-open path remains an explicit precondition guard; the refactor must preserve that behavior before any `begin_nested()` call is attempted.

## Workflow Principles

- Authentication correctness is query-only; telemetry is not part of the success path.
- Auth failures surface at the auth boundary, not later as poisoned-transaction fallout.
- Savepoint rollback is structural containment, not a policy convention.

## Terminology

- **Auth boundary**: The `require_auth()` / `_lookup_api_key()` dependency surface in the recognition HTTP adapter.
- **Savepoint containment**: A `session.begin_nested()` block whose rollback is triggered by exception propagation to the context-manager boundary.
- **SQLSTATE classification**: Failure handling driven by PostgreSQL error codes such as `42P01` and `25P02`, with fallback only for non-PostgreSQL test environments.

## Current State Analysis

- `recognition/interface_adapters/http/deps/auth.py` still uses message-text detection for missing-table fallback and still returns success after a best-effort `repo.touch(record)`.
- `recognition/infrastructure/repositories/api_key_repository.py` exposes `get_by_hash()` and `touch()` on the same session, so the auth helper currently couples lookup and mutation.
- `recognition/interface_adapters/http/deps/session.py` commits the outer request session after dependency resolution, which means any auth-side exception suppression can leave a poisoned transaction alive until business logic runs.
- The test stack already supports nested transactions through `begin_nested()` in the package fixtures, so savepoint-based containment is available without an infrastructure change.

## Target Outcome

The auth helper classifies database failures using structured error data, rejects permanent auth-store faults immediately, and returns auth success only from lookup state. Auth DB work runs inside a nested transaction boundary that rolls back on failure and leaves the outer request session usable for downstream queries.

## Context Loading

- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Rules: `docs/agentic/rules/testing-python.md`
- Rules: `docs/agentic/rules/planning-review-guide.md`
- Spec: `docs/specs/auth-transaction-isolation-spec.md`
- Assessment: `docs/assessments/infailed-sql-transaction-persistent-after-slr-2026-04-10.md`
- Prior resilience plans: `docs/tasks/15.0/slr-1-session-lifecycle-resilience-task-plan.md`
- Handoff/MCP state: `ASMT-REVIEW-1`, including resolved `ATI-SPEC-PLAN-*` findings

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| -------- | ----- | ---------------- | --------------- | --------------------- | ------------ |
| Auth dependency surface | Backend | `require_auth()` returns `AuthContext` for existing route consumers | Internal lookup and error-handling refactor only; dependency signature stays stable | Yes | `pytest recognition/tests/api/test_authentication.py -q` |
| Request session usage | Backend | Auth and business logic currently share one mutable transaction with no structural containment | Shared-session design remains, but auth DB work gains a nested-transaction boundary | Yes | targeted auth regression plus downstream route coverage |
| API-key repository | Backend | Lookup and touch helpers exist on one repository | Tier 1 stops calling `touch()` from the auth success path | No external compatibility requirement | auth regression tests |

## Proposed Solution

1. Preserve the existing `session is None` short-circuit before any repository or nested-transaction work so breaker-open requests fail at the auth boundary instead of crashing on `AttributeError`.
2. Introduce an internal auth lookup result surface so authentication returns pure lookup data and no longer performs `touch()` inline.
3. Replace message-text-only failure handling with SQLSTATE-first classification, using PostgreSQL codes such as `42P01` and `25P02` when available.
4. Wrap only the database lookup portion of auth work in `session.begin_nested()` and require exceptions to escape to the context-manager boundary so SQLAlchemy issues the rollback-to-savepoint automatically.
5. Perform the `record is None -> HTTPException(403)` translation and success-result construction after the nested block exits cleanly, so business auth outcomes are not raised from inside the savepoint boundary.
6. Translate true lookup failures at the auth boundary instead of allowing downstream code to discover the broken transaction later.

## Files and Surfaces to Change

| Surface | File | Change |
| ------- | ---- | ------ |
| Backend auth dependency | `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py` | Introduce pure-query auth lookup, SQLSTATE-aware failure classification, and nested-transaction containment |
| Repository surface | `apps/prototype-description-service/recognition/infrastructure/repositories/api_key_repository.py` | Stop relying on `touch()` from the auth correctness path; retain lookup semantics needed by the auth helper |
| API tests | `apps/prototype-description-service/recognition/tests/api/test_authentication.py` | Add regression coverage for fail-fast schema faults, savepoint containment, and pure-query auth success |
| API regression surface | `apps/prototype-description-service/recognition/tests/api/test_retention_api.py` | Add or extend a downstream same-request scenario proving an auth-side DB failure is translated at the auth boundary and does not leave the outer session unusable |

## Related Files

| File | Note |
| ---- | ---- |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | Owns the outer request-session lifecycle that the nested auth boundary must preserve |
| `apps/prototype-description-service/recognition/config/security.py` | Defines the auth-enabled/dev-key behavior that ATI-001 hardens |
| `apps/prototype-description-service/recognition/tests/conftest.py` | Confirms fixture-level nested-transaction support already exists |
| `docs/tasks/15.0/E15-9-api-key-usage-telemetry-deferral-task-plan.md` | Follow-on task for ATI-004 once this core isolation work lands |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_authentication.py -q`
  - `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_retention_api.py -q`
- Contract and failure-mode verification:
  - Verify `session is None` still fails through the existing breaker-open/auth-unavailable path before any nested transaction logic runs.
  - Verify the auth helper no longer calls `repo.touch(...)` on the success path.
  - Verify the nested auth helper contains failures without producing downstream `25P02` fallout.
  - Verify the savepoint block encloses only the lookup query; `record is None` translation to `HTTPException(403)` and success result construction happen after the nested block exits.
- Manual verification is not a close gate; proof stays in repo-owned tests.

## Slice Delivery

### Slice 1: SQLSTATE-Aware Auth Failure Classification

**Spec items**: `ATI-001`, `ATI-002`

**Goal**: Make authentication a pure lookup path and fail fast on permanent auth-store faults.

Changes:

- Introduce or refactor an internal lookup result type for auth success.
- Replace missing-table text parsing with SQLSTATE-first failure classification.
- Remove `repo.touch(record)` from the auth success path.
- Preserve the explicit `session is None` guard before the nested lookup path is entered.

Proof:

- `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_authentication.py -q`

### Slice 2: Savepoint Containment for Auth DB Work

**Spec items**: `ATI-003`

**Goal**: Ensure auth-side SQL errors roll back to a savepoint and do not poison the outer request transaction.

Changes:

- Add the `session.begin_nested()` boundary around only the auth lookup query.
- Keep exception translation outside the nested block so rollback-to-savepoint happens automatically.
- Perform `record is None` rejection and success-result construction after the nested block exits.
- Add regression coverage that forces an auth-side SQL failure and then proves the same request path fails at the auth boundary rather than later with `25P02`.
- If [`test_retention_api.py`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/tests/api/test_retention_api.py) continues to use [`FakeSession`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/tests/api/conftest.py), extend that fake with a real `begin_nested()` test seam (enter/exit tracking plus rollback signaling) or replace the scenario with a package-level fixture that exercises an actual nested transaction.

Proof:

- `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_authentication.py -q`
- `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_retention_api.py -q`

## Consolidated Checklist

## Context and Ownership

- [x] Load the spec, assessment, and current handoff findings before editing code.
- [x] Keep auth dependency signatures stable for existing route consumers.
- [x] Preserve the shared request session while isolating auth-side failures structurally.
- [x] Preserve the `session is None` auth guard before any savepoint work is attempted.

### Checklist for Slice 1: SQLSTATE-Aware Auth Failure Classification

- [x] Replace message-text-first auth failure detection with SQLSTATE-first classification.
- [x] Remove inline telemetry writes from auth success.
- [x] Add deterministic auth regression coverage for fail-fast schema faults and invalid keys.
- [x] Ensure business `403` invalid-key handling is raised after the nested lookup block exits.

### Checklist for Slice 2: Savepoint Containment for Auth DB Work

- [x] Add the nested transaction boundary around auth DB work.
- [x] Limit the nested block to the lookup query and let savepoint rollback be driven by real lookup exceptions only.
- [x] Ensure no exception suppression occurs inside the nested block.
- [x] Add regression coverage proving auth failures no longer surface later as `25P02`.
- [x] Make the downstream regression concrete in `test_retention_api.py` by either extending `FakeSession.begin_nested()` or using a fixture with actual nested-transaction support.

## Review Readiness

- [x] No auth-side database failure path continues silently after a poisoned transaction state.
- [x] The pure-query auth path and savepoint containment are both covered by deterministic tests.
- [x] Handoff records the change, verification evidence, and any follow-on telemetry dependency.

## Success Criteria

- [x] Missing auth schema faults fail fast instead of silently falling through to dev-key success.
- [x] API-key authentication no longer depends on `touch()` or `flush()` to succeed.
- [x] Auth-side SQL failures are contained by a savepoint-backed nested transaction and do not surface later as `25P02` in business logic.
