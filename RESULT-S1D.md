# FIR-9 S1d — Discrimination results

## 1. Baseline (start)

```
cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests -k atlas -q
.............                                                            [100%]
13 passed, 1844 deselected in 12.30s
```

Pre-existing suite at worktree start: **13 passed**. Production `atlas_repository.py` was not modified.

## 2. Tests added (file)

**Only edited:** `recognition/tests/test_atlas_repository.py`

| Finding | New / changed tests |
| --- | --- |
| FIR-9-BR-02A | `test_iter_tenant_embeddings_isolates_exact_tenant_id_set` — two tenants; exact id set `{A}` |
| FIR-9-BR-02B | `test_list_foreign_embedding_models_ignores_other_tenant_models` — tenant B foreign model ignored for A; `assert_requested_embedding_model` stays quiet |
| FIR-9-BR-03 | `test_iter_tenant_embeddings_excludes_disposed_identities` — disposed row absent from yielded ids |
| FIR-9-BR-04A | `test_centroid_fallback_uses_representatives_not_members` — missing-MV cluster with distinct rep vs member vectors; assert rep mean |
| FIR-9-BR-04B | `test_centroid_fallback_uses_member_embeddings_when_no_reps` — no reps, members only; assert member mean |
| FIR-9-BR-05 | `test_require_tenant_uuid_rejects_malformed_id`, `test_coerce_cluster_ids_rejects_malformed_id`, `test_iter_tenant_embeddings_rejects_malformed_tenant_id` — `ValueError` names the bad value |

Helper: `_seed_identity(..., disposed_at=)`, `_seed_tenant(...)`.

**Not production-changed.** BR-01 purge side already covered by existing `test_atlas_purge_disposed_scope_keeps_live_points_and_runs` in `test_atlas_schema_purge.py` (no edit needed).

## 3. Measurement method

Copy `atlas_repository.py` → backup; assert anchor once; apply mutant; run `-k atlas -q --tb=line`; classify:

- `rc==0` → SURVIVED
- `rc==1` with `failed` count → KILLED
- else → HARNESS-ERROR

Restore in `finally`; verify `git diff --quiet` on production path.

CONTROL: comment above `class AtlasRepository:` → must SURVIVE.

## 4. Battery output (after tests landed)

### BASELINE (unmutated, post-tests)

```
.....................                                                    [100%]
21 passed, 1844 deselected in 6.16s
```

### CONTROL (no-op comment) → SURVIVED

```
=== CONTROL rc=0 verdict=SURVIVED ===
.....................                                                    [100%]
21 passed, 1844 deselected in 6.26s
```

### BR-02A — delete `.where(MediaIdentity.tenant_id == tenant_uuid)` from `iter_tenant_embeddings` → KILLED

```
=== BR-02A_iter_tenant rc=1 verdict=KILLED victims=1 ===
1 failed, 20 passed, 1844 deselected in 6.25s
FAILED recognition/tests/test_atlas_repository.py::test_iter_tenant_embeddings_isolates_exact_tenant_id_set
```

### BR-02B — delete tenant filter from `list_foreign_embedding_models` → KILLED

```
=== BR-02B_list_foreign rc=1 verdict=KILLED victims=1 ===
1 failed, 20 passed, 1844 deselected in 6.26s
FAILED recognition/tests/test_atlas_repository.py::test_list_foreign_embedding_models_ignores_other_tenant_models
```

### BR-03 — delete `.where(MediaIdentity.disposed_at.is_(None))` → KILLED

```
=== BR-03_disposed_filter rc=1 verdict=KILLED victims=1 ===
1 failed, 20 passed, 1844 deselected in 6.19s
FAILED recognition/tests/test_atlas_repository.py::test_iter_tenant_embeddings_excludes_disposed_identities
```

### BR-04A — `embeddings = []` at first assignment in `_mean_of_representatives_centroid` → KILLED

```
=== BR-04A_rep_empty rc=1 verdict=KILLED victims=1 ===
1 failed, 20 passed, 1844 deselected in 6.26s
FAILED recognition/tests/test_atlas_repository.py::test_centroid_fallback_uses_representatives_not_members
```

### BR-04B — force `get_member_fallback_embeddings` path empty → KILLED

```
=== BR-04B_member_empty rc=1 verdict=KILLED victims=1 ===
1 failed, 20 passed, 1844 deselected in 6.29s
FAILED recognition/tests/test_atlas_repository.py::test_centroid_fallback_uses_member_embeddings_when_no_reps
```

### BR-05 — `raise ValueError(...)` → `return uuid.UUID(int=0)` in `_require_tenant_uuid` → KILLED

```
=== BR-05_nil_uuid rc=1 verdict=KILLED victims=2 ===
2 failed, 19 passed, 1844 deselected in 6.21s
FAILED recognition/tests/test_atlas_repository.py::test_require_tenant_uuid_rejects_malformed_id
FAILED recognition/tests/test_atlas_repository.py::test_iter_tenant_embeddings_rejects_malformed_tenant_id
```

### BR-01 companion (purge predicate, production purge_service not edited by this lane)

Mutant: `_atlas_point_predicate` always `return None`.

```
=== BR-01 point_predicate return None ===
rc= 1
FAILED recognition/tests/test_atlas_schema_purge.py::test_atlas_purge_disposed_scope_keeps_live_points_and_runs
AssertionError: disposed scope must delete exactly one atlas point; got 2
1 failed in 0.46s
```

**Verdict: KILLED** (existing S1a test; measured this session). Restored clean.

## 5. Summary table

| Mutant | Verdict before (bdcde1e9 / start) | Verdict after | Victim count |
| --- | --- | --- | --- |
| CONTROL (comment) | SURVIVED | SURVIVED | 0 |
| BR-02A iter tenant filter | SURVIVED | **KILLED** | 1 |
| BR-02B list_foreign tenant filter | SURVIVED | **KILLED** | 1 |
| BR-03 disposed filter | SURVIVED | **KILLED** | 1 |
| BR-04A rep embeddings=[] | SURVIVED | **KILLED** | 1 |
| BR-04B member embeddings=[] | SURVIVED | **KILLED** | 1 |
| BR-05 nil UUID instead of ValueError | SURVIVED | **KILLED** | 2 |
| BR-01 point predicate return None | (S1a gap; now pinned) | **KILLED** | 1 |

## 6. Final suite counts

**Atlas (`-k atlas`):**

```
21 passed, 1844 deselected in 6.16s
```

**Full `recognition/tests`:**

```
1807 passed, 58 skipped, 4 warnings in 215.24s (0:03:35)
```

## 7. Survivors

**None of the six assigned atlas read-path mutants survive.** CONTROL still SURVIVES (harness sanity). Production `atlas_repository.py` and `purge_service.py` restored clean after measurement (`git diff --quiet` on both).

## 8. Scope note

- No production behaviour changes.
- No handoff/MCP writes (orchestrator-owned).
- Lane-owned file: `recognition/tests/test_atlas_repository.py` + this `RESULT-S1D.md`.
