# S4 · Cluster diagnostics per embedding space

- **Wave:** W3 batch C · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0, S1, S2 merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_clusters.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_clusters.py`

## Goal

Show how each leg's space groups people, as diagnostics and never as the decision. Everything is computed inside one leg's space (EMB-01). Projections are pictures, never inputs to metrics (VIZ-18, VIZ-19).

## Read first

- Scope doc § "Clustering: ML tactics and visualizations"
- `recognition/application/orchestration/clustering/discovery_pipeline.py`: `prepare_cluster_caches(assignment_writer, tenant_id, *, session=None)` is async and DB-coupled. S4 does not call it, and no S4 code reads a tenant store. S4 implements pure numpy reference threshold clustering in `firbench_clusters.py` as `reference_threshold_cluster(vectors, *, similarity_threshold)` (S0 Build 10). It takes the leg's vectors from `cache.npz` and records the production config (HDBSCAN, and its epsilon source `recognition/application/discovery/graph/selection.py:44-46`) as metadata only.
- W2 inventory § "Dependencies" (whether `umap-learn` is importable on the VM)

## Build

1. Partition metrics against GT identities. Units are GT faces. Only `named` faces are scored; `unknown` and `unresolved` faces are excluded from every pairwise and B-cubed value.
   - Noise policy: a face labelled `-1` is noise (every singleton cluster is labelled `-1`). A noise face forms no predicted pair. It counts as a missed true pair in pairwise recall. In B-cubed it is a cluster of size 1.
   - Pairwise precision = co-assigned true pairs / co-assigned predicted pairs; pairwise recall = co-assigned true pairs / all true pairs. Both over named faces.
   - B-cubed precision and recall are averaged over named faces.
   - Merges = named clusters holding two or more identities. Fragmentation = identities split over two or more clusters.
   - Unknown-absorbed = `unknown` faces placed in a cluster that holds at least one named face. An unknown face never adds a true pair.
   - Singleton/noise fraction = noise faces / named faces.
2. `order_stability(cluster_fn, vectors, *, n_orders, seed)`: `cluster_fn` maps a vector array to labels; the driver passes `functools.partial(reference_threshold_cluster, similarity_threshold=s)`. Re-run with permuted insertion orders and report the fraction of co-assignment pairs that are stable.
3. `chaining_check`: held-out pairs whose cluster link path passes through a third identity (GRPH-18, GRPH-22).
4. `mutual_knn_graph(vectors, k)` (GRPH-17).
5. Dendrogram via `scipy.cluster.hierarchy.linkage` on cosine distance `d = 1 − x·y` of unit vectors (GRPH-18):
   - `method` must be `average` or `complete`. `ward`, `median` and `centroid` raise `LinkageMetricError`.
   - The dendrogram is cut at `d = 1 − s`, where `s` is the production similarity threshold recorded in the run manifest's `firbench` block (S6a writes it from `settings.similarity_threshold`). HDBSCAN's Euclidean `cluster_selection_epsilon = sqrt(2(1 − s))` is recorded as metadata and is never the dendrogram height.
   - The acceptance τ from `scores.json` is drawn as a separate reference line at `d = 1 − τ`, labelled `acceptance τ (not a cluster cut)`. τ is a 1:N acceptance quantity, not a pairwise linkage height, so the two are never identified. For τ = 0.41 the line sits at d = 0.59.
   - If no production threshold is recorded for a leg, the dendrogram is written uncut with the caption `no production cut recorded`, and cut labels are null.
   - Return linkage, cut labels (or null) and the cophenetic correlation.
6. `pca_spectrum`: explained-variance ratio per component, effective dimension (participation ratio) and the retained component count, which is written beside the spectrum. Variance spectra do not preserve pairwise distances; a truncated display can drop pair geometry.
7. Companions:
   - intra/inter-identity cosine histograms and norm histograms
   - kNN-Jaccard drift between two runs of the same leg key
   - linear CKA between two runs of the same leg kind (same dimension only; otherwise refuse)
8. `projection_coords(vectors, *, n_neighbors, min_dist, seed)`:
   - Uses UMAP when available. Otherwise returns `unavailable` and the report shows the PCA-2 scatter labelled the same way.
   - Parameters and versions are stored with the coordinates.
   - The output object carries a `diagnostic_only` flag.
   - Any metric function receiving it raises `ProjectionLeakError`.
9. `clusters.json` writer, deterministic, validated against `clusters-v1` (S0 Build 9). It holds the partition metrics, the dendrogram cut and its caption, the production config metadata and the parameters of every projection.

## RED tests

- Known partition: 3 identities with one planted merge and one planted split give exact pairwise and B-cubed values. Relabelling the clusters leaves them unchanged.
- Noise and unknown semantics: a noise face is a missed pair in pairwise recall and a size-1 cluster in B-cubed; an unknown face placed with a named face increments unknown-absorbed and adds no true pair.
- Dendrogram: with `s` = 0.80 the cut is at `d` = 0.20. The acceptance τ = 0.41 line is drawn at `d` = 0.59 and is labelled `acceptance τ (not a cluster cut)`. With no recorded `s`, the output has null cut labels and the caption `no production cut recorded`.
- `ward` on cosine raises `LinkageMetricError`.
- Metrics are byte-identical when projection parameters change. Passing projection coords to a metric raises `ProjectionLeakError`.
- CKA of a space with itself is 1. CKA across different dimensions refuses.
- Order stability is 1.0 for a deterministic order-free clusterer on separated blobs.

## Done when

Tests pass on the VM. Owns the AE-9 linkage and projection refusals.
