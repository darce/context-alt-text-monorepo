---
title: Identity merge and cluster recovery
boundary_owner: recognition
status: draft (GPUFLOW-2)
since: GPUFLOW-2
---

# Identity merge and cluster recovery

Recognition-side cluster merge receipts, pairwise recovery admission, LIFO
revert, and the operator-merge audit field. Not the WordPress person-merge
undo stack. Machine-readable companion schemas:

- [recognition-cluster-snapshot.schema.json](../../../packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json)
- [roster-entry.schema.json](../../../packages/shared-contracts/schemas/roster-entry.schema.json)
- [recognition-cluster-merge-candidates-response.schema.json](../../../packages/shared-contracts/schemas/recognition-cluster-merge-candidates-response.schema.json)
- [roster-merge-candidates-response.schema.json](../../../packages/shared-contracts/schemas/roster-merge-candidates-response.schema.json)

## Two undo stacks, never conflated (INT-09)

| Surface | Token | Reverts | Owner |
| --- | --- | --- | --- |
| Roster "Merged from N groups · Undo" | WP `PersonMergeService` `undo_token`, `UNDO_TOKEN_TTL_SECONDS` (24 h) | A WP person merge via `POST /roster/persons/merge/undo` | PHP person merge |
| Workbench "Merged automatically · Undo" | `undoable_merge_receipt_id` from the cluster snapshot → projection | A recognition cluster merge via `POST /recognition/clusters/{id}/revert-merge` | Recognition receipts |

Neither surface reads the other's token. No lane bridges them. The receipt
revert is the only recognition undo surface.

## `cluster_merge_receipts`

One row per merge (automatic or operator). Greenfield table in
`001_identity_schema.py` (C0). ORM: `IdentityCluster.merge_receipts` ordered
by `created_at` desc. Receipts carry `tenant_id` (`NOT NULL`, RLS like sibling
identity tables).

| Column | Type | Meaning |
| --- | --- | --- |
| `receipt_id` | UUID PK | Stable receipt id; the undo handle |
| `tenant_id` | UUID NOT NULL | Tenant FK; RLS like sibling identity tables |
| `survivor_cluster_id` | UUID | Cluster that kept the members |
| `source_cluster_id` | UUID | Cluster that was absorbed; revert reuses this UUID |
| `source_label` | string \| null | Label to restore on revert |
| `moved_identity_ids` | UUID[] | Exact membership moved; revert restores this set |
| `rule_version` | string | Calibration / merge-rule version that admitted the merge |
| `kind` | `auto` \| `operator` | Vocabulary is this enum only (sr-007) |
| `created_at` | timestamptz | Receipt push time |
| `expires_at` | timestamptz | `created_at + ACX_MERGE_UNDO_WINDOW_DAYS` |
| `reverted_at` | timestamptz \| null | Set on successful revert; unreverted while null |

`ACX_MERGE_UNDO_WINDOW_DAYS` default **7**. Undo window is this setting, never
a client constant.

Receipts for a survivor form an ordered stack. Only the newest unreverted
receipt is undoable (LIFO).

## Pairwise admission rule (GRPH-22)

Recovery merge runs after `run_singleton_hac_refinement`, gated by
`ACX_RECOVERY_MERGE_ENABLED` (default `false` until the C1 policy block is
accepted). For residual singleton/small cluster R and candidate destination D
(by centroid cosine), admit **only if every clause holds for every moved
member**:

1. Every member of R has cosine ≥ `τ_pair` to ≥ k destination exemplars from
   k distinct source media.
2. R is internally coherent (all intra-R pairs ≥ `τ_intra`).
3. The runner-up destination's best pairwise score trails by ≥ δ for every
   member (competing-identity margin).
4. Neither R nor D is bound to a different named person.
5. The member's quality stratum is not abstained.

Any member failing any clause → the whole residual is abstained and a merge
suggestion is emitted. There is no partial move. Never merge by best edge.
Never use UMAP/t-SNE projections for merge decisions. Complete-link
safeguards stay. Numbers (`τ_pair`, `τ_intra`, δ, k ≥ 2, per-stratum floors,
suggestion-band cuts) come only from the accepted C1 calibration policy
block; this contract does not invent them.

On admission the producer writes one `cluster_merge_receipts` row
(`kind: auto`, `rule_version`, `expires_at = now + ACX_MERGE_UNDO_WINDOW_DAYS`).

## Housekeeping purge (RES-07)

The clustering run's last step purges receipts that are reverted
(`reverted_at` set) or expired (`expires_at` in the past). Same-rate
reclaimer: the writer of receipts is the writer of the purge. Clients never
delete receipts.

## LIFO revert

`revert_merge(tenant_id, receipt_id, path cluster id)`:

- Cross-tenant (receipt missing under this `tenant_id` / RLS) → **404**; do
  not leak receipt existence.
- Refuse `409` `merge_receipt_stale` unless path cluster id equals
  `receipt.survivor_cluster_id` AND every moved identity is still in the
  survivor cluster.
- Refuse `receipt_not_top` unless the receipt is the survivor's newest
  unreverted one.
- Refuse `receipt_expired` past `expires_at`.
- Restore the source cluster under its stored `source_cluster_id` (UUID
  reused). If that id is occupied, refuse `409` `merge_receipt_stale`.
- Restore `moved_identity_ids` into that cluster, labelled `source_label`
  when that label is non-empty, else `"<name> (restored)"` where `<name>` is
  the survivor's current display name (4.2.3 semantics). Set `reverted_at`.
- Return the restored `source_cluster_id`.
- Mirror `merge_cluster` step for step: move members, clear
  `moved_by_merge_id` on them, `recompute_representatives` +
  `recompute_centroid` for both clusters, best-effort `refresh_centroids_view`
  (warn, never roll back), delete stale `ClusterMergeSuggestion` rows for
  both clusters, set `identity_count` from a member count, broadcast
  `cluster_merge_reverted`.

Refusals other than cross-tenant 404 are `409` problem-details with `code`
(API-05). A second recovery run MUST NOT re-attach the restored cluster
solely because it was previously merged.

```json
{
  "type": "https://context-alt-text.dev/problems/receipt-not-top",
  "title": "Receipt is not the top unreverted merge",
  "status": 409,
  "code": "receipt_not_top"
}
```

```json
{
  "type": "https://context-alt-text.dev/problems/receipt-expired",
  "title": "Merge receipt has expired",
  "status": 409,
  "code": "receipt_expired"
}
```

```json
{
  "type": "https://context-alt-text.dev/problems/merge-receipt-stale",
  "title": "Merge receipt is stale",
  "status": 409,
  "code": "merge_receipt_stale"
}
```

## HTTP

Recognition (mounted by `svc-route-registry`; `_tenant_id = Depends(get_tenant_id)`):

- `GET /recognition/clusters/{cluster_id}/merge-candidates` →
  [recognition-cluster-merge-candidates-response.schema.json](../../../packages/shared-contracts/schemas/recognition-cluster-merge-candidates-response.schema.json)
- `POST /recognition/clusters/{id}/revert-merge` takes
  `(tenant_id, receipt_id, path cluster id)`; body `{ "receipt_id": "<uuid>" }`.
  Success returns the restored `source_cluster_id`.

WordPress:

- `GET acx/v1/roster/persons/{id}/merge-candidates` →
  [roster-merge-candidates-response.schema.json](../../../packages/shared-contracts/schemas/roster-merge-candidates-response.schema.json)
- `POST acx/v1/workbench/clusters/{id}/revert-merge` proxies the recognition
  revert body `{ "receipt_id": "<uuid>" }` with the path cluster id.

Band cuts are read from the accepted calibration policy block. No route
embeds literal similarity thresholds.

## Retired surfaces

The receipt revert is the only recognition undo surface. Implementation
lanes delete the following (greenfield delete-over-flag; no compatibility
shim):

- `POST /recognition/clusters/revert-merge` (no path cluster id; body
  source/target identifiers)
- WP `POST /acx/v1/recognition/clusters/revert-merge` and curation-sync
  `revert_merge_cluster`

Those routes must not remain as aliases of the receipt revert.

## Merge-candidate similarity (B6)

Candidate `similarity` is
`max(centroid cosine, latest pending ClusterMergeSuggestion similarity)`
over the canonical unordered pair (`min uuid`, `max uuid`). Only `pending`
suggestions not older than the latest cluster mutation participate. The band
rule applies after that max.

Person aggregation excludes candidates whose person_id equals the probe
person_id; the schema text says so and the service drops them.

## Projection path for quality and undo (B2, rg-015)

The snapshot `clusters[]` object is the only path by which quality and undo
availability reach WordPress. Four fields, stored as-is, never derived:

| Snapshot / projection column | Wire type | Source |
| --- | --- | --- |
| `representative_quality` | number \| null | Representative row `quality_score`, renamed at export (API-10). `representative_quality` normalizes sharpness before weighting. |
| `quality_components` | object \| null | Representative row `quality_components` (`confidence`, `bbox_area`, `sharpness`, `occlusion_severity`). `sharpness` is raw variance-of-Laplacian (minimum 0, unbounded above). |
| `representative_media_id` | integer \| null | Persisted representative identity's WP attachment ID |
| `undoable_merge_receipt_id` | uuid string \| null | Newest unreverted, unexpired receipt for that cluster |

`representative_quality` and `quality_components` are co-required (JSON
Schema `dependentRequired` / `dependencies` both ways). When components are
present they require all four parts; a missing signal is null, never omitted.

Absent fields stay null. Re-running bootstrap/targeted sync on the same
`snapshot_version` is a no-op (COR-1 / FLOW-06). Heal by reprocessing into a
fresh version. No PHP backfill. Roster
[roster-entry.schema.json](../../../packages/shared-contracts/schemas/roster-entry.schema.json)
reads those columns: `clusters[].representative_identity` carries
`representative_quality` and `quality_components`; `clusters[]` carries
`representative_media_id` and `undoable_merge_receipt_id`.

Workbench "Merged automatically · Undo" shows only while projected
`undoable_merge_receipt_id` is non-null, and submits that id.

The composite always ships with its parts (UXR-15). No tier recomputes
quality. `representative_media_id` is the attachment integer, not a UUID and
not parsed from `representative_thumb_path`.

## Operator merge audit (HAI-15)

Person merge is two-step. Step 1 shows `#merge-survivor` as an unranked,
score-free list in `name ASC`, filtered by `#merge-search` typeahead, and
requires a pick. The pick is committed to dialog state and sent as
`operator_initial_choice`. Step 2 (only after the pick) fetches merge
candidates and re-renders `#merge-survivor` sorted by similarity desc (name
asc within band). The merge request carries both `operator_initial_choice`
and the final survivor.

`POST acx/v1/roster/persons/merge` (commit) fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `survivor_id` | integer | Final confirmed survivor (`acx_persons.id`) |
| `loser_id` | integer | Absorbed person |
| `operator_initial_choice` | integer | Required. Positive existing same-tenant person id, not the loser. Audit only; never a ranking input |

`operator_initial_choice` is required on commit: a positive existing
same-tenant person id, not the loser. Missing or invalid gives `422`
`invalid_initial_choice`. It is stored on the WP merge record. It is not a
recognition receipt field. PHP MUST persist the submitted value and MUST NOT
replace it with the top ranked candidate.
