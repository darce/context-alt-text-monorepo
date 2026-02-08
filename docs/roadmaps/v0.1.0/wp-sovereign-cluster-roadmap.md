# WordPress Sovereign Cluster Architecture Roadmap (v0.1.0)

## Objective

Make the WordPress plugin self-sufficient for cluster display and curation after clusters are computed, even when the recognition backend is unavailable.

## Problem Statement

Current architecture is proxy-first:

- Plugin routes under `acx/v1/recognition/*` proxy to FastAPI via `RecognitionController`.
- Cluster reads/writes depend on live backend connectivity.
- If backend service is disconnected or subscription ends, cluster UI appears empty.

This creates:

- Perceived data loss and reduced product trust.
- Higher churn and lower conversion.
- Latency and brittleness from synchronous cross-service dependency.

## Greenfield Constraints

This roadmap follows `docs/agentic/instructions.md` greenfield policy:

- No production users and no existing data preservation requirement.
- No data migration burden; storage surfaces are disposable.
- No long-lived feature flags for architecture rollout.
- Prefer clean rewrites and direct cutover over backward-compatibility shims.
- Backend schema changes should be folded into baseline migration `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`.

## North-Star Architecture

### 1) Sovereign local read model in WordPress

WordPress owns a local projection of cluster state used by UI at all times:

- Cluster label state
- Cluster membership state
- Local representative thumbnails
- User curation history and final decisions

UI reads local projection first. Backend becomes compute/sync peer, not runtime dependency.

### 2) Curation-first conflict policy

Conflict precedence:

1. User curation in plugin (highest weight)
2. Explicit operator actions (merge/split/reassign/dismiss)
3. Backend computed suggestions

Backend suggestions can propose, but must not overwrite curated ground truth without explicit user action.

### 3) Pull-first sync (v0.1.0) with idempotent bidirectional sync (v0.2+)

**v0.1.0 scope (pull-only):**

- Plugin pulls cluster snapshots from backend on demand (admin action) or on schedule (WP-Cron).
- Curation writes go directly to backend via existing proxy AND are cached locally.
- No outbox pattern, no operation IDs, no dead-letter handling yet.

**v0.2+ scope (full bidirectional):**

- Plugin outbound changes are recorded as immutable operations with operation IDs.
- Backend imports them idempotently.
- Backend emits snapshot/delta updates with monotonic version/event IDs.
- Plugin applies updates idempotently and only when they do not violate curation precedence.
- Outbox sync via Action Scheduler with retry/backoff/dead-letter.

### 4) Degraded/offline-first operation

When backend is unavailable:

- Cluster listing/detail still render from local store.
- Thumbnail and membership views remain functional.
- Mutations queue for later sync (where safe).
- Admin sees explicit "offline/sync delayed" status, not empty state.

## Target Data Model (WordPress)

All cluster state lives in plugin-owned tables. WordPress taxonomies are **not used** for cluster modeling — clusters are computed identity groupings that change with re-clustering, not content-taxonomic concepts. Taxonomy overhead (term relationships, slugs, term counts, archive pages) provides no value here and creates cleanup burden.

> **Decision: no `acx_identity_cluster` taxonomy.** The UI already fetches via REST API — it does not need WP_Query/taxonomy integration.

### Plugin-owned tables

- `wp_acx_clusters`
  - `cluster_uuid` (pk)
  - `tenant_id`
  - `label` (nullable)
  - `curation_state` (`uncurated`|`confirmed`|`dismissed`)
  - `representative_thumb_path`
  - `identity_count`
  - `snapshot_version` (monotonic, from backend)
  - `is_user_confirmed` (bool)
  - `created_at`, `updated_at`, `last_synced_at`
- `wp_acx_identity_members`
  - `identity_uuid` (pk)
  - `cluster_uuid` (fk)
  - `attachment_id`
  - `bbox_json`
  - `thumb_path`
  - `similarity` (float)
  - `created_at`, `updated_at`
- `wp_acx_sync_state`
  - `stream_name`
  - `last_snapshot_version`
  - `updated_at`

### Deferred to v0.2+ (outbox pattern)

- `wp_acx_cluster_operations` (outbox)
  - `operation_id` (uuid, pk)
  - `operation_type`
  - `payload_json`
  - `origin` (`user`|`sync`)
  - `status` (`pending`|`acked`|`failed`)
  - `retry_count`, `next_retry_at`

## API and Contract Evolution

Backend contract changes needed. **Note:** the current `EventBroadcaster` is an in-memory SSE fanout with no persistence, no event IDs, and no replay capability. These endpoints require new backend infrastructure.

### v0.1.0 scope (snapshot pull)

1. **Snapshot export endpoint** (NEW — backend workstream required)
   - `GET /tenants/{tenant_id}/clusters/snapshot`
   - Full cluster state by tenant with monotonic snapshot version.
   - Returns clusters, members, representatives in a single payload.
   - This is the primary sync mechanism for v0.1.0.

### v0.2+ scope (full bidirectional)

2. Delta/event endpoint
   - Ordered events since `last_event_id`.
   - Requires persistent event store (does not exist yet).
3. Idempotent mutation ingest
   - Accept `operation_id` and return stable ack status.
4. Conflict metadata
   - Include `source`, `actor`, `created_at`, `cluster_version` for deterministic resolution.

## Phased Roadmap

> **Structural note:** Original Phase 0 (telemetry for read ratios and drift counts) was merged into Phase 1. Measuring local-vs-remote read ratios is meaningless before the local projection exists. Phase 4 (drift detection/reconciliation) is deferred to post-v0.1.0 — with zero users, if local and remote diverge, re-pulling the snapshot is sufficient.

### Phase 1: Scaffolding and Local Projection Foundation

Deliverables:

- Document current proxy seams and offline failure behavior.
- Define direct-cutover contracts for local-read/local-write architecture.
- Implement net-new schema creation in `LifecycleManager` via `dbDelta()` for plugin tables (`wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`). Current `LifecycleManager` only stores version options — all table creation is new work.
- Create local repository layer in plugin (cluster + member + sync-state repositories).
- Add projector that can ingest backend snapshot into local model.
- Store local thumbnails with deterministic thumb keys.

Exit criteria:

- Cluster list/detail UI can render from local store for previously computed clusters.

### Phase 2: Read-Path Flip (Offline First)

Deliverables:

- Refactor plugin REST handlers to read local projection first.
- Remove proxy-first read dependency for cluster views.
- UI surfaces explicit sync status and stale age.

Exit criteria:

- Disabling backend connectivity no longer removes existing cluster UI data.

### Phase 3: Local-First Writes and Pull Sync

Deliverables:

- User curation actions write to local state AND forward to backend via existing proxy (dual-write, no outbox).
- Implement scheduled snapshot pull via WP-Cron (see [Background Scheduling Strategy](#background-scheduling-strategy)).
- If backend is unreachable during curation write, local state is still persisted; remote write is retried on next scheduled sync.

Exit criteria:

- User actions are durable locally.
- Scheduled sync keeps local projection current when backend is available.

### Phase 4: Remove Hard Runtime Dependency

Deliverables:

- Replace proxy-only cluster reads in `RecognitionController` with local service facade.
- Keep backend integration as sync/compute pipeline, not blocking UI.
- Update docs/diagrams to reflect sovereign plugin architecture.

Exit criteria:

- Plugin is operational for cluster browsing/curation during backend outage and after service disconnect.

### Deferred to post-v0.1.0

**Outbox and Bidirectional Sync (original Phase 3 scope):**

- Outbox table (`wp_acx_cluster_operations`) with operation IDs.
- Background sync worker via Action Scheduler with retry/backoff/dead-letter.
- Idempotent mutation ingest on backend.

**Drift Detection and Reconciliation (original Phase 4 scope):**

- Periodic reconciliation job comparing local checksum/version vs backend snapshot.
- Deterministic conflict resolution rules with curation precedence.
- Conflict review queue and drift observability dashboards.

## Background Scheduling Strategy

A **2-stage approach** for background task scheduling:

### Stage 1 — WP-Cron (v0.1.0)

Used for pull-only sync and simple scheduled operations.

- **Zero external dependencies** — built into WordPress core.
- Sufficient for periodic snapshot pulls and simple retry-on-next-cycle.
- Limitation: pseudo-cron (fires on page visit), so timing is imprecise — acceptable for eventual consistency.
- Register on activation: `wp_schedule_event(time(), 'hourly', 'acx_sync_pull_snapshot')`.
- Simple retry: `wp_schedule_single_event(time() + $backoff, 'acx_retry_sync', [$args])`.

### Stage 2 — Action Scheduler (v0.2+)

Migrate to Action Scheduler when outbox pattern with retry/backoff/dead-letter is introduced.

- **Purpose-built** for queued, retryable, schedulable background jobs.
- Built-in retry with configurable max attempts.
- Searchable job history with admin UI.
- Concurrency-safe (row-level claim locking).
- Ships as a library (`woocommerce/action-scheduler` via Composer) — no WooCommerce dependency required (~200KB).
- Migration is straightforward: replace `wp_schedule_*` calls with `as_schedule_*` calls.

| Concern | WP-Cron (v0.1.0) | Action Scheduler (v0.2+) |
|---|---|---|
| Zero dependencies | Yes | No (bundle library) |
| Retry/backoff | Manual | Built-in |
| Dead-letter / failure visibility | Manual | Built-in admin UI |
| Concurrency safety | None | Row-level claim locking |
| Job history/audit | None | Searchable log |
| Sufficient for pull-only sync | Yes | Overkill |
| Sufficient for outbox with retry | Awkward | Purpose-built |

## Workstreams and Code Anchors

Plugin seams:

- `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php` (single ~900-line controller, handles all proxy routes)
- `apps/prototype-wp-alt-context/src/api/class-api.php` (route registration, workbench/roster endpoints)
- `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` (minimal — only stores version options, no table creation yet)
- `apps/prototype-wp-alt-context/js/admin/api/recognition/clusterApi.ts`
- `apps/prototype-wp-alt-context/js/admin/api/recognition/identityApi.ts`
- `apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts`
- `apps/prototype-wp-alt-context/js/admin/hooks/*`

Backend seams:

- `apps/prototype-description-service/recognition/interface_adapters/http/routers/*` (analyze, clusters, suggestions, events, media, diagnostics, health)
- `apps/prototype-description-service/recognition/application/orchestration/cluster_service.py`
- `apps/prototype-description-service/recognition/application/events/broadcaster.py` (**in-memory SSE fanout only** — no persistent event store, no event IDs, no replay)

> **Backend workstream required:** The snapshot export endpoint (`GET /tenants/{tenant_id}/clusters/snapshot`) does not exist and must be built as a parallel backend effort before Phase 1 exit criteria can be met.

Diagram references:

- `docs/agentic/diagrams/backend-uml/master.mmd`
- `docs/agentic/diagrams/backend-uml/hexagonal-map.mmd`
- `docs/agentic/diagrams/backend-uml/agent-quick-start.mmd`
- `docs/agentic/diagrams/system-overview.mmd`
- `docs/agentic/diagrams/backend-uml/components/http-boundary.mmd`
- `docs/agentic/diagrams/backend-uml/workflows/image-to-cluster-happy-path.mmd`
- `docs/agentic/diagrams/backend-uml/workflows/startup_sequence.mmd`

## Risks and Mitigations

- Risk: multiple faces in one attachment cannot be modeled with simple post-meta or taxonomies.
  - Mitigation: all identity-level data lives in plugin-owned tables (`wp_acx_identity_members`), not WordPress-native constructs.
- Risk: conflicting updates between local curation and backend suggestions.
  - Mitigation: strict curation-first precedence policy. For v0.1.0 (pull-only sync), local curation wins unconditionally; snapshot pull skips clusters with user-confirmed curation state.
- Risk: aggressive rewrite introduces regressions.
  - Mitigation: contract tests, integration tests, and direct cutover verification in local/dev environments.
- Risk: backend snapshot endpoint does not exist yet.
  - Mitigation: parallel backend workstream; plugin can still render locally-cached data even if snapshot endpoint is not ready.
- Risk: WP-Cron pseudo-cron timing is imprecise.
  - Mitigation: acceptable for eventual consistency; admin can trigger manual sync; upgrade path to Action Scheduler is documented.

## Success Metrics

- Cluster UI renders from local store when backend is unreachable (binary: yes/no, not SLA percentage).
- Median cluster list latency in admin: measurably lower than proxy-only baseline (local DB read vs HTTP round-trip).
- Curation actions persist locally even during backend outage.
- Scheduled sync keeps local projection within one sync interval of backend state.

## Definition of Done (v0.1.0 roadmap outcome)

- WordPress can render and curate existing computed clusters with backend offline.
- Local curation is durable and prioritized as ground truth.
- Sync is idempotent, observable, and recoverable.
- Backend dependency is moved from runtime requirement to eventual consistency channel.
- No compatibility shims or rollout feature flags are required for the final architecture.

---

# Consolidated Checklist

## Phase 1: Scaffolding and Local Projection Foundation

- [ ] Document current proxy seams and offline failure behavior.
- [ ] Define direct-cutover contracts for local-read/local-write architecture.
- [ ] Implement net-new `dbDelta()` schema creation in `LifecycleManager` for `wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`.
- [ ] Add cluster/member/sync-state repository classes in plugin.
- [ ] Implement snapshot projector to ingest backend snapshot into local tables.
- [ ] Persist deterministic local thumbnails.
- [ ] (Backend parallel) Build snapshot export endpoint (`GET /tenants/{tenant_id}/clusters/snapshot`).

## Phase 2: Read-Path Flip

- [ ] Refactor cluster read endpoints to local projection.
- [ ] Remove proxy-first read dependency for cluster list/detail/members.
- [ ] Surface offline and staleness status in UI.

## Phase 3: Local-First Writes and Pull Sync

- [ ] Write curation mutations locally AND forward to backend via proxy (dual-write, no outbox).
- [ ] Register WP-Cron scheduled event for periodic snapshot pull (`acx_sync_pull_snapshot`).
- [ ] Handle backend-unreachable gracefully: persist local state, retry remote on next sync cycle.

## Phase 4: Hard Dependency Removal

- [ ] Replace runtime proxy dependency for cluster UX with local service facade.
- [ ] Keep backend as compute/sync peer only.
- [ ] Update architecture diagrams and contracts to final model.

## Deferred to post-v0.1.0

- [ ] Add outbox table (`wp_acx_cluster_operations`) with operation IDs.
- [ ] Migrate from WP-Cron to Action Scheduler for robust retry/backoff/dead-letter.
- [ ] Implement idempotent mutation ingest on backend.
- [ ] Add periodic reconciliation job against backend snapshots/events.
- [ ] Enforce deterministic conflict rules with curation precedence.
- [ ] Add conflict review queue and drift observability.

## Success Criteria

- [ ] Previously computed clusters remain visible during backend outage.
- [ ] Local curation remains durable and authoritative.
- [ ] Scheduled pull sync keeps local projection current.
- [ ] No rollout feature flags or backward-compatibility shims remain.
