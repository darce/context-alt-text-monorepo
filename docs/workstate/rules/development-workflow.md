# Development Workflow

> Load this document for detailed workflow procedures: branch isolation, scaffolding, TDD cycle, commit conventions, and review preparation.

---

## Branch Isolation Protocol (MANDATORY)

**Code files must never be edited on the `main` branch.** The protected path policy lives in [harness-protocol.yaml](../contracts/harness-protocol.yaml) and is enforced in both harnesses:

- **VS Code Copilot**: `.github/hooks/terminal-guard.json` runs `.github/hooks/guard-main-branch.py` and `.github/hooks/guard-worktree-drift.py` on `PreToolUse`.
- **Claude Code**: `.claude/settings.json` runs `scripts/hooks/guard-main-branch.sh` and `scripts/hooks/guard-worktree-drift.sh` on `PreToolUse`.

The main-branch guard blocks in two cases: when the current edit targets a protected code path on `main`, and when protected code is already dirty on `main` and you try to keep editing anything else. That second case is deliberate: once implementation drift exists on `main`, the next step is to move it onto a feature branch or stash it, not continue layering more edits around it.

Protected code roots: `apps/`, `packages/`, `scripts/`, `.github/hooks/`, `.claude/`, and `mk/`.

Protected code extensions: `*.py`, `*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.php`, `*.sql`, `*.sh`, `*.css`, `*.scss`, `*.mk`.

Protected root files: `Makefile`.

**Allowed on `main`:** only non-planning operator docs, generated snapshots, and other repo-local surfaces that appear in `branch_isolation.permitted_main_surfaces`. Planning artifacts are protected on `main` and must be created and updated on the task branch from the first file write. See [planning-pipeline.md § Planning starts on the task branch](planning-pipeline.md#planning-starts-on-the-task-branch-from-the-first-artifact).

**Task-plan progress lives on the task branch:** update checklist progress and status blocks in `docs/tasks/`, `docs/epics/`, package-local planning docs, and similar planning artifacts on the owning task branch after each implementation or review turn. MCP handoff remains the live cross-branch source of truth while the branch is open; the planning docs land on `main` only when the reviewed branch merges.

- Treat checklist items as complete only after the relevant handoff review findings for that turn are fixed or explicitly resolved.
- Do not mark a task-plan slice complete on initial implementation alone; unresolved branch-review or planning-review findings mean the checklist stays in-progress on the task branch.
- Do not mirror in-progress planning-doc status back to `main` while the task branch is still open; that split state is exactly the ambiguity this policy removes.

### Main-Worktree Allow-List

`branch_isolation.permitted_main_surfaces` in [harness-protocol.yaml](../contracts/harness-protocol.yaml) is a per-project configurable allow-list for legitimate non-planning edits that still belong on the primary `main` worktree while task work happens in linked worktrees. Projects adopting this harness are expected to rewrite the list to match their own operator surfaces; the entries below are this repo's current shipped policy:

- `CLAUDE.md`: canonical agent dispatcher that stays editable on `main`
- `.github/copilot-instructions.md`: VS Code harness mirror of `CLAUDE.md`
- `docs/workstate/BOOTSTRAP.md`: operator-facing cold-start reference
- `docs/workstate/instructions.md`: canonical agent instructions surface
- `docs/workstate/contracts/**`: harness contracts that stay editable on `main`
- `docs/workstate/rules/**`: workflow rules that stay editable on `main`
- `docs/workstate/maps/**`: routing and map artifacts that stay editable on `main`
- `docs/workstate/generated/**`: generated workstate artifacts that can update on `main`
- `docs/tasks/archive/**`: archived task snapshots that stay editable on `main`
- `DASHBOARD.txt`: regenerated dashboard artifact on `main`
- `CURRENT_TASK.json`: regenerated current-task snapshot on `main`

Keep each allow-list entry narrow and explainable. If a surface exists only to support this repo's workflow, add it here with a reason in the contract. If a path is code or code-adjacent implementation, do not put it on this list just to bypass the guard.

### Shared Workstate Surface

The shared workstate surface is installed from the private `darce/workstate` repo and its published package family:

- `https://github.com/darce/workstate.git` — canonical shared surface and package source for skills, hooks, prompts, commands, contracts, lifecycle helpers, and workflow generators
- `mcp-workstate-handoff` — handoff MCP package consumed by repo and consumer harnesses
- `mcp-workstate-orchestrator` — orchestrator MCP package consumed by lane and worker tooling
- `workstate-system` — passive shared surface installed into consumer repositories
- `workstate-bootstrap` — bootstrap CLI that installs and updates the shared surface in consumer projects

MCP-server packages keep the `mcp-workstate-` prefix (`mcp-workstate-handoff`, `mcp-workstate-orchestrator`); shared-surface and CLI packages use `workstate-system` and `workstate-bootstrap`. These canonical names are referenced by `docs/workstate/consumer-setup.md` and the doc-lock test in `scripts/test_consumer_setup_doc.py`; do not introduce alternate prefixes.

For the current migration, sync direction is one-way: the workstate package source is the source of truth. Consumers clone the remote surface into `<consumer-root>/.workstate/remote/`, materialize managed surfaces from `.workstate-bootstrap.json`, and do not install from `context-alt-text-monorepo` URLs.

`TODO(E17-10-POST-MVP-SYNC)`: define the reverse-sync workflow for upstream edits made in `darce/workstate`, including how they are reviewed and merged back into this monorepo without drift.

`TODO(E17-10-POST-MVP-CLEANUP)`: once Slice 5 proves the consumer flow end to end, delete the duplicated in-tree shared-surface copies from this monorepo or replace them with the agreed post-MVP sync model.

### Protected Planning Surfaces

`branch_isolation.protected_main_surfaces` is the complementary contract list for non-code paths that are still protected on `main`. In this repo that list includes top-level and package-local planning artifacts such as:

- `docs/tasks/**/*.md`, `packages/*/docs/tasks/**`
- `docs/assessments/**`, `packages/*/docs/assessments/**`
- `docs/scopes/**`
- `docs/epics/**`, `packages/*/docs/epics/**`
- `docs/specs/**`, `packages/*/docs/specs/**`
- `docs/adrs/**`, `packages/*/docs/adrs/**`

These paths must move with the task branch from the first edit onward. Do not add them back to `permitted_main_surfaces`.

### Maintenance-Task Pattern

Permitted `main` edits still need handoff registration. Before any ad-hoc operator doc, Makefile, config, or script patch on `main`, register a lightweight maintenance task such as:

`set_handoff_state(task_ref='MAINT-<slug>', objective='Describe the main-branch patch', status='in_progress')`

The main-branch guard now warns when permitted edits happen without an active task. This rollout is warning-only, but the registration step is still mandatory workflow discipline. The same `MAINT-*` convention is also a deliberate worktree-drift bypass for the PreToolUse drift guard, so intentional maintenance edits to the primary worktree do not trip `WorkspaceRootDriftError` while still leaving an auditable handoff trail.

### Worktree-Drift Guard

When an active task targets a linked worktree, the drift guard compares each edit target's canonical path against the task's stored `target_worktree_path`. If an edit resolves into a different worktree, the default action is **block** with `WorkspaceRootDriftError`.

The guard passes silently only when one of these conditions is true:

- there is no active task, no `target_worktree_path`, or the active task itself targets `main`
- the task ref starts with `MAINT-`
- the repo-relative path matches `branch_isolation.permitted_main_surfaces` on the primary worktree

Every non-silent outcome writes a trace record to `.task-state/branch_isolation_guard.jsonl`.

### `ALT_ALLOW_WORKTREE_DRIFT=1`

Use `ALT_ALLOW_WORKTREE_DRIFT=1` only for intentional cross-worktree edits that do not fit the `MAINT-*` pattern or an existing allow-list entry. The override is shell-session scoped and downgrades the drift block to a logged pass for commands launched from that shell.

Example:

```bash
ALT_ALLOW_WORKTREE_DRIFT=1 codex
```

Do not treat the env var as a permanent local setting. If a path should routinely be editable on the primary worktree, add a narrow `permitted_main_surfaces` entry instead. Planning docs are not eligible for that allow-list; if the work is truly maintenance on `main`, use a `MAINT-*` task ref.

**Before any code edit:**

1. Create a feature branch: `git checkout -b feature/<task-id>-<slug>`
2. Or use Claude Code worktree isolation: `Agent` tool with `isolation: "worktree"`
3. Or use the full lane orchestration: `make lane-open TASK=<task> LANE=<lane>`

**If you inherit dirty code changes on `main`:** stop and move them to a feature branch or stash them before starting new implementation work. Treat uncommitted code on `main` as a workflow defect, not a normal starting state.

**Isolation tiers** (choose based on task complexity):

| Tier                       | Mechanism                                 | When to use                                                    |
| -------------------------- | ----------------------------------------- | -------------------------------------------------------------- |
| **Feature branch**         | `git checkout -b feature/<id>-<slug>`     | Single-agent, single-task work                                 |
| **Worktree (Claude Code)** | `Agent` tool with `isolation: "worktree"` | Delegated subtasks that should not touch the main working tree |
| **Lane orchestration**     | `make lane-open` + `make lane-handoff`    | Multi-agent parallel work with scope enforcement               |

Guard implementations: `.github/hooks/guard-main-branch.py` and `scripts/hooks/guard-main-branch.sh`. If a hook incorrectly blocks a legitimate edit, fix the hook scope -- do not normalize code edits on `main`.

### Worktree Ownership Rule

**The root worktree stays on `main`. Always. Linked worktrees are always on feature branches.**

- Never check out `main` in a linked worktree (`git worktree add ... main` is forbidden). Git allows only one worktree per branch -- checking out `main` elsewhere blocks all other worktrees from accessing it.
- After merging, return the root worktree to `main` immediately.

**If `main` gets trapped in a linked worktree:**

```bash
git -C /path/to/linked-worktree checkout --detach HEAD   # free main
git checkout main                                          # reclaim in root
git worktree remove /path/to/linked-worktree              # clean up
```

**After merging a feature branch to `main`:**

```bash
git checkout main                  # return root to main
git branch -d feature/<merged>     # delete the merged branch
```

`make task-finish` performs a belt-and-suspenders post-archive check for this invariant. If the task's `target_branch` still exists after archive, the script prints the exact `git branch -d ...` cleanup command. Manual `archive_task_state` callers still own branch deletion themselves.

### Dirty Worktree Teardown (MANDATORY)

**Never force-remove a linked worktree that has uncommitted changes without triaging every dirty file first.** Uncommitted edits in a linked worktree are local to that worktree -- force-removing discards them permanently.

**Before removing any linked worktree:**

1. **Run `git -C <worktree-path> status --short`**. If the output is empty, the worktree is clean and safe to remove.
2. **If dirty files exist, triage each one:**
   - Files that belong to the worktree's task branch: commit them on the branch (even as a WIP commit) before removal.
   - Files that belong to other workstreams (branch bleed): move them to the root worktree or their correct branch via `cp` or `git stash` before removal.
   - Files that are redundant with main: confirm with `git diff main -- <file>` and discard explicitly.
3. **Never use `git worktree remove --force` on a dirty worktree** without completing step 2. The `--force` flag exists for stuck lock files, not for skipping triage.
4. **If the dirty file count exceeds 5 or spans multiple task refs, stop and ask the user** before proceeding. Mixed dirty state is a workflow defect signal, not a cleanup opportunity.

**The `make task-finish` helper enforces this:** it refuses to proceed (exit code 4) when untracked or modified files exist outside `.task-state/dirty-allowlist`. Manual worktree removal bypasses this check.

**Recovery options when work is already lost:** VS Code/Cursor Timeline view, JetBrains Local History, Time Machine/filesystem snapshots, or MCP handoff (decisions/findings/test results survive in `handoff.db`).

### Concurrent Editor Buffers (BUFFER ISOLATION)

> **Branch isolation prevents agent-vs-agent collisions across branches. Buffer isolation prevents agent-vs-editor collisions inside the same root worktree.**

A long-lived editor buffer can silently regress files: the editor loads a file pre-merge, then auto-save writes the stale buffer back to disk post-merge, overwriting the merged content. `git status` shows `M <file>` with no record of who wrote it. No agent layer can detect this race in real time.

#### Editor-side mitigations (mandatory for any editor open against this repo)

| Editor | Setting that prevents stale-buffer overwrites |
| --- | --- |
| **VS Code** / **Cursor** | `"files.autoSave": "off"` is the safest default. If auto-save is required, use `"files.autoSave": "onFocusChange"` AND enable `"files.refactoring.autoSave": false` so renames/refactors do not silently flush. Always set `"editor.formatOnSave"` to `false` for files outside your active focus. |
| **JetBrains** (IntelliJ, PyCharm, WebStorm) | Settings → Appearance & Behavior → System Settings → uncheck "Save files when switching to another application" and "Save files automatically if application is idle for N sec". Use explicit `Ctrl+S` instead. |
| **vim / neovim** | Add `set autoread` so the editor reloads files when they change on disk. Without this, switching branches under a held buffer creates the same staleness. |
| **Emacs** | `(global-auto-revert-mode 1)` enables auto-reload from disk. |

The key behavior is **reload-on-disk-change**. An editor that reloads when a file changes on disk cannot clobber a merge.

This repo commits the safe VS Code defaults in `.vscode/settings.json`, and `scripts/check_harness_sync.py` fails if those defaults drift.

#### Detection-side mitigations (enforced by the lifecycle scripts)

1. **`make context`** (every session start) prints a `⚠ Working-tree integrity` warning when `git diff --name-only HEAD` reports tracked files that are not listed in `.task-state/dirty-allowlist`. This catches stale buffer flushes that happened *between* sessions.
2. **`make task-finish`** (every merge teardown) runs the same check via bash and **refuses to archive** when integrity fails (exit code 4). This catches stale buffer flushes that happened *during* a session, before the archive write commits an invalid state.

Escape hatch: `.task-state/dirty-allowlist` -- a newline-delimited list of repo-relative paths intentionally modified outside any task.

```bash
# Example .task-state/dirty-allowlist
# Files I'm intentionally editing in parallel with task work:
docs/workstate/instructions.md
docs/workstate/rules/development-workflow.md
# Pre-existing repo-local work that pre-dates the active task:
scripts/mcp/handoff_integrity_guard.py
```

---

## Pre-Merge Gate (MANDATORY)

> **No feature branch merges to `main` without a passing pre-merge gate. No exceptions.**

### Gate Requirements

A feature branch is **merge-ready** only when **all** of the following are true:

1. **At least one review pass on the active task ref**, with findings recorded in MCP handoff via `review_findings(operation="record"|"batch_record")`. The review can be a planning review (for docs-only branches) or a branch review (for code branches). The choice is enforced by [Context Routing for Reviews](#context-routing-for-reviews).
2. **Zero open findings** on the task ref. Every recorded finding must be in status `fixed`, `deferred` (with rationale), or `wontfix` (with rationale). Verify with `review_findings(operation="list", status="open")`.
3. **Fresh `test_result` evidence** for the current branch state, recorded via `record_event(event_kind="test_result", ...)`. The PHP/Python/TS branch-review guides specify which test commands satisfy this for each stack. "Fresh" means recorded against the current HEAD commit SHA.
4. **`handoff_close_check(enforce=True, current_commit_sha=<HEAD>)` passes.** This is the canonical machine-checked gate. It verifies items 1-3 against the handoff DB and refuses to pass if anything is missing.
5. **Slice-complete decision recorded** for the work landing in the merge, using the `<author_tag>_slice_complete_<work_ref>_<slug>` grammar.

### Enforcement Mechanisms

- **Handoff DB (authoritative).** `handoff_close_check(enforce=True)` is the canonical check.
- **Branch isolation hook.** Blocks code edits on `main`, preventing the most common bypass.
- **Documentation.** Referenced from [CLAUDE.md](../../../CLAUDE.md) Critical Rules for cold-start visibility.
- **Reviewer sign-off.** The reviewer must cite the slice-complete decision ID of the artifact under review (see [Decision-ID Review Anchoring](#decision-id-review-anchoring) below) for bidirectional traceability.

### Decision-ID Review Anchoring

> **Use handoff decision IDs as review anchors — they are easier to reference and verify than git commit SHAs.**

Every `record_event(event_kind="decision", ...)` call returns a numeric `decision_id` (e.g. `#1452`). That ID is the stable, queryable handle for a slice. Reference it instead of typing or looking up commit SHAs wherever a human-readable anchor is needed.

**Implementer pattern** — when recording a slice-complete decision, note the returned ID:
```
record_event(event_kind="decision", decision="cdx_slice_complete_E17-2_patches", ...)
→ response: { "decision_id": 1452, ... }
Announce: "Slice complete — decision #1452"
```

**Reviewer pattern** — pass the decision ID as `subject_path` in the review run:
```
review_runs(review={
  "operation": "record",
  "review_run_id": "<tag>-review-<task-ref>-<N>",
  "subject_path": "decision #1452",
  "verdict": "pass_with_findings",
  ...
})
```
Record the verdict decision body as: `"Reviewed slice-complete decision #1452 on task <task-ref>."` This creates a bidirectional chain queryable with `search_handoff("decision #1452")`.

**Verification** — to confirm review coverage before the gate:
```
review_runs(review={"operation": "list", "task_ref": "<task-ref>"})
# Inspect subject_path fields — must include the latest slice-complete decision ID.
```

**Why this is easier than commit SHAs:** decision IDs appear in tool responses and chat output and do not require a separate `git rev-parse` call. They survive branch rebases. The pre-merge gate (`handoff_close_check`) already validates that a review run exists for the task ref; the decision ID in `subject_path` provides the human-auditable link without changing the gate's enforcement logic.

### Pre-Merge Sequence

```
On the feature branch, after final commit:

1.  Run the stack-specific test suite. Record results:
    record_event(event_kind="test_result", task_ref=..., command=..., passed=true,
                 actor={..., commit_sha=<HEAD>})

2.  Run review-ready and resolve all NOT READY reasons:
    make review-ready

3.  Request review (planning or branch, per Context Routing). Pass the
    slice-complete decision ID to the reviewer (see Decision-ID Review Anchoring
    above). Reviewer records findings in MCP and records a review_run with
    subject_path="decision #<slice-complete-id>".

4.  For each open finding: fix the issue, then close it with verification_evidence:
    review_findings(operation="update", finding_id=..., status="fixed",
                    verified_commit_sha=<HEAD>, verification_evidence=...)

5.  Confirm zero open findings:
    review_findings(operation="list", task_ref=..., status="open")
    Expected: total_matching == 0

6.  Record the slice-complete decision:
    record_event(event_kind="decision", decision="<tag>_slice_complete_<work_ref>_<slug>",
                 actor={..., commit_sha=<HEAD>})
    Note the returned decision_id — pass it to the reviewer in step 3.

7.  Run the canonical close check:
    handoff_close_check(enforce=True, current_commit_sha=<HEAD>)
    Expected: ok=true, no failures

8.  Merge the feature branch into main, return root to main, delete the feature branch, close any still-open post-merge review findings on the merged task from a descendant `main` context, archive the task, and regenerate DASHBOARD.txt (`render_handoff(kind='dashboard')`).
```

### When the Gate May Be Skipped

**Never.** If a finding cannot be fixed in this branch, mark it `deferred` with rationale and a follow-up task ref -- that satisfies item 2 without skipping the gate. Trivial doc-only edits with no review process should still record a brief MCP decision for audit trail continuity.

### Gate Failure Recovery

If `handoff_close_check(enforce=True)` fails:

- Read the failure reasons. Each is one of: missing review, open findings, stale test results, missing slice-complete decision, commit-SHA mismatch.
- Resolve the underlying issue. Do not work around the check by passing `enforce=False` — that defeats the gate.
- Re-run the check until it passes.
- Only then merge.

If a stale test_result blocks the gate, re-run the test suite and record a fresh `test_result` event tied to the current HEAD SHA.

---

## Slice Checklist

> Full lifecycle with Makefile targets and MCP tool calls: **[lifecycle-map.md](../lifecycle-map.md)** (stages I1–I7).

For every unit of work (feature slice, bug fix, refactor):

1. Identify the roadmap epic; ensure task is active → `set_handoff_state` or `switch_task`
2. **Write the failing test first** → `make slice-start TEST_CMD="..."` records `record_event(test_result, passed=false)` before any implementation edit — TDD is mandatory
3. **Scaffold the minimal signature that test needs**: create signatures + `NotImplementedError` bodies; verify the failure is for the intended reason before proceeding
4. If remote dependencies exist, add a provider interface + mock
5. Implement minimal production code to pass tests (Red → Green → Refactor) → record `record_event(test_result, passed=true)`
6. **Apply format and auto-fix**: `make format-all` from repo root (or per-component equivalent in lane workers: `make format-handoff`, `make format-orchestrator`, `make format` from the app dir). Runs `ruff check --fix --unsafe-fixes` + `ruff format` on Python, `npm run lint:fix` + `npm run format:fix` on TS/JS, `composer cs-fix` on PHP. Many violations are auto-fixable — eliminate them before the refactor pass and before the full test run.
7. Refactor for clarity while tests stay green
8. Run the [UML Change Checklist](uml-change-checklist.md) if architecture changed
9. Security pass: nonce/capability checks, escape/sanitize
10. Accessibility pass: keyboard navigation, ARIA labels
11. Run full test suite locally
12. **Commit the slice** → `make slice-commit MSG="..."` (commits + `close_slice` + regenerates CURRENT_TASK.json and DASHBOARD.txt atomically server-side)
13. **Before requesting review**: `make review-ready`; confirm zero errors
14. **Self-review with bug-finding heuristics**: Walk your diff through the [Bug-Finding Heuristics](branch-review-guide.md#bug-finding-heuristics-universal) checklist
15. **Regression trap sweep (handoff-learned)**: Verify stale/offline flows keep manual recovery, remote calls use shared timeout helpers, retry loops are per-cycle bounded, import/update paths preserve payload/provenance integrity, and reopened findings include explicit rationale
16. **Escalate when risk warrants**: If the slice crosses audit triggers such as architecture transitions, multi-service state machines, persistence changes, or broad UI state surfaces, run the [Multi-Lens Audit Workflow](branch-review-guide.md#multi-lens-audit-workflow) instead of a single-lens branch review
17. **End-of-turn user report must cite handoff evidence**: When a turn records a handoff decision, the final user-facing report for that turn must include the decision number (for example `Handoff decision: #1452`) so the chat summary and MCP trail stay explicitly linked.

External-install verification note:

- For the E17-13 MCP cleanup path, verify `workstate-handoff-mcp` and `workstate-orchestrator-mcp` from pinned `pip install` commands against the standalone repos in a scratch venv, not the old package-local Makefile guard guidance.
- The live verification contract is: pinned `pip install` from the standalone repos in a scratch venv, then `mcp-workstate-handoff --workspace-root . doctor` plus `mcp-workstate-orchestrator --workspace-root . --help` CLI/import smoke checks.
- Do not hardcode absolute filesystem paths; prefer `${env:HOME}`, `${workspaceFolder}`, and `${REPO_ROOT:-$PWD}`.

Commit SHA provenance discipline:

- Pass the **canonical 40-character SHA** from `git rev-parse HEAD` to every handoff `commit_sha` field. Never type SHAs from memory.
- The MCP write path validates every `commit_sha` via `git rev-parse --verify <sha>^{commit}` and rejects fabricated SHAs. Abbreviated SHAs that resolve uniquely are auto-expanded to 40 chars.
- Validation is bypassed in test suites via `AGENT_HANDOFF_SKIP_SHA_VALIDATION`. See [testing-python.md § Commit SHA Provenance Discipline](testing-python.md#commit-sha-provenance-discipline-mandatory).

---

## Gradual Layering

- **DO NOT** implement top-to-bottom (entire feature at once)
- **DO** scaffold interfaces, classes, and function signatures first
- **DO** implement in thin layers: signature -> tests -> minimal implementation -> refactor
- **DO** commit frequently (per-layer, not per-feature)

---

## Scaffolding First (MANDATORY)

**Before writing any implementation or tests, scaffold all interfaces and contracts.**

For TDD-compatible scaffolding, the order is:

1. Write the failing test stub that defines the expected behavior.
2. Scaffold only the minimal signature the test needs.
3. Verify the test fails for the intended reason.
4. Implement the smallest change that makes the test pass.

- Add function/method signatures with complete type hints
- Write comprehensive docstrings (Args, Returns, Raises, Examples)
- Use `raise NotImplementedError("TODO: ...")` as initial body
- **Verify scaffolds compile/type-check** before moving to implementation
- Test scaffolding is required first: create test files, fixtures, and failing test stubs before any implementation

**This applies to ALL new code**: Python functions/classes, TypeScript/React components/hooks, test signatures/fixtures, and cross-layer API schemas in `docs/workstate/contracts/`.

### Scaffolding Definition of Done

- [ ] All public function/method signatures exist with full type hints
- [ ] Docstrings describe Args, Returns, Raises (no implementation details)
- [ ] Bodies contain only `raise NotImplementedError("TODO: <specific task>")`
- [ ] `make typecheck` (from `apps/prototype-description-service/`) or `npm run typecheck` (TS) passes with zero errors
- [ ] Test file exists with `@pytest.mark.skip("scaffold")` or `it.todo()` stubs
- [ ] Cross-layer contracts (if any) are documented in `docs/workstate/contracts/`

**Enforcement**: Task checklists MUST include a "Phase 0: Scaffolding" section that is completed and verified before implementation phases begin.

## Cross-Boundary Change Protocol

Follow this checklist whenever a change alters or depends on a shared contract across a service, language, schema, or MCP boundary.

Trigger paths:

- `apps/prototype-description-service/`
- `apps/prototype-wp-alt-context/src/`
- `apps/prototype-wp-alt-context/js/`
- Installed `workstate-handoff-mcp`
- `docs/workstate/contracts/`

1. **Discover the owning contract.** Check [../contracts/](../contracts/). If none exists for a new cross-boundary call, scaffold the contract first.
2. **Validate contract parity.** If the contract is stale, update it in the same slice.
3. **Map changed fields to tests.** If no test covers the boundary, add one in the same slice.
4. **Run a runtime-parity check.** Verify the real runtime path, not only stubs. If local runtime verification is unavailable, log the gap as a finding.
5. **Record the change.** Use `record_decision` with the relevant template: [CONTRACT_CHANGE](../templates/DECISION_CONTRACT_CHANGE.template.md), [BREAKING_CHANGE](../templates/DECISION_BREAKING_CHANGE.template.md), or [CROSS_LANE](../templates/DECISION_CROSS_LANE.template.md).
6. **Notify affected lanes/owners** with the contract path, changed surface, and required follow-up.

## Architecture Diagram Change Protocol

Follow the [UML Change Checklist](uml-change-checklist.md) whenever a slice changes architecture represented in `docs/workstate/diagrams/`.

Trigger paths:

- `docs/workstate/diagrams/`
- `docs/workstate/maps/`
- `apps/prototype-description-service/recognition/`
- `apps/prototype-wp-alt-context/src/api/`
- `apps/prototype-wp-alt-context/js/admin/`

If a change modifies controller families, route namespaces, page inventory, workflow sequencing, or state-machine structure, update the relevant Mermaid diagrams in the same slice.

---

## Orchestrated Task Execution

When a task plan includes a "Lane Decomposition" section, use multi-agent orchestration: the orchestrator decomposes work into lanes, workers implement each lane in isolated worktrees.

### Choosing the Execution Path

| Condition                                                  | Execution path                                             |
| ---------------------------------------------------------- | ---------------------------------------------------------- |
| Codex harness detected + `codex-subagent-bridge` available | MCP worker lifecycle tools with `backend="codex-subagent"` |
| Shell-only + worktrees available                           | `make lane-open` / `make lane-run` / `make lane-handoff`   |
| Single-agent, no decomposition needed                      | Standard slice checklist above (no lanes)                  |

### Orchestrator Responsibilities

1. Initialize MCP task state (`set_handoff_state`).
2. Create the lane manifest (`make lane-manifest-init`).
3. Create worktree lanes and dispatch assignments via `make lane-dispatch` or MCP lane messages.
4. When using Codex subagents, start workers with `worker_start_all(task_ref, backend="codex-subagent")` and monitor with `worker_status`.
5. Review worker handoffs, intake merge-ready lanes in dependency order, and refresh downstream lanes.
6. If work was salvaged or added on the orchestrator/root branch outside a lane branch, propagate or refresh it before dispatching dependent lanes. A worker reporting "missing contract/stub surface" from its own worktree is a valid branch-state blocker, not noise.
7. Cross-lane briefs go through `record_lane_brief` (MCP) or `make lane-dispatch` (shell); never rely on chat memory alone.

### Worker Responsibilities

1. Poll `make lane-inbox` (or `make lane-prompt` for a generated prompt) to discover current assignment.
2. Implement only within owned paths.
3. Record test results, decisions, and blockers in MCP with `actor.lane_id`.
4. Hand back via `make lane-handoff` or, if blocked, report with `STATUS=blocked`.

Operational notes:

- `handoff_failed` after completed execution: intake or salvage the saved result, then restart the worker. Do not redo the slice.
- Hold downstream lanes when their worktree is missing upstream contracts, even if those files exist on the root branch.

### References

- Full playbook: [../playbooks/host-adapters/worktree-codex-playbook.md](../playbooks/host-adapters/worktree-codex-playbook.md)
- Lane-scoped context and prompt budgets: [../playbooks/lane-scoped-context.md](../playbooks/lane-scoped-context.md)
- Worker lifecycle MCP tools: [../contracts/workstate-handoff-mcp.md](../contracts/workstate-handoff-mcp.md)
- Lane brief template: [../templates/WORKTREE_LANE_BRIEF.template.md](../templates/WORKTREE_LANE_BRIEF.template.md)

---

## Epic, Task, and Decision Naming

### Epic Titles

New epics use a global sequential index in the title:

```text
E12. Epic and Task Reference Prefixing and Handoff Enforcement (v0.3.1)
```

Each epic declares an `Epic Short ID` (e.g., `E12`) near the top, namespacing all task references under that epic.

### Task Plan Titles

Task plan titles use the epic's short id plus a local sequential index, or a package/project-local task id for standalone work:

```text
E12-1. Naming Spec and Template Update
E12-3. MCP Decision Enforcement and Context Router
AHMCP-2. Bounded CURRENT_TASK Rendering and Mutation Output Cleanup
```

Use the epic-owned form by default. Use the package/project-local form only for standalone package work.

### Decision IDs

Slice-complete decision canonical form:

```text
<author_tag>_slice_complete_<work_ref>_<slug>
```

- `author_tag`: 2-12 lowercase letters identifying the agent (e.g., `cdx`, `copilot`, `claude`, `gemini`)
- `work_ref`: task reference (e.g., `E12-1`)
- `slug`: descriptive lowercase `[a-z0-9_]+`

Example: `cdx_slice_complete_E12-1_gate_validation`. Legacy `slice_complete_<slug>` format is grandfathered.

### Slice References

Slices use `Slice 1`, `Slice 2`, etc. headings. The compact form `E12-1/S1` is for cross-doc citations only.

### Templates

When creating new planning artifacts, load the corresponding template:

| Artifact   | Template                                                      |
| ---------- | ------------------------------------------------------------- |
| Assessment | [ASSESSMENT.template.md](../templates/ASSESSMENT.template.md) |
| Spec       | [SPEC.template.md](../templates/SPEC.template.md)             |
| ADR        | [ADR.template.md](../templates/ADR.template.md)               |
| Epic       | [EPIC.template.md](../templates/EPIC.template.md)             |
| Task plan  | [TASK_PLAN.template.md](../templates/TASK_PLAN.template.md)   |
| Roadmap    | [ROADMAP.template.md](../templates/ROADMAP.template.md)       |

### Planning Pipeline and Document Lifecycle

Not every layer is required -- small changes skip directly to a task plan. The full pipeline:

```
Epic (optional umbrella)
  └─ [Intake] → Assessment → Spec → [ADR] → Task Plan → Implementation → Review
```

`[Intake]` is the P0 scope-intake stage: required for new features and epics; skipped for bug fixes and spec-derived tasks. See [planning-pipeline.md § Stage 0](planning-pipeline.md#stage-0-intake-new-features-and-epics--conditional).

Full documentation: [planning-pipeline.md](planning-pipeline.md). Required gates between stages:

- Assessment → Spec: findings must cite `file:line` in current code
- Spec → Task Plan: at least one planning review pass with findings in MCP; all findings resolved
- Spec → ADR: only when a spec item is explicitly design-uncertain
- ADR → Task Plan: ADR reviewed before implementation tasks are created from it
- Task Plan → Implementation: task plan document committed and discoverable on `main` before `make task-start` is run; see [Stage 4 prerequisites](planning-pipeline.md#task-start-workflow)

#### Where Epics Fit

| Artifact      | Scope                                                      | Location                                           |
| ------------- | ---------------------------------------------------------- | -------------------------------------------------- |
| **Epic**      | Multi-phase capability spanning multiple task plans         | `docs/epics/v<version>/`                           |
| **Task plan** | Bounded unit of work under an epic (or standalone)          | `docs/tasks/<N>.0/` or package-local `docs/tasks/` |

**Create an epic** when work requires multiple task plans, has phase ordering dependencies, or spans multiple agents/sessions. **Skip to a task plan** for single-phase work, bug fixes, or small features.

#### Computing the Next Epic Number

Epic numbers are globally sequential across all `docs/epics/**/*-epic.md` files. Scan for the highest `E<number>`, increment by one. Numbers are permanent -- cancelled epics retire their number, never reuse it.

#### Version Directories

Epics are filed under `docs/epics/v<version>/` matching the target release milestone. Consolidated carry-forward work goes in the new version directory; the old epic gets a carry-forward note.

### Context Routing for Reviews

| Request intent                                            | Guide to load                                        |
| --------------------------------------------------------- | ---------------------------------------------------- |
| Code review, branch diff, PR review                       | [branch-review-guide.md](branch-review-guide.md)     |
| Assessment, spec, epic, task plan, roadmap, or ADR review | [planning-review-guide.md](planning-review-guide.md) |

For creating/updating planning artifacts, load the matching template from the table above.

### Grandfathering Rule

Historical documents and decision rows are grandfathered. Do not retroactively rename unless an artifact concretely blocks tooling or enforcement. The naming rules apply to **new** work only.

### New-Work Compliance Checklist

Reviewers can verify naming compliance for new artifacts with this short checklist:

1. Epic title starts with `E<number>.` and contains the correct global sequential index.
2. Epic declares an `Epic Short ID` field near the top.
3. Task plan title starts with `<EpicShortID>-<N>.` matching the owning epic, or uses the declared package/project-local task id when the task is not epic-owned.
4. Slice-complete decisions use the `<author_tag>_slice_complete_<work_ref>_<slug>` grammar.
5. Historical docs and decision rows that predate the scheme are left as-is unless they cause a concrete blocker.

---

## Conventional Commits

```text
feat(dashboard): add coverage trend visualization
fix(workbench): correct filter reset behavior
docs(architecture): update face recognition flow
test(coverage-card): add accessibility tests
refactor(api): simplify error handling
chore(deps): update react-query to v5.18
```

---

## Branch Naming

```text
feat/dashboard-cards
fix/alt-text-escaping
refactor/clustering-pipeline
```

---

## Roadmap Status Tags

```text
[DONE]     - User-visible, tested, documented
[PARTIAL]  - Some flows complete, more slices planned
[PLANNED]  - No implementation yet
[BLOCKED]  - Awaiting dependency (include brief reason)
```

---

## Session State with MCP Handoff + CURRENT_TASK.json

MCP handoff state is the source of truth; `CURRENT_TASK.json` is a generated view. A `docs/tasks/` plan is optional; an MCP handoff task is not.

Source-of-truth policy:

- `.task-state/handoff.db` is authoritative. `CURRENT_TASK.json` is derived output -- never hand-edit it.
- If markdown drifts from DB, regenerate (`render_handoff(kind='dashboard')`) and continue from DB state.
- After archiving a merged task, regenerate DASHBOARD.txt in the same cleanup slice (`render_handoff(kind='dashboard')`).
- A task is not fully cleaned up until its review findings are closed or explicitly deferred.

**Use for:** every repo change, multi-session tasks, complex debugging, multi-phase implementations.
**When MCP is unavailable:** treat as a blocker; fall back to generated markdown temporarily.

**Workflow:**

1. Initialize or update active task via `set_handoff_state`.
2. Record session outcomes via MCP tools. After every `record_decision` covering a code change, notify the user (mandatory).
3. Read compact snapshot at session start via `get_handoff_state`.
4. Record a slice-complete decision for every completed slice using the [decision naming grammar](#decision-ids).
5. Close the slice in every active tracker before moving on. Mark completed/skipped MCP next actions and update task-plan checklist boxes.
6. Before close/final handoff, run `handoff_close_check(enforce=True, current_commit_sha=<HEAD>)`.
7. Before requesting review, run `make review-ready` and resolve all NOT READY reasons.
8. Regenerate DASHBOARD.txt after merge/archive (mandatory): `render_handoff(kind='dashboard')`. If a completed task still appears in NEEDS ATTENTION, close or defer its remaining findings first.
9. Use template fallback only when MCP is unavailable.

### Provenance Drift Recovery

The handoff provenance guard blocks two classes of writes before they land in MCP:

- MCP tool writes whose explicit `actor.branch` matches the active task `target_branch` but whose `actor.commit_sha` does not resolve to the task worktree HEAD.
- Bash Python-API fallback writes (`from workstate_handoff_mcp import ...`) that do not start with an explicit `cd <target_worktree_path> &&` or do not pass an explicit `task_ref=...`.

When the guard fires with `handoff provenance drift`, recover by switching to the owning worktree and retrying there:

- `cd <target_worktree_path>`
- rerun the MCP write, or for the Bash fallback rerun it as `cd <target_worktree_path> && uvx --from "mcp-workstate-handoff==0.12.0" python3 -c "... task_ref='<task-ref>' ..."`

The guard is fail-open when it cannot resolve task identity or git metadata; validation failures should not become write outages. There is no bypass marker for normal implementation work. If a legitimate cross-worktree write is required, stop and route that operation through the owning task worktree instead of forcing it from the wrong cwd.

**Template location:** [templates/CURRENT_TASK.template.md](../templates/CURRENT_TASK.template.md)

> [!TIP]
> The `<- ACTIVE` marker in the progress section tells the next agent exactly where to resume without reading the entire file.
