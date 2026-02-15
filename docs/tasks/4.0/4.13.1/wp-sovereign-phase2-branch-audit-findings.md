# Branch Audit — `refactor/4.13.1-wp-sovereign` (Phase 2 Read-Path Flip)

> **Date:** 2026-02-14
> **Scope:** 34 files changed (22 modified, 12 new), +1566 lines vs `main`
> **Categories:** ANTIPATTERN · DEAD_CODE · COMPLEXITY · GAP

---

## Summary

| Severity   | Count |
| ---------- | ----- |
| **HIGH**   | 3     |
| **MEDIUM** | 4     |
| **LOW**    | 3     |
| **Total**  | **10** |

---

## Automated Check Results (reported by submitter)

| Check                                   | Result                |
| --------------------------------------- | --------------------- |
| `make check` (ruff + mypy + pytest)     | N/A (no Python changes) |
| `npm run typecheck`                     | :x: Not confirmed     |
| `npm run test -- --run`                 | :x: Not confirmed     |
| `npm run lint`                          | :x: Not confirmed     |
| `check-architecture-compliance.js`      | :x: Not confirmed     |
| `composer phpstan`                      | :x: Not confirmed     |
| `composer test`                         | :x: Not confirmed     |

> **Note:** Automated checks have not been confirmed passing on the current state of the branch. The submitter must run all checks and confirm zero errors before requesting merge.

---

## HIGH Severity

### H-1 · N+1 query in `load_members_by_cluster`

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | `src/api/class-clusters-controller.php` L275–L288               |
| **Category** | COMPLEXITY                                                      |

`load_members_by_cluster()` iterates over cluster rows and calls `$this->members_repository->list_for_cluster()` **once per cluster**:

```php
foreach ( $cluster_rows as $row ) {
    $members_by_cluster[ $cluster_id ] = $this->members_repository->list_for_cluster( $cluster_id, $limit, 0 );
}
```

With the default `$limit = 50` clusters, this fires **50 individual SELECT queries** per request plus the original cluster query (51 total). This scales linearly with page size and will dominate response latency on non-trivial datasets.

**Fix:** Add a batch method `list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array` on `IdentityMembersRepositoryInterface` that executes a single `WHERE cluster_uuid IN (...)` query and groups results in PHP.

---

### H-2 · Local-path response shape omits pagination envelope

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | `src/api/class-clusters-controller.php` L111–L120               |
| **Category** | GAP                                                             |

When the local projection path handles `list_clusters()`, the response is a **flat JSON array** of cluster objects:

```php
$payload = $this->cluster_mapper->map_cluster_list( $rows, $members_by_cluster );
return new WP_REST_Response( $payload, 200 );
```

The task plan (Pattern B) specifies an envelope: `{ "clusters": [...], "tenant_id": "..." }`. The proxy path returns whatever shape the backend provides (typically includes `total_count`, pagination metadata). The frontend cannot implement pagination correctly when the local path silently drops the envelope.

This applies to `list_clusters` and `list_top_unlabeled_clusters` — both return bare arrays from the local path.

**Fix:** Wrap the mapper output in the expected envelope. At minimum match `{ "clusters": [...] }`. Consider adding `total_count` by running a second `COUNT(*)` query in the repository (or adding a count method).

---

### H-3 · Critical test coverage gaps

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | Multiple test files (see below)                                 |
| **Category** | GAP                                                             |

Several important code paths have zero test coverage:

1. **`SyncStatusControllerTest`** — the single test never asserts the `is_stale` field at all. No test case where `is_stale` is `true` vs `false`. The staleness threshold logic (`is_projection_stale()`) is completely untested.

2. **`ClustersControllerTest`** — no test for `list_clusters` or `get_cluster_members` when `should_use_local_projection()` returns `false` (proxy fallback path for those endpoints). Only `top-unlabeled` proxy path is tested.

3. **`SyncStatusIndicator.test.tsx`** — only tests the stale state. No tests for: loading state (returns `null`), error state (renders "unavailable"), or fresh/ok badge.

4. **`useSyncStatus.test.tsx`** — only tests the success path. No test exercises the `isError` branch (deferred has `reject` available but never calls it).

**Fix:** Add test cases covering each missing branch.

---

## MEDIUM Severity

### M-1 · 6 duplicated private methods across mapper classes

|              |                                                                                 |
| ------------ | ------------------------------------------------------------------------------- |
| **Files**    | `src/sovereign/mappers/class-cluster-response-mapper.php`, `src/sovereign/mappers/class-member-response-mapper.php` |
| **Category** | COMPLEXITY                                                                      |

Both mappers contain **identical** implementations of 6 private helper methods:

| Method | Lines (cluster) | Lines (member) |
|---|---|---|
| `resolve_thumb_url()` | L245–258 | L113–126 |
| `resolve_media_url()` | L260–270 | L128–138 |
| `is_http_url()` | L272–274 | L140–142 |
| `extract_bbox_pixels()` | L279–300 | L147–168 |
| `normalize_similarity_value()` | L313–319 | L83–89 |
| `normalize_confidence_value()` | L321–328 | L91–97 |

**Fix:** Extract into a shared `trait MapsResponseFields` or a standalone `ResponseFieldNormalizer` utility class in `src/sovereign/mappers/`.

---

### M-2 · `should_use_local_projection` duplicated in 2 controllers

|              |                                                                                         |
| ------------ | --------------------------------------------------------------------------------------- |
| **Files**    | `src/api/class-clusters-controller.php` L295–305, `src/api/class-media-identities-controller.php` L120–132 |
| **Category** | COMPLEXITY                                                                              |

Both controllers contain functionally identical `should_use_local_projection()` methods that check sync state version and last-updated to decide local vs proxy. The only trivial difference is a local variable name (`$normalized` vs inline `trim()`).

**Fix:** Move to the shared base class `AbstractRecognitionProxyController` as a `protected` method, or extract to a `LocalProjectionGate` helper.

---

### M-3 · `list_for_cluster` query missing tenant_id scoping

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | `src/sovereign/repositories/class-identity-members-repository.php` L150–178 |
| **Category** | ANTIPATTERN                                                     |

The `list_for_cluster()` query filters only by `cluster_uuid`:

```sql
SELECT * FROM {members_table} WHERE cluster_uuid = %s
```

No `tenant_id` filter or JOIN to the clusters table. Called from `ClustersController::get_cluster_detail()`, `get_cluster_members()`, and `load_members_by_cluster()` — none pass a tenant_id.

While UUID uniqueness makes exploitation unlikely, this lacks defense-in-depth. Compare with `list_for_media_ids()` which correctly JOINs to the clusters table and filters by `c.tenant_id = %s`.

**Fix:** Add a `tenant_id` parameter and JOIN to the clusters table, or document the UUID-uniqueness assumption with a PHPDoc annotation.

---

### M-4 · `get_cluster_detail` silently proxies when local cluster not found

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | `src/api/class-clusters-controller.php` L230–247                |
| **Category** | ANTIPATTERN                                                     |

When `should_use_local_projection()` returns `true` but `find_by_uuid()` returns `null` (cluster not in local DB), the code falls through to `proxy_request()`:

```php
if ( $this->should_use_local_projection( $tenant_id ) ) {
    $cluster_row = $this->clusters_repository->find_by_uuid( $cluster_id );
    if ( is_array( $cluster_row ) ) {
        // ...local path...
        return new WP_REST_Response( $payload, 200 );
    }
}
// Falls through to proxy when cluster not found locally
return $this->proxy_request( ... );
```

If local projection is the authority (snapshot version > 0), a missing cluster should return 404 — not silently relay to a potentially stale backend. This undermines local-first semantics.

**Fix:** When `should_use_local_projection()` is `true` and `find_by_uuid()` returns `null`, return `new WP_Error('cluster_not_found', ..., ['status' => 404])`.

---

## LOW Severity

### L-1 · `SyncStatusController` extends proxy base class unnecessarily

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | `src/api/class-sync-status-controller.php` L19                  |
| **Category** | ANTIPATTERN                                                     |

`SyncStatusController` extends `AbstractRecognitionProxyController` but never calls `proxy_request()`. It only uses two inherited methods: `get_tenant_id()` and `can_manage_recognition()`. This couples a local-only endpoint to proxy infrastructure (API keys, base URL configuration).

**Fix:** Extract `get_tenant_id()` and `can_manage_recognition()` into a lighter base class or trait. Alternatively, accept this coupling as a convenience — it works — and document the intent.

---

### L-2 · RecognitionController composition root has no shared DI

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | `src/api/class-recognition-controller.php` L28–35               |
| **Category** | ANTIPATTERN                                                     |

All sub-controllers are instantiated with `new Controller()` and no arguments. Each creates its own independent `SyncStateRepository` (3 instances) and `IdentityMembersRepository` (2 instances). While functionally correct (stateless repositories), this prevents the composition root from injecting shared instances or test doubles.

**Fix:** Accept optional sub-controller instances or a repository factory in the constructor. Lower priority since nullable constructor params on sub-controllers already enable test DI.

---

### L-3 · Future-timestamp edge case in staleness check

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | `src/api/class-sync-status-controller.php` L56–69               |
| **Category** | GAP                                                             |

When `updated_at` is in the future (server clock skew), `time() - $timestamp` is negative, which is always `< $threshold`, so `is_projection_stale()` returns `false`. This silently treats a future timestamp as "not stale" — possibly masking clock drift issues.

**Fix:** Guard with `max(0, time() - $timestamp)` or document the intentional behavior.

---

## Recommended Fix Order

### Phase 1 — Correctness (before merge)

1. **H-2** — Wrap local-path cluster responses in the expected envelope shape with pagination metadata.
2. **H-3** — Add missing test cases: `is_stale` assertions, proxy fallback tests, loading/error component states.
3. **M-4** — Return 404 from `get_cluster_detail` when local projection is authoritative but cluster not found.

### Phase 2 — Robustness (soon after merge)

4. **H-1** — Replace N+1 `load_members_by_cluster` with a batch query.
5. **M-3** — Add `tenant_id` scoping to `list_for_cluster()`.
6. **M-2** — Extract `should_use_local_projection()` to shared base class.
7. **M-1** — Extract duplicated mapper helpers into a trait.

### Phase 3 — Maintainability (tech debt backlog)

8. **L-1** — Decouple `SyncStatusController` from proxy base class.
9. **L-2** — Add shared DI to `RecognitionController` composition root.
10. **L-3** — Guard future-timestamp edge case in staleness check.

---

# Consolidated Checklist

## Phase 1 — Correctness (before merge)

- [x] **H-2** — Wrap `map_cluster_list()` and `map_top_unlabeled_clusters()` return values in `{ "clusters": [...] }` envelope; add total count if feasible.
- [x] **H-3** — Add `SyncStatusControllerTest` case asserting `is_stale = true` when `updated_at` is old and `is_stale = false` when recent.
- [x] **H-3** — Add `ClustersControllerTest` case for proxy fallback path (sync version 0, no updated_at).
- [x] **H-3** — Add `SyncStatusIndicator.test.tsx` cases for loading state, error state, and fresh/ok badge.
- [x] **H-3** — Add `useSyncStatus.test.tsx` case for error/rejection path.
- [x] **M-4** — Return 404 `WP_Error` from `get_cluster_detail()` when local projection active but cluster not found.

## Phase 2 — Robustness

- [x] **H-1** — Add `list_for_cluster_uuids(array, int)` batch method to `IdentityMembersRepositoryInterface` and use in `load_members_by_cluster`.
- [x] **M-3** — Add `tenant_id` parameter and JOIN to `list_for_cluster()` query.
- [x] **M-2** — Move `should_use_local_projection()` to `AbstractRecognitionProxyController`.
- [x] **M-1** — Extract `resolve_thumb_url`, `resolve_media_url`, `is_http_url`, `extract_bbox_pixels`, `normalize_similarity_value`, `normalize_confidence_value` into `trait MapsResponseFields`.

## Phase 3 — Maintainability

- [x] **L-1** — Consider lighter base class or trait for `SyncStatusController`.
- [x] **L-2** — Accept optional sub-controller instances in `RecognitionController::__construct()`.
- [x] **L-3** — Guard `is_projection_stale()` against negative deltas from future timestamps.

## Success Criteria

- [x] Zero HIGH findings remaining
- [x] `composer test` passes with zero errors
- [x] `composer phpstan` passes (if configured)
- [x] `npm run typecheck` passes with zero new errors
- [x] `npm run test -- --run` passes with zero failures
- [x] `npm run lint` passes
- [x] `node scripts/check-architecture-compliance.js` passes (zero errors)
- [x] Branch audit re-run shows no regressions
