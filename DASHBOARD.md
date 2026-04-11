# DASHBOARD

_Generated from .task-state/handoff.db. Last generated: 2026-04-10 23:57 UTC_

## Needs Attention
  ⚠ AOMCP-4               1 open (1 medium)
  ⚠ AHMCP-9               blocked: 1 open blocker

## All Tasks

```
  Task                                          Status         Find  Block  Act  Last            
  ────────────────────────────────────────────  ─────────────  ────  ─────  ───  ────────────────
  AHMCP-23                                      done              0      0    0  23:57           
> AHMCP-9                                       blocked           0      1    0  22:37           
  AHMCP-8                                       done              0      0    0  20:52           
  ACE-EXTRACT                                   active            0      0    0  19:55           
  REVIEW-INTAKE-ASSESS                          active            0      0    0  18:06           
  AHMCP-RI-PLAN                                 done              0      0    0  06:23           
  RLS-TEST-DSN-FIX                              done              0      0    0  06:04           
  REVIEW-INTAKE-PROPOSAL                        in_progress       0      0    0  05:47           
  SLR-4                                         done              0      0    0  04:38           
  SESSION-LIFECYCLE-RESILIENCE                  review            1      0    1  04:21           
  SLR-3                                         active            0      0    0  04:12           
  SLR-1                                         done              0      0    0  03:27           
  INVEST-LOCAL-SYNC                             done              0      0    0  2026-04-09 21:35
  AHMCP-22-BR-FIXES                             done              0      0    0  2026-04-09 19:12
  AHMCP-22                                      done              0      0    0  2026-04-09 19:12
  AHMCP-21-BR-FIXES                             done              0      0    0  2026-04-09 19:04
  AHMCP-21                                      done              0      0    0  2026-04-09 19:03
  AOMCP-4                                       done              1      0    0  2026-04-09 18:59
  AHMCP-19                                      done              0      0    0  2026-04-09 16:47
  AHMCP-20                                      done              0      0    0  2026-04-09 06:02
```

## Open Findings

### AOMCP-4
- [MEDIUM] AOMCP-4-BR-01: packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/ace_metrics.py -- AOMCP-4 regressed explicit state-dir handling in `ace_metrics._handoff_memory()`. The function still accepts `state_dir` and uses it for direct SQLite counts, but after the migration it now configures the handoff runtime with `RuntimeConfig.for_repo(workspace_root)` and drops that explicit override. Repro from the merged AOMCP-4 code: monkeypatching `RuntimeConfig.for_repo` while calling `_handoff_memory('task-1', alt_state_dir, root)` shows it is invoked with `state_dir=None`, so the hot-state snapshot reads the default repo `.task-state` while the decision/finding counts come from the caller-supplied `alt_state_dir`. That mixes two different databases inside one metrics payload and breaks fixture/override callers that rely on the documented pass-through behavior of `for_repo()`.

### LANE-ORCH
- [LOW] TECH-DEBT-LANE-1-session-bleed-stash: docs/tasks/tech-debt/lane-orchestration-followups.md:17 -- git stash@{0} on main labeled 'session-bleed accumulated working-tree at codex/e15-7-plan-fixes pre-merge stash 2026-04-08' contains ~17 modified + 4 untracked files from prior sessions across multiple unrelated tasks (BUG-401 auth fix, AHMCP-8 task plan, planning doc edits, hook tweaks, test mods). The stash was created during the merge train cleanup when the root worktree had to be checked out from codex/e15-7-plan-fixes back to main but had accumulated branch-bleed. Each modified file needs to be triaged into its right destination. Some files are already obsolete (overlapped by merged commits), some belong on a new feature branch, some are hook/doc edits that can land on main directly. Do NOT auto-pop — several files will conflict with the local-sync, AOMCP-1, and E15-7 work that has since landed. See the tech-debt doc for triage commands.
- [LOW] TECH-DEBT-LANE-2-stale-long-lived-branches: docs/tasks/tech-debt/lane-orchestration-followups.md:57 -- Three feature branches in refs/heads/ pre-date the current line of development by 100+ commits each and have no linked worktrees: feature/edit-clusters (289 ahead of main), feature/face-detection-foundation (162 ahead), feature/hybrid-roster (205 ahead). They make `git branch -a`, `git log --all`, and tab-completion noisier as more feature work comes down the pipeline, and they are prime candidates for accidental rebase/merge conflicts because their fork points are very old. Recommend converting to archive/* tags so the history is preserved without keeping movable refs.
- [LOW] TECH-DEBT-LANE-3-pre-existing-v2-envelope-test-failure: packages/agent-handoff-mcp/tests/test_handoff_state.py:783 -- test_v2_envelope_no_legacy_mirroring asserts that the v2 response envelope does not mirror fields from `data` to the top level (e.g. active, limits, findings_open). The current implementation still mirrors these fields, so the test fails. This is pre-existing — it was failing before the lane orchestration improvements slice, and the lane orchestration changes do not touch the envelope wrapper. Documented here so it does not get blamed on the wrong slice in the future. The lane-orch slice ran the full test_handoff_state.py suite and saw 104 tests pass + this 1 failure; the 3 new lane-orch tests are all green.
- [LOW] TECH-DEBT-LANE-4-placeholder-worktrees: docs/tasks/tech-debt/lane-orchestration-followups.md:145 -- Three linked worktrees exist with 0 commits ahead of main and clean working trees as of 2026-04-08: context-alt-text-monorepo-ahmcp-mem0 (feature/ahmcp-mem0-feature-candidates), context-alt-text-monorepo-branch-isolation (feature/branch-isolation-guardrails), context-alt-text-monorepo-e16-planning (feature/e16-sync-completion-retention-hardening). They consume disk space and add noise to `git worktree list`. If they are intentional planning surfaces, they should be documented in the relevant task plan or epic file and given a clear lifecycle. Otherwise, they should be removed.

### SESSION-LIFECYCLE-RESILIENCE
- [LOW] SLR-4-BR-01: apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py:221 -- Unused Request parameter on get_observability_session. After the SLR-4 pool split, the breaker checks were removed from get_observability_session (line 221), but the function still declares request: Request in its signature. The parameter is no longer referenced in the function body. FastAPI injects it harmlessly, and tests still pass it, so this is not a bug. However, it may confuse future readers into thinking the observability path consults the business breaker. Could be left in place if a future observability-specific breaker is planned, or removed for clarity.

## Deferred / Won't Fix

### AHMCP-14
- [WONTFIX] [LOW] AHMCP-14-BR-01: scripts/hooks/guard-task-plan-findings.py:60 -- Detection threshold of 3+ consecutive finding bullets is a deliberate calibration to avoid false positives, but it accepts residual risk: a 1- or 2-bullet finding paste still slips past the scanner. The branch-review-guide hard rule (no findings outside MCP) is the authoritative ban — the hook is a defense-in-depth backstop, not the primary enforcement. Calibrated to 0 false positives across the existing task plan corpus, so the threshold is correct for now. If a future incident shows agents pasting 1-2 findings to evade the hook, drop the threshold to 2 in _CONSECUTIVE_THRESHOLD and re-run the corpus scan.
- [WONTFIX] [LOW] AHMCP-14-BR-02: scripts/hooks/test_guard_task_plan_findings.py:1 -- The scanner unit tests live in scripts/hooks/test_guard_task_plan_findings.py but are not picked up by either packages/agent-handoff-mcp/Makefile or packages/agent-orchestrator-mcp/Makefile because both packages' pytest testpaths point only at their own tests/. The tests will only run via direct python -m pytest scripts/hooks/test_guard_task_plan_findings.py invocation or if a future make target is added. This matches the existing convention (.github/hooks/test_*.py have the same gap) so it is not a regression, but it means CI does not auto-verify the scanner.
