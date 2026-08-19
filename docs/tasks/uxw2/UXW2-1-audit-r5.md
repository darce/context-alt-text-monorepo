# UXW2-1 r5 board audit — current tree

Read-only re-check of listed findings against this throwaway mirror.
Constructs located by name, not by stale finding line numbers. Every
`file:line` below was re-derived with `sed -n '<N>p' <file>` immediately
before this document was written. No test suite was executed.

---

### UXW2-1-R1-09 — FIXED

**Claim:** The original report’s RED tally (`8 failed / 1 passed`) contradicted the per-file breakdown, `Final HEAD` named a lane SHA, a REF-09 cite pointed at `ScanTabContent.tsx:217-222` which did not hold the `queueState` reads, VM commits carried Co-authored-by trailers, and `REPORT.md` sat at the repo root.

**Evidence:** `REPORT.md` is absent at the repo root (`ls: cannot access 'REPORT.md': No such file or directory`). The living report is `docs/tasks/uxw2/UXW2-1-report.md`. That file has no `8 failed`, no scratch-dir path, and no 40-hex string. Line 80 is `Final HEAD: recorded by the integrator in the canonical worktree after transplant.` Line 23 states TEST-08 ×3 was re-run at this lane’s code HEAD. `ScanTabContent.tsx` currently reads `queueState` at 48 (`const { queueState, dispatchQueue } = useWorkbenchFilters();`) and passes `queueState.index` / `kind` / `band` at 216 / 219 / 221; the living report does not cite `ScanTabContent.tsx:217-222`.

**Verdict rationale:** Every hygiene assertion in the finding is now false of the current tree. The report was relocated, the contradictory RED headline is gone, the forbidden lane SHA is gone, and the stale REF-09 cite is gone. Co-authored-by trailers are not present in the living report; the original finding already recorded they were stripped at port.

---

### UXW2-1-R2-02 — FIXED

**Claim:** `pendingSearchWrites` was cleared only on exact URL match, so a lost `rq` write was silently re-applied by the next unrelated `commitSearchParams`; the buffer survived unmount / route change; non-overlay writers last-write-won against the render snapshot.

**Evidence:** Reconcile, buffer, and `commitSearchParams` now live in `pendingSearchWrites.ts`. `reconcilePendingSearchWrites` (54) clears on URL==pending (58) **or** on `rqSnapshot == null || urlRq !== rqSnapshot` (61–67). The same pair exists for `p` (70–81). Last-instance unmount is `retainWorkbenchFilterInstance` (122–129): `if (workbenchFilterInstanceCount <= 0)` then `clearPendingSearchWrites()`. `useWorkbenchFilters.ts:118` is `useEffect(() => retainWorkbenchFilterInstance(), []);`. Non-overlay writers call `commitSearchParams` from the shared module: `useTabParam.ts:18`, `useOverlayParam.ts:17`, `usePanesParam.ts:20`, `WorkbenchNavContext.tsx:50`. Tests: external-nav not resurrected (`useWorkbenchFilters.test.tsx:269`, assert 307 `toContain('rq=merge.all.0')`); last-instance unmount (311, pre-unmount peek 341, assert 347 `toEqual({})`); same-tick `useTabParam` merge (562, assert 594 `toContain('rq=assignment.all.0')`).

**Verdict rationale:** Exact-match-only clear is gone. A URL that is neither the pending value nor the pre-write snapshot (including a null snapshot) abandons the buffer, so `applyPendingSearchWrites` (35) cannot resurrect it on the next unrelated commit. Last-instance unmount clears. Every named writer merges pending through `commitSearchParams` (95–104). Kill-power from the assertions: revert reconcile to exact-match-only and `:307` expects `rq=merge.all.0` after `setCurrentPage` and would see the pending `assignment` instead; drop the unmount clear and `:347` would still see `{ rq: … }`; replace a writer with raw `setSearchParams` and `:594` would miss `rq=assignment.all.0`.

---

### UXW2-1-R3-02 — FIXED

**Claim:** `docs/tasks/uxw2/UXW2-1-report.md` contradicted itself on whether TEST-08 ×3 ran at HEAD, and cited forbidden lane-scratch paths.

**Evidence:** Current L23: `Subject-line citations only; no 40-hex strings; TEST-08 ×3 re-run at this lane's code HEAD (see GREEN evidence).` Current L30: `Three full-suite runs at this lane's code HEAD (\`npx vitest run\` from \`apps/prototype-wp-alt-context\`):`. L80 is the integrator `Final HEAD` formula. `grep` of the file for scratch-dir prefixes, `8 failed`, and 40-hex: no matches.

**Verdict rationale:** The L17-vs-L38 contradiction the finding named is gone; both remaining TEST-08 sentences now say the same thing (runs at this lane’s code HEAD). No scratch-dir path remains in this file.

---

### UXW2-1-R3-03 — FIXED

**Claim:** Three of eight TEST-15 RED citations in the report (and in two fix-commit bodies) did not resolve to the named assertion: `ReviewQueue.test.tsx:676` was a harness constructor, and `reviewQueueUrl.test.tsx:377` was not the STEP_INDEX pin.

**Evidence:** Living report table (`docs/tasks/uxw2/UXW2-1-report.md:20`) cites `ReviewQueue.test.tsx:663` SET_KIND and `:707` SET_BAND. Those lines are now:

```
663:    expect(reduceSpy.mock.calls.some(([, action]) => action.type === QUEUE_ACTION.SET_KIND)).toBe(true);
707:    expect(reduceSpy.mock.calls.some(([, action]) => action.type === QUEUE_ACTION.SET_BAND)).toBe(true);
```

R2-05 cites (`report:19`) `ScanTabContent.reviewQueueUrl.test.tsx:362` / `:376` / `:394`:

```
362:      expect(locSearch()).toContain('rq=all.all.2');
376:      expect(locSearch()).toContain('rq=assignment.strong.0');
394:      expect(locSearch()).toContain('rq=assignment.strong.0');
```

`ReviewQueue.test.tsx:676` is no longer a constructor used as a RED cite; `:646` / `:690` are the `makeQueueHarness` lines.

**Verdict rationale:** Every TEST-15 file:line currently stamped in the living closure table resolves to the named assertion. Historical commit-message bodies were not used to form this verdict.

---

### UXW2-1-R3-05 — FIXED

**Claim:** Last-instance unmount was pinned only by a single-instance test, so dropping `if (workbenchFilterInstanceCount <= 0)` (clear on every unmount) left the suite green; the `pSnapshot` abandon branch had zero coverage.

**Evidence:** Guard is `pendingSearchWrites.ts:126` `if (workbenchFilterInstanceCount <= 0)`. Production still mounts two instances: `ScanTabContent.tsx:48` and `WorkbenchMediaContext.tsx:61`. Dual-instance test `useWorkbenchFilters.test.tsx:350` `unmounting one of two mounted instances keeps the pending buffer alive (UXW2-1-R3-05)`: after `fill`, `:390` `peek().rq` is defined; after `drop-one`, `:394` `peek().rq` is still defined; after full unmount, `:396` `toEqual({})`. `p` abandon coverage: hook-level non-null snapshot `useWorkbenchFilters.test.tsx:447` (`initialEntries={['/?p=1']}`, assert `:479` `peek().p` undefined) plus the later null-snapshot pins under R4-01/R5-01 (`:399`, `:727`).

**Verdict rationale:** Dropping the `<= 0` guard so every unmount clears would make `:394` go red (`expected undefined to be defined`) while one of two instances is still mounted. Deleting the `p` abandon arm would leave pending `p=2` after the `:447` race (URL `p=3` matches neither pending nor snapshot `'1'`), so `:479` `toBeUndefined()` would receive `2`. Both requested tests exist and have kill power against the mutants the finding named.

---

### UXW2-1-R3-06 — FIXED

**Claim:** Abandon keyed on `urlRq !== rqSnapshot` was a no-op when the pre-write snapshot was null and the destination also omitted `rq` (the common overlay-href shape); pending was retained and re-applied on the next unrelated commit. Same hole for `p`. The shipped test navigated to `?rq=merge.all.0` and took the working branch.

**Evidence:** Current abandon disjuncts are `pendingSearchWrites.ts:62` `pendingSearchWrites.rqSnapshot == null ||` and `:76` `pendingSearchWrites.pSnapshot == null ||`. Overlay href still omits `rq`/`p`: `ToWorkbenchOptions` (`appLinks.ts:78–86`) has only status/tab/advanced/panel/panes; `buildWorkbenchOverlayHref` (`:184–187`) forwards `{ tab, panel }` only. `WorkbenchPage.tsx:48` still mounts `SyncStatusIndicator`; `SyncStatusIndicator.tsx:223–224` still call `buildWorkbenchOverlayHref`. Tests that take the null-snapshot/null-dest path: `useWorkbenchFilters.test.tsx:483` (assert `:513` `peek().rq` undefined) and `:516` (assert `:559` `loc` `not.toContain('rq=')`), plus direct `queuePendingQueueState(..., null)` at `:750` (assert `:753`).

**Verdict rationale:** Null snapshot + empty dest is now abandon, for both `rq` and `p`. Mutant: drop `== null ||` and keep only `url !== snapshot`. On `:483` / `:750`, `urlRq` and `rqSnapshot` are both null, so `null !== null` is false and pending is retained; `:513` / `:753` `toBeUndefined()` would receive the assignment queue. On `:516`, the next `handleSearchChange` would re-apply it and `:559` would see `rq=` in `loc.search`.

---

### UXW2-1-R3-07 — PARTIAL

**Claim:** R2-04’s negative chip pins spy `reduceQueueAction` as called by the harness’s own dispatch, not by `ScanTabContent`; they only excluded `SET_INDEX`, so a chip handler that also fired `onClampIndex` stayed green; the report’s TEST-15 mutant mutated the test, not production.

**Evidence:** `useQueueHarnessState` still dispatches locally: `ReviewQueue.test.tsx:198–199` `setQueueState((prev) => workbenchFilters.reduceQueueAction(prev, action));`. Kind-chip test `:625` still `vi.spyOn(workbenchFilters, 'reduceQueueAction')` (`:645`) and `makeQueueHarness(...)` (`:646`). Production `ScanTabContent.tsx:107–110` is `dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: nextKind })` and is not the subject of these two tests. What did change: `:661–662` `expect(onClampIndex).not.toHaveBeenCalled()` / `onStepIndex`; `:663–664` keep the paired `.some(SET_KIND).toBe(true)` and `.every(SET_KIND).toBe(true)` (band twin `:707–708`). `ReviewQueue.tsx:750–758` `handleFilterClick` still calls only `onKindChange`.

**Verdict rationale:** Survives: the chip pins still observe the harness reducer, not `ScanTabContent`’s `dispatchQueue`; a TEST-15 “harness not reducing” mutant still edits test-side `reduceQueueAction` usage. Fixed: the SET_INDEX-only hole. A chip handler that additionally called `onClampIndex` now fails `:661` and also fails `:664` (CLAMP_INDEX would make `.every(SET_KIND)` false). The `.some()` vacuity guard the finding asked to keep is present.

---

### UXW2-1-R3-08 — FIXED

**Claim:** Exporting `commitSearchParams` from the feature hook inverted layers: `useTabParam` / `useOverlayParam` / `usePanesParam` imported `useWorkbenchFilters.ts` and pulled in the review-queue reducer, `serializeQueueState`, and the module buffer; three previously isolated tests had to `importOriginal`-spread the real module.

**Evidence:** Neutral module `pendingSearchWrites.ts` owns the buffer, `commitSearchParams` (95), and reconcile. Generic writers import that module, not the feature hook: `useTabParam.ts:4`, `useOverlayParam.ts:4`, `usePanesParam.ts:5`, `WorkbenchNavContext.tsx:6`. `pendingSearchWrites.ts:2` imports `serializeQueueState` from `workbenchQueueUrl`, not `reduceQueueAction`. `useWorkbenchFilters.ts` imports the shared module (lines 4–11) and does not re-export `commitSearchParams`. The three named tests are full replacements again, not `importOriginal`: `WorkbenchPage.test.tsx:97–99` `vi.mock('...useWorkbenchFilters', () => ({ useWorkbenchFilters: vi.fn() }))`; `ScanTabContent.nav03.test.tsx:46–51` returns a stub `{ queueState, dispatchQueue }`.

**Verdict rationale:** The FIX (move `commitSearchParams` and the pending buffer into a neutral module both layers import) is in the tree. Generic URL hooks no longer import `useWorkbenchFilters` and no longer pull the reducer. `serializeQueueState` remains a dependency of the buffer module because applying a pending `rq` must serialise it; that is the shared write-through, not a layering inversion through the feature hook. The `importOriginal` cost is gone.

---

### UXW2-1-R3-09 — FIXED

**Claim:** `seedPendingSearchWritesForTests` was a test-only export that wrote arbitrary state into the production module buffer, existed so the unmount test could assert without a URL land, and let any production importer plant a queue state.

**Evidence:** `grep` of `apps/prototype-wp-alt-context/js` for `seedPendingSearchWritesForTests`: no matches. Last-instance unmount (`useWorkbenchFilters.test.tsx:311`) fills via `dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' })` plus a raw `setSearchParams`, then peeks (`:341`). Remaining test helpers on the production module are `resetPendingSearchWritesForTests` (`pendingSearchWrites.ts:25`) and `peekPendingSearchWritesForTests` (`:31`). `queuePendingPage` / `queuePendingQueueState` are the production queue APIs, not a seeder.

**Verdict rationale:** The seeder is deleted. The unmount test is driven through a real commit, which is one of the two fixes the finding allowed. `peek`/`reset` remain as TEST-07 isolation/observe helpers and cannot plant a queue state. The “any production importer can plant via the seeder” hole is gone.

---

### UXW2-1-R3-10 — PARTIAL

**Claim:** `usePanesParam.test.tsx` (covering panes and overlay) had no `beforeEach(resetPendingSearchWritesForTests)`, so a dirty module buffer from an earlier file in the same worker could leak `rq`/`p` into these assertions (TEST-07).

**Evidence:** Reset is present: `usePanesParam.test.tsx:8` imports `resetPendingSearchWritesForTests`; `:27–29` `beforeEach(() => { resetPendingSearchWritesForTests(); })`. Setter assertions still do not inspect `rq`/`p`: `:66` `toContain('panes=library-collapsed')`, `:72` `not.toContain('panes=')`. Sibling-preservation asserts are also `toContain` on tab/panel/status/panes.

**Verdict rationale:** Fixed: the missing `beforeEach` is in the file, so this file starts with a clean buffer. Survives: no assertion would go red if the `beforeEach` were deleted. `commitSearchParams` would merge a leaked `rq` into `search`, but every check is `toContain` / `not.toContain('panes=')`, which still pass with an extra `rq=` param. The isolation call is present; its kill power is not.

---

### UXW2-1-R4-01 — FIXED

**Claim:** The r3 widen of both abandon branches to `snapshot == null || url !== snapshot` was pinned only on the `rq` twin. Reverting **only** the `p` condition to `pSnapshot !== undefined && urlP !== pSnapshot` left the FE suite green. The only `p` test mounted at `/?p=1`, so `pSnapshot` was `'1'` and the old predicate still abandoned. The null-snapshot / null-destination hole is production-reachable via `buildWorkbenchOverlayHref` (no `p`), blast radius `p>=2` because `pageMatches(null, 1)` treats omitted `p` as landed.

**Evidence:** `p` abandon is `pendingSearchWrites.ts:75–81` (`pSnapshot == null || urlP !== pSnapshot`). `pageMatches` is `:51–52` `urlP === String(page) || (page === 1 && urlP === null)`. Overlay href still omits `p` (`appLinks.ts:184–187`). Direct pin that takes the named hole: `useWorkbenchFilters.test.tsx:727` `UXW2-1-R5-01: p buffer snapshotted from a bare URL is dropped when dest still has no p and pending page is > 1` — `queuePendingPage(2, null)` then `reconcilePendingSearchWrites(new URLSearchParams(''))`, assert `:733` `peek().p` `toBeUndefined()`. Hook-level twin from `'/'`: `:399` (assert `:439`). Non-null snapshot sibling `:717`. In-flight keep while URL still equals snapshot `:745`.

**Verdict rationale:** The named mutant (`pSnapshot == null ||` → `pSnapshot !== undefined &&`) on `:76` would keep pending `p=2` for a null snapshot and empty dest: `pageMatches(null, 2)` is false, then `null !== undefined && null !== null` is false, so the delete at `:80` does not run. `:733` (and `:439`) would then receive `2` instead of `undefined`. That is the exact TEST-15 the finding said was missing.

---

### UXW2-1-R4-02 — FIXED

**Claim:** The rewritten last-instance unmount case was individually vacuous: `dispatchQueue(SET_KIND)` landed `rq` in the URL, reconcile deleted the buffer inside `act()`, and the trailing `expect(peek()).toEqual({})` passed whether or not the unmount clear ran. (Correction: the `<= 0` guard itself was already pinned by the dual-instance test.)

**Evidence:** Last-instance test `useWorkbenchFilters.test.tsx:311`. Setup starts at `'/?rq=merge.all.0'`, then `fill` dispatches assignment **and** overwrites the URL to `rq=merge.all.0`. After `act()`, `:341–345` `expect(peekPendingSearchWritesForTests().rq).toEqual({ kind: 'assignment', band: 'all', index: 0 })` — buffer still live. Then `unmount()` and `:347` `toEqual({})`. Dual-instance pin of the guard remains at `:350` / `:394`. Guard line: `pendingSearchWrites.ts:126`.

**Verdict rationale:** The load-bearing pre-unmount peek is back. Reconcile cannot have emptied the buffer inside `act()`: URL is `merge.all.0`, pending is `assignment`, snapshot is `merge.all.0`, so the keep-while-in-flight path retains pending and `:341` would fail if it had been cleared. If the unmount clear is missing, `:347` then fails with `{ rq: … }` vs `{}`. The dual-instance test still kills “clear on every unmount”. The individually-vacuous last-instance case the finding named is gone.

---

### UXW2-1-R4-03 — FIXED

**Claim:** After later test insertions, the living report’s R2-02 row cited `useWorkbenchFilters.test.tsx:301` (then `});`) and `:347` (then a `<Route>`), while the real assertions had moved; same defect class as R3-03.

**Evidence:** Current R2-02 row is `docs/tasks/uxw2/UXW2-1-report.md:18`. It cites `:307` (reconcile), `:347` (unmount), `:594` (same-tick `useTabParam`). Re-derived:

```
307:    expect(screen.getByTestId('loc').textContent).toContain('rq=merge.all.0');
347:    expect(peekPendingSearchWritesForTests()).toEqual({});
594:    expect(screen.getByTestId('loc').textContent).toContain('rq=assignment.all.0');
```

R2-04/R2-05 cites still match (`ReviewQueue.test.tsx:663` / `:707`; `reviewQueueUrl.test.tsx:362` / `:376` / `:394`) as under R3-03.

**Verdict rationale:** The stale `:301` / misplaced `:347` (as useTabParam) cites are gone. Every remaining closure-table file:line in that row resolves to the named assertion at this tree.

---

### UXW2-1-R4-04 — FIXED

**Claim:** Every R3-06 abandon/resurrect assertion was against `peekPendingSearchWritesForTests()` or raw `loc.search`, never against chip `aria-pressed` / the polite N-of-M live region; no r3 test mounted `ReviewQueue` after an abandon. A regression that kept the URL clean while desyncing chip pressed-state would pass.

**Evidence:** New case `ReviewQueue.test.tsx:713` `after an abandoned rq write, chip aria-pressed matches the URL (UXW2-1-R4-04)` mounts `ReviewQueue` with `useWorkbenchFilters` `dispatchQueue` (not the harness). After overlay-abandon then unrelated search, `:790–793`:

```
    const assignmentPressed =
      screen.getByRole('button', { name: 'Close matches' }).getAttribute('aria-pressed') === 'true';
    expect(loc.includes('rq=assignment')).toBe(assignmentPressed);
    expect(assignmentPressed).toBe(false);
```

Production chip `aria-pressed` is `ReviewQueue.tsx:989` (`filter === REVIEW_QUEUE_FILTER.ASSIGNMENT`). Overlay href still omits `rq`/`p` (`appLinks.ts:78–86`, `:184–187`). Live region `ReviewQueue.tsx:1029` `aria-live="polite"` is not asserted in this case.

**Verdict rationale:** The named user-visible hole is pinned. URL-clean / chip-pressed desync makes `:792` red (`false` vs `true`). Resurrected `rq=assignment` with chip pressed makes `:793` red (`true` vs `false`). Hook-level R3-06 tests still peek/`loc.search`; that is no longer the only layer. The N-of-M live region is still unasserted after abandon (see Undone); it was the secondary surface, not the regression the finding said would pass.

---

## Tally
FIXED: 12 | PARTIAL: 2 | OPEN: 0 | UNVERIFIABLE: 0

## Undone

- No mutant was executed; every kill-power claim above is from reading the assertion and the line the named mutant would change.
- Historical fix-commit message bodies (R3-03’s second half) were not inspected; git log is not evidence for this audit.
- `docs/tasks/uxw2/UXW2-1-r3-fix-report.md` still carries r3-era line cites and an “R3-08 not done” note that the current tree has outgrown; it was not in the finding list and was not rewritten here.
- R3-07 still does not assert `ScanTabContent`’s `dispatchQueue` path for chip clicks.
- R3-10’s `beforeEach` reset has no assertion that fails if the reset is removed.
- R4-04 does not assert the N-of-M `aria-live` region after abandon.
- `peekPendingSearchWritesForTests` / `resetPendingSearchWritesForTests` still ship from the production `pendingSearchWrites.ts` module (allowed leftover of R3-09 option 1).
