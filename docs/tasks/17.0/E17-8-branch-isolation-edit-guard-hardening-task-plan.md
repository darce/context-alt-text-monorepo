# E17-8. Branch-Isolation Edit Guard Hardening

- **Date**: 2026-04-16
- **Author**: Claude Opus 4
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-8`
- **Review Coverage Target**: 2
- **Hard Prerequisites**: E17-6 has merged to `main` (verified 2026-04-16: commit `8454d409 feat(E17-6): complete Phase 3 core retrofit + BR-04/05/06 fixes` plus follow-on BR cleanup through `d221e98f`). `harness-protocol.yaml` and `scripts/check_harness_sync.py` are present on `main`. This plan is ready to branch from `main` immediately.

---

## Objective

Expand the branch-isolation edit guard to cover all code-adjacent paths (scripts, hooks, config, Makefiles), drive the protected-path list from `harness-protocol.yaml` (single source of truth, per-project configurable), and add a PreToolUse worktree-drift check that **blocks** edits routed to the wrong worktree when an active task targets a different one — with an explicit per-project `permitted_main_surfaces` allow-list for the legitimate main-worktree planning edits (task plans, assessments, agentic docs, dashboard artifacts) and an `ALT_ALLOW_WORKTREE_DRIFT=1` escape hatch.

Retroactive landing note (2026-04-18, revised post-E17-8-BR-20): the planning-doc surfaces that were originally described as generic main-branch exceptions landed as explicit entries in a NEW contract-governed protected-main-surface list, `branch_isolation.protected_main_surfaces` — NOT in `permitted_main_surfaces`. The two surfaces have opposite meanings: `protected_main_surfaces` (planning docs: `docs/tasks/**/*.md`, `docs/assessments/**`, `docs/scopes/**`, `docs/epics/**`, `docs/specs/**`, `docs/adrs/**`, and 5 `packages/*/docs/**` variants) are additively BLOCKED on main via `is_branch_isolation_protected_path` → `find_protected_main_surface`; `permitted_main_surfaces` (operator-maintained docs/config: `CLAUDE.md`, `.github/copilot-instructions.md`, `docs/agentic/BOOTSTRAP.md`, `docs/agentic/instructions.md`, `docs/agentic/contracts/**`, `docs/agentic/rules/**`, `docs/agentic/maps/**`, `docs/agentic/generated/**`, `docs/tasks/archive/**`, `DASHBOARD.txt`, `CURRENT_TASK.json`) pass the drift check with a trace log. Both lists ship 11 entries each in this repo's `harness-protocol.yaml`. This plan now reflects that shipped shape rather than the earlier broader prose.

## Problem Statement

On 2026-04-16 an edit to `.github/hooks/terminal-guard.py` landed on `main` instead of `feature/e17-6`. Five gaps enabled this:

1. **Narrow `code_roots`**: both guard scripts (`guard-main-branch.py`, `guard-main-branch.sh`) hardcode `_PROTECTED_ROOTS = ("apps/", "packages/")`. Files under `scripts/`, `.github/hooks/`, `.claude/`, and `mk/` are unprotected, and the root `Makefile` has no exact-match protected-file mechanism.
2. **Hardcoded path lists**: both guards duplicate the same `code_roots` and `protected_extensions` values inline. `harness-protocol.yaml` (E17-6 Slice 3) defines these canonically, but neither guard reads from it yet.
3. **No worktree-drift detection at edit time**: when the VS Code workspace root is `main` and the active task targets a feature worktree, native edit tools resolve to the main-branch copy. The existing `context_drift` warning only fires after MCP writes (post-hoc); there is no PreToolUse check that compares the edit target's worktree against `target_worktree_path`.
4. **No allow-list for legitimate main-worktree edits**: even if a drift check existed, operators routinely need to update task plans, assessments, and agentic docs on `main` while feature work proceeds in worktrees. Without an explicit allow-list encoded in the per-project contract, any drift check strict enough to catch the terminal-guard.py incident would also block routine planning updates.
5. **Warn-only posture has failed**: E17-4 Slice 2 already landed a warning-only main-change guard. The 2026-04-16 incident demonstrates that agents do not respect warning-level signals during implementation. The drift check must default to **block**, not prompt; the escape hatch belongs on the operator's side of the wire (env var), not inside the hook's escalation policy.

## Constraints

- Guards must remain headless and CI-safe (no MCP introspection at validation time).
- `harness-protocol.yaml` is the single source of truth for `code_roots`, `protected_extensions`, root-level protected files, **and the new `permitted_main_surfaces` allow-list**. Both guards read from it at runtime.
- The allow-list is **per-project configurable**: every project that adopts the harness writes its own `permitted_main_surfaces` entries in its own `harness-protocol.yaml`. The list shipped in this repo is this repo's policy, not a framework default.
- The worktree-drift check's default posture is **block** (not ask, not warn). Warn-only was tried and demonstrably failed.
- Escape hatches: (a) `ALT_ALLOW_WORKTREE_DRIFT=1` environment variable downgrades the block to a warn-only pass for the current shell; (b) task refs matching the existing `MAINT-*` convention pass silently (consistent with main-branch maintenance-task rule); (c) edit paths matching any `permitted_main_surfaces` glob pass with a trace log.
- The worktree-drift check must degrade gracefully when no active task is registered (no block; silent pass).
- Edit paths must be resolved to an absolute canonical form (`Path(target).resolve()`) before matching against worktree roots or glob patterns — never match against tool-supplied relative paths.
- Existing permitted main-branch edits (docs, task plans, `CLAUDE.md`, markdown) continue without friction after the allow-list lands.
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

**harness-protocol.yaml** (E17-6, merged to `main`):
- `branch_isolation.code_roots`: currently `["apps/", "packages/"]`
- `branch_isolation.protected_extensions`: currently 10 extensions
- No `code_roots` entry for `scripts/`, `.github/`, `.claude/`, `mk/`
- No `root_protected_files` entry for root-level code-adjacent files such as `Makefile`
- **No `permitted_main_surfaces` entry** — the allow-list concept does not exist yet

**check_harness_sync.py** (E17-6, merged to `main`):
- Validates hooks section only; does not cross-check that guard scripts read the contract's `code_roots`
- Does not validate the new `permitted_main_surfaces` block exists or has non-empty entries

## Out of Scope

- Graduating E17-4 Slice 2's warning-only main-change guard to a hard block (separate follow-up).
- MCP write branch enforcement changes (AHMCP-32).
- Skill or hook content edits beyond the guard wiring.
- Multi-project distribution / hoist concerns for the allow-list pattern (each project owns its own list; no cross-project sharing mechanism in this task).
- Interactive per-edit override UI (the env var escape hatch is the operator-side contract).

## Target Outcome

- An edit to any file with a protected extension under `scripts/`, `.github/hooks/`, `.claude/`, `mk/`, or another contracted `code_root`, plus any contracted root protected file, is blocked on `main` with a named error.
- An edit routed to the main-worktree path while the active task targets a different worktree is **blocked** by the drift check with a named `WorkspaceRootDriftError`, unless the edit path matches a `permitted_main_surfaces` glob, or the active task ref starts with `MAINT-`, or `ALT_ALLOW_WORKTREE_DRIFT=1` is set.
- Both guards read `code_roots`, `protected_extensions`, `root_protected_files`, and `permitted_main_surfaces` from `harness-protocol.yaml` at runtime.
- `harness-protocol.yaml` ships a default `permitted_main_surfaces` block covering task plans, assessments, scopes, epics, `CLAUDE.md`, `docs/agentic/BOOTSTRAP.md`, agentic contracts/rules/maps, `DASHBOARD.txt`, `CURRENT_TASK.md`, and the archived-task view — documented as per-project configurable, not as a framework default.
- `make check-harness-sync` catches a divergence between the contract's `code_roots`, `permitted_main_surfaces`, and actual guard behavior.
- Existing permitted main-branch edits (docs, task plans, `CLAUDE.md`) continue to work.
- The E17-7 Slice 2 checkbox-sync hook (which writes to `docs/tasks/**/*.md` on `main`) does not trip the drift block because its target is explicitly allow-listed.

## Context Loading

- Guard scripts: `.github/hooks/guard-main-branch.py`, `scripts/hooks/guard-main-branch.sh`
- Harness contract: `docs/agentic/contracts/harness-protocol.yaml`
- Harness sync validator: `scripts/check_harness_sync.py`
- VS Code hook definitions: `.github/hooks/terminal-guard.json`
- Claude hook definitions: `.claude/settings.json`
- Branch isolation rules: `docs/agentic/rules/development-workflow.md` (Branch Isolation Protocol)
- E17-4 delivery reference: `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md`
- E17-7 Slice 2 coordination: [`docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md`](E17-7-handoff-evolution-and-portable-workflow-task-plan.md) — checkbox-sync hook target surface
- Motivating incident: `docs/scopes/e17-8-branch-isolation-edit-guard-scope.md`
- Telemetry log: `.task-state/branch_isolation_guard.jsonl`
- DASHBOARD naming drift investigation: `docs/assessments/dashboard-md-vs-txt-guidance-drift-investigation-2026-04-16.md` (motivates the Slice 3 lint guard on stale `DASHBOARD.md` references and the `.gitignore` entry for untracked strays; the rename itself lives in E17-7 Slice 4, not here) <!-- lint-dashboard-txt: allow -->

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility | Verification |
|---|---|---|---|---|---|
| `harness-protocol.yaml` `branch_isolation.code_roots` | `docs/agentic/contracts/` | `["apps/", "packages/"]` | add `scripts/`, `.github/hooks/`, `.claude/`, `mk/` | non-breaking expansion | `make check-harness-sync` passes |
| `harness-protocol.yaml` `branch_isolation.protected_extensions` | `docs/agentic/contracts/` | 10 extensions | add `.mk` | non-breaking expansion | edit to `mk/handoff.mk` on main is blocked |
| `harness-protocol.yaml` `branch_isolation.root_protected_files` | `docs/agentic/contracts/` | does not exist | add `["Makefile"]` | new field | edit to root `Makefile` on main is blocked |
| `harness-protocol.yaml` `branch_isolation.permitted_main_surfaces` | `docs/agentic/contracts/` | does not exist | new list of `{pattern, reason}` entries; per-project configurable | new field | drift-check edits to listed patterns pass with trace log |
| `guard-main-branch.py` | `.github/hooks/` | hardcoded `_PROTECTED_ROOTS` tuple | read from `harness-protocol.yaml` at runtime | behavior-preserving refactor | blocked-path test cases |
| `guard-main-branch.sh` | `scripts/hooks/` | hardcoded regex `^(apps/|packages/)` | read from `harness-protocol.yaml` via `python3 -c` extraction at runtime | behavior-preserving refactor | blocked-path test cases |
| `guard-main-branch.py` `_EDIT_TOOLS` | `.github/hooks/` | `{"apply_patch", "create_file"}` | audit and cover every regular-file mutator | non-breaking expansion | edit via those tools is blocked on main |
| Worktree drift PreToolUse (new) | `.github/hooks/` + `scripts/hooks/` + `.claude/settings.json` | does not exist | new hook; **block-mode default** + `ALT_ALLOW_WORKTREE_DRIFT=1` escape hatch + `permitted_main_surfaces` allow-list + `MAINT-*` task-ref bypass | n/a | drift is blocked; allow-list passes with trace; no-task degrades silently |
| `check_harness_sync.py` | `scripts/` | validates hooks only | add `code_roots` and `permitted_main_surfaces` drift checks | non-breaking extension | intentional `code_roots` or allow-list mismatch fails |
| Shared contract loader helper (new) | `scripts/hooks/_harness_protocol.py` | does not exist | single-import utility for both guard scripts to load the contract | new module | guards import from the helper; `check_harness_sync.py` asserts import wiring |

## Proposed Solution

Four slices deliver the guard hardening. They land in order:

1. Expand `code_roots` + add `permitted_main_surfaces` to the contract; add the shared contract-loader helper; refactor both guards to read from the contract.
2. Add the worktree-drift PreToolUse check in block-mode with escape hatches, allow-list consultation, and `MAINT-*` bypass.
3. Extend `check_harness_sync.py` with `code_roots`, `permitted_main_surfaces`, and dashboard-naming lint validation.
4. Coordinate sequencing with E17-7 Slice 2 and document the operator-facing escape hatch contract in `development-workflow.md`.

**Sequencing coordination with E17-7 Slice 2**: E17-7 Slice 2 introduces a checkbox-sync hook that writes to `docs/tasks/**/*.md` on `main` when slices complete. If E17-8 Slice 2's block-mode drift check ships while a feature task is active but the `permitted_main_surfaces` allow-list is missing the task-plan pattern, checkbox-sync writes will be blocked. **Mitigation**: E17-8 Slice 1 (which lands the allow-list) **must merge to `main` before E17-7 Slice 2 ships**, regardless of whether E17-8 Slice 2's drift check has also landed. The two slices form an ordered pair; their coordination is the Slice 4 checklist item in this plan and a prerequisite bullet in the E17-7 Slice 2 checklist.

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| Contract | `docs/agentic/contracts/harness-protocol.yaml` | expand `code_roots`; add `.mk` to `protected_extensions`; add `root_protected_files: ["Makefile"]`; add new `permitted_main_surfaces` list |
| Contract (BR-20 retro-documented) | `docs/agentic/contracts/harness-protocol.yaml` | add NEW `protected_main_surfaces` list (11 entries) that ADDITIVELY BLOCKS planning-doc patterns on main independent of the existing `code_roots` + `protected_extensions` intersection. Loaded by `_harness_protocol.load_branch_isolation_policy` as `BranchIsolationPolicy.protected_main_surfaces: tuple[MainSurfacePattern, ...]`. Queried by `is_branch_isolation_protected_path` → `find_protected_main_surface`. |
| Shared loader (new) | `scripts/hooks/_harness_protocol.py` | single-source contract loader used by both guards |
| VS Code guard | `.github/hooks/guard-main-branch.py` | read policy via the shared loader; audit missing edit tools |
| Claude guard | `scripts/hooks/guard-main-branch.sh` | read policy via `python3 -c "from _harness_protocol import ..."` |
| Worktree drift (new, VS Code) | `.github/hooks/guard-worktree-drift.py` | new PreToolUse hook; block-mode + escape hatches + allow-list |
| Worktree drift (new, Claude) | `scripts/hooks/guard-worktree-drift.sh` | new PreToolUse hook; block-mode + escape hatches + allow-list |
| VS Code hooks | `.github/hooks/terminal-guard.json` | register `guard-worktree-drift.py` as PreToolUse |
| Claude hooks | `.claude/settings.json` | register `guard-worktree-drift.sh` as PreToolUse |
| Harness contract | `docs/agentic/contracts/harness-protocol.yaml` | add worktree-drift hook entry |
| Sync validator | `scripts/check_harness_sync.py` | add `code_roots` + `permitted_main_surfaces` drift check; add dashboard-naming lint |
| Branch isolation docs | `docs/agentic/rules/development-workflow.md` | document expanded `code_roots`, worktree-drift guard, `permitted_main_surfaces` per-project configurability, and the `ALT_ALLOW_WORKTREE_DRIFT` escape hatch |
| Gitignore | `.gitignore` | add `DASHBOARD.md` stray-file exclusion | <!-- lint-dashboard-txt: allow -->

## Verification Strategy

- `make check-harness-sync` passes after all slices.
- `make check-all` stays green.
- An edit to `scripts/hooks/<file>.py` on `main` is blocked with a named error.
- An edit to `.github/hooks/<file>.py` on `main` is blocked with a named error.
- An edit to `.claude/skills/<file>/SKILL.md` on `main` is permitted; `.md` remains outside `protected_extensions`, which verifies false-positive avoidance.
- An edit to `mk/handoff.mk` on `main` is blocked after `.mk` is added to `protected_extensions`.
- An edit to root `Makefile` on `main` is blocked via `root_protected_files`.
- An edit routed to `/Users/.../context-alt-text-monorepo/.github/hooks/terminal-guard.py` while the active task targets `/Users/.../context-alt-text-monorepo-e17-8/` is **blocked** by the drift check with a `WorkspaceRootDriftError` naming both paths.
- An edit routed to `/Users/.../context-alt-text-monorepo/docs/tasks/17.0/E17-8-...md` under the same active task is **allowed** with a trace log (matches `docs/tasks/**/*.md` in `permitted_main_surfaces`).
- An edit under the same active task is **allowed** silently when the active task ref is `MAINT-DASHBOARD-20260416` (MAINT-prefix bypass).
- An edit under the same active task is **allowed** with a warn-only log when `ALT_ALLOW_WORKTREE_DRIFT=1` is set (escape hatch).
- With no active task (fresh session), all edits pass silently.
- Docs and markdown edits on `main` continue to work for any path in `permitted_main_surfaces`.
- The E17-7 Slice 2 checkbox-sync hook writes to `docs/tasks/**/*.md` on `main` without tripping the drift block.

## Slice Delivery

### Slice 1: Expand `code_roots`, Add `permitted_main_surfaces`, and Refactor Guards to Read from Contract

**Goal**: both guards read the full policy from `harness-protocol.yaml` instead of hardcoding it; the contract expands the protected surface and adds the per-project allow-list that Slice 2 and the E17-7 Slice 2 checkbox-sync hook will consult.

Changes:

- Expand `harness-protocol.yaml` `branch_isolation.code_roots` to include: `scripts/`, `.github/hooks/`, `.claude/`, `mk/`.
- Add `.mk` to `branch_isolation.protected_extensions`.
- Add `branch_isolation.root_protected_files: ["Makefile"]`.
- Add a new `branch_isolation.permitted_main_surfaces` block, documented inline as per-project configurable. Default entries for this repo:

  ```yaml
  permitted_main_surfaces:
    - pattern: "docs/tasks/**/*.md"
      reason: "Task-plan progress + checkbox sync (coordinates with E17-7 Slice 2 auto-sync hook)"
    - pattern: "docs/assessments/**"
      reason: "Planning artifacts land on main pre-implementation"
    - pattern: "docs/scopes/**"
      reason: "Scope notes for upcoming tasks"
    - pattern: "docs/epics/**"
      reason: "Epic-level planning artifacts"
    - pattern: "CLAUDE.md"
      reason: "Canonical agent dispatcher; synced from docs/agentic/instructions.md"
    - pattern: ".github/copilot-instructions.md"
      reason: "VS Code harness mirror of CLAUDE.md"
    - pattern: "docs/agentic/BOOTSTRAP.md"
      reason: "Operator-facing cold-start reference"
    - pattern: "docs/agentic/instructions.md"
      reason: "Canonical instructions surface"
    - pattern: "docs/agentic/contracts/**"
      reason: "Harness contracts (yaml only; no code extensions)"
    - pattern: "docs/agentic/rules/**"
      reason: "Rule surfaces referenced from CLAUDE.md"
    - pattern: "docs/agentic/maps/**"
      reason: "Role/tech/routing maps"
    - pattern: "docs/agentic/generated/**"
      reason: "Generated surfaces (regenerate-task-views writes here)"
    - pattern: "docs/tasks/archive/**"
      reason: "Archived task snapshots"
    - pattern: "DASHBOARD.txt"
      reason: "Live dashboard artifact; regenerated by hooks"
    - pattern: "CURRENT_TASK.md"
      reason: "On-demand task snapshot; regenerated by generate_current_task_md"
  ```

  Each entry carries a `reason` string so future maintainers can tell why a pattern is on the list and which subsystem would break if it were removed. Any project forking the harness is expected to rewrite this list to match its own main-branch conventions; the shipped list is this repo's policy, not a framework default.

- Add a new shared loader module `scripts/hooks/_harness_protocol.py` exposing:
  - `load_branch_isolation_policy(workspace_root: Path) -> BranchIsolationPolicy` returning `code_roots`, `protected_extensions`, `root_protected_files`, and `permitted_main_surfaces` as one immutable dataclass.
  - `is_permitted_main_surface(rel_path: str, policy: BranchIsolationPolicy) -> tuple[bool, str|None]` returning `(matched, reason)` for a given repo-relative path, using `pathlib.PurePosixPath.match` and the stored glob patterns.
  - Raises `HarnessContractMissingError` with a named remediation string when `harness-protocol.yaml` is missing or unparseable.

- Refactor `guard-main-branch.py`:
  - Replace the hardcoded `_PROTECTED_ROOTS`/`_CODE_EXTENSIONS` constants with a call to `load_branch_isolation_policy()`.
  - Treat `harness-protocol.yaml` presence as a required runtime dependency: if the contract file is missing, the guard emits a loud error on stderr (naming the expected path and remediation) and exits with a block decision so the agent cannot silently operate on an under-protected surface. There is no hardcoded fallback policy.
  - Audit the VS Code harness file-mutating tool surface and expand `_EDIT_TOOLS` to every regular-file mutator; at minimum add `replace_string_in_file` and `multi_replace_string_in_file`.

- Refactor `guard-main-branch.sh`:
  - Call the shared loader via an embedded `python3 -c "import sys; sys.path.insert(0, 'scripts/hooks'); from _harness_protocol import load_branch_isolation_policy; ..."` extraction. Same contract-required policy as the VS Code guard: missing contract → loud stderr + block; no hardcoded fallback list.

- Keep the `startswith(code_root) + extension_match` semantic unchanged for the main-branch guard; only the source of the lists changes.

Design decision: root-level code-adjacent files are protected through `root_protected_files`, starting with `Makefile`. Additional root files stay out of scope unless the same accidental-main-edit pattern recurs.

Proof:

- An edit to `scripts/check_skills.py` on `main` is blocked.
- An edit to `.github/hooks/terminal-guard.py` on `main` is blocked.
- An edit to root `Makefile` on `main` is blocked.
- An edit to `docs/tasks/foo.md` on `main` is permitted.
- An edit to `CLAUDE.md` on `main` is permitted.
- `is_permitted_main_surface("docs/tasks/17.0/foo.md", policy)` returns `(True, "Task-plan progress + checkbox sync ...")`.
- `is_permitted_main_surface("apps/prototype-wp-alt-context/src/foo.php", policy)` returns `(False, None)`.
- Removing `scripts/` from the contract's `code_roots` causes `make check-harness-sync` to detect drift (Slice 3 dependency; manual verification until then).
- With `harness-protocol.yaml` temporarily moved aside, each guard emits a named stderr error and returns a block decision — there is no silent permissive fallback.

### Slice 2: Worktree-Drift PreToolUse Check (Block-Mode + Escape Hatches + Allow-List)

**Goal**: detect at edit time when a file is being modified in a worktree other than the one the active task targets, and **block** the edit by default. Allow only through explicit, auditable escape hatches: the `permitted_main_surfaces` allow-list, the `MAINT-*` task-ref convention, or the `ALT_ALLOW_WORKTREE_DRIFT=1` env var.

Changes:

- Add `.github/hooks/guard-worktree-drift.py` (VS Code harness) and `scripts/hooks/guard-worktree-drift.sh` (Claude harness). Both implement the same 9-step algorithm:

  1. Parse PreToolUse hook input; exit 0 if the tool is not `Edit`, `Write`, `apply_patch`, `create_file`, `replace_string_in_file`, or `multi_replace_string_in_file`.
  2. Extract the edit target; resolve to absolute canonical path with `Path(target).resolve()`. Never match relative paths.
  3. Import `agent_handoff_mcp` via the Python API (`from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state`); configure against the current workspace root; read the active task's `target_worktree_path` and `target_branch` via `get_handoff_state(sections="identity")`.
  4. Exit 0 silently if no active task is registered, or `target_worktree_path` is null, or `target_branch` is `main`/`master` (planning work).
  5. Exit 0 with a trace log if the active task `task_ref` starts with `MAINT-` (consistent with the main-branch maintenance-task rule).
  6. Exit 0 with a warn-only log if `os.environ.get("ALT_ALLOW_WORKTREE_DRIFT") == "1"` (operator-side escape hatch).
  7. Compute the edit target's containing worktree by walking up from the resolved path until a `.git` file or directory is found; resolve that worktree's canonical path.
  8. If the containing worktree path equals `target_worktree_path` → exit 0 silently (no drift).
  9. If the containing worktree path differs: load the contract policy via `scripts/hooks/_harness_protocol.py`. If the edit's repo-relative path matches any `permitted_main_surfaces` glob AND the containing worktree is the main-root worktree, exit 0 with a trace log naming the matching pattern and its reason. Otherwise, raise `WorkspaceRootDriftError` and exit with a **block** permissionDecision, naming: the edit target, the containing worktree, the expected `target_worktree_path`, and all three escape hatches the operator can use (`MAINT-` task ref, `ALT_ALLOW_WORKTREE_DRIFT=1`, or adding the path to `permitted_main_surfaces`).

- Register both hooks in `.github/hooks/terminal-guard.json` and `.claude/settings.json`.
- Add the hook entry to `harness-protocol.yaml` under `hooks.pre_tool_use`.
- Performance budget: must complete in <200ms (one SQLite read via the handoff API, one subprocess `git` call, one YAML parse). Measure with `time python3 .github/hooks/guard-worktree-drift.py < test_payload.json`.

Escalation posture:
- **Default: BLOCK**. Warn-only has failed in practice (see Problem Statement bullet 5).
- Escape hatches are operator-controlled and auditable: env var (shell-session-scoped), task-ref convention (handoff-state-scoped), allow-list (contract-scoped). All three emit trace logs to `.task-state/branch_isolation_guard.jsonl`.

Proof:

- An edit to `/Users/.../context-alt-text-monorepo/.github/hooks/terminal-guard.py` while active task targets `/Users/.../context-alt-text-monorepo-e17-8/` is blocked with `WorkspaceRootDriftError` naming both paths and the three escape hatches.
- An edit to `/Users/.../context-alt-text-monorepo/docs/tasks/17.0/E17-8-....md` under the same active task is allowed with a trace log naming `docs/tasks/**/*.md`.
- An edit under the same active task is allowed silently when `task_ref == "MAINT-DASHBOARD-20260416"`.
- An edit under the same active task is allowed with a warn-only log when `ALT_ALLOW_WORKTREE_DRIFT=1`.
- An edit to `/Users/.../context-alt-text-monorepo-e17-8/scripts/check_skills.py` while active task targets the same worktree passes silently.
- With no active task (fresh session), all edits pass silently.
- The hook completes in <200ms.
- The E17-7 Slice 2 checkbox-sync hook's writes to `docs/tasks/**/*.md` on `main` pass with a trace log, not a block.

### Slice 3: `check_harness_sync` Validation + Dashboard Naming Lint

**Goal**: CI catches divergence between the contract's `code_roots`/`protected_extensions`/`permitted_main_surfaces` and the actual guard behavior, and catches reintroductions of the stale `DASHBOARD.md` name once E17-7 Slice 4 normalizes it to `DASHBOARD.txt`. <!-- lint-dashboard-txt: allow -->

Changes:

- Extend `scripts/check_harness_sync.py` with a `_check_branch_isolation()` function that validates **behavior**, not duplicated literals. After Slice 1 the guards no longer carry a hardcoded fallback policy, so parsing guard source for `_PROTECTED_ROOTS` / regex literals would only inspect dead defaults. Instead the validator:
  - Reads `code_roots`, `protected_extensions`, `root_protected_files`, and `permitted_main_surfaces` from `harness-protocol.yaml` as the single source of truth.
  - Drives each guard (`guard-main-branch.py`, `guard-main-branch.sh`) through a fixture harness: for each `code_root`, feed a synthetic PreToolUse payload of a file inside the root with a protected extension, and assert the guard returns a block decision. For a permitted-root fixture (e.g. `docs/foo.md`), assert the guard returns allow. Do the same for each entry in `root_protected_files`.
  - Confirms wiring, not literals: parses the Python guard to assert it imports `load_branch_isolation_policy` from `scripts/hooks/_harness_protocol.py`, and parses the shell guard to assert its embedded `python3 -c` extraction names the same helper. No duplicated policy lists are compared.
  - Asserts that removing `harness-protocol.yaml` makes each guard emit the named contract-required stderr error and return a block decision (the Slice 1 no-fallback behavior).
  - Validates `permitted_main_surfaces` shape: each entry has a `pattern` (non-empty string) and a `reason` (non-empty string); `pattern` parses as a valid glob via `pathlib.PurePosixPath.match` on a representative sample path.
  - Drives `guard-worktree-drift.py` through a fixture harness: constructs a synthetic active task with `target_worktree_path` pointing to a non-main worktree, then asserts a block decision for a code-root edit on main and an allow decision for a `permitted_main_surfaces` match. Also exercises the `MAINT-` bypass and `ALT_ALLOW_WORKTREE_DRIFT=1` env var.
  - Reports any code_root / root_protected_file / permitted_main_surface whose fixture does not exercise the expected decision. That output is the drift signal, not a literal diff.

- Add a `_check_dashboard_naming()` function to the same validator that:
  - Greps tracked non-archive markdown (`git ls-files '*.md'` minus `docs/archive/**` and `**/tests/**`), the root `Makefile`, and `packages/agent-orchestrator-mcp/src/**/dashboard_extension.py` for the literal string `DASHBOARD.md`. <!-- lint-dashboard-txt: allow -->
  - Fails with a named diff if any hit remains after E17-7 Slice 4 has landed. Depends on E17-7 Slice 4 — land this lint *after* the rename so the first run is clean.
  - Rationale documented in `docs/assessments/dashboard-md-vs-txt-guidance-drift-investigation-2026-04-16.md`.

- Add `DASHBOARD.md` to the repo-root `.gitignore` so stray untracked copies (produced by older local clones or pre-AHMCP-23 artifacts) stop surfacing in `git status` and cannot be accidentally committed. <!-- lint-dashboard-txt: allow -->

- Wire both new checks into `make check-harness-sync`.

Proof:

- `make check-harness-sync` passes after Slices 1-2 and after E17-7 Slice 4 lands the dashboard-name normalization.
- Adding a new `code_root` to the contract and running the fixture harness produces a block decision from both guards for a file inside that root with a protected extension.
- Removing the contract loader call from `guard-main-branch.py` (or breaking the `python3 -c` extraction in `guard-main-branch.sh`) causes the wiring check to fail with a named remediation message.
- Removing a `pattern` or `reason` field from a `permitted_main_surfaces` entry causes the shape check to fail with a named line reference.
- Intentionally breaking the drift hook's allow-list consultation (e.g. always returning block) causes the drift-hook fixture harness to fail on the task-plan path case.
- Moving `harness-protocol.yaml` aside causes each guard fixture to assert the contract-required stderr error and a block decision.
- Reintroducing `DASHBOARD.md` into any tracked non-archive markdown, the Makefile, or the `dashboard_extension.py` docstring causes the validator to fail with a named line reference. <!-- lint-dashboard-txt: allow -->
- A manually dropped `DASHBOARD.md` in the repo root does not appear in `git status`. <!-- lint-dashboard-txt: allow -->

### Slice 4: Coordination with E17-7 Slice 2 + Operator Documentation

**Goal**: document the operator-facing contract for `permitted_main_surfaces` configuration and the `ALT_ALLOW_WORKTREE_DRIFT` escape hatch, and confirm the sequencing against E17-7 Slice 2's checkbox-sync hook.

Changes:

- Extend `docs/agentic/rules/development-workflow.md` § Branch Isolation Protocol with:
  - A new subsection documenting `permitted_main_surfaces` as a per-project configurable allow-list in `harness-protocol.yaml`. Include the full shipped list as the repo's current policy, with each entry's reason.
  - A new subsection documenting the `ALT_ALLOW_WORKTREE_DRIFT=1` env-var escape hatch: its scope (shell session), its trace-log location, and when to use it (only for intentional cross-worktree edits that do not fit the `MAINT-*` or allow-list patterns).
  - Update the `MAINT-*` maintenance-task section to mention that this convention is now a drift-hook bypass as well as a main-branch edit permission, citing the 9-step algorithm.
- Verify E17-7 Slice 2 sequencing: the E17-7 Slice 2 checkbox-sync hook's target pattern (`docs/tasks/**/*.md`) is in `permitted_main_surfaces` on main before E17-7 Slice 2 ships. This check is the prerequisite bullet in the E17-7 Slice 2 checklist (cross-reference added to E17-7 in the same PR that lands this slice).
- Cross-link from E17-7 task plan's Slice 2 checklist to this task plan's Slice 1 checkbox ("permitted_main_surfaces includes `docs/tasks/**/*.md`") as the explicit prerequisite.

Proof:

- `development-workflow.md` documents the allow-list and env-var escape hatch with the current repo defaults verbatim.
- E17-7 task plan's Slice 2 checklist references this task plan's Slice 1 `permitted_main_surfaces` entry.
- A reader of only `development-workflow.md` can configure a new project's `permitted_main_surfaces` correctly without reading this task plan.
- `make check-all` stays green.

---

## Consolidated Checklist

### Context and Ownership

- [x] Verify E17-6 has merged (harness-protocol.yaml is on main) — confirmed 2026-04-16
- [x] Confirm the guard scripts still use hardcoded path lists (no interim changes)
- [x] Confirm `check_harness_sync.py` does not already validate `code_roots` or `permitted_main_surfaces`
- [x] Confirm `scripts/hooks/_harness_protocol.py` does not exist

### Checklist for Slice 1: Expand `code_roots` + Allow-List + Refactor Guards

- [x] `harness-protocol.yaml` `code_roots` includes `scripts/`, `.github/hooks/`, `.claude/`, `mk/`
- [x] `harness-protocol.yaml` adds `.mk` to `protected_extensions`
- [x] `harness-protocol.yaml` adds `root_protected_files: ["Makefile"]`
- [x] `harness-protocol.yaml` adds `permitted_main_surfaces` (11 operator-maintained entries: CLAUDE.md, .github/copilot-instructions.md, docs/agentic/{BOOTSTRAP.md, instructions.md, contracts/**, rules/**, maps/**, generated/**}, docs/tasks/archive/**, DASHBOARD.txt, CURRENT_TASK.json) and `protected_main_surfaces` (11 planning-doc entries listed in the retroactive landing note above). Both lists are configured per-project.
- [x] Each `permitted_main_surfaces` entry has both `pattern` and `reason` fields populated
- [x] `scripts/hooks/_harness_protocol.py` exposes `load_branch_isolation_policy` and `is_permitted_main_surface`
- [x] `_harness_protocol.py` raises `HarnessContractMissingError` with a named remediation when the contract is absent
- [x] `guard-main-branch.py` reads from the shared loader; no hardcoded fallback list remains
- [x] `guard-main-branch.py` `_EDIT_TOOLS` covers every regular-file mutator in the VS Code harness
- [x] `guard-main-branch.sh` reads from the shared loader via `python3 -c`; no hardcoded fallback list remains
- [x] Edits to `scripts/`, `.github/hooks/`, `.claude/`, `mk/` code files on `main` are blocked
- [x] Root `Makefile` edits on `main` are blocked
- [x] Edits to docs, markdown, and permitted config on `main` are not blocked
- [x] With contract missing, guards emit a named stderr error and return a block decision (no silent permissive fallback)

### Checklist for Slice 2: Worktree-Drift Check (Block-Mode + Escape Hatches)

- [x] `guard-worktree-drift.py` and `guard-worktree-drift.sh` implement the 9-step algorithm identically
- [x] Default escalation is **block** with `WorkspaceRootDriftError`, not ask, not warn
- [x] Edit-path resolution uses `Path(target).resolve()` — no relative-path matching
- [x] `ALT_ALLOW_WORKTREE_DRIFT=1` env var downgrades block to warn-only pass
- [x] `MAINT-*` task-ref prefix bypasses the drift check with a trace log
- [x] Edit paths matching `permitted_main_surfaces` globs on the main-root worktree pass with a trace log
- [x] No active task or null `target_worktree_path` passes silently
- [x] Active task targeting `main`/`master` passes silently (planning work)
- [x] Block error message names the edit target, containing worktree, expected `target_worktree_path`, and all three escape hatches
- [x] Hook registered in `terminal-guard.json` and `.claude/settings.json`
- [x] Hook registered in `harness-protocol.yaml` under `hooks.pre_tool_use`
- [ ] Performance: <200ms completion time
- [x] Trace log entries written to `.task-state/branch_isolation_guard.jsonl` for every non-silent outcome

### Checklist for Slice 3: Sync Validator Extension + Dashboard Naming Lint

- [x] `check_harness_sync.py` exercises both main-branch guards through a fixture harness (not via parsing duplicated literals)
- [x] `check_harness_sync.py` exercises the worktree-drift hook through a fixture harness: block case, allow-list case, MAINT bypass, env-var bypass
- [x] `check_harness_sync.py` validates `permitted_main_surfaces` entry shape (`pattern` and `reason` non-empty; pattern is a valid glob)
- [ ] `check_harness_sync.py` validates absence of `DASHBOARD.md` in tracked non-archive markdown, the Makefile, and the `dashboard_extension.py` docstring (depends on E17-7 Slice 4 completion) <!-- lint-dashboard-txt: allow -->
- [x] `check_harness_sync.py` asserts the contract-required stderr + block behavior when `harness-protocol.yaml` is moved aside
- [x] `.gitignore` excludes `DASHBOARD.md` <!-- lint-dashboard-txt: allow -->
- [ ] `make check-harness-sync` passes after Slices 1-2 and after E17-7 Slice 4
- [x] Intentional contract drift is detected and reported
- [x] Intentional `permitted_main_surfaces` shape drift is detected and reported
- [x] Intentional `DASHBOARD.md` reintroduction is detected and reported <!-- lint-dashboard-txt: allow -->
- [ ] `make check-all` stays green

### Checklist for Slice 4: Coordination + Documentation

- [x] `development-workflow.md` documents `permitted_main_surfaces` as per-project configurable in `harness-protocol.yaml`, with the repo's current shipped list reproduced verbatim
- [x] `development-workflow.md` documents the `ALT_ALLOW_WORKTREE_DRIFT=1` env-var escape hatch (scope, trace-log location, when to use)
- [x] `development-workflow.md` `MAINT-*` subsection mentions the drift-hook bypass in addition to the main-branch edit permission
- [x] E17-7 Slice 2 checklist gains an explicit prerequisite bullet referencing this task plan's Slice 1 `permitted_main_surfaces` entry for `docs/tasks/**/*.md`
- [x] A reader of only `development-workflow.md` can configure a new project's `permitted_main_surfaces` correctly without reading this task plan
- [ ] `make check-all` stays green

## Review Readiness

- [x] E17-6 prerequisite confirmed merged (2026-04-16)
- [ ] `make check-all` stays green after each slice
- [x] No MCP write-enforcement changes are included
- [x] No graduation of E17-4 Slice 2's warning-only main-change guard is included
- [x] E17-7 Slice 2 sequencing prerequisite (allow-list lands before checkbox-sync ships) is documented in both task plans

## Success Criteria

- [x] Both main-branch guards read `code_roots`, `protected_extensions`, `root_protected_files`, and `permitted_main_surfaces` from `harness-protocol.yaml` via a shared loader
- [x] Root `Makefile` is protected through `root_protected_files`
- [x] `scripts/`, `.github/hooks/`, `.claude/`, and `mk/` code files are protected on `main`
- [x] Worktree-drift check **blocks by default** with `WorkspaceRootDriftError`; escape hatches (env var, `MAINT-*`, allow-list) each work as documented
- [x] `permitted_main_surfaces` ships with 11 operator-maintained entries covering agent dispatchers, agentic contracts/rules/maps, and generated artifacts; planning docs (task plans, assessments, scopes, epics, specs, ADRs) are additively BLOCKED on main via the new `protected_main_surfaces` list (also 11 entries)
- [x] `permitted_main_surfaces` is documented as per-project configurable, not as a framework default
- [ ] E17-7 Slice 2 checkbox-sync hook writes to `docs/tasks/**/*.md` on main without tripping the drift block
- [ ] `make check-harness-sync` catches `code_roots`, `permitted_main_surfaces`, and `DASHBOARD.md` drift <!-- lint-dashboard-txt: allow -->
- [x] `.gitignore` prevents stray untracked `DASHBOARD.md` from polluting `git status` <!-- lint-dashboard-txt: allow -->
- [x] Existing permitted main-branch edits (docs, markdown, configs) work without friction
- [x] `development-workflow.md` documents the full operator-facing contract without pointing operators at this task plan

## Coordination Note

**E17-7 Slice 2 dependency**: E17-7 Slice 2 introduces a checkbox-sync hook that writes to `docs/tasks/**/*.md` on `main` when slices complete. This task plan's Slice 1 lands the `permitted_main_surfaces` allow-list that includes that pattern. **Ordering**: E17-8 Slice 1 must merge to `main` before E17-7 Slice 2 ships, regardless of whether E17-8 Slices 2-4 have also landed. The two task plans share this ordering constraint as an explicit cross-reference in both checklists.
