# UXW2-1 R2 — review-finding closure

Lane: close remaining R1-08 / R1-09 / R1-13 and R2-01..05 on the workbench `rq=` URL owner.
Canonical branch: `feature/uxw2-1`.
Baseline: `sync: mirror local feature/uxw2-1` (lane SHA listed below).

All 40-char SHAs below are **lane SHA (non-portable)** from `git log --format=%H` in this worktree after the named commit existed.

## Closure table

| ID | Commit (subject) | Test | TEST-15 mutant killed |
| --- | --- | --- | --- |
| R2-02 | `fix(fe): UXW2-1-R2-02 ghost pending write` | `useWorkbenchFilters.test.tsx` external-navigate + last-instance unmount + same-tick `useTabParam` | Revert reconcile to exact-match only → `expected '?rq=assignment.all.0&p=2' to contain 'rq=merge.all.0'` (`useWorkbenchFilters.test.tsx:301:51`). Unmount-clear missing → `expected { rq: … } to deeply equal {}` (`:312:47`). Writer not merging pending → `expected '?tab=scan' to contain 'rq=assignment.all.0'` (`:347:51`). |
| R2-05 | `fix(fe): UXW2-1-R2-05 test hygiene unpinned seams` | `ScanTabContent.reviewQueueUrl.test.tsx` (`beforeEach(resetPendingSearchWritesForTests)`; double-Next; Prev-under-strong; Strong at index 1; full `rq=merge.strong.0`) | `dispatchQueue({type:SET_INDEX,index:queueState.index+delta})` → `expected '?rq=all.all.1' to contain 'rq=all.all.2'` (`:362:27`). STEP_INDEX-drops-band → `expected '?rq=assignment.all.0' to contain 'rq=assignment.strong.0'` (`:377:27`). SET_BAND-skips-index-reset → `expected '?rq=assignment.strong.1' to contain 'rq=assignment.strong.0'` (`:376:27`). |
| R2-04 | `fix(fe): UXW2-1-R2-04 dead onIndexChange wiring` | `ReviewQueue.test.tsx` chip spies on `reduceQueueAction` | Harness not reducing → `expected false to be true` (`ReviewQueue.test.tsx:676:94` SET_KIND; `:711:94` SET_BAND). |
| R2-03 / R1-13 | `docs(plan): UXW2-1-R1-13 tick shipped slices` | `docs/tasks/uxw2/UXW2-1-workbench-review-filters-task-plan.md` | Slice 1/2 ticked; filename `doubleWrite` → `rqDoubleWrite`; no finding-status list. |
| R2-01 / R1-08 / R1-09 | this report | this file | Subject-line citations; only lane SHAs that `git cat-file -e` accepts; TEST-08 ×3 on this HEAD; no path citations to lane scratch. |

R1-01..07,10,11,12 remain on `fix(workbench): UXW2-1-R1-01-12 close review-queue URL writer findings` (not re-opened).

## Lane SHAs (non-portable)

- `ad699609e45717e1c0f9624236cd4501128fcb36` — `fix(fe): UXW2-1-R2-02 ghost pending write`
- `b8a61ff88729b24ff0aa6ecede7096b6a7b48c3c` — `fix(fe): UXW2-1-R2-05 test hygiene unpinned seams`
- `9aaeb6540f368efb3f43ba76784599969ac9a804` — `fix(fe): UXW2-1-R2-04 dead onIndexChange wiring`
- `e9b25b7230148befc08b366185bbd45d1b8225ad` — `docs(plan): UXW2-1-R2-01 report provenance`
- `c4cee15b80a25704ff319af5fed886cb3a2b4552` — `docs(plan): UXW2-1-R1-13 tick shipped slices`
- `af30887537f8df3e6d179153026596b14cb4c8aa` — `sync: mirror local feature/uxw2-1`
- `6cb83c996976008e9fcae318ae7f43ac641dbda6` — `fix(workbench): UXW2-1-R1-01-12 close review-queue URL writer findings`
- `1fcfaaedfd23b4461279ec6db2de18d7eb8284cd` — `fix(workbench): UXW2-1 single URL owner for review-queue rq= state`

## GREEN evidence (verbatim, this worktree)

`npx tsc --noEmit --project tsconfig.type-check.json`: clean.

`npm run lint` after R2 commits: `✖ 119 problems (118 errors, 1 warning)`. Touched-file lint vs the mirror commit: same single pre-existing `@typescript-eslint/consistent-type-definitions` on `PendingSearchWrites`. Count did not grow.

Full frontend `npm test` ×3 at the last finding commit (`docs(plan): UXW2-1-R1-13 tick shipped slices`):

```
 Test Files  208 passed (208)
      Tests  2366 passed (2366)
   Start at  02:37:59
   Duration  330.04s (transform 10.30s, setup 46.45s, import 34.39s, tests 104.08s, environment 106.30s)
```

```
 Test Files  208 passed (208)
      Tests  2366 passed (2366)
   Start at  02:43:30
   Duration  638.03s (transform 21.24s, setup 105.28s, import 65.13s, tests 191.78s, environment 201.37s)
```

```
 Test Files  208 passed (208)
      Tests  2366 passed (2366)
   Start at  02:54:10
   Duration  437.05s (transform 14.21s, setup 50.62s, import 43.22s, tests 193.59s, environment 108.94s)
```

## Flake evidence (R1-08 / TEST-08)

Runs 1–3: **no FAIL lines**. `grep FAIL` on `/tmp/uxw2-1-r2-test-{1,2,3}.log` empty. Dual-React `useRef` of null was a leftover `node_modules/node_modules` symlink into a sibling checkout; removed locally (not committed). Suite then ran in this worktree. Untouched-file flake: none on 3 consecutive full runs.

## Files changed (R2)

- `useWorkbenchFilters.ts` — snapshot+abandon reconcile; last-instance unmount clear; exported `commitSearchParams`.
- `useTabParam.ts` / `useOverlayParam.ts` / `usePanesParam.ts` / `WorkbenchNavContext.tsx` — writers merge pending.
- `ReviewQueue.tsx` / `ScanTabContent.tsx` — dropped dead `onIndexChange` / `handleIndexChange`.
- Tests as in the table. Harness Parents reduce through `reduceQueueAction`.
- `docs/tasks/uxw2/UXW2-1-workbench-review-filters-task-plan.md`.

## Decisions

- Shared module overlay kept (R1-01). Reconcile now abandons when URL `rq` is neither the pre-write snapshot nor the pending value.
- Non-overlay writers merge pending instead of last-write-winning.
- Chip negative pin spies `reduceQueueAction` (no SET_INDEX), not a dead prop.

## Undone

- e2e chip-persistence still not added (original slice leftover).

Final HEAD = e9b25b7230148befc08b366185bbd45d1b8225ad (lane SHA, non-portable); canonical branch feature/uxw2-1.
