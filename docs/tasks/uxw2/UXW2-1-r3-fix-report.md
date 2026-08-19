# UXW2-1 r3 fix report

Throwaway mirror. Commits cited by subject only. Hashes omitted.

## Items

### 1. R3-01 / R3-02 / R3-03 / R2-01 / R1-09

Commit: `docs(uxw2-1): UXW2-1-R3-01 report truth repair`

No new tests.

Rewrote `docs/tasks/uxw2/UXW2-1-report.md` in place: deleted the Lane SHAs section and every 40-hex string; dropped R2-02/04/05 subjects that `git log --fixed-strings --grep` returns empty for on this mirror; aligned TEST-08 ×3 to `docs(uxw2-1): UXW2-1-R1-13 tick shipped review-filter slices` (not re-run at tip) and listed that in that report's Undone; stripped scratch paths; replaced board-status prose with a handoff-DB pointer; Final HEAD deferred to the integrator.

`sed -n` of the three repaired line cites:

```
ReviewQueue.test.tsx:651
    expect(reduceSpy.mock.calls.some(([, action]) => action.type === QUEUE_ACTION.SET_KIND)).toBe(true);

ReviewQueue.test.tsx:686
    expect(reduceSpy.mock.calls.some(([, action]) => action.type === QUEUE_ACTION.SET_BAND)).toBe(true);

ScanTabContent.reviewQueueUrl.test.tsx:394
      expect(locSearch()).toContain('rq=assignment.strong.0');
```

Verification (item 1 rules; hashes omitted):

```
git grep -cE '[0-9a-f]{40}' -- docs/tasks/uxw2/UXW2-1-report.md
# no match, exit 1

scratch-dir grep on UXW2-1-report.md (temp + lane-dir prefixes)
# no match, exit 1 each

git log --format=%H --fixed-strings --grep='docs(uxw2-1): UXW2-1-R3-01 report truth repair'
git log --format=%H --fixed-strings --grep='fix(fe): UXW2-1-R3-04 pin remaining commitSearchParams seams'
git log --format=%H --fixed-strings --grep='fix(fe): UXW2-1-R3-05 unmount guard and p abandon'
git log --format=%H --fixed-strings --grep='fix(fe): UXW2-1-R3-06 abandon null snapshot null dest'
git log --format=%H --fixed-strings --grep='fix(fe): UXW2-1-R3-10 panes test buffer reset'
# each: 1 match
```

GREEN: mechanical; no suite.

### 2. R3-04

Commit: `fix(fe): UXW2-1-R3-04 pin remaining commitSearchParams seams`

Tests (all in `useWorkbenchFilters.test.tsx`):
- `useOverlayParam in the same tick merges pending rq instead of ghosting it (UXW2-1-R3-04)` (`:514`; assert `:546`)
- `usePanesParam in the same tick merges pending rq instead of ghosting it (UXW2-1-R3-04)` (`:550`; assert `:582`)
- `setAdvancedOpen in the same tick merges pending rq instead of ghosting it (UXW2-1-R3-04)` (`:586`; assert `:630`)

Production writers unchanged (`useOverlayParam.ts:17`, `usePanesParam.ts:20`, `WorkbenchNavContext.tsx:50`).

Before/after mutant pairs:

| mutant | HEAD (no new tests) | after tests |
| --- | --- | --- |
| overlay: raw `setSearchParams` | GREEN `Tests  20 passed (20)` | RED `expected '?panel=conflicts' to contain 'rq=assignment.all.0'` |
| panes: raw `setSearchParams` | (same HEAD green; panes unpinned) | RED `expected '?panes=control-collapsed' to contain 'rq=assignment.all.0'` |
| setAdvancedOpen: raw `setSearchParams` | (same HEAD green; seam unpinned) | RED `expected '?advanced=open' to contain 'rq=assignment.all.0'` |

GREEN after restore: `Tests  23 passed (23)` (`npx vitest run js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx`).

### 3. R3-05 / R3-09

Commit: `fix(fe): UXW2-1-R3-05 unmount guard and p abandon`

Deleted `seedPendingSearchWritesForTests`. Kept `resetPendingSearchWritesForTests` (`useWorkbenchFilters.ts:115`) and `peekPendingSearchWritesForTests` (`:121`).

Tests:
- rewritten setup: `unmounting the last hook instance clears the pending search buffer (R2-02)` (`:306`)
- `unmounting one of two mounted instances keeps the pending buffer alive (UXW2-1-R3-05)` (`:315`; assert `:359`)
- `a p write abandoned by an external navigate does not resurrect (UXW2-1-R3-05)` (`:364`; assert `:396`)

Before/after mutant pairs:

| mutant | HEAD (before new tests) | after tests |
| --- | --- | --- |
| drop `if (workbenchFilterInstanceCount <= 0)` so every unmount clears | GREEN `Tests  23 passed (23)` | RED `expected undefined to be defined` (`:359`) |
| delete `pSnapshot` abandon branch | GREEN `Tests  23 passed (23)` | RED `expected 2 to be undefined` (`:396`) |

GREEN after restore: `Tests  25 passed (25)`.

### 4. R3-06 + rest of R2-02

Commit: `fix(fe): UXW2-1-R3-06 abandon null snapshot null dest`

`useWorkbenchFilters.ts:152-155` (`rqSnapshot == null` or `urlRq !== rqSnapshot`); same on `p` (`:171-172`). First `urlRq === pendingRq` clear unchanged.

Tests:
- `a queue write snapshotted from a bare URL is abandoned when the destination also omits rq (UXW2-1-R3-06)` (`:400`; assert `:430`)
- `the abandoned rq does not resurrect on the next unrelated commit (UXW2-1-R3-06)` (`:433`; assert `:476`)

TEST-06 RED before the production change:
- `expected { kind: 'assignment', …(2) } to be undefined`
- `expected '?tab=scan&panel=conflicts&rq=assignme…' not to contain 'rq='` received `?tab=scan&panel=conflicts&rq=assignment.all.0&p=1&s=cat`

TEST-15 restore HEAD `rqSnapshot !== undefined && urlRq !== rqSnapshot`:
RED `expected '?tab=scan&panel=conflicts&rq=assignme…' not to contain 'rq='` received `?tab=scan&panel=conflicts&rq=assignment.all.0&p=1&s=cat`

GREEN after fix: `Tests  27 passed (27)` on the filters file; with `ScanTabContent.reviewQueueUrl.test.tsx`: `Test Files  2 passed (2)` / `Tests  36 passed (36)` (deep links `:331` / `:383` / `:417` stayed green).

### 5. R3-10 (partial) / R3-08 (not done)

Commit: `fix(fe): UXW2-1-R3-10 panes test buffer reset`

`usePanesParam.test.tsx:27-29` `beforeEach(resetPendingSearchWritesForTests)`.

GREEN: `Tests  7 passed (7)` (`npx vitest run js/admin/hooks/__tests__/usePanesParam.test.tsx`).

Dirty-buffer beforeEach mutant stayed GREEN (`Tests  7 passed (7)`): existing panes assertions never inspect `rq`. R3-10 kill power not proven.

R3-08 module split not attempted beyond the ownership check.

### 6. R3-07

Not done. See Undone.

## Suite counts observed

```
cd apps/prototype-wp-alt-context && npx vitest run \
  js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx \
  js/admin/hooks/__tests__/usePanesParam.test.tsx \
  js/admin/pages/workbench/__tests__/ScanTabContent.reviewQueueUrl.test.tsx

 Test Files  3 passed (3)
      Tests  43 passed (43)
   Start at  06:05:06
   Duration  10.34s (transform 2.71s, setup 1.16s, import 4.24s, tests 2.04s, environment 2.12s)
```

Did not run `npm test` or `npx tsc`.

## Design changes to existing assertions

Only `useWorkbenchFilters.test.tsx:306-313` (`unmounting the last hook instance clears the pending search buffer (R2-02)`). Setup now fills the buffer with `dispatchQueue` inside `act()` instead of `seedPendingSearchWritesForTests`. Assertion `expect(peekPendingSearchWritesForTests()).toEqual({})` is unchanged.

## For the integrator

R3-11 DB half cannot be written from this throwaway mirror. Finding status is live in the handoff DB; query it, do not read it here.

Reviewer-named as verified-fixed-in-code (this lane did not close the rows): `R1-02`, `R1-04`, `R1-07`, `R1-11`, `R1-12`.

`git diff --name-only` from the opening `sync: mirror local feature/uxw2-1` commit through this report (ownership list only):

```
apps/prototype-wp-alt-context/js/admin/hooks/__tests__/usePanesParam.test.tsx
apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx
apps/prototype-wp-alt-context/js/admin/hooks/useWorkbenchFilters.ts
docs/tasks/uxw2/UXW2-1-report.md
docs/tasks/uxw2/UXW2-1-r3-fix-report.md
```

## Canon IDs satisfied

Grepped in `canon/lexicons/engineering.md` before citing.

- DATA-14 — `useWorkbenchFilters.ts:152` (one pending buffer; overlay href must not resurrect a second `rq` write); same-tick seams `useOverlayParam.ts:17`, `usePanesParam.ts:20`, `WorkbenchNavContext.tsx:50`
- REF-09 — `useWorkbenchFilters.ts:152-155` / `:171-172` (derived pending vs live URL)
- REF-25 — `docs/tasks/uxw2/UXW2-1-report.md` (dead SHAs / scratch paths boarded up)
- REF-26 — same file: commit identity is the subject line, not a parallel SHA list
- RLSE-06 — `useWorkbenchFilters.test.tsx:514` / `:550` / `:586` (same-tick overlay/panes/advanced)
- TEST-06 — item 4 tests observed failing before the production change
- TEST-07 — `useWorkbenchFilters.ts:115`; `usePanesParam.test.tsx:27`
- TEST-08 — `UXW2-1-report.md` TEST-08 ×3 attributed to `docs(uxw2-1): UXW2-1-R1-13 tick shipped review-filter slices`, not this tip
- TEST-15 — mutants in items 2–4; RED lines pasted above
- TEST-19 — not satisfied (item 6)

## Undone

- R3-08: `pendingSearchWrites.ts` split not done. The three param hooks plus `WorkbenchNavContext.tsx` are in ownership, but existing `importOriginal` mocks in `WorkbenchPage.test.tsx` / `ScanTabContent.nav03.test.tsx` / `ScanTabContent.controlPaneOrder.test.tsx` are not. Guard said stop.
- R3-10 mutant: dirty `beforeEach` did not redden existing panes assertions (they never look at `rq`). Reset is in place; kill not proven.
- R3-07: chip pin still spies harness `reduceQueueAction`. Production mutant would edit `ReviewQueue.tsx` (out of ownership). Harness-boundary simulation is the defect the finding describes. Left undone.
- Full frontend suite not re-run at this tip.
- Handoff DB rows (R3-11) not closed from this mirror.
