# Clustering Quality Collapse Analysis

Investigation of batch processed at **2025-12-14 13:18:16**.

## Root Cause: Cold Start with Graph Algorithm

**The database was reset before the batch** (`reset_dev_db.sh` at 13:13:53), which:
- Wiped all existing clusters
- Wiped all representatives
- Wiped all centroids

The batch then ran as a **cold start** (0 clusters, 0 reps) through `ClusterService`:

```
[clustering] Found 0 existing clusters for discovery
[clustering] Discovery inputs: 0 clusters (0 labeled)
[clustering] Discovery inputs: 0 clusters with representatives, 0 with centroids
```

### What Happened

| Phase | Result |
|-------|--------|
| RepresentativeDiscovery | 0 candidates (no reps to match) |
| CentroidDiscovery | 0 candidates (no centroids) |
| **GraphDiscovery** | 0 candidates, **284 new cluster proposals** |

**Problem**: GraphDiscovery (HDBSCAN with epsilon=0.55) processed 483 identities and created **284 clusters** instead of ~10-15 correct clusters.

---

## Why This Is Different from Expected Cold Start

**Expected**: `RepresentativeOnlyClustering` should handle cold starts via sequential matching.

**Actual**: `ClusterService.cluster_unclustered_identities()` was used, which:
1. Has no special cold-start detection
2. Uses 3-phase discovery even with 0 clusters
3. Falls back entirely to GraphDiscovery for all 483 identities
4. Graph algorithm fragments them into many small clusters

---

## Evidence of Fragmentation

User performed **~180 manual merges** afterward, mostly to `Muted Yarrow` cluster:

```
[curation] MERGED ... target_cluster=a0bbe3be-... (Muted Yarrow)
[curation] MERGED ... target_cluster=a0bbe3be-... (Muted Yarrow)
... (repeated 150+ times)
```

---

## Recommendations

### Option 1: Use RepresentativeOnlyClustering for Cold Start

Detect when `len(existing_clusters) == 0` in `cluster_unclustered_identities` and route to `RepresentativeOnlyClustering` instead of the 3-phase pipeline.

### Option 2: Lower Epsilon / Use Chinese Whispers

- Chinese Whispers may produce better results with native cosine similarity
- HDBSCAN epsilon 0.55 may still be too strict for cold start

### Option 3: Remove Graph Algorithms Entirely

Given that:
1. Cold start works better with `RepresentativeOnlyClustering`
2. Incremental matching via reps/centroids handles most cases
3. Graph algorithms are causing fragmentation

**Simplify to representative-only matching** for all scenarios.

---

## Next Steps

1. Confirm which approach you prefer
2. Implement cold-start detection in `cluster_unclustered_identities`
3. Re-run test batch to validate fix
