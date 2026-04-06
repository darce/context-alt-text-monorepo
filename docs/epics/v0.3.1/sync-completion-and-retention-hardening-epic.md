# E16. Sync Completion and Retention Hardening (v0.4.0)

> **Epic Short ID**: E16

## Objective

Close the remaining sync and retention hardening gaps carried forward from v0.2.0. When this epic is complete, the system hardens the already-landed incremental delta path with explicit contract coverage and deletion semantics, detects and reconciles drift between local and remote state, propagates retention export version metadata consistently across backend and WordPress boundaries, and tracks embedding-level disposal for fine-grained audit compliance.

## Problem Statement

The v0.2.0 epics delivered the core sync pipeline (snapshot projector, outbox drain, conflict resolution), retention controls (policy, export, purge, audit), and the full suggestion/proposal lifecycle. Four hardening items remain unfinished:

1. **Delta sync is implemented but under-contracted.** The backend and WordPress delta path already exist, but the remaining hardening gaps are explicit shared-contract coverage, deletion/tombstone semantics, and clearer fallback/repair behavior when a delta chain becomes invalid.
2. **Drift reconciliation does not exist.** If local projected state diverges from the recognition service (e.g., a missed outbox drain, a failed partial sync), there is no mechanism to detect or correct the divergence.
3. **Export version metadata is inconsistent across boundaries.** Retention exports already carry backend `schema_version`, but the version contract is not yet treated as a first-class shared boundary across the HTTP envelope, WordPress proxy layer, and shared contracts.
4. **Embedding disposal is bulk-only.** Embeddings are deleted as part of cluster/snapshot purge operations. There is no per-embedding disposal audit trail, which limits fine-grained compliance reporting.

## UX Vision

- Operators see noticeably faster sync cycles because only changed data is transferred after the initial snapshot, with explicit visibility when the system falls back to a full snapshot.
- If local state drifts from the recognition service, the admin dashboard surfaces a reconciliation prompt with a clear diff of what diverged and a one-click repair action.
- Exported retention archives include a machine-readable version header that is consistent across backend payloads, API responses, and WordPress consumers so future tooling can parse or migrate them automatically.
- The audit timeline can show embedding-level disposal events alongside cluster and identity events, giving privacy officers a complete chain of custody.

## Constraints

- Greenfield project; no backward-compatibility obligation for older export consumers, but the existing `schema_version` convention must be handled explicitly rather than silently replaced.
- Delta ingest must degrade gracefully to a full snapshot pull when the delta chain is broken or the backend rejects a stale cursor.
- Drift reconciliation must not auto-correct without operator confirmation; surface a proposal and wait for explicit acceptance.
- Embedding disposal tracking must not materially degrade purge throughput for large tenants.

## Terminology

- **Delta ingest**: An incremental sync path where only records changed since the last acknowledged cursor are transferred, instead of pulling the full snapshot.
- **Drift reconciliation**: A detection and repair mechanism that compares projected local state against the recognition service and surfaces divergences for operator action.
- **Export format versioning**: A schema version header embedded in retention export payloads so consumers can detect and handle format changes.
- **Embedding-level disposal**: Granular audit logging of individual vector embedding deletions during purge operations, as opposed to bulk cluster-level logging only.

## Current State

- Snapshot-based sync works end-to-end (pull, project, outbox drain, conflict resolution).
- Delta sync also works end-to-end today: the backend repository and API expose `get_delta`, WordPress fetches delta first, and the projector merges delta payloads into local state. The remaining gap is hardening, not first implementation.
- No drift detection or reconciliation logic exists anywhere in the codebase.
- Retention export (`POST /retention/export`, status polling, data retrieval) is fully functional and already emits integer `schema_version`, but the version contract is not yet formalized and propagated consistently as a named cross-boundary requirement.
- Purge operations delete embeddings in bulk alongside their parent clusters; audit events record cluster-level disposal but not individual embedding disposal.

## v0.2.0 Audit Trail

This epic consolidates the genuinely open items discovered during a full audit of the five v0.2.0 epics. The audit verified every unchecked checklist item against the current codebase. Items that were implemented but never checked off have been closed in this audit; only the items below remain.

| v0.2.0 Epic                                              | Open Item                                | Disposition                      |
| -------------------------------------------------------- | ---------------------------------------- | -------------------------------- |
| `remaining-sync-workbench-and-retention-epic.md` Phase 1 | Delta ingest path with snapshot fallback | Carried forward; Phase 1         |
| `remaining-sync-workbench-and-retention-epic.md` Phase 1 | Drift reconciliation                     | Carried forward; Phase 2         |
| `remaining-sync-workbench-and-retention-epic.md` Phase 6 | Export format versioning and import      | Carried forward; Phase 3         |
| `remaining-sync-workbench-and-retention-epic.md` Phase 6 | Embedding-level disposal tracking        | Carried forward; Phase 4         |
| `sovereign-sync-and-workbench-ux-epic.md` Track A        | Delta ingest                             | Duplicate of above; consolidated |
| `sovereign-sync-and-workbench-ux-epic.md` Track A        | Drift reconciliation                     | Duplicate of above; consolidated |
| `recognition-ux-and-ergonomics-epic.md` Deferred         | Delta ingest and drift reconciliation    | Duplicate of above; consolidated |

### v0.2.0 items verified as IMPLEMENTED (now closed)

All autonomous-lane-orchestration items (review_runner, lane_exec, worker/orchestrator daemons, per-lane locking, lane-close/prune, auto-close after intake). All recognition-state-reconciliation Phase 5 items (retention policy service, audit events, export/purge endpoints, enforcement, WP retention controller, RetentionPage UI, AuditTimeline). All remaining-sync Phases 2-5 (representative pin/unpin through outbox, cluster_merged accept-machine revert with moved-member provenance, bidirectional conflict resolution, workbench IA, suggestion tables/endpoints/WP proxy/frontend hooks). All remaining-sync cross-cutting worktree lane lifecycle (close, prune, MCP tool, auto-close). All sovereign-sync Track A conflict resolution and representative pin/unpin. All sovereign-sync Track B batch migration and tab removal. Async export, scheduled disposal worker, retention presets, audit event listing endpoint.

## Target Architecture

### Delta Ingest Hardening

The WordPress sync client already has a cursor-based delta path alongside the existing full-snapshot path. The remaining work is to formalize the delta contract, make fallback semantics explicit, and ensure edge cases like deletions and stale cursor recovery are observable and testable. The outbox drain and conflict resolution pipelines remain unchanged; they consume projected state regardless of how it was ingested.

### Drift Reconciliation

A new reconciliation service compares a checksum or fingerprint of the local projected state against one computed by the recognition service. When divergence is detected, the service produces a structured diff (added, removed, modified records) and surfaces it in the admin dashboard as a reconciliation proposal. The operator can accept the proposal (which triggers a corrective sync) or dismiss it. Drift checks run on a configurable schedule or on-demand.

### Export Version Metadata

Retention export payloads already include top-level integer `schema_version`. The remaining work is to make that version field a first-class shared contract across the backend payload, HTTP response envelope, and WordPress proxy layer. For v0.3.0, the priority is consistent propagation and contract ownership, not inventing a second parallel version field. Multi-version import migration remains deferred.

### Embedding-Level Disposal

The purge service records a disposal audit event for each embedding vector deleted, including the embedding ID, parent cluster/snapshot reference, disposal timestamp, and acting policy. These events flow into the same audit timeline used for cluster-level events. A batch-insert pattern keeps throughput acceptable for large purge operations.

### Design Decisions

| Decision                                                                                                       | Rationale                                                                                                          |
| -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Delta ingest falls back to full snapshot on chain break                                                        | Avoids complex cursor repair logic; full snapshot is already proven                                                |
| Drift reconciliation requires operator confirmation                                                            | Automatic correction could mask upstream bugs; operator trust requires visibility                                  |
| Export version stays on the existing `schema_version` field unless an explicit schema migration says otherwise | Avoids inventing a duplicate `format_version` field and keeps the boundary honest about the current implementation |
| Embedding disposal uses batch audit inserts                                                                    | Per-row insert would degrade purge throughput for tenants with millions of embeddings                              |

### Data Model

- **Delta cursor**: stored in `acx_sync_state` (WP options or sync_state table); canonical source is the recognition service's last-seen sequence number.
- **Drift fingerprint**: computed by both sides from sorted record hashes; compared at reconciliation time.
- **Export schema_version**: integer field in the export payload and the downloaded archive metadata; must also be surfaced consistently through the HTTP response envelope and WordPress proxy layer.
- **Embedding disposal events**: rows in the existing `audit_events` table with `event_type = 'embedding_disposed'` and embedding-specific data in the `payload` JSONB column (embedding ID, parent cluster/member references).

## Phased Delivery

### Phase 1: Delta Ingest Hardening -- planned

> **Status**: planned
> **Task plans**: not yet scoped

**Goal**: Harden the already-landed delta path with explicit contracts, deletion semantics, and repair visibility.

Deliverables:

- Formalize the existing draft delta contract (`docs/agentic/contracts/cluster-delta-api.md`) to stable status and add a companion JSON schema to `packages/shared-contracts/schemas/`
- Explicit fallback semantics for stale cursor / broken chain (i.e., when the server cannot produce a delta from the client's `since_version` because the version is too old or the delta log has been pruned), including whether this stays distinct from generic fallback-to-snapshot
- Deletion/tombstone semantics for delta payloads, or an explicit rule that deletions require snapshot fallback
- Cursor acknowledgement lifecycle documented and tested end to end
- Tests for delta happy path, chain break fallback, first-sync (no cursor), and the chosen deletion semantics

Exit criteria:

- The existing delta path has a shared contract and explicit fallback semantics
- Chain break triggers automatic full-snapshot fallback without operator intervention
- Round-trip integration test passes with delta and fallback scenarios, including the chosen deletion/tombstone behavior

### Phase 2: Drift Reconciliation -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Detect and surface divergence between local projected state and recognition service state.

Deliverables:

- Fingerprint computation on both backend and WordPress sides
- Reconciliation service that compares fingerprints and produces a structured diff
- Admin dashboard reconciliation prompt with diff display and accept/dismiss actions
- Configurable reconciliation schedule owned by WordPress (configured via WP admin settings, executed via WP cron triggering a backend fingerprint comparison endpoint; the backend provides the computation endpoint, WordPress owns the schedule)
- Shared contract for the fingerprint comparison payload and reconciliation diff surface

Exit criteria:

- Intentionally introduced drift is detected and surfaced in the admin UI
- Accepting a reconciliation proposal corrects the local state to match the service
- Dismissing a proposal suppresses the prompt until the next scheduled check

### Phase 3: Export Version Metadata Hardening -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Make the existing export version field a consistent shared contract across backend, HTTP, and WordPress boundaries.

Deliverables:

- Decide whether the existing integer `schema_version` remains canonical or whether a renamed field requires an explicit schema migration
- Propagate the chosen version field through export service output, the export job response schema, and the WordPress retention controller proxy
- Add contract definition for the versioned export format in shared contracts
- Export API and WordPress proxy tests verify the version field is present and correct

Exit criteria:

- Every new export payload and cross-boundary response carries the agreed version field
- Export API and WordPress proxy tests fail if the version field is missing

### Phase 4: Embedding-Level Disposal Tracking -- not-started

> **Status**: not-started
> **Task plans**: not yet scoped

**Goal**: Record per-embedding disposal audit events during purge operations.

Deliverables:

- Purge service updated to emit per-embedding audit events using batch inserts
- Audit event schema extended with `embedding_disposed` event type and embedding-specific payload
- Audit timeline UI displays embedding disposal events
- Performance benchmark confirming purge throughput stays within acceptable bounds

Exit criteria:

- Purging a cluster with N embeddings produces N audit events (one per embedding)
- Audit timeline shows embedding disposal events with parent references
- Purge throughput for a 10K-embedding tenant stays within 2x of current bulk-only performance

## External Dependencies

| Dependency                                                                                                     | Owner      | Status                                                                                                                                                                | Blocks           |
| -------------------------------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| Shared delta and export contract definitions across `docs/agentic/contracts/` and `packages/shared-contracts/` | Backend    | Human-readable delta draft exists at `docs/agentic/contracts/cluster-delta-api.md`; machine-readable shared-contract schemas for delta and export are not started yet | Phase 1, Phase 3 |
| WordPress hardening work for delta fallback and export-version propagation                                     | PHP Plugin | Not started                                                                                                                                                           | Phase 1, Phase 3 |

## Review Path

- Phase 1: cross-boundary branch review with backend/PHP contract focus
- Phase 2: cross-boundary review plus release-style multi-lens audit because it adds a new reconciliation surface across backend, PHP, and UI
- Phase 3: cross-boundary branch review with contract and retention-boundary focus
- Phase 4: cross-boundary branch review (backend purge service, audit persistence, WordPress audit timeline UI) plus targeted performance evidence review for purge throughput

## Code Anchors

| Layer                    | File                                                                                              | Note                                                                                                                                                                                      |
| ------------------------ | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend delta tests      | `apps/prototype-description-service/recognition/tests/unit/test_cluster_repository_delta_stub.py` | Existing integration tests for the working `get_delta()` path; filename is stale but coverage is real                                                                                     |
| Backend retention router | `apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py`     | Export endpoints to propagate the agreed version field through the HTTP envelope                                                                                                          |
| Backend export service   | `apps/prototype-description-service/recognition/domain/services/export_service.py`                | Async export already emits `schema_version`; Phase 3 decides and propagates the canonical version field                                                                                   |
| Backend purge service    | `apps/prototype-description-service/recognition/domain/services/purge_service.py`                 | Purge logic to emit per-embedding events                                                                                                                                                  |
| Backend audit service    | `apps/prototype-description-service/recognition/domain/services/audit_service.py`                 | Audit event recording                                                                                                                                                                     |
| WP sync pull job         | `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php`                        | Phase 1 fallback-to-snapshot behavior lives here via `try_delta_sync()`; this is the primary WordPress owner for delta fetch/fallback semantics                                           |
| WP sync client contract  | `apps/prototype-wp-alt-context/src/sovereign/sync/interface-snapshot-client.php`                  | Defines `fetch_delta()` and acknowledgement semantics that Phase 1 hardens alongside the backend delta contract                                                                           |
| WP sync projector        | `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php`                   | Projector already implements `project_delta()`; keep this anchor for merge/application behavior after the fetch/fallback path succeeds                                                    |
| WP sync state            | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php`        | Snapshot version storage (also used as delta `since_version` cursor); Phase 1 may extend with explicit delta cursor methods if acknowledgement semantics diverge from snapshot versioning |
| WP retention controller  | `apps/prototype-wp-alt-context/src/api/class-retention-controller.php`                            | Export proxy to forward version field                                                                                                                                                     |
| Frontend audit timeline  | `apps/prototype-wp-alt-context/js/admin/pages/retention/AuditTimeline.tsx`                        | UI to display embedding disposal events                                                                                                                                                   |

---

# Consolidated Checklist

## Phase 1: Delta Ingest Hardening -- planned

- [ ] Formalize existing draft delta contract and add JSON schema to `packages/shared-contracts/`
- [ ] Document and test explicit chain-break / fallback semantics
- [ ] Define and test delta deletion/tombstone behavior or explicit snapshot-fallback rule
- [ ] Document and test cursor acknowledgement lifecycle
- [ ] Add/extend tests: delta happy path, chain break fallback, first-sync no-cursor, deletion semantics

## Phase 2: Drift Reconciliation -- not-started

- [ ] Implement fingerprint computation on backend
- [ ] Implement fingerprint computation on WordPress side
- [ ] Build reconciliation service with structured diff output
- [ ] Add shared contract definition for fingerprint comparison and reconciliation diff payloads
- [ ] Add admin dashboard reconciliation prompt component
- [ ] Wire accept/dismiss actions to corrective sync / suppression
- [ ] Add configurable reconciliation schedule
- [ ] Add tests: drift detection, acceptance corrects state, dismissal suppresses

## Phase 3: Export Version Metadata Hardening -- not-started

- [ ] Decide whether existing integer `schema_version` remains canonical or whether an explicit schema migration introduces a renamed field
- [ ] Propagate the canonical version field through export service output and the HTTP response envelope
- [ ] Update the WordPress retention controller proxy to preserve the canonical version field
- [ ] Add contract definition for the versioned export format in `packages/shared-contracts/`
- [ ] Add tests: version field present in every export payload and proxy response

## Phase 4: Embedding-Level Disposal Tracking -- not-started

- [ ] Extend audit events with `embedding_disposed` event type and embedding-specific payload
- [ ] Update purge service to emit per-embedding audit events (batch inserts)
- [ ] Update audit timeline UI to display embedding disposal events
- [ ] Add performance benchmark for purge throughput with per-embedding logging
- [ ] Add tests: per-embedding events created, parent references correct

## Deferred (Post-v0.3.0)

> Expanded rationale and activation criteria: [docs/deferred-features/retention-and-audit-stretch.md](../../../docs/deferred-features/retention-and-audit-stretch.md)

- [ ] Multi-version export import migration (read older format versions and upgrade on import)
- [ ] GDPR-specific retention policy presets (right-to-erasure workflow beyond disposal)
- [ ] Paginated full audit event log with advanced filtering (current timeline is sufficient for MVP)
