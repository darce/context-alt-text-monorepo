# Superpowers Evaluation for Agentic Process Hardening

## Objective

Evaluate whether [`obra/superpowers`](https://github.com/obra/superpowers) would materially reduce the work described in [agentic-development-process-hardening-epic.md](/Users/daniel/Development/context-alt-text-monorepo/docs/epics/v0.3.0/agentic-development-process-hardening-epic.md), especially around startup discipline, planning, review, hooks, and orchestration.

## Executive Summary

`superpowers` would help this repo most as a **workflow and skill-pattern reference**, not as a drop-in replacement for the repo's MCP handoff and orchestration stack.

It is strongest in four areas:

- startup discipline through skill-first bootstrapping and session-start hooks
- explicit plan/spec workflow conventions
- reusable execution skills for debugging, verification, code review, and worktree use
- lightweight subagent orchestration patterns expressed as prompts and skills

It is weakest exactly where this repo's epic is most differentiated:

- durable task memory and selective retrieval
- structured handoff state with findings, blockers, decisions, and artifact search
- contract ownership and blocking contract gates
- runtime-parity evidence and review readiness as durable state
- process metrics and close checks

The right move is to **borrow patterns and selectively vendor a few skill/hook ideas**, while keeping `agent-handoff-mcp` as the canonical review ledger and orchestration substrate.

## Surfaces Reviewed

Upstream repository:

- [README](https://github.com/obra/superpowers/blob/main/README.md)
- [Cursor plugin manifest](https://github.com/obra/superpowers/blob/main/.cursor-plugin/plugin.json)
- [docs](https://github.com/obra/superpowers/tree/main/docs)
- [docs/superpowers/specs](https://github.com/obra/superpowers/tree/main/docs/superpowers/specs)
- [skills](https://github.com/obra/superpowers/tree/main/skills)
- [code-reviewer agent](https://github.com/obra/superpowers/blob/main/agents/code-reviewer.md)
- [hooks](https://github.com/obra/superpowers/tree/main/hooks)

Locally inspected files from the upstream checkout:

- `/tmp/superpowers/README.md`
- `/tmp/superpowers/.cursor-plugin/plugin.json`
- `/tmp/superpowers/docs/README.codex.md`
- `/tmp/superpowers/.codex/INSTALL.md`
- `/tmp/superpowers/docs/superpowers/specs/2026-03-23-codex-app-compatibility-design.md`
- `/tmp/superpowers/docs/superpowers/plans/2026-03-23-codex-app-compatibility.md`
- `/tmp/superpowers/agents/code-reviewer.md`
- `/tmp/superpowers/hooks/hooks.json`
- `/tmp/superpowers/hooks/hooks-cursor.json`
- `/tmp/superpowers/hooks/session-start`
- `/tmp/superpowers/docs/windows/polyglot-hooks.md`
- selected skills under `/tmp/superpowers/skills/`

Local comparison points:

- [agentic-development-process-hardening-epic.md](/Users/daniel/Development/context-alt-text-monorepo/docs/epics/v0.3.0/agentic-development-process-hardening-epic.md)
- [agent-handoff-mcp README](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/README.md)
- [agent-handoff-mcp contract](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/agent-handoff-mcp.md)

## Findings

### 1. `superpowers` addresses workflow discipline, not durable coordination state

The upstream system is built around skills, commands, hooks, plans, and agents. Its README describes a workflow of brainstorming, worktree setup, plan writing, subagent execution, TDD, code review, and branch finishing. That is highly relevant to this repo's process-hardening goals.

However, it does **not** provide an equivalent to this repo's durable MCP ledger:

- no task-state database
- no first-class decisions, blockers, tests, findings, and close checks
- no artifact indexing/search layer
- no lane-scoped runtime state comparable to `agent-handoff-mcp`

Implication:

- `superpowers` can help enforce better behavior at the prompt/skill layer
- it does not remove the need for `agent-handoff-mcp`
- it cannot substitute for the epic's selective-memory, evidence-gate, or closeout objectives

### 2. `agent-handoff-mcp` does not substantially duplicate `superpowers`; the two systems sit at different layers

There is some conceptual overlap, but very little feature duplication.

What overlaps conceptually:

- worktree-aware execution patterns
- task/plan execution workflows
- code review as a named workflow
- multi-agent or subagent orchestration concepts

What `superpowers` primarily offers:

- skills as behavioral wrappers
- plan/spec conventions
- startup hooks
- review prompts and process discipline

What `agent-handoff-mcp` primarily offers:

- persistent coordination state
- review finding lifecycle
- blocker/test/decision records
- artifact indexing and search
- orchestrator and worker lifecycle tools
- dashboards and close checks

Conclusion:

- `agent-handoff-mcp` and `superpowers` are more complementary than redundant
- the epic should continue to treat `agent-handoff-mcp` as canonical state
- `superpowers` is best seen as a candidate source of **workflow UX and skill policy**, not replacement tooling

### 3. The strongest portable idea from `superpowers` is its skill-first workflow packaging

The most useful part of `superpowers` is that it packages process into composable, named skills:

- `using-superpowers`
- `writing-plans`
- `executing-plans`
- `requesting-code-review`
- `receiving-code-review`
- `verification-before-completion`
- `using-git-worktrees`
- `subagent-driven-development`

That directly addresses parts of the epic around:

- startup protocol
- review discipline
- execution convergence
- consistent worktree usage
- verification-before-success claims

What this repo can learn:

- make process entrypoints more explicit and discoverable
- make skills state their trigger, owned outputs, stop conditions, and escalation rules more sharply
- encode "verification before completion" as an explicit workflow, not just a cultural expectation

What should not be copied verbatim:

- the extreme `using-superpowers` enforcement tone
- plans that require exhaustive inline code and 2-5 minute microsteps for every task
- workflow assumptions that ignore this repo's MCP handoff state and branch-gate model

### 4. `superpowers` hooks are useful as a pattern, but should be implemented selectively in the harness

The upstream hook system is primarily a **session-start bootstrap**. It injects the full `using-superpowers` skill into session context and shows warnings about legacy installations. It also carries platform-specific wrapper work to make hooks run in Cursor and Claude Code.

This is useful in principle because the epic explicitly wants:

- cold-start discipline
- smaller set of authoritative startup surfaces
- reduced reliance on agents remembering the process

But the exact upstream implementation should **not** be vendored as-is here.

Why not:

- it injects a large amount of policy text into the session by default
- that conflicts with this repo's new selective-memory direction
- it is toolchain-specific and partly compensates for limitations in those host platforms
- it does not know about this repo's MCP state, active-task brief, or contract surfaces

Recommendation:

- yes, implement **hooks in the harness** if the host platform supports them reliably
- no, do not use them as full-skill text dumpers

Best-fit hook behavior for this repo:

- `SessionStart`: inject a minimal startup brief, not a long policy wall
  - active task ref
  - open blockers/findings count
  - required context-loading order
  - reminder to use repo-local rules/contracts first
- optional pre-action hook:
  - remind on boundary-touching work if no contract owner or contract path has been identified
- optional completion hook:
  - remind if a code/docs change lacks a recorded handoff decision

In other words: use hooks as **lightweight harness guards**, not as the primary policy store.

### 5. `superpowers` would help Phase 1 and Phase 4 of the epic more than the other phases

Most directly helped sections of the epic:

- **Phase 1: Context Loading and Handoff Discipline**
  - startup protocol ideas
  - skill-trigger clarity
  - branch/worktree setup discipline
- **Phase 4: MCP and Tooling Automation**
  - prompt-wrapped workflows
  - review and verification helpers
  - harness hook ideas
  - clearer execution/recovery/convergence rules

Partially helped:

- **Git Workflow Assessment**
  - worktree use
  - finishing flow
  - branch isolation discipline
- **Phase 3: Runtime Parity and Test Fidelity Gates**
  - indirectly, via `verification-before-completion` and TDD-oriented workflow

Weakly or not meaningfully helped:

- **Phase 2: Contract Ownership and Documentation Sync**
  - `superpowers` has specs and plans, but not a mature contract-ownership/gating system
- **Phase 5: Evaluation and Release Audit Layer**
  - little direct support for metrics, findings summaries, or quality-gate reporting over time
- **Selective memory / handoff tiering**
  - `superpowers` does not provide an equivalent memory model; this remains local work

### 6. The spec/plan split in `superpowers` is worth borrowing, but not its exact plan format

The upstream repo has a useful split between:

- `docs/superpowers/specs/...`
- `docs/superpowers/plans/...`

That maps well to this repo's desire to separate:

- validated intended design
- executable implementation slices

What is worth learning:

- keep design/spec artifacts separate from execution plans
- ensure plans reference approved design/spec documents explicitly
- make plans concrete enough to execute without conversational memory

What does not fit well here:

- extremely fine-grained tasks with embedded code blocks for every step
- scaffold-heavy or micro-commit assumptions
- a plan format that substitutes for contract ownership, handoff state, and repo-specific review gates

Recommendation:

- borrow the **spec/plan separation**
- do not vendor the **plan verbosity model**

### 7. The code-review and verification skills are strong candidates for local adaptation

Two upstream patterns are especially valuable:

- `verification-before-completion`
- `receiving-code-review`

Why they matter here:

- they reinforce the repo's "evidence before claims" rule
- they reduce a recurring failure mode where success is claimed before verification
- they force technical evaluation of review feedback instead of reflexive agreement

But they still need local adaptation:

- this repo wants findings-first review output with file/line references
- this repo wants handoff decisions and finding lifecycle tied into the workflow
- this repo needs contract/rule/runtime-parity checks beyond generic code quality

Recommendation:

- adapt these as local skills or review-guide sections
- do not vendor the prose wholesale

### 8. The worktree skill contains a useful environment-detection pattern for managed workspaces

The `superpowers` Codex App compatibility design documents a practical pattern:

- detect linked worktrees and detached HEAD with read-only git commands
- avoid trying to create nested worktrees when the host already manages the workspace
- switch branch-finishing behavior when the environment is externally managed

That is useful locally because this repo already cares about:

- worktree-driven development
- orchestrator/worker lane isolation
- host-specific runtime constraints

Recommendation:

- borrow the detection pattern for harness-aware worktree workflows
- adapt it into local worktree/orchestrator skills if host-managed workspaces become common

### 9. `superpowers` does not solve the epic's hardest local problems: selective memory, contract gates, and durable metrics

The epic's most demanding work remains local:

- shaping handoff into hot/warm/cold memory tiers
- targeted retrieval of task state instead of replaying history
- explicit contract-change gates with fixture/schema evidence
- process metrics around drift, ctx7 usage, and review readiness

`superpowers` offers good discipline, but it is still largely **instructional** and **prompt-mediated**. The epic is asking for **durable state**, **blocking evidence gates**, and **automation surfaces**.

That means:

- `superpowers` can reduce some workflow design effort
- it cannot save the core MCP and handoff implementation work

## What Makes Sense to Use Out of the Box

Low-risk candidates to adapt or vendor locally:

- the idea of a `verification-before-completion` skill
- the idea of a `receiving-code-review` skill or reviewer-response guide
- the worktree environment-detection pattern for managed workspaces
- spec/plan separation as a planning convention
- lightweight harness hooks for startup reminders

Higher-risk candidates that should be adapted, not vendored directly:

- `using-superpowers`
- `writing-plans`
- `subagent-driven-development`
- `requesting-code-review`
- the code-reviewer agent prompt

Why only adapt:

- they assume a different workflow engine
- they do not know about MCP handoff, contract gates, or selective-memory goals
- some are intentionally forceful and would conflict with this repo's more explicit local rules

## What Does Not Make Sense to Vendor

- the full plugin/hook packaging
- session-start full-skill context injection
- the entire upstream skill library as a second policy system
- any workflow that would compete with `agent-handoff-mcp` as the system of record

## Epic Coverage Matrix

| Epic Area | Help from `superpowers` | Notes |
| --- | --- | --- |
| Startup discipline / cold start | High | Strong skill-first and hook-first patterns |
| Planning workflow | Medium | Good spec/plan split, but task granularity is too prescriptive |
| Worktree workflow | Medium | Good managed-worktree detection and finishing behavior |
| Review discipline | Medium | Good review/verification patterns, but not findings-first or MCP-aware |
| MCP/tooling automation | Medium | Useful wrapper/hook ideas, but no durable MCP state equivalent |
| Contract ownership and gating | Low | Specs and plans exist, but not contract-owner enforcement |
| Selective memory / handoff tiering | Low | No equivalent to the epic's handoff memory model |
| Runtime-parity evidence | Low-Medium | Verification culture helps, but no runtime-parity framework |
| Metrics / quality gates / close checks | Low | Largely absent compared to local MCP ambitions |

## Recommended Local Next Steps

1. Add a small follow-up task under the epic for `skill and hook harvesting from superpowers`.
2. Prototype one harness `SessionStart` hook that injects only:
   - active task ref
   - open findings/blockers summary
   - required context-loading order
3. Draft local skills for:
   - verification before completion
   - receiving code review
4. Add a local note to the epic or templates that spec and plan documents should remain separate artifacts.
5. Keep `agent-handoff-mcp` as canonical state; do not attempt to replace it with upstream skills or hooks.

## Bottom Line

`superpowers` is a strong source of **workflow ergonomics** and **skill packaging**. It is not a replacement for this repo's MCP handoff architecture.

The best local use is:

- borrow selected skill ideas
- adopt lightweight hook patterns
- adapt worktree-environment detection
- keep all durable review state, contract gating, selective memory, and metrics inside the local MCP/handoff system

That would save meaningful design time in the epic's startup and automation phases without derailing the repo's more ambitious local process-hardening work.

