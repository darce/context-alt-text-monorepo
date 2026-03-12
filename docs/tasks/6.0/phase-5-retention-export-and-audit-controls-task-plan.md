# Phase 5: Retention, Export, and Audit Controls

## Problem Statement

The system stores machine-derived biometric state (embeddings, clustering, detection metadata) on the backend with no operator-visible lifecycle controls. Operators cannot inspect what biometric data is retained, request export of that data, trigger purging of working state no longer needed after local projection, or audit when retention lifecycle actions occurred. The MVP cannot credibly claim privacy-minimized retention without these controls.

## Workflow Principles

- **Minimized retention, not sovereignty.** Phase 5 delivers operator-visible retention controls and auditable lifecycle actions. Full sovereignty (customer-controlled embedding authority, ephemeral compute, region-pinning) is deferred post-v0.2.0.
- **Disposal after projection acknowledgement.** Machine-derived working state that is no longer needed after WordPress has projected and acknowledged the snapshot should be eligible for disposal under explicit tenant policy. The disposal boundary is: once WordPress has acknowledged the projection, backend embeddings and intermediate clustering state become disposal-eligible.
- **Audit before action.** Every retention lifecycle action (retain, export, purge, dispose) must produce an audit event before or atomically with the action. Operators must be able to reconstruct what happened from the audit log alone.
- **Backend is the authority for policy enforcement.** Retention policy, export, and purge logic live on the backend. WordPress does not own retention logic but proxies backend-authored read and write actions for operator UX. All policy decisions, export generation, and purge execution happen on the backend; the plugin relays requests and caches responses.
- **Representative pin/unpin is a low-frequency curation mutation.** It follows the established outbox replay contract. The local read model must be extended before the outbox operation is wired -- do not ship a replay-only mutation that has no local visibility.

## Terminology

- **Retention mode**: the tenant-level policy governing how long machine-derived state is kept. Values: `retain_all` (default -- keep everything), `dispose_after_ack` (eligible for disposal once projection is acknowledged), `purge_on_demand` (retained until the operator triggers explicit purge).
- **Disposal**: the backend's removal of machine-derived working state (embeddings, intermediate clustering data) that is no longer needed after projection acknowledgement. Disposal is a soft-delete: rows are marked as disposed and excluded from future queries, but physical deletion is a separate `purge` step.
- **Purge**: permanent physical deletion of disposed or all machine-derived state for a tenant. Irreversible. Requires explicit operator action.
- **Export**: a tenant-scoped bulk extract of all machine-derived data (clusters, members, embeddings metadata, detection records) in a portable format. Does NOT include raw embedding vectors (those are not useful outside the model that generated them); includes cluster labels, member assignments, detection bounding boxes, media references, similarity scores, and representative metadata.
- **Audit event**: a timestamped record of a retention lifecycle action (retain, dispose, export, purge) with actor, scope, payload summary, and result status.
- **Representative pin/unpin parity**: extending the WordPress projection schema to store `representative_id` and `is_pinned` state, and wiring the existing backend `PATCH /clusters/{id}/representatives/{rep_id}/pin` endpoint into the outbox replay contract so pin/unpin decisions survive offline periods.

## Current State Analysis

- The backend `tenants` table has only `id`, `site_url`, `next_person_number`, and timestamps. No retention policy fields, no disposal eligibility markers, no audit event storage.
- The backend `media_identities` table stores embeddings and detection metadata with no lifecycle columns (`deleted_at`, `disposed_at`, `anonymized_at`).
- The backend `identity_clusters` and `identity_cluster_representatives` tables track clustering state with `is_user_selected` (pin) support but no disposal or retention markers.
- `RecognitionEvent` in `observability.py` tracks algorithmic events (assignment decisions, clustering feedback). It does not cover administrative or governance events (export, purge, policy changes).
- The backend `get_snapshot()` method exports cluster and member data for WordPress projection but is not a user-facing export surface. The snapshot `ClusterSnapshotClusterResponse` includes `representative_thumb_path` but not `representative_id` or `is_pinned`.
- The backend has `PATCH /clusters/{id}/representatives/{rep_id}/pin` for pin/unpin. The WordPress plugin does NOT project representative `id` or `is_pinned` -- the `representative_thumb_path` column is the only representative data stored locally, and `is_pinned` is declared on `TopUnlabeledRepresentative` but currently has no projected local source -- it relies on backend data which does not include pin state in the cluster snapshot payload.
- There are no outbox operation types for representative pin/unpin. No `pin_representative` or `unpin_representative` operations exist in the WordPress outbox.
- WordPress `acx_clusters.representative_thumb_path` is always overwritten from the backend snapshot (not guarded by `is_user_confirmed`).
- No export, retention, audit, or purge REST endpoints exist on the backend.
- No retention or audit information is surfaced to the plugin admin UI.
- The `settings.py` and `security.py` backend config files have no retention-related settings.

## Proposed Solution

Build Phase 5 in eight layers:

1. **Backend: Tenant policy model and migration.** Add `retention_mode`, `last_export_at`, `last_purge_at`, and `retention_updated_at` fields to the `tenants` table. Add an `audit_events` table for tenant-scoped lifecycle event logging. Create a new follow-on Alembic migration (`003_retention_audit.py`) since `001_identity_schema.py` will not rerun on already-migrated environments and `002_clustering_feedback.py` already exists.

2. **Backend: Audit event service.** A domain service that records structured audit events atomically with the actions they describe. Every retention lifecycle action (policy change, export, purge, disposal) emits an audit event in the same database transaction.

3. **Backend: Export and purge service layer.** Domain services for tenant-scoped data export (portable JSON extract) and purge (physical deletion of disposed/all machine state). Export produces a structured JSON document covering clusters, members, detection metadata, and representative info. Purge cascades through embeddings, clusters, members, representatives, suggestions, and scan job data. Both emit audit events transactionally.

4. **Backend: HTTP endpoints.** Mount a `retention` router with: policy read (`GET`), policy update (`PATCH`), export trigger (`POST`), purge trigger (`POST`), audit event listing (`GET`). All admin-only (`X-API-Key` with tenant scoping).

5. **Plugin: Representative projection extension.** Extend the snapshot export to include `representative_id` and `is_pinned` per cluster. Extend `acx_clusters` schema with `representative_id` and `is_representative_pinned` columns. Update the snapshot projector to store these. Wire pin/unpin as a new outbox operation type through the established outbox replay contract.

6. **Plugin: Complete the deferred compound-topology accept path.** Move the remaining `cluster_merged` acceptance work from Phase 4 into this plan. Enrich the merge outbox payload with moved-member provenance, then add the final `cluster_merged` revert contract to the conflict resolution workflow so operators can accept machine state for all supported compound topology operations.

7. **Plugin: Retention status proxy.** Add a WordPress REST endpoint that proxies the backend retention policy and audit summary for operator display. No local storage -- the plugin reads from the backend on demand and caches briefly. Add endpoint URL to `localize_spa_config`.

8. **Frontend: Retention and audit admin surface.** Add a retention settings panel showing current policy, last export/purge timestamps, and recent audit history. Add export and purge action buttons with confirmation dialogs. Surface retention mode in the sync status area so operators understand the data governance posture without navigating to a separate page.

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
        # 3. Record purge_completed audit event with counts
        # 4. Update tenant.last_purge_at
        ...
```

### Backend: Retention Router Pattern

```python
# In recognition/interface_adapters/http/routers/retention.py
# Router-level require_auth enforces API-key authentication on all routes
# (matches existing pattern in analyze.py, events.py, etc.)
router = APIRouter(
    prefix="/retention",
    tags=["retention"],
    dependencies=[Depends(require_auth)],
)

@router.get("/policy")
async def get_retention_policy(tenant_id: str = Depends(get_tenant_id)):
    """Read current tenant retention policy and lifecycle timestamps."""
    ...

@router.patch("/policy")
async def update_retention_policy(
    request: UpdateRetentionPolicyRequest,
    tenant_id: str = Depends(get_tenant_id),
    _: None = Depends(require_write_access),
):
    """Update tenant retention mode. Emits audit event."""
    ...

@router.post("/export")
async def trigger_export(
    tenant_id: str = Depends(get_tenant_id),
    _: None = Depends(require_write_access),
):
    """Trigger a tenant data export. Returns export payload."""
    ...

@router.post("/purge")
async def trigger_purge(
    request: PurgeRequest,
    tenant_id: str = Depends(get_tenant_id),
    _: None = Depends(require_write_access),
):
    """Trigger permanent deletion of machine-derived state. Irreversible."""
    ...

@router.get("/audit")
async def list_audit_events(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List tenant-scoped audit events, newest first."""
    ...
```

### Plugin: Representative Schema Extension

```php
// In LifeCycleManager -- extend acx_clusters table definition
// Add columns:
//   representative_id varchar(36) NULL
//   is_representative_pinned tinyint(1) NOT NULL DEFAULT 0
```

### Plugin: Representative Pin Outbox Operation

```php
// In ClusterMutationsController -- new mutation endpoint
// POST /acx/v1/recognition/clusters/{uuid}/pin-representative
// Writes outbox operation with:
//   operation_type: 'representative_pinned' or 'representative_unpinned'
//   entity_type: 'cluster'
//   entity_key: cluster_uuid
//   payload: { representative_id: <id>, is_pinned: true/false }

// In OutboxDispatcher -- representative pin dispatch
//
// The existing dispatcher interpolates a single %s from entity_key into
// topology paths. The backend pin endpoint requires both cluster_id AND
// representative_id in the URL:
//   PATCH /clusters/{cluster_id}/representatives/{rep_id}/pin
//
// Adding a route-table-only entry is insufficient. The dispatcher needs a
// dedicated representative-pin dispatch branch (or multi-segment path
// support) that:
//   1. Reads representative_id from the outbox operation payload.
//   2. Formats both cluster_id (from entity_key) and representative_id
//      into the path before sending the PATCH request.
//
// Option A: Add a private dispatch_representative_pin() method that
//   builds the path manually:
//     $path = sprintf(
//         '/recognition/clusters/%s/representatives/%s/pin',
//         rawurlencode($entity_key),
//         rawurlencode($payload['representative_id'])
//     );
//
// Option B: Extend TOPOLOGY_ROUTES to support multiple placeholders
//   with a 'params' key that maps %1$s, %2$s to payload fields, and
//   update dispatch_topology_operation() to resolve them.
//
// Either approach is acceptable. Option A is simpler for a single use
// case; Option B is more general if future operations also need
// multi-segment paths.
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

### Snapshot Export Extension: Representative Data

The `ClusterSnapshotClusterResponse` must be extended to include representative `id` and `is_pinned` so WordPress can project them locally:

```python
class ClusterSnapshotClusterResponse(BaseModel):
    cluster_uuid: str
    label: str | None
    curation_state: Literal["active", "dismissed", "confirmed"]
    is_user_confirmed: bool
    identity_count: int
    representative_thumb_path: str | None = None
    representative_id: str | None = None       # NEW
    representative_is_pinned: bool = False      # NEW
```

The WordPress snapshot projector uses the new fields during `merge_snapshot_for_tenant()` to populate `acx_clusters.representative_id` and `acx_clusters.is_representative_pinned`. Unlike `representative_thumb_path` (pure machine state, always overwritten), representative pin columns follow the same optimistic-write contract as other curation mutations (label, merge, reassign): the `ClusterMutationsController` writes the local column immediately for operator feedback, then enqueues the outbox operation for backend replay. During snapshot projection, the projector overwrites `representative_id` and `is_representative_pinned` from the backend **only when no pending outbox operation targets the same cluster's representative pin** (i.e., if `wp_acx_sync_outbox` contains a `pending` or `conflict` row with `operation_type IN ('representative_pinned', 'representative_unpinned')` and matching `entity_key`, the snapshot does not overwrite the local pin columns). This mirrors the `is_user_confirmed` guard for cluster labels: unacknowledged local curation is preserved until the outbox drains or the operator resolves a conflict. Once the outbox operation is acknowledged (or discarded), the next snapshot projection overwrites freely.

## Functions to Change

### Backend (Python)

| File                                                                                               | Change                                                                                                                                                                                                                                                                                                           |
| -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/db/models/tenant.py`                                           | Add `retention_mode`, `last_export_at`, `last_purge_at`, `retention_updated_at` columns to `Tenant` model.                                                                                                                                                                                                       |
| `apps/prototype-description-service/db/models/observability.py`                                    | Add `AuditEvent` model with `tenant_id`, `event_type`, `actor`, `scope`, `payload` (JSONB), `result_status`, `created_at`.                                                                                                                                                                                       |
| `apps/prototype-description-service/db/migrations/versions/003_retention_audit.py`                 | New follow-on Alembic migration. Add `audit_events` table, extend `tenants` table with retention policy columns, and add `disposed_at` columns. Depends on `002_clustering_feedback`. (`001` will not rerun on already-migrated environments.)                                                                   |
| `apps/prototype-description-service/recognition/config/settings.py`                                | Add `default_retention_mode` setting (default `retain_all`) for tenant initialization.                                                                                                                                                                                                                           |
| `apps/prototype-description-service/recognition/domain/services/audit_service.py`                  | New service. `record_event(tenant_id, event_type, actor, scope, payload, result_status)` writes an `AuditEvent` within the caller's session/transaction.                                                                                                                                                         |
| `apps/prototype-description-service/recognition/domain/services/export_service.py`                 | New service. `export_tenant_data(tenant_id, actor)` queries all machine-derived state (clusters, members, representatives, detection metadata), builds a portable JSON payload (no raw embedding vectors), records audit events atomically, and updates `tenant.last_export_at`.                                 |
| `apps/prototype-description-service/recognition/domain/services/purge_service.py`                  | New service. `purge_tenant_data(tenant_id, actor, scope)` performs cascading deletion of machine-derived state in dependency order. `scope='disposed'` deletes only rows marked as disposed; `scope='all'` deletes everything. Records audit events atomically. Updates `tenant.last_purge_at`.                  |
| `apps/prototype-description-service/recognition/domain/services/retention_policy_service.py`       | New service. `get_policy(tenant_id)` reads current policy fields. `update_policy(tenant_id, retention_mode, actor)` validates the new mode, updates the tenant row, and records a `policy_updated` audit event atomically.                                                                                       |
| `apps/prototype-description-service/recognition/infrastructure/repositories/audit_repository.py`   | New repository. `create_event(...)`, `list_events(tenant_id, limit, offset)`, `count_events(tenant_id)`. Thin wrapper over SQLAlchemy queries on `AuditEvent`.                                                                                                                                                   |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py`      | New router. `GET /retention/policy`, `PATCH /retention/policy`, `POST /retention/export`, `POST /retention/purge`, `GET /retention/audit`. Router-level `require_auth` dependency for API-key authentication; `require_write_access` on mutating endpoints (`PATCH`, `POST`). Tenant-scoped via `get_tenant_id`. |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/requests.py`       | Add `UpdateRetentionPolicyRequest(retention_mode)` and `PurgeRequest(scope, confirm)` request schemas.                                                                                                                                                                                                           |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py`      | Add `RetentionPolicyResponse`, `AuditEventResponse`, `AuditEventListResponse`, `ExportResponse`, `PurgeResponse` response schemas. Extend `ClusterSnapshotClusterResponse` with `representative_id` and `representative_is_pinned`.                                                                              |
| `apps/prototype-description-service/recognition/interface_adapters/http/router.py`                 | Mount `retention` router alongside existing routers.                                                                                                                                                                                                                                                             |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | Extend `get_snapshot()` to include `representative_id` and `is_user_selected` (pin state) in the per-cluster snapshot data. Extend `_to_domain()` if needed so representative metadata flows through to snapshot serialization.                                                                                  |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`        | Extend `acknowledge-projection` handler: when `tenant.retention_mode == 'dispose_after_ack'`, invoke the disposal marking service to set `disposed_at` on eligible `media_identities`, `identity_clusters`, and `identity_cluster_representatives` rows for the acknowledged snapshot.                           |

### Plugin (WordPress PHP)

| File                                                                                     | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`                 | Add `representative_id varchar(36) NULL` and `is_representative_pinned tinyint(1) NOT NULL DEFAULT 0` columns to `acx_clusters` table definition.                                                                                                                                                                                                                                                                                                                                                  |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | Update `merge_snapshot_for_tenant()` to write `representative_id` and `is_representative_pinned` from snapshot data. Update `resolve_representative_thumb_path()` to prefer `representative_id` when present. Add `pin_representative(cluster_uuid, representative_id, is_pinned, tenant_id)` method for local state update after outbox acknowledgement.                                                                                                                                          |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php`          | Pass `representative_id` and `representative_is_pinned` through to `merge_snapshot_for_tenant()`.                                                                                                                                                                                                                                                                                                                                                                                                  |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php`                | No changes -- the outbox drain already handles new operation types generically.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php`           | Add `representative_pinned` and `representative_unpinned` dispatch support. Requires a dedicated dispatch branch (or multi-segment path support) that reads `representative_id` from the outbox payload and formats both `cluster_id` (from `entity_key`) and `representative_id` into the `PATCH /recognition/clusters/{id}/representatives/{rep_id}/pin` path. A simple route-table entry with single `%s` interpolation is insufficient -- see the Representative Pin Outbox Operation pattern. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php`               | No changes -- the writer already handles arbitrary operation types.                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`           | Add `POST /acx/v1/recognition/clusters/{uuid}/pin-representative` endpoint that writes to local `acx_clusters` and enqueues an outbox operation (`representative_pinned` / `representative_unpinned`).                                                                                                                                                                                                                                                                                             |
| `apps/prototype-wp-alt-context/src/api/class-retention-controller.php`                   | New controller. Proxies backend retention endpoints: `GET /acx/v1/retention/status`, `POST /acx/v1/retention/export`, `POST /acx/v1/retention/purge`, `PATCH /acx/v1/retention/policy`. Caches policy reads via WP transient (60s TTL). Permission: `manage_options`.                                                                                                                                                                                                                              |
| `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`                 | Update composition root to instantiate `RetentionController` and register its routes.                                                                                                                                                                                                                                                                                                                                                                                                              |
| `apps/prototype-wp-alt-context/src/admin/class-admin.php`                                | Add `retentionStatus`, `retentionExport`, `retentionPurge`, `retentionPolicy`, and `recognitionPinRepresentative` endpoint URLs to `localize_spa_config()`.                                                                                                                                                                                                                                                                                                                                        |

### Frontend (TypeScript/React)

| File                                                                             | Change                                                                                                                                                                                                                                   |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/retention.ts`      | New file. `RetentionMode`, `RetentionPolicy`, `AuditEvent`, `RetentionStatusResponse`, `ExportResponse`, `PurgeResponse` types.                                                                                                          |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/index.ts`          | Export `retention.ts` types.                                                                                                                                                                                                             |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts`        | `TopUnlabeledRepresentative.is_pinned` already exists as a regular boolean field. No type change needed -- the projected local source will be wired once `acx_clusters.is_representative_pinned` is populated by the snapshot projector. |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/retentionApi.ts`         | New file. API functions: `fetchRetentionStatus()`, `updateRetentionPolicy()`, `triggerExport()`, `triggerPurge()`.                                                                                                                       |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/index.ts`                | Barrel export retention API functions.                                                                                                                                                                                                   |
| `apps/prototype-wp-alt-context/js/admin/api/queryKeys.ts`                        | Add `retention` key factory (`retention.all`, `retention.status`, `retention.audit`).                                                                                                                                                    |
| `apps/prototype-wp-alt-context/js/admin/hooks/useRetentionStatus.ts`             | New hook. `useQuery` for retention policy and recent audit events.                                                                                                                                                                       |
| `apps/prototype-wp-alt-context/js/admin/hooks/useUpdateRetentionPolicy.ts`       | New hook. `useMutation` for policy updates, invalidates retention queries.                                                                                                                                                               |
| `apps/prototype-wp-alt-context/js/admin/hooks/useExportTenantData.ts`            | New hook. `useMutation` for export trigger.                                                                                                                                                                                              |
| `apps/prototype-wp-alt-context/js/admin/hooks/usePurgeTenantData.ts`             | New hook. `useMutation` for purge trigger with confirmation requirement.                                                                                                                                                                 |
| `apps/prototype-wp-alt-context/js/admin/hooks/usePinRepresentative.ts`           | New hook. `useMutation` for `POST /acx/v1/recognition/clusters/{uuid}/pin-representative`, invalidates cluster queries.                                                                                                                  |
| `apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx`                 | New page or panel. Shows current retention policy, export/purge action buttons with confirmation dialogs, and recent audit event timeline.                                                                                               |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` | Add retention mode badge (compact display of current `retention_mode` if not `retain_all`). Links to retention panel.                                                                                                                    |
| `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx`                 | Add retention summary card: current mode, last export/purge timestamps, link to retention page.                                                                                                                                          |

## Related Files

| File                                                                                         | Note                                                                                                                                                                    |
| -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/recognition/domain/repositories.py`                      | Defines `mark_representative_user_selected()` and `get_user_selected_representatives()` -- the backend representative pin interface that outbox dispatcher will target. |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Has `PATCH /clusters/{id}/representatives/{rep_id}/pin` endpoint. The outbox dispatcher maps to this.                                                                   |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-resolution-service.php`     | Conflict resolution service from Phase 4. Representative pin conflicts follow the same resolution pattern if they arise.                                                |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-repository.php`             | Conflict recording. Representative pin outbox operations may generate conflicts on version mismatch like any other curation mutation.                                   |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/sync.ts`                       | Existing `SyncHealth` and `SyncStatusResponse` types. Retention mode may be surfaced alongside sync health.                                                             |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncStatus.ts`                              | Existing sync status hook. Retention status is a separate query, not merged into sync status.                                                                           |
| `docs/tasks/6.0/phase-4-offline-and-conflict-ux-task-plan.md`                                | Phase 4 delivers the conflict and dead-letter infrastructure that representative pin/unpin outbox operations use.                                                       |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md`          | Parent epic with Phase 5 exit criteria and the authority-split architecture.                                                                                            |
| `docs/agentic/contracts/cluster-snapshot-api.md`                                             | Snapshot contract that needs `representative_id` and `representative_is_pinned` extensions.                                                                             |

---

# Consolidated Checklist

## Completed (Pre-existing Infrastructure)

- [x] Backend `PATCH /clusters/{id}/representatives/{rep_id}/pin` endpoint exists with `PinRepresentativeRequest`.
- [x] Backend `mark_representative_user_selected()` repository method and `is_user_selected` column on `identity_cluster_representatives`.
- [x] Backend `get_snapshot()` returns tenant cluster/member state for WordPress projection.
- [x] Backend `RepresentativeResponse` schema has `is_pinned` field (aliased from `is_user_selected`).
- [x] WordPress `acx_clusters.representative_thumb_path` column projected from backend snapshot.
- [x] WordPress outbox infrastructure (writer, drain) supports durable replay for arbitrary operation types. The dispatcher supports existing single-segment topology routes and the roster curation batch endpoint; representative pin/unpin requires new multi-segment dispatch logic (see Phase 4 dispatcher work in this plan).
- [x] WordPress `ClusterMutationsController` is the curation mutation entrypoint (label, merge, reassign, etc.).
- [x] WordPress `localize_spa_config()` injects endpoint URLs into the frontend.
- [x] WordPress sync pull + snapshot projector transactionally projects backend state.
- [x] RLS (Row Level Security) on all tenant-scoped backend tables.
- [x] Plugin `manage_options` capability check pattern for admin-only REST endpoints.

## Phase 0: Scaffolding

- [ ] Add `AuditEvent` model stub in `db/models/observability.py` with `__tablename__` and column definitions.
- [ ] Add retention policy columns to `Tenant` model in `db/models/tenant.py` with defaults.
- [ ] Create new Alembic migration `003_retention_audit.py` (depends on `002_clustering_feedback`). Add `audit_events` table and `tenants` column extensions. Do not modify `001_identity_schema.py`.
- [ ] Add domain service stubs: `audit_service.py`, `export_service.py`, `purge_service.py`, `retention_policy_service.py` with `raise NotImplementedError("TODO")`.
- [ ] Add `audit_repository.py` stub with query method signatures.
- [ ] Add `retention.py` router stub with route registrations returning `501 Not Implemented`.
- [ ] Add request/response schema stubs: `UpdateRetentionPolicyRequest`, `PurgeRequest`, `RetentionPolicyResponse`, `AuditEventResponse`, `AuditEventListResponse`, `ExportResponse`, `PurgeResponse`.
- [ ] Extend `ClusterSnapshotClusterResponse` with `representative_id: str | None = None` and `representative_is_pinned: bool = False`.
- [ ] Mount retention router in `router.py`.
- [ ] Add `representative_id` and `is_representative_pinned` columns to `acx_clusters` table in `LifeCycleManager`.
- [ ] Add `RetentionController` PHP stub with route registrations returning `501 Not Implemented`.
- [ ] Wire `RetentionController` into `RecognitionController` composition root.
- [ ] Add pin-representative endpoint stub in `ClusterMutationsController`.
- [ ] Add `retention.ts` TypeScript type stubs.
- [ ] Add `retentionApi.ts` API function stubs.
- [ ] Add retention query key factory in `queryKeys.ts`.
- [ ] Add hook stubs: `useRetentionStatus.ts`, `useUpdateRetentionPolicy.ts`, `useExportTenantData.ts`, `usePurgeTenantData.ts`, `usePinRepresentative.ts`.
- [ ] Add `RetentionPage.tsx` component stub.
- [ ] Add endpoint URLs to `localize_spa_config()` for retention and pin-representative.
- [ ] Create backend test stubs: `test_retention_policy.py`, `test_export_service.py`, `test_purge_service.py`, `test_audit_events.py`.
- [ ] Create PHP test stubs: `RetentionControllerTest.php`, representative pin integration tests.
- [ ] Create Vitest test stubs: retention page, retention hooks, pin representative.
- [ ] Update `contracts/cluster-snapshot-api.md` with `representative_id` and `representative_is_pinned` fields.
- [ ] Verify scaffolds compile: backend `mypy`, PHP `composer phpstan`, TS `npm run typecheck`.

## Phase 1: Backend -- Tenant Policy Model and Audit Event Storage

- [ ] Implement `AuditEvent` SQLAlchemy model with tenant FK, indexes on `(tenant_id, event_type)` and `(tenant_id, created_at DESC)`.
- [ ] Implement tenant policy columns with server defaults (`retention_mode='retain_all'`).
- [ ] Verify `003_retention_audit.py` migration applies cleanly on top of `002_clustering_feedback`. Run `alembic upgrade head` against a fresh database and against an already-migrated database to confirm both paths work.
- [ ] Add RLS policy on `audit_events` table matching existing tenant-scoped table pattern.
- [ ] Implement `AuditRepository.create_event()`: insert within caller's session (no separate commit -- the caller controls the transaction boundary).
- [ ] Implement `AuditRepository.list_events(tenant_id, limit, offset)`: paginated query ordered by `created_at DESC`.
- [ ] Implement `AuditRepository.count_events(tenant_id)`: count for pagination headers.
- [ ] Implement `RetentionPolicyService.get_policy(tenant_id)`: read tenant retention fields, return structured dict.
- [ ] Implement `RetentionPolicyService.update_policy(tenant_id, retention_mode, actor)`: validate `retention_mode` is one of the allowed values, update tenant row, record `policy_updated` audit event atomically (same transaction).
- [ ] Implement `AuditService.record_event(session, tenant_id, event_type, actor, scope, payload, result_status)`: creates `AuditEvent` within the given session. Used by all lifecycle services to ensure audit events are transactional.
- [ ] Add `default_retention_mode` to `RecognitionSettings` with default `retain_all`.
- [ ] Add pytest tests: tenant policy CRUD, audit event recording and querying, policy update emits audit event, invalid retention_mode is rejected, RLS isolation.

## Phase 2: Backend -- Export and Purge Service Layer

- [ ] Implement `TenantExportService.export_tenant_data(tenant_id, actor)`: query clusters (with representatives including `is_user_selected`), members (with identity metadata excluding raw embedding vectors), detection records (bbox, confidence, media refs, similarity), and scan job summaries. Build portable JSON payload. Record `export_started` and `export_completed` audit events. Update `tenant.last_export_at`. All within one transaction.
- [ ] Define export payload schema: `{ tenant_id, exported_at, schema_version, clusters: [...], members: [...], identities: [...], representatives: [...], scan_jobs: [...] }`. Each entity includes its UUID, timestamps, and human-readable fields but NOT raw float32 embedding arrays.
- [ ] Implement `TenantPurgeService.purge_tenant_data(tenant_id, actor, scope)`:
  - `scope='disposed'`: delete rows where a disposal marker is set (requires disposal marking to be implemented first -- see Phase 2 disposal marking below).
  - `scope='all'`: cascade-delete ALL machine-derived state in dependency order using the real table names from `db/models/`: `identity_suggestions` -> `cluster_merge_suggestions` -> `identity_cluster_blocks` -> `identity_constraints` -> `recognition_events` -> `recognition_runs` -> `clustering_feedback` -> `assignment_decisions` -> `clustering_job_reports` -> `identity_scan_job_items` -> `identity_scan_jobs` -> `identity_clustering_jobs` -> `identity_cluster_representatives` -> `identity_members` -> `identity_clusters` -> `curation_replay_records` -> `media_identities`. After source table deletions, refresh the `mv_identity_cluster_centroids` materialized view (it is a derived surface, not a tenant-owned source table -- use `REFRESH MATERIALIZED VIEW CONCURRENTLY` rather than direct DELETE). Batch deletions per table (e.g. 1000 rows per batch) with a transaction-per-batch pattern rather than one mega-transaction. Accumulate `deleted_counts` across batches. Preserve the `tenant` row itself and `api_keys`.
  - Record `purge_started` and `purge_completed` audit events with deletion counts.
  - Update `tenant.last_purge_at`.
- [ ] Implement disposal marking: add `disposed_at` column to `media_identities`, `identity_clusters`, and `identity_cluster_representatives`. When `retention_mode='dispose_after_ack'` and a projection acknowledgement is received, mark the acknowledged snapshot's source data as disposed. Wire the disposal check into the `acknowledge-projection` handler in `analyze.py` (or its backing domain service) so `dispose_after_ack` mode has a concrete activation mechanism.
- [ ] Add pytest tests: export produces valid payload with expected structure and no embedding vectors; purge with `scope='all'` removes all machine state and emits correct audit events; purge with `scope='disposed'` only deletes disposed rows; disposal marking after projection acknowledgement; purge counts are accurate; export and purge update tenant timestamps.

## Phase 3: Backend -- Policy, Export, Purge, and Audit HTTP Endpoints

- [ ] Implement `GET /retention/policy`: returns `RetentionPolicyResponse` with `retention_mode`, `last_export_at`, `last_purge_at`, `retention_updated_at`.
- [ ] Implement `PATCH /retention/policy`: accepts `UpdateRetentionPolicyRequest(retention_mode)`, validates mode, calls `RetentionPolicyService.update_policy()`, returns updated policy.
- [ ] Implement `POST /retention/export`: calls `TenantExportService.export_tenant_data()`, returns `ExportResponse` with inline JSON payload and summary counts. For MVP, the export is synchronous and returned inline. Async/file-based export is a stretch goal.
- [ ] Add export size guard: before building the full payload, query the count of exportable identities. If the count exceeds a configurable threshold (e.g. 50k), return HTTP 413 with an advisory message pointing to the async export stretch goal. This keeps the MVP export honest without requiring the full async pipeline.
- [ ] Implement `POST /retention/purge`: accepts `PurgeRequest(scope, confirm)` where `confirm` must be `true` (prevents accidental purge). Calls `TenantPurgeService.purge_tenant_data()`, returns `PurgeResponse` with deleted counts. Returns `422` if `confirm` is not `true`. Returns `400` if `scope` is invalid.
- [ ] Implement `GET /retention/audit`: returns `AuditEventListResponse` with paginated audit events (limit/offset query params), ordered newest first.
- [ ] All endpoints use router-level `require_auth` dependency for API-key authentication. Mutating endpoints (`PATCH /policy`, `POST /export`, `POST /purge`) additionally depend on `require_write_access`. Tenant scoping via `get_tenant_id`.
- [ ] Add pytest tests: policy CRUD via HTTP, export endpoint returns valid payload, purge endpoint requires confirmation, audit endpoint returns paginated events, unauthorized requests are rejected, tenant isolation is enforced.

## Phase 4: Plugin -- Representative Projection Extension and Pin Mutation Parity

- [ ] Add `representative_id varchar(36) NULL` and `is_representative_pinned tinyint(1) NOT NULL DEFAULT 0` columns to `acx_clusters` in `LifeCycleManager`.
- [ ] Extend `ClustersRepository::merge_snapshot_for_tenant()` to write `representative_id` and `is_representative_pinned` from the snapshot `representative_id` and `representative_is_pinned` fields. These columns follow the optimistic-write guard: skip overwriting when a pending or conflicted outbox row targets the same cluster's representative pin (`operation_type IN ('representative_pinned', 'representative_unpinned')` with matching `entity_key`). Once the outbox operation is acknowledged or discarded, subsequent projections overwrite freely.
- [ ] Extend `SnapshotProjector` to pass `representative_id` and `representative_is_pinned` from the snapshot response through to `merge_snapshot_for_tenant()`.
- [ ] Extend `ClusterResponseMapper` to include `representative_id` and `is_representative_pinned` in cluster responses. Update `TopUnlabeledRepresentative` to use the projected `is_pinned` value.
- [ ] Add `ClustersRepository::pin_representative(cluster_uuid, representative_id, is_pinned, tenant_id)`: update local `representative_id` and `is_representative_pinned` columns. Used for immediate local feedback when the operator pins/unpins.
- [ ] Add `POST /acx/v1/recognition/clusters/{uuid}/pin-representative` endpoint in `ClusterMutationsController`: accepts `{ representative_id, is_pinned }`, updates local state via `pin_representative()`, enqueues outbox operation (`representative_pinned` or `representative_unpinned`), returns updated cluster data. Permission: `manage_options`.
- [ ] Add outbox operation type handling in `OutboxDispatcher`: add a dedicated dispatch branch (or multi-segment path support) for `representative_pinned` and `representative_unpinned` that reads `representative_id` from the outbox payload and formats both `cluster_id` (from `entity_key`) and `representative_id` into `PATCH /recognition/clusters/{cluster_id}/representatives/{representative_id}/pin` with `{ is_pinned: true/false }` body. The existing single-`%s` route table interpolation is insufficient for this two-parameter path. The backend pin endpoint returns HTTP 204 (No Content) with no response body -- the dispatcher must treat status 204 as a success case without attempting to parse a response body (do not pass through `normalize_single_response()`).
- [ ] Add PHPUnit tests: snapshot projection writes `representative_id` and `is_representative_pinned`; pin-representative endpoint updates local state and enqueues outbox operation; outbox dispatcher maps pin operations to correct backend endpoint; pending outbox pin operation guards local pin columns from snapshot overwrite; once outbox is acknowledged/discarded, snapshot projection overwrites pin columns freely.

## Phase 5: Plugin -- Complete Deferred Compound Topology Acceptance

- [ ] Enrich `ClusterMutationsController::merge_clusters()` outbox payload with `moved_member_uuids` (or equivalent member UUID provenance) alongside the existing `target_cluster_id`. Capture the moved member UUIDs from the same local rows being reassigned so the payload remains authoritative for later conflict resolution.
- [ ] Extend `ConflictResolutionService` so `cluster_merged` conflicts can support `accepted` once the payload carries moved-member provenance. The accept-machine path must move only the recorded members back to the source cluster (`entity_key`), restore source/target `identity_count`, un-dismiss the source cluster, clear cluster curation guards on both affected clusters, discard the outbox row, and mark the conflict resolved inside one transaction.
- [ ] Extend `ConflictController::determine_allowed_resolutions()` so `cluster_merged` advertises `['accepted', 'dismissed']` only when the enriched payload is present and complete. Incomplete or legacy payloads remain dismiss-only.
- [ ] Update `ConflictInbox` preview/confirmation copy for `cluster_merged` so operators see which members will be moved back and which local cluster state will be restored before confirming acceptance.
- [ ] Add PHPUnit and Vitest coverage for the enriched payload, successful revert, stale-member abort, `allowed_resolutions` upgrade, and `cluster_merged` preview/confirmation UX.

## Phase 6: Plugin -- Retention Status Proxy and Admin Surface

- [ ] Implement `RetentionController::get_status()`: proxies backend `GET /retention/policy` and `GET /retention/audit?limit=5`, merges into `RetentionStatusResponse`. Caches via WP transient (`acx_retention_status_{tenant_id}`, 60s TTL). Falls back to `{ available: false, policy: null, recent_audit_events: [] }` when the backend is unreachable (operator sees "unable to fetch retention status" in the UI, not a hard error). The `available` flag lets the frontend distinguish between a degraded response and a normal one without relying on nullable policy alone.
- [ ] Implement `RetentionController::update_policy()`: proxies backend `PATCH /retention/policy`, invalidates transient cache on success.
- [ ] Implement `RetentionController::trigger_export()`: proxies backend `POST /retention/export`, returns the export payload. Invalidates transient cache on success (since `last_export_at` changed).
- [ ] Implement `RetentionController::trigger_purge()`: proxies backend `POST /retention/purge`, requires `confirm=true` parameter, returns purge summary. Invalidates transient cache on success.
- [ ] Add endpoint URLs to `localize_spa_config()`: `retentionStatus`, `retentionPolicy`, `retentionExport`, `retentionPurge`.
- [ ] Add PHPUnit tests: status endpoint proxies and caches correctly; cache invalidation on writes; unreachable backend returns graceful fallback; policy update forwards to backend; export and purge proxy correctly with confirmation enforcement.

## Phase 7: Frontend -- Retention and Audit Admin Surface

- [ ] Implement `useRetentionStatus` hook: `useQuery` for `GET /acx/v1/retention/status`, 60s staleTime.
- [ ] Implement `useUpdateRetentionPolicy` mutation hook: `PATCH /acx/v1/retention/policy`, invalidates `retention.status`.
- [ ] Implement `useExportTenantData` mutation hook: `POST /acx/v1/retention/export`, invalidates `retention.status`.
- [ ] Implement `usePurgeTenantData` mutation hook: `POST /acx/v1/retention/purge`, invalidates `retention.status` + `sync.all` + `clusters.all`.
- [ ] Implement `usePinRepresentative` mutation hook: `POST /acx/v1/recognition/clusters/{uuid}/pin-representative`, invalidates `clusters.all`.
- [ ] Implement `RetentionPage` component:
  - Current retention mode selector (`retain_all`, `dispose_after_ack`, `purge_on_demand`) with save button.
  - Last export timestamp and "Export Data" button with confirmation dialog (explains what is exported and what is excluded).
  - Last purge timestamp and "Purge Data" button with strong confirmation dialog (scope selector: `disposed` vs `all`, explains irreversibility, requires typed confirmation).
  - Recent audit event timeline (5 most recent events with type, actor, timestamp, and payload summary).
  - "View all audit events" link (stretch goal: paginated audit log).
  - Graceful degradation when backend is unreachable: show "Backend unavailable -- retention status cannot be loaded" with retry affordance.
- [ ] Add retention mode badge to `SyncStatusIndicator`: shows compact retention mode label (e.g., "Retention: Dispose after ack") when mode is not `retain_all`. Links to `RetentionPage`.
- [ ] Add retention summary card to `DashboardPage`: current mode, last export/purge timestamps.
- [ ] Wire `RetentionPage` into the admin routing (new route or workbench overlay panel).
- [ ] Add Vitest tests: retention page renders policy state correctly; policy update calls correct API; export button triggers export with confirmation; purge button requires confirmation and calls correct API with scope; audit timeline renders events; backend-unavailable state shows graceful fallback; retention badge shows in sync indicator when mode is not `retain_all`; pin representative hook calls correct endpoint.

## Phase 8: Integration Tests

- [ ] Backend integration test: create tenant, set retention policy, export data, verify export payload structure, purge with `scope='all'`, verify all machine state deleted, verify audit events recorded for each action.
- [ ] Backend integration test: `dispose_after_ack` mode marks data as disposed after projection acknowledgement; purge with `scope='disposed'` deletes only disposed rows.
- [ ] Backend integration test: snapshot export includes `representative_id` and `representative_is_pinned` for clusters with pinned representatives.
- [ ] PHP integration test: snapshot projection writes `representative_id` and `is_representative_pinned`; pin-representative endpoint creates outbox operation; outbox drain dispatches pin to backend.
- [ ] PHP integration test: retention status endpoint proxies backend policy and caches correctly.
- [ ] Vitest integration test: retention page end-to-end flow with mocked API responses.
- [ ] All backend pytest, PHP PHPUnit/PHPStan, TypeScript type checks, and Vitest/ESLint checks pass.

## Stretch Goals

- [ ] Async/file-based export for large tenants (export returns a job ID, status polled separately, download URL when ready).
- [ ] Paginated full audit event log page with filtering by event type.
- [ ] Scheduled disposal worker that automatically purges disposed state on a configurable interval.
- [ ] Export format versioning and import capability for cross-site migration.
- [ ] Embedding-level disposal tracking (dispose individual identity embeddings vs. entire clusters).
- [ ] Batch pin/unpin representative operations.
- [ ] Retention policy presets (e.g., "GDPR mode" = `dispose_after_ack` + auto-purge after 30 days).

## Success Criteria

- [ ] Operators can read and update the tenant retention policy (`retain_all`, `dispose_after_ack`, `purge_on_demand`) from the admin UI without database access.
- [ ] Operators can trigger a tenant data export that produces a portable JSON payload covering clusters, members, detection metadata, and representative info (no raw embeddings).
- [ ] Operators can trigger a purge of machine-derived state with explicit confirmation, and the system records the action in the audit log.
- [ ] Every retention lifecycle action (policy change, export, purge, disposal) produces an auditable event visible to the operator.
- [ ] Representative `id` and `is_pinned` state survive sync projection and are visible in the local WordPress cluster data.
- [ ] Representative pin/unpin decisions are durable across offline periods via the outbox replay contract.
- [ ] Operators can accept machine state for `cluster_merged` conflicts once moved-member provenance is present, with the revert running transactionally and without partial member reassignment.
- [ ] The retention mode is visible in the sync status area and dashboard so operators understand the data governance posture at a glance.
- [ ] The MVP can credibly claim privacy-minimized retention and auditable handling of machine-derived biometric state.
- [ ] All backend pytest, PHP PHPUnit/PHPStan, TypeScript type checks, and Vitest/ESLint checks pass.

## Out of Scope

- **Full data sovereignty**: customer-controlled embedding authority, ephemeral compute APIs, and sovereignty-tier deployment modes are deferred post-v0.2.0.
- **Delta ingest**: replacing snapshot-heavy sync with richer deltas is tracked in deferred/post-v0.2.0 scope.
- **Region-pinning and encryption**: tenant-level encryption, key-management hooks, and region-pinning compliance features are deferred post-v0.2.0.
- **Backend-authored machine proposals for person names**: proposal generation/storage does not exist yet. Tracked separately from retention controls.
- **Embedding vector export**: raw float32 embedding arrays are excluded from the export payload because they are not portable across model versions. Only derived metadata (cluster assignments, similarity scores, bounding boxes) is exported.
