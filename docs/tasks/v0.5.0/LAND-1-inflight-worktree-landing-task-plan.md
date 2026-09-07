# Task Plan: LAND-1

> **Metadata**
>
> - **Date**: 2026-09-07 11:30 EST
> - **Author**: Claude Opus 5
> - **Project**: context-alt-text-monorepo (cross-task coordination)
> - **Task ID**: `LAND-1`
> - **Target Branch**: `feature/land-1`
> - **Review Coverage Target**: 2
>
> Finding bodies live in the handoff DB. This plan references groups by name only.

---

## LAND-1. Land or retire every inflight worktree and branch

## Objective

Converge every linked worktree and branch reported by a fresh, named inventory to root on `main` plus only lanes that are actively executing. Land the five live components (GPULIFE-1, HEALTHOBS-1, DEMOGATE-2, EVID-1, GPUOPS-1) through the pre-merge gate, reap only worktrees proven redundant by that inventory, park the August eval-harness cluster under deterministic archive tags, and ship the repo-side tool that stops this from recurring. All counts in this plan are derived from the inventory artifact; none are carried forward from an earlier run.

## Problem Statement

Sub-lane worktrees are integrated into their parent branch but never torn down; review worktrees outlive the review; lane rows stay `planned` after the branch has landed; and main-target maintenance rows never get `plan-done`. Git is the source of truth for "landed", but the handoff DB and filesystem have drifted from it. The remedy therefore needs one reconstructable Git manifest, an explicit coordinator protocol for DB closure, and a serialized root-ref merge queue.

## Constraints

- Pre-Merge Gate Rule: every merge to `main` needs `handoff_close_check(enforce=True)` green, fresh `test_result` at HEAD, zero open findings (or explicit defer/wontfix with rationale), slice-complete decision.
- rg-017: never force-remove a dirty worktree. Re-verify `git status --short` immediately before apply; a prior clean result is not reusable evidence.
- Never start/stop the live GPU. `acx-gpu-burst` stays STOPPED; no operator-gated deployment steps are executed by this plan.
- Implementation and grunt work runs on `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` (the supported dispatch field; the lane manifest may override it only by an explicit operator decision). Local junior subagents only for classification and fetching. Local host runs `tsc`/`vitest`/`pytest` verification and the bounded remote gate.
- Worktree rule: root stays on `main`; delete merged branches after `task-finish`.
- Peer-session dirty files in root (`vite.config.ts`, `.codex/config.toml`, `.mcp.json`, `.vscode/mcp.json`) are not touched.
- The inventory is captured at one named `INVENTORY_SHA` before any mutation. Linked worktrees and branch-only refs are separate classes; a count not present in the raw manifest is not an acceptance claim.
- Handoff rows and findings share one DB resource. `land-1-hygiene` is the sole DB writer for this task, uses an expected revision for every conditional update, and reads back the exact status and counts before the next DB batch.

## Workflow Principles

- Model the landing as a DAG and topological-sort it ([GRPH-01]); partition by connected components before ordering ([GRPH-06]); name the cut vertex ([GRPH-05]); colour the file-conflict graph so same-file lanes never run concurrently ([GRPH-09]); list-schedule ready nodes by longest remaining chain ([GRPH-31]).
- [RES-07] Steady-state reclaimer: every mechanism that creates a worktree ships with a same-rate purge (`make worktree-reap`, same release).
- [RES-06]/[RES-02] Fail fast, bounded waits: classify before mutating; refuse to reap anything not proven redundant by `merge-base --is-ancestor` or the contracted `git cherry` fallback; a missing parent is `NEEDS_REVIEW`; the remote gate has a deadline and an exit-code/SHA check.
- [RES-14] Handshaking: each component lands independently behind its own gate; a red gate on one never blocks siblings.
- [RES-01]/[API-02] Idempotent steps: every landing/reap step is re-runnable; nothing double-applies on retry.
- [RES-10] Fencing: one owner per branch at a time — lane locks respected, no two lanes with the same colour dispatched concurrently.
- [FLOW-06] Derived state heals from the log: worktree/row inventory is re-derived from git on every run, never remembered.
- [GRPH-09] Shared-file edges are hard dependencies: the healthobs/GPUOPS `apps/prototype-description-service/api/main.py` edge is serialized and cannot be hidden by file coloring.
- Root `main` updates use one coordinator lock and one intake queue. Lane work and reviews may run in parallel only after complete-diff conflict coloring; root-ref mutation, ancestry recomputation, and post-merge evidence are serialized.
- [RES-12]/[PERF-14] Batch the chatty path: `plan-done`, finding dispositions and archive tags go through batch operations, not 60 single writes.
- [PERF-04] Amdahl: the serial fraction is the `wiring → gpuops-1` cut vertex; everything else is scheduled in parallel.
- [OBS-01]/[OBS-05] Expose state: `make worktree-reap` prints the full redundant list (never just a count); `check-all` treats the explicit exit-3 redundancy signal as advisory unless `REAP_STRICT=1`; thresholds live in `mk/lane-maintenance.mk`, not the script.

## Terminology

- **Redundant worktree**: linked worktree whose branch is an ancestor of its parent (`feature/<task>`) or of `main` with zero unique commits (`git cherry` shows no `+`).
- **Branch-only ref**: a `refs/heads/*` branch present in the branch manifest but absent from every `git worktree list --porcelain` branch record; it is never treated as a linked worktree or auto-reaped by the worktree pass.
- **Inventory manifest**: the raw, named-commit record containing `git worktree list --porcelain`, `git for-each-ref refs/heads`, the derived linked/branch-only split, and the generated class table.
- **Expected revision**: the handoff-row or findings-store revision read immediately before a conditional update; a mismatch aborts the batch and forces reclassification.
- **Component**: connected component of the conflict graph whose edges are "changed the same file relative to `main`".
- **Landed**: `git merge-base --is-ancestor <branch> main` exits 0.
- **Parked**: branch tagged `archive/<branch>-<yyyymmdd>`, task row `blocked` with rationale, open findings `deferred`.
- **Parent authority**: the lane registry is authoritative for *ownership*, not for parentage — lane rows carry `branch`, `task_ref` and `status`, but no parent edge, so the parent must be derived. It is derived from the branch-naming convention (`feature/<task>-<sub>` → the longest `feature/<task…>` prefix that exists in the live `refs/heads` inventory; `review/<task>` → `feature/<task>`) and that derivation is treated as an inference, never an authority. Two consequences are load-bearing: a `feature/*` branch whose inferred parent does not exist as a ref is `UNKNOWN`/`NEEDS_REVIEW` and is never silently re-compared against `main`; and the comparison actually used is captured as `(branch, branch_oid, parent, parent_oid)` in one snapshot before any mutation and re-verified inside the delete transaction, so a tip that moved between snapshot and delete aborts rather than deleting against stale evidence. Adding a durable parent edge to the lane row would remove the inference entirely and is the right upstream fix; until it exists, the fail-closed derivation above is the contract.
- **Lane ownership**: a worktree named by a lane row whose `status` is not terminal (`merged`, `closed`) is owned and is never a reap candidate, whatever its containment or cleanliness says. A re-dispatched lane is landed and clean by construction, so those two signals cannot distinguish it from a finished one. If lane ownership cannot be read at all, every linked worktree is `UNKNOWN`; the `--allow-missing-lane-state` opt-out marks every emitted record `lane_verified: false` so a receipt can never report "examined, nothing eligible" when it means "never examined".

## Current State Analysis

The coordinator captures the inventory under the coordinator lock before Slice 1 and again before every mutating slice. No branch/worktree mutation may run while the three Git snapshots are being written. From the orchestrator root, record the exact commit and raw command outputs without editing them:

```bash
INVENTORY_SHA="$(git rev-parse HEAD)"
INVENTORY_DIR=".task-state/LAND-1/inventory/${INVENTORY_SHA}"
mkdir -p "$INVENTORY_DIR"
git show -s --format='%H%n%ad%n%s' --date=iso-strict "$INVENTORY_SHA" > "$INVENTORY_DIR/commit.txt"
git worktree list --porcelain > "$INVENTORY_DIR/worktrees.porcelain"
git for-each-ref --format='%(refname:short)%09%(objectname)' refs/heads > "$INVENTORY_DIR/branches.tsv"
```

The manifest parser joins `worktrees.porcelain` branch records to `branches.tsv`: linked worktrees are the intersection, branch-only refs are `branches.tsv` rows with no linked worktree, and detached worktrees remain an explicit third class. It then evaluates parent reachability, dirtiness, findings, and row state at that same `INVENTORY_SHA`, writes the full names (not only counts), and renders this table from the raw files:

| Class | Linked worktrees | Branch-only refs | Branch refs | Evidence in the named manifest |
| --- | --- | --- | --- | --- |
| Redundant linked worktrees | derived | — | derived | worktree record, parent, `merge-base`/`git cherry`, clean-status result |
| Brief-only or unregistered linked worktrees | derived | — | derived | worktree record plus handoff-row lookup |
| Live linked worktrees | derived | — | derived | worktree record, branch tip, lane row, findings snapshot |
| Stale/parked branch-only refs | — | derived | derived | branch ref, 12-entry disposition (Slice 2), archive tag result |
| Coordination and detached worktrees | derived | — | — | worktree record and task/lane ownership |

Every numeric cell in the rendered table is generated from these two raw Git commands at the recorded `INVENTORY_SHA`; no prior table is an input. The handoff DB snapshot is recorded beside the Git files with its query timestamp and per-row expected revision. `SANDBOX-INVISIBLE:` this planning mirror cannot verify the live task ref population, so it intentionally asserts no static branch/worktree count; the orchestrator must generate and attach the manifest before applying any slice.

The conflict graph is also regenerated from complete branch diffs at the named parent SHA (`git diff --name-only "$INVENTORY_SHA...refs/heads/<branch>"` plus semantic review of shared entry points). A branch is not considered disjoint merely because `merge-tree` is clean.

### Conflict graph (files changed vs `main`, pairwise intersection)

```
gpulife-1-r3-wiring ──3── gpuops-1-reconcile ──1── gpuops-1-c-installer
   (installer, contract doc,         (installer and cloud-init)
    test_gpu_lifecycle_install)

healthobs-1-dedupe ──shared-file intake──▶ gpuops-1
                         (apps/prototype-description-service/api/main.py:
                          both add an include_router line)

evid-1        (isolated: scripts/gpu_burst_evidence.py, export-gpu-evidence.sh, mk/gpu-evidence.mk, tests)
demogate-2    (isolated: infra/oci/demo/*)
guidedfix-2-* (isolated: docs only)
aug-cluster   (isolated from live set; dense internal overlap on scripts/eval_harness)
```

The `wiring — gpuops-1` edge is semantic, not just textual: both branches independently implemented the GID-10001 `groupadd` fix in `scripts/deploy/gpu-lifecycle-install.sh`. `merge-tree` can report clean while `main` would carry **two** group-provisioning paths, so the reconcile node remains the cut vertex of the plan ([GRPH-05]). The healthobs/GPUOPS edge is a hard dependency even when the hunks are clean: `apps/prototype-description-service/api/main.py` has one shared `include_router` resource. Healthobs must land or be explicitly rebased into a GPUOPS intake worktree before GPUOPS verification; it cannot be parallel-coloured away.

Before dispatch and again before each root intake, recompute the complete file-diff intersection at the current parent tip. If a newly observed intersection appears, add a dependency/intake node and recolour before dispatching that lane. `git diff --name-only "$INVENTORY_SHA...refs/heads/<branch>"` is the file list input; semantic shared-entry-point review is mandatory for router, installer, contract, and manifest files.

## Target Outcome

- `git worktree list --porcelain` → exactly the root, the LAND-1 coordination worktree, and lanes with a live dispatch; the manifest records any detached worktree explicitly.
- Every branch in the redundant class deleted; every parked branch has an `archive/` tag.
- Five live components landed on `main` with gate evidence, rows `done` + archived.
- `make task-reap` reports no ambiguous rows; `manage_worktree_lane(list)` returns no planned rows for landed branches, with the exact before/after row counts in the DB readback.
- `make worktree-reap` exists, is tested, and its explicit redundancy signal is exit 3; `check-all` treats that signal as advisory unless `REAP_STRICT=1`.

## Context Loading

- `docs/workbay/rules/graph-theory-heuristics.md` — GRPH-01/05/06.
- `docs/workbay/rules/development-workflow.md` § Pre-Merge Gate, § Dirty Worktree Teardown, when available; this checkout ignores `docs/workbay/rules/**`, so use the `CONTRACT-DELTA:` block instead of planning a tracked edit.
- `scripts/workbay_lifecycle/handlers/task_finish.py:_branch_is_merged` — ancestor-then-`git cherry` merged check whose semantics `scripts/worktree_reap.py` copies (plugin file, not importable from tracked code).
- `~/Development/agentic-protocol-monorepo/scripts/worktree_reachability.py` — prior art: blob-reachability instead of `status --short` as the reap-safety predicate.
- Prior art (semantic search `find_related_prior_work`): `MAINT-worktree-close-wave-20260816`, `MAINT-inflight-board-clearing-20260710`, VLM-5 landing decision #2081 (ff-merge after `handoff_close_check(enforce=True)`).
- GPUOPS-1 continuation `cont-20260907T141614730082Z-e38702a0` — groups A–F, lane test commands, API gotchas.
- Lane test commands: from `manage_worktree_lane(list, task_ref=…)` rows (copied into the manifest section).

## Contract and Boundary Impact

- No service/schema/MCP contract changes from LAND-1 itself.
- `docs/workbay/contracts/gpu-lifecycle.md` has one owner: `gpuops-1-a-contract`. Wiring, `gpuops-1-e-durability`, and all other lanes consume the landed contract and submit any requested change to A through the serialized intake queue; they do not edit the file.
- New make target + script (`worktree-reap`) is repo-local (`scripts/worktree_reap.py`, `mk/lane-maintenance.mk`); it shells out to git only and imports no workbay internals.

## Proposed Solution

### DAG

```
                 ┌──────────────────────────────────────────────────┐
                 │ N0 rows-hygiene [R_DB writer]                    │
                 └──────────────┬─────────────────┬─────────────────┘
                                │                 │
                                ▼                 ▼
                  N1 reap-redundant       N10 park-august
                  (Git-only apply)        (DB/findings batch)

  N12 bleed and N11 worktree-reap tool (TDD) can start after their own preflight.
  N3 healthobs ──gate──ship──finish──▶ N7a GPUOPS shared-file intake
  N4 demogate  ──gate──ship──finish                (not DB-parallel with N0/N10)
  N5 evid-1: refresh ─┬─ lane evid-py  ─┐
                      ├─ lane evid-sh  ─┼─ review ── gate ── ship ── finish
                      └─ lane evid-mk  ─┘

  N2 gpulife-1: lane R2L-01 (on wiring) ── ff gpulife-1 ── gate ── ship ── finish
       │
       │ hard edge (shared installer)                            N6 gpuops B, D, F (parallel work only)
       ▼                                                          │
  N7 gpuops-1 reconcile: merge main, dedupe groupadd ──▶ N6b→N6d→N6f sibling intake queue
       │                                                          │
       └──────────────────────▶ N7a shared-file intake ──▶ A, C, E (serial by owned resource)
                                                               │
                                                               ▼
                  N9 gpuops-1: 7-lens /wb-review-slice ── fixes ── gate ── ship ── finish

Critical path (GRPH-31): N2 → N7 → sibling intake queue → N7a → N9; the DB writer and root merge queue are serial resources, not free DAG width.
```

Colouring ([GRPH-09]): lanes touching `scripts/deploy/gpu-lifecycle-install.sh` / `docs/workbay/contracts/gpu-lifecycle.md` / `scripts/deploy/tests/test_gpu_lifecycle_install.py` (wiring R2L-01, GPUOPS reconcile, A as contract owner, and C as installer owner) share a serialized colour. The healthobs lane and GPUOPS also share `apps/prototype-description-service/api/main.py`, so N7a is an explicit intake edge. B/D/F may implement in parallel from a common parent, but their intakes are queued one at a time; E consumes B's intent output and A's contract rather than owning either file.

### Landing protocol (applied identically to every component; each step idempotent)

All root-ref mutations and handoff DB writes run under one coordinator lock. Lane implementation and review work may run in parallel only after complete-diff coloring; `make lane-intake`, branch landing, DB batches, ancestry recomputation, and post-merge evidence are serialized. Every mutation records `(task_ref, lane_id, old_sha, new_sha, expected_db_revision, command, exit_code, timestamp)` in the handoff evidence.

1. At the current parent tip, classify every sub-lane and capture its expected branch SHA, parent SHA, clean status, and handoff-row revision. A missing parent, missing branch, changed tip, dirty worktree, or new shared-file edge is `NEEDS_REVIEW`; it is never silently treated as redundant or ready.
2. For a sibling intake, acquire the coordinator lock and run `make lane-intake TASK=<task-ref> LANE=<lane>` from the orchestrator root. Its scratch-worktree cherry-pick and lane tests must pass before the parent advances. If it conflicts because a sibling already advanced the parent, abort the scratch intake, run `make lane-refresh TASK=<task-ref> LANE=<lane>` for that lane, rerun its required tests and close check at the refreshed SHA, then retry the intake under the lock.
3. Refresh the component from the exact latest `main` with a merge (not a rebase when the branch carries review provenance), then recompute the complete diff and the candidate SHA. For LAND-1 itself, this refresh is an explicit prerequisite immediately before Slice 5.
4. Run the component's local verification from the candidate checkout. Do not record evidence against a moving branch: record the command, exit code, and exact `CANDIDATE_SHA` only after the command completes.
5. Run the remote gate in the foreground under a bounded deadline, for example `set -o pipefail; timeout --kill-after=30s 3600s make check-remote 2>&1 | tee .task-state/LAND-1/gates/<CANDIDATE_SHA>.log`. Require the `timeout` command to exit 0, require the log to exist, and require it to name `CANDIDATE_SHA`; a timeout, non-zero exit, missing log, or SHA mismatch stops the landing. No `nohup`, `disown`, or detached gate is accepted.
6. After remote completion, record one `test_result` at the unchanged `CANDIDATE_SHA`; update findings with each resolution's `verified_commit_sha` and rationale; and record the slice-complete decision. Lint-only findings are deferred only to a named next wave with rationale.
7. Run `handoff_close_check(enforce=True)` from the unchanged candidate checkout and require the returned/evidenced head SHA to equal `CANDIDATE_SHA`. This is the final enforced close check after all tests and findings updates, not an earlier preflight check.
8. Still under the coordinator lock, merge the candidate into `main` (`--ff-only` where possible, otherwise the declared merge strategy), verify `git merge-base --is-ancestor <candidate> main`, verify the resulting `main` tip, and only then close landed lane rows via the DB coordinator using their expected revisions and read back the exact status. `wb ship` alone is not trusted.
9. For cleanup, `git worktree remove` and `git branch -d` are separate idempotent Git operations; record each result, rerun classification after either partial failure, and render `render_handoff(kind='dashboard')` only after the readback.

The reaper is Git-only. `land-1-hygiene` owns handoff-row closure and findings updates; for redundant rows it performs the conditional close after the successful pre-reap classification/cleanliness preflight and before the reaper apply, then reads back the row revision. The reaper never calls the DB. If the later Git apply fails, hygiene compensates the row state from a fresh classification instead of claiming completion.

Recovery for partial states is explicit: (a) a lock conflict or failed DB conditional write performs no Git mutation and retries only after a fresh manifest; (b) a successful pre-reap close followed by an apply failure reclassifies and reopens/marks the row blocked with the failure evidence; (c) a failed worktree removal preserves the branch and row audit, and no branch deletion is attempted; (d) a removed worktree with failed branch deletion retains and tags the branch, then retries deletion only after expected-tip revalidation; (e) if both Git operations succeed but DB readback fails, do not repeat deletion—read Git state, reconcile the row with its expected revision, and stop if the branch moved or was recreated. A missing parent always remains `NEEDS_REVIEW` until an operator supplies a new parent.

## Files and Surfaces to Change

`scripts/workbay_lifecycle/` and `Makefile.d/` are workbay-plugin output (gitignored, `.gitignore:135`, `:138`); nothing added there lands on `main`. The reaper lives on tracked surfaces:

- `scripts/worktree_reap.py` (new) — `classify(repo) -> list[WorktreeRecord]`, `apply(records, *, dry_run)`; classification contract = `task_finish._branch_is_merged` semantics (`git merge-base --is-ancestor <branch> <parent>` OR every `git cherry <parent> <branch>` line is `-`), dirtiness = `git status --porcelain` non-empty (a dirty record is never reaped). A missing parent is `NEEDS_REVIEW`, not redundant; branch-only refs are emitted separately and are not implicitly reaped; apply takes a repository lock and revalidates the expected branch tip, parent tip, worktree path, and clean status immediately before each mutation. A failed worktree removal leaves the branch untouched; a removed worktree with a failed branch delete is recorded for safe retry after tip revalidation. The reaper is Git-only and never closes handoff rows or writes findings.
- `scripts/test_worktree_reap.py` (new) — added to the `test-scripts` list in `Makefile`.
- `mk/lane-maintenance.mk` — `worktree-reap` (dry run, JSON + table) returns exit 3 when redundancy is found; `worktree-reap-check` exposes the same redundancy signal, while `check-all` maps that signal to advisory exit 0 unless `REAP_STRICT=1` (unexpected errors remain failures). `make context` is plugin-owned; a warning there is filed as an upstream request, not implemented here.
- `docs/workbay/rules/**` — no tracked edit is planned: this directory is gitignored in this checkout. The operator applies the exact `CONTRACT-DELTA:` wording below out-of-band to `docs/workbay/rules/development-workflow.md`.
- `docs/workbay/constitution.md` + `CLAUDE.md` — new guard rg-019 (sub-lane worktrees are reaped in the same slice that integrates them).
- `docs/tasks/v0.5.0/lanes/*` — the 5 orphan briefs, committed on `feature/land-1`.

### CONTRACT-DELTA: Landing Protocol (operator-applied out-of-band)

`docs/workbay/rules/development-workflow.md` is absent/ignored in this checkout, so the following exact wording is printed for an operator to apply there; this plan does not edit `docs/workbay/rules/**`:

> **Landing Protocol**
>
> 1. Reclassify every sub-lane at the current parent tip. Require the expected branch SHA, parent SHA, clean worktree, and handoff-row revision; a missing parent or changed tip blocks the operation.
> 2. Intake one lane at a time under the coordinator's root-ref lock. Use a scratch worktree, cherry-pick the lane commits, and run the lane's required verification before advancing the parent.
> 3. Refresh the component from the exact latest `main` and recompute its complete file-diff intersection before testing.
> 4. Run local verification and record `test_result` at the unchanged candidate SHA.
> 5. Run the remote gate in the foreground under a bounded timeout. Require exit 0, a retained log, and the candidate SHA in that log; detached gates are not evidence.
> 6. Update findings and record the slice-complete decision with the candidate SHA and rationale.
> 7. Run `handoff_close_check(enforce=True)` after all tests and findings updates; require its evidenced head SHA to equal the candidate SHA.
> 8. Merge the candidate under the root-ref lock, verify the resulting `main` ancestry and tip, then close rows through the handoff coordinator with expected-revision readback. Reclassify after any partial Git operation and never force-remove a dirty worktree.

## Related Files

- `scripts/workbay_lifecycle/handlers/task_finish.py` — `_branch_is_merged`, worktree-remove/branch-delete ordering (read-only reference).
- `config/lane-orchestration/GPUOPS-1.json`, `EVID-1.json`, `GPULIFE-1.json` — owned_paths for the fix lanes (owned_paths override in the brief is inert; edit the manifest).
- `scripts/vm/reap-lane.sh` — VMREAP-3 follow-up target (unstarted; not in this plan's DAG).

## Verification Strategy

- Tool: `python3 -m pytest scripts/test_worktree_reap.py -q` — fixtures build a temp repo with (a) ancestor sub-lane, (b) sub-lane with one unique commit, (c) dirty ancestor, (d) review branch == main, (e) sub-lane rebased onto parent (SHAs differ, `git cherry` all `-`); assert `classify` returns REDUNDANT for (a)/(d)/(e), LIVE for (b), DIRTY for (c), and that `apply` removes only REDUNDANT. Mutation check: drop the `git cherry` fallback → (e) fails.

The five fixtures above cover the happy classification set only. Idempotence and safe teardown are separately claimed and separately tested, each with a deterministic fixture and an injected failure rather than an observed one:

- **(f) missing parent** — sub-lane whose derived parent ref was deleted: `UNKNOWN`, never compared against `main`, never reaped.
- **(g) branch-only ref** — a `refs/heads` entry with no worktree record: absent from the class table entirely, and untouched by `apply`.
- **(h) concurrent run** — a second reaper holding the repository lock: the second invocation refuses with `ReapLockError` and mutates nothing; assert the first run's removals are unaffected.
- **(i) branch tip advances between classification and delete** — monkeypatch the ref to move inside the delete transaction: the compare-and-delete rejects, the branch survives, and the run reports the abort rather than exiting 0.
- **(j) half-failed removal** — inject an error from `git worktree remove` and, separately, from `git branch -d` after a successful removal: assert no branch is deleted when its worktree removal failed, and that re-running the reaper converges rather than compounding the partial state.
- **(k) active lane** — a worktree named by a non-terminal lane row while landed and clean: `LIVE`, survives `--apply`. Mutation check: ignore lane ownership → (k) fails.
- **(l) unreadable lane registry** — the ownership probe raises: every linked worktree is `UNKNOWN`, `--apply` removes nothing, and `--allow-missing-lane-state` emits `lane_verified: false` on every record.
- **(m) harness scratch** — a `.task-state/*.stamp` name no allowlist enumerates does not block a reap, while `.task-state/remote-exec-*/turn.patch` still does.

`--apply` is not enabled by the success criterion until (f)–(m) are green; each must refuse or report its case rather than proceeding.
- Inventory: attach the `INVENTORY_SHA`, `commit.txt`, `worktrees.porcelain`, `branches.tsv`, generated linked/branch-only manifest, and DB snapshot. Re-run the two named Git commands at each mutating-slice boundary and assert that every rendered count and every branch disposition is derivable from those raw files.
- Landing: per component, `git merge-base --is-ancestor <branch> main` == 0 and a fresh `git worktree list --porcelain` contains no removed path; `handoff_close_check(enforce=True)` JSON is archived with the exact candidate SHA after the remote gate and findings update.
- Hygiene: `make task-reap` → no ambiguous rows; the DB readback includes exact before/after counts and expected revisions. The worktree reaper's explicit redundancy signal is exit 3; `check-all` is exit 0 for that advisory signal unless `REAP_STRICT=1`.
- Reviews: adversarial `/wb-review-slice` on gpuops-1 (7 lenses: state-machine, failure-modes, boundary-contract, operator-ux, naming-truth, test-integrity, canon) — 1 local + 6 remote; on evid-1 (3 lenses: failure-modes, test-integrity, boundary-contract).
- Gate: foreground `timeout --kill-after=30s 3600s make check-remote` per component, with exit 0, retained log, and candidate-SHA assertions before any `test_result` or merge.

## Slice Delivery

### Slice 1: Redundancy reaper tool (TDD) and first reap

**Goal**: `make worktree-reap` classifies every linked worktree from the named inventory and, with `--apply`, removes only proven-redundant clean Git worktrees and their branches. Handoff-row closure is a separate, pre-reap coordinator step owned by `land-1-hygiene`; the reaper never closes rows.
**Proof**: unit tests above; the dry run's full JSON/table output matches the inventory manifest, missing-parent and branch-only records are not applied, and `--apply` records lock acquisition, expected-tip revalidation, each Git mutation, and readback. A redundancy result exits 3. Partial removal is replay-safe under the recovery protocol. Commit the orphan briefs; land the `guidedfix-2-*` briefs as one docs commit on `feature/land-1`, then process those linked worktrees through the same pre-reap row closure and Git-only reaper flow.

### Slice 2: Handoff-row hygiene and August parking

**Goal**: no ambiguous rows; main-target rows closed; August cluster parked.
**Proof**: `make task-reap` shows no ambiguous rows; the junior-agent classification of the current ambiguous-row snapshot is recorded as one decision; the main-target batch and August findings batch use expected revisions and exact before/after readback. The following is the required 12-entry disposition manifest for the named August inventory (regenerate it if the raw branch set differs):

| Branch ref | Disposition | Handoff status/rationale |
| --- | --- | --- |
| `vlm-6` | task `VLM-6`, archive and keep | `blocked`; parked, re-plan against current `main` |
| `fir-12` | task `FIR-12`, archive and keep | `blocked`; parked, re-plan against current `main` |
| `descqual-2` | task `DESCQUAL-2`, archive and keep | `blocked`; parked, re-plan against current `main` |
| `corpus-1` | task `CORPUS-1`, archive and keep | `blocked`; parked, re-plan against current `main` |
| `vlm6-lex` | task `VLM6-LEX`, archive and keep | `blocked`; parked, re-plan against current `main` |
| `cmap-1` | task `CMAP-1`, archive and keep | `blocked`; parked, re-plan against current `main` |
| `fir12-r7-int` | branch-only, archive and keep | no retained task row; branch-only ref is explicitly retained for later triage |
| `lane/l11-rescue` | branch-only, archive and keep | no retained task row; branch-only ref is explicitly retained for later triage |
| `evalsurf-1` | branch-only, archive and keep | no retained task row; branch-only ref is explicitly retained for later triage |
| `defwave-1-d1-lintratchet` | branch-only, archive and keep | no retained task row; branch-only ref is explicitly retained for later triage |
| `review/defwave-1-d1` | branch-only, archive and keep | no retained task row; branch-only review ref is explicitly retained for later triage |
| `ocirv-1-rev-ops` | branch-only, archive and keep | no retained task row; branch-only ref is explicitly retained for later triage |

For each row, resolve `refs/heads/<branch>` to `BRANCH_SHA` and use `TAG=archive/<branch>-<yyyymmdd>`. If `TAG` exists, accept it only when `git cat-file -t "$TAG"` is `tag` and `git rev-parse "$TAG^{commit}"` equals `BRANCH_SHA`; otherwise fail without mutation. If it does not exist, create an annotated tag at `BRANCH_SHA` with owner, date, and revisit metadata in the tag message. Require one tag and one non-empty status/rationale for every manifest row, defer open findings with verification evidence for task rows, and assert the exact disposition counts after parking. Branch deletion remains operator-gated; the default is tag-and-keep.

### Slice 3: Land the four small components

**Goal**: GPULIFE-1, HEALTHOBS-1, DEMOGATE-2, EVID-1 on `main`.
**Proof**: per-component landing protocol with the final enforced close check and gate evidence at the exact merge candidate SHA. GPULIFE-1 needs one remote lane (R2L-01 on `gpulife-1-r3-wiring`, brief already committed at `09fe6345a`). EVID-1 needs three remote fix lanes split by owned file, then a 3-lens review. HEALTHOBS-1 and DEMOGATE-2 need only gate + ship. After healthobs lands, the GPUOPS coordinator must intake/recompute the shared `apps/prototype-description-service/api/main.py` diff before any GPUOPS verification.

### Slice 4: GPUOPS-1 reconcile, fix, review, land

**Goal**: one group-provisioning path in the installer; all assigned findings closed or explicitly dispositioned; adversarial review green; landed.
**Proof**: after N2 lands, `git merge main` into `feature/gpuops-1`; a reconcile lane removes the duplicate `groupadd` path and keeps the stricter guard (`test_every_supplementary_group_is_a_name_the_installer_resolves` plus wiring's `216/GROUP` preflight assertion both pass). B/D/F may implement from the common parent, but their lane intakes are serialized and each is retested at the current parent SHA. N7a then consumes the landed healthobs router change and recomputes complete diffs. A owns the contract; C follows the reconcile installer intake; E consumes B's intent output and A's contract. Run the 7-lens review, fixes, final bounded gate, final close check, ship, and finish.

### Slice 5: Make it not recur

**Goal**: `check-all` fails on redundant worktrees; landing protocol documented; guard recorded.
**Proof**: explicit `make worktree-reap`/`worktree-reap-check` reports exit 3 for a fixture with redundancy; `check-all` maps that signal to advisory exit 0 unless `REAP_STRICT=1`, and the converged repo has no redundancy. Before this slice, under the root-ref lock, run `git -C <LAND1_WORKTREE> merge --no-ff main`, capture `LAND1_SHA=$(git -C <LAND1_WORKTREE> rev-parse HEAD)`, rerun LAND-1 local verification from that worktree, run the foreground bounded remote gate, update findings, and run `handoff_close_check(enforce=True)` with evidenced head `LAND1_SHA`. Only then merge `feature/land-1` into `main`, verify the resulting `main` tip and ancestry, and render state. The operator applies the `CONTRACT-DELTA:` Landing Protocol out-of-band because `docs/workbay/rules/**` is gitignored here; rg-019 in constitution + `CLAUDE.md` remains a separate tracked sync; `make check-all` is green; upstream request filed for a `make context` warning.

## Lane Decomposition (Multi-Agent)

Lanes are dispatched under their **owning** task_ref (findings and gate audit stay on the right ref — the GATE-01 lesson). LAND-1 owns Slices 1, 2, 5 and the coordination of 3–4.

### Lanes

| Lane | Task | Branch | Owned paths (repository-relative) | Dependencies | Working directory and required test | Dispatch posture |
| --- | --- | --- | --- | --- | --- | --- |
| gpulife-1-r3-wiring (R2L-01) | GPULIFE-1 | feature/gpulife-1-r3-wiring | `scripts/deploy/gpu-lifecycle-install.sh`; `scripts/deploy/tests/test_gpu_lifecycle_install.py` | none; shares installer colour with GPUOPS reconcile/C | repo root; `LC_ALL=C python3 -m pytest scripts/deploy/tests/test_gpu_lifecycle_deploy_wiring.py scripts/deploy/tests/test_gpu_lifecycle_install.py scripts/test_deploy_workflow_gate.py -q` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| evid-1-py | EVID-1 | feature/evid-1-py | `scripts/gpu_burst_evidence.py`; `scripts/test_gpu_burst_evidence.py` | EVID-1 refresh | repo root; `python3 -m pytest scripts/test_gpu_burst_evidence.py -q` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| evid-1-sh | EVID-1 | feature/evid-1-sh | `scripts/deploy/lib/export-gpu-evidence.sh`; `scripts/deploy/tests/test_export_gpu_evidence_shell.py`; `scripts/deploy/tests/test-export-gpu-evidence.sh` | EVID-1 refresh | repo root; `python3 -m pytest scripts/deploy/tests/test_export_gpu_evidence_shell.py -q` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| evid-1-mk | EVID-1 | feature/evid-1-mk | `mk/gpu-evidence.mk`; `docs/runbooks/gpu-evidence-capture.md` | EVID-1 refresh | repo root; `make -n gpu-evidence-export` followed by the shell test named by the lane brief | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| gpuops-1-b-intent | GPUOPS-1 | feature/gpuops-1-b-intent | `infra/oci/gpu_lifecycle/intent.py` `[new; B owns creation]`; `infra/oci/gpu_lifecycle/tests/test_intent.py` `[new; B owns creation]`; `infra/oci/gpu_lifecycle/tests/test_intent_controller.py` `[new; B owns creation]` | common GPUOPS parent | repo root; `python3 -m pytest infra/oci/gpu_lifecycle/tests/test_intent.py infra/oci/gpu_lifecycle/tests/test_intent_controller.py -q` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| gpuops-1-d-observe | GPUOPS-1 | feature/gpuops-1-d-observe | `infra/oci/gpu_lifecycle/reaper.py`; `apps/prototype-description-service/scene/application/gpu_intent.py` `[new; D owns creation]`; `apps/prototype-description-service/scene/application/gpu_state.py`; `apps/prototype-description-service/scene/interface_adapters/http/routers/gpu.py` `[new; D owns creation]`; `apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py`; `apps/prototype-description-service/scene/tests/test_gpu_router.py` `[new; D owns creation]` | common GPUOPS parent; intake after B if consuming intent | repo root for `python3 -m pytest infra/oci/gpu_lifecycle/tests -q`; `apps/prototype-description-service/` for `python3 -m pytest scene/tests/test_gpu_router.py -q` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| gpuops-1-f-process | GPUOPS-1 | feature/gpuops-1-f-process | `scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py`; `docs/runbooks/oci-instance-state-and-cost.md`; `docs/tasks/v0.5.0/lanes/GPUOPS-1-_common.md` `[new; F owns creation]`; `config/lane-orchestration/GPUOPS-1.json` `[workspace-local manifest; generated, not committed by F]` | common GPUOPS parent | repo root; `LC_ALL=C python3 -m pytest scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py -q` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| gpuops-1-e-durability | GPUOPS-1 | feature/gpuops-1-e-durability | `infra/oci/gpu_lifecycle/tests/test_intent_durability.py` `[new; E owns creation]`; consumes `infra/oci/gpu_lifecycle/intent.py` and `docs/workbay/contracts/gpu-lifecycle.md` without editing either | after B; after A's contract is landed | repo root; `python3 -m pytest infra/oci/gpu_lifecycle/tests/test_intent.py infra/oci/gpu_lifecycle/tests/test_intent_controller.py infra/oci/gpu_lifecycle/tests/test_intent_durability.py -q` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| gpuops-1-reconcile | GPUOPS-1 | feature/gpuops-1 | `scripts/deploy/gpu-lifecycle-install.sh`; `scripts/deploy/tests/test_gpu_lifecycle_install.py` | after GPULIFE-1 wiring; cut vertex before C/A/E | repo root; `LC_ALL=C python3 -m pytest scripts/deploy/tests/test_gpu_lifecycle_deploy_wiring.py scripts/deploy/tests/test_gpu_lifecycle_install.py -q` plus `shellcheck scripts/deploy/gpu-lifecycle-install.sh` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| gpuops-1-a-contract | GPUOPS-1 | feature/gpuops-1-a-contract | `docs/workbay/contracts/gpu-lifecycle.md` `[sole contract owner]` | after reconcile; E consumes the result | repo root; `make lint-task-plans` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| gpuops-1-c-installer | GPUOPS-1 | feature/gpuops-1-c-installer | `scripts/deploy/gpu-lifecycle-install.sh`; `infra/oci/cloud-init.yaml`; `apps/prototype-description-service/scene/tests/test_gpu_lifecycle_install_script.py` | after reconcile and its intake; serialized with installer colour | repo root; `LC_ALL=C python3 -m pytest scripts/deploy/tests/test_gpu_lifecycle_install.py apps/prototype-description-service/scene/tests/test_gpu_lifecycle_install_script.py -q` and `shellcheck scripts/deploy/gpu-lifecycle-install.sh` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| land-1-reap-tool | LAND-1 | feature/land-1 | `scripts/worktree_reap.py`; `scripts/test_worktree_reap.py`; `mk/lane-maintenance.mk`; `Makefile` test-scripts list | N0 preflight before apply | repo root; `python3 -m pytest scripts/test_worktree_reap.py -q` | `codex-remote` / `gpt-5.6-luna` / `reasoning_effort=high` |
| land-1-hygiene | LAND-1 | feature/land-1 | handoff DB only; no repository file | sole writer for rows/findings; serializes with N10 | orchestrator root; `make task-reap` plus DB before/after readback | local + junior classification; no remote dispatch |

In the dispatch-posture column, `codex-remote` is the mandated routing label. The checked-in MCP backend flag is selected from the runtime's advertised backend list (normally `codex-subagent` for the Codex bridge); the model and `reasoning_effort` fields remain explicit and are recorded with the lane dispatch.

### Merge Order

1. Capture the named Git/DB inventory. Run N0's DB preflight and expected-revision readback before N1's Git-only apply; N10 shares the same DB/findings resource with N0 and is queued after N0, never parallel.
2. While the DB writer is idle, N11 (reaper tool TDD), N12 (root bleed), N3 (healthobs), N4 (demogate), N5 (EVID lanes), and N2 (wiring lane) may implement/review in parallel subject to complete-diff coloring. Their root intakes do not run in parallel.
3. After N2 lands, run N7 reconcile. B/D/F may continue implementation from the common GPUOPS parent, but each sibling goes through a distinct queued intake: acquire the coordinator lock, `make lane-intake TASK=GPUOPS-1 LANE=<lane>`, run the lane's tests and close check at the new parent tip, then release the lock. A conflict triggers `make lane-refresh` plus fresh tests before retry.
4. After healthobs lands, N7a performs the `apps/prototype-description-service/api/main.py` shared-file intake and recomputes the complete conflict graph. Only then may A, C, and E run in their declared serial order; A is the sole contract owner, C follows the installer reconcile, and E consumes B/A outputs.
5. N9 GPUOPS review/fixes, the bounded gate, final close check, and root merge run through the same single intake queue. Each root merge recomputes ancestry and records fresh evidence before the next candidate is admitted.
6. Before Slice 5, refresh `feature/land-1` from the exact latest `main`, rerun all local/remote/close-check evidence at that SHA, then intake it and verify the resulting `main` tip. Slice 5 lands last so `worktree-reap-check` runs against the converged state.

### Manifest

`config/lane-orchestration/` is gitignored workspace-local state (`.gitignore:189`), not a versioned surface. Each manifest is `{task_ref, lanes: {lane_id: {...}}, depends_on, merge_order, downstream, routing, default_done_definition}`. Existing lane ids: GPUOPS-1 `gpuops-1-r1-intent-reader/r2-service-parity/r3-installer-fencing/r4-reaper-start` (landed, rows still `planned`); EVID-1 `evid-1-evidence` (→ `feature/evid-1`), `evid-1-rev`; GPULIFE-1 `gpulife-1-rev-a/rev-d/fix/r3-wiring/r3-preflight`.

Per new lane, in order: (1) close or reclassify stale rows through `land-1-hygiene` with an expected revision; (2) `git worktree add ../context-alt-text-monorepo-<lane> -b feature/<lane> feature/<parent>`; (3) `manage_worktree_lane upsert` with `task_ref`, `lane_id`, `branch`, `worktree_path`, `owned_paths`, `test_command`; (4) add `lanes[lane_id]` and the declared `depends_on` edges (`gpuops-1-e-durability → gpuops-1-b-intent`, `gpuops-1-a-contract → gpuops-1-reconcile`, `gpuops-1-c-installer → gpuops-1-reconcile`, plus the healthobs → GPUOPS shared-file intake) to the workspace manifest and validate with `load_manifest`; (5) open the lane and generate its brief with the checked-in command surface:

```bash
make lane-open TASK=<task-ref> LANE=<lane> ENTER_SHELL=0
scripts/worktree-lane brief --orchestrator-root "$(git rev-parse --show-toplevel)" \
  --task-ref <task-ref> --lane-id <lane> --branch feature/<lane> \
  --worktree-path ../context-alt-text-monorepo-<lane> \
  --owned-path <repo-relative-path> --test-command '<command>' \
  --definition '<done definition>'
```

`make lane-open` already invokes the `scripts/worktree-lane brief` step; the explicit form above is the supported fallback when the brief must be regenerated. Set the runtime posture separately with the supported fields, then send the human assignment with the supported lane-dispatch command:

```bash
workbay-handoff-mcp dispatch-lane-work --task-ref <task-ref> --lane-id <lane> \
  --backend codex-subagent --model gpt-5.6-luna --reasoning-effort high
make lane-dispatch TASK=<task-ref> LANE=<lane> SUBJECT="<lane subject>" \
  MESSAGE="<objective, owned paths, dependencies, and required tests>"
```

Workers poll with `make lane-inbox TASK=<task-ref> LANE=<lane>` and submit through the existing lane handoff flow. There is no `dispatch_wave`, no `brief=` parameter on `dispatch_lane_work`, and no plan-level detached dispatch. Manifest alone is not a lane; a brief payload `owned_paths_override` is inert.

LAND-1's own two lanes run locally on `feature/land-1` and need no task manifest, but they still use the same coordinator lock for DB writes and root-ref intake.

### Orchestration Mode

The coordinator starts each ready lane with `make lane-open TASK=<task-ref> LANE=<lane> ENTER_SHELL=0`, sets `--backend`, `--model`, and `--reasoning-effort` with `workbay-handoff-mcp dispatch-lane-work`, and sends the brief with `make lane-dispatch`. A brief names the lane's exact owned paths, working directory, dependencies, required commands, and fresh finding-id range. The only bounded wait in this plan is the foreground remote gate; worker dispatch is not a detached gate and root merges are not concurrent.

All root merges/intakes use one queue protected by the repository lock, for example `flock "$(git rev-parse --git-dir)/LAND-1-main-merge.lock" -- make lane-intake TASK=<task-ref> LANE=<lane>`. After each intake, the coordinator recomputes `git merge-base --is-ancestor`, complete file diffs, local tests, findings, and `handoff_close_check(enforce=True)` at the exact candidate SHA before admitting the next root mutation.

## Consolidated Checklist

- [ ] S1 reaper tool tests red → green; the generated manifest's redundant linked-worktree class is removed only after hygiene preflight; branch-only refs remain on their explicit disposition path; orphan briefs committed
- [ ] S2 every current ambiguous row is classified and closed/reclassified through one DB writer; the 12-entry August disposition is tagged, statused, and counted from the named manifest; open findings on parked task rows are deferred with rationale
- [ ] S3 GPULIFE-1, HEALTHOBS-1, DEMOGATE-2, EVID-1 landed with gate evidence and rows archived
- [ ] S4 GPUOPS-1 reconciled, sibling intakes serialized, shared healthobs/API edge rechecked, findings closed, 7-lens review, landed
- [ ] S5 exact latest `main` merged into `feature/land-1` before final verification; `worktree-reap-check` in `check-all` + `CONTRACT-DELTA:` printed for the ignored rules path + rg-019 synced; `make check-all` green
- [ ] Every landing decision recorded in handoff; dashboard re-rendered after each

## Context and Ownership

- [ ] Loaded the available graph rules, the pre-merge/dirty-worktree guidance when present, and the GPUOPS-1 continuation packet before editing; if `docs/workbay/rules/**` is unavailable, recorded that it is ignored and used the `CONTRACT-DELTA:` block.
- [ ] Contract touched: `docs/workbay/contracts/gpu-lifecycle.md` (sole owner `gpuops-1-a-contract`; all other lanes consume it). No other boundary changes.

### Checklist for Slice 1: Redundancy reaper tool (TDD) and first reap

- [ ] `scripts/test_worktree_reap.py` fixtures (a)–(e) written first and red
- [ ] `scripts/test_worktree_reap.py` fixtures (f)–(m) — missing parent, branch-only, lock contention, tip advance, half-failed removal, active lane, unreadable registry, harness scratch
- [ ] `scripts/worktree_reap.py` classify/apply green; `mk/lane-maintenance.mk` targets; `test-scripts` entry
- [ ] Dry run matches the named inventory table; hygiene closes/reclassifies rows before Git apply; apply records lock/tip revalidation and removes only the redundant linked-worktree class
- [ ] Missing-parent and branch-only records are visible and not applied; exit 3/advisory `check-all`/`REAP_STRICT=1` semantics verified
- [ ] `guidedfix-2-*` briefs landed as docs; those worktrees/branches removed

### Checklist for Slice 2: Handoff-row hygiene and August parking

- [ ] Ambiguous rows classified (MERGED / BRANCH_GONE / BRANCH_EXISTS / PLANNING_ONLY) and closed per class
- [ ] Main-target rows `plan-done` in one conditional batch with exact before/after readback
- [ ] Every row in the 12-entry branch disposition has a deterministic annotated tag at its recorded SHA and a status/rationale; parked task findings are deferred with `verification_evidence`
- [ ] `make task-reap` shows no ambiguous rows and the readback matches the manifest snapshot

### Checklist for Slice 3: Land the four small components

- [ ] GPULIFE-1: R2L-01 lane green, ff to wiring, bounded gate, final close check at candidate SHA, ship, finish
- [ ] HEALTHOBS-1: ff to dedupe, bounded gate, final close check at candidate SHA, ship, finish
- [ ] DEMOGATE-2: bounded gate, final close check at candidate SHA, ship, finish
- [ ] EVID-1: refresh from main, three fix lanes, 3-lens review, bounded gate, final close check at candidate SHA, ship, finish

### Checklist for Slice 4: GPUOPS-1 reconcile, fix, review, land

- [ ] `feature/gpuops-1` merged with main after GPULIFE-1 lands; reconcile lane leaves one group-provisioning path
- [ ] Lanes B, D, F implement in parallel but intake one at a time with conflict/retest evidence; A owns the contract, C follows reconcile, E consumes B/A; all have fenced finding-id ranges
- [ ] Healthobs `apps/prototype-description-service/api/main.py` change is serially intaken and complete-diff coloring is recomputed before GPUOPS verification
- [ ] 7-lens adversarial review (1 local + 6 remote) with codemap/prior-art packets; fixes; gate; ship; finish

### Checklist for Slice 5: Make it not recur

- [ ] `worktree-reap-check` in `check-all` with advisory exit 3 and `REAP_STRICT=1` enforcement; upstream request filed for a `make context` warning
- [ ] Exact latest `main` merged into `feature/land-1`; local tests, foreground bounded remote gate, findings update, and final enforced close check rerun at the refreshed SHA; resulting `main` tip verified
- [ ] `CONTRACT-DELTA:` Landing Protocol supplied for out-of-band application to ignored `docs/workbay/rules/**`; rg-019 in constitution + `CLAUDE.md` same commit
- [ ] `make check-all` green; LAND-1 gate; ship; finish

## Review Readiness

- `/wb-review-plan` on this document before Slice 3 dispatch (planning review, 2 passes: 1 local, 1 remote against canon). `make plan-analyze` is broken in this workspace (`skill 'plan-draft' has no live command_id in portable_commands.json` — upstream workbay-plugin defect); triage ran through the planning-review skill directly.
- Each landed component: branch review already recorded on its ref; LAND-1 adds only gate evidence.

## Stretch Goals

- VMREAP-3 (VM orphan-lane sweep) as an extra independent lane once the VM `UserTasksMax` operator item is done.
- Cherry-pick `cmap-1` / `evalsurf-1` single commits onto fresh branches if still wanted (conflicts are small).

## Success Criteria

- The final named inventory has no redundant linked worktree; every branch-only ref has an explicit disposition; the linked-worktree set is root plus active dispatches.
- `make task-reap` → no ambiguous rows; no `planned` lane rows for landed branches; DB readbacks match expected revisions.
- Five components on `main`, each with `handoff_close_check(enforce=True)` evidence and `check-remote` green at the shipped SHA.
- `make worktree-reap` exists with tests and explicit redundancy exit 3; `make check-all` includes advisory `worktree-reap-check` and honors `REAP_STRICT=1`.
