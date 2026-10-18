# FEBT-1 W1 errors lane — verification evidence

Verify-only pass on `fix/febt-1-w1-errors`. No files under `js/`, `src/`, or tests were edited. Commands were run from the repo root in the order below. Each fenced block is the raw stdout+stderr captured in this pass (not reconstructed, not copied from a prior evidence file).

## Command 1

Command:

```
cd apps/prototype-wp-alt-context && npm ci --silent ; echo "EXIT=$?"
```

Raw output:

```
(node:2348191) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
EXIT=0
```

EXIT=0

## Command 2

Command:

```
cd apps/prototype-wp-alt-context && npm run typecheck ; echo "EXIT=$?"
```

`typecheck` is `tsc --noEmit --project tsconfig.type-check.json`.
tsc itself printed no diagnostic lines (empty type-error stream). The only stdout is the npm script banner plus the exit echo.

Raw output:

```

> prototype-wp-alt-context@0.0.4 typecheck
> tsc --noEmit --project tsconfig.type-check.json

EXIT=0
```

EXIT=0

## Command 3

Command:

```
cd apps/prototype-wp-alt-context && npx vitest run js/admin ; echo "EXIT=$?"
```

No `FAIL` lines and no vitest error blocks were present in this output. The full captured stream follows.

Raw output:

```
(node:2354956) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:2354978) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)

 RUN  v4.1.5 /home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context

(node:2355108) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > navigates with prev/next without changing index on accept (PR-54 live-queue semantics)
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > focuses next card primary action after accept (authoritative advance-focus gate)
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > focuses empty-state anchor when the queue drains
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > fires existing accept mutation and invalidates projection keys
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > fires reject mutation after hold window
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > BR-15: accept A, next to B (flush), accept B → 2 POSTs order preserved; held card disabled only
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > uses the shared drain message for empty state and drain announcement
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > UI-04: drain announcement uses error copy when top-unlabeled failed
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > R7-06: queue header decrements after accepting names through ReviewQueue
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > R7-06: queue header decrements after accepting names through ReviewQueue
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > REV4-02: queue Retry announces in-flight busy then distinct retry-failed copy
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > Slice 5 multi-select bulk + matrix M1 surface > default-empty selection tray; Select toggles; PR-38 Accept N for label; zero bulk-accept
An update to ReviewQueueHarness2 inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > Slice 5 multi-select bulk + matrix M1 surface > default-empty selection tray; Select toggles; PR-38 Accept N for label; zero bulk-accept
A component suspended inside an `act` scope, but the `act` call was not awaited. When testing React components that depend on asynchronous data, you must await the result:

await act(() => ...)
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > Slice 5 multi-select bulk + matrix M1 surface > DUX-W2R2-RV-01: Retry after partial fail does not commit a later-selected gated card
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > Slice 5 multi-select bulk + matrix M1 surface > DUX-W2R2-RV-05: Retry onClick is a no-op while stored-face gated and reason stays resolvable when tray collapses
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > Slice 5 multi-select bulk + matrix M1 surface > DUX-W2R2-RV-05: Retry onClick is a no-op while stored-face gated and reason stays resolvable when tray collapses
An update to NameFaceControl inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > names the reviewed face from the lightbox for the whole same-group run
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > UXW2-6 slice 3 group accept of close matches > offers the close-match count before any write and confirms through the bulk sequencer
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > UXW2-6 slice 3 group accept of close matches > offers the close-match count before any write and confirms through the bulk sequencer
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > UXW2-6 slice 3 group accept of close matches > DUX-W2R2-RV-04: Close Match Confirm does not commit unreviewed stored-face siblings
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > UXW2-6 slice 3 group accept of close matches > Just this one accepts only the current suggestion
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > UXW2-6 slice 3 group accept of close matches > Just this one accepts only the current suggestion
An update to ForwardRef(ReviewQueue2) inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > UXW2-6 slice 3 group accept of close matches > excludes weaker siblings from the offered close-match count
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > UXW2-6 slice 3 group accept of close matches > caps the offer at 25 and states how many close matches were not included
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > UXW2-6 slice 3 group accept of close matches > reuses pinned partial-failure copy when a group accept stops mid-sequence
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx (119 tests) 52134ms
     ✓ renders exactly one review card at a time (one-card invariant)  1182ms
     ✓ navigates with prev/next without changing index on accept (PR-54 live-queue semantics)  3129ms
     ✓ focuses next card primary action after accept (authoritative advance-focus gate)  1118ms
     ✓ filters with kind chips and shows one card for the filtered set  2399ms
     ✓ kind chip calls onKindChange once and never dispatches SET_INDEX (R1-06/R2-04)  665ms
     ✓ band chip calls onBandChange once and never dispatches SET_INDEX (R1-06/R2-04)  633ms
     ✓ kind chip on ScanTabContent dispatch writes rq=assignment.all.0 and presses the chip (UXW2-1-R3-07)  1498ms
     ✓ two synchronous Next clicks advance index by 2 (R1-05)  361ms
     ✓ fires existing accept mutation and invalidates projection keys  460ms
     ✓ fires reject mutation after hold window  354ms
     ✓ BR-16: undo before navigate yields 0 POSTs  1512ms
     ✓ BR-16: navigate during hold flushes exactly 1 POST and announces  500ms
     ✓ BR-15: accept A, next to B (flush), accept B → 2 POSTs order preserved; held card disabled only  1104ms
     ✓ exposes focusCurrentCard imperative handle  474ms
     ✓ renders unavailable guidance instead of a false empty state  461ms
     ✓ preserves restored index across staggered query resolution (BR-06 reload gate)  1084ms
     ✓ does not move focus on Next after a failed accept (BR-13)  907ms
     ✓ DUX-L7-RV-03: re-announces identical copy through one persistent live node  694ms
     ✓ DUX-W2R1-RV-04: repeat announcement mutates the persistent node text (AT-observable), not just data-announce-seq  708ms
     ✓ shows filtered-empty escape hatch when filters hide pending work (S1-01 / COG-03)  730ms
     ✓ shows person-commit + HAI-05 disclosure on ASSIGNMENT when clusterId present  816ms
     ✓ hides person-commit on MERGE cards  427ms
     ✓ header count decrements after a label commit remount with stale fetchers  1806ms
     ✓ R1-22: queue header and findings unlabeled count agree after a drop  849ms
     ✓ R1-29: filtered header uses shown copy, not a false remaining total  712ms
     ✓ curate control on a name card reports the cluster id upward (UXW2-3-R3-01)  752ms
     ✓ shows person-commit as primary on NAME cards with disclosure  690ms
     ✓ DUX-L7-RV-01 DUX-L7-RV-04: Tab-reachable disclosure toggles closed on second keyboard activation  1252ms
     ✓ DUX-L7-RV-04: NAME person-commit drain moves focus to the empty-state anchor  800ms
     ✓ person-commit success renders View in roster → link to #/roster  300ms
     ✓ person-commit while accept hold is open flushes held accept first  868ms
     ✓ BR-27: focus on NAME card lands on person-commit combobox/confirm (not demoted Accept)  428ms
     ✓ BR-30: person-commit failure after accept advances shows queue-level alert; retry fires 1 POST  1003ms
     ✓ UI-04: drain announcement uses error copy when top-unlabeled failed  945ms
     ✓ E21-14: top-unlabeled 500 keeps the Clear filters escape hatch and announces both states  435ms
     ✓ REV2-09: empty-queue Resync refetches top-unlabeled without drain confirmation  906ms
     ✓ R2-12: repair_pending with empty served page mounts Resync and does not drain-only  397ms
     ✓ R5-09: findings Resync and queue Resync have distinct accessible names  535ms
     ✓ REV2-08: error Retry refetches name suggestions with the other findings queries  745ms
     ✓ REV4-02: queue Retry announces in-flight busy then distinct retry-failed copy  370ms
     ✓ BR-34: null-clusterId assignment item renders no person-commit chrome  410ms
       ✓ default-empty selection tray; Select toggles; PR-38 Accept N for label; zero bulk-accept  1174ms
       ✓ BR-47: selected card disables single Accept/Reject with deselect reason; deselect re-enables  606ms
       ✓ DUX-L8-RV-02: blocks selection acceptance until every gated suggestion was disclosed  404ms
       ✓ DUX-W2R2-RV-01: Retry after partial fail does not commit a later-selected gated card  907ms
       ✓ DUX-W2R2-RV-05: Retry onClick is a no-op while stored-face gated and reason stays resolvable when tray collapses  787ms
       ✓ bulk undo during hold = 0 POSTs  392ms
       ✓ truncation gate: truncated target disables commit until total-N confirm  383ms
       ✓ band chips filter queue by similarity post-eligibility; compose with KIND; merge excluded (BR-60)  531ms
       ✓ BR-59: truncation gate keys off the filter-intersected selection only  476ms
     ✓ names the reviewed face from the lightbox for the whole same-group run  671ms
       ✓ offers the close-match count before any write and confirms through the bulk sequencer  490ms
       ✓ DUX-W2R2-RV-04: Close Match Confirm does not commit unreviewed stored-face siblings  607ms
       ✓ Just this one accepts only the current suggestion  428ms
       ✓ excludes weaker siblings from the offered close-match count  307ms
       ✓ caps the offer at 25 and states how many close matches were not included  402ms
       ✓ reuses pinned partial-failure copy when a group accept stops mid-sequence  357ms
(node:2357226) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx (100 tests) 13491ms
     ✓ renders a Suggest alt text control  397ms
     ✓ W3-C-04 Accept is secondary; Save alt text is the single primary  460ms
     ✓ announces saving into the polite region while an edited save is in flight [a11y][BR-56]  321ms
     ✓ does not steal focus from elsewhere on the page after a successful accept [a11y][WBUX-5-S2C3A-BR-22]  650ms
     ✓ keeps co-mounted suggest and inline editors free of duplicate accessible names [A11Y-03][WBUX-5-S2C3A-BR-08]  644ms
     ✓ keeps a single commit authority while editing [S2c-3a]  470ms
     ✓ cancels back to the draft without committing [INT-09][S2c-3a]  320ms
     ✓ keeps Save enabled while the length advisory is showing in edit mode [A11Y-36][S2c-3c]  303ms
     ✓ enqueues exactly one correction for two same-tick Save activations [S2C3A-BR-16]  364ms
     ✓ derives workbench status from alt OR decorative (two-fact rule) [class-api.php:338][TEST-15]  361ms
     ✓ allows decorative retry after PARTIAL without false CAS conflict [S6-A-02][rg-002]  749ms
     ✓ reconciles cache from stored_alt_text on decorative PARTIAL failure [S7-BR-02]  398ms
(node:2357865) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx > WorkbenchFindingsPanel > renders Avatar for a dedicated face-thumbs URL instead of FaceThumbnail
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx (57 tests) 3681ms
     ✓ renders counts, previews, and an enabled primary action for populated findings  672ms
(node:2358103) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewMutations.test.tsx (50 tests) 678ms
(node:2358242) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx > ClusterLabelingPanel > two rapid Rename anyway clicks fire the mutation once (UXW2-3-R3-06)
An update to ClusterLabelingPanel inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to ClusterLabelingPanel inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to ClusterLabelingPanel inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx > ClusterLabelingPanel > two rapid Enter presses fire the mutation once (UXW2-3-R1-04 / R2-02)
An update to ClusterLabelingPanel inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to ClusterLabelingPanel inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to ClusterLabelingPanel inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx (59 tests) 15478ms
     ✓ offers a way back when the face group has no members  464ms
     ✓ blocks save with pre-save duplicate guard for an existing cluster and merges with named target (PR-18/23/24)  1138ms
     ✓ moves focus to the first duplicate-guard action when the guard opens (UXW2-3-R6-06)  460ms
     ✓ R1-17: merge success drops result.source_id from topUnlabeled  410ms
     ✓ person-only collision binds instead of offering rename-anyway (UXW2-3-R2-07)  388ms
     ✓ keeps normal save path when no matching existing label exists  316ms
     ✓ shows network error inline with alert role  384ms
     ✓ shows projection-not-ready error inline with alert role  326ms
     ✓ dismisses duplicate guard on Cancel and keeps editing available  799ms
     ✓ keeps input editable while save is pending  333ms
     ✓ announces roster loading and empty states (A11Y-24 / FIX-7)  415ms
     ✓ reserved machine-shaped input is rejected before remote guard runs (BR-46)  338ms
     ✓ remote guard collides on machine-shaped label via case-insensitive raw equality (BR-50 / BR-42)  374ms
     ✓ BR-46 / BR-66: human-labeled merge target offers copy + clickable merge (control)  330ms
     ✓ BR-46: remote guard with only a null-labeled row resolves to no collision  351ms
     ✓ BR-46: reserved machine-shaped label is rejected before remote guard  322ms
     ✓ BR-46: human label Cluster-Dad proceeds past reserved validation to save  334ms
     ✓ typed free-text Save arms guard with merge when local collision is loaded (FIX-9)  308ms
     ✓ clicking confirm on a suggestion row primes that option (UXW2-3-R1-08b)  308ms
     ✓ type + Enter on an existing group name primes the same merge guard (UXW2-3-R1-12)  373ms
     ✓ two rapid Rename anyway clicks fire the mutation once (UXW2-3-R3-06)  397ms
     ✓ Rename anyway clicked twice in the same tick fires the mutation once (UXW2-3-R3-21)  371ms
     ✓ Save name after a settled submit fires again (UXW2-3-R3-21)  597ms
     ✓ type + Enter binds a roster person past the naming-options limit (UXW2-3-R1-07)  304ms
(node:2358812) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/DescriptionHistoryPage.test.tsx (38 tests) 3897ms
(node:2358973) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useCorrectMediaAlt.test.tsx (35 tests) 2854ms
(node:2359135) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useWorkbenchFindings.test.tsx (42 tests) 578ms
(node:2359227) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/IdentityThumbnail.test.tsx (27 tests) 536ms
(node:2359397) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/banned-vocabulary.test.tsx (33 tests) 1305ms
(node:2359594) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useBulkReviewCommit.test.tsx (41 tests) 296ms
(node:2359685) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx (27 tests) 1036ms
(node:2359746) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx (24 tests) 3894ms
       ✓ resolves an inline prompt on every one of 60 unlabeled cards from a single batch  1701ms
(node:2359928) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/DashboardPage.test.tsx (34 tests) 2237ms
(node:2360057) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/SettingsPage.test.tsx (50 tests) 1888ms
(node:2360152) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.test.tsx (22 tests) 1769ms
(node:2360268) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx > WorkbenchPage > surfaces scan errors in the UI
Scan submission failed Error: Scan failed
    at Object.mutate (/home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx:263:30)
    at /home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts:179:20
    at handleScanFaces (/home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAnalyzeCta.tsx:39:5)
    at executeDispatch (/home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19116:9)
    at runWithFiberInDEV (/home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:874:13)
    at processDispatchQueue (/home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19166:19)
    at /home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19767:9
    at batchedUpdates$1 (/home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:3255:40)
    at dispatchEventForPluginEventSystem (/home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19320:7)
    at dispatchEvent (/home/gate/grok-sandbox/fix-febt-1-w1-errors-0e68abfe/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:23585:11)

 ✓ js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx (24 tests) 5091ms
     ✓ shows a local-mode notice when recognition source is local  429ms
     ✓ surfaces scan errors in the UI  503ms
     ✓ updates media page size through URL-backed filters  401ms
     ✓ closes the overlay when the dismiss action is used  305ms
     ✓ opens the advanced drawer, moves focus inside, and restores focus on Escape  311ms
(node:2360453) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterEntries.test.tsx (35 tests) 1490ms
     ✓ confirms before deleting a person  371ms
(node:2360548) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/reviewQueueDriver.test.ts (44 tests) 62ms
(node:2360606) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ConflictInbox.test.tsx (27 tests) 1727ms
(node:2360675) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/__tests__/DescribeRunApplyView.test.tsx > DescribeRunApplyView > surfaces partial apply ids so operators know alt is live but history is missing [RLSE-05]
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/__tests__/DescribeRunApplyView.test.tsx > DescribeRunApplyView > omits the applied sentence when every write was partial [BR-90c]
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/__tests__/DescribeRunApplyView.test.tsx > DescribeRunApplyView > caps long partial id lists and uses item headings with media ids [BR-90d][BR-111]
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/__tests__/DescribeRunApplyView.test.tsx > DescribeRunApplyView > surfaces media ids alongside colliding captions on partial rows [BR-111]
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to DescribeRunApplyView inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

 ✓ js/admin/pages/__tests__/DescribeRunApplyView.test.tsx (21 tests) 1393ms
(node:2360786) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx > WorkbenchPage (integration-lite) > paints new findings after projection-ready without reload or remount (E15-23 / E15-24 gate)
An update to WorkbenchMediaProvider inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to WorkbenchMediaProvider inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to CheckboxProvider inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to CheckboxProvider inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectContent inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectContent inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItemText inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to SelectItem inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to Select inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx > WorkbenchPage (integration-lite) > paints new findings after projection-ready without reload or remount (E15-23 / E15-24 gate)
A component suspended inside an `act` scope, but the `act` call was not awaited. When testing React components that depend on asynchronous data, you must await the result:

await act(() => ...)

 ✓ js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx (12 tests) 2860ms
     ✓ uses real hooks to trigger scan and invalidate identities  891ms
     ✓ paints new findings after projection-ready without reload or remount (E15-23 / E15-24 gate)  319ms
(node:2360947) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltInlineEditor.test.tsx (21 tests) 880ms
(node:2361002) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/recognitionApi.test.ts (46 tests) 49ms
(node:2361077) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx (26 tests) 1209ms
(node:2361143) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchMedia.test.tsx (10 tests) 477ms
(node:2361209) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/mediaFooterSinglePrimary.dom.test.tsx (13 tests) 1331ms
(node:2361295) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx (34 tests) 205ms
(node:2361312) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/SyncStatusIndicator.test.tsx (33 tests) 369ms
(node:2361379) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts (55 tests) 36ms
(node:2361397) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/PersonWorkspacePanel.scrubber.test.tsx (16 tests) 1460ms
(node:2361468) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSaveAction.test.tsx (24 tests) 95ms
(node:2361535) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.search.test.tsx (20 tests) 1657ms
(node:2361585) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.workspace.test.tsx (15 tests) 842ms
(node:2361634) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx (36 tests) 947ms
(node:2361703) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx > TopClusterCard > renders a dedicated face-thumb avatar when the representative carries a face-thumbs URL
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx (27 tests) 394ms
(node:2361711) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx (32 tests) 490ms
(node:2361741) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/dashboard-uxmap-code-parity.test.ts (9 tests) 23ms
(node:2361772) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/http.test.ts (32 tests) 87ms
(node:2361785) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachine.test.ts (16 tests) 87ms
(node:2361846) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/MergeSuggestionCard.test.tsx (16 tests) 514ms
(node:2361856) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.commitExclusivity.test.tsx (10 tests) 1169ms
     ✓ [TEST-06] headline: generate draft, save different text via editor, Accept refuses and keeps operator text  309ms
(node:2361928) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/Panels.test.tsx (42 tests) 449ms
(node:2362008) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchMediaContext.test.tsx (12 tests) 190ms
(node:2362016) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/describeApi.test.ts (32 tests) 27ms
(node:2362071) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx > PersonWorkspacePanel evidence images > opens FaceLightbox when a croppable thumbnail button is clicked
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx > PersonWorkspacePanel evidence images > resets lightbox when entry person identity changes
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx > PersonWorkspacePanel evidence images > resets lightbox when entry id changes with empty person_uuid
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx > PersonWorkspacePanel evidence images > resets lightbox when person_uuid changes with the same entry id
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx > PersonWorkspacePanel evidence images > resets lightbox when person_uuid collides with prior entry id
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx > PersonWorkspacePanel evidence images > closes lightbox via dialog close affordance and allows reopen
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx > PersonWorkspacePanel evidence images > closes lightbox via dialog close affordance and allows reopen
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

 ✓ js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx (17 tests) 1377ms
(node:2362126) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.container.test.tsx (15 tests) 897ms
(node:2362179) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.memberFix.test.tsx (17 tests) 2411ms
     ✓ rejects cluster-7 without calling onCommitCluster and shows reserved message  330ms
     ✓ BR-64: clears reserved status when creating a human name after reject, then commits  412ms
     ✓ BR-64: clears reserved status when selecting an existing entry after reject, then commits  308ms
(node:2362230) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/projectionConsumerHarness.test.tsx (14 tests) 1360ms
(node:2362292) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-render-parity.test.ts (14 tests) 39ms
(node:2362342) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/syncPresentation.test.ts (31 tests) 74ms
(node:2362350) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.reviewQueueUrl.test.tsx (9 tests) 1446ms
     ✓ chip click → aria-pressed=true AND rq=assignment.all.0; Next keeps it; chip again removes rq  471ms
(node:2362418) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RetentionPage.test.tsx (13 tests) 1313ms
(node:2362478) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltInlineEditor.siblingSuccess.test.tsx (4 tests) 426ms
(node:2362540) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/PersonCommitControl.test.tsx (26 tests) 881ms
(node:2362589) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useShowAllClusterMembers.test.tsx (9 tests) 595ms
(node:2362597) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchTwoPaneLayout.test.tsx (13 tests) 270ms
(node:2362648) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaIdentities.test.tsx (8 tests) 161ms
(node:2362660) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx > SuggestionCard UXC-02 stored-reference disclosure > DUX-L8-RV-01: keeps approval blocked until the stored-face disclosure is rendered
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx (19 tests) 614ms
(node:2362718) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjectionInvalidation.test.tsx (8 tests) 378ms
(node:2362730) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/appError.test.ts (28 tests) 23ms
(node:2362792) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.reviewUrl.test.tsx (8 tests) 466ms
(node:2362847) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/recognitionCooldownGate.test.tsx (6 tests) 237ms
stderr | js/admin/hooks/__tests__/recognitionCooldownGate.test.tsx > useRecognitionCooldown observable state > reports the live window and counts remaining seconds down to idle
An update to TestComponent inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2362855) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.test.tsx (7 tests) 516ms
(node:2362902) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.test.tsx (13 tests) 507ms
(node:2362958) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineEffects.test.ts (8 tests) 369ms
(node:2362995) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx (13 tests) 251ms
(node:2363003) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx (5 tests) 591ms
(node:2363074) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx (9 tests) 482ms
(node:2363136) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/EmptyState.test.tsx (17 tests) 286ms
stderr | js/admin/components/ui/__tests__/EmptyState.test.tsx > EmptyState (shared dead-end primitive) > mounts an empty persistent live region, then announces the unavailable state [A11Y-24]
An update to Root inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to EmptyState inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2363150) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobMachine.test.ts (179 tests) 35ms
(node:2363207) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.politeExclusivity.test.tsx (6 tests) 614ms
     ✓ [TEST-06] co-mount: Suggest draft then editor save → exactly one polite region holds the later cue  319ms
(node:2363283) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DashboardSyncHealthSection.test.tsx (11 tests) 596ms
(node:2363330) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterActionMutations.test.tsx (10 tests) 534ms
(node:2363393) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/retryPolicy.test.ts (27 tests) 23ms
(node:2363410) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterZeroStateReachability.test.tsx (6 tests) 382ms
(node:2363464) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.controlPaneOrder.test.tsx (9 tests) 169ms
(node:2363502) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/clusterAutoRetry.test.ts (17 tests) 29ms
(node:2363532) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.offline.test.tsx (12 tests) 461ms
(node:2363589) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.identitiesDegraded.test.tsx (4 tests) 639ms
(node:2363608) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/tokens/__tests__/design-tokens.test.ts (6 tests) 47ms
(node:2363666) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/JobTimeline.test.tsx (21 tests) 152ms
(node:2363748) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeCta.test.tsx (12 tests) 318ms
stderr | js/admin/pages/workbench/__tests__/BulkDescribeCta.test.tsx > BulkDescribeCta state matrix (A11Y-24) > announces the shared recognition cooldown with its remaining window
An update to BulkDescribeProgress inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2363769) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterLabelMutations.test.tsx (6 tests) 369ms
(node:2363830) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/workbenchControlOnePrimary.dom.test.tsx (2 tests) 586ms
     ✓ counts exactly one .button-primary across labeling Done, lightbox name, and review-card commit  568ms
(node:2363867) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/buildNamingOptions.test.ts (14 tests) 20ms
(node:2363896) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/WorkbenchPage.test.tsx (16 tests) 355ms
(node:2363927) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRecognitionJobHistory.test.tsx (5 tests) 68ms
(node:2363964) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useInlineSuggestionBatch.test.tsx (8 tests) 341ms
(node:2364016) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.authExpired.test.tsx (2 tests) 217ms
(node:2364041) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/navigation/__tests__/appLinks.test.ts (14 tests) 27ms
(node:2364072) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobProgressStreamHelpers.test.ts (17 tests) 41ms
(node:2364110) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterConfirmSuggestion.test.tsx (6 tests) 51ms
(node:2364122) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx (8 tests) 482ms
(node:2364222) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.source.test.tsx (4 tests) 201ms
(node:2364252) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.reviewCta.test.tsx (6 tests) 232ms
(node:2364298) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/DegradedModeBanner.test.tsx (13 tests) 184ms
(node:2364350) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.test.tsx (7 tests) 324ms
(node:2364376) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.personAware.test.tsx (9 tests) 464ms
(node:2364425) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/recognitionCooldown.test.ts (18 tests) 29ms
(node:2364453) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/resolveMergeSurvivor.test.ts (10 tests) 13ms
(node:2364498) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useBulkDescribe.test.tsx (7 tests) 317ms
(node:2364510) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobProgressStream.test.tsx (7 tests) 93ms
(node:2364565) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.nav03.test.tsx (1 test) 71ms
(node:2364581) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/App.test.tsx (6 tests) 298ms
(node:2364638) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/refreshRestNonce.test.ts (12 tests) 34ms
(node:2364649) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.authExpired.test.tsx (2 tests) 246ms
(node:2364715) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeRunApply.test.tsx (6 tests) 470ms
(node:2364780) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/logger.test.ts (11 tests) 24ms
(node:2364788) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/syncVocabulary.test.ts (3 tests) 47ms
(node:2364806) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesTable.reservedLabel.test.tsx (5 tests) 928ms
(node:2364907) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterMatchAction.test.tsx (6 tests) 80ms
(node:2365000) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.dropCaches.test.ts (5 tests) 15ms
(node:2365087) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useTopUnlabeledTotal.test.tsx (8 tests) 449ms
(node:2365158) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/phasePresentation.test.ts (10 tests) 14ms
(node:2365195) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/navigation/__tests__/appLinks.guard.test.ts (2 tests) 66ms
(node:2365312) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSelectedClusterTruncation.test.tsx (6 tests) 285ms
(node:2365471) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/usePanesParam.test.tsx (7 tests) 68ms
(node:2365494) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/WorkbenchPage.scatter.test.tsx (6 tests) 266ms
(node:2365545) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRosterHooks.cacheMerge.test.tsx (2 tests) 66ms
(node:2365553) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/envelopeMetadata.test.ts (10 tests) 15ms
(node:2365571) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRecognitionPolling.test.ts (12 tests) 11ms
(node:2365623) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaStats.test.tsx (2 tests) 192ms
(node:2365639) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts (33 tests) 41ms
(node:2365691) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ClusterPanelContext.test.tsx (5 tests) 255ms
(node:2365702) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/rosterRoute.test.ts (13 tests) 27ms
(node:2365764) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/adminUrls.test.ts (6 tests) 139ms
(node:2365772) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/decodeHtmlEntities.test.ts (10 tests) 21ms
(node:2365821) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAnalyzeCta.test.tsx (8 tests) 217ms
(node:2365845) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncTrigger.test.tsx (5 tests) 71ms
stderr | js/admin/hooks/__tests__/useSyncTrigger.test.tsx > useSyncTrigger > triggers once when stale if auto-trigger is explicitly enabled
A component suspended inside an `act` scope, but the `act` call was not awaited. When testing React components that depend on asynchronous data, you must await the result:

await act(() => ...)

(node:2365863) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewQueries.test.tsx (2 tests) 139ms
(node:2365923) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DashboardRecentActivitySection.test.tsx (6 tests) 166ms
(node:2365939) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/scanApiBatching.test.ts (6 tests) 17ms
(node:2365987) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/identitySuggestionMappers.test.ts (5 tests) 11ms
(node:2365998) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobStateMachineProgress.test.ts (10 tests) 16ms
(node:2366057) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts (3 tests) 17ms
(node:2366065) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterMutations.test.tsx (1 test) 64ms
(node:2366076) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeProgress.test.tsx (3 tests) 180ms
stderr | js/admin/pages/workbench/__tests__/BulkDescribeProgress.test.tsx > BulkDescribeProgress a11y countdown (polite region does not re-announce every second) > keeps the announced sentence static while only the aria-hidden countdown ticks
An update to BulkDescribeProgress inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

stderr | js/admin/pages/workbench/__tests__/BulkDescribeProgress.test.tsx > BulkDescribeProgress cooldown-vs-error precedence > prefers the paused notice over the assertive retry alert when a 429 hard error meets an armed cooldown
An update to BulkDescribeProgress inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2366144) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterActions.offline.test.tsx (3 tests) 204ms
(node:2366195) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > shows the close-match count before any write and uses the canonical term
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > surfaces an explicit truncation signal when more than 25 qualify
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > keeps a single accent primary on the confirm control
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx (6 tests) 303ms
stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > confirm and skip call the matching callbacks; Esc uses onOpenChange
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

(node:2366214) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobCoordination.test.ts (6 tests) 60ms
(node:2366263) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/buildDashboardPriorityModel.test.ts (24 tests) 17ms
(node:2366279) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobPersistence.test.ts (7 tests) 59ms
(node:2366297) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobStateMachineUtils.test.ts (6 tests) 11ms
(node:2366354) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.labelPanelReachable.test.tsx (2 tests) 157ms
(node:2366362) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DescribePanel.test.tsx (8 tests) 222ms
(node:2366419) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.filters.test.tsx (2 tests) 199ms
(node:2366446) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.tombstones.test.ts (4 tests) 9ms
(node:2366495) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/GuidanceCard.test.tsx (6 tests) 146ms
(node:2366511) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/menuHeadingParity.test.ts (6 tests) 11ms
(node:2366579) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/rosterEntryContract.test.ts (2 tests) 9ms
(node:2366591) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useAriaAnnounce.test.tsx (2 tests) 76ms
(node:2366612) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/OrientationCard.test.tsx (6 tests) 274ms
(node:2366662) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.labelAnnounce.test.tsx (1 test) 133ms
(node:2366728) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.queueFilter.test.tsx (2 tests) 137ms
(node:2366747) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/LightboxNameFace.test.tsx (4 tests) 272ms
(node:2366799) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx (3 tests) 341ms
(node:2366815) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/appQueryClient.test.ts (5 tests) 24ms
(node:2366872) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/__tests__/query-conditions.test.ts (3 tests) 12ms
(node:2366882) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/degradedModeBannerLogic.vocabularySource.test.ts (10 tests) 10ms
(node:2366898) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ConfirmTabContent.test.tsx (3 tests) 176ms
(node:2366958) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/StepMap.test.tsx (3 tests) 188ms
(node:2366974) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts (7 tests) 12ms
(node:2367026) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/pageHeadingBoundary.test.ts (6 tests) 8ms
(node:2367046) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/mediaFooterCtaState.test.ts (7 tests) 10ms
(node:2367085) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/snapshotContract.test.ts (2 tests) 8ms
(node:2367136) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/name-face-surface.test.ts (4 tests) 223ms
(node:2367200) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useScrollRestoration.test.ts (4 tests) 41ms
(node:2367219) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/InlineSuggestionPrompt.test.tsx (7 tests) 181ms
(node:2367236) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx (3 tests) 120ms
(node:2367286) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/settingsResponseContract.test.ts (2 tests) 8ms
(node:2367302) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/review-queue-styles.test.ts (4 tests) 9ms
(node:2367360) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/retention/__tests__/AuditTimeline.emptyState.test.tsx (5 tests) 211ms
(node:2367379) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeMedia.test.tsx (3 tests) 196ms
(node:2367430) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx (1 test) 86ms
(node:2367446) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ownedGettextLiterals.test.ts (1 test) 171ms
(node:2367506) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/normalizeTopUnlabeledRepresentative.test.ts (4 tests) 9ms
(node:2367524) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncStatus.test.tsx (2 tests) 48ms
(node:2367586) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineDerivedState.test.ts (2 tests) 34ms
(node:2367602) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/workbenchMediaApi.test.ts (3 tests) 12ms
(node:2367610) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/routeHelpers.test.ts (9 tests) 14ms
(node:2367671) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/workbenchMediaDetailContract.test.ts (3 tests) 12ms
(node:2367687) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useTabParam.test.tsx (4 tests) 60ms
(node:2367743) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/workbenchQueueUrl.test.ts (4 tests) 10ms
(node:2367752) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/registerConfig.test.ts (3 tests) 15ms
(node:2367768) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/degradedModeBannerLogic.test.ts (6 tests) 9ms
(node:2367827) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchFilters.rqDoubleWrite.test.tsx (4 tests) 55ms
(node:2367843) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/AdvancedDrawer.test.tsx (2 tests) 218ms
(node:2367901) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/context/__tests__/ToastContext.test.tsx (1 test) 208ms
(node:2367918) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncOffline.test.ts (4 tests) 34ms
(node:2367975) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useBulkRetryOperations.test.tsx (2 tests) 52ms
(node:2367987) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/userFacingError.test.ts (3 tests) 8ms
(node:2368005) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ReviewSurfaceContext.wiring.test.tsx (1 test) 90ms
stderr | js/admin/pages/workbench/__tests__/ReviewSurfaceContext.wiring.test.tsx > WorkbenchProvider wiring — ReviewSurfaceProvider is in the stack (BR-01) > mounts a useReviewSurface consumer without throwing
An update to JobPipelineProvider inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to JobPipelineProvider inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to JobPipelineProvider inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to JobPipelineProvider inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to JobPipelineProvider inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act
An update to JobPipelineProvider inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2368064) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/deriveIdentitiesPresentationSource.test.ts (4 tests) 9ms
(node:2368080) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/topUnlabeledClustersContract.test.ts (2 tests) 8ms
(node:2368144) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.emptyState.test.tsx (1 test) 150ms
(node:2368160) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterActions.test.tsx (4 tests) 192ms
(node:2368225) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/UserFacingErrorNotice.test.tsx (2 tests) 104ms
(node:2368236) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/MergeSurvivorContext.test.tsx (3 tests) 60ms
(node:2368297) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterMediaMap.test.ts (2 tests) 33ms
(node:2368315) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/radio-group-styles.test.ts (4 tests) 11020ms
     ✓ ships radio-group rules in the production admin CSS bundle  11012ms
(node:2368650) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaSelectionState.test.ts (2 tests) 32ms
(node:2368669) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/DebugMetricsPanel.test.tsx (3 tests) 123ms
(node:2368730) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.test.ts (6 tests) 11ms
(node:2368746) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/clusterListContract.test.ts (2 tests) 8ms
(node:2368763) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-parity.test.ts (1 test) 7ms
(node:2368820) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/scanApiError.test.ts (5 tests) 9ms
(node:2368835) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/personCommitVisibility.test.ts (4 tests) 12ms
(node:2368878) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/ConfirmDialog.test.tsx (2 tests) 247ms
(node:2368906) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchNavContext.test.tsx (1 test) 40ms
(node:2368922) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/clusterLabelsContract.test.ts (2 tests) 7ms
(node:2368995) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/FaceGroupScatter.test.tsx (5 tests) 128ms
(node:2369019) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ReviewSurfaceContext.test.tsx (2 tests) 117ms
(node:2369081) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/roster-keyboard-walk.spec.guard.test.ts (3 tests) 9ms
(node:2369104) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-one-primary.test.ts (4 tests) 12ms
(node:2369134) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/comboboxEchoOrder.contract.test.tsx (1 test) 248ms
(node:2369180) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/target-card-styles.test.ts (3 tests) 10784ms
     ✓ ships target-card rules in the production admin CSS bundle  10774ms
(node:2369541) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.expandError.test.tsx (1 test) 82ms
(node:2369571) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeReviewLink.test.tsx (4 tests) 92ms
(node:2369621) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncHealth.test.tsx (1 test) 35ms
(node:2369637) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useOverlayParam.test.tsx (1 test) 36ms
(node:2369694) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useRosterFaceCursor.test.tsx (1 test) 26ms
(node:2369711) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/retryAfter.test.ts (4 tests) 8ms
(node:2369727) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/settings/__tests__/healthStatus.test.ts (4 tests) 7ms
(node:2369785) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionToolbar.failure.test.tsx (2 tests) 139ms
(node:2369803) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/syncHealthContract.test.ts (1 test) 7ms
(node:2369866) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/requestTimeout.test.ts (2 tests) 8ms
(node:2369882) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterDragDrop.test.ts (1 test) 26ms
(node:2369917) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/clusterApiQueries.repairPending.test.ts (1 test) 6ms
(node:2369955) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/orientation-card-styles.test.ts (1 test) 6ms
(node:2369971) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/AnchorSelectionModal.emptyState.test.tsx (1 test) 184ms
(node:2370033) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRemoteActionGate.test.ts (2 tests) 7ms

 Test Files  232 passed (232)
      Tests  2898 passed (2898)
   Start at  15:20:59
   Duration  505.09s (transform 29.57s, setup 61.26s, import 69.47s, tests 190.03s, environment 135.64s)

EXIT=0
```

EXIT=0

## Command 4

Command:

```
git log --oneline -1
```

Raw output:

```
3d81a45 sandbox base (fix-febt-1-w1-errors-0e68abfe, history-stripped, remote-severed)
```

EXIT=0

## Command 5

Command:

```
git status --short
```

git status --short printed nothing (working tree clean at verification time, before this evidence file existed).

Raw output:

```
```

EXIT=0

## VERDICT

TYPECHECK PASS / TESTS PASS
