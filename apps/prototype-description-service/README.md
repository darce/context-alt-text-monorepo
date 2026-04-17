# Prototype Description Service

This directory contains the experimental rewrite scaffolding for the description service.  
It uses a hexagonal-inspired layout with explicit application layers and HTTP interface adapters.

## Running the API

```bash
cd apps/prototype-description-service
pyenv install 3.12.7  # if you don't have it yet
pyenv virtualenv 3.12.7 description-service
pyenv activate description-service  # optional interactive shell convenience
pip install -e ".[dev]"
uvicorn api.main:app --reload
```

For non-interactive harnesses and scripted commands, the canonical runtime selector is `PYENV_VERSION=description-service`; use `pyenv exec` only when the command launches Python directly.

### Face Detection (InsightFace)

Face detection requires InsightFace which has platform-specific installation:

**Linux x86_64** (including Hugging Face Spaces):

```bash
pip install -e ".[face]"      # CPU
pip install -e ".[gpu]"       # GPU (CUDA)
```

**macOS Apple Silicon**:

```bash
# InsightFace requires compilation with correct SDK paths
./scripts/install_insightface_mac.sh
pip install -e ".[dev]"
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

Need alternative instructions (manual psql workflow)? See
[`db/README.md`](db/README.md).

Need a repeatable local startup helper? Use `scripts/start_prototype_local.sh`:

```bash
cd apps/prototype-description-service
scripts/start_prototype_local.sh start
```

The script mirrors the recognition service helper (installs the editable
package with dev extras, sources `.env`, enforces the cache paths, and
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
TRANSFORMERS_CACHE=/Volumes/Butter/cache/huggingface_cache
HF_HUB_CACHE=/Volumes/Butter/cache/huggingface_cache
TORCH_HOME=/Volumes/Butter/cache/torch
YOLO_CONFIG_DIR=/Volumes/Butter/cache/yolo
MPLCONFIGDIR=/Volumes/Butter/cache/matplotlib
INSIGHTFACE_CACHE_DIR=/Volumes/Butter/cache/insightface
INSIGHTFACE_HOME=/Volumes/Butter/cache/insightface
```

### Production / Hugging Face Spaces

Match the archived service’s Dockerfile so caches live inside the container at
`/data/cache` (set these via deployment env vars or your platform’s secrets):

```bash
CACHE_BASE=/data/cache
HF_HOME=/data/cache/huggingface_cache
TRANSFORMERS_CACHE=/data/cache/huggingface_cache
HF_HUB_CACHE=/data/cache/huggingface_cache
TORCH_HOME=/data/cache/torch
YOLO_CONFIG_DIR=/data/cache/yolo
MPLCONFIGDIR=/data/cache/matplotlib
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

### Available health endpoints

| Endpoint                  | Description                            |
| ------------------------- | -------------------------------------- |
| `GET /health`             | Aggregated status for every subsystem. |
| `GET /recognition/health` | Recognition subsystem health probe.    |
| `GET /roster/health`      | Roster subsystem health probe.         |
| `GET /scene/health`       | Scene analysis subsystem health probe. |

Each endpoint currently returns a static `"ok"` status. They are intended as integration points for future database, pgvector, or model checks.
