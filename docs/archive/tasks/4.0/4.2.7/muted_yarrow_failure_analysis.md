# Muted Yarrow Matching Failure Analysis

Investigation of why Muted Yarrow cluster fails while Russet Ridgeway works.

## Root Cause: Insufficient Representatives

| Cluster | Members | Representatives | Works? |
|---------|---------|-----------------|--------|
| **Muted Yarrow** | **195** | **1** | [ ] |
| Onyx Marsh | 31 | 1 | WARNING |
| Russet Ridgeway | 23 | 10 | [x] |
| Mairin Taylor | 15 | 10 | [x] |
| Kay Bertrand | 8 | 8 | [x] |

**The problem**: Muted Yarrow has 195 members from manual merges but only **1 representative embedding**. This single representative cannot match the diverse face variations across all merged clusters.

---

## Why This Happens

1. **Initial clustering** creates cluster with 1-2 members -> 1 representative
2. **Manual merges** move members from other clusters -> member count increases
3. **Representatives are NOT recomputed** after merge -> still only 1 rep
4. **New faces** don't match the single representative -> create new clusters

### Evidence from Logs

```
[RepresentativeDiscovery] NO MATCH: identity f80be588-...
  best_cluster=a0bbe3be-... (Muted Yarrow)
  best_sim=0.4838 (threshold=0.85)
```

Similarity of 0.48 is far below 0.85 threshold.

---

## Why Russet Ridgeway Works

Russet Ridgeway (db1ca158-...) has **10 representatives** covering diverse face angles. When new faces arrive, at least one representative matches well.

```
[clustering] ACCEPTED identity=404e5e2e-... cluster=db1ca158-... (Russet Ridgeway)
[clustering] ACCEPTED identity=00ddb8dc-... cluster=db1ca158-... (Russet Ridgeway)
... (10 total accepted)
```

---

## Fix Options

### Option 1: Recompute Representatives After Merge

Update `merge_cluster()` to call `recompute_representatives()` with better coverage:

```python
async def merge_cluster(...):
    # Move members
    await member_repo.move_members(source_cluster_id, target_cluster_id)
    
    # Recompute representatives for better coverage!
    await self.assignment_writer.recompute_representatives(target_cluster_id)
```

### Option 2: Increase max_representatives_per_cluster

Current setting may be limiting representatives. Increase to 10+ for large clusters.

### Option 3: Manual Representative Refresh

Add API endpoint to manually trigger representative recomputation:
```
POST /clusters/{cluster_id}/recompute-representatives
```

---

## Immediate Fix (Manual)

Until code is fixed, call `recompute_representatives()` for affected clusters via script or API.
