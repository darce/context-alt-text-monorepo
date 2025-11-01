# Context Alt Text — Database Install & Production Guide

_Last updated: 2025-01-21_

This guide shows how to stand up the database for the Recognition Service in **local development** (SQLite or PostgreSQL) and how to provision and operate it in **production** (PostgreSQL + pgvector).

**Architecture Decision:**

- **Local Development:** SQLite (zero dependencies) or PostgreSQL (Docker Compose)
- **Production:** PostgreSQL 15/16 with pgvector extension (canonical store for tenants, users, roster entities, reference embeddings, augmented embeddings, progressive learning)
- **FAISS:** Optional derived in-memory index synchronized from database (hot-reload on updates)

**Stack**

- **SQLite** (local dev): Single-file database, JSON blob storage for embeddings, no extensions required
- **PostgreSQL 15/16** (production): Canonical store with native vector similarity search via pgvector
- **pgvector** extension (vector column + HNSW/IVFFLAT ANN indexes)
- **Alembic** (Python migrations): Version-controlled schema evolution for both databases
- Optional: **pgBouncer** (connection pooling), **FAISS** (derived index for GPU/IVF-PQ acceleration)

---

## 1) Local Development

### Option A — SQLite (Zero Dependencies, Recommended for Quick Start)

**Why SQLite for local dev:**

- No external dependencies (single file: `recognition.db`)
- Identical schema to PostgreSQL (except vector columns → JSON blobs)
- Fast for small corpora (<1K embeddings)
- Perfect for unit tests and CI pipelines

**Setup:**

```bash
# No installation needed! SQLite ships with Python stdlib
python -c "import sqlite3; print(sqlite3.sqlite_version)"  # Should show 3.35+

# Create database and apply migrations
cd apps/recognition-service
alembic -c db/alembic.ini upgrade head  # Creates recognition.db and applies schema

# Verify
sqlite3 data/recognition.db ".tables"
# Expected: tenants, roster_entities, reference_embeddings, augmented_embeddings, ...
```

**Connection String:**

```
sqlite:///./data/recognition.db
```

**SQLite Schema Notes:**

- Embeddings stored as JSON text: `embedding_json TEXT NOT NULL`
- Manual cosine similarity: `1 - spatial.distance.cosine(a, b)`
- No native vector indexes (full scan for search; acceptable for <1K embeddings)
- Compatible Alembic migrations with PostgreSQL (database-specific branches)

**Limitations:**

- No row-level security (single-tenant dev environment)
- Manual similarity computation (slower for >1K embeddings)
- No HNSW/IVFFLAT indexes (use PostgreSQL for realistic performance testing)

---

### Option B — Docker Compose (PostgreSQL, Recommended for Multi-Tenant Testing)

Create `docker-compose.db.yml` at the repo root:

```yaml
version: "3.9"
services:
  db:
    image: pgvector/pgvector:pg16 # Postgres with pgvector preinstalled
    container_name: cat_db
    environment:
      POSTGRES_USER: cat_dev
      POSTGRES_PASSWORD: cat_dev_pass
      POSTGRES_DB: cat_recognition
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "cat_dev"]
      interval: 5s
      timeout: 3s
      retries: 10
    volumes:
      - ./db/init:/docker-entrypoint-initdb.d
      - cat_pgdata:/var/lib/postgresql/data
volumes:
  cat_pgdata: {}
```

Create the init script at `db/init/001-init.sql`:

```sql
-- Create extensions on first boot
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector; -- pgvector
```

Up the database:

```bash
docker compose -f docker-compose.db.yml up -d
docker compose -f docker-compose.db.yml logs -f db
```

👉 Connection URL for local dev:

```
postgresql://cat_dev:cat_dev_pass@127.0.0.1:5432/cat_recognition
```

#### (Optional) pgAdmin

Add another service to the compose file:

```yaml
pgadmin:
  image: dpage/pgadmin4
  environment:
    PGADMIN_DEFAULT_EMAIL: admin@example.com
    PGADMIN_DEFAULT_PASSWORD: admin
  ports:
    - "8080:80"
  depends_on:
    - db
```

---

### Option B — macOS (Homebrew)

```bash
brew install postgresql@16
brew services start postgresql@16

# Create database and enable extensions (pgvector must be installed; install / build if needed)
createdb cat_recognition
psql -d cat_recognition -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'
psql -d cat_recognition -c 'CREATE EXTENSION IF NOT EXISTS "citext";'
psql -d cat_recognition -c 'CREATE EXTENSION IF NOT EXISTS "pgcrypto";'
psql -d cat_recognition -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

If `CREATE EXTENSION vector;` fails, install pgvector (e.g., `brew install pgvector`) or build it from source, then retry.

---

### Apply Schema Migrations (Alembic)

**One-time setup:**

```bash
cd apps/recognition-service
pip install alembic psycopg[binary]  # PostgreSQL driver
pip install aiosqlite  # SQLite async driver (optional)

# Migrations are pre-configured under db/
# (New projects do NOT need to run `alembic init`)
```

**Configure Alembic for database-agnostic migrations:**

`db/alembic.ini`:

```ini
[alembic]
script_location = db/migrations
sqlalchemy.url = ${DATABASE_URL}  # Read from environment

[alembic:env]
# Set this in environment or .env file
# DATABASE_URL=sqlite:///./data/recognition.db  # Local
# DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/cat_recognition  # Docker
```

`db/migrations/env.py`:

```python
from alembic import context
from sqlalchemy import engine_from_config, pool
import os

config = context.config
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))

def run_migrations_offline():
    """Run migrations in 'offline' mode (generate SQL)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Run migrations in 'online' mode (execute against database)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Create baseline migration (0001):**

```bash
alembic revision -m "baseline schema: tenants, roster, embeddings"
```

Edit `db/migrations/versions/0001_baseline_schema.py`:

```python
"""baseline schema: tenants, roster, embeddings

Revision ID: 0001
Revises:
Create Date: 2025-01-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Detect database type
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # Enable extensions
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

        # Tenants table
        op.create_table(
            "tenants",
            sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("plan", sa.Text(), nullable=False, server_default="free"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id")
        )

        # Roster entities
        op.create_table(
            "roster_entities",
            sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("tenant_id", sa.UUID(), nullable=False),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("type", sa.Text(), nullable=False, server_default="person"),
            sa.Column("display_name", sa.Text(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id")
        )
        op.create_index("roster_entities_tenant_label_idx", "roster_entities", ["tenant_id", "label"])

        # Reference embeddings (curated)
        op.create_table(
            "reference_embeddings",
            sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
            sa.Column("tenant_id", sa.UUID(), nullable=False),
            sa.Column("roster_entry_id", sa.UUID(), nullable=False),
            sa.Column("embedding", sa.Text(), nullable=False),  # pgvector type added below
            sa.Column("image_path", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["roster_entry_id"], ["roster_entities.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id")
        )

        # Use raw SQL to set vector type (Alembic doesn't have native pgvector support)
        op.execute("ALTER TABLE reference_embeddings ALTER COLUMN embedding TYPE vector(512) USING embedding::vector")
        op.create_index("ref_emb_tenant_idx", "reference_embeddings", ["tenant_id"])
        op.create_index("ref_emb_roster_idx", "reference_embeddings", ["roster_entry_id"])

        # Augmented embeddings (progressive learning)
        op.create_table(
            "augmented_embeddings",
            sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
            sa.Column("tenant_id", sa.UUID(), nullable=False),
            sa.Column("roster_entry_id", sa.UUID(), nullable=False),
            sa.Column("observation_id", sa.UUID(), nullable=False),
            sa.Column("embedding", sa.Text(), nullable=False),  # pgvector type added below
            sa.Column("source", sa.Text(), nullable=False, server_default="wordpress_confirm"),
            sa.Column("attachment_id", sa.BigInteger(), nullable=True),
            sa.Column("bbox", sa.JSON(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("quality_tier", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["roster_entry_id"], ["roster_entities.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("observation_id")
        )

        op.execute("ALTER TABLE augmented_embeddings ALTER COLUMN embedding TYPE vector(512) USING embedding::vector")
        op.create_index("aug_emb_tenant_idx", "augmented_embeddings", ["tenant_id"])
        op.create_index("aug_emb_roster_idx", "augmented_embeddings", ["roster_entry_id"])
        op.create_index("aug_emb_quality_idx", "augmented_embeddings", ["quality_tier"])

    elif dialect == "sqlite":
        # SQLite: JSON blob storage for embeddings
        op.create_table(
            "tenants",
            sa.Column("id", sa.Text(), nullable=False),  # UUID as text
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("plan", sa.Text(), nullable=False, server_default="free"),
            sa.Column("created_at", sa.Text(), nullable=False),  # ISO8601 text
            sa.PrimaryKeyConstraint("id")
        )

        op.create_table(
            "roster_entities",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("type", sa.Text(), nullable=False, server_default="person"),
            sa.Column("display_name", sa.Text(), nullable=True),
            sa.Column("meta", sa.Text(), nullable=False, server_default="{}"),  # JSON as text
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id")
        )
        op.create_index("roster_entities_tenant_label_idx", "roster_entities", ["tenant_id", "label"])

        op.create_table(
            "reference_embeddings",
            sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("roster_entry_id", sa.Text(), nullable=False),
            sa.Column("embedding_json", sa.Text(), nullable=False),  # JSON array as text
            sa.Column("image_path", sa.Text(), nullable=True),
            sa.Column("metadata", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["roster_entry_id"], ["roster_entities.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id")
        )
        op.create_index("ref_emb_tenant_idx", "reference_embeddings", ["tenant_id"])
        op.create_index("ref_emb_roster_idx", "reference_embeddings", ["roster_entry_id"])

        op.create_table(
            "augmented_embeddings",
            sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("roster_entry_id", sa.Text(), nullable=False),
            sa.Column("observation_id", sa.Text(), nullable=False),
            sa.Column("embedding_json", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False, server_default="wordpress_confirm"),
            sa.Column("attachment_id", sa.Integer(), nullable=True),
            sa.Column("bbox", sa.Text(), nullable=True),  # JSON as text
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("quality_tier", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["roster_entry_id"], ["roster_entities.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("observation_id")
        )
        op.create_index("aug_emb_tenant_idx", "augmented_embeddings", ["tenant_id"])
        op.create_index("aug_emb_roster_idx", "augmented_embeddings", ["roster_entry_id"])
        op.create_index("aug_emb_quality_idx", "augmented_embeddings", ["quality_tier"])

def downgrade() -> None:
    op.drop_table("augmented_embeddings")
    op.drop_table("reference_embeddings")
    op.drop_table("roster_entities")
    op.drop_table("tenants")
```

**Apply migrations:**

```bash
# SQLite (local)
export DATABASE_URL="sqlite:///./data/recognition.db"
alembic upgrade head

# PostgreSQL (Docker Compose)
export DATABASE_URL="postgresql+psycopg://cat_dev:cat_dev_pass@127.0.0.1:5432/cat_recognition"
alembic upgrade head
```

**Verify:**

```bash
# SQLite
sqlite3 data/recognition.db ".tables"
sqlite3 data/recognition.db ".schema tenants"

# PostgreSQL
psql "$DATABASE_URL" -c "\dt"
psql "$DATABASE_URL" -c "\d roster_entities"
psql "$DATABASE_URL" -c "\dx"  # Should show vector extension
```

---

### Local Seed Data (Optional)

`db/init/010-seed.sql`:

```sql
INSERT INTO tenants (id, name, plan) VALUES (gen_random_uuid(), 'Dev Tenant', 'pro') RETURNING id;
-- Save the printed UUID and use it to seed test users / API keys.
```

For SQLite, create `data/seed.sql` and run:

```bash
sqlite3 data/recognition.db < data/seed.sql
```

In the app, set request-scoped tenant (PostgreSQL with RLS):

```sql
SET LOCAL app.tenant_id = '<dev-tenant-uuid>';
```

---

### App Configuration (.env)

Create `.env.local` (never commit secrets):

```bash
# Database
DATABASE_URL=sqlite:///./data/recognition.db  # Local SQLite
# DATABASE_URL=postgresql+psycopg://cat_dev:cat_dev_pass@127.0.0.1:5432/cat_recognition  # Docker

# Database pooling (PostgreSQL only)
DB_POOL_MIN=2
DB_POOL_MAX=10

# pgvector tuning (PostgreSQL only)
PGVECTOR_LISTS=100
IVFFLAT_PROBES=10

# FAISS acceleration (optional)
USE_FAISS_ACCELERATION=false
FAISS_INDEX_PATH=./data/faiss_index.bin

# Multi-tenant
DEFAULT_TENANT_ID=<your-dev-tenant-uuid>
```

---

## 2) Production Requirements

### Choose a Managed Postgres that supports pgvector

Pick a provider with:

- **pgvector** extension support on **Postgres 15/16**
- **Automated backups** + **Point-in-Time Recovery (PITR)**
- **High availability** (Multi-AZ/Region) and **automatic failover**
- **TLS required** for all connections and network isolation (VPC/Private Link/Firewall)

**Recommended providers:**

- **AWS RDS PostgreSQL** (pgvector support via extension)
- **Google Cloud SQL PostgreSQL** (pgvector enabled)
- **Azure Database for PostgreSQL** (Flexible Server with pgvector)
- **Supabase** (managed PostgreSQL with pgvector built-in)
- **Neon** (serverless PostgreSQL with pgvector)

### Minimum Provisioning

- **Instance class**: start with 2–4 vCPU, 8–16 GB RAM for small tenants; scale vertically first.
- **Storage**: 100–200 GB GP/SSD to start; enable autoscale if available.
- **Connection pooling**: pgBouncer in transaction mode, pool size aligned with worker count.
- **Parameters** (tune as you scale):
  - `shared_buffers` ~25% RAM
  - `work_mem` 64–128MB (watch memory per connection)
  - `maintenance_work_mem` 512MB+ for index build
  - `effective_cache_size` ~50–75% RAM
  - For pgvector IVFFLAT: size `lists` at index build; set `ivfflat.probes` per query for recall/latency
  - For pgvector HNSW: `hnsw.ef_construction` 64–200 (build time vs quality), `hnsw.ef_search` 40–500 (query recall)

### Create DB, Roles, and Extensions

Run **once** on the production instance:

```sql
CREATE DATABASE cat_recognition;
\c cat_recognition

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;

-- Roles
CREATE ROLE cat_app LOGIN PASSWORD '<strong-long-password>';
CREATE ROLE cat_readonly NOLOGIN;

-- Grant minimal privileges (after migrations create objects)
GRANT USAGE ON SCHEMA public TO cat_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cat_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cat_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cat_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cat_readonly;
```

Run your **migrations** (Alembic) using a CI/CD deploy job. Keep DDL in version control and require migrations to pass before app deploys.

**Create ANN indexes (after initial data load):**

```sql
-- IVFFLAT index (fast build, good for <1M embeddings)
CREATE INDEX ref_emb_vec_ivfflat_idx ON reference_embeddings
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX aug_emb_vec_ivfflat_idx ON augmented_embeddings
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- HNSW index (slower build, excellent recall, better for >100K embeddings, requires pgvector ≥0.5.0)
-- CREATE INDEX ref_emb_vec_hnsw_idx ON reference_embeddings
--   USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- CREATE INDEX aug_emb_vec_hnsw_idx ON augmented_embeddings
--   USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

### Row-Level Security (RLS)

Enable policies so each request only sees its tenant:

```sql
ALTER TABLE roster_entities ENABLE ROW LEVEL SECURITY;
CREATE POLICY roster_tenant_iso ON roster_entities
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE reference_embeddings ENABLE ROW LEVEL SECURITY;
CREATE POLICY ref_emb_tenant_iso ON reference_embeddings
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE augmented_embeddings ENABLE ROW LEVEL SECURITY;
CREATE POLICY aug_emb_tenant_iso ON augmented_embeddings
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

In the API server, **always** set the tenant GUC per request/transaction:

```python
# FastAPI dependency
async def set_tenant_context(tenant_id: UUID, db: AsyncSession):
    await db.execute(text("SET LOCAL app.tenant_id = :tenant_id"), {"tenant_id": str(tenant_id)})
    return tenant_id
```

### Progressive Learning & Materialized Views

Create materialized view for aggregate embeddings:

```sql
CREATE MATERIALIZED VIEW roster_aggregate_embeddings AS
SELECT
  re.id AS roster_entry_id,
  re.tenant_id,
  AVG(
    CASE
      WHEN ref.embedding IS NOT NULL THEN ref.embedding
      WHEN aug.quality_tier = 'high' THEN aug.embedding
      WHEN aug.quality_tier = 'medium' THEN aug.embedding * 0.8
      WHEN aug.quality_tier = 'low' THEN aug.embedding * 0.5
    END
  ) AS aggregate_embedding
FROM roster_entities re
LEFT JOIN reference_embeddings ref ON ref.roster_entry_id = re.id
LEFT JOIN augmented_embeddings aug ON aug.roster_entry_id = re.id
GROUP BY re.id, re.tenant_id;

CREATE UNIQUE INDEX roster_agg_emb_roster_idx ON roster_aggregate_embeddings(roster_entry_id);

-- HNSW index on aggregates (primary search index)
CREATE INDEX roster_agg_emb_vec_hnsw_idx ON roster_aggregate_embeddings
  USING hnsw (aggregate_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

**Refresh strategy:**

```python
# After WordPress confirmation adds augmented embedding
async def refresh_aggregate_embeddings(db: AsyncSession):
    await db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY roster_aggregate_embeddings"))

    # Optionally trigger FAISS rebuild
    if settings.USE_FAISS_ACCELERATION:
        await hybrid_manager.rebuild_from_database()
```

### FAISS Integration (Optional)

Enable FAISS for corpora >10K embeddings or GPU acceleration:

```python
# In app startup
if settings.USE_FAISS_ACCELERATION:
    from recognition_core.hybrid_index import HybridIndexManager

    hybrid_manager = HybridIndexManager(storage_adapter)

    # Load persisted index or rebuild
    if settings.FAISS_INDEX_PATH and Path(settings.FAISS_INDEX_PATH).exists():
        hybrid_manager.load_from_disk(settings.FAISS_INDEX_PATH)
    else:
        await hybrid_manager.rebuild_from_database()
        if settings.FAISS_INDEX_PATH:
            hybrid_manager.save_to_disk(settings.FAISS_INDEX_PATH)
```

**Scheduled refresh (optional background job):**

```python
# Celery/APScheduler task
@app.task
async def rebuild_faiss_index():
    """Rebuild FAISS from database (run every 6-12 hours or on-demand)"""
    await hybrid_manager.rebuild_from_database()
    if settings.FAISS_INDEX_PATH:
        hybrid_manager.save_to_disk(settings.FAISS_INDEX_PATH)
```

### Security

- Enforce **TLS** and **network allowlists** (VPC peering / Private Link).
- **Rotate secrets** (managed secret store) and use **least-privilege** DB roles.
- **Do not store card data**. Keep only Stripe IDs and subscription status.
- Enable **pgAudit** (or provider logs) for DDL/DML events on roster/embeddings if required by policy.
- Audit progressive learning: log all `augmented_embeddings` inserts with WordPress user ID and timestamp.

### Backups & DR

- Enable **automated backups** + **PITR**.
- Quarterly **restore rehearsal** to a staging environment.
- Snapshot **FAISS index files** only if you adopt FAISS; they can be rebuilt from Postgres.

### Observability

- Capture **slow query logs**; set threshold (e.g., 200–300 ms) and analyze weekly.
- Export **metrics**: connections, cache hit ratio, bloat, autovacuum activity, table/index sizes.
- Track **embedding corpus growth** per tenant and **query latency percentiles**.

### Maintenance

- **VACUUM/ANALYZE** regularly; consider more aggressive autovacuum for `embeddings`.
- **Reindex** if IVFFLAT parameters change or after large deletes.
- Consider **partitioning** `embeddings` by `created_at` if >50M rows.

---

## 3) CI/CD Hooks (suggested)

- `make db.up` → starts Docker DB locally
- `make db.migrate` → runs Alembic migrations
- `make db.seed` → seeds dev tenant
- PR check: run migrations against an ephemeral Postgres, then run tests
- Deploy: apply migrations first, then roll app (blue/green or canary)

---

## 4) Sanity Checklist

**Local**

- [ ] `\dx` shows `vector`
- [ ] Migration `upgrade head` succeeds
- [ ] Basic search query returns results under 50–150 ms

**Production**

- [ ] TLS enforced; DB not publicly routable
- [ ] PITR enabled; backup retention policy documented
- [ ] RLS enabled; GUC set per request
- [ ] SLOs defined for recognition latency; alerts on breach
- [ ] Stripe webhooks reach the app; subscription status updates within 10s

---

## 5) Connection Strings

- Local: `postgresql://cat_dev:cat_dev_pass@127.0.0.1:5432/cat_recognition`
- Production (example): `postgresql://cat_app:***@db.internal:5432/cat_recognition?sslmode=require`

---

### Appendix: Minimal DDL Reference (from the persistence plan)

See `recognition-backend-persistence-plan.md` for full DDL (tenants, users, api_keys, subscriptions, usage_counters, roster_entities, embeddings). Reuse those migrations unmodified in both local and production.
