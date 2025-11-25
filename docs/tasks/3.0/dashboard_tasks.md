# Dashboard Tasks

Admin home screen providing at-a-glance metrics, activity feed, recognition insights, and automation pipeline status. Aligns with roadmap v3.0 Phase 1 (Epic D) objectives and serves as the primary navigation entry point for the plugin.

## Overview

The Dashboard provides at-a-glance status through **six key components**:

1. **Hero Status Banner** — Primary accessibility signal and scan status
2. **Coverage Card** — Visual progress tracking with donut chart and trend
3. **Activity Card** — Recent operation timestamps and activity feed
4. **Recognition Insights Card** — Pending face/brand recognition work
5. **Automation Pipeline Card** — Background job queue status
6. **Action Footer** — Quick-access CTAs and navigation

All components are React/TypeScript with comprehensive test coverage, accessibility compliance, and analytics instrumentation.

---

## 1. Hero Status Banner

### Component Status

- [x] Component created (`HeroStatus.tsx`)
- [x] Unit tests with state variants (`HeroStatus.test.tsx`)
- [x] State-driven styling (info, warning, success, error)
- [x] CTA button with dynamic routing
- [x] Relative timestamp display
- [ ] Storybook story with all state variants
- [ ] Integration with real-time scan status

### Backend Work

- [ ] PHP `HeroStatusService` calculates current state
- [ ] REST endpoint `/wp-json/cat/v1/dashboard/hero` (optional live refresh)
- [ ] Hook into first-run scan completion to update state
- [ ] Admin notice integration for critical states

### Testing Needs

- [x] Renders message and CTA correctly
- [x] State-based CSS class application
- [x] Timestamp formatting (human-readable)
- [x] Missing/null data handling
- [ ] Screen reader announcements (aria-live regions)

### Accessibility Work

- [x] Semantic HTML structure
- [ ] ARIA landmarks for status section
- [ ] Live region for dynamic updates
- [ ] Keyboard navigation to CTA button

---

## 2. Coverage Card

Shows alt-text coverage metrics with donut chart visualization and optional trend sparkline.

### Component Status

- [x] Component created (`CoverageCard.tsx`)
- [x] Donut chart sub-component (`CoverageDonut.tsx`)
- [x] Trend sparkline sub-component (`CoverageTrend.tsx`)
- [x] Unit tests with multiple scenarios (`CoverageCard.test.tsx`)
- [x] Storybook stories (`CoverageCard.stories.tsx`)
- [x] React Query integration with `useCoverageMetrics()` hook
- [x] Loading/error states with retry button
- [x] Feature flag for trend display (`featureFlags.coverageTrend`)
- [x] Analytics instrumentation (card seen, trend enabled)
- [x] Accessibility: aria-describedby for donut and trend
- [x] Zero-state messaging when no library items exist
- [ ] Drill-down click to open Workbench filtered view
- [ ] Export coverage report action (CSV/PDF)

### Backend Work

- [x] REST endpoint `/wp-json/cat/v1/dashboard/coverage` (stub exists)
- [ ] PHP `CoverageMetricsService` calculates metrics from scanner data
- [ ] Persist coverage history on each `MissingAltTextScanner` run
- [ ] Return trend data points (last 30 snapshots, bounded)
- [ ] Add query parameter for date range filtering (?days=7,30,90)
- [ ] Implement caching with WP Transients API (5-minute cache)
- [ ] Add breakdown by MIME type (images, videos, PDFs)

### Data Contract Work

- [ ] Publish JSON Schema for `/wp-json/cat/v1/dashboard/coverage` response
- [ ] Create golden fixture under `docs/architecture/contracts/dashboard/coverage.json`
- [ ] Document `trend_series` array structure (timestamp, coverage_percent, total, with_alt, missing)
- [ ] Frontend/backend sync on field names and types

### Testing Needs

- [x] Percentage clamping (0-100 range)
- [x] Zero-state messaging when total === 0
- [x] Feature flag gating for trend display
- [x] MSW stubs for endpoint integration
- [x] Loading skeleton display
- [x] Error state with retry button
- [x] Screen reader alternatives (aria-describedby)
- [ ] Drill-down navigation behavior
- [ ] Export action triggering

### Analytics Work

- [x] IntersectionObserver tracks card visibility
- [x] Emit `cat_dashboard_card_seen` event
- [x] Emit `cat_dashboard_coverage_trend_enabled` when trend is shown
- [ ] Track drill-down clicks: `cat_coverage_drilldown`
- [ ] Track export actions: `cat_coverage_export`

---

## 3. Activity Card

Shows recent plugin activity timestamps (alt-text generation, recognition jobs, manual edits, roster syncs).

### Component Status

- [x] Component created (`ActivityCard.tsx`)
- [x] Unit tests (`ActivityCard.test.tsx`)
- [x] Display list of recent activities with relative timestamps
- [x] Tooltip support for timestamp details
- [x] Format relative timestamps ("2 hours ago", "yesterday")
- [x] Empty state handling ("No recent activity")
- [ ] Activity type icons (generated, manual edit, recognition, error)
- [ ] "View All Activity" link to full activity log page
- [ ] Filtering by activity type (dropdown or tabs)
- [ ] Show user avatars for manual edit activities
- [ ] Pagination or "Load More" for long lists
- [ ] Real-time updates for new activities

### Backend Work

- [ ] Create `GET /wp-json/cat/v1/dashboard/activity` endpoint
- [ ] Return array of activity objects with type, message, timestamp, user, attachment_id
- [ ] Add pagination support (?page=1&per_page=10)
- [ ] Add filtering by activity type (?type=generation,recognition,manual)
- [ ] Add capability check (manage_options)
- [ ] Store activities in custom table or post meta for performance

### Activity Types Needed

- [ ] `alt_text_generated` - Automatic generation completed
- [ ] `alt_text_edited` - Manual edit by user
- [ ] `recognition_completed` - Face/brand recognition finished
- [ ] `recognition_failed` - Recognition job error
- [ ] `bulk_generation_started` - Bulk job initiated
- [ ] `bulk_generation_completed` - Bulk job finished
- [ ] `roster_synced` - Roster sync completed

---

## 4. Recognition Insights Card

Shows recognition insights: pending faces/brands, unresolved matches, confidence scores.

### Component Status

- [x] Component created (`RecognitionCard.tsx`)
- [x] Unit tests (`RecognitionCard.test.tsx`)
- [x] Display count of pending face detections
- [x] Display count of pending brand detections
- [x] Show count of unresolved matches
- [x] Warning styling for non-zero counts
- [ ] "Review Matches" button linking to recognition review page
- [ ] Show average confidence score for recent recognitions
- [ ] Empty state when no recognition data available
- [ ] Visual indicators for confidence levels (high/medium/low)
- [ ] Quick preview of top unresolved matches (thumbnails)
- [ ] "Sync Roster" action button

### Backend Work

- [ ] Create `GET /wp-json/cat/v1/dashboard/recognition` endpoint
- [ ] Return counts of pending detections, unresolved matches
- [ ] Include sample of top unresolved matches with thumbnails
- [ ] Add average confidence score calculation
- [ ] Add capability check (manage_options)
- [ ] Query custom recognition tables for metrics
- [ ] Add roster sync status indicator (last sync timestamp)
- [ ] Cache recognition metrics for 2 minutes

### Integration Work

- [ ] Query recognition observations from custom tables
- [ ] Calculate pending counts (faces/brands without roster matches)
- [ ] Calculate unresolved counts (matches below confidence threshold)
- [ ] Provide sample matches for preview

---

## 5. Automation Pipeline Card

Shows pipeline status: queued jobs, running jobs, completed jobs, error states.

### Component Status

- [x] Component created (`AutomationCard.tsx`)
- [x] Unit tests (`AutomationCard.test.tsx`)
- [x] Display count of queued jobs
- [x] Display count of running jobs
- [x] Display count of completed jobs (last 24 hours)
- [x] Display next scheduled run time
- [ ] Display count of failed jobs with error state
- [ ] "View Queue" button linking to automation queue page
- [ ] Progress bars for running jobs
- [ ] Estimated time remaining for queued jobs
- [ ] "Pause/Resume Queue" action button
- [ ] Real-time updates for job status changes
- [ ] Retry action for failed jobs

### Backend Work

- [ ] Create `GET /wp-json/cat/v1/dashboard/automation` endpoint
- [ ] Return job counts by status (queued, running, completed, failed)
- [ ] Include running jobs with progress percentages
- [ ] Include failed jobs with error messages
- [ ] Add capability check (manage_options)
- [ ] Query Action Scheduler or custom job queue table

### Job Queue Integration

- [ ] Integrate with Action Scheduler API for job status
- [ ] Query pending actions: `as_get_scheduled_actions()`
- [ ] Query running actions: `as_get_scheduled_actions(['status' => 'in-progress'])`
- [ ] Query failed actions with error logs
- [ ] Calculate progress for batch jobs (completed / total items)

---

## 6. Action Footer

Call-to-action footer with primary action buttons and quick links.

### Component Status

- [x] Component created (`ActionFooter.tsx`)
- [x] Unit tests (`ActionFooter.test.tsx`)
- [ ] Add primary CTA: "Generate Alt Text" button (opens Workbench)
- [ ] Add secondary CTA: "Review Recognition" button (opens recognition page)
- [ ] Add quick link: "View All Activity"
- [ ] Add quick link: "Plugin Settings"
- [ ] Implement responsive layout (stack on mobile)
- [ ] Add keyboard navigation support
- [ ] Style with WordPress button classes for consistency

---

## 7. Dashboard-Wide Features

### Performance Optimization

- [x] React Query caching implemented for coverage metrics
- [ ] Implement stale-while-revalidate strategy for all endpoints
- [ ] Add request deduplication for concurrent fetches
- [ ] Implement optimistic updates for actions (pause/resume queue)
- [ ] Code split dashboard cards for smaller initial bundle
- [ ] Implement virtual scrolling for activity feed if > 100 items
- [ ] Add performance monitoring: track render times

### Error Handling

- [x] Inline retry button on CoverageCard on fetch error
- [ ] Implement error boundaries for each dashboard card
- [ ] Show user-friendly error messages (no stack traces)
- [ ] Add "Report Issue" link on error states
- [ ] Log errors to browser console with context
- [ ] Send critical errors to backend logging endpoint
- [ ] Implement graceful degradation (show cached data on error)
- [ ] Add offline detection and appropriate messaging

### Accessibility

- [x] Basic ARIA attributes on CoverageCard
- [ ] Add comprehensive ARIA labels to all cards
- [ ] Ensure all interactive elements are keyboard accessible
- [ ] Add screen reader announcements for dynamic updates
- [ ] Implement focus management for modals/overlays
- [ ] Add skip links for dashboard sections
- [ ] Ensure color contrast meets WCAG AA standards
- [ ] Add reduced motion alternatives for animations
- [ ] Test with screen readers (NVDA, JAWS, VoiceOver)

### Internationalization

- [ ] Extract all user-facing strings to translation functions
- [ ] Use `wp.i18n.__()` for translations
- [ ] Add text domain: `context-alt-text`
- [ ] Generate `.pot` file for translators
- [ ] Test with RTL languages (Arabic, Hebrew)
- [ ] Format numbers/dates according to locale

### Configuration

- [x] Feature flag for CoverageTrend: `featureFlags.coverageTrend`
- [ ] Add user preference for dashboard layout (compact/expanded)
- [ ] Add user preference for auto-refresh interval
- [ ] Add user preference for which cards to show/hide
- [ ] Add admin setting for default dashboard view
- [ ] Store preferences in user meta: `wp_usermeta`
- [ ] Add "Reset to Defaults" action

### Help & Onboarding

- [ ] Add contextual help tooltips for each card
- [ ] Implement first-time user onboarding tour
- [ ] Add "What's This?" help icon on complex metrics
- [ ] Link to documentation for each dashboard section
- [ ] Add empty state messaging with getting started guide
- [ ] Implement feature announcements for new capabilities

---

## 8. Testing Strategy

### Frontend Tests (Vitest + RTL)

- [x] Unit tests for HeroStatus, CoverageCard, ActivityCard
- [x] Storybook stories for CoverageCard variations
- [x] MSW stubs for endpoint integration
- [ ] Complete unit test coverage for all dashboard components (>90%)
- [ ] Integration tests for dashboard data fetching
- [ ] Accessibility tests with axe-core for all components
- [ ] Visual regression tests with Percy or Chromatic

### Backend Tests (PHPUnit)

- [ ] PHPUnit controller tests for `/wp-json/cat/v1/dashboard/coverage` contract
- [ ] Lock JSON schema by comparing responses against published fixture
- [ ] Simulate nonce failures and insufficient capability
- [ ] Verify history trimming logic keeps most recent 30 entries
- [ ] Test scan orchestration records coverage snapshots
- [ ] Seed fixtures + contract assertions for dashboard bootstrap payloads

### E2E Tests (Playwright/Cypress)

- [ ] Load dashboard and verify all cards render
- [ ] Click through to Workbench from coverage card
- [ ] Interact with automation queue (pause/resume)
- [ ] Review recognition matches
- [ ] Test error states and retry actions
- [ ] Test responsive behavior on mobile

---

## 9. Success Metrics

- **Coverage Card**: Users click through to Workbench at >20% rate
- **Activity Card**: Users engage with activity log within first session
- **Recognition Card**: Users review pending matches within 24 hours of detection
- **Automation Card**: Users monitor queue status regularly (>3 times/week)
- **Performance**: Dashboard initial load < 1.5s on 3G connection
- **Accessibility**: All cards pass axe-core audit with zero critical issues
- **Test Coverage**: >90% line coverage across all dashboard components

---

## 10. Dependencies

- **WordPress REST API**: All dashboard endpoints under `/wp-json/cat/v1/dashboard/*`
- **React Query**: For data fetching, caching, and synchronization
- **Action Scheduler**: For job queue metrics (AutomationCard)
- **Custom Tables**: Recognition observations, activity log
- **Feature Flags**: From `ContextAltTextAdmin.featureFlags`
- **Analytics**: Event tracking via `emitDashboardEvent()`
- **Radix UI**: Headless primitives for accessible components
- **SCSS**: Design token layer for theming

---

## Related Documentation

- `docs/architecture/frontend-uml/dashboard-coverage-detail-v2.mmd` - CoverageCard data flow
- `docs/architecture/frontend-uml/admin-spa-modules-v2.mmd` - Dashboard routing
- `docs/architecture/frontend-uml/sequence-complete-workflow.mmd` - Complete workflow sequences
- `docs/architecture/rules/roadmap-v3.md` - Phase 1 (Epic D) requirements
