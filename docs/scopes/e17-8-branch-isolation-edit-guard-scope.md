# E17-8. Branch-Isolation Edit Guard Hardening — Scope Note

- **Date**: 2026-04-16
- **Owning Epic**: E17 (follow-on to E17-4 workflow integrity)
- **Status**: intake — awaiting task-plan drafting

## Motivating Incident

On 2026-04-16 an edit to `terminal-guard.py` landed on `main` instead of the active task's `feature/e17-6` worktree. Root cause:

1. The VS Code workspace root is the main worktree. Native Edit/Write tools resolve relative paths against that root even when the active handoff task targets a feature worktree.
2. The branch-isolation guard's `code_roots` only cover `apps/` and `packages/`. Files under `scripts/hooks/`, `.github/hooks/`, `.claude/`, `mk/`, and root `Makefile` are unprotected — so code-adjacent edits silently land on main.
3. There is no PreToolUse check that compares an edit's target worktree against the active task's `target_worktree_path`. The existing `context_drift` warning only fires on MCP writes (post-hoc).

## Objective

Close all three gaps so "edit lands on the wrong branch" becomes detectable at the moment of the edit, not after `make check-all` fails on main.

## MVP Scope

- Expand `branch_isolation.code_roots` in `docs/agentic/contracts/harness-protocol.yaml` to include `scripts/`, `.github/hooks/`, `.claude/`, and `mk/`; protect root-level `Makefile` through a separate exact-match contract field rather than overloading directory roots.
- Refactor `scripts/hooks/guard-main-branch.sh` and `.github/hooks/guard-main-branch.py` to read the protected path policy from the contract (single source of truth — stops hard-coded path prefixes drifting between the two harnesses).
- Audit the VS Code guard's file-mutating tool surface so native regular-file edits are covered, not just `apply_patch` / `create_file`.
- Add a PreToolUse workspace-root drift check: resolve the edit target's absolute path, compare its containing worktree against the active task's `target_worktree_path`, and block mismatches by default — for any extension, not just code.
- Add a contract-backed allow-list for legitimate main-worktree planning surfaces plus explicit operator escape hatches so docs, task plans, and `CLAUDE.md` remain editable on `main` without weakening the default block posture.
- Wire the new guard into `make check-harness-sync` so contract drift fails CI.

## Success Criteria

- An intentional regression edit to `scripts/hooks/<file>` or `.github/hooks/<file>` from main is blocked with a named error.
- A regular-file mutator outside `apply_patch` / `create_file` is also blocked on a protected path, proving the native edit surface is covered end-to-end.
- An intentional edit routed to the wrong worktree (main-worktree path while active task targets a feature worktree) is blocked by the drift check by default.
- Existing permitted main-branch edits (docs, task plans, `CLAUDE.md`) continue to work without friction through the allow-list / override path.
- `make check-harness-sync` catches a divergence between the branch-isolation contract and actual guard behavior.

## Not-Doing

- Graduating E17-4 Slice 2's warning-only main-change guard to a hard block (separate follow-up once drift telemetry is collected).
- Changing MCP write-enforcement semantics — AHMCP-32 already owns that surface.
- Skill or hook **content** edits beyond the guard wiring itself.
- Open questions about multi-project distribution (tracked separately in the hoist scope note).

## Assumptions

- E17-4 Slice 2 (main-change warning) and Slice 7 (AHMCP-32 MCP write enforcement) are in place. This task builds on both.
- `docs/agentic/contracts/harness-protocol.yaml` (E17-6 Slice 3) is the right canonical surface for the contract values.
- BR-06 test regression (`REVIEW_READY_STATE_SECTIONS` contract-bundle mismatch) is resolved separately before this task starts — it's not in E17-8 scope but blocks clean CI.

## Sequencing

- Drops in after E17-6 merges (uses `harness-protocol.yaml`).
- Independent of the hoist task plan. Can land in parallel with hoist design.
