# Prototype Description Service – Database Guide

This document covers everything needed to bootstrap or completely reset the
prototype description service database. The stack mirrors the 4.0
face-scan/clustering plan:

- PostgreSQL 15+ with the [`pgvector`](https://github.com/pgvector/pgvector)
  extension.
- SQLAlchemy 2.x (async runtime) + Alembic migrations.
- InsightFace embeddings stored as `VECTOR(1024)` rows in `media_faces`.

## 1. Prerequisites

- PostgreSQL user with rights to create/drop databases and extensions.
- `pgvector` extension installed on the server (`CREATE EXTENSION vector;`).
- Python 3.11+ virtual environment.

## 2. Environment Variables

Copy the sample file once and tweak as needed:

```bash
cd apps/prototype-description-service
cp .env.example .env
```

| Variable            | Purpose                                                                                                 | Default                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `POSTGRES_DSN`      | Async SQLAlchemy DSN used by the FastAPI app                                                            | `postgresql+asyncpg://context:context@localhost:5432/context_alt_text_service` |
| `POSTGRES_SYNC_DSN` | Optional sync DSN for Alembic. If omitted we derive it from `POSTGRES_DSN`.                             | same host/DB via psycopg                                               |
| `PGVECTOR_DIM`      | Embedding dimension stored in `media_faces.embedding`. Keep at 1024 unless the embedding model changes. | `1024`                                                                 |

> 💡 Both the runtime and Alembic automatically load `.env` when present.

## 3. Fresh Bootstrap Workflow

These steps take a completely clean workstation to a running API with the
baseline schema applied.

````bash
# 1. Create & enter a virtual environment
cd apps/prototype-description-service
pyenv install 3.11.9  # if you don't have it yet
pyenv virtualenv 3.11.9 description-service
pyenv shell description-service

# 2. Install dependencies (includes SQLAlchemy, alembic, pgvector bindings)
pip install -e .

# 3. Prepare PostgreSQL
createdb context_alt_text_service             # or use psql -c "CREATE DATABASE ..."
psql -d context_alt_text_service -c 'CREATE EXTENSION IF NOT EXISTS vector;'

# 4. Apply the baseline migration
alembic -c db/alembic.ini upgrade head

## 3.1 Dedicated database owner (optional but recommended)

For local development and CI we prefer a role that owns `context_alt_text_service` so
you can safely run migrations and schema drops without touching your personal
PostgreSQL user. After creating the database above, switch the owner with:

```sql
CREATE ROLE context_service WITH LOGIN PASSWORD 'change-me' CREATEDB;
GRANT ALL PRIVILEGES ON DATABASE context_alt_text_service TO context_service;
ALTER DATABASE context_alt_text_service OWNER TO context_service;
````

When you run `psql postgres` afterwards, `\\l` should show the new owner in
the `Owner` column. Update `.env` so the DSNs use `context_service`/`change-me`
before rerunning Alembic or starting the API.

# 5. Run the API

uvicorn api.main:app --reload

````

At the end of step 4 the baseline auth/identity tables will exist, including
`tenants`, `api_keys`, `media_identities`, `identity_clusters`,
`identity_members`, and `identity_scan_jobs`.
The migration also issues `CREATE EXTENSION IF NOT EXISTS vector`, but running it
manually up front guarantees the role you are using has the required privilege.

## 4. Nuking & Recreating the Database

Only do this when you intentionally want to blow away **all** face-scan data.

```bash
cd apps/prototype-description-service
pyenv shell description-service                   # if not already active

# (Option A) Drop & recreate the database completely
psql -c 'DROP DATABASE IF EXISTS context_alt_text_service;'
psql -c 'CREATE DATABASE context_alt_text_service;'
psql -d context_alt_text_service -c 'CREATE EXTENSION IF NOT EXISTS vector;'

# (Option B) Keep the DB but rollback objects
alembic -c db/alembic.ini downgrade base
alembic -c db/alembic.ini upgrade head
````

> ⚠️ Dropping the database requires a superuser or a role that owns the DB.
> Disconnect any active sessions first (`SELECT pg_terminate_backend(pid) ...`).

## 5. Service Startup Checklist (Clean Room)

1. **Clone repo & install deps** – follow the bootstrap workflow above.
2. **Verify env vars** – `cat .env` and ensure DSNs point to the right host.
3. **Run migrations** – `alembic -c db/alembic.ini upgrade head` (re-run on schema changes).
4. **Smoke test** – `uvicorn api.main:app --reload` then hit `GET /health`.

If you see errors similar to `type "vector" does not exist`, confirm that the
extension was installed in the target database **before** running migrations.

## 6. Handy Commands

| Task                            | Command                                                                            |
| ------------------------------- | ---------------------------------------------------------------------------------- |
| Generate a new Alembic revision | `alembic -c db/alembic.ini revision -m "describe change"`                          |
| Autogenerate models diff        | `alembic -c db/alembic.ini revision --autogenerate -m "..."`                       |
| Inspect current head            | `alembic -c db/alembic.ini current`                                                |
| Re-run latest migration         | `alembic -c db/alembic.ini downgrade -1 && alembic -c db/alembic.ini upgrade head` |

Keep this guide close whenever you need to rebuild or reseed the prototype
environment.
