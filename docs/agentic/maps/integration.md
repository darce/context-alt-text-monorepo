# Integration Context Map

> Quick reference for cross-service work between WordPress and Recognition Service.

## Critical Files (Read First)

| Priority | File                                               | Purpose                       |
| -------- | -------------------------------------------------- | ----------------------------- |
| 1        | `docs/agentic/contracts/clustering-api.md`         | WP REST -> FastAPI endpoints  |
| 2        | `docs/agentic/contracts/recognition-clustering.md` | FastAPI API spec              |
| 3        | `docs/agentic/contracts/curation-sync-api.md`      | Outbox replay contract        |
| 4        | `docs/agentic/contracts/cluster-snapshot-api.md`   | Snapshot pull contract        |
| 5        | `docs/agentic/contracts/security.md`               | Auth, tenant isolation        |
| 6        | `packages/shared-contracts/schemas/`               | JSON Schema definitions       |
| 7        | `docs/agentic/diagrams/system-overview.mmd`        | High-level architecture       |

## Request Flows

### Pull flow: React -> PHP -> FastAPI (reads, scan jobs)

```
React UI
    | fetch('/wp-json/acx/v1/recognition/...')
    | or EventSource for SSE
PHP REST Layer (proxy controllers)
    | inject tenant_id + API key, forward
FastAPI Routers
    | process, return JSON or SSE stream
PHP
    | return to frontend
React UI (update TanStack Query cache)
```

### Push flow: Outbox drain -> FastAPI (curation replay)

```
Operator curation (label, merge, reassign, person bind)
    | writes to wp_acx_sync_outbox
OutboxDrain (wp-cron or manual trigger)
    | reads pending outbox rows, dispatches via OutboxDispatcher
OutboxDispatcher
    | POST /roster/curation/sync (person/cluster-person ops)
    | POST /recognition/clusters/{id}/merge, etc. (topology ops)
FastAPI
    | 200 acknowledged, 409 conflict, 4xx/5xx error
OutboxDrain
    | acknowledged: mark done, update sync state
    | conflict: store in wp_acx_sync_conflicts, surface to operator
    | transient error: retry with bounded attempts, dead-letter after max
```

### Snapshot projection flow: PHP <- FastAPI (sync pull)

```
SyncPullJob (wp-cron or manual trigger via SyncStatusController)
    | GET /tenants/{tenant_uuid}/clusters/snapshot
SnapshotProjector
    | atomic projection into wp_acx_clusters + wp_acx_identity_members
    | conflict detection: curated rows absent from snapshot -> wp_acx_sync_conflicts
    | POST /tenants/{tenant_uuid}/acknowledge-projection
SyncStateRepository
    | update sync_health, version cursors, metrics
```

## Tenant ID Generation

WordPress generates tenant ID from site URL:

```php
$tenant_id = md5(get_site_url());  // 32-char hex string
```

The Recognition Service expects this in:

- `X-Tenant-ID` header (for reads)
- `tenant_id` field in JSON body (for writes)
- Path param `tenant_uuid` (for snapshot endpoint)

## Authentication

| Environment | Method                                          |
| ----------- | ----------------------------------------------- |
| Local dev   | `RECOGNITION_ALLOWED_API_KEYS` env var (comma-separated) |
| Production  | API key in `Authorization: Bearer <key>` header |
| WordPress   | Key stored in `acx_recognition_api_key` option  |

All conflict, dead-letter, and sync status endpoints require `manage_options` capability on the WP side. Backend endpoints are gated by API key + tenant isolation.

See [../contracts/security.md](../contracts/security.md) for full details.

## Key Diagrams

- [../diagrams/system-overview.mmd](../diagrams/system-overview.mmd) — Full system architecture
- [../diagrams/sovereign-data-flow.mmd](../diagrams/sovereign-data-flow.mmd) — Sovereign sync data flow
- [../diagrams/backend-uml/agent-quick-start.mmd](../diagrams/backend-uml/agent-quick-start.mmd) — API routing
- [../diagrams/frontend-uml/proxy-boundary.mmd](../diagrams/frontend-uml/proxy-boundary.mmd) — Proxy layer detail

## Common Tasks

### Add new endpoint (both sides)

1. **Define contract** in `docs/agentic/contracts/`
2. **FastAPI**: Add router in `recognition/interface_adapters/http/routers/` or `roster/`
3. **PHP**: Add controller in `src/api/` or dispatch via `OutboxDispatcher`
4. **Frontend**: Add API client in `js/admin/api/recognition/`
5. **Tests**: API test (Python), PHPUnit test, Vitest component test

### Add a new outbox operation type (full stack)

1. **PHP**: Enqueue via `OutboxWriter::write()` in the mutations controller
2. **PHP**: Add dispatch route in `OutboxDispatcher` (topology routes or curation dispatch)
3. **Backend**: Handle in `roster/router.py` (curation) or existing topology endpoint
4. **PHP**: Add conflict acceptance logic in `ConflictResolutionService` if needed
5. **Frontend**: Update `conflictApi.ts` types if new `allowed_resolutions` rules apply
6. **Tests**: PHPUnit for drain + conflict, pytest for backend handler

### Change request/response shape

1. Update JSON Schema in `packages/shared-contracts/schemas/`
2. Update contract markdown in `docs/agentic/contracts/`
3. Update Python Pydantic model
4. Update TypeScript types in `js/admin/api/recognition/types/`
5. Update PHP DTO/response mapper if applicable

### Debug cross-service issue

1. Check WP REST response: `/wp-json/acx/v1/recognition/...`
2. Check Recognition Service logs (FastAPI)
3. Verify `tenant_id` matches between systems
4. Check API key is valid and has write access
5. For outbox issues: check `wp_acx_sync_outbox` status, error fields, attempt count
6. For conflicts: check `wp_acx_sync_conflicts` for open records
