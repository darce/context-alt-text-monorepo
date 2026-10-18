# Roadmap v4 -- Face Recognition UX and Plugin Ergonomics

> **Status:** Active -- Epics A-C complete, Epic D in progress.
> **Predecessor:** [roadmap-v3.hybrid.md](roadmap-v3.hybrid.md) (core vision, closed), [v0.1.0 Sovereign Cluster Epic](../epics/v0.1.0/wp-sovereign-cluster-epic.md) (completed), [v0.3.1 Production Readiness Epic](../epics/v0.3.1/production-readiness-epic.md) (tracked)

---

## Objective

Evolve the plugin from a functional recognition prototype into a polished face-management tool that non-technical WordPress admins can operate confidently. The focus is on three product pillars: (1) a usable face roster CRUD for managing recognized identities, (2) a dashboard that provides actionable coverage insights, and (3) recognition UX refinements that close the gap between "working demo" and "trustworthy product."

## Problem Statement

The v0.1.0/v0.2.0 releases established the sovereign data model and reliability baseline, but the admin experience is incomplete:

- **Roster is read-only.** Admins cannot create, edit, rename, or delete roster entries from the UI. The only mutation path is the cluster commit flow, which is discovery-dependent.
- **Dashboard is a static placeholder.** It shows coverage stats and quick-action links but no live cluster/identity data, no pending-review counts, and no guidance on what to do next.
- **Recognition UX has friction.** Cluster labeling works but lacks bulk actions, keyboard shortcuts, inline search for existing roster entries during labeling, and clear disambiguation between "Entries" (operator-curated identities) and "Clusters" (system-inferred groupings).
- **Sync architecture is snapshot-only.** Full-snapshot sync is functional but does not scale; outbox, delta ingest, and drift reconciliation are documented but unimplemented.

## Constraints

- **Greenfield policy**: no production users. Clean rewrites preferred over long-lived compatibility shims; legacy local options (if present) use one-time import-and-retire cutover.
- **Plugin boundary rule**: only monorepo-managed code changes. No WordPress core, LocalWP, or system config edits.
- **Curation-first precedence**: user curation decisions override backend suggestions unconditionally. Roster CRUD operations are curation and must be treated as ground truth.
- **Sovereign model preservation**: local-read behavior cannot regress. Dashboard and roster must render from local projection, not live backend.
- **Self-hostable backend**: backend runs on low-cost ARM VPS. No GPU dependency for core flows.
- **Phase 1 UX reliability is prerequisite**: error boundaries, URL-synced tabs, WorkbenchPage decomposition (from production-readiness Phase 1) must be complete before product expansion begins.

## Terminology

- **Person**: an operator-curated identity record (name, optional tags, optional reference photo). Created manually or via cluster commit. Stored in `wp_acx_persons`. See [ADR-002](../adrs/ADR-002-person-as-first-class-local-entity.md).
- **Cluster**: a system-inferred grouping of visually similar faces. Stored in `wp_acx_clusters`. May be unlabeled (pending review) or assigned to a person.
- **Commit/Assign**: the action of assigning a cluster to a person, confirming the system's grouping as correct.
- **Label derivation**: when a cluster has a `person_id`, its display label is the person's name. When unassigned, the cluster shows its backend-assigned label (e.g. "Person N").
- **Coverage**: the percentage of media library items that have alt text populated.
- **Pending review**: clusters that the system has formed but the operator has not yet confirmed or dismissed.
- **Roster page**: the admin UI page where persons and clusters are managed (the page is called "Roster"; the entity is called "Person").

## Current State

### Confirmed Complete (v0.1.0 + v0.2.0 Phase 1)

- Sovereign local-first read path.
- Snapshot sync with curation-first conflict policy.
- TanStack React Query with centralized key factory.
- Error boundaries at route and cluster-module level.
- URL-synced tabs and scroll restoration.
- WorkbenchPage decomposed into tab content components.
- SyncStatusIndicator visible on all workbench tabs.
- "Saving..." hang fixed; scan-complete no longer force-navigates.

### Current Gaps

- Persons stored as flat `acx_roster_entries` WP option (not a table). No CRUD endpoints beyond list and commit.
- `acx_roster_assignments` WP option stores cluster-to-entry mappings separately from the option list -- a dual source of truth with no reconciliation path.
- `RosterEntriesTable` is a read-only table with no action column.
- `DashboardPage` has coverage stats and quick-action cards but no cluster/identity counts, no pending-review summary, no "what to do next" guidance.
- `ClusterDrawerPanel` receives 20+ props via drilling (not yet contextified despite Phase 1c improvements).
- No inline person search/autocomplete during cluster labeling.
- No bulk cluster actions (merge multiple, dismiss multiple).
- "People" vs "Clusters" distinction is not explained in the UI.
- Sync is full-snapshot only; no outbox, delta, or drift reconciliation.
- Backend has no `roster_entries` table; `identity_clusters.roster_id` column exists but is non-functional.

## Target Architecture

### Design Decisions

| Decision                                                | Rationale                                                                                                                                                                                                                                            |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Person is a first-class local entity (`wp_acx_persons`) | Person provides identity stability across cluster lifecycle (merges, splits, re-clustering). Option storage does not support indexing, pagination, or relational integrity. See [ADR-002](../adrs/ADR-002-person-as-first-class-local-entity.md). |
| Label derivation, not duplication                       | When `person_id IS NOT NULL`, cluster display label = person name. No dual source of truth for names.                                                                                                                                                |
| Person CRUD is 100% local (no backend proxy)            | Person is a curation concern owned by the plugin. Create/rename/delete happen in plugin tables only. Sync to backend `roster_id` is a separate concern (Epic D).                                                                                     |
| `acx_roster_assignments` option retired                 | The assignment IS the `person_id` FK on `wp_acx_clusters`. No separate mapping needed.                                                                                                                                                               |
| Dashboard reads local projection only                   | Sovereign model -- dashboard never depends on live backend. Coverage, cluster counts, pending-review counts all derive from local tables.                                                                                                            |
| Inline person search uses local data                    | Autocomplete during cluster labeling queries local persons, not backend. Fast and offline-resilient.                                                                                                                                                 |
| Bulk actions are frontend-only orchestration            | Multi-select + batch mutation reuses existing single-item mutation hooks. No new backend endpoints.                                                                                                                                                  |

### Data Model Evolution

**New table: `wp_acx_persons`** ([ADR-002](../adrs/ADR-002-person-as-first-class-local-entity.md))

| Column                 | Type                  | Note                                    |
| ---------------------- | --------------------- | --------------------------------------- |
| `id`                   | BIGINT AUTO_INCREMENT | Primary key (local FK target)           |
| `person_uuid`          | CHAR(36)              | Stable sync identifier (UUID v4, unique) |
| `name`                 | VARCHAR(255)          | Display name (unique)                   |
| `tags`                 | TEXT (JSON)           | Optional categorization tags            |
| `reference_thumb_path` | VARCHAR(512)          | Optional representative face thumbnail  |
| `cluster_count`        | INT                   | Denormalized count of assigned clusters |
| `created_at`           | DATETIME              |                                         |
| `updated_at`           | DATETIME              |                                         |

Indexes/constraints: `UNIQUE KEY idx_name (name)`, `UNIQUE KEY idx_person_uuid (person_uuid)`.

**Modified table: `wp_acx_clusters`** -- add `person_id BIGINT UNSIGNED DEFAULT NULL` (logical FK to `wp_acx_persons.id`, no hard constraint per dbDelta limitations).

**Label derivation rule**: when `person_id IS NOT NULL`, cluster display label = `wp_acx_persons.name`. When `NULL`, cluster shows its own `label` column (backend-assigned "Person N").

**Legacy option cutover policy**: `acx_roster_entries` and `acx_roster_assignments` are retired after one-time import (if present) into `wp_acx_persons` + `wp_acx_clusters.person_id`.

## Phased Delivery

### Epic A: Person CRUD Tool

> **Epic**: [recognition-ux-and-ergonomics-epic.md](../epics/v0.2.0/recognition-ux-and-ergonomics-epic.md) Phase 1-2
> **Scope**: Full CRUD for persons -- create, read, update, delete.

**Goal**: Admins can manage known identities directly, without relying on cluster discovery as the only entry point.

Deliverables:

- Create `wp_acx_persons` table with `dbDelta`. Retire `acx_roster_entries` and `acx_roster_assignments` WP options.
- Add `person_id` column to `wp_acx_clusters`.
- Add `person_uuid` generation + uniqueness guarantees in `wp_acx_persons` for backend sync contract.
- REST API endpoints: `POST /acx/v1/roster/persons`, `PUT /acx/v1/roster/persons/{id}`, `DELETE /acx/v1/roster/persons/{id}`.
- `RosterEntriesTable` gains action column: edit (inline or modal), delete (with confirmation).
- "Add Person" button above the table.
- "People" vs "Clusters" explanatory copy in Roster page header and empty states.
- Label derivation: assigning a person to a cluster sets the cluster's display label to the person's name.

Exit criteria:

- Operator can create, rename, tag, and delete persons from the Roster page.
- Deleting a person does not destroy associated clusters (soft dissociation: `person_id` set to NULL, cluster reverts to backend label).

### Epic B: Dashboard Buildout

> **Epic**: [recognition-ux-and-ergonomics-epic.md](../epics/v0.2.0/recognition-ux-and-ergonomics-epic.md) Phase 3
> **Scope**: Replace static placeholder dashboard with live data and actionable guidance.

**Goal**: Dashboard is the admin's home base -- it answers "what's the state of my library?" and "what should I do next?"

Deliverables:

- **Coverage panel** (exists): total media, missing alt text, coverage %. Add: "with faces detected" count.
- **Identity panel** (new): person count, assigned cluster count, pending-review cluster count.
- **Action guidance** (new): contextual "next step" card. Examples: "You have 12 clusters pending review" with link to Confirm tab; "3 persons have no assigned clusters" with link to Roster.
- **Recent activity** (enhance): show last 5 recognition jobs with status, duration, and link to results.
- All data reads from local projection (sovereign) and WordPress-local metadata only.
- Dashboard scope is Alt Context plugin data only; do not aggregate or store telemetry for other installed plugins.

Exit criteria:

- Dashboard renders live cluster and identity counts from local projection tables.
- "What to do next" guidance updates dynamically based on pending-review count.
- Dashboard loads in < 500ms from local DB (no backend dependency).

### Epic C: Recognition UX Polish

> **Epic**: [recognition-ux-and-ergonomics-epic.md](../epics/v0.2.0/recognition-ux-and-ergonomics-epic.md) Phase 4
> **Scope**: Bulk cluster actions, keyboard shortcuts, and labeling flow improvements.

**Goal**: Reduce friction in the cluster review and labeling workflow for operators processing large batches.

Deliverables:

- Multi-select clusters in ClusterGrid (checkbox or Shift+click).
- Bulk merge: merge selected clusters into one.
- Bulk dismiss: dismiss selected clusters as not-a-face or not-relevant.
- Keyboard navigation in cluster grid and drawer (arrow keys, Enter to open, Escape to close).
- Inline person search/autocomplete in cluster labeling flow (combobox with local data).
- Cluster drawer: show face count, confidence range, and cluster age.
- Toast notifications for mutation outcomes (merge, split, reassign, commit).

Exit criteria:

- Operator can select 5 clusters and merge them in one action.
- Cluster grid is fully navigable via keyboard.
- Cluster labeling combobox offers existing persons as suggestions.
- Every mutation (merge, split, reassign, commit, dismiss) shows a toast confirmation.

### Epic D: Sovereign Sync Evolution (Deferred)

> **Scope**: Outbox, Action Scheduler, delta ingest, drift reconciliation, person UUID sync to backend `roster_id`.
> **Prerequisite**: Person CRUD and dashboard must be stable before sync architecture changes.

This epic is carried forward from the [sovereign-sync-and-workbench-ux-epic.md](../epics/v0.2.0/sovereign-sync-and-workbench-ux-epic.md) Track A. Implementation plans exist at `docs/tasks/4.0/4.13.3/v0.2-sovereign-*.md`. Sequenced after Epics A-C because the current snapshot sync is functional and product UX gaps are higher priority than sync optimization.

Sync scope additions:

- Outbox carries `wp_acx_persons.person_uuid` to backend `identity_clusters.roster_id`.
- Backend removes/replaces `cluster_repository.get_roster_entry_name()` (`SELECT name FROM roster_entries`) so roster ID paths no longer rely on a nonexistent table.
- Drift reconciliation surfaces conflicting person assignments instead of silently overwriting curation.

## External Dependencies

| Dependency                              | Owner    | Status      | Blocks                    |
| --------------------------------------- | -------- | ----------- | ------------------------- |
| Production-readiness Phase 1 complete   | Frontend | Complete    | Epic A, B, C prerequisite |
| Local projection tables available       | Plugin   | Complete    | Epic B dashboard metrics  |
| Person UUID sync contract + backend roster lookup remediation | Backend  | Not started | Epic D (sync evolution)   |

## Code Anchors

| Layer              | File/Area                                                    | Note                                            |
| ------------------ | ------------------------------------------------------------ | ----------------------------------------------- |
| Frontend roster    | `js/admin/pages/roster/RosterEntriesTable.tsx`               | Currently read-only; gains CRUD actions         |
| Frontend roster    | `js/admin/pages/roster/RosterEntriesSection.tsx`             | Wraps table; gains "Add Person" button          |
| Frontend roster    | `js/admin/pages/RosterPage.tsx`                              | Page shell; gains explanatory copy              |
| Frontend dashboard | `js/admin/pages/DashboardPage.tsx`                           | Static placeholder; gains live data panels      |
| Frontend labeling  | `js/admin/pages/workbench/identity-clusters/`                | Cluster labeling combobox gains person search   |
| Frontend clusters  | `js/admin/pages/roster/ClusterGrid.tsx`                      | Gains multi-select and bulk actions             |
| Frontend clusters  | `js/admin/pages/roster/ClusterDrawerPanel.tsx`               | Gains metadata display (count, confidence, age) |
| Plugin API         | `src/api/class-api.php`                                      | Gains CRUD endpoints for persons                |
| Plugin data        | `src/support/class-life-cycle-manager.php`                   | `wp_acx_persons` table + `person_id` column     |
| Roster API layer   | `js/admin/api/rosterApi.ts`                                  | Gains create/update/delete functions            |
| Backend roster     | `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | Replace legacy `roster_entries` lookup and align with person UUID sync to `roster_id` (Epic D) |
| Architecture       | `docs/adrs/ADR-002-person-as-first-class-local-entity.md` | Decision record for Person entity               |

## Risks and Mitigations

- **Legacy option cutover safety**: development snapshots may still carry option-based person data.
  Mitigation: activation performs idempotent one-time import from `acx_roster_entries`/`acx_roster_assignments`, then retires both options only after successful table write.
- **UUID sync contract integrity**: backend `roster_id` is UUID while local FK is BIGINT.
  Mitigation: `wp_acx_persons.person_uuid` is required/unique and is the only value synced to backend `roster_id`.
- **Dashboard query performance**: counting clusters and identities on every dashboard load could be slow with large datasets.
  Mitigation: denormalize counts into `wp_acx_sync_state` or a dedicated stats cache, updated on sync and mutation.
- **Bulk action complexity**: multi-select + batch mutation introduces new state management patterns.
  Mitigation: reuse existing single-item mutation hooks; batch is frontend orchestration only.
- **Scope creep into sync architecture**: temptation to fix sync issues when touching roster or dashboard.
  Mitigation: sync evolution is explicitly Epic D, sequenced after A-C.

## Long-Term Backlog (Carried Forward from v3)

These items from [roadmap-v3.hybrid.md](roadmap-v3.hybrid.md) are not in scope for v4 epics but remain relevant for future iterations:

- Alt text generation via provider-agnostic LLM (draft review/approval workflow) -- originally v3 Epic D
- Observability: structured logging, metrics, audit logs -- originally v3 Epic F
- Advanced roster analytics (duplicate detection, tagging suggestions)
- Multi-tenant backend support with per-site API keys
- Offline processing queue using managed job runner
- Accessibility insights dashboard with trendlines and digests

## Success Metrics

- Operator can manage persons (create, edit, delete) without touching cluster discovery flow.
- Assigning a person to a cluster deterministically sets the cluster's display label.
- Dashboard renders live cluster/identity data from local projection in < 500ms.
- Cluster review workflow supports bulk operations (merge/dismiss 5+ clusters at once).
- All new features work offline (sovereign model) with stale data clearly indicated.
- Test coverage: all CRUD endpoints, all new UI components, all bulk action flows.

---

# Consolidated Checklist

## Epic A: Person CRUD Tool

- [x] Create `wp_acx_persons` table via `dbDelta`. Retire `acx_roster_entries` and `acx_roster_assignments` WP options.
- [x] Add required unique `person_uuid` to `wp_acx_persons` and generate it on create/import paths.
- [x] Add `person_id` column to `wp_acx_clusters`.
- [x] Add REST endpoints: create, update, delete persons.
- [x] Implement label derivation rule (person assignment sets cluster display label).
- [x] Add action column to `RosterEntriesTable` (edit, delete).
- [x] Add "Add Person" button and create form/modal.
- [x] Add "People" vs "Clusters" explanatory copy.

## Epic B: Dashboard Buildout

- [x] Add identity panel (person count, assigned clusters, pending review).
- [x] Add contextual "next step" guidance card.
- [x] Enhance coverage panel with "faces detected" count.
- [x] Enhance recent activity with status, duration, and result links.

## Epic C: Recognition UX Polish

- [x] Add multi-select to ClusterGrid.
- [x] Implement bulk merge action.
- [x] Implement bulk dismiss action.
- [x] Add keyboard navigation to cluster grid and drawer.
- [x] Add inline person search in cluster labeling combobox.
- [x] Add metadata display to ClusterDrawerPanel (face count, confidence, age).
- [x] Add toast notifications for all mutation outcomes.

## Epic D: Sovereign Sync Evolution -- DEFERRED

- [x] Outbox schema and lifecycle.
- [ ] Person UUID sync to backend `identity_clusters.roster_id`.
- [x] Remove/replace backend `roster_entries` lookup path used by `get_roster_entry_name()`.
- [ ] Action Scheduler migration.
- [ ] Delta ingest with snapshot fallback.
- [ ] Drift reconciliation with curation-safe conflict policy.

## Success Criteria

- [ ] Person CRUD fully operational from UI.
- [ ] Label derivation rule applied consistently across all display paths.
- [ ] Dashboard renders live recognition data.
- [ ] Bulk cluster operations work for 5+ clusters.
- [ ] All features sovereign (work offline with local projection).
- [ ] Full test coverage for new endpoints and components.
