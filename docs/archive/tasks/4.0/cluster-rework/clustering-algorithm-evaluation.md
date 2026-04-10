# Clustering Algorithm Evaluation (Chinese Whispers vs Current Pipeline)

## Context
- Current pipeline in `apps/prototype-description-service/recognition/application/identity_clustering_service.py`:
  - Representative-based matching to existing clusters (Stage 1).
  - Ward linkage (hierarchical agglomerative clustering) on remaining identities (Stage 2) with cosine→Euclidean conversion on unit vectors.
  - Optional auto-merge pass using centroid similarity.
- Observed issues: high false negatives (same person split across clusters) and false positives. Batch-to-batch consistency remains problematic.
- New alternative: `chinese_whispers.py` implements Chinese Whispers (CW) graph clustering.

## 1) Quality of the Chinese Whispers Implementation
- Uses NetworkX, normalizes embeddings, computes full similarity matrix, adds edges above an `edge_threshold` (default `similarity_threshold + 0.05`), runs label propagation for up to `cw_iterations` (default 20).
- Strengths:
  - Deterministic enough with early convergence; random shuffle per iteration reduces bias.
  - Edge weights based on cosine similarity; weighted voting among neighbors is faithful to CW.
  - Creates clusters from label assignments and reuses existing cluster creation callback.
  - Straightforward code; logs nodes/edges, iterations.
- Gaps/risks:
  - Quadratic memory/time to build full similarity matrix (`np.dot` over N x N). For N=5k, ~25M entries (~100 MB float32) but may spike; beyond that, performance/memory may degrade.
  - Edge threshold default is arbitrary (+0.05 over similarity threshold); no dynamic tuning based on data distribution.
  - No degree/edge pruning beyond threshold; susceptible to “bridges” if threshold is too low.
  - No batching/approximation; all-pairs similarity is computed.
  - Lacks telemetry on cluster size distribution, edge counts, convergence stats beyond debug log.
  - No guard for disconnected nodes beyond singleton cluster creation.

## 2) Suitability vs Current Problem
- Goal: maximize accuracy (reduce false negatives), willing to pay compute/storage.
- CW suitability:
  - Pros: Graph-based methods often excel at capturing manifold structure, can avoid chaining effects seen in hierarchical clustering if threshold is tuned well; non-parametric (no cluster count) and robust to order.
  - Cons: Needs dense edge computation; quality hinges on a well-chosen edge threshold to avoid bridges or fragmentation. Without pruning or validation, 0.77 similarity pairs may still land in separate components if no strong edge connects them.
- Compared to Ward:
  - Ward linkage is variance-minimizing but sensitive to threshold conversion and normalization; can split if batch boundaries stop cross-batch merges.
  - CW could be more tolerant of varying densities but requires careful edge threshold + potential k-NN sparsification to prevent over-connecting.
- Given high false negatives, CW could help if:
  - We set edge threshold close to assignment threshold (e.g., 0.6) and ensure k-NN or mutual-NN edges to connect likely pairs.
  - We run CW on the combined set of new + existing embeddings (or representatives) rather than only the new batch.
- Given willingness to trade performance for accuracy, CW is a viable alternative/supplement, but needs safeguards and tuning.

## Recommendations
- Integrate CW as an optional Stage 2 alternative behind a flag for high-accuracy runs; default to a moderate edge threshold (≈0.6) with k-NN pruning (e.g., top-50 mutual neighbors) to avoid bridging while ensuring connectivity.
- Add telemetry: nodes, edges, sparsity, iterations, cluster size stats, min/max/mean edge weights of chosen labels.
- Run CW on representatives + new identities or on all unclustered identities (with a manageable cap) to allow cross-batch merges.
- Keep Ward available; empirically compare CW vs Ward on labeled validation sets to choose defaults.

## Additional Debug Data Needed
- Logs of representative matching decisions (best rep/centroid sims) for split cases.
- Cluster similarity matrix (top centroid pairs) after clustering to see if auto-merge should have merged.
- Distribution of pairwise similarities within/between clusters for problem tenants.
- Batch sizes and whether async path was taken (to confirm cross-batch merges are considered).

## Next Steps
- Add a feature-flagged CW path in the pipeline for batches under a configurable cap (e.g., <= 2k identities).
- Implement k-NN edge construction (mutual top-K) and expose `cw_threshold`, `cw_k`, `cw_iterations` in settings.
- Add telemetry and diagnostic scripts (e.g., similar-cluster finder already added) to compare CW vs Ward on real data.***
