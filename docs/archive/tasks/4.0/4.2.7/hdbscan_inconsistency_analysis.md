# HDBSCAN Batch Consistency Analysis

## Summary

Investigation into why clustering behaves inconsistently across batches when HDBSCAN is activated for large identity counts.

## Key Findings

### 1. Algorithm Selection Logic

From [`graph.py:_select_algorithm`](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/application/discovery/graph.py):

```python
hdbscan_limit = self.settings.hdbscan_max_batch_size or 500
if identities_count <= hdbscan_limit:
    # Epsilon correctly computed from cosine threshold
    epsilon = math.sqrt(2.0 * (1.0 - target_cosine))  # approx 0.548 for 0.85
    return HdbscanGraphAlgorithm(cluster_selection_epsilon=epsilon)
else:
    return DeterministicChineseWhispers(threshold=similarity_threshold)
```

**Current behavior**: Batches <=500 identities use HDBSCAN; larger batches use Chinese Whispers.

### 2. Distance Metric Configuration

| Algorithm | Metric | Threshold/Epsilon | Semantic Meaning |
|-----------|--------|-------------------|------------------|
| Chinese Whispers | Cosine similarity (dot product) | 0.88 | Faces with sim >=0.88 form edges |
| HDBSCAN | Euclidean distance | 0.548 (computed) | Faces with d <=0.548 are nearby |

The conversion `d = sqrt(2*(1-cos))` is mathematically correct for normalized vectors.

### 3. Log Analysis: Batch Behavior

| Batch | Identities | Accepted | New Clusters | Cluster Quality |
|-------|------------|----------|--------------|-----------------|
| 17 | 190 | 21 | 125 | Poor - excessive fragmentation |
| 18 | 75 | 0 | 20 | Baseline (cold start) |
| 19 | 106 | 51 | 19 | **Good - proper merging** |
| 20 | 190 | 27 | 119 | Poor - excessive fragmentation |

**Pattern**: Batches 17 and 20 (both 190 identities) show severe fragmentation creating 100+ singleton clusters, while batch 19 (106 identities) behaves correctly.

### 4. Historical Epsilon Issue

Older logs (log.6) show hardcoded epsilon:
```
HDBSCAN: 26 identities -> 6 clusters, 8 outliers (eps=0.1200)
```

This epsilon=0.12 corresponds to cosine similarity approx 0.993, which is far too strict and causes excessive fragmentation. The current code computes epsilon correctly, but the **default in HdbscanGraphAlgorithm is still 0.12**.

### 5. Root Cause Candidates

1. **Stale Default**: [`hdbscan_adapter.py`](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/infrastructure/clustering/hdbscan_adapter.py) has `cluster_selection_epsilon=0.12` as default
2. **Anchor Injection Behavior**: GraphDiscovery injects anchors which changes cluster composition
3. **Batch Composition**: Larger batches with more inter-person variety may expose edge cases

## Verification Steps

1. Add logging to confirm which epsilon value is actually used at runtime
2. Compare GraphDiscovery output between 106-identity and 190-identity batches
3. Check if anchor count affects HDBSCAN cluster formation

## Proposed Fix

Update the default epsilon in `HdbscanGraphAlgorithm.__init__` to match the cosine-to-euclidean conversion:

```diff
- cluster_selection_epsilon: float = 0.12,
+ cluster_selection_epsilon: float = 0.55,  # sqrt(2*(1-0.85))
```

This ensures any direct instantiation without explicit epsilon uses a sensible default.
