# Facial Clustering Rework Proposal (Accuracy-First)

## Goals
- Maximize clustering accuracy (minimize false negatives/positives) even with higher compute/storage.
- Improve over time as clusters grow; avoid drift toward “average face”.
- Handle mixed workflows: one-shot 5k+ library, incremental batches, merge/split corrections.

## Pipeline Proposal
### 0. Preprocessing (Embeddings)
- Continue using face embeddings (robust to lighting/pose). Add optional PCA/whitening to reduce noise and align variance:
  - PCA → 256–512 dims, whitening to equalize variance; reduces dominance of high-variance axes.
  - Keep raw + whitened embeddings if storage allows; use whitened for clustering/search.
- Quality gating: down-weight or exclude low-confidence detections; store `quality_score`.
- Normalize to unit vectors; standardize threshold semantics.

### 1. Representative Matching (Hard Gate)
- Keep rep-based assignment as first step. Improve reps:
  - Diversity-aware selection (farthest-point/k-center), cap per media, refresh after merges/splits.
  - Optionally maintain PCA/whitened reps too.
- Always include existing reps in clustering batches to allow cross-batch merges/label propagation.

### 2. Graph-Based Clustering (Primary Path)
- Build a **mutual k-NN graph** (e.g., k=50) over normalized (optionally whitened) embeddings for current batch + relevant reps:
  - Use FAISS/Annoy for scalable k-NN; store index per tenant for reuse across batches.
  - Edges: cosine similarity; prune below threshold (~assignment threshold).
  - Mutual k-NN to avoid weak one-way bridges.
- Run **HDBSCAN** (preferred) or **community detection (Leiden/Louvain)** on this sparse graph:
  - HDBSCAN handles variable density, labels noise; better than global-threshold Ward for mixed-quality faces.
  - Community detection is an alternative if HDBSCAN is unavailable; both operate on the k-NN graph.
- Keep **Ward linkage** as a fallback for small batches (<= few hundred) where O(N²) is fine.

### 3. Post-Clustering Merge/Split
- Centroid/rep merge pass: build centroid or rep-set k-NN graph; merge clusters above similarity threshold (aligned with assignment threshold). If any merged cluster has a human label, propagate it to the merged cluster.
- Split low-quality clusters: rerun HDBSCAN/graph clustering on a cluster’s members if internal similarities drop below threshold or user flags errors.
- Label propagation: if reps are labeled, propagate to cluster and update reps.

### 4. Incremental & One-Shot Flows
- **One-shot 5k+**: mutual k-NN + HDBSCAN/community detection on all embeddings (possibly after PCA/whitening). Use stored k-NN index to avoid full O(N²) distances.
- **Incremental batches**: rep-match; cluster new + reps with graph method; post-merge across existing clusters via centroid/rep graph.
- **User merges/splits/removals**: re-run local HDBSCAN/merge on affected clusters; refresh reps.

## Rationale (Algorithms & Preprocessing)
- **Why embeddings**: robust to pose/lighting; dimensionality manageable. Raw pixels would require heavy augmentation/modeling and are less practical for clustering.
- **Why PCA/whitening**: reduces noise, aligns variance, mitigates dominance of high-variance axes; can improve neighborhood structure for clustering/ANN.
- **Why graph + HDBSCAN**: handles variable densities, non-parametric cluster count, marks noise; mutual k-NN reduces chaining/bridging vs full graph; better suited to avoid both FNs and FPs.
- **Why Ward fallback**: stable/deterministic for small N; keep for tiny batches/tests.

## Improving Over Time (Avoid “Average Face” Drift)
- Maintain diverse reps; refresh reps after merges/splits.
- Use rep-based assignment (actual faces) instead of centroids for matching; centroids only for merge/suggest.
- Periodic merge pass on centroids/reps to reconcile splits.
- Track cluster health: min/avg pairwise similarity, noise rate; trigger re-cluster on degraded clusters.

## Dependencies (commercial-friendly)
- Add `hdbscan` (BSD) and `faiss-cpu` or `annoy` for k-NN graph construction.
- Optional: `leidenalg`/`igraph` for community detection (check licensing), otherwise use NetworkX or rely on HDBSCAN.

## Telemetry & Diagnostics
- Per-identity decision logs: best rep sim, best centroid sim, path taken.
- Graph stats: nodes, edges, sparsity, k, threshold, HDBSCAN params, cluster sizes, noise fraction.
- Merge stats: candidate pairs above threshold, merges performed/skipped.
- Scripts: k-NN overlap/quality checks; similar-centroid finder; rep coverage report.

## Open Questions / Clarifications
- Do we have labeled validation sets to tune thresholds/k/min_cluster_size?
- What is the typical batch size distribution (to set k and caps)?
- Do we need hard latency budgets for online paths, or can we offload to async jobs by default?
- Any constraints on adding FAISS/HDBSCAN in the target deployment?
