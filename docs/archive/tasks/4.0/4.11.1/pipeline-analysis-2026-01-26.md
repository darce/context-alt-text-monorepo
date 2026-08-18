# Clustering Pipeline Analysis: Zero Suggestions & Singleton Proliferation

**Date**: 2026-01-26  
**Branch**: `refactor/4.11.1-clustering-persitence-and-false-positives`  
**Status**: 🔴 CRITICAL - Complete system failure

---

## Executive Summary

The clustering system is producing **zero user-facing suggestions** despite processing 198 identities into 110 clusters. The root causes are:

1. **Chicken-and-egg problem**: Suggestions require labeled clusters, but clustering produces unlabeled clusters
2. **Conservative discovery**: Representative/Centroid discovery finding 0 matches in most chunks
3. **HDBSCAN noise**: 44-46 identities classified as "noise" → singletons
4. **Missing two-pass strategy**: No HAC refinement pass to merge similar singletons

---

## Database State Analysis

```
Total clusters:               110
Labeled clusters:              25 (22.7%)
Unlabeled clusters:            85 (77.3%)
Singleton clusters:            68 (61.8%)
Assignment suggestions:         0 ← CRITICAL
Total identities:             198
```

---

## Root Cause #1: Suggestion Eligibility Requires Labels

**Location**: [eligibility.py#L10-27](../../../../apps/prototype-description-service/recognition/application/suggestions/eligibility.py#L10)

```python
def is_eligible_cluster(cluster: object, tenant_id: str) -> bool:
    label = getattr(cluster, "label", None)
    if not label or str(label).startswith("cluster-"):
        logger.info("[suggestions] Skipping suggestion: cluster missing meaningful label")
        return False
    return True
```

**Problem**: During initial clustering:

1. All clusters are created **unlabeled**
2. `SuggestionService.create()` calls `is_eligible_cluster()`
3. Unlabeled clusters are **skipped** → 0 suggestions persisted
4. User must manually label each cluster before suggestions can work

**Evidence from logs**:

```
SUGGESTED ... cluster=ad892d0b-af10-4f43-a4ad-fbdcded5ce66 confidence=0.00
```

But `SELECT * FROM identity_suggestions` returns 0 rows because the cluster had no label.

**Archived app comparison**: The archived `SuggestionService.create_suggestion()` has **no eligibility check** - it creates suggestions for any cluster.

### Fix Options

**Option A: Remove eligibility check entirely** (like archived app)

- Pros: Suggestions work immediately
- Cons: UI shows UUID-based cluster names until labeled

**Option B: Auto-label clusters on creation**

- Use auto-labeling like "Cluster 1", "Cluster 2"
- Suggestions can target these immediately

**Option C: Create suggestions without labels, filter in UI**

- Persist all suggestions
- Frontend filters to only show suggestions for labeled clusters
- Preserves suggestions for when clusters get labeled

**Recommendation**: Option C - persist all suggestions, let UI decide visibility

---

## Root Cause #2: Discovery Pipeline Finding Zero Matches

**Log pattern**:

```
RepresentativeDiscovery: 0 candidates, 5 remaining
CentroidDiscovery: 0 candidates, 5 remaining
GraphDiscovery: 0 candidates, 3 new cluster proposals
```

**Why representatives don't match**:

- First chunk creates clusters with representatives
- Second chunk: representatives exist but similarity < `similarity_threshold` (0.80)
- All 5 identities fall through to HDBSCAN

**HDBSCAN noise problem**:

```
GraphDiscovery ... clusters=41 noise=44-46
```

With `min_cluster_size=2`, any identity without a close neighbor becomes noise → singleton.

**Archived app difference**: Used Ward HAC with `similarity_threshold=0.75`, more aggressive linking.

### Fix Options

**Option A: Lower similarity_threshold to 0.75**

- Match archived app behavior
- Risk: More false positives

**Option B: Add HAC post-processing pass**

- After HDBSCAN, run HAC on singletons
- Group similar singletons into clusters
- Apple Photos uses this two-pass approach

**Option C: Adjust HDBSCAN parameters**

- Lower `cluster_selection_epsilon` (currently 0.55)
- Consider `min_samples=1` with `min_cluster_size=2`

**Recommendation**: Option B + lower thresholds - implement two-pass like Apple Photos

---

## Root Cause #3: Suggestion Band Creates SUGGEST but No Persistence

**Log evidence**:

```
SUGGESTED ... confidence=0.00 reason=similarity 63.52% within suggestion band
SUGGESTED ... confidence=0.00 reason=similarity 64.62% within suggestion band
```

The gate correctly identifies `SUGGEST` decisions when similarity is in [0.65, 0.80) band, but:

- `SuggestionService.create()` is called
- `is_eligible_cluster()` returns False (no label)
- Suggestion is discarded

---

## Root Cause #4: No Merge Suggestions Table

```sql
SELECT 'Merge suggestions', COUNT(*) FROM identity_cluster_merge_suggestions;
-- ERROR: relation "identity_cluster_merge_suggestions" does not exist
```

The merge suggestion feature was designed but never implemented in the schema.

---

## Specific False Positive/Negative Examples

### Media 6665: HDBSCAN False Positive (Ochre Ridgeway → Sable Verity cluster)

**Root Cause Identified**: HDBSCAN grouped media 6665 (Ochre Ridgeway) with media 6689 (Sable Verity) despite only **14.7% cosine similarity** between them.

**Evidence from logs** (`logs/archive/logs/recognition.log.9:257`):

```
new_cluster job_id=0694f630-eec9-7f2f-8000-3c25c41e1efa identity_count=2 media_ids=['6665', '6689']
```

**Similarity verification**:

```sql
-- Computed similarity between the two identities
similarity = 0.1472 (14.7%)  -- WAY BELOW 80% threshold!
```

**Why HDBSCAN grouped them**:

1. HDBSCAN uses density-based clustering with `cluster_selection_epsilon` as a "merging distance"
2. The epsilon parameter (0.5477) controls when to merge clusters in the hierarchy, NOT a strict similarity threshold
3. With `min_cluster_size=2`, HDBSCAN can create 2-member clusters from any points in the same density region
4. **Critical bug**: The code created new clusters without validating pairwise similarities

**Code location**: [discovery.py#L204-207](../../../../apps/prototype-description-service/recognition/application/discovery/graph/discovery.py#L204)

```python
# BEFORE: No validation - blindly trusts HDBSCAN groupings
member_sims = compute_member_similarities(member_vectors_group)
new_clusters.append((new_members, member_sims))
```

**Fix Applied**: Added `validate_pairwise_similarities()` function that:

1. Computes cosine similarity between all pairs in proposed cluster
2. Rejects groups where any pair falls below `similarity_threshold`
3. Splits invalid groups into singleton clusters
4. Logs rejection with media IDs and actual similarity

```python
# AFTER: Validate all pairs meet threshold
is_valid, min_pairwise_sim = validate_pairwise_similarities(
    member_vectors_group, self.settings.similarity_threshold
)
if is_valid:
    member_sims = compute_member_similarities(member_vectors_group)
    new_clusters.append((new_members, member_sims))
else:
    # Split invalid group into singleton clusters
    logger.info("[GraphDiscovery] Pairwise validation REJECTED group: ...")
    for member in new_members:
        new_clusters.append(([member], [1.0]))
```

### Media 6656: Clear image of Coral Ridgeway, no match

```
new_cluster job_id=e7aaee06-1830-4611-a174-0bbf47932246 identity_count=1 media_ids=['6656']
```

This became a singleton cluster. Need to check:

1. Was there an existing Coral Ridgeway cluster?
2. What was the similarity to that cluster?
3. Why did it not match?

---

## Comparison: Current vs Archived App

| Aspect                  | Archived App (4.2.3) | Current App    | Impact                  |
| ----------------------- | -------------------- | -------------- | ----------------------- |
| similarity_threshold    | 0.75                 | 0.80           | More singletons         |
| Suggestion eligibility  | None                 | Label required | Zero suggestions        |
| Clustering algorithm    | Ward HAC             | HDBSCAN        | More noise/singletons   |
| Two-pass clustering     | No                   | No             | Could reduce singletons |
| Auto-merge              | Yes (disabled)       | No             | N/A                     |
| complete_link_min_floor | 0.75                 | 0.80           | Stricter validation     |

---

## Recommended Fixes (Priority Order)

### P0: Enable Suggestions for Unlabeled Clusters

**File**: `recognition/application/suggestions/eligibility.py`

```python
def is_eligible_cluster(cluster: object, tenant_id: str) -> bool:
    # Always allow suggestions - UI will filter by label if needed
    if tenant_id and getattr(cluster, "tenant_id", "").lower() != tenant_id.lower():
        return False
    return True  # Remove label check
```

### P1: Add Two-Pass Clustering (HAC Refinement)

After HDBSCAN creates clusters:

1. Collect all singleton clusters
2. Run HAC on singleton centroids with lower threshold (0.70)
3. Merge singletons that cluster together

### P2: Lower Similarity Threshold

Change `similarity_threshold` from 0.80 to 0.75 to match archived app behavior.

### P3: Show Cluster Matches When Labeling

When user clicks to label a cluster:

1. Compute similarity to all labeled clusters
2. Show top 5 matches with similarity %
3. Allow one-click assignment instead of text search

---

## Verification Queries

```sql
-- Check suggestion persistence after P0 fix
SELECT COUNT(*) FROM identity_suggestions;

-- Verify cluster has suggestions after labeling
SELECT c.label, COUNT(s.id) as suggestion_count
FROM identity_clusters c
LEFT JOIN identity_suggestions s ON s.suggested_cluster_id = c.id
GROUP BY c.label
ORDER BY suggestion_count DESC;

-- Check singleton rate
SELECT
  CASE WHEN (SELECT COUNT(*) FROM identity_members m WHERE m.cluster_id = c.id) = 1
       THEN 'singleton' ELSE 'multi' END as type,
  COUNT(*)
FROM identity_clusters c
GROUP BY 1;
```

---

## Next Steps

1. [x] Implement P0 fix (remove label eligibility check)
2. [x] Add pairwise validation to prevent HDBSCAN false positives
3. [ ] Re-run clustering to verify suggestions are created
4. [ ] Trace media 6656 specific decisions (Coral Ridgeway false negative)
5. [ ] Implement P3 (cluster matching UI) for better UX
6. [ ] Consider P1 (HAC refinement) for singleton reduction
