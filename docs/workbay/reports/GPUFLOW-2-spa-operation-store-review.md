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
