# Cluster curation recompute findings

## Context

- Split and wrong-person curation are not updating the UI reliably.
- Example failure: `/clusters/{id}/split` timed out through the WP proxy (cURL error 28 after 60s) for media_id 6589.
- Goal: recompute representatives/centroid after curation and kick incremental clustering for unclustered identities.

## Current behavior (code)

- Split flow:

  - Endpoint `POST /recognition/clusters/{cluster_id}/split` calls `split_cluster`.
  - `split_cluster` in `apps/prototype-description-service/recognition/application/orchestration/cluster_split.py`:
    - loads members -> runs hierarchical split -> moves members -> creates new clusters
    - updates `identity_count` and label assignments
    - does not recompute representatives or centroid
    - does not refresh centroid view
    - does not trigger incremental clustering

- Wrong-person flow:

  - Endpoint `POST /recognition/clusters/reassign` with `target_cluster_id = null` calls `remove_identity_from_cluster`.
  - `remove_identity_from_cluster` in `apps/prototype-description-service/recognition/application/orchestration/cluster_curation.py`:
    - removes the member and decrements `identity_count`
    - does not recompute representatives or centroid
    - does not trigger incremental clustering

- Incremental clustering:
  - `cluster_unclustered_identities` exists in `apps/prototype-description-service/recognition/application/orchestration/incremental_clustering.py`.
  - It is only called via explicit endpoints or jobs, not from curation paths.

## Why UI appears broken

- The WP proxy times out after 60s (cURL error 28). The split endpoint is synchronous.
- If the split request is slow or blocked, the UI never receives a response and does not refresh.
- Even when the split succeeds, the cluster metadata used by discovery stays stale because reps/centroid are not recomputed.

## Impact on identity accuracy

- Stale representatives/centroid keep mixed embeddings, which can:
  - keep assigning new identities to the wrong cluster
  - prevent suggestions from moving toward the correct cluster
- Unclustered identities remain unclustered until a manual clustering job runs, so user corrections do not propagate.

## Directionality of user curation

- Split is a strong signal that the cluster contains multiple people, but it does not say which group should keep the label.

  - Current logic uses the representative or centroid as a proxy. This can be wrong for mixed clusters.
  - Better: include `anchor_identity_id` (or similar) in the split request to keep the label on that group.

- Wrong-person removal is a strong negative signal for that identity/cluster pair.
  - If it is immediately reclustered without constraints, the same mistake can reoccur.
  - This is a good place for a "do not assign to this cluster" constraint.

## Recommendations

- After split:

  - Recompute representatives and centroid for the original cluster and all new clusters.
  - Refresh the centroid view if available.
  - Consider using `assignment_writer.recompute_representatives` and `assignment_writer.recompute_centroid` from
    `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py`.

- After wrong-person removal:

  - Recompute representatives/centroid for the source cluster.
  - Mark the removed identity as unclustered, then run incremental clustering.
  - Add a simple constraint to prevent re-assigning the identity back to the same cluster.

- For incremental clustering:

  - Use `JobService.queue_clustering` or background tasks so curation requests return quickly.
  - Return 202 with a job id and let the UI poll.

- For observability:
  - Log duration for split/removal operations and include tenant_id, cluster_id, media_id(s), and job_id.
  - This makes it easier to confirm whether timeouts are before or after persistence.

## Open questions

- Should split accept an explicit `anchor_identity_id` to keep the label on the correct person?
- Should there be a durable negative constraint store (identity_id, blocked_cluster_id) to avoid immediate re-merge?
- Which worker should execute curation jobs: reuse scan worker or introduce a curation queue?

## Proposed answers

Anchor on split: yes, add anchor_identity_id. You only know the “correct person” if the UI tells you which face the user is acting on. When the user clicks “Split cluster” from a specific identity row or face card, pass that identity as the anchor so the label stays with that group. Without an anchor it is ambiguous; fall back to representative/centroid or largest group only when no anchor is provided.

Negative constraint store: yes, but make it “soft”. Persist (identity_id, blocked_cluster_id, created_by_user_id, reason, expires_at?) and apply it only to automatic assignment/suggestion. Allow explicit user merge or explicit reassignment to override and remove the block. This avoids immediate re-merge while still letting the user reattach when they are confident.

Which worker: reuse the scan worker first. Curation jobs are DB-heavy but lighter than scan/analyze, so a new queue is extra surface area. Add a curation job type handled by the existing worker, keep it high priority, and keep jobs idempotent and short. If instability continues, then split into a dedicated curation worker or a small in-process background task queue, but start with reuse to minimize moving parts.
