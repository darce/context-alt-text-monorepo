# Dev Slice Review: Background Surfacing Batching (4.11.2)

**Date**: 2026-02-05  
**Reviewer**: Automated code review  
**Scope**: All modified files in the 4.11.2 background-surfacing dev slice  
**Backend tests**: 434 passed, 4 skipped

---

## Summary

The slice successfully replaces the N+1 query pattern in `surface_for_newly_labeled_cluster()` with a single batched fetch via `get_member_identities_for_clusters()`, adds chunked processing with per-chunk sessions in the background task, and hardens the WP admin script dependencies. The core goal — eliminating multi-minute stalls on large datasets — is met.

The issues below are ordered by severity.

---

## 1. Domain Entity Mutation (Anti-Pattern) — HIGH

**File**: [cluster_repository.py](../../../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py#L490-L491)

```python
domain_identity = self._to_domain_identity(model)
domain_identity.cluster_id = cluster_key  # ← mutates after construction
```

`MediaIdentity` is a `@dataclass` (not `frozen=True`), so this works at runtime. But mutating a domain entity inside an infrastructure method is a code smell:

- **Violation of single-responsibility**: the repository method silently enriches domain objects beyond what the domain model defines.
- **Fragile coupling**: if `MediaIdentity` ever becomes `frozen=True` (like `IdentityMember`), this line throws `FrozenInstanceError`.
- **Inconsistency**: `_to_domain_identity()` on line 735 always sets `cluster_id=None`, then the batch method overwrites it. Callers of the single-cluster `get_member_identities()` (line 469) never set `cluster_id`, so the same entity looks different depending on which method produced it.

**Fix**: Pass `cluster_id` into `_to_domain_identity()`:

```python
def _to_domain_identity(self, model: MediaIdentity, *, cluster_id: str | None = None) -> DomainIdentity:
    ...
    cluster_id=cluster_id,
```

---

## 2. Late/Inline `import` Statements — MEDIUM

**Files**:

- [refresh_service.py#L482](../../../../apps/prototype-description-service/recognition/application/suggestions/refresh_service.py#L482): `import time as _time`
- [clustering.py#L62-L63](../../../../apps/prototype-description-service/recognition/application/tasks/clustering.py#L62-L63): `import asyncio` + `import time as _time`

Both imports are inside function bodies. The `asyncio` import is especially gratuitous — it's a stdlib module with no circular-dependency risk.

**Why it matters**: Late imports defeat static analysis (mypy/pylint can't flag unused imports), hide dependencies from readers, and slightly penalize each function call.

**Fix**: Move both to the module top.

---

## 3. Dead N+1 Warning (Vestigial Guard) — MEDIUM

**File**: [refresh_service.py#L621-L627](../../../../apps/prototype-description-service/recognition/application/suggestions/refresh_service.py#L621-L627)

```python
if _total_db_queries > 10:
    logger.warning(
        "[suggestions] N+1 QUERY DETECTED: %d queries for %d clusters. "
        "Consider batching get_members() and session.get() calls.",
        _total_db_queries,
        unlabeled_count,
    )
```

After the batching fix, `_total_db_queries` is always `1` (the single `get_member_identities_for_clusters` call). This warning can never fire. The message text still references the old N+1 pattern ("Consider batching get_members()…") which no longer exists.

**Fix**: Either remove the block, or lower the threshold to `> 3` and update the message to reflect the current query model.

---

## 4. Duplicate Service Rebuild Inside Chunk Loop — MEDIUM

**File**: [clustering.py#L148-L157](../../../../apps/prototype-description-service/recognition/application/tasks/clustering.py#L148-L157)

Inside the per-chunk loop the task opens a new session (good), but then rebuilds the entire `ClusterService` tree via `cluster_service_builder(session=session, tenant_id=tenant_id)` on every chunk, then re-derives `refresh_service` and `surface_fn` via `getattr`. The same `cluster_service_builder` was already called once outside the loop (line 78) to load the representative cache.

**Inefficiency**: Each call to `cluster_service_builder` likely instantiates repositories, gate, settings, etc. For N chunks this is N unnecessary object constructions.

**Fix**: Consider extracting a lighter factory that re-binds just the session on an existing service graph. At minimum, cache the `surface_fn` callable validation outside the loop and only reconstruct the session-bound service inside.

---

## 5. No Upper Bound on `get_by_tenant(…, limit=1000)` — MEDIUM

**Files**:

- [clustering.py#L97](../../../../apps/prototype-description-service/recognition/application/tasks/clustering.py#L97)
- [refresh_service.py#L497](../../../../apps/prototype-description-service/recognition/application/suggestions/refresh_service.py#L497)

Both paths call `get_by_tenant(tenant_id, limit=1000)` to load all clusters into memory. With the `selectinload(representatives → identity)` + `selectinload(centroid_data)` options, each cluster object carries its full representative embeddings. At 1000 clusters × ~5 reps × 512-D float32 vectors = ~10 MB of embeddings loaded into Python heap per call.

**Risk**: As tenants grow beyond several hundred clusters, this becomes a latency + memory issue — exactly the compounding effect Enberg (§2.4) warns about.

**Mitigation**: Since only the cluster IDs and `user_confirmed`/`label` fields are needed here, consider a lightweight query that returns just `(id, label, user_confirmed, identity_count)` from `ClusterModel` without the eager loads. The representative cache is loaded separately anyway.

---

## 6. `representatives_by_cluster` Shadowed by Single-Key Dict — LOW

**File**: [clustering.py#L122](../../../../apps/prototype-description-service/recognition/application/tasks/clustering.py#L122)

```python
representatives_by_cluster = {cluster_id: rep_embeddings}
```

This dict is passed into `surface_for_newly_labeled_cluster()` but always contains only the one labeled cluster. If the method is ever extended to match against multiple labeled clusters simultaneously, this will silently miss them. The current implementation is correct but the variable name overpromises.

**Fix (cosmetic)**: Rename to `labeled_reps` or add a comment clarifying intent.

---

## 7. Inconsistent `Sequence[str]` vs `list[str]` in Fake Repositories — LOW

**Files**:

- Protocol: `Sequence[str]` ([repositories.py#L133](../../../../apps/prototype-description-service/recognition/domain/repositories.py#L133))
- Fakes: `list[str]` ([fakes.py#L51](../../../../apps/prototype-description-service/recognition/tests/fakes.py#L51), [conftest.py#L169](../../../../apps/prototype-description-service/recognition/tests/conftest.py#L169), [api/conftest.py#L403](../../../../apps/prototype-description-service/recognition/tests/api/conftest.py#L403))

The Protocol defines the parameter as `Sequence[str]`, but all three fake implementations type it as `list[str]`. This is technically compatible (list is a Sequence), but it's a protocol contract divergence that mypy `--strict` would flag in future and makes copy-paste error propagation easy.

**Fix**: Use `Sequence[str]` in all fakes to mirror the protocol signature.

---

## 8. Redundant Empty-Check Branches for `rep_embeddings` — LOW

**File**: [refresh_service.py#L464-L477](../../../../apps/prototype-description-service/recognition/application/suggestions/refresh_service.py#L464-L477)

The code has three nearly identical logging+return blocks for the NumPy size-0 array check, the sequence-length-0 check, and the None check:

```python
if isinstance(rep_embeddings, np.ndarray):
    if rep_embeddings.size == 0:
        logger.info(...)
        return 0
elif len(rep_embeddings) == 0:
    logger.info(...)
    return 0
```

This is correct (it was the mypy fix for NumPy truthiness), but all three branches log the identical message. They could be consolidated into a small helper:

```python
def _is_empty_reps(reps: Sequence[np.ndarray] | np.ndarray | None) -> bool:
    if reps is None:
        return True
    if isinstance(reps, np.ndarray):
        return reps.size == 0
    return len(reps) == 0
```

---

## 9. Frontend WP Global Check Is Warn-Only — LOW

**File**: [main.tsx#L12-L28](../../../../apps/prototype-wp-alt-context/js/admin/main.tsx#L12-L28)

The defensive WP global check logs `console.warn(…)` but proceeds to render the app regardless. If `wp.hooks` is truly missing, downstream code may still crash. This is acceptable for diagnostics, but consider gating features that depend on `wp.hooks` with `typeof` guards at usage sites.

---

## 10. No Explicit `quality_score` Field in `_to_domain_identity` — INFO

**File**: [cluster_repository.py#L720-L735](../../../../apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py#L720-L735)

The `_to_domain_identity` method does not map `model.quality_score` → `DomainIdentity`. The domain `MediaIdentity` dataclass also lacks this field. Per the root-cause-analysis from 4.11.1, `quality_score` was added to the ORM model but is never surfaced to domain consumers. This is not a regression from this slice but is worth noting for completeness.

---

## Items Not Flagged (Looks Good)

| Area                                                           | Assessment                                                                     |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Batch query correctness (`get_member_identities_for_clusters`) | JOIN + IN clause is idiomatic; NULL-embedding filter is correct                |
| Chunking logic in `clustering.py`                              | Chunk boundary estimator is sound; fresh session per chunk prevents MVCC bloat |
| Timeout (30s `asyncio.timeout`)                                | Already present and tested in `test_background_surfacing_task.py`              |
| Background task error isolation                                | `try/except` around entire task with `logger.exception` — good                 |
| PHP script deps (`wp-element`, `wp-i18n`, `wp-hooks`)          | Added in both dev and production enqueue paths — correct                       |
| Integration test (`test_proactive_suggestions.py`)             | End-to-end label → background surface → suggestion assert — solid coverage     |
| Unit test stubs (batch surfacing, timeout)                     | Cover happy path, empty set, and large-set — good                              |
| Protocol update (`SuggestionRefreshServiceProtocol`)           | `candidate_cluster_ids` + `representatives_by_cluster` added correctly         |

---

## Recommended Priority

| #   | Finding                   | Effort | Risk if Deferred                 |
| --- | ------------------------- | ------ | -------------------------------- |
| 1   | Domain entity mutation    | 10 min | Medium — breaks on `frozen=True` |
| 2   | Late imports              | 5 min  | Low — style/static-analysis      |
| 3   | Dead N+1 warning          | 5 min  | Low — misleading logs            |
| 4   | Duplicate service rebuild | 30 min | Low — perf overhead per chunk    |
| 5   | Unbounded cluster load    | 30 min | Medium at scale (>500 clusters)  |
| 6   | Variable name shadowing   | 2 min  | Cosmetic                         |
| 7   | Fake type inconsistency   | 5 min  | Low                              |
| 8   | Redundant empty checks    | 10 min | Low                              |
| 9   | WP warn-only check        | 10 min | Low                              |
| 10  | Missing quality_score     | 15 min | Low (pre-existing)               |

---

# Consolidated Checklist

## This Pass (Quick Fixes — < 10 min each)

- [x] **#1** Pass `cluster_id` into `_to_domain_identity()` instead of mutating after construction (`cluster_repository.py`)
- [x] **#2** Move `import asyncio` and `import time` to module top in `clustering.py` and `refresh_service.py`
- [x] **#3** Remove dead N+1 warning block (`_total_db_queries > 10`) in `refresh_service.py`
- [x] **#6** Rename `representatives_by_cluster` to `labeled_reps` (or add clarifying comment) in `clustering.py`
- [x] **#7** Change `list[str]` → `Sequence[str]` in fake repos (`fakes.py`, `conftest.py`, `api/conftest.py`)
- [x] **#8** Consolidate triplicated empty-rep checks into `_is_empty_reps()` helper (`refresh_service.py`)

## Deferred (Document as Tech Debt)

- [ ] **#4** Extract lighter session-rebind in chunk loop instead of full `cluster_service_builder` rebuild (`clustering.py`) — _Defer: perf impact is marginal; avoid new abstraction until chunking pattern stabilizes_
- [ ] **#5** Add lightweight ID-only cluster query for surfacing (avoid eager-loading reps/centroids when only IDs/labels needed) — _Defer: broader refactor; current limit=1000 is adequate; revisit when tenant cluster counts approach 500+_
- [ ] **#9** Add `typeof` guards at `wp.hooks` usage sites, not just warn-and-continue (`main.tsx` + downstream consumers) — _Defer: keep rendering, guard at usage sites only; not a regression_
- [ ] **#10** Map `quality_score` from ORM model into domain `MediaIdentity` (pre-existing gap, not a regression) — _Defer: fix belongs in the detection pipeline, not the mapping layer_

---

# Runtime Issue Analysis (Browser Console Errors)

**Date**: 2026-02-05 (same session)  
**Context**: After deploying the 4.11.2 slice, browser console shows three classes of errors during label rename.

## R1. `wp.hooks.doAction` is undefined — LOW

**Source**: `svg-painter.js`, `heartbeat.min.js` (WP core scripts)

WP core scripts call `wp.hooks.doAction` before the `wp-hooks` module is loaded. The plugin correctly declares `wp-hooks` as a script dependency in both dev and production enqueue paths (`class-admin.php`), but WP core scripts are enqueued independently by WordPress itself and don't inherit the plugin's dependency chain.

**Impact**: Noisy console errors. Does not affect plugin functionality — these scripts are unrelated to the recognition workbench.

**Disposition**: Outside plugin boundaries. No action required.

---

## R2. 500 Errors on GET Endpoints — HIGH

**Symptom**: Browser 500s on `GET /recognition/suggestions`, `GET /recognition/suggestions/merge`, `GET /recognition/media-identities`.

**Key evidence**:

- Python backend log has **zero errors** — no tracebacks, no `"Unhandled exception"` entries
- The `generic_exception_handler` (`exception_handlers.py:53`) logs all 500s via `logger.exception()` and none appear
- Background surfacing log shows a **30-second gap** between the last progress line (100/105 clusters at 0.38s) and the `asyncio.timeout(30)` warning
- PHP proxy timeout for GET requests is 30s (`class-recognition-controller.php:1061`)
- PHP proxy retries 500s 3x with exponential backoff (500ms / 1000ms / 2000ms), amplifying each failure to ~3.5s total

**Root cause (most likely)**: The background surfacing function completes its scanning phase in 0.38s (all 105 clusters enumerated), then enters the per-identity suggestion creation loop which calls `_gate.evaluate()` and `upsert_by_identity_cluster()` per match — each involving 2-3 DB roundtrips. Something in this phase blocks for ~30s before the timeout fires. During this window:

1. The background task's `async with session_factory()` context holds an open session/transaction
2. If the suggestion upsert acquires row-level locks or the `_gate.evaluate()` path does heavy I/O, the asyncio event loop may be starved of CPU time to service incoming GET requests
3. The PHP proxy's 30s GET timeout expires → returns `WP_Error` as 500 to the browser
4. The 3x retry amplifies each failed endpoint into a ~3.5s blocking `usleep()` in the PHP process

Alternatively, the Python uvicorn process may crash or hang after the timeout, and errors go to stderr (terminal output) rather than `recognition.log`.

**Next steps to confirm**:

1. Check uvicorn terminal output for tracebacks during the 30s window
2. Add `logger.info` at the top of each GET route handler to confirm requests reach the Python backend
3. Add a watchdog log inside the surfacing per-identity loop (e.g., every 10 identities) to find the exact stall point
4. Consider reducing `asyncio.timeout` from 30s → 10s

---

## R3. Label Shows "Saved!" But Reverts to UUID — HIGH

**Symptom**: User sets label 'Flaxen Yarrow', sees "Saved!" success indicator, then the label reverts to displaying `cluster-{uuid}`.

**Confirmed working**:

| Layer                         | Status                                                                              |
| ----------------------------- | ----------------------------------------------------------------------------------- |
| PATCH backend                 | ✅ `label='Flaxen Yarrow'` committed in 0.019s                                        |
| `user_confirmed` flag         | ✅ Set to `True` by `cluster_mutations.py:84` (`bool(label)`)                       |
| PATCH response shape          | ✅ `ClusterResponse.is_auto_label` = `False` (from domain `not user_confirmed`)     |
| Optimistic update             | ✅ `updateCachedClusterLabel` sets `cluster_label: label`, `is_auto_label: false`   |
| `onSuccess` callback          | ✅ Re-applies cache update + `invalidateQueries()` + `onRenameSuccess()` ("Saved!") |
| React Query `placeholderData` | ✅ `useMediaIdentities` uses `(prev) => prev` — keeps data on refetch failure       |
| DB state after PATCH          | ✅ `label='Flaxen Yarrow'`, `user_confirmed=True`, `is_auto_label=False`              |

**Label display logic** (`formatClusterLabel` in `utils.ts`):

- If `rawLabel && !isAutoLabel` → returns the label ✅
- Otherwise → returns `cluster-{normalizedId}` (the UUID the user sees)

**How the revert happens**: The `invalidateQueries()` in `onSuccess` triggers background refetches across 5 query families. These refetches hit the 500-returning endpoints (R2 above). React Query retries once (`retry: 1`), and if both attempts fail, the query enters error state but **retains the optimistic cache data**. Under normal operation, the label should persist.

The revert to UUID most likely occurs when:

1. The 500s on `GET /recognition/media-identities` cause the query to enter a persistent error state
2. A subsequent user interaction or navigation causes the `IdentityClusterItem` component to unmount/remount
3. On remount, React Query fires a fresh fetch (optimistic cache was for the old query instance), which again 500s
4. With no data at all, the component can't render the label

**`Promise<void>` concern**: `updateClusterLabel` in `clusterApi.ts:26` discards the PATCH response body entirely. The response contains the authoritative `is_auto_label: false` and `label: 'Flaxen Yarrow'` which could seed the cache, but it's thrown away. This forces reliance on the optimistic update + refetch pattern, which fails when the refetch 500s.

**Disposition**: Root cause is R2 (the 500 errors). Fix R2 and R3 resolves. Additionally, returning the response body from `updateClusterLabel` (changing `Promise<void>` → `Promise<ClusterResponse>`) would make the system more resilient to refetch failures.

---

## Runtime Issues — Action Items

| ID  | Issue                 | Priority | Action                                                                                                                |
| --- | --------------------- | -------- | --------------------------------------------------------------------------------------------------------------------- |
| R2  | 500s on GET endpoints | **P0**   | Diagnose the 30s stall in background surfacing; check uvicorn terminal output; add GET handler entry logs             |
| R3  | Label reverts to UUID | **P0**   | Caused by R2; additionally change `updateClusterLabel` return type from `Promise<void>` to `Promise<ClusterResponse>` |
| R1  | wp.hooks undefined    | **P3**   | No action (WP core loading order issue)                                                                               |

---

## References

- Kleppmann, _Designing Data-Intensive Applications_, Ch 7 (Transactions / MVCC snapshot isolation)
- Enberg, _Latency_, §2.4 (compounding latency), §6.1–6.3 (caching strategies for batch vs per-item)
- `docs/tasks/4.0/4.11.2/background-surfacing-ui-hang-plan.md` (parent task plan)
