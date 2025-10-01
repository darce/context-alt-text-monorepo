# Alt-Text Workbench Tasks

Admin surface for prioritizing attachments missing descriptive text, triaging recognition insights, and generating or approving captions. Aligns with roadmap Phase 1 objectives and Tasks backlog items for the Workbench route and modules.

## 1. Workbench Shell

- [x] Route `AltTextWorkbench` under SPA router with feature-gated nav entry.
- [x] Hydrate initial payload via `ContextAltTextAdmin.data.workbench` with counts, filters, user preferences.
- [x] Provide React Query hydration + refetch plumbing for attachments, selection state, and recognition jobs.
- [ ] Wire page-level toasts/notices to shared notification system.
- [ ] Persist user layout preference (grid/list, column order) in REST-backed user meta.

## 2. Media Queue (Grid/List)

- [ ] Implement `MediaList` component with virtualized scrolling, responsive breakpoints, and lazy-loaded thumbnails.
- [x] Surface alt-text status chips (Missing, Draft, Published) with inline WordPress edit links.
- [ ] Rework list layout to render one row per asset (list-style view akin to Media Library) with pagination, alt-text preview, thumbnail, MIME type, dimensions, last modified timestamp, and quick access to edit in Media Library.
- [ ] Inline metadata: title, file type, dimensions, last modified, recognition confidence indicator.
- [ ] Add quick filters: `All`, `Needs Alt Text`, `Has Draft`, `Flagged`, `Recently Updated` (5m, 1h, 24h).
- [ ] Integrate column sorter + search field that debounces against REST query params.
- [ ] Wire media search input to WordPress core `/wp/v2/media` endpoint (reuse `search`, `media_type`, `mime_type` params) with optimistic loading states; hydrate results into queue while preserving active filters/pagination.
    - [ ] Start with server-backed search that proxies the built-in media search (no custom index) and share nonce/auth plumbing with existing list fetches.
    - [ ] Map REST responses into Workbench entity cache so filter toggles + pagination survive while search terms are applied or cleared.
    - [ ] Provide inline loading/error affordances inside the search field (spinner, clear button, SR-only live status).
- [ ] Provide empty-state illustrations + copy when queue has zero items after filters applied.
- [ ] Skeleton shimmer + error states for list fetches; include retry button and aria-live messaging.
- [ ] Keyboard focus ring and roving tab index for card/list items.

## 3. Selection & Bulk Actions

- [ ] `SelectionToolbar` exposes multi-select (shift+click, keyboard range) with count of selected attachments.
- [ ] Bulk actions: `Generate Alt Text`, `Regenerate`, `Mark as Reviewed`, `Clear Selection`.
- [ ] Confirmation modals with preview of impacted items; include negative path (cancel) coverage.
- [ ] Bulk status updates cascade to list rows without full refetch (optimistic update + rollback).
- [ ] Persist last bulk action + timestamp for analytics instrumentation (`cat_workbench_bulk_action`).
- [ ] Provide `Select All in Filter` flow with backend acknowledgement to avoid stale selections.

## 4. Recognition & Context Modules

- [ ] `RecognitionActions` panel triggers face/brand recognition for selected items; display queued/running/completed states.
- [ ] Hook toggles recognition service availability (per roadmap remote dependency guard) and surfaces helpful error copy.
- [ ] Render recognition insights preview (faces, brands, scenes) with ability to jump to roster entries.
- [ ] Attachments display observation confidence + last synced roster entity.
- [ ] Design how roster workflow surfaces inside the Workbench (e.g., per-row roster match chips, quick links into Roster Manager, unresolved identity prompts) and document the integration plan.
- [ ] Instrument `cat_workbench_recognition_triggered` analytics event with selection size + filters.

## 5. Draft Authoring & Preview

- [ ] `BulkAltTextPanel` provides side-by-side original media + draft textarea with word/character counters.
- [ ] Live preview slider (before/after) as described in roadmap Epic B.
- [ ] Support AI-generated drafts (via `cat/generate_alt_text`) with spinner + fallback copy.
- [ ] Validation: enforce policy (length range, avoid banned phrases) before allowing submit.
- [ ] Save-as-draft vs publish toggles; publish writes to attachment alt text via REST mutation.
- [ ] Auto-save drafts every 30 seconds (configurable via settings) using debounced mutation.
- [ ] Display diff between current alt text and pending draft on hover/focus.

## 6. Accessibility & Keyboard System

- [ ] 100% keyboard navigation: selection, filters, bulk actions, preview panels.
- [ ] Shortcut map aligned with Dashboard (Command/Ctrl+Shift+G to generate, Command/Ctrl+Shift+F to focus filters, etc.).
- [ ] Toggleable shortcut helper overlay with audible descriptions, integrated with global accessibility system.
- [ ] Ensure screen reader announcements for selection changes, bulk action outcomes, and errors via aria-live regions.
- [ ] Provide high-contrast mode toggle or respect global preference, ensuring WCAG 2.1 AA compliance.

## 7. Telemetry & Observability

- [ ] Emit `cat_workbench_seen` when the page enters viewport, including filter context.
- [x] Track per-action analytics (generate, regenerate, mark reviewed, recognition trigger) via shared `emitDashboardEvent` utility.
- [ ] Log fetch failures to WordPress debug log with correlation IDs for remote service troubleshooting.
- [ ] Integrate client-side perf marks (First Render, First Interaction) for synthetic monitoring.

## 8. TDD Roadmap

- [ ] Component tests covering `MediaList` filtering, virtualized pagination, selection flows.
- [ ] Tests for `SelectionToolbar` keyboard shortcuts, analytics events, and optimistic updates.
- [ ] MSW-backed tests for recognition trigger success/failure states and bulk generation flows.
- [ ] Axe scans for Workbench route, ensuring no regressions when toggling list/grid or opening modals.
- [ ] Contract tests verifying `/wp-json/cat/v1/workbench/media` and `/wp-json/cat/v1/alt-text/bulk` schemas stay aligned with fixtures.
- [ ] PHPUnit coverage for new REST controllers (media queue, bulk operations, recognition triggers) including nonce/cap checks.

## 9. Dependencies & Integrations

- [ ] REST endpoints: `/workbench/media`, `/workbench/filters`, `/alt-text/bulk`, `/recognition/run` documented with JSON Schema under `docs/architecture/contracts/workbench/`.
- [ ] Ensure feature flags (e.g., `CAT_FEATURE_WORKBENCH_BULK_AI`) gracefully hide dependent UI.
- [ ] Coordinate with Roster Manager for cross-linking roster entities when recognition identifies matches.
- [ ] Sync queue state with Automation route to avoid conflicting bulk jobs.

## 10. Launch Checklist

- [ ] In-app walkthrough or tooltip tour introducing selection, generation, and preview features.
- [ ] QA matrix covering browsers (Chrome, Firefox, Safari), screen readers (VO, NVDA), and high DPI displays.
- [ ] Update README + docs with Workbench usage steps and keyboard shortcuts.
- [ ] Confirm telemetry dashboards ingest Workbench events before enabling feature flag in production builds.
- [ ] Run smoke script (WP-CLI or Playwright) exercising bulk generate + publish flow end-to-end.
