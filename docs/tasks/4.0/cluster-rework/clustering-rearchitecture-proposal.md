# Facial Clustering Re-Architecture (Accuracy-First)

## Goals
- Minimize false negatives (split same person across clusters) and false positives (merge different people).
- Stay robust as clusters grow; avoid “average face” drift while incorporating diverse/low-quality angles.
- Accept higher compute/storage in exchange for accuracy; commercial-license-friendly dependencies only.

## Observed Issues (from current pipeline)
- Batch isolation: new batches don’t fully reconcile with existing clusters; centroid-only merges miss high-sim pairs.
- Centroid drift: more images can push centroids toward a generic face, hurting future assignments.
- Sparse representative coverage; rep matching fails when reps are few or non-diverse.
- Ward linkage/threshold is global; struggles with variable density and cross-batch connectivity.

## Proposed Pipeline (outline)
1) **Preprocess embeddings**:
   - L2-normalize (keep raw embedding too).
   - Optional PCA → whitening (e.g., 512→256 or 1024→256) to de-correlate and reduce noise; store both normalized and whitened vectors.
   - Quality score per embedding (detection confidence, blur/occlusion heuristic) used as weights.
2) **Representative management**:
   - Maintain diverse reps per cluster via k-center/farthest-point sampling on normalized/whitened embeddings.
   - Cap per-media/per-cluster reps, refresh reps when clusters change (merges/splits).
3) **Assignment of new identities** (always includes existing reps):
   - Rep matching first; require mutual similarity above threshold (rep↔identity) to reduce FPs.
   - If unmatched, append identities to a staging set for batch clustering.
4) **Batch clustering (accuracy-first)**:
   - Build a **mutual k-NN graph** (e.g., k=50) on normalized or whitened embeddings (new identities + existing reps) using FAISS/Annoy for speed; prune edges below similarity threshold (~0.6).
   - Run **HDBSCAN** on the k-NN graph (variable density, labels + noise). Alternative: Leiden/Louvain on the graph if HDBSCAN not available; keep **Ward** as a small-batch fallback (<= few hundred).
   - Label propagation: if a cluster contains reps with labels, propagate the most confident label.
5) **Post-cluster merge pass**:
   - Build centroid/repr k-NN graph of all clusters; merge pairs above threshold to reconcile cross-batch splits.
   - After merge, refresh reps and labels.
6) **Split/cleanup**:
   - For clusters with high internal variance or low pairwise sims, re-run HDBSCAN locally to split; reselect reps.
7) **Incremental learning**:
   - When users merge clusters or correct misassignments, update reps and re-run local merge/split on affected clusters.
   - Optional lightweight fine-tuning: maintain a per-tenant centering/whitening transform updated with new data.

## Algorithm Choices & Rationale
- **k-NN Graph + HDBSCAN**: Handles variable density, reduces need for global threshold, labels noise, and improves FN/FP balance. Use mutual k-NN to avoid “bridges”.
- **Community Detection (Leiden/Louvain)**: Viable alternative on the same graph; good for larger graphs when HDBSCAN isn’t available.
- **Ward (fallback)**: Keep for small N; consistent and deterministic.
- **Chinese Whispers (optional)**: Only if using a sparse k-NN graph; avoid full similarity matrix to control O(N²).
- **PCA/Whitening**: Reduces correlation/noise in embeddings, often improves cosine clustering; keep original vectors for downstream recognition if needed.
- **Raw pixels**: Avoid for clustering—use embeddings to stay model-agnostic and performant; focus on better embedding preprocessing/graph construction instead.

## Parameter Suggestions (tunable)
- similarity_threshold: ~0.6 (align across assignment, edges, merges).
- k (k-NN): 30–50; mutual k-NN to prune weak bridges.
- HDBSCAN: min_cluster_size ~5–10; min_samples ~1–5; use cosine metric on normalized/whitened vectors.
- PCA dims: 1024→256 (adjust per model); whitening on the reduced space.
- Reps: max 10 per cluster; per-media cap 2–3; refresh after merges/splits.
- Auto-merge cap: apply centroid/repr merges when total identities <= configurable max to limit O(N²) checks.

## Telemetry & Validation
- Per-identity decision logs: best rep sim, best centroid sim, chosen path.
- Graph stats: nodes, edges, sparsity, k, threshold; HDBSCAN params; cluster count/size distribution; noise rate.
- Merge stats: candidate pairs above threshold, merges performed/skipped.
- Quality stats: intra-cluster sim distribution; inter-centroid top similarities.
- Evaluations: FN/FP on labeled sets; before/after merge; effect of PCA/whitening.

## Open Questions / Clarifications
- Target batch sizes for typical runs (to tune k and caps).
- Availability of labeled pairs for offline tuning (to set thresholds/k/HDBSCAN params).
- Whether adding FAISS/Annoy and HDBSCAN is acceptable in production dependencies.
- Preferred handling of noise/unclustered faces (discard vs hold for later batches).***
