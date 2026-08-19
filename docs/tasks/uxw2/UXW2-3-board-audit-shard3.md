# UXW2-3 board audit — shard 3

Read-only re-check of this shard against current HEAD. r1–r3 originating subjects are not standalone commits on this transplant (they landed inside the feature/uxw2-3 mirror-sync). R4-01 is.

### UXW2-3-R1-04 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx:338`
- **Evidence:**
  - `if (submittingRef.current || labelMutation.isPending || mergeMutation.isPending) {` (`ClusterLabelingPanel.tsx:338`)
  - `submittingRef.current = true;` (`ClusterLabelingPanel.tsx:341`)
  - Enter: `if (isPending || isLoading) { return; }` (`NameFaceControl.tsx:411-412`)
  - `it('two rapid Enter presses fire the mutation once (UXW2-3-R1-04 / R2-02)'` (`ClusterLabelingPanel.test.tsx:1265`)
  - `it('ignores Enter while isPending'` (`NameFaceControl.test.tsx:418`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Parallel PATCH is gone: sync `submittingRef` plus `isPending` refuse re-entry; Save is disabled while pending. Leftover: `inputDisabled={mergeMutation.isPending}` (`ClusterLabelingPanel.tsx:626`) and `keeps input editable while save is pending` (`ClusterLabelingPanel.test.tsx:529`) still leave the combobox enabled during label save — not last-write-wins.

### UXW2-3-R1-07 — PARTIAL

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/PersonCommitControl.tsx:87`
- **Evidence:**
  - Done — NFC fold: `raw.normalize('NFC').replace(/\s+/g, ' ').trim().toLocaleLowerCase();` (`NameFaceControl.tsx:31`)
  - Done — resolve against full `options`, not overlay budget: `const resolution = resolveNameFaceInput(options, raw);` (`NameFaceControl.tsx:305`); `if (matches.length > 1) { return { kind: 'ambiguous', name, matches }; }` (`NameFaceControl.tsx:105-106`)
  - Done — display filter is `includes`, not `startsWith`: `normalizeNameFaceLabel(option.label).includes(folded)` (`NameFaceControl.tsx:149`)
  - Done — Enter binds the active overlay row: `if (overlayOpen && activeIndex >= 0 && displayedOptions[activeIndex]) { confirmDisplayedOption(displayedOptions[activeIndex]);` (`NameFaceControl.tsx:414-415`)
  - Not done — PersonCommitControl still maps roster entries only: `(rosterQuery.data ?? []).map((entry) => ({` (`PersonCommitControl.tsx:87`). Label panel still uses `buildNamingOptions({ rosterEntries, labelMatches, … })` (`ClusterLabelingPanel.tsx:214-216`)
  - Not done — primary is always `commitLabel={__('Save name', 'alt-context')}` (`PersonCommitControl.tsx:189`). No `Create person` / `Save as` strings in the tree
- **Fixed by:** n/a (partial)
- **Reasoning:** Create-vs-bind no longer resolves against a prefix-sliced first-match. The three-surface `buildNamingOptions(+similarity)` unification and Create-vs-Save preview were never done.

### UXW2-3-R1-10 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/reservedLabel.ts:11`
- **Evidence:**
  - `export const getReservedLabelMessage = (): string =>` / `__('This label format is reserved for automatic group IDs. Choose a descriptive name.', 'alt-context');` (`reservedLabel.ts:11-12`)
  - Call sites: `setError(getReservedLabelMessage());` (`useClusterSaveAction.ts:115`, `:156`, `:228`; `ClusterLabelingPanel.tsx:347`) and `setReservedError(getReservedLabelMessage());` (`PersonCommitControl.tsx:127`)
  - Guard: `expect(reserved).toMatch(/__\(\s*'This label format is reserved/);` (`gettext-literals.test.ts:114`) plus `does not pass CONST identifiers into __() across identity-clusters` (`gettext-literals.test.ts:117`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Literal sits inside `__()` at the definition site. The five named call sites no longer pass a variable into `__()`.

### UXW2-3-R1-14 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:295`
- **Evidence:**
  - Count is `matchTotal = matchingOptions.length` (`NameFaceControl.tsx:253`), not `OVERLAY_OPTIONS_LIMIT`
  - Debounce: `LIVE_ANNOUNCE_DEBOUNCE_MS = 400` (`NameFaceControl.tsx:28`); `window.setTimeout(() => { setAnnouncedTotal(matchTotal); }, LIVE_ANNOUNCE_DEBOUNCE_MS)` (`NameFaceControl.tsx:266-268`)
  - `_n('%d naming option', '%d naming options', announcedTotal, 'alt-context')` (`NameFaceControl.tsx:295`)
  - Loading: `return __('Loading people…', 'alt-context');` (`NameFaceControl.tsx:282`)
  - Tests: `expect(screen.getByRole('status')).toHaveTextContent('8 naming options');` (`NameFaceControl.test.tsx:306`); `'1 naming option'` (`NameFaceControl.test.tsx:314`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Announcement is the true filtered total, pluralised, debounced, and not a zero-count while loading. Overlay cap is display-only.

### UXW2-3-R2-02 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx:341`
- **Evidence:**
  - `submittingRef.current = true;` is set before `const remoteGuard = await evaluateRemoteDuplicateGuard(trimmed);` (`ClusterLabelingPanel.tsx:341` then `:358`); cleared in `finally` (`:373-375`)
  - Test delays `listRecognitionClusters` 50ms then `{Enter}{Enter}` (`ClusterLabelingPanel.test.tsx:1265-1270`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** The remote-await window is covered by a sync latch, not only React Query `isPending`. Same test as R1-04.

### UXW2-3-R2-06 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx:77`
- **Evidence:**
  - Singular identity: `/\bidentity\b/i,` (`banned-vocabulary.test.tsx:77`)
  - ReviewQueue + empty/pending + MergeUndoBanner + ClusterActions + IdentityClusterItem fixtures (`banned-vocabulary.test.tsx:731-735`)
  - Mutant pin: `expect(source).not.toMatch(/Unable to load unlabeled clusters\./);` (`banned-vocabulary.test.tsx:999`)
  - MergeUndoBanner: `__('existing group', 'alt-context')` (`MergeUndoBanner.tsx:23`)
  - `clusterMutationUtils.ts:26`: `__('That group is already named %s - nothing to merge.', 'alt-context')`
  - `useClusterSaveAction` rewrite pin: `fails if useClusterSaveAction reverts the missing-person string` (`gettext-literals.test.ts:145`)
  - Gettext guard walks every `__()` first arg via `extractFirstArg` (`gettext-literals.test.ts:128-141`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Named holes (ReviewQueue, singular `identity`, MergeUndoBanner, clusterMutationUtils, missing-person string, variable msgid) are closed. Duplicate-guard still not a fixture — see Undone; its current copy has no banned words.

### UXW2-3-R3-01 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx:227`
- **Evidence:**
  - `onLabel={(clusterId: string) => dispatchClusterPanel({ type: 'open_label', clusterId })}` (`ScanTabContent.tsx:227`)
  - Mount gate: `{clusterPanel.mode === 'label' && clusterPanel.clusterId ? (` / `<ClusterLabelingPanel` (`ScanTabContent.tsx:199-200`)
  - Producer: `case 'open_label':` / `return { mode: 'label', clusterId: action.clusterId };` (`ClusterPanelContext.tsx:17-18`)
  - Queue wires curate → that dispatcher: `onCurateGroup={onLabel}` (`ReviewQueue.tsx:1688`); button `{__('Merge or split this group', 'alt-context')}` (`PersonCommitControl.tsx:240`)
  - Absence-grep lock replaced: `expect(scan).toMatch(/type:\s*'open_label'/);` (`ScanTabContent.labelPanelReachable.test.tsx:127`); comment at `ClusterLabelingPanel.test.tsx:1124`
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** `open_label` has a live producer again. Reachability test still stubs ReviewQueue and the panel (see Undone); production wiring is present.

### UXW2-3-R3-04 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:505`
- **Evidence:**
  - Row wrapper: `role="presentation"` (`NameFaceControl.tsx:505`)
  - Reject: `tabIndex={-1}` (`NameFaceControl.tsx:566`)
  - Hidden CSS: `opacity: var(--acx-opacity-hidden);` / `pointer-events: none;` (`_name-face.scss:86-87`)
  - Test: `it('listbox children are presentational rows and the reject is out of Tab order (UXW2-3-R3-04)'` (`NameFaceControl.test.tsx:370`); `toHaveAttribute('tabindex', '-1')` (`:382`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Claimed defects (non-option row wrappers, tabbable reject, invisible-but-tappable reject) are gone. Header child of the listbox is still un-roled — see New observations.

### UXW2-3-R3-07 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx:731`
- **Evidence:**
  - `queue-empty` mocks resolved-empty suggestions (`banned-vocabulary.test.tsx:751-773`) and waits for `.acx-review-queue__empty` (`:980-984`)
  - Default recognition mocks never resolve (`banned-vocabulary.test.tsx:491-494`); `queue-pending` asserts `/loading/i` (`:986-987`)
  - ClusterActions / IdentityClusterItem fixtures (`:734-735`); copy `{__('Remove from group', 'alt-context')}` / `{__('Split group', 'alt-context')}` (`ClusterActions.tsx:74`, `:86`); `{__('Unnamed person', 'alt-context')}` (`IdentityClusterItem.tsx:76`); `{__('Remove this face from the group', 'alt-context')}` (`IdentityClusterItem.tsx:411`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Empty vs pending are distinct; the two previously-unswept components are mounted and rewritten. `merge-dialog-open` was renamed to `merge-undo-banner` rather than opening the labeling-panel duplicate-guard (see Undone).

### UXW2-3-R3-10 — FIXED

- **Anchor now:** `docs/tasks/uxw2/UXW2-3-fix-lane-report.md:35`
- **Evidence:**
  - Heading is `## Gate evidence (suite green, lint RED)` (`UXW2-3-fix-lane-report.md:35`), not `## GREEN evidence`
  - Gate paste: `Test Files  209 passed (209)` / `Tests  2403 passed (2403)` (`:40-41`)
  - Closure table: `| R1-16 | **partial**` (`:13`)
  - Old `1 failed | 2402 passed` lives under `## Superseded (round 2, before the last fix)` (`:50`)
  - Undone still records the two follow-up commits were not re-run as a full suite (`:76`) and that R1-16d/h are not claimed (`:79`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Headline no longer presents a red suite as green; table and Undone agree on R1-16. Same finding as R3-22.

### UXW2-3-R3-13 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx:227`
- **Evidence:** Same producer/mount as R3-01. `onCurateGroup={onLabel}` (`ReviewQueue.tsx:1688`). Behaviour test `curate control mounts the labeling panel Name combobox` (`ScanTabContent.labelPanelReachable.test.tsx:113`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Duplicate of R3-01. R1-08c harness coverage on the panel is reachable from Scan again.

### UXW2-3-R3-16 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx:354`
- **Evidence:**
  - APG case now passes `suggestion_id` + `onRejectSuggestion` and asserts `const reject = screen.getByRole('button', { name: 'Reject Ada Lovelace' });` (`NameFaceControl.test.tsx:351`) then `expect(option).not.toContainElement(reject);` (`:354`)
  - Reject is a sibling of `role="option"` (`NameFaceControl.tsx:512` vs `:564`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Re-nesting the button inside the option would fail `not.toContainElement`. The old `querySelector('button')` / no-reject-rendered case is gone. Old `:299` is now the R1-14 live-region describe.

### UXW2-3-R3-19 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useOpenReviewTargetLifecycle.ts:99`
- **Evidence:**
  - `status === 'rebound'`
  - `? __('This group was merged — switched to the surviving group.', 'alt-context')`
  - `: __('This review target is no longer available.', 'alt-context'),` (`useOpenReviewTargetLifecycle.ts:98-100`)
  - Guard extracts any non-literal first arg (`gettext-literals.test.ts:128-141`), not only `GETTEXT_NON_LITERAL`'s SCREAMING_CASE identifier (`:12`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Ternary is outside `__()`; both branches are string literals. The old `__(status === 'rebound' ? LIVE_TARGET_* : LIVE_TARGET_*, …)` form is gone.

### UXW2-3-R3-22 — FIXED

- **Anchor now:** `docs/tasks/uxw2/UXW2-3-fix-lane-report.md:35`
- **Evidence:** Same rewrite as R3-10. No `## GREEN evidence` heading remains. R1-16 is `**partial**` (`:13`). Red `1 failed | 2402 passed` is under `## Superseded` (`:50`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Duplicate of R3-10 from a second panel.

### UXW2-3-R3-25 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx:617`
- **Evidence:**
  - Roster-error branch is a ternary; `<label htmlFor="cluster-label-input">` sits in the non-error arm (`ClusterLabelingPanel.tsx:599` then `:617`)
  - `if (rosterError) { rosterRetryRef.current?.focus(); }` (`ClusterLabelingPanel.tsx:193-194`); Retry has `ref={rosterRetryRef}` (`:605`)
  - Test: `expect(document.querySelector('label[for="cluster-label-input"]')).toBeNull();` / `expect(screen.getByRole('button', { name: 'Retry' })).toHaveFocus();` (`ClusterLabelingPanel.test.tsx:1313-1314`)
- **Fixed by:** not a standalone commit subject on this transplant
- **Reasoning:** Orphan `for` is gone; focus moves to Retry. Tests cover both.

### UXW2-3-R4-01 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:992`
- **Evidence:**
  - Production: `{__('Remove from group', 'alt-context')}` / `{__('Split group', 'alt-context')}` (`ClusterActions.tsx:74`, `:86`)
  - Positives: `getByText('Remove from group', { selector: 'button' })` (`IdentityClusterList.test.tsx:992`); `getByRole('button', { name: /split group/i })` (`:1051`)
  - Negatives retargeted: `/Remove from group/i` / `/Split group/i` (`:388-389`); `/remove from group/i` (`:1024`)
- **Fixed by:** `fix(fe): UXW2-3-R4-01 retarget IdentityClusterList queries to group copy`
- **Reasoning:** Queries match the r3b copy. Old `'Remove from Cluster'` / `'Split cluster'` accessible-name waits are gone.

## Tally
FIXED: 15 | OPEN: 0 | PARTIAL: 1 | INVALID: 0 | MOVED: 0

## Undone

- **R1-07 remains PARTIAL.** PersonCommitControl is still a roster-only mapper (`PersonCommitControl.tsx:87`); ClusterLabelingPanel still uses `buildNamingOptions` with labelled groups (`ClusterLabelingPanel.tsx:214-216`). Primary button is always `Save name` (`PersonCommitControl.tsx:189`) — no Create-vs-Save preview.
- **R1-04 leftover (not last-write-wins).** `inputDisabled={mergeMutation.isPending}` (`ClusterLabelingPanel.tsx:626`) plus `keeps input editable while save is pending` (`ClusterLabelingPanel.test.tsx:529`) still leave the combobox enabled during label save. Enter/Save are guarded.
- **Banned-vocab still does not mount the labeling-panel duplicate-guard.** `merge-dialog-open` became `merge-undo-banner`. Current guard copy uses `group` (`ClusterLabelingPanel.tsx:647-686`) so this is a coverage gap, not a live banned string.
- **Labeling-panel reachability test is stubbed.** `ScanTabContent.labelPanelReachable.test.tsx` mocks `ClusterLabelingPanel` as a combobox stub and `ReviewQueue` as a button that calls `onLabel`. Production path `PersonCommitControl` → `ReviewQueue.onCurateGroup={onLabel}` → `ScanTabContent` `open_label` exists; the real panel is not mounted in that test.
- **r1–r3 originating commit subjects are not standalone git commits on this transplant.** Only R4-01's subject greps from `git log`. Do not treat the mirror-sync subject as a per-finding closer.

## New observations

- **Listbox header is still a non-option child.** `role="listbox"` (`NameFaceControl.tsx:484`) contains `<div className={…__suggestions-header} id={…}>` (`NameFaceControl.tsx:488`) with no `role="presentation"` / `group`. The R3-04 test skips that child by class. Assistive tech still sees a non-option inside the listbox.
- **Dead comments still say "Split cluster".** `ClusterActions.tsx:31` JSDoc; `IdentityClusterItem.tsx:266` line comment. Not rendered; the banned-vocab sweep will not catch them.
- **`GETTEXT_NON_LITERAL` is still SCREAMING_CASE-only** (`gettext-literals.test.ts:12`). The real kill path is `extractFirstArg` (`:128-141`). A future `__(lowercaseIdent, …)` is caught by the extractor, not the regex.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
