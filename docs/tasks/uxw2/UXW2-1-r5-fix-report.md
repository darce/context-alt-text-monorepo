# UXW2-1 r5 fix report

Throwaway mirror. Commits cited by subject only. Line numbers re-derived
with `sed -n '<n>p' <file>` after the last code commit.

## Item 1 — UXW2-1-R5-01 (HIGH): p-branch abandon pin

Commit: `test(fe): UXW2-1-R5-01 pin p-branch abandon with null snapshot`

Direct `queuePendingPage` + `reconcilePendingSearchWrites` so TEST-15 hits
the p-buffer abandon arm. Hook-level overlay races can still land via
`commitSearchParams` and then clear as a match, which is why the
`pSnapshot !== undefined &&` revert previously survived.

Tests (`useWorkbenchFilters.test.tsx`):
- non-null snapshot, URL `p` matches neither pending nor snapshot (`:717`)
- null snapshot, dest still has no `p`, pending page > 1 (`:727`; assert `:733`)

Mutant: `sed` `pendingSearchWrites.pSnapshot == null ||` →
`pendingSearchWrites.pSnapshot !== undefined &&`

RED:
```
 Test Files  1 failed (1)
      Tests  2 failed | 28 passed (30)
AssertionError: expected 2 to be undefined
 UXW2-1-R5-01: p buffer snapshotted from a bare URL is dropped when dest still has no p and pending page is > 1
```
(Companion R4-01 hook-level case also went red under this mutant; the
direct reconcile is the deterministic kill.)

Restore: `git checkout --` `pendingSearchWrites.ts` (diff clean).

GREEN:
```
 Test Files  1 passed (1)
      Tests  30 passed (30)
```

## Item 2 — UXW2-1-R5-02 (MEDIUM): choice A

Commit: `test(fe): UXW2-1-R5-02 choose A null-snapshot abandon`

Choice **A**: a null snapshot means the URL had no value; abandoning an
empty dest is correct because a legitimate landing would have written the
value. Evidence:

- `pageMatches(null, 1)` is true, so queued page-1 from a bare URL lands
  on the pre-write URL before the `snapshot == null` disjunct
  (`useWorkbenchFilters.test.tsx:737`).
- Hook reconcile runs in `useEffect` after `setSearchParams` flush
  (`useWorkbenchFilters.ts:118` retain, reconcile on `searchParams`), so
  page>1 / non-default `rq` in-flight first sees the flushed URL, not the
  pre-write empty dest.
- Null-snapshot abandon is the external-nav path.

Comment at `pendingSearchWrites.ts:65` states that in one sentence; p-arm
comment at `:79`. Conditions unchanged (`:62` rq, `:76` p).

Flip-pin tests: null snapshot + empty dest + pending page>1 (`:727`) and
the rq sibling (`:753`). In-flight keep while URL still equals a non-null
snapshot (`:745`).

B-flip mutant: drop `== null ||`, keep only `url !== snapshot`.

RED:
```
 Test Files  1 failed (1)
      Tests  5 failed | 28 passed (33)
AssertionError: expected 2 to be undefined
 UXW2-1-R5-01: p buffer snapshotted from a bare URL is dropped when dest still has no p and pending page is > 1
AssertionError: expected { kind: 'assignment', …(2) } to be undefined
 UXW2-1-R5-02: rq buffer snapshotted from a bare URL is dropped when dest still has no rq
```
Page-1 characterization (`:737`) stayed green (pageMatches). In-flight
keep (`:745`) stayed green.

GREEN after restore:
```
 Test Files  1 passed (1)
      Tests  33 passed (33)
```

## Item 3 — UXW2-1-R3-04 (MEDIUM): pin three writers

Queue pending `rq` in the module buffer, then invoke the writer. That
kills a raw `setSearchParams((prev) => { ... })` that ignores
`applyPendingSearchWrites` even if same-tick updater chaining would save
a `dispatchQueue` + writer race.

### overlay

Commit: `test(fe): UXW2-1-R3-04 pin useOverlayParam commitSearchParams merge`

Test: `useOverlayParam.test.tsx:27` (assert `:43`). Writer:
`useOverlayParam.ts:17`.

RED (raw `setSearchParams`):
```
 Test Files  1 failed (1)
      Tests  1 failed (1)
AssertionError: expected 'panel=conflicts' to contain 'rq=assignment.all.0'
```

GREEN after `git checkout -- useOverlayParam.ts`:
```
 Test Files  1 passed (1)
      Tests  1 passed (1)
```

### tab

Commit: `test(fe): UXW2-1-R3-04 pin useTabParam commitSearchParams merge`

Test: `useTabParam.test.tsx:73` (assert `:89`). Writer: `useTabParam.ts:18`.

RED:
```
 Test Files  1 failed (1)
      Tests  1 failed | 3 passed (4)
AssertionError: expected 'tab=scan' to contain 'rq=assignment.all.0'
```

GREEN after `git checkout -- useTabParam.ts`:
```
 Test Files  1 passed (1)
      Tests  4 passed (4)
```

### setAdvancedOpen

Commit: `test(fe): UXW2-1-R3-04 pin setAdvancedOpen commitSearchParams merge`

Test: `WorkbenchNavContext.test.tsx:39` (assert `:55`). Writer:
`WorkbenchNavContext.tsx:50`.

RED:
```
 Test Files  1 failed (1)
      Tests  1 failed (1)
AssertionError: expected 'advanced=open' to contain 'rq=assignment.all.0'
```

GREEN after `git checkout -- WorkbenchNavContext.tsx`:
```
 Test Files  1 passed (1)
      Tests  1 passed (1)
```

## Item 4 — UXW2-1-R5-03 (MEDIUM): report truth

This commit. Rewrote `docs/tasks/uxw2/UXW2-1-report.md`:

- Re-derived every `file:line` in the closure table.
- Dropped "unresolved here (`fix(fe): …` returns empty)" sentences;
  production is cited by file:line.
- Replaced the stale GREEN block (old 208/2366 runs taken at
  `docs(uxw2-1): UXW2-1-R1-13 tick shipped review-filter slices`) with
  three full-suite runs at this lane's code HEAD.

## Gate

`npx tsc --noEmit --project tsconfig.type-check.json`: clean.

Three full-suite runs (`npx vitest run` from `apps/prototype-wp-alt-context`):

```
 Test Files  210 passed (210)
      Tests  2383 passed (2383)
   Start at  09:56:23
   Duration  331.30s (transform 10.06s, setup 44.55s, import 35.25s, tests 109.65s, environment 103.45s)
```

```
 Test Files  210 passed (210)
      Tests  2383 passed (2383)
   Start at  10:02:09
   Duration  294.04s (transform 8.91s, setup 38.64s, import 30.35s, tests 98.19s, environment 92.24s)
```

```
 Test Files  210 passed (210)
      Tests  2383 passed (2383)
   Start at  10:07:36
   Duration  283.97s (transform 7.71s, setup 37.43s, import 28.51s, tests 93.98s, environment 90.08s)
```

## Undone

- e2e chip-persistence still not added (original slice leftover).
- `usePanesParam.test.tsx` still has no module-buffer merge pin; only the
  same-tick pin in `useWorkbenchFilters.test.tsx` covers panes.
- `npm run lint` not re-run on this lane.
- Choice A leaves a theoretical window if something called
  `reconcilePendingSearchWrites` on the pre-write empty URL after queuing
  page>1 and before `setSearchParams` flush. The hook path does not do
  that; no production change was made to close it.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
