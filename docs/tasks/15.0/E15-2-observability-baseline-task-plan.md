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
2. Add correlation ID middleware that extracts `X-Request-ID` from the request header (or generates one), stores it in `contextvars`, and injects it into every log record and response header.
3. Enhance health probes: `/health` checks DB + model cache; `/ready` adds worker liveness. Both unauthenticated.
4. Add `prometheus-client` for request metrics: histogram for latency, counter for requests by status class, gauge for active connections. Expose via `/metrics`.

## Files and Surfaces to Change

| Surface | File | Change |
|---------|------|--------|
| Log config | `api/logging_config.py` | Replace `ContextualFormatter` with JSON formatter |
| Correlation middleware | `recognition/interface_adapters/http/middleware/correlation.py` | New: extract/generate request ID, store in contextvars |
| App wiring | `api/main.py` | Register correlation + metrics middleware |
| Health router | `recognition/interface_adapters/http/routers/health.py` | Enhance checks, add `/ready` |
| Subsystem health | `recognition/application/health.py` | Real dependency probes (DB, model cache) |
| Metrics middleware | `recognition/interface_adapters/http/middleware/metrics.py` | New: request timing + counters |
| Metrics endpoint | `api/main.py` or health router | `/metrics` Prometheus exposition |
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
  - `curl https://api.altcontext.com/ready` returns JSON with dependency checks
  - `curl https://api.altcontext.com/metrics` returns Prometheus text format
  - Log files contain valid JSON lines with `correlation_id` field
- Manual verification:
  - `jq . < logs/recognition.log` parses every line without error
  - `X-Request-ID` header in response matches correlation_id in corresponding log lines

## Slice Delivery

### Slice 1: Structured JSON Logging + Correlation ID Middleware

**Goal**: Every log record is a JSON object with a correlation ID that traces from request to response.

Changes:

- Add `python-json-logger` to `pyproject.toml` dependencies.
- Replace `ContextualFormatter` in `api/logging_config.py` with `pythonjsonlogger.json.JsonFormatter`. Preserve `WatchedFileHandler` and `RecognitionFilter`.
- Add `recognition/interface_adapters/http/middleware/correlation.py`: middleware that extracts `X-Request-ID` or generates `req-<uuid7>`, stores in `contextvars.ContextVar`, adds to response headers.
- Add a logging filter that injects the correlation ID from contextvars into every log record.
- Update `exception_handlers.py` to read correlation ID from contextvars instead of generating per-handler.
- Register middleware in `api/main.py`.
- Add `recognition/tests/api/test_correlation.py`: correlation ID in response header, correlation ID in log output, generated when header absent, propagated when header present.

Proof:

- `pytest recognition/tests/api/test_correlation.py` passes
- Log output is valid JSON with `correlation_id` field

### Slice 2: Enhanced Health and Readiness Probes

**Goal**: `/health` and `/ready` check real dependencies; monitoring systems get actionable status.

Changes:

- Enhance `recognition/application/health.py` to check: DB connectivity (query), model cache directory exists and contains expected model files, pool stats within bounds.
- Add `/ready` endpoint to `recognition/interface_adapters/http/routers/health.py` that includes all `/health` checks plus worker process liveness (check for running scan worker PID or recent heartbeat).
- Both endpoints return structured JSON: `{status: "healthy"|"degraded"|"unhealthy", checks: [{name, status, detail}], timestamp}`.
- Neither endpoint requires authentication.
- Add `recognition/tests/api/test_health_probes.py`: healthy when all deps up, degraded when model cache missing, unhealthy when DB down, `/ready` reflects worker status.

Proof:

- `pytest recognition/tests/api/test_health_probes.py` passes
- `/ready` returns dependency check details

### Slice 3: Request Metrics and Operational Runbook

**Goal**: Operators can monitor request latency and error rates; a runbook documents the diagnostics flow.

Changes:

- Add `prometheus-client` to `pyproject.toml` dependencies.
- Add `recognition/interface_adapters/http/middleware/metrics.py`: middleware that records request latency histogram (by method, path, status), request counter (by method, status class), active request gauge.
- Expose `/metrics` endpoint via `prometheus_client.make_asgi_app()` mounted in `api/main.py`.
- Register metrics middleware in `api/main.py`.
- Add `recognition/tests/api/test_metrics.py`: metrics endpoint returns Prometheus text, latency histogram populated after requests, counter increments.
- Write `docs/operations/observability-runbook.md`: how to check health, read structured logs, query metrics, trace a request by correlation ID, diagnose common failures.

Proof:

- `pytest recognition/tests/api/test_metrics.py` passes
- Full test suite passes: `make check` from `apps/prototype-description-service/`
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
- [ ] `/health` checks DB + model cache
- [ ] `/ready` checks DB + model cache + worker liveness
- [ ] Both endpoints unauthenticated
- [ ] Structured response schema documented
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
- [ ] `X-Request-ID` in response matches `correlation_id` in logs
- [ ] `/ready` returns dependency check details including model cache and DB
- [ ] `/metrics` exposes request latency P50/P95/P99 and error counts
- [ ] Operator can diagnose a failed sync from endpoints and logs alone
