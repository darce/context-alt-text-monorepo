# Upstream request (consolidated): orchestration loop — synthesis of the 2026-07-13 VLM + E21-4 retros

**Date**: 2026-07-13 · **Author**: claude-fable-5 · **Supersedes**: [orchestration-loop-retro](../2026-07-13-orchestration-loop-retro/README.md) (VLM) and [e21-loop-retro-and-main-collisions](../2026-07-13-e21-loop-retro-and-main-collisions/README.md) (E21-4). Two independent same-day sessions, two orchestrators, one host. Combined scope: 3 merges to main, 7 grok passes, 12 reviewer subagents, 51 findings closed, 9 remote-gate runs.

## 1. Combined evidence

| Mechanism | Combined data | Verdict |
| --- | --- | --- |
| In-process adversarial reviewers | 12 subagents, 38 verified findings, incl. 3 high that tests/plan-review/self-verify all missed (word-salad token vote; 5-pass timeout bomb; call-site contrast duty) | **Highest ROI in both sessions. The load-bearing quality mechanism.** |
| grok-cli offload | 7 passes: 5 clean first-pass landings, 1 killed-but-salvaged, 1 killed-lost | **Brief style is the success lever** (below); transport unreliable only under local memory pressure |
| Remote OCI gate VM | 9 successful runs, ~124–129s each, 1762–1821 backend tests, zero VM-side errors; 3 *local* background invocations killed; 1 flaky test cost one rerun | **VM: excellent.** All failures were local-host or coverage problems |
| plan-analyze → planning-review | 1 full cycle (E21-4): both stages caught real issues; but ~70% lens overlap between the two skills | Earn their cost; consolidate the skills (below) |
| Continuation artifacts (ORCH-CONTINUITY) | 2 tracks, cold-start-to-productive in 3 tool calls, multiple sessions | Keep; needs first-class syntax (below) |

**Brief-style finding (the key cross-session delta):** E21-4's grok passes were 4/4 first-pass because briefs were *deterministic prescriptions* (literal→token snap tables, per-finding fix text, zero design judgment). The VLM session's judgment-bearing briefs produced the session's only design defects (fixed in review). Rule for the offload skill: **grok gets prescriptions, subagents get problems, the orchestrator keeps judgment.**

## 2. Remote OCI gate VM: performance + expansion

**Verdict: the VM is the most reliable component in the loop.** ~2 minutes per ~1800-test backend run, deterministic exit codes, no infra errors across 9 runs. Fix list:

1. Add `test-js` (npm ci + vitest) and verify the PHP target — E21-4's frontend surface merged gated only by local scoped vitest.
2. De-flake or quarantine `test_worker_timeout_marks_failed_exactly_once` (cancellation timing under xdist; one 4-min rerun).
3. Document foreground-with-timeout as the only supported local invocation (3/3 background invocations were killed by the local host, not the VM).

**What else to offload to the VM (beyond tests)** — it is an idle x86 box with build-essential between gate runs; candidates in leverage order:

1. **Remote lane execution (the big one).** Run the offload worker (grok-cli/codex CLI + lane worktree clone) *on the VM* over Tailscale SSH, exactly like `check-remote` ships HEAD today. This removes the local-RAM cause of both dispatch kills AND the memory-guard friction in one move: the local host keeps only the orchestrator. Workbay already has the transport pattern (`scripts/remote_gate.sh` run/ship model) — generalize it to `dispatch_lane_work(execution_host=remote-gate)`.
2. **Codemap indexing.** `index_repository(mode=moderate)` is the heaviest recurring local job (37k nodes, re-index after every merge). The codebase-graph tool already supports `persistence: true` artifacts (`.codebase-memory/graph.db.zst`) designed for "bootstrap from artifact" — index on the VM post-merge, ship the artifact back.
3. **Mutation-probe review support.** Reviewer mutation runs (break code → run suite → restore) are CPU-bound full-suite work; a `check-remote TARGETS="mutate <patch>"` mode would let reviewers mutation-test against the VM instead of local scoped approximations.
4. **Bake-offs and eval harness** (VLM-4 S3): CPU-side scoring (`report.build_reports`, deterministic re-score) fits the gate VM; only the model inference belongs on the GPU host.
5. Already proven elsewhere: image builds (`REMOTE_BUILD` deploy path). Lint/format sweeps are cheap enough locally — not worth the round-trip.

## 3. Main-writer collisions: synthesis + fix order

Observed across both sessions: untracked `config/lane-orchestration/` on root blocking `plan-accept --local`; main advancing mid-task in *both directions* (VLM merge broke E21-4's baseline; E21-4's merges moved main twice under the VLM loop); three linked worktrees sharing root `DASHBOARD.txt`. Convention (merge-main-into-branch before every gate+merge; `checkout --ours` on plan add/add) held both times — but it is memorized, not enforced.

Fixes, in leverage order (1–2 are one-line-ish; 3–4 are the durable ones):

1. **Give lane-orchestration manifests an owned home**: generate under `.task-state/` (gitignored) or ship a tracked `.gitignore` rule. Untracked files on shared root are the collision primitive.
2. **Scope `plan-accept`'s clean-tree check to the plan path** (ignore untracked paths outside the target file).
3. **Advisory main-write lease**: `.task-state/main-write.lock` `{holder_task_ref, pid, ts, ttl}` taken by `plan-accept`, ff-merges, and MAINT commits; contending make targets print holder+age and wait/abort instead of colliding. Cheap file protocol, no daemon.
4. **Gate-driven merge-back prompt**: `integrity_check(kind=close)` already stores `last_observed_integration_sha` — WARN when `main` has advanced past it, so the merge-main-into-branch step is prompted by the gate, not remembered by the agent. Complement: after any ff-merge to main, record a handoff event that other agents' `make context` surfaces ("main advanced by <task_ref> to <sha>").

## 4. Memory guard: practical disposition (time/disk trades accepted)

Keep the guard; fix its economics. Concrete changes, all trading time or disk for pressure relief:

1. **Backend-declared cost class** (already filed in [hostgov-remote-backend-cost-class](../2026-07-13-hostgov-remote-backend-cost-class/README.md)): remote-API CLIs (grok) admit as `light` — their inference is remote; local footprint is one CLI process. Revert the global `rss_per_heavy_gib=0.5` workaround once landed. Misplaced `host_memory:` config must be a loud validation error, not a silent default.
2. **Wait, don't refuse** (trade time): admission under pressure should queue with backoff (configurable `admission_max_wait_s`, e.g. 300s) instead of rejecting. A dispatch that starts 3 minutes late beats one that fails preflight; the loop is asynchronous anyway.
3. **Daemonize + journal dispatches** (trade disk): run offload passes under `setsid`/launchd with a PID file and an on-disk journal (brief, lane, checkpoint SHAs) in `.task-state/dispatch/<id>/`; on abnormal exit, auto-commit WIP as `wip(offload-salvage): <dispatch_id>`. This converts memory-pressure kills from lost work into a resumable state — the VLM session proved manual salvage works; make it automatic. Disk cost trivial.
4. **Pressure telemetry baseline** (trade disk): persist the preflight admission snapshot per dispatch to `.task-state/hostgov-samples.jsonl`; the guard can then distinguish chronic baseline creep (this 8GB host sits at `warn` idle) from dispatch-caused spikes, and the operator gets evidence for tuning instead of folklore.
5. **The structural fix is §2.1**: move lane execution to the OCI VM and the local guard only ever sees the orchestrator + reviewers.

## 5. Continuation syntax: first-class, like /offload

Today the loop driver is a hand-rolled markdown artifact (`artifacts(record/get, source_label=...)`) with ad-hoc `metadata.loop_state` JSON — it works (3-call cold start, both sessions) but every orchestrator reinvents the shape, and the handoff server's *actual* `continuation` tool + `load_session.data.continuation` auto-injection go unused because packets are session-scoped, not track-scoped.

**Request: a `/continuation` skill + typed op, mirroring the /offload shape:**

- `continuation(operation="save", track="vlm-pipeline", phase=..., next_tasks=[...], blocked={...}, done=[...], priors=[...], on_resume="...", bump=True)` — schema-validated `loop_state`, server-side version bump, one canonical section set (MISSION / LOOP STATE / ON RESUME / PRIORS / GATES).
- `continuation(operation="resume", track=...)` — returns the packet AND its companions (recipe refs) in one call; `load_session` injects the newest packet *for the named track* at session start.
- `/continuation save|resume|status <track>` skill wrapping it, so the PAUSE/REALIGN protocol step becomes one verb instead of a 2k-char artifact upsert each pause.

## 6. Skills: consolidate plan-analyze + planning-review; shared preamble

**Merge the two planning skills.** Measured overlap: both validate TASK_PLAN template conformance, junior-agent implementability, and `path:symbol` anchor grounding; both record `review_mode="planning"` findings and a planning `review_runs` row; plan-analyze's 8 passes ⊂ planning-review's 9-lens checklist plus triage framing. Proposal:

- One `planning-review` skill with `depth: triage | full`. Triage = anchor spot-checks + template validation + findings, session prefix `plan-analyze-*` preserved; full = complete checklist + verdict + acceptance flow. `make plan-analyze` stays as an alias for `plan-review DEPTH=triage`.
- The full-depth precheck ("did triage happen?") becomes an internal stage rather than a cross-skill marker handshake.
- Net: one checklist source (the guide), one skill doc, no behavior loss.

**Hoist the duplicated step-0 ceremony.** Every skill carries the same ~15-line "ensure task scope / MAINT-row / ambiguous-task / WorktreeNotFoundError" preamble. Extract to one shared `skill-preamble.md` the generator injects by reference — skills shrink, the dance stays canonical, and fixes to it land once.

**Cull from briefs/skills (8/8 and 4/4 evidence):** in-brief `/branch-review your own diff` for grok; per-pass token-governance warnings on telemetry-less backends; slice-packet + semantic-reinjection framing for fix-round re-reviews (branch_diff *is* the normal mode there — stop requiring the verdict to apologize for it).

## 7. Consolidated asks (priority order)

1. **Offload judge**: `self_verify.passed && commit_landed` ⇒ `completed_unreviewed`; `needs_guidance` only for an actual question. 8/8 false-negative across sessions. Also: persist full worker reports (~480-char lane-message truncation destroys the pass deliverable).
2. **Remote lane execution on the gate VM** (§2.1) — kills the memory-guard friction and dispatch fragility structurally; interim: daemonized dispatch + salvage checkpoints (§4.3) and wait-queue admission (§4.2).
3. **Collision kit** (§3): lane-manifest home, path-scoped plan-accept, main-write lease, gate-driven merge-back warning.
4. **hostgov cost classes** (§4.1) + loud config validation.
5. **`/continuation` typed op + skill** (§5).
6. **Merge plan-analyze into planning-review with depth param; shared step-0 preamble; cull list** (§6).
7. **Gate VM coverage**: `test-js` target, PHP verification, de-flake the timeout test; document foreground invocation.
8. **Write-API ergonomics** (from VLM retro, still open): auto-fill `expected_revision`, name required fields in the first error, top-level `error` consistently, kwarg naming (`review_run_id`), `manage_worktree_lane` upsert ergonomics; merge `dispatch_lane_work`+`run_offload_pass` into one call.
