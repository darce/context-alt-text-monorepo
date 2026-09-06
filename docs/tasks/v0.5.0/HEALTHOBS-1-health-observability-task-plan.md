# Task Plan — HEALTHOBS-1

> - **Date**: 2026-09-06
> - **Project**: context-alt-text-monorepo (description-service + deploy)
> - **Task ID**: `HEALTHOBS-1`
> - **Branch**: `feature/healthobs-1` (integration) with lane branches `feature/healthobs-1-liveness`, `feature/healthobs-1-headroom`
> - **Incident**: prod postgres died 2026-09-02 23:05 UTC (ENOSPC during `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_identity_cluster_centroids`) and stayed down until 2026-09-06 while `GET /health` kept answering `200 {"status":"ok"}`.

## HEALTHOBS-1. Liveness must touch the pool; postgres needs a disk-headroom guard

## Objective

Make `GET /health` on the description service report the database pool
truthfully (503 `unhealthy` when a bounded pool probe cannot reach postgres),
add a disk-headroom guard in front of the materialized-view refresh that
killed prod, and surface container health in compose so `docker ps` and the
deploy smoke stop lying.

## Problem statement

Three independent gaps let a four-day outage pass unnoticed:

1. `/health` is process-only by design (PR-01). Its comment claims a Caddy
   active probe at 10s that does not exist (`Caddyfile` has no health
   checks). Every consumer that matters, including the deploy smoke in
   `scripts/deploy/sync-demo.sh` and `recognition-service.sh verify/status`,
   reads `/health`, so nothing observed the dead pool.
2. `_refresh_mv_concurrent_with_bypass` refreshes the MV with no check on
   free space. A concurrent refresh needs roughly twice the MV footprint in
   temp and WAL; ENOSPC there crashed postgres.
3. `docker-compose.env.yml` has a `pg_isready`-only postgres healthcheck and no
   healthcheck at all on `api` or `worker`. `restart: unless-stopped` gave up
   and the stale `docker ps` view showed nothing wrong.

## Constraints

- **Bounded latency**: the pool probe on `/health` must be wall-clock bounded
  (`ACX_HEALTH_DB_TIMEOUT_SECONDS`, default 2.0, validated at load, rg-008).
  A timeout is `unhealthy`, never a hang and never an unhandled exception.
- **Identity survives failure**: a 503 `/health` body still carries
  `commit_sha` and `image_variant` so `recognition-service.sh verify/status`
  can attribute the deployed build during an outage. Those deploy consumers
  must read the body regardless of HTTP status.
- **No dependency projections on `/health`** beyond the single `database`
  check: `pool_stats`, `breaker_state`, `model_cache`, `description_adapter`
  stay on `/ready` and `/health/detailed`.
- **Guard is a skip, not a crash**: insufficient headroom logs a warning with
  free bytes, required bytes and probe path, skips the refresh, and leaves
  every caller's surrounding work intact. Fail closed to "skip" when the probe
  path is missing or unreadable.
- **Central vocabulary** (sr-007): status strings come from
  `shared.health.HealthStatus`; no magic strings.
- **No new secrets, no new images, no network in the sandbox**: python and
  shell checks are the verification surface; the coordinator runs the same
  suites locally before recording evidence.
- **Never weaken a test**. The two liveness-only tests are replaced by tests
  that pin the new contract, with the rationale rewritten in the docstrings.

## Slices

### Slice 1 — `/health` probes the pool (lane `healthobs-1-liveness`)

- [ ] `apps/prototype-description-service/api/main.py`: `liveness()` becomes
      async, takes `http_deps.get_observability_session`, runs
      `check_database` under `asyncio.wait_for(...)` with the configured
      timeout, returns 503 with `status: unhealthy` and a `database` check
      block when the pool is unreachable or the probe times out; 200 with
      `status: ok` otherwise. Body always includes `timestamp`,
      `commit_sha`, `image_variant`. Stale Caddy comment removed.
- [ ] `apps/prototype-description-service/recognition/tests/api/test_health_probes.py`:
      replace `test_root_health_is_liveness_only` and
      `test_root_health_does_not_open_db_session` with tests for 200 on a
      healthy pool, 503 when the session dependency yields `None`, 503 when
      the probe exceeds the timeout (bounded wall clock asserted), identity
      fields present on 503, and the forbidden-key set minus `database`.
- [ ] `apps/prototype-description-service/recognition/application/health.py`
      (only if a bounded wrapper is needed): `check_database_bounded(...)`.
- [ ] `scripts/deploy/recognition-service.sh`: `verify`, `status`, and the
      boot smoke keep working when `/health` is 503; the smoke container has
      its own postgres so it still expects 200. `scripts/deploy/tests` stays
      green (run with `LC_ALL=C` on macOS).
- Test: `cd apps/prototype-description-service && python -m pytest recognition/tests/api/test_health_probes.py -q -p no:cacheprovider`

### Slice 2 — disk-headroom guard and compose healthchecks (lane `healthobs-1-headroom`)

- [ ] New `apps/prototype-description-service/shared/disk_headroom.py`:
      `DiskHeadroomSettings` (`ACX_PG_HEADROOM_PROBE_PATH`,
      `ACX_PG_HEADROOM_MIN_BYTES` default 2 GiB, validated at load) and
      `probe_disk_headroom(path) -> DiskHeadroom` via `os.statvfs`, returning a
      typed result (`free_bytes`, `total_bytes`, `probe_path`, `status`
      OK/DEGRADED/UNHEALTHY) and never raising past the boundary.
- [ ] `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`:
      `_refresh_mv_concurrent_with_bypass` reads
      `pg_total_relation_size('mv_identity_cluster_centroids')`, requires
      `free_bytes >= max(min_bytes, 2 * mv_bytes)`, and skips with a warning
      otherwise. The skip is observable: returns a typed outcome
      (`MvRefreshOutcome` StrEnum REFRESHED/SKIPPED_HEADROOM) and logs the
      numbers. When `ACX_PG_HEADROOM_PROBE_PATH` is unset the guard logs once
      at WARNING that headroom is unguarded and proceeds (dev/test parity).
- [ ] `apps/prototype-description-service/docker-compose.env.yml`: postgres
      healthcheck also fails when `/var/lib/postgresql/data` usage exceeds
      `ACX_PG_DISK_MAX_USED_PCT` (default 90); `api` gets an HTTP healthcheck
      on `/health` (python stdlib, no curl assumption); `worker` gets a cheap
      process-level healthcheck; `api` and `worker` mount `${ACX_PGDATA_PATH}`
      read-only at `/run/acx/pg-headroom` and set
      `ACX_PG_HEADROOM_PROBE_PATH=/run/acx/pg-headroom`.
- [ ] `apps/prototype-description-service/.env.prod.example`: document the
      three new variables.
- [ ] Tests: `shared/tests/test_disk_headroom.py` (statvfs stub, thresholds,
      missing path fails closed) and a repository test proving the refresh is
      skipped and the outcome returned when headroom is short.
- Test: `cd apps/prototype-description-service && python -m pytest shared/tests/test_disk_headroom.py recognition/tests -q -p no:cacheprovider -k "headroom or refresh_mv or cluster_repository"`

### Slice 3 — readiness surfaces headroom (integration branch, after Slices 1 and 2 merge)

- [ ] `/ready` and `/health/detailed` include a `disk_headroom` check
      (DEGRADED below threshold, never UNHEALTHY) using `shared.disk_headroom`.
- [ ] Adversarial `/wb-review-slice` on `feature/healthobs-1`; findings live
      in handoff, not here.

## Non-goals

- Caddy active health checks (no probe exists today; adding one is a separate
  edge change).
- Alerting or paging integration.
- Changing `restart:` policies or postgres tuning.
- Any GPU or describe-adapter work (tracked under the DEMOGATE / GPU flip).

## Verification plan

- Lane suites above, run remotely by the lane and re-run locally by the
  coordinator before `record_event(test_result)`.
- `scripts/deploy/tests` under `LC_ALL=C`.
- Manual on the VM after deploy: stop `acx-prod-postgres-1`, expect
  `curl -s -o /dev/null -w '%{http_code}' https://api.altcontext.com/health`
  to print 503 within the timeout, then start it again.

## Decisions

Recorded in handoff under `HEALTHOBS-1`; this plan links to them by id only.
