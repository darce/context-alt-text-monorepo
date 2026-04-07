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

Close the remaining security gaps that block public internet exposure of the recognition service. When this task is complete, the API enforces rate limits, rejects non-allowlisted browser origins, and supports no-downtime key rotation.

## Problem Statement

API key authentication and tenant isolation are already implemented (`auth.py`, `security.py`, `api_key_repository.py`). Three gaps remain:

1. **Rate limiting is configured but not enforced.** `SecuritySettings` defines `rate_limit_requests_per_minute=60` and `rate_limit_burst=10`, but no middleware applies them. A single client can send unlimited requests.
2. **No browser origin policy.** No `CORSMiddleware` or origin allowlist exists. Any origin can call privileged endpoints from a browser.
3. **No key rotation support.** The `api_keys` table supports multiple keys per tenant, but there is no documented rotation ceremony, no expiration, and no mechanism to have two valid keys during cutover.

## Constraints

- Scope is `apps/prototype-description-service/` only; no WP plugin changes.
- Rate limiting must be per-API-key (not per-IP) to support multi-tenant fairness.
- CORS must allow the WP demo origin (configured via env var) while blocking arbitrary browser origins.
- Key rotation must work without downtime: old key remains valid until explicitly revoked.
- No new Python dependencies unless strictly necessary; prefer FastAPI/Starlette built-ins where possible.
- Branch isolation: all code changes on `feature/e15-1-security-baseline`, not `main`.

## Workflow Principles

- Wire existing configuration before adding new configuration. `SecuritySettings` already has rate limit fields; use them.
- Security contract (`docs/agentic/contracts/security.md`) is the boundary doc; update it in the same slices as behavior changes.
- Tests first: each slice adds failing tests before the implementation.

## Terminology

- **Rate limit tier**: The `rate_limit_tier` field on `ApiKey` that can override the global default.
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
| App wiring | `api/main.py` | Register `CORSMiddleware` only (rate limit is dependency-based, not middleware) |
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
  - `PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/api/test_rate_limiting.py -v`
  - `PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/api/test_cors.py -v`
  - `PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/api/test_key_rotation.py -v`
- Runtime-parity:
  - `curl -H "X-Api-Key: <key>" https://api.altcontext.com/health` returns 200
  - Repeated rapid requests trigger 429 with `Retry-After` header
  - `curl -H "Origin: https://evil.com" -I https://api.altcontext.com/recognition/health` returns no CORS headers
- Contract verification:
  - Security contract documents rate limiting, CORS, and rotation behavior

## Slice Delivery

### Slice 1: Rate Limiting via Auth-Chained Dependency

**Goal**: Enforce per-key rate limits with deterministic 429 responses, using a dependency seam that runs **after** `require_auth` resolves the key identity.

**Why not middleware:** FastAPI middleware runs before route dependencies, so it cannot see `AuthContext.api_key_id` without duplicating the DB lookup that already happens in `require_auth`. The correct seam is a `Depends(enforce_rate_limit)` that consumes the resolved `AuthContext` from a chained `Depends(require_auth)`.

Changes:

- Add `recognition/interface_adapters/http/deps/rate_limit.py` with `enforce_rate_limit(auth: AuthContext = Depends(require_auth))` -- sliding-window counter keyed by `auth.api_key_id`, applying `auth.rate_limit_tier` override if set, falling back to global `SecuritySettings.rate_limit_requests_per_minute`.
- Raise `HTTPException(status_code=429, ...)` with `Retry-After` and `X-RateLimit-*` headers on breach. Use the existing exception handler pattern in `exception_handlers.py`.
- Update protected routers (`analyze.py`, `clusters.py`, `retention.py`, etc.) to depend on `enforce_rate_limit` in addition to `require_auth`. The chained dependency naturally pulls the auth context.
- Add `recognition/tests/api/test_rate_limiting.py` with tests for: under limit (200), at limit (429), burst handling, per-key isolation (different keys do not share counters), `Retry-After` header presence, tier override behavior.
- Update `docs/agentic/contracts/security.md` rate limiting section.

Proof:

- `pytest recognition/tests/api/test_rate_limiting.py` passes
- Rate limit headers present in integration test responses
- Anonymous/disabled-auth requests bypass the limiter (auth disabled = no key identity = no per-key counter)

### Slice 2: CORS Origin Allowlist

**Goal**: Reject cross-origin browser requests from non-allowlisted domains.

Changes:

- Add `allowed_origins: list[str]` to `SecuritySettings` (env: `RECOGNITION_ALLOWED_ORIGINS`, comma-separated).
- Register `CORSMiddleware` in `api/main.py` with configured origins, allowed methods, and allowed headers.
- Add `recognition/tests/api/test_cors.py` with tests for: allowlisted origin gets CORS headers, non-allowlisted origin does not, preflight OPTIONS returns correct headers, empty allowlist blocks all CORS.
- Update `.env.prod.example` with `RECOGNITION_ALLOWED_ORIGINS`.
- Update security contract CORS section.

Proof:

- `pytest recognition/tests/api/test_cors.py` passes
- Contract documents CORS behavior

### Slice 3: Key Lifecycle, Rotation, and Operator CLI Provisioning

**Goal**: Support no-downtime key rotation, explicit revocation, expiry, and an operator-side CLI for provisioning beta-tester keys -- without introducing an HTTP admin surface gated by an authority that does not yet exist.

**Why not an HTTP admin router:** The current `is_admin` flag in `AuthContext` is set only for `RECOGNITION_ALLOWED_API_KEYS` dev keys -- DB-backed production keys always return `is_admin=False`. The security contract explicitly marks dev keys as local-only debugging keys. Building HTTP admin endpoints behind `is_admin` would either be unreachable in production (no admin keys exist) or would require shipping dev-key semantics into production, which contradicts the security baseline this task is meant to establish. A real production admin authority is a separate design concern out of scope for E15-1.

**Operator workflow for this task:** beta-tester key provisioning happens via a CLI run by the operator with direct DB access. The CLI is a Python module under `scripts/manage_api_keys.py` that uses the existing repository layer. Once a future admin-authority design is settled, an HTTP admin surface can be added in a follow-up task.

Changes:

- Add `expires_at: datetime | None` and `revoked_at: datetime | None` to `ApiKey` model in `db/models/tenant.py`.
- Edit baseline schema `db/migrations/versions/001_identity_schema.py` with the new columns (greenfield policy: no follow-on migration file).
- Modify `api_key_repository.py` to filter `revoked_at IS NOT NULL` and `expires_at < now()` keys in lookup.
- Modify `auth.py` `require_auth` to surface expired/revoked rejections with a descriptive 401 detail.
- Add `apps/prototype-description-service/scripts/manage_api_keys.py` CLI with subcommands:
  - `create --tenant <id> [--expires-in <days>]` — generates a raw key, stores hash, prints the raw key once to stdout
  - `list --tenant <id>` — prints active keys (id, last4, created_at, last_used_at, expires_at)
  - `revoke --key-id <id>` — soft-revoke (sets `revoked_at`)
- Add `recognition/tests/api/test_key_rotation.py`: expired key rejected, revoked key rejected, two keys valid simultaneously.
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

- [ ] Loaded security contract (`docs/agentic/contracts/security.md`) before editing
- [ ] Confirmed no external dependency context required via `ctx7`
- [ ] Branch created: `feature/e15-1-security-baseline`

### Checklist for Slice 1: Rate Limiting via Auth-Chained Dependency

- [ ] Failing tests written first (`test_rate_limiting.py`)
- [ ] `enforce_rate_limit` dependency implemented in `deps/rate_limit.py` (consumes `AuthContext` from chained `Depends(require_auth)`)
- [ ] Protected routers updated to depend on `enforce_rate_limit`
- [ ] Rate limit headers in responses (Retry-After, X-RateLimit-*)
- [ ] Per-key counter isolation verified in tests
- [ ] Security contract updated
- [ ] All tests pass

### Checklist for Slice 2: CORS Origin Allowlist

- [ ] Failing tests written first (`test_cors.py`)
- [ ] `allowed_origins` added to `SecuritySettings`
- [ ] `CORSMiddleware` registered in `api/main.py`
- [ ] `.env.prod.example` updated
- [ ] Security contract updated
- [ ] All tests pass

### Checklist for Slice 3: Key Rotation and Lifecycle

- [ ] Failing tests written first (`test_key_rotation.py`)
- [ ] `ApiKey` model columns added
- [ ] Schema migration updated (greenfield: `001_identity_schema.py`)
- [ ] Repository filters expired/revoked keys
- [ ] Admin router with create/revoke endpoints
- [ ] Security contract updated
- [ ] Full `make check` passes

## Review Readiness

- [ ] Security contract updated in every slice that changes behavior
- [ ] `.env.prod.example` documents all new env vars
- [ ] No raw API keys logged anywhere
- [ ] Handoff decision records the change with verification evidence

## Success Criteria

- [ ] Rate limit breach returns 429 with `Retry-After` header
- [ ] Non-allowlisted browser origin receives no CORS headers
- [ ] Two API keys can be valid simultaneously for the same tenant
- [ ] Expired/revoked keys are rejected with 401
- [ ] Security contract documents rate limiting, CORS, and rotation
