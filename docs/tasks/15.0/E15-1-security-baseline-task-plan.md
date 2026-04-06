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

1. Add a lightweight in-memory rate limiter middleware using a sliding-window counter keyed by API key hash. No external dependency needed; FastAPI middleware + `asyncio.Lock` + dict is sufficient for single-process MVP.
2. Add `CORSMiddleware` with `RECOGNITION_ALLOWED_ORIGINS` env var. Default to empty (deny all browser CORS) unless explicitly configured.
3. Add `expires_at` and `revoked_at` columns to `ApiKey`. Modify `require_auth` to reject expired/revoked keys. Add admin endpoints for key creation and revocation.

## Files and Surfaces to Change

| Surface | File | Change |
|---------|------|--------|
| Rate limiting middleware | `recognition/interface_adapters/http/middleware/rate_limit.py` | New: sliding-window rate limiter |
| Auth dependency | `recognition/interface_adapters/http/deps/auth.py` | Add expiry/revocation checks |
| Security config | `recognition/config/security.py` | Add `allowed_origins` field |
| App wiring | `api/main.py` | Register CORSMiddleware + rate limit middleware |
| DB model | `db/models/tenant.py` | Add `expires_at`, `revoked_at` to ApiKey |
| Schema migration | `db/migrations/versions/` | New migration for ApiKey columns |
| API key repository | `recognition/infrastructure/repositories/api_key_repository.py` | Filter expired/revoked keys |
| Admin router | `recognition/interface_adapters/http/routers/admin.py` | New: key creation/revocation endpoints |
| Security contract | `docs/agentic/contracts/security.md` | Add rate limiting, CORS, rotation docs |
| Env template | `.env.prod.example` | Add `RECOGNITION_ALLOWED_ORIGINS` |
| Tests | `recognition/tests/api/test_rate_limiting.py` | New |
| Tests | `recognition/tests/api/test_cors.py` | New |
| Tests | `recognition/tests/api/test_key_rotation.py` | New |

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

### Slice 1: Rate Limiting Middleware

**Goal**: Enforce per-key rate limits with deterministic 429 responses.

Changes:

- Add `recognition/interface_adapters/http/middleware/rate_limit.py`: sliding-window counter keyed by `api_key_hash`, configurable via `SecuritySettings`.
- Wire middleware in `api/main.py`.
- Return 429 with `Retry-After` header and `X-RateLimit-Remaining` / `X-RateLimit-Limit` headers on all responses.
- Add `recognition/tests/api/test_rate_limiting.py` with tests for: under limit (200), at limit (429), burst handling, per-key isolation, `Retry-After` header presence.
- Update `docs/agentic/contracts/security.md` rate limiting section.

Proof:

- `pytest recognition/tests/api/test_rate_limiting.py` passes
- Rate limit headers present in integration test responses

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

### Slice 3: Key Rotation and Lifecycle

**Goal**: Support no-downtime API key rotation with explicit revocation.

Changes:

- Add `expires_at: datetime | None` and `revoked_at: datetime | None` to `ApiKey` model in `db/models/tenant.py`.
- Update schema migration (`001_identity_schema.py` per greenfield policy) with the new columns.
- Modify `api_key_repository.py` to filter expired/revoked keys in lookup.
- Modify `auth.py` `require_auth` to reject expired/revoked keys with 401 and descriptive error.
- Add `recognition/interface_adapters/http/routers/admin.py` with:
  - `POST /admin/api-keys` (create key, returns raw key once, stores hash)
  - `DELETE /admin/api-keys/{key_id}` (soft-revoke: sets `revoked_at`)
- Gate admin endpoints behind `require_auth` + `is_admin` check.
- Add `recognition/tests/api/test_key_rotation.py` with tests for: create key, use new key, revoke old key, expired key rejected, revoked key rejected, two keys valid simultaneously.
- Update security contract rotation section.

Proof:

- `pytest recognition/tests/api/test_key_rotation.py` passes
- Full test suite passes: `make check` from `apps/prototype-description-service/`

---

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded security contract (`docs/agentic/contracts/security.md`) before editing
- [ ] Confirmed no external dependency context required via `ctx7`
- [ ] Branch created: `feature/e15-1-security-baseline`

### Checklist for Slice 1: Rate Limiting Middleware

- [ ] Failing tests written first (`test_rate_limiting.py`)
- [ ] Middleware implemented (`middleware/rate_limit.py`)
- [ ] Middleware wired in `api/main.py`
- [ ] Rate limit headers in responses
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
