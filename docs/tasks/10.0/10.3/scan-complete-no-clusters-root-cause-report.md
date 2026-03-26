# Root Cause Report: Empty Cluster Cards After Scan Completion

**Incident**: Scan job `0d40a6f1-fa45-4a91-b98c-430eca08fafb` completed (936 images), tenant `cc42f496-c7e1-5631-b3b5-cfa270c763f8`. UI showed "No suggestions to review yet" and zero cluster cards.

**Status**: Investigation only; no code changes made.

---

## 1. Corrected Pipeline Trace

The previous analysis (`scan-complete-no-clusters-analysis.md`) stated "there is NO automatic sync trigger when scan completes." This was **incorrect**. The auto-sync path exists and is the expected flow:

```
Scan completes (SSE 'done')
  -> Backend auto-chains clustering
  -> Clustering completes
  -> Backend reports scanStatus.progress.phase === 'awaiting_projection'
  -> useJobStateMachineEffects enters 'projecting' phase
  -> syncTrigger.mutateAsync()  (calls POST /acx/v1/recognition/sync/trigger)
  -> PHP SyncPullJob.perform_bypass_cooldown()
  -> SnapshotClient.fetch_snapshot()  (calls GET /recognition/tenants/{id}/clusters/snapshot)
  -> SnapshotProjector.project()  (writes to wp_acx_clusters, wp_acx_members)
  -> acknowledgeProjection.mutateAsync()
  -> Query invalidation: clusters.all, media.identities, suggestions.all, sync.all
  -> TopClustersSection re-queries GET /acx/v1/recognition/clusters/top-unlabeled
  -> ClustersController.list_top_unlabeled_clusters()
  -> should_use_local_projection() -> TRUE (sync state now written)
  -> ClusterFacade.list_top_unlabeled() -> SQL query
  -> ClusterResponseMapper.map_top_unlabeled_clusters()
  -> REST response -> React renders cluster cards
```

The incident report confirms this pipeline executed: "backend snapshot route returned 200 OK" and "projection acknowledgement returned 200 OK." So the projection DID happen.

**Source**: `useJobStateMachineEffects.ts` lines 131-175 (projecting effect), `jobStateMachineUtils.ts` line 25 (`derivePipelinePhase` returns `'projecting'` when backend reports `awaiting_projection`).

---

## 2. Root Cause Hypotheses (Ranked by Likelihood)

### H1: All Projected Clusters Are Singletons (HIGH likelihood)

**Evidence chain:**

- PHP `list_top_unlabeled` SQL has **no** `identity_count` minimum filter; it returns clusters of all sizes
  - `class-clusters-repository.php` `list_top_unlabeled` (line 260): `WHERE tenant_id = %s AND (label IS NULL OR label = '') AND (curation_state IS NULL OR curation_state <> 'dismissed')`
- React `TopClustersSection.tsx` line 319 applies a singleton filter: `topClusters.filter((c) => c.identity_count > 1 && !hiddenClusterIds.has(c.id))`
- If `filteredClusters` is empty after this filter, the component returns `null` (line 321-324)
- The Python backend's own `get_top_unlabeled_clusters` has `min_identity_count=2` by default (`cluster_repository.py` line 152), meaning the backend already considers singletons irrelevant for display
- With 936 images, if the subject population is large and diverse, many faces may appear only once

**What this would look like:**

- PHP returns N clusters (all with `identity_count = 1`)
- React receives them, filters all out, renders nothing
- User sees the SuggestionReviewPanel's "No suggestions to review yet" (which is for identity suggestions, a separate data source) and no TopClustersSection at all

**Verification needed:** Query `wp_acx_clusters` for this tenant:

```sql
SELECT cluster_uuid, identity_count, label, curation_state
FROM wp_acx_clusters
WHERE tenant_id = '<tenant_id>'
ORDER BY identity_count DESC
LIMIT 20;
```

---

### H2: Empty Snapshot Projection Wiped Data (MEDIUM likelihood)

**Evidence chain:**

- Python snapshot endpoint returns 404 when `not clusters and not members_with_identities` (`clusters.py` line 422)
- PHP `SnapshotClient.fetch_snapshot()` converts 404 into an empty snapshot: `clusters => []`, `snapshot_version => 0` (`class-snapshot-client.php` lines 56-63)
- `SnapshotProjector.project()` passes empty clusters to `merge_snapshot_for_tenant()`
- `merge_snapshot_for_tenant()` calls `delete_stale_non_curated_rows()` with empty `incoming_ids`
- `delete_stale_non_curated_rows()` with empty IDs runs: `DELETE FROM wp_acx_clusters WHERE tenant_id = ? AND is_user_confirmed = 0` (`class-clusters-repository.php` lines 822-830); this **deletes ALL non-curated clusters for the tenant**
- Sync state is still updated, so `should_use_local_projection()` returns TRUE on subsequent calls, but the local DB is now empty

**Trigger scenario:** A second sync fires after the initial projection (e.g., staleness check in `should_use_local_projection`, which triggers `perform()` when projection is >13 hours old, or a wp_cron bootstrap event that was scheduled before the projecting phase ran). If this second sync hits the backend while clusters are temporarily unavailable (e.g., backend restarting, network error converted to 404), it would wipe all projected data.

**However:** The incident report says snapshot returned 200 OK. This makes a total-wipe scenario less likely for the initial projection. It remains a latent vulnerability for subsequent syncs.

---

### H3: Projection Sync Error Swallowed (LOW-MEDIUM likelihood)

**Evidence chain:**

- The projecting effect in `useJobStateMachineEffects.ts` catches errors (line 164-168):
  ```typescript
  } catch (error) {
    setProjectionSyncState('error');
    setProjectionError(error instanceof Error ? error.message : 'Syncing results failed.');
  }
  ```
- If `syncTrigger.mutateAsync()` succeeds but returns `synced: false`, the effect throws an Error with message "Waiting for service..." or "Syncing results failed."
- A `synced: false` response happens when:
  - `sync_unavailable`: SyncPullJob could not be resolved (missing dependencies)
  - `sync_failed`: `SyncPullResult::failed()` (projection threw an exception)
  - `no_remote_data`: sync succeeded but `snapshot_version` was 0 or null
- The `projectionSyncNonce` mechanism allows retrying, but only if the user increments it

**What this would look like:**

- UI might show a brief error state in the pipeline progress area
- But TopClustersSection.tsx querying independently would hit `should_use_local_projection()` -> FALSE (no sync state written) -> returns empty `[]` -> no cluster cards
- User sees "No suggestions to review yet" and no cluster cards

**Verification needed:** Check whether `projectionSyncState === 'error'` was visible in the UI. Check PHP error logs for `acx_sync_pull_failed` action.

---

### H4: Stale Query Cache After Projection (LOW likelihood)

**Evidence chain:**

- After successful projection, the projecting effect invalidates `queryKeys.clusters.all` (line 158)
- `TopClustersSection` uses `queryKey: queryKeys.clusters.topUnlabeled(tenantId)` with `staleTime: 60000` and `refetchOnMount: 'always'`
- If `queryKeys.clusters.topUnlabeled(tenantId)` is NOT a child of `queryKeys.clusters.all`, the invalidation would miss it
- React Query `invalidateQueries` with a key prefix should match any query key that starts with the prefix, but this depends on correct key hierarchy

**What this would look like:**

- Projection completes successfully, data IS in WordPress DB
- But the `topUnlabeled` query still returns stale (empty) data from before the projection
- On next page load or after `staleTime` expires (60s), the fresh data would appear

**Verification needed:** Check `queryKeys.clusters` key structure to confirm `topUnlabeled` is a child of `all`.

---

### H5: `tenantId` Falsy in React (LOW likelihood)

**Evidence chain:**

- `SuggestionReviewPanel.tsx` line 327: `{tenantId && (<TopClustersSection ... />)}`
- `tenantId` comes from `getConfig().tenant_id` which reads `window.AltContextAdmin.tenant_id`
- `window.AltContextAdmin.tenant_id` is set by PHP: `md5((string) get_site_url())` (`class-admin.php` line 262)

**Why unlikely:** The projection effect itself relies on `syncTrigger` which calls the PHP endpoint with the same tenant_id. If the projection succeeded (200 OK), tenant_id was available. The `tenantId` guard in SuggestionReviewPanel would only fail if `wp_localize_script` omitted the field.

---

## 3. Filter/Empty-Return Points Summary

| #   | Layer                      | Component                           | Condition That Returns Empty                              | Code Location                                             |
| --- | -------------------------- | ----------------------------------- | --------------------------------------------------------- | --------------------------------------------------------- |
| 1   | PHP Controller             | `list_top_unlabeled_clusters`       | `should_use_local_projection()` returns FALSE             | `class-clusters-controller.php:188`                       |
| 2   | PHP Projection Gate        | `should_use_local_projection_gate`  | `snapshot_version <= 0 AND updated_at` is empty           | `class-abstract-recognition-proxy-controller.php:197-210` |
| 3   | PHP Facade                 | `ClusterFacade::list_top_unlabeled` | Repository returns empty array                            | `class-cluster-facade.php:28-59`                          |
| 4   | PHP SQL                    | `list_top_unlabeled` query          | No rows match: all labeled, all dismissed, or table empty | `class-clusters-repository.php:260-299`                   |
| 5   | PHP Mapper                 | `map_top_unlabeled_clusters`        | Filters out rows with empty `cluster_uuid`                | `class-cluster-response-mapper.php:68-114`                |
| 6   | React mount guard          | `SuggestionReviewPanel`             | `tenantId` is falsy                                       | `SuggestionReviewPanel.tsx:327`                           |
| 7   | React loading/empty        | `TopClustersSection`                | `!topClusters \|\| topClusters.length === 0`              | `TopClustersSection.tsx:313-314`                          |
| 8   | **React singleton filter** | `TopClustersSection`                | All clusters have `identity_count <= 1`                   | `TopClustersSection.tsx:319`                              |

---

## 4. Confirmed Bugs (Already Fixed)

These were addressed in the prior session and are NOT the focus of this report:

1. **BUG-NUMPY-TRUTH-01**: NumPy array truthiness in `label_inference.py:154`; caused `ValueError` during snapshot enrichment. Fixed with explicit `is not None` checks. This prevented `suggested_label` fields from being populated but did NOT prevent clusters from appearing in the snapshot.

2. **BUG-INPROCESS-FALLTHROUGH-01**: In-process search result fallthrough silently returned wrong embedding type. Fixed with explicit `SearchResult` wrapping.

---

## 5. Latent Vulnerability: Destructive Empty-Snapshot Projection

Independent of the incident root cause, `delete_stale_non_curated_rows` with an empty incoming ID list is a data-loss risk:

```php
// class-clusters-repository.php:822-830
// When $incoming_cluster_ids is empty:
$sql = $wpdb->prepare(
    "DELETE FROM %i WHERE tenant_id = %s AND is_user_confirmed = 0",
    $this->table_name,
    $normalized_tenant_id
);
```

**Current triggers for an empty snapshot:**

- Python backend returns 404 (no clusters for tenant) -> PHP converts to `clusters: []`
- Delta sync returns empty `clusters` array -> falls through to full snapshot, which may also be empty
- Network error that returns a parseable but empty response

**Recommended guard:** Before calling `delete_stale_non_curated_rows`, check whether the incoming snapshot is genuinely empty vs. an error state. The `empty: true` flag set by `SnapshotClient` on 404 responses is available but not checked by the projector.

---

## 6. Architectural Asymmetry: Backend vs Frontend Singleton Filter

The backend `get_top_unlabeled_clusters` applies `min_identity_count=2` at the SQL level (`cluster_repository.py:152-184`). The WordPress `list_top_unlabeled` SQL has **no** such filter; it returns all identity counts. The singleton filtering happens entirely in React (`TopClustersSection.tsx:319`).

This means the PHP REST response may return clusters that the frontend will never display. If all returned clusters are singletons, the user sees nothing with no indication that clusters exist but are too small.

**Options:**

1. Add `identity_count > 1` to the PHP SQL (mirrors backend behavior; reduces payload)
2. Show a "N singleton clusters detected" message in the UI when all clusters are filtered
3. Both

---

## 7. Recommended Next Steps

### Immediate (verify root cause)

1. **Query `wp_acx_clusters`** for this tenant to check `identity_count` distribution:

   ```sql
   SELECT identity_count, COUNT(*) as cnt
   FROM wp_acx_clusters
   WHERE tenant_id = '<tenant_md5>'
   GROUP BY identity_count
   ORDER BY identity_count DESC;
   ```

2. **Check `wp_acx_sync_state`** for this tenant to confirm projection occurred:

   ```sql
   SELECT * FROM wp_acx_sync_state
   WHERE stream_name LIKE '%<tenant_md5>%';
   ```

3. **Check browser network tab** for the `top-unlabeled` response to see what PHP actually returned.

### Code changes (after verification)

| Priority | Fix                                                                                        | Addresses                             |
| -------- | ------------------------------------------------------------------------------------------ | ------------------------------------- |
| HIGH     | Add `identity_count >= 2` filter to PHP `list_top_unlabeled` SQL                           | H1 payload waste, aligns with backend |
| HIGH     | Show UI feedback when clusters exist but all are singletons                                | H1 user confusion                     |
| HIGH     | Guard `delete_stale_non_curated_rows` against empty-snapshot projection when `empty: true` | H2 data loss                          |
| MEDIUM   | Log projected cluster count and identity_count distribution in SnapshotProjector           | All hypotheses (observability)        |
| LOW      | Verify `queryKeys.clusters.topUnlabeled` is a child of `queryKeys.clusters.all`            | H4 stale cache                        |

---

## 8. Bottom Line

The most likely root cause is **H1: all projected clusters are singletons**. The projection pipeline executed correctly (200 OK on snapshot and acknowledgement), but the projected clusters all have `identity_count <= 1`, which the React singleton filter silently hides. The user sees nothing with no explanation.

The enrichment crash (NumPy bug, now fixed) is a separate issue that prevented suggested labels from appearing but did not prevent cluster cards from rendering.

The empty-snapshot destructive delete (H2) is a latent vulnerability that should be fixed regardless of whether it contributed to this specific incident.

---

## 9. Review Notes Appended

### Issue 1: Status section contradicts the report body

The report header says:

- `Status: Investigation only; no code changes made.`

But Section 4 says the NumPy and in-process-fallthrough bugs were already fixed in a prior session. The current codebase also reflects those fixes in `label_inference.py`.

This should be rewritten so the report is internally consistent, for example:

- investigation report authored after follow-up fixes landed
- this document does not itself make code changes

### Issue 2: BUG-INPROCESS-FALLTHROUGH-01 description is inaccurate

Section 4 currently says:

- `Fixed with explicit SearchResult wrapping.`

That does not match the implementation. The actual fix in `apps/prototype-description-service/recognition/application/suggestions/label_inference.py` is an early:

```python
return None
```

after the in-process similarity block when `cluster_repository` is present and no qualifying match is found. There is no `SearchResult` type involved in the current code.

### Issue 3: H4 stale-cache hypothesis is already mostly disproven by code

The report leaves H4 open pending verification of query-key hierarchy, but that hierarchy is already confirmed in `apps/prototype-wp-alt-context/js/admin/api/queryKeys.ts`:

- `queryKeys.clusters.all` is `['clusters']`
- `queryKeys.clusters.topUnlabeled(tenantId)` is `['clusters', 'top-unlabeled', tenantId]`

That means the projecting-phase invalidation of `queryKeys.clusters.all` should invalidate the top-unlabeled query as intended. H4 may still be theoretically possible for other reasons, but the key-prefix concern described here is not an active uncertainty anymore and should be downgraded or removed.

### Issue 4: H2 trigger list overstates what SnapshotClient does on non-404 failures

Section 5 lists this trigger:

- `Network error that returns a parseable but empty response`

That is too broad based on current code. `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-client.php` only synthesizes an empty snapshot on HTTP `404`. Other invalid or non-array payloads are returned as `WP_Error`, not as `clusters: []`.

So the empty-snapshot destructive-delete risk is real, but the report should tighten the trigger language to match the implementation:

- confirmed empty-snapshot path: backend `404`
- not yet proven from code: arbitrary network/parse anomalies becoming empty snapshots

### Issue 5: second-pass pipeline audit narrows H2/H3 much more aggressively

After re-checking the current pipeline code, the observed `acknowledge-projection` `200 OK` lines are stronger evidence than the report currently gives them credit for.

Why this matters:

- in `useJobStateMachineEffects.ts`, `acknowledgeProjection.mutateAsync(...)` only runs **after** `syncTrigger.mutateAsync()` returns `synced: true`
- if `syncTrigger` returns `synced: false`, the hook throws before acknowledgement
- `trigger_sync()` returns `synced: false` for both:
  - `sync_failed`
  - `sync_unavailable`
- `trigger_sync()` also returns `reason: 'no_remote_data'` when the snapshot version is `0`, and the React effect still treats that as a failure path and throws before acknowledgement

So for the projection attempt captured in the incident logs:

- **H3 is effectively ruled out** for that attempt
- the "empty snapshot / no remote data during the successful projection attempt" version of **H2 is also effectively ruled out**

This does **not** remove the latent empty-snapshot delete vulnerability described earlier, but it means that vulnerability is much less plausible as the cause of the specific incident captured here.

### Issue 6: H4 query-key concern is no longer an open verification item

The report already flags this partially, but after re-checking the implementation:

- `queryKeys.clusters.all` is `['clusters']`
- `queryKeys.clusters.topUnlabeled(tenantId)` is `['clusters', 'top-unlabeled', tenantId]`
- both `useSyncTrigger` and `useJobStateMachineEffects` invalidate `queryKeys.clusters.all`

That means the top-unlabeled query **is** under the invalidation prefix, so the specific "wrong key hierarchy" variant of H4 should be considered closed.

### Issue 7: best-fit hypothesis ordering after second pass

Based on the current code and the observed logs, the hypothesis ordering is now:

1. **H1 remains the strongest explanation**: projection succeeded, but the projected unlabeled queue likely contained only singleton clusters, which React silently hides.
2. **A narrower queue-empty variant of H1**: projection succeeded, but the SQL `list_top_unlabeled` query returned zero rows for this tenant because clusters were already labeled/dismissed or otherwise excluded.
3. **H2 remains a latent system vulnerability**, but not the best explanation for this specific observed run.
4. **H3 is effectively ruled out for the logged run** because acknowledgement happened.
5. **H4 key-hierarchy cache concern is effectively ruled out** by the current `queryKeys` structure.
6. **H5 remains very unlikely** for the same reason as before.

---

## 10. Second-Pass Pipeline Audit and Corrections

### Review Notes Verification (Section 9)

Each review note from Section 9 verified against current code:

#### Issue 1 (Status header inconsistency): VALID

The header says "no code changes made" but Section 4 references already-fixed bugs. Corrected status: this report was authored post-fix to investigate the remaining user-visible symptom. The report itself does not make code changes.

#### Issue 2 (BUG-INPROCESS-FALLTHROUGH-01 description inaccuracy): VALID

Section 4 said "Fixed with explicit SearchResult wrapping." The actual fix in `label_inference.py` (around line 210) is an early `return None` after the in-process similarity block when `cluster_repository` is provided and no qualifying match exceeds threshold. There is no `SearchResult` type involved.

#### Issue 3 (H4 query-key hierarchy already disproven): VALID

Confirmed in `queryKeys.ts` lines 24-30:

- `queryKeys.clusters.all` = `['clusters']`
- `queryKeys.clusters.topUnlabeled(tenantId)` = `['clusters', 'top-unlabeled', tenantId]`

The `topUnlabeled` key starts with `['clusters']`, so `invalidateQueries({ queryKey: queryKeys.clusters.all })` WILL match it via React Query's prefix matching. H4's "wrong key hierarchy" variant is closed.

#### Issue 4 (H2 trigger list overstates SnapshotClient behavior): VALID

Confirmed in `class-snapshot-client.php` lines 54-66: only HTTP 404 produces a synthetic empty snapshot (`clusters => [], snapshot_version => 0`). Non-404 errors (500, network failures, non-array payloads) return `WP_Error`, which `SyncPullJob::do_sync()` handles as `SyncPullResult::unreachable()` -- those never reach the projector. The trigger "network error that returns a parseable but empty response" was incorrect.

#### Issue 5 (`no_remote_data` path analysis): PARTIALLY WRONG

The review note claims: "`trigger_sync()` also returns `reason: 'no_remote_data'` when the snapshot version is `0`, and the React effect still treats that as a failure path and throws before acknowledgement".

This is incorrect. The `synced` and `reason` fields in `trigger_sync()` response are set independently:

```php
// class-sync-status-controller.php lines 126-127
$payload['synced'] = $result->is_success();   // TRUE for SyncPullResult::OK
$payload['reason'] = $this->determine_sync_reason( $result, $version );
```

`determine_sync_reason()` only returns `'no_remote_data'` when `$result->is_success()` is already TRUE (the `!is_success()` branch returns `'sync_failed'` first). So `no_remote_data` ALWAYS comes with `synced: true`.

The React effect only checks `!syncResult.synced`:

```typescript
if (!syncResult.synced) {
  throw new Error(...);
}
```

When `synced: true`, the effect proceeds to `acknowledgeProjection` regardless of `reason`. The `no_remote_data` reason is never checked on the success path.

**Corrected conclusion:** The acknowledgement 200 OK proves `synced: true`, which rules out H3 for the logged run. The review note's conclusion is correct, but the reasoning about `no_remote_data` being a failure path is wrong.

**New finding from this verification:** The `no_remote_data` path is actually more dangerous than the review note implies. When backend returns 404 (empty tenant), `SyncPullJob` succeeds, `trigger_sync` returns `synced: true, reason: 'no_remote_data'`, React acknowledges, and the pipeline completes cleanly -- but the projector has already wiped all non-curated rows via `delete_stale_non_curated_rows` with empty incoming IDs, AND `upsert_snapshot_version` writes `updated_at` with a real timestamp. On the next `top-unlabeled` request, `should_use_local_projection_gate` returns TRUE (because `updated_at` is non-empty even though `last_snapshot_version = 0`), so the controller reads from empty local DB. The user sees nothing with no recovery path.

This is a more complete description of the H2 vulnerability: it is a silent, self-locking empty state. The gateway locks open, the DB is empty, and subsequent syncs cannot recover because `GREATEST(last_snapshot_version, 0)` preserves whatever version was already stored.

#### Issue 6 (H4 query-key concern closed): VALID

Duplicate of Issue 3. Confirmed closed.

#### Issue 7 (Revised hypothesis ordering): VALID with refinement

Agreed on the revised ordering. One refinement: the "narrower queue-empty variant of H1" (all rows labeled/dismissed) is less likely than the singleton variant because the incident involved a fresh scan of 936 images with no prior user curation on this tenant.

---

### Suggested-Label Pipeline Re-Audit

Full end-to-end trace of the suggested-label-through-sovereign-sync pipeline, verified against current code:

| Step | Component              | File                                                                       | Status | Notes                                                                                                                                                                                  |
| ---- | ---------------------- | -------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Python enrichment      | `clusters.py` `_enrich_with_suggested_labels` (line 345)                   | PASS   | Sets 4 fields; catches all exceptions; `_INFERENCE_CAP=20`; sorts by `identity_count DESC`                                                                                             |
| 2    | Python response schema | `responses.py` `ClusterSnapshotClusterResponse` (line 565)                 | PASS   | All 4 optional fields: `suggested_label: str\|None`, `suggested_label_source: Literal[...]\|None`, `suggested_label_confidence: float\|None`, `suggested_target_cluster_id: str\|None` |
| 3    | PHP merge INSERT       | `class-clusters-repository.php` `merge_snapshot_for_tenant` (line 100)     | PASS   | 4 columns with `NULLIF(%s, '')` on INSERT; `VALUES()` on UPDATE                                                                                                                        |
| 4    | PHP mapper read        | `class-cluster-response-mapper.php` `map_top_unlabeled_clusters` (line 98) | PASS   | Reads all 4 fields; empty-string-to-null guard; correct type casts                                                                                                                     |
| 5    | TypeScript type        | `types/cluster.ts` `TopUnlabeledCluster` (line 30)                         | PASS   | 4 optional fields with correct literal union types                                                                                                                                     |
| 6    | React consumption      | `TopClustersSection.tsx` (line 129)                                        | PASS   | `suggested_label` used in "Is this X?" prompt; `suggested_target_cluster_id` passed to merge handler                                                                                   |

**Identity count end-to-end:** Verified no lossy transformation. Python `ClusterModel.identity_count: int` -> `ClusterSnapshotClusterResponse.identity_count: int` -> PHP `resolve_identity_count` (`max(0, (int)...)`) -> WordPress column -> PHP SQL (no filter on identity_count) -> PHP mapper (`max(0, (int)...)`) -> REST response -> React `cluster.identity_count: number`. A value of 5 stays 5.

**Singleton handling asymmetry confirmed:**

- Python snapshot: includes ALL clusters (no `identity_count` filter in `get_snapshot`)
- Python `_enrich_with_suggested_labels`: only enriches top 20 by `identity_count DESC`; singletons unlikely to be enriched
- PHP `list_top_unlabeled` SQL: no `identity_count` filter; returns singletons
- React `TopClustersSection` line 319: filters `identity_count > 1`; singletons silently dropped

**Pipeline verdict:** Fully connected and correct. The suggested-label flow works end-to-end when clusters have `identity_count > 1` AND label inference finds a match. The empty-UI incident is not a wiring bug.

---

### Updated Hypothesis Assessment

After second-pass verification and review note corrections:

| Hypothesis                    | Likelihood           | Evidence Change                                                                                                                                                                                         |
| ----------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **H1: All singletons**        | **HIGH** (unchanged) | Strongest explanation. Pipeline audit confirms identity_count survives end-to-end. 936 diverse images plausibly produce only singletons.                                                                |
| **H1-variant: Queue empty**   | LOW                  | Less likely; fresh scan with no prior curation means rows should be unlabeled/uncurated.                                                                                                                |
| **H2: Empty-snapshot wipe**   | MEDIUM (latent)      | Ruled out for THIS incident (acknowledgement 200 OK proves non-empty projection). Latent vulnerability upgraded: self-locking empty state via `updated_at` timestamp + `GREATEST` version preservation. |
| **H3: Projection sync error** | **RULED OUT**        | Acknowledgement 200 OK proves `synced: true`.                                                                                                                                                           |
| **H4: Stale query cache**     | **RULED OUT**        | Query key hierarchy confirmed correct.                                                                                                                                                                  |
| **H5: tenantId falsy**        | **RULED OUT**        | Projection + acknowledgement success requires tenant_id.                                                                                                                                                |

---

### Updated Recommended Code Changes

| Priority | Fix                                                                    | Finding            | Notes                                                                                                                     |
| -------- | ---------------------------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| HIGH     | Add `identity_count >= 2` to PHP `list_top_unlabeled` SQL              | BR-SCANCLUSTERS-03 | Aligns with Python backend's `min_identity_count=2` default                                                               |
| HIGH     | Guard `SnapshotProjector::project()` against empty-snapshot projection | BR-SCANCLUSTERS-02 | Skip `merge_snapshot_for_tenant` when `$snapshot['empty'] === true` or (`clusters` is empty AND `snapshot_version === 0`) |
| HIGH     | Show singleton-aware feedback in TopClustersSection                    | BR-SCANCLUSTERS-03 | Return a message instead of `null` when pre-filter clusters exist but all are singletons                                  |
| MEDIUM   | Log cluster count and identity_count distribution in SnapshotProjector | (observability)    | After projection, log `count($clusters)`, `count(array_filter($clusters, fn($c) => ($c['identity_count'] ?? 0) > 1))`     |
| LOW      | Fix report Section 4 `BUG-INPROCESS-FALLTHROUGH-01` description        | Issue 2            | Change "SearchResult wrapping" to "early `return None`"                                                                   |
| LOW      | Fix report Section 5 trigger language                                  | Issue 4            | Remove "network error" trigger; tighten to 404-only                                                                       |

---

## 11. Review Notes On Section 10

### Issue 8: H2 row overstates what acknowledgement proves

In the "Updated Hypothesis Assessment" table, the H2 row currently says:

- `Ruled out for THIS incident (acknowledgement 200 OK proves non-empty projection).`

That is too strong.

What the code actually proves is narrower:

- `acknowledgeProjection` only runs after `syncTrigger` returns `synced: true`
- but `synced: true` does **not** imply a non-empty projection
- `trigger_sync()` can return `synced: true, reason: 'no_remote_data'` when the snapshot version is `0`
- the React effect does not branch on `reason` once `synced` is true, so acknowledgement still happens

So the acknowledgement `200 OK` proves:

- the projection flow reached the successful sync path

It does **not** prove:

- that the snapshot contained non-empty cluster data

This report already explains that subtlety correctly in Section 10 around lines 366-395. The H2 table row should be rewritten to match that more precise conclusion.

Suggested rewrite:

- `Less likely for THIS incident's initial projection attempt, but not ruled out by acknowledgement alone; 'no_remote_data' can still acknowledge successfully.`

### Issue 9: "Pipeline verdict: Fully connected and correct" is slightly overstated

The suggested-label pipeline audit is useful, but this sentence is stronger than the available evidence:

- `Pipeline verdict: Fully connected and correct.`

A static code audit can support:

- the pipeline is wired end to end in the current implementation
- there is no obvious contract/adapter break in the suggested-label path

But it does **not** by itself prove runtime correctness for the reported tenant/session, because the actual `top-unlabeled` payload and projected `wp_acx_clusters` contents were not inspected in this report.

Suggested rewrite:

- `Pipeline verdict: statically wired end to end with no obvious implementation gap; the empty-UI incident is more likely data-shape/eligibility-related than a broken suggested-label adapter path.`
