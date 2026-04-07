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
- **Correlation ID**: A unique request identifier (`X-Request-ID` header or generated UUID) propagated through all log records for a single request lifecycle.
- **Health probe**: An unauthenticated HTTP endpoint that checks dependency availability and returns structured status.
- **Readiness probe**: A health check that indicates whether the service can accept traffic (dependencies connected, models loaded).

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

An operator at `https://api.altcontext.com/ready` sees a JSON response showing Postgres connected, model cache populated, and worker process alive. Logs on the VM are single-line JSON records with correlation IDs that match the `X-Request-ID` header from WordPress requests. A `/metrics` endpoint exposes request count, latency P50/P95/P99, and error rate by endpoint.

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
3. Enhance health probes: `/health` checks DB + model cache. `/ready` checks DB + model cache only -- **worker liveness is excluded** because the API and worker run as separate Docker Compose containers and the API container cannot inspect the worker process table without a defined cross-service heartbeat contract. Worker heartbeat is its own future task. Both endpoints unauthenticated. Both endpoints live at the **root level** in `api/main.py` (not under `/recognition`) so monitoring systems hit a stable contract regardless of subsystem routing.
4. Add `prometheus-client` for request metrics: histogram for latency (buckets), counter for requests by status class, gauge for active connections. Expose via `/metrics`. **Percentiles (P50/P95/P99) are computed downstream by PromQL** (`histogram_quantile(0.95, ...)`); the metrics endpoint exposes raw histogram buckets, not pre-computed percentiles.

## Files and Surfaces to Change

| Surface | File | Change |
|---------|------|--------|
| Log config | `api/logging_config.py` | Replace `ContextualFormatter` with JSON formatter |
| Correlation middleware | `recognition/interface_adapters/http/middleware/correlation.py` | New: extract/generate request ID, store in contextvars |
| App wiring | `api/main.py` | Register correlation + metrics middleware |
| Root health/ready endpoints | `api/main.py` | Enhance existing root `/health` with dependency checks; add root `/ready` (both owned by `api/main.py`, not the recognition router) |
| Subsystem health | `recognition/application/health.py` | Real dependency probes (DB, model cache) — invoked by root endpoints |
| Metrics middleware | `recognition/interface_adapters/http/middleware/metrics.py` | New: request timing + counters |
| Metrics endpoint | `api/main.py` | `/metrics` Prometheus ASGI app mount at root |
| Dependencies | `pyproject.toml` | Add `python-json-logger`, `prometheus-client` |
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
| `recognition/worker/handlers/scan.py` | Worker already generates `request_id`; should use shared correlation context |
| `Makefile` targets `logs-tail`, `logs-rotate` | Must remain compatible with new JSON format |
| `docker-compose.prod.yml` | No changes needed; logs go to stdout/file as before |

## Verification Strategy

- Deterministic tests:
  - `PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/api/test_correlation.py -v`
  - `PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/api/test_health_probes.py -v`
  - `PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/api/test_metrics.py -v`
- Runtime-parity:
  - `curl https://api.altcontext.com/health` returns enriched JSON with dependency checks
  - `curl https://api.altcontext.com/ready` returns JSON with DB + model cache checks (worker liveness intentionally excluded)
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
- Update `exception_handlers.py` to read correlation ID from contextvars instead of generating per-handler.
- Register middleware in `api/main.py`.
- Add `recognition/tests/api/test_correlation.py`: ID in response header, ID in log output, generated when no header, echoed when header present, ID stable across multiple log lines for one request.

Proof:

- `pytest recognition/tests/api/test_correlation.py` passes
- Log output is valid JSON with `correlation_id` field
- Same ID appears in both the response header and all log lines for a single request

### Slice 2: Root-Level Health and Readiness Probes (No Worker Liveness)

**Goal**: Root `/health` and `/ready` probes return structured dependency status. Both endpoints live in `api/main.py` and check what the API container can actually observe.

**Scope boundary:** Worker liveness is **excluded** from `/ready` in this task. The API and scan worker run as separate Docker Compose services; the API container cannot inspect the worker process table, and no cross-service heartbeat contract exists yet. Adding a heartbeat (DB-backed or worker health endpoint) is its own follow-on task. This slice ships honest probes that only assert what the API process can verify.

Changes:

- Enhance `recognition/application/health.py` to check: DB connectivity (live query), model cache directory exists and contains expected InsightFace files, pool stats within bounds.
- Update root `/health` in `api/main.py` to call the enhanced subsystem checks and return structured JSON: `{status: "healthy"|"degraded"|"unhealthy", checks: [{name, status, detail}], timestamp}`.
- Add root `/ready` in `api/main.py` returning the same shape, with the same DB + model cache checks (no worker liveness).
- Neither endpoint requires authentication.
- Add `recognition/tests/api/test_health_probes.py`: healthy when all deps up, degraded when model cache missing, unhealthy when DB down. Worker-liveness assertions are intentionally absent.

Proof:

- `pytest recognition/tests/api/test_health_probes.py` passes
- `curl https://api.altcontext.com/health` and `/ready` return structured JSON with DB + model cache check details
- `/ready` does NOT claim worker liveness; the response schema explicitly omits a worker check

### Slice 3: Request Metrics (Histogram Buckets) and Operational Runbook

**Goal**: Operators can monitor request latency distribution and error rates. The metrics endpoint exposes Prometheus histogram buckets; percentiles are derived downstream via PromQL.

**Why histogram buckets, not pre-computed percentiles:** Prometheus histograms emit `_bucket`, `_count`, and `_sum` series. P50/P95/P99 are computed by PromQL using `histogram_quantile()` against the buckets, not exposed directly by the metrics endpoint. The previous version of this plan claimed `/metrics` would expose percentiles directly, which is not how Prometheus histograms work. Switching to summary metrics would expose pre-computed quantiles but loses aggregability across instances and is the wrong tradeoff for this baseline.

Changes:

- Add `prometheus-client` to `pyproject.toml` dependencies.
- Add `recognition/interface_adapters/http/middleware/metrics.py`: middleware that records:
  - `http_request_duration_seconds` Histogram (labels: `method`, `path`, `status`)
  - `http_requests_total` Counter (labels: `method`, `status_class`)
  - `http_requests_in_flight` Gauge
- Expose `/metrics` endpoint via `prometheus_client.make_asgi_app()` mounted in `api/main.py`.
- Register metrics middleware in `api/main.py`.
- Add `recognition/tests/api/test_metrics.py`: metrics endpoint returns Prometheus text, histogram bucket series populated after requests, counter increments by status class, in-flight gauge tracks concurrent requests.
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
- [ ] All tests pass; `jq` validates log output

### Checklist for Slice 2: Health and Readiness Probes

- [ ] Failing tests written first (`test_health_probes.py`)
- [ ] Root `/health` (in `api/main.py`) enriched with DB + model cache checks
- [ ] Root `/ready` (in `api/main.py`) checks DB + model cache only -- no worker liveness
- [ ] Both endpoints unauthenticated and at root level (not under `/recognition`)
- [ ] Structured response schema documented in the runbook
- [ ] Worker-liveness deferral noted in plan and runbook
- [ ] All tests pass

### Checklist for Slice 3: Request Metrics and Runbook

- [ ] Failing tests written first (`test_metrics.py`)
- [ ] Prometheus middleware records latency + counts
- [ ] `/metrics` endpoint exposes Prometheus text format
- [ ] Runbook written (`docs/operations/observability-runbook.md`)
- [ ] Full `make check` passes

## Review Readiness

- [ ] No authentication required for health/ready/metrics endpoints
- [ ] Log format change does not break `make logs-rotate`
- [ ] Correlation ID flows from request through domain logging to response
- [ ] Handoff decision records the change with verification evidence

## Success Criteria

- [ ] `jq . < logs/recognition.log` parses every line
- [ ] Backend-generated correlation ID appears in both response header (`X-Request-ID`) and `correlation_id` field of every log line for the same request
- [ ] Root `/health` and `/ready` (in `api/main.py`) return dependency check details for DB and model cache; worker liveness is intentionally excluded
- [ ] `/metrics` exposes Prometheus histogram buckets for request duration and counters for requests by status class
- [ ] Operator runbook documents the PromQL `histogram_quantile()` formula for deriving P50/P95/P99 from the histogram buckets
- [ ] Operator can diagnose a failed sync from endpoints and logs alone
