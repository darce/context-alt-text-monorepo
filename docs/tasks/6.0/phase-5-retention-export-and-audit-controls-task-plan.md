# Phase 5: Retention, Export, and Audit Controls

## Problem Statement

The system stores machine-derived biometric state (embeddings, clustering, detection metadata) on the backend with no operator-visible lifecycle controls. Operators cannot inspect what biometric data is retained, request export of that data, trigger purging of working state no longer needed after local projection, or audit when retention lifecycle actions occurred. The MVP cannot credibly claim privacy-minimized retention without these controls.

## Workflow Principles

- **Minimized retention, not sovereignty.** Phase 5 delivers operator-visible retention controls and auditable lifecycle actions. Full sovereignty (customer-controlled embedding authority, ephemeral compute, region-pinning) is deferred post-v0.2.0.
- **Disposal after projection acknowledgement (with provenance tracking).** Machine-derived working state that is no longer needed after WordPress has projected and acknowledged the snapshot should be eligible for disposal under explicit tenant policy. The disposal boundary is: once WordPress has acknowledged the projection, backend embeddings and intermediate clustering state become disposal-eligible. **Implementation requirement:** the `get_snapshot()` endpoint must stamp each exported row with a `snapshot_generation_id` (UUID generated per snapshot build), and the `acknowledge-projection` request must include that `snapshot_generation_id` in its payload so the backend can identify which rows to mark as disposed. The `disposed_at` marking service uses `snapshot_generation_id` to identify exactly which source rows (`media_identities`, `identity_clusters`, `identity_cluster_representatives`) belonged to the acknowledged snapshot, rather than relying on the derived `snapshot_version` timestamp. The migration adds a `last_exported_snapshot_id` column to each source table.
- **Audit before action.** Every retention lifecycle action (retain, export, purge, dispose) must produce an audit event before or atomically with the action. Operators must be able to reconstruct what happened from the audit log alone.
- **Backend is the authority for policy enforcement.** Retention policy, export, and purge logic live on the backend. WordPress does not own retention logic but proxies backend-authored read and write actions for operator UX. All policy decisions, export generation, and purge execution happen on the backend; the plugin relays requests and caches responses.
- **Sync follow-on work stays out of this plan.** Representative pin/unpin parity and deferred `cluster_merged` conflict acceptance are tracked under the sovereign-sync follow-on epic, not under retention/export/audit delivery.

## Terminology

- **Retention mode**: the tenant-level policy governing how long machine-derived state is kept. Values: `retain_all` (default -- keep everything), `dispose_after_ack` (eligible for disposal once projection is acknowledged), `purge_on_demand` (retained until the operator triggers explicit purge).
- **Disposal**: the backend's removal of machine-derived working state (embeddings, intermediate clustering data) that is no longer needed after projection acknowledgement. Disposal is a soft-delete: rows are marked as disposed and excluded from future queries, but physical deletion is a separate `purge` step.
- **Purge**: permanent physical deletion of disposed or all machine-derived state for a tenant. Irreversible. Requires explicit operator action.
- **Export**: a tenant-scoped bulk extract of all machine-derived data (clusters, members, embeddings metadata, detection records) in a portable format. Does NOT include raw embedding vectors (those are not useful outside the model that generated them); includes cluster labels, member assignments, detection bounding boxes, media references, similarity scores, and representative metadata.
- **Audit event**: a timestamped record of a retention lifecycle action (retain, dispose, export, purge) with actor, scope, payload summary, and result status.

## Current State Analysis

- The backend `tenants` table has only `id`, `site_url`, `next_person_number`, and timestamps. No retention policy fields, no disposal eligibility markers, no audit event storage.
- The backend `media_identities` table stores embeddings and detection metadata with no lifecycle columns (`deleted_at`, `disposed_at`, `anonymized_at`).
- The backend `identity_cluster_representatives` table has `is_user_selected` (pin) support. The `identity_clusters` table tracks clustering state with `user_confirmed` and related confirmation columns but no pin marker. Neither table has disposal or retention markers.
- `RecognitionEvent` in `observability.py` tracks algorithmic events (assignment decisions, clustering feedback). It does not cover administrative or governance events (export, purge, policy changes).
- The backend `get_snapshot()` method exports cluster and member data for WordPress projection but is not a user-facing export surface. The snapshot `ClusterSnapshotClusterResponse` includes `representative_thumb_path` but not `representative_id` or `is_pinned`.
- WordPress `acx_clusters.representative_thumb_path` is always overwritten from the backend snapshot (not guarded by `is_user_confirmed`). Representative `id` and `is_pinned` are not projected locally (tracked in the sovereign-sync follow-on epic, not this plan).
- No export, retention, audit, or purge REST endpoints exist on the backend.
- No retention or audit information is surfaced to the plugin admin UI.
- The `settings.py` and `security.py` backend config files have no retention-related settings.

## Proposed Solution

Build Phase 5 as a retention/governance track:

1. **Backend: Tenant policy model and migration.** Add `retention_mode`, `last_export_at`, `last_purge_at`, and `retention_updated_at` fields to the `tenants` table. Add an `audit_events` table for tenant-scoped lifecycle event logging. Create a new follow-on Alembic migration (`003_retention_audit.py`) since `001_identity_schema.py` will not rerun on already-migrated environments and `002_clustering_feedback.py` already exists.

2. **Backend: Audit event service.** A domain service that records structured audit events atomically with the actions they describe. Every retention lifecycle action (policy change, export, purge, disposal) emits an audit event in the same database transaction.

3. **Backend: Export and purge service layer.** Domain services for tenant-scoped data export (portable JSON extract) and purge (physical deletion of disposed/all machine state). Export produces a structured JSON document covering clusters, members, detection metadata, and representative info. Purge cascades through embeddings, clusters, members, representatives, suggestions, and scan job data. Both emit audit events transactionally.

4. **Backend: HTTP endpoints.** Mount a `retention` router with: policy read (`GET`), policy update (`PATCH`), export trigger (`POST`), purge trigger (`POST`), audit event listing (`GET`). All admin-only (`X-API-Key` with tenant scoping).

5. **Plugin: Retention status proxy.** Add a WordPress REST endpoint that proxies the backend retention policy and audit summary for operator display. No local storage -- the plugin reads from the backend on demand and caches briefly. Add endpoint URL to `localize_spa_config`.

6. **Frontend: Retention and audit admin surface.** Add a retention settings panel showing current policy, last export/purge timestamps, and recent audit history. Add export and purge action buttons with confirmation dialogs. Surface retention mode in the sync status area so operators understand the data governance posture without navigating to a separate page.

Representative pin/unpin parity and the deferred `cluster_merged` conflict-acceptance contract were moved out of this plan. They now belong with the sovereign-sync follow-on work because they extend projection, outbox replay, and conflict-resolution semantics rather than retention governance.

## Patterns to Follow

### Backend: Audit Event Model

```python
# In db/models/observability.py -- new model
class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # event_type values: 'policy_updated', 'export_started', 'export_completed',
    #   'purge_started', 'purge_completed', 'disposal_completed'
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    # actor: 'api_key:<hash_prefix>', 'system:disposal_worker', 'system:projection_ack'
    scope: Mapped[str] = mapped_column(String(50), nullable=False, default="tenant")
    # scope: 'tenant', 'cluster:<uuid>', 'member:<uuid>'
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # payload: structured per event_type, e.g. {'retention_mode': 'dispose_after_ack', 'previous': 'retain_all'}
    result_status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    # result_status: 'success', 'failed', 'partial'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### Backend: Tenant Policy Extension

```python
# In db/models/tenant.py -- extend Tenant model
class Tenant(Base):
    # ... existing fields ...
    retention_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="retain_all"
    )
    # retention_mode: 'retain_all' | 'dispose_after_ack' | 'purge_on_demand'
    last_export_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_purge_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

### Backend: Export Service Pattern

```python
# In recognition/domain/services/export_service.py
class TenantExportService:
    """Produces a portable JSON export of all machine-derived state for a tenant."""

    async def export_tenant_data(
        self, tenant_id: str, actor: str
    ) -> dict:
        """Export clusters, members, detection metadata, and representative info.

        Does NOT include raw embedding vectors. Emits audit events atomically.
        Returns a structured dict suitable for JSON serialization.
        """
        # 1. Record export_started audit event
        # 2. Query clusters with representatives, members with identity metadata
        # 3. Build export payload
        # 4. Record export_completed audit event
        # 5. Update tenant.last_export_at
        # All within a single transaction
        ...
```

### Backend: Purge Service Pattern

```python
# In recognition/domain/services/purge_service.py
class TenantPurgeService:
    """Permanently deletes machine-derived state for a tenant."""

    async def purge_tenant_data(
        self, tenant_id: str, actor: str, scope: str = "disposed"
    ) -> dict:
        """Purge machine-derived state.

        scope='disposed': delete only rows marked as disposed (safe default).
        scope='all': delete ALL machine-derived state (embeddings, clusters, members,
                     representatives, suggestions, scan data). Irreversible.

        Emits audit events atomically. Returns summary of deleted counts.
        """
        # 1. Record purge_started audit event
        # 2. Delete in dependency order (see Phase 2 checklist for full cascade).
        #    Batch deletions per table (e.g. 1000 rows per batch) with a
        #    transaction-per-batch pattern. Accumulate deleted_counts across batches.
        # 3. Refresh mv_identity_cluster_centroids (for BOTH scope values).
        # 4. Record purge_completed audit event with counts
        # 5. Update tenant.last_purge_at
        # Preserve: tenant row, api_keys, audit_events (audit trail must survive purge).
        ...
```

### Backend: Retention Router Pattern

```python
# In recognition/interface_adapters/http/routers/retention.py
#
# IMPORTANT: Retention routes derive tenant_id exclusively from the
# authenticated API key's tenant_claim (via require_auth / require_write_access)
# rather than from get_tenant_id(). This eliminates the header-vs-query-param
# mismatch gap present in lower-sensitivity read endpoints.
#
# Background: get_tenant_id() accepts tenant_id from either the X-Tenant-ID
# header or a ?tenant_id query param, but require_auth only cross-checks the
# authenticated claim against the X-Tenant-ID header. A query-param-only
# request would bypass that check. Because retention endpoints perform
# high-sensitivity operations (export, purge, policy changes), they must
# derive tenant solely from the auth context.
#
# A shared get_authenticated_tenant_id() dependency should:
#   1. Call require_auth to obtain the AuthContext.
#   2. Return auth.tenant_claim if present.
#   3. Raise 403 if tenant_claim is None and the caller is not admin.
#   4. For admin keys (tenant_claim=None, is_admin=True), fall back to
#      X-Tenant-ID header (not query param) to allow admin overrides.
#
# This dependency replaces both require_auth and get_tenant_id for this
# router, so the router does NOT need a separate router-level require_auth.

router = APIRouter(
    prefix="/retention",
    tags=["retention"],
)

@router.get("/policy")
async def get_retention_policy(
    tenant_id: str = Depends(get_authenticated_tenant_id),
):
    """Read current tenant retention policy and lifecycle timestamps."""
    ...

@router.patch("/policy")
async def update_retention_policy(
    request: UpdateRetentionPolicyRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    _: None = Depends(require_write_access),
):
    """Update tenant retention mode. Emits audit event."""
    ...

@router.post("/export")
async def trigger_export(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    _: None = Depends(require_write_access),
):
    """Trigger a tenant data export. Returns export payload."""
    ...

@router.post("/purge")
async def trigger_purge(
    request: PurgeRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    _: None = Depends(require_write_access),
):
    """Trigger permanent deletion of machine-derived state. Irreversible."""
    ...

@router.get("/audit")
async def list_audit_events(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List tenant-scoped audit events, newest first."""
    ...
```

### Plugin: Retention Proxy Pattern

```php
// In RetentionController -- new REST controller
// GET /acx/v1/retention/status
//   Proxies backend GET /retention/policy + GET /retention/audit?limit=5
//   Returns merged response with policy fields and recent audit events
//   Caches for 60 seconds via transient to avoid hammering backend on page loads
//
// POST /acx/v1/retention/export
//   Proxies backend POST /retention/export
//
// POST /acx/v1/retention/purge
//   Proxies backend POST /retention/purge
//   Requires explicit confirmation parameter
//
// PATCH /acx/v1/retention/policy
//   Proxies backend PATCH /retention/policy
```

### Frontend: Retention Types

```typescript
// In js/admin/api/recognition/types/retention.ts
export type RetentionMode =
  | "retain_all"
  | "dispose_after_ack"
  | "purge_on_demand";

export interface RetentionPolicy {
  retention_mode: RetentionMode;
  last_export_at: string | null;
  last_purge_at: string | null;
  retention_updated_at: string | null;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  actor: string;
  scope: string;
  payload: Record<string, unknown>;
  result_status: "success" | "failed" | "partial";
  created_at: string;
}

export interface RetentionStatusResponse {
  available: boolean; // false when backend is unreachable
  policy: RetentionPolicy | null; // null when available=false
  recent_audit_events: AuditEvent[];
}

export interface ExportResponse {
  tenant_id: string;
  exported_at: string;
  cluster_count: number;
  member_count: number;
  identity_count: number;
  download_url?: string; // If async/file-based export is used
  data?: Record<string, unknown>; // If inline JSON export
}

export interface PurgeResponse {
  tenant_id: string;
  purged_at: string;
  scope: "disposed" | "all";
  deleted_counts: {
    clusters: number;
    members: number;
    identities: number;
    representatives: number;
    suggestions: number;
    scan_jobs: number;
  };
}
```

## Functions to Change

### Backend (Python)

| File                                                                                               | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `apps/prototype-description-service/db/models/tenant.py`                                           | Add `retention_mode`, `last_export_at`, `last_purge_at`, `retention_updated_at` columns to `Tenant` model.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `apps/prototype-description-service/db/models/observability.py`                                    | Add `AuditEvent` model with `tenant_id`, `event_type`, `actor`, `scope`, `payload` (JSONB), `result_status`, `created_at`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `apps/prototype-description-service/db/migrations/versions/003_retention_audit.py`                 | New follow-on Alembic migration. Add `audit_events` table, extend `tenants` table with retention policy columns, and add `disposed_at` and `last_exported_snapshot_id` columns to `media_identities`, `identity_clusters`, and `identity_cluster_representatives`. Depends on `002_clustering_feedback`. (`001` will not rerun on already-migrated environments.)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `apps/prototype-description-service/recognition/config/settings.py`                                | Add `default_retention_mode` setting (default `retain_all`) for tenant initialization.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `apps/prototype-description-service/recognition/domain/services/audit_service.py`                  | New service. `record_event(tenant_id, event_type, actor, scope, payload, result_status)` writes an `AuditEvent` within the caller's session/transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `apps/prototype-description-service/recognition/domain/services/export_service.py`                 | New service. `export_tenant_data(tenant_id, actor)` queries all machine-derived state (clusters, members, representatives, detection metadata), builds a portable JSON payload (no raw embedding vectors), records audit events atomically, and updates `tenant.last_export_at`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `apps/prototype-description-service/recognition/domain/services/purge_service.py`                  | New service. `purge_tenant_data(tenant_id, actor, scope)` performs cascading deletion of machine-derived state in dependency order. `scope='disposed'` deletes only rows marked as disposed; `scope='all'` deletes everything. Records audit events atomically. Updates `tenant.last_purge_at`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `apps/prototype-description-service/recognition/domain/services/retention_policy_service.py`       | New service. `get_policy(tenant_id)` reads current policy fields. `update_policy(tenant_id, retention_mode, actor)` validates the new mode, updates the tenant row, and records a `policy_updated` audit event atomically.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `apps/prototype-description-service/recognition/infrastructure/repositories/audit_repository.py`   | New repository. `create_event(...)`, `list_events(tenant_id, limit, offset)`, `count_events(tenant_id)`. Thin wrapper over SQLAlchemy queries on `AuditEvent`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py`      | New router. `GET /retention/policy`, `PATCH /retention/policy`, `POST /retention/export`, `POST /retention/purge`, `GET /retention/audit`. All endpoints derive tenant via `get_authenticated_tenant_id` (auth-claim-first, no query-param fallback). `require_write_access` on mutating endpoints (`PATCH`, `POST`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/tenant.py`            | Add `get_authenticated_tenant_id` dependency: extracts `tenant_id` from the authenticated API key's `tenant_claim`. For admin keys (`tenant_claim=None, is_admin=True`), falls back to `X-Tenant-ID` header only (not query param). Raises 403 if neither source provides a tenant. Used by retention router for high-sensitivity operations.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/requests.py`       | Add `UpdateRetentionPolicyRequest(retention_mode)` and `PurgeRequest(scope, confirm)` request schemas.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py`      | Add `RetentionPolicyResponse`, `AuditEventResponse`, `AuditEventListResponse`, `ExportResponse`, `PurgeResponse` response schemas. (Extending `ClusterSnapshotClusterResponse` with `representative_id` and `representative_is_pinned` is tracked in the sovereign-sync follow-on.)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `apps/prototype-description-service/recognition/interface_adapters/http/router.py`                 | Mount `retention` router alongside existing routers.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | Extend `get_snapshot()` to: (1) generate a `snapshot_generation_id` UUID per call and stamp each exported row's `last_exported_snapshot_id` column, (2) return `snapshot_generation_id` in the snapshot response envelope so the WP projector can echo it back during acknowledgement, (3) filter out rows where `disposed_at IS NOT NULL` so disposed rows are excluded from subsequent snapshot exports and tenant data exports. (Including `representative_id` and `is_user_selected` in snapshot data is tracked in the sovereign-sync follow-on.)                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`        | Extend `acknowledge-projection` handler: accept optional `snapshot_generation_id` in the acknowledgement payload. When `tenant.retention_mode == 'dispose_after_ack'` **and** `snapshot_generation_id` is present and valid, invoke the disposal marking service to `SET disposed_at = now() WHERE last_exported_snapshot_id = :snapshot_generation_id` on `media_identities`, `identity_clusters`, and `identity_cluster_representatives`. When `retention_mode == 'dispose_after_ack'` but `snapshot_generation_id` is absent or not a valid UUID format, reject the acknowledgement with HTTP 422 (the dispose contract requires provenance). A format-valid `snapshot_generation_id` that matches zero rows succeeds as a no-op disposal (acknowledgement proceeds). When `retention_mode` is not `dispose_after_ack`, accept the acknowledgement regardless of whether `snapshot_generation_id` is present (backward compatibility with older WP clients during rollout). |

### Plugin (WordPress PHP)

| File                                                                                   | Change                                                                                                                                                                                                                                                                                                        |
| -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/interface-snapshot-client.php`       | Extend `acknowledge_projection()` signature to accept `string $snapshot_generation_id` as a third parameter. The generation ID is required for disposal marking when `retention_mode='dispose_after_ack'`.                                                                                                    |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-client-transport.php` | Extend `acknowledge_projection()` to include `snapshot_generation_id` in the HTTP POST body alongside `snapshot_version`.                                                                                                                                                                                     |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php`             | Extend `maybe_acknowledge_projection()` to extract `snapshot_generation_id` from the snapshot response envelope and pass it to `$this->client->acknowledge_projection()`. Skip the generation-ID parameter gracefully when the snapshot response does not include it (backward compatibility during rollout). |
| `apps/prototype-wp-alt-context/src/api/class-retention-controller.php`                 | New controller. Proxies backend retention endpoints: `GET /acx/v1/retention/status`, `POST /acx/v1/retention/export`, `POST /acx/v1/retention/purge`, `PATCH /acx/v1/retention/policy`. Caches policy reads via WP transient (60s TTL). Permission: `manage_options`.                                         |
| `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`               | Update composition root to instantiate `RetentionController` and register its routes.                                                                                                                                                                                                                         |
| `apps/prototype-wp-alt-context/src/admin/class-admin.php`                              | Add `retentionStatus`, `retentionExport`, `retentionPurge`, `retentionPolicy` endpoint URLs to `localize_spa_config()`.                                                                                                                                                                                       |

### Frontend (TypeScript/React)

| File                                                                             | Change                                                                                                                                     |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/retention.ts`      | New file. `RetentionMode`, `RetentionPolicy`, `AuditEvent`, `RetentionStatusResponse`, `ExportResponse`, `PurgeResponse` types.            |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/index.ts`          | Export `retention.ts` types.                                                                                                               |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/retentionApi.ts`         | New file. API functions: `fetchRetentionStatus()`, `updateRetentionPolicy()`, `triggerExport()`, `triggerPurge()`.                         |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/index.ts`                | Barrel export retention API functions.                                                                                                     |
| `apps/prototype-wp-alt-context/js/admin/api/queryKeys.ts`                        | Add `retention` key factory (`retention.all`, `retention.status`, `retention.audit`).                                                      |
| `apps/prototype-wp-alt-context/js/admin/hooks/useRetentionStatus.ts`             | New hook. `useQuery` for retention policy and recent audit events.                                                                         |
| `apps/prototype-wp-alt-context/js/admin/hooks/useUpdateRetentionPolicy.ts`       | New hook. `useMutation` for policy updates, invalidates retention queries.                                                                 |
| `apps/prototype-wp-alt-context/js/admin/hooks/useExportTenantData.ts`            | New hook. `useMutation` for export trigger.                                                                                                |
| `apps/prototype-wp-alt-context/js/admin/hooks/usePurgeTenantData.ts`             | New hook. `useMutation` for purge trigger with confirmation requirement.                                                                   |
| `apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx`                 | New page or panel. Shows current retention policy, export/purge action buttons with confirmation dialogs, and recent audit event timeline. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` | Add retention mode badge (compact display of current `retention_mode` if not `retain_all`). Links to retention panel.                      |
| `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx`                 | Add retention summary card: current mode, last export/purge timestamps, link to retention page.                                            |

## Related Files

| File                                                                                | Note                                                                                                        |
| ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/sync.ts`              | Existing `SyncHealth` and `SyncStatusResponse` types. Retention mode may be surfaced alongside sync health. |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncStatus.ts`                     | Existing sync status hook. Retention status is a separate query, not merged into sync status.               |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md` | Parent epic with Phase 5 exit criteria and the authority-split architecture.                                |
| `docs/agentic/contracts/cluster-snapshot-api.md`                                    | Snapshot contract that needs `snapshot_generation_id` extension for disposal provenance.                    |

---

# Consolidated Checklist

## Completed (Pre-existing Infrastructure)

- [x] Backend `get_snapshot()` returns tenant cluster/member state for WordPress projection.
- [x] WordPress `acx_clusters.representative_thumb_path` column projected from backend snapshot.
- [x] WordPress outbox infrastructure (writer, drain) supports durable replay for arbitrary operation types.
- [x] WordPress `ClusterMutationsController` is the curation mutation entrypoint (label, merge, reassign, etc.).
- [x] WordPress `localize_spa_config()` injects endpoint URLs into the frontend.
- [x] WordPress sync pull + snapshot projector transactionally projects backend state.
- [x] RLS (Row Level Security) on all tenant-scoped backend tables.
- [x] Plugin `manage_options` capability check pattern for admin-only REST endpoints.

## Phase 0: Scaffolding

- [x] Add `AuditEvent` model stub in `db/models/observability.py` with `__tablename__` and column definitions.
- [x] Add retention policy columns to `Tenant` model in `db/models/tenant.py` with defaults.
- [x] Create new Alembic migration `003_retention_audit.py` (depends on `002_clustering_feedback`). Add `audit_events` table and `tenants` column extensions. Do not modify `001_identity_schema.py`.
- [x] Add domain service stubs: `audit_service.py`, `export_service.py`, `purge_service.py`, `retention_policy_service.py` with `raise NotImplementedError("TODO")`.
- [x] Add `audit_repository.py` stub with query method signatures.
- [x] Add `retention.py` router stub with route registrations returning `501 Not Implemented`.
- [x] Add `get_authenticated_tenant_id` shared dependency in `deps/tenant.py`: derives tenant_id exclusively from the authenticated API key's `tenant_claim` (via `require_auth`), falling back to `X-Tenant-ID` header for admin keys. Does NOT accept `?tenant_id` query param. Used by retention router for high-sensitivity operations.
- [x] Add request/response schema stubs: `UpdateRetentionPolicyRequest`, `PurgeRequest`, `RetentionPolicyResponse`, `AuditEventResponse`, `AuditEventListResponse`, `ExportResponse`, `PurgeResponse`.
- [x] Mount retention router in `router.py`.
- [x] Add `RetentionController` PHP stub with route registrations returning `501 Not Implemented`.
- [x] Wire `RetentionController` into `RecognitionController` composition root.
- [x] Add `retention.ts` TypeScript type stubs.
- [x] Add `retentionApi.ts` API function stubs.
- [x] Add retention query key factory in `queryKeys.ts`.
- [x] Add hook stubs: `useRetentionStatus.ts`, `useUpdateRetentionPolicy.ts`, `useExportTenantData.ts`, `usePurgeTenantData.ts`.
- [x] Add `RetentionPage.tsx` component stub.
- [x] Add endpoint URLs to `localize_spa_config()` for retention surfaces.
- [x] Create backend test stubs: `test_retention_policy.py`, `test_export_service.py`, `test_purge_service.py`, `test_audit_events.py`.
- [x] Create PHP test stubs: `RetentionControllerTest.php`.
- [x] Create Vitest test stubs: retention page and retention hooks.
- [x] Update `contracts/cluster-snapshot-api.md` with `snapshot_generation_id` (UUID) and existing `source_job_id` in the response envelope, optional `snapshot_generation_id` in the acknowledge-projection request payload, and correct the acknowledge-projection route path to match the actual code (`/recognition/jobs/{job_id}/acknowledge-projection` on the analyze router).
- [x] Verify scaffolds compile: backend `mypy`, PHP `composer phpstan`, TS `npm run typecheck`.

## Phase 1: Backend -- Tenant Policy Model and Audit Event Storage

- [x] Implement `AuditEvent` SQLAlchemy model with tenant FK, indexes on `(tenant_id, event_type)` and `(tenant_id, created_at DESC)`.
- [x] Implement tenant policy columns with server defaults (`retention_mode='retain_all'`).
- [ ] Verify `003_retention_audit.py` migration applies cleanly on top of `002_clustering_feedback`. Run `alembic upgrade head` against a fresh database and against an already-migrated database to confirm both paths work.
- [x] Add RLS policy on `audit_events` table matching existing tenant-scoped table pattern.
- [x] Implement `AuditRepository.create_event()`: insert within caller's session (no separate commit -- the caller controls the transaction boundary).
- [x] Implement `AuditRepository.list_events(tenant_id, limit, offset)`: paginated query ordered by `created_at DESC`.
- [x] Implement `AuditRepository.count_events(tenant_id)`: count for pagination headers.
- [x] Implement `RetentionPolicyService.get_policy(tenant_id)`: read tenant retention fields, return structured dict.
- [x] Implement `RetentionPolicyService.update_policy(tenant_id, retention_mode, actor)`: validate `retention_mode` is one of the allowed values, update tenant row, record `policy_updated` audit event atomically (same transaction).
- [x] Implement `AuditService.record_event(session, tenant_id, event_type, actor, scope, payload, result_status)`: creates `AuditEvent` within the given session. Used by all lifecycle services to ensure audit events are transactional.
- [x] Add `default_retention_mode` to `RecognitionSettings` with default `retain_all`.
- [ ] Add pytest tests: tenant policy CRUD, audit event recording and querying, policy update emits audit event, invalid retention_mode is rejected, RLS isolation.

## Phase 2: Backend -- Export and Purge Service Layer

- [ ] Implement `TenantExportService.export_tenant_data(tenant_id, actor)`: query clusters (with representatives including `is_user_selected`), members (with identity metadata excluding raw embedding vectors), detection records (bbox, confidence, media refs, similarity), and scan job summaries. Build portable JSON payload. Record `export_started` and `export_completed` audit events. Update `tenant.last_export_at`. All within one transaction.
- [ ] Define export payload schema: `{ tenant_id, exported_at, schema_version, clusters: [...], members: [...], identities: [...], representatives: [...], scan_jobs: [...] }`. Each entity includes its UUID, timestamps, and human-readable fields but NOT raw float32 embedding arrays.
- [ ] Implement `TenantPurgeService.purge_tenant_data(tenant_id, actor, scope)`:
  - `scope='disposed'`: delete rows where a disposal marker is set (requires disposal marking to be implemented first -- see Phase 2 disposal marking below).
  - `scope='all'`: cascade-delete ALL machine-derived state in dependency order using the real table names from `db/models/`: `identity_suggestions` -> `cluster_merge_suggestions` -> `identity_cluster_blocks` -> `identity_constraints` -> `recognition_events` -> `recognition_runs` -> `clustering_feedback` -> `assignment_decisions` -> `clustering_job_reports` -> `identity_scan_job_items` -> `identity_scan_jobs` -> `identity_clustering_jobs` -> `identity_cluster_representatives` -> `identity_members` -> `identity_clusters` -> `curation_replay_records` -> `media_identities`. Batch deletions per table (e.g. 1000 rows per batch) with a transaction-per-batch pattern rather than one mega-transaction. Accumulate `deleted_counts` across batches. Preserve the `tenant` row itself, `api_keys`, and `audit_events` (the audit trail must survive purge).
  - After source table deletions (for **both** `scope='disposed'` and `scope='all'`), refresh the `mv_identity_cluster_centroids` materialized view (`REFRESH MATERIALIZED VIEW CONCURRENTLY`). The view is a derived surface, not a tenant-owned source table.
  - Record `purge_started` and `purge_completed` audit events with deletion counts.
  - Update `tenant.last_purge_at`.
- [ ] Implement snapshot provenance tracking: add `last_exported_snapshot_id` (UUID, nullable) column to `media_identities`, `identity_clusters`, and `identity_cluster_representatives`. `get_snapshot()` generates a `snapshot_generation_id` per call and stamps it on each exported row. The snapshot response envelope includes `snapshot_generation_id` so the WP projector echoes it back during acknowledgement.
- [ ] Implement disposal marking: add `disposed_at` column to `media_identities`, `identity_clusters`, and `identity_cluster_representatives`. When `retention_mode='dispose_after_ack'` and a projection acknowledgement is received with a valid `snapshot_generation_id`, mark rows where `last_exported_snapshot_id = :snapshot_generation_id` as disposed. Wire the disposal check into the `acknowledge-projection` handler in `analyze.py` (or its backing domain service) so `dispose_after_ack` mode has a concrete activation mechanism. Reject the acknowledgement with HTTP 422 only when `retention_mode='dispose_after_ack'` and `snapshot_generation_id` is absent or not a valid UUID format (the dispose contract requires provenance). When the `snapshot_generation_id` is format-valid but matches zero rows, succeed as a no-op disposal (the acknowledgement proceeds normally -- this handles cases where rows were re-stamped by a newer snapshot export). When `retention_mode` is not `dispose_after_ack`, accept the acknowledgement regardless of whether `snapshot_generation_id` is present, preserving backward compatibility with older WP clients during rollout.
- [ ] Update `get_snapshot()` to exclude disposed rows (`WHERE disposed_at IS NULL` on `media_identities`, `identity_clusters`, and `identity_cluster_representatives`). The export service must apply the same filter to avoid including disposed rows in tenant exports.
- [ ] Add pytest tests: export produces valid payload with expected structure and no embedding vectors; purge with `scope='all'` removes all machine state and emits correct audit events; purge with `scope='disposed'` only deletes disposed rows and refreshes materialized view; disposal marking after projection acknowledgement; disposed rows are excluded from `get_snapshot()` results; purge counts are accurate; export and purge update tenant timestamps; `audit_events` survive purge.

## Phase 3: Backend -- Policy, Export, Purge, and Audit HTTP Endpoints

- [ ] Implement `GET /retention/policy`: returns `RetentionPolicyResponse` with `retention_mode`, `last_export_at`, `last_purge_at`, `retention_updated_at`.
- [ ] Implement `PATCH /retention/policy`: accepts `UpdateRetentionPolicyRequest(retention_mode)`, validates mode, calls `RetentionPolicyService.update_policy()`, returns updated policy.
- [ ] Implement `POST /retention/export`: calls `TenantExportService.export_tenant_data()`, returns `ExportResponse` with inline JSON payload and summary counts. For MVP, the export is synchronous and returned inline. Async/file-based export is a stretch goal.
- [ ] Add export size guard: before building the full payload, query the count of exportable identities. If the count exceeds a configurable threshold (e.g. 50k), return HTTP 413 with an advisory message pointing to the async export stretch goal. This keeps the MVP export honest without requiring the full async pipeline.
- [ ] Implement `POST /retention/purge`: accepts `PurgeRequest(scope, confirm)` where `confirm` must be `true` (prevents accidental purge). Calls `TenantPurgeService.purge_tenant_data()`, returns `PurgeResponse` with deleted counts. Returns `422` if `confirm` is not `true`. Returns `400` if `scope` is invalid.
- [ ] Implement `GET /retention/audit`: returns `AuditEventListResponse` with paginated audit events (limit/offset query params), ordered newest first.
- [ ] All endpoints derive tenant via `get_authenticated_tenant_id` (a new shared dependency that extracts tenant_id from the authenticated API key's `tenant_claim`, not from `get_tenant_id`). This eliminates the header-vs-query-param cross-check gap in `get_tenant_id` for high-sensitivity retention operations. Admin keys (no `tenant_claim`) fall back to `X-Tenant-ID` header only. Mutating endpoints (`PATCH /policy`, `POST /export`, `POST /purge`) additionally depend on `require_write_access`.
- [ ] Add pytest tests: policy CRUD via HTTP, export endpoint returns valid payload, purge endpoint requires confirmation, audit endpoint returns paginated events, unauthorized requests are rejected, tenant isolation is enforced.

## Moved Out: Representative Projection Extension and Pin Mutation Parity

Tracked in: [Sovereign Sync Expansion + Workbench UX Continuation](../../epics/v0.2.0/sovereign-sync-and-workbench-ux-epic.md)

- [ ] Add `representative_id varchar(36) NULL` and `is_representative_pinned tinyint(1) NOT NULL DEFAULT 0` columns to `acx_clusters` in `LifeCycleManager`.
- [ ] Extend `ClustersRepository::merge_snapshot_for_tenant()` to write `representative_id` and `is_representative_pinned` from the snapshot `representative_id` and `representative_is_pinned` fields. These columns follow the optimistic-write guard: skip overwriting when a pending or conflicted outbox row targets the same cluster's representative pin (`operation_type IN ('representative_pinned', 'representative_unpinned')` with matching `entity_key`). Once the outbox operation is acknowledged or discarded, subsequent projections overwrite freely.
- [ ] Extend `SnapshotProjector` to pass `representative_id` and `representative_is_pinned` from the snapshot response through to `merge_snapshot_for_tenant()`.
- [ ] Extend `ClusterResponseMapper` to include `representative_id` and `is_representative_pinned` in cluster responses. Update `TopUnlabeledRepresentative` to use the projected `is_pinned` value.
- [ ] Add `ClustersRepository::pin_representative(cluster_uuid, representative_id, is_pinned, tenant_id)`: update local `representative_id` and `is_representative_pinned` columns. Used for immediate local feedback when the operator pins/unpins.
- [ ] Add `POST /acx/v1/recognition/clusters/{uuid}/pin-representative` endpoint in `ClusterMutationsController`: accepts `{ representative_id, is_pinned }`, updates local state via `pin_representative()`, enqueues outbox operation (`representative_pinned` or `representative_unpinned`), returns updated cluster data. Permission: `manage_options`.
- [ ] Add outbox operation type handling in `OutboxDispatcher`: add a dedicated dispatch branch (or multi-segment path support) for `representative_pinned` and `representative_unpinned` that reads `representative_id` from the outbox payload and formats both `cluster_id` (from `entity_key`) and `representative_id` into `PATCH /recognition/clusters/{cluster_id}/representatives/{representative_id}/pin` with `{ is_pinned: true/false }` body. The existing single-`%s` route table interpolation is insufficient for this two-parameter path. The backend pin endpoint returns HTTP 204 (No Content) with no response body -- the dispatcher must treat status 204 as a success case without attempting to parse a response body (do not pass through `normalize_single_response()`).
- [ ] Add PHPUnit tests: snapshot projection writes `representative_id` and `is_representative_pinned`; pin-representative endpoint updates local state and enqueues outbox operation; outbox dispatcher maps pin operations to correct backend endpoint; pending outbox pin operation guards local pin columns from snapshot overwrite; once outbox is acknowledged/discarded, snapshot projection overwrites pin columns freely.

## Moved Out: Complete Deferred Compound Topology Acceptance

Tracked in: [Sovereign Sync Expansion + Workbench UX Continuation](../../epics/v0.2.0/sovereign-sync-and-workbench-ux-epic.md)

- [ ] Enrich `ClusterMutationsController::merge_clusters()` outbox payload with `moved_member_uuids` (or equivalent member UUID provenance) alongside the existing `target_cluster_id`. Capture the moved member UUIDs from the same local rows being reassigned so the payload remains authoritative for later conflict resolution.
- [ ] Extend `ConflictResolutionService` so `cluster_merged` conflicts can support `accepted` once the payload carries moved-member provenance. The accept-machine path must move only the recorded members back to the source cluster (`entity_key`), restore source/target `identity_count`, un-dismiss the source cluster, clear cluster curation guards on both affected clusters, discard the outbox row, and mark the conflict resolved inside one transaction.
- [ ] Extend `ConflictController::determine_allowed_resolutions()` so `cluster_merged` advertises `['accepted', 'dismissed']` only when the enriched payload is present and complete. Incomplete or legacy payloads remain dismiss-only.
- [ ] Update `ConflictInbox` preview/confirmation copy for `cluster_merged` so operators see which members will be moved back and which local cluster state will be restored before confirming acceptance.
- [ ] Add PHPUnit and Vitest coverage for the enriched payload, successful revert, stale-member abort, `allowed_resolutions` upgrade, and `cluster_merged` preview/confirmation UX.

## Phase 4: Plugin -- Retention Status Proxy and Admin Surface

- [x] Implement `RetentionController::get_status()`: proxies backend `GET /retention/policy` and `GET /retention/audit?limit=5`, merges into `RetentionStatusResponse`. Caches via WP transient (`acx_retention_status_{tenant_id}`, 60s TTL). Falls back to `{ available: false, policy: null, recent_audit_events: [] }` when the backend is unreachable (operator sees "unable to fetch retention status" in the UI, not a hard error). The `available` flag lets the frontend distinguish between a degraded response and a normal one without relying on nullable policy alone.
- [x] Implement `RetentionController::update_policy()`: proxies backend `PATCH /retention/policy`, invalidates transient cache on success.
- [x] Implement `RetentionController::trigger_export()`: proxies backend `POST /retention/export`, returns the export payload. Invalidates transient cache on success (since `last_export_at` changed).
- [x] Implement `RetentionController::trigger_purge()`: proxies backend `POST /retention/purge`, requires `confirm=true` parameter, returns purge summary. Invalidates transient cache on success. After a successful purge, trigger a forced sync pull (`SyncPullJob::execute()` or equivalent) so the local projection tables are reconciled against the now-empty backend state before cluster queries refetch. Without this step, invalidating frontend query keys would re-read stale local projection rows until the next scheduled sync.
- [x] Add endpoint URLs to `localize_spa_config()`: `retentionStatus`, `retentionPolicy`, `retentionExport`, `retentionPurge`.
- [x] Extend acknowledge-projection flow to carry `snapshot_generation_id`: update `SnapshotClientInterface::acknowledge_projection()` to accept `string $snapshot_generation_id`, update `SnapshotClientTransport` to include it in the HTTP POST body, and extend `SyncPullJob::maybe_acknowledge_projection()` to extract `snapshot_generation_id` from the snapshot response envelope and pass it through. When the snapshot response does not include `snapshot_generation_id` (rollout/backward compat), omit it from the request body.
- [x] Add PHPUnit tests: status endpoint proxies and caches correctly; cache invalidation on writes; unreachable backend returns graceful fallback; policy update forwards to backend; export and purge proxy correctly with confirmation enforcement; successful purge triggers a forced sync pull that reconciles local projection tables; acknowledge-projection forwards `snapshot_generation_id` when present in the snapshot response; omits it gracefully when absent.

## Phase 5: Frontend -- Retention and Audit Admin Surface

- [x] Implement `useRetentionStatus` hook: `useQuery` for `GET /acx/v1/retention/status`, 60s staleTime.
- [x] Implement `useUpdateRetentionPolicy` mutation hook: `PATCH /acx/v1/retention/policy`, invalidates `retention.status`.
- [x] Implement `useExportTenantData` mutation hook: `POST /acx/v1/retention/export`, invalidates `retention.status`.
- [x] Implement `usePurgeTenantData` mutation hook: `POST /acx/v1/retention/purge`, invalidates `retention.status` + `sync.all` + `clusters.all`. The plugin purge proxy triggers a forced sync pull before returning, so by the time the frontend invalidates cluster queries the local projection tables already reflect the purged backend state.
- [x] Implement `RetentionPage` component:
  - Current retention mode selector (`retain_all`, `dispose_after_ack`, `purge_on_demand`) with save button.
  - Last export timestamp and "Export Data" button with confirmation dialog (explains what is exported and what is excluded).
  - Last purge timestamp and "Purge Data" button with strong confirmation dialog (scope selector: `disposed` vs `all`, explains irreversibility, requires typed confirmation).
  - Recent audit event timeline (5 most recent events with type, actor, timestamp, and payload summary).
  - Recent-audit summary copy clarifying that the panel shows the five most recent audit events until a fuller audit-log view exists.
  - Graceful degradation when backend is unreachable: show "Backend unavailable -- retention status cannot be loaded" with retry affordance.
- [x] Add retention mode badge to `SyncStatusIndicator`: shows compact retention mode label (e.g., "Retention: Dispose after ack") when mode is not `retain_all`. Links to `RetentionPage`.
- [x] Add retention summary card to `DashboardPage`: current mode, last export/purge timestamps.
- [x] Wire `RetentionPage` into the admin routing (new route or workbench overlay panel).
- [x] Add Vitest tests: retention page renders policy state correctly; policy update calls correct API; export button triggers export with confirmation; purge button requires confirmation and calls correct API with scope; audit timeline renders events; backend-unavailable state shows graceful fallback; retention badge shows in sync indicator when mode is not `retain_all`.

## Phase 6: Integration Tests

- [ ] Backend integration test: create tenant, set retention policy, export data, verify export payload structure, purge with `scope='all'`, verify all machine state deleted, verify audit events recorded for each action.
- [ ] Backend integration test: `dispose_after_ack` mode marks data as disposed after projection acknowledgement; purge with `scope='disposed'` deletes only disposed rows.
- [ ] PHP integration test: retention status endpoint proxies backend policy and caches correctly.
- [ ] Vitest integration test: retention page end-to-end flow with mocked API responses.
- [ ] All backend pytest, PHP PHPUnit/PHPStan, TypeScript type checks, and Vitest/ESLint checks pass.

## Stretch Goals

- [ ] Async/file-based export for large tenants (export returns a job ID, status polled separately, download URL when ready).
- [ ] Paginated full audit event log page with filtering by event type.
- [ ] Scheduled disposal worker that automatically purges disposed state on a configurable interval.
- [ ] Export format versioning and import capability for cross-site migration.
- [ ] Embedding-level disposal tracking (dispose individual identity embeddings vs. entire clusters).
- [ ] Retention policy presets (e.g., "GDPR mode" = `dispose_after_ack` + auto-purge after 30 days).

## Success Criteria

- [ ] Operators can read and update the tenant retention policy (`retain_all`, `dispose_after_ack`, `purge_on_demand`) from the admin UI without database access.
- [ ] Operators can trigger a tenant data export that produces a portable JSON payload covering clusters, members, detection metadata, and representative info (no raw embeddings).
- [ ] Operators can trigger a purge of machine-derived state with explicit confirmation, and the system records the action in the audit log.
- [ ] Every retention lifecycle action (policy change, export, purge, disposal) produces an auditable event visible to the operator.
- [ ] The retention mode is visible in the sync status area and dashboard so operators understand the data governance posture at a glance.
- [ ] The MVP can credibly claim privacy-minimized retention and auditable handling of machine-derived biometric state.
- [ ] All backend pytest, PHP PHPUnit/PHPStan, TypeScript type checks, and Vitest/ESLint checks pass.

## Out of Scope

- **Representative pin/unpin parity**: moved to the sovereign-sync follow-on epic because it extends snapshot projection and outbox replay, not retention governance.
- **Deferred `cluster_merged` machine-acceptance contract**: moved to the sovereign-sync follow-on epic because it is conflict-resolution/reconciliation work, not retention governance.
- **Full data sovereignty**: customer-controlled embedding authority, ephemeral compute APIs, and sovereignty-tier deployment modes are deferred post-v0.2.0.
- **Delta ingest**: replacing snapshot-heavy sync with richer deltas is tracked in deferred/post-v0.2.0 scope.
- **Region-pinning and encryption**: tenant-level encryption, key-management hooks, and region-pinning compliance features are deferred post-v0.2.0.
- **Backend-authored machine proposals for person names**: proposal generation/storage does not exist yet. Tracked separately from retention controls.
- **Embedding vector export**: raw float32 embedding arrays are excluded from the export payload because they are not portable across model versions. Only derived metadata (cluster assignments, similarity scores, bounding boxes) is exported.
