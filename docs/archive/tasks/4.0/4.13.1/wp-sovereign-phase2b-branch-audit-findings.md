# Branch Audit — Phase 2b: Snapshot Endpoint (Backend)

> **Date:** 2026-02-15
> **Scope:** 7 files changed (response schemas, repository protocol, SQLAlchemy repo, clusters router, fakes, stubs, test file)
> **Categories:** ANTIPATTERN · GAP · COMPLEXITY

---

## Summary

| Severity   | Count | Status    |
| ---------- | ----- | --------- |
| **HIGH**   | 3     | RESOLVED  |
| **MEDIUM** | 4     | RESOLVED  |
| **LOW**    | 3     | RESOLVED  |
| **Total**  | **10**| **DONE**  |

---

## Automated Check Results (reported by submitter)

| Check                                   | Result             |
| --------------------------------------- | ------------------ |
| `make check` (ruff + mypy + pytest)     | :x: tests failing  |
| `npm run typecheck`                     | N/A (no TS change) |
| `npm run test -- --run`                 | N/A                |
| `npm run lint`                          | N/A                |
| `check-architecture-compliance.js`      | N/A                |
| `composer phpstan`                      | N/A                |
| Cyclomatic complexity (radon, grade C+) | Not checked        |

---

## HIGH Severity

### H-1 · `TypeError` on `None` bbox coordinates in member response builder -- RESOLVED

|              |                                                                    |
| ------------ | ------------------------------------------------------------------ |
| **Files**    | `recognition/interface_adapters/http/routers/clusters.py` L220-225 |
| **Category** | GAP                                                                |

**Issue:** `MediaIdentity.bbox_x` and `bbox_y` are typed `int | None`. Arithmetic and Pydantic field assignment without null guards would cause `TypeError`.

**Resolution:** Added null guards defaulting to `0`:
```python
bbox_x = identity.bbox_x or 0
bbox_y = identity.bbox_y or 0
```
Bbox values passed to FaceBoxResponse are now guaranteed to be `int`.

### H-2 · Route URL diverges from contract -- RESOLVED

|              |                                                                |
| ------------ | -------------------------------------------------------------- |
| **Files**    | `recognition/interface_adapters/http/routers/clusters.py` L168 |
| **Category** | GAP                                                            |

Contract specified: `GET /tenants/{tenant_id}/clusters/snapshot`
Implementation uses: `GET /tenants/{tenant_uuid}/clusters/snapshot`

The path parameter is named `tenant_uuid` (not `tenant_id`) because `tenant_id` is a reserved Query parameter name in the transitive dependency chain: `get_cluster_repository` -> `get_session` -> `get_tenant_id_optional(tenant_id: Query)`. FastAPI validates parameter sources across the full dependency tree at module-load time and rejects the collision. A separate-router approach was attempted but does not help because the collision is intrinsic to the endpoint's own dependency chain, not cross-route.

**Resolution:** Path param renamed to `tenant_uuid`. Contract (`contracts/cluster-snapshot-api.md`) updated to document the actual URL. Rule 13 added to `backend-python-guidelines.md` and a corresponding section added to `testing-python.md` to prevent recurrence.

### H-3 · `image_width` / `image_height` computed as rough estimate — RESOLVED

|              |                                                                    |
| ------------ | ------------------------------------------------------------------ |
| **Files**    | `recognition/interface_adapters/http/routers/clusters.py` L227-228 |
| **Category** | ANTIPATTERN                                                        |

**Issue:** Contract specifies actual image dimensions. Implementation was computing `bbox_width + bbox_x * 2` as a "rough estimate", which is incorrect.

**Resolution:** Return `0` as sentinel value. Added contract note that consumer resolves dimensions from WordPress media metadata (`wp_postmeta`). This aligns with v0.1.0 scope where plugin-side bbox normalization is assumed.

---

## MEDIUM Severity

### M-1 · `BboxSnapshotResponse` duplicates `FaceBoxResponse` -- RESOLVED

|              |                                                      |
| ------------ | ---------------------------------------------------- |
| **Files**    | `recognition/interface_adapters/http/routers/clusters.py` L234 |
| **Category** | COMPLEXITY                                           |

**Issue:** Two identical bbox models existed.

**Resolution:** Removed `BboxSnapshotResponse` class entirely. Snapshot endpoint now uses `FaceBoxResponse` for member bboxes, reusing the canonical model.

### M-2 · Snapshot endpoint function is 80+ lines — RESOLVED

|              |                                                                |
| ------------ | -------------------------------------------------------------- |
| **Files**    | `recognition/interface_adapters/http/routers/clusters.py` L161-275 |
| **Category** | COMPLEXITY                                                     |

**Issue:** Monolithic 80-line handler spanning auth, data fetch, and two response builders.

**Resolution:** Extracted two helper functions:
- `_build_cluster_responses(clusters)` - L138-166
- `_build_member_responses(members_with_identities)` - L169-200

Main handler now ~30 lines, delegating to helpers.

### M-3 · `FakeClusterForRepo` has invalid UUID default -- RESOLVED

|              |                                                                       |
| ------------ | --------------------------------------------------------------------- |
| **Files**    | `recognition/tests/fakes.py` L85                                      |
| **Category** | GAP                                                                   |

**Issue:** Default `tenant_id` was `"default-tenant"`, invalid as UUID.

**Resolution:** Changed to `tenant_id: str = "00000000-0000-0000-0000-000000000000"` (nil UUID).

### M-4 · Tests seed data into both stores independently -- RESOLVED

|              |                                                                     |
| ------------ | ------------------------------------------------------------------- |
| **Files**    | `recognition/tests/api/test_api_clusters.py` L206-249, conftest L534 |
| **Category** | COMPLEXITY                                                          |

**Issue:** Snapshot tests manually seeded both `fake_cluster_service` and `fake_cluster_repository` separately, creating dual-store fragility.

**Resolution:** Updated `seed_cluster()` helper to accept optional `fake_cluster_repository` parameter and seed both stores in a single call. Tests now pass `fake_cluster_repository=fake_cluster_repository` to eliminate manual dual-seeding.

---

## LOW Severity

### L-1 · Unused `Path` import -- RESOLVED

|              |                                                              |
| ------------ | ------------------------------------------------------------ |
| **Files**    | `recognition/interface_adapters/http/routers/clusters.py` L11 |
| **Category** | DEAD_CODE                                                    |

**Issue:** Path import was briefly added during workaround attempts.

**Resolution:** Verified via grep - no `Path` import present. Import cleanup complete.

### L-2 · `ClusterSnapshotResponse.generated_at` is `str` instead of `datetime` -- RESOLVED

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | `recognition/interface_adapters/http/schemas/responses.py` L405 |
| **Category** | ANTIPATTERN                                                     |

**Issue:** Field was typed `str` with ISO8601 comment; required manual `.isoformat()` call.

**Resolution:** Changed to `generated_at: datetime`. Pydantic now handles serialization automatically, enforcing format correctness at the model level.

### L-3 · `ClusterSnapshotClusterResponse.curation_state` is `str` instead of `Literal` -- RESOLVED

|              |                                                                 |
| ------------ | --------------------------------------------------------------- |
| **Files**    | `recognition/interface_adapters/http/schemas/responses.py` L386 |
| **Category** | ANTIPATTERN                                                     |

**Issue:** Field allowed any string value. Contract specifies exactly three: `"active"`, `"dismissed"`, `"confirmed"`.

**Resolution:** Changed to `curation_state: Literal["active", "dismissed", "confirmed"]`. Now type-safe and OpenAPI-documented.

---

## Recommended Fix Order

### Phase 1 — Correctness (COMPLETED)

1. **H-1** ✓ — Null guards for bbox coordinates
2. **H-2** ✓ — Route parameter renamed to `tenant_uuid`, contract updated
3. **H-3** ✓ — Image dimensions return `0` sentinel

### Phase 2 — Robustness (COMPLETED)

4. **M-1** ✓ — `BboxSnapshotResponse` removed, `FaceBoxResponse` reused
5. **M-2** ✓ — Extracted helper functions from the 80-line endpoint
6. **M-3** ✓ — Valid UUID default for `FakeClusterForRepo.tenant_id`
7. **M-4** ✓ — Unified test seeding into `seed_cluster()` helper

### Phase 3 — Maintainability (COMPLETED)

8. **L-1** ✓ — No unused `Path` import
9. **L-2** ✓ — `generated_at` typed as `datetime`
10. **L-3** ✓ — `curation_state` constrained to `Literal` enum

---

# Consolidated Checklist

## Phase 1 — Correctness

- [x] **H-1** — Null guards for `bbox_x` / `bbox_y`; prevented TypeError
- [x] **H-2** — Route parameter `{tenant_uuid}`, contract updated
- [x] **H-3** — Image dimensions return `0` sentinel

## Phase 2 — Robustness

- [x] **M-1** — `BboxSnapshotResponse` removed; using `FaceBoxResponse`
- [x] **M-2** — Extracted `_build_cluster_responses()` and `_build_member_responses()` helpers
- [x] **M-3** — `FakeClusterForRepo.tenant_id` default: nil UUID
- [x] **M-4** — `seed_cluster()` now atomic; seeds both stores

## Phase 3 — Maintainability

- [x] **L-1** — No unused imports
- [x] **L-2** — `generated_at: datetime`
- [x] **L-3** — `curation_state: Literal[...]`

## Success Criteria

- [x] Zero HIGH findings remaining
- [ ] `make check` passes (ruff + mypy + pytest) — *awaiting test run*
- [ ] All existing tests continue to pass — *awaiting test run*
- [ ] Branch audit re-run shows no regressions — *awaiting test run*
