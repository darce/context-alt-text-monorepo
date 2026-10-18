# Clustering Algorithm Comparison

## Use Case Analysis

### 1. Batch Clustering (5000+ images, one shot)
*   **Requirement**: High accuracy, reasonable speed, handle noise (non-faces or unknown faces).
*   **DBSCAN**:
    *   *Pros*: Excellent at finding arbitrary shapes and rejecting noise (outliers). `O(n log n)` with spatial indexing (like KD-tree), though high-dimensional data (128d/512d) degrades this to `O(n^2)`.
    *   *Cons*: Sensitive to `eps` (distance threshold). If the density of face clusters varies (some people have tight clusters, others loose), it fails.
*   **HDBSCAN**:
    *   *Pros*: Handles varying densities much better than DBSCAN. Often "just works" with fewer parameters.
    *   *Cons*: Slower than DBSCAN. Complexity is higher.
*   **Chinese Whispers (CW)**:
    *   *Pros*: **Linear time complexity** `O(E)` where E is edges. Extremely fast for large datasets. Used by Dlib for this exact purpose.
    *   *Cons*: Non-deterministic (results can vary slightly between runs). Heuristic-based. Requires building a graph first (adjacency matrix), which is `O(n^2)` unless using approximate nearest neighbors (ANN).

### 2. Incremental Improvement (Merging & Adding Samples)
*   **Requirement**: Merging discrete clusters should improve the "model" of that person.
*   **DBSCAN/HDBSCAN**:
    *   *Challenge*: These are typically "batch" algorithms. To add data, you often re-run or use complex "incremental" variants.
    *   *Merging*: Merging two clusters in DBSCAN effectively means finding a bridge of points between them. If you manually merge them, you are asserting they are the same, but the algorithm might split them again on the next run if the density gap remains.
*   **Chinese Whispers**:
    *   *Challenge*: Also primarily a batch algorithm on the graph.
    *   *Merging*: Easier to conceptualize as adding "edges" between two clusters in the graph and letting the label propagation flow.

### 3. Correction (Removing incorrect faces)
*   **Requirement**: User splits a cluster.
*   **DBSCAN/HDBSCAN**:
    *   If a user removes a face from a cluster, they are essentially marking it as "noise" or a different label.
    *   *Risk*: On re-clustering, if the point is still spatially close, it will be pulled back in unless explicitly constrained.
*   **Chinese Whispers**:
    *   Similar risk. The graph topology dictates the cluster.

## Technical Feasibility & Recommendation

### Environment Constraints
*   **Current Stack**: Python, `scikit-learn`, `numpy`.
*   **Missing**: `networkx`, `dlib`, `hdbscan` are NOT currently installed.
*   **Constraint**: We should prefer solutions that don't require heavy new dependencies unless necessary.

### Evaluation
1.  **Chinese Whispers**:
    *   *Verdict*: **Strongest candidate for Face Clustering**. It is the industry standard for this specific problem (e.g., Dlib).
    *   *Implementation*: Since we lack `dlib`/`networkx`, we would need to implement a simple version of it (it's not complex: ~50 lines of code) or add `networkx`.
    *   *Why*: It handles the "hub-and-spoke" nature of face clusters well.

2.  **DBSCAN**:
    *   *Verdict*: **Good Baseline**. Available in `sklearn`.
    *   *Why*: It solves the "noise" problem (false positives) better than Ward. It's a good first step to try without adding dependencies.
    *   *Risk*: The `eps` parameter is global. If one person has very diverse photos (loose cluster) and another has very similar photos (tight cluster), one `eps` might not fit both.

3.  **HDBSCAN**:
    *   *Verdict*: **Best Quality, High Cost**.
    *   *Why*: Solves the `eps` problem of DBSCAN.
    *   *Cost*: Requires compiling/installing `hdbscan` (C extensions) or using the slower `sklearn.cluster.HDBSCAN` (available in newer scikit-learn versions, check version).

### Proposed Strategy: "Graph-Based Clustering" (Chinese Whispers approach)

Given the user's preference for **accuracy**, the **Chinese Whispers** (Graph Clustering) approach is superior for faces because face embeddings lie on a hypersphere where "distance" is cosine similarity.

**Recommendation**:
1.  **Implement a custom Graph Clustering (Chinese Whispers)** using `numpy`.
    *   It is lightweight.
    *   We can control the edge construction (e.g., "only link if similarity > 0.75").
    *   This directly addresses the "False Positive" issue by being strict about edges.
2.  **Workflow**:
    *   **Step 1 (Graph Construction)**: Calculate pairwise similarities (or use ANN for 5000+ images). Threshold strictly (e.g., > 0.7) to create edges.
    *   **Step 2 (Clustering)**: Run Chinese Whispers (Label Propagation) on the graph.
    *   **Step 3 (Refinement)**: Calculate centroids of resulting clusters.
    *   **Step 4 (Incremental)**: For new images, match against centroids. If match > threshold, assign. If not, hold in "buffer" until buffer size > N, then re-cluster the buffer + representatives.

This approach scales well (5000 images is small for this) and is highly accurate if the edge threshold is tuned.

#### Comparison Matrix

| Feature | Ward (Current) | DBSCAN | Chinese Whispers |
| :--- | :--- | :--- | :--- |
| **Accuracy (Faces)** | Low (Spherical assumption) | Medium (Density assumption) | **High** (Graph structure) |
| **False Positives** | High (Forces assignment) | Low (Noise support) | **Low** (Strict edges) |
| **False Negatives** | Medium | High (if eps strict) | Low (Transitive matching) |
| **Scalability** | Medium ($O(N^3)$ or $O(N^2)$) | Medium ($O(N^2)$) | **High** ($O(E)$) |
| **Dependencies** | `sklearn` (Present) | `sklearn` (Present) | Custom / `networkx` |

**Decision**: Go with **Chinese Whispers (Graph Clustering)**.
*   **Action**: Implement a standalone `ChineseWhispersClustering` class in `recognition/application`.
*   **Reason**: Best trade-off for face recognition accuracy and scalability.
