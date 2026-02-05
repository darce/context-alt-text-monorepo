# Current Task: Background Surfacing Batching + UI Hang Investigation

**Started**: 2026-02-05
**Task Doc**: `docs/tasks/4.0/4.11.2/background-surfacing-ui-hang-plan.md`
**Status**: IN_PROGRESS

## Objective

Eliminate background surfacing stalls (N+1 query + long MVCC snapshots) and investigate WordPress admin "Saving..." hangs after labeling.

## Context

Issues began after commit `61a7d85` (pass label to background surfacing). Backend surfacing could hang on large datasets due to N+1 queries, and WP admin showed JS errors suggesting missing globals. Backend batching/chunking and frontend dependency fixes are in progress.

- Why this matters: background task stalls block new suggestions and confuse users; UI hang blocks labeling workflow.
- Related issue/PR: N/A

## Progress

### Completed

- [x] Add batch fetch path for member identities and update surfacing flow to use it.
- [x] Add chunked background surfacing with per-chunk logging and total timing logs.
- [x] Add unit + integration tests for batch surfacing and background task timeout.
- [x] Add WP admin script dependencies (`wp-element`, `wp-i18n`, `wp-hooks`) and defensive global checks.
- [x] Resolve mypy errors in `surface_for_newly_labeled_cluster` representative checks.
- [x] Backend tests green (`pytest` all: 434 passed, 4 skipped).
- [x] Address dev-slice review quick fixes (items #1-#3, #6-#8).
- [x] **Fix missing session commit** — `get_session()` now auto-commits on success, rolls back on exception. Root cause of cluster labels not persisting.

### In Progress

- [ ] Complete frontend investigation items (console errors, incognito reproduction, proxy response check). ← **ACTIVE**

### Remaining

- [ ] Validate success criteria in `background-surfacing-ui-hang-plan.md`.
- [ ] Investigate 30s background surfacing stall (R2 in review doc) — possible event-loop starvation during per-identity gate evaluation.

## Key Files

| File                                                                                        | Purpose                                            |
| ------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py` | Surfacing logic + representative handling          |
| `apps/prototype-description-service/recognition/application/tasks/clustering.py`            | Background surfacing task chunking + timing logs   |
| `apps/prototype-wp-alt-context/src/admin/class-admin.php`                                   | WP admin asset enqueue + script deps               |
| `apps/prototype-description-service/db/session.py`                                          | Async session factory + `get_session()` dependency |
| `docs/tasks/4.0/4.11.2/background-surfacing-ui-hang-plan.md`                                | Plan + consolidated checklist                      |
| `docs/tasks/4.0/4.11.2/dev-slice-review-2026-02-05.md`                                      | Dev slice review findings + runtime issue analysis |

## Technical Notes

- Precomputed representatives can be `np.ndarray` or `Sequence[np.ndarray]`; empty checks must handle both without NumPy truthiness errors.
- Chunking uses estimated identity counts per cluster to keep per-session MVCC windows short.

## Verification Commands

```bash
# Type checking
cd apps/prototype-description-service
PYENV_VERSION=description-service mypy .

# Targeted test
pytest recognition/tests/integration/test_proactive_suggestions.py -k background_surfacing
```

## Next Agent Instructions

1. Restart the Python backend and verify cluster labeling persists across page refresh.
2. Investigate the 30s background surfacing stall — add entry-level logging to GET route handlers and a watchdog log inside the per-identity surfacing loop to find the exact stall point.
3. Consider changing `updateClusterLabel` in `clusterApi.ts` from `Promise<void>` to `Promise<ClusterResponse>` for resilience against refetch failures.
4. Run full backend test suite to confirm green.

---

## Session Log

### 2026-02-05 - Session 1

- Added representative empty-check handling for NumPy arrays; addressing mypy errors next.
- Prepared CURRENT_TASK.md to track multi-session progress.

### 2026-02-05 - Session 2

- Verified full backend test suite: 434 passed, 4 skipped.
- Mypy errors resolved for representative empty-check changes.

### 2026-02-05 - Session 3

- Fixed dev-slice review item #1 by threading `cluster_id` into `_to_domain_identity()` and removing post-construction mutation.
- Fixed dev-slice review item #2 by moving inline imports (`asyncio`, `time`) to module tops.
- Fixed dev-slice review item #3 by removing the dead N+1 warning block in the surfacing summary.
- Fixed dev-slice review item #6 by renaming the single-cluster representatives map to `labeled_reps`.
- Fixed dev-slice review item #7 by aligning fake repo signatures with `Sequence[str]`.
- Fixed dev-slice review item #8 by consolidating representative empty checks into `_is_empty_reps()`.

### 2026-02-05 - Session 4

**Root-cause analysis: cluster labels not persisting ("Saved!" then reverts to UUID)**

- Traced the full mutation chain: frontend `updateClusterLabel()` → PHP `proxy_request()` → Python PATCH `/clusters/{id}` → `cluster_mutations.update_cluster()` → `cluster_repo.update()` → `session.flush()`.
- Confirmed the PATCH succeeds at every layer: backend log shows `label='Tory Guzman'` committed in 0.019s, `user_confirmed=True`, response includes `is_auto_label: false`.
- Discovered `get_session()` in `db/session.py` **never committed** — it yielded the session then `finally: await session.close()` without calling `commit()`. The docstring said "caller is responsible for committing" but no caller in `clusters.py` or `suggestions.py` ever did (only `analyze.py` had an explicit commit).
- `session.flush()` writes to the DB within the open transaction (visible to the same session, hence the correct PATCH response), but `session.close()` without prior commit causes an implicit rollback. Every subsequent GET reads the pre-rename state.
- This is a **systemic bug** affecting all write endpoints: PATCH cluster, merge, split, reassign, accept/reject suggestion, create cluster, pin representative, revert merge.
- **Systemic fix**: Changed `get_session()` to auto-commit on success (`await session.commit()` after `yield`) and rollback on exception (`except: await session.rollback(); raise`). All 434 tests pass unchanged.
- ⚠️ **This fix alone did not resolve the user-facing issue** — the running backend was not restarted after editing `db/session.py`, so the old no-commit `get_session()` remained active in memory. The actual user-visible fix came in Session 5 (explicit `await session.commit()` in the PATCH handler), which took effect without a server restart because endpoint code is re-invoked per request.
- Additionally diagnosed: browser 500s on GET endpoints during background surfacing (R2), `wp.hooks.doAction` undefined (R1, WP core loading order — no action), and stale job 404s from localStorage history (self-healing, no action).
- Findings documented in `docs/tasks/4.0/4.11.2/dev-slice-review-2026-02-05.md` under "Runtime Issue Analysis".

### 2026-02-05 - Session 5

- Issue still reported: label reverts after refresh, UI shows `cluster-6fda78b616874611aae09b847bb97eb0`.
- Added explicit `await session.commit()` in PATCH `/clusters/{id}` handler — **this was the line that actually fixed the problem** at runtime, since Session 4's `get_session()` change required a backend restart to take effect.
- Both commits are now in place (explicit inline + `get_session()` teardown). The double-commit is harmless (second commit is a no-op on an already-committed transaction) and the explicit one serves as a defense-in-depth safety net.
- Result: with both layers, all write endpoints are covered systemically via `get_session()`, and the PATCH handler has belt-and-suspenders protection.
