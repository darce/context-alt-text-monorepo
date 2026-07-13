# Upstream request: E21-4 loop retro — offload judge/reports, main-writer collisions, gate coverage

> **Superseded by** [2026-07-13-orchestration-consolidated](../2026-07-13-orchestration-consolidated/README.md) — cross-session synthesis with solutions.

**Date**: 2026-07-13 · **Author**: claude-fable-5 (orchestrator) · **Session scope**: E21-4 design-token system, plan→merge in one session (5 slices, 4 grok offload passes, 5 in-process reviewer subagents, 26 findings closed, merged 562cfe79). Corroborates and extends [2026-07-13-orchestration-loop-retro](../2026-07-13-orchestration-loop-retro/README.md) (VLM session, same day, independent evidence).

## Performance evaluation

| Mechanism | Uses | Outcome | Verdict |
| --- | --- | --- | --- |
| grok-cli offload (prescription briefs) | 4 | 4/4 commit landed first pass, self-verify green each time; zero fallback-to-opus needed | **Reliable when briefs are deterministic snap-tables.** Transport solid this session (contrast w/ VLM session kills). |
| In-process adversarial reviewers (slice-scoped + harmonization) | 5 | 26 verified findings incl. 1 high the computed contrast test could NOT catch (call-site duty vs token duty); ~90–100k tokens each | **Highest ROI, again.** Caught what tests, plan review, and grok self-verify all missed. |
| Remote gate `make check-remote` | 5 | ~124s per full backend run; consistent EXIT codes; 1 flake (VLM5-F2B timing test) cost one 4-min rerun; 2 background runs killed by harness → foreground reliable | **VM performs well; run foreground; gate has coverage gaps (below).** |
| plan-analyze → planning-review → plan-accept | 1 cycle | Template check caught structural nonconformance; formal pass added 1 real finding (S4 vacuous-audit risk); acceptance flow blocked by root dirt (below) | Both review stages earned their cost this session. |
| review-parallel merge/retire + resolve-op closes | 1 round | 0 scratch drift, commit-guarded closes all clean; SHA guard correctly rejected one fabricated suffix | Friction that pays. Keep. |

## Learned

1. **needs_guidance is now 8/8 false-negative across two same-day sessions** (4 here + 4 VLM). `commit_landed + self_verify.passed + orchestrator adversarial diff review` is the de-facto judge everywhere. The recorded outcome field is dead weight that every consumer must override.
2. **Worker reports truncate at ~480 chars** in lane messages — grok's per-finding verdict tables and heading-audit decisions were lost, forcing the orchestrator to re-derive them from the diff. The report is the contract deliverable of a pass; truncating it silently converts delegation into re-work.
3. **Token-level acceptance tests cannot see call-site duty errors.** The one high-severity finding (white button text on a 3:1-duty token) passed every token test by construction. Adversarial call-site review is not optional on design-token work.
4. **Deterministic prescription briefs are the grok success lever**: enumerate literal→token snap tables and per-finding fix prescriptions; leave zero design judgment in the lane. 4/4 first-pass landings vs the VLM session's judgment-bearing briefs.
5. **Main advanced mid-task and the merge-back protocol absorbed it** — but only because the plan add/add conflict resolution (`checkout --ours`) is memorized convention, not tooling.

## Cull (empty ceremony)

- **"Run /branch-review on your own diff" in grok briefs** — reconfirmed: never produced a usable verdict; report truncation destroys it even when produced. Cull from briefs (already argued in the VLM retro; +4 data points here).
- **dispatch_lane_work + run_offload_pass as two calls** — the dispatch message's brief is re-supplied to the pass; one call with the brief would do. Candidate API merge.
- **Per-pass "token governance degraded" warnings on grok** (no telemetry backend) — log once per backend registration.
- **`local_requires_clean_tree` on plan-accept counting *untracked* paths** — another agent's untracked lane config blocked acceptance of a plan file that conflicts with nothing. Clean-tree checks for a single-file docs commit should scope to the target path (or at minimum ignore untracked paths outside it).

## Keep (legitimately helpful — do not simplify away)

- Durable continuation artifact + companion recipe (cold start to productive in 3 tool calls, two sessions running).
- Slice-scoped reviewer scratch refs + `merge(retire_sources=true)` + single combined review run.
- Commit-guarded finding closes + full-SHA validation (rejected a fabricated suffix this session — working exactly as designed).
- `close_slice` four-section rationale enforcement — the slice packets became the review fan-out inputs verbatim.
- Pre-merge `integrity_check(kind=close, enforce=true)` — single failure surfaced (status not done) was legitimate.

## Remote OCI gate VM: verdict + gaps

Performed well: 5 runs, ~124s each for 1762–1784 backend tests, stable, no infra errors. Gaps to fix:

1. **No JS/frontend target** — `make check-remote` cannot gate vitest; the E21-4 frontend surface shipped gated only by local scoped vitest. Add a `test-js` gate target (npm ci + vitest run) to the VM image.
2. **PHP target still unverified** (standing driver note; no PHP task has run yet).
3. **Known flake**: `test_worker_timeout_marks_failed_exactly_once` (VLM5-F2B, cancellation timing under xdist) — quarantine or de-flake; it cost a full gate rerun.
4. Background invocations of check-remote were killed twice by the local harness (not the VM) — document foreground-with-timeout as the supported invocation.

## Memory guard (hostgov host_memory admission): keep, do not remove

Removal is the wrong fix. The guard exists for co-resident local-model workers and should stay for them. The actual defects are already filed in [2026-07-13-hostgov-remote-backend-cost-class](../2026-07-13-hostgov-remote-backend-cost-class/README.md): remote-API backends (grok-cli) are force-classed `heavy`, and a misplaced `host_memory:` block fails silently. **Disposition requested: backend-declared cost class (remote-API CLIs admit as `light`/ungated), loud config-validation error on misplaced blocks, and revert of the global `rss_per_heavy_gib=0.5` workaround once cost classes land.** With those, the guard is zero-friction for remote backends and still protects the host from real local inference.

## Main-writer collisions (multi-agent): observed + requested fixes

Observed this session: (a) untracked `config/lane-orchestration/` from another agent blocked `plan-accept --local` (ORCH-CONTINUITY blocker #17); (b) main advanced (72d357f6, VLM merge) mid-task requiring merge-back + re-gate; (c) three linked worktrees active concurrently sharing root `DASHBOARD.txt`/`CURRENT_TASK.json` surfaces.

Requested, in order of leverage:

1. **Declare an owned home for lane-orchestration manifests**: either generate them under `.task-state/` (already gitignored) or ship a tracked `.gitignore` rule for `config/lane-orchestration/`. Ad-hoc untracked files on the shared root are the collision primitive; every clean-tree consumer inherits the breakage.
2. **Scope plan-accept's clean-tree check to the plan path** (see Cull) — collision-tolerant by construction.
3. **Advisory main-write lease**: a `.task-state/main-write.lock` (holder, task_ref, ts, TTL) taken by `plan-accept`, ff-merges, and MAINT commits; other agents' make targets print holder+age instead of failing mid-flight. Convention today, tooling tomorrow — the merge-main-into-branch discipline only works because both agents happened to follow it.
4. **`last_observed_integration_sha` drift hint**: `integrity_check(kind=close)` already stores it; have it WARN when main has advanced past that SHA so the merge-back step is prompted by the gate rather than remembered.

## Requests to workbay (priority order)

1. **Fix the offload judge** (8/8 false-negative): `self_verify.passed && commit_landed` → `outcome=completed_unreviewed`; reserve `needs_guidance` for an actual worker question. (Duplicates VLM retro #1 — now with double the evidence.)
2. **Persist full worker reports**: lift the ~480-char lane-message truncation (store body out-of-line if needed); a pass's verdict table must survive to the orchestrator.
3. **Lane-manifest home + plan-accept path-scoped clean-tree** (collision fixes 1–2 above).
4. **Remote-gate frontend target** (`test-js`) in the gate VM contract; document foreground invocation.
5. **hostgov cost-class disposition** as specified in the hostgov request (keep guard, class by backend).
6. **Merge dispatch+run offload API**; demote per-pass governance-degraded warnings to per-backend.
