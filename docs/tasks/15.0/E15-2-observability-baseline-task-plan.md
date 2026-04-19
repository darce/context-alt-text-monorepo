# E15-2. Observability Baseline: Structured Logs, Health Probes, and Request Metrics

> **Metadata**
>
> - **Date**: 2026-04-06
> - **Author**: Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-2-observability-baseline`
> - **Review Coverage Target**: 2

---

## Objective

Make the recognition service diagnosable without SSH access. When this task is complete, operators can determine service health from HTTP endpoints, trace failed requests through structured JSON logs with correlation IDs, and monitor latency/error rates from exposed metrics.

## Problem Statement

The service is deployed and serving HTTPS, but failures are opaque:

1. **Logs are plain text.** `api/logging_config.py` uses a `ContextualFormatter` that outputs human-readable lines. No machine-parseable JSON. External log aggregators cannot index fields without regex parsing.
2. **Correlation IDs exist only in error responses.** `exception_handlers.py` generates `req-<uuid>` trace IDs for errors, but normal request/response cycles have no correlation. WordPress-triggered actions cannot be traced through the backend.
3. **Health checks are shallow.** `/health` returns static "ok" without probing dependencies. No `/ready` endpoint. No model cache availability check.
4. **No request metrics.** No latency percentiles, no error counts, no request volume tracking. The only production metric is pool stats behind an auth-gated endpoint.

## Constraints

- Scope is `apps/prototype-description-service/` only.
- Structured logging must not break existing `WatchedFileHandler` log rotation (Makefile `logs-rotate` target).
- Health probes must not require authentication (monitoring systems need unauthenticated access).
- Metrics exposition should be lightweight; Prometheus client library is acceptable but a full Prometheus server is out of scope.
- Branch isolation: all code changes on `feature/e15-2-observability-baseline`.

## Workflow Principles

- Observability is infrastructure, not features. Keep middleware thin and decoupled from business logic.
- Structured logging replaces the existing formatter; it does not add a parallel logging path.
- Health probes check real dependencies, not cached state. A health endpoint that always returns 200 is worse than no health endpoint.

## Terminology

- **Structured JSON logging**: Log records emitted as single-line JSON objects with indexed fields (timestamp, level, logger, correlation_id, path, status_code, etc.).
- **Correlation ID (canonical)**: A unique request identifier carried through the request lifecycle. **Three surfaces, one value:**
  - HTTP request/response **header**: `X-Request-ID` (HTTP convention, unchanged)
  - JSON **log field**: `correlation_id`
  - JSON **response body field**: `correlation_id` (**renamed** from the existing `trace_id` in `exception_handlers.py` response bodies — Slice 1 change; greenfield policy, no shim) (PA-03, PA-14, PA-17)
- **Health probe**: An unauthenticated HTTP endpoint (or for `/health/detailed`, auth-gated) that checks dependency availability and returns structured status using the `HealthStatus` enum (PA-09).
- **HealthStatus enum**: `shared/health.HealthStatus(StrEnum)` with members `OK`, `DEGRADED`, `UNHEALTHY`. Replaces the current plain-string `HealthReport.status` per sr-007 (PA-09).
- **Model cache — on-disk**: The InsightFace `buffalo_l` ONNX bundle directory on the model volume. Checked by `/ready` via a **fresh filesystem stat** on every request (no caching) so a mid-run delete of the bundle flips `/ready` to `UNHEALTHY` within one probe interval (PA-10, PA-15).
- **Model cache — in-memory**: The loaded `FaceAnalysis` handle inside the process. Not checked by `/ready` in this task (its absence indicates the process is still starting; orchestrator should rely on `/health` for liveness and `/ready` for traffic admission).
- **Readiness probe**: A health check that indicates whether the service can accept traffic (DB pool check-out succeeds, breaker not open, on-disk model cache present).
- **Route-template path label**: Prometheus metrics use FastAPI's resolved route template (`request.scope["route"].path`, e.g., `/clusters/{cluster_id}`), **not** the raw URL (`/clusters/abc-123`). This bounds `http_request_duration_seconds{path=...}` cardinality at the number of routes, not the number of requests (PA-06).

## Current State Analysis

### What works

- `api/logging_config.py`: `ContextualFormatter` supports optional extra fields (media_id, cluster_id, etc.).
- `recognition/observability/logging.py`: `ClusteringLogger` provides structured decision logging with context.
- `exception_handlers.py`: `_trace_id_for()` extracts `X-Request-ID` or generates `req-<uuid>`, included in all error responses.
- `/health` endpoint aggregates subsystem health (recognition, roster, scene).
- `recognition/interface_adapters/http/routers/health.py`: checks database connectivity.
- `db/session.py`: `get_pool_stats()` returns pool metrics.
- `WatchedFileHandler` in logging config supports external log rotation.

### What is broken or missing

- Log output is plain text, not JSON. External systems cannot parse fields.
- Correlation IDs exist only in error paths. Success responses and intermediate logs have no request ID.
- No `contextvars` propagation: request context is not available to domain-layer loggers.
- Health subsystem checks (`recognition/application/health.py`, `roster/application/health.py`, `scene/application/health.py`) return static "ok" without dependency probes.
- No `/ready` endpoint. Container orchestrators cannot distinguish "starting" from "ready."
- No model cache health check (InsightFace model loaded? Model files present on disk?).
- No `prometheus-client` or equivalent. No `/metrics` endpoint.
- No request timing middleware. No latency distribution data.
- No error rate tracking by endpoint or status code class.

## Target Outcome

An operator at `https://api.altcontext.com/ready` sees a JSON response showing Postgres connected, breaker closed, and the on-disk InsightFace bundle present. `GET /health` returns 200 as long as the API process is up (liveness-only, no I/O). Logs on the VM are single-line JSON records with correlation IDs that match the `X-Request-ID` header from WordPress requests. A `/metrics` endpoint exposes request count, latency P50/P95/P99, and error rate by endpoint. Worker liveness is **not** part of this task's readiness contract: the API container already has `scan_worker_available()` for per-request gating (`recognition/application/tasks/scan.py:37-54`, `recognition/interface_adapters/http/routers/analyze.py:184-190`), but that is a request-path decision, not an orchestrator-visible probe, and a cross-container heartbeat contract is its own follow-on task (PR-01).

## Context Loading

- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Rules: `docs/agentic/rules/testing-python.md`
- Context map: `docs/agentic/maps/backend.md`
- External docs via `ctx7` only if: `python-json-logger` or `prometheus-client` API needs verification

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|----------|-------|-----------------|----------------|----------------------|--------------|
| Health/ready HTTP surface | Backend | None (ad hoc) | Document health/ready response schema | No (greenfield) | Integration tests |
| Log format | Backend/Ops | None | Document structured JSON log schema | No | Log output inspection |

## Proposed Solution

1. Replace `ContextualFormatter` with a JSON formatter (via `python-json-logger` or a minimal custom implementation). Keep `WatchedFileHandler` for rotation compatibility.
2. Add correlation ID middleware that extracts `X-Request-ID` from the request header (or generates one), stores it in `contextvars`, and injects it into every log record and response header. **Backend-only scope:** the WP plugin proxy does not currently emit `X-Request-ID`. This task generates and echoes correlation IDs but does not depend on upstream WP behavior. End-to-end correlation through WP→backend is a follow-on plugin task once a WP-side request-ID emit lands.
3. Adopt a three-tier health surface at the **root level** in `api/main.py` (not under `/recognition`) so monitoring systems hit a stable contract regardless of subsystem routing (PR-01 canonical contract):
   - `GET /health` — **liveness only**. Returns 200 whenever the ASGI process can respond. No DB, no model-cache stat, no breaker check. Unauthenticated. Safe for Caddy active probe at 10 s.
   - `GET /ready` — **readiness**. Returns 200 iff the DB pool check-out succeeds (`SELECT 1`), the recognition breaker is closed, and the on-disk InsightFace `buffalo_l` bundle files are present. Unauthenticated. Safe for orchestrator rolling-deploy gates and Prometheus Blackbox Exporter.
   - `GET /health/detailed` — auth-gated operator diagnostic (full pool stats, breaker state, rotation status, model-cache inventory). Lands in Slice 2.5 alongside router consolidation.
   Worker liveness is **excluded** from `/ready` (separate Docker Compose services, no cross-container heartbeat contract); `scan_worker_available()` remains a per-request gate inside the API, not an orchestrator-visible probe.
4. Add `prometheus-client` for request metrics: histogram for latency (buckets), counter for requests by status class, gauge for active connections. Expose via `/metrics`. **Percentiles (P50/P95/P99) are computed downstream by PromQL** (`histogram_quantile(0.95, ...)`); the metrics endpoint exposes raw histogram buckets, not pre-computed percentiles. **`/metrics` is implemented as a normal FastAPI route guarded by `Depends(require_auth)`**, not `prometheus_client.make_asgi_app()` mounted on the app (PR-02) — an ASGI sub-app mount bypasses FastAPI dependencies and cannot honor the `require_auth` gate. The route body calls `prometheus_client.generate_latest()` and returns it with `CONTENT_TYPE_LATEST`. The OCI host is publicly reachable and an open `/metrics` leaks request volume and endpoint shape to any passer-by; operators (and the host-local Prometheus scraper) call it with an API key.

## Plan-Analyze Recommendations

Derived from `plan-analyze-e15-2-observability-20260419-run-01` (see MCP findings E15-2-PA-01..PA-16) and the literature pass on Nygard *Release-it!*, Enberg *Latency*, Hattingh *Using Asyncio in Python*, Kleppmann *DDIA*, and Fowler/Beck *Refactoring*. Each recommendation names the driving finding(s); status is tracked in MCP, not here.

1. **Split the router consolidation into Slice 2.5 (PA-01).** Slice 2 lands new root `/health` + `/ready`. A new **Slice 2.5** deletes `recognition/interface_adapters/http/routers/health.py`, `roster/interface_adapters/http/health_router.py`, and `scene/interface_adapters/http/health_router.py`, and lifts their diagnostic content into an auth-gated `/health/detailed`. Rationale: Fowler — behavior-preserving refactors stay in their own slice; Nygard — machine probes and operator diagnostics have different audiences and should not share a URL.

2. **Three-tier probe architecture (PA-01, PA-02).** Target shape:
   - `GET /health` — liveness. 200 if process up. No I/O. Safe for Caddy active probe @ 10 s.
   - `GET /ready` — readiness. 200 only if DB pool check-out succeeds (`SELECT 1`), recognition breaker is not open, and the on-disk InsightFace `buffalo_l` bundle files are present. Cheap. Safe for orchestrator rolling-deploy gate and Prometheus Blackbox Exporter.
   - `GET /health/detailed` — operator diagnostic. Full `get_pool_stats`, breaker state, WatchedFileHandler rotation status, model-cache inventory. **Auth-required.**
   - `GET /metrics` — Prometheus scrape.
   Caddy `reverse_proxy` uses `health_uri /ready health_interval 10s health_timeout 2s health_status 2xx`; Blackbox probes `/health` for external up/down.

3. **Fix the handler shape (PA-04).** Per Hattingh ch. on Executors: most DB libraries are sync. Either declare `/ready` as `def` so FastAPI threadpools it, or use a genuinely async DB path. Do **not** leave it as `async def` calling blocking `observability_session` — that blocks the event loop under probe frequency and cascades into `/v1/describe` latency.

4. **Correlation ID propagation across the queue hop is deferred out of E15-2 (PR-03).** The Kleppmann end-to-end framing still applies — correlation must cross process boundaries as payload, not via `contextvars` — but the scan-job persistence surface (`ScanQueueItem` in `recognition/application/scan/queue_repository.py:16-31`, `IdentityScanJobItem` in `db/models/jobs.py:56-80`, and the enqueue/claim queries in `recognition/infrastructure/repositories/scan_queue_repository.py:74-100,300-368`) has no correlation column today. Adding one is a schema + repository + scheduler change that belongs in a worker-observability follow-on task, not in the API-layer observability baseline. E15-2 scope therefore covers correlation IDs *within* an API request lifecycle (middleware → contextvars → log filter → response header) and leaves worker-process correlation to the follow-on. Slice 1 does **not** touch `recognition/worker/handlers/scan.py` or any queue schema.

5. **Reserved-key guard on the JSON formatter (PA-12).** Emit caller-supplied `extra={}` under a `context.*` subkey so `service`, `level`, `correlation_id`, `timestamp`, `logger` cannot be silently clobbered by `ClusteringLogger` call sites. Add a test that passes `extra={"service": "evil"}` and asserts the framework-owned `service` field wins.

6. **Histogram buckets chosen from observed distribution (PA-03, Slice 3).** Default `(0.005..10)` bucket set has a sparse tail for description-service requests (~1–30 s typical). Use `(0.25, 0.5, 1, 2, 5, 10, 30, 60, +Inf)` as the initial set, and document in the runbook that recording-on-response-complete introduces coordinated-omission bias — tail numbers are lower bounds. Revisit buckets after one day of staging data.

7. **Delete orphaned `api/schemas/health.py` in Slice 2.5 (PA-16).** Greenfield policy — no compatibility shim. Same slice as the router consolidation so the deletion lands atomically with the replacement schema.

8. **Bulkhead note for forward work (PA-11, informational).** When a VLM worker lands on the OCI A1 host, separate API and worker DB pools even on one host so a pathological VLM batch cannot exhaust the pool serving `/v1/describe`. Not a Slice blocker — capture in the Slice 3 runbook under *Known limits*.

## Files and Surfaces to Change

| Surface | File | Change |
|---------|------|--------|
| Log config | `api/logging_config.py` | Replace `ContextualFormatter` with JSON formatter |
| Correlation middleware | `recognition/interface_adapters/http/middleware/correlation.py` | New: extract/generate request ID, store in contextvars |
| App wiring | `api/main.py` | Register correlation + metrics middleware |
| Root health/ready endpoints | `api/main.py` | Make root `/health` liveness-only (200 + `{"status":"ok"}`, no I/O) and add root `/ready` as the dependency probe (DB + breaker + on-disk model cache). Both owned by `api/main.py`, not the recognition router (PR-01, PR-04). |
| Subsystem health | `recognition/application/health.py` | Real dependency probes (DB, breaker, on-disk model cache) — invoked by `/ready` and `/health/detailed`; **not** by liveness-only `/health` (PR-01, PR-04) |
| Metrics middleware | `recognition/interface_adapters/http/middleware/metrics.py` | New: request timing + counters |
| Metrics endpoint | `api/main.py` | `/metrics` FastAPI route guarded by `Depends(require_auth)`; body calls `prometheus_client.generate_latest()` and returns `CONTENT_TYPE_LATEST` — **not** an ASGI sub-app mount (PR-02) |
| Dependencies | `pyproject.toml` | Add `python-json-logger>=2.0.7,<3` and `prometheus-client>=0.20,<1` with explicit version pins (PA-07); verify latest via `ctx7` before committing |
| Status enum | `shared/health.py` | Add `HealthStatus(StrEnum)` (OK, DEGRADED, UNHEALTHY); retype `HealthReport.status: HealthStatus` per sr-007 (PA-09) |
| Env template | `.env.prod.example` | Document any new config vars |
| Exception handlers | `recognition/interface_adapters/http/exception_handlers.py` | Use contextvars correlation ID instead of per-handler generation |
| Tests | `recognition/tests/api/test_correlation.py` | New |
| Tests | `recognition/tests/api/test_health_probes.py` | New |
| Tests | `recognition/tests/api/test_metrics.py` | New |
| Runbook | `docs/operations/observability-runbook.md` | New: operator diagnostics guide |

## Related Files

| File | Note |
|------|------|
| `recognition/observability/logging.py` | `ClusteringLogger` uses `extra` dict; must propagate correlation ID |
| `recognition/worker/handlers/scan.py` | **Out of scope for E15-2 (PR-03).** Queue-hop correlation propagation is deferred to a worker-observability follow-on task that owns the scan-job schema change. Worker continues to generate its own `request_id` for now. |
| `Makefile` targets `logs-tail`, `logs-rotate` | Must remain compatible with new JSON format |
| `docker-compose.prod.yml` | No changes needed; logs go to stdout/file as before |

## Verification Strategy

- Deterministic tests:
  - `PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/api/test_correlation.py -v`
  - `PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/api/test_health_probes.py -v`
  - `PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/api/test_metrics.py -v`
- Runtime-parity:
  - `curl https://api.altcontext.com/health` returns `{"status":"ok"}` with 200 whenever the process is up (no dependency checks — liveness only, PR-01)
  - `curl https://api.altcontext.com/ready` returns JSON with DB + breaker + on-disk model cache checks (worker liveness intentionally excluded)
  - `curl https://api.altcontext.com/metrics` returns Prometheus text format with histogram buckets
  - `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))` produces a P95 latency value when run against the metrics endpoint
  - Log files contain valid JSON lines with `correlation_id` field
- Manual verification:
  - `jq . < logs/recognition.log` parses every line without error
  - Backend-generated correlation IDs appear in both response headers (`X-Request-ID`) and log output for the same request
  - Note: end-to-end WP→backend correlation requires a separate plugin task (out of scope for E15-2)

## Slice Delivery

### Slice 1: Structured JSON Logging + Backend-Generated Correlation IDs

**Goal**: Every log record is a JSON object with a backend-generated correlation ID. Each request gets a fresh ID (or echoes an upstream `X-Request-ID` header if one is supplied), the ID flows through every log record for the request lifecycle, and the same ID appears in the response header.

**Scope boundary:** This slice generates and echoes correlation IDs at the backend boundary. The WP plugin proxy does not currently emit `X-Request-ID`, so end-to-end WP-to-backend continuity is **not** a success criterion of this task. A follow-on plugin task can add `X-Request-ID` emission to `class-abstract-recognition-proxy-controller.php` once the backend contract is in place.

Changes:

- Add `python-json-logger` to `pyproject.toml` dependencies.
- Replace `ContextualFormatter` in `api/logging_config.py` with `pythonjsonlogger.json.JsonFormatter`. Preserve `WatchedFileHandler` and `RecognitionFilter`.
- Add `recognition/interface_adapters/http/middleware/correlation.py`: middleware that reads incoming `X-Request-ID` if present, otherwise generates `req-<uuid7>`, stores it in a `contextvars.ContextVar`, and adds it to the response headers.
- Add a logging filter that injects the correlation ID from contextvars into every log record.
- Update `exception_handlers.py` to (a) read correlation ID from contextvars instead of generating per-handler and (b) **rename the response body key from `trace_id` to `correlation_id`** across all error response shapes (greenfield, no alias) (PA-03, PA-14, PA-17).
- Register middleware in `api/main.py`.
- Add `recognition/tests/api/test_correlation.py`: ID in response header, ID in log output, generated when no header, echoed when header present, ID stable across multiple log lines for one request, error response body contains `correlation_id` (not `trace_id`).
- Add `recognition/tests/api/test_log_rotation.py`: emit a test log line, simulate `make logs-rotate` (move file + signal/reopen via `WatchedFileHandler`), emit a second line, assert both lines parse as valid JSON and appear in their respective files with no partial / truncated records (PA-11, PA-18).

Proof:

- `pytest recognition/tests/api/test_correlation.py` passes
- Log output is valid JSON with `correlation_id` field
- Same ID appears in both the response header and all log lines for a single request

### Slice 2: Root-Level Liveness and Readiness Probes (No Worker Liveness)

**Goal**: Root `/health` is liveness-only; root `/ready` is the dependency probe. Both endpoints live in `api/main.py` and check only what the API container can actually observe. This slice adopts the PR-01 canonical contract everywhere.

**Scope boundary:** Worker liveness is **excluded** from `/ready` in this task. The API and scan worker run as separate Docker Compose services; the API container cannot inspect the worker process table, and no cross-service heartbeat contract exists yet. Adding a heartbeat (DB-backed or worker health endpoint) is its own follow-on task. This slice ships honest probes that only assert what the API process can verify.

Changes:

- Introduce `HealthStatus(StrEnum)` in `shared/health.py` with members `OK`, `DEGRADED`, `UNHEALTHY`. Retype `HealthReport.status` to `HealthStatus` (PA-09).
- Update root `/health` in `api/main.py` to be **liveness-only** (PR-01): returns `{"status": HealthStatus.OK, "timestamp": ...}` with 200 whenever the process can respond. No DB, no model-cache stat, no breaker probe, no I/O. Safe for Caddy active probe at 10 s.
- Add root `/ready` in `api/main.py` (PR-01): returns `{status: HealthStatus, checks: [{name, status, detail}], timestamp}` with dependency checks for (a) DB connectivity via live pool check-out, (b) recognition breaker state (not open), (c) on-disk InsightFace `buffalo_l` bundle presence via fresh `Path.is_dir()`/`Path.is_file()` stat on every call (no caching; PA-10, PA-15). Does **not** probe worker liveness and does **not** probe the in-memory `FaceAnalysis` handle.
- Enhance `recognition/application/health.py` to provide the dependency-probe helpers that `/ready` calls (DB check, breaker check, on-disk model cache check). These helpers are also reused by `/health/detailed` in Slice 2.5.
- Neither `/health` nor `/ready` requires authentication.
- Handler shape: `def` (threadpooled) for sync DB calls, OR fully async with an async DB driver — never `async def` wrapping blocking `observability_session` (PA-04). `/health` is trivially sync (no I/O) so the shape question only matters for `/ready`.
- Add `recognition/tests/api/test_health_probes.py`:
  - `/health` returns 200 + `{"status":"ok"}` and performs **no** I/O (asserted by monkeypatching the DB session factory and confirming it is never entered) — PR-01 liveness contract
  - `/ready` healthy when all deps up
  - `/ready` degraded when at least one non-critical check fails
  - `/ready` unhealthy when DB down
  - `/ready` model-cache check flips `UNHEALTHY` within one call after a bundle file is unlinked mid-test (PA-10)
  - worker-liveness assertions are intentionally absent from both endpoints

Proof:

- `pytest recognition/tests/api/test_health_probes.py` passes
- `curl https://api.altcontext.com/health` returns `{"status":"ok"}` with 200 — no dependency checks (liveness only)
- `curl https://api.altcontext.com/ready` returns structured JSON with DB + breaker + on-disk model cache check details
- `/ready` does NOT claim worker liveness; the response schema explicitly omits a worker check

### Slice 2.5: Health Surface Consolidation

**Goal**: Resolve PA-01 by reducing four parallel health routers to a single root surface plus one auth-gated diagnostic endpoint. Ships after Slice 2 so any probe regression is independently revertable (Fowler — one small step at a time).

Changes:

- Delete `recognition/interface_adapters/http/routers/health.py`, `roster/interface_adapters/http/health_router.py`, `scene/interface_adapters/http/health_router.py`.
- Delete `api/schemas/health.py` (orphaned by the new response shape — PA-16).
- Add `GET /health/detailed` in `api/main.py` (auth-gated via existing `require_auth`). Returns full `get_pool_stats`, breaker state, WatchedFileHandler rotation status, model-cache inventory.
- Remove the subsystem `application/health.py` files once their content moves into the root handler helpers — or keep them as pure functions called by `api/main.py` with no router attached.
- Update any tests that imported the deleted routers.

Proof:

- `pytest` full description-service suite passes with zero references to `/recognition/health`, `/roster/health`, `/scene/health`.
- `curl https://api.altcontext.com/health/detailed` without auth returns 401; with auth returns full diagnostic JSON.
- `grep -r "api.schemas.health" apps/prototype-description-service/` returns no matches.

### Slice 3: Request Metrics (Histogram Buckets) and Operational Runbook

**Goal**: Operators can monitor request latency distribution and error rates. The metrics endpoint exposes Prometheus histogram buckets; percentiles are derived downstream via PromQL.

**Why histogram buckets, not pre-computed percentiles:** Prometheus histograms emit `_bucket`, `_count`, and `_sum` series. P50/P95/P99 are computed by PromQL using `histogram_quantile()` against the buckets, not exposed directly by the metrics endpoint. The previous version of this plan claimed `/metrics` would expose percentiles directly, which is not how Prometheus histograms work. Switching to summary metrics would expose pre-computed quantiles but loses aggregability across instances and is the wrong tradeoff for this baseline.

Changes:

- Add `prometheus-client>=0.20,<1` to `pyproject.toml` dependencies (PA-07).
- Add `recognition/interface_adapters/http/middleware/metrics.py`: middleware that records:
  - `http_request_duration_seconds` Histogram (labels: `method`, `path`, `status`). **`path` label resolves to `request.scope["route"].path` (FastAPI route template), not `request.url.path`** — bounds cardinality at the number of routes, not the number of requests (PA-06).
  - `http_requests_total` Counter (labels: `method`, `status_class`)
  - `http_requests_in_flight` Gauge
  - Histogram buckets: `(0.25, 0.5, 1, 2, 5, 10, 30, 60, +Inf)`.
- Expose `/metrics` as a **FastAPI route** in `api/main.py` guarded by `Depends(require_auth)` (PA-05, PR-02). Route body: `return Response(prometheus_client.generate_latest(), media_type=CONTENT_TYPE_LATEST)`. **Do not** use `prometheus_client.make_asgi_app()` mounted on the app — an ASGI sub-app mount bypasses FastAPI dependencies and cannot honor `require_auth`. Operators and the host-local Prometheus scraper supply an API key; anonymous requests get 401.
- Register metrics middleware in `api/main.py`.
- Add `recognition/tests/api/test_metrics.py`:
  - metrics endpoint requires auth (401 without key, 200 with key) (PA-05)
  - histogram bucket series populated after successful requests
  - **Exception path**: an endpoint that raises an unhandled exception still produces (a) a histogram observation for that request, (b) a `http_requests_total{status_class="5xx"}` increment, (c) a decremented `http_requests_in_flight` gauge — no metric leak on error (PA-13)
  - path label resolves to route template: two requests to `/clusters/<uuid-a>` and `/clusters/<uuid-b>` share the same `path="/clusters/{cluster_id}"` label (PA-06)
  - in-flight gauge tracks concurrent requests
- Write `docs/operations/observability-runbook.md`: how to check health/ready, read structured logs, query metrics with PromQL examples (including the `histogram_quantile` formula for P50/P95/P99), trace a request by correlation ID, diagnose common failures.

Proof:

- `pytest recognition/tests/api/test_metrics.py` passes
- Full test suite passes: `make check` from `apps/prototype-description-service/`
- Runbook documents the PromQL formula for deriving P50/P95/P99 from the exposed histogram buckets
- Runbook is sufficient for a new operator to diagnose a failed sync

---

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded backend context map and testing guide before editing
- [ ] Confirmed `python-json-logger` and `prometheus-client` package availability via `ctx7` or PyPI
- [ ] Branch created: `feature/e15-2-observability-baseline`

### Checklist for Slice 1: Structured JSON Logging + Correlation ID

- [ ] Failing tests written first (`test_correlation.py`)
- [ ] JSON formatter replaces `ContextualFormatter`
- [ ] Correlation ID middleware implemented and registered
- [ ] `WatchedFileHandler` and `RecognitionFilter` preserved
- [ ] Exception handlers use contextvars correlation ID
- [ ] Reserved-key guard: caller `extra={}` nested under `context.*`; test asserts framework keys (`service`, `level`, `correlation_id`) cannot be clobbered (PA-12)
- [ ] Queue-hop correlation propagation is explicitly **deferred** from E15-2 (PR-03); `recognition/worker/handlers/scan.py` and the scan-job schema are not modified in this task. A worker-observability follow-on task owns the schema + repository change.
- [ ] `exception_handlers.py` response body key renamed `trace_id` → `correlation_id` across every error shape; test asserts no `trace_id` key remains (PA-03, PA-14, PA-17)
- [ ] Log-rotation regression test in `test_log_rotation.py`: JSON output survives `make logs-rotate` with no partial lines (PA-11, PA-18)
- [ ] `python-json-logger>=2.0.7,<3` pinned in `pyproject.toml`; `ctx7` verification cited in commit (PA-07)
- [ ] All tests pass; `jq` validates log output

### Checklist for Slice 2: Health and Readiness Probes

- [ ] Failing tests written first (`test_health_probes.py`)
- [ ] `/health` is liveness-only (no I/O, 200 if process up); test asserts the DB session factory is never entered during a `/health` request (PR-01)
- [ ] `/ready` checks DB pool check-out + breaker-not-open + on-disk model cache — no worker liveness, no in-memory model-handle probe (PR-01)
- [ ] Both endpoints unauthenticated and at root level (not under `/recognition`)
- [ ] Handler shape is `def` (threadpooled) or fully async — no `async def` wrapping blocking DB calls (PA-04)
- [ ] `HealthStatus(StrEnum)` introduced in `shared/health.py`; no magic-string status literals remain in health code (PA-09, sr-007)
- [ ] Model-cache check performs a fresh `Path` stat on every call (no cached result); test asserts an unlinked ONNX file flips status to `UNHEALTHY` within one call (PA-10)
- [ ] Model-cache check probes **on-disk files only**, not in-memory `FaceAnalysis` handle; enumerated `buffalo_l` bundle paths documented in runbook (PA-15)
- [ ] Structured response schema documented in the runbook
- [ ] Worker-liveness deferral noted in plan and runbook
- [ ] All tests pass

### Checklist for Slice 2.5: Health Surface Consolidation

- [ ] Subsystem routers (`recognition`/`roster`/`scene` health routers) removed
- [ ] Orphaned `api/schemas/health.py` deleted (PA-16)
- [ ] Auth-gated `/health/detailed` returns pool stats + breaker state + model-cache inventory
- [ ] No references to `/recognition/health`, `/roster/health`, `/scene/health` remain in codebase
- [ ] Tests updated for new URL surface

### Checklist for Slice 3: Request Metrics and Runbook

- [ ] Failing tests written first (`test_metrics.py`)
- [ ] Prometheus middleware records latency + counts
- [ ] `http_request_duration_seconds` buckets set to `(0.25, 0.5, 1, 2, 5, 10, 30, 60, +Inf)` initial values; revisit after one day of staging data
- [ ] `path` label uses FastAPI route template (`request.scope["route"].path`), not raw URL; test asserts two UUIDs collapse to the same label (PA-06)
- [ ] `/metrics` implemented as a FastAPI route with `Depends(require_auth)` (not an ASGI sub-app mount); body returns `generate_latest()` with `CONTENT_TYPE_LATEST`. Test asserts 401 without key, 200 with key (PA-05, PR-02)
- [ ] Exception-path metrics: forced 500 produces bucket observation + `status_class=5xx` counter increment + gauge decrement (PA-13)
- [ ] `prometheus-client>=0.20,<1` pinned in `pyproject.toml`; `ctx7` verification cited (PA-07)
- [ ] `/metrics` endpoint exposes Prometheus text format
- [ ] Runbook written (`docs/operations/observability-runbook.md`) including:
  - `histogram_quantile` PromQL formulas for P50/P95/P99
  - Coordinated-omission caveat (tail numbers are lower bounds because middleware records on response-complete)
  - Caddy `reverse_proxy` `health_uri /ready` snippet
  - Prometheus Blackbox Exporter probe config for `/health`
  - Known limits: bulkhead deferral for future VLM worker pool separation (PA-11)
- [ ] Full `make check` passes

## Review Readiness

- [ ] Auth policy consistent across the plan: `/health` and `/ready` are unauthenticated; `/metrics` and `/health/detailed` require `require_auth` (PR-01, PR-02)
- [ ] Log format change does not break `make logs-rotate`
- [ ] Correlation ID flows from request through domain logging to response
- [ ] Handoff decision records the change with verification evidence

## Success Criteria

- [ ] `jq . < logs/recognition.log` parses every line
- [ ] Backend-generated correlation ID appears in both response header (`X-Request-ID`) and `correlation_id` field of every log line for the same request
- [ ] Root `/health` (in `api/main.py`) returns 200 + `{"status":"ok"}` as a pure liveness probe with no I/O; root `/ready` (in `api/main.py`) returns dependency check details for DB + breaker + on-disk model cache. Worker liveness is intentionally excluded from both (PR-01)
- [ ] `/metrics` exposes Prometheus histogram buckets for request duration and counters for requests by status class
- [ ] Operator runbook documents the PromQL `histogram_quantile()` formula for deriving P50/P95/P99 from the histogram buckets
- [ ] Operator can diagnose a failed sync from endpoints and logs alone
