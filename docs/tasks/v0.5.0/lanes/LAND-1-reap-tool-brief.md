# LAND-1 lane brief — `land-1-reap-tool` (TDD)

Task: LAND-1 · Branch: `feature/land-1` · Plan: `docs/tasks/v0.5.0/LAND-1-inflight-worktree-landing-task-plan.md` (Slice 1, Slice 5 code half).
Finding-id range reserved for this lane: `LAND-1-RT-01..RT-20`. Do not reuse other ids.

## Objective

Ship `make worktree-reap`: a tracked, tested tool that enumerates every linked git worktree of this repo, classifies it, and (with `--apply`) removes the ones proven redundant. Tests first (red), then the implementation (green), then the make wiring. Nothing in this lane touches `scripts/workbay_lifecycle/` or `Makefile.d/` — both are gitignored plugin output.

## Why (problem)

Sub-lane worktrees are merged into their parent branch and never torn down. Today 20 of 28 worktrees have a branch that is an ancestor of its parent with zero unique commits. There is no repo-side reclaimer, so the count only grows ([RES-07] steady-state reclaimer: anything that grows needs a same-rate purge shipped in the same release).

## Deliverables (owned paths)

1. `scripts/test_worktree_reap.py` — pytest, no external deps beyond stdlib + git. Fixtures build a throwaway repo under `tmp_path` with `git init`, one commit on `main`, a `feature/parent` branch, and linked worktrees via `git worktree add`. Cases:
   - (a) sub-lane branch == ancestor of `feature/parent`, clean → `REDUNDANT`
   - (b) sub-lane with one unique commit → `LIVE`
   - (c) ancestor sub-lane with an untracked file → `DIRTY` (never reaped)
   - (d) `review/x` branch pointing at `main` → `REDUNDANT`
   - (e) sub-lane rebased onto parent: same patch, different SHA (`git cherry parent sub` all `-`) → `REDUNDANT`
   - (f) worktree whose branch has no parent match and is not an ancestor of `main` → `LIVE`
   - `apply(dry_run=False)` removes only `REDUNDANT` worktrees and deletes their branches; (b)/(c)/(f) untouched; running it twice is a no-op ([RES-01] idempotent retry).
   - `apply` refuses (raises / non-zero) when the target is the root worktree or the current worktree.
   - Mutation check to include as a test comment: removing the `git cherry` fallback must make (e) fail.
2. `scripts/worktree_reap.py` — `#!/usr/bin/env python3`, using the standard library for Git and classification logic. Ownership is authoritative registry data, so the reaper requires the `workbay_handoff_mcp` package; `--json`, `--check`, and `--apply` require it as well. The supported entry points are `make worktree-reap`, `make worktree-reap-check`, and `make worktree-reap-advise`.
   - `WorktreeRecord(path, branch, parent, status: Literal["REDUNDANT","LIVE","DIRTY","ROOT","UNKNOWN"], reason)`.
   - `parent_of(branch)`: `feature/<task>-<sub>` → `feature/<task>` when that branch exists; `review/<task>-…` → `feature/<task>` if it exists else `main`; otherwise `main`. Keep this a single pure function; tests cover it.
   - `is_merged(repo, branch, parent)`: `git merge-base --is-ancestor branch parent` OR every line of `git cherry parent branch` starts with `-`. Any git error → `False` (safe default). This mirrors `task_finish._branch_is_merged` in the workbay plugin; copy the semantics, do not import it.
   - `is_dirty(path)`: `git -C path status --porcelain --untracked-files=all` non-empty.
   - `classify(repo) -> list[WorktreeRecord]` from `git worktree list --porcelain`. Root worktree → `ROOT`. A worktree that cannot be inspected → `UNKNOWN`, never a neighbouring status ([GRPH-27] closed vocabulary).
   - `apply(records, *, dry_run=True) -> dict` — for each `REDUNDANT`: `git worktree remove <path>` (no `--force`, ever — rg-017), then `git branch -d <branch>`. Returns `{"removed": [...], "skipped": [...], "errors": [...]}`.
   - CLI: `python3 scripts/worktree_reap.py [--repo PATH] [--apply] [--check] [--json]`. Default is a dry run that prints a table of every record (full list, never just a count — [OBS-05]). `--check` exits `0` when nothing is redundant, `3` when redundant worktrees exist, and `1` on an inspection or mutation error; redundancy is reported as `3` regardless of `REAP_STRICT`. `worktree-reap-advise` maps only that `3` to advisory success unless `REAP_STRICT=1`.
3. `mk/lane-maintenance.mk` — add:
   ```make
   worktree-reap: ## Dry-run: list linked worktrees whose branch is already landed in its parent (REAP_ARGS=--apply to remove)
   	@$(PYTHON) scripts/worktree_reap.py --repo "$(CURDIR)" $(REAP_ARGS)
   worktree-reap-check: ## Fail when redundant worktrees exist (wired into check-all)
   	@$(PYTHON) scripts/worktree_reap.py --repo "$(CURDIR)"
   ```
   Use whatever `$(PYTHON)` / python variable the file already uses; if none, `python3`. Append `worktree-reap-check` to the `check-all` prerequisites in `Makefile` **only if** `check-all` already lists other `mk/` targets that way (see how `lane-overlaps-check` is added in `mk/lane-overlaps.mk`: it does `check-all: lane-overlaps-check`; do the same in `mk/lane-maintenance.mk`).
4. `Makefile` — add `scripts/test_worktree_reap.py` to the `test-scripts` file list (around line 553).

## Verification

- `python3 -m pytest scripts/test_worktree_reap.py -q` green.
- `make worktree-reap REAP_ARGS=--json` on this repo runs without error (the sandbox may have no linked worktrees; that is fine — output must still be valid JSON with an empty list). The make target supplies the required registry-backed runtime.
- `make worktree-reap-check` returns `3` when redundant worktrees exist and `0` otherwise; registry and Git inspection errors return non-zero.
- `make -n worktree-reap worktree-reap-check` resolves.
- Do not run `--apply` against the real repo in this lane.

## Constraints

- No `--force` on `git worktree remove`; no `git branch -D`. A dirty worktree is reported, never removed.
- No new dependencies. No changes outside the four owned paths.
- Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`.
- Commit on `feature/land-1` with a plain message; no attribution trailers.
- If something in this brief is already implemented, verify and report `ALREADY-FIXED:`; never weaken a test.

## Canon anchors

[RES-07] steady-state reclaimer · [RES-06] fail fast: classify before mutating · [RES-01]/[API-02] idempotent apply · [FLOW-06] state derived from git each run, never cached · [OBS-01]/[OBS-05] expose the full list, not a count · [GRPH-03] reachability (`is-ancestor`) is the landed predicate · [GRPH-27] closed status vocabulary.
