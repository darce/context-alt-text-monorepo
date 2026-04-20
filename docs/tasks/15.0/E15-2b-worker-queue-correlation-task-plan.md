# E15-2b. Worker / Queue Correlation Propagation

> **Metadata**
>
> - **Date**: 2026-04-19
> - **Author**: Claude Opus 4.7
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-2b`
> - **Target Worktree**: `/Users/daniel/Development/context-alt-text-monorepo-e15-2b`
> - **Predecessor**: E15-2 Slice 1 (landed — `88e0dd16`, API-side correlation middleware + logging filter + JSON formatter)
> - **Review Coverage Target**: 1

---

## Objective

Propagate the E15-2 `correlation_id` across the scan-job queue hop so every log line the async worker emits for a queued scan carries the same ID that the enqueueing API request carried. When this is done, an operator grepping `correlation_id=req-<uuid7>` across backend API logs and worker logs returns a single end-to-end trace for one request, even though the work was handed off to a separate async task.

## Problem Statement

E15-2 established one correlation ID per request **within** an API-request lifetime: ASGI middleware extracts or generates `X-Request-ID`, a contextvar binds it to the request scope, a logging filter stamps it on every record, and the response echoes it back. That contract terminates at the moment the request enqueues scan work:

1. **`IdentityScanJobItem` has no correlation column.** Items are persisted with `id / job_id / tenant_id / media_id / media_url / status / attempts / identities_detected / last_error / timestamps` — there is no field to carry the enqueueing request's `correlation_id` across the process boundary (`apps/prototype-description-service/db/models/jobs.py:56-80`).
2. **Worker handlers generate their own throwaway `request_id`.** `ScanItemHandler._process_item` calls `uuid.uuid4()` to tag each worker log line (`apps/prototype-description-service/recognition/worker/handlers/scan.py:49-80`). That ID has no relation to the API request that created the item.
3. **Enqueue path has no hook to forward the ID.** `ScanQueueService.populate_scan_job_items` iterates media entries in a chunk loop and calls `self._repository.enqueue_items` with `(media_id, media_url)` tuples only; neither the service method nor `SqlAlchemyScanQueueRepository.enqueue_items` accepts a correlation_id (`apps/prototype-description-service/recognition/application/scan/scan_queue_service.py:75` (def), `:102-103` (chunk loop calling `enqueue_items`); `apps/prototype-description-service/recognition/infrastructure/repositories/scan_queue_repository.py:74-100`). The enqueue is scheduled via FastAPI `background_tasks.add_task(chain_populate_and_process, ...)` at `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py:216-240`, which runs **after** the response is sent — outside the ASGI request scope where `_correlation_id_var` is bound — so the correlation_id must be captured at request scope and passed as an explicit kwarg into the background task, not re-read from the contextvar inside the worker coroutine.

4. **Worker process initializes logging without a correlation_id surface.** `apps/prototype-description-service/recognition/worker/scan_worker.py::main` calls `logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", ...)`; no `CorrelationIdFilter` is installed, the format string has no `%(correlation_id)s` placeholder, and there is no `python-json-logger` JsonFormatter. Binding `_correlation_id_var` inside `_process_item` therefore surfaces nothing in the emitted log line. The worker must share `configure_logging()` with the API process (same filter + formatter + field contract) before contextvar binding has any observable effect.

The consequence: once a scan is queued, all downstream worker log lines — detector/generator calls, progress updates, failure messages — are un-joinable with the originating API request. Any future end-to-end tracing work (E15-6) depends on this hop being instrumented first.

## Constraints

- Scope is `apps/prototype-description-service/` only. No plugin changes; WP does not yet emit `X-Request-ID` upstream (E15-2 constraint).
- Greenfield schema policy: edit `db/migrations/versions/001_identity_schema.py` directly; no data migration or backfill.
- Correlation propagation crosses a process boundary, so the ID must live in the **payload** (row column), not in shared memory or a contextvar. This is the PR-03 framing from E15-2: "correlation must cross process boundaries as payload, not via contextvars" (Kleppmann, *Designing Data-Intensive Applications*).
- Worker code MUST NOT log the correlation_id under a field name other than `correlation_id` — the JSON log field contract from E15-2 is single-surface.
- No changes to the `X-Request-ID` / response-body / middleware contracts established in E15-2 Slice 1.
- Branch isolation: all code on `feature/e15-2b`.

## Workflow Principles

- One ID, three surfaces, same key: `X-Request-ID` header, `correlation_id` log field, `correlation_id` DB column. No synonym drift.
- The queue row **is** the hand-off contract. If the column cannot be populated at enqueue time (e.g., a legacy call path without a request context), the row is still valid — the column is nullable and the worker falls back to a generated id, logged explicitly as "worker-origin" so the gap is visible in aggregation.
- Do not introduce a new correlation generator in the worker path. The fallback is the one already owned by the middleware (`generate_correlation_id` in `middleware/correlation.py`) — worker imports that same helper so the format (`req-<uuid7>`) is identical whether the id came from the API or from worker fallback.
- Denormalize correlation onto `identity_scan_job_items` (not only onto `identity_scan_jobs`): the worker claim path reads one row per item and logs once per item. Storing the id on each item means the worker log-filter has zero extra queries per log line.

## Terminology

- **Correlation ID (inherited from E15-2)**: `req-<uuid7>` string. Single canonical form across API and worker surfaces.
- **Queue-hop propagation**: the act of persisting the correlation_id onto the scan-job row at enqueue time, then reading it back on the worker claim and binding it to the worker's log context.
- **Worker-origin correlation**: a `correlation_id` generated inside the worker when the claimed row has `correlation_id IS NULL`. Logged with a structured field `correlation_source: CorrelationSource.WORKER` so downstream log aggregation can distinguish inherited IDs from fallback IDs. (API-origin rows emit `correlation_source: CorrelationSource.API`.)
- **`CorrelationSource` enum**: a `StrEnum` defined alongside the existing correlation contextvar in `recognition/interface_adapters/http/middleware/correlation.py`, with members `API = "api"` and `WORKER = "worker"`. All producers (repository persist, worker bind, logger extra) and tests import from this single surface; no code path compares or emits the magic strings `"api"` / `"worker"` directly. Enforces short rule sr-007.

## Target Outcome

An operator investigating a failed scan takes the `correlation_id` returned in the API response for `POST /recognition/analyze` (e.g., `req-01234567-89ab-7cde-8f01-234567890abc`), greps it across all recognition-service logs, and gets:

1. API request line from `CorrelationIdMiddleware` receipt.
2. Enqueue log line from `scan_queue_service.enqueue`.
3. For each scan item the request produced: worker `[worker] START` / `[worker] COMPLETE` / `[worker] FAIL` lines, all tagged with the same `correlation_id`.
4. Any embedding/detector failures raised inside `ScanService.process_media_item`.

All of those records share `correlation_id=req-01234567-89ab-7cde-8f01-234567890abc`. Today, only step 1 is guaranteed.

Worker fallback path (row with `correlation_id IS NULL`, e.g., from a pre-E15-2b enqueue) emits a fresh id with `correlation_source: "worker"` — also greppable, also trace-able, but marked non-inherited.

## Proposed Solution

1. **Schema**: add `correlation_id TEXT` (nullable) + `correlation_source TEXT` (nullable) columns to `identity_scan_job_items`. Edit `001_identity_schema.py` directly (greenfield). Index on `correlation_id` is **not** added in this task — queue rows are short-lived (pending → processing → completed within minutes), grep-across-log-files is the operator path, not DB lookup. A follow-on task can add an index if production log volume makes a DB lookup necessary.
2. **`CorrelationSource` enum**: add `class CorrelationSource(StrEnum): API = "api"; WORKER = "worker"` to `recognition/interface_adapters/http/middleware/correlation.py`. This is the single import surface for every producer/consumer in Slice 1 and Slice 2; magic strings are not permitted (sr-007).
3. **Application repository contract**: change `ScanQueueRepository.enqueue_items` to accept `items: Iterable[tuple[int, str, str | None]]` (media_id, media_url, correlation_id) and persist `correlation_id` + `correlation_source=CorrelationSource.API.value` when the id is non-null; `CorrelationSource.WORKER` is never written at enqueue time.
4. **Scan queue service**: `ScanQueueService.populate_scan_job_items` does **not** read `get_correlation_id()` itself. Instead, it accepts a new `correlation_id: str | None = None` kwarg, and its existing chunk loop (`scan_queue_service.py:102-103`) threads that value through every `self._repository.enqueue_items(...)` call for the request. Reading the contextvar happens at the HTTP layer (step 5), not inside the service, because the background-task scheduling in `analyze.py` runs the service coroutine **after** the ASGI response is sent — outside the request scope where the contextvar is bound.
5. **Call-site capture**: in `recognition/interface_adapters/http/routers/analyze.py` (`chain_populate_and_process` scheduling near `:216-240`), capture `correlation_id = get_correlation_id()` at request scope **before** calling `background_tasks.add_task(chain_populate_and_process, ..., correlation_id=correlation_id)`. The chain coroutine forwards the captured value into `ScanQueueService.populate_scan_job_items(..., correlation_id=correlation_id)`. No direct contextvar read inside the chain.
6. **Worker handler**: `ScanItemHandler._process_item` replaces `request_id = uuid.uuid4()` with:
   - If `item.correlation_id` is non-null → `(correlation_id, correlation_source) = (item.correlation_id, CorrelationSource.API)`.
   - Else → `(generate_correlation_id(), CorrelationSource.WORKER)` (imported from the middleware module).
   - Binds the id to the per-item log scope via the existing `_correlation_id_var` contextvar (set for the duration of the item, reset in a `finally` because the worker is long-lived — unlike the API, where the asyncio task is naturally request-scoped, the worker task processes many items in sequence).
7. **Worker process logging**: `recognition/worker/scan_worker.py::main` replaces `logging.basicConfig(...)` with a call to the shared `configure_logging()` used by the API so the `CorrelationIdFilter` + JsonFormatter contract from E15-2 apply to every worker log line. Without this step, Slice 2's contextvar binding is observable in tests only, not in production logs.
8. **Worker claim path**: `claim_pending_items` / `claim_pending_items_any` return the new `correlation_id` field on `ScanQueueItem`. Add `correlation_id: str | None`, `correlation_source: str | None` to the dataclass.
9. **Fake repository + test doubles**: `recognition/tests/api/conftest.py` and unit-test fakes gain the new columns. `create_scan_job_record` at `analyze.py:216` does not change; only the repository/service signatures change and the new `correlation_id` kwarg is threaded through the background-task chain.

## Out of Scope / Explicit Non-Goals

- **End-to-end WP→backend correlation.** The WP plugin still does not emit `X-Request-ID`; E15-2b does not change that. A plugin task owns the upstream header injection.
- **Clustering queue**: `IdentityClusteringJob` has no per-item table; clustering is job-level and does not cross a queue boundary in the same way. If E15-6 needs clustering-job correlation too, it is a sibling task, not a slice here.
- **Correlation on `identity_scan_jobs` (parent).** Only the per-item table gets the column. The job row is written once from inside the API request; its creation is already covered by the API log line. Adding the column on the parent would duplicate state without adding query/grep value.
- **Index on `correlation_id`.** Deferred (see Proposed Solution #1).
- **Retention / purging of correlation_id.** The field inherits the job row's lifecycle — no separate TTL. If GDPR-style request-id scrubbing becomes a requirement, a later task scopes that.

## Files and Surfaces

| Surface | File | Change |
|---|---|---|
| Schema | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Add `correlation_id`, `correlation_source` TEXT columns on `identity_scan_job_items` |
| Model | `apps/prototype-description-service/db/models/jobs.py` | Add mapped columns on `IdentityScanJobItem` |
| Enum + middleware | `apps/prototype-description-service/recognition/interface_adapters/http/middleware/correlation.py` | Add `CorrelationSource(StrEnum)` with `API="api"` / `WORKER="worker"`; re-export alongside `generate_correlation_id` and `_correlation_id_var` for worker import |
| Domain dataclass | `apps/prototype-description-service/recognition/application/scan/queue_repository.py` | Add `correlation_id: str \| None`, `correlation_source: str \| None` to `ScanQueueItem`; update `ScanQueueRepository.enqueue_items` signature |
| Repository | `apps/prototype-description-service/recognition/infrastructure/repositories/scan_queue_repository.py` | Persist + read the new columns in `enqueue_items`, `claim_pending_items(_postgres\|_generic)`, `claim_pending_items_any` |
| Service | `apps/prototype-description-service/recognition/application/scan/scan_queue_service.py` | Add `correlation_id: str \| None` kwarg to `populate_scan_job_items`; thread through the existing chunk loop (`:102-103`) into every `enqueue_items` call |
| HTTP call-site | `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` | Capture `correlation_id = get_correlation_id()` at request scope before `background_tasks.add_task(chain_populate_and_process, ..., correlation_id=correlation_id)`; chain forwards kwarg into `populate_scan_job_items` |
| Worker process | `apps/prototype-description-service/recognition/worker/scan_worker.py` | Replace `logging.basicConfig(...)` in `main()` with a call to the shared `configure_logging()` so `CorrelationIdFilter` + JsonFormatter apply to every worker log line |
| Worker handler | `apps/prototype-description-service/recognition/worker/handlers/scan.py` | Replace local `uuid.uuid4()` with correlation-aware binding using `CorrelationSource` enum; set `_correlation_id_var`; reset in `finally` |
| Test fakes | `apps/prototype-description-service/recognition/tests/api/conftest.py`, `recognition/tests/unit/test_scan_queue_service.py` | Update fake repository signatures; add correlation_id assertions |
| Tests | `apps/prototype-description-service/recognition/tests/unit/test_scan_queue_correlation.py` (new) | Unit coverage for enqueue propagation + HTTP-layer capture |
| Tests | `apps/prototype-description-service/recognition/tests/unit/test_scan_handler_correlation.py` (new) | Worker handler uses inherited vs fallback ID; logs carry correlation_id; contextvar reset between items |

## Slice Plan

### Slice 1 — Schema + enqueue propagation

**Goal**: The scan-job item row carries a correlation_id column, the API enqueue path reads it from the contextvar and persists it, and the worker claim path returns it. Worker behavior not yet changed — it still generates its own `request_id` — but the row is ready.

**Scope boundary**: No worker-handler log change in this slice. The column exists end-to-end (migration → model → dataclass → enqueue → claim), fakes updated, unit tests assert the value round-trips.

**Changes**:
- Edit `001_identity_schema.py`: add `sa.Column("correlation_id", sa.Text(), nullable=True)` and `sa.Column("correlation_source", sa.Text(), nullable=True)` to `identity_scan_job_items`.
- Add mapped columns to `IdentityScanJobItem`.
- Add `CorrelationSource(StrEnum)` to `middleware/correlation.py` (members: `API="api"`, `WORKER="worker"`). All subsequent producers/consumers import from here.
- Extend `ScanQueueItem` dataclass with `correlation_id: str | None = None`, `correlation_source: str | None = None`.
- Update `ScanQueueRepository.enqueue_items` protocol and `SqlAlchemyScanQueueRepository.enqueue_items` implementation to accept and persist correlation fields; persist `CorrelationSource.API.value` when `correlation_id` is non-null.
- Add `correlation_id: str | None = None` kwarg to `ScanQueueService.populate_scan_job_items`; thread the value through the existing chunk loop at `scan_queue_service.py:102-103` into every `self._repository.enqueue_items(...)` call. The service does **not** read the contextvar itself.
- In `analyze.py`, capture `correlation_id = get_correlation_id()` at request scope and forward it as an explicit kwarg through `background_tasks.add_task(chain_populate_and_process, ..., correlation_id=correlation_id)` into `populate_scan_job_items`.
- Update all claim paths to populate `correlation_id` + `correlation_source` on returned `ScanQueueItem`s.
- Update test fakes in `conftest.py` and `test_scan_queue_service.py`.

**Proof**:
- `test_scan_queue_correlation.py::test_populate_persists_correlation_id_when_kwarg_set` — calling `populate_scan_job_items(..., correlation_id="req-fixed")` persists matching `correlation_id` and `correlation_source=CorrelationSource.API.value` on every item.
- `test_scan_queue_correlation.py::test_populate_without_correlation_leaves_columns_null` — kwarg omitted → row has `correlation_id IS NULL` and `correlation_source IS NULL`.
- `test_scan_queue_correlation.py::test_analyze_router_captures_contextvar_before_background_task` — with `_correlation_id_var` set on the request, the scheduled background task receives the captured id as a kwarg (not re-read from contextvar inside the coroutine).
- `test_scan_queue_correlation.py::test_claim_returns_persisted_correlation_id` — round-trips through `claim_pending_items`.
- Existing `test_scan_queue_service.py` suite stays green.

### Slice 2 — Worker handler correlation binding

**Goal**: Worker log lines carry inherited `correlation_id` when the row has one, or a worker-origin fallback id with `correlation_source: "worker"` when it does not. Both cases flow through the JSON log filter established in E15-2.

**Changes**:
- `recognition/worker/scan_worker.py::main`: replace `logging.basicConfig(...)` with `from api.logging_config import configure_logging; configure_logging()`. This installs the `CorrelationIdFilter` + JsonFormatter from E15-2 so every worker log record gets a `correlation_id` field. Without this, steps below are unobservable in production logs.
- `ScanItemHandler._process_item`:
  - Import `CorrelationSource`, `generate_correlation_id`, `_correlation_id_var` from `recognition.interface_adapters.http.middleware.correlation`.
  - Resolve correlation: `correlation_id, correlation_source = (item.correlation_id, CorrelationSource.API) if item.correlation_id else (generate_correlation_id(), CorrelationSource.WORKER)`.
  - Bind via `token = _correlation_id_var.set(correlation_id)` inside the per-item `async with semaphore` block; `_correlation_id_var.reset(token)` in `finally`. Worker is long-lived so explicit reset is required (unlike the API middleware, where each request runs in its own asyncio task).
  - Remove `request_id = uuid.uuid4()` and the `request_id=%s` placeholders in log messages. The filter now supplies `correlation_id` on every record; the message string becomes `[worker] START scan_item job_id=%s item_id=%s media_id=%s`.
  - Emit `correlation_source` via `extra={"correlation_source": correlation_source.value}` on the START log line.

**Proof**:
- `test_scan_handler_correlation.py::test_worker_inherits_correlation_id_from_item` — processing an item with `correlation_id="req-fixed-value"` emits logs carrying that exact id.
- `test_scan_handler_correlation.py::test_worker_generates_fallback_when_item_has_no_correlation_id` — logs carry a `req-<uuid7>`-format id plus `correlation_source=CorrelationSource.WORKER.value` (`"worker"`).
- `test_scan_handler_correlation.py::test_contextvar_reset_between_items` — after processing item A then item B, the contextvar returns to its pre-call value; A's id does not leak into B's log scope.
- `test_scan_handler_correlation.py::test_worker_main_installs_correlation_logging` — after `main()` bootstraps logging, the root logger's handlers include a `CorrelationIdFilter` (direct `handler.filters` inspection) and emitted records carry a `correlation_id` attribute.
- `pytest recognition/tests/api/test_correlation.py` (existing E15-2 Slice 1 coverage) still green — no regression on API-side contract.

## Verification Strategy

- **TDD**: RED tests first for each slice. Per `docs/agentic/rules/testing-python.md`.
- **Command**: `PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/unit/test_scan_queue_correlation.py recognition/tests/unit/test_scan_handler_correlation.py recognition/tests/unit/test_scan_queue_service.py recognition/tests/api/test_correlation.py -v`
- **Manual smoke**: With worker running locally (`make run-worker` or equivalent), enqueue via `POST /recognition/analyze`, grep logs for the `correlation_id` from the response; expect API enqueue line + one worker line per item, all sharing the id.

## Success Criteria

- `identity_scan_job_items.correlation_id` column exists, populated by API path when contextvar is set.
- Worker log lines for a request all carry the same `correlation_id` as the API response header.
- Fallback path (null column) emits a distinct `correlation_source: "worker"` so operators can distinguish inherited vs locally-generated IDs in aggregation.
- No regression in existing scan-queue or API correlation tests.
- Zero open review findings.
- `handoff_close_check(enforce=True)` green on final branch HEAD.

## Consolidated Checklist

- [x] Slice 1 RED tests land first
- [x] `001_identity_schema.py` updated with two nullable Text columns
- [x] `IdentityScanJobItem` mapped columns added
- [x] `CorrelationSource(StrEnum)` added to `middleware/correlation.py`; no magic strings in producer/consumer code (sr-007)
- [x] `ScanQueueItem` dataclass extended
- [x] `enqueue_items` signature + implementation carry correlation through
- [x] `ScanQueueService.populate_scan_job_items` accepts `correlation_id` kwarg and threads it through the chunk loop
- [x] `analyze.py` captures `get_correlation_id()` at request scope before `background_tasks.add_task` and forwards it as a kwarg
- [x] All claim paths return correlation fields
- [x] Slice 1 test file covers: kwarg-set, kwarg-omitted, HTTP-layer capture, round-trip through claim
- [x] Slice 2 RED tests land first
- [x] `scan_worker.py::main` switched from `logging.basicConfig` to shared `configure_logging()`
- [x] Worker handler resolves correlation from item or generates fallback via `CorrelationSource` enum
- [x] Worker handler sets + resets `_correlation_id_var` per item
- [x] `request_id=` log fragments removed from worker scan handler
- [x] `correlation_source` emitted in worker START log extra (enum `.value`)
- [x] Existing E15-2 Slice 1 tests remain green
- [x] Task plan Consolidated Checklist items checked off before task close

## Dependencies

- **Upstream (landed)**: E15-2 Slice 1 (`88e0dd16` on `feature/e15-2`) — correlation middleware, logging filter, JSON formatter, `_correlation_id_var`, `generate_correlation_id`.
- **Downstream (blocks)**: E15-6 end-to-end tracing cannot assert cross-hop traces until this task lands.

## Review Readiness

- All green TDD slices with RED evidence in the slice decisions.
- Zero open findings on E15-2b.
- `make review-ready` passes.
- `handoff_close_check(enforce=True)` passes on final HEAD.
