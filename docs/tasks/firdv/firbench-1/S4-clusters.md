# S4 · Cluster diagnostics per embedding space

- **Wave:** W3 batch C · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0, S1, S2 merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_clusters.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_clusters.py`

## Goal

Show how each leg's space groups people, as diagnostics and never as the decision. Everything is computed inside one leg's space (EMB-01). Projections are pictures, never inputs to metrics (VIZ-18, VIZ-19).

## Read first

- Scope doc § "Clustering: ML tactics and visualizations"
- `recognition/application/orchestration/clustering/discovery_pipeline.py`: `prepare_cluster_caches` (bounded read). Evaluate the production clustering path as one config, beside a reference threshold clustering at the frozen τ.
- W2 inventory § "Dependencies" (whether `umap-learn` is importable on the VM)

## Build

1. Partition metrics against GT identities: pairwise precision/recall, B-cubed precision/recall, false-merge count, fragmentation count, unknown-absorbed count (unknown faces placed into a named cluster), singleton/noise fraction under an explicit noise policy.
2. `order_stability(cluster_fn, vectors, *, n_orders, seed)`: re-run with permuted insertion orders and report the fraction of co-assignment pairs that are stable.
3. `chaining_check`: held-out pairs whose cluster link path passes through a third identity (GRPH-18, GRPH-22).
4. `mutual_knn_graph(vectors, k)` (GRPH-17).
5. Dendrogram via `scipy.cluster.hierarchy.linkage` on cosine distance:
   - `method` must be `average` or `complete`. `ward`, `median` and `centroid` raise `LinkageMetricError`.
   - The cut is at distance 1 − τ from `scores.json`.
   - Return linkage, cut labels and the cophenetic correlation.
6. `pca_spectrum`: explained-variance ratio per component and effective dimension (participation ratio).
7. Companions:
   - intra/inter-identity cosine histograms and norm histograms
   - kNN-Jaccard drift between two runs of the same leg key
   - linear CKA between two runs of the same leg kind (same dimension only; otherwise refuse)
8. `projection_coords(vectors, *, n_neighbors, min_dist, seed)`:
   - Uses UMAP when available. Otherwise returns `unavailable` and the report shows the PCA-2 scatter labelled the same way.
   - Parameters and versions are stored with the coordinates.
   - The output object carries a `diagnostic_only` flag.
   - Any metric function receiving it raises `ProjectionLeakError`.
9. `clusters.json` writer, deterministic.

## RED tests

- Known partition: 3 identities with one planted merge and one planted split give exact pairwise and B-cubed values. Relabelling the clusters leaves them unchanged.
- `ward` on cosine raises `LinkageMetricError`.
- Metrics are byte-identical when projection parameters change. Passing projection coords to a metric raises `ProjectionLeakError`.
- CKA of a space with itself is 1. CKA across different dimensions refuses.
- Order stability is 1.0 for a deterministic order-free clusterer on separated blobs.

## Done when

Tests pass on the VM. Owns the AE-9 linkage and projection refusals.
