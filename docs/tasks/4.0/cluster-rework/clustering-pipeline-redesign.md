# Clustering Pipeline Redesign (Accuracy-First, Greenfield)

## Context & Pain Points
- Current pipeline: representatives (Stage 1) + Ward linkage (Stage 2) on remaining identities, optional centroid-based merge. Experimental Chinese Whispers present.
- Issues: high false negatives and false positives; batch-to-batch splits; quality degrades as clusters grow (centroid drift toward “average face”).
- Goal: maximize accuracy, accept higher compute/storage, ensure clusters improve recognition over time (including odd angles/occlusions/noisy images).

## Proposed Architecture (High Accuracy Over Speed)
1) **Preprocessing & Embeddings**
   - Keep high-quality face embeddings as the primary feature; raw pixel clustering is infeasible at scale and less robust to pose/lighting than learned embeddings.
   - Normalize embeddings (L2). Optionally add **PCA + whitening** to 256–512 dims:
     - Rationale: decorrelate dimensions, stabilize similarity scales, and reduce noise; can improve DBSCAN/HDBSCAN performance.
     - Store both raw and whitened vectors if needed for compatibility.
   - Quality gating: down-weight or drop very low detection scores; keep “odd angle/occluded” embeddings but mark them with quality metadata for weighting, not exclusion.

2) **Representative Management (Hard Gate)**
   - Maintain diverse representatives per cluster (farthest-point / k-center selection); enforce per-media caps to avoid near-duplicate domination.
   - Always attempt rep matching first for new identities; rep similarity should be the primary assignment path to avoid centroid drift.
   - Periodically refresh reps after merges/splits to keep diversity.

3) **Sparse Graph Construction (k-NN)**
   - Build a **mutual k-NN graph** (e.g., k=50) on normalized (optionally whitened) embeddings for the current run:
     - Use FAISS/Annoy for k-NN to avoid full O(N²).
     - Prune edges below the assignment threshold (~0.6–0.65) and require mutual edges to avoid bridging.
   - For cross-batch consistency, include existing cluster representatives (or centroids as a fallback) in the graph so new faces can connect to prior clusters.

4) **Primary Clustering Algorithm**
   - **HDBSCAN** on the k-NN graph (preferred):
     - Handles variable density, marks noise, less sensitive to a single global epsilon.
     - Good for reducing false negatives/positives in face data with mixed densities.
   - Alternate/backup: **Community detection** (Leiden/Louvain) on the mutual k-NN graph if HDBSCAN isn’t available.
   - Keep **Ward linkage** as a fast path for small batches (≤ few hundred) where O(N²) is acceptable.
   - Thresholds aligned: use the same similarity threshold for edge pruning, assignment, and centroid merges to avoid inconsistent decisions.

5) **Post-Clustering Merge/Split**
   - After clustering, run a **centroid/representative graph merge**:
     - Build a centroid k-NN graph; merge clusters whose centroid/rep similarity ≥ assignment threshold.
     - Apply label propagation: if any merged cluster is labeled, carry label forward.
   - For outliers/noise (HDBSCAN noise points), attempt rep matching; if none, keep as singleton or queue for human review.
   - For misassignments: allow removing a member and rerun a local recluster (HDBSCAN/DBSCAN) on that cluster’s members, then refresh reps.

6) **Cross-Batch & Incremental Handling**
   - For new batches, cluster over new identities + existing reps to enable cross-batch merges.
   - Periodic scheduled merge job over all clusters/reps to reconcile historical splits.
   - Maintain a per-tenant k-NN index to avoid recomputing neighbors from scratch.

7) **Improving Recognition as Clusters Grow**
   - Use reps (not centroids) for recognition; update reps with diversity-aware selection as clusters grow (include “odd angles/occlusions” to improve generalization).
   - Optionally fine-tune a per-tenant similarity calibration: track intra-/inter-cluster similarity distributions to adjust thresholds dynamically.
   - Track “hard positives” (difficult samples that are correctly assigned) to bias future matching toward broader pose/lighting coverage.

8) **Telemetry & Debug**
   - Per-identity decision logs: best rep sim, best centroid sim, path taken.
   - Graph stats: nodes, edges, sparsity, k, threshold; HDBSCAN params; cluster count/size distribution; noise rate.
   - Merge stats: candidate pairs, merges performed/skipped.
   - Similar cluster diagnostics: centroid k-NN pairs above threshold (for auditing).

9) **Dependencies (commercial-friendly)**
   - Add `hdbscan` (BSD) and `faiss-cpu` or `annoy` for k-NN graph.
   - Keep `networkx` only for diagnostics; for production, rely on k-NN + HDBSCAN/community detection.

## Rationale Highlights
- **Graph + HDBSCAN**: More tolerant of variable density than Ward, less order-sensitive, better at reducing FNs/FPs when threshold and k are tuned.
- **Mutual k-NN**: Avoids spurious bridges; scales better than full similarity matrix.
- **PCA + Whitening**: Helps stabilize similarity scales and reduce noise; beneficial before density-based clustering.
- **Representative-first matching**: Prevents centroid drift and leverages diverse examples, improving recognition as clusters grow (even with odd angles/occlusions).
- **Post-merge on centroids/reps**: Catches batch-induced splits and propagates labels.

## Open Questions / Clarifications
- Target k and batch size ranges? (e.g., typical N per run, max N).
- Acceptance of additional native dependencies (e.g., FAISS) vs pure Python?
- Availability of labeled evaluation sets to benchmark Ward vs HDBSCAN vs CW?
- Desired noise handling (flag vs auto-assign) and UI expectations for merge/split suggestions.
