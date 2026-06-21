# Task Plan

> **Metadata**
>
> - **Date**: 2026-06-21 14:30 EST
> - **Author**: Claude Opus 4.8
> - **Owning Epic**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-31`
> - **Review Coverage Target**: 2

---

## E15-31. Tailscale-gated `/admin` router for operator tenant API-key lifecycle

## Objective

Ship a single-operator `/admin` surface on the recognition FastAPI service that performs the tenant + API-key lifecycle (create tenant, mint key, list, revoke/rotate, view last-used, audit grant/revoke) over a Tailscale-gated network path plus a shared admin token. When complete, the operator grants and revokes a tenant key from a browser in seconds instead of the multi-step `ssh + docker exec ... python -m scripts.manage_api_keys` ceremony, and every grant/revoke is durably audit-logged.

## Intake

- **Scope source**: handoff decision `claude_intake_tenant_admin_scope` (intake, 4 AskUserQuestion answers) on `MAINT-tenant-admin-scope-20260621`.
- **Open-question resolutions**: handoff decision `claude_plan_analyze_resolve_open_qs` (#1073) on the same MAINT ref.
- **Plan-analyze findings carried in**: `tenant-admin-PA-01..06` (planning review_mode) on `MAINT-tenant-admin-scope-20260621`. Referenced by id, not duplicated, per the Review Findings Placement rule.
- **Not-Doing (MVP)**: public tenant self-service/signup; multi-admin SSO/RBAC; billing/quota enforcement (view-only usage only); per-tenant CORS management; deleting the `manage_api_keys` CLI (the admin API and CLI coexist over the same service code).

## Problem Statement

`E15-1` shipped the security baseline but **explicitly deferred the HTTP admin surface**: `docs/tasks/15.0/E15-1-security-baseline-task-plan.md:196` ("Why not an HTTP admin router") and `docs/workstate/contracts/security.md:401-448` ("HTTP admin surface: deferred. No admin router ships with E15-1. A real production admin authority is required first"). Today the only admin path is the operator CLI `apps/prototype-description-service/scripts/manage_api_keys.py`, and `E15-29` go-live (`docs/tasks/15.0/E15-29-public-demo-go-live-task-plan.md:51,126`) still mints demo keys by hand on the prod VM via `docker exec`.

This task resolves the deferral by naming **the Tailscale tailnet plus a shared admin token as the production admin authority** and building the deferred surface on top of it. The recognition VM is already enrolled on a tailnet for SSH (`infra/oci/README.md:130-423`), so the network substrate exists; what is missing is (a) an admin authority/auth primitive, (b) the HTTP surface, and (c) binding that surface to the tailnet.

## Constraints

- **Plugin boundary**: only files under `apps/prototype-description-service/`, `docs/`, `scripts/` change. All deploy files touched (`Caddyfile`, `docker-compose.prod.yml`, `Dockerfile`, `.env.prod.example`) live under `apps/prototype-description-service/`.
- **No new admin authority via the dev-key path**: `AuthContext.is_admin` (`recognition/interface_adapters/http/deps/auth.py:36,44`) is set true only by the `RECOGNITION_ALLOWED_API_KEYS` plaintext bypass, which is **banned in production** (`recognition/config/security.py:96-113`, `api/main.py:111-128`). `/admin` must NOT reuse it; it gets its own `require_admin` dependency (PA-02).
- **Network gating alone is insufficient** for confidentiality because routers mount on the same Caddy-published app (`api/main.py:170-172`). The shared admin token is enforced in-app as defense-in-depth even on the tailnet (PA-01/PA-02).
- **Schema**: this service uses Alembic (`apps/prototype-description-service/db/migrations/versions/`), not the `001_identity_schema.py` single-file pattern. MVP reuses the existing `audit_events` table (`db/models/observability.py:195`) and adds **no migration** (PA-04).
- **Greenfield**: no back-compat shims; the CLI stays but delegates key-minting to the same extracted service the router uses (no duplicated mint/hash logic — PA-03).
- **Raw key is unrecoverable** after mint (`secrets.token_urlsafe` + one-way hash); it is surfaced exactly once in the create response and never logged.

## Workflow Principles

- Single source of truth for key minting: one `mint_api_key` helper used by both the CLI and the router.
- Fail-closed: when `RECOGNITION_ADMIN_ENABLED=true` but `RECOGNITION_ADMIN_TOKEN` is unset, the app refuses to start — same shape as `_check_dev_key_guard` (`api/main.py:111-128`).
- Every state change (mint, revoke, tenant-create) writes an `audit_events` row before returning success; revoke resolves `tenant_id` from the key first (the table's `tenant_id` is `NOT NULL` CASCADE — PA-04).
- Replicate the CLI's BR-02 env/DSN safety assertion in-process so a mis-pointed container cannot silently mint/revoke against the wrong DB (PA-05).

## Terminology

- **Admin authority**: the combination of (tailnet reachability) AND (valid `RECOGNITION_ADMIN_TOKEN`). Either alone is insufficient by policy.
- **Mint**: generate a new raw API key, hash it, persist the hash, return the raw key once.
- **Operator**: the single human running the service (the "JUST ME" intake answer); not an end-user/tenant.

## Current State Analysis

- **Works**: `SqlAlchemyApiKeyRepository` (`recognition/infrastructure/repositories/api_key_repository.py`) exposes `create`, `list_for_tenant`, `revoke`, `touch_by_id`, `get_by_hash`; `Tenant`/`ApiKey` models (`db/models/tenant.py:37,69`); `AuditService.record_event` (`recognition/application/services/audit_service.py:18`); `auth_enabled`/`api_key_hash_algorithm` config (`recognition/config/security.py:52-58`).
- **Missing**: any admin auth primitive (no `require_admin`), any `/admin` router, any env-gated `include_router` pattern, any audit write on key grant/revoke (`manage_api_keys.py` writes none; `auth_audit.py` is log-only), any Tailscale binding for the app.
- **Misleading**: the scope phrase "thin wrap over manage_api_keys" understates net-new work — key minting + hashing live in the CLI command `_cmd_create` (`scripts/manage_api_keys.py:104-141`), not the repository, so a "wrap" must first extract that logic (PA-03).

## Target Outcome

A `RECOGNITION_ADMIN_ENABLED`-gated `/admin` router mounted on the recognition app, every route behind `Depends(require_admin)`, exposing JSON endpoints plus a minimal server-rendered HTML console (no SPA build added to the Python image). In production the surface is reachable only over the tailnet (Caddy serves `/admin` on a tailnet-bound site, not the public site) and additionally requires the shared token. The operator opens the console, sees live tenants + key status, mints a key (shown once), and revokes — each action audit-logged to `audit_events`. `docs/workstate/contracts/security.md` is updated to record that the deferred admin surface is now shipped and what authority backs it.

## Context Loading

- Rules: `docs/workstate/rules/backend-python-guidelines.md`, `docs/workstate/rules/testing-python.md`.
- Contracts: `docs/workstate/contracts/security.md` (§ Operator CLI / HTTP admin deferral, lines 401-448).
- Predecessor: `docs/tasks/15.0/E15-1-security-baseline-task-plan.md:99,196,275`.
- Handoff/MCP: decisions `claude_intake_tenant_admin_scope`, `claude_plan_analyze_resolve_open_qs` (#1073); findings `tenant-admin-PA-01..06` on `MAINT-tenant-admin-scope-20260621`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Recognition HTTP admin surface | backend | `docs/workstate/contracts/security.md:401-448` (admin surface "deferred") | Add `/admin` routes + admin authority; flip the deferral note to "shipped (tailnet + token)" | no — greenfield, no prior admin clients | API tests + updated contract section |
| API-key minting | backend | mint+hash inline in `scripts/manage_api_keys.py:104-141` | Extract to shared `mint_api_key`; CLI delegates | yes — CLI behavior must be unchanged | existing `test_manage_api_keys` stays green |
| Audit log | backend | `audit_events` written only by scene/retention | Add grant/revoke/tenant-create writers | no | API test asserts audit row written |
| Deploy topology | infra (in-app) | `Caddyfile`/`docker-compose.prod.yml` publish only the public app | Add tailnet-bound `/admin` exposure + env vars | no | config validation + operator runbook |

## Proposed Solution

Five slices, each behavior-plus-proof. Slices 1–4 are app code with deterministic tests; Slice 5 is the deployment/network gate plus contract/runbook updates. The admin token gate (Slice 2) is enforced from the first endpoint so no slice ships an unauthenticated admin surface.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend (new) | `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py` | `mint_api_key(session, tenant_id, tier, expires_in_days)` + `revoke_key` / `upsert_tenant` helpers wrapping the repo + audit |
| backend | `apps/prototype-description-service/scripts/manage_api_keys.py` | `_cmd_create` delegates to `mint_api_key` (remove inline `token_urlsafe`+hash) |
| backend (new) | `apps/prototype-description-service/recognition/interface_adapters/http/deps/admin_auth.py` | `require_admin` dependency; constant-time `secrets.compare_digest` on `RECOGNITION_ADMIN_TOKEN` |
| backend | `apps/prototype-description-service/recognition/config/security.py` | add `admin_enabled` + `admin_token` fields; add `validate_admin_config` fail-closed check |
| backend (new) | `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py` | tenant + key lifecycle JSON endpoints, all `Depends(require_admin)`; audit each mutation; BR-02 env/DSN assertion |
| backend (new) | `apps/prototype-description-service/recognition/interface_adapters/http/templates/admin/console.html` (+ Jinja2 wiring) | server-rendered console (list/create/revoke), HTMX actions, raw key shown once |
| backend | `apps/prototype-description-service/api/main.py` | conditional `app.include_router(admin_router, prefix="/admin")` behind `admin_enabled`; fail-closed startup check |
| deploy | `apps/prototype-description-service/Caddyfile`, `docker-compose.prod.yml`, `.env.prod.example` | tailnet-bound `/admin` exposure + `RECOGNITION_ADMIN_ENABLED` / `RECOGNITION_ADMIN_TOKEN` |
| docs | `docs/workstate/contracts/security.md` | flip the "HTTP admin surface deferred" note to "shipped"; document the tailnet+token authority |
| docs | `infra/oci/README.md`, `docs/tasks/15.0/E15-29-public-demo-go-live-task-plan.md` | operator runbook: use `/admin` over tailnet instead of manual `docker exec` |

## Related Files

| File | Note |
| --- | --- |
| `recognition/infrastructure/repositories/api_key_repository.py` | reused as-is for create/list/revoke/touch |
| `db/models/tenant.py:37,69` | `Tenant`/`ApiKey` models; `ApiKey.tenant_id` FK CASCADE |
| `db/models/observability.py:195-217` | `audit_events` (tenant_id NOT NULL) — reused, no migration |
| `recognition/interface_adapters/http/deps/auth.py:111-128` | dev-key guard pattern to mirror for fail-closed startup |
| `recognition/shared/ids.py:16` | UUIDv7 generator — use if the create-tenant endpoint mints the UUID server-side |

## Verification Strategy

- Deterministic tests (run from `apps/prototype-description-service/`):
  - `pytest recognition/tests/scripts/test_manage_api_keys.py` — CLI unchanged after mint extraction (Slice 1).
  - `pytest recognition/tests/api/test_admin_auth.py` — token valid/invalid/missing, fail-closed (Slice 2).
  - `pytest recognition/tests/api/test_admin_router.py` — create→list→mint→revoke flow, auth required on every route, audit row written, revoke resolves tenant (Slice 3).
  - `pytest recognition/tests/api/test_admin_mount.py` — `/admin` 404 when disabled, mounted when enabled, startup refuses when enabled w/o token, console HTML renders (Slice 4).
- Contract/fixture verification:
  - `grep -n "deferred" docs/workstate/contracts/security.md` shows the admin-surface note flipped (Slice 5).
- Manual verification:
  - With `RECOGNITION_ADMIN_ENABLED=true` + token set, load `/admin/` over the tailnet, mint a key, confirm it authenticates a recognition request, revoke it, confirm 401 thereafter.

## Slice Delivery

### Slice 1: Extract shared key-minting service

**Goal**: One `mint_api_key` helper owns token generation + hashing; the CLI delegates to it with no behavior change.

Changes:
- Add `api_key_admin_service.py` with `mint_api_key(session, tenant_id, tier, expires_in_days) -> tuple[ApiKey, str]` (raw + record), replicating `secrets.token_urlsafe(32)` + `hashlib.new(get_security_settings().api_key_hash_algorithm)`.
- `scripts/manage_api_keys.py:_cmd_create` calls `mint_api_key`; delete its inline mint/hash.

Proof:
- New unit test: minted raw key hashes to a value `SqlAlchemyApiKeyRepository.get_by_hash` resolves.
- `pytest recognition/tests/scripts/test_manage_api_keys.py` stays green.

### Slice 2: `require_admin` dependency + admin config

**Goal**: A reusable admin gate that fails closed.

Changes:
- `security.py`: add `admin_enabled` (`RECOGNITION_ADMIN_ENABLED`, default false) + `admin_token` (`RECOGNITION_ADMIN_TOKEN`); add `validate_admin_config()` raising when enabled and token empty.
- `deps/admin_auth.py`: `require_admin` reads the configured header, constant-time-compares against `admin_token`, raises 401 on mismatch/missing.

Proof:
- `pytest recognition/tests/api/test_admin_auth.py`: valid token → pass; wrong/missing → 401; enabled w/o token → `validate_admin_config` raises.

### Slice 3: Admin REST endpoints + audit wiring

**Goal**: Tenant + key lifecycle over JSON, every route gated, every mutation audited.

Changes:
- `routers/admin.py`: `POST /admin/tenants` (upsert), `GET /admin/tenants`, `POST /admin/tenants/{tenant_id}/keys` (mint → raw key once), `GET /admin/tenants/{tenant_id}/keys` (status/created/last_used/expires/revoked), `POST /admin/keys/{key_id}/revoke`. All `dependencies=[Depends(require_admin)]`.
- Each mutation calls `AuditService.record_event(session, tenant_id=..., event_type="api_key.mint|api_key.revoke|tenant.create", actor="admin", scope="admin_router", payload={...})`; revoke loads the `ApiKey` to resolve `tenant_id` before auditing.
- Router init asserts env/DSN agreement (mirror `manage_api_keys._validate_env_vs_dsn`).

Proof:
- `pytest recognition/tests/api/test_admin_router.py`: full create→list→mint→revoke flow; 401 without token on every route; asserts an `audit_events` row per mutation; revoke of an unknown key → 404.

### Slice 4: Env-gated mount + server-rendered console

**Goal**: `/admin` exists only when enabled; minimal HTML console; no SPA toolchain added.

Changes:
- `api/main.py`: in `create_app`, when `security.admin_enabled` mount `admin_router` at `/admin` and call `validate_admin_config()` fail-closed (mirroring `_check_dev_key_guard` at `api/main.py:111-128,134`).
- Add Jinja2 template `templates/admin/console.html` + a `GET /admin/` HTML route: tenant/key table, create-tenant+mint form (raw key shown once), revoke buttons via HTMX.

Proof:
- `pytest recognition/tests/api/test_admin_mount.py`: disabled → `/admin/` 404; enabled → mounted + console renders; enabled w/o token → startup raises.

### Slice 5: Tailscale gate + contract/runbook

**Goal**: In production `/admin` is reachable only over the tailnet; the deferral contract is resolved.

Changes:
- `Caddyfile` / `docker-compose.prod.yml`: serve `/admin` on a tailnet-bound listener (separate site bound to the tailscale interface / internal network), not the public site; add `RECOGNITION_ADMIN_ENABLED` + `RECOGNITION_ADMIN_TOKEN` to `.env.prod.example`.
- `docs/workstate/contracts/security.md:401-448`: flip "HTTP admin surface: deferred" → shipped; document tailnet + shared-token authority.
- `infra/oci/README.md` + `E15-29` go-live: operator runbook uses `/admin` over tailnet instead of `docker exec ... manage_api_keys`.

Proof:
- Caddy/compose config validated (`docker compose -f docker-compose.prod.yml config`); `grep -n "deferred" docs/workstate/contracts/security.md` confirms the note flipped; operator runbook reviewed.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded `security.md` admin-deferral contract, `E15-1` predecessor, and the MAINT plan-analyze findings/decision before editing.
- [ ] Recorded boundary ownership (admin surface, mint, audit, deploy) and confirmed no prior admin client needs compatibility.

### Checklist for Slice 1: Extract shared key-minting service

- [ ] Add `api_key_admin_service.mint_api_key` replicating token+hash from `get_security_settings().api_key_hash_algorithm`.
- [ ] `manage_api_keys._cmd_create` delegates; inline mint/hash deleted.
- [ ] Unit test mint→`get_by_hash`; `test_manage_api_keys.py` green.

### Checklist for Slice 2: `require_admin` dependency + admin config

- [ ] Add `admin_enabled` + `admin_token` + `validate_admin_config` to `security.py`.
- [ ] Add `deps/admin_auth.require_admin` with `secrets.compare_digest`.
- [ ] `test_admin_auth.py`: valid/invalid/missing + fail-closed all covered.

### Checklist for Slice 3: Admin REST endpoints + audit wiring

- [ ] `routers/admin.py` with the five endpoints, all `Depends(require_admin)`.
- [ ] Each mutation writes `audit_events` via `AuditService.record_event`; revoke resolves tenant first.
- [ ] Env/DSN assertion replicated; `test_admin_router.py` covers flow + auth + audit + 404.

### Checklist for Slice 4: Env-gated mount + server-rendered console

- [ ] Conditional mount + fail-closed startup in `api/main.py`.
- [ ] Jinja2 console template + `GET /admin/` route; raw key shown once.
- [ ] `test_admin_mount.py` covers disabled/enabled/no-token/render.

### Checklist for Slice 5: Tailscale gate + contract/runbook

- [ ] `Caddyfile`/`docker-compose.prod.yml`/`.env.prod.example` bind `/admin` to tailnet + add env vars.
- [ ] `security.md` admin-deferral note flipped to shipped with authority documented.
- [ ] `infra/oci/README.md` + `E15-29` runbook updated to `/admin`-over-tailnet.

## Review Readiness

- [ ] No boundary-touching change without matching contract/test evidence (admin surface ↔ security.md; mint ↔ CLI test).
- [ ] Runtime-parity: manual tailnet reachability + key round-trip captured for Slice 5 (config tests can mask network gating).
- [ ] Handoff decision records each slice + verification + the security.md contract change.

## Stretch Goals

- [ ] `GET /admin/keys/{key_id}/usage` last-used detail view.
- [ ] Rotate-in-place convenience (mint new + revoke old in one action) on the console.

## Success Criteria

- [ ] Operator mints and revokes a tenant key from `/admin/` over the tailnet in seconds; raw key shown once.
- [ ] `/admin` returns 401 without the admin token and is unreachable off-tailnet in prod config.
- [ ] Every mint/revoke/tenant-create writes an `audit_events` row.
- [ ] `manage_api_keys` CLI behavior unchanged (mint logic now shared, not duplicated).
- [ ] `docs/workstate/contracts/security.md` records the admin surface as shipped with its authority.
