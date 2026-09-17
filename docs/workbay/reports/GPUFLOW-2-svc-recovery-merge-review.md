# GPUFLOW-2 svc-recovery-merge review

Verdict: fail

| Field | Value |
| --- | --- |
| Base | `5ba695da2` |
| Tip | `d8a2c749f` |
| Files | `apps/prototype-description-service/recognition/application/orchestration/clustering/recovery_merge.py`; `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py`; `apps/prototype-description-service/recognition/application/settings/clustering.py`; `apps/prototype-description-service/recognition/tests/unit/test_recovery_merge.py`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx` |

The first four paths are the declared `svc-recovery-merge` paths. The two
`IdentityClusterList` paths are outside that owned set.

## FINDINGS

### GPUFLOW-2-SVCRECOVERYMERGE-R-01 — high

File: `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py:710-724,739-741,822-828`

Evidence: `run_singleton_hac_refinement` returns before the new tail call when
HAC is absent, when fewer than two singletons exist, or when fewer than two
usable embeddings remain. Those are normal scan states, so the call to
`run_recovery_merge` is not guaranteed to execute for a clustering run.

Impact: With recovery enabled, residual singleton/small clusters are silently
left unprocessed on those runs, and the required receipt reclaimer is skipped
as well. The low-level tests call `run_recovery_merge_on_clusters` directly and
therefore do not cover the production control flow. This violates the
post-HAC/RES-07 run-step contract ([RES-07]).

Fix: Use one exit path (or a `finally`/shared post-HAC step) that invokes
recovery after any HAC work and preserves the existing merge count result.

### GPUFLOW-2-SVCRECOVERYMERGE-R-02 — high

File: `apps/prototype-description-service/recognition/application/orchestration/clustering/recovery_merge.py:547-562,575-584`

Evidence: Admission reads `metadata["quality_score"]`, otherwise substitutes
`identity.confidence`, and defaults every missing operating condition to
`"unknown"`. The production domain conversion used by the batch member loader
does not populate `metadata` or the persisted `quality_score`; it only supplies
confidence and embedding provenance. Consequently the C1 quality-band and
operating-condition floors are evaluated against detection confidence (or an
universal unknown stratum), not the canonical quality evidence.

Impact: A high-confidence, low-quality face can clear a high-band floor, or a
valid member can be forced into the wrong abstained cell. Automatic recovery can
therefore admit false merges, violating the calibration/provenance gate
([PROV-01], [CAL-01]).

Fix: Carry the stored quality score and operating-condition evidence through
the repository/domain read model, reject missing or mismatched provenance, and
add a production-shaped admission test rather than relying on confidence as a
surrogate.

### GPUFLOW-2-SVCRECOVERYMERGE-R-03 — high

File: `apps/prototype-description-service/recognition/application/orchestration/clustering/recovery_merge.py:326-346,565-597`

Evidence: The batch repository path deliberately supplies all identities,
including mixed embedding models. Recovery then computes centroids/cosines for
all of those members while `_rank_destinations` compares only one
cluster-level model value (falling back to the first member) and allows a
missing model on either side. There is no per-member dimension, revision, or
full embedding-space check.

Impact: A cluster containing foreign-space members can influence destination
ranking and admission, producing cross-model false merges; a dimension mismatch
can instead crash the clustering run. The C2 decision is not fail-closed on
embedding-space evidence ([GRPH-22], [CAL-11]).

Fix: Partition or reject every member against the complete accepted runtime
binding before centroid or pairwise calculation; reject mixed/unknown models and
dimension mismatches, and cover those cases with a red test.

### GPUFLOW-2-SVCRECOVERYMERGE-R-04 — high

File: `apps/prototype-description-service/recognition/application/orchestration/clustering/recovery_merge.py:361-372,453-467,692-711`

Evidence: The receipt records a snapshot list of `moved_identity_ids`, but the
durable path subsequently calls `move_members(source_id, dest_id)`, which bulk
moves every current source member. It never verifies that the row count equals
the receipt list, and it deletes the source cluster even when the move returns
zero or a concurrent writer changed the source. Receipt creation and the
source/destination mutation also have no producer-side lock/CAS.

Impact: A concurrent assignment or recovery run can move identities that are
absent from the receipt, or persist a receipt for a no-op/partial move. Revert
then cannot restore the exact prior partition and source deletion can discard
unaccounted members. This is a read-check-write race ([CON-05], [CON-11]).

Fix: Serialize the source/destination/member mutation, update exactly the
captured identity IDs, require an exact affected-row count, and commit the
receipt only with that successful mutation; abort rather than delete on a CAS
miss.

### GPUFLOW-2-SVCRECOVERYMERGE-R-05 — high

File: `apps/prototype-description-service/recognition/application/orchestration/clustering/recovery_merge.py:392,401-404`

Evidence: Reverted receipts are purged before candidate evaluation, and the
candidate set contains every non-empty cluster with no exclusion or durable
block for a cluster restored by C3. The identity-merge contract explicitly
requires that a second recovery run not re-attach a restored cluster solely
because it was previously merged.

Impact: An operator can undo an automatic merge and have the next clustering
run immediately merge the restored cluster again. Undo is therefore not a
durable operator decision, and purging first also removes the only history this
code could use to prevent reattachment.

Fix: Persist and consult a post-revert recovery block/provenance marker (or an
equivalent exclusion set) before admission, and perform the RES-07 purge after
the recovery decision while retaining whatever guard data the contract needs.

### GPUFLOW-2-SVCRECOVERYMERGE-R-06 — low

File: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx:1`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx:1`

Evidence: The inlined delta changes these two SPA paths, but the declared
`svc-recovery-merge` owned-path list contains only the four recognition backend
paths named in the scope table. The UX lane owns `IdentityClusterList.tsx`.

Impact: The delta crosses the lane boundary and can conflict with or bypass the
owning SPA lane's review and merge routing ([TEAM-04]).

Fix: Remove these paths from this lane's delta and dispatch the UI change to its
declared owner, or amend ownership before merging.

## Verification

- Required composer-lock test: passed (`1 passed`).
- Lane-row recovery/suggestion tests: passed (`18 passed`).

## Re-review r2c (d8a2c749f..7092a36d8)

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-2-SVCRECOVERYMERGE-R-01 | fixed | `discovery_pipeline.py:699-707` moves the old body behind a helper, and `:825-851` wraps every return path in `try/finally` with one `run_recovery_merge` call. The added `test_singleton_hac_runs_recovery_once_for_each_early_exit` covers the three normal early exits (`test_recovery_merge.py:363-406`). |
| GPUFLOW-2-SVCRECOVERYMERGE-R-02 | fixed | `recovery_merge.py:692-736` loads persisted `MediaIdentityModel.quality_score`, `:797-817` carries that value into `RecoveryMember`, and `:983-995` uses this query in the session-backed path. The fallback conversion now assigns `quality_score=None` at `:800-805` rather than substituting `identity.confidence`. |
| GPUFLOW-2-SVCRECOVERYMERGE-R-03 | fixed | `recovery_merge.py:361-401` validates every member's model id, vector rank, and dimensionality before `_rank_destinations`; rejected residual members are abstained at `:513-535`, so mixed or malformed residuals never reach centroid/cosine math. The new foreign-model and wrong-dimension tests exercise those paths (`test_recovery_merge.py:235-306`). |
| GPUFLOW-2-SVCRECOVERYMERGE-R-04 | fixed | `_apply_recovery_receipt` locks both clusters and applies a source-member CAS in `recovery_merge.py:861-941`: source count, exact update rowcount, and zero remaining source rows are required before destination update/source deletion. Receipt insertion and flush follow the mutation inside the savepoint at `:943-946`. |
| GPUFLOW-2-SVCRECOVERYMERGE-R-05 | fixed | `recovery_merge.py:404-422` builds non-expired reverted-receipt exclusions before evaluation and `:552-576` abstains/emits a suggestion before admission. The added regression test blocks the same restored identity set until expiry (`test_recovery_merge.py:310-360`). The mutable-set limitation is recorded separately as R-08. |

### FINDINGS

#### GPUFLOW-2-SVCRECOVERYMERGE-R-07 — high

File: `apps/prototype-description-service/recognition/application/orchestration/clustering/recovery_merge.py:161-173,679-686,617-625`; `apps/prototype-description-service/recognition/tests/unit/test_recovery_merge.py:621-677`

Evidence: Both receipt stores now purge only `expires_at <= now`; `reverted_at` is no longer a purge predicate. The changed test named `test_expired_and_reverted_receipts_are_purged` now expects `purged_receipts == 1` and retains the reverted row. This contradicts the identity-merge contract's last-step requirement to purge reverted or expired receipts ([RES-07]).

Impact: The fix keeps reverted receipts as an exclusion mechanism but silently weakens the reclaimer contract and its observable purge count. There is no separate durable recovery-block record that would justify dropping the reverted-row purge, so the changed test codifies a release-contract regression.

#### GPUFLOW-2-SVCRECOVERYMERGE-R-08 — high

File: `apps/prototype-description-service/recognition/application/orchestration/clustering/recovery_merge.py:404-437,552-576`

Evidence: `_reverted_receipt_exclusions` records only the moved-identity set or `(source_label, survivor_id)`, and `_residual_is_reverted_excluded` checks only those mutable values. It never compares the receipt's `source_cluster_id` with `residual.cluster_id`. After a revert, a normal membership change to the restored unnamed cluster changes the identity set and still leaves no label key, so the next run can admit the same restored cluster again. The regression test covers only the unchanged identity set (`test_recovery_merge.py:331-360`). This violates the contract's API-05 guard that a second recovery run must not re-attach the restored cluster solely because it was previously merged ([CON-11]).

#### GPUFLOW-2-SVCRECOVERYMERGE-R-09 — medium

File: `apps/prototype-description-service/recognition/application/orchestration/clustering/recovery_merge.py:476-480,861-946`; `apps/prototype-description-service/recognition/tests/unit/test_recovery_merge.py:569-616,681-716`

Evidence: The delta moves durable work into the new session-backed `_apply_recovery_receipt`, while `run_recovery_merge_on_clusters` is explicitly plan-only. The updated tests now assert the in-memory store remains empty and manually add the planned receipt, and the admitted-merge test inspects only the returned receipt; no added test invokes `run_recovery_merge` or verifies the lock/count/CAS/receipt ordering. The high-risk durable path can therefore regress while the targeted suite remains green ([TEST-03]).

Verdict: fail
