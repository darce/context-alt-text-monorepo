# Development Workflow

> Load this document for detailed workflow procedures: scaffolding, TDD cycle, commit conventions, and review preparation.

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

| Condition | Execution path |
| --- | --- |
| Codex harness detected + `codex-subagent-bridge` available | MCP worker lifecycle tools with `backend="codex-subagent"` |
| Shell-only + worktrees available | `make lane-open` / `make lane-run` / `make lane-handoff` |
| Single-agent, no decomposition needed | Standard slice checklist above (no lanes) |

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

- Full playbook: [../worktree-codex-playbook.md](../worktree-codex-playbook.md)
- Lane-scoped context and prompt budgets: [../lane-scoped-context.md](../lane-scoped-context.md)
- Worker lifecycle MCP tools: [../contracts/agent-handoff-mcp.md](../contracts/agent-handoff-mcp.md)
- Lane brief template: [../templates/WORKTREE_LANE_BRIEF.template.md](../templates/WORKTREE_LANE_BRIEF.template.md)

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
- If markdown drifts from DB, regenerate (`generate_current_task_md`) and continue from DB state.

**When to use:**

- Every change that edits repo files
- Tasks spanning multiple sessions (> 1 hour of work)
- Complex debugging where findings need to be preserved
- Multi-phase implementations with dependencies between phases

**When NOT to use:**

- Only when MCP tooling is unavailable; treat that as a blocker and fall back temporarily to generated markdown until MCP access is restored

**Workflow:**

1. Initialize or update active task via MCP `set_handoff_state`.
2. Record session outcomes via MCP tools (`record_decision`, `update_next_actions`, `record_test_result`, `report_blocker`).
3. Read compact snapshot at session start via `get_handoff_state`.
4. Record a structured `slice_complete_<short_label>` decision for every completed slice, including docs-only or no-plan slices.
5. Before close/final handoff, run `handoff_close_check(enforce=True, current_commit_sha=<HEAD>)` and resolve all failures.
6. Before requesting branch review, run `make review-ready` from the current worktree and resolve all reported NOT READY reasons.
7. Regenerate markdown view on demand via `generate_current_task_md`.
8. Use template fallback only when MCP tooling is unavailable.

**Template location:** [templates/CURRENT_TASK.template.md](../templates/CURRENT_TASK.template.md)

> [!TIP]
> The `<- ACTIVE` marker in the progress section tells the next agent exactly where to resume without reading the entire file.
