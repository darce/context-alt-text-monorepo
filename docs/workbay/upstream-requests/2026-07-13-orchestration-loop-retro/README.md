# Upstream request: orchestration-loop friction — evidence from the 2026-07-13 VLM session

**Date**: 2026-07-13 · **Author**: claude-fable-5 (orchestrator) · **Session scope**: VLM-5 close-out (18 findings) + VLM-4 S1–S2 (implement, 2 review rounds, 7 findings), both merged to main. Backends used: grok-cli offload (3 dispatches), in-process Agent subagents (7), inline implementation, remote test gate.

## Performance evaluation (evidence, not vibes)

| Mechanism | Uses | Outcome | Verdict |
| --- | --- | --- | --- |
| In-process adversarial reviewers (Agent tool, scratch refs, merge/retire) | 5 | 12 real defects incl. 2 high (word-salad token vote, 5-pass timeout bomb) and mutation-proven test gaps; zero false pipelines | **Highest ROI. Keep, invest.** |
| In-process implementer subagent (VLM-4 S2b) | 1 | 648-line commit, green, correctly deferred handoff writes to coordinator | **Works. Keep.** |
| grok-cli offload | 3 | 1 clean success (VLM-5 F2 tests); 1 killed-but-salvaged (S1, found a real prod gap); 1 killed-no-output (S2a) | **Value real, transport unreliable on this host.** |
| Inline implementation by orchestrator | 2 (S2a core, both fix cycles) | Fastest path for well-specified pure modules and review fixes | Delegation has a floor; don't offload below it. |
| Remote gate (`make check-remote`) | 4 | Green each time (~2.5 min); 1 bg run killed → foreground reliable | Keep; run foreground. |

## What was learned

1. **Adversarial review with mutation probes is the load-bearing quality mechanism.** It falsified a plan assumption (step-wise token vote unreachable on one-shot llama.cpp) that survived planning review, implementation, and self-verify.
2. **Judge offloads by artifacts, not pass status.** `needs_guidance` + `failed_stage=review` is now 4/4 a false negative; `commit_landed` + independent test rerun + adversarial diff review is the real verdict.
3. **Killed dispatches are recoverable**: worktree salvage (status → test → commit → decision-with-salvage-note) turned a killed pass into a landed slice.
4. **Stale `__pycache__` from reviewer mutation runs poisons later test runs** (same-size edits defeat pyc invalidation) — new defect prior.
5. **Concurrent main writers are survivable** with merge-main-into-branch before every gate+merge, but only by convention; nothing enforces it.

## What should be culled (empty ceremony)

- **"Run /branch-review on your own diff" in grok briefs**: the review stage has never produced a usable verdict (4/4 false-negative) and the orchestrator independently reviews anyway. Cull from briefs until the judge is fixed.
- **Per-pass token-budget theater on grok**: no token telemetry → "governance degraded" warning every pass. Log once per backend, not per dispatch.
- **Slice-packet enumeration + semantic-reinjection in `/review-parallel` for fix-cycle re-reviews**: every round this session used the branch_diff fallback (auto-fix commits have no slice packets). The fallback IS the normal mode for fix rounds — promote it; stop framing it as a degradation that needs justifying in the verdict.
- **`WORKBAY_ALLOW_BASH_MAIN_WRITE` bypasses on linked-worktree commands**: ~10 bypasses this session for formatter/pytest/commit commands that begin `cd <linked-worktree> &&` — all false positives, each logged, diluting the audit trail the guard exists to keep.

## What legitimately helps (keep, do not "simplify" away)

- Brief contract (END-STATE, scoped TEST_CMD + baseline, verified anchors, out-of-scope, defect priors, anti-pattern list) — grok and subagents both delivered against it.
- `offload_preflight` (admission + codemap freshness) — cheap, caught nothing this session but the check is right.
- Scratch-ref review namespace + `merge(retire_sources=true)` + single `review_run` + verdict decision — clean audit shape, zero drift.
- Commit-guarded finding closes with full SHAs + resolution notes — friction that pays.
- The durable loop artifact (ORCH-CONTINUITY) — cold-started this session in 3 tool calls.

## Requests to workbay (priority order)

1. **Fix the offload pass judge.** `self_verify.passed && commit_landed` must yield `outcome=completed` (or `completed_unreviewed`); reserve `needs_guidance` for an actual worker question. The current shape forces every orchestrator to hard-code "ignore the verdict."
2. **Write-API ergonomics.** One session hit five serial write rejections that each cost a failed call + inspect + retry: `close_slice` demanding `expected_revision` (auto-fetch it server-side), descendant-commit closes demanding `resolution_notes` (name it in the first error), `record_review_run`'s kwarg being `review_run_id` (docs say `run_id`), `manage_worktree_lane` upsert requiring `worktree_path` for an existing lane, and `ok=false` responses burying the reason in `data.error` while top-level `error` is null. Uniform: top-level `error`, server-side auto-fill where the server already knows the value.
3. **First-class provenance on MCP writes (or a thin CLI).** Every one of ~15 handoff writes was a Bash heredoc (`configure_runtime` + actor dict) because the MCP tool path loses actor/branch attribution. Either accept a full actor on the MCP tools reliably, or ship `workbay handoff <op> --task-ref --sha ...` so orchestrators stop templating Python.
4. **Main-branch guard: linked-worktree awareness.** A command whose first token sequence is `cd <registered-linked-worktree> && ...` cannot write to main; skip the block/bypass dance. Registered worktrees are known to the daemon.
5. **`task-start` should finish the job.** Auto-rsync `Makefile.d/` + `scripts/` overlays, copy `.workbay/remote-gate.env`, and produce a venv that can collect the app's tests (this session's slim root venv lacked fastapi/sqlalchemy → collection errors, worked around via `../../.venv`). Fix the `task-finish` hang (manual teardown is now muscle memory, which is the failure mode).
6. **Dispatch survivability.** Offload passes should run daemonized (survive parent Bash kill) and write a salvage checkpoint (auto-commit WIP with a `wip(offload)` marker) on abnormal exit. 2/3 dispatches this session died with the parent process on a memory-pressured host.
7. **Concurrent-main coordination.** Two mid-loop main advances by another agent (e21-4). Convention held, but workbay should offer an advisory merge-lock or at minimum a `context_drift`-style warning on `git merge` into main when another lane merged within N minutes. Related: lane materialization dropped untracked `config/lane-orchestration/` into the ROOT worktree — lane state belongs under `.task-state/` or the lane worktree.

## Cross-references

- ORCH-CONTINUITY blocker (2026-07-13): main-branch collision conventions.
- `error_class=cli_failure` events on VLM-4 (dispatch kills).
- Loop artifact `vlm-pipeline-implementation-loop-v1` v6 §ON RESUME (proven workarounds).
- Memory: `project_background_dispatch_kills_20260713`.
