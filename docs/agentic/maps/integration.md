# Integration Context Map

> Quick reference for cross-service work between WordPress and Recognition Service.

## Critical Files (Read First)

| Priority | File                                               | Purpose                     |
| -------- | -------------------------------------------------- | --------------------------- |
| 🔥 1     | `docs/agentic/contracts/clustering-api.md`         | WP REST → FastAPI endpoints |
| 🔥 2     | `docs/agentic/contracts/recognition-clustering.md` | FastAPI API spec            |
| 🔥 3     | `docs/agentic/contracts/security.md`               | Auth, tenant isolation      |
| 🔥 4     | `packages/shared-contracts/schemas/`               | JSON Schema definitions     |
| 🔥 5     | `docs/agentic/diagrams/system-overview.mmd`        | High-level architecture     |

## Request Flow

```
WordPress Frontend (React)
    ↓ fetch('/wp-json/acx/v1/recognition/...')
    ↓ OR EventSource('/wp-json/acx/v1/recognition/jobs/{id}/stream') for SSE
WordPress PHP (RecognitionController)
    ↓ Inject tenant_id, forward with API key
Recognition Service (FastAPI)
    ↓ Process, return JSON or SSE stream
WordPress PHP
    ↓ Return to frontend (or proxy SSE)
React UI (update state)
```

## Tenant ID Generation

WordPress generates tenant ID from site URL:

```php
$tenant_id = md5(get_site_url());  // 32-char hex string
```

The Recognition Service expects this in:

- `X-Tenant-ID` header (for reads)
- `tenant_id` field in JSON body (for writes)

## Authentication

| Environment | Method                                          |
| ----------- | ----------------------------------------------- |
| Local dev   | `RECOGNITION_ALLOWED_API_KEYS` env var (comma-separated) |
| Production  | API key in `Authorization: Bearer <key>` header |
| WordPress   | Key stored in `acx_recognition_api_key` option  |

See [../contracts/security.md](../contracts/security.md) for full details.

## Key Diagrams

- [../diagrams/system-overview.mmd](../diagrams/system-overview.mmd) — Full system architecture
- [../diagrams/backend-uml/agent-quick-start.mmd](../diagrams/backend-uml/agent-quick-start.mmd) — API routing
- [../diagrams/frontend-uml/proxy-boundary.mmd](../diagrams/frontend-uml/proxy-boundary.mmd) — Proxy layer detail

## Common Tasks

### Add new endpoint (both sides)

1. **Define contract** in `docs/agentic/contracts/clustering-api.md`
2. **FastAPI**: Add router in `recognition/interface_adapters/http/routers/`
3. **PHP proxy**: Add route in `RecognitionController.php`
4. **Frontend**: Add API client in `js/admin/api/`
5. **Tests**: API test (Python), integration test (PHP), component test (React)

### Change request/response shape

1. Update JSON Schema in `packages/shared-contracts/schemas/`
2. Update contract markdown in `docs/agentic/contracts/`
3. Update Python Pydantic model
4. Update TypeScript types
5. Update PHP DTO (if exists)

### Debug cross-service issue

1. Check WP REST response: `/wp-json/acx/v1/recognition/...`
2. Check Recognition Service logs (FastAPI)
3. Verify `tenant_id` matches between systems
4. Check API key is valid and has write access
