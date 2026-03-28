# ADPH-4. Playbook, Skill, and Hook Architecture Hardening

> **Metadata**
> - **Date**: 2026-03-28 16:05 EDT
> - **Author**: codex

## Objective

Restructure the agentic process docs so agent-agnostic operational truth lives in playbooks and rules, agent-specific wrappers live in skills, and MCP/tooling hooks are defined as explicit portable process events rather than host-product magic. When complete, the repo should have a clearer separation between canonical process guidance, agent adapters, and automation hooks that support the dev process.

## Problem Statement

`docs/agentic/playbooks/` and `docs/agentic/skills/` currently overlap in purpose. Some playbooks are truly agent-agnostic operating procedures, while others are explicitly Codex-specific. The skills already act as Codex-oriented execution wrappers, but they duplicate parts of the same orchestration workflows documented in playbooks. That makes it unclear where canonical truth belongs and creates drift risk when one layer changes first.

At the same time, the repo already has several hook-like behaviors in the tooling layer; ACE reflection detection after reviews, close-check enforcement, worker observability logging, and review dispatch. But these behaviors are not yet framed as a coherent, agent-agnostic hook architecture. If hooks remain implicit and host-specific, they become process magic rather than inspectable tooling contracts. If the repo wants to stay agent-agnostic, it needs portable hook semantics at the MCP/tooling layer and thin host-specific adapters above them.

## Constraints

- Canonical operational guidance must remain agent-agnostic and human-readable.
- Skills may remain agent-specific, but they must point back to canonical process docs instead of becoming the only source of truth.
- Hook semantics must be defined in MCP/tooling terms, not in terms of one host product’s lifecycle model.
- Additive first: restructure and clarify ownership before deleting or merging major doc surfaces.
- Existing repo workflows (`worktree-orchestrator`, `worktree-worker`, daemon lifecycle, lane commands, MCP handoff) must keep working during the transition.

## Workflow Principles

- Playbooks own durable operating procedure; skills own agent-specific execution wrappers.
- Rules own mandatory invariants and gates; playbooks own how to operate inside those constraints.
- Hooks should be explicit, typed, and observable; no hidden state mutation without a durable MCP/log trail.
- Tooling architecture must describe portable semantics first, then per-agent adapters second.

## Terminology

- **Playbook**: An agent-agnostic operating procedure that both humans and agents can follow.
- **Skill**: An agent-specific wrapper that decides when to load a playbook and how to execute it in one host/runtime.
- **Hook semantic**: A named automation event such as `after_review_findings_recorded` or `before_close_check` that has stable expected behavior regardless of host.
- **Hook adapter**: A host-specific integration that triggers a hook semantic, such as a Codex-side tool wrapper or daemon callback.
- **Canonical process layer**: The combined rules/playbooks/contracts surfaces that define what must happen independent of a specific agent product.

## Current State Analysis

- Current playbooks:
  - [ace-pruning-playbook.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/playbooks/ace-pruning-playbook.md) is agent-agnostic and should stay a playbook.
  - [lane-scoped-context.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/playbooks/lane-scoped-context.md) is mostly agent-agnostic orchestration guidance.
  - [worktree-codex-playbook.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/playbooks/worktree-codex-playbook.md) mixes generic orchestration process with Codex-specific launch and workflow details.
  - [codex-custom-mcp-playbook.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/playbooks/codex-custom-mcp-playbook.md) is explicitly Codex-specific and not agent-agnostic.
- Current skills:
  - [worktree-orchestrator/SKILL.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/skills/worktree-orchestrator/SKILL.md) and [worktree-worker/SKILL.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/skills/worktree-worker/SKILL.md) already function as execution wrappers that point back to canonical docs.
  - [daemon-lifecycle/SKILL.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/skills/daemon-lifecycle/SKILL.md) is clearly agent-facing and operational.
- Current hook-like tooling behaviors already exist:
  - ACE reflection detection after findings in `worker_daemon.py`
  - write-time slice-summary validation in `core.py`
  - close-check/review-ready gating in `core.py` and `review_ready.py`
  - worker/orchestrator observability events and dispatch flows
- The `agentfactory-book` guidance is directionally aligned with this repo on tool/resource/prompt separation and execution-time injection, but the repo has not yet formalized an agent-agnostic hook layer to match those ideas.

## Target Outcome

The repo should clearly distinguish:
- `rules/` for mandatory invariants
- `playbooks/` for canonical agent-agnostic procedures
- `skills/` for agent-specific wrappers/adapters

The hook model should also be explicit. `agent-handoff-mcp` and associated tooling should document and gradually implement a small set of portable hook semantics for review, handoff, close-check, telemetry, and guidance injection. Host-specific integrations may trigger those hooks, but the semantics and resulting state changes must live in the repo/tooling contract, not in one agent product’s behavior.

## Context Loading

- Rules: [instructions.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/instructions.md), [development-workflow.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/rules/development-workflow.md)
- Contracts: [agent-handoff-mcp.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/agent-handoff-mcp.md)
- Handoff/MCP state: inspect current playbook/skill/hook review findings and recent decisions under `agentic-development-process-hardening-epic`
- External docs via `ctx7` only if: MCP hook/resource/prompt design needs current upstream protocol guidance beyond local literature notes

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Agentic docs IA | agentic-process docs | [instructions.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/instructions.md) and `docs/agentic/README.md` | Clarify ownership boundaries between rules, playbooks, and skills | Yes; additive and routing-safe | docs review |
| Skill/playbook relationship | agent-specific wrappers | current `SKILL.md` files + playbooks | Convert skills into thin wrappers that explicitly cite canonical playbooks/rules, not duplicate them | Yes; current skills remain usable during migration | docs review |
| Hook semantics | MCP/tooling | [agent-handoff-mcp.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/agent-handoff-mcp.md) | Define agent-agnostic hook semantics and expected durable outputs | Yes; start with documented semantics and additive tool support | pytest + contract doc |
| Host-specific adapters | Codex-oriented docs | playbooks + skills + Make/MCP wrappers | Split portable semantics from Codex-specific attachment and execution guidance | Yes; Codex flows remain documented, but as adapters not canonical truth | docs review |

## Proposed Solution

Implement this in four slices. First, classify the existing playbooks and skills by ownership and portability, then restructure the docs so canonical process remains agent-agnostic. Second, split mixed playbooks into portable core procedure plus host-specific adapter guidance. Third, define a portable hook-semantic model in the MCP/tooling contract and map existing behaviors onto it. Fourth, add the minimum supporting docs/tooling updates so agents and operators can understand which hooks exist, what they do, and where host-specific integrations plug in.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| docs | `docs/agentic/README.md` | Clarify the roles of rules, playbooks, skills, and host-specific adapters |
| docs | `docs/agentic/playbooks/README.md` | Classify playbooks as canonical agent-agnostic procedures and move host-specific items out or relabel them |
| docs | `docs/agentic/playbooks/worktree-codex-playbook.md` | Split into portable orchestration procedure plus Codex-specific adapter guidance |
| docs | `docs/agentic/playbooks/codex-custom-mcp-playbook.md` | Reclassify as host-specific adapter/setup doc rather than canonical playbook |
| docs | `docs/agentic/playbooks/lane-scoped-context.md` | Keep as portable context-playbook and align wording accordingly |
| docs | `docs/agentic/skills/worktree-orchestrator/SKILL.md` | Thin further toward wrapper/trigger/owned-output guidance |
| docs | `docs/agentic/skills/worktree-worker/SKILL.md` | Same wrapper-thinning and canonical references |
| docs | `docs/agentic/contracts/agent-handoff-mcp.md` | Add hook semantics section for portable process hooks and durable outputs |
| docs | `docs/agentic/instructions.md` | Update routing guidance so skills are wrappers and playbooks are canonical for shared procedure |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Only if needed: expose or rename explicit hook-adjacent MCP surfaces for discoverability |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py` | Document/map existing hook-like events to the new semantics; code changes only if needed for clarity |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_ready.py` | Same mapping if hook semantics require additive visibility |

## Related Files

| File | Note |
| --- | --- |
| `docs/agentic/playbooks/ace-pruning-playbook.md` | Strong example of agent-agnostic playbook content |
| `docs/agentic/skills/daemon-lifecycle/SKILL.md` | Good example of agent-specific execution wrapper |
| `mk/handoff.mk` | Existing shell wrappers around review/handoff/orchestration surfaces that may correspond to portable hook semantics |
| `scripts/worktree-lane` | Current orchestration helper with both portable workflow logic and repo-specific command integration |
| `docs/literature/process/agentfactory-book/` | Background source for tool/resource/prompt separation, execution-time injection, and playbook/skill ideas |

## Verification Strategy

- Deterministic checks:
  - `git diff --check -- docs/agentic docs/tasks/12.0/playbook-skill-boundary-and-hook-architecture-task-plan.md`
- Contract/consistency verification:
  - Verify every skill points to a canonical playbook/rule instead of owning duplicated process detail
  - Verify every portable hook semantic names a durable MCP/log outcome
- Manual verification:
  - Confirm a human operator can find the canonical orchestration procedure without reading a Codex-specific skill
  - Confirm a Codex-oriented agent can still find the correct execution wrapper through the skill layer

## Slice Delivery

### Slice 1: Classify and Reframe the Surfaces

**Goal**: Establish clear ownership boundaries between rules, playbooks, and skills.

Changes:

- Classify each existing playbook as one of:
  - canonical agent-agnostic playbook
  - mixed portable + host-specific doc
  - host-specific adapter/setup doc
- Update `docs/agentic/README.md` and `playbooks/README.md` so the directory roles are explicit.
- State the rule that skills are wrappers/adapters and must not become canonical process truth.

Proof:

- Repo docs clearly describe where canonical process lives and where agent-specific wrappers live
- No ambiguity remains about whether `codex-custom-mcp-playbook.md` is agent-agnostic

### Slice 2: Split Portable Procedure from Host-Specific Guidance

**Goal**: Keep playbooks portable and move agent-specific details into adapter docs or skills.

Changes:

- Split `worktree-codex-playbook.md` into:
  - a portable worktree-orchestration playbook
  - a Codex-specific adapter/execution companion
- Reclassify `codex-custom-mcp-playbook.md` as a host-specific setup doc, not a canonical shared playbook.
- Thin `worktree-orchestrator` and `worktree-worker` skills so they mostly cover trigger, ownership, and execution wrapper details while pointing back to the canonical playbook.

Proof:

- Canonical orchestration procedure can be read without Codex-specific assumptions
- Skills remain usable but visibly depend on canonical process docs

### Slice 3: Define Portable Hook Semantics

**Goal**: Describe hooks as agent-agnostic process events with durable outputs.

Changes:

- Add a hook-semantics section to the MCP contract covering events such as:
  - `after_review_findings_recorded`
  - `before_close_check`
  - `after_worker_turn`
  - `after_task_switch`
  - `before_review_prompt_build`
- For each hook semantic, define:
  - trigger condition
  - allowed side effects
  - required durable output (MCP row, JSONL event, typed error, or generated summary)
  - what must remain explicit to the operator/agent
- Map existing behaviors (ACE reflection detection, slice-summary enforcement, review-ready gating, observability logging) onto that model.

Proof:

- The contract can describe current hook-like behavior without referring to a single host product
- Each semantic has an inspectable durable output

### Slice 4: Align Tooling and Guidance

**Goal**: Make the hook model and doc ownership visible in everyday workflow guidance.

Changes:

- Update `instructions.md` routing language so agents know:
  - rules = invariants
  - playbooks = shared procedure
  - skills = host-specific wrappers
- Update any relevant MCP/tooling docs to point to explicit hook semantics instead of vague automation language.
- If needed, add small discoverability improvements in `agent-handoff-mcp` so hook-adjacent surfaces are easier to understand.

Proof:

- Agents and humans can follow the same canonical playbook while using different agent-specific wrappers
- Hook behavior is described as inspectable tooling semantics, not hidden magic

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and current playbooks/skills before editing.
- [ ] Confirmed which existing playbooks are portable vs host-specific.
- [ ] Recorded compatibility expectations for current skill-driven workflows.

## Slice 1: Classify and Reframe the Surfaces

- [ ] Classified existing playbooks and skills by ownership/portability.
- [ ] Updated top-level docs IA guidance.
- [ ] Declared skills as wrappers, not canonical truth.

## Slice 2: Split Portable Procedure from Host-Specific Guidance

- [ ] Separated portable orchestration procedure from Codex-specific guidance.
- [ ] Reclassified host-specific setup docs appropriately.
- [ ] Thinned skills toward wrapper/trigger/owned-output roles.

## Slice 3: Define Portable Hook Semantics

- [ ] Added a contract section for portable process hooks.
- [ ] Mapped existing hook-like tooling behaviors into that model.
- [ ] Defined durable outputs and operator visibility for each hook.

## Slice 4: Align Tooling and Guidance

- [ ] Updated instructions/routing to reflect the new ownership model.
- [ ] Updated doc/tooling references to explicit hook semantics.
- [ ] Verified the resulting guidance works for both humans and agents.

## Stretch Goals

- [ ] Add an explicit hook-discovery MCP surface or doctor output describing which portable hook semantics are currently active.
- [ ] Add a host-adapter directory structure that separates Codex-specific docs from future non-Codex adapters more clearly.

## Success Criteria

- [ ] Canonical operational procedure is clearly agent-agnostic and lives in playbooks/rules rather than in skills.
- [ ] Skills are thin agent-specific wrappers that point back to canonical process docs.
- [ ] MCP/tooling hooks are described as portable semantics with durable outputs, enabling agent-agnostic automation reasoning.
