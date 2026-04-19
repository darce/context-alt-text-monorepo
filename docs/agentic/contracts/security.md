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

**Note**: Raw API keys are never stored; only their hashes are persisted.

## Environment Variables

| Variable                             | Default         | Description                                        |
| ------------------------------------ | --------------- | -------------------------------------------------- |
| `RECOGNITION_AUTH_ENABLED`           | `true`          | Enable/disable authentication globally             |
| `RECOGNITION_ALLOWED_API_KEYS`       | (empty)         | Comma-separated list of dev keys for local testing |
| `RECOGNITION_API_KEY_HEADER`         | `Authorization` | Header name for API key extraction                 |
| `RECOGNITION_API_KEY_HASH_ALGORITHM` | `sha256`        | Algorithm for key hashing                          |
| `RECOGNITION_MAX_PAGE_SIZE`          | `500`           | Maximum allowed page size for list endpoints       |

### Example Configuration

```bash
# Production
export RECOGNITION_AUTH_ENABLED=true
export RECOGNITION_API_KEY_HEADER=Authorization

# Development/Testing
export RECOGNITION_AUTH_ENABLED=true
export RECOGNITION_ALLOWED_API_KEYS=dev-key-1,dev-key-2
```

## Tenant Isolation

Each API key is scoped to a specific tenant. The service enforces tenant isolation at multiple levels:

1. **Header Validation**: The `X-Tenant-ID` header must match the tenant claim from the API key
2. **Query Scoping**: All database queries filter by `tenant_id`
3. **Row-Level Security**: PostgreSQL RLS policies enforce tenant boundaries

### Tenant Mismatch Handling

If an API key's tenant claim doesn't match the normalized `X-Tenant-ID` header, `require_auth` raises `HTTPException(status_code=403, detail="tenant mismatch")`.

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
- The API key has a valid tenant claim, OR
- The API key is an admin/dev key

## Admin Keys

Development API keys (from `RECOGNITION_ALLOWED_API_KEYS`, surfaced as `settings.dev_api_keys`) are marked as `is_admin=True` and have cross-tenant access for debugging and administrative operations.

**⚠️ Warning**: Never use dev keys in production environments.

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

**Bypass rules** (both return immediately without counting):

1. `RECOGNITION_AUTH_ENABLED=false` — auth is disabled; no key identity to rate-limit against.
2. Dev keys from `RECOGNITION_ALLOWED_API_KEYS` — these resolve with `api_key_id=None` and `is_admin=True`; they are local-only debugging keys and must never ship to production.

**Deployment constraint**: the in-memory counter is correct only under a single worker process. Multi-worker deployment requires a shared counter store (Redis/DB) and is out of scope for E15-1.

**Fail-closed startup guard**: `create_app()` refuses to start with `RuntimeError` when `RECOGNITION_RUNTIME_MODE=production` and `dev_api_keys` is non-empty. In non-production runtime modes, a WARNING log is emitted instead.

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

