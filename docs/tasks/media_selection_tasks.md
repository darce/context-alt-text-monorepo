# Media Selection Workflow — Implementation Tasks

These tasks extend the Alt-Text Workbench slice described in the UML diagram `frontend-uml/media-selection-workflow.mmd` and align with Roadmap v3 (Epic A: Workbench Shell, Epic B: Queue UX).

## REST + Data Plumbing

- [ ] **Expose `GET /workbench/media`**
  - Route namespace: `cat/v1`.
  - Capability: `manage_options` (match dashboard surface).
  - Query params: pagination (`page`, `per_page`), filters (`status`, `updated_after`, `search`), sort (`order`, `orderby`).
  - Response schema: array of normalized media items `{ id, title, status: "missing"|"draft"|"published", thumbnailUrl, updatedAt }` plus pagination headers. Reuse DTOs in the JS bootstrap (`dashboardData.ts`).
  - Data source: reuse `MissingAltTextScanner` summary to seed defaults; fall back to WP_Query with `_wp_attachment_image_alt` meta checks.
- [ ] **Localize Workbench payload**
  - Extend `Admin::get_data()` to include `data['workbench']` with initial item batch derived from the REST handler (avoid duplicating query logic).
  - Populate feature flag map with `workbenchEnabled`, `workbenchRecognition`, `workbenchBulkAI` in sync with `FeatureFlags` service.

## SPA Behavior

- [ ] **Hydrate `useWorkbenchMedia`**
  - Ensure the hook accepts initial items from localization and swaps to live REST data after the first fetch (`enabled` true when endpoint provided).
  - Handle loading, fetching, and error states surfaced to the UI (`Refreshing media queue…`, retry CTA).
  - Cache key: `['workbench', 'media', filterStateHash]` to isolate filter combinations.
- [ ] **Optimistic bulk updates**
  - Wire selection toolbar actions to enqueue UI updates while background job runs (mark as reviewed, generate drafts).
  - Roll back optimistically updated items on REST failure, surface toast via notification bus.
- [ ] **Analytics instrumentation**
  - Emit `cat_workbench_seen` when Workbench route first mounts (include current filters / selection size).
  - Emit `cat_workbench_bulk_action` for each toolbar action with payload `{ action, ids, count }`.

## Persistence & Scan Alignment

- [ ] **Persist scan summaries**
  - Store latest scan output (total/with_alt/missing) via `MissingAltTextScanner` whenever a scan completes.
  - Read stored summary both in REST handler (coverage percent) and SPA bootstrap to avoid stale counts.
  - Ensure first-run scan populates summary within 30 seconds of activation (Roadmap MVP requirement).

## Testing

- [ ] PHPUnit coverage for `/workbench/media` handler (cap checks, filter permutations, pagination headers).
- [ ] Vitest/RTL covering `WorkbenchApp` initial render, loading state, error retry, and optimistic rollback.
- [ ] Analytics tests ensuring `emitDashboardEvent` receives the correct payloads per action.

