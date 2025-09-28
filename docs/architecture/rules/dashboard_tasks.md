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
1. Define shared `CoverageDonut` component in SPA primitives with props `{ total, withAlt, missing }`.
2. Expose `useCoverageMetrics()` hook that reads from REST endpoint `/wp-json/cat/v1/dashboard/coverage` (stubbed until backend ready).
3. Persist coverage history (already captured via `MissingAltTextScanner`) and expose through same endpoint.
4. Build `CoverageTrend` component that consumes the history array, rendering a sparkline/line chart; gate behind feature flag until usefulness validated.
5. Add Storybook stories for both components (empty, partial, full coverage, and loading states).
6. Wire components into the dashboard page route and ensure data hydration via React Query.
7. Replace bespoke coverage donut/sparkline markup with Radix UI primitives once the component library is available.
8. Replace the CSS pseudo-element radial illusion with an actual SVG doughnut chart that renders arcs based on coverage percentages; retire the `.cat-progress--radial` hack and avoid misusing `@radix-ui/react-progress` for circular visuals.

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

## 3. Actionable Footer

- Quick actions:
  - `Run scan again`
  - `Generate drafts for selection`
  - `Sync roster`
- Secondary text: `Last scan completed X minutes ago.`
- Consistent color palette (warning for missing alt text, success for completed tasks).
- Small sparkline/iconography per card to convey liveliness.

## Component & Styling Stack

- [ ] Integrate Radix UI headless primitives across dashboard surfaces (cards, buttons, dialogs, dropdowns) to standardize accessibility and keyboard behaviour.
- [ ] Introduce a lightweight SCSS design token layer (colors, spacing, typography) and wire Vite to compile `.scss` into the bundle.
- [ ] Refactor existing React components to wrap Radix primitives; only author bespoke components when Radix lacks an equivalent. Document any exceptions in Storybook.
- [ ] Update Storybook stories to showcase Radix-based components and demonstrate theme overrides via SCSS tokens.

## Layout Notes

- Structure: hero at top, two rows of diagnostic cards, footer CTA row.
- Ensure cards respond gracefully on narrower screens (stack to single column).
- Integrate with SPA data layer (React Query or equivalent) for live refresh without reloads.
