# UXW2-3-R3a — interactive naming/commit path

Lane cwd. Commits by subject only. No 40-hex SHAs.

## Closure table

| Item | Findings | Commit subject | New/changed tests | TEST-15 mutant RED |
| --- | --- | --- | --- | --- |
| 1 | R3-01, R3-13 | `fix(fe): UXW2-3-R3-01 UXW2-3-R3-13 restore labeling panel reachability` | `offers a curate-group control that reports the cluster id`; `curate control on a name card reports the cluster id upward`; `curate control mounts the labeling panel Name combobox`; `ScanTabContent source dispatches open_label`; R2-07 absence grep replaced by comment | Mutant delete `onLabel={…open_label}`: `TestingLibraryElementError: Unable to find role="combobox" and name "Name"`. Mutant delete curate button: `Unable to find an accessible element with the role "button" and name "Merge or split this group"` |
| 2 | R3-02 | `fix(fe): UXW2-3-R3-02 Save and Enter share the same commit resolution` | `type Gra, ArrowDown, then Save name binds Grace — Save and Enter agree`; `Save is not an enabled no-op after a same-fold row click` (mockClear after row click — specified form was GREEN at HEAD because the row click already committed) | Mutant `onClick={() => commitValue(value)}`: `AssertionError: expected "vi.fn()" to be called with arguments: [ { kind: 'roster', …(2) } ]` Received `{ kind: 'create', name: 'Gra' }` |
| 3 | R3-12, R3-03 | `fix(fe): UXW2-3-R3-12 UXW2-3-R3-03 person rows bind via onCommit` | `clicking the second of two same-fold people binds that roster id`; `checkmark on the second same-fold person carries that id into the write`; harness `onOptionConfirm` opt-in | Mutant restore `onOptionConfirm` short-circuit above person branch: `AssertionError: expected "vi.fn()" to be called with arguments: [ 'ALEX CARTER' ]` Number of calls: 0 (not `Received 'Alex Carter'` — deleted person branch routes to `onSave`, not first-fold bind) |
| 4 | R3-06, R3-20, R3-21 | `fix(fe): UXW2-3-R3-06 UXW2-3-R3-20 UXW2-3-R3-21 latch Rename anyway` | `two rapid Rename anyway clicks fire the mutation once`; `a second checkmark during an in-flight write is ignored`; `a second option selection during an in-flight write is ignored` | See before/after pair below |
| 5 | R3-05, R3-16 | `fix(fe): UXW2-3-R3-05 UXW2-3-R3-16 APG reject nesting can fail` | APG `aria-controls` case now renders reject + `not.toContainElement` | See before/after pair below |
| 6 | R3-04 | `fix(fe): UXW2-3-R3-04 listbox rows are presentational` | `listbox children are presentational rows and the reject is out of Tab order` | Mutant delete `tabIndex={-1}`: `Expected the element to have attribute: tabindex="-1" Received: null` |
| 7 | R3-14 | `fix(fe): UXW2-3-R3-14 two-stage Escape and aria-controls` | `first Escape closes the overlay, second Escape cancels the edit`; APG Escape half moved to second keypress | Mutant restore unconditional `onCancel?.()`: `AssertionError: expected "vi.fn()" to not be called at all, but actually been called 1 times` |
| 8 | R3-25, R3-26 | `fix(fe): UXW2-3-R3-25 UXW2-3-R3-26 visible naming labels` | `the name input has a visible associated label`; roster-error case extended (`label[for]` null + Retry focused) | Mutant revert PersonCommitControl to `ariaLabel`-only: `TestingLibraryElementError: Unable to find an element with the text: Name this person` |
| 9 | R3-27 | (no code) | none | n/a — deferred wontfix, see below |

GREEN after each fix: the named tests passed. ClusterLabelingPanel after item 1: 43 passed (deleted grep lock; 44−1). After items 3–8: **47 passed (47)**.

Curate control is `button button-link acx-person-commit__curate` with **no SCSS** this round (lane B owns `js/admin/styles/**`).

ScanTabContent mount test uses a stub ReviewQueue that calls `onLabel` plus a stub panel that renders `role="combobox" name="Name"`, plus a positive source pin. End-to-end real ReviewQueue → real ClusterLabelingPanel mount is **unproven**.

## Before/after mutant pairs

### Item 4 — handleOptionConfirm / handleSelectOption guard removal

**Before (prover + this HEAD, unmutated):** remove both pending guards → **GREEN**, `47 passed` (prover: `44 passed`). Those paths do not write after the item-3 person-branch deletion; mutation count cannot go RED.

**After (this lane, same mutant on the new tests):** still **GREEN**, `47 passed`. Recorded honestly. The killing mutant for this item is Rename anyway.

**Rename anyway mutant (after the fix):** revert to `void labelMutation.mutateAsync(duplicateGuard.label)` → **RED** `AssertionError: expected "vi.fn()" to be called 1 times, but got 2 times`.

**Rename anyway before the fix:** same two-click test → **RED** `got 2 times` (observed before implementing `submitLabel`).

### Item 5 — nest reject `<button>` inside `role="option"`

**Before (prover + unmutated HEAD, old APG assertion):** move reject inside option → **GREEN** (`1 passed | 17 skipped`). Default options have no `suggestion_id`; even when rendered the button is a sibling so `querySelector('button')` is null.

**After (new assertion):** same mutant → **RED** `expect(element).not.toContainElement(element)`.

## Suite counts (verbatim)

```
npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx
 Test Files  2 passed (2)
      Tests  49 passed (49)
```

Baseline to beat: `44 passed (44)`. Beat it.

```
npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx
 Test Files  1 passed (1)
      Tests  47 passed (47)
```

Baseline to beat: `44 passed (44)`. Beat it.

```
npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/PersonCommitControl.test.tsx
      Tests  17 passed (17)

npx vitest run js/admin/pages/workbench/__tests__/ScanTabContent.labelPanelReachable.test.tsx
      Tests  2 passed (2)

npx vitest run js/admin/pages/workbench/
 Test Files  82 passed (82)
      Tests  1222 passed (1222)
```

Did **not** run full `npm test` (HEAD baseline `Tests 2403 passed (2403)`). Did **not** present eslint as green. Known eslint baseline remains `✖ 118 problems (117 errors, 1 warning)` — lane B.

`npm run typecheck`: first run `TS2339 mockClear` on the R3-02 Save no-op test. Fixed by passing an explicit `vi.fn()`. Re-run: `tsc --noEmit --project tsconfig.type-check.json` exit 0 (typecheck ok).

## Cross-lane fallout

None observed. Did not run `banned-vocabulary.test.tsx` or `IdentityClusterItem.test.tsx`. New copy: `Merge or split this group`, visible labels `Name this person` / `Person name`. Integrator should re-run those lane-B files.

## Design changes to existing assertions

1. **Item 3 — `NameFaceControl` ArrowDown×2+Enter.** Old: `onOptionConfirm` called with Grace, `onCommit` not called. New: person rows bind via `onCommit({ kind: 'roster', rosterEntryId: 2, name: 'Grace Hopper' })`; `onOptionConfirm` not called. Encodes the person-first design. ClusterEditForm `:114` `onLabelChange` not-called for **cluster** rows is unchanged (still goes through `onOptionConfirm`).
2. **Item 3 — ClusterEditForm handleCommit prefill.** Roster bind with >1 same-fold match no longer no-ops when the folded name equals prefill. R1-13 single exact match still no-ops.
3. **Item 7 — APG first Escape.** Old: one `{Escape}` calls `onCancel`. New: first Escape only closes the overlay; second calls `onCancel`. Same change on `Home / End / Escape`. `aria-controls` still asserted while the listbox is open.

## Canon IDs (grepped)

| ID | Lexicon | Code |
| --- | --- | --- |
| RLSE-04 | `docs/reviews/uxp-2/lexicons/engineering.md:292` | `ScanTabContent.tsx:227` `open_label` restores the map's z-name-curate surface |
| TEST-06 | `engineering.md:147` | every new test observed RED first |
| TEST-07 | `engineering.md:148` | `NameFaceControl.test.tsx` `onOptionConfirm` opt-in |
| TEST-15 | grepped in `docs/reviews/e21-15-rev1-verdict.md` + this report's mutant lines | every item |
| REF-09 | `engineering.md:121` | `NameFaceControl.tsx:334` Save uses the same resolution as Enter |
| DATA-14 | `engineering.md:90` | `ClusterLabelingPanel.tsx:698` Rename anyway through `submitLabel` (one latch) |
| INT-05 | cited in `docs/tasks/21.0/E21-18-control-pane-rework-design.md:76` | Save no longer an enabled no-op; two-stage Escape |
| A11Y-03 | `accessibility.md:17` | `NameFaceControl.tsx:452` visible `<label htmlFor>` |
| A11Y-04 | `accessibility.md:18` | same visible label; reject `aria-label` kept |
| A11Y-11 | `accessibility.md:35` | `NameFaceControl.tsx:465` `aria-controls` only when overlay open; roster-error Retry focused |
| A11Y-12 | `accessibility.md:36` | `NameFaceControl.tsx:505` `role="presentation"` on listbox row wrappers |
| A11Y-14 | `accessibility.md:38` | reject stays pointer-reachable; Tab excluded (`tabIndex={-1}` at `:566`) |
| A11Y-18 | `accessibility.md:47` | residual: roster bind has no undo — new finding, not fixed here (item 9) |
| A11Y-20 | `accessibility.md:49` | `NameFaceControl.tsx` Escape: overlay close is not a surprise cancel |

Not cited (grep in `docs/reviews/uxp-2/lexicons` returned no row): REF-25, REF-26, INT-06, INT-07, A11Y-29, FORM-03, NAV-13.

## Deferred with rationale

**R3-27 — close as `wontfix`.** Single-gesture checkmark commit is what R1-12 / R2-07 closed (`Confirm match with %s` is an explicit confirm, not a surprise context change). Conflicts with the task-plan §Decisions line *"Naming ALWAYS binds a roster person; retire 'Just label'"*. Residual: the write has no undo — raise as a **new** A11Y-18 finding for a later slice. No code, no test.

## Undone

- Panel roster rows still write **label-only** via `updateClusterLabel`; `commitClusterToRosterEntry` exists and is not wired. Do not claim R3-12 fully closed.
- Item 4 option-confirm/select-option guard mutant stayed GREEN (those paths do not write).
- Real ReviewQueue → real ClusterLabelingPanel mount unproven (wiring + source pin only).
- `_name-face.scss` reject hit-test (R3-15) is lane B.
- Full `npm test` / eslint not re-run here.
- Curate control unstyled.

## `git diff --name-only <BASE>..HEAD`

```
apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/ScanTabContent.labelPanelReachable.test.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterEditForm.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/PersonCommitControl.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/PersonCommitControl.test.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx
docs/tasks/uxw2/UXW2-3-fix-r3a-report.md
```

No `js/admin/styles/`, `docs/ux-maps/`, `ClusterActions.tsx`, `IdentityClusterItem.tsx`, `banned-vocabulary.test.tsx`, `gettext-literals.test.ts`, `useOpenReviewTargetLifecycle.ts`, or `UXW2-3-fix-lane-report.md`.
