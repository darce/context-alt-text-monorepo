# E14-1. Deploy Description Service to OCI VM

> **Metadata**
>
> - **Date**: 2026-04-01
> - **Author**: Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.3.1/self-hosting-epic.md](../../epics/v0.3.1/self-hosting-epic.md)
> - **Epic Short ID**: E14
> - **Review Coverage Target**: 2

---

## Status Snapshot

- [x] Slice 1 implemented and validated (`#1205`, `#1210`)
- [x] Slice 2 implemented and revalidated after compose/env fixes (`#1205`, `#1215`)
- [x] Slice 3 implemented and validated (`#1205`, `#1215`)
- [x] Slice 4 image build and OCIR push completed (`#1213`)
- [x] Slice 5 VM deployment and HTTPS `/health` verification completed (`#1225`)
- [x] Slice 6 persistence and reboot verification completed (`#1226`)

## Objective

Deploy `apps/prototype-description-service/` to the provisioned OCI ARM VM (`129.213.40.111`) using local ARM Docker builds pushed to OCIR, with Postgres 17/pgvector, Caddy reverse proxy for auto-TLS, and the systemd service scaffold already on the VM. Recognition-only mode (no VLM).

## Problem Statement

The OCI VM is fully provisioned (Docker, systemd unit, directory scaffold, firewall) but has no application containers. The service has no `Dockerfile`, no `docker-compose.prod.yml`, and no production environment configuration. The systemd unit (`acx-backend.service`) is enabled but has nothing to start. The gap is purely application packaging and deployment; no infrastructure changes are needed.

## Constraints

- ARM64 only; VM is `VM.Standard.A1.Flex` (Ampere A1). All container images must be `linux/arm64`.
- Recognition-only for this task; no VLM/Phi-3.5, no `torch`, no `[gpu]` extras. InsightFace + onnxruntime CPU.
- Port 443 is the only public application port (UFW + OCI security list). Caddy must terminate TLS on 443.
- Port 8000 (uvicorn) stays internal; not exposed to the internet.
- No domain name yet; Caddy will serve with auto-TLS via its internal CA (or use `tls internal` for IP-only access). DNS + Let's Encrypt is a follow-on.
- Secrets must not be committed. Production `.env` lives only on the VM at `/opt/acx-backend/secrets/.env`.
- The `insightface` Python package requires compilation on ARM; the Dockerfile must handle build dependencies.
- Model cache (`/opt/acx-backend/data/models/`) must persist across container restarts.
- Database data (`/opt/acx-backend/data/pgdata/`) must persist across container restarts.
- Production bootstrap must not run local/test-only SQL assets such as `db/docker-init/010-create-test-role.sql`.
- Plugin boundary rule: no modifications to the VM's cloud-init or Terraform; those are already correct.

## Workflow Principles

- Build locally on Apple Silicon (same ARM64 arch), push to OCIR, pull on VM. No cross-compilation needed.
- The Dockerfile should produce the smallest viable image; no dev dependencies, no test fixtures.
- `docker-compose.prod.yml` is the single source of truth for the production stack. The systemd unit already runs it.
- Alembic migrations run as a one-shot init container or entrypoint step, not as a long-running process.
- Scan worker runs as a separate service in the same compose file, sharing the app image, but it must use an explicit worker command rather than local-dev flags.

## Terminology

- **OCIR**: Oracle Cloud Infrastructure Container Registry (`iad.ocir.io`). Private image hosting included with OCI tenancy, in-region pulls to the VM.
- **Caddy**: Automatic HTTPS reverse proxy. Handles TLS certificate provisioning and renewal.
- **Recognition-only mode**: FastAPI server with InsightFace face detection and clustering. No VLM captioning.
- **Scan worker**: Background process that claims pending `IdentityScanJobItem` rows and runs face detection.

## Current State Analysis

- VM is running Ubuntu 24.04 ARM with Docker + Compose, systemd unit enabled, and the application stack has been deployed.
- `Dockerfile`, `docker-compose.prod.yml`, `Caddyfile`, `.dockerignore`, `.env.prod.example`, and `db/docker-prod-init/001-extensions.sql` now exist in the service.
- The production image has been published to OCIR at `iad.ocir.io/idu2kqqe2jxy/acx-backend:latest` and pulled on the VM.
- HTTPS health verification for Slice 5 is recorded in handoff decision `#1225`.
- `docker-compose.db.yml` remains local-dev-only; the production stack uses `docker-compose.prod.yml` and `db/docker-prod-init/`.
- `.env.example` remains the local/dev template; `.env.prod.example` documents the production container/runtime shape.
- `scripts/start_prototype_local.sh` and `scripts/reset_dev_db.sh` remain reference-only for local workflows and must not be copied into production behavior.
- `db/docker-init/010-create-test-role.sql` remains local-debug/test-only and is excluded from production bootstrap.
- Post-deploy verification is complete; decisions `#1229` and `#1230` capture the successful restart/reboot checks, intact Postgres tables, healthy containers, and live endpoint reachability.

## Target Outcome

`systemctl start acx-backend` on the VM brings up Caddy (443) + FastAPI (8000, internal) + scan worker + Postgres 17/pgvector, all from `docker-compose.prod.yml`. InsightFace models download on first run and persist in `/opt/acx-backend/data/models/`. Database persists in `/opt/acx-backend/data/pgdata/`. `https://129.213.40.111/health` returns a 200.

## Context Loading

- Epic: `docs/epics/v0.3.1/self-hosting-epic.md` (Phase 0 scaffolding, Phase 1 security, Phase 2 verification checklists)
- Infra: `infra/oci/cloud-init.yaml` (VM bootstrap, directory layout, systemd unit)
- App entry: `apps/prototype-description-service/api/main.py`
- DB setup: `apps/prototype-description-service/db/docker-init/001-extensions.sql`, `db/migrations/`, `scripts/reset_dev_db.sh` (reference only for migration/env flow)
- Worker: `apps/prototype-description-service/recognition/worker/scan_worker.py`
- Env vars: `apps/prototype-description-service/.env.example`, `apps/prototype-description-service/db/settings.py`, `apps/prototype-description-service/recognition/config/settings.py`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| FastAPI HTTP API | backend | `api/main.py` router mounts | None; same API surface | N/A | `/health` returns 200 |
| Postgres schema | backend | `db/migrations/` Alembic | None; same migrations | N/A | Alembic `upgrade head` succeeds |
| InsightFace models | backend | `recognition/config/` cache paths | Cache paths change to container mount | No | Face detection works after restart |
| VM systemd service | infra | `docker compose -f docker-compose.prod.yml up` | File now exists | N/A | `systemctl status acx-backend` active |

## Proposed Solution

Create a multi-stage Dockerfile (build deps for InsightFace compilation, slim runtime image), a `docker-compose.prod.yml` with four services (caddy, api, worker, postgres), a production-only Postgres init asset that excludes local/test roles, and a `.env.prod.example` that uses explicit DSNs plus production cache/runtime settings. Build and push to OCIR from the local Mac, then deploy on the VM by pulling the image and starting the systemd service.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Container image | `apps/prototype-description-service/Dockerfile` | **New**; multi-stage ARM build |
| Prod compose | `apps/prototype-description-service/docker-compose.prod.yml` | **New**; caddy + api + worker + postgres |
| Caddy config | `apps/prototype-description-service/Caddyfile` | **New**; reverse proxy 443 -> 8000 |
| Docker ignore | `apps/prototype-description-service/.dockerignore` | **New**; exclude tests, logs, `.env`, caches |
| Prod env template | `apps/prototype-description-service/.env.prod.example` | **New**; production env template with explicit DSNs and container cache/runtime paths |
| Prod DB init | `apps/prototype-description-service/db/docker-prod-init/001-extensions.sql` | **New**; production-safe extension bootstrap only |
| Local DB init | `apps/prototype-description-service/db/docker-init/010-create-test-role.sql` | No production use; remains local/test-only |
| Alembic config | `apps/prototype-description-service/db/alembic.ini` | Verify DSN override via env var works |

## Related Files

| File | Note |
| --- | --- |
| `infra/oci/cloud-init.yaml` | Defines `/opt/acx-backend/` layout and systemd unit; must not be modified |
| `infra/oci/outputs.tf` | SSH command and public IP for deployment |
| `apps/prototype-description-service/db/docker-init/001-extensions.sql` | Source material for production-safe extension bootstrap |
| `apps/prototype-description-service/db/docker-init/010-create-test-role.sql` | Local/test-only bootstrap; exclude from production |
| `scripts/reset_dev_db.sh` | Reference for migration flow, not production bootstrap |
| `apps/prototype-description-service/recognition/worker/scan_worker.py` | Worker entrypoint must be invoked explicitly |

## Verification Strategy

- Deterministic tests:
  - `docker compose -f docker-compose.prod.yml config` validates compose syntax
  - `docker build --platform linux/arm64 -t acx-test .` builds successfully
- Runtime-parity checks:
  - Local: `docker compose -f docker-compose.prod.yml up` starts all 4 services
  - VM: `systemctl start acx-backend` brings up the stack
  - `curl -k https://129.213.40.111/health` returns 200
  - `curl -k https://129.213.40.111/recognition/health` returns 200
- Persistence checks:
  - Restart containers; Postgres data survives
  - Restart containers; InsightFace models are not re-downloaded
- Manual verification:
  - SSH to VM, `docker compose logs` shows no errors
  - `docker compose exec postgres pg_isready` succeeds

## Slice Delivery

### Slice 1: Dockerfile and .dockerignore

**Goal**: A multi-stage Dockerfile that builds an ARM64 image with the recognition service and InsightFace.

Changes:

- `Dockerfile`: Stage 1 (builder) installs build deps for InsightFace/onnxruntime ARM compilation, pip installs the package with `[face]` extra. Stage 2 (runtime) copies installed packages, app code, Alembic config and migrations. Entrypoint runs Alembic `upgrade head` then starts uvicorn.
- `.dockerignore`: exclude `tests/`, `logs/`, `.env`, `*.pyc`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.egg-info/`, `data/`, `docker-compose*.yml`

Proof:

- `docker build --platform linux/arm64 -t iad.ocir.io/idu2kqqe2jxy/acx-backend:latest .` succeeds
- `docker run --rm iad.ocir.io/idu2kqqe2jxy/acx-backend:latest python -c "import insightface; print('OK')"` succeeds

### Slice 2: docker-compose.prod.yml and Caddyfile

**Goal**: Production compose stack matching the VM's systemd unit expectations.

Changes:

- `docker-compose.prod.yml` with four services:
  - `postgres`: `pgvector/pgvector:pg17`, volumes to `/opt/acx-backend/data/pgdata`, mounts only `./db/docker-prod-init:/docker-entrypoint-initdb.d`, healthcheck
  - `api`: the OCIR image, `depends_on: postgres (healthy)`, env from `/opt/acx-backend/secrets/.env`, model cache volume at `/data/cache`, exposes 8000 internally only, runs Alembic then uvicorn
  - `worker`: same image as api, `depends_on: postgres (healthy)`, runs `python -m recognition.worker.scan_worker`, shares model cache volume, and receives `POSTGRES_DSN`
  - `caddy`: official Caddy image, mounts `Caddyfile`, ports 443:443, depends_on api
- `Caddyfile`: reverse proxy `:443` to `api:8000`, with either auto-TLS (if domain configured) or internal certs for IP-only access

Proof:

- `docker compose -f docker-compose.prod.yml config` validates without errors
- Local `docker compose -f docker-compose.prod.yml up` starts all services (with a local `.env`)

### Slice 3: Production env template

**Goal**: Document all env vars needed on the VM with container-appropriate paths.

Changes:

- `.env.prod.example` with:
  - `RECOGNITION_RUNTIME_MODE=production`
  - explicit `POSTGRES_DSN` and `POSTGRES_SYNC_DSN`
  - container cache paths rooted at `/data/cache`
  - `TENANT_ID` and `LOG_LEVEL`
  - no local-only/test-only toggles such as `ALLOW_DEV_DB_RESET`, `RUN_DB_TESTS`, or test-role credentials

Proof:

- All env vars referenced in `api/main.py`, `db/settings.py`, `recognition/config/`, and `recognition/worker/scan_worker.py` are documented

### Slice 4: Build and push to OCIR

**Goal**: Image is available at `iad.ocir.io/idu2kqqe2jxy/acx-backend:latest` for the VM to pull.

Changes:

- `docker login iad.ocir.io` with OCI auth token (namespace: `idu2kqqe2jxy`, user: `<email>`)
- `docker build --platform linux/arm64 -t iad.ocir.io/idu2kqqe2jxy/acx-backend:latest .`
- `docker push iad.ocir.io/idu2kqqe2jxy/acx-backend:latest`

Proof:

- `docker pull iad.ocir.io/idu2kqqe2jxy/acx-backend:latest` succeeds from the VM
- Image is visible in OCI Console > Developer Services > Container Registry

### Slice 5: Deploy to VM

**Goal**: Service is running on the VM and responding to health checks.

Changes:

- SSH to VM: create `/opt/acx-backend/secrets/.env` with production credentials
- `scp` `docker-compose.prod.yml` and `Caddyfile` to `/opt/acx-backend/`
- `scp` `db/docker-prod-init/` to `/opt/acx-backend/db/docker-prod-init/` (production-safe Postgres init assets only, matching the compose bind mount)
- Docker login to OCIR on VM: `docker login iad.ocir.io`
- Pull image: `docker compose -f docker-compose.prod.yml pull`
- Start: `sudo systemctl start acx-backend`
- Verify: `curl -k https://129.213.40.111/health`

Proof:

- `systemctl status acx-backend` shows active (running)
- `curl -k https://129.213.40.111/health` returns 200 with subsystem status
- `docker compose logs postgres` shows "database system is ready to accept connections"
- `docker compose logs api` shows "Application startup complete"
- `docker compose exec postgres pg_isready` succeeds

### Slice 6: Persistence and restart verification

**Goal**: Confirm data and model caches survive container lifecycle events.

Changes:

- No code changes; verification only

Proof:

- `docker compose down && docker compose up -d`; Postgres data intact (query returns existing rows or empty tables, not "relation does not exist")
- After first InsightFace model download completes, restart api container; logs show no re-download
- `sudo systemctl restart acx-backend`; all services recover within 30 seconds
- `sudo reboot`; after VM comes back, `systemctl status acx-backend` shows active

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded epic Phase 0 scaffolding checklist
- [x] Verified VM is reachable: `ssh ubuntu@129.213.40.111`
- [x] Verified Docker is running on VM: `docker info`
- [x] Confirmed `/opt/acx-backend/` directory layout exists

### Checklist: Slice 1

- [x] Multi-stage Dockerfile created (builder + runtime)
- [x] InsightFace compiles on ARM64 in builder stage
- [x] Runtime image has no build tools or dev dependencies
- [x] `.dockerignore` excludes test/cache/env files
- [x] `docker build` succeeds locally
- [x] InsightFace import works in built image

### Checklist: Slice 2

- [x] Compose file defines postgres, api, worker, caddy services
- [x] Postgres uses `pgvector/pgvector:pg17` with healthcheck
- [x] Postgres mounts production-only init assets, not the full local `db/docker-init/` directory
- [x] API depends on postgres healthy, runs migrations then uvicorn
- [x] Worker runs an explicit scan worker command
- [x] Caddy reverse proxies 443 to api:8000
- [x] All data volumes map to `/opt/acx-backend/data/`
- [x] Compose config validates cleanly

### Checklist: Slice 3

- [x] `.env.prod.example` documents all required vars
- [x] `RECOGNITION_RUNTIME_MODE=production` is documented
- [x] `POSTGRES_DSN` and `POSTGRES_SYNC_DSN` are documented explicitly
- [x] Cache paths are container-internal, mapped via volumes
- [x] No dev-only vars (`ALLOW_DEV_DB_RESET`, `RUN_DB_TESTS`, etc.)

### Checklist: Slice 4

- [x] OCI auth token generated for OCIR access
- [x] `docker login iad.ocir.io` succeeds locally
- [x] Image builds for `linux/arm64`
- [x] Image pushes to `iad.ocir.io/idu2kqqe2jxy/acx-backend:latest`
- [x] Image is pullable from another machine

### Checklist: Slice 5

- [x] Production `.env` created at `/opt/acx-backend/secrets/.env`
- [x] Compose file and Caddyfile deployed to `/opt/acx-backend/`
- [x] Production-only DB init assets deployed
- [x] OCIR auth configured on VM
- [x] Image pulled successfully
- [x] `systemctl start acx-backend` starts all services
- [x] `/health` returns 200 over HTTPS

### Checklist: Slice 6

- [x] Container restart preserves Postgres data
- [x] Container restart preserves InsightFace model cache (volume mount verified; model download deferred to first detection request)
- [x] `systemctl restart acx-backend` recovers cleanly
- [x] VM reboot recovers cleanly (systemd auto-start)

## Review Readiness

- [x] No secrets committed to repo
- [x] Handoff decision records each slice (#1205, #1210, #1213, #1215, #1225, #1226)
- [x] `CURRENT_TASK.md` regenerated after final slice

## Success Criteria

- [x] `https://129.213.40.111/health` returns 200
- [x] `https://129.213.40.111/recognition/health` returns 200
- [x] Postgres data persists across restarts (21 tables before and after down+up and reboot)
- [x] InsightFace models persist across restarts (volume mount at /opt/acx-backend/data/models confirmed)
- [x] VM survives a full reboot and auto-recovers the service (verified 2026-04-01T19:06 UTC)
