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
| `key_hash`     | string   | SHA-256 hash of the API key |
| `created_at`   | datetime | Creation timestamp          |
| `last_used_at` | datetime | Last usage timestamp        |

**Note**: Raw API keys are never stored; only their hashes are persisted.

## Environment Variables

| Variable                           | Default         | Description                                        |
| ---------------------------------- | --------------- | -------------------------------------------------- |
| `RECOGNITION_AUTH_ENABLED`         | `true`          | Enable/disable authentication globally             |
| `RECOGNITION_ALLOWED_API_KEYS`     | (empty)         | Comma-separated list of dev keys for local testing |
| `RECOGNITION_API_KEY_HEADER`       | `Authorization` | Header name for API key extraction                 |
| `RECOGNITION_API_KEY_HASH_ALGORITHM` | `sha256`      | Algorithm for key hashing                          |
| `RECOGNITION_MAX_PAGE_SIZE`        | `500`           | Maximum allowed page size for list endpoints       |

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

If an API key's tenant claim doesn't match the `X-Tenant-ID` header, the request is rejected with:

```json
{
  "error": "HTTPException",
  "message": "tenant mismatch",
  "status_code": 403
}
```

## Write Access Control

Mutate endpoints (POST, PATCH, DELETE) require additional write access verification via the `require_write_access` dependency:

| Endpoint                          | Method | Requires Write Access |
| --------------------------------- | ------ | --------------------- |
| `/analyze`                        | POST   | Yes                   |
| `/clustering/jobs`                | POST   | Yes                   |
| `/clusters/{id}`                  | PATCH  | Yes                   |
| `/clusters/{id}/merge`            | POST   | Yes                   |
| `/clusters/{id}/assign`           | POST   | Yes                   |
| `/clusters/reassign`              | POST   | Yes                   |
| `/clusters/create-for-identity`   | POST   | Yes                   |
| `/clusters/revert-merge`          | POST   | Yes                   |
| `/suggestions/{id}/accept`        | POST   | Yes                   |
| `/suggestions/{id}/reject`        | POST   | Yes                   |
| `/jobs/{id}/cancel`               | POST   | Yes                   |
| `/roster/curation/sync`           | POST   | Yes                   |
| `/tenants/{id}/acknowledge-projection` | POST | Yes                |
| `/clusters`                       | GET    | No (read-only)        |
| `/suggestions`                    | GET    | No (read-only)        |
| `/jobs/{id}`                      | GET    | No (read-only)        |
| `/tenants/{id}/clusters/snapshot` | GET    | No (read-only)        |

### WordPress-Side Authorization (WP REST)

All conflict, dead-letter, and sync status endpoints in the WordPress plugin require `manage_options` capability:

| WP REST Endpoint                                  | Capability Required |
| ------------------------------------------------- | ------------------- |
| `GET/POST /acx/v1/recognition/conflicts`          | `manage_options`    |
| `GET/POST /acx/v1/recognition/conflicts/{id}/*`   | `manage_options`    |
| `GET /acx/v1/recognition/outbox/failed`            | `manage_options`    |
| `POST /acx/v1/recognition/outbox/{id}/retry`       | `manage_options`    |
| `POST /acx/v1/recognition/outbox/{id}/discard`     | `manage_options`    |
| `GET/POST /acx/v1/recognition/sync-status`         | `manage_options`    |

Write access is granted when:

- Authentication is disabled (`AUTH_ENABLED=false`), OR
- The API key has a valid tenant claim, OR
- The API key is an admin/dev key

## Admin Keys

Development API keys (from `DEV_API_KEYS`) are marked as `is_admin=True` and have cross-tenant access for debugging and administrative operations.

**⚠️ Warning**: Never use dev keys in production environments.

## Error Responses

### 401 Unauthorized

Missing or malformed authorization header:

```json
{
  "error": "HTTPException",
  "message": "Authorization header required",
  "status_code": 401
}
```

### 403 Forbidden

Invalid API key or tenant mismatch:

```json
{
  "error": "HTTPException",
  "message": "invalid or missing API key",
  "status_code": 403
}
```

### Structured Error Format

All errors include:

```json
{
  "error": "<exception_class>",
  "message": "<human_readable_message>",
  "path": "<request_path>",
  "trace_id": "<request_id_or_generated>"
}
```

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

## Future Enhancements


