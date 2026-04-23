# Scope: E15-3a-BR-21 — Clustering-jobs write-path stability (breaker + bulkhead + fail-fast)

> **Metadata**
>
> - **Date**: 2026-04-23
> - **Owning task**: [E15-3a](../tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md) — finding `E15-3a-BR-21`
> - **Backing assessment**: [`docs/assessments/e15-3a-br21-clustering-insert-statement-timeout-2026-04-23.md`](../assessments/e15-3a-br21-clustering-insert-statement-timeout-2026-04-23.md)
> - **Prior precedent**: [`docs/assessments/infailed-sql-transaction-investigation-2026-04-09.md`](../assessments/infailed-sql-transaction-investigation-2026-04-09.md) (deferred the stability layer this scope closes)
> - **Target branch**: `feature/e15-3a` (couples the fix to the Slice 2 roundtrip gate)
> - **Intake decision**: MCP id `2261` — `e15_3a_br21_scope_intake_recorded`
> - **Revision**: 2026-04-23 v2 — planning-review findings `E15-3a-PLAN-01..03` addressed in-place.

## Intake summary

Three intake questions + one constraint question were answered before this note was drafted. User selections:

| Dimension | Answer |
|---|---|
| MVP layers | **C** (breaker + bulkhead + asyncio session-ownership audit). A (operator unblock) is no-code prerequisite; B and D fold in as supporting dependencies of the C slice family. |
| Branch | `feature/e15-3a`. |
| Fail-fast variant | **Belt-and-braces.** `pg_locks` pre-flight probe **and** bounded `SET LOCAL statement_timeout` on the tenants `SELECT ... FOR UPDATE`. |
| Regression-test fidelity | **Both** unit (breaker state machine) **and** integration (real Postgres fixture with a blocker transaction, asserting fail-fast `< 1 s`). |

This is not a one-slice fix. The scope note sequences five slices that close BR-21 *and* the 2026-04-09 deferred stability work in one pass.

## Planning-review adjustments (v2)

Three high-severity planning findings were filed against the initial scope. All three are structural; they are resolved by collapsing the original S4+S5 into a unified clustering-dedicated session boundary and by reframing the latency SLO as backend-measured with a narrow plugin-proxy follow-on.

- **PLAN-01 (S4 atomicity).** The original S4 moved only the write to a dedicated engine, which would have severed the `SELECT ... FOR UPDATE` / INSERT atomicity. **Resolution:** bulkhead at the **route boundary**, not the query boundary. A new `get_clustering_session()` dependency yields sessions bound to a dedicated `clustering_engine`; the whole `POST /recognition/clustering/jobs` handler — lock, lookup, INSERT — runs on that session. Atomicity is preserved; pool isolation is still achieved.
- **PLAN-02 (cross-repo retry).** The original `< 1 s` *end-to-end* LocalWP budget is unattainable while the WP mutation proxy (`class-recognition-proxy-policy.php:51-52`, `class-abstract-recognition-proxy-controller.php:118-119`) retries any `status >= 500` three times with exponential backoff and ignores `Retry-After`. **Resolution:** restate the primary SLO as **backend-measured** (FastAPI entry → 503 emission, `< 1 s`), and add a new slice **S5** that narrows the plugin's mutation-proxy retry policy to exclude fast `503 Retry-After` responses (still retries on `502`/`504` and transport errors). The LocalWP end-to-end latency is observed in the run log but does not gate merge.
- **PLAN-03 (S5 session ownership).** The original S5 proposed converting `get_session()` itself — a shared dependency used by many routers — while also claiming scope was limited to clustering+tenants. **Resolution:** collapse the session-ownership work into the new `get_clustering_session()` introduced by S4. `get_session()` keeps its current semantics for every other route; only the clustering route graduates to endpoint-owned `async with session.begin():` on the dedicated dependency. Broader session-ownership audits across the rest of the codebase are explicitly a follow-on task.

## MVP scope

The MVP delivers a clustering-jobs write path whose worst-case **backend-measured** latency under a zombie lock-holder is `< 1 s`, with the pool-level fault isolation and diagnostic surface needed to prevent BR-21 from recurring silently.

Concretely:

- **Admission-side fail-fast.** `POST /recognition/clustering/jobs` refuses to enter a transaction when a conflicting `pg_locks` row is present against `tenants` or `identity_clustering_jobs`, returning `503 Service Unavailable` with `Retry-After: 5`.
- **Bounded lock-wait.** The `SELECT ... FOR UPDATE` on the tenants row (`clusters.py:209`) is wrapped in `SET LOCAL statement_timeout='1s'`; the 10 s cliff becomes a 1 s fail-fast.
- **Circuit breaker.** N (3) consecutive `QueryCanceledError`s within a 30 s rolling window open a breaker for 30 s; requests during the open window return `503` in `< 10 ms` without touching the DB.
- **Route-boundary bulkhead + owned transaction.** A new `get_clustering_session()` FastAPI dependency yields sessions bound to a dedicated `clustering_engine` (`pool_size=2, max_overflow=1`). The clustering-jobs handler wraps its whole unit-of-work in `async with session.begin():` so the `SELECT ... FOR UPDATE`, the active-job lookup, and the INSERT all run inside one atomic transaction on one bulkheaded connection with asyncio-cancellation-safe `ROLLBACK`. `get_session()` is **not** modified.
- **Plugin proxy policy.** The WP mutation-proxy retry loop is narrowed so a backend `503` with a `Retry-After` header is surfaced to the caller immediately instead of being retried three times. `502`/`504` and transport errors continue to retry under the existing mutation policy.
- **Observability.** Every session checkout logs both `X-Request-ID` (correlation id) and `pg_backend_pid()` so a future incident can be joined to a Postgres `pg_stat_activity` row in one query.

## Slice sequence

| # | Slice | Rough size | Unblocks |
|---|---|---|---|
| S1 | Observability: correlation_id + `pg_backend_pid()` logging on session checkout + `/metrics` histogram on clustering-jobs admission latency. | S | Diagnostic floor for the rest of the work. |
| S2 | Fail-fast admission: `pg_locks` pre-flight probe + `SET LOCAL statement_timeout='1s'` on the tenants `SELECT ... FOR UPDATE`. | S | E15-3a **Slice 2** backend-side roundtrip gate; minimum to turn BR-21 into a fast backend 503. |
| S3 | Circuit breaker around the clustering-jobs write path with the N-failures-in-window open policy. | M | Pool-level protection from convoy; preempts the cascading failure Nygard §4.3 describes. |
| S4 | Clustering-dedicated session + route-boundary bulkhead: new `get_clustering_session()` FastAPI dep bound to a dedicated `AsyncEngine` (`pool_size=2, max_overflow=1`); handler uses `async with session.begin():`. Combines former S4 bulkhead with PLAN-01/PLAN-03 atomicity and ownership fixes. | M | Pool isolation for `/recognition/analyze` / `/health/detailed`; asyncio cancellation-safe ROLLBACK on clustering writes. Closes the 2026-04-09 deferred remediation scoped to clustering. |
| S5 | WP mutation-proxy policy: treat backend `503` with `Retry-After` as non-retryable in `class-abstract-recognition-proxy-controller.php`; keep retry behavior for `502`/`504` and transport errors. | S | End-to-end LocalWP latency honors the backend contract; fixes PLAN-02. |

E15-3a's Slice 2 backend roundtrip gate unblocks after **S1 + S2** land. S3–S4 close the pool-side stability gap; S5 closes the proxy-side contract mismatch. The whole sequence ships on `feature/e15-3a`.

## Success criteria

1. A pytest integration test spins up Postgres, opens a blocker transaction holding `SELECT ... FOR UPDATE` on a test tenant, and asserts `POST /recognition/clustering/jobs` for that tenant returns `503` in `< 1,000 ms` **measured at the FastAPI layer** (request entry → response emission). LocalWP end-to-end latency is observed but not gated.
2. A pytest unit test exercises the circuit breaker state machine: three consecutive `QueryCanceledError`s transition to `open`; the next call returns `503` in `< 10 ms` without calling the repository; after the cooldown window, the breaker transitions to `half_open` and admits a single trial request.
3. A pytest integration test asserts the clustering-writes pool is a distinct `AsyncEngine` from the business pool (`engine is not clustering_engine`) and that exhausting the clustering pool does not block a concurrent `/health/detailed` request. Additionally: `POST /recognition/clustering/jobs` completes a full `SELECT ... FOR UPDATE` → lookup → INSERT cycle inside one transaction on one connection from the clustering pool (no cross-connection hand-off).
4. A PHPUnit test against `class-abstract-recognition-proxy-controller.php` asserts that a mocked backend response of `503 Retry-After: 5` is surfaced to the WP caller on the first attempt without the 3× retry loop; `502` and `504` continue to retry.
5. The Slice 2 roundtrip gate in `docs/tasks/15.0/E15-3a-localwp-oci-run-log.md` captures a green clustering-jobs round trip from LocalWP with the plugin UI showing real cluster suggestions (not "No suggestions to review").
6. Every clustering-jobs request's structured log record contains both `correlation_id` and `pg_backend_pid`; a deliberate post-mortem can join them in one query.
7. `handoff_close_check(enforce=True)` passes on `feature/e15-3a` with zero open findings — including BR-21 and `E15-3a-PLAN-01..03` marked `fixed` with `verified_commit_sha` pointing at the merge commit of the final slice.

## Not-doing

- **Do not widen `statement_timeout`** from 10 s globally. It is Nygard's fault-isolation boundary working as designed; widening it reintroduces the 2026-04-09 failure mode.
- **Do not remove the `SELECT ... FOR UPDATE`** on tenants. The idempotent-clustering-job guarantee depends on it; we bound the wait, we don't remove the lock.
- **Do not replace asyncpg** or change the driver. asyncpg is correct; the gap is in the layers above.
- **Do not refactor `/recognition/analyze`**. BR-21 is the clustering-jobs write path specifically. The bulkhead protects `/analyze` but does not touch its code.
- **Do not modify `get_session()`** or any non-clustering router's session lifecycle. The new `get_clustering_session()` is additive. A cross-cutting `get_session()` audit is explicitly a follow-on task, not in this scope.
- **Do not build a global circuit-breaker registry** (cross-endpoint). BR-21 scope is the clustering-jobs write path only; extending the breaker to all write endpoints is a follow-on task.
- **Do not gate merge on a new operational runbook.** The diagnostic SQL already lives in §6 of the backing assessment.
- **Do not overhaul the plugin mutation-proxy retry engine.** S5 is a targeted policy change for `503 Retry-After` only; global retry-policy redesign is out of scope.
- **Do not gate merge on LocalWP end-to-end latency.** The `< 1 s` SLO is backend-measured. Observed LocalWP latency goes into the run log as evidence; any excess attributable to proxy/PHP overhead is a separate finding, not a merge blocker.

## Assumptions

- The operator playbook (assessment §6) is executed once before S1 lands; this clears the current zombie lock-holder so the feature branch can run tests against a healthy DB.
- The Postgres backend has `pg_stat_activity` and `pg_locks` available to the `acx_app` role. (Verified by the 2026-04-09 assessment artifacts.)
- The current `pool_size=_settings.pool_size` value is large enough that a 2-slot bulkhead carveout does not starve the main pool. If it is not, S4 must also bump `pool_size`; that sub-decision will be recorded on the S4 slice.
- The breaker's open-duration (30 s) and threshold (3 failures / 30 s window) are reasonable defaults; they are configurable via `db/settings.py` and tuning is a post-merge operation, not a merge blocker.
- The WP mutation proxy can distinguish `503` with a `Retry-After` from a `503` without one via the existing `wp_remote_retrieve_header()` call chain; no new plugin infrastructure is needed for S5.

## Review readiness

- A short task plan following this scope note will sequence S1–S5 with named MCP test commands and a Consolidated Checklist (per the task-plan template).
- Each slice lands with its own `slice_complete_*` MCP decision, an updated `DASHBOARD.txt`, and test evidence tied to the HEAD SHA of that slice.
- Pre-merge gate: `handoff_close_check(enforce=True)` passes on `feature/e15-3a` after the final slice; BR-21 and `E15-3a-PLAN-01..03` are the last open findings closed.

## Handoff

This scope note is the intake record for the BR-21 implementation plan. Next action: draft `docs/tasks/15.0/E15-3a-br21-clustering-stability-task-plan.md` from this scope and submit it to `/planning-review` before the first slice begins. The assessment and this scope note v2 are the authoritative inputs; no additional scoping rounds are needed.
