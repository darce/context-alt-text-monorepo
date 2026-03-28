# Sovereign Sync Expansion + Workbench UX Continuation (Follow-On Epic)

## Status

Closed. All items either delivered under v0.2.0 task plans or moved to [sync-completion-and-retention-hardening-epic (v0.3.1)](../v0.3.1/sync-completion-and-retention-hardening-epic.md).

## Objective

Implement the next sovereign sync architecture layer and close remaining product-surface UX gaps that go beyond the reliability baseline established in [production-readiness-epic.md](../v0.3.1/production-readiness-epic.md).

This epic owns:

- Sovereign sync architecture expansion:
  - outbox,
  - Action Scheduler migration,
  - delta ingest,
  - drift reconciliation,
  - representative pin/unpin replay parity,
  - deferred compound conflict acceptance for `cluster_merged`,
  - bidirectional conflict resolution for person-name edits.
- Product-surface UX changes that are not reliability-critical but improve day-to-day curation and administration:
  - Batch tab retirement or re-homing under Dashboard IA.
  - Previous/next media navigation controls (top-of-page).
  - Roster CRUD operations and Entries vs Clusters information architecture clarity.
  - Dashboard page buildout with live data.

## Relationship to Production-Readiness Epic

The later [production-readiness-epic.md](../v0.3.1/production-readiness-epic.md) Phase 1 now owns all **frontend-only reliability fixes**, specifically:

| Item                                        | Owned By                      | Rationale                                |
| ------------------------------------------- | ----------------------------- | ---------------------------------------- |
| Error Boundaries (AP-1)                     | production-readiness Phase 1a | Reliability: crash prevention            |
| "Saving..." hang fix (AP-2)                 | production-readiness Phase 1a | Reliability: bounded mutation lifecycle  |
| Non-disruptive scan complete (AP-3)         | production-readiness Phase 1a | Reliability: user context preservation   |
| URL-synced tabs and pagination (AP-4, AP-5) | production-readiness Phase 1b | Reliability: navigation state continuity |
| Scroll restoration (AP-4)                   | production-readiness Phase 1b | Reliability: navigation state continuity |
| SyncStatusIndicator above tabs (PG-1)       | production-readiness Phase 1c | Reliability: sync visibility             |
| WorkbenchPage decomposition (AP-6, AP-7)    | production-readiness Phase 1c | Reliability: structural maintainability  |

This follow-on epic captures **product expansion** and **architecture evolution** that should be tracked now but not block the v0.2.0 production baseline.

## Sources and Inputs

- [production-readiness-epic.md](../v0.3.1/production-readiness-epic.md)
- [roadmap-v3.hybrid.md](../../roadmaps/roadmap-v3.hybrid.md)
- [v0.2-sovereign-outbox-task-plan.md](../../tasks/4.0/4.13.3/v0.2-sovereign-outbox-task-plan.md)
- [v0.2-sovereign-action-scheduler-task-plan.md](../../tasks/4.0/4.13.3/v0.2-sovereign-action-scheduler-task-plan.md)
- [v0.2-sovereign-delta-ingest-task-plan.md](../../tasks/4.0/4.13.3/v0.2-sovereign-delta-ingest-task-plan.md)
- [v0.2-sovereign-drift-reconciliation-task-plan.md](../../tasks/4.0/4.13.3/v0.2-sovereign-drift-reconciliation-task-plan.md)

## Scope

### Track A: Sovereign Sync Expansion

- Outbox table and operation lifecycle for mutation durability and replay.
- Action Scheduler-backed job execution model for retries, backoff, and dead-letter handling.
- Delta ingest contract to reduce full snapshot dependency for routine sync.
- Drift reconciliation flow for long-outage or mismatch recovery.
- Representative projection and pin/unpin replay parity.
- Deferred compound conflict acceptance for `cluster_merged` once payload provenance is available.
- Bidirectional conflict resolution for person-name edits.

### Track B: Workbench UX Continuation (Product Expansion)

**Prerequisite**: production-readiness Phase 1 must be complete (error boundaries, URL-synced tabs, WorkbenchPage decomposition). This track builds on that structural foundation.

- Batch tab retirement or migration to Dashboard IA.
- Dual-position media detail navigation controls (top and bottom).
- Roster CRUD operations (create/edit/delete entries).
- Roster information architecture and copy clarity ("Entries" vs "Clusters").
- Dashboard page buildout with live coverage data and navigation shortcuts.

## Non-Goals

- Dashboard analytics implementation details beyond what is required to re-home Batch functionality.
- LLM alt-text generation workflow.
- Replacing sovereign local-read model or curation-first precedence.

## Phased Plan

### Phase A1: Outbox + Scheduler Foundation

Deliverables:

- Outbox schema and repository layer.
- Action Scheduler worker orchestration with retry/backoff/dead-letter.
- Operator-visible operation status fields for failed/replayed mutations.

Exit criteria:

- User mutations are durable offline and replay when backend is reachable.
- Failed operations are inspectable and retryable.

### Phase A2: Delta and Drift

Deliverables:

- Delta ingest endpoint and consumer path.
- Snapshot fallback path retained for bootstrap/recovery.
- Drift detection and reconciliation queue with explicit user-safe conflict policy.

Exit criteria:

- Routine sync payloads are materially reduced versus full snapshot.
- Drift can be detected and reconciled without destructive overwrite of curation decisions.

### Phase B1: Dashboard + Batch IA Migration

**Prerequisite**: production-readiness Phase 1c (WorkbenchPage decomposition, SyncStatusIndicator above tabs).

Deliverables:

- Dashboard page with live coverage summary (media analyzed %, identities identified, clusters pending review).
- Batch functionality migrated from standalone Workbench tab to Dashboard "Recent Jobs" or "Queue" section.
- Batch tab removed from Workbench; tab count reduced from 3 to 2 (Scan, Confirm).
- Migration telemetry: track whether users look for batch in old location.

Exit criteria:

- Batch workflows are discoverable from Dashboard without a dedicated tab.
- WorkbenchPage has only 2 tabs with a cleaner mental model.
- Dashboard renders live data, not placeholder copy.

### Phase B2: Roster CRUD + Navigation Polish

**Prerequisite**: production-readiness Phase 1b (URL-synced tabs, scroll restoration).

Deliverables:

- Roster Entries tab: add create, edit, delete operations (API + UI).
- Roster copy contract: explicit "Entries" vs "Clusters" terminology with empty/loading/error/populated states.
- Top-of-page previous/next navigation controls on media detail pages (when detail is surfaced in-SPA or via query param handoff).

Exit criteria:

- Operators can manage roster entries (CRUD) from the Roster page.
- Operators can explain the difference between configured identities and inferred clusters from the UI alone.
- Media detail navigation cursors appear at top and bottom of page.

## Code Anchors

| Layer                 | File/Area                                                                         | Note                                                      |
| --------------------- | --------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Plugin sync           | `apps/prototype-wp-alt-context/src/sovereign/sync/`                               | Outbox, scheduler, replay, reconciliation                 |
| Plugin API            | `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php`          | Sync status semantics and UX-facing state                 |
| Frontend workbench    | `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`                  | Tab removal after Phase 1c decomposition                  |
| Frontend dashboard    | `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx`                  | Static placeholder -- needs live data buildout            |
| Frontend roster       | `apps/prototype-wp-alt-context/js/admin/pages/roster/`                            | Entries CRUD, clusters rendering/copy                     |
| Frontend roster hooks | `apps/prototype-wp-alt-context/js/admin/pages/roster/hooks/`                      | useClusterActions, useClusterDragDrop, useClusterMediaMap |
| Roster API            | `apps/prototype-wp-alt-context/js/admin/api/rosterApi.ts`                         | Roster data fetching layer                                |
| Backend API           | `apps/prototype-description-service/recognition/interface_adapters/http/routers/` | Delta/snapshot ingest endpoints                           |

## Consolidated Checklist

### Track A: Sync Architecture

- [x] Implement outbox schema + lifecycle.
- [x] Migrate async sync execution to Action Scheduler.
- [x] Implement delta ingest path with snapshot fallback. -- Moved to [sync-completion-and-retention-hardening-epic (v0.3.1)](../v0.3.1/sync-completion-and-retention-hardening-epic.md) Phase 1.
- [x] Implement drift reconciliation flow and conflict-safe replay policy. -- Moved to [sync-completion-and-retention-hardening-epic (v0.3.1)](../v0.3.1/sync-completion-and-retention-hardening-epic.md) Phase 2.
- [x] Implement representative projection and pin/unpin replay parity. -- Delivered.
- [x] Complete `cluster_merged` accept-machine revert contract with moved-member provenance. -- Delivered.
- [x] Implement bidirectional conflict resolution for person-name edits. -- Delivered.

### Track B: Workbench UX Continuation

- [x] Build Dashboard page with live coverage data.
- [x] Migrate Batch functionality from Workbench tab to Dashboard.
- [x] Remove Batch tab from Workbench (reduce to Scan + Confirm).
- [x] Add Roster Entries CRUD operations (create, edit, delete).
- [x] Clarify Entries vs Clusters in UI copy and structure.
- [x] Add top-of-page previous/next media navigation controls.
