# Scripts

Utility scripts for local development and testing.

## Directory Structure

```text
scripts/
├── db_shell.sh                 # Database shell access
├── deploy-env.sh               # Deployment environment helper
├── reset_dev_db.sh             # Database reset
├── setup.sh                    # Initial environment setup
├── start_prototype_local.sh    # Local development server
├── install_insightface_mac.sh  # macOS ARM64 insightface setup
├── generate_canonical_report.py # Canonical reporting utility
├── manage_api_keys.py          # Create/list/revoke tenant API keys
├── verify_identity_schema.py   # Assert the baseline schema footprint
└── utilities/
    └── compare_media_embeddings.py  # Embedding similarity comparison
```

## start_prototype_local.sh

Starts the prototype description service with automatic dependency installation and database setup.

**Usage:**

```bash
./scripts/start_prototype_local.sh [command]
```

**Commands:**

- `start` - Install dependencies and launch uvicorn (default)
- `install` - Install/upgrade dependencies only
- `stop` - Stop running service
- `help` - Show help

**Environment variables:**

- `SKIP_INSTALL=1` - Skip dependency installation
- `SKIP_DB_START=1` - Skip starting Postgres container
- `HOST` - Uvicorn host (default: 0.0.0.0)
- `PORT` - Uvicorn port (default: 8000)
- `FORCE_INSTALL=1` - Force reinstall dependencies even offline

**Auto-setup features:**

- Starts Docker/Colima if needed
- Starts Postgres container
- Installs Python dependencies
- Launches uvicorn with hot reload

## reset_dev_db.sh

Resets the development database by dropping and recreating it with fresh migrations.

**Usage:**

```bash
./scripts/reset_dev_db.sh [--with-sample-data]
```

**Options:**

- `--with-sample-data` - Seed the database with sample test data

**What it does:**

- Bootstraps `.env` from `.env.example` when a clean checkout has no local env yet
- Drops and recreates the database
- Runs Alembic migrations
- Creates the `recognition_test_user` for RLS testing
- Optionally seeds sample data

**Safety:**

- Direct script usage requires `ALLOW_DEV_DB_RESET=1` in `.env` or the shell environment
- `make reset` exports `ALLOW_DEV_DB_RESET=1` automatically because the target is already explicitly destructive and local-only
- Only runs if `ENV_MODE=local` or `ENV_MODE=development`
- Uses the canonical `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`DB_NAME` variables from `.env`

## Test User Setup

The `recognition_test_user` PostgreSQL role is automatically created:

1. **On first container creation** - via `/docker-entrypoint-initdb.d/010-create-test-role.sql`
2. **On database reset** - via `reset_dev_db.sh`

The test user has:

- CREATEDB and CREATEROLE privileges
- Full access to all tables and sequences in the public schema
- Ability to set `log_min_duration_statement` for debugging
- **NOT** a SUPERUSER (so RLS policies remain enforced)

## Testing with RLS

To run tests with Row-Level Security enabled:

1. Ensure test user exists (it's created automatically on first DB start or reset)

2. Set environment variable in `.env`:

   ```env
   ALLOW_RLS_BYPASS_FOR_TESTS=0
   ```

3. Run tests:

   ```bash
   python -m pytest
   ```

The test user has sufficient privileges to run tests while still enforcing RLS policies, allowing you to verify that tenant isolation works correctly.
