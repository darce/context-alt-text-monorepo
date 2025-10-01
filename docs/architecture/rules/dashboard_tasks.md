# Dashboard Experience Tasks

## 1. Hero Status

- Render headline message (`We found N images missing alt text`) sourced from the latest scan summary.
- Call-to-action button `Open Alt-Text Workbench` that routes to the SPA workbench surface.
- Adaptive copy:
  - `Scanning…` state when counts are not yet available.
  - `Scan complete — fix them now.` once results are ready.
- Display timestamp badge (timeago) for the last completed scan.

## 2. Diagnostic Cards (Two-Row Grid)

### Coverage & Trend
- Donut chart: missing vs total images to surface overall coverage percentage.
- Line chart (evaluate usefulness) showing progress over time as missing count declines; confirm signal clarity before committing.

Implementation steps:
- [x] Define shared `CoverageDonut` component in SPA primitives with props `{ total, withAlt, missing }`.
- [x] Expose `useCoverageMetrics()` hook that reads from REST endpoint `/wp-json/cat/v1/dashboard/coverage` (stubbed until backend ready).
- [ ] Persist coverage history (already captured via `MissingAltTextScanner`) and expose through same endpoint.
- [x] Build `CoverageTrend` component that consumes the history array, rendering a sparkline/line chart; gate behind feature flag until usefulness validated.
- [x] Add Storybook stories for both components (empty, partial, full coverage, and loading states).
- [x] Wire components into the dashboard page route and ensure data hydration via React Query.
- [ ] Replace bespoke coverage donut/sparkline markup with Radix UI primitives once the component library is available.
- [ ] Verify WordPress analytics listeners record the `cat_dashboard_card_seen` and `cat_dashboard_coverage_trend_enabled` events emitted by the dashboard UI.
- [ ] Define the migration plan (timing, primitives, fallbacks) for replacing the bespoke SVG donut/sparkline with Radix or a shared chart utility when available.
- [x] Replace the CSS pseudo-element radial illusion with an actual SVG doughnut chart that renders arcs based on coverage percentages; retire the `.cat-progress--radial` hack and avoid misusing `@radix-ui/react-progress` for circular visuals.
- [ ] Publish JSON Schema + golden example fixtures for `/wp-json/cat/v1/dashboard/coverage` covering both the summary fields and each `trend_series` entry; land them under `docs/architecture/contracts/dashboard/` so frontend/backends share the contract.
- [ ] Extend `MissingAltTextScanner` persistence so each completed scan appends a coverage snapshot to a bounded history store (keep last 30 entries) and expose a `wp cat dashboard backfill-coverage-history` CLI to seed existing installs.
- [x] Layer React Query states into the card (`isLoading`, `isRefetching`, `isError`) with skeleton, retry, and inline error copy; show a neutral "No Media Library items yet" message when `total === 0` instead of the chart.
- [x] Introduce narrated alternatives for the donut and trend (`aria-describedby` + visually hidden delta text) so screen readers receive the coverage percentage and latest change without relying on the SVGs.
- [x] Add Vitest + RTL coverage for `CoverageCard`, `CoverageDonut`, and the upcoming `CoverageTrend` verifying clamped percentages, zero-state messaging, feature-flag gating, and endpoint integration via MSW stubs.
- [x] Instrument analytics when the card enters the viewport (`cat_dashboard_card_seen`) and when the trend toggle/feature flag is enabled to measure sparkline engagement before graduating the feature.

### Latest Activity
- Card showing timestamps for:
  - Last recognition run
  - Last alt-text generation batch
  - Last roster sync
- Include quick links to relevant logs/detail views.

### Recognition Insights
- Counts of detected faces/brands awaiting approval or unresolved matches.
- Highlight potential follow-ups (e.g., `3 faces need review`).

### Automation Pipeline
- Status chips for queued/running/completed bulk jobs.
- Provide pending job count and next scheduled run time.

## TDD Test Suite Roadmap

- [ ] Draft failing tests for `HeroStatus` that codify scanning vs ready copy, CTA routing, and the timestamp badge before iterating on the component.
  - [x] Capture default bootstrap payload and assert the component renders the localized message variants using React Testing Library queries.
  - [x] Verify CTA button invokes `Open Alt-Text Workbench` navigation via mocked router history.
  - [x] Assert the relative timestamp badge updates when the query data changes (simulate via React Query invalidate).
- [x] Capture desired loading/empty/error behaviors for `CoverageCard` + `CoverageTrend` via component tests that assert skeletons, zero-state messaging, and feature-flagged trend rendering.
  - [x] Define MSW handlers for success, timeout, and empty dataset responses to drive Vitest scenarios.
  - [x] Assert the donut clamps values, trend hides when feature flag off, and zero-library message replaces charts.
  - [x] Document the pending trend flag in the test file so toggling the flag requires updating expectations.
- [ ] Add integration-style tests for `LatestActivity`, `RecognitionInsights`, and `AutomationPipeline` cards that assert placeholder/resolved states so future UI slices stay regression-safe.
  - [x] Mock dashboard bootstrap payload with partial data to confirm fallbacks and skeleton UIs render correctly.
  - [ ] Validate that resolved state links/buttons route to expected URLs using a shared test utility.
  - [x] Cover edge cases (null timestamps, zero counts) to lock in desired copy and avoid regressions during refactors.
- [ ] Introduce a dashboard page smoke test that mounts the full SPA route with MSW-powered REST fixtures to enforce data hydration contracts as new cards land.
  - [x] Stand up a shared `renderDashboard` helper that wraps React Query provider, router, and theme tokens.
  - [ ] Assert hydration requests hit the expected endpoints and respond to refetch events.
  - [ ] Include an accessibility audit snapshot (axe) to catch regressions as new components arrive.

### WordPress (PHPUnit + WP-CLI Acceptance)
- [ ] Create PHPUnit controller tests that specify the `/wp-json/cat/v1/dashboard/coverage` contract, including history window rules, zero-library handling, and REST nonce requirements.
  - [ ] Lock the JSON schema by comparing controller responses against the published fixture using `wp_json_file_decode` and `assertSame`.
  - [ ] Simulate nonce failures and insufficient capability to ensure the endpoint rejects unauthorized access.
  - [ ] Verify history trimming logic keeps the most recent 30 entries with deterministic timestamps supplied via a fake clock helper.
- [ ] Add acceptance-style WP_CLI tests documenting the expected output/side-effects of the upcoming `wp cat dashboard backfill-coverage-history` command.
  - [ ] Create a disposable test site fixture with legacy scans and assert the command backfills missing history rows.
  - [ ] Confirm idempotency by running the command twice and ensuring no duplicate rows appear.
  - [ ] Capture error messaging when the scanner has never been executed to guide ops troubleshooting.
- [ ] Expand backend tests for scan orchestration so each completed `MissingAltTextScanner` run records a coverage snapshot and triggers any async analytics hooks.
  - [ ] Introduce a fake analytics transport and assert events fire with the correct payload after persistence.
  - [ ] Ensure transactional rollbacks on failure do not persist partial history entries.
  - [ ] Verify cron-driven and manual scan triggers share the same recording path via data providers.
- [ ] Seed fixtures + contract assertions for dashboard bootstrap payloads to keep frontend and backend synchronized as new cards and metrics ship.
  - [ ] Store canonical bootstrap JSON under `docs/architecture/contracts/dashboard/bootstrap.json` and reference it in tests.
  - [ ] Write assertions that the localized bootstrap enqueues expected cards and omits feature-flagged entries by default.
  - [ ] Add smoke coverage for the enqueue script to confirm the payload survives serialization/deserialization.

## 3. Actionable Footer

- Quick actions:
  - `Run scan again`
  - `Generate drafts for selection`
  - `Sync roster`
- Secondary text: `Last scan completed X minutes ago.`
- Consistent color palette (warning for missing alt text, success for completed tasks).
- Small sparkline/iconography per card to convey liveliness.

## Component & Styling Stack

- [x] Integrate Radix UI headless primitives across dashboard surfaces (buttons, progress, tooltips). Cards remain bespoke (documented in Storybook notes).
- [x] Introduce a lightweight SCSS design token layer (colors, spacing, typography) and wire Vite to compile `.scss` into the bundle.
- [x] Refactor existing React components to wrap Radix primitives; only author bespoke components when Radix lacks an equivalent. Document any exceptions in Storybook.
- [x] Update Storybook stories to showcase Radix-based components and demonstrate theme overrides via SCSS tokens.

## Layout Notes

- Structure: hero at top, two rows of diagnostic cards, footer CTA row.
- Ensure cards respond gracefully on narrower screens (stack to single column).
- Integrate with SPA data layer (React Query or equivalent) for live refresh without reloads.
