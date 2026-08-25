# Lane C report — D-2 + D-22 + D-23

## Result

MECE six-item ACX IA (glossary names kept). Review Queue is the naming home for unnamed faces. People is named-people only. Description Runs is describer history. Data Retention is policy/export/purge (audit timeline removed). One primary action per interactive ux-map screen. D-23 zone failure states are not complete: six unique zone ids still declare a strict subset versus render (listed in Fix round).

Final HEAD: recorded by the integrator after transplant.

## Commits (subject lines only)

- `docs(ux-maps): D-2 proposed IA`
- `fix(admin): D-2 MECE submenu homes`
- `fix(admin): D-22 one primary per screen`
- `fix(admin): D-23 zone failure states`
- `fix(admin-ia): W3-C-01 scatter-status-region`
- `fix(admin-ia): W3-C-03 unassigned-persons-home`
- `fix(admin-ia): W3-C-02 dual-home-audit`
- `fix(admin-ia): W3-C-04 one-primary-chrome`
- `fix(admin-ia): W3-C-05 assign-actions-status`
- `fix(admin-ia): W3-C-09 failure-header`
- `fix(admin-ia): W3-C-07 media-filter-copy`
- `fix(admin-ia): W3-C-06 literal-copy-pins`
- `fix(admin-ia): W3-C-10 empty-state-a11y`
- `fix(admin-ia): W3-C-08 uxmap-integrity`
- `fix(admin-ia): W3-C-11 fixture-hygiene`
- `fix(admin-ia): W3-C-12 one-primary-composed`
- `fix(admin-ia): W3-C-13 uxmap-url-params`

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

`SUBMENU_IA` pins unique goals (`apps/prototype-wp-alt-context/src/admin/class-menu.php:15`). Unassigned-person guidance targets People `personFilter=unassigned` (`GuidanceCard.tsx:52`). Review Queue cannot show zero-face-group persons.

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
- `GuidanceCard.tsx:52` — `href={toRoster({ personFilter: 'unassigned' })}`
- `DashboardPage.tsx:242` — Fix missing descriptions `--secondary`
- `WorkbenchPage.tsx:207` — `<FaceGroupScatter` wired from `status`/`scanRun`
- `FaceGroupScatter.tsx:23` — `Unable to load face-group status.`
- `FaceGroupScatter.tsx:73` — aria-label `Face-group status`
- `PersonWorkspacePanel.tsx:219` — count suppressed when `projection_status === 'failed'`
- `PersonWorkspacePanel.tsx:241` — `Refreshing linked faces…`
- `ClusterDrawerPanel.tsx:570` — `Loading people to assign…`
- `MediaSelection.tsx:338` — `Loading media…`
- `MediaSelection.tsx:342` — `Unable to load media.`
- `MediaSelection.tsx:291` — status `<Select.Root>` still value-only (INT-02)
- `PersonCommitControl.tsx:212` — name-commit `button-secondary`
- `MediaAltSuggest.tsx:826` — Accept `button-secondary`
- `RetentionPage.tsx:250` — `See description run history`
- `IdentityClusterList.tsx:103` — genuine empty `EmptyState` heading

## Verification

- `composer test:unit -- --filter MenuTest` — OK (5 tests, 51 assertions)
- `npx vitest run js/admin` — 227 files, 2649 tests passed
- Targeted RED/GREEN/mutant runs per W3-C item (see Fix round)

## Fix round

Adversarial FAIL on HEAD: several D-2/D-22/D-23 items were claimed closed but not. TDD order. Prior report claimed a Retention copy change with no diff; that sentence is deleted. Unassigned guidance no longer points at Review Queue. UMAP scatter claim replaced with status-region copy.

### TDD RED (verbatim)

W3-C-01: `Unable to find an accessible element with the role "region" and name "Face-group status"` (zone still `aria-label="Face group scatter"`).

W3-C-02: `expected document not to contain element, found <span class="acx-retention__detail"> Showing the five most recent audit events. </span>`

W3-C-03: `Expected the element to have attribute: href="#/roster?personFilter=unassigned"` / `Received: href="#/workbench?tab=scan"`

W3-C-04: `workbench-2pane workbench-2pane-shell primaries: : expected [] to have a length of 1 but got +0`

W3-C-05: empty-assign test already existed; loading/error tests went RED until `rosterStatus` branched (`Unable to find ... Loading people to assign…` after mutant).

W3-C-07: `Expected element to have text content: Unable to load media.` / `Received: Unable to load filters.` (mutant; initial toolbar tests injected booleans).

W3-C-08: `workbench-2pane workbench-control -> .../ControlPane.tsx: expected [ Array(1) ] to deeply equal []`

W3-C-09: `expected document not to contain element, found <p class="acx-roster__person-workspace-meta"> 4 face groups assigned </p>` (mutant; count on failure).

W3-C-06: `Unable to find an element with the text: Could not load every face in this group.` after copy mutant.

W3-C-10: `Unable to find an element with the text: Scan media to find faces in this item.` after body mutant.

### TEST-15 mutants (production mutated, suite RED, restored)

- W3-C-01: `{false && (<FaceGroupScatter .../>)}`. RED: `Unable to find an element by: [data-testid="acx-zone-z-cluster-umap"]`. Restore clean.
- W3-C-03: href back to `toWorkbench({ tab: 'scan' })`. RED: expected roster unassigned href. Restore clean.
- W3-C-02: extra `Full audit log` heading. RED: queryBy heading found. Restore clean.
- W3-C-04: Accept class `button-primary`. RED: `Expected the element to have class: button-secondary`. Restore clean.
- W3-C-05: loading copy `Loading people…`. RED: missing `Loading people to assign…`. Restore clean.
- W3-C-09: always print cluster_count. RED: `4 face groups assigned` present on failed. Restore clean.
- W3-C-07: error copy `Unable to load filters.`. RED: expected media wording. Restore clean.
- W3-C-06: expandError copy dropped "every". RED: missing literal. Restore clean.
- W3-C-10: empty body `Scan this item to find faces.`. RED: missing literal. Restore clean.
- W3-C-08: `code_ref` → ControlPane.tsx. RED: missing file. Restore clean.

### Closed this round

- W3-C-01: scatter state from `projectionSyncState` / `clusters_created` / online / `isSynced`; zone is status, not UMAP plot.
- W3-C-02: Retention audit timeline unmounted; link to Description Runs. Dropped `job-assign-faces` / `act-filter-unassigned` from roster-people map.
- W3-C-03: unassigned persons → `#/roster?personFilter=unassigned`.
- W3-C-04: exactly one primary per interactive screen; shell `act-scan-media-queue`; name-commit and Accept demoted; DOM counts.
- W3-C-05: assign-actions loading/error before empty; combobox still mounts when roster is empty so create works.
- W3-C-06: literal copy pins (scatter, expandError, dead-letter empty, conflict loading testid, identity empty body).
- W3-C-07: filter zone copy is media-query wording; tested via MediaSelection mocked `mediaQuery`.
- W3-C-08: live `code_ref`s, `?panes=`, dropped unrendered zone states, preview no longer draws a 2D cluster map.
- W3-C-09: suppress count on projection failure; distinct refreshing label.
- W3-C-10: genuine zero-detections uses `EmptyState` (not warning); scatter loading `role="status"` `aria-live="polite"`.
- W3-C-11: ClusterDrawerPanel assign tests use a full `RosterEntry` factory (no `as never`).

## Undone

- WP parent slug stays `alt-context-dashboard` (`class-admin.php` out of ownership); Review Queue cannot become the top-level click.
- Six unique D-23 zone ids still declare a strict subset versus render: `z-lightbox-media`, `z-lightbox-controls`, `z-settings-form`, `z-recent-activity`, `z-advanced`, `z-review-suggestions-group-card`. Closing them was optional; accounting is required.
- `AuditTimeline` component remains on disk; RetentionPage no longer mounts it.
- No browser walk.
- ClusterLabelingPanel still maps `rosterError ? [] : persons` (out of this round's assign-actions tests).
- Review-card accent still uses `acx-accent-primary-action` on name-commit; chrome class is secondary.

## Canon cited

- **NAV-05** — unassigned persons live on People (`personFilter=unassigned`); describer history lives on Description Runs; Retention no longer duplicates an audit home.
- **NAV-06** — Review Queue remains the high-frequency unnamed-face work item; Settings last.
- **NAV-01** — each interactive ux-map screen has exactly one primary action; `primary_action_id` matches that action.
- **INT-02** — library/scan status filters remain `<select>` value changes; verbs stay on buttons.
- **designed-unknown** — scatter/assign/filters now branch loading/empty/error instead of a silent subset; six leftover D-23 zones still declare a strict subset (listed in Undone).
- **TEST-15** — each W3-C item had a production mutant that turned the guarding test red; copy asserts are literals.
- **A11Y-21** — scatter loading uses `role="status"` / `aria-live="polite"` so AT hears the transition.

## Micro fix round

Closed W3-C-12 (composed workbench-control one WP primary) and W3-C-13 (workbench-2pane.md `pane`/`empty` drift).

Final HEAD: recorded by the integrator after transplant.

### Commits (subject lines only)

- `fix(admin-ia): W3-C-12 one-primary-composed`
- `fix(admin-ia): W3-C-13 uxmap-url-params`

### TDD RED (verbatim)

W3-C-12: `expected [ <button …(5)></button>, …(2) ] to have a length of 1 but got 3`

W3-C-13 url_params: `workbench-2pane workbench-2pane-shell missing "url_params: \`panes\`, \`cluster\`, \`media\`, \`panel\`, \`status\`, \`endpoint\`, \`s\`, \`p\`, \`perPage\`" from workbench-2pane.md: expected false to be true`

W3-C-13 ASCII: `expected 'z-name-curate states=[default,loading,error,edge_input]'` / received `z-name-curate states=[default,loading,empty,error, …]`

### TEST-15 mutants (production mutated, suite RED, restored)

- W3-C-12: LightboxNameFace `commitButtonClassName` re-promoted to `button-primary`. RED: `expected [ <button …(5)></button>, …(1) ] to have a length of 1 but got 2`. Restore clean (`git diff` on production files showed only the intended demotions).
- W3-C-13: shell md `url_params` `panes` → `pane`. RED: missing json `url_params: \`panes\`, …` line. Restore clean.

### Code (sed-verified after last code commit)

- `ClusterLabelingPanel.tsx:586` — lastMerge Done `button-secondary`
- `LightboxNameFace.tsx:131` — Save name `button-secondary`
- `PersonCommitControl.tsx:211` — name-commit `button-secondary` only (no `acx-accent-primary-action`)
- `workbench-2pane.md:57` / `:131` — `url_params` `panes`
- `workbench-2pane.md:104` / `:143` — ASCII `#/workbench?panes=`
- `workbench-2pane.md:113` — `z-name-curate states=[default,loading,error,edge_input]`

### Closed this round

- W3-C-12: composed workbench-control DOM counts exactly one `.button-primary` (suggestion Yes remains); Done, lightbox Save name, and review-card name-commit are secondary chrome.
- W3-C-13: md url_params + ASCII match json `panes`; z-name-curate ASCII dropped retired `empty`. `uxmap-render-parity` lints md url_params vs json.

### Verification

- `npx vitest run js/admin` — 228 files, 2652 tests passed

### Undone

- `ClusterLabelingPanel.tsx:781` Merge-into-group is still `button-primary` (duplicate-guard, not lastMerge Done).
- Other workbench-control widgets still use `button-primary` (suggestion Yes, bulk-commit, TopClusterCard confirm, ClusterReviewPanel confirm-removal, IdentityClusterItem wrong-person confirm, CloseMatchAcceptOffer). Composed count test keeps suggestion Yes as the remaining primary.
- Six unique D-23 zone ids still declare a strict subset versus render (listed in prior Undone).
- No browser walk.

### Canon cited

- **NAV-01** — composed workbench-control chrome has one WP `.button-primary`; residual naming CTAs are secondary.
- **COL-03** — review-card name-commit dropped `acx-accent-primary-action` so secondary chrome is not a second accent.
- **TEST-15** — C-12 re-promote lightbox primary → count 2; C-13 `pane` mutant → url_params lint RED; both restored.
