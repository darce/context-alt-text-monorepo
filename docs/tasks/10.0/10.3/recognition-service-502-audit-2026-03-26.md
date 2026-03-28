# Recognition Service 502 Audit

**Date:** 2026-03-26
**Scope:** Recognition backend service failure path behind WordPress `502` responses after scan/clustering completion
**Primary question:** What do the reported `502` responses actually point to, and what backend fractures make them likely?

---

## Executive Summary

The `502` responses are not pointing to a single bad cluster or a missing-label bug. The strongest concrete backend signal is **database connection pool exhaustion in the recognition service**.

Rotated backend logs show repeated unhandled `sqlalchemy.exc.TimeoutError` failures:

- `QueuePool limit of size 10 overflow 5 reached, connection timed out, timeout 30.00`
- failures originate in `recognition/interface_adapters/http/deps/session.py`
- the crash point is session acquisition and tenant-context setup in `db/tenant_context.py`

That means the failing requests are dying **before** or **during** FastAPI dependency setup, not because a specific route reached a business-logic exception.

There is also a second, separate product fracture: the backend suggestion backfill pipeline intentionally skips surfacing suggestions when there are no confirmed labeled clusters yet. That explains why the UI can legitimately show `No suggestions to review yet.` even after clustering succeeds on a greenfield dataset.

So the current user-visible symptom is a compound failure:

1. Some requests are genuinely failing because the backend cannot acquire DB connections quickly enough.
2. Other routes degrade into empty responses or no-op behavior.
3. Suggestion generation itself is bootstrapping-hostile when there are zero confirmed labels.
4. The WordPress proxy/UI path collapses several very different states into the same empty-state presentation.

---

## Evidence Trail

### Backend log evidence

`apps/prototype-description-service/logs/recognition.log.1` contains repeated failures around `2026-03-26 12:11` through `12:13`:

- `QueuePool limit of size 10 overflow 5 reached, connection timed out, timeout 30.00`
- stack traces go through:
  - `recognition.interface_adapters.http.deps.session.get_session()`
  - `recognition.interface_adapters.http.deps.session.get_optional_session()`
  - `db.tenant_context.set_tenant_context()`
  - `session.execute("RESET app.bypass_rls")`
  - FastAPI dependency resolution
  - `recognition.interface_adapters.http.exception_handlers.generic_exception_handler()`

This is the strongest direct evidence for the 5xx path.

### Pool configuration evidence

`apps/prototype-description-service/db/settings.py` sets default DB pool limits to:

- `DB_POOL_SIZE=10`
- `DB_MAX_OVERFLOW=5`
- `DB_POOL_TIMEOUT=30`

`apps/prototype-description-service/db/session.py` applies those limits to the shared async engine used by the HTTP service.

### Error payload evidence

`apps/prototype-description-service/recognition/interface_adapters/http/exception_handlers.py` currently returns raw exception details from `generic_exception_handler()`:

- `error: exc.__class__.__name__`
- `message: str(exc)`
- `path`
- `trace_id`

For pool-exhaustion failures, that means 500 responses can expose the full `QueuePool limit of size 10 overflow 5 reached...` message, including internal pool sizing and timeout configuration.

### Suggestion backfill evidence

`apps/prototype-description-service/logs/scan_worker.log` shows:

- `[suggestions] backfill skipped tenant_id=... reason=no_confirmed candidates=525 fallback_recovered=0`

The code path in `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py` confirms this behavior:

- `backfill_for_new_unlabeled_clusters()` returns early when `get_confirmed_labeled(tenant_id)` is empty
- this is not an error path; it is current intended logic

---

## Findings

### F1. The most likely source of the `502`s is backend DB pool exhaustion, not cluster-specific corruption

**Severity:** Critical

**Why it matters:** This is the backend failure that best matches the browser console symptoms.

**What the code shows:**

- `db/session.py` creates a shared async SQLAlchemy engine with a pool capped at `10 + 5 overflow`.
- `deps/session.py` makes most request paths pay for a DB checkout before useful work starts.
- `tenant_context.py` immediately issues SQL statements to set/reset tenant-scoped RLS variables on that checked-out connection.

**What the logs show:**

- requests are timing out waiting for a pool checkout
- failures are happening while dependencies are being solved, before the route logic can safely degrade

**What this means operationally:**

- WordPress may report these as `502` because its proxy sees an upstream 500-class failure or retry exhaustion.
- The backend service itself is returning generic 500s from the FastAPI exception handler, not a domain-specific error.

---

### F2. “Optional session” routes still require a real connection just to discover whether the database is healthy

**Severity:** High

**Why it matters:** Several read paths look tolerant on paper, but are still fragile under pool stress.

**What the code shows:**

- `get_optional_session()` does `SELECT 1` before yielding a usable session.
- when a tenant is present, it also calls `set_tenant_context()`.
- `get_job_status()` in `routers/analyze.py` then attempts additional tenant setup again when a DB session exists.

**Fracture:**

The code treats “optional session” as a best-effort dependency, but the best-effort probe itself still performs connection acquisition and DB work. Under saturation, that probe becomes one more thing that fails.

For job polling specifically, the duplication is stronger than the original audit stated:

- `get_optional_session()` already does `SELECT 1`, `RESET app.bypass_rls`, and `SET LOCAL app.current_tenant`
- `get_job_status()` then repeats tenant-oriented work via `ensure_tenant_exists()` and `set_tenant_context()`

So the hottest polling path is not just “doing some extra work”; it is redoing tenant setup on top of an already tenant-aware dependency.

**Impact:**

- status polling
- media identity reads
- persisted job lookups

all remain exposed to DB pool pressure, even on routes that conceptually should be lightweight read/status operations.

---

### F3. The post-scan workload shape is pool-hostile

**Severity:** High

**Why it matters:** The failures happen immediately after large scans, which is when the system does the most follow-on work.

**Pressure sources visible in code:**

- the UI polls `/jobs/{job_id}`
- the UI asks for suggestions and media identities
- clustering routes and follow-on helpers can create fresh sessions in background tasks
- `run_background_surface_suggestions()` opens multiple fresh sessions per chunk
- request-scoped and background work both use the same shared HTTP-side session factory in some flows

Those background surfacing tasks are not unbounded: `run_background_surface_suggestions()` is wrapped in `asyncio.timeout(30)`. That does limit individual task duration, but the cap still matches the default `DB_POOL_TIMEOUT=30`, which means a single saturated background task can overlap almost perfectly with the full request-side wait window.

**Relevant code:**

- `recognition/application/tasks/clustering.py`
- `recognition/interface_adapters/http/routers/clusters.py`
- `recognition/application/tasks/scan.py`

**Assessment:**

Even if nothing is leaking, the service is shaped to spike connection demand right after the exact user action that triggers heavy scan/clustering work. With a pool of `15` max logical slots, it does not have much headroom for bursts.

This is best understood as a queueing and tail-latency problem, not a simple “slow query” problem. Once the system approaches capacity, queue wait dominates the user-observed response time and the slowest requests determine what the user experiences.

---

### F4. Suggestion generation is intentionally empty for greenfield tenants with no confirmed labels

**Severity:** High

**Why it matters:** This explains the “no suggestions” half of the symptom even when clustering itself worked.

**What the code shows:**

`SuggestionRefreshService.backfill_for_new_unlabeled_clusters()` exits early when:

- there are candidate unlabeled clusters, but
- `confirmed_clusters = get_confirmed_labeled(tenant_id)` returns empty

The exact log reason is `reason=no_confirmed`.

The important nuance is that “confirmed labeled” is stricter than “cluster exists and a user touched it.” The underlying confirmed-label query excludes synthetic `cluster-*` labels, so the pipeline only bootstraps once a user explicitly renames at least one cluster. Other curation actions by themselves do not seed the suggestion path.

**Impact:**

On a greenfield corpus, the system can create hundreds of clusters and still generate zero review suggestions until a user first confirms or labels some seed clusters.

**Why this is a fracture:**

The backend behavior is consistent with the code, but inconsistent with the product expectation suggested by the UI copy. The system looks “ready for review” while the backend still has no seed labels to compare against.

---

### F5. The service has observability for pool pressure, but it is not part of the operational path that needs it

**Severity:** Medium

**Why it matters:** The backend already has the beginnings of the right diagnostic surface, but it is not wired into the failure experience.

**What the code shows:**

- `db/session.py` exposes `get_pool_stats()`
- `recognition/interface_adapters/http/routers/health.py` exposes `/health/pool`
- `recognition/interface_adapters/http/exception_handlers.py` returns raw exception details in generic 500 responses

**Fracture:**

- the pool metrics are not surfaced in the WordPress admin flow
- they are not attached to failure responses
- they are not used to degrade or shed load before generic 500s happen
- the raw 500 payload is informative in the least safe way: it leaks implementation details instead of surfacing structured operator guidance

**Result:**

Operators see `502`, `No suggestions`, and `Loading media...` instead of “database pool saturated.”

---

### F6. The WordPress/plugin layer can turn backend failures into false empty-state narratives

**Severity:** Medium

**Why it matters:** This is not the backend root cause, but it explains why the failure is hard to interpret from the UI.

**What the code shows:**

- `class-abstract-recognition-proxy-controller.php` forwards 500-class upstream responses and can also emit its own `502 proxy_failed`
- the `post_scan_read` policy already used by suggestions/media/name-suggestion reads prefers a `10s` timeout, `1` attempt, and no circuit breaker
- `class-suggestions-controller.php` degrades proxy failures into empty suggestion envelopes
- `class-media-identities-controller.php` can degrade unavailable backend reads into empty identity results

**Effect:**

A saturated backend can manifest as:

- direct `502` responses for some routes
- empty `200` payloads for others

The `post_scan_read` policy is useful because it avoids retry storms and circuit-breaker churn after scans, but it also means backend pool failures can be converted into empty success payloads quickly and consistently. That reduces blast radius while increasing the risk of masked backend failure.

---

## Likely Failure Chain

The most plausible end-to-end runtime sequence is:

1. A large scan/clustering run completes or reaches late-stage processing.
2. Follow-on reads and background work increase DB pressure.
3. The recognition HTTP service exhausts its SQLAlchemy pool.
4. FastAPI dependencies fail while trying to acquire a session and set tenant context.
5. The backend emits generic 500 responses.
6. WordPress surfaces some of those as `502`, while other plugin routes degrade into empty success payloads.
7. Independently, suggestion backfill still returns nothing because the tenant has no confirmed labeled clusters yet.

This combined chain matches the user’s reported mix of:

- `502`
- `404` on stale/local-only mutation paths
- `No suggestions to review yet.`
- `No identities detected yet.`
- media reload hangs/timeouts

---

## Remediation Options

### Immediate containment

1. Increase backend pool headroom for dev/test runs that process large batches.
2. Add explicit logging of pool utilization before and after high-fanout post-scan tasks.
3. Return `503 database_unavailable` for session-acquisition failures instead of generic 500 where possible.
4. Instrument latency as a distribution, not a single average: track at least p50/p95/p99 for total request time, DB pool wait, queue wait, and handler time separately.
5. Treat timeouts as ambiguous signals, not proof that the backend definitively failed. A timed-out request may still be queued, executing, or even eventually succeed upstream.
6. Add producer-side throttling/backoff for the hot paths that create this incident shape: job polling, sync triggers, and post-scan fan-out reads.

### Structural fixes

1. Split lightweight status endpoints from tenant-aware DB dependencies so `/jobs/{job_id}` can answer from memory or a cheaper persistence path without full tenant-context setup.
2. Remove duplicate tenant-context work in request paths that already passed through `get_optional_session()`, especially `get_job_status()`.
3. Move background surfacing/backfill work off the HTTP engine pool or onto a dedicated worker/session factory.
4. Add load-shedding or bounded concurrency for post-scan suggestion/backfill tasks.
5. Surface `/health/pool` or equivalent diagnostics in the admin/debug UI so saturation is visible when it happens.
6. Mask internal pool topology in generic 500 responses while preserving trace IDs for operators.
7. Prefer adaptive or experimentally tuned timeouts over static intuition-based timeout values on the hottest distributed paths.

### Product-contract fixes

1. Rework suggestion bootstrapping so a greenfield tenant can still get useful first-pass review items without prior confirmed labels.
2. Stop treating backend unavailability as empty suggestions/identities in user-facing review flows when that changes meaning materially.
3. Keep “projection/backend unavailable” distinct from “no review items exist” all the way to the UI.

Items 2 and 3 are already partially addressed by recent work:

- `D777` added `data_source: backend_proxy | unavailable` distinctions on the read paths that were previously collapsing into empty local data
- `D780` added `projection_not_ready` (`409`) for local-only mutations so projection lag is no longer misreported as a missing cluster

The remaining gap is narrower but still important: some read controllers still turn backend 500s into empty `200` payloads through `is_proxy_unavailable()`, so pool exhaustion can still masquerade as “no suggestions” or “no identities.”

---

## Literature Implications

The literature reviewed for this second pass reinforces that this incident is fundamentally about queueing, ambiguity, and overload control rather than just “make the timeout bigger.”

### DDIA: timeouts do not tell you what happened

Kleppmann’s discussion of partial failures and unbounded delays is directly applicable here: when a timeout occurs, the caller still does not know whether the remote side never received the request, is merely slow, or processed it after the caller gave up waiting. That matters for this stack because:

- the WordPress proxy currently turns some backend timeouts/500s into empty `200` payloads
- the UI can then treat “unknown outcome” as “no data exists”
- retrying blindly risks compounding load on the already saturated path

Design implication for this repo: follow-up fixes should prefer explicit “backend unavailable / result unknown” semantics over silent empty-state degradation when the underlying request timed out or failed upstream.

### DDIA + Enberg: queueing dominates tail latency near saturation

Both texts emphasize that once a system approaches capacity, queue wait becomes a large part of response time and averages stop being useful. That maps closely to the observed pool starvation:

- request time is dominated by waiting for DB connections, not just handler logic
- parallel fan-out increases the chance that one slow stage drags the entire user-visible flow
- the slowest requests matter most because they control what the operator sees during incidents

Design implication for this repo: any implementation plan should measure and alert on staged latency distributions, especially:

- pool checkout wait
- request queue wait
- handler execution time
- upstream proxy round-trip

### Enberg: asynchronous systems need backpressure, not just buffering

Enberg’s treatment of asynchronous processing is a good fit for the current architecture: async execution helps until producer rate outruns consumer capacity, at which point concurrency must be bounded. In this incident class, the producers are:

- the UI pollers and retry actions
- the WordPress proxy fan-out reads after scan/clustering
- background suggestion-surfacing work using the same DB-side engine pool

Design implication for this repo: the next implementation plan should include explicit backpressure or producer throttling, not just larger buffers or longer waits. Otherwise the system simply converts overload into longer queues and worse tail latency.

### Enberg: partial failures need per-stage visibility

The literature’s guidance on partial errors also maps well here. This stack often has mixed outcomes in one incident:

- job polling may 502
- suggestions may return empty `200`
- top-unlabeled may be local-only bootstrapping
- mutation routes may return `409 projection_not_ready`

Design implication for this repo: preserve per-stage failure provenance through the stack instead of collapsing it into one empty state or one generic error string.

---

## Contract and Repo Alignment

This audit should be read with the current repo contracts and instructions in mind so any follow-up plan stays implementable and ownership-correct.

### Contract alignment

- Per [clustering-api.md](../../../agentic/contracts/clustering-api.md), `GET /recognition/clusters/top-unlabeled` is a **local-projection-only** WordPress surface. Any proposal to add backend fallback there would be a contract change, not just an implementation tweak.
- Per [clustering-api.md](../../../agentic/contracts/clustering-api.md), suggestions, merge suggestions, name suggestions, and media identities currently use envelopes with `data_source`, and proxy-unavailable behavior is documented as empty `200` with `data_source: "unavailable"`. If we change that behavior, the contract docs must change in the same scope.
- Per [recognition-clustering.md](../../../agentic/contracts/recognition-clustering.md), the backend job-status route remains tenant-scoped. Any optimization of `/recognition/jobs/{job_id}` still needs to preserve correct tenant ownership and RLS semantics.

### Instructions alignment

- Per [instructions.md](../../../agentic/instructions.md), this repo is treated as **greenfield**. Follow-up fixes should therefore prefer clean rewrites of masking or duplicated logic over layering compatibility shims.
- The same instructions require centralized status values and discourage stringly failure semantics. If follow-up work introduces statuses such as `database_unavailable`, `pool_saturated`, or new `data_source` variants, they should be added as canonical enums/constants and documented in the contracts.
- `rg-015` also matters here: boundary adapters must not invent ambiguous metadata. For this incident class, that means error provenance should come from the actual layer that knows it, not from inferred empty envelopes that guess at state.

### Planning implications

Per [planning-review-guide.md](../../../agentic/rules/planning-review-guide.md), any follow-up implementation plan based on this audit should:

- keep current-state claims synchronized with the real code and contracts
- assign failure-handling changes to the correct owner boundary
- avoid backward-compatibility detours that the repo’s greenfield policy does not justify
- define any new status/error semantics in the same scope as the code that will emit them

---

## Refactor Crosswalk

The existing refactoring evaluations already identify several changes that would materially help this incident class. None of them replaces the need to fix pool saturation directly, but several would make the 502 path easier to debug and less brittle.

### Backend refactors that would help most

1. **`analyze_media()` split-phase extraction** from [refactoring-evaluation.md](../../tech-debt/refactoring-evaluation.md)

   The recommendation to split `analyze_media()` into `_prepare_tenant_context()` and `_prepare_media_items()` maps directly to this audit. Right now tenant provisioning, request parsing, queue setup, and background scheduling are interleaved in one long router handler. Splitting those phases would make it much easier to see whether a given failure is:

   - tenant/session setup
   - media request shaping
   - queue creation
   - background handoff

   That would improve both logging and error classification for the 500/502 path.

2. **`TenantContext` value object / tenant threading reduction** from [refactoring-evaluation.md](../../tech-debt/refactoring-evaluation.md)

   The `tenant_id` Shotgun Surgery finding is directly relevant. This audit found tenant context being resolved and applied in multiple places, including repeated `set_tenant_context()` work after session acquisition. A single boundary-owned `TenantContext` object would:

   - reduce duplicate tenant resolution/setup
   - shrink the blast radius of tenant-format changes
   - make it clearer where RLS setup should happen exactly once

   This would not solve pool starvation by itself, but it would remove incidental duplication around the exact failure path seen in the logs.

3. **Replace `AbstractRecognitionProxyController` inheritance with a composed `ProxyPolicy` service** from [refactoring-evaluation.md](../../tech-debt/refactoring-evaluation.md)

   This would help with the false-empty-state problem documented in F6. The current proxy layer mixes circuit breaking, request policy, tenant resolution, and fallback behavior inside a shared inheritance layer. A composed `ProxyPolicy` service would make per-route failure handling easier to reason about and test, especially for:

   - when to return a hard failure
   - when to degrade to empty data
   - when to surface “backend unavailable” explicitly

### Frontend refactors that would improve diagnosis

1. **Extract `useSyncStatusPresentation()` from `SyncStatusIndicator`** from [refactoring-typescript-evaluation.md](../../tech-debt/refactoring-typescript-evaluation.md)

   This is the most relevant frontend refactor for the audit. The current incident is partly hard to debug because sync/projection/backend state is not represented consistently. A presentation hook would let the workbench reuse one canonical interpretation of:

   - backend unavailable
   - projection pending
   - projection failed
   - no review items

   instead of letting each surface improvise its own empty-state behavior.

2. **Split `jobStateMachineUtils.ts` by concern** from [refactoring-typescript-evaluation.md](../../tech-debt/refactoring-typescript-evaluation.md)

   The recommendation to separate selectors, derivation, and formatting would directly improve debugging of the “completed but empty” state. The current audit depends on distinguishing domain phase from UI wording; separating those concerns would make that much easier to inspect and test.

3. **Extract `useJobProgressStream()` into smaller hooks** from [refactoring-typescript-evaluation.md](../../tech-debt/refactoring-typescript-evaluation.md)

   This would help determine whether the workbench is reacting to:

   - SSE updates
   - polling fallback
   - broadcast coordination
   - stale local state

   During incidents where job state flips between “projecting,” “complete,” and error banners, that separation would reduce the debugging burden considerably.

4. **Centralize status enums / constants** from [refactoring-typescript-evaluation.md](../../tech-debt/refactoring-typescript-evaluation.md)

   This would not fix the backend, but it would make the UI less likely to collapse distinct failure states into the same string-driven branch. For this incident class, centralized status constants would be especially useful around:

   - projection states
   - sync health
   - job terminal states
   - “unavailable” versus “empty” data-source semantics

### Priority assessment

If the goal is to improve this exact incident class, the highest-value refactors from the existing evaluations are:

1. Split `analyze_media()` and related backend request phases.
2. Introduce a single boundary-owned `TenantContext` path.
3. Extract `useSyncStatusPresentation()` and split `jobStateMachineUtils.ts`.
4. Replace proxy-controller inheritance with a composed `ProxyPolicy` service.

These recommendations are worth treating as incident-response hardening, not just general code-health cleanup, because they directly affect the ability to localize, surface, and safely degrade backend failures like the ones behind these 502s.

---

## Bottom Line

The reported `502`s point most directly to **backend database pool starvation during request dependency setup**. That is the hard failure.

The “no suggestions” and “no identities” views are not evidence that the backend found nothing. They are partly explained by:

- degraded empty responses on the WordPress side, and
- a backend suggestion pipeline that intentionally does nothing until confirmed labels exist.

So the right diagnosis is not “one bad endpoint.” It is a stacked reliability problem across:

- connection management
- dependency design
- post-scan workload shape
- greenfield suggestion bootstrapping
- error-to-empty-state translation
