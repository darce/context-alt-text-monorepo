# UXW2-1 r6 fix report

Throwaway mirror. Commits cited by subject only. Line numbers re-derived
with `sed -n '<N>p' <file>` after the last code commit
(`test(fe): UXW2-1-R3-10 pin panes isolation reset kill power`).
No 40-hex strings.

## Closure table

| ID | Commit (subject) | Test | TEST-15 RED | GREEN |
| --- | --- | --- | --- | --- |
| UXW2-1-R3-07 | `test(fe): UXW2-1-R3-07 pin production kind-chip dispatch` | `kind chip on ScanTabContent dispatch writes rq=assignment.all.0 and presses the chip (UXW2-1-R3-07)` (`ReviewQueue.test.tsx:857`; assert `:919`) | see Item 1 | `Tests  1 passed \| 81 skipped (82)` |
| UXW2-1-R3-10 | `test(fe): UXW2-1-R3-10 pin panes isolation reset kill power` | `setter writes collapsed state and clears back to both (param removed)` (`usePanesParam.test.tsx:61`; assert `:76`) | see Item 2 | `Tests  7 passed (7)` |

## Item 1 — UXW2-1-R3-07 (low)

Harness chip pins kept (`:724` / `:725` `.some/.every(SET_KIND)`; band twin `:768` / `:769`). New case mounts **ScanTabContent** (production `dispatchQueue` at `ScanTabContent.tsx:109`), not `makeQueueHarness`. Starts at `/?rq=all.all.2` so a second same-tick clamp/step is visible. Click Close matches. Assert URL `rq=assignment.all.0` (`:919`) plus chip `aria-pressed` (`:922-932`) and `1 of 3` (`:933`).

Mutant A: in `ReviewQueue.tsx` `handleFilterClick` (`:757` `onKindChange(...)`), add `onClampIndex(index);` (pre-click index 2). Restore: `git checkout --` `ReviewQueue.tsx`.

RED:
```
 Test Files  1 failed (1)
      Tests  1 failed | 81 skipped (82)
AssertionError: expected '?rq=assignment.all.2' to contain 'rq=assignment.all.0'
```
Failing assertion: `expect(screen.getByTestId('loc').textContent).toContain('rq=assignment.all.0');`
Diff line: `onClampIndex(index);`

Mutant B: `ScanTabContent.tsx:109` `QUEUE_ACTION.SET_KIND` → `QUEUE_ACTION.SET_BAND`. Restore: `git checkout --` `ScanTabContent.tsx`.

RED:
```
 Test Files  1 failed (1)
      Tests  1 failed | 81 skipped (82)
AssertionError: expected '?rq=all.assignment.0' to contain 'rq=assignment.all.0'
```

GREEN after restore:
```
 Test Files  1 passed (1)
      Tests  1 passed | 81 skipped (82)
```

## Item 2 — UXW2-1-R3-10 (low)

Seed the module buffer in a `beforeEach` that **precedes** the isolation reset (`:31-34` `queuePendingQueueState` / `queuePendingPage`; `:36-38` `resetPendingSearchWritesForTests`). Existing setter (`:61`) now asserts the full search (`:76` `toBe('panes=library-collapsed')`) and `not.toContain('rq=')` (`:77`). Isolation call kept; existing `toContain` / `not.toContain('panes=')` unchanged.

Mutant: delete the `beforeEach(() => { resetPendingSearchWritesForTests(); })` block (`:36-38`). Restore: put the block back.

RED:
```
 Test Files  1 failed (1)
      Tests  1 failed | 6 passed (7)
AssertionError: expected 'rq=assignment.all.0&p=2&panes=library…' to be 'panes=library-collapsed' // Object.is equality
```
Failing assertion: `expect(result.current.search).toBe('panes=library-collapsed');`

GREEN after restore:
```
 Test Files  1 passed (1)
      Tests  7 passed (7)
```

## Gate

From `apps/prototype-wp-alt-context`:

- Targeted R3-07: `npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx -t "UXW2-1-R3-07"` → `1 passed | 81 skipped (82)`
- Targeted R3-10: `npx vitest run js/admin/hooks/__tests__/usePanesParam.test.tsx` → `7 passed (7)`
- Full suite: `npx vitest run` → `Test Files  210 passed (210)` / `Tests  2384 passed (2384)`
- `npm run typecheck` → clean (`tsc --noEmit --project tsconfig.type-check.json`)

## Undone

- `composer test` skipped (PHP untouched).
- `make context` has no rule in this throwaway. MCP tools were unavailable; `uvx` Python API `get_handoff_state` returned no active task, so no `record_event`.
- Harness-level chip spies still observe `makeQueueHarness` (`:724-725`, `:768-769`); kept as required, not replaced.
- Band-chip production dispatch path not added (brief asked for a kind-chip case).
- Mutant A used `onClampIndex(index)` (stale pre-click index). `onClampIndex(0)` would not redden `:919` because `SET_KIND` already zeros the index.
- R4-04 still does not assert the N-of-M `aria-live` region after abandon.
- `peekPendingSearchWritesForTests` / `resetPendingSearchWritesForTests` still ship from production `pendingSearchWrites.ts`.
- `npm run lint` not run.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
