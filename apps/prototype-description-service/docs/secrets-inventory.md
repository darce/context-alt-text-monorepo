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
| description-service (OCI prod/staging/dev) | `apps/prototype-description-service/.env.prod.example` | `/opt/acx-backend/<env>/.env` |
| description-service (OCI dev-fir benchmark stack) | `apps/prototype-description-service/.env.fir.example` | `/opt/acx-backend/dev-fir/.env` |
| OCI demo stack | `infra/oci/demo/.env.example` | `/opt/acx-backend/demo/secrets/.env` (scripts re-link `.env` to it) |
| WP plugin Playwright | `apps/prototype-wp-alt-context/.env.local.example` | `apps/prototype-wp-alt-context/.env.local` |

## Per-environment runtime files

One file per backend env, edited in place on the VM:
`/opt/acx-backend/<env>/.env`, owner `ubuntu:ubuntu`, mode `0600`. Compose reads
it (`env_file: .env`) and `recognition-service.sh` checks and rewrites it
(`ACX_IMAGE_TAG` guard; atomic `ACX_IMAGE_REPO` upsert). Because that rewrite is
an `os.replace`, a `.env -> secrets/.env` symlink does not survive it. The
legacy `<env>/secrets/.env` files still on the VM are stale copies that nothing
reads, so do not edit them ([REF-09] mirrored state drifts).

| Env | Template | Secret backend | Secrets held in the file |
|---|---|---|---|
| `prod` | `.env.prod.example` | `oci_vault` (live) | OCID map only; `POSTGRES_PASSWORD` filled by the `ExecStartPre` fetch |
| `staging`, `dev` | `.env.prod.example` (change identity block, `RECOGNITION_SECRET_BACKEND=env`) | `env` | `POSTGRES_PASSWORD`, DSNs, `RECOGNITION_ADMIN_TOKEN` if `/admin` is on |
| `dev-fir` | `.env.fir.example` | `env` (Vault opt-in block in the template) | `POSTGRES_PASSWORD` and the two DSNs (one value, three places) |

Create a new env file from its template:

```bash
scp apps/prototype-description-service/.env.fir.example ubuntu@acx-backend.tail1a44b8.ts.net:/tmp/env.fir
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'install -d -m 0755 /opt/acx-backend/dev-fir &&
  install -m 0600 /tmp/env.fir /opt/acx-backend/dev-fir/.env && rm /tmp/env.fir'
```

Replace every placeholder before the first `deploy dev-fir`. Every env gets its
own DB password: never copy one between envs ([PG-09] a shared password
widens the blast radius of one leak to every env; CARD-10).

### Rotation

| What | `env` backend (staging, dev, dev-fir) | `oci_vault` backend (prod) |
|---|---|---|
| DB password | `ALTER ROLE <POSTGRES_USER> PASSWORD '<new>'` in the env's postgres container, then set the same value in `POSTGRES_PASSWORD`, `POSTGRES_DSN` and `POSTGRES_SYNC_DSN`, then `systemctl restart acx-<env>` | New Vault secret version, then `ALTER ROLE`, then restart; see `infra/oci/vault-instance-principal-runbook.md` § 5 |
| `RECOGNITION_ADMIN_TOKEN` | Edit the value (≥32 chars), restart | New Vault secret version, restart |
| Tenant API keys | Not in any env file: revoke and re-mint through the env's `/admin` console (`docs/runbooks/key-management.md`) | same |
| `OCIR_AUTH_TOKEN` | — | `make ocir-token-rotate` |

`POSTGRES_PASSWORD` only initializes a **fresh** pgdata directory. Changing it
in `.env` without `ALTER ROLE` leaves the existing role on the old password and
the api fails its DB login on restart.

### Moving an env onto OCI Vault

No IAM change is needed. The live `acx-backend-secret-read` policy reads
secret-family **in tenancy**; see the drift note in the runbook § 2. Create env-specific secrets. Names
must be unique within the vault, e.g. `dev-fir-pg-password` and
`dev-fir-admin-token`. Put their OCIDs in that env's
`RECOGNITION_VAULT_SECRET_MAP` and set `RECOGNITION_SECRET_BACKEND=oci_vault`.
Boot requires **both** `PGPASSWORD` and `RECOGNITION_ADMIN_TOKEN` even when
`/admin` is off (`shared/secrets.py:validate_oci_vault_boot`). Blank the DSNs,
then enable the `ExecStartPre` fetch with that env's `--secret-name`. Never
reuse prod's OCIDs.

prod, staging, dev and dev-fir all run on the one acx-backend VM and share
its instance principal (dynamic group `acx-backend-dg`); the live
`acx-backend-secret-read` policy reads secret-family in tenancy, so that
identity can read every env's secrets, prod's included. Env-specific secret
names therefore give naming separation, not access isolation; Vault on the
shared VM does not isolate dev-fir from prod. Narrowing the policy is the
operator-gated follow-up in
[infra/oci/vault-instance-principal-runbook.md](../../../infra/oci/vault-instance-principal-runbook.md)
section 2; real per-env isolation needs a separate instance/dynamic group.

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
