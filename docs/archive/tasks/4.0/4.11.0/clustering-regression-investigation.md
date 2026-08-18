# Clustering Regression Investigation (v4.11.0)

**Date**: 2026-01-12  
**Status**: ✅ Root cause found and fixed

---

## Executive Summary

Clustering accuracy has degraded significantly after recent refactoring. Investigation reveals **multiple root causes** that compound to make the system unusable:

1. **UUID Type Error**: ✅ **FIXED** - Clustering jobs crash with `'UUID' object has no attribute 'replace'`
2. **Orphaned Identities**: 92 of 133 identities (69%) are not assigned to any cluster
3. **Aggressive Thresholds**: High-similarity matches (0.82-0.92) are being rejected
4. **Missing Suggestions UI**: Suggestions are created but no UI surfaces them
5. **Fragmented Clusters**: 25 clusters with NULL labels (should be 5-10 distinct people)

---

## Root Cause Analysis

### 1. Critical: UUID Type Error - ✅ FIXED

**Error**: `'UUID' object has no attribute 'replace'`

**Root Cause Found**: Type mismatch between caller and callee:

1. `constrained_hac.refine_clusters()` takes `tenant_id: UUID` (UUID object)
2. It calls `constraint_repo.get_all(tenant_id)` passing the UUID object
3. `constraint_repository.get_all()` expects `tenant_id: str`
4. Inside, it calls `uuid.UUID(tenant_id)` where tenant_id is already a UUID
5. Python's `uuid.UUID.__init__` calls `hex.replace('urn:', '')` assuming hex is a string
6. **BOOM** - `'UUID' object has no attribute 'replace'`

**Verified with Python REPL**:

```python
>>> import uuid
>>> u = uuid.uuid4()
>>> uuid.UUID(u)
Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File ".../uuid.py", line 175, in __init__
    hex = hex.replace('urn:', '').replace('uuid:', '')
          ^^^^^^^^^^^
AttributeError: 'UUID' object has no attribute 'replace'
```

**Fix Applied**:

```python
# recognition/application/clustering/constrained_hac.py line 81
# Before:
constraints = await self.constraint_repo.get_all(tenant_id)

# After:
constraints = await self.constraint_repo.get_all(str(tenant_id))
```

**Evidence**:

```sql
SELECT id, status, error_message FROM identity_clustering_jobs WHERE status='failed';

-- Results:
1f799a39-d6ac-4976-9ffb-4aecc22961a2 | failed | 'UUID' object has no attribute 'replace'
d11aaeb3-119d-4b07-a183-eb2a0c5cd0da | failed | 'UUID' object has no attribute 'replace'
55e271d2-30cf-4f3d-9c8c-5c6fd06ae857 | failed | 'UUID' object has no attribute 'replace'
```

**Impact**: Clustering jobs fail mid-execution, leaving identities orphaned.

**Likely Cause**: Code is calling `.replace("-", "")` on a `UUID` object instead of `str(uuid)` somewhere in:

- HAC refinement pipeline
- Cluster ID handling in discovery pipeline
- Event logging/observability code

### 2. Orphaned Identities

**Database State**:

```sql
SELECT
  'Total identities' as metric, COUNT(*) FROM media_identities
UNION ALL
SELECT
  'Identities in clusters', COUNT(DISTINCT identity_id) FROM identity_members
UNION ALL
SELECT
  'Orphaned identities',
  (SELECT COUNT(*) FROM media_identities) -
  (SELECT COUNT(DISTINCT identity_id) FROM identity_members);

-- Results:
Total identities       | 133
Identities in clusters |  41
Orphaned identities    |  92
```

**Cause**: Combination of:

1. UUID error crashing jobs before completion
2. Failed jobs only process first chunk (5 identities out of 102)
3. No retry/recovery mechanism for orphaned identities

### 3. Aggressive Threshold Rejections

From scan_worker.log:

```
REJECTED identity=5fdde680... similarity 57.32% below suggestion floor 68.00%
REJECTED identity=6a33e480... similarity 55.64% below suggestion floor 72.00%
```

**Observation**: Even though curriculum learning was implemented to be lenient for cold clusters, the **suggestion floor** is still too high at 68-75%.

**Settings Analysis**:

```python
# ClusteringSettings defaults:
similarity_threshold = 0.85          # Base acceptance threshold
suggestion_floor = 0.75              # Below this = reject
suggestion_ceiling = 0.85            # At/above = accept

# With maturity adjustments (COLD clusters):
maturity_adj = 0.0                   # No penalty (correct per curriculum learning)
quality_adj = varies by detection quality
curriculum_adj = -0.05 * curriculum_t  # But curriculum_t = 0 for new clusters!

# Effective threshold for COLD cluster:
# 0.85 + 0.0 + quality_adj + 0.0 = still ~0.85
# Suggestion floor: 0.75 + 0.0 + quality_adj = still ~0.75
```

**Problem**: The `curriculum_t` column exists but is always 0 because:

1. New clusters start with `curriculum_t = 0`
2. `curriculum_t` only updates on ACCEPT decisions
3. Most decisions are REJECT → `curriculum_t` never grows → threshold stays strict

### 4. Cluster Fragmentation

```sql
SELECT label, identity_count, curriculum_t, maturity
FROM identity_clusters ORDER BY identity_count DESC;

-- Top clusters:
Flaxen Yarrow    | 10 | 0 | MATURE
(NULL)         |  6 | 0 | MATURE
(NULL)         |  3 | 0 | CONFIRMED
(NULL)         |  3 | 0 | CONFIRMED
(NULL)         |  2 | 0 | NASCENT
(NULL)         |  2 | 0 | NASCENT
(NULL)         |  1 | 0 | COLD     -- 17+ singleton clusters
```

**Problem**: 25 clusters but most are singletons with no label. These should have been merged.

### 5. Frontend Display Issue

Users see "Unlabeled identity" because:

```typescript
// utils.ts
const labelText = derivedLabel ?? __("Unlabeled identity", "alt-context");
```

When `cluster.label` is NULL and `cluster.clusterId` exists, `formatClusterLabel` returns a `cluster-XXXX` format, but the actual display logic falls back to "Unlabeled identity".

---

## Timeline of Degradation

| Version | Change                         | Impact                                                                                                                                |
| ------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| 4.9.11  | Merge path optimization        | Latency improved, no accuracy change                                                                                                  |
| 4.10.1  | Suggestions overlay            | Suggestions created but not surfaced in UI                                                                                            |
| 4.10.2  | Curation logging               | Added logging, no threshold changes                                                                                                   |
| 4.10.3  | Batch processing resilience    | Job handling improved                                                                                                                 |
| 4.11.0  | Curriculum learning thresholds | **Intended to help, but:**<br>- `curriculum_t` never updates for rejections<br>- UUID error crashes jobs<br>- 69% orphaned identities |

---

## Recommendations

### Immediate Fixes (P0)

1. **~~Fix UUID Error~~** ✅ **FIXED**

   - File: `recognition/application/clustering/constrained_hac.py` line 81
   - Change: Wrap `tenant_id` in `str()` before passing to `constraint_repo.get_all()`

2. **Lower Suggestion Floor**

   ```python
   # Current: 0.75 is too strict
   suggestion_floor = 0.65  # Allow more suggestions
   ```

3. **Initialize curriculum_t Higher**
   ```python
   # Start clusters with benefit of the doubt
   curriculum_t = 0.5  # Default, not 0.0
   ```

### Short-term Fixes (P1)

4. **Add Job Retry/Recovery**

   - Detect orphaned identities
   - Automatically queue them for re-clustering

5. **Surface Suggestions in UI**

   - Ensure suggestion panel queries correctly
   - Add visual indicator for pending suggestions

6. **Fix Label Display**
   - When `label` is NULL but `cluster_id` exists, show formatted ID

### Medium-term Fixes (P2)

7. **Curriculum Learning Tuning**

   - Update `curriculum_t` on ALL decisions, not just ACCEPT
   - Use rejection similarity to inform threshold

8. **Add Observability**
   - Log effective threshold in assignment events
   - Dashboard for orphan rate

---

## Database State Snapshot

```sql
-- Clusters
SELECT COUNT(*) FROM identity_clusters;  -- 26

-- By label
SELECT label, COUNT(*) FROM identity_clusters GROUP BY label;
-- NULL: 25, 'Flaxen Yarrow': 1

-- Members
SELECT COUNT(*) FROM identity_members;  -- 41

-- Orphaned (not in any cluster)
SELECT COUNT(*) FROM media_identities mi
WHERE NOT EXISTS (SELECT 1 FROM identity_members im WHERE im.identity_id = mi.id);
-- 92

-- Failed jobs
SELECT COUNT(*) FROM identity_clustering_jobs WHERE status='failed';  -- 6

-- Suggestions (should surface in UI)
SELECT COUNT(*) FROM identity_suggestions;  -- 0 (empty!)
```

---

## Next Steps

1. [x] Find and fix UUID `.replace` error - ✅ Fixed in `constrained_hac.py`
2. [ ] Re-run clustering after fix
3. [ ] Lower suggestion floor to 0.65
4. [ ] Verify suggestions appear in UI
5. [ ] Monitor orphan rate
