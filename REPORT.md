# UXW2-1 — Single URL owner for review-queue `rq=` state

Baseline: `9c287fd540e13a02d762bd97f3550b4aea083c37` (branch `master`).

## RED evidence (before implementation)

`npx vitest run` on the two ported repro files + new real-router test — **8 failed / 1 passed (control)**:

`js/admin/hooks/__tests__/useWorkbenchFilters.rqDoubleWrite.test.tsx` (3 failed):
- `kind chip click from default: second setQueueState({index:0}) must not clobber kind` — queueState.kind was `all`, expected `assignment`
- `kind chip click at index 3: kind must survive the same-tick index reset` — kind clobbered to `all`
- `Clear filters button (onKindChange + onBandChange same tick) clears kind AND band` — band write clobbered the kind reset (`rq=assignment.all.0` survived)

`js/admin/hooks/__tests__/useWorkbenchFilters.scanTabMirror.test.tsx` (4 failed):
- `chip from default: URL must contain rq=assignment (no split-brain)` — URL was `''`
- `chip then Next: chip must stay active` — local reverted to `all.all.1`
- `chip when rq already present (index 3): kind sticks` — local `all.all.0`
- `Clear filters with both active: rq removed entirely` — URL `?rq=assignment.all.0`

`js/admin/pages/workbench/__tests__/ScanTabContent.reviewQueueUrl.test.tsx` (3 failed, real MemoryRouter + real `useWorkbenchFilters`):
- `chip click → aria-pressed=true AND rq=assignment.all.0; …` — `expected '' to contain 'rq=assignment.all.0'`
- `band + kind combine into rq=assignment.strong.0` — `expected '' to contain 'rq=assignment.strong.0'`
- `Clear filters removes rq and unpresses both chip groups` — `expected '' to contain 'rq=merge.strong.0'`

## GREEN evidence (after implementation)

- Full plugin frontend suite `npm test` (vitest run): **209 files passed, 2356 tests passed, 0 failed** (~297s).
- `npm run typecheck` (`tsc --noEmit -p tsconfig.type-check.json`): **clean**.
- `npm run lint`: **118 problems (117 errors, 1 warning)** — byte-identical count to baseline (verified via `git stash -u` + re-lint + `git stash pop`); all errors are in files untouched by this change. Zero new lint issues.
- Touched suites re-run individually: ReviewQueue.test.tsx / ReviewQueue.authExpired.test.tsx / ScanTabContent.* (3) / mediaFooterSinglePrimary.dom.test.tsx / WorkbenchPage.test.tsx / useWorkbenchFilters.* (4 files) — all pass.

## Files changed

- `js/admin/hooks/useWorkbenchFilters.ts` — `QUEUE_ACTION` enum + `QueueAction` union + `QUEUE_ACTION_HANDLERS` map + `reduceQueueAction`; `pendingQueueRef` write-through; `setQueueState` re-based on pending state; new `dispatchQueue`.
- `js/admin/pages/workbench/ScanTabContent.tsx` — deleted `queueIndex/queueKind/queueBand` useStates + URL→local mirror effect; reads `queueState` directly; four handlers → single `dispatchQueue` each.
- `js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx` — `handleFilterClick`/`handleBandClick` drop the extra `onIndexChange(0)`; new required `onClearFilters` prop; Clear-filters button uses it.
- Tests: ported repros (`useWorkbenchFilters.rqDoubleWrite.test.tsx`, `useWorkbenchFilters.scanTabMirror.test.tsx`), new `ScanTabContent.reviewQueueUrl.test.tsx`, `dispatchQueue` cases in `useWorkbenchFilters.test.tsx`, harness updates in `ReviewQueue.test.tsx` (5 sites), `ReviewQueue.authExpired.test.tsx`, `mediaFooterSinglePrimary.dom.test.tsx`, `WorkbenchPage.test.tsx`, `ScanTabContent.{nav03,controlPaneOrder}.test.tsx`.
- `docs/ux-maps/workbench-operator-loop.uxmap.json` (+ `.md` companion): `rq` added to `workbench-scan` url_params; new `z-review-queue` zone with states `default|filtered_empty|drained|error`.

## Canon satisfied

- DATA-14 (no dual writes): `useWorkbenchFilters.ts` single `writeQueueState`; ScanTabContent mirror deleted (`ScanTabContent.tsx:84-116`).
- REF-09 (derive, don't mirror): `ScanTabContent.tsx:217-222` reads `queueState.kind/band/index` directly.
- RLSE-06 (double-tap/timing): `pendingQueueRef` write-through (`useWorkbenchFilters.ts:166-172`); tests `rqDoubleWrite` (3 same-tick cases) + `two dispatchQueue calls in one tick both land`.
- TEST-19 (mock only non-domain seams): `ScanTabContent.reviewQueueUrl.test.tsx` uses real MemoryRouter + real `useWorkbenchFilters` + real `ReviewQueue`; only REST API + unrelated contexts mocked.
- RLSE-04 (undesigned state): split-brain "chip on / URL off" eliminated by construction (chip state derives from URL only).
- REF-02 (enum-keyed handler map): `QUEUE_ACTION_HANDLERS` (`useWorkbenchFilters.ts:55-63`), no switch.
- NAV-11 (deep link round-trips): test `deep link rq=merge.all.1 mounts with chip pressed and second merge card`.
- COG-03 / NAV-07 / INT-06: Clear filters now actually clears kind AND band in one write (`ReviewQueue.tsx` Clear-filters `onClick={onClearFilters}`; test `Clear filters removes rq and unpresses both chip groups`).
- A11Y-21: live region untouched (`.acx-review-queue__live` + lifecycle announce preserved; aria-pressed now truthful).

## Left undone

- e2e `tests/e2e/a11y/review-queue.spec.ts` chip-persistence assertion (DIAGNOSIS "tests to pin" (c)) — out of the 25-min budget; unit/integration coverage above pins the same contract.
- `clamp_index` action exists in the map for the ReviewQueue clamp effect path; the clamp effect still calls `onIndexChange` (single write, now merged against pending state) — semantically covered, not separately wired.

## Final HEAD

`a1eb942e30a2067beb16b8a07fa758f139692826`
