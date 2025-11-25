# Prototype Description Service

This directory contains the experimental rewrite scaffolding for the description service.  
It uses a hexagonal-inspired layout with explicit application layers and HTTP interface adapters.

## Running the API

```bash
cd apps/prototype-description-service
pyenv install 3.11.9  # if you don't have it yet
pyenv virtualenv 3.11.9 description-service
pyenv shell description-service
pip install -e .
uvicorn api.main:app --reload
```

### Database (Dockerized Postgres + pgvector)

A disposable Postgres instance is bundled via Compose so every developer has the
same schema/extension setup:

```bash
cd apps/prototype-description-service
docker compose -f docker-compose.db.yml down -v
docker compose -f docker-compose.db.yml up -d postgres   # start container (reads PGxxx vars from .env)
./scripts/reset_dev_db.sh                                 # drop + recreate schema with current .env credentials
```

The Compose service forwards port `55432` (`localhost:55432`) and picks up
`PGUSER/PGPASSWORD/DB_NAME` from `.env`. `reset_dev_db.sh` now drives the
container directly (creates the configured user, recreates the database,
adds pgvector, and runs Alembic) so there is no need for a host-side Postgres.
Stop it with `docker compose -f docker-compose.db.yml down`.

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

Need the real InsightFace weights on macOS/Apple Silicon? Run:

```bash
cd apps/prototype-description-service
scripts/install_insightface_mac.sh
```

It ensures Command Line Tools are configured and installs `insightface` with
the proper compiler flags before caching the models under `CACHE_BASE`.

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
