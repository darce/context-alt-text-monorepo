# Algorithm Strategy Analysis

Evaluating whether HDBSCAN/Chinese Whispers are necessary vs representative-only matching.

## Cold Start: How It Actually Works

The `RepresentativeOnlyClustering` class handles cold starts via **sequential matching**:

```
for each identity:
    if matches any cached representative >= threshold:
        add to that cluster
    else:
        create new singleton cluster
        add identity as representative to cache
```

**Key insight**: As it processes faces sequentially, newly created clusters become candidates for matching subsequent faces. This **builds representatives on-the-fly**.

| Face # | Action | Reason |
|--------|--------|--------|
| 1 | Create singleton A | No representatives exist |
| 2 | Join A | Matches A's representative |
| 3 | Create singleton B | No match |
| 4 | Join A | Matches A's representative |
| 5 | Join B | Matches B's representative |

This is how cold start clusters faces correctly **without** graph algorithms.

---

## Current Pipeline Flow

```
Cold Start (0 existing clusters):
  -> RepresentativeOnlyClustering: builds clusters sequentially (O(n*k) where k grows)

Incremental (existing clusters):
  Phase 1: RepresentativeDiscovery -> match to existing reps (O(n*k))
  Phase 2: CentroidDiscovery -> match to centroids (O(n*k))
  Phase 3: GraphDiscovery -> cluster remaining (O(n^2))
```

**Problem**: Phase 3 only runs on "remaining" identities. If Phases 1-2 work well, Phase 3 sees very few identities.

---

## When Graph Algorithms Add Value

| Scenario | Rep-Only | Graph Algo |
|----------|----------|------------|
| All faces return matches | [x] Best | [ ] Unused |
| Many orphan faces | WARNING Creates many singletons | [x] Groups them |
| Transitive bridging needed | [ ] No transitivity | [x] Finds connections |

**Graph algorithms are valuable when** you have many faces that don't match existing representatives but are related to each other.

---

## Recommendation

Since `fix/4.2.6-batch-consistency` added anchor injection and bypass, the transitive bridging benefit is diminished. Consider:

### Option A: Simplify to Representative-Only

Remove HDBSCAN/Chinese Whispers from Phase 3. Accept more singletons, rely on:
- Manual merging via UI
- Suggestion system for borderline matches

**Pros**: Simpler, faster, deterministic
**Cons**: More singletons to curate

### Option B: Use Chinese Whispers as Fallback Only

Keep for batches where >50% of identities reach Phase 3 (rare if matching works well).

**Pros**: Best of both worlds
**Cons**: Maintains code complexity

---

## Questions

1. In your typical batches, what percentage reach Phase 3 (unmatched by rep/centroid)?
2. How many singletons are acceptable per batch?
