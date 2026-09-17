FINDINGS: [{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-01","severity":"high","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/describeOperationStore.ts","line":171,"summary":"Storage failures are swallowed while the caller reports a durable context","evidence":"writeStorageItem catches every sessionStorage.setItem exception and putDescribeOperationContext still replaces the in-memory snapshot and emits subscribers; a reload then has no persisted run to resume."},{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-02","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/useBulkDescribe.ts","line":102,"summary":"Terminal runs retain a non-null active run id after the store is cleared","evidence":"retainedRunIdRef keeps the last store id for the mount, while the terminal effect clears only the store; the downstream MediaSelection currently treats any non-null runId as activity and run relevance."},{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-03","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/describeOperationStore.ts","line":46,"summary":"In-memory operation snapshots are not tenant-scoped","evidence":"runContext and suggestByMediaId are process-global, and their fast paths return cached contexts without recording or checking the tenant that populated them; changing configured tenant in the same SPA lifetime can expose the previous tenant context."},{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-04","severity":"low","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/__tests__/describeOperationStore.test.ts","line":1,"summary":"The delta changes test paths outside the declared lane ownership","evidence":"The inlined delta changes both hooks/__tests__/describeOperationStore.test.ts and hooks/__tests__/useBulkDescribe.test.tsx, but the lane-owned list contains only describeOperationStore.ts, activeDescribeRun.ts, and useBulkDescribe.ts."}]
Verdict: fail

# GPUFLOW-2 spa-operation-store review

| Scope item | Value |
| --- | --- |
| Base | `284616c05` |
| Tip | `2bb8e1121` |
| Files | `js/admin/hooks/describeOperationStore.ts`, `js/admin/hooks/activeDescribeRun.ts`, `js/admin/hooks/useBulkDescribe.ts`, plus the two changed hook test paths |

## FINDINGS

### GPUFLOW-2-SPAOPERATIONSTORE-R-01 — high

- File: `apps/prototype-wp-alt-context/js/admin/hooks/describeOperationStore.ts:161-175,303-315`
- Evidence: `writeStorageItem` catches every `sessionStorage.setItem` failure and returns no status. `putDescribeOperationContext` then updates the in-memory context and notifies subscribers as though the `(state, context)` pair were durable. `readStorageItem` likewise converts read failures into an empty store. This conflicts with the A4 reload proof and the fail-closed/silence-is-not-success rule (`GRPH-29`, `rg-015`).
- Impact: A successful submit can poll in the current mount, but navigation or reload silently loses the run when storage is unavailable. If a replacement write fails, an old key can remain and a later reload can resume the wrong run. The accepted upstream run can therefore be orphaned or mis-associated without an operator-visible error.
- Fix: Make the storage adapter return an explicit success/failure result, and either reject/degrade the operation visibly when the durable write cannot be completed or provide an explicit non-durable mode. Do not claim durable resume after a swallowed write; add throwing-storage and stale-key tests.

### GPUFLOW-2-SPAOPERATIONSTORE-R-02 — medium

- File: `apps/prototype-wp-alt-context/js/admin/hooks/useBulkDescribe.ts:97-105,119-123`
- Evidence: `retainedRunIdRef` deliberately keeps the last run id after the terminal effect clears the operation store. The A4 contract says the hook derives `runId` from the store and clears it on terminal status. The current downstream `MediaSelection` uses a non-null `runId` for activity and `isRunRelevant`, so this retained value keeps a completed run looking active to consumers.
- Impact: After completion, the same mounted workbench can continue presenting the terminal run as relevant and prevent the idle-GPU consumer from returning to its no-run behavior. This also makes the effective active-run API differ from the cleared durable store until unmount.
- Fix: Keep terminal result data separate from the active/resumable run id. Return `null` from the active run source once terminal status is observed, and let the outcome panel read the already-fetched terminal progress independently.

### GPUFLOW-2-SPAOPERATIONSTORE-R-03 — medium

- File: `apps/prototype-wp-alt-context/js/admin/hooks/describeOperationStore.ts:44-47,214-216,243-247,303-327`
- Evidence: `runContext` and `suggestByMediaId` are global process state with no tenant marker. `hydrateRunFromStorage` skips rehydration whenever the global run is non-null, and `liveSuggestContext` returns a cached media context without resolving the current tenant. A tenant-keyed storage key does not protect these in-memory fast paths after configuration changes within one SPA lifetime.
- Impact: A tenant switch or config replacement can make the next tenant poll or render the previous tenant's operation, violating the tenant-keyed boundary and potentially exposing cross-tenant operation identifiers.
- Fix: Associate every in-memory snapshot with the tenant that populated it and invalidate/re-hydrate when `getConfig().tenant_id` changes; ensure clears remove only the owning tenant slot and add a tenant-switch regression test.

### GPUFLOW-2-SPAOPERATIONSTORE-R-04 — low

- File: `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/describeOperationStore.test.ts:1`; `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useBulkDescribe.test.tsx:1`
- Evidence: Mechanical audit of the inlined delta finds these two changed paths outside the declared `spa-operation-store` owned list. The declared list contains only `describeOperationStore.ts`, `activeDescribeRun.ts`, and `useBulkDescribe.ts`.
- Impact: Sibling-owned test changes cross the lane boundary and can conflict with the test owners or obscure which lane is responsible for their review.
- Fix: Move those test changes to their owning lane, or update the task ownership manifest before merging.

## VERIFICATION

- Changed-path audit: the inlined delta contains five paths; the three production paths are owned and the two test paths are outside the declared owned list (R-04).
- Required lane test: `"$resolved_python" -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` — `1 passed`.
- Assigned Vitest proof was attempted with `apps/prototype-wp-alt-context/node_modules/.bin/vitest`; this worktree has no local Vitest dependency, so no JavaScript test pass is claimed.

## Re-review r5 (2bb8e1121..6b7f51450)

VERIFIED: {"GPUFLOW-2-SPAOPERATIONSTORE-R4-01":"not_fixed","GPUFLOW-2-SPAOPERATIONSTORE-R4-02":"not_fixed","GPUFLOW-2-SPAOPERATIONSTORE-R4-03":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-2-SPAOPERATIONSTORE-R4-01 | not_fixed | The delta leaves `writeStorageItem` and `removeStorageItem` swallowing every storage exception (`describeOperationStore.ts:191-205`). `putDescribeOperationContext` still updates the tenant cache and emits before/without confirming the write (`:384-405`), so a run can still look durable only in memory. |
| GPUFLOW-2-SPAOPERATIONSTORE-R4-02 | not_fixed | The fix delta has no `useBulkDescribe.ts` hunk. The hook still retains `storedRunId` in `retainedRunIdRef` and derives `runId` from that fallback (`useBulkDescribe.ts:97-105`), while terminal cleanup only clears the store (`:119-123`). |
| GPUFLOW-2-SPAOPERATIONSTORE-R4-03 | fixed | Run and suggestion snapshots are now keyed by `TenantScope`; hydration and both live fast paths resolve the current tenant (`describeOperationStore.ts:243-317`), and put/clear operations address only that tenant (`:383-435`). The added tenant-switch test exercises both caches (`describeOperationStore.test.ts:122-145`). |

### FINDINGS

FINDINGS: [{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-05","severity":"high","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/describeOperationStore.ts","line":356,"summary":"Transient storage read failure can delete a valid resumable run","evidence":"The new purgeInvalid branch treats readStoredContext(runKey)===null as malformed whenever a second read is non-null. readStoredContext returns null for any getItem exception because readStorageItem catches it, so a transient first-read failure followed by a successful second read removes the valid run key and silently destroys reload state."}]

#### GPUFLOW-2-SPAOPERATIONSTORE-R-05 — high

- File: `apps/prototype-wp-alt-context/js/admin/hooks/describeOperationStore.ts:349-359`
- Evidence: The fix adds a second `readStorageItem(runKey)` after `readStoredContext(runKey)` returned `null`. The latter also returns `null` when the first `sessionStorage.getItem` throws (`:184-188`), so an intermittent read failure followed by a successful read enters the new branch and calls `removeStorageItem(runKey)` on an otherwise valid resumable run.
- Impact: A transient storage read failure during subscription can silently delete durable operation state, so reload recovery is lost even though the stored payload was valid. This is a new data-loss path in the fix delta, distinct from the unchanged swallowed-write/removal path above.
- Fix: Preserve the distinction between “storage read failed” and “no value/invalid value”; only remove a key after a successful, validated read proves it is malformed or expired.

Verdict: fail

## Re-review r6 (6b7f51450..ad71a35cf)

VERIFIED: {"GPUFLOW-2-SPAOPERATIONSTORE-R4-01":"partially_fixed","GPUFLOW-2-SPAOPERATIONSTORE-R4-02":"fixed","GPUFLOW-2-SPAOPERATIONSTORE-R5-05":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-2-SPAOPERATIONSTORE-R4-01 | partially_fixed | `describeOperationStore.ts:199-240,442-461,485-505` now distinguishes read/write/remove outcomes, marks failed writes `memory_only`, and uses a tombstone to suppress a failed delete in the current process. The tombstone is only a module-local `Set` (`:66-69`), so a failed `removeItem` still leaves the old key to be rehydrated after a real page reload; the new persistence marker is also not consumed by the active-run/UI path. |
| GPUFLOW-2-SPAOPERATIONSTORE-R4-02 | fixed | `useBulkDescribe.ts:97-114,128-134` separates `activeRunIdRef` from `lastTerminalRunIdRef`, clears the former after terminal progress, and returns only the active id. A terminal run therefore no longer remains a non-null active `runId`, although the downstream terminal-summary regression is reported below. |
| GPUFLOW-2-SPAOPERATIONSTORE-R5-05 | fixed | `describeOperationStore.ts:199-211,243-271,417-425` preserves `error` versus `absent` versus validated `value`; `purgeInvalid` removes only an actually read invalid/expired value and no longer performs the destructive second read. The added one-shot read-error test exercises retry without removal (`describeOperationStore.test.ts:118-135`). |

### FINDINGS

FINDINGS: [{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-06","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useBulkDescribe.test.tsx","line":224,"summary":"Cancellation test removes terminal-cleanup coverage","evidence":"The fix changes the status returned by fetchBulkDescribeRunMock from cancelled to running while cancelBulkDescribeRunMock still returns cancelled, then asserts a non-null runId. The test no longer drives the terminal cancellation path that should clear the active run."},{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-07","severity":"low","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/__tests__/describeOperationStore.test.ts","line":1,"summary":"The fix delta still changes paths outside the lane-owned list","evidence":"The current delta edits both hooks/__tests__/describeOperationStore.test.ts and hooks/__tests__/useBulkDescribe.test.tsx, while the spa-operation-store lane row owns only describeOperationStore.ts, activeDescribeRun.ts, and useBulkDescribe.ts. This repeats a current-delta ownership violation rather than being a change to an owned production path."},{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-08","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/useBulkDescribe.ts","line":113,"summary":"Terminal summary identity is private, so the workbench hides terminal review UI","evidence":"The fix feeds lastTerminalRunIdRef only into useDescribeRunProgress and returns the active-only runId. Existing MediaSelection computes hasDescribeActivity/isPanelVisible from that runId and passes it to BulkDescribeReviewLink; after terminal cleanup it becomes null, so the terminal progress panel and failed/cancelled Review & apply drafts link disappear even though progress.run still contains the terminal result."}]

#### GPUFLOW-2-SPAOPERATIONSTORE-R-06 — medium

- File: `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useBulkDescribe.test.tsx:220-232`
- Evidence: The fix changes `fetchBulkDescribeRunMock` from a `cancelled` response to `running`, while the cancel mutation still resolves `cancelled`. The assertion consequently continues to expect a non-null active `runId` and never exercises terminal cleanup for cancellation. This weakens the proof for the exact lifecycle changed by R4-02 (CARD-06).
- Fix: Keep the status poll terminal for this test and assert `runId` becomes null while the terminal summary remains available; add a separate non-terminal cancellation assertion if needed.

#### GPUFLOW-2-SPAOPERATIONSTORE-R-07 — low

- File: `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/describeOperationStore.test.ts:1`; `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useBulkDescribe.test.tsx:1`
- Evidence: The fix delta changes both hook test paths, but the declared spa-operation-store lane list owns only the three production hook paths. The current fix therefore still crosses the lane boundary with test edits.
- Fix: Move the test changes to their owning lane or update the ownership manifest before merge.

#### GPUFLOW-2-SPAOPERATIONSTORE-R-08 — medium

- File: `apps/prototype-wp-alt-context/js/admin/hooks/useBulkDescribe.ts:97-114,142`; downstream `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:133-145,564,653-657,717-725`
- Evidence: The fix keeps `lastTerminalRunIdRef` private to progress polling and returns only the active `runId`. The existing workbench uses that returned id for `hasDescribeActivity`, terminal panel visibility, GPU relevance, and `BulkDescribeReviewLink`. Once the terminal effect clears the store, the returned id is null, so the panel and review link are suppressed even though the hook still has `progress.run` for the terminal summary.
- Impact: A completed/failed/cancelled run no longer drives active/GPU indicators as intended, but terminal outcome UI and review navigation are lost as a side effect.
- Fix: Expose a separate terminal-summary id/state to the workbench, or base panel/review rendering on the retained terminal progress while continuing to use active `runId` only for activity and GPU relevance.

Verdict: pass_with_findings

## Re-review r7 (377ee8b0b..eeee5074a)

VERIFIED: {"SPAOPE-ca632d51fc35756f-H-51ac649ed6dc2e5929ce7ef5":"fixed","GPUFLOW-2-SPAOPERATIONSTORE-R4-01":"not_fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| SPAOPE-ca632d51fc35756f-H-51ac649ed6dc2e5929ce7ef5 | fixed | The `useBulkDescribe.ts` hunk adds a separate `activeRunId` and computes the public `runId` as `activeRunId ?? lastTerminalRunId` (`+102-117`); terminal cleanup stores the id for the summary before clearing the active store entry (`+132-139`). The terminal tests now assert `activeRunId` is null while `runId` and `progress.run` retain the terminal result (`useBulkDescribe.test.tsx:+235-239,+292-298`). |
| GPUFLOW-2-SPAOPERATIONSTORE-R4-01 | not_fixed | The inlined delta has no `describeOperationStore.ts` hunk. The existing storage adapter still catches write/remove exceptions (`describeOperationStore.ts:213-231`), `putDescribeOperationContext` only labels a failed write `memory_only` while emitting the snapshot (`:448-461`), and `persistRunContext` still sets the active run without inspecting that outcome (`useBulkDescribe.ts:76-86`). A failed write/remove therefore remains silent and reload can still lose or resurrect state. |

### FINDINGS

FINDINGS: [{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-09","severity":"high","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/useBulkDescribe.ts","line":105,"summary":"Terminal summary state is not tenant-scoped","evidence":"The delta adds hook-instance React state `lastTerminalRunId` and falls back to it for `runId` (`useBulkDescribe.ts:105-117`) without recording the tenant. The operation store itself resolves and caches by tenant (`describeOperationStore.ts:57-80,318-335`), so switching a mounted workbench to a tenant with no active stored run leaves the previous tenant's terminal id and progress query visible, including its review link."},{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-10","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx","line":564,"summary":"The new activeRunId is not consumed by the workbench GPU relevance path","evidence":"The fix makes `runId` remain non-null for a terminal summary while adding `activeRunId` separately (`useBulkDescribe.ts:28-31,115-117`), but MediaSelection still assigns `activeDescribeRunId = bulkDescribe.runId` and passes `runId !== null` to `GpuTierStatus` (`MediaSelection.tsx:133,142-144,564`). A completed run therefore keeps the GPU status path relevant after active store cleanup; the newly added active id is unused by this downstream consumer."},{"id":"GPUFLOW-2-SPAOPERATIONSTORE-R-11","severity":"low","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useBulkDescribe.test.tsx","line":1,"summary":"The fix delta edits a test path outside this lane's owned list","evidence":"The inlined delta changes `hooks/__tests__/useBulkDescribe.test.tsx`, while the lane-owned list contains only `describeOperationStore.ts`, `activeDescribeRun.ts`, and `useBulkDescribe.ts`. This repeats a cross-lane test ownership violation in the current fix commit."}]

#### GPUFLOW-2-SPAOPERATIONSTORE-R-09 — high

- File: `apps/prototype-wp-alt-context/js/admin/hooks/useBulkDescribe.ts:103-117`
- Evidence: The fix stores the terminal summary id in `useState` and uses it whenever the tenant-scoped active store returns null. No tenant identity is captured with that state or used to reset it. The store's own cache is tenant-scoped (`describeOperationStore.ts:57-80,318-335`), so a same-mount tenant switch to a tenant without an active run can display the previous tenant's terminal run and expose its id/result and review URL. This violates the tenant boundary and the A4 foreign-tenant isolation proof (`GRPH-29`).
- Fix: Pair the terminal summary with the resolved tenant and clear it when that tenant changes, or source terminal summaries from the tenant-scoped operation store; add a mounted tenant-switch regression test.

#### GPUFLOW-2-SPAOPERATIONSTORE-R-10 — medium

- File: `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:133,142-144,564`; `apps/prototype-wp-alt-context/js/admin/hooks/useBulkDescribe.ts:28-31,115-117`
- Evidence: `runId` now intentionally remains the terminal summary id, while `activeRunId` is the cleared store-backed id. The existing workbench still treats `bulkDescribe.runId` as `activeDescribeRunId` and uses its non-null value for `GpuTierStatus.isRunRelevant`. Consequently a terminal run continues to drive the GPU relevance/status path after cleanup even though the fix introduced the correct active-id distinction. The terminal panel/review path should use the summary id, but activity/GPU paths need `activeRunId` (`rg-015`).
- Fix: Consume `bulkDescribe.activeRunId` for active/GPU relevance and expose/use a separate terminal-summary id for panel and review rendering.

#### GPUFLOW-2-SPAOPERATIONSTORE-R-11 — low

- File: `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useBulkDescribe.test.tsx:1`
- Evidence: The inlined r7 delta changes this test path, but the lane-owned list grants this lane only the three production hook paths. The test change must be reviewed/merged by its owning lane or the ownership manifest must be updated before merge.
- Fix: Move the test hunk to its owning lane, or explicitly assign the test path to this lane before landing it (`CARD-06`).

Verdict: fail
