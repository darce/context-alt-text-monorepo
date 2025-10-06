# Alt-Text Workbench Tasks

Admin surface for prioritizing attachments missing descriptive text, triaging recognition insights, and generating or approving captions. Aligns with roadmap v3.0 Phase 1 objectives and Tasks backlog items for the Workbench route and modules.

## 1. Workbench Shell

- [x] Route `AltTextWorkbench` under SPA router with feature-gated nav entry
- [x] Component created (`WorkbenchApp.tsx`)
- [x] Hydrate initial payload via `ContextAltTextAdmin.data.workbench` with counts, filters, user preferences
- [x] Provide React Query hydration + refetch plumbing for attachments, selection state, and recognition jobs
- [ ] Wire page-level toasts/notices to shared notification system
- [ ] Persist user layout preference (grid/list, column order) in REST-backed user meta
- [ ] Add Storybook stories for WorkbenchApp
- [ ] Integration tests for workbench route hydration

## 2. Media Queue (Grid/List)

<!-- markdownlint-disable-next-line MD024 -->
### Component Status

- [x] Component created (`MediaList.tsx`)
- [x] List layout rendering one row per asset with thumbnail, metadata
- [x] Props: items, selectedIds, onToggleSelect, viewMode
- [x] Surface alt-text status chips (Missing, Draft, Published)
- [x] Inline WordPress edit links for each media item
- [x] Inline metadata: title, file type, dimensions, last modified
- [x] Keyboard focus ring and roving tab index for list items (space/enter to select)
- [x] Empty-state copy when queue has zero items after filters applied
- [ ] Grid view variant (currently list-only)
- [ ] Virtualized scrolling for large libraries (deferred: only needed when library > 1000 items)
- [ ] Recognition confidence indicator (deferred to post-MVP)
- [ ] Quick filters UI: `All`, `Needs Alt Text`, `Has Draft`, `Flagged`, `Recently Updated`
- [ ] Column sorter integration
- [ ] Skeleton shimmer loading states (currently uses global loading)

### Search & Filtering

- [x] Wire media search input to custom REST endpoint `/context-alt-text/v1/workbench/media`
- [x] Server-backed search integrated with WP_Query search functionality
- [x] React Query caching with filter state preservation during search
- [x] Supports `search`, `status`, pagination query params
- [x] Optimistic loading states during search
- [x] Provide inline loading/error affordances inside search field (spinner, clear button)
- [x] Search debouncing (currently immediate)
- [x] SR-only live status announcements for search results
- [ ] Advanced filter dropdown with multiple status options

### Pagination

- [x] Component created (`PaginationControls.tsx`)
- [x] Props: currentPage, totalPages, onPageChange, loading state
- [x] Previous/Next navigation
- [x] Page number display
- [x] Jump to page input
- [x] Items per page selector
- [x] Total items count display

## 3. Selection & Bulk Actions

<!-- markdownlint-disable-next-line MD024 -->
### Component Status

- [x] Component created (`SelectionToolbar.tsx`)
- [x] Props: selectedIds, totalCount, onClearSelection, onBulkAction
- [x] Multi-select with count of selected attachments
- [x] Bulk actions wired: `Generate Alt Text`, `Regenerate`, `Mark as Reviewed`, `Clear Selection`
- [x] Clear Selection button with count display
- [ ] Shift+click range selection
- [ ] Keyboard range selection (Shift+Arrow)
- [ ] "Select All" checkbox in toolbar
- [ ] "Select All in Filter" flow with backend acknowledgement
- [ ] Confirmation modals with preview of impacted items
- [ ] Optimistic UI updates for bulk actions (currently triggers full refetch)
- [ ] Rollback mechanism on bulk action failure
- [ ] Persist last bulk action + timestamp for analytics (`cat_workbench_bulk_action`)
- [ ] Bulk action progress indicators (for long-running operations)
- [ ] Unit tests for SelectionToolbar
- [ ] Storybook stories for selection states

## 4. Recognition & Context Modules

<!-- markdownlint-disable-next-line MD024 -->
### Component Status

- [x] Component created (`RecognitionActions.tsx`)
- [x] Props: selectionCount, disabled, onTriggerRecognition
- [x] Panel triggers face/brand recognition for selected items
- [x] Feature flag toggles recognition service availability
- [x] Disabled state when no items selected or service unavailable
- [ ] Job queue status display (queued/running/completed states)
- [ ] Surface helpful error copy when recognition service fails
- [ ] Render recognition insights preview in MediaList rows
- [ ] Display observation confidence scores (post-MVP)
- [ ] Display matched roster entities (post-MVP)
- [ ] Unit tests for RecognitionActions
- [ ] Storybook stories for various states

### Backend Integration

**MVP Recognition Flow** (Backend-Only Architecture per Roadmap):

1. Workbench triggers recognition via `onTriggerRecognition` callback
2. WP REST endpoint `/context-alt-text/v1/recognition/analyze`
3. Backend Recognition Service processes request (`/api/v0/analyze-scene`)
4. **All face detection, recognition, and roster matching happens in backend**
5. Results stored as observations in WP database
6. Observations used during alt-text generation
7. **No frontend face tagging or roster management in MVP**

### Post-MVP Enhancements

- [ ] Design roster workflow UI for Workbench (per-row match chips, quick links)
- [ ] Unresolved identity prompts with manual assignment flow
- [ ] Recognition confidence visualization (color-coded badges)
- [ ] Quick preview of detected faces/brands on hover
- [ ] Link to full roster manager for entity details

### Analytics

- [ ] Instrument `cat_workbench_recognition_triggered` event
- [ ] Track selection size + active filters in event payload
- [ ] Track success/failure rates
- [ ] Track average processing time

## 5. Draft Authoring & Preview

<!-- markdownlint-disable-next-line MD024 -->
### Component Status

- [x] Component created (`BulkAltTextPanel.tsx`)
- [x] Props: selectedIds, items, onGenerateDrafts, onSaveDrafts
- [x] Component created (`MediaPreview.tsx`)
- [x] Props: selectedIds, items
- [x] Preview display for selected media items
- [ ] Side-by-side original media + draft textarea layout
- [ ] Word/character counters
- [ ] Live preview slider (before/after) per roadmap Epic B
- [ ] AI-generated drafts via `cat/generate_alt_text` with loading states
- [ ] Loading spinner during draft generation
- [ ] Fallback copy when generation fails
- [ ] Draft validation: length range enforcement
- [ ] Draft validation: banned phrases check
- [ ] Save-as-draft vs publish toggle buttons
- [ ] REST mutation to write published alt text to attachment
- [ ] Auto-save drafts every 30 seconds (debounced)
- [ ] Configurable auto-save interval via settings
- [ ] Display diff between current and pending draft
- [ ] Diff highlighting on hover/focus
- [ ] Undo/redo for draft edits
- [ ] Unit tests for BulkAltTextPanel and MediaPreview
- [ ] Storybook stories for authoring workflows

## 6. Accessibility & Keyboard System

- [ ] 100% keyboard navigation: selection, filters, bulk actions, preview panels
- [ ] Shortcut map aligned with Dashboard (Command/Ctrl+Shift+G to generate, Command/Ctrl+Shift+F to focus filters)
- [ ] Toggleable shortcut helper overlay with audible descriptions
- [ ] Screen reader announcements for selection changes via aria-live regions
- [ ] Screen reader announcements for bulk action outcomes
- [ ] Screen reader announcements for errors
- [ ] High-contrast mode toggle or respect global preference
- [ ] WCAG 2.1 AA compliance verification
- [ ] Keyboard focus trap management for modals
- [ ] Skip links for main content areas

## 7. Telemetry & Observability

- [ ] Emit `cat_workbench_seen` when page enters viewport with filter context
- [x] Track per-action analytics via shared `emitDashboardEvent` utility
- [x] Analytics for: generate, regenerate, mark reviewed, recognition trigger
- [ ] Log fetch failures to WordPress debug log with correlation IDs
- [ ] Integrate client-side perf marks (First Render, First Interaction)
- [ ] Track filter usage patterns
- [ ] Track search query patterns
- [ ] Track bulk action success/failure rates
- [ ] Track average time to complete workflows

## 8. Testing Strategy

### Component Tests

- [ ] MediaList filtering, pagination, selection flows
- [ ] SelectionToolbar keyboard shortcuts, analytics events
- [ ] SelectionToolbar optimistic updates and error handling
- [ ] RecognitionActions success/failure states (MSW-backed)
- [ ] BulkAltTextPanel draft generation flows (MSW-backed)
- [ ] PaginationControls navigation and boundary conditions
- [ ] MediaPreview rendering with various media types

### Accessibility Tests

- [ ] Axe scans for Workbench route
- [ ] No regressions when toggling list/grid
- [ ] No regressions when opening modals
- [ ] Keyboard-only navigation verification
- [ ] Screen reader announcement verification

### Contract Tests

- [ ] `/wp-json/cat/v1/workbench/media` schema validation
- [ ] `/wp-json/cat/v1/alt-text/bulk` schema validation
- [ ] `/wp-json/cat/v1/recognition/analyze` schema validation
- [ ] Fixtures aligned with OpenAPI specs

### Backend Tests (PHPUnit)

- [ ] REST controller for media queue endpoint
- [ ] REST controller for bulk operations endpoint
- [ ] REST controller for recognition trigger endpoint
- [ ] Nonce validation for all mutation endpoints
- [ ] Capability checks for all endpoints
- [ ] Pagination and filtering logic
- [ ] Search query sanitization

## 9. REST API Contracts

### Required Endpoints

- [x] `GET /wp-json/context-alt-text/v1/workbench/media` (implemented)
  - Query params: `search`, `status`, `page`, `per_page`
  - Returns: paginated media items with alt-text status
- [ ] `POST /wp-json/context-alt-text/v1/alt-text/bulk`
  - Body: `{ action: 'generate'|'regenerate'|'mark_reviewed', attachment_ids: number[] }`
  - Returns: job_id or immediate results for small batches
- [ ] `POST /wp-json/context-alt-text/v1/recognition/analyze`
  - Body: `{ attachment_ids: number[] }`
  - Returns: job_id or immediate analysis results
- [ ] `GET /wp-json/context-alt-text/v1/workbench/filters`
  - Returns: available filter options and counts
- [ ] `PUT /wp-json/context-alt-text/v1/user-preferences`
  - Body: `{ layout: 'grid'|'list', columns: string[], auto_save_interval: number }`
  - Returns: updated preferences

### JSON Schema Documentation

- [ ] Publish schemas under `docs/architecture/contracts/workbench/`
- [ ] Create golden fixtures for each endpoint
- [ ] Frontend/backend sync on field names and types
- [ ] Versioning strategy for breaking changes

## 10. Feature Flags & Dependencies

### Feature Flags

- [x] `CAT_FEATURE_WORKBENCH` - Master toggle for workbench route
- [x] `CAT_FEATURE_RECOGNITION` - Recognition service availability
- [ ] `CAT_FEATURE_WORKBENCH_BULK_AI` - AI-powered bulk generation
- [ ] `CAT_FEATURE_WORKBENCH_GRID_VIEW` - Grid view variant
- [ ] `CAT_FEATURE_AUTO_SAVE_DRAFTS` - Auto-save functionality

### Integrations

- [ ] Coordinate with Roster Manager for cross-linking entities (post-MVP)
- [ ] Sync queue state with Automation route to avoid conflicts
- [ ] Share notification system with Dashboard
- [ ] Share analytics infrastructure with Dashboard

## 11. Launch Checklist

- [ ] In-app walkthrough or tooltip tour for first-time users
- [ ] Introduction to selection and bulk actions
- [ ] Introduction to recognition triggers
- [ ] Introduction to draft preview and publishing
- [ ] QA matrix covering:
  - Browsers: Chrome, Firefox, Safari, Edge
  - Screen readers: VoiceOver, NVDA, JAWS
  - High DPI displays (Retina, 4K)
  - Mobile responsive breakpoints
- [ ] Update README with Workbench usage documentation
- [ ] Document keyboard shortcuts in user guide
- [ ] Confirm telemetry dashboards ingest Workbench events
- [ ] Run smoke script (WP-CLI or Playwright)
- [ ] Exercise bulk generate + publish flow end-to-end
- [ ] Performance validation on large libraries (>1000 items)

## Related Documentation

- `docs/architecture/frontend-uml/media-selection-workflow.mmd` - Workbench data flow
- `docs/architecture/frontend-uml/face-recognition-workflow.mmd` - Recognition integration
- `docs/architecture/frontend-uml/workbench-flow.mmd` - User interaction flows
- `docs/architecture/rules/roadmap-v3.md` - Phase 1 Epic requirements
- `docs/architecture/contracts/workbench/` - API schemas and fixtures (to be created)
