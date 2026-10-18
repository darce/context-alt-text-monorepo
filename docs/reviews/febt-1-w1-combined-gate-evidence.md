# FEBT-1 W1 combined-gate evidence

Verify-only gate on this checkout. No source edits. Commands run in order with `; echo "EXIT=$?"` appended.

## Command 1

`git log --oneline -1 ; echo "EXIT=$?"`

```
dee5bda sandbox base (feature-febt-1-deb48db9, history-stripped, remote-severed)
EXIT=0
```

EXIT=0

## Command 2

`cd apps/prototype-wp-alt-context && npm ci ; echo "EXIT=$?"`

```
(node:2464712) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
npm warn deprecated abab@2.0.6: Use your platform's native atob() and btoa() methods instead
npm warn deprecated whatwg-encoding@2.0.0: Use @exodus/bytes instead for a more spec-conformant and faster implementation
npm warn deprecated domexception@4.0.0: Use your platform's native DOMException instead
npm warn deprecated node-domexception@1.0.0: Use your platform's native DOMException instead
npm warn deprecated glob@10.5.0: Old versions of glob are not supported, and contain widely publicized security vulnerabilities, which have been fixed in the current version. Please update. Support for old versions may be purchased (at exorbitant rates) by contacting i@izs.me

added 648 packages, and audited 649 packages in 11s

173 packages are looking for funding
  run `npm fund` for details

12 vulnerabilities (2 low, 1 moderate, 9 high)

To address all issues, run:
  npm audit fix

Run `npm audit` for details.
npm warn allow-scripts 4 packages have install scripts not yet covered by allowScripts:
npm warn allow-scripts   @parcel/watcher@2.5.6 (install: node scripts/build-from-source.js)
npm warn allow-scripts   es5-ext@0.10.64 (postinstall:  node -e "try{require('./_postinstall')}catch(e){}" || exit 0)
npm warn allow-scripts   esbuild@0.27.7 (postinstall: node install.js)
npm warn allow-scripts   msw@2.13.6 (postinstall: node -e "import('./config/scripts/postinstall.js').catch(() => void 0)")
npm warn allow-scripts
npm warn allow-scripts Run `npm install-scripts ls` to review, or `npm install-scripts approve <pkg>` to allow.
EXIT=0
```

EXIT=0

## Command 3

`cd apps/prototype-wp-alt-context && npm run typecheck ; echo "EXIT=$?"`

```

> prototype-wp-alt-context@0.0.4 typecheck
> tsc --noEmit --project tsconfig.type-check.json

EXIT=0
```

EXIT=0

## Command 4

`cd apps/prototype-wp-alt-context && npx vitest run js/admin ; echo "EXIT=$?"`

```
(node:2466361) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:2466386) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)

 RUN  v4.1.5 /home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context

(node:2466450) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx (119 tests) 9495ms
     ✓ BR-16: undo before navigate yields 0 POSTs  324ms
     ✓ BR-15: accept A, next to B (flush), accept B → 2 POSTs order preserved; held card disabled only  376ms
       ✓ DUX-W2R2-RV-05: Retry onClick is a no-op while stored-face gated and reason stays resolvable when tray collapses  330ms
(node:2466876) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx (100 tests) 3422ms
(node:2467152) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx > WorkbenchFindingsPanel > renders Avatar for a dedicated face-thumbs URL instead of FaceThumbnail
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx (57 tests) 1339ms
(node:2467248) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewMutations.test.tsx (50 tests) 242ms
(node:2467256) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx (59 tests) 6136ms
     ✓ announces roster loading and empty states (A11Y-24 / FIX-7)  411ms
(node:2467400) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/DescriptionHistoryPage.test.tsx (38 tests) 1556ms
(node:2467455) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useCorrectMediaAlt.test.tsx (35 tests) 2308ms
(node:2467532) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useWorkbenchFindings.test.tsx (42 tests) 389ms
(node:2467564) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/IdentityThumbnail.test.tsx (27 tests) 366ms
(node:2467614) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/banned-vocabulary.test.tsx (33 tests) 703ms
(node:2467669) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useBulkReviewCommit.test.tsx (41 tests) 170ms
(node:2467678) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx (27 tests) 947ms
(node:2467729) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx (24 tests) 2215ms
       ✓ resolves an inline prompt on every one of 60 unlabeled cards from a single batch  947ms
(node:2467805) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/DashboardPage.test.tsx (34 tests) 1932ms
(node:2467905) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/SettingsPage.test.tsx (50 tests) 911ms
(node:2467936) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.test.tsx (22 tests) 1300ms
(node:2468003) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx > WorkbenchPage > surfaces scan errors in the UI
Scan submission failed Error: Scan failed
    at Object.mutate (/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx:263:30)
    at /home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts:179:20
    at handleScanFaces (/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAnalyzeCta.tsx:39:5)
    at executeDispatch (/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19116:9)
    at runWithFiberInDEV (/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:874:13)
    at processDispatchQueue (/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19166:19)
    at /home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19767:9
    at batchedUpdates$1 (/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:3255:40)
    at dispatchEventForPluginEventSystem (/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:19320:7)
    at dispatchEvent (/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/node_modules/react-dom/cjs/react-dom-client.development.js:23585:11)

 ✓ js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx (24 tests) 3048ms
     ✓ updates media page size through URL-backed filters  480ms
(node:2468079) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterEntries.test.tsx (35 tests) 816ms
(node:2468133) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/reviewQueueDriver.test.ts (44 tests) 31ms
(node:2468184) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ConflictInbox.test.tsx (27 tests) 1798ms
(node:2468240) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/__tests__/DescribeRunApplyView.test.tsx (21 tests) 734ms
(node:2468250) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx (12 tests) 2584ms
     ✓ uses real hooks to trigger scan and invalidate identities  515ms
(node:2468344) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltInlineEditor.test.tsx (21 tests) 603ms
(node:2468406) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/recognitionApi.test.ts (46 tests) 48ms
(node:2468415) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx (26 tests) 1034ms
(node:2468472) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchMedia.test.tsx (10 tests) 460ms
(node:2468523) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/mediaFooterSinglePrimary.dom.test.tsx (13 tests) 1186ms
(node:2468602) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx (34 tests) 363ms
(node:2468611) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/SyncStatusIndicator.test.tsx (33 tests) 883ms
(node:2468663) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts (55 tests) 33ms
(node:2468693) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/PersonWorkspacePanel.scrubber.test.tsx (16 tests) 1502ms
(node:2468770) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSaveAction.test.tsx (24 tests) 90ms
(node:2468786) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.search.test.tsx (20 tests) 2261ms
     ✓ rejects cluster-7 without calling createPerson and shows reserved message  393ms
     ✓ creates Pat Rivera via createPerson (human-label control)  332ms
(node:2469166) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.workspace.test.tsx (15 tests) 1783ms
     ✓ [PAG-M3-S2] restores the default workspace after ?person= is set then cleared  449ms
(node:2472093) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx (36 tests) 977ms
(node:2472164) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx > TopClusterCard > renders a dedicated face-thumb avatar when the representative carries a face-thumbs URL
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx (27 tests) 1195ms
     ✓ renders Avatar data-missing when the representative has no usable image data  304ms
(node:2472384) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx (32 tests) 543ms
(node:2472642) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobMachine.test.ts (199 tests) 98ms
(node:2472692) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/dashboard-uxmap-code-parity.test.ts (9 tests) 23ms
(node:2472704) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/http.test.ts (32 tests) 221ms
(node:2472796) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachine.test.ts (16 tests) 185ms
(node:2472881) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/MergeSuggestionCard.test.tsx (16 tests) 3458ms
     ✓ renders labels and similarity for merge review  392ms
     ✓ disables actions while pending and calls handlers when active  355ms
     ✓ passes human label to onOpenOriginal lightbox payload  338ms
     ✓ BR-35: queue ordinal makes co-rendered equal-match cards unique in group/Yes/face accnames  472ms
(node:2473122) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.commitExclusivity.test.tsx (10 tests) 4509ms
     ✓ [TEST-06] headline: generate draft, save different text via editor, Accept refuses and keeps operator text  1660ms
     ✓ mirror: Accept a draft, then inline editor open buffer refuses to overwrite  353ms
     ✓ in-flight exclusivity: editor save pending disables Suggest Accept; settles re-enables  370ms
     ✓ discrimination: normal inline save with no interleaved commit still writes and announces  419ms
     ✓ discrimination: after Suggest refusal, Dismiss then regenerate+Accept succeeds  652ms
     ✓ discrimination: after editor refusal, Cancel then re-edit+Save succeeds  432ms
(node:2473357) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/Panels.test.tsx (42 tests) 1293ms
(node:2473511) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchMediaContext.test.tsx (12 tests) 520ms
(node:2473735) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/describeApi.test.ts (32 tests) 35ms
(node:2473882) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx (17 tests) 4793ms
     ✓ renders FaceThumbnail for croppable instances, not a raw 96px img  786ms
     ✓ opens FaceLightbox when a croppable thumbnail button is clicked  451ms
     ✓ resets lightbox when entry person identity changes  305ms
     ✓ resets lightbox when person_uuid collides with prior entry id  544ms
     ✓ closes lightbox via dialog close affordance and allows reopen  913ms
     ✓ renders distinct ordinal accessible names for multi-group evidence  412ms
(node:2474954) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.container.test.tsx (15 tests) 1865ms
(node:2475190) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.memberFix.test.tsx (17 tests) 3045ms
     ✓ fires exactly one reassign call with the picked target (rg-002)  354ms
     ✓ rejects cluster-7 without calling onCommitCluster and shows reserved message  418ms
     ✓ commits Pat Rivera via onCommitCluster (human-label control)  380ms
     ✓ BR-64: clears reserved status when creating a human name after reject, then commits  455ms
(node:2475312) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/projectionConsumerHarness.test.tsx (14 tests) 1374ms
(node:2475562) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-render-parity.test.ts (14 tests) 46ms
(node:2475651) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/logger.test.ts (22 tests) 35ms
(node:2475677) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/syncPresentation.test.ts (31 tests) 65ms
(node:2475706) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.reviewQueueUrl.test.tsx (9 tests) 1243ms
     ✓ chip click → aria-pressed=true AND rq=assignment.all.0; Next keeps it; chip again removes rq  406ms
(node:2475737) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RetentionPage.test.tsx (13 tests) 1083ms
(node:2475847) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltInlineEditor.siblingSuccess.test.tsx (4 tests) 380ms
(node:2475960) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/PersonCommitControl.test.tsx (26 tests) 949ms
(node:2476313) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useShowAllClusterMembers.test.tsx (9 tests) 702ms
(node:2477505) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchTwoPaneLayout.test.tsx (13 tests) 329ms
(node:2477553) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaIdentities.test.tsx (8 tests) 208ms
(node:2477766) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx > SuggestionCard UXC-02 stored-reference disclosure > DUX-L8-RV-01: keeps approval blocked until the stored-face disclosure is rendered
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx (19 tests) 509ms
(node:2477796) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjectionInvalidation.test.tsx (8 tests) 469ms
(node:2477873) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/appError.test.ts (28 tests) 67ms
(node:2477936) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.reviewUrl.test.tsx (8 tests) 910ms
     ✓ opening review persists panel=review&cluster=<id> in the URL  379ms
(node:2477995) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/recognitionCooldownGate.test.tsx (6 tests) 656ms
     ✓ suspends all six gated pollers for the whole window, then resumes at expiry without remount; sync health cadence untouched  497ms
stderr | js/admin/hooks/__tests__/recognitionCooldownGate.test.tsx > useRecognitionCooldown observable state > reports the live window and counts remaining seconds down to idle
An update to TestComponent inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2478071) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.test.tsx (7 tests) 814ms
(node:2478121) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.test.tsx (13 tests) 882ms
(node:2478238) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineEffects.test.ts (8 tests) 504ms
(node:2478283) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx (13 tests) 329ms
(node:2478349) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx (5 tests) 996ms
     ✓ does not churn the live region on rapid successive status changes [B-01]  326ms
(node:2478432) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx (9 tests) 724ms
(node:2478492) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/EmptyState.test.tsx (17 tests) 480ms
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

(node:2478552) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.politeExclusivity.test.tsx (6 tests) 554ms
     ✓ [TEST-06] co-mount: Suggest draft then editor save → exactly one polite region holds the later cue  312ms
(node:2478615) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DashboardSyncHealthSection.test.tsx (11 tests) 443ms
(node:2478679) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterActionMutations.test.tsx (10 tests) 534ms
(node:2478735) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/retryPolicy.test.ts (27 tests) 25ms
(node:2478883) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterZeroStateReachability.test.tsx (6 tests) 355ms
(node:2478939) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.controlPaneOrder.test.tsx (9 tests) 158ms
(node:2478951) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/clusterAutoRetry.test.ts (17 tests) 27ms
(node:2478999) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.offline.test.tsx (12 tests) 451ms
(node:2479053) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.identitiesDegraded.test.tsx (4 tests) 565ms
(node:2479110) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/tokens/__tests__/design-tokens.test.ts (6 tests) 44ms
(node:2479140) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/JobTimeline.test.tsx (21 tests) 264ms
(node:2479172) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeCta.test.tsx (12 tests) 254ms
stderr | js/admin/pages/workbench/__tests__/BulkDescribeCta.test.tsx > BulkDescribeCta state matrix (A11Y-24) > announces the shared recognition cooldown with its remaining window
An update to BulkDescribeProgress inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2479182) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterLabelMutations.test.tsx (6 tests) 379ms
(node:2479284) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/workbenchControlOnePrimary.dom.test.tsx (2 tests) 489ms
     ✓ counts exactly one .button-primary across labeling Done, lightbox name, and review-card commit  474ms
(node:2479343) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/buildNamingOptions.test.ts (14 tests) 19ms
(node:2479387) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/WorkbenchPage.test.tsx (16 tests) 316ms
(node:2479480) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRecognitionJobHistory.test.tsx (5 tests) 120ms
(node:2479530) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useInlineSuggestionBatch.test.tsx (8 tests) 329ms
(node:2479543) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.authExpired.test.tsx (2 tests) 190ms
(node:2479615) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/navigation/__tests__/appLinks.test.ts (14 tests) 16ms
(node:2479679) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobProgressStreamHelpers.test.ts (17 tests) 15ms
(node:2479734) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterConfirmSuggestion.test.tsx (6 tests) 47ms
(node:2479784) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx (8 tests) 468ms
(node:2480536) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.source.test.tsx (4 tests) 198ms
(node:2480577) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.reviewCta.test.tsx (6 tests) 213ms
(node:2480606) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/DegradedModeBanner.test.tsx (13 tests) 164ms
(node:2480759) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.test.tsx (7 tests) 308ms
(node:2480808) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.personAware.test.tsx (9 tests) 845ms
     ✓ assigned cluster: Open person review deep-links to the roster person workspace  437ms
(node:2480847) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/recognitionCooldown.test.ts (18 tests) 38ms
(node:2480887) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/resolveMergeSurvivor.test.ts (10 tests) 12ms
(node:2480921) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useBulkDescribe.test.tsx (7 tests) 342ms
(node:2480951) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobProgressStream.test.tsx (7 tests) 113ms
(node:2481030) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.nav03.test.tsx (1 test) 66ms
(node:2481082) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/App.test.tsx (6 tests) 307ms
(node:2481179) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/refreshRestNonce.test.ts (12 tests) 45ms
(node:2481196) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.authExpired.test.tsx (2 tests) 369ms
(node:2481270) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeRunApply.test.tsx (6 tests) 467ms
(node:2481282) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/syncVocabulary.test.ts (3 tests) 23ms
(node:2481333) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesTable.reservedLabel.test.tsx (5 tests) 829ms
(node:2481375) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterMatchAction.test.tsx (6 tests) 77ms
(node:2481467) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.dropCaches.test.ts (5 tests) 26ms
(node:2481499) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useTopUnlabeledTotal.test.tsx (8 tests) 431ms
(node:2481746) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/phasePresentation.test.ts (10 tests) 27ms
(node:2482291) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/navigation/__tests__/appLinks.guard.test.ts (2 tests) 633ms
     ✓ fails when any js/admin production file outside appLinks.ts contains a raw #/ hash literal  606ms
(node:2482322) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSelectedClusterTruncation.test.tsx (6 tests) 295ms
(node:2482389) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/usePanesParam.test.tsx (7 tests) 96ms
(node:2482426) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/WorkbenchPage.scatter.test.tsx (6 tests) 258ms
(node:2482482) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRosterHooks.cacheMerge.test.tsx (2 tests) 63ms
(node:2482550) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/envelopeMetadata.test.ts (10 tests) 14ms
(node:2482599) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRecognitionPolling.test.ts (12 tests) 15ms
(node:2482647) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaStats.test.tsx (2 tests) 195ms
(node:2482656) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts (33 tests) 28ms
(node:2482687) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ClusterPanelContext.test.tsx (5 tests) 252ms
(node:2482720) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/rosterRoute.test.ts (13 tests) 30ms
(node:2482747) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/adminUrls.test.ts (6 tests) 444ms
     ✓ no production producer of tab=clusters remains (grep-asserted)  412ms
(node:2482786) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/decodeHtmlEntities.test.ts (10 tests) 13ms
(node:2482816) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAnalyzeCta.test.tsx (8 tests) 216ms
(node:2482826) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncTrigger.test.tsx (5 tests) 76ms
stderr | js/admin/hooks/__tests__/useSyncTrigger.test.tsx > useSyncTrigger > triggers once when stale if auto-trigger is explicitly enabled
A component suspended inside an `act` scope, but the `act` call was not awaited. When testing React components that depend on asynchronous data, you must await the result:

await act(() => ...)

(node:2482915) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewQueries.test.tsx (2 tests) 166ms
(node:2482944) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DashboardRecentActivitySection.test.tsx (6 tests) 209ms
(node:2483043) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/scanApiBatching.test.ts (6 tests) 16ms
(node:2483081) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/identitySuggestionMappers.test.ts (5 tests) 11ms
(node:2483153) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobStateMachineProgress.test.ts (10 tests) 13ms
(node:2483182) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts (3 tests) 16ms
(node:2483193) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterMutations.test.tsx (1 test) 118ms
(node:2483250) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/__tests__/BulkDescribeProgress.test.tsx > BulkDescribeProgress a11y countdown (polite region does not re-announce every second) > keeps the announced sentence static while only the aria-hidden countdown ticks
An update to BulkDescribeProgress inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

 ✓ js/admin/pages/workbench/__tests__/BulkDescribeProgress.test.tsx (3 tests) 208ms
stderr | js/admin/pages/workbench/__tests__/BulkDescribeProgress.test.tsx > BulkDescribeProgress cooldown-vs-error precedence > prefers the paused notice over the assertive retry alert when a 429 hard error meets an armed cooldown
An update to BulkDescribeProgress inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

(node:2483317) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterActions.offline.test.tsx (3 tests) 200ms
(node:2483375) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > shows the close-match count before any write and uses the canonical term
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > surfaces an explicit truncation signal when more than 25 qualify
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx (6 tests) 280ms
stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > keeps a single accent primary on the confirm control
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > confirm and skip call the matching callbacks; Esc uses onOpenChange
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

(node:2484098) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobCoordination.test.ts (6 tests) 60ms
(node:2484157) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/buildDashboardPriorityModel.test.ts (24 tests) 18ms
(node:2484169) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobPersistence.test.ts (7 tests) 56ms
(node:2484226) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobStateMachineUtils.test.ts (6 tests) 10ms
(node:2484317) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.labelPanelReachable.test.tsx (2 tests) 147ms
(node:2484347) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DescribePanel.test.tsx (8 tests) 231ms
(node:2484385) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.filters.test.tsx (2 tests) 180ms
(node:2484465) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.tombstones.test.ts (4 tests) 10ms
(node:2484474) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/GuidanceCard.test.tsx (6 tests) 137ms
(node:2484504) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/menuHeadingParity.test.ts (6 tests) 9ms
(node:2484535) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/rosterEntryContract.test.ts (2 tests) 9ms
(node:2484559) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useAriaAnnounce.test.tsx (2 tests) 85ms
(node:2484618) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/OrientationCard.test.tsx (6 tests) 249ms
(node:2484708) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.labelAnnounce.test.tsx (1 test) 133ms
(node:2484749) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.queueFilter.test.tsx (2 tests) 228ms
(node:2484778) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/LightboxNameFace.test.tsx (4 tests) 264ms
(node:2484835) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx (3 tests) 305ms
(node:2484867) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/appQueryClient.test.ts (5 tests) 21ms
(node:2484900) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/__tests__/query-conditions.test.ts (3 tests) 12ms
(node:2484908) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/degradedModeBannerLogic.vocabularySource.test.ts (10 tests) 10ms
(node:2484958) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ConfirmTabContent.test.tsx (3 tests) 181ms
(node:2485021) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/StepMap.test.tsx (3 tests) 179ms
(node:2485102) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts (7 tests) 16ms
(node:2485142) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/pageHeadingBoundary.test.ts (6 tests) 8ms
(node:2485205) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/mediaFooterCtaState.test.ts (7 tests) 9ms
(node:2485234) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/snapshotContract.test.ts (2 tests) 8ms
(node:2485261) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/name-face-surface.test.ts (4 tests) 214ms
(node:2485312) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useScrollRestoration.test.ts (4 tests) 43ms
(node:2485321) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/InlineSuggestionPrompt.test.tsx (7 tests) 182ms
(node:2485373) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx (3 tests) 114ms
(node:2485405) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/settingsResponseContract.test.ts (2 tests) 11ms
(node:2485437) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/review-queue-styles.test.ts (4 tests) 9ms
(node:2485466) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/retention/__tests__/AuditTimeline.emptyState.test.tsx (5 tests) 195ms
(node:2485546) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeMedia.test.tsx (3 tests) 198ms
(node:2485618) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx (1 test) 83ms
(node:2485645) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ownedGettextLiterals.test.ts (1 test) 202ms
(node:2486373) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/normalizeTopUnlabeledRepresentative.test.ts (4 tests) 9ms
(node:2486430) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncStatus.test.tsx (2 tests) 83ms
(node:2486468) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineDerivedState.test.ts (2 tests) 34ms
(node:2486478) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/workbenchMediaApi.test.ts (3 tests) 10ms
(node:2486588) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/routeHelpers.test.ts (9 tests) 13ms
(node:2486654) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/workbenchMediaDetailContract.test.ts (3 tests) 12ms
(node:2486696) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useTabParam.test.tsx (4 tests) 92ms
(node:2486729) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/workbenchQueueUrl.test.ts (4 tests) 10ms
(node:2486740) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/registerConfig.test.ts (3 tests) 13ms
(node:2486798) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/degradedModeBannerLogic.test.ts (6 tests) 9ms
(node:2486856) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchFilters.rqDoubleWrite.test.tsx (4 tests) 94ms
(node:2486890) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/AdvancedDrawer.test.tsx (2 tests) 179ms
(node:2486953) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/context/__tests__/ToastContext.test.tsx (1 test) 201ms
(node:2486983) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncOffline.test.ts (4 tests) 31ms
(node:2486992) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useBulkRetryOperations.test.tsx (2 tests) 44ms
(node:2487023) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/userFacingError.test.ts (3 tests) 8ms
(node:2487031) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ReviewSurfaceContext.wiring.test.tsx (1 test) 71ms
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

(node:2487080) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/deriveIdentitiesPresentationSource.test.ts (4 tests) 8ms
(node:2487110) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/topUnlabeledClustersContract.test.ts (2 tests) 8ms
(node:2487138) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.emptyState.test.tsx (1 test) 140ms
(node:2487177) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterActions.test.tsx (4 tests) 246ms
(node:2487228) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/UserFacingErrorNotice.test.tsx (2 tests) 138ms
(node:2487301) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/MergeSurvivorContext.test.tsx (3 tests) 61ms
(node:2487317) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterMediaMap.test.ts (2 tests) 33ms
(node:2487366) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/radio-group-styles.test.ts (4 tests) 12603ms
     ✓ ships radio-group rules in the production admin CSS bundle  12595ms
(node:2487685) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaSelectionState.test.ts (2 tests) 30ms
(node:2487722) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/DebugMetricsPanel.test.tsx (3 tests) 88ms
(node:2487734) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.test.ts (6 tests) 10ms
(node:2487744) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/clusterListContract.test.ts (2 tests) 8ms
(node:2487796) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-parity.test.ts (1 test) 8ms
(node:2487804) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/scanApiError.test.ts (5 tests) 8ms
(node:2487838) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/personCommitVisibility.test.ts (4 tests) 8ms
(node:2487846) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/ConfirmDialog.test.tsx (2 tests) 259ms
(node:2487891) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchNavContext.test.tsx (1 test) 38ms
(node:2487918) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/clusterLabelsContract.test.ts (2 tests) 7ms
(node:2487966) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/FaceGroupScatter.test.tsx (5 tests) 128ms
(node:2488011) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ReviewSurfaceContext.test.tsx (2 tests) 120ms
(node:2488045) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/roster-keyboard-walk.spec.guard.test.ts (3 tests) 9ms
(node:2488064) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-one-primary.test.ts (4 tests) 15ms
(node:2488079) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/comboboxEchoOrder.contract.test.tsx (1 test) 247ms
(node:2488146) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/target-card-styles.test.ts (3 tests) 8852ms
     ✓ ships target-card rules in the production admin CSS bundle  8845ms
(node:2488393) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.expandError.test.tsx (1 test) 70ms
(node:2488429) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeReviewLink.test.tsx (4 tests) 96ms
(node:2488437) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncHealth.test.tsx (1 test) 33ms
(node:2488469) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useOverlayParam.test.tsx (1 test) 35ms
(node:2488477) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useRosterFaceCursor.test.tsx (1 test) 25ms
(node:2488547) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/retryAfter.test.ts (4 tests) 8ms
(node:2488577) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/settings/__tests__/healthStatus.test.ts (4 tests) 10ms
(node:2488587) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionToolbar.failure.test.tsx (2 tests) 123ms
(node:2488648) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/syncHealthContract.test.ts (1 test) 7ms
(node:2488814) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/requestTimeout.test.ts (2 tests) 8ms
(node:2488867) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterDragDrop.test.ts (1 test) 26ms
(node:2488914) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/clusterApiQueries.repairPending.test.ts (1 test) 5ms
(node:2488924) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/orientation-card-styles.test.ts (1 test) 6ms
(node:2488954) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/AnchorSelectionModal.emptyState.test.tsx (1 test) 181ms
(node:2488967) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRemoteActionGate.test.ts (2 tests) 6ms

 Test Files  232 passed (232)
      Tests  2929 passed (2929)
   Start at  16:15:34
   Duration  434.11s (transform 15.56s, setup 60.01s, import 57.13s, tests 132.48s, environment 134.65s)

EXIT=0
```

EXIT=0

## SEAM

Command 3 (`npm run typecheck`) completed with EXIT=0. `tsc --noEmit --project tsconfig.type-check.json` printed no errors.

Command 4 (`npx vitest run js/admin`) completed with EXIT=0. The suite printed `Test Files  232 passed (232)` and `Tests  2929 passed (2929)`. The logger suite line was `✓ js/admin/utils/__tests__/logger.test.ts (22 tests) 35ms`.

On this tree, `js/admin/utils/http.ts` still defines `HTTPError` and `ResponseParseError` with `status`, `endpoint`, and `bodyPreview`. `js/admin/utils/logger.ts` imports those classes plus `NonceRefreshFailedError` and `AppError`. `projectBoundaryError` emits `{ name, message, status, endpoint }` for `HTTPError` / `ResponseParseError` (message is `HTTP ${status}` or `JSON parse error`) and does not copy `bodyPreview`. `projectAppError` emits `{ tag, message }` plus `status`/`endpoint` when present; the `AppError` `http` variant has `status` and `endpoint`, not `bodyPreview`.

Step 3 and step 4 were both clean. The logger/http error-class seam held.

## VERDICT

Typecheck EXIT=0. js/admin vitest EXIT=0 (232 files / 2929 tests passed).

TYPECHECK PASS / TESTS PASS


## git show --stat HEAD

```
commit acda1a445b132ae41dea62e64d28fbfb507eb7f1
Author: grok-sandbox <sandbox@grok.invalid>
Date:   Wed Sep 2 16:24:37 2026 +0000

    Record FEBT-1 W1 combined-gate typecheck and vitest evidence
    
    Verify-only run of typecheck and js/admin vitest on the merged W1 tree.

 docs/reviews/febt-1-w1-combined-gate-evidence.md | 2201 ++++++++++++++++++++++
 1 file changed, 2201 insertions(+)
```

EXIT=0
