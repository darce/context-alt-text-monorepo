# UXW2-3-r5 fix report

Commits by subject. Hold-copy literals in `ReviewQueue.tsx` not rewritten.

## Items

| Item | Finding | Commit subject | Tests | TEST-15 mutant RED | After |
| --- | --- | --- | --- | --- | --- |
| 1 | UXW2-3-R5-01 | `test(fe): UXW2-3-R5-01 pin COMMITTING hold copy` | `renders committing-phase role=status with HOLD_COMMITTING_STATUS_COPY and no Undo` | See mutant below | COMMITTING arm now has kill power. ReviewQueue 79 tests. |
| 2 | UXW2-3-R5-02 | `fix(fe): UXW2-3-R5-02 correct hold-copy SSOT comment` | same COMMITTING test + existing HOLDING pin | Both mutants still RED (below) | Variable msgid rejected. Literals kept. Comment matches tests-as-pin. |

### Item 1 mutant (COMMITTING arm swapped to HOLDING copy)

Filter `-t 'committing-phase role=status'` selected 1 test (78 skipped).

```
Error: expect(element).not.toHaveTextContent()

Expected element not to have text content:
  Undo
Received:
  Saving… — Undo
```

```
      Tests  1 failed | 78 skipped (79)
```

Failing test: `renders committing-phase role=status with HOLD_COMMITTING_STATUS_COPY and no Undo`.

Restore GREEN (same filter):

```
      Tests  1 passed | 78 skipped (79)
```

`ReviewQueue.tsx` `git diff` empty after restore.

### Item 2 — variable msgid rejected

Tried `__(HOLD_COMMITTING_STATUS_COPY, …)` / `__(HOLD_STATUS_COPY, …)` in `CommitHoldRegion`. Blocked by `does not pass CONST identifiers into __() across identity-clusters` (`GETTEXT_NON_LITERAL` plus first-arg extractor). Did not disable the guard.

```
AssertionError: expected [ …(3) ] to deeply equal []

- Expected
+ Received

- []
+ [
+   "ReviewQueue.tsx: __(HOLD_COMMITTING_STATUS_COPY,",
+   "ReviewQueue.tsx:1540 HOLD_COMMITTING_STATUS_COPY",
+   "ReviewQueue.tsx:1541 HOLD_STATUS_COPY",
+ ]
```

```
      Tests  1 failed | 2 skipped (3)
```

Route taken: keep `__()` literals in `ReviewQueue.tsx`; pin both strings via imported `HOLD_*_COPY` in `ReviewQueue.test.tsx`. `HOLD_COMMITTING_STATUS_COPY` consumer is the new COMMITTING test. Comment at `useSuggestionReviewMutations.ts:37` / `:40` updated to that fact.

### Item 2 mutants (re-run after SSOT route)

COMMITTING arm-swap, same filter as item 1:

```
Error: expect(element).not.toHaveTextContent()

Expected element not to have text content:
  Undo
Received:
  Saving… — Undo
```

```
      Tests  1 failed | 78 skipped (79)
```

HOLDING ASCII control (`'Saving... - Undo'`). Filter `-t 'HOLD_STATUS_COPY, pause-on-focus'` selected 1 test:

```
Error: expect(element).toHaveTextContent()

Expected element to have text content:
  Saving… — Undo
Received:
  Saving... - UndoUndo
```

```
      Tests  1 failed | 78 skipped (79)
```

Same HOLDING mutant against the full `ReviewQueue.test.tsx` file:

```
      Tests  6 failed | 73 passed (79)
```

Both mutants reverted. `ReviewQueue.tsx` `git diff` empty after restore.

## Stamped lines (sed after last code commit)

- `ReviewQueue.tsx:1536-1539` — COMMITTING / HOLDING `__()` literals still in place.
- `useSuggestionReviewMutations.ts:37-41` — comments now say tests pin the gettext literals; hook announce still uses `HOLD_STATUS_COPY` (`:1070`).
- `ReviewQueue.test.tsx:45` — imports `HOLD_COMMITTING_STATUS_COPY`.
- `ReviewQueue.test.tsx:3597` / `:3616` — HOLDING pin unchanged (`toHaveTextContent(HOLD_STATUS_COPY)`).
- `ReviewQueue.test.tsx:3635` / `:3650-3651` — COMMITTING pin (`HOLD_COMMITTING_STATUS_COPY`, `not.toHaveTextContent('Undo')`).
- `gettext-literals.test.ts:12` / `:117` — unreadied guard that rejected the variable-msgid route.

## Gate

```
cd apps/prototype-wp-alt-context
npx vitest run
```

```
 Test Files  211 passed (211)
      Tests  2421 passed (2421)
```

Baseline was 211 / 2420; +1 is the COMMITTING test.

```
npm run typecheck
```

`tsc --noEmit --project tsconfig.type-check.json` — exit 0, no diagnostics.

Owned-file eslint (the three files this lane may edit) — exit 0.

## Undone

- Variable-msgid SSOT in `ReviewQueue.tsx` blocked by `gettext-literals.test.ts` `does not pass CONST identifiers into __()` (`GETTEXT_NON_LITERAL`). Literals kept; tests pin both exports. No eslint-plugin rule disabled (sr-001).
- `useSuggestionReviewMutations.test.tsx` still says the component consumes `HOLD_STATUS_COPY`. Outside ownership; left as-is.
- Full-app `npm run lint` (`eslint .`) is already red: 119 errors / 1 warning, none in owned files. Not fixed.
- No UX-map edit: rendered hold copy and zones unchanged.
- No contract edit: no payload, endpoint, or enum change.
- Handoff Python API unavailable (`ModuleNotFoundError: No module named 'workbay_handoff_mcp'`). No handoff write.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
