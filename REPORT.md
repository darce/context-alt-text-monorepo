# Lane C report — D-2 + D-22 + D-23

## Result

MECE six-item ACX IA (glossary names kept). Review Queue is the only naming home. One primary per screen. Twenty form/queue/forced_choice/ai_review zones declare loading/empty/error; components render those failure branches.

Final HEAD: recorded by the integrator after transplant.

## Commits (subject lines only)

- `docs(ux-maps): D-2 proposed IA`
- `fix(admin): D-2 MECE submenu homes`
- `fix(admin): D-22 one primary per screen`
- `fix(admin): D-23 zone failure states`

## Taxonomy (D-2)

One home per goal; frequency after the required WP parent (`docs/ux-maps/dashboard.md:14`):

| Order | menu_title | goal |
| --- | --- | --- |
| 1 | Overview | orient |
| 2 | Review Queue | name a person from unnamed faces (highest-frequency demo task) |
| 3 | People | manage named people |
| 4 | Description Runs | see what the describer did |
| 5 | Data Retention | keep/delete/export policy |
| 6 | Settings | configure service (rare, last) |

`SUBMENU_IA` pins unique goals (`apps/prototype-wp-alt-context/src/admin/class-menu.php:15`). Unassigned-person guidance targets Review Queue (`GuidanceCard.tsx:52`).

## TDD RED (verbatim)

D-2 PHP: `Failed asserting that false is true.` (`MenuTest::testSubmenusAreMeceFrequencyOrderedAndCapabilityStable`)

D-2 JS: `Expected the element to have attribute: href="#/workbench?tab=scan"` / `Received: href="#/roster?personFilter=unassigned"`

D-22: `Expected the element to have class: acx-button--secondary` / `Received: acx-button acx-button--primary`

D-23 scatter error (after literalizing the assert): `Expected element to have text content: Unable to load face group scatter.` / `Received: scatter failedRetry`

## TEST-15 mutants (production mutated, suite RED, restored)

- D-2: `SUBMENU_IA` naming slug pointed at People. RED: expected `alt-context-workbench` got `alt-context-roster`. Restore clean.
- D-22: Fix missing descriptions class flipped to `--primary`. RED: expected `--secondary`. Restore clean.
- D-23: scatter error copy `Unable to load face group scatter.` → `scatter failed`. RED as above. Restore clean. First mutant used the production constant as the expected string (TEST-15 false green); assert is now a literal.

## Code (sed-verified after last code commit)

- `class-menu.php:15` — `SUBMENU_IA`
- `GuidanceCard.tsx:52` — `href={toWorkbench({ tab: 'scan' })}`
- `DashboardPage.tsx:242` — Fix missing descriptions `--secondary`
- `DashboardSyncHealthSection.tsx:186` — Open Review Queue `--secondary`
- `WorkbenchPage.tsx:207` — `<FaceGroupScatter`
- `PersonWorkspacePanel.tsx:237` — `Unable to load linked faces.`
- `ClusterDrawerPanel.tsx:562` — `No named people to assign yet.`
- `MediaSelection.tsx:338` — `Loading filters…`
- `FaceGroupScatter.tsx:23` — scatter error copy
- `MediaSelection.tsx:291` — status `<Select.Root>` still value-only (INT-02)

## Verification

- `composer test:unit -- --filter MenuTest` — OK (5 tests, 51 assertions)
- vitest: GuidanceCard/DashboardPage D-2+D-22, uxmap parity, uxmap-one-primary, FaceGroupScatter, MediaSelectionToolbar failure, PersonWorkspacePanel, ClusterDrawerPanel, ConflictInbox, DeadLetterPanel, SettingsPage, IdentityClusterList, WorkbenchPage — passed
- `npm run typecheck` — clean

## Undone

- WP parent slug stays `alt-context-dashboard` (`class-admin.php` out of ownership); Review Queue cannot become the top-level click.
- Workbench-control NameFaceControl / person-commit still uses `button-primary`; map demotes name to secondary — visual leftover vs `act-run-recognition`.
- Several D-23 first_time/edge_input/degraded states alias empty+CTA or parent modifiers; UMAP scatter is a status region, not a 2D plot.
- Retention audit timeline still exists on Data Retention (policy home); only nav/copy framing changed.
- No browser walk; no full `npx vitest run` of the whole `js/admin` tree after D-23.
- Cluster drawer empty-state test uses a partial roster row (`as never`).

## Canon cited

- **NAV-05** — six submenus mutually exclusive; naming and description-history each have one home.
- **NAV-06** — Review Queue sits above Settings as the high-frequency work item; Settings last.
- **NAV-01** — brief maps “one primary per screen”; chrome now has a single primary + secondary remainder (depth still one submenu).
- **INT-02** — library/scan status filters remain `<select>` value changes; verbs stay on buttons.
- **designed-unknown** — form/queue/forced_choice/ai_review zones declare and render loading/empty/error instead of a silent subset of the parent screen.
- **TEST-15** — each item had a production mutant that turned the guarding test red; scatter assert was switched from self-referential copy to a literal so the mutant could kill.
