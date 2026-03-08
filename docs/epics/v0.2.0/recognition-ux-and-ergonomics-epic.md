# Recognition UX and Plugin Ergonomics (v0.2.0+)

## Status

Phases 1-4 complete. Phase 5 (Sovereign Sync -- Person Push) is next.

## Objective

Transform the face recognition admin experience from a functional prototype into a polished tool that WordPress operators can use confidently for day-to-day identity management: full roster CRUD, an actionable dashboard, and streamlined cluster review workflows.

## Problem Statement

The v0.1.0 sovereign architecture and v0.2.0 reliability baseline established a solid technical foundation, but the admin-facing product surface has significant ergonomic gaps:

1. **Roster is read-only.** The only way to create a person record is to commit a cluster. Admins cannot pre-populate known identities, rename entries after creation, or delete stale entries. The `RosterEntriesTable` displays data but has no action column.
2. **Dashboard is a static shell.** `DashboardPage.tsx` shows library coverage stats and quick-action links but has no cluster/identity counts, no pending-review summary, and no contextual guidance on what to do next.
3. **Cluster review is one-at-a-time.** No multi-select, no bulk merge/dismiss, no keyboard navigation. Processing a large batch of clusters requires repetitive click-per-cluster interaction.
4. **Labeling lacks person awareness.** When labeling a cluster, the operator must type a name from memory. There is no autocomplete or search against existing persons.
5. **"People" vs "Clusters" is unexplained.** The Roster page has two tabs but no copy that helps operators understand what each concept means or how they relate.
6. **Dual source of truth for names.** Cluster labels (synced from backend) and roster entries (`acx_roster_entries` WP option) are two independent naming systems with no reconciliation. `acx_roster_assignments` stores mappings separately.

## UX Vision

**Roster Management**: Admins open the Roster page, see a searchable table of known persons with face counts and last-updated timestamps. They can add a new person (name + optional tags), edit an existing person inline, or delete one with a confirmation dialog. Deleting a person does not destroy associated clusters -- it soft-dissociates them (sets `person_id` to NULL, cluster reverts to its backend-assigned label).

**Dashboard Home Base**: The dashboard is the first thing admins see. It shows: coverage stats, person/cluster counts, pending-review count with a "Review N clusters" call-to-action, and a "what to do next" guidance card that adapts to the current state (e.g., "You have 12 unreviewed clusters -- review them now").

**Efficient Cluster Review**: Admins can Shift-click to multi-select clusters in the grid, then bulk-merge or bulk-dismiss in one action. Keyboard shortcuts (arrow keys, Enter, Escape) make it possible to review without a mouse. Every mutation shows a toast confirmation.

**Roster-Aware Labeling**: When labeling a cluster, a combobox offers existing persons as suggestions (searched locally). Assigning a person to a cluster sets the cluster's display label to the person's name (label derivation rule). Creating a new person from the labeling flow is still possible via "Create new."

## Constraints

- **Production-readiness Phase 1 prerequisite**: error boundaries, URL-synced tabs, and WorkbenchPage decomposition must be complete. This epic builds on that structural foundation.
- **Greenfield policy**: no production users. Clean rewrites preferred; legacy local options (if present) use one-time import-and-retire cutover.
- **Plugin boundary rule**: only monorepo-managed code changes.
- **Curation-first precedence**: roster CRUD operations are curation; they override backend suggestions.
- **Sovereign model**: all new surfaces read from local projection. No live backend dependency for rendering.
- **Accessibility**: all new interactive surfaces must be keyboard-operable. Roster CRUD forms must meet WCAG 2.1 AA.

## Terminology

- **Person**: operator-curated identity record (name, tags, optional reference thumbnail). Ground truth for "who is this person." Stored in `wp_acx_persons`. See [ADR-002](../../agentic/ADR-002-person-as-first-class-local-entity.md).
- **Person UUID**: stable UUID v4 stored on each person row (`person_uuid`). This is the only value synced to backend `identity_clusters.roster_id`.
- **Cluster**: system-inferred grouping of visually similar faces. May be unlabeled (pending review) or assigned to a person.
- **Assign/Commit**: assigning a cluster to a person -- confirming the system's grouping as correct. The `person_id` FK on the cluster row is the assignment.
- **Label derivation**: when `person_id IS NOT NULL`, cluster display label = person name. When unassigned, cluster shows its backend-assigned label ("Person N").
- **Pending review**: clusters the system has formed but the operator has not yet confirmed or dismissed.
- **Soft dissociation**: deleting a person sets `person_id = NULL` on associated clusters. Clusters revert to backend label.
- **Bulk action**: an operation applied to multiple selected clusters at once (merge, dismiss).

## Current State

### Complete (Foundation)

- Sovereign local-read path with curation-first conflict policy.
- Snapshot sync operational.
- Error boundaries at route and cluster-module level.
- URL-synced tabs and scroll restoration.
- WorkbenchPage decomposed into tab content components.
- `RosterEntriesTable` renders roster entries in a read-only table.
- `RosterEntriesSection` wraps the table with loading/error states.
- `ClusterGrid` renders clusters with drag-and-drop face reassignment.
- `ClusterDrawerPanel` shows cluster detail with commit-to-roster flow.
- `DashboardPage` has coverage stats, quick-action cards, and recent activity list.
- `rosterApi.ts` has `listRosterEntries()` and `commitClusterToRosterEntry()`.

### Gaps

- Backend has no `roster_entries` table; `identity_clusters.roster_id` exists but is non-functional.
- `commit_roster_cluster` does not set `is_user_confirmed = 1`, so snapshot sync can overwrite person assignments.
- No outbox or push mechanism exists; local curation changes are not propagated to the backend.
- Person UUIDs are generated locally but never synced to backend `roster_id`.

## Target Architecture

### Design Decisions

| Decision                                              | Rationale                                                                                                                                                                                               |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Person as first-class local entity (`wp_acx_persons`) | Person provides identity stability across cluster lifecycle. Option storage lacks indexing/pagination/relational integrity. See [ADR-002](../../agentic/ADR-002-person-as-first-class-local-entity.md). |
| Label derivation, not duplication                     | When `person_id IS NOT NULL`, cluster label = person name. Single source of truth. No label reconciliation needed.                                                                                      |
| Person CRUD is 100% local (no backend proxy)          | Person is a curation concern. Create/rename/delete in plugin tables only. Sync to backend `roster_id` is Epic D.                                                                                        |
| `acx_roster_assignments` option retired               | Assignment IS the `person_id` FK on `wp_acx_clusters`. No separate mapping needed.                                                                                                                      |
| Dashboard reads local projection only                 | Sovereign model. Dashboard data (coverage, cluster counts, pending review) all derive from local tables.                                                                                                |
| Dashboard scope is plugin-local only                  | Use Alt Context plugin tables plus WordPress-local media metadata; do not aggregate data from unrelated plugins.                                                                                        |
| Inline person search uses local data                  | Combobox autocomplete queries local persons. Fast, offline-resilient, no backend roundtrip.                                                                                                             |
| Bulk actions are frontend orchestration               | Multi-select + batch mutation reuses existing single-item hooks. No new backend endpoints needed.                                                                                                       |
| Soft dissociation on person delete                    | Deleting a person sets `person_id = NULL` on clusters. Clusters revert to backend-assigned label. Curation-safe.                                                                                        |

### Data Model

**New table: `wp_acx_persons`** ([ADR-002](../../agentic/ADR-002-person-as-first-class-local-entity.md))

```sql
CREATE TABLE {prefix}acx_persons (
    id BIGINT UNSIGNED AUTO_INCREMENT,
    person_uuid CHAR(36) NOT NULL,
    name VARCHAR(255) NOT NULL,
    tags TEXT,
    reference_thumb_path VARCHAR(512) DEFAULT NULL,
    cluster_count INT UNSIGNED DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY idx_name (name),
    UNIQUE KEY idx_person_uuid (person_uuid)
);
```

**Modified table: `wp_acx_clusters`** -- add `person_id BIGINT UNSIGNED DEFAULT NULL` (logical FK to `wp_acx_persons.id`, no hard constraint per dbDelta limitations).

**Label derivation rule**: when `person_id IS NOT NULL`, cluster display label = `wp_acx_persons.name`. When `NULL`, cluster shows its own `label` column (backend-assigned "Person N").

**Legacy option cutover policy**: `acx_roster_entries` and `acx_roster_assignments` are retired after one-time import (if present) into `wp_acx_persons` + `wp_acx_clusters.person_id`.

## Phased Delivery

### Phase 1: Person CRUD Backend (Plugin REST API) -- COMPLETED

> **Status**: completed
> **Task plan**: [phase-2-recognition-ux-polish-task-plan.md](../../tasks/5.0/phase-2-recognition-ux-polish-task-plan.md) Phase 1

**Goal**: Persons have a proper storage layer and full CRUD REST endpoints.

Deliverables:

- `wp_acx_persons` table via `dbDelta()` in lifecycle manager.
- `person_id` column added to `wp_acx_clusters`.
- Required `person_uuid` generation for new/imported persons; enforce unique constraint.
- Retire `acx_roster_entries` and `acx_roster_assignments` WP options.
- REST endpoints: `POST`, `PUT /{id}`, `DELETE /{id}` for persons.
- Validation: name uniqueness, non-empty name, tag format.
- Soft dissociation: deleting a person nullifies `person_id` on assigned clusters.
- Label derivation: assigning a person sets cluster display label to person name.

Exit criteria:

- `POST /acx/v1/roster/persons` creates a person. `PUT` renames/tags it. `DELETE` removes it and dissociates clusters.
- Person create/import paths persist stable `person_uuid`; backend sync uses `person_uuid -> identity_clusters.roster_id`.
- All endpoints have PHPUnit test coverage.

### Phase 2: Person CRUD Frontend (UI) -- COMPLETED

> **Status**: completed
> **Task plan**: [phase-2-recognition-ux-polish-task-plan.md](../../tasks/5.0/phase-2-recognition-ux-polish-task-plan.md) Phase 2

**Goal**: Admins can manage persons entirely from the Roster page UI.

Deliverables:

- `rosterApi.ts`: add `createPerson()`, `updatePerson()`, `deletePerson()`.
- TanStack Query mutations with optimistic updates for create/update/delete.
- Action column in `RosterEntriesTable`: inline edit (name, tags), delete with confirmation dialog.
- "Add Person" button above the table with create form/modal.
- "People" vs "Clusters" explanatory copy in Roster page header and empty states.

Exit criteria:

- Operator can create, rename, tag, and delete persons from the Roster page.
- Optimistic updates provide instant feedback; rollback on error.
- Vitest coverage for all new mutations and UI interactions.

### Phase 3: Dashboard Buildout -- COMPLETED

> **Status**: completed
> **Task plan**: [phase-3-dashboard-buildout-task-plan.md](../../tasks/5.0/phase-3-dashboard-buildout-task-plan.md)

**Goal**: Dashboard is the admin's home base with live data and contextual guidance.

Deliverables:

- **Identity panel**: person count, assigned cluster count, pending-review cluster count. Data from local projection via new `useIdentityStats` hook.
- **Guidance card**: contextual "next step" that adapts to state. Examples: "12 clusters pending review", "3 persons have no assigned clusters", "All caught up!" Uses explicit `unassigned_persons_count` from dashboard stats endpoint.
- **Coverage enhancement**: add "media with faces detected" count alongside existing total/missing/coverage.
- **Activity enhancement**: recent jobs show duration and direct link to results in Confirm tab.

Exit criteria:

- Dashboard renders live cluster/identity counts. Zero backend dependency.
- Guidance card changes text based on pending-review count and roster state.
- Dashboard loads in < 500ms from local DB.

### Phase 4: Recognition UX Polish -- COMPLETED

> **Status**: completed
> **Task plan**: [phase-4-recognition-ux-polish-task-plan.md](../../tasks/5.0/phase-4-recognition-ux-polish-task-plan.md)

**Goal**: Cluster review is efficient for large batches via multi-select, bulk actions, keyboard nav, and roster-aware labeling.

Deliverables:

- **Multi-select**: checkbox or Shift+click in ClusterGrid. Visual selection state.
- **Bulk merge**: merge N selected clusters into one. Confirmation dialog with preview.
- **Bulk dismiss**: dismiss N selected clusters. Confirmation dialog.
- **Keyboard navigation**: arrow keys in grid, Enter to open drawer, Escape to close. Focus management compliant with ARIA grid pattern.
- **Roster-aware labeling**: cluster labeling combobox searches existing persons. "Create new" option for people that do not exist yet. Assigning a person applies the label derivation rule.
- **Toast notifications**: all mutation outcomes (merge, split, reassign, commit, dismiss) show a brief toast.
- **Drawer metadata**: face count, confidence score range, cluster creation date.

Exit criteria:

- Operator can select 5+ clusters and merge/dismiss in one action.
- Cluster grid is fully navigable via keyboard.
- Cluster labeling offers person suggestions.
- Every mutation shows a toast confirmation.

## External Dependencies

| Dependency                            | Owner                 | Status   | Blocks                       |
| ------------------------------------- | --------------------- | -------- | ---------------------------- |
| Production-readiness Phase 1 complete | Frontend              | Complete | All phases                   |
| `wp_acx_clusters` table exists        | v0.1.0 sovereign epic | Complete | Phase 1 (`person_id` column) |

## Code Anchors

| Layer               | File/Area                                        | Note                                            |
| ------------------- | ------------------------------------------------ | ----------------------------------------------- |
| Plugin lifecycle    | `src/support/class-life-cycle-manager.php`       | Add `wp_acx_persons` table + `person_id` column |
| Plugin API          | `src/api/class-api.php`                          | Add CRUD endpoints; retire option-based storage |
| Frontend roster     | `js/admin/pages/roster/RosterEntriesTable.tsx`   | Add action column (edit, delete)                |
| Frontend roster     | `js/admin/pages/roster/RosterEntriesSection.tsx` | Add "Add Person" button, create form            |
| Frontend roster     | `js/admin/pages/RosterPage.tsx`                  | Add explanatory copy, section headers           |
| Frontend API        | `js/admin/api/rosterApi.ts`                      | Add create/update/delete functions              |
| Frontend hooks      | `js/admin/hooks/useRosterHooks.ts`               | Add mutation hooks for person CRUD              |
| Frontend dashboard  | `js/admin/pages/DashboardPage.tsx`               | Add identity panel, guidance card               |
| Frontend clusters   | `js/admin/pages/roster/ClusterGrid.tsx`          | Add multi-select, keyboard nav                  |
| Frontend clusters   | `js/admin/pages/roster/ClusterDrawerPanel.tsx`   | Add metadata display                            |
| Frontend labeling   | `js/admin/pages/workbench/identity-clusters/`    | Add person combobox search                      |
| Frontend components | `js/components/ui/`                              | Toast component (if not yet present)            |

## Risks and Mitigations

- **Legacy option cutover safety**: development snapshots may still contain option-based roster data.
  Mitigation: activation import is idempotent and retires `acx_roster_entries`/`acx_roster_assignments` only after successful import into table-backed person records.
- **UUID sync contract integrity**: local cluster assignment FK is BIGINT while backend sync column is UUID.
  Mitigation: `wp_acx_persons.person_uuid` is required and unique; sync writes only this UUID to backend `roster_id`.
- **Bulk action state complexity**: multi-select + batch mutation introduces new frontend state management.
  Mitigation: dedicated `useClusterSelection` hook encapsulates selection state; batch operations reuse single-item mutation hooks.
- **Dashboard query performance with large libraries**: counting clusters/identities on every load.
  Mitigation: denormalize counts into a stats cache updated on sync and mutation. Fallback: query with `COUNT(*)` is fast for < 10K rows.
- **Keyboard navigation accessibility**: ARIA grid pattern is complex to implement correctly.
  Mitigation: follow Radix UI patterns where possible; manual testing with VoiceOver/NVDA.

---

# Consolidated Checklist

## Phase 1: Person CRUD Backend -- COMPLETED

- [x] Create `wp_acx_persons` table schema in lifecycle manager.
- [x] Add `person_id` column to `wp_acx_clusters` table.
- [x] Retire `acx_roster_entries` and `acx_roster_assignments` WP options.
- [x] Add `POST /acx/v1/roster/persons` endpoint with name uniqueness validation.
- [x] Add `PUT /acx/v1/roster/persons/{id}` endpoint for name and tags update.
- [x] Add `DELETE /acx/v1/roster/persons/{id}` endpoint with cluster soft-dissociation.
- [x] Implement label derivation rule (person assignment sets cluster display label).
- [x] PHPUnit tests for all CRUD endpoints.

## Phase 2: Person CRUD Frontend -- COMPLETED

- [x] Add `createPerson`, `updatePerson`, `deletePerson` to `rosterApi.ts`.
- [x] Add TanStack Query mutation hooks for create/update/delete.
- [x] Add action column to `RosterEntriesTable` (edit, delete buttons).
- [x] Add inline edit mode for person name and tags.
- [x] Add delete confirmation dialog.
- [x] Add "Add Person" button and create form above table.
- [x] Add "People" vs "Clusters" explanatory copy to Roster page.
- [x] Vitest coverage for mutations and UI interactions.

## Phase 3: Dashboard Buildout -- COMPLETED

- [x] Create `useIdentityStats` hook reading from local projection.
- [x] Add identity panel to `DashboardPage` (person count, assigned, pending review).
- [x] Add contextual guidance card with dynamic "next step" copy.
- [x] Enhance coverage panel with "faces detected" count.
- [x] Enhance recent activity with duration and result links.
- [x] Vitest coverage for dashboard panels and hooks.

## Phase 4: Recognition UX Polish -- COMPLETED

- [x] Create `useClusterSelection` hook for multi-select state.
- [x] Add checkbox/Shift-click selection to `ClusterGrid`.
- [x] Implement bulk merge action with confirmation dialog.
- [x] Implement bulk dismiss action with confirmation dialog.
- [x] Add keyboard navigation (arrow keys, Enter, Escape) to cluster grid.
- [x] Add keyboard navigation to ClusterDrawerPanel.
- [x] Add person combobox search to cluster labeling flow (searches persons locally).
- [x] Add toast notification component (or wire existing).
- [x] Add toast notifications for all mutation outcomes.
- [x] Add metadata display to ClusterDrawerPanel (face count, confidence, age).
- [x] Vitest and interaction test coverage for all new behaviors.

## Phase 5: Sovereign Sync -- Person Push and Curation Protection -- NOT STARTED

> **Task plan**: [phase-5-sovereign-sync-person-push-task-plan.md](../../tasks/5.0/phase-5-sovereign-sync-person-push-task-plan.md)

- [ ] Set `is_user_confirmed = 1` on cluster when person is assigned (curation protection).
- [ ] Revert `is_user_confirmed = 0` on cluster when person is deleted (soft dissociation).
- [ ] Add `wp_acx_outbox` table for async push events.
- [ ] Wire outbox writes into person CRUD and cluster commit endpoints.
- [ ] Implement outbox drain via WP cron.
- [ ] Add backend `POST /roster/persons/sync` endpoint.
- [ ] Bind `identity_clusters.roster_id` to `person_uuid` on backend.
- [ ] Remove broken `roster_entries` reference from `cluster_repository.get_roster_entry_name()`.

## Deferred (Post-Epic)

- [ ] Action Scheduler integration (upgrade from WP cron drain).
- [ ] Delta ingest and drift reconciliation.
- [ ] Bidirectional conflict resolution for person name edits.
