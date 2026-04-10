## Alternative Considered: In-Memory Mutation Accumulator - do not implement


### The Idea

Instead of writing each operation to the database immediately, accumulate mutations in memory and commit a reduced set of changes at the end:

```python
# Hypothetical in-memory accumulator pattern
class ClusterMutationAccumulator:
    def __init__(self):
        self.member_moves: dict[str, str] = {}  # member_id -> new_cluster_id
        self.cluster_updates: dict[str, dict] = {}  # cluster_id -> {field: value}
        self.pending_deletes: set[str] = set()
    
    def move_member(self, member_id: str, target_cluster_id: str):
        self.member_moves[member_id] = target_cluster_id
    
    def update_cluster(self, cluster_id: str, **fields):
        self.cluster_updates.setdefault(cluster_id, {}).update(fields)
    
    async def flush(self, session: AsyncSession):
        # Single bulk UPDATE for all member moves
        if self.member_moves:
            await session.execute(
                update(MemberModel)
                .where(MemberModel.id.in_(self.member_moves.keys()))
                .values(cluster_id=case(self.member_moves))
            )
        # Batched cluster updates
        for cluster_id, fields in self.cluster_updates.items():
            await session.execute(
                update(ClusterModel).where(ClusterModel.id == cluster_id).values(**fields)
            )
        await session.commit()
```

### Does This Help?

**Partially, but it's redundant with the planned optimization.**

| Aspect | In-Memory Accumulator | Deferred Work (Planned) |
|--------|----------------------|------------------------|
| Reduces DB round trips | ✅ Yes | ✅ Yes (fewer ops in request) |
| Reduces lock hold time | ⚠️ Slightly (still commits) | ✅ Yes (minimal sync commit) |
| Removes MV refresh from hot path | ❌ No | ✅ Yes |
| Removes recompute from hot path | ❌ No | ✅ Yes |
| Correctness risk | ⚠️ High (crash loses data) | ✅ Low (DB is source of truth) |
| Implementation complexity | High | Medium |

### Analysis

The in-memory accumulator reduces the *number* of database round trips but doesn't change *what* gets done synchronously. The merge path would still:

1. Accumulate mutations in memory
2. Flush all mutations (bulk UPDATE, bulk INSERT, etc.)
3. **Still call recompute_representatives, recompute_centroid, refresh MV**
4. **Still hold locks during flush + recompute**

The latency win from batching is ~10-20% (fewer round trips), but the 80% of latency comes from recompute and MV refresh, which can't be batched—they require reading all cluster members.

### Kleppmann's Perspective

From *Designing Data-Intensive Applications*, Ch. 7 (Transactions):

> "If you want to ensure durability, you need to wait until the write has been written to disk, typically requiring an fsync or equivalent. [...] If you don't wait, you risk losing data."

The in-memory accumulator delays writes, which risks data loss on crash. For a merge operation, losing the "members moved" state would leave the database in an inconsistent state (members still in source cluster, but user saw "merge complete").

The deferred-work pattern is safer because:
1. The **essential state change** (members moved) is committed immediately
2. Only **derived data** (reps, centroids, MV) is deferred
3. If the worker crashes, derived data can be recomputed from primary data

This aligns with Kleppmann's Ch. 10 distinction between *primary data* (members belong to cluster X) and *derived data* (cluster X has these representatives).

### Verdict

**Don't implement the in-memory accumulator.** The deferred-work pattern achieves the same latency reduction with better correctness guarantees. The accumulator would add complexity without addressing the root cause (sync recompute/MV refresh).

If you later need to optimize for very high merge throughput (100+ merges/second), consider:
1. **Command batching**: Coalesce multiple merge requests into a single transaction
2. **CQRS pattern**: Separate write model (immediate) from read model (eventually consistent)

But for the current use case (occasional user-initiated merges), deferred work is sufficient.
