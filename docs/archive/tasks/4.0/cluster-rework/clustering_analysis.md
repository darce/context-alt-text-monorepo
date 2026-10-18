# Clustering Analysis & Findings

## Current Implementation Status
The current `IdentityClusteringService` employs a hybrid approach:
1.  **Incremental Clustering**: Uses `RepresentativeMatcher` to match new identities against existing cluster representatives.
    *   **Logic**: 
        *   Checks representative similarity.
        *   If "borderline" (0.6-0.7), validates against cluster centroid.
        *   If enabled, validates against random cluster members to prevent drift.
        *   If no representative match, checks centroid similarity for all clusters.
        *   If no centroid match, creates a new cluster.
2.  **Batch Clustering (Stage 2)**: Uses Ward linkage hierarchical clustering (`sklearn.cluster.AgglomerativeClustering`).
    *   **Logic**: Applied when there are multiple unclustered identities (e.g., initial load or fallback).
    *   **Metric**: Euclidean distance on normalized embeddings (equivalent to cosine distance).

## Benchmark Results
A synthetic benchmark was created to evaluate the Ward clustering component:
*   **Easy Dataset** (Low noise, distinct clusters):
    *   **ARI (Adjusted Rand Index)**: 1.0000 (Perfect)
    *   **Homogeneity**: 1.0000
    *   **Completeness**: 1.0000
*   **Hard Dataset** (High noise, overlapping/borderline clusters):
    *   **ARI**: ~0.0000 (Failure)
    *   **Observation**: The current threshold-based Ward clustering collapses or fragments significantly when noise increases.

## Problem Analysis
The user reports "many false positives and even more false negatives".
*   **False Positives**: Likely due to:
    *   **Greedy Incremental Matching**: The first representative that passes the threshold accepts the identity. If a cluster has a "bad" representative (outlier), it can attract non-matching identities.
    *   **Centroid Drift**: As clusters grow, the centroid might shift, or the "borderline validation" might be too lenient.
    *   **Fixed Thresholds**: A global similarity threshold (0.6) might be too loose for some dense regions of the embedding space and too strict for others.
*   **False Negatives**: Likely due to:
    *   **Strict Thresholds**: Valid matches slightly below 0.6 are rejected.
    *   **Representative Coverage**: If a cluster's representatives don't cover the variance of the face (pose, lighting), new variations won't match.
    *   **Ward Linkage Limitations**: Ward minimizes variance, which tends to produce spherical clusters of similar size. It struggles with uneven cluster sizes or non-spherical shapes.

## Proposed Improvements
1.  **DBSCAN (Density-Based Spatial Clustering of Applications with Noise)**:
    *   *Pros*: Does not require specifying number of clusters. Can find arbitrarily shaped clusters. Handles noise (outliers) well (points not assigned to any cluster).
    *   *Cons*: Sensitive to parameters (`eps`, `min_samples`). Hard to use with varying densities.
    *   *Applicability*: Good for "cleaning" data or batch processing, but `eps` tuning is critical.

2.  **Chinese Whispers**:
    *   *Pros*: Graph-based, very effective for face clustering (used in Dlib). Linear time complexity. No need to specify K.
    *   *Cons*: Heuristic-based, non-deterministic (order matters).
    *   *Applicability*: Strong candidate for face clustering.

3.  **HDBScan (Hierarchical DBSCAN)**:
    *   *Pros*: improved version of DBSCAN. Robust to varying densities.
    *   *Cons*: Slower than simple DBSCAN.

4.  **Refined Hybrid Pipeline**:
    *   **Strict First Pass**: High-precision matching (e.g., threshold 0.75) to form reliable "cores".
    *   **Loose Second Pass**: Try to merge cores or attach singles using a more global view (e.g., graph-based or DBSCAN on centroids).
    *   **Representative Management**: Improve how representatives are chosen (e.g., "medoids" or "boundary points" rather than just random or first-seen).

## Recommendation
Given the goal of **accuracy** over speed:
1.  **Replace/Augment Ward with DBSCAN or Chinese Whispers** for the batch stage. DBSCAN is available in `sklearn`. Chinese Whispers would need implementation or a library.
2.  **Adaptive Thresholding**: Instead of a hard 0.6, consider local density.
3.  **Post-processing Verification**: A "re-clustering" step that periodically reviews clusters to split false positives (e.g., checking if a cluster has two distinct sub-groups).

For the immediate next step, implementing **DBSCAN** as an alternative to Ward in the `_stage2_batch_clustering` seems like the most direct path to test if density-based clustering handles the "hard" cases better than variance-minimization (Ward).
