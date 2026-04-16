# E17-8. Branch-Isolation Edit Guard Hardening

- **Date**: 2026-04-16
- **Author**: Claude Opus 4
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-8`
- **Review Coverage Target**: 2

---

## Objective

Expand the branch-isolation edit guard to cover all code-adjacent paths (scripts, hooks, config, Makefiles), drive the protected-path list from `harness-protocol.yaml` (single source of truth), and add a PreToolUse worktree-drift check that prompts before edits routed to the wrong worktree when an active task targets a different one.

## Problem Statement

On 2026-04-16 an edit to `.github/hooks/terminal-guard.py` landed on `main` instead of `feature/e17-6`. Three gaps enabled this:

1. **Narrow `code_roots`**: both guard scripts (`guard-main-branch.py`, `guard-main-branch.sh`) hardcode `_PROTECTED_ROOTS = ("apps/", "packages/")`. Files under `scripts/`, `.github/hooks/`, `.claude/`, and `mk/` are unprotected, and the root `Makefile` has no exact-match protected-file mechanism.
2. **Hardcoded path lists**: both guards duplicate the same `code_roots` and `protected_extensions` values inline. `harness-protocol.yaml` (E17-6 Slice 3) defines these canonically, but neither guard reads from it yet.
3. **No worktree-drift detection at edit time**: when the VS Code workspace root is `main` and the active task targets a feature worktree, native edit tools resolve to the main-branch copy. The existing `context_drift` warning only fires after MCP writes (post-hoc); there is no PreToolUse check that compares the edit target's worktree against `target_worktree_path`.

## Constraints

- Guards must remain headless and CI-safe (no MCP introspection at validation time).
- `harness-protocol.yaml` is the single source of truth for `code_roots`, `protected_extensions`, and root-level protected files. Both guards read from it at runtime.
- Existing permitted main-branch edits (docs, task plans, `CLAUDE.md`, markdown) must continue without friction.
- The worktree-drift check must degrade gracefully when no active task is registered (no block; silent pass).
- This task does not graduate E17-4 Slice 2's warning-only main-change guard to a hard block.
- This task does not change MCP write-enforcement semantics (AHMCP-32 owns that surface).

## Current State Analysis

**guard-main-branch.py** (VS Code harness):
- Line 11: `_PROTECTED_ROOTS = ("apps/", "packages/")`
- Line 10: `_CODE_EXTENSIONS` = 10 extensions hardcoded
- Line 13: `_EDIT_TOOLS = {"apply_patch", "create_file"}` — does not cover `replace_string_in_file` or `multi_replace_string_in_file`
- Line 72-74: `_is_protected_code_path()` checks `startswith(_PROTECTED_ROOTS)` + extension match
- No worktree-aware path resolution
- No contract file reading

**guard-main-branch.sh** (Claude Code harness):
- Line 44: hardcodes `^(apps/|packages/)` as a regex
- Same extension set as a regex literal
- No contract file reading
- Warning-only maintenance-task check (lines 49-63) exists but doesn't block

**harness-protocol.yaml** (E17-6, new on `feature/e17-6`):
- `branch_isolation.code_roots`: currently `["apps/", "packages/"]`
- `branch_isolation.protected_extensions`: currently 10 extensions
- No `code_roots` entry for `scripts/`, `.github/`, `.claude/`, `mk/`
- No `root_protected_files` entry for root-level code-adjacent files such as `Makefile`

**check_harness_sync.py** (E17-6, new):
- Validates hooks section only; does not cross-check that guard scripts read the contract's `code_roots`

## Out of Scope

- Graduating E17-4 Slice 2's warning-only main-change guard to a hard block (separate follow-up).
- MCP write branch enforcement changes (AHMCP-32).
- Skill or hook content edits beyond the guard wiring.
- Multi-project distribution / hoist concerns.

## Target Outcome

- An edit to any file with a protected extension under `scripts/`, `.github/hooks/`, `.claude/`, `mk/`, or another contracted `code_root`, plus any contracted root protected file, is blocked on `main` with a named error.
- An edit routed to the main-worktree path while the active task targets a different worktree is warned or blocked by the drift check.
- Both guards read `code_roots` and `protected_extensions` from `harness-protocol.yaml` at runtime.
- `make check-harness-sync` catches a divergence between the contract's `code_roots` and actual guard behavior.
- Existing permitted main-branch edits (docs, task plans, `CLAUDE.md`) continue to work.

## Context Loading

- Guard scripts: `.github/hooks/guard-main-branch.py`, `scripts/hooks/guard-main-branch.sh`
- Harness contract: `docs/agentic/contracts/harness-protocol.yaml`
- Harness sync validator: `scripts/check_harness_sync.py`
- VS Code hook definitions: `.github/hooks/terminal-guard.json`
- Claude hook definitions: `.claude/settings.json`
- Branch isolation rules: `docs/agentic/rules/development-workflow.md` (Branch Isolation Protocol)
- E17-4 delivery reference: `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md`
- Motivating incident: `docs/scopes/e17-8-branch-isolation-edit-guard-scope.md`
- Telemetry log: `.task-state/branch_isolation_guard.jsonl`
- DASHBOARD naming drift investigation: `docs/assessments/dashboard-md-vs-txt-guidance-drift-investigation-2026-04-16.md` (motivates the Slice 3 lint guard on stale `DASHBOARD.md` references and the `.gitignore` entry for untracked strays; the rename itself lives in E17-7 Slice 4, not here)

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility | Verification |
|---|---|---|---|---|---|
| `harness-protocol.yaml` `branch_isolation` | `docs/agentic/contracts/` | `code_roots=["apps/", "packages/"]`; no root file list | add `scripts/`, `.github/`, `.claude/`, `mk/`; add `.mk`; add `root_protected_files=["Makefile"]` | non-breaking expansion | `make check-harness-sync` passes |
| `guard-main-branch.py` | `.github/hooks/` | hardcoded `_PROTECTED_ROOTS` tuple | read from `harness-protocol.yaml` at runtime | behavior-preserving refactor | blocked-path test cases |
| `guard-main-branch.sh` | `scripts/hooks/` | hardcoded regex `^(apps/|packages/)` | read from `harness-protocol.yaml` via `python3 -c` extraction at runtime | behavior-preserving refactor | blocked-path test cases |
| `guard-main-branch.py` `_EDIT_TOOLS` | `.github/hooks/` | `{"apply_patch", "create_file"}` | audit and cover every regular-file mutator, at minimum `apply_patch`, `create_file`, `replace_string_in_file`, `multi_replace_string_in_file` | non-breaking expansion | edit via those tools is blocked on main |
| Worktree drift PreToolUse (new) | `.github/hooks/` + `.claude/settings.json` | does not exist | new hook comparing edit target worktree to `target_worktree_path` | n/a | drift is warned/blocked; no-task degrades silently |
| `check_harness_sync.py` | `scripts/` | validates hooks only | add `code_roots` drift check | non-breaking extension | intentional `code_roots` mismatch fails |

## Proposed Solution

Three slices deliver the guard hardening. They land in order:

1. Expand `code_roots` in the contract and refactor both guards to read from it
2. Add worktree-drift PreToolUse check
3. Extend `check_harness_sync.py` with `code_roots` validation

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| Contract | `docs/agentic/contracts/harness-protocol.yaml` | expand `code_roots`; add `.mk` to `protected_extensions`; add `root_protected_files: ["Makefile"]` |
| VS Code guard | `.github/hooks/guard-main-branch.py` | read `code_roots` + `protected_extensions` + `root_protected_files` from contract; audit missing edit tools |
| Claude guard | `scripts/hooks/guard-main-branch.sh` | read `code_roots` + `protected_extensions` + `root_protected_files` from contract via `python3 -c` |
| Worktree drift (new) | `.github/hooks/guard-worktree-drift.py` | new PreToolUse hook; compare edit path worktree to `target_worktree_path` |
| VS Code hooks | `.github/hooks/terminal-guard.json` | register `guard-worktree-drift.py` as PreToolUse |
| Claude drift hook (new) | `scripts/hooks/guard-worktree-drift.sh` | new PreToolUse hook; compare edit path worktree to `target_worktree_path` |
| Claude hooks | `.claude/settings.json` | register `guard-worktree-drift.sh` as PreToolUse |
| Harness contract | `docs/agentic/contracts/harness-protocol.yaml` | add worktree-drift hook entry |
| Sync validator | `scripts/check_harness_sync.py` | add `code_roots`/`protected_extensions` drift check |
| Branch isolation docs | `docs/agentic/rules/development-workflow.md` | document expanded `code_roots` and worktree drift guard |

## Verification Strategy

- `make check-harness-sync` passes after all slices.
- An edit to `scripts/hooks/<file>.py` on `main` is blocked with a named error.
- An edit to `.github/hooks/<file>.py` on `main` is blocked with a named error.
- An edit to `.claude/skills/<file>/SKILL.md` on `main` is permitted; `.md` remains outside `protected_extensions`, which verifies false-positive avoidance.
- An edit to `mk/handoff.mk` on `main` is blocked after `.mk` is added to `protected_extensions`.
- An edit to root `Makefile` on `main` is blocked via `root_protected_files`.
- An edit routed to `/Users/.../context-alt-text-monorepo/.github/hooks/terminal-guard.py` while the active task targets `/Users/.../context-alt-text-monorepo-e17-8/` is warned by the drift check.
- With no active task registered, the drift check passes silently.
- Docs and markdown edits on `main` continue to work.
- `make check-all` stays green.

## Slice Delivery

### Slice 1: Expand `code_roots` and Refactor Guards to Read from Contract

**Goal**: both guards read the path list from `harness-protocol.yaml` instead of hardcoding it; the contract expands the protected surface.

Changes:

- Expand `harness-protocol.yaml` `branch_isolation.code_roots` to include: `scripts/`, `.github/`, `.claude/`, `mk/`.
- Add `.mk` to `branch_isolation.protected_extensions`.
- Add `branch_isolation.root_protected_files: ["Makefile"]`.
- Refactor `guard-main-branch.py`:
  - Load `code_roots`, `protected_extensions`, and `root_protected_files` from the contract YAML at runtime.
  - Fall back to the current hardcoded values if the contract file is missing (CI resilience).
  - Audit the VS Code harness file-mutating tool surface and expand `_EDIT_TOOLS` to every regular-file mutator; at minimum add `replace_string_in_file` and `multi_replace_string_in_file`.
- Refactor `guard-main-branch.sh`:
  - Load `code_roots`, `protected_extensions`, and `root_protected_files` from the contract via an embedded `python3 -c` extraction.
  - Fall back to the current hardcoded regex if the contract file is missing.
- Keep the `startswith(code_root) + extension_match` semantic unchanged; only the source of the lists changes.

Design decision: root-level code-adjacent files are protected through `root_protected_files`, starting with `Makefile`. Additional root files stay out of scope unless the same accidental-main-edit pattern recurs.

Proof:

- An edit to `scripts/check_skills.py` on `main` is blocked.
- An edit to `.github/hooks/terminal-guard.py` on `main` is blocked.
- An edit to root `Makefile` on `main` is blocked.
- An edit to `docs/tasks/foo.md` on `main` is permitted.
- An edit to `CLAUDE.md` on `main` is permitted.
- Removing `scripts/` from the contract's `code_roots` causes `make check-harness-sync` to detect drift (Slice 3 dependency; manual verification until then).
- The guards work when the contract file is missing (fallback path).

### Slice 2: Worktree-Drift PreToolUse Check

**Goal**: detect at edit time when a file is being modified in the wrong worktree.

Changes:

- Add `.github/hooks/guard-worktree-drift.py`:
  - Reads the active task's `target_worktree_path` from `handoff.db` via the Python API (not MCP; hooks run before MCP is available).
  - Resolves the edit target's absolute path and determines its containing worktree via `git rev-parse --show-toplevel`.
  - If the edit's worktree differs from `target_worktree_path`, emit a `permissionDecision: "ask"` with a descriptive reason naming both paths.
  - If no active task is registered, or `target_worktree_path` is null, pass silently (exit 0).
  - Performance budget: must complete in <200ms. Use a subprocess call to `git rev-parse --show-toplevel` (cached by the OS) and a single SQLite read.
- Add `scripts/hooks/guard-worktree-drift.sh` for Claude Code rather than extending `guard-main-branch.sh`; keep the drift prompt as a separate single-responsibility hook.
- Register the new hook in `.github/hooks/terminal-guard.json` and `.claude/settings.json`.
- Add the hook entry to `harness-protocol.yaml`.

Escalation policy:
- Default: `"ask"` (confirmation prompt). The user can override to proceed.
- Future: graduate to `"block"` after telemetry confirms low false-positive rate.

Proof:

- An edit to `/Users/.../context-alt-text-monorepo/.github/hooks/terminal-guard.py` while active task targets `/Users/.../context-alt-text-monorepo-e17-8/` triggers the drift prompt.
- An edit to `/Users/.../context-alt-text-monorepo-e17-8/scripts/check_skills.py` while active task targets the same worktree passes silently.
- With no active task (fresh session), all edits pass silently.
- The hook completes in <200ms (measure with `time python3 .github/hooks/guard-worktree-drift.py < test_payload.json`).

### Slice 3: `check_harness_sync` Code-Roots Validation + Dashboard Naming Lint

**Goal**: CI catches divergence between the contract's `code_roots`/`protected_extensions` and the actual guard implementations, and catches reintroductions of the stale `DASHBOARD.md` name once E17-7 Slice 4 normalizes it to `DASHBOARD.txt`.

Changes:

- Extend `scripts/check_harness_sync.py` with a `_check_branch_isolation()` function that:
  - Reads `code_roots` and `protected_extensions` from `harness-protocol.yaml`.
  - Parses `guard-main-branch.py` to extract the runtime-loaded or fallback `_PROTECTED_ROOTS` and `_CODE_EXTENSIONS`.
  - Parses `guard-main-branch.sh` to extract the regex patterns for roots and extensions.
  - Reports any contract values missing from either guard's runtime surface.
- Add a `_check_dashboard_naming()` function to the same validator that:
  - Greps tracked non-archive markdown (`git ls-files '*.md'` minus `docs/archive/**` and `**/tests/**`), the root `Makefile`, and `packages/agent-orchestrator-mcp/src/**/dashboard_extension.py` for the literal string `DASHBOARD.md`.
  - Fails with a named diff if any hit remains after E17-7 Slice 4 has landed. Depends on E17-7 Slice 4 — land this lint *after* the rename so the first run is clean.
  - Rationale documented in `docs/assessments/dashboard-md-vs-txt-guidance-drift-investigation-2026-04-16.md`.
- Add `DASHBOARD.md` to the repo-root `.gitignore` so stray untracked copies (produced by older local clones or pre-AHMCP-23 artifacts) stop surfacing in `git status` and cannot be accidentally committed.
- Wire both new checks into `make check-harness-sync`.

Proof:

- `make check-harness-sync` passes after Slices 1-2 and after E17-7 Slice 4 lands the dashboard-name normalization.
- Removing a `code_root` entry from the contract (but leaving it in the guard fallback) causes the validator to detect drift.
- Adding a new `code_root` to the contract without updating the guards causes the validator to detect drift.
- Reintroducing `DASHBOARD.md` into any tracked non-archive markdown, the Makefile, or the `dashboard_extension.py` docstring causes the validator to fail with a named line reference.
- A manually dropped `DASHBOARD.md` in the repo root does not appear in `git status`.

---

## Consolidated Checklist

### Context and Ownership

- [ ] Verify E17-6 has merged (harness-protocol.yaml is on main)
- [ ] Confirm the guard scripts still use hardcoded path lists (no interim changes)
- [ ] Confirm `check_harness_sync.py` does not already validate `code_roots`

### Checklist for Slice 1: Expand `code_roots` + Refactor Guards

- [ ] `harness-protocol.yaml` `code_roots` includes `scripts/`, `.github/`, `.claude/`, `mk/`
- [ ] `harness-protocol.yaml` adds `.mk` to `protected_extensions`
- [ ] `harness-protocol.yaml` adds `root_protected_files: ["Makefile"]`
- [ ] `guard-main-branch.py` reads from contract at runtime with hardcoded fallback
- [ ] `guard-main-branch.py` `_EDIT_TOOLS` covers every regular-file mutator in the VS Code harness
- [ ] `guard-main-branch.sh` reads from contract at runtime with hardcoded fallback via `python3 -c`
- [ ] Edits to `scripts/`, `.github/`, `.claude/`, `mk/` code files on `main` are blocked
- [ ] Root `Makefile` edits on `main` are blocked
- [ ] Edits to docs, markdown, and permitted config on `main` are not blocked
- [ ] Guard works when contract file is missing (fallback path)

### Checklist for Slice 2: Worktree-Drift Check

- [ ] `guard-worktree-drift.py` reads `target_worktree_path` from handoff DB
- [ ] `guard-worktree-drift.sh` mirrors the same drift check for Claude Code
- [ ] Edit to wrong-worktree path triggers `"ask"` confirmation
- [ ] No active task or null `target_worktree_path` passes silently
- [ ] Hook registered in `terminal-guard.json` and `.claude/settings.json`
- [ ] Hook registered in `harness-protocol.yaml`
- [ ] Performance: <200ms completion time

### Checklist for Slice 3: Sync Validator Extension + Dashboard Naming Lint

- [ ] `check_harness_sync.py` validates `code_roots` and `protected_extensions` against both guards
- [ ] `check_harness_sync.py` validates absence of `DASHBOARD.md` in tracked non-archive markdown, the Makefile, and the `dashboard_extension.py` docstring (depends on E17-7 Slice 4 completion)
- [ ] `.gitignore` excludes `DASHBOARD.md`
- [ ] `make check-harness-sync` passes after Slices 1-2 and after E17-7 Slice 4
- [ ] Intentional contract drift is detected and reported
- [ ] Intentional `DASHBOARD.md` reintroduction is detected and reported
- [ ] `make check-all` stays green

## Review Readiness

- [ ] `make check-all` stays green after each slice
- [ ] No MCP write-enforcement changes are included
- [ ] No guard graduation to hard-block is included

## Success Criteria

- [ ] Both guards read `code_roots` and `protected_extensions` from `harness-protocol.yaml`
- [ ] Root `Makefile` is protected through `root_protected_files`
- [ ] `scripts/`, `.github/`, `.claude/`, and `mk/` code files are protected on `main`
- [ ] Worktree-drift check warns when edits target the wrong worktree
- [ ] `make check-harness-sync` catches `code_roots` drift between contract and guards
- [ ] `make check-harness-sync` catches `DASHBOARD.md` reintroductions after E17-7 Slice 4 landed the rename
- [ ] `.gitignore` prevents stray untracked `DASHBOARD.md` from polluting `git status`
- [ ] Existing permitted main-branch edits (docs, markdown, configs) work without friction
