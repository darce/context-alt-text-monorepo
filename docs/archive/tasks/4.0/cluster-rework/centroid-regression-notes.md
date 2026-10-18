# Centroid Regression Notes – Batch-Size Artifacts

## Summary

- When analyzing **10 images**, clustering assigns distinct clusters for three different people (expected).
- When analyzing **20 images**, the same three distinct people are merged into a single cluster with centroid similarities in the 0.67–0.87 range (incorrect).
- Centroids in the failing case still report norm ≈ 1.0; the issue appears upstream (assignment logic/thresholding under larger batches) rather than missing normalization.

## Evidence

### Failing case (20 images)
Command: `../../scripts/compare_media_embeddings.py --media-ids 2872 2871`

- Identities (all in same cluster `7cc1ac7a-...-3ad0`):
  - media_id=2871 identity=3cbb44b1-a061-40e9-9e8c-f43f0b6c1cde centroid_norm=1.0000
  - media_id=2872 identity=650fe5b0-58d2-4755-aa1c-192f8f049f5a centroid_norm=1.0000
  - media_id=2872 identity=4135b055-81d1-45e3-a77d-b7a3e07dd3e6 centroid_norm=1.0000
- Pairwise similarities (same cluster):
  - 0.5367, 0.5363, 0.4924
- Identity vs centroid (same cluster):
  - 0.7353, 0.6726, 0.8691
- Ground truth: these are 3 different people but were merged.

### Passing case (10 images after DB reset)
Command: `../../scripts/compare_media_embeddings.py --media-ids 2872 2871`

- Identities (distinct clusters):
  - media_id=2871 identity=17f84264-358f-4a77-8f4c-e83e19b84c29 centroid_norm=1.0000
  - media_id=2872 identity=176d8262-4bf0-4e0c-af7f-8be79cadb6be centroid_norm=1.0000
  - media_id=2872 identity=fb5bb209-8cbb-40f7-b698-3085bf2d9fe8 centroid_norm=1.0000
- Pairwise similarities (cross-cluster):
  - 0.5367, 0.5363, 0.4924
- Identity vs centroid (separate clusters):
  - 0.9386, 1.0000, 0.9262
- Ground truth: 3 different people correctly separated.

## Observations and Suspicions

- Centroids remain unit-normalized in both scenarios (centroid_norm=1.0), so the regression is not due to missing normalization.
- Pairwise similarities between the problematic identities (~0.49–0.54) are below the 0.6 threshold, yet they end up in the same cluster when 20 images are processed. This points to threshold enforcement or assignment logic under load/batch size, not raw similarity values.
- The failing run shows one identity-centroid similarity spiking to ~0.87, suggesting the centroid is being pulled toward one embedding as additional embeddings are added—possibly due to segmentation/duplicate detection in the batch inflating membership or mis-normalized inputs before the latest fixes.
- Clustering consistency should be invariant to batch size; current behavior is not.

## Immediate Checks

- Verify the updated migration is applied (materialized view recomputed) after normalization fixes, especially after increasing batch size.
- Inspect assignment threshold enforcement during incremental clustering for large batches (ensure normalized identity vectors are used and similarity checks happen post-centroid update when strict validation is enabled).
- Confirm sample data / batch composition when 20 images are sent—are there duplicate detections or mislabeled embeddings inflating centroid similarity?

## Next Steps

- Re-run clustering after the latest normalization fixes and a full DB reset/rebuild to see if the batch-size artifact persists.
- Add logging around `_assign_to_cluster` during larger batches to capture per-identity similarity vs threshold before/after centroid update.
- Consider tightening similarity thresholds or enabling strict validation by default and re-clustering to see if the merges stop at the cost of more clusters.

## Notes from “Introduction to Machine Learning with Python” (Chapter 3)

- **Whitening and scale sensitivity**: PCA whitening equalizes variance across components; analogously, re-scaling/standardizing embeddings (or projecting to a whitened subspace) can reduce any dominance by high-variance embedding axes that might amplify borderline similarities when batch size increases.
- **Feature extraction vs raw pixels**: The text stresses that raw pixel similarity is brittle to shifts/lighting; if our upstream embedding generator is sensitive to cropping/lighting, applying an additional dimensionality reduction (e.g., PCA with whitening) or learned post-normalization could reduce noise that drifts centroids when more images enter a batch.
- **Skewed datasets**: The faces example warns that skew (many samples of one person) biases similarity. Check whether larger batches include duplicates/near-duplicates for one person that overpower the centroid and pull dissimilar identities into the cluster—consider limiting per-identity contributions or down-weighting duplicates.
- **Additive components (NMF intuition)**: NMF’s additive decomposition is better at separating overlapping sources. While we don’t switch algorithms, the takeaway is to audit whether embeddings from multi-face images are getting mixed (e.g., overlapping detections), effectively “adding sources” that pollute centroids. Improving face/identity separation upstream could reduce centroid drift.
- **Dimensionality reduction for robustness**: PCA improved nearest-neighbor face matching in the book. A small post-embedding PCA/whitening stage before clustering might stabilize cosine distances across batches; worth experimenting on a snapshot to see if cross-batch similarities tighten around ground truth.
