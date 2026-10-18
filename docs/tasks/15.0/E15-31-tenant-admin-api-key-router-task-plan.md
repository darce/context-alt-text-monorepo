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

Ship a single-operator `/admin` surface on the recognition FastAPI service that performs the tenant + API-key lifecycle (create tenant, mint key, list, revoke/rotate, view last-used, audit grant/revoke) reachable only over a tailnet path plus a shared admin token. When complete, the operator grants and revokes a tenant key from a browser in seconds instead of the multi-step `ssh + docker exec ... python -m scripts.manage_api_keys` ceremony, and every grant/revoke is durably audit-logged.

## Intake

- **Scope source**: handoff decision `claude_intake_tenant_admin_scope` (intake, 4 AskUserQuestion answers) on `MAINT-tenant-admin-scope-20260621`.
- **Open-question resolutions**: handoff decision `claude_plan_analyze_resolve_open_qs` (#1073) on the same MAINT ref.
- **Plan-analyze findings carried in**: `tenant-admin-PA-01..06` (planning) on `MAINT-tenant-admin-scope-20260621`. Referenced by id, not duplicated, per the Review Findings Placement rule.
- **Not-Doing (MVP)**: public tenant self-service/signup; multi-admin SSO/RBAC; billing/quota enforcement (view-only usage only); per-tenant CORS management; deleting the `manage_api_keys` CLI (the admin API and CLI coexist over the same service code).

## Problem Statement

`E15-1` shipped the security baseline but **explicitly deferred the HTTP admin surface**: `docs/tasks/15.0/E15-1-security-baseline-task-plan.md:196` ("Why not an HTTP admin router") and `docs/workbay/contracts/security.md:401-448` ("HTTP admin surface: deferred. No admin router ships with E15-1. A real production admin authority is required first"). Today the only admin path is the operator CLI `apps/prototype-description-service/scripts/manage_api_keys.py`, and `E15-29` go-live (`docs/tasks/15.0/E15-29-public-demo-go-live-task-plan.md:51,126`) still mints demo keys by hand on the prod VM via `docker exec`.

This task resolves the deferral by naming **the Tailscale tailnet plus a shared admin token as the production admin authority** and building the deferred surface on top of it. The recognition VM is already enrolled on a tailnet for SSH (`infra/oci/README.md:130-423`), so the network substrate exists; what is missing is (a) an admin authority/auth primitive, (b) the HTTP surface, and (c) binding that surface to the tailnet while denying it on the public vhost.

## Constraints

- **Plugin boundary**: only files under `apps/prototype-description-service/`, `docs/`, and `scripts/` are **edited**. `infra/oci/README.md` is the canonical host-level Tailscale runbook and is **referenced read-only** (not edited); the operator runbook for `/admin` lives in `docs/` to stay unambiguously in-boundary (resolves boundary tension flagged by review `policy-01`).
- **No new admin authority via the dev-key path**: `AuthContext.is_admin` (`recognition/interface_adapters/http/deps/auth.py:224,260-261`) is set true only by the `RECOGNITION_ALLOWED_API_KEYS` plaintext bypass, which is **banned in production** (`recognition/config/security.py:96-113`, `api/main.py:111-128`). `/admin` gets its own `require_admin` dependency reading a **dedicated header**, never `is_admin`, the DB, or `api_key_header` (PA-02; review `sec-03`).
- **Network gating alone is insufficient**: routers mount on the same Caddy-published app (`api/main.py:170-172`), and the public `api.altcontext.com` vhost (`Caddyfile:5-7`) proxies all paths to `prod-api:8000`. The shared admin token is enforced in-app even on the tailnet, **and** the public vhost must explicitly deny `/admin*` (PA-01/PA-02; review `complete-04`, `sec-01`).
- **Schema**: this service uses Alembic (`apps/prototype-description-service/db/migrations/versions/`), not the `001_identity_schema.py` single-file pattern. MVP reuses the existing `audit_events` table (`db/models/observability.py:195`) and adds **no migration** (PA-04).
- **Greenfield**: no back-compat shims; the CLI stays but delegates key-minting to the same extracted service the router uses (no duplicated mint/hash logic — PA-03).
- **No new runtime/JS toolchain**: the console renders via hand-written `starlette.responses.HTMLResponse` — **no Jinja2, no HTMX, no `StaticFiles` mount** (Jinja2 is not a current dependency; HTMX has no delivery path on a tailnet-gated surface). Plain HTML forms POST and 303-redirect (review `complete-01/02`, `slice-01-jinja2-dep-missing`).
- **Raw key is unrecoverable** after mint (`secrets.token_urlsafe` + one-way hash); surfaced exactly once on the create response and never logged.

## Workflow Principles

- Single source of truth for key minting: one `mint_api_key` helper used by both the CLI and the router; it does not own the transaction (callers commit).
- Fail-closed (`validate_admin_config`): refuse to start when `RECOGNITION_ADMIN_ENABLED=true` and (`RECOGNITION_ADMIN_TOKEN` is empty **or** shorter than 32 chars), mirroring `_check_dev_key_guard` (`api/main.py:111-128`) and `validate_production_security` (`security.py:94-114`). When `RECOGNITION_RUNTIME_MODE=production` and admin is enabled, also require an explicit `RECOGNITION_ADMIN_TAILNET_BOUND=1` acknowledgement or refuse to start (review `sec-04`).
- Every state change (mint, revoke, tenant-create) writes an `audit_events` row **in the same request-scoped transaction** as the mutation (single commit), so no partial un-audited state is possible; revoke resolves `tenant_id` from the key first (`audit_events.tenant_id` is `NOT NULL` CASCADE — PA-04; review `sec-05`).
- Replicate the CLI's BR-02 env/DSN safety assertion in-process with an explicit `runtime_mode → {prod,local}` mapping so the guard is not a silent no-op (PA-05; review `slice-03-env-dsn-mirror-noop`).

## Terminology

- **Admin authority**: the combination of (tailnet-only reachability, enforced by the public-vhost `/admin*` deny) AND (valid `RECOGNITION_ADMIN_TOKEN` on the dedicated header). Either alone is insufficient by policy.
- **Mint**: generate a new raw API key, hash it, persist the hash, return the raw key once.
- **Operator**: the single human running the service (the "JUST ME" intake answer); not an end-user/tenant.

## Current State Analysis

- **Works**: `SqlAlchemyApiKeyRepository` (`recognition/infrastructure/repositories/api_key_repository.py`) exposes `create` (takes `expires_at: datetime`, no commit), `list_for_tenant`, `revoke`, `touch_by_id`, `get_by_hash`; `Tenant`/`ApiKey` models (`db/models/tenant.py:37,69`; `Tenant.site_url` is `unique NOT NULL`); `AuditService.record_event` (instance method on `AuditService()`, `recognition/application/services/audit_service.py:18`); `auth_enabled`/`api_key_hash_algorithm` config (`recognition/config/security.py:52-58`).
- **Missing**: any admin auth primitive (no `require_admin`, no admin header field), any `/admin` router, any env-gated `include_router` pattern, any audit write on key grant/revoke (`manage_api_keys.py` writes none; `auth_audit.py` is log-only), any public-vhost `/admin` deny, any tailnet binding for the app.
- **Misleading**: "thin wrap over manage_api_keys" understates net-new work — key minting + hashing live in the CLI command `_cmd_create` (`scripts/manage_api_keys.py:104-141`), not the repository (PA-03); the live deploy is `docker-compose.env.yml` + `docker-compose.caddy.yml` (per-env `${ACX_ENV}-api` alias → `prod-api`), **not** the single-env `docker-compose.prod.yml` whose bare `api` service does not match the Caddyfile's `prod-api` upstream (review `sec-02`).

## Target Outcome

A `RECOGNITION_ADMIN_ENABLED`-gated `/admin` router mounted on the recognition app, every route behind `Depends(require_admin)` on a dedicated `X-Admin-Token` header, exposing JSON endpoints plus a minimal hand-written HTML console (no Jinja2/HTMX/SPA). In production the public `api.altcontext.com` vhost returns `404` for `/admin*`, and the surface is reachable only over the tailnet (via `tailscale serve` or an `ssh -L` tunnel to `prod-api:8000`); the shared token is required on top. The operator opens the console, sees live tenants + key status, mints a key (shown once), and revokes — each action audit-logged atomically. `docs/workbay/contracts/security.md` is updated to record the deferred admin surface as shipped and what authority backs it.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Contracts: `docs/workbay/contracts/security.md` (§ Operator CLI / HTTP admin deferral, lines 401-448).
- Predecessor: `docs/tasks/15.0/E15-1-security-baseline-task-plan.md:99,196,275`.
- Deploy: `apps/prototype-description-service/Caddyfile`, `docker-compose.env.yml`, `docker-compose.caddy.yml`; host Tailscale runbook `infra/oci/README.md:130-423` (read-only reference).
- Handoff/MCP: decisions `claude_intake_tenant_admin_scope`, `claude_plan_analyze_resolve_open_qs` (#1073); findings `tenant-admin-PA-01..06` and the planning-review findings on `E15-31`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Recognition HTTP admin surface | backend | `docs/workbay/contracts/security.md:401-448` (admin surface "deferred") | Add `/admin` routes + admin authority; flip the deferral note to "shipped (tailnet + token)" | no — greenfield, no prior admin clients | API tests + updated contract section |
| API-key minting | backend | mint+hash inline in `scripts/manage_api_keys.py:104-141` | Extract to shared `mint_api_key`; CLI delegates | yes — CLI behavior must be unchanged | existing `test_manage_api_keys` stays green |
| Audit log | backend | `audit_events` written only by scene/retention | Add grant/revoke/tenant-create writers, atomic with the mutation | no | API test asserts audit row written + rollback on audit failure |
| Deploy topology | infra (in-app) | `Caddyfile` public vhost proxies all paths; live stack = `docker-compose.env.yml` + `docker-compose.caddy.yml` | Public-vhost `/admin*` deny + tailnet exposure + env vars | no | `caddy validate` + `curl …/admin/ → 404` runtime check |

## Proposed Solution

Five slices, each behavior-plus-proof. Slices 1–4 are app code with deterministic tests; Slice 5 is the deployment/network gate plus contract/runbook updates. The admin token gate (Slice 2) is enforced from the first endpoint so no slice ships an unauthenticated admin surface.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend (new) | `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py` | `async mint_api_key(session, tenant_id, tier, expires_in_days) -> tuple[ApiKey, str]` (+ `revoke_key`, `upsert_tenant` helpers); no commit (caller owns txn) |
| backend | `apps/prototype-description-service/scripts/manage_api_keys.py` | `_cmd_create` delegates to `mint_api_key` (remove inline `token_urlsafe`+hash; keep its `await session.commit()`) |
| backend (new) | `apps/prototype-description-service/recognition/interface_adapters/http/deps/admin_auth.py` | `require_admin` dependency; constant-time `secrets.compare_digest` on `RECOGNITION_ADMIN_TOKEN` read from the dedicated admin header |
| backend | `apps/prototype-description-service/recognition/config/security.py` | add `admin_enabled`, `admin_token`, `admin_header` (default `X-Admin-Token`) fields; add `validate_admin_config()` (token-empty / <32-char / production-without-ack) |
| backend (new) | `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py` | tenant + key lifecycle JSON endpoints + `GET /admin/` HTML console (HTMLResponse), all `Depends(require_admin)`; audit each mutation atomically; BR-02 env/DSN assertion with explicit mapping |
| backend (new) | `apps/prototype-description-service/recognition/interface_adapters/http/admin_console.py` | `render_console(tenants, keys, *, minted_key=None) -> str` hand-written HTML (escaped); no template engine |
| backend | `apps/prototype-description-service/api/main.py` | conditional `app.include_router(admin_router, prefix="/admin")` behind `admin_enabled`; call `validate_admin_config()` fail-closed at startup (mirror `_check_dev_key_guard`) |
| deploy | `apps/prototype-description-service/Caddyfile` | public `api.altcontext.com` vhost denies `/admin*` (`respond @admin 404`) before the catch-all `reverse_proxy` |
| deploy | `apps/prototype-description-service/docker-compose.env.yml`, `.env.prod.example` | publish api to host loopback for the tailnet path + `RECOGNITION_ADMIN_ENABLED` / `RECOGNITION_ADMIN_TOKEN` / `RECOGNITION_ADMIN_TAILNET_BOUND` env vars |
| docs | `docs/workbay/contracts/security.md` | flip the "HTTP admin surface deferred" note (lines 401-448) to "shipped"; document the tailnet+token authority |
| docs (new) | `docs/runbooks/admin-tenant-keys.md` | operator runbook: reach `/admin` over the tailnet (`tailscale serve` / `ssh -L`), replacing the manual `docker exec` flow; references `infra/oci/README.md` |
| docs | `docs/tasks/15.0/E15-29-public-demo-go-live-task-plan.md` | point the demo-key step at the runbook instead of manual `docker exec` |

## Related Files

| File | Note |
| --- | --- |
| `recognition/infrastructure/repositories/api_key_repository.py:67,96,105,116` | reused for create/list/revoke/touch; `create` takes `expires_at` and does not commit |
| `db/models/tenant.py:37,41,69` | `Tenant`/`ApiKey`; `Tenant.site_url` unique NOT NULL; `ApiKey.tenant_id` FK CASCADE |
| `db/models/observability.py:195-217` | `audit_events` (tenant_id NOT NULL CASCADE) — reused, no migration |
| `api/main.py:111-128` | `_check_dev_key_guard` — the fail-closed startup pattern to mirror |
| `recognition/config/security.py:94-114` | `validate_production_security` — prod boot-refusal pattern to mirror for `validate_admin_config` |
| `recognition/shared/ids.py:16` | UUIDv7 generator — not used; tenant_id is client-supplied to match the CLI |

## Verification Strategy

- Deterministic tests (run from `apps/prototype-description-service/`):
  - `pytest recognition/tests/scripts/test_manage_api_keys.py` — CLI unchanged after mint extraction (Slice 1).
  - `pytest recognition/tests/api/test_admin_auth.py` — token valid/invalid/missing; tenant API key on an `/admin` route → 401; fail-closed (empty/<32-char/production-no-ack) raises (Slices 2).
  - `pytest recognition/tests/api/test_admin_router.py` — create→list→mint→revoke; auth required on every route; audit row per mutation; injected audit failure rolls back the mutation; unknown tenant on mint → 404; duplicate site_url → 409; revoke-already-revoked → 200 idempotent; env/DSN guard refuses production+local-DSN (Slice 3).
  - `pytest recognition/tests/api/test_admin_mount.py` — `/admin/` 404 when disabled; mounted + console HTML renders when enabled; startup raises when enabled w/o valid token (Slice 4).
- Contract/fixture verification:
  - Slice 5: `grep -c "deferred" docs/workbay/contracts/security.md` returns 0 inside the rewritten Operator-CLI/admin section, and the section contains the post-edit anchors `RECOGNITION_ADMIN_TOKEN` + `tailnet`.
- Runtime-parity / manual verification:
  - `caddy validate --config Caddyfile --adapter caddyfile`; with the stack up, `curl -so /dev/null -w "%{http_code}" https://api.altcontext.com/admin/` returns `404`, while the tailnet path (`tailscale serve` URL or `ssh -L` tunnel) serves `/admin/`.
  - With `RECOGNITION_ADMIN_ENABLED=true` + token, mint a key over the tailnet, confirm it authenticates a recognition request, revoke it, confirm 401 thereafter.

## Slice Delivery

### Slice 1: Extract shared key-minting service

**Goal**: One `mint_api_key` helper owns token generation + hashing; the CLI delegates with no behavior change.

Changes:
- Add `api_key_admin_service.py` with `async mint_api_key(session, tenant_id: uuid.UUID, tier: RateLimitTier, expires_in_days: int | None) -> tuple[ApiKey, str]`: converts days → UTC `expires_at` internally (`datetime.now(tz=UTC)+timedelta(days=...)`, mirroring `manage_api_keys.py:111-113`), `secrets.token_urlsafe(32)` + `hashlib.new(get_security_settings().api_key_hash_algorithm)`, calls `SqlAlchemyApiKeyRepository.create(...)`, returns `(record, raw)`. **Does not commit** — callers own the transaction.
- `scripts/manage_api_keys.py:_cmd_create` calls `mint_api_key` then keeps its existing `await session.commit()`; inline mint/hash deleted.

Proof:
- New unit test: minted raw key hashes to a value `SqlAlchemyApiKeyRepository.get_by_hash` resolves; helper performs no commit (caller controls).
- `pytest recognition/tests/scripts/test_manage_api_keys.py` stays green.

### Slice 2: `require_admin` dependency + admin config (fail-closed)

**Goal**: A reusable, strictly-separate admin gate that fails closed.

Changes:
- `security.py`: add `admin_enabled` (`RECOGNITION_ADMIN_ENABLED`, default false), `admin_token` (`RECOGNITION_ADMIN_TOKEN`), `admin_header` (`RECOGNITION_ADMIN_TOKEN_HEADER`, default `X-Admin-Token`). Add `validate_admin_config()` raising when admin_enabled and (token empty **or** `len(token) < 32`), and — when `RECOGNITION_RUNTIME_MODE=production` and admin_enabled — raising unless `RECOGNITION_ADMIN_TAILNET_BOUND=1` is set (mirror `validate_production_security`).
- `deps/admin_auth.py`: `require_admin` reads `settings.admin_header` (never `api_key_header`/DB/`is_admin`), `secrets.compare_digest` against `admin_token`, raises 401 on missing/mismatch.

Proof:
- `pytest recognition/tests/api/test_admin_auth.py`: valid token → pass; wrong/missing → 401; a valid **tenant API key** presented to an `/admin` route → 401 (separation locked in); `validate_admin_config` raises for empty token, <32-char token, and production+enabled-without-ack; passes with ack.

### Slice 3: Admin REST endpoints + atomic audit wiring

**Goal**: Tenant + key lifecycle over JSON, every route gated, every mutation audited atomically.

Changes:
- `routers/admin.py`:
  - `POST /admin/tenants` — request `{tenant_id: UUID (client-supplied, matches CLI), site_url}`; upsert; duplicate `site_url` (unique constraint) → 409.
  - `GET /admin/tenants` — list.
  - `POST /admin/tenants/{tenant_id}/keys` — mint → raw key once; unknown tenant (FK IntegrityError, as caught at `manage_api_keys.py:124-133`) → 404.
  - `GET /admin/tenants/{tenant_id}/keys` — status/created/last_used/expires/revoked.
  - `POST /admin/keys/{key_id}/revoke` — unknown key → 404; already-revoked → 200 idempotent (preserve original `revoked_at`, no re-stamp).
  - All `dependencies=[Depends(require_admin)]`.
- Each mutation: `AuditService().record_event(session, tenant_id=str(tenant_id), event_type=<enum>, actor="admin", scope="admin_router", payload={...})` **on the same session/transaction as the mutation** (single commit; injected audit failure rolls back the mutation). `event_type` values come from a single `AdminAuditEvent` `StrEnum` (`api_key.mint`/`api_key.revoke`/`tenant.create`) per sr-007. Revoke resolves `tenant_id` from the `ApiKey` before auditing.
- Router/app init asserts env/DSN agreement: map `runtime_mode == "production" → "prod"`, else `→ "local"`, pass with `postgres_dsn` into `_validate_env_vs_dsn`, raise on non-None (fail-closed) — not a silent no-op.

Proof:
- `pytest recognition/tests/api/test_admin_router.py`: full create→list→mint→revoke; 401 on every route without token; an `audit_events` row per mutation; injected audit-write failure rolls back the mint/revoke (no orphaned state); unknown tenant → 404; duplicate site_url → 409; revoke-already-revoked → 200 idempotent; env/DSN guard refuses `production`+local-DSN and passes non-production+local-DSN.

### Slice 4: Env-gated mount + hand-written HTML console

**Goal**: `/admin` exists only when enabled; minimal console; zero new dependency.

Changes:
- `api/main.py`: in `create_app`, when `security.admin_enabled` call `validate_admin_config()` (fail-closed, mirroring `_check_dev_key_guard` at `api/main.py:111-128,134`) then `app.include_router(admin_router, prefix="/admin")`.
- `admin_console.py` + `GET /admin/` route: `render_console(...) -> str` returns an escaped hand-written HTML page (`starlette.responses.HTMLResponse`) — tenant/key table, create-tenant+mint form, revoke buttons — using plain HTML `<form method=post>` that 303-redirect back to `/admin/`. Raw key rendered once on the mint response page. **No Jinja2, no HTMX, no StaticFiles.**

Proof:
- `pytest recognition/tests/api/test_admin_mount.py`: disabled → `/admin/` 404; enabled → mounted + `GET /admin/` returns 200 HTML containing the form; enabled w/o valid token → startup raises. (No `import jinja2` anywhere — assert the module imports with only stdlib + starlette.)

### Slice 5: Public-vhost deny + tailnet exposure + contract/runbook

**Goal**: In production `/admin` is denied on the public vhost and reachable only over the tailnet; the deferral contract is resolved.

Changes:
- `Caddyfile` — in the `api.altcontext.com` block, before the catch-all proxy:
  ```
  api.altcontext.com {
      @admin path /admin /admin/*
      respond @admin 404
      reverse_proxy prod-api:8000
  }
  ```
  (404, not 403, to avoid confirming the surface exists.)
- Tailnet exposure (host-level Tailscale already installed per `infra/oci/README.md`): publish the api container to the VM loopback (`docker-compose.env.yml`: `ports: ["127.0.0.1:8000:8000"]`) and expose `/admin` on the tailnet via `tailscale serve --bg --https=443 --set-path /admin http://127.0.0.1:8000/admin`; **or** document an `ssh -L 8001:127.0.0.1:8000 <vm-over-tailnet>` operator tunnel. The mandatory invariant (either path): the public vhost denies `/admin*`; the tailnet path serves it; the admin token is still required.
- `.env.prod.example`: add `RECOGNITION_ADMIN_ENABLED`, `RECOGNITION_ADMIN_TOKEN` (note: generate via `python -c "import secrets; print(secrets.token_urlsafe(32))"`), `RECOGNITION_ADMIN_TAILNET_BOUND=1`.
- `docs/workbay/contracts/security.md:401-448`: flip "HTTP admin surface: deferred" → shipped; document tailnet + shared-token authority and the public-vhost deny.
- `docs/runbooks/admin-tenant-keys.md` (new) + `E15-29` go-live: operator reaches `/admin` over the tailnet instead of `docker exec ... manage_api_keys`; references `infra/oci/README.md`.

Proof:
- `caddy validate --config Caddyfile --adapter caddyfile`; runtime parity: `curl -so /dev/null -w "%{http_code}" https://api.altcontext.com/admin/` → `404`; tailnet path serves `/admin/`.
- `grep -c "deferred" docs/workbay/contracts/security.md` → 0 within the rewritten admin section; section contains anchors `RECOGNITION_ADMIN_TOKEN` and `tailnet`.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded `security.md` admin-deferral contract, `E15-1` predecessor, the live deploy files (`Caddyfile`/`docker-compose.env.yml`/`docker-compose.caddy.yml`), and the MAINT plan-analyze findings/decision before editing.
- [ ] Recorded boundary ownership (admin surface, mint, audit, deploy) and confirmed no prior admin client needs compatibility.

### Checklist for Slice 1: Extract shared key-minting service

- [ ] `api_key_admin_service.mint_api_key`: days→`expires_at`, token+hash via `get_security_settings().api_key_hash_algorithm`, returns `(ApiKey, raw)`, no commit.
- [ ] `manage_api_keys._cmd_create` delegates; keeps its own commit; inline mint/hash deleted.
- [ ] Unit test mint→`get_by_hash`; `test_manage_api_keys.py` green.

### Checklist for Slice 2: `require_admin` dependency + admin config

- [ ] Add `admin_enabled`, `admin_token`, `admin_header` (`X-Admin-Token`) to `security.py`.
- [ ] `validate_admin_config`: empty / <32-char token + production-without-`RECOGNITION_ADMIN_TAILNET_BOUND` all raise.
- [ ] `deps/admin_auth.require_admin` reads the dedicated header, `secrets.compare_digest`, never `api_key_header`/DB/`is_admin`.
- [ ] `test_admin_auth.py`: valid/invalid/missing + tenant-key→401 + all fail-closed cases.

### Checklist for Slice 3: Admin REST endpoints + atomic audit wiring

- [ ] `routers/admin.py` with the five endpoints, all `Depends(require_admin)`.
- [ ] `AdminAuditEvent` StrEnum; each mutation writes `audit_events` via `AuditService()` atomically (single commit); revoke resolves tenant first.
- [ ] Error contract: unknown tenant→404, duplicate site_url→409, revoke-already-revoked→200 idempotent.
- [ ] Env/DSN guard with explicit `runtime_mode→{prod,local}` mapping (not a no-op).
- [ ] `test_admin_router.py` covers flow + auth + audit + rollback + all error cases + env/DSN negative case.

### Checklist for Slice 4: Env-gated mount + hand-written HTML console

- [ ] Conditional mount + fail-closed `validate_admin_config()` in `api/main.py`.
- [ ] `admin_console.render_console` (HTMLResponse, escaped) + `GET /admin/`; plain forms, 303 redirect; raw key shown once; no Jinja2/HTMX/StaticFiles.
- [ ] `test_admin_mount.py` covers disabled/enabled/render/no-token; asserts no `jinja2` import.

### Checklist for Slice 5: Public-vhost deny + tailnet exposure + contract/runbook

- [ ] `Caddyfile` public `api.altcontext.com` denies `/admin*` (404) before the catch-all proxy.
- [ ] `docker-compose.env.yml` loopback publish + `.env.prod.example` admin vars (incl. `RECOGNITION_ADMIN_TAILNET_BOUND`); tailnet path (`tailscale serve`/`ssh -L`) documented.
- [ ] `security.md` admin-deferral note flipped to shipped with authority documented.
- [ ] `docs/runbooks/admin-tenant-keys.md` + `E15-29` updated to `/admin`-over-tailnet.

## Review Readiness

- [ ] No boundary-touching change without matching contract/test evidence (admin surface ↔ security.md; mint ↔ CLI test).
- [ ] Runtime-parity captured for Slice 5 (public `/admin/`→404 + tailnet path serves) — config-only validation cannot prove off-tailnet unreachability.
- [ ] Handoff decision records each slice + verification + the security.md contract change.

## Stretch Goals

- [ ] `GET /admin/keys/{key_id}/usage` last-used detail view.
- [ ] Rotate-in-place convenience (mint new + revoke old in one action) on the console.

## Success Criteria

- [ ] Operator mints and revokes a tenant key from `/admin/` over the tailnet in seconds; raw key shown once.
- [ ] `/admin` returns 401 without the admin token; the public `api.altcontext.com` vhost returns 404 for `/admin*` (the mechanism backing "unreachable off-tailnet").
- [ ] Every mint/revoke/tenant-create writes an `audit_events` row atomically with the mutation.
- [ ] `manage_api_keys` CLI behavior unchanged (mint logic now shared, not duplicated).
- [ ] `docs/workbay/contracts/security.md` records the admin surface as shipped with its authority.
