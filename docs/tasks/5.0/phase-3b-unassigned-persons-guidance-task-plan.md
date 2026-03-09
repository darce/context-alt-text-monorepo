# Phase 3: Unassigned Persons Guidance + Filtered Roster CTA

## Problem Statement

Dashboard guidance currently relies on a heuristic to infer "persons with no clusters," which can be inaccurate in mixed states. Operators need guidance that reflects real local data and takes them directly to the right remediation surface in one click. This task adds an authoritative unassigned-person count and a filtered Roster Entries CTA flow.

## Workflow Principles

- **Sovereign accuracy**: guidance must be derived from local plugin tables (`wp_acx_persons`, `wp_acx_clusters`) with no backend dependency.
- **Actionable UX**: every guidance state must provide a direct next action, not generic navigation.
- **Deterministic semantics**: "unassigned person" means a person with zero assigned clusters, not a derived proxy from unrelated counters.
- **URL-addressable state**: filtered roster view must be deep-linkable via query params.

## Terminology

- **Unassigned person**: a row in `wp_acx_persons` with no matching rows in `wp_acx_clusters` where `person_id = persons.id`.
- **Guidance state precedence**: pending-review guidance has highest priority, then unassigned-person guidance, then first-use, then all-caught-up.
- **Filtered Roster Entries view**: roster entries tab with `personFilter=unassigned`, showing only entries with `cluster_count === 0`.

## Current State Analysis

- `/apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx` guidance logic has three states and no accurate unassigned-person branch.
- `/apps/prototype-wp-alt-context/src/api/class-api.php` dashboard stats endpoint returns `people_count`, `assigned_clusters_count`, and `pending_clusters_count`, but not unassigned-person count.
- `/apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx` supports tab query params, but roster entries do not support URL-driven filtering for unassigned persons.
- Recent Activity duration + `View Results` links are already implemented and covered by tests; this task does not re-spec that behavior.
- Existing dashboard and roster tests do not validate unassigned-person guidance or filtered CTA behavior.

## Proposed Solution

Add `unassigned_persons_count` to dashboard stats from local SQL, use that field in guidance logic, and route the guidance CTA to `#/roster?tab=entries&personFilter=unassigned`. Implement URL-driven filtering in roster entries so operators land directly on the subset requiring action. Keep all logic local and deterministic.

## Non-Goals

- Do not rework Recent Activity link/duration behavior in this task; that behavior already exists.
- Do not require a mandatory `GuidanceCard` extraction; keep extraction optional and behavior-focused outcomes mandatory.

## Patterns to Follow

### Authoritative Unassigned Count (PHP)

```php
$table_persons  = $wpdb->prefix . 'acx_persons';
$table_clusters = $wpdb->prefix . 'acx_clusters';

$unassigned_persons = (int) $wpdb->get_var(
	$wpdb->prepare(
		'SELECT COUNT(*) FROM %i p
		 WHERE NOT EXISTS (
			 SELECT 1 FROM %i c
			 WHERE c.person_id = p.id
		 )',
		$table_persons,
		$table_clusters
	)
);
```

### Guidance Precedence + Filtered CTA (TypeScript/React)

```tsx
if (stats.pending_clusters_count > 0) {
  return <a href="#/workbench?tab=confirm">Go to Workbench</a>;
}
if (stats.unassigned_persons_count > 0) {
  return <a href="#/roster?tab=entries&personFilter=unassigned">Review unassigned persons</a>;
}
if (stats.people_count === 0) {
  return <a href="#/workbench?tab=scan">Go to Scan tab</a>;
}
return <p>All caught up.</p>;
```

### URL-Driven Roster Filtering (TypeScript/React)

```tsx
const [searchParams, setSearchParams] = useSearchParams();
const personFilter = searchParams.get('personFilter');

const visibleEntries =
  personFilter === 'unassigned'
    ? entries.filter((entry) => entry.cluster_count === 0)
    : entries;

const clearFilter = () => {
  setSearchParams((prev) => {
    const next = new URLSearchParams(prev);
    next.delete('personFilter');
    next.set('tab', 'entries');
    return next;
  }, { replace: true });
};
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `apps/prototype-wp-alt-context/src/api/class-api.php` | 539-568 | Add `unassigned_persons_count` to `get_dashboard_stats()` using local persons/clusters query. |
| `apps/prototype-wp-alt-context/js/admin/api/dashboardApi.ts` | 4-8 | Extend `DashboardStats` with `unassigned_persons_count`. |
| `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx` | 96-151 | Replace heuristic guidance with accurate unassigned-person state and filtered roster CTA. |
| `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx` | 19-108 | Read `personFilter` via `useSearchParams`, apply `personFilter=unassigned`, render filtered empty state, add clear-filter action. |
| `apps/prototype-wp-alt-context/tests/Unit/DashboardApiTest.php` | 25-49 | Add assertions for `unassigned_persons_count`. |
| `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DashboardPage.test.tsx` | 54-122 | Add guidance test coverage for unassigned-person state and CTA href. |
| `apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterEntries.test.tsx` | 40-55 | Add filtered entries tests and filtered empty-state tests. |
| `apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.container.test.tsx` | 145-154 | Add route bootstrap test with `personFilter=unassigned` preserving entries tab state. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/js/admin/hooks/useTabParam.ts` | Existing tab URL sync behavior; ensure filter addition does not regress tab handling. |
| `apps/prototype-wp-alt-context/js/admin/utils/routeHelpers.ts` | Existing hash/query bootstrapping behavior for SPA routes. |
| `docs/epics/v0.2.0/recognition-ux-and-ergonomics-epic.md` | Epic-level Phase 3 deliverables should reference this task plan. |
| `docs/tasks/5.0/phase-3-dashboard-buildout-task-plan.md` | Parent Phase 3 plan; this task is a focused implementation slice. |

---

# Consolidated Checklist

## Completed

- [x] Backend contract extended with authoritative `unassigned_persons_count`.
- [x] Dashboard guidance uses filtered roster CTA: `#/roster?tab=entries&personFilter=unassigned`.
- [x] Roster entries support URL-driven `personFilter=unassigned` filtering with clear-filter action.
- [x] Dashboard and roster tests cover unassigned guidance and filtered roster bootstrap/behavior.

## Phase 0: Scaffolding

- [x] Document contract change in this task plan: `DashboardStats.unassigned_persons_count`.
- [x] Add/update test stubs for dashboard guidance and roster filtered mode.
- [x] Confirm TypeScript typecheck and PHPUnit discovery include new tests.

## Phase 1: Backend Contract and Metric

- [x] **Test (red)**: update `DashboardApiTest` with failing assertion for `unassigned_persons_count`.
- [x] Add `unassigned_persons_count` query in `get_dashboard_stats()`.
- [x] Return `unassigned_persons_count` in REST payload.
- [x] **Test (green)**: `DashboardApiTest` passes with expected count.

## Phase 2: Dashboard Guidance State

- [x] **Test (red)**: add `DashboardPage` test for unassigned-person guidance branch and CTA URL.
- [x] Extend `DashboardStats` TypeScript interface with `unassigned_persons_count`.
- [x] Add guidance branch for `unassigned_persons_count > 0`.
- [x] Set CTA href to `#/roster?tab=entries&personFilter=unassigned`.
- [x] Enforce guidance precedence: pending review > unassigned persons > first-use > all-caught-up.
- [x] **Test (green)**: guidance branch test passes and existing guidance tests remain green.

## Phase 3: Filtered Roster Entries UX

- [x] **Test (red)**: add `RosterEntries` test for filtered mode (`personFilter=unassigned`) and filtered empty state.
- [x] Read `personFilter` from URL in `RosterEntriesSection` via `useSearchParams`.
- [x] Filter entries to `cluster_count === 0` when `personFilter=unassigned`.
- [x] Add filtered empty-state copy for no matching entries.
- [x] Add clear-filter control that removes `personFilter` and preserves `tab=entries`.
- [x] **Test (green)**: filtered mode tests pass; route bootstrap test preserves `tab` and `personFilter`.

## Stretch Goals

- [x] Add a visible "Filtered: Unassigned" badge in roster entries header.
- [x] Add a count chip in dashboard CTA ("Review N unassigned persons").

## Success Criteria

- [x] Dashboard guidance for unassigned persons is based on authoritative local count, not heuristic logic.
- [x] Clicking the guidance CTA opens Roster Entries already filtered to unassigned persons.
- [x] Filtered roster mode is URL-addressable, test-covered, and reversible via clear-filter.
- [x] Existing dashboard and roster flows remain unchanged when no `personFilter` query param is set.
