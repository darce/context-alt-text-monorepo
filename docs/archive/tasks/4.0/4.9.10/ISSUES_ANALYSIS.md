# Issues Analysis: Curation Flow & Scan Worker Stability (2025-12-24)

**Context**: User reported multiple issues during manual testing of the curation workflow.

---

## 1. Summary of Issues

| #   | Issue                                       | Severity | Root Cause                              | Fix Complexity |
| --- | ------------------------------------------- | -------- | --------------------------------------- | -------------- |
| 1   | Duplicate key constraint during reassign    | **High** | Missing idempotency check               | Simple         |
| 2   | Deadlock during cluster merge               | **High** | Concurrent member updates               | Medium         |
| 3   | Duplicate RENAMED API calls (7x in 250ms)   | Medium   | React component re-render or StrictMode | Medium         |
| 4   | Suggestions not shown to user               | Low      | By design: only user-labeled clusters   | Clarify UX     |
| 5   | Scan worker crashes after db reset          | Medium   | Race: worker starts before migrations   | Simple         |
| 6   | Scan worker crashes on transaction rollback | Medium   | Unhandled exception bubbling            | Simple         |

---

## 2. Issue Details

### 2.1 Duplicate Key Constraint During Reassign

**Symptoms**:

```
sqlalchemy.dialects.postgresql.asyncpg.IntegrityError: duplicate key value violates unique constraint "unique_identity_member"
```

**Log Evidence** ([recognition.log#L303](../../../../apps/prototype-description-service/logs/recognition.log)):

```
INSERT INTO identity_members (id, ..., identity_id) VALUES (..., '0458c1d3-f080-4fe8-8b50-fa9753914b06')
```

**Root Cause**:
In `assign_outlier_to_cluster` (`cluster_curation.py`, historical module later split into smaller orchestration services), the code:

1. Checks if identity is already in a cluster
2. Removes from source cluster if different
3. Adds to target cluster

But it doesn't check if the identity is **already a member of the target cluster**. This can happen when:

- User clicks "Assign" multiple times rapidly
- A previous assignment completed but UI didn't update
- An identity was assigned during clustering, then user tries to assign again

**Fix**:

```python
# In cluster_curation.py, before add_member:
existing_member = await member_repo.get_member(target_cluster_id, str(identity_model.id))
if existing_member:
    logger.info("[curation] Identity already in target cluster, skipping add")
    return cluster
```

Or use upsert semantics in `add_member`:

```python
async def add_member_if_not_exists(...) -> IdentityMember | None:
    """Add member only if not already present. Returns None if already exists."""
    # Use INSERT ... ON CONFLICT DO NOTHING
```

---

### 2.2 Deadlock During Cluster Merge

**Symptoms**:

```
asyncpg.exceptions.DeadlockDetectedError: deadlock detected
Process 81726 waits for ShareLock on transaction 50576; blocked by process 81682.
Process 81682 waits for AccessExclusiveLock on relation 1719539
```

**Log Evidence** ([recognition.log#L1954](../../../../apps/prototype-description-service/logs/recognition.log)):

```sql
UPDATE identity_members SET cluster_id=$1 WHERE identity_members.id = $2
```

**Root Cause**:
During merge, `move_members` updates multiple rows sequentially without deterministic ordering. If two concurrent merges affect overlapping members, they can deadlock.

**Fix**:

1. Lock rows in deterministic order (by ID) before updating
2. Or use a single bulk UPDATE with proper ordering:

```python
async def move_members(self, from_cluster_id: str, to_cluster_id: str) -> int:
    # Use a single UPDATE statement instead of row-by-row
    stmt = (
        update(MemberModel)
        .where(MemberModel.cluster_id == from_uuid)
        .where(MemberModel.tenant_id == tenant_uuid)
        .values(cluster_id=to_uuid)
    )
    result = await self._session.execute(stmt)
    return result.rowcount
```

---

### 2.3 Duplicate RENAMED API Calls

**Symptoms**:
7 RENAMED log entries in 250ms for the same cluster ([recognition.log#L294-301](../../../../apps/prototype-description-service/logs/recognition.log)):

```
15:03:15,967 RENAMED old_label='None' new_label='Flaxen Yarrow'
15:03:15,970 RENAMED old_label='None' new_label='Flaxen Yarrow'  # 3ms later
15:03:16,041 RENAMED old_label='Flaxen Yarrow' new_label='Flaxen Yarrow'  # 71ms later
...
15:03:16,208 RENAMED old_label='Flaxen Yarrow' new_label='Flaxen Yarrow'
```

**Root Cause Candidates**:

1. **React StrictMode**: Double-invokes effects in development
2. **Multiple component instances**: Same cluster rendered in multiple views
3. **Missing mutation deduplication**: `useMutation` called multiple times before first completes

**Fix**:

1. Add client-side mutation deduplication:

```typescript
const renameMutation = useMutation({
  mutationKey: ['rename-cluster', clusterId],  // Dedupe by key
  mutationFn: ...
});
```

2. Add server-side idempotency:

```python
async def update_cluster(cluster_id: str, label: str) -> Cluster:
    cluster = await repo.get_by_id(cluster_id)
    if cluster.label == label:
        return cluster  # No-op, don't log or update
    ...
```

---

### 2.4 Suggestions Not Shown to User

**Symptoms**:
UI shows no suggestions even though clustering produces candidates.

**Log Evidence**:

```
[suggestions] Skipping suggestion: cluster not user-labeled cluster_id=e4fc8656-a261-420c-844a-88e40b4983bc
```

**Root Cause**:
This is **by design** in `_is_eligible_cluster`:

```python
if not cluster.user_confirmed or not cluster.label or cluster.label.startswith("cluster-"):
    logger.info("[suggestions] Skipping suggestion: cluster not user-labeled")
    return False
```

Suggestions are only created for clusters that:

1. Have a user-provided label (not auto-generated)
2. Are marked `user_confirmed`

**UX Implication**:
Users must label at least one cluster before suggestions appear. First-time users see no suggestions.

**Possible Enhancement**:
Create suggestions for auto-labeled clusters but display them differently in UI:

- "Auto-detected cluster: Person A (3 photos) - 89% match"
- Allow user to confirm or dismiss

---

### 2.5 Scan Worker Crashes After DB Reset

**Symptoms**:

```
Scan worker crashed (retrying in 5s): database "context_alt_text_service" does not exist
Scan worker crashed (retrying in 5s): relation "identity_clustering_jobs" does not exist
```

**Root Cause**:
`reset_dev_db.sh` drops and recreates the database, but the scan worker is still running and tries to query during the gap.

**Fix**:

1. `reset_dev_db.sh` should stop the scan worker first
2. Scan worker should wait for db availability before starting loop:

```python
async def wait_for_database(max_retries: int = 30) -> None:
    for i in range(max_retries):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                return
        except Exception:
            await asyncio.sleep(1)
    raise RuntimeError("Database unavailable after max retries")
```

---

### 2.6 Scan Worker Transaction Rollback

**Symptoms**:

```
Scan worker crashed (retrying in 5s): This Session's transaction has been rolled back due to a previous exception during flush. To begin a new transaction with this Session, first issue Session.rollback().
```

**Root Cause**:
The scan worker's job processing doesn't properly handle exceptions in the middle of a transaction. After a flush failure, the session is in a bad state but the worker tries to continue.

**Fix**:
Wrap job processing with proper exception handling:

```python
async def process_job(job_id: str) -> None:
    async with get_session() as session:
        try:
            # ... process job ...
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.exception("Job %s failed", job_id)
            raise
```

---

## 3. Priority Matrix

| Issue                 | User Impact      | Frequency   | Priority       |
| --------------------- | ---------------- | ----------- | -------------- |
| 2.1 Duplicate key     | Blocks curation  | Medium      | **P1**         |
| 2.2 Deadlock          | Blocks merge     | Low         | **P1**         |
| 2.3 Duplicate renames | Wastes resources | High        | P2             |
| 2.5 Worker db crash   | Dev friction     | After reset | P2             |
| 2.6 Worker rollback   | Worker restarts  | Occasional  | P2             |
| 2.4 No suggestions    | Confusing UX     | First-time  | P3 (by design) |

---

## 4. Implementation Plan

### Phase 1: Critical Fixes (P1) ✅ COMPLETE

1. **add_member_if_not_exists** in `member_repository.py` ✅

   - Added `add_member_if_not_exists()` with `INSERT ... ON CONFLICT DO NOTHING`
   - Updated `assign_outlier_to_cluster` to use it

2. **Bulk move_members** in `member_repository.py` ✅
   - Replaced row-by-row UPDATE with single bulk statement
   - Deadlock prevention via atomic update

### Phase 2: Stability (P2) ✅ COMPLETE

3. **Server-side rename idempotency** ✅

   - Added check for unchanged label in `update_cluster`
   - Returns early without logging when no change

4. **Scan worker resilience** ✅

   - Added `wait_for_database()` function
   - Checks db availability before starting main loop
   - Retries with db check after crashes

5. **React mutation deduplication** ✅
   - Added `mutationKey` to all mutations in `useClusterMutations.ts`:
     - `renameMutation`: `['rename-cluster', clusterId]`
     - `mergeMutation`: `['merge-cluster', clusterId]`
     - `revertMergeMutation`: `['revert-merge', clusterId]`
     - `reassignMutation`: `['reassign-identities', clusterId]`
     - `assignToClusterMutation`: `['assign-to-cluster', clusterId]`
     - `createClusterMutation`: `['create-cluster-for-identity']`
     - `splitMutation`: `['split-cluster', clusterId]`

### Phase 3: UX (P3) ✅ COMPLETE

6. **Surface suggestions when clusters become user-labeled** ✅

   - Added `SuggestionService.surface_for_newly_labeled_cluster()` method
   - Scans identities in auto-labeled clusters and creates suggestions against newly-labeled cluster
   - Called automatically when a cluster is renamed/user-confirmed via `ClusterService.update_cluster()`
   - Logs: `[suggestions] SURFACED identity_id=... cluster_id=... similarity=...`

7. **% similarity shown in UI** ✅ (already implemented)

   - `InlineSuggestionPrompt` displays `{matchPercent}%` from `topMatch.similarity * 100`

8. **Similarity % updates after curation events** ✅
   - Frontend invalidates `identity-suggestions` on `cluster_updated`, `cluster_merged`, `cluster_split`, `suggestions_updated` events
   - Backend calls `refresh_for_identity()` on manual_assign, wrong_person, manual_split events
   - Backend calls `refresh_for_cluster()` on cluster structural changes

---

## 5. Files Modified

| File                     | Changes                                                | Status |
| ------------------------ | ------------------------------------------------------ | ------ |
| `member_repository.py`   | Added `add_member_if_not_exists`, fixed `move_members` | ✅     |
| `cluster_curation.py`    | Uses idempotent add, checks label before rename        | ✅     |
| `scan_worker.py`         | Added db availability check, retry with db check       | ✅     |
| `useClusterMutations.ts` | Added `mutationKey` to all 7 mutations                 | ✅     |
| `suggestion/service.py`  | Added `surface_for_newly_labeled_cluster()`, logging   | ✅     |
| `cluster_service.py`     | Calls suggestion surfacing after cluster labeling      | ✅     |
| `useClusterEvents.ts`    | Invalidates suggestions on `cluster_updated` event     | ✅     |
