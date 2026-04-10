# 4.11.2 Implementation Plan: Background Surfacing + UI Hang

## Context

Issues began after commit `61a7d85` (fix(suggestions): pass label to background surfacing).

Two regressions were observed:

1. Background surfacing can stall for minutes on large datasets (N+1 query pattern).
2. WordPress admin UI shows "Saving..." indefinitely even though the backend response returns quickly.

This plan covers the backend performance fix and a focused investigation of the frontend hang.

## Log Evidence

**Problem 1: Background task never completes (N+1 query issue)**

```
2026-02-04 21:24:10,720 INFO [curation] RENAMED cluster_id=aa55cc12... new_label='Test Quick'
2026-02-04 21:24:10,725 INFO [suggestions] Background surfacing starting for cluster_id=aa55cc12... label=Test Quick
2026-02-04 21:24:10,739 INFO [suggestions] surface_for_newly_labeled_cluster: using passed label=Test Quick (optimistic)
# NOTE: No completion log - task hung for 12+ minutes until server restart
2026-02-04 21:36:00,488 ERROR get_optional_session: exception during yield/commit: 404: Cluster not found
```

**Problem 2: With fresh/small dataset, completes quickly (0.7s)**

```
2026-02-04 21:37:04,694 INFO [curation] RENAMED cluster_id=60afcf6d... new_label='Quick Response Test'
2026-02-04 21:37:04,698 INFO [suggestions] Background surfacing starting...
2026-02-04 21:37:04,727 INFO [suggestions] surface_for_newly_labeled_cluster: using passed label=Quick Response Test (optimistic)
2026-02-04 21:37:05,423 INFO [suggestions] Background surfacing completed: surfaced=0
```

**Problem 3: With ~196 unlabeled clusters, takes ~1s (still manageable)**

```
2026-02-04 21:06:13,108 INFO [suggestions] Background surfacing starting...
2026-02-04 21:06:13,134 INFO [suggestions] found 3 representatives for cluster_id=...
2026-02-04 21:06:13,288 INFO [suggestions] found 196 unlabeled clusters to scan
2026-02-04 21:06:13,965 INFO [suggestions] no matches found cluster_id=...
2026-02-04 21:06:13,965 INFO [suggestions] Background surfacing completed: surfaced=0
```

**Key observation**: The N+1 query pattern in `surface_for_newly_labeled_cluster()` causes:

- For each unlabeled cluster → `get_members()` query
- For each member → `session.get(MediaIdentityModel)` query
- With 200+ clusters × N members each = potentially thousands of sequential DB queries

## Goals

- Eliminate the N+1 query pattern in `surface_for_newly_labeled_cluster()`.
- Keep background tasks short-lived and avoid long MVCC snapshots.
- Restore reliable UI completion state after labeling.
- Add observability to confirm improvements (timing + query counts).

## Non-Goals

- Re-architect clustering or suggestion ranking.
- Change the external API contract.
- Optimize unrelated clustering stages.

## Current Findings

- N+1 query pattern: per-unlabeled-cluster `get_members()`, then per-member `session.get(MediaIdentityModel)`.
- Background task uses a single async session for the full scan; this can create long MVCC snapshots.
- UI hang correlates with WordPress core JS errors (e.g., `svg-painter.js`, `heartbeat.min.js`), suggesting missing WP globals.

---

## Patterns & Antipatterns

### Backend Antipatterns (AVOID)

```python
# BAD: N+1 query pattern - current implementation
for unlabeled_cluster in unlabeled_clusters:
    members = await self._cluster_repository.get_members(unlabeled_cluster.id)  # Query per cluster
    for member in members:
        model = await self._session.get(MediaIdentityModel, member.identity_id)  # Query per member
        # ... process
```

```python
# BAD: Single long-lived session for entire background task
async with session_factory() as session:
    # 5+ minutes of work with one MVCC snapshot
    for cluster in all_clusters:
        for member in members:
            await session.get(...)  # Stale reads accumulate
```

### Backend Patterns (USE)

```python
# GOOD: Batch fetch all identities in one query
async def get_identities_for_clusters(
    self, cluster_ids: Sequence[str]
) -> dict[str, list[MediaIdentity]]:
    """Fetch all identities for multiple clusters in a single query."""
    stmt = (
        select(ClusterMemberModel, MediaIdentityModel)
        .join(MediaIdentityModel, ClusterMemberModel.identity_id == MediaIdentityModel.id)
        .where(ClusterMemberModel.cluster_id.in_(cluster_ids))
    )
    result = await self._session.execute(stmt)
    # Group by cluster_id
    by_cluster: dict[str, list[MediaIdentity]] = defaultdict(list)
    for member, identity in result.all():
        by_cluster[str(member.cluster_id)].append(self._build_identity(identity))
    return by_cluster
```

```python
# GOOD: Chunked processing with fresh sessions
CHUNK_SIZE = 1000
for i in range(0, len(identities), CHUNK_SIZE):
    chunk = identities[i:i + CHUNK_SIZE]
    async with session_factory() as session:
        # Process chunk with fresh MVCC snapshot
        await process_chunk(session, chunk)
```

```python
# GOOD: Timeout protection for background tasks
async with asyncio.timeout(30):  # Already added in clustering.py
    await surface_fn(cluster_id, cluster_label=cluster_label)
```

### Frontend Antipatterns (AVOID)

```tsx
// BAD: Not handling mutation states properly
const mutation = useMutation({ mutationFn: ... });
// No isPending check, button stays "Saving..." forever if error occurs
```

```tsx
// BAD: Relying on WordPress globals without checking
wp.hooks.doAction("my-action"); // Crashes if wp.hooks is undefined
```

### Frontend Patterns (USE)

```tsx
// GOOD: Handle all mutation states
const mutation = useMutation({
  mutationFn: (label) => updateClusterLabel(clusterId, label),
  retry: false, // Don't retry on client errors
  onSuccess: () => {
    /* clear error, invalidate queries */
  },
  onError: (err) => {
    /* show error to user */
  },
});

// In JSX - check isPending, isError, isSuccess
<Button disabled={mutation.isPending}>
  {mutation.isPending ? "Saving..." : "Save"}
</Button>;
```

```tsx
// GOOD: Defensive check for WordPress globals
if (typeof window.wp?.hooks?.doAction === "function") {
  window.wp.hooks.doAction("my-action");
}
```

---

## Files to Touch

### Backend (Python)

| File                                                            | Purpose                   | Changes                                       |
| --------------------------------------------------------------- | ------------------------- | --------------------------------------------- |
| `recognition/domain/repositories.py`                            | Repository protocols      | Add `get_identities_for_clusters()` signature |
| `recognition/infrastructure/repositories/cluster_repository.py` | SQLAlchemy implementation | Implement batch identity fetch                |
| `recognition/application/suggestions/refresh_service.py`        | Surfacing orchestration   | Replace N+1 loop with batched fetch           |
| `recognition/application/tasks/clustering.py`                   | Background task wrapper   | Already has timeout; add chunk processing     |
| `recognition/tests/unit/suggestions/test_refresh_service.py`    | Unit tests                | Add batch surfacing tests                     |
| `recognition/tests/integration/test_cluster_repository.py`      | Integration tests         | Add batch fetch tests                         |

### Frontend (TypeScript/React)

| File                                                                  | Purpose             | Investigation                 |
| --------------------------------------------------------------------- | ------------------- | ----------------------------- |
| `js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx` | Label mutation UI   | Check mutation state handling |
| `js/admin/api/recognition/clusterApi.ts`                              | API client          | Verify response handling      |
| `js/admin/utils/http.ts`                                              | HTTP fetch wrapper  | Check error propagation       |
| `js/admin/hooks/useRecognitionHooks.ts`                               | Data fetching hooks | Verify query invalidation     |

### PHP (WordPress Plugin)

| File                                       | Purpose        | Investigation               |
| ------------------------------------------ | -------------- | --------------------------- |
| `src/api/class-recognition-controller.php` | REST proxy     | Verify PATCH response shape |
| `src/admin/class-admin-enqueue.php`        | Script enqueue | Check WP dependencies       |

---

## Plan

### 1) Backend: Batch member identity fetch

- Add a repository method to fetch identities for many clusters in one query.
- Replace per-cluster member lookup with a single batched query.
- Ensure returned identities include `cluster_id` so downstream logic can remain unchanged.

Deliverables:

- Repository interface update + SQLAlchemy implementation.
- Updated background surfacing loop to iterate over a preloaded list of identities.

### 2) Backend: Reduce long-running transaction risk

- Process identities in chunks (e.g., 1k or 5k) to keep transactions short.
- Consider flushing per chunk, or opening a fresh session for each chunk.
- Add a timeout or watchdog log if the background task exceeds expected runtime.

Deliverables:

- Chunked processing in `surface_for_newly_labeled_cluster()`.
- Optional session refresh per chunk if needed for MVCC relief.

### 3) Backend: Reduce per-identity DB round-trips

- Batch block checks (if applicable) by prefetching block lists for all identities in the batch.
- Consider a bulk upsert in `SuggestionRepository` to avoid per-identity DB writes.

Deliverables:

- One query per batch for blocks (optional).
- Bulk upsert helper (optional) with fallback to per-identity upsert if needed.

### 4) Observability

- Add timing logs for:
  - total identities fetched
  - total processing time
  - per-batch processing time
- Keep N+1 warning but adjust thresholds now that batching is in place.

Deliverables:

- Structured logs in `refresh_service.py`.

### 5) Frontend: Investigate "Saving..." hang

- Verify WP globals exist at runtime: `window.wp`, `wp.hooks`, `wp.i18n`.
- Confirm script dependencies in admin enqueue include `wp-hooks`, `wp-i18n`, `wp-element`, `wp-api-fetch`.
- Reproduce in incognito with all other plugins disabled.
- Validate proxy response content-type and JSON shape from `class-recognition-controller.php`.

Deliverables:

- Checklist results + root cause notes.
- Fix to enqueue order/deps or proxy response as needed.

## Tests

- Add/adjust unit tests for repository batch method.
- Add a targeted integration test for background surfacing with multiple clusters.
- Manual UI test: label a cluster and confirm UI resolves from "Saving..." within 1s.

## Rollout

- Ship backend batching + chunking first.
- Observe logs in staging (or local) with 200+ clusters.
- Apply frontend fix once root cause is confirmed.

## Risks

- Bulk query may load too many identities into memory; mitigate with batching.
- Chunked commits may change write interleaving; validate suggestion counts.
- WP admin errors may be from unrelated plugin or theme interference.

## Exit Criteria

- Background surfacing completes within <10s on 200+ clusters.
- No long-lived background tasks without completion logs.
- UI "Saving..." reliably resolves after label change.

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Add `get_member_identities_for_clusters()` signature to `ClusterRepository` protocol in `domain/repositories.py`
- [x] Add unit test file `recognition/tests/unit/test_batch_surfacing.py` for batch surfacing
- [x] Verify scaffolds pass type-check: `mypy .` from `apps/prototype-description-service/`

## Phase 1: Backend Batch Fetch

- [x] Implement `get_member_identities_for_clusters()` in `infrastructure/repositories/cluster_repository.py`
- [x] Write integration test for batch fetch with multiple clusters
- [x] Update `surface_for_newly_labeled_cluster()` to use batched fetch
- [x] Remove N+1 loop (per-cluster `get_members()` + per-member `session.get()`)

## Phase 2: Backend Chunking & Observability

- [x] Add chunk processing (1k identities per chunk) in `clustering.py` background surfacing task
- [x] Add timing logs: total identities, total time, per-chunk time
- [x] Verify 30s timeout in `clustering.py` still fires correctly
- [x] Add N+1 warning threshold adjustment (now expect <10 queries vs thousands)

## Phase 3: Backend Tests

- [x] Unit test: batch surfacing with 0 unlabeled clusters (empty candidate list)
- [x] Unit test: batch surfacing with 100+ identities across 50 clusters
- [x] Integration test: end-to-end cluster labeling triggers background surfacing

## Phase 4: Frontend Investigation

- [ ] Check browser console for WP global errors: `window.wp`, `wp.hooks`, `wp.i18n`
- [x] Verify script deps in `class-admin-enqueue.php` include `wp-hooks`, `wp-i18n`, `wp-element`
- [ ] Reproduce in incognito with other plugins disabled
- [x] Validate `PATCH /clusters/{id}` response from PHP proxy returns correct JSON
- [x] Check `ClusterLabelingPanel.tsx` mutation state handling (`isPending`, `isError`)

## Phase 5: Frontend Fix (if needed)

- [x] Fix script enqueue dependencies (if missing)
- [ ] Fix proxy response content-type or JSON shape (if malformed)
- [x] Add defensive checks for WP globals (if applicable)

## Success Criteria

- [ ] Background surfacing completes within <10s on 200+ clusters
- [ ] Log shows batch query count <10 (vs thousands in N+1 pattern)
- [ ] UI "Saving..." resolves within 1s after label change
- [ ] No console errors from WordPress core JS globals
- [x] Backend pytest run clean (434 passed, 4 skipped)
- [ ] All tests pass: `pytest` (backend), `npm test` (frontend)
