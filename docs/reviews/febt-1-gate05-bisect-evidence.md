# HEAD:
cf761aa8c1f3cd25c79d2e51f005f0f45fed57fc

# INSTALL:

Command:

```text
npm ci --ignore-scripts
```

Outcome (verbatim):

```text
npm warn deprecated abab@2.0.6: Use your platform's native atob() and btoa() methods instead
npm warn deprecated whatwg-encoding@2.0.0: Use @exodus/bytes instead for a more spec-conformant and faster implementation
npm warn deprecated domexception@4.0.0: Use your platform's native DOMException instead
npm warn deprecated node-domexception@1.0.0: Use your platform's native DOMException instead
npm warn deprecated glob@10.5.0: Old versions of glob are not supported, and contain widely publicized security vulnerabilities, which have been fixed in the current version. Please update. Support for old versions may be purchased (at exorbitant rates) by contacting i@izs.me

added 648 packages in 11s

173 packages are looking for funding
  run `npm fund` for details
```

Command:

```text
ls -la ./node_modules/.bin/vitest
```

Outcome (verbatim):

```text
lrwxrwxrwx 1 gate gate 20 Sep  3 04:05 ./node_modules/.bin/vitest -> ../vitest/vitest.mjs
```

# STEP A — ISOLATION BASELINE:

| test name | PASS/FAIL | duration | error line if failed |
| --- | --- | --- | --- |
| `shows a friendly inline message when merge rejects a self-target request` | FAIL | 5070ms | `Error: Test timed out in 5000ms.` |
| `shows undo when merge completes and reverts on request` | PASS | 313ms | — |
| `renders face thumbnail when media_url is provided` | PASS | 119ms | — |
| `allows clicking the unlabeled text to start editing` | PASS | 236ms | — |
| `allows unlinking an identity (wrong person) only for singletons` | PASS | 302ms | — |
| `allows splitting a cluster` | PASS | 277ms | — |
| `issues exactly one batched suggestions fetch at projection depth for N unlabeled cards` | PASS | 121ms | — |
| `resolves an inline prompt on every one of 60 unlabeled cards from a single batch` | PASS | 1.24s | — |
| `renders nothing for an identity absent from the keyed envelope (empty-match)` | PASS | 167ms | — |

Vitest treats `-t` as a regular expression. The two mandated commands whose names contain
parentheses selected no tests. They were repeated with the parentheses escaped so that the
named tests actually ran:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx -t "allows unlinking an identity \\(wrong person\\) only for singletons"
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx -t "renders nothing for an identity absent from the keyed envelope \\(empty-match\\)"
```

The first named failure has a standalone defect because it times out in isolation. It was
excluded from the positions 1–14 prefix bisect as directed, but it was then measured as the
immediate predecessor of the first solo-passing probe.

# STEP B — BISECT ROUNDS:

Probe P: `shows undo when merge completes and reverts on request`.

## Round 1

Command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx -t 'renders placeholder when no identities exist|BR-46: list renders when labelMatches includes a null-label summary|renders an unavailable warning when identity data cannot be loaded|S3-T6 a11y: unavailable affordance is a polite live region with named Retry control|BR-05: renders a distinct "reachable but erroring" warning for endpoint_error, not a confident empty|BR-09: an empty local projection reads as "not synced yet", not a confident "none detected"|keeps backend-fallback clusters labelable while hiding local-only corrective actions|shows undo when merge completes and reverts on request'
```

Included names:

1. `renders placeholder when no identities exist`
2. `BR-46: list renders when labelMatches includes a null-label summary`
3. `renders an unavailable warning when identity data cannot be loaded`
4. `S3-T6 a11y: unavailable affordance is a polite live region with named Retry control`
5. `BR-05: renders a distinct "reachable but erroring" warning for endpoint_error, not a confident empty`
6. `BR-09: an empty local projection reads as "not synced yet", not a confident "none detected"`
7. `keeps backend-fallback clusters labelable while hiding local-only corrective actions`
8. P

Probe result: PASS.

Verbatim result tail:

```text
 Test Files  1 passed (1)
      Tests  8 passed | 16 skipped (24)
   Start at  04:07:16
   Duration  2.72s (transform 1.12s, setup 235ms, import 1.47s, tests 411ms, environment 441ms)
```

## Round 2

Command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx -t 'does not render pin plumbing on the cluster preview \(UXA-07\)|allows renaming a manually labeled cluster|renames auto-labeled clusters to new label|shows identity suggestions in the overlay|uses search to find cluster by label when saving to an existing label|treats a self-match returned by label lookup as a rename|merges into existing cluster when label matches|shows undo when merge completes and reverts on request'
```

Included names:

1. `does not render pin plumbing on the cluster preview (UXA-07)`
2. `allows renaming a manually labeled cluster`
3. `renames auto-labeled clusters to new label`
4. `shows identity suggestions in the overlay`
5. `uses search to find cluster by label when saving to an existing label`
6. `treats a self-match returned by label lookup as a rename`
7. `merges into existing cluster when label matches`
8. P

Probe result: PASS.

Verbatim result tail:

```text
 Test Files  1 passed (1)
      Tests  8 passed | 16 skipped (24)
   Start at  04:07:26
   Duration  3.09s (transform 1.14s, setup 233ms, import 1.48s, tests 768ms, environment 440ms)
```

## Round 3

Command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx -t 'renders placeholder when no identities exist|BR-46: list renders when labelMatches includes a null-label summary|renders an unavailable warning when identity data cannot be loaded|S3-T6 a11y: unavailable affordance is a polite live region with named Retry control|BR-05: renders a distinct "reachable but erroring" warning for endpoint_error, not a confident empty|BR-09: an empty local projection reads as "not synced yet", not a confident "none detected"|keeps backend-fallback clusters labelable while hiding local-only corrective actions|does not render pin plumbing on the cluster preview \(UXA-07\)|allows renaming a manually labeled cluster|renames auto-labeled clusters to new label|shows identity suggestions in the overlay|uses search to find cluster by label when saving to an existing label|treats a self-match returned by label lookup as a rename|merges into existing cluster when label matches|shows undo when merge completes and reverts on request'
```

Included names: declaration positions 1–14, followed by P. The standalone-failing test at
position 15 was not selected.

Probe result: PASS.

Verbatim result tail:

```text
 Test Files  1 passed (1)
      Tests  15 passed | 9 skipped (24)
   Start at  04:08:14
   Duration  3.11s (transform 1.09s, setup 297ms, import 1.35s, tests 856ms, environment 442ms)
```

## Round 4

Command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx -t 'shows a friendly inline message when merge rejects a self-target request|shows undo when merge completes and reverts on request'
```

Included names:

1. Q: `shows a friendly inline message when merge rejects a self-target request`
2. P

Probe result: FAIL (`shows undo when merge completes and reverts on request` timed out in
5010ms). This is the smallest measured predecessor set and identifies the immediately
preceding test as Q.

# STEP C — CONFIRMATION:

Pair command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx -t 'shows a friendly inline message when merge rejects a self-target request|shows undo when merge completes and reverts on request'
```

Verbatim pair-run tail:

```text
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx (24 tests | 2 failed | 22 skipped) 10087ms
     × shows a friendly inline message when merge rejects a self-target request 5072ms
     × shows undo when merge completes and reverts on request 5010ms

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 2 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > shows a friendly inline message when merge rejects a self-target request
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:747:3
    745|   });
    746|
    747|   it('shows a friendly inline message when merge rejects a self-target…
       |   ^
    748|     (api.mergeCluster as Mock).mockRejectedValueOnce(
    749|       new Error(

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/2]⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > shows undo when merge completes and reverts on request
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:798:3
    796|   });
    797|
    798|   it('shows undo when merge completes and reverts on request', async (…
       |   ^
    799|     const mergeDeferred = createDeferred<unknown>();
    800|     const revertDeferred = createDeferred<unknown>();

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[2/2]⎯


 Test Files  1 failed (1)
      Tests  2 failed | 22 skipped (24)
   Start at  04:07:42
   Duration  12.29s (transform 992ms, setup 233ms, import 1.35s, tests 10.09s, environment 448ms)
```

Solo re-run command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx -t "shows undo when merge completes and reverts on request"
```

Verbatim solo re-run tail:

```text
 Test Files  1 passed (1)
      Tests  1 passed | 23 skipped (24)
   Start at  04:08:21
   Duration  2.59s (transform 1.10s, setup 236ms, import 1.43s, tests 299ms, environment 453ms)
```

# OBSERVED MECHANISM:

Q configures `mergeCluster` to reject, drives the fake-timer-backed interaction, and then
waits for an alert that never appears in this checkout:

```text
  it('shows a friendly inline message when merge rejects a self-target request', async () => {
    (api.mergeCluster as Mock).mockRejectedValueOnce(
      new Error(
        'Request to /recognition/clusters/cluster-1/merge failed (400): {"code":"invalid_target_cluster_id","message":"Source and target cluster IDs must differ."}',
      ),
    );
```

```text
    await runWithTimers(() => user.click(getSaveButton()));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'That group is already named Existing Label - nothing to merge.',
      );
    });
```

The teardown attempts to settle shared query/deferred/timer state inside additional `act`
calls before switching back to real timers and cleaning up:

```text
  afterEach(async () => {
    // Cancel in-flight queries to prevent async leaks between tests
    if (activeQueryClient) {
      await activeQueryClient.cancelQueries();
      activeQueryClient.clear();
      activeQueryClient = null;
    }

    await actFlow(async () => {
      await resolveFindClusterDeferreds(null);
    });
    await act(async () => {
      await vi.runAllTimersAsync();
      await Promise.resolve();
    });
    vi.useRealTimers();
    cleanup();
  });
```

Hypothesis only: Q times out with an unfinished `waitFor`/`act` chain. Its teardown does not
fully neutralize that chain, as evidenced by the overlapping-`act()` warnings in both Q and
P during the pair run. P then times out, despite passing both alone and after all tests in
positions 1–14. No fix was applied or tested.

# VERDICT:
ISOLATION LEAK CONFIRMED — poisoner is shows a friendly inline message when merge rejects a self-target request
