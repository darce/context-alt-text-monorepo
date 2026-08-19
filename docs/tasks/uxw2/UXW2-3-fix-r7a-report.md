# UXW2-3-fix-r7a report

Disclosure only fires when a machine name actually backs the field. Duplicate-guard focus lands on the first action. Person-commit accessible name comes from the visible `<label>`.

## Items

| Id | Commit subject | Proving test | Verbatim RED | GREEN |
| --- | --- | --- | --- | --- |
| UXW2-3-R6-05 | `fix(fe): UXW2-3-R6-05 gate suggestion disclosure on suggestedCreateName` | `does not render the model-output disclosure when suggestedCreateName is null (UXW2-3-R6-05)` (+ present twin) | See below. Absent-case fired. | `Tests  1 passed \| 18 skipped (19)` after restore; PersonCommitControl file `Tests  20 passed (20)` |
| UXW2-3-R6-06 | `fix(fe): UXW2-3-R6-06 move focus to duplicate-guard first action` | `moves focus to the first duplicate-guard action when the guard opens (UXW2-3-R6-06)` | See below. Identity `toBe` (body vs merge button). | `Tests  1 passed \| 47 skipped (48)`; file `Tests  48 passed (48)` |
| UXW2-3-R6-08 | `fix(fe): UXW2-3-R6-08 drop redundant ariaLabel on person-commit` | `takes the accessible name from the visible label, not aria-label (UXW2-3-R6-08)` | See below. Accname resolved to the mutant aria-label string. | `Tests  1 passed \| 19 skipped (20)`; file `Tests  20 passed (20)` |

Commits verified with `git log --format=%s --fixed-strings --grep="<subject>"`.

## 1. UXW2-3-R6-05 — disclosure only when there is a suggestion

**Prop keyed on:** `suggestedCreateName` (non-empty after `trim`).

Honest because ReviewQueue already uses that prop as the machine create-name: NAME passes `suggestion.suggested_name` (`ReviewQueue.tsx:1858-1860`); CLUSTER passes `cluster.suggested_label` (`:1923-1925`); ASSIGNMENT passes nothing (`:1767`). Same value prefills the field. Null/blank/whitespace means there is no model name to confirm — a banner here would label the operator's own typing as face-matching output ([HAI-05], [HAI-13], [PERC-07]).

`PersonCommitControl.tsx:72` `hasMachineSuggestion = Boolean(suggestedCreateName?.trim())`. Render gated at `:160`.

Pinned both directions:

- present: `PersonCommitControl.test.tsx:170` (`suggestedCreateName: 'Morgan'`); CLUSTER integration `ReviewQueue.test.tsx:1857` (`suggested_label: 'Morgan'`).
- absent: `PersonCommitControl.test.tsx:175` (`null`); CLUSTER fixture `ReviewQueue.test.tsx:1838` `suggested_label: null` now asserts absence at `:1854`. ASSIGNMENT (`:1472` / `:1494`) also asserts absence — that card never had a create-name suggestion.

UX map: `workbench-operator-loop.uxmap.json` `z-identity-preview` gained state `suggested` (disclosure on); sibling `.md` render updated.

### TEST-15 mutant RED (unconditional render restored)

Filter `-t 'does not render the model-output disclosure when suggestedCreateName is null'` selected 1 test.

```
Error: expect(element).not.toBeInTheDocument()

expected document not to contain element, found <p
  class="acx-person-commit__disclosure"
>
  Suggested by face matching based on similarity — confirm before treating it as fact.
</p> instead
```

Restore: `git diff` on `PersonCommitControl.tsx` showed only the intended `hasMachineSuggestion` gate (no leftover unconditional `<p>`). Absent-case GREEN after restore.

## 2. UXW2-3-R6-06 — blocking choice moves focus; live region dropped

**Carrier: focus, not a live region.**

[A11Y-21] is for async status *without* focus. This guard already blocked commit. [A11Y-24] / [A11Y-11]: the state needs a keyboard stop, same pattern as `rosterRetryRef` (`ClusterLabelingPanel.tsx:194`). Focus lands on the first actionable control (`:201` via `duplicateGuardFirstActionRef`, Merge when offered else Rename anyway). AT announces that control's name.

A polite `role="status"` deferred the blocking choice and competed with the show-all region (`:574`). Did not keep an assertive live region on top of focus — two channels would serialize against each other. Guard is `role="group"` + `aria-labelledby` (`:657`) so the explanation names the group; the message to the operator is the focused button.

Proving test `ClusterLabelingPanel.test.tsx:167` asserts `document.activeElement` `toBe` the Merge button (`:176`), not by text.

### TEST-15 mutant RED (focus call deleted)

Filter `-t 'moves focus to the first duplicate-guard action'` selected 1 test.

```
AssertionError: expected <body><div>…(1)</div></body> to be <button type="button" …(1)></button> // Object.is equality
```

Received: `document.body`. Expected: Merge into group "Slate Willow" button.

Restore: focus call back at `:201`. `git diff` clean of mutant.

UX map: `workbench-2pane.uxmap.json` `z-name-curate` gained `duplicate-guard`; sibling `.md` render + states summary updated.

## 3. UXW2-3-R6-08 — visible `<label>` is the accessible name

Call site no longer passes `ariaLabel`. `visibleLabel` + `inputId` remain (`PersonCommitControl.tsx:198-199`). `NameFaceControl` still renders `<label htmlFor>` when those are set (`NameFaceControl.tsx:452-456`). With `ariaLabel` undefined, React omits `aria-label={ariaLabel}` (`:477`). Verified: `getByLabelText('Name this person')` + `toHaveAccessibleName` + `htmlFor`/`id` + `not.toHaveAttribute('aria-label')` (`PersonCommitControl.test.tsx:143-151`).

[A11Y-03] associate a visible label. [A11Y-04] visible text in the accessible name. [A11Y-55] a non-empty `aria-label` discards the host `<label>`. [A11Y-12] wrong ARIA overrides correct semantics.

### TEST-15 mutant RED (`ariaLabel="Stale aria name"` — different string)

Filter `-t 'takes the accessible name from the visible label'` selected 1 test.

```
Error: expect(element).toHaveAccessibleName()

Expected element to have accessible name:
  Name this person
Received:
  Stale aria name
```

Restore: `ariaLabel` line gone. `git diff` on `PersonCommitControl.tsx` showed only that deletion.

## Gate

From `apps/prototype-wp-alt-context`, at the last code commit:

```
npx vitest run
```

```
 Test Files  211 passed (211)
      Tests  2430 passed (2430)
```

```
npx tsc --noEmit --project tsconfig.type-check.json
```

exit 0, no diagnostics.

## Undone

- `ClusterEditForm.tsx:189-190` still pairs `ariaLabel` + `visibleLabel` both `'Person name'`. Same A11Y-55 trap. Other lane. Not fixed.
- `NameFaceControl.tsx:477` still assigns `aria-label={ariaLabel}` whenever the prop is a non-empty string. Person-commit is safe because the prop is omitted. A future caller that passes both will silently drop the visible label. Shared-control finding; not edited (hard boundary).
- ASSIGNMENT person-commit (`ReviewQueue.tsx:1767`) still does not pass a create-name. Cannot thread a new prop (must not edit `ReviewQueue.tsx`). Disclosure correctly stays off.
- Duplicate-guard path with no Merge (Rename anyway first) uses the fallback ref on that button. No separate identity test for that branch.
- `workbench-operator-loop.uxmap.md` mermaid / slice list not updated (not the zone-state render). `workbench-2pane.preview.md` has no zone-state list.
- No contract edit: no payload, endpoint, or enum change.
- Handoff Python API / `make context` unavailable on this throwaway mirror. No handoff write.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
