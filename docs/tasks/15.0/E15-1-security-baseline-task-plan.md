# E15-1. Security Baseline: Rate Limiting, Origin Policy, and Key Rotation

> **Metadata**
>
> - **Date**: 2026-04-06
> - **Author**: Claude Opus 4.6
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-1-security-baseline`
> - **Review Coverage Target**: 2

---

## Objective

Close the remaining security gaps that block public internet exposure of the recognition service. When this task is complete, the API enforces rate limits, rejects non-allowlisted browser origins, supports no-downtime key rotation, and emits audit-trail log events for every authentication decision (success and failure) with a non-reversible key fingerprint.

### Explicit deliverable: auth-event fingerprint logging

The owning epic lists "audit logging of auth events with key fingerprint" as an E15-1 deliverable. This plan delivers it as part of Slice 3 (key lifecycle) rather than deferring it, because the fingerprint derivation must be consistent with the key-storage hash already introduced by the lifecycle work. Scope: every `require_auth` outcome (success, invalid key, expired, revoked, tenant mismatch) emits a structured log entry containing `api_key_id` (when resolvable), a 12-char prefix of the stored hash (never the raw key), tenant claim, outcome code, and trace id. Rate-limit 429 events reuse the same emitter.

## Problem Statement

API key authentication and tenant isolation are already implemented (`auth.py`, `security.py`, `api_key_repository.py`). Three gaps remain:

1. **Rate limiting is configured but not enforced.** `SecuritySettings` defines `rate_limit_requests_per_minute=60` and `rate_limit_burst=10`, but no middleware applies them. A single client can send unlimited requests.
2. **No browser origin policy.** No `CORSMiddleware` or origin allowlist exists. Any origin can call privileged endpoints from a browser.
3. **No key rotation support.** The `api_keys` table supports multiple keys per tenant, but there is no documented rotation ceremony, no expiration, and no mechanism to have two valid keys during cutover.

## Constraints

- Scope is `apps/prototype-description-service/` only; no WP plugin changes.
- Rate limiting must be per-API-key (not per-IP) to support multi-tenant fairness.
- **Rate-limit deployment assumption**: the public demo runs a **single worker process** (uvicorn default or `--workers 1`). The in-memory counter is correct only under this assumption. Multi-worker deployment requires a shared counter store (Redis/DB) and is explicitly out of scope for this task — a follow-up task must introduce the shared store before horizontal scaling. This constraint is a success criterion, not an aspiration.
- **CORS scope justification**: the WP plugin is a server-side PHP caller (`wp_remote_post`) and does not require CORS. The `CORSMiddleware` + origin allowlist introduced by Slice 2 is a **defensive guard for future browser-origin callers** (e.g. an operator admin UI or a marketing-site demo widget) that are anticipated but do not yet exist. The default origin allowlist is empty (deny-all) so the middleware is inert until an operator explicitly opts in an origin. If no browser caller materializes by the end of v0.4.0, Slice 2 may be removed in a follow-up task.
- Key rotation must work without downtime: old key remains valid until explicitly revoked.
- No new Python dependencies unless strictly necessary; prefer FastAPI/Starlette built-ins where possible.
- Branch isolation: all code changes on `feature/e15-1-security-baseline`, not `main`.

## Workflow Principles

- Wire existing configuration before adding new configuration. `SecuritySettings` already has rate limit fields; use them.
- Security contract (`docs/agentic/contracts/security.md`) is the boundary doc; update it in the same slices as behavior changes.
- Tests first: each slice adds failing tests before the implementation.

## Terminology

- **Rate limit tier**: The `rate_limit_tier` field on `ApiKey` that can override the global default. Values are constrained to a centralized `RateLimitTier` StrEnum defined in `recognition/config/security.py`:
  - `STANDARD` (default; uses `SecuritySettings.rate_limit_requests_per_minute`, currently 60 RPM)
  - `PRO` (3× standard = 180 RPM)
  - `ENTERPRISE` (10× standard = 600 RPM; also used for dev/admin keys, see dev-key policy below)
  Existing DB rows with `rate_limit_tier='free'` (legacy test fixture) are reconciled to `STANDARD` in Slice 1 and the column value set is asserted via a migration-time check. Per short rule sr-007, all tier comparisons reference the enum; no scattered string literals.
- **Origin allowlist**: A configured list of browser origins permitted to make cross-origin requests.
- **Key rotation**: The ability to have two valid API keys for the same tenant simultaneously, allowing the old key to be revoked after the new key is verified.

## Current State Analysis

### What works

- API key validation: `require_auth` dependency in `auth.py` validates Bearer/X-Api-Key headers against hashed keys in the DB.
- Tenant isolation: `X-Tenant-ID` header checked against key's `tenant_claim`.
- Write access control: `require_write_access` gates POST/PATCH endpoints.
- Security configuration: `SecuritySettings` in `recognition/config/security.py` loads rate limit settings from env vars.
- `AuthContext` already carries `rate_limit_tier` from the resolved API key.
- Error handling: exception handlers generate trace IDs for all error responses.

### What is broken or missing

- `SecuritySettings.rate_limit_requests_per_minute` and `rate_limit_burst` are loaded but never read by any middleware.
- No `CORSMiddleware` in `api/main.py`.
- No `RECOGNITION_ALLOWED_ORIGINS` or equivalent env var.
- `ApiKey` model has no `expires_at` or `revoked_at` column.
- No key creation/revocation API endpoint (keys are currently seeded manually or via direct DB insert).
- Security contract (`docs/agentic/contracts/security.md`) documents auth but not rate limiting or CORS.

## Target Outcome

The deployed API at `api.altcontext.com` enforces per-key rate limits (429 with `Retry-After` on breach), rejects cross-origin requests from non-allowlisted domains, and allows operators to rotate API keys without downtime. The security contract documents all three behaviors.

## Context Loading

- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Rules: `docs/agentic/rules/testing-python.md`
- Context map: `docs/agentic/maps/backend.md`
- Contract: `docs/agentic/contracts/security.md`
- External docs via `ctx7` only if: FastAPI CORSMiddleware behavior or Starlette rate-limiting patterns need verification

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|----------|-------|-----------------|----------------|----------------------|--------------|
| HTTP security | Backend | `docs/agentic/contracts/security.md` | Add rate limiting, CORS, rotation sections | No (greenfield) | Integration tests |
| WP plugin auth | PHP Plugin | `src/api/class-sync-status-controller.php` | None (plugin already sends API key) | N/A | N/A |

## Proposed Solution

1. **Rate limiting via dependency, not middleware.** The current call flow resolves the API key inside the `require_auth` FastAPI dependency (after middleware). Middleware cannot see `AuthContext.api_key_id`/`rate_limit_tier` without duplicating the auth/DB lookup. The correct seam is a `Depends(require_auth) → Depends(enforce_rate_limit)` chain that runs after authentication has resolved the key identity. Implementation: a `RateLimiter` dependency that reads `AuthContext` from the prior dependency, applies a sliding-window counter keyed by `api_key_id`, and raises `HTTPException(429, ...)` with `Retry-After` headers via the existing exception-handler pattern. Storage: in-memory dict with `asyncio.Lock` for single-process MVP.
2. Add `CORSMiddleware` with `RECOGNITION_ALLOWED_ORIGINS` env var. Default to empty (deny all browser CORS) unless explicitly configured.
3. Add `expires_at` and `revoked_at` columns to `ApiKey`. Modify `require_auth` and `api_key_repository` to reject expired/revoked keys. Provision new keys via a documented operator CLI (`scripts/manage_api_keys.py`) and an out-of-band ceremony, **not** an HTTP admin router (the current `is_admin` flag is dev-key-only and cannot gate a production admin surface without first defining a real admin authority -- out of scope for this task).

## Files and Surfaces to Change

| Surface | File | Change |
|---------|------|--------|
| Rate limit dependency | `recognition/interface_adapters/http/deps/rate_limit.py` | New: `enforce_rate_limit` dependency that consumes `AuthContext` from `require_auth` |
| Auth dependency | `recognition/interface_adapters/http/deps/auth.py` | Add expiry/revocation checks; wire `Depends(require_auth)` upstream of rate limit |
| Router wiring | `recognition/interface_adapters/http/routers/*.py` | Replace `Depends(require_auth)` with the chained `Depends(require_auth) + Depends(enforce_rate_limit)` on protected routers |
| Security config | `recognition/config/security.py` | Add `allowed_origins` field; reuse existing `rate_limit_requests_per_minute` / `rate_limit_burst` |
| App wiring | `api/main.py` | Register `CORSMiddleware`; add fail-closed startup guard that raises when `RecognitionSettings.runtime_mode == "production"` and `SecuritySettings.dev_api_keys` is non-empty |
| Auth audit log | `recognition/interface_adapters/http/deps/auth.py` + new `recognition/observability/auth_audit.py` | Emit structured log event (`api_key_id`, hash-prefix fingerprint, tenant claim, outcome code, trace id) on every `require_auth` decision and 429 rate-limit event |
| DB model | `db/models/tenant.py` | Add `expires_at`, `revoked_at` to ApiKey |
| Schema | `db/migrations/versions/001_identity_schema.py` | Edit baseline (greenfield policy: no follow-on migration) |
| API key repository | `recognition/infrastructure/repositories/api_key_repository.py` | Filter expired/revoked keys in lookup |
| Operator CLI | `apps/prototype-description-service/scripts/manage_api_keys.py` | New: `create`, `list`, `revoke` subcommands operating directly against the DB |
| Security contract | `docs/agentic/contracts/security.md` | Add rate limiting, CORS, rotation, and key-provisioning ceremony docs |
| Env template | `.env.prod.example` | Add `RECOGNITION_ALLOWED_ORIGINS` |
| Tests | `recognition/tests/api/test_rate_limiting.py` | New |
| Tests | `recognition/tests/api/test_cors.py` | New |
| Tests | `recognition/tests/api/test_key_rotation.py` | New (covers lifecycle + repository behavior, not HTTP admin) |
| Tests | `recognition/tests/scripts/test_manage_api_keys.py` | New (CLI behavior) |

## Related Files

| File | Note |
|------|------|
| `recognition/interface_adapters/http/exception_handlers.py` | Already handles 503 with Retry-After; rate limit 429 follows same pattern |
| `recognition/interface_adapters/http/deps/auth.py` | Core auth logic; rate limit tier is already in AuthContext |
| `db/migrations/versions/001_identity_schema.py` | Greenfield: schema changes go directly here |

## Verification Strategy

- Deterministic tests:
  - `VIRTUAL_ENV= uv run --locked --extra dev python -m pytest recognition/tests/api/test_rate_limiting.py -v`
  - `VIRTUAL_ENV= uv run --locked --extra dev python -m pytest recognition/tests/api/test_cors.py -v`
  - `VIRTUAL_ENV= uv run --locked --extra dev python -m pytest recognition/tests/api/test_key_rotation.py -v`
- Runtime-parity (must exercise **protected** endpoints — the `/health` root is intentionally unauthenticated and would pass even if auth/rate-limit wiring regressed):
  - `curl -H "X-Api-Key: <key>" -H "X-Tenant-ID: <tenant>" https://api.altcontext.com/recognition/health/pool` returns 200
  - Repeated rapid requests against `/recognition/clusters` (a protected route under `enforce_rate_limit`) trigger 429 with `Retry-After` header
  - `curl -H "Origin: https://evil.com" -H "X-Api-Key: <key>" -I https://api.altcontext.com/recognition/clusters` returns no `Access-Control-Allow-Origin` header
  - Revoked-key smoke: `manage_api_keys.py revoke --key-id <id>`, then a request with that key returns 401
- Contract verification:
  - Security contract documents rate limiting, CORS, and rotation behavior

## Slice Delivery

### Slice 1: Rate Limiting via Auth-Chained Dependency

**Goal**: Enforce per-key rate limits with deterministic 429 responses, using a dependency seam that runs **after** `require_auth` resolves the key identity.

**Why not middleware:** FastAPI middleware runs before route dependencies, so it cannot see `AuthContext.api_key_id` without duplicating the DB lookup that already happens in `require_auth`. The correct seam is a `Depends(enforce_rate_limit)` that consumes the resolved `AuthContext` from a chained `Depends(require_auth)`.

Changes:

- Add `RateLimitTier` StrEnum to `recognition/config/security.py` with `STANDARD`/`PRO`/`ENTERPRISE` values and a `tier_rpm(tier, settings) -> int` helper that maps tier → RPM using `SecuritySettings.rate_limit_requests_per_minute` as the `STANDARD` baseline. Reconcile existing `'free'` string in `test_authentication.py` fixture to `RateLimitTier.STANDARD`.
- Add `recognition/interface_adapters/http/deps/rate_limit.py` with `enforce_rate_limit(auth: AuthContext = Depends(require_auth))` — sliding-window counter keyed by `auth.api_key_id`, applying `RateLimitTier(auth.rate_limit_tier).tier_rpm(...)` if set, falling back to `STANDARD`.
- **Dev/admin-key policy**: dev keys from `RECOGNITION_ALLOWED_API_KEYS` resolve to `api_key_id=None` in `auth.py` (line 212). These keys **bypass the limiter entirely** — they are local-only debugging keys per the security contract and must never ship to production. The limiter's `enforce_rate_limit` returns early with a no-op when `auth.api_key_id is None and auth.is_admin`.
- **Fail-closed production guard**: add a startup check in `api/main.py` that raises `RuntimeError` (refusing to start the app) when `RecognitionSettings.runtime_mode == "production"` AND `SecuritySettings.dev_api_keys` is non-empty. This reuses the existing runtime signal (`RECOGNITION_RUNTIME_MODE`, default `"production"`, already read by `recognition/config/settings.py:71` and set by `.env.prod.example:23`) — **no new env var is introduced**. A log-only warning is insufficient because operator misconfiguration must not silently ship dev-key semantics into a public environment. In non-production modes (`RECOGNITION_RUNTIME_MODE=test` or any other value) the check downgrades to a WARNING-level log. `.env.prod.example` must ship with `RECOGNITION_ALLOWED_API_KEYS=` (empty) rather than any `CHANGE_ME` placeholder — a non-empty placeholder value will trip the fail-closed guard on accidental copy-paste deployment. The existing `ACX_ENV` env var (consumed by deploy tooling, not the Python runtime) is intentionally **not** the signal here, because the guard must be evaluated inside the FastAPI process against config that the process itself sees.
- **429 response shape**: raise plain `HTTPException(status_code=429, detail="rate limit exceeded")` with `Retry-After` and `X-RateLimit-*` response headers, **matching the auth-boundary pattern** used by `require_auth` 401/403 errors (not the structured envelope used by domain errors like `RecognitionError`). This is pinned to avoid divergence between implementation and tests. Document the shape in `contracts/security.md` alongside the existing 401/403 section.
- Update protected routers (`analyze.py`, `clusters.py`, `retention.py`, etc.) to depend on `enforce_rate_limit` in addition to `require_auth`. The chained dependency naturally pulls the auth context.
- Add `recognition/tests/api/test_rate_limiting.py` with tests for: under limit (200), at limit (429), burst handling, per-key isolation (different keys do not share counters), `Retry-After` header presence, tier override behavior, **dev-key bypass** (a key from `RECOGNITION_ALLOWED_API_KEYS` is never rate-limited), and **auth-disabled bypass** (`RECOGNITION_AUTH_ENABLED=false` — limiter is a no-op since there is no key identity).
- Update `docs/agentic/contracts/security.md` rate limiting section.

Proof:

- `pytest recognition/tests/api/test_rate_limiting.py` passes
- Rate limit headers present in integration test responses
- Anonymous/disabled-auth requests and dev keys bypass the limiter, asserted by dedicated tests

### Slice 2: CORS Origin Allowlist

**Goal**: Reject cross-origin browser requests from non-allowlisted domains.

Changes:

- Add `allowed_origins: list[str]` to `SecuritySettings` (env: `RECOGNITION_ALLOWED_ORIGINS`, comma-separated). Default is empty list (deny-all).
- Register `CORSMiddleware` in `api/main.py` with **pinned secure defaults**:
  - `allow_origins=settings.allowed_origins` (exact match only)
  - `allow_credentials=False` (never `True` — would enable cross-origin credential leaks with any permissive origin)
  - `allow_origin_regex=None` (no regex — exact match only to avoid over-broad patterns)
  - `allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"]` (explicit list, not `*`)
  - `allow_headers=["Authorization", "X-Api-Key", "X-Tenant-ID", "Content-Type"]` (explicit list, not `*`)
  - `max_age=600` (10-minute preflight cache)
- Add `recognition/tests/api/test_cors.py` with tests for: allowlisted origin gets CORS headers, non-allowlisted origin does not, preflight OPTIONS returns correct headers, empty allowlist blocks all CORS, **`Access-Control-Allow-Credentials` header is absent from responses** (Starlette's `CORSMiddleware` omits the header entirely when `allow_credentials=False`, so the test asserts absence rather than `== "false"`), **wildcard origin (`*`) rejected by config validation**.
- Update `.env.prod.example` with `RECOGNITION_ALLOWED_ORIGINS` (including a comment that the deploy defaults to empty = no browser CORS).
- Update security contract CORS section with the secure-defaults rationale.

Proof:

- `pytest recognition/tests/api/test_cors.py` passes
- Contract documents CORS behavior

### Slice 3: Key Lifecycle, Rotation, and Operator CLI Provisioning

**Goal**: Support no-downtime key rotation, explicit revocation, expiry, and an operator-side CLI for provisioning beta-tester keys -- without introducing an HTTP admin surface gated by an authority that does not yet exist.

**Why not an HTTP admin router:** The current `is_admin` flag in `AuthContext` is set only for `RECOGNITION_ALLOWED_API_KEYS` dev keys -- DB-backed production keys always return `is_admin=False`. The security contract explicitly marks dev keys as local-only debugging keys. Building HTTP admin endpoints behind `is_admin` would either be unreachable in production (no admin keys exist) or would require shipping dev-key semantics into production, which contradicts the security baseline this task is meant to establish. A real production admin authority is a separate design concern out of scope for E15-1.

**Operator workflow for this task:** beta-tester key provisioning happens via a CLI run by the operator with direct DB access. The CLI is a Python module under `scripts/manage_api_keys.py` that delegates persistence to the API-key repository. The current `SqlAlchemyApiKeyRepository` only exposes `get_by_hash`/`touch`/`touch_by_id`, so this slice extends it with explicit write-boundary methods (`create`, `list_for_tenant`, `revoke`, `mark_expired_if_due`) before the CLI can call them; the CLI never issues raw SQL. Once a future admin-authority design is settled, an HTTP admin surface can be added in a follow-up task on top of those same repository methods.

Changes:

- Add `expires_at: datetime | None` and `revoked_at: datetime | None` to `ApiKey` model in `db/models/tenant.py`.
- Edit baseline schema `db/migrations/versions/001_identity_schema.py` with the new columns (greenfield policy: no follow-on migration file).
- Extend `SqlAlchemyApiKeyRepository` (`recognition/infrastructure/repositories/api_key_repository.py`) with explicit write-boundary methods the CLI and `require_auth` path both call:
  - `get_by_hash(...)` (existing) now filters `revoked_at IS NOT NULL` and `expires_at < now()` out of lookup
  - `create(tenant_id, hashed_key, rate_limit_tier, expires_at=None) -> ApiKey`
  - `list_for_tenant(tenant_id, include_revoked=False) -> list[ApiKey]`
  - `revoke(api_key_id, now=...) -> ApiKey` (soft-revoke: sets `revoked_at`)
  - All write methods are async, commit on the caller's session, and return the persisted row so the CLI can print deterministic output.
- Modify `auth.py` `require_auth` to surface expired/revoked rejections with a descriptive 401 detail.
- Add `apps/prototype-description-service/scripts/manage_api_keys.py` CLI with subcommands that delegate to the repository methods above (never raw SQL):
  - `create --tenant <id> [--expires-in <days>] [--tier <STANDARD|PRO|ENTERPRISE>]` — generates a raw key via `secrets.token_urlsafe(32)`, hashes it with the configured `api_key_hash_algorithm`, calls `repo.create(...)`, prints the raw key once to stdout
  - `list --tenant <id> [--include-revoked]` — calls `repo.list_for_tenant(...)` and prints (id, last4, created_at, last_used_at, expires_at, revoked_at)
  - `revoke --key-id <id>` — calls `repo.revoke(...)`
- **Expiry semantics (pinned)**: key expiry is evaluated **per-request at the `require_auth` boundary only**. A request that passes `require_auth` at time T with a still-valid key completes normally even if the key expires at T+ε — in-flight requests are never interrupted. This matches how `revoked_at` is checked and avoids mid-request 401s.
- **Rotation runbook (documented in `contracts/security.md`)**:
  1. Operator runs `manage_api_keys.py create --tenant <id>` and captures the raw key from stdout.
  2. **If the raw key is lost before it can be shared with the tester**: operator runs `manage_api_keys.py revoke --key-id <id>` on the just-created key and starts the ceremony over. The DB stores only the hash, so a lost raw key cannot be recovered — this is by design.
  3. Operator shares the raw key with the tester through an operator-approved secure channel (e.g. 1Password shared vault, Signal). Plaintext email or Slack DMs are explicitly disallowed.
  4. Tester configures the new key in the plugin Settings page.
  5. **Before revoking the old key**: operator runs `manage_api_keys.py list --tenant <id>` and confirms the new key's `last_used_at` is non-null and more recent than the old key's `last_used_at`. This is the signal that the tester has successfully cut over.
  6. Operator runs `manage_api_keys.py revoke --key-id <old-key-id>` to soft-revoke the old key.
- Add `recognition/observability/auth_audit.py` with `emit_auth_event(outcome, api_key_id, key_hash, tenant_claim, trace_id)` — derives the fingerprint as `key_hash[:12]` (stored hash prefix; never touches the raw key) and logs a structured record via the standard logging stack. `require_auth` calls the emitter on every terminal path (success, 401, 403) and `enforce_rate_limit` calls it on 429. Raw API keys are never passed to the emitter.
- Add `recognition/tests/api/test_key_rotation.py`: expired key rejected, revoked key rejected, two keys valid simultaneously, **in-flight request started before expiry completes normally even if expiry lapses during processing**.
- Add `recognition/tests/api/test_auth_audit.py`: success / invalid-key / expired / revoked / tenant-mismatch / rate-limit paths each emit exactly one structured log record; the record contains `api_key_id` when resolvable and a 12-char hash-prefix fingerprint; the raw API key value never appears in any log record captured by `caplog`.
- Add `recognition/tests/scripts/test_manage_api_keys.py`: CLI create/list/revoke happy paths, error cases, masking of stored hashes.
- Update security contract: add the rotation/lifecycle behavior, the CLI provisioning ceremony, and an explicit note that an HTTP admin surface is deferred until a production admin authority is defined.
- Document beta-tester onboarding flow in the security contract: operator runs `manage_api_keys.py create` for the tester's tenant, gives the raw key to the tester via a secure channel once, tester configures it in the plugin Settings page (which already accepts the key as a WP option).

Proof:

- `pytest recognition/tests/api/test_key_rotation.py` passes
- `pytest recognition/tests/scripts/test_manage_api_keys.py` passes
- Full test suite passes: `make check` from `apps/prototype-description-service/`
- Security contract documents CLI ceremony and explicit deferral of HTTP admin surface

---

## Consolidated Checklist

### Context and Ownership

- [x] Loaded security contract (`docs/agentic/contracts/security.md`) before editing
- [x] Confirmed no external dependency context required via `ctx7`
- [x] Branch created: `feature/e15-1-security-baseline`

### Checklist for Slice 1: Rate Limiting via Auth-Chained Dependency

- [x] Failing tests written first (`test_rate_limiting.py`)
- [x] `enforce_rate_limit` dependency implemented in `deps/rate_limit.py` (consumes `AuthContext` from chained `Depends(require_auth)`)
- [x] Protected routers updated to depend on `enforce_rate_limit`
- [x] Rate limit headers in responses (Retry-After, X-RateLimit-*)
- [x] Per-key counter isolation verified in tests
- [x] Security contract updated
- [x] All tests pass

### Checklist for Slice 2: CORS Origin Allowlist

- [x] Failing tests written first (`test_cors.py`)
- [x] `allowed_origins` added to `SecuritySettings`
- [x] `CORSMiddleware` registered in `api/main.py`
- [x] `.env.prod.example` updated
- [x] Security contract updated
- [x] All tests pass

### Checklist for Slice 3: Key Rotation, Lifecycle, and Auth Audit Logging

- [x] Failing tests written first (`test_key_rotation.py`, `test_auth_audit.py`)
- [x] `ApiKey` model columns added (`expires_at`, `revoked_at`)
- [x] Schema migration updated (greenfield: `001_identity_schema.py`)
- [x] Repository extended with `create` / `list_for_tenant` / `revoke` write methods; `get_by_hash` filters expired/revoked keys
- [x] Operator CLI (`scripts/manage_api_keys.py`) with `create`/`list`/`revoke` subcommands, delegating to repo methods (no raw SQL)
- [x] Auth audit emitter (`recognition/observability/auth_audit.py`) wired into `require_auth` and `enforce_rate_limit`; fingerprint is hash-prefix only; raw keys never logged
- [x] Fail-closed startup guard in `api/main.py` refuses to start when `RecognitionSettings.runtime_mode == "production"` and `SecuritySettings.dev_api_keys` is non-empty; reuses existing `RECOGNITION_RUNTIME_MODE` signal (no new env var); `.env.prod.example` ships with empty `RECOGNITION_ALLOWED_API_KEYS=`
- [x] HTTP admin surface explicitly deferred in security contract (no admin router shipped this task)
- [x] Security contract updated
- [x] Full `make check` passes

## Review Readiness

- [x] Security contract updated in every slice that changes behavior
- [x] `.env.prod.example` documents all new env vars
- [x] No raw API keys logged anywhere
- [x] Handoff decision records the change with verification evidence

## Success Criteria

- [x] Rate limit breach returns 429 with `Retry-After` header
- [x] Non-allowlisted browser origin receives no CORS headers
- [x] Two API keys can be valid simultaneously for the same tenant
- [x] Expired/revoked keys are rejected with 401
- [x] Every auth decision (success/401/403/429) emits a structured audit event with a hash-prefix fingerprint; raw keys never appear in logs
- [x] Production-like deploy with `dev_api_keys` set refuses to start
- [x] Security contract documents rate limiting, CORS, rotation, and audit-log shape
