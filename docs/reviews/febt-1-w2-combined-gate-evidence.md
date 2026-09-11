# FEBT-1 W2 combined-gate evidence

```
86af36a2106c03ab6c74c509128f1a9182e38658
```

### 1. npm run typecheck (first attempt; missing tsc)

`cd apps/prototype-wp-alt-context && npm run typecheck ; echo "EXIT=$?"`

```
> prototype-wp-alt-context@0.0.4 typecheck
> tsc --noEmit --project tsconfig.type-check.json

EXIT=127
sh: 1: tsc: not found
```

### npm ci (explicit; required because step 1 failed on missing tsc)

`cd apps/prototype-wp-alt-context && npm ci ; echo "EXIT=$?"`

```
(node:2693062) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
npm warn deprecated abab@2.0.6: Use your platform's native atob() and btoa() methods instead
npm warn deprecated whatwg-encoding@2.0.0: Use @exodus/bytes instead for a more spec-conformant and faster implementation
npm warn deprecated domexception@4.0.0: Use your platform's native DOMException instead
npm warn deprecated node-domexception@1.0.0: Use your platform's native DOMException instead
npm warn deprecated glob@10.5.0: Old versions of glob are not supported, and contain widely publicized security vulnerabilities, which have been fixed in the current version. Please update. Support for old versions may be purchased (at exorbitant rates) by contacting i@izs.me

added 648 packages, and audited 649 packages in 10s

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

### 1. npm run typecheck (after npm ci)

`cd apps/prototype-wp-alt-context && npm run typecheck ; echo "EXIT=$?"`

```
> prototype-wp-alt-context@0.0.4 typecheck
> tsc --noEmit --project tsconfig.type-check.json

EXIT=0
```

### 3. console.* grep (production, excluding logger.ts and __tests__)

`cd apps/prototype-wp-alt-context && bash -c 'grep -rnE "console\.(log|warn|error|info|debug)" js/admin --include=*.ts --include=*.tsx | grep -v "js/admin/utils/logger.ts" | grep -v "__tests__"' ; echo "EXIT=$?"`

Expected: NO matches (grep EXIT=1).

```
EXIT=1
```

### 4. instanceof error-class grep (excluding appError.ts and http.ts)

`cd apps/prototype-wp-alt-context && bash -c 'grep -rnE "instanceof (HTTPError|ResponseParseError|AuthExpiredError|NonceRefreshFailedError|NetworkError|TimeoutError|DOMException)" js/admin --include=*.ts --include=*.tsx | grep -v "js/admin/utils/appError.ts" | grep -v "js/admin/utils/http.ts"' ; echo "EXIT=$?"`

Expected: matches ONLY inside `__tests__` files in `it(...)` test NAME strings, never as a real runtime check.

```
js/admin/utils/__tests__/retryPolicy.test.ts:212:  it('isCooldownSignal means "should open a cooldown", not instanceof HTTPError [W1-L1-09]', () => {
js/admin/utils/__tests__/http.test.ts:453:    ).rejects.toSatisfy((err: unknown) => err instanceof DOMException && err.name === 'AbortError');
js/admin/utils/__tests__/http.test.ts:479:          if (reason instanceof DOMException) {
js/admin/utils/__tests__/logger.test.ts:376:  it('does not project boundary errors via instanceof HTTPError|ResponseParseError|NonceRefreshFailedError [W2-L5]', async () => {
js/admin/utils/__tests__/recognitionCooldown.test.ts:142:    it('does not branch on instanceof HTTPError — classifier owns the class check [W2-L5][TEST-15]', async () => {
js/admin/hooks/__tests__/clusterAutoRetry.test.ts:52:  it('retries a pre-classified AppError 429 without instanceof HTTPError (E-02)', () => {
EXIT=0
```

Observer notes (not copied from other evidence files):
- All 6 hits are under `__tests__`; no production-code hit.
- Test-name-only hits: retryPolicy.test.ts:212, logger.test.ts:376, recognitionCooldown.test.ts:142, clusterAutoRetry.test.ts:52.
- Non-test-name runtime checks (test files, not production):
  - `js/admin/utils/__tests__/http.test.ts:453` — `err instanceof DOMException`
  - `js/admin/utils/__tests__/http.test.ts:479` — `if (reason instanceof DOMException)`

### 5. JOB_PROGRESS_STALL_THRESHOLD_MS grep

`cd apps/prototype-wp-alt-context && bash -c 'grep -rn "JOB_PROGRESS_STALL_THRESHOLD_MS" js/admin' ; echo "EXIT=$?"`

Expected: NO matches (EXIT=1).

```
EXIT=1
```

### 2. npx vitest run js/admin (full admin suite)

`cd apps/prototype-wp-alt-context && npx vitest run js/admin ; echo "EXIT=$?"`

```
(node:2695685) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:2695715) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)

 RUN  v4.1.5 /home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context

(node:2695754) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx (119 tests) 8582ms
     ✓ navigates with prev/next without changing index on accept (PR-54 live-queue semantics)  301ms
       ✓ DUX-W2R2-RV-05: Retry onClick is a no-op while stored-face gated and reason stays resolvable when tray collapses  315ms
(node:2695961) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx (100 tests) 3046ms
(node:2696038) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx > WorkbenchFindingsPanel > renders Avatar for a dedicated face-thumbs URL instead of FaceThumbnail
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/WorkbenchFindingsPanel.test.tsx (57 tests) 934ms
(node:2696072) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewMutations.test.tsx (50 tests) 242ms
(node:2696126) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx (62 tests) 6347ms
     ✓ announces roster loading and empty states (A11Y-24 / FIX-7)  411ms
(node:2696263) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/DescriptionHistoryPage.test.tsx (38 tests) 1539ms
(node:2696320) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useCorrectMediaAlt.test.tsx (35 tests) 2303ms
(node:2696370) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useWorkbenchFindings.test.tsx (42 tests) 388ms
(node:2696380) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/IdentityThumbnail.test.tsx (27 tests) 358ms
(node:2696432) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/banned-vocabulary.test.tsx (33 tests) 694ms
(node:2696482) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useBulkReviewCommit.test.tsx (41 tests) 170ms
(node:2696493) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx (27 tests) 952ms
(node:2696564) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx (24 tests) 2170ms
       ✓ resolves an inline prompt on every one of 60 unlabeled cards from a single batch  920ms
(node:2696618) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/DashboardPage.test.tsx (34 tests) 1100ms
(node:2696686) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/SettingsPage.test.tsx (50 tests) 899ms
(node:2696695) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.test.tsx (22 tests) 812ms
(node:2696751) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stdout | js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx > WorkbenchPage > surfaces scan errors in the UI
[alt-context/jobStateMachineMutations] scan.submit {
  requestId: '53a3fd30-54b3-4848-8d99-ad6fe1d43107',
  event: 'scan.submit',
  status: 'failed',
  failedCount: 1
}

stderr | js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx > WorkbenchPage > surfaces scan errors in the UI
[alt-context/jobStateMachineMutations] Scan submission failed { requestId: '53a3fd30-54b3-4848-8d99-ad6fe1d43107', tag: 'unknown' }

stdout | js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx > WorkbenchPage > records successful scans and invalidates identity queries
[alt-context/jobStateMachineMutations] scan.submit {
  requestId: '53a3fd30-54b3-4848-8d99-ad6fe1d43107',
  jobId: 'job-123',
  event: 'scan.submit',
  status: 'pending',
  done: 0,
  total: 1,
  failedCount: 0
}

 ✓ js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx (24 tests) 2679ms
(node:2696831) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterEntries.test.tsx (35 tests) 836ms
(node:2696884) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/reviewQueueDriver.test.ts (44 tests) 30ms
(node:2696912) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ConflictInbox.test.tsx (27 tests) 1069ms
(node:2696929) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/__tests__/DescribeRunApplyView.test.tsx (21 tests) 780ms
(node:2697000) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stdout | js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx > WorkbenchPage (integration-lite) > uses real hooks to trigger scan and invalidate identities
[alt-context/jobStateMachineMutations] scan.submit {
  requestId: '9faeb3db-abee-4f3e-9ec1-d20b5cd3970b',
  jobId: 'job-123',
  event: 'scan.submit',
  status: 'pending',
  done: 0,
  total: 1,
  failedCount: 0
}

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

 ✓ js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx (12 tests) 2016ms
     ✓ uses real hooks to trigger scan and invalidate identities  538ms
(node:2697076) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltInlineEditor.test.tsx (21 tests) 607ms
(node:2697105) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/recognitionApi.test.ts (46 tests) 48ms
(node:2697155) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx (26 tests) 1059ms
(node:2697167) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchMedia.test.tsx (10 tests) 456ms
(node:2697218) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/mediaFooterSinglePrimary.dom.test.tsx (13 tests) 1119ms
(node:2697269) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx (34 tests) 191ms
(node:2697277) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/SyncStatusIndicator.test.tsx (33 tests) 329ms
(node:2697328) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.test.ts (55 tests) 32ms
(node:2697336) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/PersonWorkspacePanel.scrubber.test.tsx (16 tests) 1231ms
(node:2697385) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSaveAction.test.tsx (24 tests) 92ms
(node:2697396) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.search.test.tsx (20 tests) 1640ms
(node:2697469) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.workspace.test.tsx (15 tests) 801ms
(node:2697498) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx (36 tests) 917ms
(node:2697548) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx > TopClusterCard > renders a dedicated face-thumb avatar when the representative carries a face-thumbs URL
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/TopClusterCard.test.tsx (27 tests) 391ms
(node:2697576) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx (32 tests) 482ms
(node:2697611) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobMachine.test.ts (199 tests) 38ms
(node:2697623) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/dashboard-uxmap-code-parity.test.ts (9 tests) 23ms
(node:2697675) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachine.test.ts (16 tests) 85ms
(node:2697683) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/http.test.ts (32 tests) 82ms
(node:2697712) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/MergeSuggestionCard.test.tsx (16 tests) 520ms
(node:2697742) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.commitExclusivity.test.tsx (10 tests) 1085ms
(node:2697794) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/Panels.test.tsx (42 tests) 374ms
(node:2697822) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchMediaContext.test.tsx (12 tests) 172ms
(node:2697852) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/describeApi.test.ts (32 tests) 25ms
(node:2697862) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx (17 tests) 1170ms
(node:2697915) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.container.test.tsx (15 tests) 770ms
(node:2697965) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.memberFix.test.tsx (17 tests) 2230ms
     ✓ BR-64: clears reserved status when creating a human name after reject, then commits  381ms
(node:2698017) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/projectionConsumerHarness.test.tsx (14 tests) 1343ms
(node:2698069) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/logger.test.ts (24 tests) 41ms
(node:2698088) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-render-parity.test.ts (14 tests) 40ms
(node:2698138) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/syncPresentation.test.ts (31 tests) 68ms
(node:2698146) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.reviewQueueUrl.test.tsx (9 tests) 1215ms
     ✓ chip click → aria-pressed=true AND rq=assignment.all.0; Next keeps it; chip again removes rq  403ms
(node:2698199) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RetentionPage.test.tsx (13 tests) 1115ms
(node:2698252) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAltInlineEditor.siblingSuccess.test.tsx (4 tests) 387ms
(node:2698296) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/PersonCommitControl.test.tsx (26 tests) 835ms
(node:2698311) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useShowAllClusterMembers.test.tsx (9 tests) 595ms
(node:2698362) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchTwoPaneLayout.test.tsx (13 tests) 268ms
(node:2698391) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaIdentities.test.tsx (8 tests) 152ms
(node:2698439) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx (11 tests) 592ms
(node:2698452) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx > SuggestionCard UXC-02 stored-reference disclosure > DUX-L8-RV-01: keeps approval blocked until the stored-face disclosure is rendered
Unknown event handler property `onLoadingStatusChange`. It will be ignored.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx (19 tests) 493ms
(node:2698502) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjectionInvalidation.test.tsx (8 tests) 379ms
(node:2698520) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/appError.test.ts (28 tests) 23ms
(node:2698560) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.reviewUrl.test.tsx (8 tests) 447ms
(node:2698573) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/hooks/__tests__/recognitionCooldownGate.test.tsx > useRecognitionCooldown observable state > reports the live window and counts remaining seconds down to idle
An update to TestComponent inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

 ✓ js/admin/hooks/__tests__/recognitionCooldownGate.test.tsx (6 tests) 239ms
(node:2698624) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.test.tsx (7 tests) 511ms
(node:2698653) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/clusterAutoRetry.test.ts (20 tests) 30ms
(node:2698684) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.test.tsx (13 tests) 419ms
(node:2698694) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineEffects.test.ts (8 tests) 366ms
(node:2698745) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx (13 tests) 252ms
(node:2698753) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx (5 tests) 505ms
(node:2698803) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
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

 ✓ js/admin/components/ui/__tests__/EmptyState.test.tsx (17 tests) 270ms
(node:2698815) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionTableBody.politeExclusivity.test.tsx (6 tests) 516ms
(node:2698864) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DashboardSyncHealthSection.test.tsx (11 tests) 462ms
(node:2698914) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterActionMutations.test.tsx (10 tests) 533ms
(node:2698924) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/retryPolicy.test.ts (27 tests) 23ms
(node:2698954) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterZeroStateReachability.test.tsx (6 tests) 345ms
(node:2698988) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.controlPaneOrder.test.tsx (9 tests) 158ms
(node:2699041) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.offline.test.tsx (12 tests) 412ms
(node:2699053) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.identitiesDegraded.test.tsx (4 tests) 551ms
(node:2699105) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/tokens/__tests__/design-tokens.test.ts (6 tests) 20ms
(node:2699114) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/JobTimeline.test.tsx (21 tests) 130ms
(node:2699168) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/__tests__/BulkDescribeCta.test.tsx > BulkDescribeCta state matrix (A11Y-24) > announces the shared recognition cooldown with its remaining window
An update to BulkDescribeProgress inside a test was not wrapped in act(...).

When testing, code that causes React state updates should be wrapped into act(...):

act(() => {
  /* fire events that update state */
});
/* assert on the output */

This ensures that you're testing the behavior the user would see in the browser. Learn more at https://react.dev/link/wrap-tests-with-act

 ✓ js/admin/pages/workbench/__tests__/BulkDescribeCta.test.tsx (12 tests) 304ms
(node:2699181) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterLabelMutations.test.tsx (6 tests) 365ms
(node:2699231) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/workbenchControlOnePrimary.dom.test.tsx (2 tests) 476ms
     ✓ counts exactly one .button-primary across labeling Done, lightbox name, and review-card commit  460ms
(node:2699258) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/buildNamingOptions.test.ts (14 tests) 20ms
(node:2699291) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/WorkbenchPage.test.tsx (16 tests) 310ms
(node:2699303) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRecognitionJobHistory.test.tsx (5 tests) 66ms
(node:2699351) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useInlineSuggestionBatch.test.tsx (8 tests) 335ms
(node:2699360) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.authExpired.test.tsx (2 tests) 187ms
(node:2699410) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/navigation/__tests__/appLinks.test.ts (14 tests) 17ms
(node:2699420) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobProgressStreamHelpers.test.ts (17 tests) 15ms
(node:2699428) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/recognitionCooldown.test.ts (20 tests) 30ms
(node:2699461) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterConfirmSuggestion.test.tsx (6 tests) 47ms
(node:2699498) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx (8 tests) 385ms
(node:2699548) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx (5 tests) 125ms
(node:2699560) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.source.test.tsx (4 tests) 169ms
(node:2699570) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/RosterPage.reviewCta.test.tsx (6 tests) 196ms
(node:2699621) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/DegradedModeBanner.test.tsx (13 tests) 174ms
(node:2699630) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.test.tsx (7 tests) 295ms
(node:2699683) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/ClusterDrawerPanel.personAware.test.tsx (9 tests) 406ms
(node:2699691) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/resolveMergeSurvivor.test.ts (10 tests) 12ms
(node:2699742) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineMutations.test.ts (4 tests) 41ms
(node:2699750) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useBulkDescribe.test.tsx (7 tests) 316ms
(node:2699804) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stdout | js/admin/hooks/__tests__/useJobProgressStream.test.tsx > useJobProgressStream > uses the latest progress when a job completes
[alt-context/hooks.jobProgressStream] stream.done {
  requestId: '5c96303e-d77b-4ab0-9997-3ffb237fc7a9',
  jobId: 'job-456',
  event: 'stream.done',
  status: 'completed',
  done: 10,
  total: 10
}

 ✓ js/admin/hooks/__tests__/useJobProgressStream.test.tsx (7 tests) 76ms
(node:2699814) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.nav03.test.tsx (1 test) 66ms
(node:2699822) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/refreshRestNonce.test.ts (12 tests) 36ms
(node:2699852) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/App.test.tsx (6 tests) 279ms
(node:2699901) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.authExpired.test.tsx (2 tests) 223ms
(node:2699949) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeRunApply.test.tsx (6 tests) 465ms
(node:2699979) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/syncVocabulary.test.ts (3 tests) 22ms
(node:2700008) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesTable.reservedLabel.test.tsx (5 tests) 756ms
(node:2700038) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterMatchAction.test.tsx (6 tests) 43ms
(node:2700087) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.dropCaches.test.ts (5 tests) 14ms
(node:2700099) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useTopUnlabeledTotal.test.tsx (8 tests) 419ms
(node:2700130) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/phasePresentation.test.ts (10 tests) 14ms
(node:2700159) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/navigation/__tests__/appLinks.guard.test.ts (2 tests) 58ms
(node:2700168) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSelectedClusterTruncation.test.tsx (6 tests) 264ms
(node:2700218) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/usePanesParam.test.tsx (7 tests) 65ms
(node:2700228) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/WorkbenchPage.scatter.test.tsx (6 tests) 246ms
(node:2700258) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRosterHooks.cacheMerge.test.tsx (2 tests) 45ms
(node:2700287) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/envelopeMetadata.test.ts (10 tests) 14ms
(node:2700295) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRecognitionPolling.test.ts (12 tests) 11ms
(node:2700325) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaStats.test.tsx (2 tests) 193ms
(node:2700355) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts (33 tests) 31ms
(node:2700365) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ClusterPanelContext.test.tsx (5 tests) 231ms
(node:2700394) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/rosterRoute.test.ts (13 tests) 26ms
(node:2700424) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/adminUrls.test.ts (6 tests) 140ms
(node:2700433) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/decodeHtmlEntities.test.ts (10 tests) 13ms
(node:2700484) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaAnalyzeCta.test.tsx (8 tests) 202ms
(node:2700494) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/hooks/__tests__/useSyncTrigger.test.tsx > useSyncTrigger > triggers once when stale if auto-trigger is explicitly enabled
A component suspended inside an `act` scope, but the `act` call was not awaited. When testing React components that depend on asynchronous data, you must await the result:

await act(() => ...)

 ✓ js/admin/hooks/__tests__/useSyncTrigger.test.tsx (5 tests) 71ms
(node:2700523) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewQueries.test.tsx (2 tests) 137ms
(node:2700552) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DashboardRecentActivitySection.test.tsx (6 tests) 141ms
(node:2700563) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/scanApiBatching.test.ts (6 tests) 16ms
(node:2700615) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/identitySuggestionMappers.test.ts (5 tests) 11ms
(node:2700625) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobStateMachineProgress.test.ts (10 tests) 13ms
(node:2700633) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts (3 tests) 15ms
(node:2700661) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useClusterMutations.test.tsx (1 test) 60ms
(node:2700691) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
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

 ✓ js/admin/pages/workbench/__tests__/BulkDescribeProgress.test.tsx (3 tests) 127ms
(node:2700720) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterActions.offline.test.tsx (3 tests) 198ms
(node:2700753) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > shows the close-match count before any write and uses the canonical term
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > surfaces an explicit truncation signal when more than 25 qualify
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > keeps a single accent primary on the confirm control
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

stderr | js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx > CloseMatchAcceptOffer (UXW2-6 slice 3) > confirm and skip call the matching callbacks; Esc uses onOpenChange
Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.

 ✓ js/admin/pages/workbench/identity-clusters/__tests__/CloseMatchAcceptOffer.test.tsx (6 tests) 279ms
(node:2700763) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobCoordination.test.ts (6 tests) 58ms
(node:2700811) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/buildDashboardPriorityModel.test.ts (24 tests) 17ms
(node:2700821) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobPersistence.test.ts (7 tests) 58ms
(node:2700849) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/jobStateMachineUtils.test.ts (6 tests) 10ms
(node:2700884) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.labelPanelReachable.test.tsx (2 tests) 154ms
(node:2700894) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/DescribePanel.test.tsx (8 tests) 203ms
(node:2700925) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelection.filters.test.tsx (2 tests) 188ms
(node:2700955) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/suggestionProjection.tombstones.test.ts (4 tests) 9ms
(node:2700984) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/GuidanceCard.test.tsx (6 tests) 132ms
(node:2701014) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/menuHeadingParity.test.ts (6 tests) 9ms
(node:2701022) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/registerConfig.test.ts (4 tests) 15ms
(node:2701051) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/rosterEntryContract.test.ts (2 tests) 9ms
(node:2701082) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/useAriaAnnounce.test.tsx (2 tests) 63ms
(node:2701090) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/dashboard/__tests__/OrientationCard.test.tsx (6 tests) 242ms
(node:2701144) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.labelAnnounce.test.tsx (1 test) 124ms
(node:2701154) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.queueFilter.test.tsx (2 tests) 132ms
(node:2701183) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/LightboxNameFace.test.tsx (4 tests) 248ms
(node:2701214) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx (3 tests) 284ms
(node:2701241) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/appQueryClient.test.ts (5 tests) 23ms
(node:2701271) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/__tests__/query-conditions.test.ts (3 tests) 12ms
(node:2701279) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/degradedModeBannerLogic.vocabularySource.test.ts (10 tests) 10ms
(node:2701311) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/UserFacingErrorNotice.test.tsx (3 tests) 119ms
(node:2701340) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ConfirmTabContent.test.tsx (3 tests) 177ms
(node:2701352) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/StepMap.test.tsx (3 tests) 170ms
(node:2701403) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts (7 tests) 11ms
(node:2701411) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/__tests__/pageHeadingBoundary.test.ts (6 tests) 8ms
(node:2701440) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/mediaFooterCtaState.test.ts (7 tests) 10ms
(node:2701469) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/snapshotContract.test.ts (2 tests) 8ms
(node:2701495) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/name-face-surface.test.ts (4 tests) 204ms
(node:2701532) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useScrollRestoration.test.ts (4 tests) 40ms
(node:2701556) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/InlineSuggestionPrompt.test.tsx (7 tests) 180ms
(node:2701564) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterPreview.test.tsx (3 tests) 112ms
(node:2701594) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/settingsResponseContract.test.ts (2 tests) 8ms
(node:2701624) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/review-queue-styles.test.ts (4 tests) 9ms
(node:2701632) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/retention/__tests__/AuditTimeline.emptyState.test.tsx (5 tests) 186ms
(node:2701687) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useDescribeMedia.test.tsx (3 tests) 193ms
(node:2701695) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ownedGettextLiterals.test.ts (1 test) 141ms
(node:2701744) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/retention/__tests__/useRetentionPageState.test.ts (1 test) 28ms
(node:2701756) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/normalizeTopUnlabeledRepresentative.test.ts (4 tests) 9ms
(node:2701784) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncStatus.test.tsx (2 tests) 44ms
(node:2701813) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useJobStateMachineDerivedState.test.ts (2 tests) 27ms
(node:2701822) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/workbenchMediaApi.test.ts (3 tests) 11ms
(node:2701851) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/routeHelpers.test.ts (9 tests) 13ms
(node:2701882) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/workbenchMediaDetailContract.test.ts (3 tests) 12ms
(node:2701891) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useTabParam.test.tsx (4 tests) 54ms
(node:2701923) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/workbenchQueueUrl.test.ts (4 tests) 9ms
(node:2701954) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/degradedModeBannerLogic.test.ts (6 tests) 9ms
(node:2701962) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useWorkbenchFilters.rqDoubleWrite.test.tsx (4 tests) 53ms
(node:2701992) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/AdvancedDrawer.test.tsx (2 tests) 176ms
(node:2702021) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/context/__tests__/ToastContext.test.tsx (1 test) 200ms
(node:2702053) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncOffline.test.ts (4 tests) 31ms
(node:2702082) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useBulkRetryOperations.test.tsx (2 tests) 42ms
(node:2702090) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/userFacingError.test.ts (3 tests) 8ms
(node:2702119) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
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

 ✓ js/admin/pages/workbench/__tests__/ReviewSurfaceContext.wiring.test.tsx (1 test) 73ms
(node:2702148) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/deriveIdentitiesPresentationSource.test.ts (4 tests) 9ms
(node:2702159) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/topUnlabeledClustersContract.test.ts (2 tests) 7ms
(node:2702193) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ScanTabContent.emptyState.test.tsx (1 test) 145ms
(node:2702221) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterActions.test.tsx (4 tests) 165ms
(node:2702249) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/MergeSurvivorContext.test.tsx (3 tests) 36ms
(node:2702278) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterMediaMap.test.ts (2 tests) 35ms
(node:2702287) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/radio-group-styles.test.ts (4 tests) 8428ms
     ✓ ships radio-group rules in the production admin CSS bundle  8420ms
(node:2702486) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useMediaSelectionState.test.ts (2 tests) 31ms
(node:2702515) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/DebugMetricsPanel.test.tsx (3 tests) 88ms
(node:2702546) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.test.ts (6 tests) 10ms
(node:2702574) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/clusterListContract.test.ts (2 tests) 8ms
(node:2702582) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-parity.test.ts (1 test) 6ms
(node:2702611) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/recognitionJobHistoryUtils.test.ts (2 tests) 7ms
(node:2702619) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/scanApiError.test.ts (5 tests) 8ms
(node:2702652) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/clusterMutationUtils.test.ts (5 tests) 9ms
(node:2702664) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/personCommitVisibility.test.ts (4 tests) 8ms
(node:2702716) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/components/ui/__tests__/ConfirmDialog.test.tsx (2 tests) 229ms
(node:2702725) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/WorkbenchNavContext.test.tsx (1 test) 34ms
(node:2702754) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/clusterLabelsContract.test.ts (2 tests) 7ms
(node:2702783) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/FaceGroupScatter.test.tsx (5 tests) 126ms
(node:2702791) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/ReviewSurfaceContext.test.tsx (2 tests) 118ms
(node:2702842) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/roster-keyboard-walk.spec.guard.test.ts (3 tests) 8ms
(node:2702851) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/__tests__/uxmap-one-primary.test.ts (4 tests) 12ms
(node:2702860) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/comboboxEchoOrder.contract.test.tsx (1 test) 231ms
(node:2702888) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/target-card-styles.test.ts (3 tests) 8572ms
     ✓ ships target-card rules in the production admin CSS bundle  8566ms
(node:2703128) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/ClusterReviewPanel.expandError.test.tsx (1 test) 71ms
(node:2703158) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/BulkDescribeReviewLink.test.tsx (4 tests) 88ms
(node:2703170) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useSyncHealth.test.tsx (1 test) 33ms
(node:2703202) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useOverlayParam.test.tsx (1 test) 34ms
(node:2703233) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useRosterFaceCursor.test.tsx (1 test) 24ms
(node:2703241) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/utils/__tests__/retryAfter.test.ts (4 tests) 7ms
(node:2703272) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/settings/__tests__/healthStatus.test.ts (4 tests) 7ms
(node:2703302) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/__tests__/MediaSelectionToolbar.failure.test.tsx (2 tests) 119ms
(node:2703331) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/__tests__/syncHealthContract.test.ts (1 test) 7ms
(node:2703361) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/requestTimeout.test.ts (2 tests) 8ms
(node:2703369) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/roster/hooks/__tests__/useClusterDragDrop.test.ts (1 test) 26ms
(node:2703397) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/api/recognition/__tests__/clusterApiQueries.repairPending.test.ts (1 test) 6ms
(node:2703405) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/styles/components/__tests__/orientation-card-styles.test.ts (1 test) 6ms
(node:2703437) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/AnchorSelectionModal.emptyState.test.tsx (1 test) 173ms
(node:2703470) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
 ✓ js/admin/hooks/__tests__/useRemoteActionGate.test.ts (2 tests) 6ms

 Test Files  236 passed (236)
      Tests  2959 passed (2959)
   Start at  17:58:20
   Duration  320.18s (transform 8.58s, setup 42.92s, import 34.97s, tests 100.29s, environment 103.78s)

EXIT=0
```

### 6. npx eslint js/admin --ext .ts,.tsx

`cd apps/prototype-wp-alt-context && npx eslint js/admin --ext .ts,.tsx ; echo "EXIT=$?"`

The `--ext` flag was accepted (no flat-config error). No retry without `--ext`.

```
(node:2705994) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:2706009) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx[24m[0m
[0m  [2m1083:23[22m  [31merror[39m  Use a ! assertion to more succinctly remove null and undefined from the type  [2m@typescript-eslint/non-nullable-type-assertion-style[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/__tests__/dashboard-uxmap-code-parity.test.ts[24m[0m
[0m  [2m246:62[22m  [31merror[39m  Unnecessary escape character: \_  [2mno-useless-escape[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.test.ts[24m[0m
[0m  [2m500:22[22m  [31merror[39m  Use the `RegExp#exec()` method instead  [2m@typescript-eslint/prefer-regexp-exec[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/api/__tests__/refreshRestNonce.test.ts[24m[0m
[0m  [2m159:33[22m  [31merror[39m  Unsafe assignment of an `any` value  [2m@typescript-eslint/no-unsafe-assignment[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/api/settingsApi.ts[24m[0m
[0m  [2m108:11[22m  [31merror[39m  "error" | "ok" | "partial" is overridden by string in this union type  [2m@typescript-eslint/no-redundant-type-constituents[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useJobStateMachineEffects.test.ts[24m[0m
[0m  [2m279:75[22m  [31merror[39m  Unsafe return of a value of type `any`  [2m@typescript-eslint/no-unsafe-return[22m[0m
[0m  [2m297:75[22m  [31merror[39m  Unsafe return of a value of type `any`  [2m@typescript-eslint/no-unsafe-return[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useMediaIdentities.test.tsx[24m[0m
[0m  [2m201:52[22m  [31merror[39m  This assertion is unnecessary since the receiver accepts the original type of the expression  [2m@typescript-eslint/no-unnecessary-type-assertion[22m[0m
[0m  [2m323:52[22m  [31merror[39m  This assertion is unnecessary since the receiver accepts the original type of the expression  [2m@typescript-eslint/no-unnecessary-type-assertion[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useWorkbenchMedia.test.tsx[24m[0m
[0m  [2m215:70[22m  [31merror[39m  This assertion is unnecessary since the receiver accepts the original type of the expression  [2m@typescript-eslint/no-unnecessary-type-assertion[22m[0m
[0m  [2m249:33[22m  [31merror[39m  Unsafe assignment of an `any` value                                                           [2m@typescript-eslint/no-unsafe-assignment[22m[0m
[0m  [2m285:52[22m  [31merror[39m  This assertion is unnecessary since the receiver accepts the original type of the expression  [2m@typescript-eslint/no-unnecessary-type-assertion[22m[0m
[0m  [2m364:65[22m  [31merror[39m  Async arrow function has no 'await' expression                                                [2m@typescript-eslint/require-await[22m[0m
[0m  [2m376:16[22m  [31merror[39m  This assertion is unnecessary since the receiver accepts the original type of the expression  [2m@typescript-eslint/no-unnecessary-type-assertion[22m[0m
[0m  [2m464:5[22m   [31merror[39m  This assertion is unnecessary since the receiver accepts the original type of the expression  [2m@typescript-eslint/no-unnecessary-type-assertion[22m[0m
[0m  [2m483:65[22m  [31merror[39m  Async arrow function has no 'await' expression                                                [2m@typescript-eslint/require-await[22m[0m
[0m  [2m548:65[22m  [31merror[39m  Async arrow function has no 'await' expression                                                [2m@typescript-eslint/require-await[22m[0m
[0m  [2m652:65[22m  [31merror[39m  Async arrow function has no 'await' expression                                                [2m@typescript-eslint/require-await[22m[0m
[0m  [2m656:32[22m  [31merror[39m  Array type using 'Array<T>' is forbidden. Use 'T[]' instead                                   [2m@typescript-eslint/array-type[22m[0m
[0m  [2m728:65[22m  [31merror[39m  Async arrow function has no 'await' expression                                                [2m@typescript-eslint/require-await[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/__tests__/DashboardPage.test.tsx[24m[0m
[0m  [2m592:30[22m  [31merror[39m  Use a ! assertion to more succinctly remove null and undefined from the type  [2m@typescript-eslint/non-nullable-type-assertion-style[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.scatter.test.tsx[24m[0m
[0m  [2m24:28[22m  [31merror[39m  This assertion is unnecessary since the receiver accepts the original type of the expression  [2m@typescript-eslint/no-unnecessary-type-assertion[22m[0m
[0m  [2m26:21[22m  [31merror[39m  This assertion is unnecessary since the receiver accepts the original type of the expression  [2m@typescript-eslint/no-unnecessary-type-assertion[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/__tests__/menuHeadingParity.test.ts[24m[0m
[0m  [2m77:35[22m  [31merror[39m  Use the `RegExp#exec()` method instead  [2m@typescript-eslint/prefer-regexp-exec[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/__tests__/pageHeadingBoundary.test.ts[24m[0m
[0m  [2m37:35[22m  [31merror[39m  Use the `RegExp#exec()` method instead  [2m@typescript-eslint/prefer-regexp-exec[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchTwoPaneLayout.tsx[24m[0m
[0m  [2m142:12[22m  [31merror[39m  This assertion is unnecessary since the receiver accepts the original type of the expression  [2m@typescript-eslint/no-unnecessary-type-assertion[22m[0m
[0m  [2m142:12[22m  [31merror[39m  Use a ! assertion to more succinctly remove null and undefined from the type                  [2m@typescript-eslint/non-nullable-type-assertion-style[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaSelection.authExpired.test.tsx[24m[0m
[0m  [2m42:6[22m  [31merror[39m  Use an `interface` instead of a `type`  [2m@typescript-eslint/consistent-type-definitions[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaSelection.identitiesDegraded.test.tsx[24m[0m
[0m  [2m55:6[22m  [31merror[39m  Use an `interface` instead of a `type`  [2m@typescript-eslint/consistent-type-definitions[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/ScanTabContent.labelPanelReachable.test.tsx[24m[0m
[0m  [2m56:43[22m  [31merror[39m  '_ref' is defined but never used  [2m@typescript-eslint/no-unused-vars[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/ScanTabContent.reviewUrl.test.tsx[24m[0m
[0m  [2m125:107[22m  [31merror[39m  '_ref' is defined but never used                             [2m@typescript-eslint/no-unused-vars[22m[0m
[0m  [2m157:30[22m   [31merror[39m  Array type using 'Array<T>' is forbidden. Use 'T[]' instead  [2m@typescript-eslint/array-type[22m[0m
[0m  [2m158:84[22m   [31merror[39m  Array type using 'Array<T>' is forbidden. Use 'T[]' instead  [2m@typescript-eslint/array-type[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/ownedGettextLiterals.test.ts[24m[0m
[0m  [2m24:6[22m  [31merror[39m  Use an `interface` instead of a `type`  [2m@typescript-eslint/consistent-type-definitions[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx[24m[0m
[0m  [2m333:10[22m  [31merror[39m  '_signal' is defined but never used  [2m@typescript-eslint/no-unused-vars[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx[24m[0m
[0m  [2m169:44[22m  [31merror[39m  '_signal' is defined but never used  [2m@typescript-eslint/no-unused-vars[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx[24m[0m
[0m  [2m13:3[22m  [31merror[39m  Expected a function expression  [2mfunc-style[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/PersonCommitControl.test.tsx[24m[0m
[0m  [2m192:33[22m  [31merror[39m  Unsafe assignment of an `any` value  [2m@typescript-eslint/no-unsafe-assignment[22m[0m
[0m  [2m213:33[22m  [31merror[39m  Unsafe assignment of an `any` value  [2m@typescript-eslint/no-unsafe-assignment[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.source.test.tsx[24m[0m
[0m  [2m12:28[22m  [31merror[39m  'NONE_REASON' is defined but never used  [2m@typescript-eslint/no-unused-vars[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx[24m[0m
[0m   [2m862:69[22m  [31merror[39m  Async arrow function has no 'await' expression  [2m@typescript-eslint/require-await[22m[0m
[0m  [2m1146:69[22m  [31merror[39m  Async arrow function has no 'await' expression  [2m@typescript-eslint/require-await[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useBulkReviewCommit.ts[24m[0m
[0m  [2m679:6[22m  [33mwarning[39m  React Hook React.useCallback has a missing dependency: 'isBulkActiveRef'. Either include it or remove the dependency array  [2mreact-hooks/exhaustive-deps[22m[0m
[0m  [2m741:5[22m  [33mwarning[39m  React Hook React.useCallback has a missing dependency: 'isBulkActiveRef'. Either include it or remove the dependency array  [2mreact-hooks/exhaustive-deps[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useInlineSuggestionBatch.ts[24m[0m
[0m  [2m43:74[22m  [31merror[39m  The following dependencies are missing in your queryKey: queryClient  [2m@tanstack/query/exhaustive-deps[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useLiveReviewTarget.ts[24m[0m
[0m   [2m34:10[22m  [31merror[39m  'unknown' overrides all other types in this union type  [2m@typescript-eslint/no-redundant-type-constituents[22m[0m
[0m  [2m132:16[22m  [31merror[39m  'unknown' overrides all other types in this union type  [2m@typescript-eslint/no-redundant-type-constituents[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/utils/__tests__/http.test.ts[24m[0m
[0m  [2m472:9[22m  [31merror[39m  Expected the Promise rejection reason to be an Error  [2m@typescript-eslint/prefer-promise-reject-errors[22m[0m
[0m[0m
[0m[4m/home/gate/grok-sandbox/feature-febt-1-deb48db9/apps/prototype-wp-alt-context/js/admin/utils/__tests__/logger.test.ts[24m[0m
[0m  [2m206:33[22m  [31merror[39m  Unsafe assignment of an `any` value  [2m@typescript-eslint/no-unsafe-assignment[22m[0m
[0m  [2m498:9[22m   [31merror[39m  Unsafe assignment of an `any` value  [2m@typescript-eslint/no-unsafe-assignment[22m[0m
[0m  [2m498:46[22m  [31merror[39m  Unsafe assignment of an `any` value  [2m@typescript-eslint/no-unsafe-assignment[22m[0m
[0m[0m
[0m[31m[1m✖ 51 problems (49 errors, 2 warnings)[22m[39m[0m
[0m[31m[1m[22m[39m[31m[1m  21 errors and 0 warnings potentially fixable with the `--fix` option.[22m[39m[0m
[0m[31m[1m[22m[39m[0m
EXIT=1
```

## Summary (this run only)

- Start HEAD: `86af36a2106c03ab6c74c509128f1a9182e38658` (this sandbox is history-stripped on `master`, not `feature/febt-1`).
- `npm ci` was run because the first typecheck printed `tsc: not found` (EXIT=127).
- Step 1 typecheck after npm ci: EXIT=0.
- Step 3 console grep: no matches, EXIT=1 (expected).
- Step 4 instanceof grep: EXIT=0, 6 hits, all under `__tests__`. Four are `it(...)` test names. Two are real runtime checks, not test names:
  - `js/admin/utils/__tests__/http.test.ts:453` — `err instanceof DOMException`
  - `js/admin/utils/__tests__/http.test.ts:479` — `if (reason instanceof DOMException)`
  No production-code hit.
- Step 5 `JOB_PROGRESS_STALL_THRESHOLD_MS` grep: no matches, EXIT=1 (expected).
- Step 2 full admin vitest: EXIT=0. `Test Files  236 passed (236)` / `Tests  2959 passed (2959)` / `Start at  17:58:20` / `Duration  320.18s`.
- Step 6 eslint `js/admin --ext .ts,.tsx`: `--ext` accepted (no retry). EXIT=1. `✖ 51 problems (49 errors, 2 warnings)`.

GATE PASS is blocked by step 4 (not only test-name matches) and by step 6. First failing step is 4, so the enum is GREP FAIL. No source edits.

## VERDICT
GREP FAIL

## Lint-gate gap (ISSUEDAG-1 docs-corrections, 2026-09-09)

Step 6 (`npx eslint js/admin --ext .ts,.tsx`) exited 1 with 49 errors / 2 warnings.
Later G1 evidence reruns tests but still supplies **no passing lint result for
the final tree**. Format/lint readiness is therefore unproven in this file.

This is a pre-existing sr-002 violation on `main` (`npm run lint` / `eslint .`
fails across files FEBT-1 never touched). Fixing it inside FEBT-1 would balloon
the branch or tempt a config relaxation (sr-001). Owner: `MAINT-lint-gate-ratchet-20260904`.
Do not read a later green vitest run as a green lint gate. Per sr-011, lint
findings are recorded `low` / deferred one wave — they do not block merge, and
they are not silently dropped.
