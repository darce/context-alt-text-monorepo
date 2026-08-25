# Recognition Service Security Configuration

**Sprint**: 4.2.4  
**Last Updated**: December 6, 2025

---

## Overview

The Recognition Service uses **API Key authentication** for securing access to its endpoints. This approach was chosen over JWT for its simplicity in a single-tenant WordPress plugin context.

## Authentication Model

### API Key-Based Authentication

All protected endpoints require a valid API key passed via the `Authorization` header:

```http
Authorization: Bearer <api_key>
```

Or via the `X-Api-Key` header (configurable):

```http
X-Api-Key: <api_key>
```

### Key Storage

API keys are stored in the `api_keys` database table with the following structure:

| Column         | Type     | Description                 |
| -------------- | -------- | --------------------------- |
| `id`           | UUID     | Primary key (UUIDv7)        |
| `tenant_id`    | UUID     | Associated tenant           |
| `api_key_hash` | string   | Hash of the API key using `RECOGNITION_API_KEY_HASH_ALGORITHM` |
| `created_at`   | datetime | Creation timestamp          |
| `last_used_at` | datetime | Last usage timestamp        |
| `expires_at`   | datetime | Optional expiry (UTC); NULL = never expires |
| `revoked_at`   | datetime | Optional soft-revoke timestamp (UTC); NULL = not revoked |

**Note**: Raw API keys are never stored; only their hashes are persisted.

## Environment Variables

| Variable                             | Default         | Description                                        |
| ------------------------------------ | --------------- | -------------------------------------------------- |
| `RECOGNITION_AUTH_ENABLED`           | `true`          | Enable/disable authentication globally             |
| `RECOGNITION_API_KEY_HEADER`         | `Authorization` | Header name for API key extraction                 |
| `RECOGNITION_API_KEY_HASH_ALGORITHM` | `sha256`        | Algorithm for key hashing                          |
| `RECOGNITION_MAX_PAGE_SIZE`          | `500`           | Maximum allowed page size for list endpoints       |
| `RECOGNITION_SECRET_BACKEND`         | `env`           | Secret source: `env` (local/CI) or `oci_vault` (prod) |

> **Tenant keys are DB-only.** The former `RECOGNITION_ALLOWED_API_KEYS` env-var
> dev-key allowlist is **retired** (decision #1882). All tenant API keys are
> minted/revoked in the service DB via `/admin` (or `scripts/manage_api_keys.py`);
> there is no plaintext key bypass. Locally, mint a dev key with `make dev-mint-key`.
> Service secrets are read through the `SecretProvider` seam (`shared/secrets.py`),
> selectable via `RECOGNITION_SECRET_BACKEND` — see
> [`docs/secrets-inventory.md`](../../../apps/prototype-description-service/docs/secrets-inventory.md)
> and [ADR-013](../../adrs/ADR-013-oci-vault-secrets-backend.md).

### Example Configuration

```bash
# Production (secrets come from OCI Vault via instance principal)
export RECOGNITION_AUTH_ENABLED=true
export RECOGNITION_API_KEY_HEADER=Authorization
export RECOGNITION_SECRET_BACKEND=oci_vault

# Development/Testing — mint a DB-backed key via /admin
export RECOGNITION_AUTH_ENABLED=true
make dev-mint-key   # prints a usable tenant API key
```

## Demo WordPress identities (AUTH-03)

The public demo keeps three separate credentials. CI must not log in as the
demo wp-admin / viewer account.

| Name | Kind | Store | Notes |
| --- | --- | --- | --- |
| `WP_ADMIN_USER` / `WP_ADMIN_PASSWORD` / `WP_ADMIN_EMAIL` | human admin | VM `secrets/.env` (mode 600) | Converged every `bootstrap-wp.sh` run (AUTH-01) |
| `WP_CI_USER` / `WP_CI_PASSWORD` / `WP_CI_EMAIL` | CI WP user | same `secrets/.env` | Role `acx_ci`; must differ from `WP_ADMIN_USER` |
| `ACX_E2E_WP_CI_USER` / `ACX_E2E_WP_CI_PASS` | GitHub Environment secrets | `demo` environment | Mapped onto Playwright `ACX_E2E_WP_ADMIN_*` env. `ACX_E2E_WP_CI_USER` must equal the VM `WP_CI_USER` (same principal bootstrap converges), not merely avoid `acx-demo-admin`/`admin`. Empty `ACX_E2E_WP_CI_PASS` is refused. Denylist match is case-insensitive. |

Issue a CI-scoped demo **API** key with `make issue-demo-ci-account LABEL="ACX CI" ADMIN_USER=acx-demo-admin` (wraps `python -m scripts.provision_demo --account ci`). Viewer keys stay `make provision-demo LABEL=...`.

## Tenant Isolation

Each API key is scoped to a specific tenant. The service enforces tenant isolation at multiple levels:

1. **Header Validation**: The `X-Tenant-ID` header must match the tenant claim from the API key
2. **Query Scoping**: All database queries filter by `tenant_id`
3. **Row-Level Security**: PostgreSQL RLS policies enforce tenant boundaries

### Tenant Mismatch Handling

If an API key's tenant claim doesn't match the normalized `X-Tenant-ID` header, `require_auth` raises `HTTPException(status_code=403, detail="tenant mismatch")`.

**Discovery exception — `GET /recognition/tenant/whoami`** (MAINT-TPR-01): this one route uses `require_auth_key_only` instead of `require_auth`. Key resolution is identical (hash, expiry, revocation, disabled-auth handling) but the `tenant_claim != X-Tenant-ID` comparison is skipped, so the route returns the key's canonical tenant regardless of the header. This lets a client that pasted a mismatched key learn the key's tenant and pair to it in one step; disclosure is bounded to the caller's own key binding. Every other route stays strict. Sole consumer is the plugin's `attempt_tenant_pairing`.

## Write Access Control

Mutate endpoints (POST, PATCH, DELETE) require additional write access verification via the `require_write_access` dependency:

| Endpoint                               | Method | Requires Write Access |
| -------------------------------------- | ------ | --------------------- |
| `/analyze`                             | POST   | Yes                   |
| `/clustering/jobs`                     | POST   | Yes                   |
| `/clusters/{id}`                       | PATCH  | Yes                   |
| `/clusters/{id}/merge`                 | POST   | Yes                   |
| `/clusters/{id}/assign`                | POST   | Yes                   |
| `/clusters/reassign`                   | POST   | Yes                   |
| `/clusters/create-for-identity`        | POST   | Yes                   |
| `/clusters/revert-merge`               | POST   | Yes                   |
| `/suggestions/{id}/accept`             | POST   | Yes                   |
| `/suggestions/{id}/reject`             | POST   | Yes                   |
| `/jobs/{id}/cancel`                    | POST   | Yes                   |
| `/roster/curation/sync`                | POST   | Yes                   |
| `/tenants/{id}/acknowledge-projection` | POST   | Yes                   |
| `/clusters`                            | GET    | No (read-only)        |
| `/suggestions`                         | GET    | No (read-only)        |
| `/jobs/{id}`                           | GET    | No (read-only)        |
| `/tenants/{id}/clusters/snapshot`      | GET    | No (read-only)        |

### WordPress-Side Authorization (WP REST)

All WordPress plugin REST endpoints require `manage_options` capability via the `can_manage_recognition` permission callback:

| WP REST Endpoint                                                 | Method | Capability Required |
| ---------------------------------------------------------------- | ------ | ------------------- |
| `/acx/v1/recognition/analyze`                                    | POST   | `manage_options`    |
| `/acx/v1/recognition/jobs/{id}`                                  | GET    | `manage_options`    |
| `/acx/v1/recognition/jobs/{id}/stream`                           | GET    | `manage_options`    |
| `/acx/v1/recognition/jobs/{id}/cancel`                           | POST   | `manage_options`    |
| `/acx/v1/recognition/jobs/{id}/acknowledge-projection`           | POST   | `manage_options`    |
| `/acx/v1/recognition/clusters`                                   | GET    | `manage_options`    |
| `/acx/v1/recognition/clusters/top-unlabeled`                     | GET    | `manage_options`    |
| `/acx/v1/recognition/clusters/labels`                            | GET    | `manage_options`    |
| `/acx/v1/recognition/clusters/{id}`                              | GET    | `manage_options`    |
| `/acx/v1/recognition/clusters/{id}/members`                      | GET    | `manage_options`    |
| `/acx/v1/recognition/clusters/{id}`                              | PATCH  | `manage_options`    |
| `/acx/v1/recognition/clusters/{id}/dismiss`                      | POST   | `manage_options`    |
| `/acx/v1/recognition/clusters/{id}/dismiss`                      | DELETE | `manage_options`    |
| `/acx/v1/recognition/clusters/{source_id}/merge`                 | POST   | `manage_options`    |
| `/acx/v1/recognition/clusters/{id}/split`                        | POST   | `manage_options`    |
| `/acx/v1/recognition/clusters/create-for-identity`               | POST   | `manage_options`    |
| `/acx/v1/recognition/clusters/reassign`                          | POST   | `manage_options`    |
| `/acx/v1/recognition/clusters/revert-merge`                      | POST   | `manage_options`    |
| `/acx/v1/recognition/clusters/{id}/assign`                       | POST   | `manage_options`    |
| `/acx/v1/recognition/clusters/{id}/representatives/{rep_id}/pin` | PATCH  | `manage_options`    |
| `/acx/v1/recognition/cluster`                                    | POST   | `manage_options`    |
| `/acx/v1/recognition/suggestions`                                | GET    | `manage_options`    |
| `/acx/v1/recognition/suggestions/merge`                          | GET    | `manage_options`    |
| `/acx/v1/recognition/suggestions/name`                           | GET    | `manage_options`    |
| `/acx/v1/recognition/suggestions/{id}/accept`                    | POST   | `manage_options`    |
| `/acx/v1/recognition/suggestions/{id}/reject`                    | POST   | `manage_options`    |
| `/acx/v1/recognition/suggestions/merge/{id}/accept`              | POST   | `manage_options`    |
| `/acx/v1/recognition/suggestions/merge/{id}/reject`              | POST   | `manage_options`    |
| `/acx/v1/recognition/suggestions/name/{id}/accept`               | POST   | `manage_options`    |
| `/acx/v1/recognition/suggestions/name/{id}/reject`               | POST   | `manage_options`    |
| `/acx/v1/recognition/identities/{id}/suggestions`                | GET    | `manage_options`    |
| `/acx/v1/recognition/media-identities`                           | GET    | `manage_options`    |
| `/acx/v1/recognition/conflicts`                                  | GET    | `manage_options`    |
| `/acx/v1/recognition/conflicts/{id}`                             | GET    | `manage_options`    |
| `/acx/v1/recognition/conflicts/{id}/resolve`                     | POST   | `manage_options`    |
| `/acx/v1/recognition/outbox`                                     | GET    | `manage_options`    |
| `/acx/v1/recognition/outbox/failed`                              | GET    | `manage_options`    |
| `/acx/v1/recognition/outbox/{id}/retry`                          | POST   | `manage_options`    |
| `/acx/v1/recognition/outbox/{id}/discard`                        | POST   | `manage_options`    |
| `/acx/v1/recognition/sync-status`                                | GET    | `manage_options`    |
| `/acx/v1/recognition/sync/trigger`                               | POST   | `manage_options`    |
| `/acx/v1/retention/status`                                       | GET    | `manage_options`    |
| `/acx/v1/retention/policy`                                       | PATCH  | `manage_options`    |
| `/acx/v1/retention/policy/preset`                                | POST   | `manage_options`    |
| `/acx/v1/retention/export`                                       | POST   | `manage_options`    |
| `/acx/v1/retention/export/{job_id}/status`                       | GET    | `manage_options`    |
| `/acx/v1/retention/export/{job_id}/data`                         | GET    | `manage_options`    |
| `/acx/v1/retention/purge`                                        | POST   | `manage_options`    |
| `/acx/v1/retention/import`                                       | POST   | `manage_options`    |
| `/acx/v1/retention/audit`                                        | GET    | `manage_options`    |

Write access is granted when:

- Authentication is disabled (`AUTH_ENABLED=false`), OR
- The API key has a valid tenant claim

## Admin access

Operator/admin actions are reached through the env-gated `/admin` console,
authenticated by `RECOGNITION_ADMIN_TOKEN` (or HTTP Basic for the browser
console) — **not** by any tenant API key. There is no cross-tenant "dev/admin
key": the former `RECOGNITION_ALLOWED_API_KEYS` / `settings.dev_api_keys`
allowlist that granted `is_admin=True` cross-tenant access is **retired**
(decision #1882). Tenant keys are DB-backed and tenant-scoped only.

## Error Responses

### 401 Unauthorized

`require_auth` raises plain FastAPI `HTTPException` responses for missing headers or invalid auth schemes:

- `401` with `detail="Authorization header required"`
- `401` with `detail="invalid authorization scheme"`

### 403 Forbidden

`require_auth` and `require_write_access` also raise plain FastAPI `HTTPException` responses for authorization failures:

- `403` with `detail="invalid or missing API key"`
- `403` with `detail="tenant mismatch"`
- `403` with `detail="Write access requires a tenant-scoped API key or admin privileges"`

### Structured Error Format

Structured `{error, message, path, trace_id}` payloads are used by the registered application exception handlers such as `RecognitionError`, `ClusterNotFoundError`, and duplicate-label `IntegrityError`. Generic 500 and pool exhaustion responses are intentionally opaque and omit `message`. Plain `HTTPException` responses raised directly by auth dependencies keep FastAPI's default `detail` shape instead of this envelope.

## Rate Limiting

Per-API-key sliding-window rate limiting is applied to every protected router after `require_auth` resolves the key identity. The limiter is implemented as a FastAPI dependency (`enforce_rate_limit` in `recognition/interface_adapters/http/deps/rate_limit.py`) rather than middleware so it can see the resolved `AuthContext.api_key_id` and `rate_limit_tier` without duplicating the DB lookup.

**Tier mapping** (values are DB-stored strings; see `RateLimitTier` in `recognition/config/security.py`):

| Tier         | Multiplier | Default RPM (with `RECOGNITION_RATE_LIMIT_RPM=60`) |
| ------------ | ---------- | -------------------------------------------------- |
| `STANDARD`   | 1x         | 60                                                 |
| `PRO`        | 3x         | 180                                                |
| `ENTERPRISE` | 10x        | 600                                                |

Legacy DB rows with `rate_limit_tier='free'` or `NULL` reconcile to `STANDARD`.

**429 response shape** (plain `HTTPException`, matching the 401/403 auth-boundary pattern — not the structured error envelope):

```http
HTTP/1.1 429 Too Many Requests
Retry-After: <seconds-until-window-reset>
X-RateLimit-Limit: <requests-per-minute-for-this-key>
X-RateLimit-Remaining: 0
Content-Type: application/json

{"detail": "rate limit exceeded"}
```

**Bypass rule**: `RECOGNITION_AUTH_ENABLED=false` — auth is disabled; no key
identity to rate-limit against. (The former dev-key allowlist bypass is retired,
decision #1882.)

**Deployment constraint**: the in-memory counter is correct only under a single worker process. Multi-worker deployment requires a shared counter store (Redis/DB) and is out of scope for E15-1.

**Fail-closed startup guard**: in production (`RECOGNITION_RUNTIME_MODE=production`)
`create_app()` refuses to start when a required secret is missing, empty, or set
to the development default (`validate_required_secrets`), and — under
`RECOGNITION_SECRET_BACKEND=oci_vault` — when OCI Vault is unreachable or a
required secret is absent (`validate_oci_vault_boot`, no env fallback).

## CORS Origin Allowlist

Cross-origin browser requests are gated by a Starlette `CORSMiddleware` registered in `api/main.py` `create_app()`. The middleware runs before route dependencies so non-allowlisted origins never reach auth/rate-limit logic with CORS response headers attached.

**Secure-defaults rationale**: the WordPress plugin is a server-side PHP caller and does not require CORS. The middleware is a defensive guard for future browser-origin callers (operator admin UI, marketing demo widget) that do not yet exist. Every knob is pinned to the tightest practical value so an operator who opts a single origin in does not accidentally widen the surface:

| Setting                | Pinned value                                                      |
| ---------------------- | ----------------------------------------------------------------- |
| `allow_origins`        | `SecuritySettings.allowed_origins` (exact match only)             |
| `allow_credentials`    | `False` (prevents credential-bearing cross-origin leaks)          |
| `allow_origin_regex`   | `None` (no regex; exact match only)                               |
| `allow_methods`        | `["GET", "POST", "PATCH", "DELETE", "OPTIONS"]` (explicit list)   |
| `allow_headers`        | `["Authorization", "X-Api-Key", "X-Tenant-ID", "Content-Type"]`   |
| `max_age`              | `600` (10-minute preflight cache)                                 |

Because `allow_credentials=False`, Starlette omits the `Access-Control-Allow-Credentials` response header entirely.

**Environment variable**: `RECOGNITION_ALLOWED_ORIGINS` — comma-separated list of exact origins (scheme + host + optional port). Empty whitespace entries are stripped. Example: `https://admin.example.com,https://demo.example.com`.

**Deny-all default**: if `RECOGNITION_ALLOWED_ORIGINS` is unset or empty, the allowlist is `[]` and no origin receives CORS headers. Browser cross-origin requests are effectively blocked.

**Wildcard rejection**: a `*` entry in `allowed_origins` raises `ValidationError` at `SecuritySettings` construction, refusing to start the app. Wildcards defeat the allowlist's purpose and would silently combine with any future `allow_credentials` change to enable credential leaks.

## WordPress Plugin Integration

The WordPress plugin should:

1. **Store API key securely** in `wp_options` (encrypted if possible)
2. **Include tenant header** with every request: `X-Tenant-ID: <site_uuid>`
3. **Handle 401/403 errors** by prompting for re-authentication
4. **Use HTTPS** for all API communication

### Example WordPress Request

```php
$response = wp_remote_post($api_url . '/analyze', [
    'headers' => [
        'Authorization' => 'Bearer ' . get_option('recognition_api_key'),
        'X-Tenant-ID' => get_option('recognition_tenant_id'),
        'Content-Type' => 'application/json',
    ],
    'body' => json_encode([
        'tenant_id' => get_option('recognition_tenant_id'),
        'media_ids' => $media_ids,
    ]),
]);
```

### Plugin Probe Wire Contract — `POST /acx/v1/settings/test` (E15-1b Slice 1)

This is the authoritative boundary definition for the plugin-facing
connection-probe endpoint. Any change to the response shape, outcome
taxonomy, or `Retry-After` semantics below is a cross-repo wire-contract
change that must land in the same slice as the producing controller and
the consuming React renderer.

**Request shape.** The plugin's `SettingsController::test_connection`
issues a `GET` to `<base_url>/recognition/health/pool` — the authenticated
pool-health endpoint — and forwards exactly two headers:

- `X-API-Key`: the configured recognition key (blank keys are still sent
  so the backend can return the authoritative 401/403 outcome instead of
  the plugin short-circuiting).
- `X-Tenant-ID`: the site-scoped UUID derived by
  `AltContext\Api\TenantIdentity::derive_from_site_url()` (SHA-1 of
  `acx-site-tenant:<lowercase,untrailingslashed site_url>`, formatted as a
  UUID-v5-shaped string). The same derivation is used for live
  recognition calls, so probe behaviour matches real request behaviour.

There is **no anonymous `/health` probe** on this surface; any such
request would succeed against a misconfigured backend and produce a false
positive in the admin UI.

**Response shape.** The response body is a closed envelope. The frontend
derives a boolean "connected" from `outcome === 'connected'`; a separate
`connected` or `error` field **must not** be added — consumers treat
unknown keys as a contract break.

```json
{
  "outcome": "connected" | "not_configured" | "invalid_key" | "expired"
           | "revoked" | "tenant_mismatch" | "rate_limited"
           | "server_error" | "network_error" | "tls_error",
  "status_code": 200,
  "retry_after_seconds": 30,
  "detail": "api key expired",
  "body": { ... }
}
```

- `outcome` is always present and is one of the ten canonical values
  enumerated by `AltContext\Api\ProbeOutcome` (PHP) and
  `TestConnectionOutcome` (TS). The plugin renderer validates this string
  at runtime and falls back to a safe "unexpected response" banner for
  any unknown value so forward-incompatible payloads cannot crash the
  Settings page.
- `status_code` is present for every outcome that reached the backend
  (i.e. every outcome except `not_configured`, `network_error`, and
  `tls_error`).
- `retry_after_seconds` is **only** emitted for `rate_limited` and is
  an integer (>= 1). See the Retry-After rule below.
- `detail` is the recognition service's error string when present, used
  by the classifier to disambiguate `expired`/`revoked`/`invalid_key`
  within 401 and `tenant_mismatch`/`invalid_key` within 403.
- `body` is the raw decoded upstream body for debugging — not a
  structured contract; consumers must not branch on it.

**Classification rules** (must stay bit-identical to
`SettingsController::classify_http_status()`, and each outcome maps to
the backend `_require_auth_impl` / rate-limit anchor shown):

| Outcome            | Trigger                                                       | Backend anchor                                                        |
| ------------------ | ------------------------------------------------------------- | --------------------------------------------------------------------- |
| `not_configured`   | Missing/empty URL → 200, **no HTTP call**                     | Plugin-local precondition (no recognition-service anchor)             |
| `connected`        | HTTP 2xx                                                      | `/recognition/health/pool` authenticated success path                 |
| `expired`          | HTTP 401 + `detail == "api key expired"`                      | `_require_auth_impl` → `classify_by_hash` returns `"expired"`         |
| `revoked`          | HTTP 401 + `detail == "api key revoked"`                      | `_require_auth_impl` → `classify_by_hash` returns `"revoked"`         |
| `invalid_key`      | HTTP 401 (other) **or** HTTP 403 `"invalid or missing API key"` | `_require_auth_impl` → `"Authorization header required"`, `"invalid authorization scheme"`, or 403 `"invalid or missing API key"` |
| `tenant_mismatch`  | HTTP 403 + `detail == "tenant mismatch"`                      | `_require_auth_impl` tenant-scope check                               |
| `rate_limited`     | HTTP 429                                                      | `enforce_rate_limit` dependency (`rate_limit.py`)                     |
| `server_error`     | HTTP >= 500                                                   | Upstream service failure (no specific anchor)                         |
| `tls_error`        | `WP_Error` with `certificate`, `SSL`, or `TLS` in the message | Transport-layer failure from `wp_remote_get`                          |
| `network_error`    | Any other `WP_Error`                                          | Transport-layer failure from `wp_remote_get`                          |

**Retry-After projection semantics.** `retry_after_seconds` is pinned to
**integer delta-seconds per RFC 7231 §7.1.3** — the form the recognition
service's `enforce_rate_limit` dependency emits (see Rate Limiting
above). HTTP-date form is **not** supported on this surface. The
controller parses via `intval`; a non-numeric or `<= 0` value causes the
field to be omitted entirely, and the UI falls back to a generic "Retry
after a few seconds." hint. The field is therefore a strict projection
of the upstream integer header, not a derived/heuristic value.

## Key Lifecycle (E15-1 Slice 3)

Keys support no-downtime rotation, explicit expiry, and soft-revocation. All
lifecycle writes go through `SqlAlchemyApiKeyRepository`; the CLI never issues
raw SQL.

- **`create(tenant_id, hashed_key, rate_limit_tier, expires_at=None)`**: inserts
  a new active key. `expires_at` is optional.
- **`get_by_hash(hashed)`**: returns the active row; filters out
  `revoked_at IS NOT NULL` and `expires_at <= now()` (UTC).
- **`classify_by_hash(hashed)`**: returns `"active" | "expired" | "revoked" |
  "unknown"` so the auth boundary can emit a descriptive 401 (`api key expired`,
  `api key revoked`) instead of a generic 403.
- **`list_for_tenant(tenant_id, include_revoked=False)`**: operator listing.
- **`revoke(api_key_id)`**: soft-revoke; sets `revoked_at` to now (UTC). The
  row is preserved for audit.
- **Expiry is evaluated only at the `require_auth` boundary.** A request that
  passes auth at time T completes normally even if the key expires during the
  request. In-flight requests are never interrupted.

## Auth Audit Logging (E15-1 Slice 3)

Logger name: **`recognition.auth_audit`**. Every terminal auth decision emits
exactly one structured INFO record via `recognition.observability.auth_audit.emit_auth_event`.

**Outcomes**: `success`, `invalid_key`, `expired`, `revoked`, `tenant_mismatch`,
`rate_limit`.

**Record structure** (via `logging` `extra=...`):

- `outcome`: one of the strings above.
- `api_key_id`: UUID string when the key resolves to a DB row; else `None`.
- `fingerprint`: first 12 characters of the stored hash. Never the raw key.
- `tenant_claim`: the claim resolved from the key (success) or the client-
  supplied `X-Tenant-ID` on failure paths.
- `trace_id`: request trace id when available.

**Raw key never-logged rule**: emitters accept only the stored hash. Raw API
keys MUST NOT be passed to this emitter, captured in exception messages, or
printed outside the single labeled stdout line written by `manage_api_keys.py create`.

## Operator CLI: Key Rotation Ceremony

Beta-tester key provisioning happens via `scripts/manage_api_keys.py`, run
by an operator with direct DB access. The CLI delegates to
`SqlAlchemyApiKeyRepository` and never issues raw SQL. As of **E15-31** the CLI
coexists with a **shipped** HTTP `/admin` surface (below); both call the same
extracted key-minting service, so the CLI ceremony here remains valid.

**Commands**:

- `create --tenant <uuid> [--expires-in <days>] [--tier STANDARD|PRO|ENTERPRISE]`
  generates a 32-byte URL-safe secret, hashes it with
  `RECOGNITION_API_KEY_HASH_ALGORITHM`, inserts a row, prints
  `api_key=<secret>` on stdout (single line) and `key_id=<uuid>` on stderr.
- `list --tenant <uuid> [--include-revoked]` prints tab-separated rows
  `id, last4_of_hash, created_at, last_used_at, expires_at, revoked_at`.
  Full stored hashes are never printed.
- `revoke --key-id <uuid>` sets `revoked_at=now()` and writes
  `revoked key_id=<uuid> revoked_at=<iso>` to stderr.
- `tenant create --tenant <uuid> --site-url <url>` creates or updates the
  bootstrap tenant row without raw SQL.
- `tenant list [--limit <n>]` prints tab-separated rows
  `tenant_id, site_url, created_at`.

**Rotation runbook**:

1. If the tenant row does not exist yet, operator runs
   `manage_api_keys.py tenant create --tenant <id> --site-url <url>`.
2. Operator runs `manage_api_keys.py create --tenant <id>` and captures the
   `api_key=...` value from stdout.
3. If the raw key is lost before it can be shared, revoke the new key and
   restart the ceremony. Hash-only storage means the raw value is
   unrecoverable — by design.
4. Operator shares the raw key with the tester via an operator-approved
   secure channel (e.g. 1Password shared vault, Signal). Plaintext email
   and Slack DMs are disallowed.
5. Tester configures the new key in the plugin Settings page.
6. Before revoking the old key, operator runs
   `manage_api_keys.py list --tenant <id>` and confirms the new key's
   `last_used_at` is non-null and more recent than the old key's — the
   signal that cutover succeeded.
7. Operator runs `manage_api_keys.py revoke --key-id <old-key-id>` to
   soft-revoke the old key.

**HTTP admin surface: shipped (E15-31).** The `/admin` router that E15-1
left out now ships, gated by a **tailnet + shared `RECOGNITION_ADMIN_TOKEN`**
admin authority — neither alone is sufficient by policy:

- **Network**: the public `api.altcontext.com` vhost denies `/admin*` with a
  `404` (Caddy `@admin` matcher → `respond @admin 404`, not 403, so the
  surface is not confirmed). `/admin` is reachable **only over the tailnet**
  (`tailscale serve` or an `ssh -L` tunnel to the prod-api loopback); see
  `docs/runbooks/admin-tenant-keys.md`.
- **Token**: every `/admin` route requires the shared `RECOGNITION_ADMIN_TOKEN`,
  checked with `secrets.compare_digest`. Browser-console routes accept it as
  the HTTP Basic password; JSON mutations require the dedicated
  `X-Admin-Token` header so browser credential replay cannot authorize a
  cross-site mutation. The gate never reads `AuthContext.is_admin`, the tenant
  `X-API-Key` header, or the DB — and there is no dev-key admin path at all
  (the `RECOGNITION_ALLOWED_API_KEYS` allowlist is retired, decision #1882).
- **Env gate / fail-closed**: the router mounts only when
  `RECOGNITION_ADMIN_ENABLED=true`. `validate_admin_config` refuses to start
  when admin is enabled with an empty or `<32`-char token, or in production
  without the `RECOGNITION_ADMIN_TAILNET_BOUND=1` acknowledgement. The prod
  compose overlay's `127.0.0.1:8000` bind persists independent of this gate
  (deploys install it unconditionally); with admin disabled that means a
  loopback-only, VM-local path to the tenant API that bypasses Caddy —
  documented and accepted in `docs/runbooks/admin-tenant-keys.md` §(a).

The operator runbook for the surface is `docs/runbooks/admin-tenant-keys.md`;
the CLI ceremony above remains a supported fallback.
