# FEBT-1 w1 machine verify-only evidence
Raw stdout/stderr from the verify-only pass. Outputs are unedited.
## Command 1
```
cd apps/prototype-wp-alt-context && npm ci --silent ; echo "EXIT=$?"
```
```
(node:2400729) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
```
EXIT=0
## Command 2
```
cd apps/prototype-wp-alt-context && npm run typecheck ; echo "EXIT=$?"
```
```

> prototype-wp-alt-context@0.0.4 typecheck
> tsc --noEmit --project tsconfig.type-check.json

```
EXIT=0
## Command 3
```
cd apps/prototype-wp-alt-context && npx vitest run js/admin ; echo "EXIT=$?"
```
```
(node:2402851) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:2402894) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)

 RUN  v4.1.5 /home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context

(node:2402924) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx (119 tests) 13058ms
     ✓ navigates with prev/next without changing index on accept (PR-54 live-queue semantics)  481ms
     ✓ filters with kind chips and shows one card for the filtered set  313ms
     ✓ header count decrements after a label commit remount with stale fetchers  311ms
       ✓ default-empty selection tray; Select toggles; PR-38 Accept N for label; zero bulk-accept  409ms
       ✓ DUX-W2R2-RV-01: Retry after partial fail does not commit a later-selected gated card  393ms
       ✓ DUX-W2R2-RV-05: Retry onClick is a no-op while stored-face gated and reason stays resolvable when tray collapses  534ms
(node:2403453) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx (100 tests) 4097ms
(node:2403554) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx > WorkbenchFindingsPanel > renders Avatar for a dedicated face-thumbs URL instead of FaceThumbnail
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx (57 tests) 1637ms
(node:2403725) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewMutations.test.tsx (50 tests) 425ms
(node:2403749) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx (59 tests) 8443ms
     ✓ offers a way back when the face group has no members  303ms
     ✓ blocks save with pre-save duplicate guard for an existing cluster and merges with named target (PR-18/23/24)  460ms
     ✓ dismisses duplicate guard on Cancel and keeps editing available  369ms
     ✓ announces roster loading and empty states (A11Y-24 / FIX-7)  413ms
     ✓ reserved machine-shaped input is rejected before remote guard runs (BR-46)  314ms
(node:2404108) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/DescriptionHistoryPage.test.tsx (38 tests) 1756ms
(node:2404207) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useCorrectMediaAlt.test.tsx (35 tests) 2319ms
(node:2404274) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useWorkbenchFindings.test.tsx (42 tests) 401ms
(node:2404346) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/IdentityThumbnail.test.tsx (27 tests) 483ms
(node:2404357) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/banned-vocabulary.test.tsx (33 tests) 1006ms
(node:2404452) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useBulkReviewCommit.test.tsx (41 tests) 231ms
(node:2404481) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx (27 tests) 993ms
(node:2404574) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx (24 tests) 2639ms
       ✓ resolves an inline prompt on every one of 60 unlabeled cards from a single batch  1210ms
(node:2404610) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/DashboardPage.test.tsx (34 tests) 1308ms
(node:2404686) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/SettingsPage.test.tsx (50 tests) 1064ms
(node:2404718) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.test.tsx (22 tests) 908ms
(node:2404793) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx > WorkbenchPage > surfaces scan errors in the UI
Scan submission failed Error: Scan failed
    at Object.mutate (/home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx:263:30)
    at /home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts:179:20
    at handleScanFaces (/home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAnalyzeCta.tsx:39:5)
    at executeDispatch (/home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19116:9)
    at runWithFiberInDEV (/home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:874:13)
    at processDispatchQueue (/home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19166:19)
    at /home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19767:9
    at batchedUpdates$1 (/home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:3255:40)
    at dispatchEventForPluginEventSystem (/home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19320:7)
    at dispatchEvent (/home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:23585:11)

 ✓ js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx (24 tests) 2801ms
(node:2404921) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterEntries.test.tsx (35 tests) 830ms
(node:2404982) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/reviewQueueDriver.test.ts (44 tests) 31ms
(node:2405005) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ConflictInbox.test.tsx (27 tests) 1095ms
(node:2405093) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/__tests__/DescribeRunApplyView.test.tsx (21 tests) 777ms
(node:2405120) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx (12 tests) 2742ms
     ✓ uses real hooks to trigger scan and invalidate identities  551ms
     ✓ paints new findings after projection-ready without reload or remount (E15-23 / E15-24 gate)  376ms
(node:2405235) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltInlineEditor.test.tsx (21 tests) 1039ms
(node:2405308) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/recognitionApi.test.ts (46 tests) 44ms
(node:2405317) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx (26 tests) 1088ms
(node:2405349) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchMedia.test.tsx (10 tests) 455ms
(node:2405362) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/mediaFooterSinglePrimary.dom.test.tsx (13 tests) 1160ms
(node:2405441) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx (34 tests) 195ms
(node:2405471) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/SyncStatusIndicator.test.tsx (33 tests) 333ms
(node:2405479) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts (55 tests) 33ms
(node:2405549) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/PersonWorkspacePanel.scrubber.test.tsx (16 tests) 1281ms
(node:2405581) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSaveAction.test.tsx (24 tests) 91ms
(node:2405590) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.search.test.tsx (20 tests) 2064ms
     ✓ narrows the directory to people whose name matches the typed query  483ms
     ✓ composes search with an active queue filter (AND, not replace)  305ms
(node:2405664) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.workspace.test.tsx (15 tests) 827ms
(node:2405703) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx (36 tests) 1428ms
(node:2405776) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx > TopClusterCard > renders a dedicated face-thumb avatar when the representative carries a face-thumbs URL
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx (27 tests) 523ms
(node:2405808) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx (32 tests) 468ms
(node:2405816) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobMachine.test.ts (199 tests) 38ms
(node:2405887) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/dashboard-uxmap-code-parity.test.ts (9 tests) 24ms
(node:2405895) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachine.test.ts (16 tests) 88ms
(node:2405903) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/MergeSuggestionCard.test.tsx (16 tests) 513ms
(node:2405933) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.commitExclusivity.test.tsx (10 tests) 1120ms
     ✓ [TEST-06] headline: generate draft, save different text via editor, Accept refuses and keeps operator text  318ms
(node:2406012) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/Panels.test.tsx (42 tests) 501ms
(node:2406041) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchMediaContext.test.tsx (12 tests) 326ms
(node:2406113) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/describeApi.test.ts (32 tests) 26ms
(node:2406145) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx (17 tests) 1211ms
(node:2406179) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.container.test.tsx (15 tests) 1543ms
(node:2406257) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.memberFix.test.tsx (17 tests) 2258ms
     ✓ BR-64: clears reserved status when creating a human name after reject, then commits  385ms
(node:2406357) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/projectionConsumerHarness.test.tsx (14 tests) 1348ms
(node:2406366) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/http.test.ts (28 tests) 74ms
(node:2406396) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-render-parity.test.ts (14 tests) 37ms
(node:2406404) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/syncPresentation.test.ts (31 tests) 66ms
(node:2406456) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.reviewQueueUrl.test.tsx (9 tests) 1223ms
     ✓ chip click → aria-pressed=true AND rq=assignment.all.0; Next keeps it; chip again removes rq  401ms
(node:2406485) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RetentionPage.test.tsx (13 tests) 1114ms
(node:2406517) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltInlineEditor.siblingSuccess.test.tsx (4 tests) 377ms
(node:2406590) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/PersonCommitControl.test.tsx (26 tests) 839ms
(node:2406620) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useShowAllClusterMembers.test.tsx (9 tests) 588ms
(node:2406651) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchTwoPaneLayout.test.tsx (13 tests) 270ms
(node:2406725) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaIdentities.test.tsx (8 tests) 152ms
(node:2406735) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx > SuggestionCard UXC-02 stored-reference disclosure > DUX-L8-RV-01: keeps approval blocked until the stored-face disclosure is rendered
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx (19 tests) 496ms
(node:2406743) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjectionInvalidation.test.tsx (8 tests) 375ms
(node:2406773) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/appError.test.ts (28 tests) 23ms
(node:2406825) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.reviewUrl.test.tsx (8 tests) 450ms
(node:2406858) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/recognitionCooldownGate.test.tsx (6 tests) 234ms
stderr | js/admin/hooks/__tests__/recognitionCooldownGate.test.tsx > useRecognitionCooldown observable state > reports the live window and counts remaining seconds down to idle
An update to TestComponent inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2406866) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.test.tsx (7 tests) 488ms
(node:2406896) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.test.tsx (13 tests) 426ms
(node:2406971) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineEffects.test.ts (8 tests) 370ms
(node:2406980) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx (13 tests) 253ms
(node:2407010) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx (5 tests) 526ms
(node:2407023) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx (9 tests) 486ms
(node:2407093) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
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

 ✓ js/admin/components/ui/__tests__/EmptyState.test.tsx (17 tests) 267ms
(node:2407103) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.politeExclusivity.test.tsx (6 tests) 496ms
(node:2407132) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DashboardSyncHealthSection.test.tsx (11 tests) 465ms
(node:2407210) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterActionMutations.test.tsx (10 tests) 538ms
(node:2407220) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterZeroStateReachability.test.tsx (6 tests) 355ms
(node:2407316) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.controlPaneOrder.test.tsx (9 tests) 154ms
(node:2407347) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.offline.test.tsx (12 tests) 433ms
(node:2407454) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.identitiesDegraded.test.tsx (4 tests) 554ms
(node:2407462) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/tokens/__tests__/design-tokens.test.ts (6 tests) 48ms
(node:2407491) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/JobTimeline.test.tsx (21 tests) 132ms
(node:2407501) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/__tests__/BulkDescribeCta.test.tsx > BulkDescribeCta state matrix (A11Y-24) > announces the shared recognition cooldown with its remaining window
An update to BulkDescribeProgress inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

 ✓ js/admin/pages/workbench/__tests__/BulkDescribeCta.test.tsx (12 tests) 294ms
(node:2407570) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterLabelMutations.test.tsx (6 tests) 366ms
(node:2407578) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/workbenchControlOnePrimary.dom.test.tsx (2 tests) 473ms
     ✓ counts exactly one .button-primary across labeling Done, lightbox name, and review-card commit  450ms
(node:2407608) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/buildNamingOptions.test.ts (14 tests) 20ms
(node:2407620) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/clusterAutoRetry.test.ts (14 tests) 25ms
(node:2407690) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/WorkbenchPage.test.tsx (16 tests) 313ms
(node:2407702) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRecognitionJobHistory.test.tsx (5 tests) 66ms
(node:2407730) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useInlineSuggestionBatch.test.tsx (8 tests) 335ms
(node:2407740) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.authExpired.test.tsx (2 tests) 186ms
(node:2407813) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/navigation/__tests__/appLinks.test.ts (14 tests) 17ms
(node:2407823) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobProgressStreamHelpers.test.ts (17 tests) 15ms
(node:2407831) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterConfirmSuggestion.test.tsx (6 tests) 52ms
(node:2407860) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx (8 tests) 389ms
(node:2407870) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.source.test.tsx (4 tests) 164ms
(node:2407947) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.reviewCta.test.tsx (6 tests) 202ms
(node:2407955) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/retryPolicy.test.ts (22 tests) 16ms
(node:2407972) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/DegradedModeBanner.test.tsx (13 tests) 171ms
(node:2408002) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.test.tsx (7 tests) 299ms
(node:2408057) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.personAware.test.tsx (9 tests) 396ms
(node:2408088) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/resolveMergeSurvivor.test.ts (10 tests) 12ms
(node:2408097) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useBulkDescribe.test.tsx (7 tests) 318ms
(node:2408124) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobProgressStream.test.tsx (7 tests) 74ms
(node:2408134) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.nav03.test.tsx (1 test) 67ms
(node:2408207) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/App.test.tsx (6 tests) 281ms
(node:2408235) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/refreshRestNonce.test.ts (12 tests) 35ms
(node:2408243) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.authExpired.test.tsx (2 tests) 219ms
(node:2408277) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeRunApply.test.tsx (6 tests) 472ms
(node:2408350) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/logger.test.ts (11 tests) 22ms
(node:2408360) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/syncVocabulary.test.ts (3 tests) 25ms
(node:2408369) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesTable.reservedLabel.test.tsx (5 tests) 799ms
(node:2408405) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterMatchAction.test.tsx (6 tests) 46ms
(node:2408436) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/recognitionCooldown.test.ts (14 tests) 25ms
(node:2408487) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.dropCaches.test.ts (5 tests) 14ms
(node:2408496) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useTopUnlabeledTotal.test.tsx (8 tests) 420ms
(node:2408504) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/phasePresentation.test.ts (10 tests) 14ms
(node:2408534) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/navigation/__tests__/appLinks.guard.test.ts (2 tests) 54ms
(node:2408543) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSelectedClusterTruncation.test.tsx (6 tests) 264ms
(node:2408615) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/usePanesParam.test.tsx (7 tests) 66ms
(node:2408623) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/WorkbenchPage.scatter.test.tsx (6 tests) 256ms
(node:2408632) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRosterHooks.cacheMerge.test.tsx (2 tests) 48ms
(node:2408663) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/envelopeMetadata.test.ts (10 tests) 15ms
(node:2408671) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRecognitionPolling.test.ts (12 tests) 11ms
(node:2408739) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaStats.test.tsx (2 tests) 193ms
(node:2408748) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts (33 tests) 33ms
(node:2408756) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ClusterPanelContext.test.tsx (5 tests) 243ms
(node:2408785) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/rosterRoute.test.ts (13 tests) 26ms
(node:2408797) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/adminUrls.test.ts (6 tests) 147ms
(node:2408872) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/decodeHtmlEntities.test.ts (10 tests) 13ms
(node:2408883) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAnalyzeCta.test.tsx (8 tests) 202ms
(node:2408891) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncTrigger.test.tsx (5 tests) 67ms
stderr | js/admin/hooks/__tests__/useSyncTrigger.test.tsx > useSyncTrigger > triggers once when stale if auto-trigger is explicitly enabled
A component suspended inside an `act` scope, but the `act` call was not awaited. When testing React components that depend on asynchronous data, you must await the result:

await act(() => ...)

(node:2408922) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewQueries.test.tsx (2 tests) 139ms
(node:2408936) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DashboardRecentActivitySection.test.tsx (6 tests) 147ms
(node:2409015) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/scanApiBatching.test.ts (6 tests) 17ms
(node:2409023) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/identitySuggestionMappers.test.ts (5 tests) 11ms
(node:2409031) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobStateMachineProgress.test.ts (10 tests) 13ms
(node:2409039) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts (3 tests) 15ms
(node:2409070) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterMutations.test.tsx (1 test) 60ms
(node:2409078) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeProgress.test.tsx (3 tests) 134ms
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

(node:2409155) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterActions.offline.test.tsx (3 tests) 200ms
(node:2409164) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > shows the close-match count before any write and uses the canonical term
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > surfaces an explicit truncation signal when more than 25 qualify
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > keeps a single accent primary on the confirm control
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx (6 tests) 284ms
stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > confirm and skip call the matching callbacks; Esc uses onOpenChange
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

(node:2409194) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobCoordination.test.ts (6 tests) 67ms
(node:2409206) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/buildDashboardPriorityModel.test.ts (24 tests) 17ms
(node:2409258) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobPersistence.test.ts (7 tests) 59ms
(node:2409313) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobStateMachineUtils.test.ts (6 tests) 10ms
(node:2409390) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.labelPanelReachable.test.tsx (2 tests) 150ms
(node:2409436) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DescribePanel.test.tsx (8 tests) 199ms
(node:2409446) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.filters.test.tsx (2 tests) 185ms
(node:2409521) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.tombstones.test.ts (4 tests) 9ms
(node:2409529) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/GuidanceCard.test.tsx (6 tests) 135ms
(node:2409537) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/menuHeadingParity.test.ts (6 tests) 9ms
(node:2409567) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/rosterEntryContract.test.ts (2 tests) 8ms
(node:2409577) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useAriaAnnounce.test.tsx (2 tests) 62ms
(node:2409606) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/OrientationCard.test.tsx (6 tests) 243ms
(node:2409656) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.labelAnnounce.test.tsx (1 test) 129ms
(node:2409664) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.queueFilter.test.tsx (2 tests) 131ms
(node:2409694) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/LightboxNameFace.test.tsx (4 tests) 251ms
(node:2409704) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx (3 tests) 302ms
(node:2409777) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/appQueryClient.test.ts (5 tests) 24ms
(node:2409786) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/__tests__/query-conditions.test.ts (3 tests) 12ms
(node:2409797) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/degradedModeBannerLogic.vocabularySource.test.ts (10 tests) 10ms
(node:2409828) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ConfirmTabContent.test.tsx (3 tests) 177ms
(node:2409843) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/StepMap.test.tsx (3 tests) 174ms
(node:2409914) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts (7 tests) 11ms
(node:2409944) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/pageHeadingBoundary.test.ts (6 tests) 8ms
(node:2409952) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/mediaFooterCtaState.test.ts (7 tests) 10ms
(node:2409982) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/snapshotContract.test.ts (2 tests) 8ms
(node:2409993) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/name-face-surface.test.ts (4 tests) 206ms
(node:2410043) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useScrollRestoration.test.ts (4 tests) 39ms
(node:2410092) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/InlineSuggestionPrompt.test.tsx (7 tests) 180ms
(node:2410101) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx (3 tests) 115ms
(node:2410129) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/settingsResponseContract.test.ts (2 tests) 8ms
(node:2410142) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/review-queue-styles.test.ts (4 tests) 16ms
(node:2410171) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/retention/__tests__/AuditTimeline.emptyState.test.tsx (5 tests) 193ms
(node:2410223) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeMedia.test.tsx (3 tests) 195ms
(node:2410232) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx (1 test) 84ms
(node:2410240) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ownedGettextLiterals.test.ts (1 test) 139ms
(node:2410270) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/normalizeTopUnlabeledRepresentative.test.ts (4 tests) 10ms
(node:2410300) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncStatus.test.tsx (2 tests) 46ms
(node:2410348) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineDerivedState.test.ts (2 tests) 29ms
(node:2410357) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/workbenchMediaApi.test.ts (3 tests) 11ms
(node:2410389) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/routeHelpers.test.ts (9 tests) 13ms
(node:2410419) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/workbenchMediaDetailContract.test.ts (3 tests) 11ms
(node:2410427) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useTabParam.test.tsx (4 tests) 55ms
(node:2410476) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/workbenchQueueUrl.test.ts (4 tests) 10ms
(node:2410507) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/registerConfig.test.ts (3 tests) 12ms
(node:2410515) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/degradedModeBannerLogic.test.ts (6 tests) 9ms
(node:2410523) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchFilters.rqDoubleWrite.test.tsx (4 tests) 54ms
(node:2410557) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/AdvancedDrawer.test.tsx (2 tests) 181ms
(node:2410589) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/context/__tests__/ToastContext.test.tsx (1 test) 201ms
(node:2410640) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncOffline.test.ts (4 tests) 33ms
(node:2410648) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useBulkRetryOperations.test.tsx (2 tests) 44ms
(node:2410656) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/userFacingError.test.ts (3 tests) 7ms
(node:2410686) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ReviewSurfaceContext.wiring.test.tsx (1 test) 70ms
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

(node:2410696) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/deriveIdentitiesPresentationSource.test.ts (4 tests) 9ms
(node:2410747) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/topUnlabeledClustersContract.test.ts (2 tests) 7ms
(node:2410776) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.emptyState.test.tsx (1 test) 147ms
(node:2410784) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterActions.test.tsx (4 tests) 165ms
(node:2410815) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/UserFacingErrorNotice.test.tsx (2 tests) 106ms
(node:2410826) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/MergeSurvivorContext.test.tsx (3 tests) 40ms
(node:2410872) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterMediaMap.test.ts (2 tests) 34ms
(node:2410902) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/radio-group-styles.test.ts (4 tests) 8373ms
     ✓ ships radio-group rules in the production admin CSS bundle  8365ms
(node:2411097) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaSelectionState.test.ts (2 tests) 31ms
(node:2411147) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/DebugMetricsPanel.test.tsx (3 tests) 93ms
(node:2411155) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.test.ts (6 tests) 10ms
(node:2411163) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/clusterListContract.test.ts (2 tests) 9ms
(node:2411194) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-parity.test.ts (1 test) 7ms
(node:2411202) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/scanApiError.test.ts (5 tests) 9ms
(node:2411231) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/personCommitVisibility.test.ts (4 tests) 8ms
(node:2411284) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/ConfirmDialog.test.tsx (2 tests) 223ms
(node:2411292) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchNavContext.test.tsx (1 test) 35ms
(node:2411304) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/clusterLabelsContract.test.ts (2 tests) 8ms
(node:2411333) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/FaceGroupScatter.test.tsx (5 tests) 123ms
(node:2411362) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ReviewSurfaceContext.test.tsx (2 tests) 123ms
(node:2411411) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/roster-keyboard-walk.spec.guard.test.ts (3 tests) 8ms
(node:2411420) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-one-primary.test.ts (4 tests) 12ms
(node:2411428) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/comboboxEchoOrder.contract.test.tsx (1 test) 226ms
(node:2411465) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/target-card-styles.test.ts (3 tests) 9525ms
     ✓ ships target-card rules in the production admin CSS bundle  9519ms
(node:2411783) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.expandError.test.tsx (1 test) 70ms
(node:2411820) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeReviewLink.test.tsx (4 tests) 91ms
(node:2411869) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncHealth.test.tsx (1 test) 33ms
(node:2411878) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useOverlayParam.test.tsx (1 test) 34ms
(node:2411888) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useRosterFaceCursor.test.tsx (1 test) 25ms
(node:2411916) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/settings/__tests__/healthStatus.test.ts (4 tests) 7ms
(node:2411926) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionToolbar.failure.test.tsx (2 tests) 122ms
(node:2411976) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/syncHealthContract.test.ts (1 test) 7ms
(node:2412007) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/requestTimeout.test.ts (2 tests) 8ms
(node:2412015) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterDragDrop.test.ts (1 test) 26ms
(node:2412025) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/clusterApiQueries.repairPending.test.ts (1 test) 5ms
(node:2412054) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/orientation-card-styles.test.ts (1 test) 6ms
(node:2412082) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/AnchorSelectionModal.emptyState.test.tsx (1 test) 176ms
(node:2412135) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRemoteActionGate.test.ts (2 tests) 6ms

 Test Files  231 passed (231)
      Tests  2898 passed (2898)
   Start at  15:39:30
   Duration  347.01s (transform 11.65s, setup 45.01s, import 39.89s, tests 114.99s, environment 107.69s)

```
EXIT=0
## Command 4
```
git log --oneline -1
```
```
1d27738 sandbox base (fix-febt-1-w1-machine-03deb769, history-stripped, remote-severed)
```
EXIT=0
## Command 5
```
git status --short
```
Command produced no output.
```
```
EXIT=0
## VERDICT
TYPECHECK PASS / TESTS PASS
