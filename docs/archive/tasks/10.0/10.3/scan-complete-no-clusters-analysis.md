# Scan Completed But No Clusters Shown Analysis

## Incident Summary

- Scan job `0d40a6f1-fa45-4a91-b98c-430eca08fafb` completed successfully for tenant `cc42f496-c7e1-5631-b3b5-cfa270c763f8`.
- The backend snapshot route returned `200 OK`.
- Projection acknowledgement returned `200 OK`.
- The UI still showed:
  - `Review Suggestions`
  - `No suggestions to review yet.`

## Confirmed Error In Logs

Two snapshot-enrichment warnings were emitted from `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` while building the sovereign snapshot:

```text
ValueError: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()
```

The exception originates from `apps/prototype-description-service/recognition/application/suggestions/label_inference.py:154`:

```python
if target_cluster.representative_identity and target_cluster.representative_identity.embedding:
```

`target_cluster.representative_identity.embedding` can be a NumPy array. Using it directly in a boolean condition raises `ValueError` when the array has more than one element.

## What The Error Explains

This error explains why `suggested_label` enrichment was skipped for at least two clusters during snapshot generation.

That means:

- the backend did find clusters worth attempting to enrich
- the snapshot code caught the exception and continued
- those clusters were projected without inferred labels

So this is a real bug, and it directly prevents the new sovereign-sync suggested-label flow from working for affected clusters.

## What The Error Does Not Fully Explain

The warning does **not** by itself explain why no cluster cards were shown at all.

Why:

- `SuggestionReviewPanel.tsx` shows `No suggestions to review yet.` when `reviewItems.length === 0`
- `TopClustersSection.tsx` is a separate section and is hidden only when:
  - `topClusters` is empty, or
  - every returned cluster has `identity_count <= 1`, or
  - every cluster has been hidden/dismissed locally

So the enrichment failure explains missing `Is this X?` prompts, but not necessarily an entirely empty naming queue.

## Most Likely Runtime Interpretation

The current evidence points to this chain:

1. Clustering completed and produced at least some cluster rows, because snapshot enrichment attempted two cluster IDs.
2. Suggested-label inference crashed for those clusters, so their `suggested_label` fields stayed null.
3. The WordPress UI still showed no cluster cards because the top-unlabeled queue likely returned no eligible non-singleton rows.

The most plausible reasons for step 3 are:

- projected clusters exist, but all are singletons and are filtered out by `TopClustersSection.tsx`
- projected clusters exist, but the local `top-unlabeled` query returned none for this tenant
- projected clusters were labeled/dismissed already and therefore excluded from the unlabeled queue

## Secondary Signals

- The `cURL error 28` SSE timeout looks incidental here. The relevant REST calls for snapshot, projection acknowledgement, merge suggestions, and name suggestions all returned `200 OK`.
- The HTML snippet showing `No identities detected yet.` is item-level UI evidence that at least some media rows have no linked identities, but it is not enough on its own to prove the whole tenant has zero clusters.

## Code-Level Root Cause

The immediate backend bug is the ambiguous truthiness check in `label_inference.py`.

Safer pattern:

```python
embedding = getattr(target_cluster.representative_identity, "embedding", None)
if target_cluster.representative_identity is not None and embedding is not None:
    target_embedding = np.asarray(embedding, dtype=np.float32)
```

If the code also needs to guard against empty vectors, it should check `np.asarray(embedding).size > 0` explicitly rather than relying on Python truthiness.

## Follow-Up Checks Needed

To explain the missing cluster cards end to end, inspect these next:

1. `GET /acx/v1/recognition/clusters/top-unlabeled?tenant_id=cc42f496c7e15631b3b5cfa270c763f8&limit=20`
2. projected `wp_acx_clusters` rows for this tenant, especially:
   - `identity_count`
   - `label`
   - `curation_state`
   - `is_user_confirmed`
   - `suggested_label`
3. whether the returned unlabeled clusters are all singletons and therefore hidden by the frontend

## Bottom Line

There is a confirmed backend bug in suggested-label inference, and it definitely prevents inferred names from appearing for some clusters.

But based on the UI behavior, that bug is probably only part of the story. The total absence of visible cluster cards suggests the top-unlabeled queue is also empty or filtered down to singletons after projection.
