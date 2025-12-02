# Embedding Model Evaluation

**Date**: December 1st 2025  
**Context**: Recognition Service V2 Rewrite  
**Purpose**: Evaluate embedding models for face recognition

---

## 🚨 CRITICAL BUG DISCOVERED: Metadata Dilution

### The Problem

**The "Cam Grant domination" bug is NOT an embedding model issue - it's a similarity calculation bug.**

Our system stores 1024D "extended embeddings" that contain:
- **First 512 dimensions**: Actual face embedding from InsightFace
- **Dimensions 512-1024**: Metadata (pose, age, gender, detection score, bbox area, etc.)

**The bug**: Similarity is calculated on the FULL 1024D vector instead of just the 512D face portion.

### Evidence from Log Analysis

```
Embedding 0:
  Full norm: 1.0000
  Face (0-512) norm: 0.4110 (17% of energy)
  Meta (512-1024) norm: 0.9116 (83% of energy)
```

When the embedding is normalized as a 1024D vector:
- **Only 17% of the "similarity"** comes from actual face features
- **83% comes from metadata** (pose, age, gender, detection quality)

### Empirical Proof

Comparing FULL vs FACE-ONLY similarity between different identities:

| Comparison | FULL (1024D) | FACE (512D) | META (512D) |
|------------|--------------|-------------|-------------|
| 0 vs 1 | 0.5679 | **-0.0521** | 0.7028 |
| 0 vs 2 | 0.6782 | **-0.0424** | 0.8033 |
| 1 vs 2 | 0.9018 | **0.5761** | 0.9655 |
| 2 vs 3 | 0.6864 | **0.0193** | 0.8771 |

**The faces are completely different (near-zero or negative similarity), but the FULL similarity is 57-90% because metadata dominates!**

This explains why:
1. 20+ different people match one cluster at 88-92% similarity
2. The pairwise similarities between those people are only 27-60%
3. This is "geometrically impossible" for true face matches - but makes perfect sense when metadata dominates

### The Fix

**Use `extract_face_embedding()` before computing similarity.**

```python
# BEFORE (buggy)
similarity = compute_similarity(identity_vector, rep_vec)  # 1024D vs 1024D

# AFTER (correct)
from recognition.domain.embeddings import extract_face_embedding
face_a = extract_face_embedding(identity_vector)  # 512D
face_b = extract_face_embedding(rep_vec)  # 512D
similarity = compute_similarity(face_a, face_b)  # Face-only comparison
```

### Files to Update

1. `recognition/application/clustering/centroid_utils.py` - `compute_similarity()`
2. `recognition/application/representatives/representative_matcher.py` - similarity calculations
3. `recognition/application/clustering/batch_clustering.py` - centroid matching
4. `recognition/application/clustering/hdbscan_clustering.py` - distance matrix
5. `recognition/application/clustering/chinese_whispers.py` - edge weights
6. `recognition/application/clustering/cluster_validation.py` - member validation

---

- Noise rate in dominant sub-class: 12.40% (vs 38.47% in standard ArcFace)
- Automatic clean data isolation without manual filtering

### Relevance to Our Problem

~~The "Cam Grant domination" problem (20+ people matching at 88-92%) suggests that:~~

~~1. Some faces in the cluster may be mislabeled (wrong person)~~
~~2. Some may be lookalikes that look similar from certain angles~~
~~3. Some may be hard samples that don't represent the true distribution~~

**UPDATE**: The above analysis was WRONG. The root cause is the **metadata dilution bug** described above. The embedding model is fine - we're just not using it correctly.

Once the bug is fixed:
- Complete-link validation will work as intended (on actual face similarity)
- Early stage guards will be meaningful
- The system will match faces, not metadata

---

## Current Model: InsightFace (buffalo_l)

### Overview

We use InsightFace with the `buffalo_l` model for face embedding generation.

**Architecture**:
- Backbone: ResNet-style (optimized)
- Embedding dimension: 512 (normalized to unit length)
- Loss function: ArcFace during training
- Detection: RetinaFace included

**Performance**:
- LFW: 99.83% accuracy
- Speed: ~50ms per face on GPU
- Well-tested in production

**The model is NOT the problem** - our similarity calculation bug is.

---

## Alternative Models Considered

### 1. FaceNet (Google)

**Architecture**: Inception-ResNet-v1  
**Loss**: Triplet loss  
**Embedding**: 512-dim

**Comparison to ArcFace**:

| Aspect | FaceNet (Triplet) | ArcFace |
|--------|------------------|---------|
| Training difficulty | Harder (triplet mining) | Easier (softmax-style) |
| LFW accuracy | 99.63% | 99.83% |
| Speed | Similar | Similar |

**Verdict**: ArcFace-trained models (like InsightFace) outperform triplet-loss models.

### 2. CosFace

**Loss function**:

$$L = -\log\frac{e^{s(\cos\theta_{y_i} - m)}}{e^{s(\cos\theta_{y_i} - m)} + \sum_{j \neq y_i} e^{s \cdot \cos\theta_j}}$$

**Difference from ArcFace**: Cosine margin (additive in cosine space) vs Angular margin (additive in angle space).

**Performance**: Very similar to ArcFace. ArcFace has slightly better theoretical properties (constant margin throughout angular range).

### 3. CurricularFace (Tencent)

**Innovation**: Adaptive curriculum learning that emphasizes easy samples early and hard samples later.

From the paper (Huang et al. 2020):

> "Our CurricularFace adaptively adjusts the relative importance of easy and hard samples during different training stages."

**Key insight for our system**:

This validates our "early stage suggestion guard" concept — being more conservative with matches when the system is still learning (few labeled clusters).

### 4. MobileFaceNet

**Trade-off**: Speed vs accuracy  
**Use case**: Mobile/edge devices  
**Verdict**: Not needed for server-side processing

---

## Recommendation: Keep InsightFace

### Why Not Switch?

1. **InsightFace already uses ArcFace loss** — There's no "upgrade" to ArcFace because that's what we're using
2. **The problem is clustering, not embeddings** — Embeddings are high quality; our assignment logic is broken
3. **Risk vs reward** — Switching models introduces new unknowns with minimal expected benefit
4. **Production proven** — InsightFace has extensive deployment history

### When to Reconsider

Consider model changes IF:

1. Accuracy drops significantly on diverse populations (fairness issue)
2. New SOTA models show >5% improvement on hard cases
3. We need faster inference (MobileFaceNet) for edge deployment

---

## Embedding Quality Improvements (Without Model Change)

### 1. Input Quality

The embedding quality depends heavily on:

- Face detection quality (bounding box accuracy)
- Face alignment (landmark-based normalization)
- Image resolution (avoid tiny faces)

**Recommendation**: Add minimum face size threshold (current: configurable via `min_bbox_area`)

### 2. Detection Confidence Weighting

Low-confidence detections produce lower-quality embeddings.

**Current implementation** (Option C): Adjust matching threshold based on detection score

```python
effective_threshold = adaptive_threshold(
    base_threshold=0.88,
    confidence=det_score,
    threshold_max_adjustment=0.03
)
```

**Issue**: This was disabled in early stage to avoid false positives. Consider re-enabling after maturity threshold.

### 3. Ensemble Approaches

Use multiple representatives per cluster to capture embedding variance:

- Profile views
- Different lighting
- Different expressions
- Different ages (for long-term data)

**Current implementation**: RepresentativeService with diversity selection

---

## Similarity Threshold Analysis

From ArcFace paper experiments on different datasets:

| Dataset | FAR@0.001 | Threshold |
|---------|-----------|-----------|
| LFW | 99.83% | ~0.78 |
| CFP-FP | 98.27% | ~0.82 |
| AgeDB | 98.28% | ~0.82 |
| MegaFace | 98.35% | ~0.85 |

**Our current settings**:

- Auto-assign threshold: 0.88 (conservative)
- Suggestion threshold: 0.80-0.88
- Complete-link floor: 0.80

These are appropriate for production use with human-in-the-loop verification.


---

## Conclusion

**Keep InsightFace (buffalo_l)** — It's already trained with ArcFace loss and performs well.

### 🚨 CRITICAL: Fix Metadata Dilution Bug FIRST

**Before any other improvements**, fix the similarity calculation to use only the 512D face embedding:

```python
from recognition.domain.embeddings import extract_face_embedding

# In compute_similarity() and all similarity calculations:
face_a = extract_face_embedding(embedding_a)  # 512D
face_b = extract_face_embedding(embedding_b)  # 512D
similarity = np.dot(face_a / np.linalg.norm(face_a), 
                    face_b / np.linalg.norm(face_b))
```

This will:
1. Fix the "Cam Grant domination" bug immediately
2. Make all other guards (complete-link, early stage) actually work
3. Reduce false positive rate dramatically

### After the Bug Fix

**Focus improvements on**:

1. ~~**Unified Assignment Gate**~~ — May not be needed once bug is fixed
2. **Complete-link validation** — Will now work correctly on face similarity
3. **Maturity checks** — Still useful for cold start protection
4. **Detection quality filters** — Still useful for input quality

**Future consideration**: If we ever train a custom model, use Sub-center ArcFace (K=3) to handle lookalikes and noisy labels at training time.
