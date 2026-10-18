# Prototype Description Service – Database Guide

This document covers everything needed to bootstrap or completely reset the
prototype description service database. The stack mirrors the 4.0
face-scan/clustering plan:

- PostgreSQL 15+ with the [`pgvector`](https://github.com/pgvector/pgvector)
  extension.
- SQLAlchemy 2.x (async runtime) + Alembic migrations.
- InsightFace embeddings stored as `VECTOR(512)` rows in `media_identities.embedding`.

## 1. Prerequisites

- PostgreSQL user with rights to create/drop databases and extensions.
- `pgvector` extension installed on the server (`CREATE EXTENSION vector;`).
- Python 3.12+ plus `uv`.

## 2. Environment Variables

Copy the sample file once and tweak as needed:

```bash
cd apps/prototype-description-service
cp .env.example .env
```

The canonical connection contract is the discrete `PG*` variables (see `.env.example`); `db/settings.py` builds the async/sync DSNs from them.

- `PGUSER` / `PGPASSWORD` / `PGHOST` / `PGPORT` / `DB_NAME` — primary connection settings. Defaults: `context` / `context` / `localhost` / `5432` / `alt_context_service`.
- `POSTGRES_DSN` — *optional* full async SQLAlchemy DSN override. When unset, `db/settings.py` derives it from the `PG*` vars (and re-exports it for the app).
- `POSTGRES_SYNC_DSN` — *optional* sync DSN override for Alembic. When unset, derived from the same `PG*` vars via psycopg.
- `PGVECTOR_DIM` — Embedding dimension stored in `media_identities.embedding`. Keep at 512 (the InsightFace model dimension) unless the embedding model changes. Default: `512`

> 💡 Both the runtime and Alembic automatically load `.env` when present.

## 3. Fresh Bootstrap Workflow

These steps take a completely clean workstation to a running API with the
baseline schema applied.

```bash
# 1. Ensure Python 3.12.7 is available
cd apps/prototype-description-service
uv python install 3.12.7  # if you don't have it yet

# 2. Sync locked dependencies (includes SQLAlchemy, alembic, pgvector bindings)
uv sync --locked --extra dev

# 3. Prepare PostgreSQL
createdb alt_context_service             # or use psql -c "CREATE DATABASE ..."
psql -d alt_context_service -c 'CREATE EXTENSION IF NOT EXISTS vector;'

# 4. Apply the baseline migration and verify the schema footprint
uv run --locked --extra dev alembic -c db/alembic.ini upgrade head
uv run --locked --extra dev python -m scripts.verify_identity_schema
```

## 3.1 Dedicated database owner (optional but recommended)

For local development and CI we prefer a role that owns `alt_context_service` so
you can safely run migrations and schema drops without touching your personal
PostgreSQL user. After creating the database above, switch the owner with:

```sql
CREATE ROLE context_service WITH LOGIN PASSWORD 'change-me' CREATEDB;
GRANT ALL PRIVILEGES ON DATABASE alt_context_service TO context_service;
ALTER DATABASE alt_context_service OWNER TO context_service;
```

When you run `psql postgres` afterwards, `\\l` should show the new owner in
the `Owner` column. Update `.env` so the DSNs use `context_service`/`change-me`
before rerunning Alembic or starting the API.

## 3.2 Run the API

```bash
uv run --locked --extra dev uvicorn api.main:app --reload
```

At the end of step 4 the baseline auth/identity tables will exist, including
`tenants`, `api_keys`, `media_identities`, `identity_clusters`,
`identity_members`, and `identity_scan_jobs`.
The migration also issues `CREATE EXTENSION IF NOT EXISTS vector`, but running it
manually up front guarantees the role you are using has the required privilege.

## 4. Nuking & Recreating the Database

Only do this when you intentionally want to blow away **all** face-scan data.

```bash
cd apps/prototype-description-service

# (Option A) Drop & recreate the database completely
psql -c 'DROP DATABASE IF EXISTS alt_context_service;'
psql -c 'CREATE DATABASE alt_context_service;'
psql -d alt_context_service -c 'CREATE EXTENSION IF NOT EXISTS vector;'

# (Option B) Keep the DB but rollback objects
uv run --locked --extra dev alembic -c db/alembic.ini downgrade base
uv run --locked --extra dev alembic -c db/alembic.ini upgrade head
uv run --locked --extra dev python -m scripts.verify_identity_schema
```

> ⚠️ Dropping the database requires a superuser or a role that owns the DB.
> Disconnect any active sessions first (`SELECT pg_terminate_backend(pid) ...`).

## 5. Service Startup Checklist (Clean Room)

1. **Clone repo & install deps** – follow the bootstrap workflow above.
2. **Verify env vars** – `cat .env` and ensure DSNs point to the right host.
3. **Run migrations** – `uv run --locked --extra dev alembic -c db/alembic.ini upgrade head`.
4. **Verify schema footprint** – `uv run --locked --extra dev python -m scripts.verify_identity_schema` must report the baseline table set before the service boots.
5. **Smoke test** – `uv run --locked --extra dev uvicorn api.main:app --reload` then hit `GET /health`.

If you see errors similar to `type "vector" does not exist`, confirm that the
extension was installed in the target database **before** running migrations.

## 6. Handy Commands

- Generate a new Alembic revision: `uv run --locked --extra dev alembic -c db/alembic.ini revision -m "describe change"`
- Autogenerate models diff: `uv run --locked --extra dev alembic -c db/alembic.ini revision --autogenerate -m "..."`
- Inspect current head: `uv run --locked --extra dev alembic -c db/alembic.ini current`
- Re-run latest migration: `uv run --locked --extra dev alembic -c db/alembic.ini downgrade -1 && uv run --locked --extra dev alembic -c db/alembic.ini upgrade head`
- Verify baseline schema footprint: `uv run --locked --extra dev python -m scripts.verify_identity_schema`

Keep this guide close whenever you need to rebuild or reseed the prototype
environment.
