# Rename Database: context_alt_text → alt_context

## Problem

The recognition database uses the legacy name `context_alt_text` / `context_alt_text_service` throughout the codebase and deployed environments. The product name is "Alt Context" and all other naming surfaces (`acx_*` prefixes, `altcontext.com` domain, `AltContext\` PHP namespace) already use the correct name. The database name is the last holdout.

## Impact

- Confusing for new contributors and operators
- Inconsistent with the `acx_*` naming convention documented in `CLAUDE.md`
- The E16 SaaS foundation epic introduces a second database (`acx_business`); having the recognition DB named `context_alt_text_service` alongside `acx_business` is jarring

## Risk

**Low.** Greenfield policy applies — no production users, no data to preserve. Alembic re-creates schema on first boot. The rename is a find-and-replace with a VM env update.

## Scope

### Repo files (~12 files, ~25 occurrences)

| File | Change |
|------|--------|
| `apps/prototype-description-service/db/settings.py:14` | `DEFAULT_DB_NAME = "context_alt_text"` → `"alt_context"` |
| `apps/prototype-description-service/db/alembic.ini:4` | Default DSN: `context_alt_text` → `alt_context` |
| `apps/prototype-description-service/db/README.md` | ~10 occurrences in examples and docs |
| `apps/prototype-description-service/db/docker-init/010-create-test-role.sql:32` | `context_alt_text_service` → `alt_context_service` |
| `apps/prototype-description-service/.env.prod.example` | `POSTGRES_DB`, `POSTGRES_DSN`, `POSTGRES_SYNC_DSN` (3 occurrences) |
| `apps/prototype-description-service/scripts/db_shell.sh:37` | Default `DB_NAME` |
| `apps/prototype-description-service/recognition/tests/integration/test_rls_tenant_context_after_chunk_commit.py:161` | Test DSN |
| `docs/epics/v0.3.1/saas-foundation-epic.md` | Schema diagram reference |
| `docs/roadmaps/roadmap-saas-operations.md` | Architecture diagram reference |
| `docs/tasks/4.0/4.9.10/ISSUES_ANALYSIS.md` | Historical reference (update or leave as-is) |
| `docs/tasks/10.0/10.1/projection-stall-direct-db-investigation-2026-03-24.md` | Historical reference |
| `docs/tasks/4.0/cluster-rework/centroid-fidelity-plan.md` | Historical reference |

### VM environments (3 envs × 3 vars)

For each of `prod`, `staging`, `dev` at `/opt/acx-backend/<env>/secrets/.env`:

```
POSTGRES_DB=alt_context_service                                              # was context_alt_text_service
POSTGRES_DSN=postgresql+asyncpg://acx_app:<pass>@postgres:5432/alt_context_service
POSTGRES_SYNC_DSN=postgresql+psycopg://acx_app:<pass>@postgres:5432/alt_context_service
```

### VM restart procedure

After updating env files, restart each environment. Postgres auto-creates the new DB name on first boot; Alembic runs migrations:

```bash
for env in prod staging dev; do
  cd /opt/acx-backend/$env
  docker compose -f docker-compose.env.yml down
  # Optionally remove old pgdata to start fresh:
  # sudo rm -rf /opt/acx-backend/data/${env}-pgdata/*
  docker compose -f docker-compose.env.yml up -d
done
```

### Docker init scripts

`db/docker-prod-init/001-extensions.sql` does **not** reference the database name (it runs inside the container's default DB). No change needed.

## Naming Convention After Rename

| Surface | Old | New |
|---------|-----|-----|
| Local dev DB | `context_alt_text` | `alt_context` |
| Production DB | `context_alt_text_service` | `alt_context_service` |
| Staging DB | `context_alt_text_staging` | `alt_context_staging` |
| Dev DB | `context_alt_text_dev` | `alt_context_dev` |
| Business DB (E16) | — | `acx_business` |

## Decision

**Executed 2026-04-24** on `MAINT-db-rename-context-alt-text-to-alt-context-20260424`. Active-file rename complete (see branch `feature/maint-db-rename-context-alt-text-to-alt-context-20260424`). Archive files intentionally not updated -- they are historical references and should remain accurate to the names in use at the time they were written. VM env-file updates and dev pgdata wipe follow in a separate operator step; see the VM restart procedure above.
