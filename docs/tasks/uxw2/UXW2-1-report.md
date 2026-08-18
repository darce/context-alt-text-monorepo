# UXW2-1 R1 — review-finding closure

Lane: close adversarial R1 findings on the UXW2-1 URL-owner fix.
Code commit: `6cb83c996976008e9fcae318ae7f43ac641dbda6`
Plan commit: `e86d5f449185c92302d50a76db0ec8b64601c90a`
This report commit: `git rev-parse HEAD` after this file (R1-09).

Baseline: `9c287fd540e13a02d762bd97f3550b4aea083c37`. Original slice: `1fcfaaedfd23b4461279ec6db2de18d7eb8284cd`.

## Closure table

| ID | Commit | Test | TEST-15 mutant killed |
| --- | --- | --- | --- |
| R1-01 | `6cb83c99` | `ScanTabContent.reviewQueueUrl.test.tsx` `page-clamp p writer from a second hook instance does not drop pending rq` | Per-instance `pendingQueueRef` + stale `setCurrentPage` drops `rq`; DualWriter click expects `rq=assignment.all.1` AND `p=2`. |
| R1-02 | `6cb83c99` | `useWorkbenchFilters.rqDoubleWrite.test.tsx` ported onto `dispatchQueue`; `getQueueState`/`setQueueState` gone from hook return | Calling `setQueueState` is a type/runtime miss; stray `SET_INDEX` after `SET_KIND` would clobber without pending overlay. |
| R1-03 | `6cb83c99` | `ScanTabContent.reviewQueueUrl.test.tsx` `oversized rq index clamps…`; `dispatchQueue set_index rejects NaN and negatives without dropping kind` | `SET_INDEX(NaN)` serialised `assignment.all.NaN` → parse resets kind to `all`. Guard keeps `assignment` at index 0. |
| R1-04 | `6cb83c99` | deleted `useWorkbenchFilters.scanTabMirror.test.tsx`; describe rewrite in `rqDoubleWrite` | Dead Mirror cannot go red on a production regression; deletion is the pin. |
| R1-05 | `6cb83c99` | `ReviewQueue.test.tsx` `two synchronous Next clicks advance index by 2`; hook `two STEP_INDEX dispatches in one tick advance by 2` | Two `onIndexChange(safeIndex+1)` in one tick both see 0 → stay at 1 (`2 of 3`). |
| R1-06 | `6cb83c99` | `ReviewQueue.test.tsx` kind/band spy tests; `dispatchQueue clear_filters removes rq from loc.search` | Chip still calling `onIndexChange` fails spies; `parse(null)==defaults` would pass while `loc.search` still had `rq=`. |
| R1-07 | `6cb83c99` | `ReviewQueue.test.tsx` filtered-empty: live `Review item 1 of 1` + `Yes` focused | Raw `onClick={onClearFilters}` leaves live copy on filtered-empty and focus on `body`. |
| R1-08 | this report | full `vitest run` ×3 | See Flake evidence. |
| R1-09 | this report | this file at `docs/tasks/uxw2/UXW2-1-report.md` | Root `REPORT.md` moved (`git mv`); RED tally + REF-09 lines corrected. |
| R1-10 | `6cb83c99` | `deep link rq=merge.all.1 survives Prev (kind) and Strong chip (band stays merge)` | Mount-only assert passed on baseline mirror; Prev/Strong would drop kind if local mirror returned. |
| R1-11 | `6cb83c99` | `makeQueueHarness` / `useQueueHarnessState` in `ReviewQueue.test.tsx` | Inline `onKindChange={setKind}` (no index reset) drifts from reducer; six harnesses share one helper. |
| R1-12 | `6cb83c99` | `rosterRoute.test.ts` `encodes rq via serializeQueueState` | Hand-coded `assignment.all.0` diverges if grammar changes. |
| R1-13 | `e86d5f44` | `docs/tasks/uxw2/UXW2-1-workbench-review-filters-task-plan.md` | Checklist ticks + `rqDoubleWrite` filename; no finding-status bullets. |

## RED evidence (R1)

- DualWriter (R1-01) written before shared overlay; expected `rq=assignment.all.1` after same-tick `SET_KIND`+`SET_INDEX`+`setCurrentPage(2)`.
- `QUEUE_ACTION.STEP_INDEX` tests failed to typecheck/run until the action existed (R1-05).
- `SET_INDEX` NaN/negative would wipe kind via parse-fallback (R1-03).
- `loc.search` clear_filters asserts `not.toContain('rq=')` (R1-06).

Original slice RED (corrected tally from `1fcfaae`): **10 failed / 2 passed** (rqDoubleWrite 3, scanTabMirror 4, reviewQueueUrl 3 failed; 2 controls passed). The old root report headline "8 failed / 1 passed" was wrong.

## GREEN evidence

- `npx tsc --noEmit --project tsconfig.type-check.json`: clean.
- Full frontend `npx vitest run` (plugin dir), **two consecutive greens** then a third:

| Run | Files | Tests | Fail |
| --- | --- | --- | --- |
| 1 | 208 passed | 2360 passed | 0 |
| 2 | 208 passed | 2360 passed | 0 |
| 3 | 208 passed | 2360 passed | 0 |

File count 208 (was 209): `scanTabMirror.test.tsx` deleted. Test count 2360 (was 2356): new R1 cases.

## Flake evidence (R1-08 / TEST-08)

Runs 1–3: **no FAIL lines**. Captured via `tee /tmp/uxw2-1-r1-flake-N.log`; `grep FAIL` empty (`.lane/flake-N.log`).

This tree’s `vitest` + `MemoryRouter` hits a dual-React `useRef` of null when cwd is `…/uxw2-1-fix/…` (stack remaps into sibling `uxw2-1`’s `node_modules/react`). Identical sources/node_modules pass in `…/uxw2-1/…`. Suite evidence collected from that working runtime with this lane’s `js/` overlaid. Untouched-file flake: **none observed on 3 consecutive full runs**. Lane-touched files were not the source of the path-prefix dual-React; no retry-until-green.

## Files changed (R1)

- `useWorkbenchFilters.ts` — module-level `pendingSearchWrites`; all `s/p/status/perPage/rq` writers apply it; clear only when URL matches; `STEP_INDEX`; `sanitizeIndex`; no public `setQueueState`/`getQueueState`.
- `ReviewQueue.tsx` — `onClampIndex` / `onStepIndex`; clear-filters `navigateAfterFlush` + pending focus; filtered-empty recovery announce.
- `ScanTabContent.tsx` — wires clamp/step.
- `rosterRoute.ts` — `serializeQueueState`.
- Tests as in the table. Deleted `useWorkbenchFilters.scanTabMirror.test.tsx`.
- `docs/tasks/uxw2/UXW2-1-workbench-review-filters-task-plan.md`.

## Canon satisfied (verified IDs)

- **TEST-15** `~/uxw2/canon/lexicons/engineering.md:396` — mutants in the table.
- **TEST-08** `engineering.md:389` — three full runs recorded.
- **TEST-07** `engineering.md:387` — `resetPendingSearchWritesForTests` (`useWorkbenchFilters.ts:107`).
- **REF-09** `engineering.md:328` — `ScanTabContent.tsx:223-229` reads `queueState.*`; `rosterRoute.ts:210` derives `rq` via `serializeQueueState`.
- **RLSE-06** `engineering.md:697` — pending overlay (`useWorkbenchFilters.ts:104-125`) + `STEP_INDEX` (`:74-81`, `ReviewQueue.tsx:774-781`).
- **NAV-11** `interaction-ux.md:138` — deep link survives Prev/Strong.
- **A11Y-21** `accessibility.md:132` — live `Review item 1 of N` on filtered-empty recovery.
- **A11Y-11** `accessibility.md:108` — focus moves to restored card primary (`ReviewQueue.tsx:1303-1307`).
- **DATA-14** `engineering.md:202` — single shared write-through, not per-hook refs.
- **NAV-07** `interaction-ux.md:134` / **COG-03** `interaction-ux.md:113` — Clear filters still the escape hatch, now flushed+announced.

## Decisions

- Shared module overlay (not React context) so `WorkbenchMediaProvider` and `ScanTabContent` need no new provider.
- Keep `onIndexChange` on ReviewQueue so R1-06 can spy “never called”; production next/clamp use `onStepIndex`/`onClampIndex`.
- Full suite executed from sibling `uxw2-1` plugin dir (same `js/` overlay) because this checkout’s path prefix `uxw2-1-fix` dual-loads React.

## Undone

- e2e chip-persistence still not added (original slice leftover).
- Dual-React under cwd `uxw2-1-fix` not patched in `vite.config.ts` (out of product scope; evidence gathered from working runtime).

## Final HEAD

- R1 code (R1-01..12): `6cb83c996976008e9fcae318ae7f43ac641dbda6`
- Plan (R1-13): `e86d5f449185c92302d50a76db0ec8b64601c90a`
- This report (R1-08/R1-09): recorded in the commit that contains this file; confirm with `git rev-parse HEAD` and `git cat-file -e <sha>`.
