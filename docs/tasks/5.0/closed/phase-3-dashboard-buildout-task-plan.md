# Phase 3: Dashboard Buildout

## Problem Statement

The dashboard is the admin's landing page, but it underserves its "home base" role. While Phase 2 added identity stats (person count, assigned clusters, pending review), a guidance card, and recent activity with duration and result links, the dashboard still lacks a media-with-faces-detected metric and the guidance card does not account for roster states like "persons with no clusters." The dashboard must become the single place where operators know what to do next.

## Workflow Principles

- **TDD**: write a failing test before each change. Red -> Green -> Refactor.
- **Sovereign model**: all dashboard data comes from local projection tables (`wp_acx_persons`, `wp_acx_clusters`, WordPress media metadata). Zero backend dependency for rendering.
- **Plugin-local scope**: use Alt Context plugin tables plus WordPress-local media metadata only. Do not aggregate data from unrelated plugins.
- **Small vertical slices**: each deliverable is independently shippable and testable.
- **Greenfield policy**: no backward-compat shims. Clean rewrites preferred.

## Terminology

- **Coverage**: percentage of media items with alt text set.
- **Faces detected**: media items that have at least one face identity stored in `wp_acx_identity_members`.
- **Pending review**: clusters where `person_id IS NULL AND curation_state = 'uncurated'`.
- **Guidance card**: contextual "next step" UI that adapts text based on system state.
- **Identity stats**: aggregate counts (people, assigned clusters, pending clusters) from local projection.
- **OrientationCard**: existing first-use onboarding component (dismissible, localStorage-persisted).

## Current State Analysis

### What Works (implemented in Phase 2)

- `DashboardPage.tsx` (204 lines) renders:
  - Library Coverage panel with total, missing, coverage percentage, and progress bar via `useMediaStats`.
  - Identity Recognition panel with people count, assigned clusters, pending review via `useIdentityStats` hook + `GET /acx/v1/dashboard/stats` endpoint.
  - Guidance card with three states: pending > 0 ("N faces waiting"), people = 0 ("Start scanning"), else ("All caught up").
  - OrientationCard (dismissible first-use onboarding).
  - Quick Actions panel with links to Scan, Review, Roster.
  - Recent Activity panel with job history, status, duration formatting (`formatDuration`), and "View Results" links (`#/workbench?tab=confirm&jobId=...`) -- all functional.
- `dashboardApi.ts` exposes `fetchDashboardStats()` returning `DashboardStats { people_count, assigned_clusters_count, pending_clusters_count }`.
- `useIdentityStats.ts` wraps the API call via TanStack Query with `queryKeys.dashboard.stats()`.
- `useRecognitionJobHistory.ts` provides `jobHistory`, `jobStatuses`, and `jobDetails` (including `started_at`/`finished_at` used for duration display).
- `get_dashboard_stats()` in `class-api.php` queries `wp_acx_persons` and `wp_acx_clusters`.
- `DashboardPage.test.tsx` covers identity stats rendering and guidance card states.
- `DashboardApiTest.php` covers the PHP endpoint response shape.

### What's Missing

- **No "media with faces" metric**: the Library Coverage panel shows total media and missing alt text, but not how many media items have detected faces. This needs a count from `wp_acx_identity_members`.
- **Guidance card incomplete**: does not handle "persons with no clusters" state. Needs an explicit `unassigned_persons_count` metric from the API (not a derived heuristic from `assigned_clusters_count`).
- **Recent activity robustness** (minor): links and duration formatting are functional. Remaining gap is graceful handling when a referenced job is no longer available (e.g., expired or purged). This is a robustness concern, not a missing feature.
- **No stale-time or refetch on focus**: `useIdentityStats` has no stale-time config, meaning it refetches on every mount. Dashboard should use a reasonable stale time (e.g., 30s) and refetch on window focus for fresh data.
- **No error state for dashboard stats**: if `GET /dashboard/stats` fails, the panel shows "Loading..." indefinitely. Need error feedback.
- **PHP endpoint missing faces-detected and unassigned-persons counts**: `get_dashboard_stats()` only returns person/cluster counts. Adding `media_with_faces_count` requires a distinct count from `wp_acx_identity_members`. Adding `unassigned_persons_count` requires a NOT EXISTS subquery against `wp_acx_clusters`.

## Proposed Solution

Enhance the existing dashboard in three vertical slices:

1. **Enhanced coverage panel**: add "media with faces" count to the PHP `get_dashboard_stats` endpoint and display it alongside existing coverage stats. Update `DashboardStats` type, `useIdentityStats`/`useMediaStats` integration.
2. **Richer guidance card**: add a fourth guidance state for "persons with no clusters" using the explicit `unassigned_persons_count` field from the stats endpoint. Optionally extract guidance into a dedicated `GuidanceCard` component if the inline logic grows unwieldy.
3. **Error and query polish**: add error state for dashboard stats, configure stale-time/refetch-on-focus for `useIdentityStats`. (Recent activity links and duration are already functional; no new work needed beyond optional robustness hardening.)

## Patterns to Follow

### PHP Endpoint Enhancement (add faces-detected count)

```php
// In class-api.php::get_dashboard_stats(), add after existing counts:

$table_members = $wpdb->prefix . 'acx_identity_members';

$media_with_faces = (int) $wpdb->get_var(
    $wpdb->prepare(
        'SELECT COUNT(DISTINCT media_id) FROM %i',
        $table_members
    )
);

// Add to response array:
// 'media_with_faces_count' => $media_with_faces,
```

### PHP Endpoint Enhancement (add unassigned-persons count)

```php
// In class-api.php::get_dashboard_stats(), add after media_with_faces:

$unassigned_persons = (int) $wpdb->get_var(
    $wpdb->prepare(
        'SELECT COUNT(*) FROM %i p WHERE NOT EXISTS (
            SELECT 1 FROM %i c WHERE c.person_id = p.id
        )',
        $table_persons,
        $table_clusters
    )
);

// Add to response array:
// 'unassigned_persons_count' => $unassigned_persons,
```

### Extended DashboardStats Type (TypeScript)

```typescript
// dashboardApi.ts
export interface DashboardStats {
  people_count: number;
  assigned_clusters_count: number;
  pending_clusters_count: number;
  media_with_faces_count: number;
  unassigned_persons_count: number;
}
```

### Guidance Logic (inline or optional extraction)

```tsx
// Inline in DashboardPage.tsx, or extracted to GuidanceCard.tsx if complexity warrants.
// Uses explicit unassigned_persons_count from API -- not a heuristic.

const renderGuidance = (stats: DashboardStats) => {
  if (stats.pending_clusters_count > 0) {
    return (/* pending review CTA: "N faces are waiting for names." */);
  }
  if (stats.unassigned_persons_count > 0) {
    return (/* "N persons have no assigned clusters." + link to Roster */);
  }
  if (stats.people_count === 0) {
    return (/* first-use: "Start by scanning your media library." */);
  }
  return (/* "All caught up." */);
};
```

### useIdentityStats with Stale Time (TypeScript)

```typescript
export const useIdentityStats = () =>
  useQuery<DashboardStats>({
    queryKey: queryKeys.dashboard.stats(),
    queryFn: fetchDashboardStats,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });
```

### Error State for Stats Panel (TypeScript)

```tsx
{isIdentityLoading ? (
  <p>{__('Loading identity stats...', 'alt-context')}</p>
) : identityError ? (
  <div className="acx-error-state">
    <p>{__('Unable to load identity stats.', 'alt-context')}</p>
    <button onClick={() => refetchIdentity()}>
      {__('Retry', 'alt-context')}
    </button>
  </div>
) : (
  /* stats grid */
)}
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `src/api/class-api.php` | `Api::get_dashboard_stats()` | Add `media_with_faces_count` and `unassigned_persons_count` to `get_dashboard_stats()` response by querying `wp_acx_identity_members` and `wp_acx_persons`/`wp_acx_clusters` |
| `js/admin/api/dashboardApi.ts` | `DashboardStats` interface | Add `media_with_faces_count: number` and `unassigned_persons_count: number` to `DashboardStats` interface |
| `js/admin/hooks/useIdentityStats.ts` | `useIdentityStats` query options | Add `staleTime: 30_000` and `refetchOnWindowFocus: true` to query options |
| `js/admin/pages/DashboardPage.tsx` | Identity stats panel render branch | Add "Media with faces" stat and "persons with no clusters" guidance state using `unassigned_persons_count`; keep guidance inline |
| `js/admin/pages/DashboardPage.tsx` | Identity stats error branch | Add error state handling for identity stats (show retry button on failure) |
| `js/admin/pages/dashboard/GuidanceCard.tsx` | new (optional) | Optional: extract guidance logic into standalone component if inline complexity warrants it |
| `tests/Unit/DashboardApiTest.php` | `DashboardApiTest::testGetDashboardStatsRespondsWithCorrectCounts` | Add test for `media_with_faces_count` and `unassigned_persons_count` in response |
| `js/admin/pages/__tests__/DashboardPage.test.tsx` | `DashboardPage` test suite | Update mock data shape to include `media_with_faces_count` and `unassigned_persons_count`; add guidance/error/zero-value test cases |

## Related Files

| File | Note |
| --- | --- |
| `js/admin/hooks/useMediaStats.ts` | Existing coverage hook. Not changed but may be composed with identity stats for enhanced coverage display. |
| `js/admin/pages/dashboard/OrientationCard.tsx` | Existing first-use onboarding card. Not changed. |
| `js/admin/api/queryKeys.ts` | Has `dashboard.stats()` key already. Not changed. |
| `js/admin/api/config.ts` | Endpoint config. `dashboardStats` endpoint already registered. Not changed. |
| `js/admin/hooks/useRecognitionJobHistory.ts` | Provides `jobHistory`, `jobStatuses`, `jobDetails` consumed by Recent Activity panel. Already functional for duration and result links. Not changed unless robustness hardening is pursued. |
| `src/support/class-life-cycle-manager.php` | Creates projection tables including `wp_acx_identity_members`. Not changed. |
| `js/admin/context/ToastContext.tsx` | Toast system already wired. Not changed. |

---

# Consolidated Checklist

## Phase 3a: Enhanced Coverage and Faces-Detected Metric

- [x] **Test (red)**: `DashboardApiTest` -- `get_dashboard_stats` includes `media_with_faces_count` and `unassigned_persons_count` in response.
- [x] **Implement**: add `COUNT(DISTINCT media_id)` query on `wp_acx_identity_members` and `NOT EXISTS` subquery for unassigned persons to `get_dashboard_stats()` in `class-api.php`.
- [x] **Test (green)**: endpoint returns correct `media_with_faces_count` and `unassigned_persons_count`.
- [x] **Implement**: add `media_with_faces_count: number` and `unassigned_persons_count: number` to `DashboardStats` interface in `dashboardApi.ts`.
- [x] **Test (red)**: `DashboardPage.test.tsx` -- renders "Media with faces" stat value and uses `unassigned_persons_count` for guidance.
- [x] **Implement**: add "Media with faces" stat to the Identity Recognition or Library Coverage panel in `DashboardPage.tsx`.
- [x] **Test (green)**: stat displays the count from API response.

## Phase 3b: Richer Guidance Card

- [x] **Test (red)**: `DashboardPage.test.tsx` -- guidance card shows "persons with no clusters" message when `unassigned_persons_count > 0`.
- [x] **Implement**: add fourth guidance state for "persons with no clusters" using explicit `unassigned_persons_count` from API (not a heuristic). Add inline to `DashboardPage.tsx`.
- [x] **Test (green)**: all four guidance states render correct copy and CTAs:
  - pending_clusters_count > 0: "N faces are waiting for names." + link to Workbench.
  - unassigned_persons_count > 0: "N persons have no assigned clusters." + link to Roster.
  - people_count === 0: "Start by scanning your media library." + link to Scan tab.
  - Default: "All caught up."
- [x] **Test (green)**: existing `DashboardPage.test.tsx` tests continue passing.

### Optional Refactor: GuidanceCard Extraction

- [x] **Optional**: if guidance logic grows complex, extract into `GuidanceCard` component in `js/admin/pages/dashboard/GuidanceCard.tsx` and add dedicated tests. Not required if inline logic remains clear and testable at the page level.

## Phase 3c: Error States and Query Polish

- [x] **Implement**: add `staleTime: 30_000` and `refetchOnWindowFocus: true` to `useIdentityStats` query options.
- [x] **Test (red)**: `DashboardPage.test.tsx` -- renders error state with retry button when `useIdentityStats` returns error.
- [x] **Implement**: add error state for Identity Recognition panel (show "Unable to load" + retry button).
- [x] **Test (green)**: clicking retry button triggers refetch.
- [x] Review all new copy uses `__()` / `_x()` with `'alt-context'` text domain.

### Optional: Recent Activity Robustness

- [x] **Optional**: add graceful handling in Recent Activity panel for jobs that are expired or no longer available (show "Status unavailable. Refresh to retry." while preserving the "View Results" link). Not blocking -- links and duration already work for available jobs.

## Success Criteria

- [x] Dashboard renders live person count, assigned cluster count, pending-review count, and media-with-faces count.
- [x] All dashboard data comes from local projection tables. Zero backend dependency.
- [x] Guidance card adapts text for at least four states: pending review, empty roster, persons without clusters, all caught up.
- [x] Identity stats panel shows error state with retry button on API failure.
- [x] `useIdentityStats` uses stale-time to avoid unnecessary refetches.
- [x] Guidance card logic (inline or extracted) has test coverage for all four states.
- [x] PHP endpoint test covers `media_with_faces_count` and `unassigned_persons_count` fields.
- [x] All existing dashboard tests continue passing.
