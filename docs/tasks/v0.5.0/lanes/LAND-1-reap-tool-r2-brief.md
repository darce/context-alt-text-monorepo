# LAND-1 lane brief — `land-1-reap-tool` round 2 (fix local review findings)

Task: LAND-1 · Branch: `feature/land-1` · Base: your own commit `15827465e` (reaper landed, 6 tests green). Findings to close: `LAND-1-RT-01`, `LAND-1-RT-02`, `LAND-1-RT-03` (read them with `review_findings` list on `task_ref=LAND-1`; bodies repeated below). New ids, if you find more: `LAND-1-RT-04..20`.

## RT-01 (medium) — landed-in-main sub-lane is misclassified LIVE

`classify` only asks `is_merged(branch, parent)`. A sub-lane merged straight into `main` (real case: `feature/healthobs-1-dedupe`, whose derived parent `feature/healthobs-1` never received it) stays `LIVE` forever. Fix: `REDUNDANT` when `is_merged(branch, parent)` **or** (`parent != "main"` and `is_merged(branch, "main")`); the `reason` must name the branch it landed in. Test (g): sub-lane merged into `main` but not into `feature/parent` → `REDUNDANT`, `parent` field still `feature/parent`.

## RT-02 (medium) — no way to fence a worktree with a live lane

A `review/<task>` worktree that hosts a running remote review has zero unique commits, so it is `REDUNDANT` by construction and `apply(dry_run=False)` would remove it under a live process. Fix: repeatable `--protect <path-or-branch>` CLI flag (make variable `REAP_PROTECT`, passed as `$(foreach p,$(REAP_PROTECT),--protect $(p))`), which forces `status="LIVE"`, `reason="protected by caller"`. `apply` must never remove a protected record even if handed a `REDUNDANT` one built elsewhere — carry a `protected: bool` field on `WorktreeRecord`. Tests: protected redundant record is skipped, branch survives; `--protect` accepts both the path and the branch form.

## RT-03 (medium) — `check-all: worktree-reap-check` breaks `lane-intake`

`lane-intake` runs `POST_INTAKE_CHECK_CMD = make check-all` right after merging a sub-lane, when that sub-lane's worktree is `REDUNDANT` by definition, so the exit-3 check fails every intake (and every dev machine with stale worktrees). Fix: `worktree-reap-check` prints the full table and exits 0 unless `REAP_STRICT=1`, in which case it exits 3. Implement via a `--check` CLI flag whose exit code honours `REAP_STRICT`; keep `worktree-reap` (no `--check`) at exit 3 on redundant. Test both exit paths through `main([...])` with `monkeypatch.setenv`.

## Verification / constraints

- `python3 -m pytest scripts/test_worktree_reap.py -q` green (≥ 9 tests).
- `make -n worktree-reap worktree-reap-check REAP_PROTECT="a b"` resolves.
- Owned paths unchanged: `scripts/worktree_reap.py`, `scripts/test_worktree_reap.py`, `mk/lane-maintenance.mk`, `Makefile`. Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**`.
- No `--force`, no `branch -D`. Commit on `feature/land-1`, plain message, no attribution trailers. Report `FIXED: <id> <sha>` per finding.

Canon: [GRPH-03] reachability into the integration branch is the landed predicate · [RES-10] explicit fencing for shared resources · [RES-06] fail fast on the mutation, never on unrelated gates · [OBS-05] print the full list.
