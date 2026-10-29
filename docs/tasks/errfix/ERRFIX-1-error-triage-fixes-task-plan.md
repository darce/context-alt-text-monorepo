# Task Plan

> **Metadata**
>
> - **Date**: 2026-10-29
> - **Author**: Claude Opus 5.5 (`claude-opus-5-5`)
> - **Project**: repo tooling (`scripts/`, agent docs, handoff data)
> - **Task ID**: `ERRFIX-1`
> - **Owning Epic**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`
> - **Epic Short ID**: E15
> - **Task Plan Status**: `proposed`
> - **Target Branch**: `feature/errfix-1`
> - **Review Coverage Target**: 1
> - **Scope Brief**: none. This is a bug and tech-debt triage built from audit decision 20506 and the WorkBay REQUEST of 2026-10-29 (R1–R5).
> - **Anchors verified at**: main `8eece0358f` (2026-10-29).

---

## ERRFIX-1. Error triage fixes

Paths are repo-relative.

## Objective

Reduce agent errors in this repo by fixing the preconditions behind the largest measured error classes. ACX fixes its own tooling, docs, lane manifests and data. Causes owned by WorkBay are filed upstream, not built here.

Baseline:
- 441 axial-coded errors (2026-10-17 → 10-29);
- 6,853 of 7,290 guard lines (94%) are "Ambiguous active task";
- remote lane pass@1 is 0.642 (lane-clustered 95% CI 0.51–0.76).

## Intake

- **Request (2026-10-29)**: "triage fixes to reduce errors … produce a task plan but do not spend 12 hours on it, use the improvements you are already proposing".
  - Implementation runs on codex-remote `gpt-6.1-sol`, high effort.
  - Grunt work and web fetching run on `gpt-6.1-terra`, high effort.
- **Reused proposals**:
  - audit decision 20506 on `MAINT-EVALOPS-AUDIT-20261029`, P0–P2;
  - WorkBay `REQUEST-review-convergence-measurable-and-planning-acceptance-20261029.md`, R1–R5;
  - the EVALOPS seam, decision `claude_decision_evalops_workbay_acx_seam_20261029`. WorkBay owns code, schema, hooks, targets and payload. ACX owns consumer docs and config, ACX evals, data supply, replay acceptance, and cleanup of its own rows and artifacts.
- **Not-Doing**: see Not Doing.

## Problem Statement

Errors cluster in preconditions, not in the code under change. The preconditions are task resolution, worktree provisioning, the transport, lane manifests and review gates.

Failures are correlated. After a failure, a retry succeeded only 0.263 of the time. Ever-success is 0.736, against the 0.994 that five independent attempts would give. Retries therefore do not recover these failures [AUDIT-11].

| Class | n (share) | Root cause | Fix | Owner | Pri | Metric |
|---|---|---|---|---|---|---|
| lane_state_provenance_drift | 124 (28.1%) | 12 live main-target rows share the repo root, so cwd resolution is ambiguous. Dead plan cursors remain. Documented commands write to the wrong row: lowercase MAINT refs, and `handoff-review-run` variables that are ignored | Slice 2, Operator S3 | ACX, plus WorkBay reclaimer, R4, R5 | P0 | Ambiguous share of guard lines; drift errors per week |
| remote_transport_infra | 90 (20.4%) | task-start symlinks payload files into the worktree. The provisioner then aborts, and preflight refuses the symlinked transport. Preflight refusals open the configuration breaker | Slice 1 | ACX, plus WorkBay transport/breaker | P0 | `transport_missing` on fresh worktrees = 0 |
| other (pytest) | 78 (17.7%) | Lane tests run in the wrong env, or run more than the changed tests | Slice 4 service-env rule | ACX, plus WorkBay lane-scoped tests | P1 | pytest errors per week |
| review_gate_loop | 66 (15.0%) | Planning review has no bound. Rounds are not in the DB. plan-accept needs a pass run | R1–R3 | WorkBay | P0 upstream | rounds-to-pass p95 ≤ 2 (needs R2) |
| brief_scope_spec | 43 (9.8%) | Missing `test_cmd`; briefs that forbid commits; briefs wider than 3 files | Slice 4 | ACX | P1 | rule violations at dispatch = 0 |
| test_fixture_env | 30 (6.8%) | Lane worktrees are missing env, deps or overlays | Slices 1, 4 | ACX | P1 | fixture/env errors per week |
| tool_api_shape | 10 (2.3%) | Write shapes that are undocumented or fail silently | WorkBay docs | WorkBay | P2 | — |

Signals outside the 441, all owned by WorkBay (see Contract and Boundary Impact):
- deadletters: 685 of 709 are `compaction_failed`;
- `lane-retire-sweep`: 19 of 56 runs completed;
- receipts: 26 of 29 `tokens_complete` receipts carry 0 tokens.

## Constraints

- Edit only this repo. WorkBay code, schema, hooks, targets and payload are filed upstream and never edited here.
- Lane routing:
  - Implementation and RED lanes run on codex-remote `gpt-6.1-sol`, high effort.
  - Grunt and web-fetch lanes run on `gpt-6.1-terra`, high effort.
  - Nothing runs on the local host.
  - Each change is one RED lane, then one implementation lane, of 1–3 files each.
- Commits are operator-only.
- Agents never touch `handoff.db` with `sqlite3` (rg-018). VACUUM is operator-run, after a backup, with the MCP servers stopped.
- Do not run `make task-reap REAP_ARGS=--apply` while `feature/errfix-1` has no commit. The dry run classifies ERRFIX-1 as closeable, because a zero-commit branch is an ancestor of main.
- Greenfield: no migrations; delete rather than flag.
- One planning review. At round 3 the operator adjudicates [FM-08, AGT-12].

## Workflow Principles

- Fix the largest measured class first [OPS-75]. Fix preconditions, not retries [AUDIT-11].
- New checks fail closed [RLSE-02]. Every subprocess call they make has a timeout [RES-02].
- Labels come from a human. Model pre-labels and agreement are diagnostics only [HITL-05, EVAL-12]. Disagreements are kept in writing [MLDATA-03].
- Cleanup is proposed and the operator can veto it. Every skip is named [AGT-06].

## Terminology

| Term | Meaning |
|---|---|
| Main-target row | A live handoff row whose target branch is `main` and whose target worktree is the repo root |
| Payload symlink | A worktree path that WorkBay task-start (`overlay_adopt`) links to `…/workbay_system/payload/<same path>` |
| Transport | `scripts/remote_agent.sh` |
| Dead cursor | An orchestrator plan cursor in state `dispatched` with "lane row missing; cannot prove dead" |
| Replay | Re-running the 2026-10-29 audit scripts in `.task-state/evalops-20261029/` to get per-class counts |

## Current State Analysis

**Provisioning**
- `scripts/workstate/provision_lane_worktree.py:_require_inside` (l.213) refuses `scripts/workbay/wb`, because task-start symlinked it into the payload. As a result `worktree_bootstrap` exits 3 on every task-start.
- WorkBay `resolve_transport` opens the transport with `O_NOFOLLOW` and refuses the symlinked `scripts/remote_agent.sh`. `offload_preflight` therefore returns `transport_missing`. Seen on errfix-1 and e15-38.

**Task resolution**
- There are 12 live main-target rows. The oldest are GTMSMOKE-1 and FIRBENCH-1, from 10-16.
- `make task-reap` (dry run) labels every one "main-target maintenance/planning row" and never marks any closeable.
- `make maint-archive-stale` archives only MAINT rows that are terminal or whose worktree is missing, so it never fires on these rows.
- Seven dead cursors: 111, 112, 113 (WBTRUST-5), 114 (FIRBENCH-1), 118, 120 and 122 (BAKECACHE-1).
- Stale feature rows with open findings: BAKECACHE-1, WBTRUST-4/5/7, and `internal-20261025` (null target).

**Docs**
- `CLAUDE.md:15` documents a lowercase `MAINT-<slug>-<YYYYMMDD>` ref, which `make plan-done` cannot close (R5).
- `CLAUDE.md:46` and `.github/copilot-instructions.md:111` document `make handoff-review-run TASK_REF=… SUBJECT=…`. The target forwards only `LIFECYCLE_ARGS` (R4).

**Manifests**
- Nothing checks for empty test commands, the service env, null model pins, briefs that forbid commits, or brief width.
- `scripts/check_lane_manifest_overlaps.py` checks owned-path overlap only.

**Storage**
- `handoff.db` is 345 MB: concept_embeddings ~118 MB (34%), task_archives 85 MB (25%), findings ~53 MB, decisions ~44 MB. It runs with `auto_vacuum=0` and WAL.
- `.task-state` is 1.9 GB, of which ~830 MB is landed-lane bundles.
- The disk is 94% used, with 13 GiB free.

## Target Outcome

- A task-start worktree bootstraps with `ok:true` and passes `offload_preflight`.
- Documented make commands run as written, and a test fails when they drift.
- At most 2 live main-target rows remain at rest, and the Ambiguous share of guard lines is under 20%.
- Lane manifests that break known-bad rules are refused before dispatch.
- Seed data exists: 100 human-labelled findings, 100 open-coded errors and a lesson-retrieval qrels seed.
- Replay after each WorkBay release shows the per-class change.

## Context Loading

- `scripts/workstate/provision_lane_worktree.py` (`_require_inside`, `_plan_overlay`, `_contained_dest_rel`, `_require_plain_overlay_dirs`) and `scripts/tests/test_provision_lane_worktree.py`
- `CLAUDE.md`, `.github/copilot-instructions.md`, `Makefile.d/lifecycle.mk` (`task-start`, `task-reap`, `handoff-review-run`) and `Makefile:test-scripts`
- `scripts/check_lane_manifest_overlaps.py`, `mk/lane-overlaps.mk` and `config/lane-orchestration/*.json`
- `.task-state/evalops-20261029/{db,axial,analyze}.py` for replay. `db.py` reads through the `workbay_handoff_mcp` API.
- Upstream REQUEST R1–R5 (WorkBay repo, read-only)

## Contract and Boundary Impact

- No REST, schema or service change.
- ACX contracts touched:
  - provisioner overlay rules: a payload symlink counts as provisioned;
  - documented commands (rg-006);
  - lane manifest validation.
- WorkBay dependencies are filed, or will be filed by the operator. This repo never edits the WorkBay checkout.

| Ask | Class | Status | Canon |
|---|---|---|---|
| R1: bound planning review at 2 rounds, then hand to the operator | review_gate_loop | filed 10-29 | FM-08, AGT-12, TEST-33 |
| R2: rounds, judge pin and human labels as DB columns | measurement | filed | OBS-02, EVAL-12 |
| R3: `plan-accept ACCEPT=operator` | review_gate_loop | filed | RLSE-29, AGT-06 |
| R4: `handoff-review-run` variables. R5: `plan-done` keeps case | drift | filed; ACX doc fix in Slice 2 | FM-12 |
| `task-reap` classifies main-target rows by staleness | drift | to file | — |
| task-start copies the transport, or `resolve_transport` accepts a digest-verified payload symlink | transport | to file | — |
| A preflight refusal does not open the 6 h breaker for all codex implementation | transport | to file | — |
| `result.json` as one wide event (lane, task, backend, model, effort, tokens, `wall_ms`); receipts carry tokens | measurement | `result.json` in REQUEST "Related"; receipts to file | OBS-02 |
| Deadletters (`compaction_failed`); retire-sweep completion | ops | REQUEST "Related" | — |
| Lane tests limited to the changed tests | other (pytest) | to file | — |
| Retrieve prior lessons before a command that failed before (19034 was missed before error 1535) | recurrence | to file | — |
| Storage: embeddings as a rebuildable sidecar (f16/int8); external-content FTS5 and no redundant indexes; `auto_vacuum=INCREMENTAL` with a size budget alert; retention with a cold export and a tombstone pointing to it | storage | to file | STOR-07, STOR-01, STOR-03, STOR-10 |

## Proposed Solution

- Three code slices (1, 2, 4). Each is a RED lane, then an implementation lane, on sol high.
- Three operator slices (S3, S5, S7). The coordinator prepares each one and the operator approves it.
- One data slice (6): a terra pre-pass, then human labels.

## Files and Surfaces to Change

- Slice 1: `scripts/tests/test_provision_lane_worktree.py`, `scripts/workstate/provision_lane_worktree.py`
- Slice 2: `scripts/test_documented_make_commands.py` (new), `CLAUDE.md`, `.github/copilot-instructions.md`, `Makefile` (`test-scripts` list)
- Slice 4: `scripts/test_check_lane_manifest_rules.py` (new), `scripts/check_lane_manifest_rules.py` (new), `mk/lane-overlaps.mk`
- Slice 6 (all new): `benchmarks/experiments/evalops/{findings,errors,qrels}-v0.jsonl`, `benchmarks/tests/test_evalops_seed_files.py`
- Operator slices: handoff rows and plan cursors (MCP), `.task-state/` bundles, `handoff.db` retention

## Related Files

- `scripts/maint_archive_stale.py`: the MAINT-only archiver; unchanged.
- `scripts/check_lane_manifest_overlaps.py` and `scripts/test_check_lane_manifest_overlaps.py`: the pattern Slice 4 follows.
- `Makefile.d/lifecycle.mk:142`: `task-reap`.

## Verification Strategy

| Slice | Proof | Live acceptance |
|---|---|---|
| 1 | `python3 -m pytest scripts/tests/test_provision_lane_worktree.py -q` | The provisioner exits 0 on the errfix-1 worktree, and `offload_preflight` there reports no `transport_missing` |
| 2 | `python3 -m pytest scripts/test_documented_make_commands.py -q`, also run in `make test-scripts` | `make handoff-review-run LIFECYCLE_ARGS=…` records against the named task |
| S3 | `list_handoff_rows` | ≤ 2 main-target rows; Ambiguous share < 20% over the 7 days after S3 |
| 4 | `python3 -m pytest scripts/test_check_lane_manifest_rules.py -q` | `make lane-manifest-rules TASK=<ref>` exits 0 on each new task's manifest before dispatch |
| S5 | `du -sh .task-state` | ≤ 1.1 GB, with the export taken before retention |
| 6 | `python3 -m pytest benchmarks/tests/test_evalops_seed_files.py -q` | 100 human labels recorded; disagreement with the pre-labels reported |
| S7 | Replay output | Per-class weekly counts against the baseline, with a lane-clustered 95% CI |

Mutation checks: each of these must turn the tests red:
- Slice 1: revert the payload-path handling;
- Slice 2: restore the old `handoff-review-run` line.

## Slice Delivery

> Each slice names the files and functions it touches and the proof that closes it.

### Slice 1: Payload symlinks provision cleanly (P0)

Lanes: `errfix-1-envr` (RED), then `errfix-1-env`.

**Goal**: a task-start worktree bootstraps, and its transport is a regular file.

Files/functions:
- RED: `scripts/tests/test_provision_lane_worktree.py`.
- Implementation: `scripts/workstate/provision_lane_worktree.py:_plan_overlay` and `:_require_inside`.

RED tests use a temp primary, a temp worktree, and a fake `<tmp>/workbay_system/payload/` that holds the same relative files.

1. A `scripts/workbay*` overlay entry that is a symlink resolving to `…/workbay_system/payload/<same relative path>` counts as provisioned. The run exits 0 and the entry is untouched.
2. A `scripts/remote_agent.sh` symlink into the payload is replaced by a regular file with the primary's bytes and the executable bit.
3. A symlink to any other path outside the worktree still raises the current `_require_inside` error.
4. A payload symlink whose relative path differs from the entry's still raises.

Implementation: in `_plan_overlay`, recognise the payload symlink before the containment check.
- For `scripts/workbay*` entries, skip it.
- For `scripts/remote_agent.sh`, plan a `file` op that writes a regular copy.
- Containment rules stay the same for every other path.

Proof:
- Tests 1–2 fail on main and pass after `errfix-1-env`. Tests 3–4 pass throughout.
- Live: rerun `python3 scripts/workstate/provision_lane_worktree.py --worktree <errfix-1 worktree>`, then `offload_preflight`.

Until this slice merges, dispatch only from freshly provisioned lane worktrees.

### Slice 2: Documented commands run as written (P0)

Lanes: `errfix-1-docr` (RED), then `errfix-1-doc`.

**Goal**: a test fails when a documented make command does not exist or ignores its variables (rg-006).

Files:
- RED: `scripts/test_documented_make_commands.py`.
- Implementation: `CLAUDE.md:15`, `CLAUDE.md:46`, `.github/copilot-instructions.md:111` and `Makefile:test-scripts`.

RED tests:

1. Every `make <target>` documented in either doc exists in the `make -pq` database. Nothing runs.
2. `make -n handoff-review-run <documented variables, with sentinels>` prints every sentinel, with a 10 s timeout [RES-02]. This fails today, because only `LIFECYCLE_ARGS` is forwarded.
3. The documented `maint-start` ref is uppercase: `MAINT-<SLUG>-<YYYYMMDD>`.
4. The `handoff-review-run` line is identical in both docs.

Implementation:

- `CLAUDE.md:15` → `make maint-start TASK=MAINT-<SLUG>-<YYYYMMDD> OBJECTIVE="..."`.
- `CLAUDE.md:46` and `.github/copilot-instructions.md:111` → `make handoff-review-run LIFECYCLE_ARGS="--task-ref <task-ref> --subject-path <path> --subject-kind <task_plan|other> --verdict <pass|pass_with_findings|fail|conditional_pass>"`.
- Add the test to `test-scripts`.
- If `make check-agent-workflows` reports either line as generated, edit the generator source it names instead.

Proof: tests 2–3 fail on main and pass after `errfix-1-doc`.

### Operator S3: Close stale main-target rows and dead cursors (P0)

The coordinator re-reads live rows (`list_handoff_rows`) and cursors, then proposes. The operator can veto. Use the `make task-reap` dry run only.

- Rows idle for more than 72 h with no live lane: propose `done` and archive. Otherwise, ask the owner.
- Open highs block archive. Either defer them with a rationale [AGT-06], or leave the row live with its owner named.
- Lowercase MAINT rows: run `set_handoff_state(task_ref=<exact ref>, status='done', status_only=True)`, then `archive`.
- Dead cursors 111–114, 118, 120 and 122: expire them through `plan_cursor` once the operator confirms no lane is running.
- Candidates as of 2026-10-29 (re-read before acting):
  - main-target rows: FACEGROUP-0 (landed in `8eece0358f`), CURUX-1, GTMSMOKE-1, FIRBENCH-1, MAINT-AURAFACE-20261017, MAINT-IDENTITY-REWEAVE-DEPLOY-20261019, MAINT-LEXICON-EXTRACTION-20261022, MAINT-SDLC-IMPLEMENTATION-20261025, `MAINT-desc-model-pick-20261026`, `MAINT-wrapup-orchestration-20261026`;
  - stale feature rows: BAKECACHE-1, WBTRUST-4/5/7, `internal-20261025`;
  - UXREC-1 and MAINT-EVALOPS-AUDIT-20261029 stay live.

Proof:
- At most 2 main-target rows remain at rest.
- Replay (S7) after 7 days shows the Ambiguous share. If it is still above 20% with ≤ 2 rows, the remainder belongs to the WorkBay resolver/reclaimer ask.

### Slice 4: Lane manifest rules (P1)

Lanes: `errfix-1-rulr` (RED), then `errfix-1-rul`.

**Goal**: manifests with known-bad shapes fail before dispatch.

Files:
- RED: `scripts/test_check_lane_manifest_rules.py`.
- Implementation: `scripts/check_lane_manifest_rules.py:main` and `mk/lane-overlaps.mk`.

The rules apply to non-terminal lanes in `config/lane-orchestration/*.json`. Skip `*.golden.json`, and lanes with a `terminal` object or a merged, closed, closed_stale or retired status.

| Rule | Level |
|---|---|
| `test_commands` is non-empty | error |
| A lane that owns `apps/prototype-description-service/**` runs every test command with `uv run --directory apps/prototype-description-service` | error |
| A codex-remote lane has a non-null `preferred_model` and `preferred_reasoning_effort`, and a non-null `preferred_speed` when that key exists | error |
| The objective or brief does not say "do not commit" or "no commits" | error |
| More than 3 owned paths | warning |
| Malformed JSON, or no `lanes` mapping | error (fail closed) [RLSE-02] |

RED: one violating fixture per rule, plus one clean fixture. Each asserts the expected exit code and message. Golden and terminal lanes are skipped, and `--task-ref` scopes the check.

Implementation:
- The checker exits 1 on any error and prints warnings.
- `mk/lane-overlaps.mk` gains `make lane-manifest-rules TASK=<ref>` (several: `TASK="<ref> <ref>"`), which checks only the named manifests. `TASK` counts only on the command line (the Makefile defaults it to the resolved task); without it the target reports every manifest. Coordinators run it before dispatch.
- It is not chained to `lane-overlaps-check` or `check-all`. On 2026-10-29, 156 of 398 manifests failed: 1,388 errors over 2,106 non-terminal lanes, mostly historical lanes never marked terminal. Historical manifests are not edited.
- The test joins `lane-overlaps-tests`, which is already in `test-scripts`.

Proof: RED fails (module missing) and passes after `errfix-1-rul`.

### Operator S5: Storage hygiene (P1)

At 345 MB, `handoff.db` is not a correctness problem. The disk is: only 13 GiB is free.

1. Delete landed-lane bundles once verified. For each bundle, run `git bundle list-heads <bundle>`, then `git merge-base --is-ancestor <head> main` for every head. Keep any bundle that fails.
   - `.task-state/uxrec-unblock-20261028T1717/facegroup-0-source-before.bundle` (217 MB)
   - `.task-state/uxrec-unblock-20261028T1717/uxrec-outbox-tenant-scope-source-before.bundle` (217 MB)
   - `.task-state/bundles-samefs/repo-8ff638b3…/5541e4bfd8fe8f40-92c21115….bundle` (208 MB)
   - `.task-state/uxrec-resume-20261027/pre-v175/runtime-state.tgz` (160 MB). This is obsolete since the v0.1.78 closure; the operator confirms.
   - `.task-state/uxrec-resume-20261028/descpick4-aligned-source.tar.gz` (29 MB). The operator confirms DESCPICK-4 landed.
2. Run `export_handoff_state`. Then run `archive(operation='retention')` at 60 days, first as a dry run (≈330 refs), then applied. The export is the tombstone target [STOR-10].
3. Optional, operator only: stop the MCP servers, `VACUUM INTO` a backup, then `VACUUM`.

The durable fixes belong to WorkBay (the storage row in the dependency table).

### Slice 6: Labelled findings and qrels (P1)

Lane: `errfix-1-lbl` on `gpt-6.1-terra`, high effort. This is the first terra dispatch.

**Before dispatch.** The coordinator exports two samples, read-only through the Python API, into `benchmarks/experiments/evalops/`. Both use a fixed seed.
- `findings-v0.jsonl`: 100 findings, stratified by severity and review mode.
- `errors-v0.jsonl`: 100 of the 441 errors.

**The lane** adds:
- `pre_label` (`defect|not_defect|unclear`), evidence and rationale to each finding;
- open codes to each error, written without seeing the axial class;
- `qrels-v0.jsonl`, seeded with the `plan-done` lowercase-ref query → decisions 19034 and 20507, plus more pairs mined from lessons that preceded a repeat error;
- `benchmarks/tests/test_evalops_seed_files.py`, which checks schema, counts, unique ids and the label enum.

**The operator** then labels the 100 findings with the pre-labels hidden, and records `human_label`.
- Disagreements stay in the file [HITL-05, MLDATA-03].
- The judge check is the blocking precision of review findings against the human labels [EVAL-12].

This slice supersedes EVALOPS items 1 and 4.

### Operator S7: Replay acceptance (P1)

After each WorkBay release, and 7 days after S3, the coordinator reruns `.task-state/evalops-20261029/axial.py` and `analyze.py`. It records the results as a `test_result` on ERRFIX-1 [OPS-75]:
- per-class weekly counts;
- pass@1 with a lane-clustered 95% CI [AUDIT-11];
- the Ambiguous share.

## Not Doing

- WorkBay code, schema, hooks, targets or payload.
- Golden set v1 (EVALOPS-1).
- Tuning retries or backoff: failures are correlated [AUDIT-11].
- Agent `sqlite3` maintenance of `handoff.db`.
- A second reclaimer in ACX. `maint_archive_stale.py` stays MAINT-only; the staleness rule belongs in WorkBay `task-reap`.
- Re-reviewing the E15-38 docs.

## Decomposition

```json
{
  "version": 1,
  "items": [
    {"id": "s1", "title": "ENVR RED: payload symlink provisioning", "independent": true, "owns": ["scripts/tests/test_provision_lane_worktree.py"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s2", "title": "ENV: provisioner accepts payload symlinks", "independent": false, "owns": ["scripts/workstate/provision_lane_worktree.py"], "depends": ["s1"], "blast": "none", "anchors": []},
    {"id": "s3", "title": "DOCR RED: documented make commands", "independent": true, "owns": ["scripts/test_documented_make_commands.py"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s4", "title": "DOC: doc fixes and test wiring", "independent": false, "owns": ["CLAUDE.md", ".github/copilot-instructions.md", "Makefile"], "depends": ["s3"], "blast": "none", "anchors": []},
    {"id": "s5", "title": "RULR RED: lane manifest rules", "independent": true, "owns": ["scripts/test_check_lane_manifest_rules.py"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s6", "title": "RUL: lane manifest rules checker", "independent": false, "owns": ["scripts/check_lane_manifest_rules.py", "mk/lane-overlaps.mk"], "depends": ["s5"], "blast": "none", "anchors": []},
    {"id": "s7", "title": "LBL: evalops seed data (terra)", "independent": true, "owns": ["benchmarks/experiments/evalops/findings-v0.jsonl", "benchmarks/experiments/evalops/errors-v0.jsonl", "benchmarks/experiments/evalops/qrels-v0.jsonl", "benchmarks/tests/test_evalops_seed_files.py"], "depends": [], "blast": "none", "anchors": []}
  ]
}
```

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests | Model |
|---|---|---|---|---|
| `errfix-1-envr` | `scripts/tests/test_provision_lane_worktree.py` | None | `python3 -m pytest scripts/tests/test_provision_lane_worktree.py -q` (red) | sol, high |
| `errfix-1-env` | `scripts/workstate/provision_lane_worktree.py` | `errfix-1-envr` | same | sol, high |
| `errfix-1-docr` | `scripts/test_documented_make_commands.py` | None | `python3 -m pytest scripts/test_documented_make_commands.py -q` (red) | sol, high |
| `errfix-1-doc` | `CLAUDE.md`, `.github/copilot-instructions.md`, `Makefile` | `errfix-1-docr` | same | sol, high |
| `errfix-1-rulr` | `scripts/test_check_lane_manifest_rules.py` | None | `python3 -m pytest scripts/test_check_lane_manifest_rules.py -q` (red) | sol, high |
| `errfix-1-rul` | `scripts/check_lane_manifest_rules.py`, `mk/lane-overlaps.mk` | `errfix-1-rulr` | same | sol, high |
| `errfix-1-lbl` | `benchmarks/experiments/evalops/{findings,errors,qrels}-v0.jsonl`, `benchmarks/tests/test_evalops_seed_files.py` | Wave 1 admitted | `python3 -m pytest benchmarks/tests/test_evalops_seed_files.py -q` | terra, high |

### Merge Order

1. Wave 1 (sol): `errfix-1-envr`, `errfix-1-docr`, `errfix-1-rulr`.
2. Wave 2 (sol): `errfix-1-env`, `errfix-1-doc` and `errfix-1-rul`, each after its RED lane merges. `errfix-1-env` goes first, because it unblocks dispatch from task-start worktrees.
3. `errfix-1-lbl` (terra) dispatches after wave 1 is admitted. A terra preflight refusal opens a configuration breaker, so it must not gate the sol lanes.
4. Operator slices:
   - S3: any time;
   - S5: before the next large wave;
   - S7: 7 days after S3, and after each WorkBay release.

### Manifest

```bash
make lane-manifest-init TASK=ERRFIX-1 LANE_IDS='errfix-1-envr errfix-1-env errfix-1-docr errfix-1-doc errfix-1-rulr errfix-1-rul errfix-1-lbl' TASK_PLAN=docs/tasks/errfix/ERRFIX-1-error-triage-fixes-task-plan.md
```

Pins on every lane:
- `preferred_backend`: `codex-remote`.
- `preferred_model`: `gpt-6.1-sol`; `gpt-6.1-terra` for `errfix-1-lbl`.
- `preferred_reasoning_effort`: `high`.
- `preferred_speed`: set it explicitly, because a null value quarantines the manifest. Use `fast`, per the 2026-10-28 routing.
- `test_commands`: from the Lanes table.

### Orchestration Mode

- **Codex remote**: lanes dispatch through the orchestrator MCP, from freshly provisioned lane worktrees. One lane per dispatch. Each launch prints the reaper command.
- **Terra check**: `list_available_backends` has no per-model catalogue, so after the sol wave is admitted, `offload_preflight` on the `errfix-1-lbl` worktree with model `gpt-6.1-terra`, effort high, speed fast must pass. If it is refused, record a blocker and ask the operator. There is no fallback model.
- **Reviews**: remote Claude Opus 5.5, xhigh effort, standard speed (Opus fast tier is org-disabled). The WorkBay review-cycle ledger admits gate passes only on `gpt-6.1-sol` xhigh, so the Opus reviews run read-only on the VM outside the ledger, and the merge is an operator step.
- **Shell fallback**: use the repo lane helpers with the same owned paths and tests.

### Landing Rules

These are bottlenecks already hit in this repo, taken from handoff lessons and the prior-work search, with the rule that avoids each one.

| Bottleneck (where seen) | Rule |
|---|---|
| Review rounds that never settle (10-28: ~12 h, 6 docs committed, 0 landed) | At most two reviews, both on remote Claude Opus 5.5 xhigh: one per wave, covering every lane in it. A finding blocks only if it is high and carries an executed failure scenario. No re-review after a verified fix; merge on green. Anything past two goes to the operator |
| Blocks on a technicality, such as style mediums or lint | Advisory findings never block. Lint becomes a `low` `lint(<tool>):` finding, deferred once (sr-011) |
| `plan-accept` returns `no_planning_review_recorded` (R4) | Record the pass with the `LIFECYCLE_ARGS` form |
| A pass verdict is refused while task-wide highs are open | Keep ERRFIX-1 free of open highs; defer them with a rationale [AGT-06] |
| `task-finish` before `plan-accept` strands the doc (decision 20418) | Run `task-finish` only after `plan-accept` lands |
| `task-reap --apply` closes a zero-commit task | Dry run only, until `feature/errfix-1` has a commit |
| One negative probe blocks all codex implementation for 6 h | Terra dispatches only after the sol wave is admitted |
| A stale `result.json` fakes completion, or a terminal event blocks re-dispatch | Clear both before arming a lane |
| A non-success outcome that still landed work (finding 11867: each such lane shipped a defect its own test would catch) | Check `commit_landed`, self-verify and `turn.patch`, and run the lane's declared test, before merging or re-dispatching |
| Finding ids reused across lanes overwrite each other | Use a fresh id range per lane and per review cycle |
| Wide briefs exhaust the wall clock; briefs that forbid commits exit 4 | 1–3 files per lane, and briefs never forbid commits. Slice 4 enforces both |
| The review sandbox has no git history | Embed the diff inline in review briefs |

---

## Consolidated Checklist

**Checklist scope rule:** list work only. Finding status lives in the handoff DB: `review_findings(review={"operation":"list","status":"open","task_ref":"ERRFIX-1"})`.

## Context and Ownership

- [ ] Loaded the rules, contracts and handoff state the slice needs.
- [ ] Confirmed the lane's owned paths do not overlap a live lane (`make lane-overlaps-check`).

### Checklist for Slice 1: Payload symlinks

- [ ] RED tests 1–4 committed; tests 1–2 fail on main.
- [ ] `_plan_overlay` handles payload symlinks; containment is otherwise unchanged.
- [ ] Live: the provisioner exits 0 and `offload_preflight` is clean on the errfix-1 worktree.

### Checklist for Slice 2: Documented commands

- [ ] RED tests 1–4 committed; tests 2–3 fail on main.
- [ ] Three doc lines fixed; the test is in `test-scripts`.

### Checklist for Operator S3: Rows and cursors

- [ ] Proposal list approved by the operator.
- [ ] Rows closed and archived, cursors expired, skips named.

### Checklist for Slice 4: Manifest rules

- [ ] One RED fixture per rule committed.
- [ ] Checker and `lane-manifest-rules TASK=<ref>` target in place; not chained to `check-all`.

### Checklist for Operator S5: Storage

- [ ] Bundles verified and removed; export taken; retention applied.

### Checklist for Slice 6: Labels and qrels

- [ ] Samples exported; terra pre-labels, open codes and qrels committed.
- [ ] 100 human labels recorded.

### Checklist for Operator S7: Replay

- [ ] Replay recorded as a `test_result` 7 days after S3.

## Review Readiness

- [ ] One planning review. A finding blocks only if it can be checked:
  - a contradiction with code at a cited `path:line`;
  - a missing required section;
  - a documented command that does not run.

  Round 3 goes to the operator [FM-08, AGT-12, TEST-33].
- [ ] A handoff decision records each slice, its verification and any contract implications.

## Stretch Goals

- Promote the replay scripts to `scripts/evalops/`, with a `make evalops-replay` target.
- Run `lane-manifest-rules` inside the dispatch path once WorkBay exposes a pre-dispatch hook.

## Success Criteria

| ID | Criterion | Proof |
|---|---|---|
| ERRFIX-SC-1 | Task-start worktrees bootstrap and pass preflight | Slice 1 tests; live provisioner run and `offload_preflight` |
| ERRFIX-SC-2 | Documented commands run as written | Slice 2 test passes in `make test-scripts` |
| ERRFIX-SC-3 | Ambiguous noise falls | ≤ 2 main-target rows; Ambiguous share < 20% over 7 days (baseline 94%) |
| ERRFIX-SC-4 | Bad manifests are refused before dispatch | Slice 4 tests; `make lane-manifest-rules TASK=<ref>` exits 0 on new manifests |
| ERRFIX-SC-5 | Disk headroom without data loss | `.task-state` ≤ 1.1 GB; export taken before retention |
| ERRFIX-SC-6 | The judge and retrieval seed exists | 100 human labels, 100 open codes and qrels; the seed-file test passes |
| ERRFIX-SC-7 | The fixes show in the numbers | Replay per class against the baseline, with a lane-clustered CI |

## Canon authority (Canon v0.26.2)

The corpus check traces each row through its card (where one applies) to the original source text.

| ID | Rule | Src | Corpus check | Applied in |
|---|---|---|---|---|
| FM-08 | Agent loops must be bounded | AI Engineering | Partial: turn cap (ch. 10). Card `reasoning/feedback-bounded-waiting.md` | Review cap; round 3 goes to the operator |
| AGT-12 | Timebox and hand off legibly | bootstrap | Practice label | Review Readiness |
| AGT-06 | Name the skip | bootstrap | Practice label | S3 deferrals |
| TEST-33 | Re-review every requested change | Implementing Effective Code Reviews, ch. 11 | Supported | Review Readiness |
| OBS-02 | One wide event per unit of work | Observability Engineering, ch. 5 | Supported | `result.json` ask |
| EVAL-12 | Validate the judge against humans | AI Engineering | Supported. Card `reasoning/context-obedience-is-a-separate-capability.md` | Slice 6 |
| RLSE-29 | Classify changes and carry evidence | The DevOps Handbook, ch. 23 | Supported | R3 |
| RLSE-02 | Gates are not suggestions | Release It!, ch. 18 | Not checked. Card `reasoning/contract-before-components.md` | Slice 4 fails closed |
| FM-12 | Concept ID, not preferred string | AAT; Semantic Web for the Working Ontologist, ch. 11 | Not checked | R5 |
| OPS-75 | Improve the measured constraint | The DevOps Handbook, ch. 2 | Supported | Slice order; S7 |
| AUDIT-11 | Account for cluster design effect | Sampling: Design and Analysis, ch. 5 | Supported: "Kish (1965) … design effect (abbreviated deff)". Card `reasoning/margin-and-design-effect-before-the-run.md` | Problem Statement; S7 |
| HITL-05 | Agreement is a diagnostic, not the truth | Human-in-the-Loop ML | Supported: highest-agreement items "oversampled the easiest items". Card `reasoning/evidence-before-commitment.md` | Slice 6 |
| MLDATA-03 | Resolve label multiplicity in writing | Designing Machine Learning Systems | Supported: "label multiplicity problem" | Slice 6 |
| RES-02 | Timeout on every blocking call | Release It!, ch. 5 | Supported. Card `reasoning/feedback-bounded-waiting.md` | Slice 2 `make -n` timeout |
| STOR-01 | Every index taxes writes | DDIA, ch. 3 | Supported: "every index slows down writes" | Storage ask |
| STOR-03 | Monitor compaction backlog | DDIA, ch. 3 | Supported | Storage ask |
| STOR-07 | Precompute is an optimization, not the source | DDIA, ch. 3 | Supported. Card `reasoning/correction-at-source.md` | Embeddings sidecar ask |
| STOR-10 | Retain tombstones until safe | Database Internals, ch. 7 | Supported: "Preserving tombstones during compaction is important to avoid data resurrection." | S5 export before retention |
