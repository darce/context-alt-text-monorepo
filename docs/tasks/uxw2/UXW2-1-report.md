# UXW2-1 R2 — review-finding closure

Lane: close remaining R1-08 / R1-09 / R1-13 and R2-01..05 on the workbench `rq=` URL owner.
Canonical branch: `feature/uxw2-1`.
Baseline: latest `sync: mirror local feature/uxw2-1` commit on this throwaway mirror.

Commits are cited by subject line only. Subjects that do not resolve via
`git log --format=%H --fixed-strings --grep="<subject>"` on this mirror are
not citations — they are named as unresolved.

## Closure table

| ID | Commit (subject) | Test | TEST-15 mutant killed |
| --- | --- | --- | --- |
| R2-02 | unresolved here (`fix(fe): UXW2-1-R2-02 ghost pending write` returns empty). Production change is present on this mirror. | `useWorkbenchFilters.test.tsx` external-navigate + last-instance unmount + same-tick `useTabParam` | Revert reconcile to exact-match only → `expected '?rq=assignment.all.0&p=2' to contain 'rq=merge.all.0'` (`useWorkbenchFilters.test.tsx:301`). Unmount-clear missing → `expected { rq: … } to deeply equal {}` (`:312`). Writer not merging pending → `expected '?tab=scan' to contain 'rq=assignment.all.0'` (`:347`). |
| R2-05 | unresolved here (`fix(fe): UXW2-1-R2-05 test hygiene unpinned seams` returns empty). Production change is present on this mirror. | `ScanTabContent.reviewQueueUrl.test.tsx` (`beforeEach(resetPendingSearchWritesForTests)`; double-Next; Prev-under-strong; Strong at index 1; full `rq=merge.strong.0`) | `dispatchQueue({type:SET_INDEX,index:queueState.index+delta})` → `expected '?rq=all.all.1' to contain 'rq=all.all.2'` (`:362`). STEP_INDEX-drops-band → `expected '?rq=assignment.all.0' to contain 'rq=assignment.strong.0'` (`ScanTabContent.reviewQueueUrl.test.tsx:394`). SET_BAND-skips-index-reset → `expected '?rq=assignment.strong.1' to contain 'rq=assignment.strong.0'` (`:376`). |
| R2-04 | unresolved here (`fix(fe): UXW2-1-R2-04 dead onIndexChange wiring` returns empty). Production change is present on this mirror. | `ReviewQueue.test.tsx` chip spies on `reduceQueueAction` | Harness not reducing → `expected false to be true` (`ReviewQueue.test.tsx:651` SET_KIND; `:686` SET_BAND). |
| R2-03 / R1-13 | `docs(uxw2-1): UXW2-1-R1-13 tick shipped review-filter slices` | `docs/tasks/uxw2/UXW2-1-workbench-review-filters-task-plan.md` | Slice 1/2 ticked; filename `doubleWrite` → `rqDoubleWrite`; no finding-status list. Original subject `docs(plan): UXW2-1-R1-13 tick shipped slices` does not resolve on this mirror. |
| R2-01 / R1-08 / R1-09 | this report | this file | Subject-line citations only; no 40-hex strings; TEST-08 ×3 taken at `docs(uxw2-1): UXW2-1-R1-13 tick shipped review-filter slices`, not re-run at the tip of this mirror. |

finding status is live in the handoff DB; query it, do not read it here.

## GREEN evidence (verbatim, this worktree)

`npx tsc --noEmit --project tsconfig.type-check.json`: clean.

`npm run lint` after R2 commits: `✖ 119 problems (118 errors, 1 warning)`. Touched-file lint vs the mirror commit: same single pre-existing `@typescript-eslint/consistent-type-definitions` on `PendingSearchWrites`. Count did not grow.

Three full-suite runs taken at `docs(uxw2-1): UXW2-1-R1-13 tick shipped review-filter slices`, not re-run at final HEAD:

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

Runs 1–3: **no FAIL lines**. Dual-React `useRef` of null was a leftover `node_modules/node_modules` symlink into a sibling checkout; removed locally (not committed). Suite then ran in this worktree. Untouched-file flake: none on 3 consecutive full runs.

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
- Three full-suite TEST-08 runs were taken at `docs(uxw2-1): UXW2-1-R1-13 tick shipped review-filter slices`, not re-run at the tip of this mirror.
- R2-02 / R2-04 / R2-05 original commit subjects do not resolve on this throwaway mirror (`git log --fixed-strings --grep` empty); they cannot be cited here.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
