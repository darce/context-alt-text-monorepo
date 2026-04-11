# Auth Transaction Isolation Specification

> **Metadata**
>
> - **Date**: 2026-04-11
> - **Author**: GPT-5.4
> - **Status**: Draft
> - **Assessment**: [docs/assessments/infailed-sql-transaction-persistent-after-slr-2026-04-10.md](../assessments/infailed-sql-transaction-persistent-after-slr-2026-04-10.md)
> - **Package version target**: n/a (monorepo `apps/prototype-description-service`)
>
> **Purpose:** This spec defines concrete, testable changes to stop auth-side database failures from poisoning the request transaction in `apps/prototype-description-service`. It turns the assessment findings into implementable boundaries, verification rules, and a narrow ADR gate.
>
> **Pipeline position:** Assessment -> **Spec** -> [ADR] -> Task Plan -> Implementation.
>
> **Exit gate:** At least one planning review pass with findings recorded in MCP. All findings resolved. Validation snippets verified against the current package. No implementation tasks may be created until this gate is passed.

**Constraints:** Greenfield policy applies. Breaking cleanup is acceptable; backward-compatibility shims are not required. The FastAPI auth dependency surface must remain compatible with current route signatures. `RECOGNITION_AUTH_ENABLED` must continue to disable auth entirely for explicit local or test use, but dev-key fallback must not mask permanent auth-store faults when auth is enabled. Start with the smallest structural fix that can be justified from current code; escalate to an ADR only if planning review shows that a shared-session savepoint boundary is insufficient.

## Design Rationale

This spec fixes a cascading failure at an integration boundary, not just an isolated helper bug. The auth dependency currently shares one mutable request transaction with downstream business logic, so an auth-side SQL failure becomes a later `25P02` failure in route code. That is the same failure family Michael Nygard describes as cascading failure and blocked-resource propagation in [Release It!](../../literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt).

The default containment model is a savepoint-backed nested transaction inside the shared request session. PostgreSQL 17 explicitly documents that `ROLLBACK TO SAVEPOINT` is the way to regain control after a statement leaves the surrounding transaction in the aborted state, short of rolling the whole transaction back. In SQLAlchemy async code, `session.begin_nested()` is the application-level boundary that maps to that savepoint behavior, so exceptions raised inside the nested block must propagate to the context-manager boundary rather than being suppressed inside it.

The telemetry path is intentionally separated from authentication correctness. Nygard's bulkhead guidance and Pekka Enberg's latency-compounding guidance both point away from a synchronous `touch()` write on the request-critical path. This spec therefore chooses post-response background execution with a dedicated session for telemetry rather than another synchronous write inside the request session.

---

## Spec Items

### ATI-001: Classify auth-store failures and fail fast on permanent schema faults

**Trace:** F3
**Priority:** P0

`apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_lookup_api_key` currently collapses a missing-table error into `record = None`, then falls through to `settings.dev_api_keys`. That makes a permanent auth-store fault look like normal auth behavior. The lookup path must classify auth-side database failures and refuse silent fallback when the underlying store is unavailable or misconfigured. Classification must prefer PostgreSQL SQLSTATE values when they are available and only fall back to message-shape heuristics for non-PostgreSQL unit-test doubles that do not expose `pgcode`.

**Before** (`apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_lookup_api_key`):

```python
try:
    record = await repo.get_by_hash(hashed)
except Exception as exc:
    if not _table_missing(exc):
        raise
    record = None

if record:
    ...

if api_key in settings.dev_api_keys:
    return None, None, "enterprise", True
```

**After:**

```python
try:
    record = await repo.get_by_hash(hashed)
except Exception as exc:
    failure = classify_auth_lookup_failure(exc)
    logger.error(
        "api key lookup failed",
        extra={"auth_failure_kind": failure.kind, "sqlstate": failure.sqlstate},
        exc_info=True,
    )
    if failure.sqlstate == "42P01":
        raise HTTPException(status_code=500, detail="api key store unavailable") from exc
    raise

if api_key in settings.dev_api_keys and settings.auth_enabled:
    return None, None, "enterprise", True
```

**Done when:**

- A missing `api_keys` table no longer falls through to dev-key success when auth is enabled.
- Auth lookup failures are classified in a way that distinguishes at least `table_missing`, `lookup_failed`, and `telemetry_failed`.
- PostgreSQL-backed failures use SQLSTATE-aware classification such as `42P01` (`undefined_table`) and `25P02` (`in_failed_sql_transaction`) before any message-text fallback.
- Invalid API keys still return `403` when the auth store is healthy.

---

### ATI-002: Make API-key authentication a pure query

**Trace:** F2
**Priority:** P0

Authentication currently performs a read and a write inside the same helper. The authentication decision must become a pure query so request correctness does not depend on `last_used_at` bookkeeping.

**Before** (`apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_lookup_api_key`):

```python
if record:
    with suppress(Exception):
        await repo.touch(record)
    return str(record.tenant_id), str(record.id), record.rate_limit_tier, False
```

**After:**

```python
if not record:
    raise HTTPException(status_code=403, detail="invalid or missing API key")

return AuthLookupResult(
    tenant_id=str(record.tenant_id),
    api_key_id=str(record.id),
    rate_limit_tier=record.rate_limit_tier,
    is_admin=False,
)
```

**Done when:**

- The lookup function no longer calls `repo.touch(...)`.
- Auth success depends only on lookup state, not on a subsequent `flush()`.
- A dedicated telemetry path exists for `last_used_at` updates.

---

### ATI-003: Contain auth DB work with a nested transaction boundary inside the request session

**Trace:** F1, F2, F4
**Priority:** P0

The shared `AsyncSession` used by `require_auth()` and route business logic must gain a structural containment boundary so auth-side failures do not leave the outer request transaction in a failed state. The default direction is a nested transaction around the auth DB work because the stack already demonstrates `begin_nested()` support in test fixtures. Exception suppression inside the nested block is explicitly out of bounds: the savepoint rollback only happens if the exception reaches the `begin_nested()` context-manager boundary.

**Before** (`apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_lookup_api_key` plus `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py::get_optional_session`):

```python
record = await repo.get_by_hash(hashed)
...
yield session
await session.commit()
```

**After:**

```python
try:
    async with session.begin_nested():
        record = await repo.get_by_hash(hashed)
        lookup = build_auth_lookup_result(record)
except Exception as exc:
    failure = classify_auth_lookup_failure(exc)
    raise translate_auth_lookup_failure(failure, exc) from exc

return lookup
```

**Done when:**

- A database failure during auth lookup or auth-side telemetry does not cause the first downstream business query to fail with `25P02`.
- The containment boundary is enforced by one shared helper rather than ad hoc `try`/`except` blocks at each call site.
- No `suppress(Exception)`, bare `except`, or equivalent in-block swallowing is allowed inside the `begin_nested()` block.
- A regression test proves that auth-side SQL failure does not poison the outer request transaction.

**Verification approach:**

- Force a SQL failure inside the auth savepoint boundary, then verify the outer request session still executes a normal query or downstream route path after the nested rollback completes.
- Assert that the first downstream business query does not fail with `25P02`; the failure must surface at the auth boundary instead.
- Keep the proof at the package level by using the existing nested-transaction-capable test fixtures instead of manual database inspection.

---

### ATI-004: Make telemetry execution explicit and non-blocking to auth correctness

**Trace:** F2, F4
**Priority:** P1

Once authentication is a pure query and containment exists, `touch()` must run through an explicit execution path with documented failure semantics. This spec chooses FastAPI `BackgroundTasks` with a dedicated session opened inside the background task. Synchronous telemetry inside the request session is rejected for this work because it adds avoidable serial latency to every authenticated request and keeps telemetry coupled to the request transaction.

**Before** (`apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py::_lookup_api_key`):

```python
with suppress(Exception):
    await repo.touch(record)
```

**After:**

```python
background_tasks.add_task(
    record_api_key_use,
    api_key_id=lookup.api_key_id,
    session_factory=async_session_factory,
)
```

**Done when:**

- The telemetry path is post-response background execution via `BackgroundTasks`, not a synchronous write in the request session.
- The background task opens its own short-lived session or unit of work rather than reusing the request-scoped session.
- A telemetry failure does not change the auth outcome returned to the caller.
- The chosen path has a regression test that forces telemetry failure without breaking request auth.

---

### ATI-005: Keep the dedicated auth-session boundary behind a narrow ADR gate

**Trace:** F1, F4
**Priority:** P2

The dedicated auth-session or connection boundary remains a valid alternative, but it should not expand scope unless planning review finds that the nested-transaction design cannot satisfy correctness or ownership rules. This keeps the ADR gate narrow and prevents premature architecture churn.

**Before:**

```python
# No explicit fallback decision exists between nested savepoints and a
# dedicated auth session boundary.
```

**After:**

```python
# Default implementation direction: shared request session + begin_nested().
# Trigger ADR only if planning review rejects that path or if proof commands
# show it cannot prevent transaction poisoning.
```

**Done when:**

- No ADR is created unless planning review identifies a concrete blocker to ATI-003.
- If an ADR is required, it compares only two options: shared-session savepoint containment and a dedicated auth-session boundary.
- Task plans are not created for the dedicated-session path without that ADR.

---

## Implementation Tiers

### Tier 1 — Ready to implement

Task plan: [docs/tasks/15.0/E15-8-auth-transaction-isolation-core-task-plan.md](../tasks/15.0/E15-8-auth-transaction-isolation-core-task-plan.md)

```text
ATI-001  Classify auth failures and fail fast on schema faults     Narrow auth-path hardening
ATI-002  Make authentication a pure query                          Removes telemetry from correctness path
ATI-003  Add nested transaction containment around auth DB work    Primary regression fix
```

Dependency notes: ATI-001 and ATI-002 can be prepared together because they both change `auth.py::_lookup_api_key`. ATI-003 depends on the resulting pure-query surface and should land in the same implementation slice or immediately after it.

### Tier 2 — Ready after Tier 1

Task plan: [docs/tasks/15.0/E15-9-api-key-usage-telemetry-deferral-task-plan.md](../tasks/15.0/E15-9-api-key-usage-telemetry-deferral-task-plan.md)

```text
ATI-004  Choose and wire the telemetry execution path              Depends on ATI-002 and ATI-003
```

Tier 2 depends on Tier 1 because the telemetry path cannot be specified honestly until auth lookup is pure and containment semantics are defined.

### Tier 3 — Blocked on ADR

Design task: `to be created if needed`
ADR: `to be created only if ATI-003 is rejected in planning review`

```text
ATI-005  Dedicated auth-session boundary alternative               Blocked unless Tier 1 proof or review rejects savepoint containment
```

The ADR must resolve whether a dedicated auth-session or connection boundary provides materially better correctness or ownership than a shared-session savepoint boundary.

---

## Spec-Review Gate

No implementation tasks may be created from this spec until:

1. The spec has been reviewed with findings recorded in MCP.
2. All review findings are resolved as fixed, deferred with rationale, or wontfix.
3. Validation snippets have been verified against the current package.

For ATI-005, the review gate applies to the ADR as well; no dedicated-session implementation task may be created until the ADR is reviewed and the spec is updated.

---

## Validation

Validation snippets verified on 2026-04-11 against the current package surface: the referenced API test files exist under `apps/prototype-description-service/recognition/tests/api/`, and the commands below match the package layout and repo Python invocation rules.

### Tier 1 validation

```bash
# --- ATI-001 / ATI-002 / ATI-003: auth lookup semantics and request auth surface ---
cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_authentication.py -q

# --- ATI-003: downstream routes that patch auth lookup continue to pass with the new auth boundary ---
cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_retention_api.py -q
```

### Tier 2 validation

```bash
# --- ATI-004: telemetry path remains non-blocking to auth correctness ---
cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/api/test_authentication.py -q
```
