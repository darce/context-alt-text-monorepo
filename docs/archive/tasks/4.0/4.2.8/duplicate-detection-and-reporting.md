# Duplicate Image Detection & Improved Reporting

**Version:** 4.2.8  
**Date:** 2025-12-18  
**Status:** Proposal

---

## Problem Statement

### Issue 1: Duplicate Images Produce Inconsistent Clusters

When the same image is uploaded twice with different `media_id` values (6694 and 6695), the clustering algorithm may assign the **same person** from each image to **different clusters** due to:

1. **Timing/batch order** — The first image's identity joins a cluster, then when the duplicate arrives later, the `complete_link` check may fail because the cluster now has representatives from other images
2. **complete_link strictness** — Even with 92.62% match to one representative, if the minimum similarity across ALL representatives falls below 0.85, the candidate is rejected

### Issue 2: Reporting Lacks Identity Granularity

The `predicted_clusters` section in canonical reports shows `member_identity_locators` with bbox coordinates, but it's difficult to:

- Correlate which specific identity (by person) is in which cluster
- Detect when the same image appears in multiple clusters via different identities
- Identify transitivity failures for duplicate images

---

## Root Cause Analysis

### complete_link Failure for Duplicate Image

**Timeline (from logs):**

1. `d43ccfb3` cluster created with Burnished Ridgeway from `6694` + `6692`
2. Burnished Ridgeway from `6695` (duplicate of 6694) tries to join via RepresentativeDiscovery
3. Match: 92.62% similarity to best representative
4. **REJECTED** by complete_link: minimum similarity across ALL reps was below 0.85
5. `6695` gets its own singleton cluster

**Why this happens:**

- 6694 and 6695 are **pixel-identical** → their embeddings should be identical
- 6692 is a **different photo** of Burnished Ridgeway → its embedding differs
- When 6695 tries to join, it matches perfectly to 6694's rep but poorly to 6692's rep
- Since it came via RepresentativeDiscovery (not GraphDiscovery), `anchor_linked=False`
- The bypass conditions don't apply: similarity (92.62%) < 95% threshold

---

## Proposed Solutions

### Solution A: Perceptual Hash-Based Duplicate Detection (Recommended)

#### Approach

Store a perceptual hash (pHash/dHash) for each media item at scan time. Before clustering, check if any media_id shares the same hash → treat all identities from duplicate images as equivalent.

#### Implementation Steps

1. **Add `image_hash` column to `media_identities`**

   ```sql
   ALTER TABLE media_identities
   ADD COLUMN image_phash VARCHAR(64);

   CREATE INDEX idx_media_identities_phash
   ON media_identities (tenant_id, image_phash);
   ```

2. **Compute hash during scan**

   ```python
   import imagehash
   from PIL import Image

   def compute_image_hash(image_bytes: bytes) -> str:
       """Compute perceptual hash for duplicate detection."""
       img = Image.open(io.BytesIO(image_bytes))
       return str(imagehash.phash(img, hash_size=16))  # 64-bit hash as hex
   ```

3. **Pre-clustering duplicate grouping**

   ```python
   async def find_duplicate_media_ids(
       session: AsyncSession,
       tenant_id: UUID,
       media_ids: list[int],
   ) -> dict[int, list[int]]:
       """Find media_ids that share the same perceptual hash.

       Returns:
           Map from canonical media_id to list of duplicate media_ids.
       """
       stmt = select(
           MediaIdentity.image_phash,
           func.array_agg(MediaIdentity.media_id.distinct())
       ).where(
           MediaIdentity.tenant_id == tenant_id,
           MediaIdentity.media_id.in_(media_ids),
           MediaIdentity.image_phash.isnot(None),
       ).group_by(
           MediaIdentity.image_phash
       ).having(
           func.count(MediaIdentity.media_id.distinct()) > 1
       )

       result = await session.execute(stmt)
       duplicates = {}
       for phash, dup_ids in result:
           canonical = min(dup_ids)  # Use lowest media_id as canonical
           duplicates[canonical] = sorted(dup_ids)
       return duplicates
   ```

4. **Enforce clustering consistency for duplicates**

   When identity A from media_id X is assigned to cluster C, automatically assign the corresponding identity A' from duplicate media_id Y to the same cluster (skip gate checks since they're provably the same).

#### Scalability

- **Hash computation**: O(1) per image at scan time (< 50ms)
- **Duplicate lookup**: O(log n) with B-tree index on (tenant_id, image_phash)
- **Storage**: 16 bytes per media item (64-bit hash as hex)

---


---

## Improved Reporting

### Enhanced `predicted_clusters` Structure

Add more context to help identify transitivity failures:

```json
{
  "predicted_clusters": [
    {
      "predicted_cluster_id": "d43ccfb3-...",
      "member_count": 2,
      "member_identities": [
        {
          "identity_id": "abc123",
          "media_id": 6694,
          "bbox": { "x": 204, "y": 289, "width": 100, "height": 145 },
          "embedding_fingerprint": "e7f3a1..." // First 8 chars of embedding hash
        },
        {
          "identity_id": "def456",
          "media_id": 6692,
          "bbox": { "x": 160, "y": 162, "width": 148, "height": 214 },
          "embedding_fingerprint": "b2c4d5..."
        }
      ],
      "creation_method": "hdbscan",
      "duplicate_media_detected": [6694, 6695] // NEW: Flag duplicates
    }
  ]
}
```

### Duplicate Detection in Reports

Add a `duplicates` section to the canonical report:

```json
{
  "duplicates": {
    "by_image_hash": {
      "a7b3c1d9...": [6694, 6695] // These media_ids are identical images
    },
    "consistency_issues": [
      {
        "duplicate_group": [6694, 6695],
        "person_bbox": { "x": 204, "y": 289, "width": 100, "height": 145 },
        "clusters_assigned": ["d43ccfb3-...", "dc34dfe5-..."],
        "expected": "single_cluster",
        "actual": "split_across_2_clusters"
      }
    ]
  }
}
```

---

## Implementation Priority

| Priority | Task                                                           | Effort | Impact                            |
| -------- | -------------------------------------------------------------- | ------ | --------------------------------- |
| 1        | Add `near_identical_to_representative` bypass in complete_link | Low    | High - Fixes immediate issue      |
| 2        | Add detailed complete_link logging                             | Low    | Medium - Better debugging         |
| 3        | Add `all_similarities` to metadata                             | Low    | Medium - Better visibility        |
| 4        | Implement perceptual hash on scan                              | Medium | High - Proper duplicate detection |
| 5        | Add `duplicates` section to canonical report                   | Medium | High - Better reporting           |
| 6        | Pre-clustering duplicate enforcement                           | Medium | High - Guaranteed consistency     |

---

## Next Steps

1. ✅ Add detailed logging to complete_link (done)
2. ✅ Add `all_similarities` to metadata (done)
3. Implement `near_identical_to_representative` bypass
4. Add perceptual hashing infrastructure
5. Enhance canonical report with duplicate detection
