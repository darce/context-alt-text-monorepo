# FEBT-1 w1 machine verify-only evidence
Raw stdout/stderr from the verify-only pass. Outputs are unedited.
## Command 1
```
cd apps/prototype-wp-alt-context && npm ci --silent ; echo "EXIT=$?"
```
```
(node:2431652) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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
(node:2432974) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:2432987) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)

 RUN  v4.1.5 /home/gate/grok-sandbox/fix-febt-1-w1-machine-03deb769/apps/prototype-wp-alt-context

(node:2433010) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx (119 tests) 8822ms
       ✓ DUX-W2R2-RV-05: Retry onClick is a no-op while stored-face gated and reason stays resolvable when tray collapses  313ms
stderr | js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx > ReviewQueue > UXW2-6 slice 3 group accept of close matches > reuses pinned partial-failure copy when a group accept stops mid-sequence
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

(node:2433217) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx (100 tests) 3179ms
(node:2433316) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx > WorkbenchFindingsPanel > renders Avatar for a dedicated face-thumbs URL instead of FaceThumbnail
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx (57 tests) 934ms
(node:2433347) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewMutations.test.tsx (50 tests) 250ms
(node:2433397) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx (59 tests) 6167ms
     ✓ announces roster loading and empty states (A11Y-24 / FIX-7)  411ms
(node:2433543) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/DescriptionHistoryPage.test.tsx (38 tests) 1599ms
(node:2433593) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useCorrectMediaAlt.test.tsx (35 tests) 2311ms
(node:2433670) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useWorkbenchFindings.test.tsx (42 tests) 389ms
(node:2433678) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/IdentityThumbnail.test.tsx (27 tests) 367ms
(node:2433731) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/banned-vocabulary.test.tsx (33 tests) 717ms
(node:2433782) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useBulkReviewCommit.test.tsx (41 tests) 169ms
(node:2433790) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx (27 tests) 945ms
(node:2433863) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx (24 tests) 2213ms
       ✓ resolves an inline prompt on every one of 60 unlabeled cards from a single batch  930ms
(node:2433915) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/DashboardPage.test.tsx (34 tests) 1098ms
(node:2433969) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/SettingsPage.test.tsx (50 tests) 908ms
(node:2434001) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.test.tsx (22 tests) 815ms
(node:2434053) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx (24 tests) 2729ms
(node:2434153) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterEntries.test.tsx (35 tests) 806ms
(node:2434187) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/reviewQueueDriver.test.ts (44 tests) 31ms
(node:2434221) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ConflictInbox.test.tsx (27 tests) 1092ms
(node:2434250) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/__tests__/DescribeRunApplyView.test.tsx (21 tests) 807ms
(node:2434304) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx (12 tests) 2106ms
     ✓ uses real hooks to trigger scan and invalidate identities  547ms
(node:2434378) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltInlineEditor.test.tsx (21 tests) 620ms
(node:2434409) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/recognitionApi.test.ts (46 tests) 46ms
(node:2434438) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx (26 tests) 1064ms
(node:2434467) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchMedia.test.tsx (10 tests) 460ms
(node:2434519) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/mediaFooterSinglePrimary.dom.test.tsx (13 tests) 1169ms
(node:2434551) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx (34 tests) 193ms
(node:2434559) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/SyncStatusIndicator.test.tsx (33 tests) 337ms
(node:2434613) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts (55 tests) 33ms
(node:2434641) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/PersonWorkspacePanel.scrubber.test.tsx (16 tests) 1233ms
(node:2434676) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSaveAction.test.tsx (24 tests) 93ms
(node:2434706) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.search.test.tsx (20 tests) 1716ms
(node:2434758) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.workspace.test.tsx (15 tests) 821ms
(node:2434808) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx (36 tests) 981ms
(node:2434879) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx > TopClusterCard > renders a dedicated face-thumb avatar when the representative carries a face-thumbs URL
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx (27 tests) 387ms
(node:2434909) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx (32 tests) 477ms
(node:2434917) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobMachine.test.ts (199 tests) 40ms
(node:2434969) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/dashboard-uxmap-code-parity.test.ts (9 tests) 23ms
(node:2434998) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachine.test.ts (16 tests) 85ms
(node:2435008) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/MergeSuggestionCard.test.tsx (16 tests) 525ms
(node:2435036) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.commitExclusivity.test.tsx (10 tests) 1140ms
     ✓ [TEST-06] headline: generate draft, save different text via editor, Accept refuses and keeps operator text  317ms
(node:2435110) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/Panels.test.tsx (42 tests) 380ms
(node:2435120) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchMediaContext.test.tsx (12 tests) 176ms
(node:2435149) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/describeApi.test.ts (32 tests) 25ms
(node:2435157) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx (17 tests) 1168ms
(node:2435228) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.container.test.tsx (15 tests) 813ms
(node:2435260) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.memberFix.test.tsx (17 tests) 2374ms
     ✓ BR-64: clears reserved status when creating a human name after reject, then commits  409ms
     ✓ BR-64: clears reserved status when selecting an existing entry after reject, then commits  310ms
(node:2435337) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/projectionConsumerHarness.test.tsx (14 tests) 1340ms
(node:2435369) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/http.test.ts (28 tests) 75ms
(node:2435400) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-render-parity.test.ts (14 tests) 43ms
(node:2435427) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/syncPresentation.test.ts (31 tests) 74ms
(node:2435459) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.reviewQueueUrl.test.tsx (9 tests) 1260ms
     ✓ chip click → aria-pressed=true AND rq=assignment.all.0; Next keeps it; chip again removes rq  404ms
(node:2435488) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RetentionPage.test.tsx (13 tests) 1142ms
(node:2435560) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltInlineEditor.siblingSuccess.test.tsx (4 tests) 404ms
(node:2435568) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/PersonCommitControl.test.tsx (26 tests) 834ms
(node:2435602) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useShowAllClusterMembers.test.tsx (9 tests) 589ms
(node:2435676) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchTwoPaneLayout.test.tsx (13 tests) 271ms
(node:2435685) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaIdentities.test.tsx (8 tests) 148ms
(node:2435714) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx > SuggestionCard UXC-02 stored-reference disclosure > DUX-L8-RV-01: keeps approval blocked until the stored-face disclosure is rendered
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx (19 tests) 497ms
(node:2435724) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjectionInvalidation.test.tsx (8 tests) 375ms
(node:2435796) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/appError.test.ts (28 tests) 23ms
(node:2435805) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.reviewUrl.test.tsx (8 tests) 442ms
(node:2435833) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/recognitionCooldownGate.test.tsx (6 tests) 244ms
stderr | js/admin/hooks/__tests__/recognitionCooldownGate.test.tsx > useRecognitionCooldown observable state > reports the live window and counts remaining seconds down to idle
An update to TestComponent inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2435844) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.test.tsx (7 tests) 524ms
(node:2435914) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.test.tsx (13 tests) 433ms
(node:2435925) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineEffects.test.ts (8 tests) 364ms
(node:2435954) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx (13 tests) 251ms
(node:2435986) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx (5 tests) 515ms
(node:2436036) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx (9 tests) 486ms
(node:2436067) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/EmptyState.test.tsx (17 tests) 269ms
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

(node:2436077) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.politeExclusivity.test.tsx (6 tests) 501ms
(node:2436152) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DashboardSyncHealthSection.test.tsx (11 tests) 471ms
(node:2436161) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterActionMutations.test.tsx (10 tests) 534ms
(node:2436192) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterZeroStateReachability.test.tsx (6 tests) 345ms
(node:2436246) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.controlPaneOrder.test.tsx (9 tests) 153ms
(node:2436293) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.offline.test.tsx (12 tests) 443ms
(node:2436301) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.identitiesDegraded.test.tsx (4 tests) 557ms
(node:2436333) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/tokens/__tests__/design-tokens.test.ts (6 tests) 43ms
(node:2436383) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/JobTimeline.test.tsx (21 tests) 136ms
(node:2436413) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeCta.test.tsx (12 tests) 280ms
stderr | js/admin/pages/workbench/__tests__/BulkDescribeCta.test.tsx > BulkDescribeCta state matrix (A11Y-24) > announces the shared recognition cooldown with its remaining window
An update to BulkDescribeProgress inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2436445) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterLabelMutations.test.tsx (6 tests) 365ms
(node:2436456) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/workbenchControlOnePrimary.dom.test.tsx (2 tests) 509ms
     ✓ counts exactly one .button-primary across labeling Done, lightbox name, and review-card commit  492ms
(node:2436530) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/buildNamingOptions.test.ts (14 tests) 20ms
(node:2436538) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/clusterAutoRetry.test.ts (14 tests) 26ms
(node:2436546) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/WorkbenchPage.test.tsx (16 tests) 318ms
(node:2436578) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRecognitionJobHistory.test.tsx (5 tests) 69ms
(node:2436607) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useInlineSuggestionBatch.test.tsx (8 tests) 331ms
(node:2436658) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.authExpired.test.tsx (2 tests) 186ms
(node:2436668) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/navigation/__tests__/appLinks.test.ts (14 tests) 17ms
(node:2436697) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobProgressStreamHelpers.test.ts (17 tests) 15ms
(node:2436709) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterConfirmSuggestion.test.tsx (6 tests) 50ms
(node:2436757) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx (8 tests) 396ms
(node:2436789) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.source.test.tsx (4 tests) 176ms
(node:2436800) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.reviewCta.test.tsx (6 tests) 209ms
(node:2436830) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/retryPolicy.test.ts (22 tests) 16ms
(node:2436839) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/DegradedModeBanner.test.tsx (13 tests) 168ms
(node:2436909) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.test.tsx (7 tests) 297ms
(node:2436919) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.personAware.test.tsx (9 tests) 404ms
(node:2436948) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/resolveMergeSurvivor.test.ts (10 tests) 13ms
(node:2436958) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useBulkDescribe.test.tsx (7 tests) 315ms
(node:2437010) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobProgressStream.test.tsx (7 tests) 76ms
(node:2437039) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.nav03.test.tsx (1 test) 67ms
(node:2437049) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/App.test.tsx (6 tests) 279ms
(node:2437089) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/refreshRestNonce.test.ts (12 tests) 34ms
(node:2437099) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.authExpired.test.tsx (2 tests) 219ms
(node:2437169) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeRunApply.test.tsx (6 tests) 468ms
(node:2437178) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/logger.test.ts (11 tests) 23ms
(node:2437208) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/syncVocabulary.test.ts (3 tests) 23ms
(node:2437218) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesTable.reservedLabel.test.tsx (5 tests) 754ms
(node:2437289) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterMatchAction.test.tsx (6 tests) 40ms
(node:2437298) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/recognitionCooldown.test.ts (14 tests) 25ms
(node:2437319) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.dropCaches.test.ts (5 tests) 14ms
(node:2437348) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useTopUnlabeledTotal.test.tsx (8 tests) 422ms
(node:2437360) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/phasePresentation.test.ts (10 tests) 16ms
(node:2437410) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/navigation/__tests__/appLinks.guard.test.ts (2 tests) 52ms
(node:2437440) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSelectedClusterTruncation.test.tsx (6 tests) 262ms
(node:2437449) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/usePanesParam.test.tsx (7 tests) 65ms
(node:2437478) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/WorkbenchPage.scatter.test.tsx (6 tests) 257ms
(node:2437490) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRosterHooks.cacheMerge.test.tsx (2 tests) 50ms
(node:2437539) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/envelopeMetadata.test.ts (10 tests) 14ms
(node:2437571) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRecognitionPolling.test.ts (12 tests) 11ms
(node:2437579) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaStats.test.tsx (2 tests) 191ms
(node:2437608) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts (33 tests) 31ms
(node:2437618) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ClusterPanelContext.test.tsx (5 tests) 231ms
(node:2437667) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/rosterRoute.test.ts (13 tests) 27ms
(node:2437697) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/adminUrls.test.ts (6 tests) 174ms
(node:2437706) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/decodeHtmlEntities.test.ts (10 tests) 13ms
(node:2437714) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAnalyzeCta.test.tsx (8 tests) 205ms
(node:2437745) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/hooks/__tests__/useSyncTrigger.test.tsx > useSyncTrigger > triggers once when stale if auto-trigger is explicitly enabled
A component suspended inside an `act` scope, but the `act` call was not awaited. When testing React components that depend on asynchronous data, you must await the result:

await act(() => ...)

 ✓ js/admin/hooks/__tests__/useSyncTrigger.test.tsx (5 tests) 69ms
(node:2437754) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewQueries.test.tsx (2 tests) 140ms
(node:2437843) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DashboardRecentActivitySection.test.tsx (6 tests) 150ms
(node:2437851) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/scanApiBatching.test.ts (6 tests) 18ms
(node:2437859) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/identitySuggestionMappers.test.ts (5 tests) 11ms
(node:2437891) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobStateMachineProgress.test.ts (10 tests) 13ms
(node:2437900) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts (3 tests) 15ms
(node:2437950) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterMutations.test.tsx (1 test) 61ms
(node:2437981) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeProgress.test.tsx (3 tests) 136ms
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

(node:2437989) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterActions.offline.test.tsx (3 tests) 199ms
(node:2438019) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > shows the close-match count before any write and uses the canonical term
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > surfaces an explicit truncation signal when more than 25 qualify
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > keeps a single accent primary on the confirm control
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > confirm and skip call the matching callbacks; Esc uses onOpenChange
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx (6 tests) 288ms
(node:2438029) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobCoordination.test.ts (6 tests) 60ms
(node:2438101) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/buildDashboardPriorityModel.test.ts (24 tests) 17ms
(node:2438110) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobPersistence.test.ts (7 tests) 59ms
(node:2438118) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobStateMachineUtils.test.ts (6 tests) 10ms
(node:2438150) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.labelPanelReachable.test.tsx (2 tests) 153ms
(node:2438158) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DescribePanel.test.tsx (8 tests) 209ms
(node:2438208) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.filters.test.tsx (2 tests) 185ms
(node:2438242) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.tombstones.test.ts (4 tests) 9ms
(node:2438250) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/GuidanceCard.test.tsx (6 tests) 139ms
(node:2438285) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/menuHeadingParity.test.ts (6 tests) 9ms
(node:2438293) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/rosterEntryContract.test.ts (2 tests) 9ms
(node:2438345) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useAriaAnnounce.test.tsx (2 tests) 65ms
(node:2438378) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/OrientationCard.test.tsx (6 tests) 246ms
(node:2438387) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.labelAnnounce.test.tsx (1 test) 130ms
(node:2438419) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.queueFilter.test.tsx (2 tests) 133ms
(node:2438427) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/LightboxNameFace.test.tsx (4 tests) 257ms
(node:2438499) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx (3 tests) 291ms
(node:2438508) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/appQueryClient.test.ts (5 tests) 24ms
(node:2438539) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/__tests__/query-conditions.test.ts (3 tests) 12ms
(node:2438547) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/degradedModeBannerLogic.vocabularySource.test.ts (10 tests) 10ms
(node:2438555) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ConfirmTabContent.test.tsx (3 tests) 174ms
(node:2438626) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/StepMap.test.tsx (3 tests) 169ms
(node:2438634) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts (7 tests) 11ms
(node:2438642) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/pageHeadingBoundary.test.ts (6 tests) 8ms
(node:2438674) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/mediaFooterCtaState.test.ts (7 tests) 9ms
(node:2438682) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/snapshotContract.test.ts (2 tests) 7ms
(node:2438730) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/name-face-surface.test.ts (4 tests) 200ms
(node:2438764) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useScrollRestoration.test.ts (4 tests) 41ms
(node:2438772) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/InlineSuggestionPrompt.test.tsx (7 tests) 181ms
(node:2438803) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx (3 tests) 113ms
(node:2438813) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/settingsResponseContract.test.ts (2 tests) 8ms
(node:2438842) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/review-queue-styles.test.ts (4 tests) 9ms
(node:2438893) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/retention/__tests__/AuditTimeline.emptyState.test.tsx (5 tests) 190ms
(node:2438901) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeMedia.test.tsx (3 tests) 194ms
(node:2438932) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx (1 test) 84ms
(node:2438940) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ownedGettextLiterals.test.ts (1 test) 140ms
(node:2438992) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/normalizeTopUnlabeledRepresentative.test.ts (4 tests) 9ms
(node:2439022) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncStatus.test.tsx (2 tests) 46ms
(node:2439033) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineDerivedState.test.ts (2 tests) 28ms
(node:2439064) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/workbenchMediaApi.test.ts (3 tests) 11ms
(node:2439074) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/routeHelpers.test.ts (9 tests) 13ms
(node:2439084) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/workbenchMediaDetailContract.test.ts (3 tests) 12ms
(node:2439156) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useTabParam.test.tsx (4 tests) 54ms
(node:2439167) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/workbenchQueueUrl.test.ts (4 tests) 10ms
(node:2439175) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/registerConfig.test.ts (3 tests) 12ms
(node:2439206) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/degradedModeBannerLogic.test.ts (6 tests) 12ms
(node:2439214) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchFilters.rqDoubleWrite.test.tsx (4 tests) 54ms
(node:2439223) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/AdvancedDrawer.test.tsx (2 tests) 176ms
(node:2439292) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/context/__tests__/ToastContext.test.tsx (1 test) 202ms
(node:2439300) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncOffline.test.ts (4 tests) 33ms
(node:2439330) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useBulkRetryOperations.test.tsx (2 tests) 45ms
(node:2439339) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/userFacingError.test.ts (3 tests) 8ms
(node:2439347) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ReviewSurfaceContext.wiring.test.tsx (1 test) 73ms
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

(node:2439440) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/deriveIdentitiesPresentationSource.test.ts (4 tests) 8ms
(node:2439448) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/topUnlabeledClustersContract.test.ts (2 tests) 7ms
(node:2439457) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.emptyState.test.tsx (1 test) 139ms
(node:2439490) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterActions.test.tsx (4 tests) 164ms
(node:2439498) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/UserFacingErrorNotice.test.tsx (2 tests) 104ms
(node:2439571) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/MergeSurvivorContext.test.tsx (3 tests) 38ms
(node:2439579) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterMediaMap.test.ts (2 tests) 36ms
(node:2439587) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/radio-group-styles.test.ts (4 tests) 8328ms
     ✓ ships radio-group rules in the production admin CSS bundle  8321ms
(node:2439805) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaSelectionState.test.ts (2 tests) 31ms
(node:2439815) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/DebugMetricsPanel.test.tsx (3 tests) 91ms
(node:2439848) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.test.ts (6 tests) 10ms
(node:2439856) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/clusterListContract.test.ts (2 tests) 8ms
(node:2439866) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-parity.test.ts (1 test) 7ms
(node:2439941) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/scanApiError.test.ts (5 tests) 8ms
(node:2439949) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/personCommitVisibility.test.ts (4 tests) 8ms
(node:2439957) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/ConfirmDialog.test.tsx (2 tests) 224ms
(node:2439990) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchNavContext.test.tsx (1 test) 35ms
(node:2439998) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/clusterLabelsContract.test.ts (2 tests) 8ms
(node:2440029) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/FaceGroupScatter.test.tsx (5 tests) 126ms
(node:2440079) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ReviewSurfaceContext.test.tsx (2 tests) 116ms
(node:2440087) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/roster-keyboard-walk.spec.guard.test.ts (3 tests) 7ms
(node:2440097) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-one-primary.test.ts (4 tests) 12ms
(node:2440127) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/comboboxEchoOrder.contract.test.tsx (1 test) 229ms
(node:2440135) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/target-card-styles.test.ts (3 tests) 8512ms
     ✓ ships target-card rules in the production admin CSS bundle  8506ms
(node:2440353) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.expandError.test.tsx (1 test) 73ms
(node:2440382) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeReviewLink.test.tsx (4 tests) 89ms
(node:2440430) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncHealth.test.tsx (1 test) 38ms
(node:2440438) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useOverlayParam.test.tsx (1 test) 34ms
(node:2440449) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useRosterFaceCursor.test.tsx (1 test) 26ms
(node:2440477) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/settings/__tests__/healthStatus.test.ts (4 tests) 7ms
(node:2440487) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionToolbar.failure.test.tsx (2 tests) 122ms
(node:2440561) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/syncHealthContract.test.ts (1 test) 7ms
(node:2440569) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/requestTimeout.test.ts (2 tests) 8ms
(node:2440581) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterDragDrop.test.ts (1 test) 26ms
(node:2440608) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/clusterApiQueries.repairPending.test.ts (1 test) 6ms
(node:2440616) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/orientation-card-styles.test.ts (1 test) 6ms
(node:2440624) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/AnchorSelectionModal.emptyState.test.tsx (1 test) 174ms
(node:2440698) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRemoteActionGate.test.ts (2 tests) 6ms

 Test Files  231 passed (231)
      Tests  2898 passed (2898)
   Start at  15:59:48
   Duration  319.82s (transform 8.80s, setup 42.57s, import 35.13s, tests 101.18s, environment 103.00s)

```
EXIT=0
## Command 4
```
git log --oneline -1
```
```
b1c1b89 sandbox base (fix-febt-1-w1-machine-03deb769, history-stripped, remote-severed)
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
