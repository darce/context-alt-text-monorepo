# Cluster Rework Critique & Analysis

**Author**: Antigravity  
**Date**: Nov 22nd 2025

## 1. Executive Summary

The proposed plans correctly identify that the current clustering pipeline is fragile, specifically regarding batch-size sensitivity (the "20 vs 10 images" regression) and long-term cluster fidelity. However, there is a **critical contradiction** between the analysis notes and the remediation plan regarding centroid normalization that must be resolved before engineering effort is spent.

The "Accuracy-First" redesign proposals (HDBSCAN/Graph-based) are directionally correct for a high-fidelity system but may be over-engineering if the root cause is simply a lack of strict validation in the current incremental logic.

## 2. Critical Findings & Caveats

### 2.1 The Normalization Contradiction
*   **The Plan**: `centroid-fidelity-plan.md` asserts that "Centroid vectors stored as raw averages... do NOT normalize" and proposes a 3-4 hour phase to fix this.
*   **The Evidence**: `centroid-regression-notes.md` explicitly states: *"Centroids remain unit-normalized in both scenarios (centroid_norm=1.0), so the regression is not due to missing normalization."*
*   **Critique**: If the evidence is correct, **Phase 1 of the Fidelity Plan is redundant** or based on a false premise. Implementing it will not fix the regression. You must verify if `centroid_utils.py` actually normalizes. If it does, the drift comes from the *averaging logic* itself (weighted average of unit vectors is not a unit vector until re-normalized, but if it is re-normalized, it might still drift if the "weight" (count) is high).

### 2.2 Batch Size Sensitivity (The "Gravity" Problem)
*   The regression (20 images merge, 10 don't) suggests that the **incremental update logic** is flawed when handling a large batch of similar-but-distinct faces.
*   **Caveat**: Ward clustering (used in Stage 2) minimizes variance. A larger batch of 20 images has more internal variance than 10. If the "distinct" people are somewhat similar, a larger batch might bridge the gap in a way that a smaller batch doesn't.
*   **Critique**: The current "Incremental" approach updates the centroid *immediately* after each assignment. In a batch of 20, the centroid moves 20 times. If the order of processing matters (it does), this is non-deterministic and fragile.

### 2.3 Chinese Whispers vs. HDBSCAN
*   I have recently implemented **Chinese Whispers (CW)**.
*   **Critique**: The proposals suggest HDBSCAN. While HDBSCAN is excellent for variable density, CW is the industry standard for *face* clustering (used by Dlib) because face embeddings on a hypersphere have specific properties that CW exploits well (transitive similarity).
*   **Recommendation**: Stick with the newly implemented CW for the "Batch" stage before jumping to HDBSCAN. It is lighter and likely sufficient if tuned.

## 3. Proposed Improvements

### 3.1 "Low Hanging Fruit" (Missed Opportunities)

1.  **Strict Post-Assignment Validation (The "Double Check")**
    *   **What**: After assigning an identity to a cluster and updating the centroid, *immediately* re-calculate the similarity. If it drops below the threshold, **reject the assignment**.
    *   **Why**: This prevents "cluster capture" where a centroid drifts so far it no longer represents its original members. This is mentioned in `centroid-fidelity-plan.md` (Phase 2) and is the **most valuable** step. Do this first.

2.  **Representative "Hard Gating"**
    *   **What**: Never assign to a cluster based *only* on the centroid. Require a match with at least one **Representative** (actual face).
    *   **Why**: Centroids are averages; they tend towards the "mean face" and lose distinctive features (scars, moles, specific angles). Representatives preserve these.
    *   **Implementation**: The current system has `RepresentativeMatcher`. Ensure it is the *primary* gate. If Rep match fails, do *not* fall back to Centroid match for assignment—only for "suggestion" or "new cluster creation".

3.  **Order-Independent Batch Processing**
    *   **What**: When processing a batch, do not update the centroid incrementally *during* the batch.
    *   **How**:
        1.  Match all items in the batch against *static* existing clusters.
        2.  Group the batch items themselves (using CW or Ward).
        3.  Merge the resulting *groups* into the existing clusters.
    *   **Why**: This removes the "20 images" artifact caused by the centroid moving while you are still processing the batch.

## 4. Strategic Recommendations

1.  **Verify Normalization First**: Run a 5-minute script to check if `update_centroid_incremental` returns a unit vector. If yes, scrap Phase 1 of the Fidelity Plan.
2.  **Implement Strict Validation**: This is the highest ROI fix for "false positives".
3.  **Adopt "Static" Batch Processing**: Stop updating centroids mid-batch. Calculate the update *after* the batch is fully assigned.
4.  **Leverage Chinese Whispers**: Use the CW implementation for the "internal batch clustering" step (Step 2 of Order-Independent Processing).

**Signed**: Antigravity  
**Date**: Nov 22nd 2025
