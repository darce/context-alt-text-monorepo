# pgcache Evaluation for Merge Latency

**Date**: 2025-12-27  
**Status**: Evaluated — not applicable to core issue  
**Related**: [merge-path-optimization.md](merge-path-optimization.md)

---

## Summary

**pgcache would not help with merge latency.** The merge path is write-heavy, and query caching only accelerates reads. However, pgcache's constraint-based invalidation pattern is applicable at the application layer for caching read-heavy endpoints.

---

## What pgcache Is

[pgcache](https://github.com/tempest98/pgcache) is a PostgreSQL wire-protocol proxy (written in Rust) that sits between the application and Postgres. It provides:

1. **Query result caching**: Caches SELECT results keyed by query + parameters
2. **Constraint-based invalidation**: Uses CDC (logical replication) to intelligently invalidate cached queries when underlying data changes
3. **Extended protocol support**: Works with prepared statements (Parse/Bind/Execute)
4. **Search path awareness**: Resolves schema-qualified queries correctly for cache key generation

### Key Innovation: Constraint-Based Invalidation

From [constraint-based-invalidation.md](https://github.com/tempest98/pgcache/blob/main/docs/constraint-based-invalidation.md):

> **Key Insight**: Invalidation only matters when the result set could GROW.

pgcache extracts WHERE clause constraints from cached queries:

```
SELECT * FROM test t JOIN test_map tm ON tm.test_id = t.id WHERE t.id = 1

→ QueryConstraints {
    column_constraints: {
        test.id = 1,
        test_map.test_id = 1  // Propagated through JOIN equivalence
    }
}
```

When a CDC event arrives (INSERT/UPDATE/DELETE), pgcache checks if the changed row matches the constraints:

| Operation | Invalidate? | Reason |
|-----------|-------------|--------|
| INSERT test_map (test_id=1) | ✅ Yes | Matches constraint, will appear in results |
| INSERT test_map (test_id=5) | ❌ No | Doesn't match constraint, won't appear |
| UPDATE test_map: test_id 1→2 | ❌ No | Leaving result set (UPDATE mechanism handles removal) |
| UPDATE test_map: test_id 5→1 | ✅ Yes | Entering result set |

This is more efficient than naive "invalidate on any write to table" strategies.

---

## Why pgcache Doesn't Help Merge Latency

### The Merge Path Is Write-Heavy

From [merge-path-optimization.md](merge-path-optimization.md), the bottlenecks are:

| Operation | Type | Cache Helps? |
|-----------|------|--------------|
| `recompute_representatives` | WRITE (INSERT/UPDATE) | ❌ No |
| `recompute_centroid` | WRITE (UPDATE) | ❌ No |
| `REFRESH MATERIALIZED VIEW` | DDL (write) | ❌ No |
| `member_repo.move_members` | WRITE (UPDATE) | ❌ No |
| `cluster_repo.delete` | WRITE (DELETE) | ❌ No |
| `constraint_repository.create` | WRITE (INSERT) | ❌ No |

**Query caching accelerates reads, not writes.** The merge request sends almost no SELECTs—it's a sequence of UPDATEs, INSERTs, DELETEs, and DDL.

### Lock Contention Persists

The `ACCESS EXCLUSIVE` lock from `REFRESH MATERIALIZED VIEW` blocks all other connections regardless of caching. pgcache would cache the *next* query after the lock releases, but it can't prevent the lock from being held.

### CDC Adds Latency, Not Removes It

pgcache uses logical replication to detect changes. There's ~50-200ms of CDC lag between when a write commits and when pgcache receives the event. This is acceptable for cache invalidation but adds latency, not removes it.

---

## Where pgcache *Could* Help (Adjacent Use Cases)

### Read Paths Blocked by Merge Locks

```
User A: POST /clusters/{id}/merge   (holds locks for 10s)
User B: GET /clusters                (blocked by locks → timeout)
```

If pgcache cached the cluster list query, User B might get a cache hit and never touch Postgres during the lock window. This reduces **collateral damage** from long-running merges.

### Hot Read Endpoints

Endpoints like:
- `GET /clusters` (list all clusters)
- `GET /clusters/{id}/members` (list members)
- `GET /clusters/{id}/suggestions` (list suggestions)

These could benefit from caching with constraint-based invalidation. But this is a second-order optimization—fixing the merge path itself (per [merge-path-optimization.md](merge-path-optimization.md)) is higher priority.

---

## Applicable Pattern: App-Layer Constraint Invalidation

The most useful idea from pgcache is **constraint-based invalidation**—but applied at the *application layer* without deploying a proxy:

```python
# Current: no caching
async def get_cluster_members(cluster_id: str) -> list[Member]:
    return await repo.get_by_cluster(cluster_id)

# With app-layer cache + constraint invalidation
async def get_cluster_members(cluster_id: str) -> list[Member]:
    key = f"members:{cluster_id}"
    if cached := await redis.get(key):
        return deserialize(cached)
    members = await repo.get_by_cluster(cluster_id)
    await redis.set(key, serialize(members), ex=30)
    return members

# Invalidation on write (constraint-based logic from pgcache)
async def move_members(source_id: str, target_id: str) -> int:
    count = await repo.move_members(source_id, target_id)
    # Only invalidate affected clusters (constraint: cluster_id = X)
    await redis.delete(f"members:{source_id}", f"members:{target_id}")
    return count
```

This is what pgcache automates, but it's simple enough to implement manually for hot paths.

---

## Comparison: Approaches to Merge Latency

| Approach | Helps Merge Latency? | Helps Read Resilience? | Complexity |
|----------|---------------------|----------------------|------------|
| **Defer work to curation job** (planned) | ✅ Yes—removes 90%+ of latency | ⚪ Indirect | Medium |
| **pgcache proxy** | ❌ No—writes aren't cached | ✅ Yes—serves stale reads during locks | High (new infra) |
| **App-layer cache + constraint invalidation** | ❌ No—still writes | ✅ Yes—reduces read load | Low-Medium |
| **Concurrent MV refresh on schedule** | ✅ Yes—removes lock contention | ⚪ Indirect | Low |
| **In-memory mutation accumulator** | ⚠️ Maybe—see analysis below | ❌ No | High (correctness risk) |

---

## Conclusion

**Do not deploy pgcache for merge latency.** Implement the deferred-work pattern from [merge-path-optimization.md](merge-path-optimization.md) instead.

pgcache is interesting technology for read-heavy workloads with complex invalidation needs. If you later need to optimize read paths (e.g., cluster list under high load), consider either:
1. Deploying pgcache as a proxy
2. Implementing app-layer caching with the constraint-invalidation pattern

For now, focus on the write-path optimization.
