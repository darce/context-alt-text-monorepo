# Prototype Description Service

This directory contains the experimental rewrite scaffolding for the description service.  
It uses a hexagonal-inspired layout with explicit application layers and HTTP interface adapters.

## Running the API

```bash
cd apps/prototype-description-service
uv python install 3.12.7  # if you don't have it yet
uv sync --locked --extra dev
uv run --locked --extra dev uvicorn api.main:app --reload
```

The checked-in `.python-version` pins the interpreter to Python 3.12.7, while `uv` manages the project-local `.venv` from `uv.lock`.

### Face Detection (InsightFace)

Face detection requires InsightFace which has platform-specific installation:

**Linux x86_64** (including Hugging Face Spaces):

```bash
uv sync --locked --extra dev --extra face      # CPU
uv sync --locked --extra dev --extra gpu       # GPU (CUDA)
```

**macOS Apple Silicon**:

```bash
# InsightFace requires compilation with correct SDK paths
uv sync --locked --extra dev
./scripts/install_insightface_mac.sh
```

Without InsightFace installed, the service falls back to stub detectors that generate synthetic embeddings (useful for testing, not production).

### Database (Local PostgreSQL reset contract)

The default local reset path targets a local PostgreSQL instance on
`localhost:5432` and uses the credentials from `.env`:

```bash
cd apps/prototype-description-service
cp .env.example .env
make postgres-start   # starts Homebrew PostgreSQL if needed
make reset            # bootstraps .env on first run, recreates DB, runs Alembic
```

The checked-in `.env.example` already publishes the canonical local
`PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`DB_NAME` contract. `make reset`
exports `ALLOW_DEV_DB_RESET=1` for the destructive local reset, while direct
`./scripts/reset_dev_db.sh` usage still requires you to opt in explicitly.

If `.env` is missing, the reset script bootstraps it from `.env.example` before
continuing. The script then verifies local mode, recreates the configured
database and role, enables `pgvector`, and runs Alembic migrations.

An optional disposable Compose database is still available via
`docker-compose.db.yml`, but it is not the default reset path. If you use it,
set `PGPORT=55432` in `.env` before running the reset so the script targets the
container instead of the native local server:

```bash
cd apps/prototype-description-service
cp .env.example .env
docker compose -f docker-compose.db.yml up -d postgres
PGPORT=55432 make reset
```

Stop the container with `docker compose -f docker-compose.db.yml down`.

#### Local vs remote reset — when to use each

The local Postgres reset above (`make reset` from this directory, or
`make reset-local WP_PATH=...` from the repo root) only touches your local
development DB. **Use it when** you want to wipe the database your local
description service is talking to.

For OCI environments, the equivalent operator workflow is `make reset-remote
ENV=<dev|staging|prod> CONFIRM_REMOTE_RESET=RESET`, documented in
[infra/oci/README.md](../../infra/oci/README.md#destructive-remote-reset).
**Use it when** you want to wipe the database that backs `acx-dev`,
`acx-staging`, or `acx-prod` on the OCI VM. The remote workflow uses `/ready`
(not `/health`) for verification and runs a post-reset bootstrap to recreate
one usable service-mode dev API key.

Don't cross the streams: `make reset-local` does not touch OCI; `make
reset-remote` does not touch your local DB.

After either reset, prove plugin connectivity end-to-end with
[`docs/operations/reset-smoke-runbook.md`](../../docs/operations/reset-smoke-runbook.md)
(post-reset key handoff → plugin selector mode → workbench probe → captured
proof). That runbook is the standing procedure for both smoke directions.

Need alternative instructions (manual psql workflow)? See
[`db/README.md`](db/README.md).

Need a repeatable local startup helper? Use `scripts/start_prototype_local.sh`:

```bash
cd apps/prototype-description-service
scripts/start_prototype_local.sh start
```

The script mirrors the recognition service helper (installs the editable
package from `uv.lock`, sources `.env`, enforces the cache paths, and
manages the uvicorn lifecycle).

## Cache Configuration

The recognition pipeline downloads sizable model assets (InsightFace, HuggingFace,
Torch, YOLO, etc.). To avoid polluting your primary disk we keep all caches on an
external drive during local development and mirror the production cache layout
from the archived recognition service.

### Local development

Populate `.env` (or export shell vars) with the paths below so every cache sits
under `/Volumes/Butter`:

```bash
CACHE_BASE=/Volumes/Butter/cache
HF_HOME=/Volumes/Butter/cache/huggingface_cache
HF_HUB_CACHE=/Volumes/Butter/cache/huggingface_cache
TORCH_HOME=/Volumes/Butter/cache/torch
YOLO_CONFIG_DIR=/Volumes/Butter/cache/yolo
INSIGHTFACE_CACHE_DIR=/Volumes/Butter/cache/insightface
INSIGHTFACE_HOME=/Volumes/Butter/cache/insightface
```

### Production / Hugging Face Spaces

Match the archived service’s Dockerfile so caches live inside the container at
`/data/cache` (set these via deployment env vars or your platform’s secrets):

```bash
CACHE_BASE=/data/cache
HF_HOME=/data/cache/huggingface_cache
HF_HUB_CACHE=/data/cache/huggingface_cache
TORCH_HOME=/data/cache/torch
YOLO_CONFIG_DIR=/data/cache/yolo
INSIGHTFACE_CACHE_DIR=/data/cache/insightface
INSIGHTFACE_HOME=/data/cache/insightface
```

Any InsightFace/HuggingFace clients we add inherit these settings automatically.

## Development Commands

This project uses a Makefile for common development tasks:

```bash
# Run all checks (lint + typecheck + test)
make check

# Run linting only
make lint

# Run type checking only
make typecheck

# Auto-fix formatting and linting issues
make format

# Run tests only
make test

# Format, typecheck, and test (for CI)
make ci

# Reset the local database
make reset

# Install dependencies
make install

# Clean cache files
make clean

# Show all available commands
make help
```

### Admin console (local `/admin` tenant management)

The env-gated operator `/admin` console (create tenants, mint/revoke API keys)
is off by default. These targets wrap `scripts/admin_dev.sh` to bring it up
locally and exercise it — no Tailscale or compose overlay needed (that path is
prod-only; see [the runbook](../../docs/runbooks/admin-tenant-keys.md)).

```bash
# Enable admin in .env (sets RECOGNITION_ADMIN_ENABLED=true + generates a
# >=32-char RECOGNITION_ADMIN_TOKEN if missing), start the service, wait for
# /admin, open the browser console, and print the token.
make admin-dev

# JSON smoke harness against the admin API:
# create tenant -> re-upsert -> mint key -> list -> revoke -> idempotent re-revoke,
# plus an unauthenticated-request-is-401 check. Exits non-zero on any failure.
make admin-test

make admin-token    # print the current admin token (stdout)
make admin-open     # open the /admin console in a browser
make admin-status   # print reachability: down | up_no_admin | up_admin
make admin-down     # stop the local service
```

The console is served at **`http://localhost:8000/admin/`** (trailing slash).
Authenticate with HTTP Basic: **username = anything, password = the admin
token** (`make admin-token`). Programmatic callers send `X-Admin-Token: <token>`
instead. `admin_dev.sh` honors `PORT`, `ADMIN_DEV_HOST`,
`ADMIN_DEV_READY_TIMEOUT`, and `ADMIN_DEV_NO_OPEN=1` (skip auto-open).

### Available health endpoints

- `GET /health` — Liveness probe (PR-01). No I/O; returns `{status: "ok", timestamp}` as long as the process can respond. Used by the Caddy active probe on a 10s interval.
- `GET /ready` — Readiness probe (PR-01). Runs DB (via the observability session dependency), session-dependency circuit breaker, and InsightFace model-cache checks and aggregates them. Returns 200 when all pass; 503 with `status: "unhealthy"` otherwise so load balancers can pull the pod.
- `GET /health/detailed` — Auth-gated operator diagnostic (PA-01 / Slice 2.5). Returns full `get_pool_stats` for both engines, circuit-breaker state, and InsightFace model-cache inventory. Requires a valid API key via the `Authorization` header.

The previous per-subsystem probes (`/recognition/health`, `/recognition/health/pool`, `/roster/health`, `/scene/health`) were consolidated into the three endpoints above in Slice 2.5; pool stats now live on `/health/detailed`.
