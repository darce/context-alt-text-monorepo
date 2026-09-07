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

Converge 28 worktrees / 50 branches / 77 live handoff rows to: root on `main` + only lanes that are actively executing. Land the five live components (GPULIFE-1, HEALTHOBS-1, DEMOGATE-2, EVID-1, GPUOPS-1) through the pre-merge gate, reap everything that is already an ancestor of its parent, park the August eval-harness cluster under archive tags, and ship the repo-side tool that stops this from recurring.

## Problem Statement

Sub-lane worktrees are integrated into their parent branch but never torn down; review worktrees outlive the review; lane rows stay `planned` after the branch has landed; main-target MAINT rows never get `plan-done`. Result: 20 worktrees whose branch is a strict ancestor of its parent (zero unique commits), 45 main-target rows that make every cwd-resolved orchestrator call return `Ambiguous active task`, and a landing procedure (`wb ship`) whose merge step is a known no-op (`claude_defect_wb_ship_merge_step_is_a_noop`). Git is the source of truth for "landed"; the DB and the filesystem have drifted from it.

## Constraints

- Pre-Merge Gate Rule: every merge to `main` needs `handoff_close_check(enforce=True)` green, fresh `test_result` at HEAD, zero open findings (or explicit defer/wontfix with rationale), slice-complete decision.
- rg-017: never force-remove a dirty worktree. Every worktree in the reap set was verified `git status --short` empty on 2026-09-07; re-verify at apply time.
- Never start/stop the live GPU. `acx-gpu-burst` stays STOPPED; no operator-gated deployment steps are executed by this plan.
- Implementation and grunt work runs on `codex-remote` / `gpt-5.6-luna` / effort `max` (mandated pin). Local junior subagents only for classification and fetching. Local host runs `tsc`/`vitest`/`pytest` verification and the remote gate.
- Worktree rule: root stays on `main`; delete merged branches after `task-finish`.
- Peer-session dirty files in root (`vite.config.ts`, `.codex/config.toml`, `.mcp.json`, `.vscode/mcp.json`) are not touched.

## Workflow Principles

- Model the landing as a DAG and topological-sort it ([GRPH-01]); partition by connected components before ordering ([GRPH-06]); name the cut vertex ([GRPH-05]); colour the file-conflict graph so same-file lanes never run concurrently ([GRPH-09]); list-schedule ready nodes by longest remaining chain ([GRPH-31]).
- [RES-07] Steady-state reclaimer: every mechanism that creates a worktree ships with a same-rate purge (`make worktree-reap`, same release).
- [RES-06]/[RES-02] Fail fast, bounded waits: classify before mutating; refuse to reap anything not proven redundant by `merge-base --is-ancestor`; every remote dispatch carries `timeout_seconds`.
- [RES-14] Handshaking: each component lands independently behind its own gate; a red gate on one never blocks siblings.
- [RES-01]/[API-02] Idempotent steps: every landing/reap step is re-runnable; nothing double-applies on retry.
- [RES-10] Fencing: one owner per branch at a time — lane locks respected, no two lanes with the same colour dispatched concurrently.
- [FLOW-06] Derived state heals from the log: worktree/row inventory is re-derived from git on every run, never remembered.
- [RES-12]/[PERF-14] Batch the chatty path: `plan-done`, finding dispositions and archive tags go through batch operations, not 60 single writes.
- [PERF-04] Amdahl: the serial fraction is the `wiring → gpuops-1` cut vertex; everything else is scheduled in parallel.
- [OBS-01]/[OBS-05] Expose state: `make worktree-reap` prints the full redundant list (never just a count) and `check-all` fails on it; thresholds live in `mk/lane-maintenance.mk`, not the script.

## Terminology

- **Redundant worktree**: linked worktree whose branch is an ancestor of its parent (`feature/<task>`) or of `main` with zero unique commits (`git cherry` shows no `+`).
- **Component**: connected component of the conflict graph whose edges are "changed the same file relative to `main`".
- **Landed**: `git merge-base --is-ancestor <branch> main` exits 0.
- **Parked**: branch tagged `archive/<branch>-<yyyymmdd>`, task row `blocked` with rationale, open findings `deferred`.

## Current State Analysis

Verified 2026-09-07 from `git for-each-ref`, `git cherry main`, `git merge-tree --write-tree`, `manage_worktree_lane(list)`, `make task-reap` (dry run).

| Class | Branches | Worktrees | Evidence |
| --- | --- | --- | --- |
| Redundant (ancestor of parent, 0 unique) | 27 | 20 | `gpuops-1-{installer,lifecycle,naming-gpu-tier,naming-provenance-ui,naming-toggle,php,r1..r4,service-api,spa}`, `gpulife-1-r3-preflight`, `healthobs-1-{headroom,liveness,mount,outcome,readiness,status}`, `review/{evid-1,gpulife-1-a,gpulife-1-d,guidedgpu-1-rev-s1a,guidedgpu-1-rev-s2a}`, `feature/guidedfix-2` (== main), `feature/vmreap-3` (== main, unstarted) |
| Brief-only sub-lanes | 3 | 3 | `guidedfix-2-{php,svc,ts}`: one docs commit each, no task row |
| Live, gate-ready | 3 | 5 | `demogate-2` (1 commit, 0 findings, 0 behind), `healthobs-1`→ff to `-dedupe` (11 commits, 0 findings, clean merge), `gpulife-1`→ff to `-r3-wiring` (8 commits, 1 low finding R2L-01, clean merge) |
| Live, needs fix lanes | 2 | 2 | `evid-1` (6 commits, 23 open, 37 behind, clean merge), `gpuops-1` (24 commits, 10 open, 17 behind, clean merge) |
| Stale August cluster (≈1050 behind) | 12 | 0 | `vlm-6` (282 unique, 70 open), `fir-12` (60, 40), `fir12-r7-int` (59), `descqual-2` (49, 15), `lane/l11-rescue` (299), `corpus-1` (2, 9), `vlm6-lex` (5, 9), `cmap-1` (1, conflicts), `evalsurf-1` (1, conflicts), `defwave-1-d1-lintratchet` + `review/defwave-1-d1` (1 wip), `ocirv-1-rev-ops` (3, conflicts) |
| Coordination | 1 | 1 | `feature/land-1` |

Handoff rows: 59 `active` (45 main-target MAINT/planning rows needing explicit `plan-done`), 18 `ambiguous` (branch missing, no merge proof: DEMOLIVE-*, DEMOUX-*, WB-CODEX-LUNA-1, DUXW2-INTEGRATION, …), 0 auto-closeable. Lane rows still `planned` for landed branches: GPUOPS-1 r1–r4, GPULIFE-1 rev-a/rev-d/fix/r3-preflight, EVID-1 evidence; EVID-1 rev `blocked`.

Root worktree bleed: 5 untracked lane briefs (`GPULIFE-1-r3-{preflight,wiring}`, `GUIDEDGPU-1-{fix-poll,rev-s1a,rev-s2a}`).

### Conflict graph (files changed vs `main`, pairwise intersection)

```
gpulife-1-r3-wiring ──3── gpuops-1 ──1── healthobs-1-dedupe
   (installer, contract doc,      (api/main.py: both add an
    test_gpu_lifecycle_install)    include_router line; merge-tree clean)

evid-1        (isolated: scripts/gpu_burst_evidence.py, export-gpu-evidence.sh, mk/gpu-evidence.mk, tests)
demogate-2    (isolated: infra/oci/demo/*)
guidedfix-2-* (isolated: docs only)
aug-cluster   (isolated from live set; dense internal overlap on scripts/eval_harness)
```

The `wiring — gpuops-1` edge is semantic, not just textual: both branches independently implemented the GID-10001 `groupadd` fix in `gpu-lifecycle-install.sh` (`6817c7080` on wiring, `de76ffc43` on gpuops-1). `merge-tree` reports clean because the hunks do not overlap, which means main would carry **two** group-provisioning paths. This is the cut vertex of the plan ([GRPH-05]).

## Target Outcome

- `git worktree list` → root + LAND-1 + lanes with a live dispatch, nothing else.
- Every branch in the redundant class deleted; every parked branch has an `archive/` tag.
- Five live components landed on `main` with gate evidence, rows `done` + archived.
- `make task-reap` reports 0 `ambiguous`; `manage_worktree_lane(list)` returns no `planned` rows for landed branches.
- `make worktree-reap` exists, is tested, and `make check-all` fails while redundant worktrees exist.

## Context Loading

- `docs/workbay/rules/graph-theory-heuristics.md` — GRPH-01/05/06.
- `docs/workbay/rules/development-workflow.md` § Pre-Merge Gate, § Dirty Worktree Teardown.
- `scripts/workbay_lifecycle/handlers/task_finish.py:_branch_is_merged` — ancestor-then-`git cherry` merged check whose semantics `scripts/worktree_reap.py` copies (plugin file, not importable from tracked code).
- `~/Development/agentic-protocol-monorepo/scripts/worktree_reachability.py` — prior art: blob-reachability instead of `status --short` as the reap-safety predicate.
- Prior art (semantic search `find_related_prior_work`): `MAINT-worktree-close-wave-20260816`, `MAINT-inflight-board-clearing-20260710`, VLM-5 landing decision #2081 (ff-merge after `handoff_close_check(enforce=True)`).
- GPUOPS-1 continuation `cont-20260907T141614730082Z-e38702a0` — groups A–F, lane test commands, API gotchas.
- Lane test commands: from `manage_worktree_lane(list, task_ref=…)` rows (copied into the manifest section).

## Contract and Boundary Impact

- No service/schema/MCP contract changes from LAND-1 itself.
- `docs/workbay/contracts/gpu-lifecycle.md` is edited by both wiring and gpuops-1 group A; the reconcile node merges them into one contract text.
- New make target + script (`worktree-reap`) is repo-local (`scripts/worktree_reap.py`, `mk/lane-maintenance.mk`); it shells out to git only and imports no workbay internals.

## Proposed Solution

### DAG

```
                 ┌──────────────────────────────────────────────────┐
                 │ N0 rows-hygiene   N1 reap-redundant   N12 bleed  │  ← no deps; start now
                 │ N10 park-august   N11 worktree-reap tool (TDD)   │
                 └──────────────────────────────────────────────────┘

  N3 healthobs ──gate──ship──finish                (independent)
  N4 demogate  ──gate──ship──finish                (independent)
  N5 evid-1: refresh ─┬─ lane evid-py  ─┐
                      ├─ lane evid-sh  ─┼─ review ── gate ── ship ── finish
                      └─ lane evid-mk  ─┘

  N2 gpulife-1: lane R2L-01 (on wiring) ── ff gpulife-1 ── gate ── ship ── finish
       │
       │ hard edge (shared installer/contract)                 N6 gpuops free lanes: B, D, F  (now)
       ▼                                                          │ B ──▶ E (durability)
  N7 gpuops-1 reconcile: merge main, dedupe groupadd ──▶ lanes A, C │
       │                                                          │
       └────────────────────────┬─────────────────────────────────┘
                                ▼
                  N9 gpuops-1: 7-lens /wb-review-slice ── fixes ── gate ── ship ── finish

Critical path (GRPH-31): N2 → N7 → N9.   Ready-frontier width at t0: 6 local + 7 remote lanes.
```

Colouring ([GRPH-09]): lanes touching `gpu-lifecycle-install.sh` / `gpu-lifecycle.md` / `test_gpu_lifecycle_install.py` (wiring R2L-01, gpuops A, gpuops C) share one colour and are serialised behind N2. All other lanes are distinct colours and run concurrently.

### Landing protocol (applied identically to every component; each step idempotent)

1. `git merge-base --is-ancestor <sub-lane> <parent>` for every sub-lane; fast-forward the parent when the sub-lane is strictly ahead and `merge-tree` is clean.
2. Refresh from `main` (merge, not rebase — lane commits carry review provenance).
3. Local verification (`pytest`/`vitest`/`phpunit` per lane row) → `record_event(test_result)` at HEAD.
4. Open findings → fix lanes, or `deferred`/`wontfix` with rationale; lint-only findings deferred to a named next wave.
5. `close_slice` → `handoff_close_check(enforce=True)` → `make check-remote` (detached, `nohup … & disown`) → second `test_result`.
6. `git merge --ff-only` (or `--no-ff` when history has merges) from root; verify `merge-base --is-ancestor <branch> main`; `wb ship` alone is not trusted.
7. `make task-finish TASK=<ref>` → close lane rows → `git worktree remove` → `git branch -d`.
8. `render_handoff(kind='dashboard')`.

## Files and Surfaces to Change

`scripts/workbay_lifecycle/` and `Makefile.d/` are workbay-plugin output (gitignored, `.gitignore:135`, `:138`); nothing added there lands on `main`. The reaper lives on tracked surfaces:

- `scripts/worktree_reap.py` (new) — `classify(repo) -> list[WorktreeRecord]`, `apply(records, *, dry_run)`; classification contract = `task_finish._branch_is_merged` semantics (`git merge-base --is-ancestor <branch> <parent>` OR every `git cherry <parent> <branch>` line is `-`), dirtiness = `git status --porcelain` non-empty (a dirty record is never reaped; blob-reachability scoring per `agentic-protocol-monorepo/scripts/worktree_reachability.py` is a stretch goal).
- `scripts/test_worktree_reap.py` (new) — added to the `test-scripts` list in `Makefile`.
- `mk/lane-maintenance.mk` — `worktree-reap` (dry run, JSON + table) and `worktree-reap-check` (exit 1 when redundant worktrees exist, wired into `check-all`). `make context` is plugin-owned; a warning there is filed as an upstream request, not implemented here.
- `docs/workbay/rules/development-workflow.md` — § Landing Protocol (the 8 steps above).
- `docs/workbay/constitution.md` + `CLAUDE.md` — new guard rg-019 (sub-lane worktrees are reaped in the same slice that integrates them).
- `docs/tasks/v0.5.0/lanes/*` — the 5 orphan briefs, committed on `feature/land-1`.

## Related Files

- `scripts/workbay_lifecycle/handlers/task_finish.py` — `_branch_is_merged`, worktree-remove/branch-delete ordering (read-only reference).
- `config/lane-orchestration/GPUOPS-1.json`, `EVID-1.json`, `GPULIFE-1.json` — owned_paths for the fix lanes (owned_paths override in the brief is inert; edit the manifest).
- `scripts/vm/reap-lane.sh` — VMREAP-3 follow-up target (unstarted; not in this plan's DAG).

## Verification Strategy

- Tool: `pytest scripts/test_worktree_reap.py` — fixtures build a temp repo with (a) ancestor sub-lane, (b) sub-lane with one unique commit, (c) dirty ancestor, (d) review branch == main, (e) sub-lane rebased onto parent (SHAs differ, `git cherry` all `-`); assert `classify` returns REDUNDANT for (a)/(d)/(e), LIVE for (b), DIRTY for (c), and that `apply` removes only REDUNDANT. Mutation check: drop the `git cherry` fallback → (e) fails.
- Landing: per component, `merge-base --is-ancestor <branch> main` == 0 and `git worktree list | grep -c <path>` == 0; `handoff_close_check(enforce=True)` JSON archived as test evidence.
- Hygiene: `make task-reap` → `ambiguous (0)`; `git worktree list | wc -l` ≤ 2 + live lanes.
- Reviews: adversarial `/wb-review-slice` on gpuops-1 (7 lenses: state-machine, failure-modes, boundary-contract, operator-ux, naming-truth, test-integrity, canon) — 1 local + 6 remote; on evid-1 (3 lenses: failure-modes, test-integrity, boundary-contract).
- Gate: `make check-remote` per component before ship.

## Slice Delivery

### Slice 1: Redundancy reaper tool (TDD) and first reap

**Goal**: `make worktree-reap` classifies every linked worktree and, with `--apply`, closes lane rows and removes proven-redundant clean worktrees + branches.
**Proof**: unit tests above; running it on the real repo reports exactly the 20 worktrees / 27 branches in the redundant class and removes them; `git worktree list` drops from 28 to 8.
**Also**: commit the 5 orphan briefs; land the 3 `guidedfix-2-*` briefs as one docs commit on `feature/land-1`, then delete those 4 worktrees/branches.

### Slice 2: Handoff-row hygiene and August parking

**Goal**: 0 ambiguous rows; main-target rows closed; August cluster parked.
**Proof**: `make task-reap` shows `ambiguous (0)`; junior-agent classification of the 18 ambiguous rows (merged-to-main via `git log --all --grep`, or genuinely lost) recorded as one decision; `plan-done` batch for the 45 main-target rows; `archive/<branch>-20260907` tags on all 12 August branches; VLM-6/FIR-12/DESCQUAL-2/CORPUS-1/VLM6-LEX/CMAP-1 rows → `blocked` ("parked: re-plan against current main") and archived; their 143 open findings → `deferred` via `review_findings(resolve, status=deferred)` with `verification_evidence`. Branch deletion for the August set is **operator-gated** (tags make it reversible; default in this plan is tag-and-keep).

### Slice 3: Land the four small components

**Goal**: GPULIFE-1, HEALTHOBS-1, DEMOGATE-2, EVID-1 on `main`.
**Proof**: per-component landing protocol steps 1–8 with evidence in handoff. GPULIFE-1 needs one remote lane (R2L-01 on `gpulife-1-r3-wiring`, brief already committed at `09fe6345a`). EVID-1 needs three remote fix lanes split by owned file, then a 3-lens review. HEALTHOBS-1 and DEMOGATE-2 need only gate + ship.

### Slice 4: GPUOPS-1 reconcile, fix, review, land

**Goal**: one group-provisioning path in the installer; 10 findings closed; adversarial review green; landed.
**Proof**: after N2 lands, `git merge main` into `feature/gpuops-1`; a reconcile lane removes the duplicate `groupadd` path and keeps the stricter guard (`test_every_supplementary_group_is_a_name_the_installer_resolves` + wiring's `216/GROUP` preflight assertion both pass); lanes A, C dispatched after reconcile; B, D, F dispatched now; E after B. 7-lens review, fixes, gate, ship, finish.

### Slice 5: Make it not recur

**Goal**: `check-all` fails on redundant worktrees; landing protocol documented; guard recorded.
**Proof**: `make worktree-reap-check` exits 1 against a fixture repo with one redundant worktree and 0 on the converged repo; § Landing Protocol in development-workflow.md; rg-019 in constitution + CLAUDE.md sync in the same commit; `make check-all` green; upstream request filed for a `make context` warning.

## Lane Decomposition (Multi-Agent)

Lanes are dispatched under their **owning** task_ref (findings and gate audit stay on the right ref — the GATE-01 lesson). LAND-1 owns Slices 1, 2, 5 and the coordination of 3–4.

### Lanes

| Lane | Task | Branch | Owned paths | Backend | Test |
| --- | --- | --- | --- | --- | --- |
| gpulife-1-r3-wiring (R2L-01) | GPULIFE-1 | feature/gpulife-1-r3-wiring | scripts/deploy/gpu-lifecycle-install.sh, scripts/deploy/tests/test_gpu_lifecycle_install.py | codex-remote luna/max | `LC_ALL=C python3 -m pytest scripts/deploy/tests/test_gpu_lifecycle_deploy_wiring.py scripts/deploy/tests/test_gpu_lifecycle_install.py scripts/test_deploy_workflow_gate.py -q` |
| evid-1-py | EVID-1 | feature/evid-1-py | scripts/gpu_burst_evidence.py, scripts/test_gpu_burst_evidence.py | codex-remote luna/max | `python3 -m pytest scripts/test_gpu_burst_evidence.py -q` |
| evid-1-sh | EVID-1 | feature/evid-1-sh | scripts/deploy/lib/export-gpu-evidence.sh, scripts/deploy/tests/test_export_gpu_evidence_shell.py, scripts/deploy/tests/test-export-gpu-evidence.sh | codex-remote luna/max | `python3 -m pytest scripts/deploy/tests/test_export_gpu_evidence_shell.py -q` |
| evid-1-mk | EVID-1 | feature/evid-1-mk | mk/gpu-evidence.mk, docs/runbooks/gpu-evidence-capture.md | codex-remote luna/max | `make -n gpu-evidence-export` + shell test |
| gpuops-1-b-intent | GPUOPS-1 | feature/gpuops-1-b-intent | infra/oci/gpu_lifecycle/intent.py, infra/oci/gpu_lifecycle/tests/test_intent*.py | codex-remote luna/max | `python3 -m pytest infra/oci/gpu_lifecycle/tests/test_intent.py infra/oci/gpu_lifecycle/tests/test_intent_controller.py -q` |
| gpuops-1-d-observe | GPUOPS-1 | feature/gpuops-1-d-observe | infra/oci/gpu_lifecycle/reaper.py, apps/prototype-description-service/scene/application/gpu_intent.py, scene/application/gpu_state.py, scene/interface_adapters/http/routers/gpu.py, scene/infrastructure/vlm/gpu_remote_adapter.py, scene/tests/test_gpu_router.py | codex-remote luna/max | `python3 -m pytest infra/oci/gpu_lifecycle/tests -q && cd apps/prototype-description-service && python -m pytest scene/tests/test_gpu_router.py -q` |
| gpuops-1-f-process | GPUOPS-1 | feature/gpuops-1-f-process | scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py, docs/runbooks/oci-instance-state-and-cost.md, docs/tasks/v0.5.0/lanes/GPUOPS-1-_common.md, config/lane-orchestration/GPUOPS-1.json | codex-remote luna/max | `LC_ALL=C python3 -m pytest scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py -q` |
| gpuops-1-e-durability | GPUOPS-1 | feature/gpuops-1-e-durability | intent.py (after B), docs/workbay/contracts/gpu-lifecycle.md | codex-remote luna/max | intent + reaper suites |
| gpuops-1-reconcile | GPUOPS-1 | feature/gpuops-1 | gpu-lifecycle-install.sh, test_gpu_lifecycle_install.py | codex-remote luna/max | installer suites + shellcheck |
| gpuops-1-a-contract | GPUOPS-1 | feature/gpuops-1-a-contract | docs/workbay/contracts/gpu-lifecycle.md | codex-remote luna/max | `make lint-task-plans` |
| gpuops-1-c-installer | GPUOPS-1 | feature/gpuops-1-c-installer | gpu-lifecycle-install.sh, infra/oci/cloud-init.yaml, single-reaper-owner test | codex-remote luna/max | installer + cloud-init suites |
| land-1-reap-tool | LAND-1 | feature/land-1 | scripts/worktree_reap.py, scripts/test_worktree_reap.py, mk/lane-maintenance.mk, Makefile (test-scripts list) | codex-remote luna/max (/wb-tdd brief) | `python3 -m pytest scripts/test_worktree_reap.py -q` |
| land-1-hygiene | LAND-1 | feature/land-1 | handoff DB only | local + junior subagent | `make task-reap` |

### Merge Order

1. Slice 1 reap (no merge; deletions only) ∥ Slice 2 hygiene ∥ N3 healthobs ∥ N4 demogate ∥ N5 evid lanes ∥ N6 gpuops B/D/F ∥ N2 wiring lane.
2. N2 lands → N7 reconcile → A, C, E.
3. N9 gpuops review → land.
4. Slice 5 (`feature/land-1`) lands last so `worktree-reap-check` runs against the converged state.

### Manifest

`config/lane-orchestration/` is gitignored workspace-local state (`.gitignore:189`), not a versioned surface. Each manifest is `{task_ref, lanes: {lane_id: {...}}, depends_on, merge_order, downstream, routing, default_done_definition}`. Existing lane ids: GPUOPS-1 `gpuops-1-r1-intent-reader/r2-service-parity/r3-installer-fencing/r4-reaper-start` (landed, rows still `planned`); EVID-1 `evid-1-evidence` (→ `feature/evid-1`), `evid-1-rev`; GPULIFE-1 `gpulife-1-rev-a/rev-d/fix/r3-wiring/r3-preflight`.

Per new lane, in order: (1) close the stale rows above (`manage_worktree_lane close`); (2) `git worktree add ../context-alt-text-monorepo-<lane> -b feature/<lane> feature/<parent>`; (3) `manage_worktree_lane upsert` with `task_ref`, `lane_id`, `branch`, `worktree_path`, `owned_paths`, `test_command`; (4) add `lanes[lane_id]` + `depends_on` edges (`gpuops-1-e-durability → gpuops-1-b-intent`, `gpuops-1-a-contract → gpuops-1-reconcile`, `gpuops-1-c-installer → gpuops-1-reconcile`) to the manifest and validate with `load_manifest`; (5) post the brief via `dispatch_lane_work(brief=…)`. Manifest alone is not a lane; a brief payload `owned_paths_override` is inert.

LAND-1's own two lanes run locally on `feature/land-1` and need no manifest.

### Orchestration Mode

`dispatch_wave` per owning task with `wave_max_width=6`, `timeout_seconds=3600`, `effort="max"`, `model="gpt-5.6-luna"`, `speed="standard"`; briefs posted first via `dispatch_lane_work(brief=…)` with `include_context_packet=true` and `context_targets` = owned paths (codemap packet + semantic prior art). Dispatches launched detached (`nohup … & disown`). Fresh finding-id ranges fenced per lane in each brief.

## Consolidated Checklist

- [ ] S1 reaper tool tests red → green; 20 worktrees / 27 branches removed; orphan briefs committed
- [ ] S2 45 `plan-done`; 18 ambiguous classified + closed; 12 archive tags; 6 rows parked; open findings on parked refs deferred with rationale
- [ ] S3 GPULIFE-1, HEALTHOBS-1, DEMOGATE-2, EVID-1 landed with gate evidence and rows archived
- [ ] S4 GPUOPS-1 reconciled, findings closed, 7-lens review, landed
- [ ] S5 `worktree-reap-check` in `check-all` + Landing Protocol doc + rg-019 synced; `make check-all` green
- [ ] Every landing decision recorded in handoff; dashboard re-rendered after each

## Context and Ownership

- [ ] Loaded development-workflow.md § Pre-Merge Gate / § Dirty Worktree Teardown, graph-theory-heuristics.md, and the GPUOPS-1 continuation packet before editing.
- [ ] Contract touched: `docs/workbay/contracts/gpu-lifecycle.md` (owner GPUOPS-1; reconcile lane merges the wiring edit). No other boundary changes.

### Checklist for Slice 1: Redundancy reaper tool (TDD) and first reap

- [ ] `scripts/test_worktree_reap.py` fixtures (a)–(e) written first and red
- [ ] `scripts/worktree_reap.py` classify/apply green; `mk/lane-maintenance.mk` targets; `test-scripts` entry
- [ ] Dry run matches the inventory table; apply removes the redundant class; lane rows closed before removal
- [ ] `guidedfix-2-*` briefs landed as docs; those worktrees/branches removed

### Checklist for Slice 2: Handoff-row hygiene and August parking

- [ ] Ambiguous rows classified (MERGED / BRANCH_GONE / BRANCH_EXISTS / PLANNING_ONLY) and closed per class
- [ ] Main-target rows `plan-done` in one batch
- [ ] `archive/<branch>-20260907` tags; parked rows `blocked` + archived; findings deferred with `verification_evidence`
- [ ] `make task-reap` shows `ambiguous (0)`

### Checklist for Slice 3: Land the four small components

- [ ] GPULIFE-1: R2L-01 lane green, ff to wiring, gate, ship, finish
- [ ] HEALTHOBS-1: ff to dedupe, gate, ship, finish
- [ ] DEMOGATE-2: gate, ship, finish
- [ ] EVID-1: refresh from main, three fix lanes, 3-lens review, gate, ship, finish

### Checklist for Slice 4: GPUOPS-1 reconcile, fix, review, land

- [ ] `feature/gpuops-1` merged with main after GPULIFE-1 lands; reconcile lane leaves one group-provisioning path
- [ ] Lanes B, D, F (now) and A, C, E (after reconcile) green with fenced finding-id ranges
- [ ] 7-lens adversarial review (1 local + 6 remote) with codemap/prior-art packets; fixes; gate; ship; finish

### Checklist for Slice 5: Make it not recur

- [ ] `worktree-reap-check` in `check-all`; upstream request filed for a `make context` warning
- [ ] § Landing Protocol in development-workflow.md; rg-019 in constitution + CLAUDE.md same commit
- [ ] `make check-all` green; LAND-1 gate; ship; finish

## Review Readiness

- `/wb-review-plan` on this document before Slice 3 dispatch (planning review, 2 passes: 1 local, 1 remote against canon). `make plan-analyze` is broken in this workspace (`skill 'plan-draft' has no live command_id in portable_commands.json` — upstream workbay-plugin defect); triage ran through the planning-review skill directly.
- Each landed component: branch review already recorded on its ref; LAND-1 adds only gate evidence.

## Stretch Goals

- VMREAP-3 (VM orphan-lane sweep) as an extra independent lane once the VM `UserTasksMax` operator item is done.
- Cherry-pick `cmap-1` / `evalsurf-1` single commits onto fresh branches if still wanted (conflicts are small).

## Success Criteria

- `git worktree list | wc -l` ≤ 2 + live dispatches; no branch is an ancestor of its parent with a worktree.
- `make task-reap` → `ambiguous (0)`; no `planned` lane rows for landed branches.
- Five components on `main`, each with `handoff_close_check(enforce=True)` evidence and `check-remote` green at the shipped SHA.
- `make worktree-reap` exists with tests; `make check-all` includes `worktree-reap-check`.
