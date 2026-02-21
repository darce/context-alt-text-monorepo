# WordPress Sovereign Cluster Architecture (v0.1.0)

## Objective

Make the WordPress plugin self-sufficient for cluster display and curation after clusters are computed, even when the recognition backend is unavailable.

## Problem Statement

Current architecture is proxy-first:

- Plugin routes under `acx/v1/recognition/*` proxy to FastAPI through a decomposed controller suite (composition root + 5 sub-controllers).
- Cluster reads and writes depend on live backend connectivity.
- If backend service is disconnected or subscription ends, cluster UI appears empty.

This creates perceived data loss, reduced product trust, and brittleness from synchronous cross-service dependency.

## UX Vision

Deliver an Apple Photos-style assisted labeling flow:

- System forms clusters around visually similar, unknown faces.
- User confirms an identity label on a cluster, which cascades to every face inside it.
- Users can refine clusters by selecting/deselecting thumbnails or moving misgrouped faces.
- High-confidence suggestions surface first; borderline matches deferred for user review.

Guiding principles: accuracy over volume, explicit user control (no auto-labeling without confirmation), resource awareness, progressive disclosure.

## Constraints

- **Greenfield policy** -- no production users, no existing data to preserve. Clean rewrites over shims. No long-lived feature flags.
- **Backend schema baseline** -- changes fold into `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`.
- **Snapshot endpoint does not exist** -- `GET /tenants/{tenant_uuid}/clusters/snapshot` is a parallel backend workstream.
- **WP-Cron for v0.1.0** -- Action Scheduler deferred to v0.2+.
- **Plugin packaging** -- sovereign code must ship in standalone plugin ZIP per the portable packaging plan.

## Terminology

- **Local projection**: plugin-owned MySQL tables (`wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`) that mirror backend cluster state.
- **Snapshot**: full cluster state for a tenant with a monotonic version. Primary sync mechanism for v0.1.0.
- **Curation**: user actions (label, confirm, dismiss, merge, split, reassign) that are authoritative ground truth.
- **Proxy-first**: current pattern where REST handlers forward requests to the backend and return the response directly.
- **Sovereign**: target pattern where REST handlers read local projection first and sync with backend asynchronously.

## Target Architecture

### Design Decisions

| Decision                                       | Rationale                                                                                                    |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| No `acx_identity_cluster` taxonomy             | Clusters are computed groupings that change with re-clustering; taxonomy overhead adds no value.             |
| Plugin-owned tables via `dbDelta`              | Multiple faces per attachment cannot be modeled with post-meta.                                              |
| Pull-first sync (v0.1.0)                       | Simplest viable sync. No outbox, no operation IDs, no dead-letter.                                           |
| WP-Cron for v0.1.0, Action Scheduler for v0.2+ | WP-Cron has zero dependencies and is sufficient for eventual consistency.                                    |
| Curation-first conflict policy                 | User curation wins unconditionally. Snapshot pull skips curated fields. Backend suggestions never overwrite. |

### North-Star Behavior

1. **Sovereign local read model** -- UI reads local projection at all times. Backend is compute/sync peer, not runtime dependency.
2. **Curation-first conflict policy** -- precedence: user curation > operator actions > backend suggestions.
3. **Pull-first sync** -- plugin pulls snapshots on demand or schedule. Curation writes go to backend via proxy AND cache locally. No outbox yet.
4. **Degraded/offline-first** -- cluster listing/detail render from local store during backend outage. Admin sees sync status, not empty state.

### Data Model (WordPress)

**Plugin-owned tables (v0.1.0)**:

- `wp_acx_clusters` -- `cluster_uuid` (pk), `tenant_id`, `label`, `curation_state`, `representative_thumb_path`, `identity_count`, `snapshot_version`, `is_user_confirmed`, `created_at`, `updated_at`, `last_synced_at`
- `wp_acx_identity_members` -- `identity_uuid` (pk), `cluster_uuid` (fk), `attachment_id`, `bbox_json`, `thumb_path`, `similarity`, `created_at`, `updated_at`
- `wp_acx_sync_state` -- `stream_name` (pk), `last_snapshot_version`, `updated_at`

**Deferred to v0.2+ (outbox pattern)**: `wp_acx_cluster_operations` with operation IDs, status tracking, retry/backoff.

### API Evolution

- **v0.1.0**: `GET /tenants/{tenant_uuid}/clusters/snapshot` (full cluster state with monotonic version)
- **v0.2+**: Delta/event endpoint, idempotent mutation ingest, conflict metadata

## Phased Delivery

### Phase 1: Scaffolding and Local Projection Foundation -- COMPLETED

> **Status**: completed
> **Task plans**: [wp-plugin-portable-packaging-plan.md](../../tasks/4.0/4.13.1/wp-plugin-portable-packaging-plan.md), [wp-sovereign-phase1-local-projection-task-plan.md](../../tasks/4.0/4.13.1/wp-sovereign-phase1-local-projection-task-plan.md)
> **Audits**: [packaging-plan-implementation-audit.md](../../tasks/4.0/4.13.1/packaging-plan-implementation-audit.md), [sovereign-phase1-branch-audit-findings.md](../../tasks/4.0/4.13.1/sovereign-phase1-branch-audit-findings.md)

**Goal**: Create local tables, repository layer, and snapshot projector so cluster data can be stored and ingested into WordPress-owned tables.

Deliverables:

- Portable versioned plugin packaging (ZIP artifact, prefix consolidation, endpoint hardening).
- `dbDelta()` schema creation for all three projection tables.
- Cluster/member/sync-state repository classes with curation-safe merge semantics.
- Snapshot projector with transaction boundary and fixture-based tests.
- Snapshot API contract documented at `docs/agentic/contracts/cluster-snapshot-api.md`.
- All audit findings (H-1, M-1 through M-5, L-1 through L-4) resolved.

Exit criteria:

- Activating the plugin creates all three projection tables idempotently.
- Fixture snapshot ingestion populates local tables and preserves curated state on re-ingestion.

### Phase 2: Read-Path Flip (Offline First) -- COMPLETED

> **Status**: completed
> **Task plans**: [wp-sovereign-phase2-read-path-flip-task-plan.md](../../tasks/4.0/4.13.1/wp-sovereign-phase2-read-path-flip-task-plan.md)

**Goal**: Plugin reads local projection first; backend becomes optional for cluster views.

Deliverables:

- Refactor plugin REST handlers (`ClustersController`, `ClusterMutationsController`, `MediaIdentitiesController`) to read local projection first.
- Remove proxy-first read dependency for cluster views.
- UI surfaces explicit sync status and stale age.

Exit criteria:

- Disabling backend connectivity no longer removes existing cluster UI data.

### Phase 3: Local-First Writes and Pull Sync -- COMPLETED

> **Status**: completed
> **Task plans**: [wp-sovereign-phase3-dual-write-task-plan.md](../../tasks/4.0/4.13.1/wp-sovereign-phase3-dual-write-task-plan.md)

**Goal**: Curation actions persist locally even during backend outage; on-demand sync keeps projection current.

Deliverables:

- User curation actions write to local state AND forward to backend via existing proxy (dual-write, no outbox).
- On-demand sync pull on read path stale-check (`SyncPullJob`), with bootstrap sync strategy for first projection seed.
- If backend is unreachable during curation write, local state is persisted; sync reconciliation occurs on the next user-triggered sync path.

Exit criteria:

- User actions are durable locally.
- User-triggered sync keeps local projection current when backend is available.

### Phase 4: Remove Hard Runtime Dependency -- NOT STARTED

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Backend becomes compute/sync peer only; cluster UX is fully sovereign.

Deliverables:

- Replace runtime proxy dependency for cluster reads with local service facade.
- Keep backend integration as sync/compute pipeline, not blocking UI.
- Update architecture diagrams and contracts to final sovereign model.
- Remove obsolete `thumbnail_url` persistence pipeline (backend DB column, domain objects, response schemas, repository reads, `ThumbnailSettings` config, `StaticFiles` mount).
- Simplify plugin thumbnail resolution: remove dead `is_http_url()` branch in `resolve_thumb_url()`, remove `thumbnail_url` proxy-response fallback in `ClustersController`, consider replacing `thumb_path` / `representative_thumb_path` `acx://` URI indirection with direct `attachment_id` usage.
- Clean up frontend: remove never-populated `thumbnail_url` fields from TS types, remove dead fast-path in `IdentityThumbnail`, collapse dual `thumb_url`/`thumbnail_url` on cluster representative types.

Note: Thumbnails are derived at render time from `bbox_json` + WordPress media attachment URLs via CSS cropping (`FaceThumbnail` component). No thumbnail images are persisted. The `acx://` URI scheme is an indirection layer encoding `attachment_id`, which is already stored directly on `wp_acx_identity_members`.

Exit criteria:

- Plugin is operational for cluster browsing/curation during backend outage and after service disconnect.
- No dead `thumbnail_url` columns, config classes, static-file mounts, or always-null response fields remain in backend or plugin.

## External Dependencies

| Dependency                                                     | Owner              | Status          | Blocks                                        |
| -------------------------------------------------------------- | ------------------ | --------------- | --------------------------------------------- |
| Snapshot endpoint `GET /tenants/{tenant_uuid}/clusters/snapshot` | Backend workstream | **Completed** | Unblocked |
| Persistent event store for delta/event endpoint                | Backend workstream | Not started     | v0.2+ scope only                              |
| Plugin packaging (v4.13.1)                                     | Plugin workstream  | **Completed**   | --                                            |

## Code Anchors

| Layer    | File                                                      | Note                                                                                  |
| -------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Plugin   | `src/api/class-recognition-controller.php`                | Composition root delegating to 5 sub-controllers. Phase 4 replaces proxy with facade. |
| Plugin   | `src/api/class-clusters-controller.php`                   | Read-only cluster queries. Phase 2 refactors to read local projection.                |
| Plugin   | `src/api/class-cluster-mutations-controller.php`          | Cluster mutations. Phase 3 adds dual-write to local + proxy.                          |
| Plugin   | `src/api/class-media-identities-controller.php`           | Identity queries. Phase 2 refactors to read local projection.                         |
| Plugin   | `src/api/class-abstract-recognition-proxy-controller.php` | Shared proxy/retry base with constant/option/filter endpoint resolution.              |
| Plugin   | `src/support/class-life-cycle-manager.php`                | Lifecycle hooks. Schema creation via `dbDelta` now implemented.                       |
| Plugin   | `src/sovereign/repositories/`                             | Cluster, member, sync-state repositories (Phase 1 complete).                          |
| Plugin   | `src/sovereign/sync/class-snapshot-projector.php`         | Curation-safe snapshot ingestion (Phase 1 complete).                                  |
| Frontend | `js/admin/api/recognition/clusterApi*.ts`                 | Cluster API layer. Phase 2 may need cache/stale-indicator awareness.                  |
| Backend  | `recognition/interface_adapters/http/routers/*`           | FastAPI route handlers.                                                               |
| Backend  | `recognition/application/events/broadcaster.py`           | In-memory SSE fanout only -- cannot be repurposed for snapshot/delta sync.            |

## Risks and Mitigations

- **Multiple faces per attachment** -- identity data lives in plugin-owned tables, not post-meta or taxonomies.
- **Conflicting curation vs backend suggestions** -- strict curation-first precedence. Snapshot pull skips user-confirmed clusters.
- **Snapshot endpoint not yet built** -- parallel backend workstream. Projector tested with fixtures.
- **WP-Cron timing imprecision** -- acceptable for eventual consistency. Manual sync available. Action Scheduler upgrade path documented.

## Success Metrics

- Cluster UI renders from local store when backend is unreachable.
- Curation actions persist locally even during backend outage.
- Scheduled sync keeps local projection within one sync interval of backend state.
- No rollout feature flags or backward-compatibility shims remain.

---

# Consolidated Checklist

## Phase 1: Scaffolding and Local Projection -- COMPLETED

- [x] Portable packaging with prefix consolidation and endpoint hardening.
- [x] `dbDelta()` schema creation for `wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`.
- [x] Cluster/member/sync-state repository classes with curation-safe merge.
- [x] Snapshot projector with transaction boundary and fixture tests.
- [x] Snapshot API contract drafted.
- [x] All branch audit findings resolved (H-1, M-1..5, L-1..4).

## Phase 2: Read-Path Flip -- COMPLETED

- [x] Refactor `ClustersController` to read local projection first.
- [x] Refactor `ClusterMutationsController` (read path analysis complete).
- [x] Refactor `MediaIdentitiesController` to read local projection.
- [x] Surface sync status and stale age in UI.
- [x] (Backend parallel) Build snapshot endpoint.

## Phase 3: Local-First Writes and Pull Sync -- COMPLETED

- [x] Dual-write curation mutations (local + proxy).
- [x] Implement on-demand stale-check sync pull (`SyncPullJob`) on read-path entry.
- [x] Handle backend-unreachable gracefully with local persistence.

## Phase 4: Hard Dependency Removal -- NOT STARTED

- [ ] Replace proxy reads with local service facade.
- [ ] Update architecture diagrams and contracts.
- [ ] Backend: drop `thumbnail_url` column (migration), remove `ThumbnailSettings`, remove `StaticFiles` mount, remove `_fetch_cluster_thumbnails()`, strip `thumbnail_url` from domain objects / response schemas / repository reads.
- [ ] Plugin: simplify `resolve_thumb_url()` (remove dead HTTP-URL branch), remove `thumbnail_url` fallback in `ClustersController`, evaluate replacing `acx://` thumb-path indirection with direct `attachment_id` lookup.
- [ ] Frontend: remove `thumbnail_url` from TS types (`ClusterIdentity`, `TopUnlabeledRepresentative`, suggestion types), remove dead `IdentityThumbnail` fast-path, collapse dual `thumb_url`/`thumbnail_url` fields.
- [ ] Delete stale `.mypy_cache` artifacts for removed `thumbnail_service`.

## Deferred (post-v0.1.0)

- [ ] Outbox table (`wp_acx_cluster_operations`) with operation IDs.
- [ ] Action Scheduler migration for retry/backoff/dead-letter.
- [ ] Delta/event endpoint and idempotent mutation ingest.
- [ ] Drift reconciliation and conflict review queue.
