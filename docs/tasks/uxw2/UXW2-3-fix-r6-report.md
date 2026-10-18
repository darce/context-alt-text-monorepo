# UXW2-3-fix-r6 report

COMMITTING hold is now announced, pinned, and remounted. Post-advance focus lands in the name field.

## Items

| Id | Commit subject | Test | TEST-15 RED | GREEN |
| --- | --- | --- | --- | --- |
| UXW2-3-R6-01 | `fix(fe): UXW2-3-R6-01 wire hold-copy SSOT and whole-content pin` | `renders committing-phase role=status with HOLD_COMMITTING_STATUS_COPY and no Undo` | See below. Fired by **assertion 1** `wholeHoldText(status)).toBe(HOLD_COMMITTING_STATUS_COPY)` — not the negative-Undo check. | `Tests  2 passed \| 78 skipped (80)` |
| UXW2-3-R6-03 | `test(fe): UXW2-3-R6-03 pin COMMITTING passthrough via deferred mock` | `R6-03: deferred accept POST renders COMMITTING through the ReviewQueue passthrough` | See below | `Tests  1 passed \| 80 skipped (81)` |
| UXW2-3-R6-07 | `fix(fe): UXW2-3-R6-07 remount hold live region on phase change` | same integration test, `expect(committing).not.toBe(holding)` | See below | `Tests  1 passed \| 80 skipped (81)` |
| UXW2-3-R6-04 | `fix(fe): UXW2-3-R6-04 delete dead phase-blind hold announce` | deletion + full suite | n/a (dead-code delete) | `Tests  2423 passed (2423)` |
| UXW2-3-R6-02 | `fix(fe): UXW2-3-R6-02 land post-advance focus on name combobox` | `BR-27: focus on NAME card lands on person-commit combobox/confirm (not demoted Accept)` | See below | `Tests  2 passed \| 79 skipped (81)` |

Supporting: `test(fe): UXW2-3-R6-03 reset fetchClusterMembers between cases` — the 404 members mock from the retirement case leaked and retired the head, so the deferred COMMITTING test saw no hold region when run in-file.

### UXW2-3-R6-01 mutant RED

Mutant: COMMITTING copy `'Saving… now'`. Filter `-t 'committing-phase role=status'` selected 1 test.

```
AssertionError: expected 'Saving… now' to be 'Saving…' // Object.is equality

Expected: "Saving…"
Received: "Saving… now"
```

Assertion that fired: `expect(wholeHoldText(status)).toBe(HOLD_COMMITTING_STATUS_COPY)` (whole-content / Object.is). The following `not.toHaveTextContent('Undo')` did **not** fire.

### UXW2-3-R6-03 mutant RED

Mutant: delete the COMMITTING arm from the `ReviewQueue.tsx` phase map (FAILED or HOLDING only). Filter `-t 'R6-03: deferred accept'` selected 1 test.

```
AssertionError: expected 'Saving… — UndoUndo' to be 'Saving…' // Object.is equality

Expected: "Saving…"
Received: "Saving… — UndoUndo"
```

### UXW2-3-R6-07 mutant RED

Mutant: remove `key={hold.phase}`. Same filter, 1 test.

```
AssertionError: expected <div …(3)><span …(1)></span></div> not to be <div …(3)><span …(1)></span></div> // Object.is equality
```

### UXW2-3-R6-02 mutant RED

Mutant: restore `'.acx-person-commit__confirm:not([disabled])'` to the front of `personCommitSelectors`. Filter `-t 'BR-27: focus on NAME card'` selected 1 test.

```
AssertionError: expected <button type="button" …(2)></button> to be <input role="combobox" …(9)></input> // Object.is equality
```

Received: Save name button. Expected: combobox named "Name this person".

### UXW2-3-R6-04 grep

Before:

```
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useSuggestionReviewData.ts:39:    holdAnnounce,
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useSuggestionReviewData.ts:151:    holdAnnounce,
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useSuggestionReviewMutations.ts:1071:    holdAnnounce: HOLD_STATUS_COPY,
```

After: zero hits (`git grep -n holdAnnounce` exit 1, empty stdout).

Corrected r5 sentence (`docs/tasks/uxw2/UXW2-3-r5-fix-report.md:106`):

> comments now say tests pin the gettext literals. The hook-returned announce string was a dead HOLDING-only copy and was not consumed by any renderer.

## What changed (stamped after last code commit)

- `useSuggestionReviewMutations.ts:38-42` — `HOLD_*_STATUS_COPY` are `__()` results; docblocks say CommitHoldRegion renders them.
- `ReviewQueue.tsx:1538-1541` — `CommitHoldRegion` imports those exports (SSOT). No `__('Saving…` left in the file.
- `ReviewQueue.tsx:1632-1639` — `key={hold.phase}` remounts the hold live region (same pattern as `key={liveSeq}` at `:1166`). COMMITTING arm of the phase map stays.
- `ReviewQueue.tsx:495-497` — combobox selector first; confirm second.
- `useSuggestionReviewMutations.ts:1070` / `useSuggestionReviewData.ts:38` and `:149` — hook-returned announce field gone.
- `ReviewQueue.test.tsx:3749-3751` — whole-content COMMITTING pin plus negative Undo.
- `ReviewQueue.test.tsx:3611` / `:3669-3674` — deferred-POST integration + remount identity.
- `ReviewQueue.test.tsx:2060` — BR-27 now requires the combobox by role and accessible name.

Canon for R6-02 (verified in `~/uxw2/canon/lexicons/`): [HAI-12] output is a proposal; [HAI-13] user is the last error detector; [HAI-11] keep an edit path when the model pre-labels; [INT-07] preview before a costly commit; [FORM-04] smart prefills, not dark defaults; [A11Y-18] reversible, checked, or confirmed.

## Gate

```
cd apps/prototype-wp-alt-context
npx vitest run
```

```
 Test Files  211 passed (211)
      Tests  2423 passed (2423)
```

```
npx tsc --noEmit --project tsconfig.type-check.json
```

exit 0, no diagnostics.

## Undone

- UX maps (`apps/prototype-wp-alt-context/docs/ux-maps/*`) are outside ownership. "Save name" is still the PRIMARY verb; post-advance focus landing is not mapped. No map edit.
- `useSuggestionReviewMutations.test.tsx` still says the component consumes `HOLD_STATUS_COPY`. Outside ownership; left as-is (same as r5).
- CLUSTER BR-27 still only asserts "inside person-commit". That card has no suggested label, so confirm is disabled and the combobox already wins. NAME is the prefilled-Save case.
- Isolated `CommitHoldRegion` COMMITTING render has no `key` of its own — remount is on the `ReviewQueue` call site (`:1633`), which is the live path.
- No contract edit: no payload, endpoint, or enum change.
- Handoff Python API / `make context` unavailable on this throwaway mirror. No handoff write.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
