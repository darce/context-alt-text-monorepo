# UXW2-1 R2 — review-finding closure

Lane: close remaining R1-08 / R1-09 / R1-13 and R2-01..05 on the workbench `rq=` URL owner.
Canonical branch: `feature/uxw2-1`.
Baseline: latest `sync: mirror local feature/uxw2-1` commit on this throwaway mirror.

Commits are cited by subject line only. Subjects that do not resolve via
`git log --format=%H --fixed-strings --grep="<subject>"` on this mirror are
not citations.

Line numbers below were re-derived with `sed -n '<n>p' <file>` after the last
code commit on this lane.

## Closure table

| ID | Commit (subject) | Test | TEST-15 mutant killed |
| --- | --- | --- | --- |
| R2-02 | present: `pendingSearchWrites.ts:54` reconcile, `:122` retain, `useWorkbenchFilters.ts:118` last-instance unmount, `commitSearchParams` at `pendingSearchWrites.ts:95` | `useWorkbenchFilters.test.tsx` external-navigate + last-instance unmount + same-tick `useTabParam` | Revert reconcile to exact-match only → `expected '?rq=assignment.all.0&p=2' to contain 'rq=merge.all.0'` (`useWorkbenchFilters.test.tsx:307`). Unmount-clear missing → `expected { rq: … } to deeply equal {}` (`:347`). Writer not merging pending → `expected '?tab=scan' to contain 'rq=assignment.all.0'` (`:594`). |
| R2-05 | present: `ScanTabContent.reviewQueueUrl.test.tsx` reducer-path pins | `ScanTabContent.reviewQueueUrl.test.tsx` (`beforeEach(resetPendingSearchWritesForTests)`; double-Next; Prev-under-strong; Strong at index 1; full `rq=merge.strong.0`) | `dispatchQueue({type:SET_INDEX,index:queueState.index+delta})` → `expected '?rq=all.all.1' to contain 'rq=all.all.2'` (`:362`). SET_BAND-skips-index-reset → `expected '?rq=assignment.strong.1' to contain 'rq=assignment.strong.0'` (`:376`). STEP_INDEX-drops-band → `expected '?rq=assignment.all.0' to contain 'rq=assignment.strong.0'` (`:394`). |
| R2-04 | present: `ReviewQueue.test.tsx` chip spies on `reduceQueueAction` | `ReviewQueue.test.tsx` chip spies on `reduceQueueAction` | Harness not reducing → `expected false to be true` (`ReviewQueue.test.tsx:663` SET_KIND; `:707` SET_BAND). |
| R2-03 / R1-13 | `docs(uxw2-1): UXW2-1-R1-13 tick shipped review-filter slices` | `docs/tasks/uxw2/UXW2-1-workbench-review-filters-task-plan.md` | Slice 1/2 ticked; filename `doubleWrite` → `rqDoubleWrite`; no finding-status list. |
| R2-01 / R1-08 / R1-09 | this report | this file | Subject-line citations only; no 40-hex strings; TEST-08 ×3 re-run at this lane's code HEAD (see GREEN evidence). |

finding status is live in the handoff DB; query it, do not read it here.

## GREEN evidence (verbatim, this worktree)

`npx tsc --noEmit --project tsconfig.type-check.json`: clean.

Three full-suite runs at this lane's code HEAD (`npx vitest run` from `apps/prototype-wp-alt-context`):

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

## Flake evidence (R1-08 / TEST-08)

Runs 1–3: **no FAIL lines**. Untouched-file flake: none on 3 consecutive full runs.

## Files changed (R2 production, still on this tree)

- `pendingSearchWrites.ts:54` reconcile (snapshot+abandon); `:95` `commitSearchParams`; `:122` last-instance unmount clear.
- `useTabParam.ts:18` / `useOverlayParam.ts:17` / `usePanesParam.ts:20` / `WorkbenchNavContext.tsx:50` — writers merge pending.
- `ReviewQueue.tsx` / `ScanTabContent.tsx` — dropped dead `onIndexChange` / `handleIndexChange`.
- Tests as in the table. Harness Parents reduce through `reduceQueueAction`.
- `docs/tasks/uxw2/UXW2-1-workbench-review-filters-task-plan.md`.

R5 pin work (tests + comment) is recorded in `docs/tasks/uxw2/UXW2-1-r5-fix-report.md`.

## Decisions

- Shared module overlay kept (R1-01). Reconcile abandons when URL `rq`/`p` is neither the pre-write snapshot nor the pending value. Null snapshot + empty dest is abandon (choice A; see r5-fix-report).
- Non-overlay writers merge pending instead of last-write-winning.
- Chip negative pin spies `reduceQueueAction` (no SET_INDEX), not a dead prop.

## Undone

- e2e chip-persistence still not added (original slice leftover).
- `npm run lint` not re-run on this lane; last recorded count was `✖ 119 problems (118 errors, 1 warning)` with one pre-existing `@typescript-eslint/consistent-type-definitions` on `PendingSearchWrites`.
- `usePanesParam.test.tsx` still has no module-buffer merge pin (same-tick pin remains in `useWorkbenchFilters.test.tsx`; R5 pinned overlay / tab / `setAdvancedOpen` in their own files).
- Original R2-02 / R2-04 / R2-05 commit subjects do not resolve on this throwaway mirror; production is cited by file:line above instead.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
