# WordPress Sovereign Cluster Architecture Roadmap (v0.1.0)

## Objective

Make the WordPress plugin self-sufficient for cluster display and curation after clusters are computed, even when the recognition backend is unavailable.

## Problem Statement

Current architecture is proxy-first:

- Plugin routes under `acx/v1/recognition/*` proxy to FastAPI through a decomposed controller suite (composition root + 5 sub-controllers).
- Cluster reads and writes depend on live backend connectivity.
- If backend service is disconnected or subscription ends, cluster UI appears empty.

This creates:

- Perceived data loss and reduced product trust.
- Higher churn and lower conversion.
- Latency and brittleness from synchronous cross-service dependency.

## Constraints

- **Greenfield policy** — no production users and no existing data to preserve. Storage surfaces are disposable. Prefer clean rewrites and direct cutover over backward-compatibility shims. No long-lived feature flags.
- **Backend schema baseline** — backend schema changes fold into `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`.
- **Snapshot endpoint does not exist** — `GET /tenants/{tenant_id}/clusters/snapshot` is required for v0.1.0 sync but has no contract doc, no backend route, and no backend implementation. This is a parallel backend workstream.
- **WP-Cron for v0.1.0** — Action Scheduler deferred to v0.2+.
- **Plugin packaging** — sovereign code must ship in the standalone plugin ZIP per `docs/tasks/4.0/4.13.1/wp-plugin-portable-packaging-plan.md`. No monorepo path coupling.

## Terminology

- **Local projection**: plugin-owned MySQL tables (`wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`) that mirror backend cluster state.
- **Snapshot**: full cluster state for a tenant with a monotonic version. The primary sync mechanism for v0.1.0.
- **Curation**: user actions (label, confirm, dismiss, merge, split, reassign) that are authoritative ground truth.
- **Proxy-first**: current pattern where REST handlers forward requests to the backend and return the response directly.
- **Sovereign**: target pattern where REST handlers read local projection first and sync with backend asynchronously.

## Current State

> Verified against codebase at commit `5b92720` (2026-02-10).

What works:

- **Controller architecture is already decomposed** — `RecognitionController` (153 lines) is a composition root delegating to `AnalysisJobsController`, `ClustersController`, `ClusterMutationsController`, `MediaIdentitiesController`, and `SuggestionsController`. Shared proxy/retry logic lives in `AbstractRecognitionProxyController` (101 lines). All delegation is typed (no `__call()` magic).
- Lifecycle hooks are wired: `register_activation_hook`, `register_deactivation_hook`, `register_uninstall_hook` delegate to `LifecycleManager`.
- `LifecycleManager` stores version options (`alt_context_version`, `alt_context_installed`) and declares `OWNED_TABLE_SUFFIXES` (`acx_clusters`, `acx_identity_members`, `acx_sync_state`) with `drop_tables()` for uninstall — but does **not** create tables yet (no `dbDelta`, no `CREATE TABLE`).
- Service URL and API key are resolved lazily per-request via `get_option()` — no constructor caching, no stale-value risk.
- Frontend API layer has grown: `clusterApi.ts` (plus `clusterApiMutations.ts`, `clusterApiMembers.ts`, `clusterApiQueries.ts`), `identityApi.ts` (plus `identityActionsApi.ts`, `identityQueriesApi.ts`), `scanApi.ts`.
- All six automated gates pass (55 PHP tests / 161 assertions, 153 JS tests, cs-check, typecheck, lint, arch).
- `EventBroadcaster` in the backend is in-memory SSE fanout only — no persistent event store, no event IDs, no replay.

What's missing:

- **No local projection tables** — table names are referenced in `LifecycleManager` for teardown, but no `dbDelta` schema creation exists.
- **No repository layer** — no cluster/member/sync-state repository classes exist in the plugin.
- **No snapshot projector** — no code to ingest backend state into local tables.
- **No snapshot endpoint** — `GET /tenants/{tenant_id}/clusters/snapshot` is not in `docs/agentic/contracts/` and has no backend route. The `EventBroadcaster` cannot be repurposed (no persistence, no event IDs).
- **No WP-Cron registration** — zero `wp_schedule_event` or `wp_next_scheduled` calls in `src/`.
- **No offline/degraded UX** — backend disconnect shows empty state, no sync status indicator.
- **Endpoint resolution is option-only** — `get_recognition_base_url()` reads `get_option()` without constant or filter precedence. The packaging plan (v4.13.1) addresses this.
- **Option key prefix inconsistency** — lifecycle/config options use `alt_context_*`, roster options use `acx_*`. Pre-existing; outside sovereign scope.

## Target Architecture

### Design Decisions

| Decision                                       | Rationale                                                                                                                                                                                                              |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No `acx_identity_cluster` taxonomy             | Clusters are computed identity groupings that change with re-clustering, not content-taxonomic concepts. Taxonomy overhead (slugs, term counts, archive pages) adds no value. UI fetches via REST API, not `WP_Query`. |
| Plugin-owned tables via `dbDelta`              | Multiple faces per attachment cannot be modeled with post-meta. Identity-level data requires its own schema.                                                                                                           |
| Pull-first sync (v0.1.0)                       | Simplest viable sync. Plugin pulls snapshots on demand or schedule. No outbox, no operation IDs, no dead-letter.                                                                                                       |
| WP-Cron for v0.1.0, Action Scheduler for v0.2+ | WP-Cron has zero dependencies and is sufficient for eventual consistency. Action Scheduler adds retry/backoff/dead-letter when outbox pattern is introduced.                                                           |
| Curation-first conflict policy                 | User curation wins unconditionally. Snapshot pull skips clusters with user-confirmed curation state. Backend suggestions propose but never overwrite curated ground truth.                                             |

### North-Star Behavior

1. **Sovereign local read model** — UI reads local projection at all times. Backend is compute/sync peer, not runtime dependency.
2. **Curation-first conflict policy** — precedence: user curation > operator actions > backend suggestions.
3. **Pull-first sync (v0.1.0)** — plugin pulls snapshots on demand or schedule. Curation writes go to backend via proxy AND cache locally. No outbox yet.
4. **Degraded/offline-first** — cluster listing/detail render from local store during backend outage. Admin sees explicit sync status, not empty state.

### Data Model (WordPress)

**Plugin-owned tables (v0.1.0)**:

- `wp_acx_clusters`
  - `cluster_uuid` (pk), `tenant_id`, `label` (nullable)
  - `curation_state` (`uncurated` | `confirmed` | `dismissed`)
  - `representative_thumb_path`, `identity_count`
  - `snapshot_version` (monotonic, from backend)
  - `is_user_confirmed` (bool)
  - `created_at`, `updated_at`, `last_synced_at`

- `wp_acx_identity_members`
  - `identity_uuid` (pk), `cluster_uuid` (fk), `attachment_id`
  - `bbox_json`, `thumb_path`, `similarity` (float)
  - `created_at`, `updated_at`

- `wp_acx_sync_state`
  - `stream_name`, `last_snapshot_version`, `updated_at`

**Deferred to v0.2+ (outbox pattern)**:

- `wp_acx_cluster_operations` — `operation_id` (uuid pk), `operation_type`, `payload_json`, `origin` (`user` | `sync`), `status` (`pending` | `acked` | `failed`), `retry_count`, `next_retry_at`

### API and Contract Evolution

**v0.1.0 — snapshot pull**:

1. `GET /tenants/{tenant_id}/clusters/snapshot` (NEW — **backend workstream required**)
   - Full cluster state by tenant with monotonic snapshot version.
   - Returns clusters, members, representatives in a single payload.
   - **Status: not started.** No contract doc, no backend route, no implementation.

**v0.2+ — full bidirectional**:

2. Delta/event endpoint — ordered events since `last_event_id` (requires persistent event store).
3. Idempotent mutation ingest — accept `operation_id`, return stable ack status.
4. Conflict metadata — `source`, `actor`, `created_at`, `cluster_version` for deterministic resolution.

### Background Scheduling Strategy

| Concern                          | WP-Cron (v0.1.0) | Action Scheduler (v0.2+)                                        |
| -------------------------------- | ---------------- | --------------------------------------------------------------- |
| Zero dependencies                | Yes              | No (bundle `woocommerce/action-scheduler` via Composer, ~200KB) |
| Retry/backoff                    | Manual           | Built-in                                                        |
| Dead-letter / failure visibility | Manual           | Built-in admin UI                                               |
| Concurrency safety               | None             | Row-level claim locking                                         |
| Job history/audit                | None             | Searchable log                                                  |
| Sufficient for pull-only sync    | Yes              | Overkill                                                        |
| Sufficient for outbox with retry | Awkward          | Purpose-built                                                   |

WP-Cron registration on activation:

- `wp_schedule_event(time(), 'hourly', 'acx_sync_pull_snapshot')`
- Simple retry: `wp_schedule_single_event(time() + $backoff, 'acx_retry_sync', [$args])`

Migration path: replace `wp_schedule_*` calls with `as_schedule_*` calls when Action Scheduler lands.

## Phased Delivery

> **Structural note:** Original Phase 0 (telemetry for read ratios and drift counts) was merged into Phase 1. Measuring local-vs-remote read ratios is meaningless before the local projection exists. Drift detection/reconciliation is deferred to post-v0.1.0 — with zero users, if local and remote diverge, re-pulling the snapshot is sufficient.

### Phase 1: Scaffolding and Local Projection Foundation

**Goal**: Create local tables and repository layer so cluster data can be read from WordPress-owned storage.

Deliverables:

- Document current proxy seams and offline failure behavior.
- Define direct-cutover contracts for local-read/local-write architecture.
- Implement `dbDelta()` schema creation in `LifecycleManager` for `wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`. Table names already declared in `OWNED_TABLE_SUFFIXES`; creation logic is new work.
- Create cluster/member/sync-state repository classes in plugin.
- Add projector that can ingest backend snapshot into local model.
- Store local thumbnails with deterministic thumb keys.

Exit criteria:

- Cluster list/detail UI can render from local store for previously computed clusters.

### Phase 2: Read-Path Flip (Offline First)

**Goal**: Plugin reads local projection first; backend becomes optional for cluster views.

Deliverables:

- Refactor plugin REST handlers (`ClustersController`, `ClusterMutationsController`, `MediaIdentitiesController`) to read local projection first.
- Remove proxy-first read dependency for cluster views.
- UI surfaces explicit sync status and stale age.

Exit criteria:

- Disabling backend connectivity no longer removes existing cluster UI data.

### Phase 3: Local-First Writes and Pull Sync

**Goal**: Curation actions persist locally even during backend outage; scheduled sync keeps projection current.

Deliverables:

- User curation actions write to local state AND forward to backend via existing proxy (dual-write, no outbox).
- Register WP-Cron scheduled event for periodic snapshot pull (`acx_sync_pull_snapshot`).
- If backend is unreachable during curation write, local state is persisted; remote write is retried on next scheduled sync.

Exit criteria:

- User actions are durable locally.
- Scheduled sync keeps local projection current when backend is available.

### Phase 4: Remove Hard Runtime Dependency

**Goal**: Backend becomes compute/sync peer only; cluster UX is fully sovereign.

Deliverables:

- Replace runtime proxy dependency for cluster reads with local service facade.
- Keep backend integration as sync/compute pipeline, not blocking UI.
- Update architecture diagrams and contracts to final sovereign model.

Exit criteria:

- Plugin is operational for cluster browsing/curation during backend outage and after service disconnect.

## External Dependencies

| Dependency                                                     | Owner                              | Status                                                                                      | Blocks                                                               |
| -------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Snapshot endpoint `GET /tenants/{tenant_id}/clusters/snapshot` | Backend workstream                 | **Not started** — no contract doc, no route, no implementation                              | Phase 1 exit criteria (local projection requires data to project)    |
| Persistent event store for delta/event endpoint                | Backend workstream                 | Not started                                                                                 | v0.2+ scope only                                                     |
| Plugin packaging (v4.13.1)                                     | Plugin workstream                  | In progress — [packaging plan](../../tasks/4.0/4.13.1/wp-plugin-portable-packaging-plan.md) | Sovereign code must ship in standalone ZIP                           |
| Endpoint resolution hardening (constant → option → filter)     | Plugin workstream (4.13.1 Phase 2) | Not started                                                                                 | Not blocking, but production deployments need configurable endpoints |

## Code Anchors

> Updated to reflect post-decomposition architecture (commit `5b92720`).

| Layer    | File                                                                                       | Note                                                                                                                                       |
| -------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Plugin   | `src/api/class-recognition-controller.php`                                                 | Composition root (153 lines) — delegates to 5 sub-controllers. Phase 4 replaces proxy reads with local facade reads.                       |
| Plugin   | `src/api/class-clusters-controller.php`                                                    | Read-only cluster queries + thumbnail hydration (189 lines). Phase 2 refactors to read local projection.                                   |
| Plugin   | `src/api/class-cluster-mutations-controller.php`                                           | Cluster mutations (297 lines). Phase 3 adds dual-write to local + proxy.                                                                   |
| Plugin   | `src/api/class-media-identities-controller.php`                                            | Identity queries (90 lines). Phase 2 refactors to read local projection.                                                                   |
| Plugin   | `src/api/class-suggestions-controller.php`                                                 | Suggestion CRUD (234 lines). Remains proxy-only (suggestions are backend-computed).                                                        |
| Plugin   | `src/api/class-abstract-recognition-proxy-controller.php`                                  | Shared proxy/retry base (101 lines). Endpoint resolution is option-only; packaging plan adds constant/filter precedence.                   |
| Plugin   | `src/api/class-api.php`                                                                    | Route registration, workbench/roster endpoints (242 lines).                                                                                |
| Plugin   | `src/support/class-life-cycle-manager.php`                                                 | Lifecycle hooks (84 lines). Declares `OWNED_TABLE_SUFFIXES` and `drop_tables()` — no `dbDelta` creation yet. Phase 1 adds schema creation. |
| Frontend | `js/admin/api/recognition/clusterApi.ts` (+ `*Mutations.ts`, `*Members.ts`, `*Queries.ts`) | Cluster API layer. Phase 2 may need cache/stale-indicator awareness.                                                                       |
| Frontend | `js/admin/api/recognition/identityApi.ts` (+ `*ActionsApi.ts`, `*QueriesApi.ts`)           | Identity API layer.                                                                                                                        |
| Frontend | `js/admin/api/recognition/scanApi.ts`                                                      | Scan/analysis API layer. Unchanged by sovereign roadmap.                                                                                   |
| Frontend | `js/admin/hooks/*`                                                                         | React hooks for recognition features.                                                                                                      |
| Backend  | `recognition/interface_adapters/http/routers/*`                                            | FastAPI route handlers (analyze, clusters, suggestions, events, media, diagnostics, health).                                               |
| Backend  | `recognition/application/orchestration/cluster_service.py`                                 | Cluster orchestration logic.                                                                                                               |
| Backend  | `recognition/application/events/broadcaster.py`                                            | **In-memory SSE fanout only** — no persistent event store, no event IDs, no replay. Cannot be repurposed for snapshot/delta sync.          |

Diagram references:

- `docs/agentic/diagrams/system-overview.mmd`
- `docs/agentic/diagrams/backend-uml/master.mmd`
- `docs/agentic/diagrams/backend-uml/hexagonal-map.mmd`
- `docs/agentic/diagrams/backend-uml/agent-quick-start.mmd`
- `docs/agentic/diagrams/backend-uml/components/http-boundary.mmd`
- `docs/agentic/diagrams/backend-uml/workflows/image-to-cluster-happy-path.mmd`
- `docs/agentic/diagrams/backend-uml/workflows/startup_sequence.mmd`

## Risks and Mitigations

- **Risk**: Multiple faces per attachment cannot be modeled with post-meta or taxonomies.
  Mitigation: all identity-level data lives in plugin-owned tables (`wp_acx_identity_members`), not WordPress-native constructs.
- **Risk**: Conflicting updates between local curation and backend suggestions.
  Mitigation: strict curation-first precedence policy. Snapshot pull skips clusters with user-confirmed curation state.
- **Risk**: Aggressive rewrite introduces regressions.
  Mitigation: contract tests, integration tests, direct cutover verification. Controller decomposition (done in v4.13.0) reduces blast radius per-controller.
- **Risk**: Snapshot endpoint does not exist yet.
  Mitigation: parallel backend workstream. Plugin can render locally-cached data even if snapshot endpoint is not ready. Phase 1 projector can be tested with fixture snapshots.
- **Risk**: WP-Cron pseudo-cron timing is imprecise.
  Mitigation: acceptable for eventual consistency. Admin can trigger manual sync. Upgrade path to Action Scheduler is documented.
- **Risk**: Sovereign code ships in standalone ZIP with stale vendor deps.
  Mitigation: packaging plan (v4.13.1) enforces `composer install --no-dev` and asset validation.

## Success Metrics

- Cluster UI renders from local store when backend is unreachable (binary: yes/no).
- Median cluster list latency in admin: measurably lower than proxy-only baseline (local DB read vs HTTP round-trip).
- Curation actions persist locally even during backend outage.
- Scheduled sync keeps local projection within one sync interval of backend state.

---

# Consolidated Checklist

## Phase 1: Scaffolding and Local Projection Foundation

- [ ] Document current proxy seams and offline failure behavior.
- [ ] Define direct-cutover contracts for local-read/local-write architecture.
- [ ] Implement `dbDelta()` schema creation in `LifecycleManager` for `wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`.
- [ ] Add cluster/member/sync-state repository classes in plugin.
- [ ] Implement snapshot projector to ingest backend snapshot into local tables.
- [ ] Persist deterministic local thumbnails.
- [ ] (Backend parallel) Build snapshot export endpoint (`GET /tenants/{tenant_id}/clusters/snapshot`) and add contract to `docs/agentic/contracts/`.

## Phase 2: Read-Path Flip

- [ ] Refactor `ClustersController`, `ClusterMutationsController`, `MediaIdentitiesController` to read local projection first.
- [ ] Remove proxy-first read dependency for cluster list/detail/members.
- [ ] Surface offline and staleness status in UI.

## Phase 3: Local-First Writes and Pull Sync

- [ ] Write curation mutations locally AND forward to backend via proxy (dual-write, no outbox).
- [ ] Register WP-Cron scheduled event for periodic snapshot pull (`acx_sync_pull_snapshot`).
- [ ] Handle backend-unreachable gracefully: persist local state, retry remote on next sync cycle.

## Phase 4: Hard Dependency Removal

- [ ] Replace runtime proxy dependency for cluster UX with local service facade.
- [ ] Keep backend as compute/sync peer only.
- [ ] Update architecture diagrams and contracts to final sovereign model.

## Deferred to post-v0.1.0

**Outbox and Bidirectional Sync:**

- [ ] Add outbox table (`wp_acx_cluster_operations`) with operation IDs.
- [ ] Migrate from WP-Cron to Action Scheduler for robust retry/backoff/dead-letter.
- [ ] Implement idempotent mutation ingest on backend.

**Drift Detection and Reconciliation:**

- [ ] Add periodic reconciliation job against backend snapshots/events.
- [ ] Enforce deterministic conflict rules with curation precedence.
- [ ] Add conflict review queue and drift observability.

**Tech Debt (carried from `docs/tasks/tech-debt/current-debt.md`):**

- [ ] **#4** Extract lighter session-rebind in chunk loop instead of full `cluster_service_builder` rebuild (`clustering.py`) — _Defer: perf impact is marginal; avoid new abstraction until chunking pattern stabilizes_
- [ ] **#5** Add lightweight ID-only cluster query for surfacing (avoid eager-loading reps/centroids when only IDs/labels needed) — _Defer: broader refactor; current limit=1000 is adequate; revisit when tenant cluster counts approach 500+_
- [ ] **#9** Add `typeof` guards at `wp.hooks` usage sites, not just warn-and-continue (`main.tsx` + downstream consumers) — _Defer: keep rendering, guard at usage sites only; not a regression_
- [ ] **#10** Map `quality_score` from ORM model into domain `MediaIdentity` (pre-existing gap, not a regression) — _Defer: fix belongs in the detection pipeline, not the mapping layer_

## Success Criteria

- [ ] Previously computed clusters remain visible during backend outage.
- [ ] Local curation remains durable and authoritative.
- [ ] Scheduled pull sync keeps local projection current.
- [ ] No rollout feature flags or backward-compatibility shims remain.
