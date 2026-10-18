# LAND-1 lane brief — `land-1-reap-tool` round 3

Task: LAND-1 · Branch: `feature/land-1` · Worktree: `/Users/daniel/Development/context-alt-text-monorepo-land-1`.
Owned paths: `scripts/worktree_reap.py`, `scripts/test_worktree_reap.py`, `mk/lane-maintenance.mk`. **Nothing else.** Round 2 touched `scripts/deploy/gpu-lifecycle-install.sh`, which is another lane's file (`LAND1R-M-09`); do not repeat that.
Finding-id range reserved for this lane: `LAND-1-R3-01..30`. Do not reuse any other id.
Test command: `python3 -m pytest scripts/test_worktree_reap.py -q`.

## Why there is a round 3

Round 2 was reviewed and left nine findings open. More importantly, **round 2's own fix broke the tool.** Read that sentence before you read anything else: the change that closed `LAND1R-H-01` made `is_dirty()` count *ignored* files. Every worktree in this repo contains a `.venv`. A real dry run at `88b67a73d` classified 16 of 19 rows `DIRTY`, including `feature/gpuops-1-fix-intent`, `feature/gpuops-1-fix-process` and `feature/gpuops-1-journal` — all three of which `git merge-base --is-ancestor` proves are landed. The reclaimer now reclaims nothing and reports that everything is fine. That is `LAND1R-H-04` and it is the first thing to fix.

Reproduce before you change anything:

```
cd /Users/daniel/Development/context-alt-text-monorepo-land-1
python3 scripts/worktree_reap.py            # dry run, no flags, prints the table
git merge-base --is-ancestor feature/gpuops-1-fix-intent feature/gpuops-1 && echo LANDED
```

The second command says LANDED. The first says DIRTY. Both cannot be right.

## Ordering

Do `LAND1R-H-04` first and re-run the dry run to confirm the table changes. Then the rest. A round that fixes the races but leaves the tool inert has not moved.

## Work items

Each of these is an open finding in the handoff DB with its own `fix` field. Read them with `review_findings(review={"operation":"list","task_ref":"LAND-1","status":"open"})` — do not work from this summary alone, and record your own findings under `LAND-1-R3-*` only.

**Classification correctness**

- `LAND1R-H-04` — ignored-only vs really-dirty. Split the predicate; gate ignored-only reclamation behind an explicit `--allow-ignored`. This is the unblocker.
- `LAND-1-RT-01` — landed-anywhere-downstream. `is_merged` only tests the derived parent, so a sub-lane merged straight into `main` reads LIVE forever. The predicate is reachability into the integration branch, not into one guessed parent ([GRPH-03]).
- `LAND1R-M-05` — a Git failure or a missing parent must be `UNKNOWN`, not `LIVE`. Collapsing every non-ancestor result to "live" hides degraded inspection.

**Mutation safety** — these three are the data-loss class. Treat the mutation path as a two-phase commit against Git, not a loop.

- `LAND1R-H-02` — re-verify that the path still maps to the classified branch, and validate branch/proof state *before* `git worktree remove`, not after.
- `LAND1R-H-03` — `_delete_branch` discards the landing-parent OID that `_proof_for_delete` computed; `_delete_ref` then deletes against the branch OID only. Carry the proof through to the delete and make the delete conditional on it.
- `LAND1R-H-01` — recheck cleanliness immediately before removal, using the `LAND1R-H-04` predicate. Git removes an ignored-only worktree without `--force`, so a classification-time check is not enough.
- `LAND1R-M-03` — deleting a redundant parent before its redundant child orphans the child's proof. Order the pending list so children are handled before parents, or recompute the proof per item.
- `LAND1R-M-04` — `apply()` mutates while still building the pending list, so the documented refusal on the current/root worktree is neither fail-fast nor all-or-nothing. Build the whole plan, validate it, then execute.

**Fencing and gates**

- `LAND-1-RT-02` — a `review/<task>` worktree hosting a live remote lane is REDUNDANT by construction and would be removed with a process attached. Add `--protect` / `REAP_PROTECT` and honour it in `apply()`. Git cannot see lane activity; this is the fence ([RES-10]).
- `LAND1R-M-06` — `REAP_PROTECT` is expanded with make's whitespace-splitting `foreach`, so a path containing a space silently becomes two arguments and the fence fails open. A safety lever that fails open is worse than none.
- `LAND-1-RT-03` — `check-all` depends on `worktree-reap-check`, which exits 3 whenever any REDUNDANT worktree exists. `lane-intake` runs `make check-all` immediately after merging a sub-lane, at which point that sub-lane's worktree is REDUNDANT *by definition*, so every intake now fails. Make the gate advisory unless `REAP_STRICT=1`. Fail-fast belongs on the mutation, not on unrelated gates.

## Fixtures the suite must gain

Round 2's fixtures still do not cover the cases that bite. Add, at minimum:

- (f) a landed branch whose worktree is clean except for an ignored `.venv` → reclaimable under `--allow-ignored`, refused without it.
- (g) a sub-lane branch merged directly into `main` with an unrelated derived parent → REDUNDANT, not LIVE.
- (h) the parent tip moves between classification and apply → refuse, mutate nothing.
- (i) the worktree path is re-pointed at a different branch between classification and apply → refuse, mutate nothing.
- (j) a redundant parent and a redundant child in the same plan → child first, parent's proof still verifiable.
- (k) a protected path is also REDUNDANT → excluded from the plan; a protected path containing a space → still excluded.
- (l) a plan containing the current or root worktree → nothing is removed at all, not "everything before it".
- (m) `git` returns non-zero for `merge-base` → UNKNOWN, and `--strict` exits non-zero on UNKNOWN.

## Rules

- Git is the only source of truth for "landed". No DB, no filesystem heuristic, no branch-name inference for the landed predicate.
- Never `--force` a worktree removal. Never `git branch -D`. Refusal is always an acceptable outcome; silent deletion never is ([rg-017]).
- `ruff`/`mypy` findings do not block; record them as `low` prefixed `lint(<tool>):`.
- Do not paste findings into any markdown file — record them in the handoff DB.
- No `Co-Authored-By` or model-attribution trailers in commit messages.
