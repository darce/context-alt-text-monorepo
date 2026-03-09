# Recognition State Reconciliation + Offline Continuity (v0.2.0+)

## Objective

Make the recognition product safe to operate in a split-connectivity world: the WordPress plugin must continue to render clusters, identities, and curation while the description service is offline, and it must reconcile back to backend-generated clustering work without silent overwrite or duplicate orchestration.

When this epic is complete, WordPress is the operator-facing source of truth for rendered state and curation, the description service is the compute backend for detection and clustering, and both sides exchange versioned proposals and acknowledgements instead of racing to overwrite each other.

## Problem Statement

The current system already supports local projection in `wpdb`, which satisfies the product requirement that the plugin remain useful when the backend is unavailable. The failure mode is that the system does not yet model the two-state architecture explicitly enough: clustering jobs can continue on the backend, local curation can continue in WordPress, and there is no complete pipeline contract for linking scan -> clustering -> projection -> acknowledgement.

That creates a split-brain risk:

- backend compute can finish work that never becomes visible in the UI at the right time,
- local curation can diverge from backend clustering state during offline periods,
- snapshot replay can preserve some curated fields but still lacks row-level lineage and explicit collision handling,
- sync status is too coarse to tell operators whether they are looking at stale machine state, pending local mutations, or both.

## UX Vision

Operators always see a usable local view of clusters and persons, even with the description service offline. The UI clearly indicates whether the view is fresh, stale, or carrying queued local changes. When a scan is launched, the operator sees one pipeline that moves through analyzing, clustering, and local projection rather than disjoint jobs.

When connectivity resumes, new machine clustering results arrive as proposals that merge automatically only where no user curation would be disturbed. Curated labels, assignments, merges, and dismissals remain authoritative. If the backend proposes a change that would collide with curation, the system records and surfaces that conflict instead of silently applying it.

## Constraints

- The plugin must render clusters, identities, and curation from local `wpdb` projection even when the description service is offline.
- User curation is ground truth. Machine clustering is advisory unless and until it is merged into uncurated local state.
- The MVP should launch a proof of concept, not a finished distributed-sync product. Prefer explicit, conservative orchestration over ambitious active-active behavior.
- The description service remains the compute backend for detection and clustering; WordPress/MySQL is not expected to perform pgvector-style similarity search or clustering.
- Changes must fit the existing sovereign architecture: local projection, snapshot-based reads today, with minimal-risk extension toward replay and reconciliation.
- Privacy claims for v0.2.0 must remain within a credible privacy-minimized retention posture; this epic should not imply full sovereignty while backend compute and retained machine state still exist.
- Backend machine state that is no longer needed after successful local projection and acknowledgement should be eligible for disposal under explicit tenant policy.

## Terminology

- **Projection state**: the cluster and identity data materialized into WordPress tables for UI rendering.
- **Curation state**: local operator-authored decisions such as person assignment, merge, dismiss, rename, and confirmation.
- **Machine proposal**: backend-generated clustering or membership change that has not yet overridden curation.
- **Pipeline job**: the full analyze -> clustering -> projection lifecycle presented to the UI as one operator-visible flow.
- **Projection version**: the backend snapshot or delta version that last updated a projected row.
- **Local revision**: a monotonic local mutation counter used to detect whether curation changed since the last backend sync base.
- **Outbox operation**: a durable local intent record that must be pushed to the backend when connectivity permits.
- **Conflict record**: an explicit local record that a backend proposal touched a curated entity and could not be safely auto-merged.

## Current State

- `wp_acx_clusters`, `wp_acx_identity_members`, and `wp_acx_persons` already let the plugin render useful recognition state locally.
- Snapshot projection already protects some curated fields with `is_user_confirmed` semantics.
- The description service can auto-chain clustering work after analyze/scan completion.
- Job lifecycle was recently patched so follow-up clustering can surface through the original scan job ID, but that only fixes one orchestration gap.
- `wp_acx_sync_state` tracks only coarse snapshot freshness; it does not model queued local mutations, last acknowledged push revision, or unresolved conflicts.
- Snapshot merge logic does not yet carry enough row-level lineage to distinguish machine refresh from curated override across clusters and memberships.
- Local roster and cluster mutations are not yet fully modeled as durable outbox operations with replay, acknowledgement, and drift detection.
- The system still behaves like two partially authoritative stores instead of one curated local authority consuming backend machine proposals.

## Target Architecture

The product should adopt an explicit authority split:

- WordPress is the authority for all operator-visible state and all curation.
- The description service is the authority for compute outputs and machine proposals.
- Sync between them is versioned, durable, and conservative.

The plugin should store:

- the last projected machine state,
- the local curation overlay,
- the queue of local changes that still need backend acknowledgement,
- the local record of conflicts that require human review.

The description service should:

- expose clustering results and snapshot or delta exports as machine proposals,
- accept durable curation updates from WordPress with idempotency and expected-base semantics,
- avoid assuming that its current clustering state is the final UI truth until WordPress has projected and acknowledged it,
- expose retention and audit semantics for machine-derived biometric state so operators can understand what was retained, exported, or purged.

The key rule is that the system should not act like an active-active dual master. Instead, it should behave like:

1. backend computes proposals,
2. WordPress projects them into local machine state,
3. WordPress overlays curation,
4. WordPress pushes curated intents back to the backend,
5. backend acknowledges and aligns future proposals to that curated baseline.

### Design Decisions

| Decision | Rationale |
| --- | --- |
| WordPress local projection is the rendering source of truth | The product requirement is offline usability. The UI cannot depend on live backend reads. |
| User curation always wins over machine clustering | This matches operator expectation and prevents silent regression of curated work. |
| Backend clustering results are treated as proposals, not final truth | This avoids active-active collisions and makes offline replay safe. |
| Pipeline status must unify analyze, clustering, and projection | Operators should not have to reason about hidden follow-up jobs. |
| Conflicts must be recorded explicitly, not silently dropped or overwritten | Collision handling is product behavior, not just storage behavior. |
| MVP uses versioned snapshots plus outbox replay before richer delta sync | This is enough for a launchable proof of concept without overbuilding distributed sync. |
| Curated cluster membership locks backend re-clustering out of auto-apply | Once the operator has merged, split, assigned, or dismissed, backend membership changes must become reviewable proposals. |
| Privacy posture for v0.2.0 is minimized retention, not sovereignty | This keeps product messaging aligned with the real MVP architecture while still improving trust and operator control. |
| Backend machine state should have auditable lifecycle markers | Retain, export, acknowledge, and purge events make split-state operations inspectable and easier to debug. |

### Data Model

The MVP does not require a perfect event-sourced model, but it does require explicit lineage and sync metadata.

**WordPress plugin**

- Extend `wp_acx_clusters` with fields such as:
  - `projection_version`
  - `machine_updated_at`
  - `local_revision`
  - `last_origin_job_id`
  - `sync_status` (`synced`, `pending_push`, `conflict`, `stale_machine_state`)
- Extend `wp_acx_identity_members` with:
  - `projection_version`
  - `local_revision`
  - `membership_source` (`machine`, `curated`)
  - `is_curated_override`
- Extend `wp_acx_sync_state` with:
  - `last_snapshot_version`
  - `last_acknowledged_outbox_seq`
  - `pending_mutation_count`
  - `has_conflicts`
  - `last_successful_push_at`
- Add `wp_acx_sync_outbox`:
  - `id`
  - `tenant_id`
  - `entity_type`
  - `entity_key`
  - `operation_type`
  - `payload_json`
  - `idempotency_key`
  - `expected_base_version`
  - `status`
  - `attempt_count`
  - `created_at`
  - `updated_at`
- Add `wp_acx_sync_conflicts`:
  - `id`
  - `tenant_id`
  - `entity_type`
  - `entity_key`
  - `backend_version`
  - `local_revision`
  - `machine_payload_json`
  - `local_payload_json`
  - `resolution_status`
  - `created_at`

**Description service**

- Link chained jobs under a stable pipeline contract:
  - analyze job id
  - follow-up clustering job id
  - projection-ready version or export cursor
- Accept curation push payloads with:
  - idempotency key
  - tenant id
  - expected base version
  - mutation payload
- Track enough backend lineage to reject stale pushes cleanly and to emit future snapshots or deltas aligned with acknowledged curation.
- Add tenant-level policy and audit fields sufficient to support:
  - retention mode visibility
  - export and purge operations
  - retain and purge lifecycle events
  - disposal of no-longer-needed machine working state after projection acknowledgement

## Phased Delivery

### Phase 1: Unified Pipeline Lifecycle -- NOT STARTED

> **Status**: not-started
> **Task plan**: [phase-1-unified-pipeline-lifecycle-task-plan.md](../../tasks/6.0/phase-1-unified-pipeline-lifecycle-task-plan.md)

**Goal**: Present analyze, clustering, and local projection as one durable operator-visible pipeline.

Deliverables:

- Stable linkage from scan jobs to follow-up clustering jobs and projection-ready output.
- A projection acknowledgement step so a backend job is not treated as fully complete until WordPress has ingested the resulting machine state.
- Job status responses and streams that expose pipeline phase and current handoff stage.
- Frontend pipeline state that distinguishes:
  - analyzing,
  - clustering,
  - awaiting local projection,
  - completed,
  - completed with conflicts.

Exit criteria:

- Launching analysis for 500 media items yields a single visible pipeline that advances through clustering and finishes only after projection is available locally.
- Operators do not need to manually infer whether clustering happened on the backend but failed to reach the UI.

### Phase 2: Curation-First Merge Contract -- NOT STARTED

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Make machine projection and local curation merge safely without silent overwrite.

Deliverables:

- Row-level lineage in local cluster and membership tables via projection version and local revision.
- Explicit merge rules for each field and relationship:
  - person assignment,
  - label,
  - curation state,
  - cluster membership,
  - dismissal state.
- Projector logic that auto-applies backend changes only to uncurated records.
- Conflict records for any backend proposal that touches curated entities.
- Tests that cover reclustering against already-curated local clusters and memberships.

Exit criteria:

- Snapshot or replay cannot overwrite curated labels, assignments, merges, splits, or dismissals.
- Backend reclustering of previously curated material is preserved as a machine proposal or conflict record, not as a destructive overwrite.

### Phase 3: Minimal Durable Sync Replay -- NOT STARTED

> **Status**: not-started
> **Task plans**: [v0.2-sovereign-outbox-task-plan.md](../../tasks/4.0/4.13.3/v0.2-sovereign-outbox-task-plan.md), [v0.2-sovereign-drift-reconciliation-task-plan.md](../../tasks/4.0/4.13.3/v0.2-sovereign-drift-reconciliation-task-plan.md)

**Goal**: Make local curation durable offline and replayable when the backend reconnects.

Deliverables:

- Outbox table and repository lifecycle for person, cluster, and membership mutations.
- Idempotent push contract from WordPress to the description service.
- Expected-base-version checks so stale local mutations are rejected cleanly instead of partially applied.
- Retry and dead-letter handling for failed pushes.
- Sync-state reporting that includes pending queue size and last successful acknowledgement.
- Tenant-visible retention metadata and audit reporting that can be surfaced alongside sync health.

Exit criteria:

- Operators can curate while the backend is offline and see those changes locally immediately.
- When connectivity resumes, queued mutations replay exactly once or land in an explicit error or conflict state.
- Operators can inspect whether machine-derived biometric working state is retained, purged, or awaiting disposal after acknowledgement.

### Phase 4: Offline and Conflict UX -- NOT STARTED

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Make stale data, queued work, and conflicts understandable to operators.

Deliverables:

- Sync status UI that distinguishes:
  - backend offline,
  - local changes queued,
  - machine state stale,
  - conflicts requiring review.
- Conflict inbox or review surface for machine proposals blocked by curation.
- Manual resync and replay controls for administrators.
- Dashboard and workbench indicators showing whether the user is looking at a fresh or stale machine baseline.
- Tenant-admin export and purge controls, or admin-visible endpoints, for machine-derived biometric state.
- Operator-visible audit history for retain, export, and purge actions where those actions affect trust in the projected machine baseline.

Exit criteria:

- Operators can tell whether the system is safe to continue using offline.
- Operators can find and resolve any collisions between backend clustering updates and local curation without database intervention.
- The MVP can credibly claim privacy-minimized retention and auditable handling of machine-derived biometric state.

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| Snapshot projector merge contract hardening | Plugin | In progress | Phase 2 exit criteria |
| Outbox and replay transport | Plugin | Not started | Phase 3 exit criteria |
| Curation push endpoint with idempotency and expected-base semantics | Backend | Not started | Phase 3 exit criteria |
| Pipeline-aware job status contract | Backend | In progress | Phase 1 exit criteria |
| Conflict review UX | Frontend | Not started | Phase 4 exit criteria |
| Tenant retention-policy fields and lifecycle audit events | Backend | Not started | Phase 3 and Phase 4 exit criteria |
| Product/privacy messaging for minimized retention | Product | Not started | Phase 4 launch readiness |

## Code Anchors

| Layer | File | Note |
| --- | --- | --- |
| Plugin lifecycle | `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` | Current schema owner for `wp_acx_clusters`, `wp_acx_identity_members`, and `wp_acx_sync_state`; extend for lineage, outbox, and conflict tables |
| Plugin sync | `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Current snapshot merge path; must enforce curation-first field and membership rules |
| Plugin sync | `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php` | Current pull orchestration; must evolve into projection acknowledgement and replay-aware sync |
| Plugin repositories | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | Current cluster merge behavior; add projection version, local revision, and conflict-safe merge semantics |
| Plugin repositories | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php` | Current membership projection path; must distinguish machine rows from curated overrides |
| Plugin repositories | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` | Current coarse sync metadata; extend for queue, acknowledgement, and conflict indicators |
| Plugin API | `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | Current sync status surface; extend with stale, queued, and conflict states |
| Plugin API | `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php` | Cluster curation entrypoint; enqueue durable local operations rather than assuming immediate backend alignment |
| Frontend | `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineEffects.ts` | Current job orchestration hook; continue toward unified pipeline semantics |
| Frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` | Current coarse freshness UI; expand for offline, queued, and conflict states |
| Backend API | `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` | Current job polling and streaming; own unified pipeline job contract |
| Backend config | `apps/prototype-description-service/recognition/config/settings.py` | Add tenant-visible retention defaults and policy controls that support MVP privacy messaging |
| Backend config | `apps/prototype-description-service/recognition/config/security.py` | Extend runtime policy surface for retention, export, and purge behavior |
| Backend worker | `apps/prototype-description-service/recognition/worker/handlers/scan.py` | Current auto-chaining from scan to clustering; must participate in stable pipeline linkage |
| Backend repository | `apps/prototype-description-service/recognition/infrastructure/repositories/job_repository.py` | Current follow-up clustering lookup; extend for pipeline-aware job status and acknowledgement |
| Backend snapshot | `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | Current snapshot export path; extend for proposal lineage, acknowledged curation, and future delta support |
| Backend model | `apps/prototype-description-service/db/models/tenant.py` | Add tenant policy fields needed for retention-mode visibility and auditability |
| Backend model | `apps/prototype-description-service/db/models/identity.py` | Current machine-derived biometric storage; annotate durable vs purgeable state for MVP |
| Backend model | `apps/prototype-description-service/db/models/observability.py` | Add retain, export, and purge audit events tied to operator-visible history |
| Backend HTTP | `apps/prototype-description-service/recognition/interface_adapters/http/router.py` | Mount export, purge, and policy visibility endpoints used by plugin or admin surfaces |

---

# Consolidated Checklist

## Phase 1: Unified Pipeline Lifecycle -- NOT STARTED

- [ ] Link analyze, clustering, and projection under one stable pipeline contract.
- [ ] Surface pipeline phase transitions from backend job APIs and streams.
- [ ] Add projection acknowledgement so backend work is not considered complete before local visibility exists.
- [ ] Update frontend job state handling to respect the unified pipeline contract.

## Phase 2: Curation-First Merge Contract -- NOT STARTED

- [ ] Add projection version and local revision fields to local cluster state.
- [ ] Add projection version and curated override semantics to local membership state.
- [ ] Define field-by-field and relationship-by-relationship merge rules.
- [ ] Record explicit conflicts when backend proposals touch curated entities.
- [ ] Add regression tests for reclustering against curated local state.

## Phase 3: Minimal Durable Sync Replay -- NOT STARTED

- [ ] Add `wp_acx_sync_outbox` and durable local mutation lifecycle.
- [ ] Add idempotent backend curation push endpoint with expected-base checks.
- [ ] Extend sync state with queue size, last acknowledgement, and replay health.
- [ ] Implement retry, dead-letter, and operator-visible failure states.
- [ ] Add tenant-visible retention mode metadata and audit reporting tied to sync status.

## Phase 4: Offline and Conflict UX -- NOT STARTED

- [ ] Expand sync indicators for offline, stale, queued, and conflict states.
- [ ] Add conflict review or inbox UX for machine proposals blocked by curation.
- [ ] Add admin-triggered replay and resync controls.
- [ ] Show local freshness and pending-sync state in dashboard and workbench.
- [ ] Add export and purge controls, or admin-visible endpoints, for machine-derived biometric state.
- [ ] Surface retain, export, and purge audit history where it affects operator trust in the projected state.

## Deferred (Post-v0.2.0)

- [ ] Replace snapshot-heavy sync with richer delta ingest once the MVP replay model is stable.
- [ ] Add backend-side storage and API support for first-class machine proposals separate from committed cluster state.
- [ ] Add richer operator tooling for merge-preview and proposal acceptance workflows.
- [ ] Explore tenant-level sovereignty tiers where WordPress becomes the authoritative long-term store for embeddings and machine proposals.
- [ ] Add customer-controlled embedding authority, ephemeral compute APIs, and sovereignty-tier deployment modes.
- [ ] Add tenant-level encryption, key-management hooks, and region-pinning compliance features.
