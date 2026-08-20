# UXW2-3 board audit — shard 1 of 3

Read-only re-check of 17 board rows against this checkout HEAD. Pre-r4 subjects do not survive as standalone commits here (folded into the feature/uxw2-3 sync transplant). R4-02 is the only finding in this shard with a greppable subject.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

### UXW2-3-R1-01 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:484`
- **Evidence:**
  - `role="listbox"` (`NameFaceControl.tsx:484`)
  - `role="option"` + `aria-selected={selected}` (`:512`–`:513`)
  - `aria-controls={overlayOpen ? listboxId : undefined}` / `aria-activedescendant={activeOptionId}` (`:465`–`:466`)
  - `aria-expanded={overlayOpen}` where `overlayOpen = listOpen && displayedOptions.length > 0 && !isPending && !isLoading` (`:254`, `:463`)
  - `handleKeyDown` has `ArrowDown` / `ArrowUp` / `Home` / `End` (`:358`, `:371`, `:381`, `:389`)
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** The popup is a real listbox; arrows move `activeIndex`; expanded state matches overlay mount. Not OPEN — the old “div of buttons, Enter/Escape only” control is gone.

### UXW2-3-R1-05 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/reservedLabel.ts:12`
- **Evidence:** every listed user-facing string is rewritten:
  - badge `return __('Group', 'alt-context');` (`NameFaceControl.tsx:47`)
  - `ariaLabel={__('Person name', 'alt-context')}` (`ClusterEditForm.tsx:155`)
  - `__('This label format is reserved for automatic group IDs. Choose a descriptive name.', 'alt-context')` (`reservedLabel.ts:12`)
  - `__('Merge into group "%s"', 'alt-context')` (`ClusterLabelingPanel.tsx:686`); merge-target copy is `group` (`:660`, `:666`)
  - `__('Unable to load unlabeled faces.', 'alt-context')` (`ReviewQueue.tsx:1242`)
  - `setError(__('Cannot save this name: missing person.', 'alt-context'))` (`useClusterSaveAction.ts:126`)
  - `__('Face group review', 'alt-context')` (`reviewCardGroupAccname.tsx:52`)
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** The claim named those surfaces/strings. Remaining `cluster` hits on those files are identifiers, comments, and translator notes — not operator copy. Roster/ops pages were out of the claim.

### UXW2-3-R1-08 — PARTIAL

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx:978`
- **Evidence:**
  - Panel now has Enter / confirm / prefill cases: R1-08a `:978`, R1-08b `:987`, R1-08c `:1009` (asserts `updateClusterLabel(..., 'Alex Carter', ...)` at `:1051`, not `rosterEntryId`)
  - `resolveCommit` reads `resolution.kind` only to skip the person-only guard, then still `submitLabel(resolution.name)` (`ClusterLabelingPanel.tsx:378`, `:389`–`:393`)
  - PersonCommit Enter→`rosterEntryId` exists (`PersonCommitControl.test.tsx:87`); prefill case is still a novel name (`:159` `prefills a suggested create name and Enter commits it`)
  - `PersonCommitControl.test.tsx` has no `Confirm match` / `getByRole('option')` click. Shared click path is covered on `NameFaceControl`, not the queue-card wrapper
- **Fixed by:** n/a (partial)
- **Reasoning:** (a) is mostly closed — prefill+roster Enter would go red if `kind` were ignored, because `skipPersonOnlyGuard` would not fire and the person collision would arm the guard. (b) is still open at the PersonCommit wrapper: no overlay click, no `suggestedCreateName` + roster-id prefill. Not FIXED — the proposed PersonCommit assertions were never added.

### UXW2-3-R1-12 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx:351`
- **Evidence:**
  - Duplicate check lives in `submitLabel` (`if (!allowRenameAnyway && !options?.skipDuplicateGuard)` then `setDuplicateGuard(localGuard)` at `:351`, `:355`)
  - Both Enter (`resolveCommit` → `submitLabel`) and confirm-a-group-row (`handleSelectOption` cluster branch) arm the same guard
  - `type + Enter on an existing group name primes the same merge guard (UXW2-3-R1-12)` (`ClusterLabelingPanel.test.tsx:997`)
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** Gesture no longer decides whether the warning appears. Clearing the guard on keystroke (`handleTypedValueChange`) is correct FORM-04, not the old bug.

### UXW2-3-R1-16 — PARTIAL

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:489`
- **Evidence:**
  - (a) FIXED — no `<form>` in `ClusterLabelingPanel.tsx`; `container.querySelector('form')` is null (`ClusterLabelingPanel.test.tsx:1089`–`:1091`)
  - (b) OPEN — default header still `__('Suggested', 'alt-context')` (`NameFaceControl.tsx:489`). Configurable, not derived from `NAMING_GROUP_SUGGESTED`. PersonCommit passes `People` (`PersonCommitControl.tsx:198`); Library does not pass a header
  - (c) FIXED — `.acx-name-face { @include acx-name-face-surface; }` (`_name-face.scss:131`); `classPrefix` default `'acx-name-face'` (`NameFaceControl.tsx:224`) now has CSS
  - (d) FIXED — `visibleLabel && inputId` renders `<label htmlFor={inputId}>` (`NameFaceControl.tsx:452`–`:453`); both live adapters pass both
  - (e) FIXED — `personUuid ? toRosterPerson(personUuid) : toRoster()` (`personCommitCopy.ts:19`–`:20`)
  - (f) FIXED — `isLoading={rosterLoading}` and `searchPlaceholder` (`ClusterLabelingPanel.tsx:625`, `:633`)
  - (g) FIXED — read-only card no longer takes `onLabel`; `isReadOnly` on `TopClusterCard` (`ReviewQueue.tsx:1912`–`:1914`); `onLabel` is now `onCurateGroup` (`:1688`)
  - (h) OPEN — headline case still `renderPanel()` with no `makeClusterMembersResponse` stub (`ClusterReviewPanel.test.tsx:258`–`:259`). Heading itself is static (`ClusterReviewPanel.tsx:116`) so the tree no longer depends on that stub to paint
  - (i) OPEN — Library default is still `__('Save', 'alt-context')` (`ClusterEditForm.tsx:80`); queue + panel use `Save name`
  - (j) FIXED — E21-5 now documents write-through (`docs/tasks/21.0/E21-5-unified-review-queue-task-plan.md:68`, `:93`)
  - (k) FIXED — UXW2-3 slice boxes are `[x]` (`docs/tasks/uxw2/UXW2-3-one-naming-surface-task-plan.md:32`)
- **Fixed by:** n/a (partial)
- **Reasoning:** Seven of eleven items are gone. (b)/(h)/(i) still match the original claim.

### UXW2-3-R2-03 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:235`
- **Evidence:**
  - `const [listOpen, setListOpen] = useState(true);` (`:235`); first Escape `setListOpen(false)` only (`:421`–`:424`)
  - `aria-labelledby={`${listboxId}-label`}` (`:486`); `aria-controls` gated on `overlayOpen` (`:465`)
  - reject is a sibling of `role="option"`, `tabIndex={-1}` (`:563`–`:566`); `:focus-visible` reveal (`_name-face.scss:94`); Delete rejects the active row
  - APG test renders `suggestion_id` + `onRejectSuggestion` and asserts `not.toContainElement(reject)` (`NameFaceControl.test.tsx:340`, `:353`–`:354`)
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** Overlay now collapses; listbox is labelled; reject is not nested. `tabIndex={-1}` is the APG “focus stays on the input” pattern (Delete), not the old invisible-and-unreachable button.

### UXW2-3-R2-07 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:316`
- **Evidence:**
  - Person-row ✓ goes through `confirmDisplayedOption` → `onCommit({ kind: 'roster', ... })` (`NameFaceControl.tsx:314`–`:316`), same bind path as Enter
  - `confirm on a person row writes a bind (UXW2-3-R2-07)` (`ClusterLabelingPanel.test.tsx:1057`); prefill test at R1-08c
  - compiled mixin selectors asserted (`name-face-surface.test.ts:21`)
  - `onLabel` / `open_label` are live curate wiring (`ReviewQueue.tsx:1688`, `ScanTabContent.tsx:227`), not a dead prop on a read-only card
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** The gesture split is gone. The later r3a restore of `open_label` is reachability, not the dead-wire defect.

### UXW2-3-R3-02 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:334`
- **Evidence:**
  - `handleSaveClick` confirms `displayedOptions[activeIndex]` when the overlay is open, else `chosenOptionValue`, else `commitValue(value)` (`:334`–`:346`)
  - Save `onClick={handleSaveClick}` (`:593`)
  - `type Gra, ArrowDown, then Save name binds Grace — Save and Enter agree (UXW2-3-R3-02)` (`NameFaceControl.test.tsx:194`)
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** Save no longer re-resolves the raw fragment while a row is highlighted.

### UXW2-3-R3-05 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx:354`
- **Evidence:**
  - APG case now feeds `suggestion_id: 's-ada'` + `onRejectSuggestion` (`NameFaceControl.test.tsx:340`)
  - `expect(option).not.toContainElement(reject)` (`:354`)
  - Production: option `div` at `:510`; reject `<button>` is a following sibling (`:564`)
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** Nesting the reject inside `role="option"` would fail `not.toContainElement`. The old `querySelector('button')` null-always assertion is gone.

### UXW2-3-R3-08 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useOpenReviewTargetLifecycle.ts:99`
- **Evidence:**
  - Two literal `__()` calls selected by the branch (`:97`–`:100`): `__('This group was merged — switched to the surviving group.', ...)` / `__('This review target is no longer available.', ...)`
  - Guard still has `GETTEXT_NON_LITERAL` (`gettext-literals.test.ts:12`) **and** `LITERAL_FIRST_ARG` + `extractFirstArg` (`:15`, `:128`–`:132`) so a ternary first arg fails
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** The exact offender (ternary inside `__()`) is gone; the guard now enforces “quoted literal” rather than “doesn’t start with SCREAMING_CASE”.

### UXW2-3-R3-11 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:335`
- **Evidence:** same as R3-02: `if (overlayOpen && activeIndex >= 0 && displayedOptions[activeIndex]) { confirmDisplayedOption(...) }` (`:335`–`:336`); chosen-option fallback `:339`; test `:194`
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** Duplicate of R3-02. Same code, same kill. Not OPEN.

### UXW2-3-R3-14 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:422`
- **Evidence:**
  - `if (overlayOpen) { e.preventDefault(); setListOpen(false); return; }` then `onCancel?.();` (`:422`–`:427`)
  - `aria-controls={overlayOpen ? listboxId : undefined}` (`:465`)
  - `first Escape closes the overlay, second Escape cancels the edit` asserts `not.toHaveAttribute('aria-controls')` (`NameFaceControl.test.tsx:385`, `:398`)
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** Library `onCancel` no longer fires on the first Escape. `aria-controls` is omitted when the listbox is unmounted.

### UXW2-3-R3-17 — PARTIAL

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx:841`
- **Evidence:**
  - `queue-empty` now stubs empty suggestion/top-unlabeled payloads (`:751`) and waits for empty copy (`:980`)
  - `queue-pending` shares the ReviewQueue node (`:841`) but default fetches hang (`:491` `new Promise(() => undefined)`) and the case asserts `/loading/i` (`:986`–`:987`)
  - `merge-dialog-open` is gone; fixture is honestly `merge-undo-banner` (`:854`) and mounts `MergeUndoBanner`, never the duplicate-guard dialog
- **Fixed by:** n/a (partial)
- **Reasoning:** The three misnamed/empty fixtures now enter the states they are named for (or were renamed). Merge-guard dialog copy (`Merge into group…`) still cannot turn this sweep red.

### UXW2-3-R3-20 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx:698`
- **Evidence:**
  - Rename anyway: `void submitLabel(duplicateGuard.label, { skipDuplicateGuard: true });` (`:695`–`:698`)
  - `submitLabel` checks and sets `submittingRef` (`:338`, `:341`)
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** No more raw `labelMutation.mutateAsync` beside the ref. A second click hits `submittingRef.current` and returns.

### UXW2-3-R3-23 — PARTIAL

- **Anchor now:** `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json:706`
- **Evidence:**
  - Cited `open_questions` strings are rewritten: “Selecting a face group in the map/list…” (`:706`); vocab item is `RESOLVED` (`:705`)
  - JSON↔render zone/state/action guard exists (`uxmap-parity.test.ts:39`–`:40`)
  - No wording ban on the map JSON. `not_doing` still: `"Clusters tab inside Roster (retired; cluster structure lives in Workbench left pane now)"` (`:714`)
- **Fixed by:** n/a (partial)
- **Reasoning:** The three `open_questions` phrases are gone and JSON==render is asserted. The “ban the wording” half of the proposed guard was never added.

### UXW2-3-R3-26 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/PersonCommitControl.tsx:194`
- **Evidence:**
  - Queue: `visibleLabel={__('Name this person', 'alt-context')}` + `inputId={...}` (`PersonCommitControl.tsx:194`–`:195`)
  - Library: `visibleLabel={__('Person name', 'alt-context')}` (`ClusterEditForm.tsx:156`)
  - Shared control: `<label htmlFor={inputId} className={`${classPrefix}__visible-label`}>` (`NameFaceControl.tsx:453`)
  - `the name input has a visible associated label (UXW2-3-R3-26)` (`PersonCommitControl.test.tsx:137`)
- **Fixed by:** not a standalone subject on this checkout
- **Reasoning:** Both live naming inputs have a visible `<label for>`. `ariaLabel` is still also passed (redundant, not the defect).

### UXW2-3-R4-02 — FIXED

- **Anchor now:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/queryRetry.tsx:13`
- **Evidence:**
  - `QUERY_RETRY_COPY` values are `__('…literal…')` at definition (`queryRetry.tsx:12`–`:14`); JSX uses the already-translated constant (`:61` `{QUERY_RETRY_COPY.RETRY}`)
  - ReviewQueue / findings consume those constants, they do not wrap them in `__()` (`ReviewQueue.tsx:886`; `WorkbenchFindingsPanel.tsx:138`, `:319`–`:320`)
  - `holdMessage` is assigned from two literal `__()` arms (`ReviewQueue.tsx:1536`–`:1539`) and rendered as `{holdMessage}` (`:1556`)
  - `grep` of `identity-clusters/*.{ts,tsx}` for `__(\s*[A-Za-z_]` : no hits
  - Guard test still `expect(offenders).toEqual([])` (`gettext-literals.test.ts:117`); regex / `collectTsFiles` not narrowed
- **Fixed by:** `fix(fe): UXW2-3-R4-02 pass string literals into __() at eight sites`
- **Reasoning:** The eight `__(CONST)` call sites are gone. The guard that was RED on those eight would now see only quoted first args. Not OPEN — this is the one subject that still greps out of `git log`.

## Tally
FIXED: 13 | OPEN: 0 | PARTIAL: 4 | INVALID: 0 | MOVED: 0

## Undone

Shard audit is complete; these board rows stay open in part:

- **R1-08** — PersonCommit still has no Confirm-match click and no `suggestedCreateName` + roster-id prefill. Panel `onCommit` still writes the name, not `rosterEntryId`.
- **R1-16 b/h/i** — overlay header still defaults to “Suggested”; headline test still unstubs `fetchClusterMembers`; Library default button is still “Save”.
- **R3-17** — duplicate-guard dialog is still not a sweep fixture.
- **R3-23** — no banned-word assertion on the uxmap JSON; `not_doing` still says “Clusters tab”.

## New observations

- `ClusterLabelingPanel` translator comments still say “cluster label” (`:659`, `:665`, `:685`). Not operator-visible; a gettext extractor will show that context to translators.
- `NameFaceControl` `__visible-label` has no CSS rule. Labels render, unstyled. Not a functional hole.
- `inputId="cluster-label-input"` is still a DOM id on the panel (`ClusterLabelingPanel.tsx:634`). Not user-facing.
