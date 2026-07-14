# Secrets ownership inventory

> **Authoritative ownership matrix** for the five trust domains in the secrets-consolidation
> scope (Phase 1). Living document — update when a secret’s owner, source-of-truth, or
> consumer changes.
>
> **Task:** `MAINT-secrets-consolidation-20260708` · Phase 1 / Slice 1
> **Related:** `docs/scopes/secrets-consolidation.md`, `docs/tasks/secrets/secrets-phase1-hygiene-task-plan.md`
> **Decision:** `#1882` — static allowlist `RECOGNITION_ALLOWED_API_KEYS` is locked for
> **removal** (delete-over-flag; enacted in Phase 1 Slice 3). Tenant API keys are
> **DB-only via `/admin`** as the sole authority. Do not re-add or document the
> allowlist as a live authentication path.

## Trust domains (summary)

| # | Domain | What belongs here | Canonical source (target) |
|---|---|---|---|
| 1 | Infra | Postgres / MariaDB / deploy path vars | env (local) · OCI Vault (prod, Phase 3) |
| 2 | Service root-of-trust | Shared operator admin token for `/admin` | env (local/prod today) · OCI Vault (Phase 3) |
| 3 | Tenant API keys | Plugin→service bearer keys | **Service DB via `/admin` only** (allowlist removal locked; Slice 3) |
| 4 | Human accounts | WP admin user/password for demo/operator login | WordPress user store / demo bootstrap — **never committed** |
| 5 | Test creds | Playwright LocalWP auth bootstrap | gitignored `apps/prototype-wp-alt-context/.env.local` (example shipped) |

## Ownership matrix

Columns: **domain** · **owner** · **source-of-truth** · **consumer** · **prod target**.

### 1. Infra

| Secret / var | Domain | Owner | Source-of-truth | Consumer | Prod target |
|---|---|---|---|---|---|
| `PGUSER` | infra | description-service / DB ops | `apps/prototype-description-service/.env` (local); compose secrets on VM | `db/settings.py` (`get_database_settings`, DSN render); `scripts/reset_dev_db.sh`; `scripts/db_shell.sh` | OCI Vault → process env / compose (Phase 3) |
| `PGPASSWORD` | infra | description-service / DB ops | service-dir `.env` (local); VM secrets dir | same as `PGUSER` | OCI Vault |
| `PGHOST` | infra | description-service / DB ops | service-dir `.env` | `db/settings.py` DSN render | compose network hostname / Vault |
| `PGPORT` | infra | description-service / DB ops | service-dir `.env` | `db/settings.py` DSN render | compose / Vault |
| `DB_NAME` | infra | description-service / DB ops | service-dir `.env` | `db/settings.py` (`_resolved_db_name`, canonicalize) | compose `POSTGRES_DB` / Vault |
| `APP_PGUSER` | infra | description-service / DB ops | service-dir `.env` (alias of `PGUSER` for shell scripts) | `scripts/reset_dev_db.sh`, `scripts/db_shell.sh` fallback | same as `PGUSER` |
| `APP_PGPASSWORD` | infra | description-service / DB ops | service-dir `.env` (alias of `PGPASSWORD`) | same shell scripts | same as `PGPASSWORD` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | infra | OCI deploy | `/opt/acx-backend/<env>/secrets/.env` (template: `.env.prod.example`) | docker-compose Postgres bootstrap | OCI Vault |
| `POSTGRES_DSN` / `POSTGRES_SYNC_DSN` | infra | description-service / OCI deploy | service `.env` or prod secrets dir | `db/settings.py:get_database_settings` | OCI Vault |
| `MARIADB_*` / `WORDPRESS_DB_*` | infra | demo stack ops | `infra/oci/demo` secrets `.env` (template: `infra/oci/demo/.env.example`) | demo compose / WordPress container | VM secrets only (chmod 600); never commit |

**Loader note:** the description-service never reads a **repo-root** `.env`. Runtime loads
`ENV_FILE = <service-dir>/.env` via `db/settings.py:_load_env_file` (and
`get_database_settings` calls that loader first). Confirmed: no tracked or on-disk
repo-root `.env`; root `.gitignore` ignores `.env` / `.env.*` with `!.env*.example`.

### 2. Service root-of-trust

| Secret / var | Domain | Owner | Source-of-truth | Consumer | Prod target |
|---|---|---|---|---|---|
| `RECOGNITION_ADMIN_TOKEN` | service root-of-trust | service operator | service-dir / VM secrets `.env` (generate ≥32 chars) | `SecuritySettings.admin_token`; `validate_admin_config`; `/admin` deps (`admin_auth`) | OCI Vault; tailnet-bound `/admin` only |
| `RECOGNITION_ADMIN_ENABLED` | service root-of-trust (flag) | service operator | same env surface | `SecuritySettings.admin_enabled`; router mount | env / Vault flag |
| `RECOGNITION_ADMIN_TAILNET_BOUND` | service root-of-trust (ack) | service operator | prod secrets `.env` | `validate_admin_config` (must be `1` in production when admin on) | explicit prod ack only |
| `RECOGNITION_ADMIN_TOKEN_HEADER` | service root-of-trust (config) | service operator | env (default `X-Admin-Token`) | admin auth dependency | env default OK |

Related non-secret mode flags on the same surface (not secrets, listed for map completeness):
`RECOGNITION_RUNTIME_MODE`, `RECOGNITION_AUTH_ENABLED`, `RECOGNITION_API_KEY_HEADER`,
rate-limit / CORS knobs (`RECOGNITION_RATE_LIMIT_*`, `RECOGNITION_MAX_PAGE_SIZE`,
`RECOGNITION_ALLOWED_ORIGINS`, `RECOGNITION_API_KEY_HASH_ALGORITHM`).

### 3. Tenant API keys (DB-only)

| Secret / var | Domain | Owner | Source-of-truth | Consumer | Prod target |
|---|---|---|---|---|---|
| Minted tenant API key (raw shown once) | tenant API keys | tenant / operator via `/admin` | **OCI/prod `--env prod` Service DB** `api_keys` table — canonical issuer of record (hash stored; raw never re-readable) | Recognition HTTP auth (`auth._lookup_api_key` → DB hash lookup); plugin via `ACX_RECOGNITION_API_KEY` / WP option | DB only; mint via prod `/admin` or `scripts/manage_api_keys.py --env prod` / `make provision-customer ENV=prod` |
| Plugin-held copy (`ACX_RECOGNITION_API_KEY` / `acx_recognition_api_key` option) | tenant API keys | site operator | WordPress option / PHP constant (not monorepo env) | WP plugin → service bearer | per-site; never commit |

**Canonical issuer of record:** the **OCI/prod `--env prod` tenant DB** is the
source of truth for real customer keys (`make provision-customer ENV=prod`, prod
`/admin`, or `scripts/manage_api_keys.py --env prod`). `make dev-mint-key` and the
local `admin-dev` console mint **local test fixtures only** — never real tenants.

**Allowlist removal locked (decision `#1882`):** `RECOGNITION_ALLOWED_API_KEYS` /
`SecuritySettings.dev_api_keys` is **not** an ownership source-of-truth. Phase 1
Slice 3 enacts removal of the env field, startup guards that only existed for it,
and the auth bypass branch. Do **not** re-document it as an onboarding or auth path.
Until Slice 3 lands, code/examples may still mention the symbol; treat any remaining
reference as legacy scheduled for deletion, not authority.

### 4. Human accounts

| Secret / var | Domain | Owner | Source-of-truth | Consumer | Prod target |
|---|---|---|---|---|---|
| `WP_ADMIN_USER` (default `acx-demo-admin`) | human accounts | demo / site operator | WordPress user store after `bootstrap-wp.sh`; template only in `infra/oci/demo/.env.example` | demo WP bootstrap | WP users table on demo VM — **never commit real passwords** |
| `WP_ADMIN_PASSWORD` | human accounts | demo / site operator | demo secrets `.env` on VM only | demo bootstrap | VM secrets (chmod 600) |
| `WP_ADMIN_EMAIL` | human accounts | demo / site operator | demo secrets `.env` | demo bootstrap | VM secrets |

Human logins are **not** machine keys. Consolidation here is documentation + gitignore
verification only — they are not merged into the tenant API-key system.

### 5. Test creds

| Secret / var | Domain | Owner | Source-of-truth | Consumer | Prod target |
|---|---|---|---|---|---|
| `ACX_E2E_WP_ADMIN_USER` | test creds | local developer / CI secret store | gitignored `apps/prototype-wp-alt-context/.env.local` (shipped template: `.env.local.example`) | Playwright LocalWP auth bootstrap | CI secret injection; never git |
| `ACX_E2E_WP_ADMIN_PASS` | test creds | local developer / CI secret store | same `.env.local` | Playwright | CI secrets |

`.gitignore` already ignores `apps/prototype-wp-alt-context/.env.local` and allowlists
`!.env.local.example` / `!.env*.example`.

## Deployable env templates (where vars are declared)

| Deployable | Template path | Runtime file (gitignored) |
|---|---|---|
| description-service (local) | `apps/prototype-description-service/.env.example` | `apps/prototype-description-service/.env` |
| description-service (OCI multi-env) | `apps/prototype-description-service/.env.prod.example` | `/opt/acx-backend/<env>/secrets/.env` |
| OCI demo stack | `infra/oci/demo/.env.example` | `/opt/acx-backend/demo/secrets/.env` |
| WP plugin Playwright | `apps/prototype-wp-alt-context/.env.local.example` | `apps/prototype-wp-alt-context/.env.local` |

## Grep coverage notes (Slice 1 proof)

Proof command:

```bash
grep -rhoE 'RECOGNITION_[A-Z_]+|APP_PG[A-Z]+|PG[A-Z]+|ACX_E2E_WP_ADMIN_[A-Z]+|WP_ADMIN_[A-Z]+' \
  apps/prototype-description-service/.env.example \
  apps/prototype-description-service/.env.prod.example \
  infra/oci/demo/.env.example \
  apps/prototype-wp-alt-context/.env.local.example \
  2>/dev/null | sort -u
```

Every **real secret** listed above is covered by that scan (or is DB/WP-store only and
intentionally not an env template secret). Identifiers that appear **only as comment
substrings** in templates (e.g. path fragment `PGDATA` from `ACX_PGDATA_PATH`,
`PGVECTOR` from `PGVECTOR_DIM`, or `RECOGNITION_URL` / `RECOGNITION_API_KEY` inside
`ACX_RECOGNITION_*` comment prose in the demo template) are **not** independent secrets —
do not treat them as additional trust-domain entries.

`RECOGNITION_ALLOWED_API_KEYS` still greps from current examples; ownership for tenant
keys is **DB-only** (see domain 3). Slice 3 removes the symbol from examples and runtime.

## Explicit non-goals (Phase 1)

- No `SecretProvider` seam (Phase 2).
- No OCI Vault backend (Phase 3).
- No merge of human WP accounts into machine-key storage.
- No plugin WP-option key storage redesign.
