# UXW2-3 — one naming surface + single-gesture create-person + plain-language wording

## Commits

- `24f894a` feat(workbench): UXW2-3 NameFaceControl + single-gesture Save name
- `b26e682` refactor(workbench): UXW2-3 adopt NameFaceControl in label panel + Library pane
- `e2f6a0a` fix(workbench): UXW2-3 plain-language wording for review surfaces

## RED evidence

- Commit 1: `PersonCommitControl.test.tsx` rewritten first against the single-gesture contract
  (novel name + Enter → `newEntryName`; roster name + Enter → `rosterEntryId`; no "Just label"
  control; reserved-name gate). Run before implementation: 12/12 failing.
- Commit 2: label-panel tests converted to the inline control (type-and-Save / suggestion-row
  ✓ confirm) before `ClusterLabelingPanel` was rewired; duplicate-guard tests failed until
  `onOptionConfirm` was wired to `handleSelectOption`.
- Commit 3: heading/vocabulary assertions updated to the new strings before the component sweep;
  banned-vocabulary extension fails against any surface still rendering "cluster".

## GREEN evidence

- Full suite: **206 test files, 2347 tests, all passed** (`npm run test`, 315s).
- `npm run typecheck` (`tsc --noEmit`): clean.
- `npm run lint`: 117 errors, all pre-existing baseline (verified: `SuggestionCards.tsx:51` blames
  boundary commit `3747699`, predating the lane; every other error is in lane-untouched files).
  Lane-touched files lint-clean.
- Mutation proof (TEST-15, commit 1): reverting the roster-match branch in `NameFaceControl`
  re-failed the roster-name commit test; restored and re-green.

## Files changed

- New: `identity-clusters/NameFaceControl.tsx`, `identity-clusters/reservedLabel.ts`.
- Rewired: `PersonCommitControl.tsx` (two-phase combobox + explicit-create + Just-label removed;
  single-gesture inline input), `ClusterEditForm.tsx` (adapter over `NameFaceControl`, DOM contract
  preserved via `classPrefix`), `ClusterLabelingPanel.tsx` (Combobox → `NameFaceControl`;
  `inputDisabled`/`hideStatusAnnouncement` added for the merge-mutation nuance and panel-owned
  status region), `useClusterSaveAction.ts` (reserved-label check via single module),
  `personCommitCopy.ts` (Just-label/Create-new strings retired; "Save name" copy).
- Wording sweep: `ClusterReviewPanel.tsx`, `ScanTabContent.tsx`, `SuggestionCards.tsx`,
  `TopClusterCard.tsx`, `MergeSuggestionCard.tsx`, `ReviewQueue.tsx`.
- Docs: `docs/ux-maps/workbench-2pane.md` — "Vocabulary" say/don't-say section (published before
  the sweep, per brief).
- Tests: `PersonCommitControl.test.tsx` (rewritten), `ReviewQueue.test.tsx`,
  `ClusterLabelingPanel.test.tsx`, `ClusterReviewPanel.test.tsx` (heading assertion added),
  `TopClusterCard.test.tsx`, `MergeSuggestionCard.test.tsx`,
  `ScanTabContent.controlPaneOrder.test.tsx`, `banned-vocabulary.test.tsx` (scoped
  `BANNED_REVIEW_SURFACE_WORDS` sweep rendering `ClusterReviewPanel`).

## Canon IDs satisfied (verified by grep; file:line)

- COG-02 — `lexicons/interaction-ux.md:112` — recognition over recall: typeahead overlay over the
  roster replaces recall-and-type-only naming.
- INT-05 — `lexicons/interaction-ux.md:162` — prominent Done: one verb-labeled "Save name" button
  at the end of the flow; the ambiguous tertiary "Just label" path is removed.
- INT-06 — `lexicons/interaction-ux.md:163` — smart action labels: "Save name", "Remove this face",
  "Skip these faces for now" name the exact object and operation.
- FORM-04 — `lexicons/interaction-ux.md:188` — smart prefills: suggested create-name prefills the
  input when the projection offers one (test: "prefills suggested create name").
- PRINCIPLES §6 — `PRINCIPLES.md:59` — unchosen default is a defect: create-vs-bind is resolved
  by the typed string (exact roster match binds, novel name creates); no separate "create" choice.
- REF-10 — `lexicons/engineering.md:329` — real, not coincidental, duplication merged: the three
  naming surfaces change together (same options pipeline, same reserved-label rule).
- REF-26 — `lexicons/engineering.md:345` — one fact, one place: reserved-label rule consolidated
  from 4 sites into `reservedLabel.ts`; vocabulary consolidated into the ux-map table.
- NAV-12 — `lexicons/interaction-ux.md:139` — matches the transferred convention of inline
  type-to-filter name pickers (peer products); no novel chrome.
- PERC-02 — `lexicons/interaction-ux.md:92` — similarity encodes semantics: one control with one
  look across the three surfaces promises one behaviour; suggestion rows keep their source badges
  as the distinctive feature.
- NAV-13 — `lexicons/interaction-ux.md:140` — controlled vocabulary before label freeze:
  say/don't-say table published in `docs/ux-maps/workbench-2pane.md` and enforced by the
  banned-vocabulary sweep.
- NAV-14 — `lexicons/interaction-ux.md:141` — audience mental model: "faces"/"face group"/"person"
  replace the engineering taxonomy ("cluster", "identities", "instances").
- A11Y-04 — `lexicons/accessibility.md:72` — every control named for its action: combobox
  aria-label "Name this person", commit button "Save name", removal "Remove this face"; visible
  label text contained in accessible names.

## Decisions made

- `NameFaceControl` kept purely presentational with `onCommit(resolution)` +
  `onOptionConfirm(option)`; legacy wirings (`onSave`/`onPersonSelect`/duplicate guard) adapted at
  the call sites so save behaviour is provably unchanged.
- `classPrefix` prop lets `ClusterEditForm` keep its `acx-identity-cluster-*` DOM contract —
  existing Library-pane tests untouched except where behaviour genuinely changed.
- Banned-vocabulary `cluster` ban scoped to a new `BANNED_REVIEW_SURFACE_WORDS` list applied to the
  rendered review panel, not the page-level `BANNED_STRINGS` — Roster/ops surfaces still render
  "cluster" and are owned by other lanes (brief §Commit 3).
- `ReviewQueue`'s read-only `TopClusterCard` keeps passing `onLabel` through (`onLabel?.(cluster.id)`)
  to preserve the prop chain; the card never renders the action in read-only mode.

## Undone / out of scope

- Roster-page files (RosterPage/ClusterDrawerPanel/NeedsAssignmentSection/PersonWorkspacePanel/
  RosterEntriesTable) untouched — another lane owns them.
- Label-panel merge-confirmation, split-dialog, and review-group aria strings still say "cluster"
  — outside the brief's changed-surface list; the banned sweep is scoped accordingly.
- `ClusterEditForm.test.tsx` `95%`/band assertions left as-is (another lane replaces bands with
  server-supplied ones).
- Pre-existing lint baseline (117 errors) untouched per sr-001 — none introduced by this lane.

## Final HEAD

`e2f6a0adda93847bac31e933ac4343e228f2c1f0`
