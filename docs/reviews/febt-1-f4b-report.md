# FEBT-1 F4b cluster-ui — lane report

Lane `febt-1-f4b-cluster-ui`. Actor `grok-4.6`.

## Findings

### FEBT1-W2A-06 (already at HEAD)

- Commit: `6bf7e6470bbdb771f1ce50eaeac3af68246831d4` (sandbox base; no new commit)
- Tests:
  - `probe TimeoutError is not live and surfaces a non-null error [FEBT1-W2A-06]`
  - `probe HTTP 500 is not live and surfaces a non-null error [FEBT1-W2A-06]`
- RED tail: none this session. `useLiveReviewTarget` already calls `shouldRetryRequest`, maps timeout/5xx to `status: 'unknown'` with non-null `error`, and those two tests were green on first run (12/12).
- UX-map: no live-probe overlay row. Indeterminate state is `'unknown'` (status only; no new copy). Overlay `unknown` is caller fallback.

### FEBT1-W2A-04

- Commit: `bd8dcdccda26fe27dfb07505c37f838b9ea9f8d5`
- Tests:
  - `HTTPError from a cluster mutation never surfaces the endpoint URL or response body [FEBT1-W2A-04]`
  - `409 yields the stale-conflict message and reload affordance [FEBT1-W2A-04]`
  - `transport failure yields the ux-map transport copy [FEBT1-W2A-04]`
- RED tail: `FAIL HTTPError from a cluster mutation never surfaces the endpoint URL — expected not to contain '/acx/v1/recognition/clusters/c1', received 'Request to /acx/v1/recognition/clusters/c1 failed (500): {"code":"boom","message":"stack trace body"}' | FAIL 409 yields the stale-conflict message — TypeError: getClusterMutationUserError is not a function | FAIL transport failure yields the ux-map transport copy — Expected "Network error — check your connection", Received "Network error. Please check your connection and try again." | Tests 3 failed | 15 passed (18)`

One owner: `getClusterMutationUserError` in `clusterMutationUtils.ts` (`classifyError` + `toUserMessage`, 409 via `classified.status === 409`). Deleted `ClusterLabelingPanel` `getErrorMessage`. `clusterAutoRetry.noteError` uses `toUserMessage` instead of `error.message`.

## UX-map copy gaps

1. Overlay has no 409 / stale-conflict row. Did not invent "someone else changed this cluster — reload". 409 uses existing in-tree copy `Label already exists. Use the dropdown to merge.` plus overlay action `Reload page`.
2. Overlay `timeout` exists, but `appError.ts` has no `_tag: 'timeout'` (F2 / W2A-05). TimeoutError still classifies as `abort`. Mutation UI uses overlay timeout copy for abort-like failures. Need F2 to export a timeout tag if abort should stay silent.
3. Overlay `http` has no sentence-level copy. Non-409 HTTP uses caller fallback `An unexpected error occurred. Please try again.`

## Verification

`cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx js/admin/utils/__tests__/userFacingError.test.ts` → 18 passed.
