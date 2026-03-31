# Phase 2: Recognition UX Polish and Plugin Ergonomics

## Problem Statement

The face recognition admin experience is functional but ergonomically incomplete: roster entries are read-only (no create/edit/delete), the dashboard shows static coverage stats without cluster or identity counts, and cluster review requires repetitive one-at-a-time interaction with no multi-select, bulk actions, or keyboard navigation. Operators managing more than a handful of identities hit friction on every workflow.

## Workflow Principles

- **TDD**: write a failing test before each fix. Red -> Green -> Refactor.
- **Vertical slices first**: avoid placeholder-only commits (`TODO` throws, `not_implemented` handlers, skipped test scaffolds). Ship minimal end-to-end increments.
- **Smallest vertical slice**: each sub-phase is independently shippable.
- **Curation-first**: roster CRUD is a curation concern owned by the plugin. Operator decisions override backend suggestions.
- **Sovereign model**: all new read surfaces query local projection tables. No live backend dependency for rendering.
- **Greenfield policy**: no production users. Clean rewrites of storage (option -> table) are preferred, with one-time import-and-retire cutover for legacy local options if present.

## Terminology

- **Person**: operator-curated identity record (name, tags, optional reference thumbnail). Ground truth for "who is this person." Stored in `wp_acx_persons`. See [ADR-002](../../../agentic/adrs/ADR-002-person-as-first-class-local-entity.md).
- **Person UUID**: stable UUID v4 persisted on each person row (`person_uuid`). This is the only value synced to backend `identity_clusters.roster_id`.
- **Cluster**: system-inferred grouping of visually similar faces. May be unlabeled (pending review) or assigned to a person.
- **Assign/Commit**: assigning a cluster to a person -- confirming the system's grouping as correct. The `person_id` FK on the cluster is the assignment.
- **Label derivation**: when `person_id IS NOT NULL`, cluster display label = person name. When unassigned, cluster shows its backend-assigned label ("Person N").
- **Pending review**: clusters the system has formed but the operator has not yet confirmed or dismissed.
- **Soft dissociation**: deleting a person sets `person_id = NULL` on associated clusters. Clusters revert to backend label.
- **Bulk action**: an operation applied to multiple selected clusters at once (merge, dismiss).

## Current State Analysis

### What Works

- Sovereign local-read path with curation-first conflict policy.
- Error boundaries at route and cluster-module level (Phase 1a).
- URL-synced tabs and scroll restoration (Phase 1b).
- WorkbenchPage decomposed into tab content components (Phase 1c).
- `RosterEntriesTable` (40 lines) renders roster entries in a read-only table with name, tags, cluster count, updated columns.
- `RosterEntriesSection` (35 lines) wraps the table with loading/error/data states.
- `ClusterGrid` renders clusters with drag-and-drop face reassignment.
- `ClusterDrawerPanel` shows cluster detail with commit-to-roster flow.
- `DashboardPage` (101 lines) has Library Coverage stats, Quick Action links, and Recent Activity list.
- `rosterApi.ts` (40 lines) has `listRosterEntries()` and `commitClusterToRosterEntry()`.
- `class-api.php` (229 lines) registers `GET acx/v1/roster/entries` and `POST acx/v1/roster/clusters/{id}/commit`.
- `LifecycleManager` (176 lines) creates 3 projection tables (`acx_clusters`, `acx_identity_members`, `acx_sync_state`) via `dbDelta()`.

### What's Broken / Missing

- **Storage mismatch**: persons stored in `acx_roster_entries` WP option, not a table. `acx_roster_assignments` stores cluster mappings separately. Dual source of truth with cluster labels. No indexing, pagination, or relational integrity.
- **No CRUD endpoints**: only `GET` (list) and `POST` (commit) exist. No create, update, or delete for persons.
- **No action column**: `RosterEntriesTable` has no edit or delete buttons per row.
- **No "Add Person" UI**: the only way to create a person is to commit a cluster with a new name.
- **Dashboard is a static shell**: no cluster/identity counts, no pending-review summary, no contextual "what to do next" guidance.
- **No multi-select**: `ClusterGrid` has no checkbox or Shift-click selection.
- **No bulk actions**: no merge-N or dismiss-N cluster operations.
- **Partial keyboard navigation only**: click/activation semantics exist, but roving focus, arrow-key traversal, and drawer focus management are missing.
- **No person-aware labeling**: cluster labeling requires typing a name from memory. No autocomplete.
- **No toast notifications**: mutation outcomes (merge, split, reassign, commit) have no visual confirmation.
- **"People" vs "Clusters" unexplained**: the Roster page has two tabs but no copy explaining the concepts.
- **Backend has no roster_entries table**: `identity_clusters.roster_id` column exists but is non-functional.

## Proposed Solution

Four independently shippable sub-phases, ordered by dependency:

1. **Phase 2a -- Person CRUD**: Create `wp_acx_persons` table with stable `person_uuid`, add `person_id` column to clusters, add plugin-local REST CRUD endpoints (no backend proxy), build create/edit/delete UI with TanStack Query mutations. Retire `acx_roster_entries` and `acx_roster_assignments` options.
2. **Phase 2b -- Dashboard Buildout**: Add identity panel with live counts, contextual guidance card, enhanced coverage and activity panels.
3. **Phase 2c -- Recognition UX Polish**: Multi-select clusters, bulk merge/dismiss, keyboard navigation, person-aware labeling combobox, toast notifications.
4. **Phase 2d -- Explanatory Copy and Onboarding**: Contextual help text for People vs Clusters, empty states, first-use guidance.

## Patterns to Follow

### Table Creation via dbDelta (PHP)

```php
// Extend LifecycleManager::maybe_create_projection_tables()
// Follow the existing pattern at L131-L172

$persons_sql = "CREATE TABLE {$wpdb->prefix}acx_persons (
    id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
    person_uuid char(36) NOT NULL,
    name varchar(255) NOT NULL,
    tags text DEFAULT '',
    reference_thumb_path varchar(512) DEFAULT NULL,
    cluster_count int unsigned DEFAULT 0,
    created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY  (id),
    UNIQUE KEY idx_name (name),
    UNIQUE KEY idx_person_uuid (person_uuid)
) $charset_collate;";

dbDelta( $persons_sql );

// Generate person_uuid on create/import using wp_generate_uuid4()

// Add person_id column to wp_acx_clusters
// (dbDelta handles ALTER TABLE for new columns)
```

### REST CRUD Endpoint Registration (PHP)

```php
// In class-api.php::register_routes(), after existing roster/entries GET

register_rest_route( 'acx/v1', '/roster/persons', array(
    'methods'             => 'POST',
    'callback'            => array( $this, 'create_person' ),
    'permission_callback' => array( $this, 'can_manage_roster' ),
    'args'                => array(
        'name' => array(
            'required'          => true,
            'type'              => 'string',
            'sanitize_callback' => 'sanitize_text_field',
        ),
        'tags' => array(
            'type'    => 'array',
            'default' => array(),
            'items'   => array( 'type' => 'string' ),
        ),
    ),
) );

register_rest_route( 'acx/v1', '/roster/persons/(?P<id>\d+)', array(
    array(
        'methods'             => 'PUT',
        'callback'            => array( $this, 'update_person' ),
        'permission_callback' => array( $this, 'can_manage_roster' ),
    ),
    array(
        'methods'             => 'DELETE',
        'callback'            => array( $this, 'delete_person' ),
        'permission_callback' => array( $this, 'can_manage_roster' ),
    ),
) );
```

### TanStack Query Mutation Hook (TypeScript)

```tsx
// js/admin/hooks/useRosterMutations.ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createPerson, updatePerson, deletePerson } from "../api/rosterApi";
import { queryKeys } from "../api/queryKeys";

export const useCreatePerson = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createPerson,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
    },
  });
};
```

### Person-Aware Combobox Pattern (TypeScript)

```tsx
// In cluster labeling, replace free-text input with existing Combobox component.
import { Combobox } from "../../../../components/ui/combobox";

const PersonCombobox = ({ onSelect, onCreate }: Props) => {
  const { data: persons } = usePersons();
  const options =
    persons?.map((person) => ({
      value: person.id.toString(),
      label: person.name,
    })) ?? [];

  return (
    <Combobox
      options={options}
      value=""
      onSelect={(value) => onSelect(Number(value))}
      onCreate={onCreate}
      placeholder={__("Select a person", "alt-context")}
      searchPlaceholder={__("Search people...", "alt-context")}
      emptyText={__("No person found.", "alt-context")}
    />
  );
};
```

### Multi-Select Hook Pattern (TypeScript)

```tsx
// js/admin/hooks/useClusterSelection.ts
export const useClusterSelection = () => {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = useCallback((clusterId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(clusterId)) next.delete(clusterId);
      else next.add(clusterId);
      return next;
    });
  }, []);

  const selectRange = useCallback((clusterIds: string[]) => {
    setSelected((prev) => new Set([...prev, ...clusterIds]));
  }, []);

  const clear = useCallback(() => setSelected(new Set()), []);

  return { selected, toggle, selectRange, clear, count: selected.size };
};
```

## Functions to Change

### Phase 2a: Person CRUD

| File                                             | Line     | Change                                                                                                                                   |
| ------------------------------------------------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `src/support/class-life-cycle-manager.php`       | L27-31   | Add `'acx_persons'` to `OWNED_TABLE_SUFFIXES`                                                                                            |
| `src/support/class-life-cycle-manager.php`       | L101-172 | Add `wp_acx_persons` table schema (`person_uuid` unique) + `person_id` column on `wp_acx_clusters` to `maybe_create_projection_tables()` |
| `src/support/class-life-cycle-manager.php`       | L37-53   | Retire `acx_roster_entries` and `acx_roster_assignments` options in `activate()`                                                         |
| `src/api/class-api.php`                          | L49-76   | Add `POST /roster/persons`, `PUT /roster/persons/{id}`, `DELETE /roster/persons/{id}` route registrations                                |
| `src/api/class-api.php`                          | L195-202 | Rewrite `get_roster_entries()` to query `wp_acx_persons` table instead of `get_option()`                                                 |
| `src/api/class-api.php`                          | new      | Add `create_person()` handler with name uniqueness validation                                                                            |
| `src/api/class-api.php`                          | new      | Add `update_person()` handler for name and tags                                                                                          |
| `src/api/class-api.php`                          | new      | Add `delete_person()` handler with cluster soft-dissociation (nullify `person_id` on assigned clusters)                                  |
| `js/admin/api/rosterApi.ts`                      | L40      | Add `createPerson()`, `updatePerson()`, `deletePerson()` API functions                                                                   |
| `js/admin/hooks/useRosterMutations.ts`           | new      | Add `useCreatePerson`, `useUpdatePerson`, `useDeletePerson` mutation hooks                                                               |
| `js/admin/pages/roster/RosterEntriesTable.tsx`   | L9-39    | Add action column with edit (inline) and delete buttons per row                                                                          |
| `js/admin/pages/roster/RosterEntriesSection.tsx` | L16-35   | Add "Add Person" button and inline create form above the table                                                                           |
| `js/admin/pages/RosterPage.tsx`                  | L103-104 | Wire mutation hooks to `RosterEntriesSection` and `RosterEntriesTable`                                                                   |

### Phase 2b: Dashboard Buildout

| File                                 | Line   | Change                                                                                                           |
| ------------------------------------ | ------ | ---------------------------------------------------------------------------------------------------------------- |
| `js/admin/hooks/useIdentityStats.ts` | new    | Create hook that queries local projection for person count, assigned cluster count, pending-review cluster count |
| `src/api/class-api.php`              | new    | Add `GET /acx/v1/dashboard/stats` endpoint returning identity/cluster counts from projection tables              |
| `js/admin/api/dashboardApi.ts`       | new    | Add `fetchDashboardStats()` API function                                                                         |
| `js/admin/pages/DashboardPage.tsx`   | L25-62 | Add identity panel between coverage and quick actions: person count, assigned clusters, pending review count     |
| `js/admin/pages/DashboardPage.tsx`   | L64-81 | Add contextual guidance card with dynamic "what to do next" copy                                                 |
| `js/admin/pages/DashboardPage.tsx`   | L83-99 | Enhance recent activity with duration and direct result links                                                    |

### Phase 2c: Recognition UX Polish

| File                                           | Line          | Change                                                                                                              |
| ---------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------- |
| `js/admin/hooks/useClusterSelection.ts`        | new           | Create multi-select hook with toggle, selectRange, clear                                                            |
| `js/admin/pages/roster/ClusterGrid.tsx`        | various       | Add checkbox per cluster card, Shift+click range selection, visual selection state                                  |
| `js/admin/pages/roster/BulkActionBar.tsx`      | new           | Floating bar shown when selection count > 0 with merge/dismiss buttons                                              |
| `js/admin/pages/roster/ClusterGrid.tsx`        | various       | Add keyboard navigation: arrow keys to move focus, Enter to open drawer, Escape to close, Space to toggle selection |
| `js/admin/pages/workbench/identity-clusters/`  | labeling flow | Replace free-text input with person combobox search                                                                 |
| `js/components/ui/Toast.tsx`                   | new           | Toast notification component (or wire existing Radix Toast primitive)                                               |
| `js/admin/pages/roster/ClusterDrawerPanel.tsx` | various       | Add face count, confidence score range, cluster creation date to metadata section                                   |

### Phase 2d: Explanatory Copy

| File                                             | Line          | Change                                                                                                    |
| ------------------------------------------------ | ------------- | --------------------------------------------------------------------------------------------------------- |
| `js/admin/pages/RosterPage.tsx`                  | L92-106       | Add explanatory copy header: "People are known identities. Clusters are face groups the system detected." |
| `js/admin/pages/roster/RosterEntriesSection.tsx` | empty state   | Replace generic empty message with actionable: "No people yet. Add one manually or assign a cluster."     |
| `js/admin/pages/DashboardPage.tsx`               | guidance card | First-use guidance: "Start by scanning your media library for faces."                                     |

## Related Files

| File                                             | Note                                                                                                           |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `src/support/class-life-cycle-manager.php`       | Owns table creation/destruction. Will add `wp_acx_persons` + `person_id` column alongside existing 3 tables.   |
| `src/api/class-api.php`                          | Owns REST route registration and roster handlers. Storage rewrite from option to table. Person CRUD endpoints. |
| `js/admin/api/rosterApi.ts`                      | Current 2-function API module. Will grow to 5 functions (person CRUD).                                         |
| `js/admin/api/queryKeys.ts`                      | Centralized query key factory. Must add `roster.persons` and `dashboard.stats` keys.                           |
| `js/admin/pages/roster/RosterEntriesTable.tsx`   | Read-only table that will gain action column.                                                                  |
| `js/admin/pages/roster/RosterEntriesSection.tsx` | Query state wrapper that will gain create form.                                                                |
| `js/admin/pages/roster/ClusterGrid.tsx`          | Cluster card grid that will gain selection and keyboard nav.                                                   |
| `js/admin/pages/roster/ClusterDrawerPanel.tsx`   | Detail panel that will gain metadata.                                                                          |
| `js/admin/pages/DashboardPage.tsx`               | Static shell that will gain live panels.                                                                       |
| `js/admin/pages/RosterPage.tsx`                  | Page component that orchestrates entries and clusters tabs.                                                    |
| `js/admin/hooks/useRosterEntries.ts`             | Existing hook for fetching persons. Not changed but consumed by combobox.                                      |
| `js/components/ui/tabs.tsx`                      | Radix UI Tabs wrapper. Not changed.                                                                            |
| `js/components/ErrorBoundary.tsx`                | Wraps new components. Not changed.                                                                             |
| `tests/php/api/`                                 | PHPUnit test directory for REST endpoint tests.                                                                |
| `js/admin/pages/roster/__tests__/`               | Vitest test directory for roster components.                                                                   |
| `js/admin/hooks/__tests__/`                      | Vitest test directory for hooks.                                                                               |

---

## Consolidated Checklist

## Delivery Guardrail

- [x] Do not land placeholder-only code paths (`WP_Error('not_implemented')`, `throw new Error('TODO')`, `it.todo()`/`@skip` scaffolds) for production behavior.
- [x] For each capability, ship one vertical slice that includes: failing test -> implementation -> passing test.

## Phase 2a: Person CRUD Backend (PHP)

- [x] **Test (red)**: `PersonCrudTest` -- POST creates person, returns 201 with person data.
- [x] **Implement**: `create_person()` -- insert into `wp_acx_persons`, validate name uniqueness.
- [x] **Test (green)**: POST with unique name succeeds; POST with duplicate returns 409.
- [x] **Test (green)**: POST persists valid `person_uuid` and enforces unique UUID constraint.
- [x] **Test (red)**: `PersonCrudTest` -- PUT updates person name and tags.
- [x] **Implement**: `update_person()` -- update row by ID, validate name uniqueness on rename.
- [x] **Test (green)**: PUT renames person; PUT with conflicting name returns 409; PUT with bad ID returns 404.
- [x] **Test (red)**: `PersonCrudTest` -- DELETE removes person and nullifies `person_id` on clusters.
- [x] **Implement**: `delete_person()` -- delete row, nullify `person_id` FK on `wp_acx_clusters`.
- [x] **Test (green)**: DELETE returns 200; assigned clusters have null `person_id`; DELETE with bad ID returns 404.
- [x] **Test (red)**: `PersonCrudTest` -- GET reads from table, not option.
- [x] **Implement**: rewrite `get_roster_entries()` to query `wp_acx_persons` table.
- [x] **Test (green)**: GET returns persons from table. Empty table returns empty array.
- [x] **Implement**: one-time idempotent activation import from `acx_roster_entries` / `acx_roster_assignments`; retire both options only after successful import into table-backed persons and cluster assignments.
- [x] **Test**: activation deletes legacy options after successful import to table and can safely retire them on a rerun when assignments are already imported.
- [x] **Test**: imported legacy persons receive stable `person_uuid` values before options are retired.
- [x] **Implement**: label derivation -- assigning person_id sets cluster display label to person name.

## Phase 2a: Person CRUD Frontend (TypeScript)

- [x] **Implement**: `createPerson()`, `updatePerson()`, `deletePerson()` API functions in `rosterApi.ts`.
- [x] **Test (red)**: `useRosterMutations` -- `useCreatePerson` calls API and invalidates query.
- [x] **Implement**: mutation hooks in `useRosterMutations.ts` with optimistic updates.
- [x] **Test (green)**: create/update/delete mutations invalidate roster persons query key.
- [x] **Test (red)**: `RosterEntriesTable` -- renders edit and delete buttons in action column.
- [x] **Implement**: action column in `RosterEntriesTable` with inline edit mode and delete confirmation.
- [x] **Test (green)**: clicking edit enables inline name/tag editing; clicking delete shows confirmation; confirming calls mutation.
- [x] **Test (red)**: `RosterEntriesSection` -- renders "Add Person" button; clicking opens create form.
- [x] **Implement**: create form with name input and optional tags, wired to `useCreatePerson`.
- [x] **Test (green)**: submitting form calls mutation; new person appears in table after invalidation.

## Phase 2b: Dashboard Buildout Checklist

- [x] **Test (red)**: `DashboardPage` -- renders identity stats panel with roster count and pending review count.
- [x] **Implement**: `GET /acx/v1/dashboard/stats` endpoint querying local projection tables and WordPress-local media metadata only.
- [x] **Implement**: `fetchDashboardStats()` in `dashboardApi.ts`.
- [x] **Implement**: `useIdentityStats` hook wrapping the API call.
- [x] **Implement**: identity stats panel in `DashboardPage` (person count, assigned clusters, pending review).
- [x] **Test (green)**: dashboard renders live counts from local projection.
- [x] **Test (green)**: dashboard remains functional with backend offline; no cross-plugin data reads are required.
- [x] **Test (red)**: `DashboardPage` -- guidance card shows appropriate message based on state.
- [x] **Implement**: guidance card component with conditional copy: pending review count > 0, empty roster, all caught up.
- [x] **Test (green)**: guidance card adapts text based on stats.
- [x] **Enhance**: recent activity panel with job duration and direct link to results.

## Phase 2c: Recognition UX Polish Checklist

- [x] **Test (red)**: `useClusterSelection` -- toggle adds/removes cluster ID from set.
- [x] **Implement**: `useClusterSelection` hook with toggle, selectRange, clear.
- [x] **Test (green)**: toggle, range select, and clear work correctly.
- [x] **Test (red)**: `ClusterGrid` -- Shift+click selects range; checkbox toggles single.
- [x] **Implement**: selection UI in `ClusterGrid` with visual selection state.
- [x] **Test (green)**: selection state reflects in UI; count badge shows selected count.
- [x] **Implement**: `BulkActionBar` floating bar with merge and dismiss buttons.
- [x] **Test (red)**: `BulkActionBar` -- merge button calls merge mutation for all selected clusters.
- [x] **Implement**: bulk merge and dismiss flows with confirmation dialogs.
- [x] **Test (green)**: bulk merge reduces N clusters to 1; bulk dismiss marks all as dismissed.
- [x] **Implement**: keyboard navigation in `ClusterGrid` (arrow keys, Enter, Escape, Space).
- [x] **Test**: grid focus management and ARIA attributes.
- [x] **Implement**: person combobox in cluster labeling flow (searches persons locally).
- [x] **Test**: combobox filters persons by search; "Create new" option appears for unknown names.
- [x] **Implement**: Toast notification component wired to Radix Toast primitive.
- [x] **Wire**: toast notifications for all mutation outcomes (merge, split, reassign, commit, dismiss).
- [x] **Implement**: metadata display in `ClusterDrawerPanel` (face count, confidence range, creation date).

## Phase 2d: Explanatory Copy Checklist

- [x] Add "People are known identities..." header copy to `RosterPage`.
- [x] Update empty state in `RosterEntriesSection` with actionable message: "No people yet. Add one manually or assign a cluster."
- [x] Add first-use guidance to `DashboardPage` guidance card.
- [x] Review all new copy through `__()` / `_x()` with `'alt-context'` text domain.

## Success Criteria

- [x] Operator can create, rename, tag, and delete persons from the Roster page.
- [x] Persons are stored in a dedicated table (`wp_acx_persons`), not WP options.
- [x] Every person has stable `person_uuid`; backend sync contract uses `person_uuid -> identity_clusters.roster_id`.
- [x] Label derivation rule: assigning a person to a cluster sets the cluster's display label.
- [x] Dashboard shows live person count, assigned cluster count, and pending-review count.
- [x] Dashboard guidance card adapts text based on current state.
- [x] Operator can Shift-click to multi-select clusters and bulk merge/dismiss in one action.
- [x] Cluster grid is navigable via keyboard (arrow keys, Enter, Escape).
- [x] Cluster labeling offers existing persons as autocomplete suggestions.
- [x] Every mutation shows a toast confirmation.
- [x] All new PHP endpoints have PHPUnit test coverage.
- [x] All new frontend hooks and components have Vitest test coverage.
- [x] `acx_roster_entries` and `acx_roster_assignments` WP options retired.
- [x] Existing test suite continues passing.
