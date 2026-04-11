# Development Workflow

> Load this document for detailed workflow procedures: branch isolation, scaffolding, TDD cycle, commit conventions, and review preparation.

---

## Branch Isolation Protocol (MANDATORY)

**Code files must never be edited on the `main` branch.** This rule is enforced in both harnesses:

- **VS Code Copilot**: `.github/hooks/terminal-guard.json` runs `.github/hooks/guard-main-branch.py` on every `PreToolUse` event and blocks `apply_patch` / `create_file` requests that target code files under `apps/` or `packages/` while the current branch is `main`.
- **Claude Code**: `.claude/settings.json` runs `scripts/hooks/guard-main-branch.sh` for `Edit|Write` requests and applies the same policy.

Protected code extensions: `*.py`, `*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.php`, `*.sql`, `*.sh`, `*.css`, `*.scss`.

**Allowed on `main`:** documentation, planning artifacts (assessments, specs, ADRs, task plans), configuration files, Makefiles, markdown, and settings. These are legitimate planning-phase edits that do not risk dirty working tree bleed. **All planning work stays on `main` so the human can review it without switching worktrees.** Feature branches and linked worktrees are created only when the plan is approved and implementation begins. See [planning-pipeline.md § Planning stays on main](planning-pipeline.md#planning-stays-on-main-implementation-branches-after-approval) for the full two-phase flow.

**Before any code edit:**

1. Create a feature branch: `git checkout -b feature/<task-id>-<slug>`
2. Or use Claude Code worktree isolation: `Agent` tool with `isolation: "worktree"`
3. Or use the full lane orchestration: `make lane-open TASK=<task> LANE=<lane>`

**If you inherit dirty code changes on `main`:** stop and move them to a feature branch or stash them before starting new implementation work. Uncommitted code on `main` is branch bleed; treat it as a workflow defect, not a normal starting state.

**Why this matters:** Uncommitted code changes on `main` bleed into every subsequent agent session. An agent that starts work on `main` inherits stale diffs from prior sessions, leading to accidental commits of unrelated changes, merge conflicts, and broken bisectability. Branch isolation eliminates this class of error.

**Isolation tiers** (choose based on task complexity):

| Tier                       | Mechanism                                 | When to use                                                    |
| -------------------------- | ----------------------------------------- | -------------------------------------------------------------- |
| **Feature branch**         | `git checkout -b feature/<id>-<slug>`     | Single-agent, single-task work                                 |
| **Worktree (Claude Code)** | `Agent` tool with `isolation: "worktree"` | Delegated subtasks that should not touch the main working tree |
| **Lane orchestration**     | `make lane-open` + `make lane-handoff`    | Multi-agent parallel work with scope enforcement               |

The harness guard implementations live at `.github/hooks/guard-main-branch.py` and `scripts/hooks/guard-main-branch.sh`. If a hook incorrectly blocks a legitimate edit, fix the scope or extension classification; do not normalize code edits on `main` as acceptable.

### Worktree Ownership Rule

**The root worktree stays on `main`. Always. Linked worktrees are always on feature branches.**

- Never check out `main` in a linked worktree (`git worktree add ... main` is forbidden).
- Never leave the root worktree on a feature branch after merging -- switch it back to `main` immediately.
- Git only allows one worktree per branch. If `main` is checked out in a linked worktree, every other agent and worktree loses access to `main`, blocking planning work, merges, and doc reads.

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

### Concurrent Editor Buffers (BUFFER ISOLATION)

> **Branch isolation prevents agent-vs-agent collisions across branches. Buffer isolation prevents agent-vs-editor collisions inside the same root worktree.**

The branch isolation rule above stops *agents* from racing on `main`, but it does not stop a long-lived **editor buffer** (VS Code, Cursor, JetBrains, vim, etc.) from doing the same thing through a different path. The failure mode looks like this:

1. You open `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` in your editor before any work begins. The editor reads the file and holds an in-memory buffer.
2. An agent merges a feature branch into `main` that adds 3 hunks to `api.py`. The on-disk file now contains the new content; HEAD agrees with disk.
3. Some time later, your editor's auto-save (or "save all", or a focus-loss flush, or a format-on-save run) writes the **stale buffer** back to disk. The buffer was loaded *before* the merge, so it does not contain the 3 new hunks. The on-disk file silently regresses to the pre-merge content while HEAD still points at the post-merge commit. `git status` now shows `M api.py` with no record of who wrote it.
4. The next merge or task-finish that tries to use the regressed file fails. In the AHMCP-15-BR-FIXES → AHMCP-16 incident on this repo, the regression was an `ImportError` from `task-finish.sh` trying to `from agent_handoff_mcp import get_archived_task` after the symbol had been silently removed by exactly this mechanism. **Stash@{1}** in this checkout is literally named `session-bleed accumulated working-tree at codex/e15-7-plan-fixes pre-merge stash 2026-04-08`, so the failure mode is recurring and named.

**No agent layer can detect this race in real time** because the editor write does not go through git, does not go through `agent-handoff-mcp`, and leaves no entry in any tracked log. The mitigations are editor-side and detection-side:

#### Editor-side mitigations (mandatory for any editor open against this repo)

| Editor | Setting that prevents stale-buffer overwrites |
| --- | --- |
| **VS Code** / **Cursor** | `"files.autoSave": "off"` is the safest default. If auto-save is required, use `"files.autoSave": "onFocusChange"` AND enable `"files.refactoring.autoSave": false` so renames/refactors do not silently flush. Always set `"editor.formatOnSave"` to `false` for files outside your active focus. |
| **JetBrains** (IntelliJ, PyCharm, WebStorm) | Settings → Appearance & Behavior → System Settings → uncheck "Save files when switching to another application" and "Save files automatically if application is idle for N sec". Use explicit `Ctrl+S` instead. |
| **vim / neovim** | Add `set autoread` so the editor reloads files when they change on disk. Without this, switching branches under a held buffer creates the same staleness. |
| **Emacs** | `(global-auto-revert-mode 1)` enables auto-reload from disk. |

The single most important behavior is **reload-on-disk-change**, not auto-save. An editor that reloads when a file changes underneath it cannot accidentally clobber a merge.

#### Detection-side mitigations (enforced by the lifecycle scripts)

Even with correct editor settings, mistakes happen. The lifecycle scripts now run a working-tree integrity check at two points:

1. **`make context`** (every session start) prints a `⚠ Working-tree integrity` warning when `git diff --name-only HEAD` reports tracked files that are not listed in `.task-state/dirty-allowlist`. This catches stale buffer flushes that happened *between* sessions.
2. **`make task-finish`** (every merge teardown) runs the same check via bash and **refuses to archive** when integrity fails (exit code 4). This catches stale buffer flushes that happened *during* a session, before the archive write commits an invalid state.

The escape hatch for both is `.task-state/dirty-allowlist` — a plain newline-delimited list of repo-relative paths that you have intentionally modified outside any task. Add a file to it when the drift is intentional; otherwise resolve the drift before recording further handoff state.

```bash
# Example .task-state/dirty-allowlist
# Files I'm intentionally editing in parallel with task work:
docs/agentic/instructions.md
docs/agentic/rules/development-workflow.md
# Pre-existing orchestrator package work that pre-dates the active task:
packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py
```

---

## Pre-Merge Gate (MANDATORY)

> **No feature branch merges to `main` without a passing pre-merge gate. No exceptions.**

Branch isolation gets the work onto a feature branch. The pre-merge gate enforces that the work has been **reviewed**, **verified**, and **logged in MCP handoff** before it lands on `main`. This rule exists because branches that merge fast and unreviewed cause the same class of regressions the branch isolation guard is meant to prevent (accidental commits, untested behavior, dirty state bleed).

### Gate Requirements

A feature branch is **merge-ready** only when **all** of the following are true:

1. **At least one review pass on the active task ref**, with findings recorded in MCP handoff via `review_findings(operation="record"|"batch_record")`. The review can be a planning review (for docs-only branches) or a branch review (for code branches). The choice is enforced by [Context Routing for Reviews](#context-routing-for-reviews).
2. **Zero open findings** on the task ref. Every recorded finding must be in status `fixed`, `deferred` (with rationale), or `wontfix` (with rationale). Verify with `review_findings(operation="list", status="open")`.
3. **Fresh `test_result` evidence** for the current branch state, recorded via `record_event(event_kind="test_result", ...)`. The PHP/Python/TS branch-review guides specify which test commands satisfy this for each stack. "Fresh" means recorded against the current HEAD commit SHA.
4. **`handoff_close_check(enforce=True, current_commit_sha=<HEAD>)` passes.** This is the canonical machine-checked gate. It verifies items 1-3 against the handoff DB and refuses to pass if anything is missing.
5. **Slice-complete decision recorded** for the work landing in the merge, using the `<author_tag>_slice_complete_<work_ref>_<slug>` grammar.

### Enforcement Mechanisms

The gate is enforced by multiple guardrails — defense in depth, not a single point of failure:

- **Handoff DB (authoritative).** `handoff_close_check(enforce=True)` is the canonical check. Any agent or operator merging without passing it is violating the protocol.
- **Branch isolation hook.** `.claude/settings.json` and `.github/hooks/terminal-guard.json` already block code edits on `main`, which prevents the most common bypass (committing fixes directly to `main` to "skip" the gate).
- **Documentation.** This section is referenced from [CLAUDE.md](../../../CLAUDE.md) Critical Rules so cold-start agents see it before any merge.
- **Reviewer sign-off.** The reviewer recording the verdict decision must cite the decision number of the artifact under review (e.g. "review of decision #966") so the bidirectional link in handoff search makes the gate traceable.

### Pre-Merge Sequence

```
On the feature branch, after final commit:

1.  Run the stack-specific test suite. Record results:
    record_event(event_kind="test_result", task_ref=..., command=..., passed=true,
                 actor={..., commit_sha=<HEAD>})

2.  Run review-ready and resolve all NOT READY reasons:
    make review-ready

3.  Request review (planning or branch, per Context Routing). Reviewer records
    findings in MCP. Reviewer records verdict decision linking to the reviewed
    artifact's decision number.

4.  For each open finding: fix the issue, then close it with verification_evidence:
    review_findings(operation="update", finding_id=..., status="fixed",
                    verified_commit_sha=<HEAD>, verification_evidence=...)

5.  Confirm zero open findings:
    review_findings(operation="list", task_ref=..., status="open")
    Expected: total_matching == 0

6.  Record the slice-complete decision:
    record_event(event_kind="decision", decision="<tag>_slice_complete_<work_ref>_<slug>",
                 actor={..., commit_sha=<HEAD>})

7.  Run the canonical close check:
    handoff_close_check(enforce=True, current_commit_sha=<HEAD>)
    Expected: ok=true, no failures

8.  Merge the feature branch into main, return root to main, delete the feature branch, close any still-open post-merge review findings on the merged task from a descendant `main` context, archive the task, and regenerate `CURRENT_TASK.md`.
```

### When the Gate May Be Skipped

**Never.** Process exemptions normalize the very behavior the gate exists to prevent. If a finding genuinely cannot be fixed in this branch, mark it `deferred` with a written rationale and an explicit follow-up task ref — that satisfies item 2 (zero **open** findings) without skipping the gate.

The only legitimate "skip" is for trivial documentation edits to files that have no associated review process (e.g., a typo fix in a README). Even then, the operator should record a brief decision in MCP so the audit trail remains intact.

### Gate Failure Recovery

If `handoff_close_check(enforce=True)` fails:

- Read the failure reasons. Each is one of: missing review, open findings, stale test results, missing slice-complete decision, commit-SHA mismatch.
- Resolve the underlying issue. Do not work around the check by passing `enforce=False` — that defeats the gate.
- Re-run the check until it passes.
- Only then merge.

If a stale test_result event blocks the gate (e.g., test was run on an older commit), re-run the test suite and record a fresh `test_result` event tied to the current HEAD SHA. The check uses commit-SHA descendants to detect staleness.

---

## Slice Checklist

For every unit of work (feature slice, bug fix, refactor):

1. Identify the roadmap epic you are advancing
2. **Scaffold first**: Create class/function signatures with type hints and docstrings BEFORE implementation
3. **Write failing tests first** (PHPUnit, Vitest, or integration) -- TDD is mandatory
4. If remote dependencies exist, add a provider interface + mock
5. Implement minimal production code to pass tests (Red -> Green -> Refactor)
6. Refactor for clarity while tests stay green
7. Run the [UML Change Checklist](uml-change-checklist.md) if architecture changed
8. Security pass: nonce/capability checks, escape/sanitize
9. Accessibility pass: keyboard navigation, ARIA labels
10. Run full test suite locally before committing
11. Commit with Conventional Commits format
12. **Before requesting review**: Run required automated checks from the [Branch Review Guide](branch-review-guide.md#how-to-use-this-guide) and confirm zero errors
13. **Self-review with bug-finding heuristics**: Walk your diff through the [Bug-Finding Heuristics](branch-review-guide.md#bug-finding-heuristics-universal) checklist
14. **Regression trap sweep (handoff-learned)**: Verify stale/offline flows keep manual recovery, remote calls use shared timeout helpers, retry loops are per-cycle bounded, import/update paths preserve payload/provenance integrity, and reopened findings include explicit rationale
15. **Escalate when risk warrants**: If the slice crosses audit triggers such as architecture transitions, multi-service state machines, persistence changes, or broad UI state surfaces, run the [Multi-Lens Audit Workflow](branch-review-guide.md#multi-lens-audit-workflow) instead of a single-lens branch review
16. **End-of-turn user report must cite handoff evidence**: When a turn records a handoff decision, the final user-facing report for that turn must include the decision number (for example `Handoff decision: #1452`) so the chat summary and MCP trail stay explicitly linked.

Package-test execution note:

- For `packages/agent-handoff-mcp/` and `packages/agent-orchestrator-mcp/`, **always invoke pytest via the package Makefile target** (`make test-handoff` / `make test-orchestrator`), never via a direct `pytest` command. The Makefile sets `PYTHONPATH` to the current worktree's `src/` directory so imports actually resolve to the worktree's source instead of whatever editable install is registered in the Python environment. Direct `pytest` invocations from a linked worktree silently test against the editable install's source path (typically the root checkout), producing false-positive verifications when the linked worktree contains a refactor that the root checkout does not. Both packages' `tests/conftest.py` enforce this with a `pytest_sessionstart` guard that aborts the session with a `pytest.UsageError` when `import agent_handoff_mcp` resolves to the wrong path. See [testing-python.md § In-Monorepo Package Test Invocation](testing-python.md#in-monorepo-package-test-invocation-mandatory) for the full rationale and the `AHMCP-10` regression that motivated the enforcement.
- Do not hardcode user-local absolute filesystem paths such as `/Users/...` in commands or examples; prefer environment variables such as `${PYENV_ROOT:-$HOME/.pyenv}` and `${REPO_ROOT:-$PWD}`.
- Canonical example: `cd "$REPO_ROOT/packages/agent-handoff-mcp" && make test-handoff` (or `make test-orchestrator` from the orchestrator package directory). The Makefile pins the interpreter via `PYENV_VERSION=description-service` and sets `PYTHONPATH` to the worktree-local `src/` directory before invoking pytest.

Commit SHA provenance discipline:

- Whenever a handoff write path accepts a `commit_sha` field (`record_event(actor=...)`, `set_handoff_state(actor=...)`, `update_review_finding(verified_commit_sha=...)`, `handoff_close_check(current_commit_sha=...)`, etc.), pass the **canonical 40-character SHA** from `git rev-parse <abbrev>` or `git rev-parse HEAD`. Never type the suffix from memory after seeing a 7-char abbreviation in `git commit` output.
- The MCP write path validates every `commit_sha` against the active git repo via `git rev-parse --verify <sha>^{commit}`. Fabricated SHAs (typed from memory or otherwise) are rejected with an error pointing at this rule. Abbreviated SHAs that resolve uniquely are auto-expanded to the full 40-char form before being stored, so callers can pass `bb24ee59` and the audit trail still records `bb24ee5945273ebc4663b6d264023d9542823310`.
- Validation is bypassed inside the test suites via the `AGENT_HANDOFF_SKIP_SHA_VALIDATION` env var (set in both packages' `tests/conftest.py`); production callers always run with validation enabled. See [testing-python.md § Commit SHA Provenance Discipline](testing-python.md#commit-sha-provenance-discipline-mandatory) for the full rationale and the `AHMCP-10`/`AHMCP-11` audit-trail bug that motivated the enforcement.

---

## Gradual Layering

- **DO NOT** implement top-to-bottom (entire feature at once)
- **DO** scaffold interfaces, classes, and function signatures first
- **DO** implement in thin layers: signature -> tests -> minimal implementation -> refactor
- **DO** commit frequently (per-layer, not per-feature)

This ensures:

- Clear contracts before implementation details
- Testable interfaces from the start
- Incremental progress with working checkpoints
- Easier code review (smaller, focused diffs)

---

## Scaffolding First (MANDATORY)

**Before writing any implementation or tests, scaffold all interfaces and contracts.**

- Add function/method signatures with complete type hints
- Write comprehensive docstrings (Args, Returns, Raises, Examples)
- Use `raise NotImplementedError("TODO: ...")` as initial body
- **Verify scaffolds compile/type-check** before moving to implementation
- Test scaffolding is required first: create test files, fixtures, and failing test stubs before any implementation

**This applies to ALL new code**:

- Backend: Python functions, classes, methods
- Frontend: TypeScript functions, React components, hooks
- Tests: Test function signatures and fixtures
- Cross-layer contracts: Define API schemas in `docs/agentic/contracts/` before implementing endpoints

### Why Scaffolding First? (Agentic Coding Rationale)

| Benefit                        | Why It Matters for Agents                                                                                                                        |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Prevents context rot**       | Agent context windows are finite. Scaffolding while problem is fresh ensures contracts are defined before 50+ implementation files dilute focus. |
| **Cheap reversibility**        | Changing a signature costs ~10 tokens; changing an implementation costs ~500. Get the API right first.                                           |
| **Token-efficient references** | Agents can reference `ClusterService.merge()` signature without re-reading 200-line implementation.                                              |
| **Parallel work enablement**   | Human can review API design in PR while agent implements.                                                                                        |
| **Incremental verification**   | `mypy`/`tsc` on scaffolds catches type mismatches before implementation obscures them.                                                           |
| **Cross-layer contracts**      | In monorepos (PHP<->Python<->TS), scaffolding both sides prevents integration drift.                                                             |

### Scaffolding Definition of Done

- [ ] All public function/method signatures exist with full type hints
- [ ] Docstrings describe Args, Returns, Raises (no implementation details)
- [ ] Bodies contain only `raise NotImplementedError("TODO: <specific task>")`
- [ ] `PYENV_VERSION=description-service mypy .` (from `apps/prototype-description-service/`) or `npm run typecheck` (TS) passes with zero errors
- [ ] Test file exists with `@pytest.mark.skip("scaffold")` or `it.todo()` stubs
- [ ] Cross-layer contracts (if any) are documented in `docs/agentic/contracts/`

**Enforcement**: Task checklists MUST include a "Phase 0: Scaffolding" section that is completed and verified before implementation phases begin.

## Cross-Boundary Change Protocol

Follow this checklist whenever a change touches a service, language, schema, or MCP boundary. This protocol applies even when only one path family is edited, as long as the change alters or depends on a shared contract.

Trigger heuristics:

- `apps/prototype-description-service/`
- `apps/prototype-wp-alt-context/src/`
- `apps/prototype-wp-alt-context/js/`
- `packages/agent-handoff-mcp/`
- `docs/agentic/contracts/`

If a change within one of those stacks modifies a shared type, endpoint signature, REST route, database schema, or MCP API surface, run the protocol before continuing.

1. Discover the owning contract. Check [../contracts/](../contracts/) for the surface that governs the boundary. If none exists and the change introduces a new cross-boundary call, scaffold the contract first.
2. Validate contract parity. Confirm the contract matches the current implementation. If it is stale, update the contract in the same slice as the code change.
3. Map changed fields to tests. Identify which downstream assertions prove the changed field or behavior. If no test covers the boundary, add one in the same slice.
4. Run a runtime-parity check. For remote calls or adapter paths, verify the real runtime path works, not only the stubbed or unit-test path. If true runtime verification is not available locally, log that gap as a finding instead of claiming full verification.
5. Record the change with evidence. Use `record_decision` with the relevant decision template from [../templates/DECISION_CONTRACT_CHANGE.template.md](../templates/DECISION_CONTRACT_CHANGE.template.md), [../templates/DECISION_BREAKING_CHANGE.template.md](../templates/DECISION_BREAKING_CHANGE.template.md), or [../templates/DECISION_CROSS_LANE.template.md](../templates/DECISION_CROSS_LANE.template.md).
6. Notify affected lanes or owners. If another lane or stack depends on the new contract shape, send a lane message or dispatch update with the contract path, changed surface, and required follow-up.

## Architecture Diagram Change Protocol

Follow the [UML Change Checklist](uml-change-checklist.md) whenever a slice changes architecture that is represented in `docs/agentic/diagrams/`.

Trigger heuristics:

- `docs/agentic/diagrams/`
- `docs/agentic/maps/`
- `apps/prototype-description-service/recognition/`
- `apps/prototype-wp-alt-context/src/api/`
- `apps/prototype-wp-alt-context/js/admin/`

If a change modifies controller families, route namespaces, page inventory, workflow sequencing, or state-machine structure, update or explicitly confirm the relevant Mermaid diagrams in the same slice.

---

## Orchestrated Task Execution

When a task plan includes a "Lane Decomposition" section, use the multi-agent orchestration workflow. The orchestrator agent decomposes work into lanes, and worker agents implement each lane in isolated worktrees.

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

- `handoff_failed` after completed execution is an orchestration-state issue, not a signal to redo the same slice. Intake or salvage the saved result, then restart the worker for the next assignment.
- Downstream lanes should be held when their branch-local worktree is missing upstream contracts or scaffold surfaces, even if those files exist on the orchestrator/root branch.

### References

- Full playbook: [../playbooks/host-adapters/worktree-codex-playbook.md](../playbooks/host-adapters/worktree-codex-playbook.md)
- Lane-scoped context and prompt budgets: [../playbooks/lane-scoped-context.md](../playbooks/lane-scoped-context.md)
- Worker lifecycle MCP tools: [../contracts/agent-handoff-mcp.md](../contracts/agent-handoff-mcp.md)
- Lane brief template: [../templates/WORKTREE_LANE_BRIEF.template.md](../templates/WORKTREE_LANE_BRIEF.template.md)

---

## Epic, Task, and Decision Naming

### Epic Titles

New epics use a global sequential index in the title:

```text
E12. Epic and Task Reference Prefixing and Handoff Enforcement (v0.3.1)
```

Each epic declares an `Epic Short ID` (e.g., `E12`) near the top of the document. This short id namespaces all task references under that epic.

### Task Plan Titles

Task plan titles use either the owning epic's short id plus a local sequential index, or a documented package/project-local task id when the work belongs to a standalone package/project rather than a monorepo epic:

```text
E12-1. Naming Spec and Template Update
E12-3. MCP Decision Enforcement and Context Router
AHMCP-2. Bounded CURRENT_TASK Rendering and Mutation Output Cleanup
```

Use the epic-owned form by default for monorepo task plans. Use the package/project-local form only when the work is explicitly owned by a standalone or package-local planning sequence.

### Decision IDs

Handoff decision ids carry an author tag and a work reference. For slice-complete decisions the canonical form is:

```text
<author_tag>_slice_complete_<work_ref>_<slug>
```

- `author_tag`: 2-4 lowercase letters identifying the authoring agent (e.g., `cdx`, `cop`, `cla`, `gem`)
- `work_ref`: the task reference such as `E12-1` or another recognized task ref
- `slug`: a descriptive lowercase label using `[a-z0-9_]+`

Example: `cdx_slice_complete_E12-1_gate_validation`

The legacy `slice_complete_<slug>` format is grandfathered for historical rows. New writes should use the prefixed form.

### Slice References

Slices within a task plan use existing `Slice 1`, `Slice 2`, etc. headings. The compact cross-doc form `E12-1/S1` is optional and should be used only when citing a specific slice from another document or handoff entry.

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

Work flows through a layered document lifecycle. Not every layer is required for every piece of work -- small changes skip directly to a task plan or implementation. The full pipeline exists to prevent premature implementation of complex or boundary-crossing work.

```
Epic (optional umbrella)
  └─ Assessment → Spec → [ADR] → Task Plan → Implementation → Review
```

Full pipeline documentation with stage definitions, exit gates, and exemplars:
[planning-pipeline.md](planning-pipeline.md).

Quick reference — required gates between stages:

- Assessment → Spec: findings must cite `file:line` in current code
- Spec → Task Plan: at least one planning review pass with findings in MCP; all findings resolved
- Spec → ADR: only when a spec item is explicitly design-uncertain
- ADR → Task Plan: ADR reviewed before implementation tasks are created from it
- Task Plan → Implementation: task plan document committed and discoverable on `main` before `make task-start` is run; see [Stage 4 prerequisites](planning-pipeline.md#task-start-workflow)

#### Where Epics Fit

Epics sit above the per-change pipeline. An epic defines the destination, phase ordering, and exit criteria for a capability or process change that spans multiple task plans. Each epic phase may trigger its own assessment → spec → task plan pipeline as the work is decomposed.

| Artifact      | Scope                                                                                       | Location                                           |
| ------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| **Epic**      | Multi-phase capability; groups task plans under a shared objective and delivery sequence    | `docs/epics/v<version>/`                           |
| **Task plan** | Executable implementation slices for one bounded unit of work under an epic (or standalone) | `docs/tasks/<N>.0/` or package-local `docs/tasks/` |

**When to create an epic:**

- Work will take more than one task plan to complete
- Work spans multiple delivery phases with ordering dependencies
- Multiple agents or sessions will contribute to the same objective

**When to skip the epic and go straight to a task plan:**

- Single-phase work with a clear scope and no phase dependencies
- Bug fixes, small features, or debt cleanup that fits in one task plan

#### Computing the Next Epic Number

Epic numbers are globally sequential across all `docs/epics/**/*-epic.md` files. To determine the next number:

1. Scan all epic files for the highest `E<number>` in the title.
2. Increment by one. Do not recycle numbers from closed or archived epics.
3. Use the new number in the epic title (`E<N>. <Title>`) and declare it as the `Epic Short ID`.

The epic number is permanent once assigned. If an epic is cancelled, its number is retired, not reused.

#### Version Directories

Epics are filed under `docs/epics/v<version>/` where the version reflects the release milestone the epic targets. When remaining work from an older version is consolidated into a new epic, the new epic goes in the new version directory and the old epic gets a carry-forward note.

### Context Routing for Reviews

When the request is a review, load the matching guide based on the target artifact:

| Request intent                                            | Guide to load                                        |
| --------------------------------------------------------- | ---------------------------------------------------- |
| Code review, branch diff, PR review                       | [branch-review-guide.md](branch-review-guide.md)     |
| Assessment, spec, epic, task plan, roadmap, or ADR review | [planning-review-guide.md](planning-review-guide.md) |

When the request is to create or update a planning artifact, load the matching template from the table above.

### Grandfathering Rule

Historical planning documents and historical handoff decision rows are grandfathered by default. Do not plan or execute retroactive renames unless a specific artifact concretely blocks review, tooling, or MCP enforcement. The naming rules above apply to **new** work only.

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

## Session State with MCP Handoff + CURRENT_TASK.md

For all repo changes, use MCP handoff state tools as the source of truth and treat `CURRENT_TASK.md` as a generated view. A `docs/tasks/` plan is optional; an MCP handoff task is not.

Source-of-truth policy:

- `.task-state/handoff.db` is authoritative for agent state.
- `CURRENT_TASK.md` is derived output; never hand-edit it as the canonical tracker.
- `CURRENT_TASK.md` includes a cross-task dashboard header plus the active task's detail section, so task switches should not erase visibility into other in-flight work.
- If markdown drifts from DB, regenerate (`generate_current_task_md`) and continue from DB state.
- After a merged task is archived, regenerate `CURRENT_TASK.md` in the same cleanup slice so completed merged work does not linger as stale active detail.
- A task is not considered fully cleaned up until its merged-task review findings are also closed or explicitly deferred; otherwise it will continue to appear in the dashboard header even after archive.

**When to use:**

- Every change that edits repo files
- Tasks spanning multiple sessions (> 1 hour of work)
- Complex debugging where findings need to be preserved
- Multi-phase implementations with dependencies between phases

**When NOT to use:**

- Only when MCP tooling is unavailable; treat that as a blocker and fall back temporarily to generated markdown until MCP access is restored

**Workflow:**

1. Initialize or update active task via MCP `set_handoff_state`.
2. Record session outcomes via MCP tools (`record_decision`, `update_next_actions`, `record_test_result`, `report_blocker`). After every `record_decision` that covers a code change, notify the user that the handoff has been updated (e.g. "Handoff updated: decision `<id>` recorded."). This notification is mandatory.
3. Read compact snapshot at session start via `get_handoff_state`.
4. Record a structured slice-complete decision for every completed slice using the [decision naming grammar](#decision-ids), including docs-only or no-plan slices.
5. Close the slice in every active tracker before moving on. Mark completed or skipped MCP next actions, update the relevant task-plan checklist boxes for the slice you just finished, and leave future-slice items open instead of carrying a fully stale checklist forward.
6. Before close/final handoff, run `handoff_close_check(enforce=True, current_commit_sha=<HEAD>)` and resolve all failures.
7. Before requesting branch review, run `make review-ready` from the current worktree and resolve all reported NOT READY reasons.
8. Regenerate markdown view on demand via `generate_current_task_md`; after merge/archive this is mandatory, and the dashboard header plus active-task detail must both reflect the latest DB state. If a completed merged task still appears, treat that as a cleanup failure: close or defer its remaining findings, then regenerate again.
9. Use template fallback only when MCP tooling is unavailable.

**Template location:** [templates/CURRENT_TASK.template.md](../templates/CURRENT_TASK.template.md)

> [!TIP]
> The `<- ACTIVE` marker in the progress section tells the next agent exactly where to resume without reading the entire file.
