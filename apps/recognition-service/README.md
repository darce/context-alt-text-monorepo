# Recognition Service

InsightFace-only FastAPI service that powers Context Alt Text's face detection, embedding, and roster matching. This document consolidates all instructions (local dev + Hugging Face deployment) and supersedes the older `recognition/README.md`.

---

## License

MIT License - see [LICENSE](../../LICENSE) file for details.

**Key Points:**

- ✅ Commercial use permitted
- ✅ Modification and redistribution allowed
- ✅ Can include other MIT-licensed libraries
- ⚠️ No warranty or liability

---

## 1. Architecture Overview

```
Clients (WordPress plugin, CLI, HF Space ingress)
        │
        ▼
FastAPI app (/api/v0/analyze-scene, /embeddings, /service/info, /health, /roster)
        │
        ▼
SceneAnalysisService ──► FaceRecognitionService (InsightFace) ──► EmbeddingRouter
        │                        │
        │                        └─ InsightFaceAdapter (SCRFD + ArcFace)
        └─ YOLOAdapter / Phi3CaptionAdapter (caption disabled for MVP)

RosterService ──► PostgreSQL (pgvector) roster storage
StartupManager ──► warms InsightFace + embeddings cache
```

- **Recognition only** for MVP: InsightFace `buffalo_l` model (detection + embeddings) with cosine similarity roster matching.
- **REST contract** preserved: WordPress client calls the same endpoints, now returning JSON payloads defined in `api/examples/`.
- **Tests** live under `tests/`; `test_api_contract.py` validates DTO examples consume the same JSON fixtures as the plugin.

### Architecture Pattern

The service retains a ports-and-adapters (hexagonal) structure:

- **Ports (interfaces)** live in `analysis/ports` and `recognition_core/domain/interfaces.py`.
- **Adapters** implement those ports (YOLO object detector, Phi-3 caption generator, InsightFace recognition, embedding router).
- **Core services** (e.g., `SceneAnalysisService`, `FaceRecognitionService`) orchestrate the adapters and expose domain logic to FastAPI routes.

Swapping inference models now requires implementing a new adapter that satisfies the relevant port—no changes to the API layer or orchestration classes. Captioning and recognition can evolve independently by introducing additional adapters and registering them through the startup factory.

---

## 2. Local Quickstart (Recognition Only)

```bash
cd apps/recognition-service

# 1. Pin pyenv to Python 3.10.17 so `python` resolves correctly
pyenv virtualenv 3.10.17 recognition-service-env   # create once
pyenv shell recognition-service-env                # activate for current session

# 2. Install dependencies and launch the API (Apple Silicon helper included)
./scripts/start_recognition_local.sh start

# Optional: skip dependency installation on subsequent runs
SKIP_INSTALL=1 ./scripts/start_recognition_local.sh start

# Optional: override defaults
# HOST=127.0.0.1 PORT=8000 LOCAL_CACHE_ROOT=/Volumes/Butter ./scripts/start_recognition_local.sh start

# Stop the service (best effort)
./scripts/start_recognition_local.sh stop
```

Offline starts are supported: the helper skips dependency installation when `pypi.org` is unreachable so previously provisioned environments boot without a network connection. Use `FORCE_INSTALL=1 ./scripts/start_recognition_local.sh install` to retry once you are back online (set `ASSUME_OFFLINE=1` to simulate the offline branch during testing).

Verify the endpoints (examples in `api/examples/`):

- `POST http://localhost:7860/api/v0/analyze-scene`
- `POST http://localhost:7860/api/v0/embeddings`
- `GET  http://localhost:7860/api/v0/service/info`
- `GET  http://localhost:7860/api/v0/health`

You can run the automated smoke tests without launching uvicorn separately:

```bash
pytest tests/integration/test_api_endpoints.py -q
```

InsightFace weights download on first run. Adjust model/device/thresholds in `recognition_core/config/settings.yaml` or override via `RECOG_SETTINGS`.

---

## 3. Database Setup & Persistence

**This service requires PostgreSQL 17+ with pgvector extension.**

The recognition service uses PostgreSQL with pgvector for high-performance vector similarity search. SQLite is not supported.

### PostgreSQL Setup

```bash
# Install PostgreSQL 17 with pgvector (macOS)
brew install postgresql@17 pgvector

# Start PostgreSQL
brew services start postgresql@17

# Create database
createdb recognition

# Enable pgvector extension
psql recognition -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Set environment variable
export DATABASE_URL="postgresql://localhost:5432/recognition"
```

### Run Migrations

```bash
cd apps/recognition-service
alembic upgrade head
```

The database schema includes:

- **Tenants** - Multi-tenant isolation
- **Roster Entries** - Face identities with metadata
- **Reference Embeddings** - Original face embeddings (pgvector VECTOR(512))
- **Augmented Embeddings** - Additional training data from confirmations
- **HNSW Index** - Fast approximate nearest neighbor search

### Environment Variables

```bash
# Required
export DATABASE_URL="postgresql://localhost:5432/recognition"

# Optional
export DEFAULT_TENANT_ID="00000000-0000-0000-0000-000000000001"
```

### Production Setup (PostgreSQL + pgvector with Docker)

For production deployments with Docker Compose:

#### Docker Compose Setup

Create `docker-compose.db.yml`:

```yaml
version: "3.9"
services:
  db:
    image: pgvector/pgvector:pg17
    container_name: recognition_db
    environment:
      POSTGRES_USER: recognition_user
      POSTGRES_PASSWORD: strong_password_here
      POSTGRES_DB: recognition
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "recognition_user"]
      interval: 5s
      timeout: 3s
      retries: 10
    volumes:
      - ./db/init:/docker-entrypoint-initdb.d
      - recognition_pgdata:/var/lib/postgresql/data
volumes:
  recognition_pgdata: {}
```

Create `db/init/001-extensions.sql`:

```sql
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector for native ANN search
```

Start PostgreSQL:

```bash
# Start database
docker compose -f docker-compose.db.yml up -d

# Wait for healthy status
docker compose -f docker-compose.db.yml ps

# Update .env to use PostgreSQL
# DATABASE_URL=postgresql+psycopg://recognition_user:strong_password_here@localhost:5432/recognition

# Apply migrations
alembic upgrade head

# Verify extensions
psql "postgresql://recognition_user:strong_password_here@localhost:5432/recognition" \
  -c "SELECT extname, extversion FROM pg_extension;"
```

#### Option B: macOS Homebrew PostgreSQL

```bash
# Install PostgreSQL 17 + pgvector
brew install postgresql@17 pgvector

# Add to ~/.zshrc (required for PATH)
echo 'export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Start PostgreSQL service
brew services start postgresql@17

# Create database
createdb recognition

# Enable extensions
psql -d recognition << EOF
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;
EOF

# Update .env
# DATABASE_URL=postgresql+psycopg://$(whoami)@localhost:5432/recognition

# Apply migrations
alembic upgrade head
```

#### Option C: Managed PostgreSQL (Production)

Recommended providers with pgvector support:

- **AWS RDS PostgreSQL** - Enable pgvector extension via parameter groups (PostgreSQL 15+)
- **Google Cloud SQL PostgreSQL** - pgvector available in PostgreSQL 15+
- **Supabase** - Built-in pgvector support (PostgreSQL 15+)
- **Neon** - Serverless PostgreSQL with pgvector (PostgreSQL 16+)
- **Azure Database for PostgreSQL** - Flexible Server with pgvector (PostgreSQL 16+)

Setup steps:

1. Provision PostgreSQL 15+ instance (17 recommended for best vector performance)
2. Enable pgvector extension via provider console
3. Create database user with appropriate permissions
4. Set `DATABASE_URL` environment variable
5. Run `alembic upgrade head` from deployment pipeline
6. Configure connection pooling (pgBouncer recommended)

**PostgreSQL provides:**

- ✅ Native vector similarity search (HNSW/IVFFLAT indexes)
- ✅ Scales to millions of embeddings
- ✅ Sub-20ms query latency for large rosters (sub-5ms with PostgreSQL 16+ HNSW)
- ✅ Row-level security for multi-tenancy
- ✅ Materialized views for aggregate embeddings
- ✅ Point-in-time recovery and automated backups

### Database Schema

The service uses a progressive learning architecture:

```text
tenants
├── roster_entries (people/brands)
│   ├── reference_embeddings (curated onboarding images)
│   └── augmented_embeddings (progressive learning from confirmations)
└── [future: subscriptions, usage_counters, api_keys]
```

**Key features:**

- **Progressive Learning**: Each WordPress confirmation adds an augmented embedding
- **Quality Tiers**: Embeddings weighted by quality (high/medium/low)
- **Aggregate Embeddings**: Weighted average computed from reference + augmented
- **Idempotency**: `observation_id` prevents duplicate confirmations
- **Multi-tenant**: All tables include `tenant_id` for isolation

### Database Migrations (Alembic)

```bash
# Check current migration status
alembic current

# Show migration history
alembic history

# Apply all pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Create new migration (after schema changes in db/models.py)
alembic revision -m "description of changes"

# Auto-generate migration from model changes
alembic revision --autogenerate -m "auto-generated changes"

# Recreate local database (drop ➜ create ➜ migrate)
psql -h "${PGHOST:-localhost}" \
     -p "${PGPORT}" \
     -U "${PGUSER}" \
     -d postgres \
     -c "DROP DATABASE IF EXISTS \"${DB_NAME}\";"

psql -h "${PGHOST:-localhost}" \
     -p "${PGPORT}" \
     -U "${PGUSER}" \
     -d postgres \
     -c "CREATE DATABASE \"${DB_NAME}\";"

alembic upgrade head
```

**Migration files**: `db/migrations/versions/`
**Configuration**: `alembic.ini` (reads `DATABASE_URL` from environment)

### Environment Configuration

The service requires `DATABASE_URL` to be set:

```bash
# PostgreSQL (local)
DATABASE_URL=postgresql+psycopg://localhost:5432/recognition

# PostgreSQL (local Docker)
DATABASE_URL=postgresql+psycopg://recognition_user:password@localhost:5432/recognition

# PostgreSQL (production - use connection string from provider)
DATABASE_URL=postgresql+psycopg://user:pass@db.provider.com:5432/dbname?sslmode=require
```

Add to `.env` file (never commit credentials):

```bash
# Database (REQUIRED)
DATABASE_URL=postgresql://localhost:5432/recognition

# Tenant ID (optional, defaults to system tenant)
DEFAULT_TENANT_ID=00000000-0000-0000-0000-000000000001

# Database pooling
DB_POOL_MIN=5
DB_POOL_MAX=10

# pgvector tuning
PGVECTOR_LISTS=100
HNSW_M=16
HNSW_EF_CONSTRUCTION=64
```

### Database Backup & Recovery

**PostgreSQL:**

```bash
# Backup
pg_dump "postgresql://user:pass@host:5432/recognition" > backup.sql

# Restore
psql "postgresql://user:pass@host:5432/recognition" < backup.sql

# Use managed service automated backups + PITR in production
```

### Troubleshooting

| Issue                            | Solution                                                                 |
| -------------------------------- | ------------------------------------------------------------------------ |
| `alembic: command not found`     | Run `pyenv shell recognition-service-env` first                          |
| `No 'script_location' key found` | Run `alembic` commands from `apps/recognition-service/`                  |
| PostgreSQL connection refused    | Verify service running: `docker compose ps` or `brew services list`      |
| `relation does not exist`        | Run `alembic upgrade head` to create tables                              |
| pgvector extension missing       | Install: `brew install pgvector` or use `pgvector/pgvector` Docker image |
| `DATABASE_URL not set`           | PostgreSQL is required; set `DATABASE_URL` environment variable          |

---

For detailed setup guides, see:

- `docs/tasks/db-install-and-production-guide.md` - Complete operational guide
- `docs/tasks/backend-recognition-persistence-plan.md` - Architecture decisions
- `docs/tasks/backend-clustering-persitence-tasks.md` - Implementation roadmap

---

## 4. Deploying to Hugging Face Spaces (Recognition MVP)

Only the recognition stack ships today. Caption generation will be enabled later.

1. **Create a Docker Space**

```bash
huggingface-cli repo create <user>/context-alt-text-recognition --type space --sdk docker
```

1. **Push the app**

```bash
git remote add hf https://huggingface.co/spaces/<user>/context-alt-text-recognition
git push hf main
```

1. **Configure environment variables**

   - `RECOG_SETTINGS` (optional) to point at a custom settings file.
   - Any private Hugging Face tokens if you pull gated weights.

1. **Smoke-test the deployment** using the same four endpoints above. Share the Space URL with the WP team only after `/api/v0/health` and `/api/v0/service/info` succeed.

---

## 4. Configuration (Pydantic Settings)

`recognition_core/config/__init__.py` loads `recognition_core/config/settings.yaml` (override via `RECOG_SETTINGS`). Key sections:

```yaml
insightface:
  model_name: "deepinsight/insightface-scrfd-arcface-w600k"
  device: "auto" # auto, cpu, cuda, mps
  cache_dir: "/tmp/insightface_models"

recognition:
  default_threshold: 0.45
  max_faces_per_image: 10

embedding_router:
  auto_reload: true
  reload_interval: 30

cache:
  hf_home: null
  hf_datasets_cache: null
  torch_home: null

caption_generator:
  type: phi3 # options: phi3, mock, or custom
  config:
    model_id: microsoft/Phi-3.5-vision-instruct
    device: auto
    class_path: null
# Example custom adapter (optional)
# caption_generator:
#   type: custom
#   class_path: "analysis.adapters.openai_caption_adapter.OpenAICaptionAdapter"
#   config:
#     init_kwargs:
#       api_key: "${OPENAI_API_KEY}"
#       model: "gpt-4o-mini"
```

Flash Attention + caption models are still in the tree for future phases (see the “Flash Attention Configuration” section below), but they are disabled by default.

Cache directories (`HF_HOME`, `HF_DATASETS_CACHE`, `TORCH_HOME`) default to subfolders inside `apps/recognition-service/.cache/` (`huggingface/`, `datasets/`, `torch/`). Override them in `settings.yaml` (`cache.*`) or via environment variables if you want to persist caches elsewhere. The startup helper ensures the directories exist so a plain `uvicorn app:app --reload` succeeds without additional setup.

---

## 5. API Reference (JSON version)

All DTO examples live in `api/examples/`.

| Endpoint                     | Description                                                                                              |
| ---------------------------- | -------------------------------------------------------------------------------------------------------- |
| `POST /api/v0/analyze-scene` | Accepts `AnalyzeSceneRequest` JSON and returns a full scene context (objects, entities, roster matches). |
| `POST /api/v0/embeddings`    | Returns embeddings + similarity matches for a single image (supports roster onboarding).                 |
| `GET /api/v0/service/info`   | Model metadata (model name, device, thresholds, loaded entities).                                        |
| `GET /api/v0/health`         | Lightweight readiness check.                                                                             |
| `/api/v0/roster/*`           | Roster CRUD + sync (see historical docs under `recognition_core/README` for legacy details).             |

Use the JSON fixtures under `api/examples/` when wiring the WordPress client and contract tests.

### Roster API Notes

- `POST /api/v0/roster` accepts JSON payloads containing precomputed embeddings (obtained via `/api/v0/embeddings`). Each successful call recomputes the aggregate embedding and persists it for the recognition service.
- `POST /api/v0/roster/{unique_id}/embeddings` appends a new reference embedding to an existing identity. Additional embeddings are averaged, which typically reduces noise and improves InsightFace match confidence.
- `DELETE /api/v0/roster/{unique_id}` removes an identity and the embedding store is refreshed immediately so subsequent recognition calls pick up the change.

### Health & Operations

- `GET /api/v0/health` provides a lightweight readiness probe suitable for load balancers, ELB targets, or Kubernetes liveness/readiness checks.
- `GET /api/v0/service/info` returns detailed runtime metadata (model name, device, thresholds, loaded roster counts) for dashboards and incident triage.
- `POST /api/v0/service/reload-embeddings` hot-reloads roster data; call it from automation after out-of-band roster updates to confirm the cache refresh path.

Container health checks can curl the readiness endpoint directly:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/api/v0/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

Monitoring systems ingesting JSON (Prometheus pushgateway sidecars, lightweight cron jobs, etc.) can re-use these endpoints without additional dependencies. For smoke testing, run `pytest tests/integration/test_api_endpoints.py -v` and `pytest tests/unit/test_scene_analysis_service.py -v` after setting `CACHE_DIR` so the service can locate model caches.

---

## 6. Development Guide

### Dependency management (pip-tools)

- Install pip-tools once per environment: `python -m pip install pip-tools`.
- Sync the local runtime + dev tooling with `./scripts/sync_local_env.sh`. The helper:
  - Invokes `scripts/install_insightface_mac.sh` automatically on Apple Silicon so `insightface` builds with the correct SDK headers.
  - Runs `pip-sync requirements_local.txt requirements_local_dev.txt`, keeping the virtualenv aligned with the checked-in requirement files.
- Pass alternative requirement files if needed (for example, `./scripts/sync_local_env.sh requirements_remote_main.txt`). The script validates paths relative to `apps/recognition-service/` before delegating to `pip-sync`.

`pip install -r …` continues to work for ad-hoc installs, but the pip-tools flow is preferred because it removes packages that are no longer declared and catches version drift earlier.

### Running Tests

```bash
# ensure pyenv env is active
pyenv shell recognition-service-env

# run core integration + unit tests
pytest tests/integration/test_api_endpoints.py -v
pytest tests/unit/test_scene_analysis_service.py -v
```

### Hexagonal Layout

- `analysis/services/scene_analysis_service.py` – orchestrates YOLO + recognition, outputs `SceneContext`.
- `recognition_core/services/face_recognition_service.py` – wraps InsightFace adapter + embedding router.
- `recognition_core/adapters/insightface_adapter.py` – detection + embeddings.
- `recognition_core/adapters/embedding_router_adapter.py` – cosine similarity over PostgreSQL-backed roster embeddings.
- `recognition_core/domain/interfaces.py` – ports (`RecognitionModelPort`, `EmbeddingRouterPort`, `RecognitionServicePort`).
- `api/routes/main.py` – JSON-first REST surface consumed by the plugin.

Remove of legacy multi-model stack completed; only InsightFace code remains.

## 7. Flash Attention & Captioning (Deferred)

Flash Attention 2 is available for the Phi-3.5 caption pathway. It remains disabled until we switch the caption service on.

```yaml
caption_generator:
  config:
    model_settings:
      flash_attention:
        enabled: false
        force_disable_devices: ["cpu", "mps"]
```

To experiment locally, enable Flash Attention in settings and install the wheel referenced in the Dockerfile snippet (CUDA-only).

## 8. Troubleshooting

| Issue                                | Fix                                                                                                                      |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `python` points to wrong interpreter | Run `pyenv shell recognition-service-env` before pip/pytest.                                                             |
| InsightFace download fails           | Check network access; run a one-off `python -c "import insightface; app=insightface.app.FaceAnalysis(); app.prepare()"`. |
| No roster matches                    | Confirm PostgreSQL is reachable, migrations are up to date (`alembic upgrade head`), and the roster contains embeddings. |
| CUDA errors                          | Force CPU via `insightface.device: "cpu"` in settings.                                                                   |

## 9. Roadmap Hooks

- WordPress plugin consumes the JSON DTOs defined here; keep `api/examples/` in sync with frontend fixtures.
- Hugging Face deployment runs the same Docker image; maintain parity between local and remote configs.
- Caption generation, Flash Attention, and multi-model extensions are deferred until after MVP recognition stability.

## 10. Legacy README

The older `recognition_core/README.md` has been superseded by this document and will be removed in a future cleanup to avoid drift.
