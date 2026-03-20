# Remaining Sync, Workbench, and Retention

## Problem Statement

The WordPress plugin synchronizes recognition state via full-snapshot pull only, has no incremental delta ingest or drift reconciliation, lacks bidirectional conflict resolution for person-name edits, does not surface machine proposals as first-class entities, and still bundles Batch UI into the Workbench instead of the Dashboard. Additionally, the retention surface is missing stretch capabilities (async export, paginated audit log, scheduled disposal, import/versioning, GDPR presets) and the orchestration pipeline has no worktree lane cleanup tooling.

## Workflow Principles

- **Curation-first precedence.** User curation decisions are ground truth. Delta ingest and drift reconciliation must never silently overwrite curated state; only a verified data delta (new backend evidence since the user's decision) may surface as a new proposal.
- **Disposal after projection acknowledgement.** Machine-derived working state that is no longer needed after WordPress has projected and acknowledged the snapshot is eligible for disposal under explicit tenant policy.
- **Audit before action.** Every retention lifecycle action (retain, export, purge, dispose) must produce an audit event before or atomically with the action.
- **Backend is authority for policy enforcement.** Retention policy, export, purge, and proposal logic live on the backend. WordPress proxies but does not own these decisions.
- **Greenfield schema policy.** No backward-compatibility migrations for dev environments. All schema changes go directly into the baseline migration (`db/migrations/versions/001_identity_schema.py`); `make reset-local` is the recovery path.
- **Contract-first for cross-layer changes.** New API surfaces (delta endpoint, proposal endpoint) must have a contract document in `docs/agentic/contracts/` before implementation begins.

## Terminology

- **Delta ingest**: An incremental sync path where the backend sends only changes since the last acknowledged snapshot version, rather than a full snapshot.
- **Drift reconciliation**: Detection and resolution of divergence between local projection and backend state accumulated during offline periods.
- **Machine proposal**: A backend-generated suggestion (name, merge, assignment) surfaced through the existing `AssignmentSuggestion`/`MergeSuggestion` system with added confidence scoring, expiry, and bulk-accept capability. Extends the existing suggestion domain rather than introducing a parallel entity.
- **Representative pin**: Operator action that locks a specific cluster representative, preventing automatic representative selection from overriding it.
- **Moved-member provenance**: Metadata recording that a member was deliberately moved by operator action (merge acceptance), so future reclustering does not silently undo the curated move.

## Current State Analysis

- Full snapshot sync works end-to-end: `SyncPullJob` -> `SnapshotClient` -> `SnapshotProjector` -> acknowledgement. No delta path exists.
- `OutboxWriter`/`OutboxDrain`/`OutboxDispatcher` handle local-to-backend curation replay for topology operations (`cluster_merged`, `identity_reassigned`, `assign_outlier_to_cluster`, etc.).
- `ConflictResolutionService` supports `accepted`/`dismissed` resolutions for projection conflicts (`curated_cluster_deleted`, `curated_member_deleted`, `member_cluster_reassignment`, `version_conflict`). No person-name bidirectional conflict handling exists.
- `ConflictInbox` UI renders conflict list with resolve actions. Labels hardcoded for current conflict types only.
- `ClusterRepresentative` domain model has `is_user_selected` and `is_provisional` fields; the snapshot contract does not include `representative_id` or `is_pinned`. Backend already exposes `PATCH /clusters/{cluster_id}/representatives/{representative_id}/pin` with `PinRepresentativeRequest`, but `class-cluster-mutations-controller.php` has no matching proxy route and the PHP response mappers (`ClusterResponseMapper`, `MemberResponseMapper`) hardcode `is_pinned` to `false`.
- `WorkbenchPage` now exposes two tabs: `scan` and `confirm`. Stale `?tab=batch` URLs fall back to `scan`.
- `DashboardPage` now includes the Batch Operations entrypoint and latest-job follow-up links.
- `AssignmentSuggestion` and `MergeSuggestion` domain models exist with `PENDING`/`ACCEPTED`/`REJECTED` status lifecycle. SQLAlchemy models live in `db/models/constraints.py` (`IdentitySuggestion` with existing `confidence_score` column; `ClusterMergeSuggestion`); exported from `db/models/__init__.py`. Backend has accept/reject endpoints in `suggestions.py` router. WordPress `SuggestionsController` (in `src/api/class-suggestions-controller.php`) already proxies list/accept/reject for both assignment and merge suggestions (7 routes). Frontend `SuggestionReviewPanel.tsx` renders assignment and merge suggestions with accept/reject actions via React Query mutations. API client functions and TypeScript types for suggestions are complete. Missing: expiry/TTL, bulk-accept, name-suggestion type, and confidence-based filtering in the existing proxy and frontend layers.
- Retention infrastructure delivered: `retention.py` router, `RetentionController` proxy, `RetentionPage.tsx`, audit events, export, purge, policy. Stretch goals not started.
- No `lane-close`, `lane-prune`, or `scripts/worktree-lane close` capability exists. Completed lane worktrees persist until manually removed.

## Proposed Solution

Deliver in 8 phases, with the first two producing foundational contracts and scaffolding, followed by backend/frontend implementation phases that can be parallelized via lane orchestration where dependencies allow.

**Phase 0: Contracts and Scaffolding** -- Write API contracts for the delta ingest endpoint and machine proposal endpoints. Scaffold interfaces and type stubs across all layers.

**Phase 1: Delta Ingest and Drift Reconciliation** -- Add a `GET /tenants/{tenant_uuid}/clusters/delta` endpoint that returns changes since a given `since_version`. Extend `SyncPullJob` and `SnapshotProjector` to consume deltas with snapshot fallback. Implement drift reconciliation that detects and flags unresolvable divergence.

**Phase 2: Topology Completion** -- Extend the snapshot contract and projection schema to include `representative_id` and `is_pinned`. Add a WordPress proxy route for the existing backend pin endpoint, fix response mappers that hardcode `is_pinned` to `false`, and add frontend pin/unpin mutation and UI. Wire pin/unpin through the outbox/replay contract. Add moved-member provenance to `cluster_merged` acceptance.

**Phase 3: Bidirectional Conflict Resolution** -- Extend the conflict record schema to store backend-proposed values. Add person-name conflict type to `ConflictInbox` with accept-backend/keep-local/merge resolution actions. Wire resolution through the outbox contract.

**Phase 4: Workbench Information Architecture** -- Move `BatchTabContent` from Workbench to Dashboard. Remove Batch tab from Workbench (reduce to Scan + Confirm).

**Phase 5: Machine Proposals via Suggestion System Extension** -- Extend the existing `AssignmentSuggestion`/`MergeSuggestion` domain with confidence scoring, expiry TTL, bulk-accept, and a new name-suggestion type. Add a WordPress proxy layer for the backend suggestion endpoints. Enhance the `SuggestionReviewPanel` with confidence display, bulk-accept UI, and name-suggestion review.

**Phase 6: Retention Stretch Goals** -- Async export, paginated audit page, scheduled disposal worker, format versioning/import, embedding-level disposal, GDPR presets.

**Phase 7: Lane Lifecycle Tooling** -- Add `lane-close`, `lane-prune`, `scripts/worktree-lane close` for worktree cleanup tied to MCP lane status.

## Patterns to Follow

### Backend: Delta Endpoint

```python
# In recognition/interface_adapters/http/routers/clusters.py
@router.get(
    "/tenants/{tenant_uuid}/clusters/delta",
    response_model=ClusterDeltaResponse,
)
async def get_tenant_cluster_delta(
    tenant_uuid: str,
    since_version: int = Query(..., ge=0),
    auth=Depends(require_auth),
    repo=Depends(get_cluster_repository),
) -> ClusterDeltaResponse:
    """Return incremental changes since since_version.

    If delta cannot be served safely, return an HTTP error and let
    the caller retry with the full snapshot endpoint.
    """
    ...
```

```python
# Response model
class ClusterDeltaResponse(BaseModel):
    tenant_id: str
    since_version: int
    current_version: int
    snapshot_generation_id: str
    added_clusters: list[ClusterSnapshotClusterResponse]
    removed_cluster_uuids: list[str]
    updated_clusters: list[ClusterSnapshotClusterResponse]
    added_members: list[ClusterSnapshotMemberResponse]
    removed_member_uuids: list[str]
    updated_members: list[ClusterSnapshotMemberResponse]
```

### PHP: Delta-Aware Sync Pull

```php
// In SyncPullJob::perform()
// 1. Read last_snapshot_version from SyncStateRepository
// 2. If version exists, try delta endpoint first
// 3. If delta returns an HTTP error, fall back to full snapshot
// 4. Apply delta via SnapshotProjector::project_delta() or full via project()

$last_version = $this->sync_state->get_last_snapshot_version( $tenant_id );
if ( $last_version > 0 ) {
    $delta = $this->snapshot_client->fetch_delta( $tenant_id, $last_version );
    if ( $delta ) {
        $this->projector->project_delta( $tenant_id, $delta );
        return;
    }
}
// Fall back to full snapshot
$snapshot = $this->snapshot_client->fetch_snapshot( $tenant_id );
$this->projector->project( $tenant_id, $snapshot );
```

### Backend: Suggestion System Extension for Machine Proposals

```python
# Extend existing domain models in recognition/domain/suggestion.py

# Add to AssignmentSuggestion dataclass:
#   confidence_score: float | None = None  # maps to confidence_score in IdentitySuggestion model
#   expires_at: datetime | None = None
#   source_job_id: uuid.UUID | None = None

# Add to MergeSuggestion dataclass:
#   confidence_score: float | None = None  # maps to confidence_score in ClusterMergeSuggestion model
#   expires_at: datetime | None = None
#   source_job_id: uuid.UUID | None = None

# Add new NameSuggestion dataclass:
@dataclass
class NameSuggestion:
    id: uuid.UUID
    cluster_id: uuid.UUID
    suggested_name: str
    confidence_score: float | None
    source: SuggestedLabelSource
    status: SuggestionStatus  # reuse existing enum
    source_job_id: uuid.UUID | None
    created_at: datetime
    expires_at: datetime | None
    resolved_at: datetime | None
```

```python
# Extend existing router in recognition/interface_adapters/http/routers/suggestions.py

@router.get("/name")
async def list_pending_name_suggestions(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> NameSuggestionListResponse:
    """List pending name suggestions, optionally filtered by confidence."""
    ...

@router.post("/name/{suggestion_id}/accept")
async def accept_name_suggestion(...) -> SuggestionActionResponse:
    """Accept a name suggestion and apply the label."""
    ...

@router.post("/name/{suggestion_id}/reject")
async def reject_name_suggestion(...) -> SuggestionActionResponse:
    """Reject a name suggestion."""
    ...

@router.post("/bulk-accept")
async def bulk_accept_suggestions(
    request: BulkAcceptRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
) -> BulkAcceptResponse:
    """Accept multiple suggestions above a confidence threshold."""
    ...
```

### PHP: Conflict Record with Backend-Proposed Value

```php
// Extend wp_acx_sync_conflicts schema
// Add column: backend_proposed_value TEXT NULL
// ConflictResolutionService gains a third resolution for bidirectional conflicts:
//   'accept_backend' -- apply backend-proposed value, clear local curation
//   'keep_local'     -- preserve local curated value, discard backend proposal
//   'merge'          -- apply a merged value (for text fields like person name)
```

### Frontend: Suggestion Extension Types

```typescript
// Extend existing js/admin/api/recognition/types/suggestion.ts

// Add to PendingSuggestion (confidence_score already exists; add only new fields):
//   expires_at: string | null;
//   source_job_id: string | null;

// Add to PendingMergeSuggestion:
//   confidence_score: number | null;
//   expires_at: string | null;

// New type:
export interface PendingNameSuggestion {
  id: string;
  cluster_id: string;
  suggested_name: string;
  confidence_score: number | null;
  source: string;
  created_at: string;
  expires_at: string | null;
}

export interface BulkAcceptRequest {
  suggestion_type: "assignment" | "merge" | "name";
  min_confidence: number;
}

export interface BulkAcceptResponse {
  accepted_count: number;
  skipped_count: number;
}
```

### Shell: Lane Close Subcommand

```bash
# In scripts/worktree-lane -- new "close" subcommand
# Usage: scripts/worktree-lane close --task <task-ref> --lane <lane-id>
#
# Steps:
#   1. Query MCP lane status; require merged or closed
#   2. Check git status in worktree; refuse if dirty (unless --force)
#   3. git worktree remove <worktree_path>
#   4. git branch -d <branch> (or -D with --force)
#   5. upsert_worktree_lane status=closed via agent-handoff-mcp
#   6. record_decision noting cleanup
```

## Functions to Change

### Phase 0: Contracts and Scaffolding

| File                                                                                             | Change                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `docs/agentic/contracts/cluster-delta-api.md`                                                    | New contract. Define `GET /tenants/{tenant_uuid}/clusters/delta` request/response, HTTP fallback semantics, and delta chain integrity.                                                                 |
| `docs/agentic/contracts/suggestion-extensions-api.md`                                            | New contract. Define suggestion system extensions: name-suggestion endpoints, confidence filtering, bulk-accept, expiry semantics, and acceptance side effects. Extends existing suggestions contract. |
| `apps/prototype-description-service/recognition/domain/repositories.py`                          | Add `ClusterRepositoryProtocol.get_delta()` method stub.                                                                                                                                               |
| `apps/prototype-description-service/recognition/domain/services/suggestion_extension_service.py` | New file. Stub `SuggestionExtensionService` with `list_name_suggestions()`, `accept_name_suggestion()`, `reject_name_suggestion()`, `bulk_accept()`, `expire_stale()`.                                 |
| `apps/prototype-wp-alt-context/src/sovereign/sync/interface-snapshot-client.php`                 | Add `fetch_delta( $tenant_id, $since_version )` method to interface.                                                                                                                                   |
| `apps/prototype-wp-alt-context/src/sovereign/sync/interface-snapshot-projector.php`              | Add `project_delta( $tenant_id, $delta )` method to interface.                                                                                                                                         |

### Phase 1: Delta Ingest and Drift Reconciliation

| File                                                                                               | Change                                                                                                     |
| -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py`       | Add `get_tenant_cluster_delta()` endpoint with `since_version` query param.                                |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | Implement `get_delta(tenant_id, since_version)` querying changes since version.                            |
| `apps/prototype-description-service/db/models/identity.py`                                         | Add `version` or `updated_at` index for efficient delta queries if not present.                            |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-client.php`                       | Add `fetch_delta()` method calling backend delta endpoint.                                                 |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-client-transport.php`             | Add transport for delta endpoint.                                                                          |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php`                    | Add `project_delta()` method applying incremental adds/removes/updates within a transaction; detect drift. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php`                         | Modify `perform()` to try delta first, fall back to full snapshot on HTTP failure or projection rejection. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-resolution-service.php`           | Add drift conflict type handling for unresolvable divergence.                                              |

### Phase 2: Topology Completion

| File                                                                                               | Change                                                                                                        |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py`       | Extend `ClusterSnapshotClusterResponse` with `representative_id` and `is_pinned`.                             |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | Include representative `id` and `is_user_selected` in snapshot query.                                         |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php`                    | Project `representative_id` and `is_pinned` into `wp_acx_clusters` (add columns if needed).                   |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php`                         | Add `representative_pinned` / `representative_unpinned` operation types.                                      |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php`                     | Route pin/unpin operations to backend pin endpoint.                                                           |
| `apps/prototype-description-service/recognition/domain/cluster.py`                                 | Add `moved_member_provenance` tracking to merge acceptance logic.                                             |
| `apps/prototype-description-service/db/models/identity.py`                                         | Add `moved_by_merge_id` or similar provenance column to `MediaIdentity`.                                      |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`                     | Add `PATCH /recognition/clusters/{cluster_id}/representatives/{representative_id}/pin` proxy route.           |
| `apps/prototype-wp-alt-context/src/sovereign/mappers/class-cluster-response-mapper.php`            | Fix `map_top_unlabeled_representative()` to read `is_pinned` from backend data instead of hardcoding `false`. |
| `apps/prototype-wp-alt-context/src/sovereign/mappers/class-member-response-mapper.php`             | Fix `map_cluster_identity()` to read `is_pinned` from backend data instead of hardcoding `false`.             |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/identityActionsApi.ts`                     | Add `pinRepresentative(clusterId, representativeId, isPinned)` API function.                                  |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/`                        | Add pin/unpin toggle UI to cluster representative display.                                                    |

### Phase 3: Bidirectional Conflict Resolution

| File                                                                                     | Change                                                                                                 |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-resolution-service.php` | Add `accept_backend` and `merge` resolution types. Handle person-name conflict application.            |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-repository.php`         | Add `backend_proposed_value` column support in queries.                                                |
| `apps/prototype-wp-alt-context/src/api/class-conflict-controller.php`                    | Expose `backend_proposed_value` in conflict detail response. Accept new resolution types.              |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/ConflictInbox.tsx`               | Add person-name conflict type label and three-way resolution UI (accept backend / keep local / merge). |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/conflicts.ts`              | Add `backend_proposed_value` field and new resolution types to TypeScript types.                       |

### Phase 4: Workbench Information Architecture

| File                                                                         | Change                                                                                                           |
| ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx`             | Import and render `BatchPanel` + `RecentJobsPanel` in a new Dashboard section.                                   |
| `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`             | Remove `batch` from `TAB_IDS`. Remove `BatchTabContent` import and rendering.                                    |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/BatchTabContent.tsx` | May need adapter changes for Dashboard context (replace `useWorkbenchContext` if Dashboard does not provide it). |

### Phase 5: Machine Proposals via Suggestion Extension

| File                                                                                                 | Change                                                                                                                                                                                                                                                     |
| ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/recognition/domain/suggestion.py`                                | Add `confidence_score`, `expires_at`, `source_job_id` fields to `AssignmentSuggestion` and `MergeSuggestion`. Add `NameSuggestion` dataclass.                                                                                                              |
| `apps/prototype-description-service/db/models/constraints.py`                                        | Add `expires_at`, `source_job_id` columns to `IdentitySuggestion` and `ClusterMergeSuggestion` (`confidence_score` already exists on `IdentitySuggestion`; add to `ClusterMergeSuggestion`). Add `NameSuggestion` model using existing suggestion pattern. |
| `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`                   | Baseline migration update: add `expires_at`, `source_job_id` columns to `identity_suggestions` and `cluster_merge_suggestions`; add `confidence_score` to `cluster_merge_suggestions`; add `name_suggestions` table. Reset with `make reset-local`.        |
| `apps/prototype-description-service/recognition/domain/services/suggestion_extension_service.py`     | Implement `SuggestionExtensionService` with `list_name_suggestions()`, `accept_name_suggestion()`, `reject_name_suggestion()`, `bulk_accept()`, `expire_stale()`.                                                                                          |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/suggestions.py`      | Add name-suggestion list/accept/reject endpoints. Add `bulk-accept` endpoint. Add `min_confidence` filter to existing list endpoints.                                                                                                                      |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py`        | Add `NameSuggestionResponse`, `BulkAcceptResponse`. Extend `SuggestionResponse` with `confidence_score`, `expires_at`.                                                                                                                                     |
| `apps/prototype-wp-alt-context/src/api/class-suggestions-controller.php`                             | Extend existing `SuggestionsController` with name-suggestion list/accept/reject proxy routes, bulk-accept proxy route, and `min_confidence` query param forwarding.                                                                                        |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/suggestion.ts`                         | Add `expires_at`, `source_job_id` to `PendingSuggestion` (already has `confidence_score`). Add `confidence_score`, `expires_at` to `PendingMergeSuggestion`. Add `PendingNameSuggestion`, `BulkAcceptRequest`, `BulkAcceptResponse`.                       |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/identityQueriesApi.ts`                       | Add `fetchPendingNameSuggestions()`, `bulkAcceptSuggestions()`.                                                                                                                                                                                            |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx` | Add confidence display, name-suggestion review section, bulk-accept action with confidence threshold slider.                                                                                                                                               |

### Phase 6: Retention Stretch Goals

| File                                                                                          | Change                                                                                                                                                                                                               |
| --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/db/models/jobs.py`                                        | Add `ExportJob` model reusing existing job pattern (`IdentityClusteringJob`): id, tenant_id, status (pending/running/completed/failed), output_path, file_size, error_message, created_at, started_at, completed_at. |
| `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`            | Baseline migration update: add `export_jobs` table. Reset with `make reset-local`.                                                                                                                                   |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py` | Replace sync export with async: `POST /retention/export` returns `{job_id}`. Add `GET /retention/export/{job_id}/status` for polling. Add `GET /retention/export/{job_id}/download` for file retrieval.              |
| `apps/prototype-description-service/recognition/domain/services/export_service.py`            | Add `start_async_export()` (creates ExportJob, returns job_id), `get_export_status()`, file-based export for large tenants, format versioning with `schema_version` header.                                          |
| `apps/prototype-description-service/recognition/domain/services/purge_service.py`             | Add scheduled disposal worker entry point.                                                                                                                                                                           |
| `apps/prototype-description-service/recognition/domain/services/retention_policy_service.py`  | Add preset policies (GDPR mode, etc.).                                                                                                                                                                               |
| `apps/prototype-description-service/recognition/domain/services/import_service.py`            | New file. Import/restore from versioned export file with validation.                                                                                                                                                 |
| `apps/prototype-description-service/db/models/identity.py`                                    | Add embedding-level `disposed_at` if not already at the right granularity.                                                                                                                                           |
| `apps/prototype-wp-alt-context/src/api/class-retention-controller.php`                        | Add proxy routes: `GET /retention/export/{job_id}/status`, `GET /retention/export/{job_id}/download`, `POST /retention/import`. Update `POST /retention/export` to return job ID.                                    |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/retentionApi.ts`                      | Add `getExportJobStatus()`, `downloadExport()`, `importTenantData()` API functions.                                                                                                                                  |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/retention.ts`                   | Add `ExportJobResponse` (job_id, status, progress, download_url), `ImportRequest`, `ImportResponse` types.                                                                                                           |
| `apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx`                              | Add export job polling UI with progress indicator, download button, paginated audit log tab, import UI, preset selector.                                                                                             |

### Phase 7: Lane Lifecycle Tooling

| File                                                       | Change                                                                        |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `scripts/worktree-lane`                                    | Add `close` subcommand (worktree remove + branch delete + MCP status update). |
| `mk/lane-maintenance.mk`                                   | Add `lane-close` and `lane-prune` targets.                                    |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Optionally add `close_worktree_lane` tool.                                    |

## Related Files

| File                                                                                      | Note                                                                                           |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `docs/agentic/contracts/cluster-snapshot-api.md`                                          | Existing snapshot contract; delta contract extends this.                                       |
| `docs/agentic/contracts/curation-sync-api.md`                                             | Existing curation replay contract; bidirectional conflict resolution extends this.             |
| `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json`              | Machine-readable snapshot schema; needs delta variant.                                         |
| `apps/prototype-description-service/recognition/config/settings.py`                       | May need new settings for delta staleness threshold, proposal expiry, disposal schedule.       |
| `apps/prototype-description-service/recognition/config/security.py`                       | Auth patterns for new endpoints.                                                               |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-cross-plane-sequencer.php`        | May need awareness of delta vs snapshot projection mode.                                       |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-split-topology-command-drain.php` | Topology command drain for compound operations; verify compatibility with provenance tracking. |

## Lane Decomposition (Multi-Agent)

This task spans all four standard lanes. Phases 1-3 and 5-6 have strong backend-to-frontend dependency chains. Phase 4 (Workbench IA) and Phase 7 (Lane Tooling) can proceed independently.

### Lanes

| Lane ID          | Owned Paths                                                                                                                                                                                                                                | Upstream Dependencies          | Required Tests                                                     |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------ | ------------------------------------------------------------------ |
| `backend-domain` | `apps/prototype-description-service/db/**`, `apps/prototype-description-service/recognition/domain/**`, `apps/prototype-description-service/recognition/infrastructure/**`, `apps/prototype-description-service/recognition/tests/unit/**` | None                           | `PYENV_VERSION=description-service pytest recognition/tests/unit/` |
| `backend-http`   | `apps/prototype-description-service/recognition/interface_adapters/http/**`                                                                                                                                                                | `backend-domain`               | `PYENV_VERSION=description-service pytest recognition/tests/unit/` |
| `wp-proxy`       | `apps/prototype-wp-alt-context/src/**`, `apps/prototype-wp-alt-context/tests/Unit/**`                                                                                                                                                      | `backend-http` (contract only) | `cd apps/prototype-wp-alt-context && composer phpunit`             |
| `frontend`       | `apps/prototype-wp-alt-context/js/**`                                                                                                                                                                                                      | `wp-proxy` (contract only)     | `cd apps/prototype-wp-alt-context && npm run test -- --run`        |

### Merge Order

1. `backend-domain` (models, repositories, services, domain tests)
2. `backend-http` (routers, HTTP-layer tests)
3. `wp-proxy` (PHP controllers, sync layer, PHP unit tests)
4. `frontend` (React pages, hooks, TypeScript tests)

### Manifest

```bash
make lane-manifest-init TASK=remaining-sync-workbench-and-retention LANE_IDS='backend-domain backend-http wp-proxy frontend' TASK_PLAN=docs/tasks/7.0/remaining-sync-workbench-and-retention-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools (`worker_start_all`, `worker_status`, `worker_stop`) with `backend="codex-subagent"`. The orchestrator daemon dispatches work, intakes merge-ready lanes, and refreshes downstream dependents automatically.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and `make lane-intake` from the orchestrator root.

### Parallelization Notes

- Phase 4 (Workbench IA) is frontend-only and can run in parallel with Phases 1-3 backend work.
- Phase 7 (Lane Tooling) is orchestration-only and can run anytime.
- Phases 1-3 are sequential within the backend domain/http lanes; the wp-proxy and frontend lanes for each phase can start as soon as the backend contract is stable.
- Phase 5 (Machine Proposals) backend work can start in parallel with Phase 3 frontend work since the proposal model is independent of conflict resolution code.
- Phase 6 (Retention Stretch) is independent of Phases 1-5 and can run in any lane slot.

---

# Consolidated Checklist

## Phase 0: Contracts and Scaffolding

- [x] Write `docs/agentic/contracts/cluster-delta-api.md` (delta endpoint contract).
- [x] Write `docs/agentic/contracts/suggestion-extensions-api.md` (name-suggestion, confidence filtering, bulk-accept, expiry contract).
- [x] Add `get_delta()` stub to `ClusterRepositoryProtocol`. **Note**: return type reuses snapshot shape; Phase 1 will need a categorized `ClusterDeltaResult` return type (see RSWR-IMPL-001).
- [x] Add `SuggestionExtensionService` stub in `suggestion_extension_service.py` with `NotImplementedError` methods.
- [x] Add `fetch_delta()` to `SnapshotClientInterface` (PHP).
- [x] Add `project_delta()` to `SnapshotProjectorInterface` (PHP).
- [x] Add `PendingNameSuggestion`, `BulkAcceptRequest`, `BulkAcceptResponse` TypeScript type stubs to existing `suggestion.ts`.
- [x] Verify scaffolds compile: `mypy .` / `npm run typecheck` / `composer phpstan`.

## Phase 1: Delta Ingest and Drift Reconciliation

- [x] Implement `get_delta()` in cluster repository (query changes since version).
- [x] Add `get_tenant_cluster_delta` HTTP endpoint in clusters router.
- [x] Implement `fetch_delta()` in `SnapshotClient` (PHP).
- [x] Implement `project_delta()` in `SnapshotProjector` (PHP; adds/removes/updates within transaction). _(Implemented via guarded tenant-wide replacement-set synthesis from unchanged local rows plus changed-cluster delta rows.)_
- [x] Modify `SyncPullJob::perform()` to try delta first, fall back to full snapshot.
- [ ] Add drift conflict type to `ConflictResolutionService` for unresolvable divergence.
- [x] Backend unit tests: delta query with version gap, empty delta, broken chain fallback. _(5 integration tests cover version gap, empty delta, microsecond boundaries, disposed clusters; broken-chain fallback deferred to PHP integration.)_
- [ ] PHP unit tests: delta projection, drift detection, fallback to full snapshot. _(Delta projection + fallback coverage landed; drift-detection coverage still pending.)_
- [ ] Frontend: update sync status display to show delta vs full sync mode.

## Phase 2: Topology Completion

- [x] Extend `ClusterSnapshotClusterResponse` with `representative_id` and `is_pinned`.
- [x] Include representative `id` and `is_user_selected` in backend snapshot query.
- [x] Add `representative_id` and `is_pinned` columns to `wp_acx_clusters` (PHP migration).
- [x] Extend `SnapshotProjector` to project representative pin state. _(Projection now persists representative metadata through the existing cluster merge path.)_
- [x] Add unified `representative_pin_updated` replay operation in `OutboxWriter`.
- [x] Route pin/unpin operations in `OutboxDispatcher` to backend endpoint.
- [x] Add `moved_by_merge_id` provenance column to `MediaIdentity` (baseline migration update; `make reset-local`).
- [x] Implement moved-member provenance recording in merge acceptance logic.
- [x] Add proxy route `PATCH /recognition/clusters/{cluster_id}/representatives/{representative_id}/pin` in `class-cluster-mutations-controller.php`.
- [x] Fix `ClusterResponseMapper::map_top_unlabeled_representative()` to read `is_pinned` from backend data.
- [x] Fix `MemberResponseMapper::map_cluster_identity()` to read `is_pinned` from backend data.
- [x] Add `pinRepresentative()` API function and React Query mutation hook.
- [x] Add pin/unpin toggle UI to cluster representative display.
- [x] Backend unit tests: snapshot includes representative metadata, provenance recorded on merge. _(Snapshot representative metadata and merge provenance coverage are both landed.)_
- [x] PHP unit tests: pin state projected, pin/unpin round-trip through outbox, proxy route returns 204. _(Implementation is now local-first with 200/pending semantics instead of direct 204 proxying; projection and outbox replay coverage landed.)_
- [x] Frontend tests: pin/unpin toggle calls mutation and updates cache.

## Phase 3: Bidirectional Conflict Resolution

- [x] Add `backend_proposed_value` column to `wp_acx_sync_conflicts` table.
- [ ] Add `person_name_conflict` conflict type to projection conflict detection.
- [ ] Add `accept_backend` and `merge` resolution types to `ConflictResolutionService`.
- [x] Expose `backend_proposed_value` in `ConflictController` detail response. _(Also included in list payloads via shared conflict mapping.)_
- [ ] Add person-name conflict type label to `ConflictInbox` UI.
- [ ] Add three-way resolution UI: accept backend / keep local / merge value.
- [ ] Wire merged-value resolution through outbox contract (replay merged name to backend).
- [ ] PHP unit tests: bidirectional conflict creation, all three resolution paths.
- [ ] Frontend tests: conflict inbox renders person-name conflicts with resolution actions.

## Phase 4: Workbench Information Architecture

- [x] Extract `BatchTabContent` dependencies so it works outside `WorkbenchProvider` context. _(The temporary redirect view landed first; final implementation removes the Workbench batch tab entirely.)_
- [x] Add Batch section to `DashboardPage` with `BatchPanel` + `RecentJobsPanel`. _(Implemented as inline Batch Operations section with latest-job follow-up rendering; BatchPanel not used since dashboard lacks media selection context.)_
- [x] Remove `batch` from `TAB_IDS` in `WorkbenchPage`.
- [x] Remove `BatchTabContent` import and rendering from `WorkbenchPage`.
- [x] Frontend tests: verify Batch renders on Dashboard, verify Workbench has only scan + confirm.

## Phase 5: Machine Proposals via Suggestion Extension

- [ ] Add `confidence_score` (where missing; `IdentitySuggestion` already has it), `expires_at`, `source_job_id` fields to `AssignmentSuggestion` and `MergeSuggestion` domain models.
- [ ] Add `NameSuggestion` dataclass to `recognition/domain/suggestion.py`.
- [ ] Add `expires_at`, `source_job_id` columns to existing suggestion tables in `db/models/constraints.py`; add `confidence_score` to `ClusterMergeSuggestion` (already exists on `IdentitySuggestion`). Add `NameSuggestion` model. Update baseline migration (`001_identity_schema.py`); `make reset-local`.
- [ ] Implement `SuggestionExtensionService` with name-suggestion CRUD, bulk-accept, and expiry logic.
- [ ] Implement acceptance side effects (apply name label to cluster on name-suggestion accept).
- [ ] Add name-suggestion list/accept/reject endpoints and `bulk-accept` endpoint to suggestions router.
- [ ] Add `min_confidence` query filter to existing suggestion list endpoints.
- [ ] Extend existing `SuggestionsController` in `class-suggestions-controller.php` with name-suggestion and bulk-accept proxy routes.
- [ ] Extend existing suggestion TypeScript types: add `expires_at`, `source_job_id` to `PendingSuggestion` (already has `confidence_score`); add `confidence_score`, `expires_at` to `PendingMergeSuggestion`. Add name-suggestion and bulk-accept types.
- [ ] Add confidence display, name-suggestion review section, and bulk-accept UI to `SuggestionReviewPanel`.
- [ ] Backend unit tests: name-suggestion lifecycle, bulk-accept above threshold, expiry.
- [ ] PHP unit tests: suggestion controller extension routes (name-suggestion, bulk-accept).
- [ ] Frontend tests: confidence display, name-suggestion review, bulk-accept action.

## Phase 6: Retention Stretch Goals

- [ ] Create `ExportJob` model in `db/models/jobs.py` (reuse existing job pattern: status, output_path, timestamps).
- [ ] Add `export_jobs` table to baseline migration (`001_identity_schema.py`); `make reset-local`.
- [ ] Implement `start_async_export()` in export service: create ExportJob record, return job_id, run export in background.
- [ ] Implement `get_export_status()` to query ExportJob state for polling.
- [ ] Add `GET /retention/export/{job_id}/status` polling endpoint.
- [ ] Add `GET /retention/export/{job_id}/download` file retrieval endpoint.
- [ ] Modify `POST /retention/export` to return `{job_id}` and run async; keep sync fallback for small exports if needed.
- [ ] File-based export for large tenants with streaming writes.
- [ ] Export format versioning: `schema_version` header in export JSON.
- [ ] Import service: validate version, restore tenant state from export file.
- [ ] Add `POST /retention/import` endpoint.
- [ ] Paginated full audit event log page with type and date-range filtering.
- [ ] Scheduled disposal worker: cron/scheduler entry point that auto-purges on configured interval.
- [ ] Embedding-level disposal tracking: per-embedding `disposed_at` (if coarser than per-identity).
- [ ] Retention policy presets: "GDPR mode" preset that sets `dispose_after_ack` + auto-purge schedule.
- [ ] PHP proxy: `GET /retention/export/{job_id}/status`, `GET /retention/export/{job_id}/download`, `POST /retention/import` routes.
- [ ] Frontend: export job polling with progress indicator, download button when complete.
- [ ] Frontend: paginated audit log tab on RetentionPage, import UI, preset selector.
- [ ] Backend unit tests: export job lifecycle (start, poll, download, failed), import validation.
- [ ] PHP unit tests: export status/download/import proxy routes.
- [ ] Frontend tests: export polling UI, download action, import form.

## Phase 7: Lane Lifecycle Tooling

- [ ] Add `close` subcommand to `scripts/worktree-lane` (remove worktree + delete branch + MCP status update).
- [ ] Add `lane-close` Makefile target with merged/closed status guard and dirty-state check.
- [ ] Add `lane-prune` Makefile target for batch cleanup of all merged/closed lanes + `git worktree prune`.
- [ ] Optionally add `close_worktree_lane` MCP tool in `agent-handoff-mcp`.
- [ ] Optionally integrate auto-close into orchestrator daemon post-intake path.

## Success Criteria

- [ ] Delta sync completes successfully when backend has incremental changes; falls back to full snapshot on stale delta.
- [ ] Operator can pin/unpin a cluster representative and see the pin survive a sync round-trip.
- [ ] Person-name conflict from backend surfaces in ConflictInbox with accept-backend/keep-local/merge options; each resolution path works.
- [ ] Batch tab appears on Dashboard (not Workbench); Workbench shows only Scan + Confirm.
- [ ] Name suggestions created by backend appear in `SuggestionReviewPanel`; operator can accept or reject; accepted name suggestions apply the label. Bulk-accept above a confidence threshold works for all suggestion types.
- [ ] Large-tenant export triggers an async job returning a job ID; status polling shows progress; completed export produces a downloadable file. Import validates schema version and restores state. Paginated audit log renders all events.
- [ ] `make lane-close` removes a merged worktree, deletes the branch, and transitions the MCP lane record to `closed`.
