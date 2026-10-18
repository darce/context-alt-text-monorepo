# Clustering Redesign Proposals (Accuracy-First)

## Goals
- Maximize clustering accuracy (minimize FNs/FPs) even at higher compute/storage cost.
- Preserve/improve recognition quality as clusters grow (no drift toward “average face”).
- Handle large one-shot batches (5k+) and incremental uploads with consistent results.
- Support post-cluster merge/split operations to correct mistakes and improve future matches.

## Preprocessing
- **Embedding normalization**: keep L2 normalization.
- **PCA/Whitening (optional, tuned)**: reduce to 256–512 dims with whitening to de-correlate features and suppress noise; helps HDBSCAN/graph methods by equalizing variance. Keep raw embeddings for backup; store whitened alongside normalized.
- **Quality gating**: drop or down-weight low-confidence detections before clustering; maintain `quality_score` per embedding for edge weights.
- **k-NN graph cache**: build/maintain a mutual k-NN index (FAISS/Annoy) per tenant for recent identities/reps to avoid all-pairs O(N²) and enable cross-batch consistency.

## Clustering Pipeline (proposed)
1) **Representative matching (hard gate)**: always try reps first; ensure reps are diverse (farthest-point/k-center) and refreshed on cluster changes. Assign new identities to labeled clusters when reps match above threshold.
2) **Graph-based clustering on k-NN graph** (primary for accuracy):
   - Build mutual k-NN graph on normalized (optionally whitened) embeddings of (new identities + existing reps for context).
   - Edge weights = cosine sim; prune edges below assignment threshold (~0.6–0.65) to avoid bridges.
   - **HDBSCAN** on the k-NN graph (preferred) to handle variable density; parameters exposed (`min_cluster_size`, `min_samples`, `cluster_selection_epsilon`).
   - For small batches (<~300), allow **Ward linkage** fallback (deterministic, simple) if desired.
   - Optional **community detection** (Leiden/Louvain) on the same k-NN graph as an alternative when HDBSCAN under/over-clusters; keep feature-flagged.
3) **Post-cluster merge (centroid/rep graph)**:
   - Build centroid (or representative-set) k-NN graph; merge clusters whose centroids/rep-sets exceed threshold (aligned with assignment threshold).
   - Propagate labels: if any merged cluster is labeled, apply to merged result.
4) **Noise handling**:
   - HDBSCAN marks noise; retain noise points for future attempts as more data arrives.
   - Allow optional “singleton to nearest cluster” assignment under a stricter threshold for UX (flagged).

## Incremental / Cross-Batch Strategy
- When clustering a new batch, include existing reps (or a sample of centroids) in the graph so cross-batch merges are possible immediately.
- Periodic job: rerun centroid/rep graph merge across all clusters to fix historical splits.
- Maintain k-NN index incrementally; update reps after merges/splits.

## Label Stability / Drift Avoidance
- Never match directly to centroids when reps exist; use reps for assignment.
- Keep reps diverse and capped per media and per cluster to avoid near-duplicate dominance.
- Store both raw and whitened embeddings; use the more stable space for clustering; keep raw for matching if needed.
- For labeled clusters, ensure representative refresh doesn’t evict rare poses; use farthest-point with label lock.

## Handling the Three UX Workflows
1) **One-shot 5k+ library**: mutual k-NN graph + HDBSCAN (or Leiden) on all embeddings; k tuned to balance sparsity/recall; optional PCA-whitening for stability. Ward only for small batches.
2) **Post-run merge of discrete clusters**: centroid/rep k-NN merge pass; surface suggestions; merging should improve future accuracy (reps/labels updated).
3) **Remove misassigned faces**: remove membership, refresh reps, optionally rerun HDBSCAN on that cluster’s members to re-split; keep noise points for reprocessing.

## Dependencies (commercial-friendly)
- `hdbscan` (BSD), `faiss-cpu` or `annoy` for k-NN graph, keep `networkx` only for diagnostics; consider `leidenalg/igraph` if allowed for community detection.

## Telemetry to Add
- Per-identity decision log: best rep sim, best centroid sim, chosen path.
- Graph stats: nodes, edges, k, threshold, sparsity, cluster counts/size distribution, noise rate, HDBSCAN parameters.
- Merge stats: candidate pairs over threshold, merges performed/skipped.
- Similar-cluster diagnostics (already have a script; extend to reps).

## Open Questions
- Do we have labeled eval sets to tune thresholds (per-tenant vs global)?
- What’s the typical batch size distribution (to choose k/limits)?
- Hardware constraints for acceptable runtime on 5k+ faces (CPU vs GPU for FAISS/HDBSCAN)?***
