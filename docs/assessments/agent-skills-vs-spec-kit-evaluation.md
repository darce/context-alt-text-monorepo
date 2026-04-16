# Agent-Skills vs Spec-Kit Evaluation for Agentic Process Improvement

## Objective

Evaluate whether [`addyosmani/agent-skills`](https://github.com/addyosmani/agent-skills) or [`github/spec-kit`](https://github.com/github/spec-kit) should be vendored into this project to reduce friction in the planning, review, and multi-model collaboration workflow — considering the pain points documented against the current `agent-handoff-mcp` + `agent-orchestrator-mcp` system.

## Executive Summary

**Neither package should be vendored wholesale.** Both address real gaps in this repo's process, but each one's strengths map to different layers of the problem, and both have critical blind spots where this repo is already ahead.

The strongest path is a **hybrid extraction**: take spec-kit's specification validation engine and extend it with agent-skills' execution-skill patterns, layered on top of the existing MCP handoff substrate. The handoff DB and orchestration layer are the project's structural advantage — they provide the durable state, multi-model handoff, and pre-merge gate that neither external project offers. The extracted patterns should plug into this substrate rather than replacing it.

| Dimension | agent-skills | spec-kit | This repo today |
|-----------|-------------|----------|-----------------|
| **Durable task state** | None (stateless docs) | `.specify/` files, no DB | `handoff.db` with decisions, findings, tests, blockers |
| **Multi-model handoff** | None (Claude-only assumed) | Agent registry (30+ agents), but command-based, not state-based | MCP-backed, model-agnostic, cross-session |
| **Spec validation** | Manual (spec skill is advisory) | **Automated 6-step analysis** with severity triage | Manual (planning review guide is checklist-based) |
| **Execution skills** | **22 gated skills** with convergence criteria | 6 lifecycle commands | ~12 skills (`.claude/skills/`), variable formality |
| **Review gates** | Code review skill (3 severity levels) | Read-only analysis command | `handoff_close_check(enforce=True)` with MCP-stored findings |
| **Contract enforcement** | None | Constitution alignment checks | Manual (contract change protocol is checklist-based) |
| **Lane/worker orchestration** | Prompt-based subagent patterns | None | `agent-orchestrator-mcp` with worktree lanes |

## Candidate Analysis

### F1: agent-skills (Addy Osmani)

**What it is.** A documentation-driven framework encoding a seven-stage development lifecycle (DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP) as 22 skill files, 3 specialist agent personas, and slash commands for Claude Code. Skills are defined as reusable operating patterns with explicit triggers, constraints, recovery rules, and convergence criteria.

**Strengths relevant to this repo:**

- **Gated execution skills with convergence criteria.** Each skill defines when it activates, what actions it performs, validation steps, and when it's honestly done. This is more formal than most of this repo's `.claude/skills/` definitions, which vary between terse checklists and full procedural playbooks.
- **Distinction between advisory and execution skills.** The framework explicitly separates "recommend" from "manage loops with safety boundaries" — a distinction this repo currently conflates (e.g., the review guides are advisory but the pre-merge gate is execution-level).
- **Context engineering discipline.** Targets ~2,000 lines of focused context per invocation. The repo's pain point of agents repeatedly reloading full handoff state maps directly to this: agent-skills would impose a context budget by design.
- **MCP wrapping pattern.** The companion curriculum teaches adding policy layers (filtering, recovery, validation) on top of raw MCP tools — relevant for the gap between raw `agent-handoff-mcp` tools and the higher-level workflows this repo encodes in prose.

**Weaknesses / gaps:**

- **No durable state.** Skills are stateless — they rely on the conversation window for continuity. In this repo, where tasks span multiple sessions and models, the conversation is not the source of truth. The handoff DB is.
- **Single-model assumption.** Composition assumes Claude reads skill descriptions and chains them. There is no protocol for Codex-started work being resumed by Claude, or for two models contributing to the same review. The repo's agent-agnostic handoff is already ahead here.
- **No structured findings or close checks.** The code-review skill produces findings as conversation output, not as durable records. Findings cannot be deferred, re-opened, or gated against. The repo's `review_findings` + `handoff_close_check` system is fundamentally more rigorous.
- **No contract ownership or boundary enforcement.** Skills do not model service boundaries, shared schemas, or the Cross-Boundary Change Protocol this repo enforces.

**Verdict:** Reference-quality execution patterns. Not a replacement for any existing subsystem. Useful as a **pattern source** for formalizing the repo's skill definitions with convergence criteria and context budgets.

### F2: spec-kit (GitHub)

**What it is.** A Python CLI toolkit (Python 3.11+, Typer/Click/Rich) implementing Spec-Driven Development through a six-step workflow: constitution → specification → planning → task breakdown → analysis → implementation. It includes an automated analysis engine that detects duplication, ambiguity, underspecification, and constitution-alignment violations across spec/plan/task artifacts.

**Strengths relevant to this repo:**

- **Automated spec validation.** The `/speckit.analyze` command runs six detection passes (duplication, ambiguity, underspecification, constitution alignment, coverage gaps, terminology drift) with severity triage. This directly addresses the repo's pain point of manual planning reviews that start from scratch each time. Currently, the planning-review-guide.md checklist is human-driven; spec-kit would automate the "current-state accuracy" and "internal consistency" checks.
- **Multi-agent registry.** The `IntegrationRegistry` and `CommandRegistrar` convert abstract commands across 30+ agent formats. This is relevant to the repo's multi-model collaboration goal — Claude, Codex, Cursor, and future agents could share a command vocabulary without model-specific skill files.
- **Extension system with lifecycle hooks.** The `before/after` hook pattern (e.g., `after_tasks`, `after_spec`) enables automation during workflow transitions. This maps to the repo's need for automated gating between planning stages — currently encoded as prose exit gates in `planning-pipeline.md` but not enforced by tools.
- **Layered configuration.** The defaults → project → local → environment resolution stack is cleaner than the repo's current mix of `CLAUDE.md`, `instructions.md`, MCP server instructions, and in-file rules.
- **Constitution-driven development.** The constitution concept — governing principles that all specs and plans must align with — maps to this repo's `instructions.md` + `CLAUDE.md` rules (`[sr-NNN]`, `[rg-NNN]`). Spec-kit could formalize these as machine-checkable constraints rather than prose rules.

**Weaknesses / gaps:**

- **No MCP integration.** Spec-kit uses direct command registration, not MCP tools. It cannot read or write to `handoff.db`, cannot participate in the pre-merge gate, and cannot record findings in the format the repo's review system expects. Integration would require an adapter layer.
- **No durable handoff state.** State is file-based (`.specify/init-options.json`, `integration.json`). There is no equivalent of the handoff DB's decision/finding/blocker/test-result records, no search across sessions, and no close-check gate.
- **No orchestration.** No concept of lanes, worktrees, or worker dispatch. The repo's `agent-orchestrator-mcp` is not addressable from spec-kit.
- **No review-as-findings workflow.** Analysis produces a Markdown report, not MCP-stored findings. Findings cannot be individually deferred, linked to commits, or gated against at merge time.
- **Python runtime dependency.** Adding spec-kit as a dependency introduces Typer, Click, Rich, PyYAML, and platformdirs into the project's Python environment. The repo's MCP packages already have their own dependency surfaces; adding another CLI toolkit increases the maintenance burden.

**Verdict:** The spec validation engine is genuinely useful and addresses a real gap. The multi-agent registry is interesting but orthogonal to the repo's MCP-based approach. The runtime dependency cost is non-trivial.

## Pain-Point Mapping

These are the chronic friction points from handoff history and process documentation, mapped to what each candidate offers:

### P1: Context Bloat and Inefficient State Retrieval

Agents repeatedly reload full handoff state when they need targeted data.

- **agent-skills:** Context budget discipline (~2,000 lines target) would help. The "five-tier context hierarchy" pattern is directly adoptable. **Borrowable pattern.**
- **spec-kit:** No help. Spec-kit doesn't manage runtime context.
- **Recommended action:** Adopt agent-skills' context budget as a skill-level constraint in `.claude/skills/`. The bounded-read levers in `agent-handoff-mcp` already exist (`sections=`, `detail=`, `top_n_*`); what's missing is a skill-level rule that forces agents to use them.

### P2: Fragmented Review Surfaces and No Review Packet

Reviewers start from scratch each time — no standardized intake packet.

- **agent-skills:** The code-review skill has structured intake (project requirements, conventions, areas of concern) but produces conversation output, not durable records. **Partial pattern.**
- **spec-kit:** The analyze command produces structured reports from artifacts. Could be adapted to produce review-intake packets. **Adaptable engine.**
- **Recommended action:** Build a review-packet generator as an orchestrator tool that combines spec-kit-style artifact analysis with MCP-stored findings and test evidence. The `get_latest_slice_review_packet` tool in `agent-orchestrator-mcp` is a prototype of this — extend it.

### P3: Manual Planning Review with No Automated Checks

The planning-review-guide.md checklist is entirely human-driven.

- **agent-skills:** The spec skill is advisory — it recommends structured specs but doesn't validate them. **No automation.**
- **spec-kit:** **Direct hit.** The analysis engine runs automated detection passes for exactly the categories in the planning review checklist: current-state accuracy (coverage gaps), internal consistency (duplication, ambiguity), and contract alignment (constitution checks). **Primary extraction target.**
- **Recommended action:** Extract spec-kit's analysis engine and wire it as a `make plan-analyze` target that runs against `docs/tasks/`, `docs/specs/`, and `docs/epics/` artifacts, outputting findings in MCP-compatible format.

### P4: Stale Verification Evidence

Test results are recorded with commit SHA but nothing compares freshness automatically.

- **agent-skills:** No help (stateless).
- **spec-kit:** No help (no test-result tracking).
- **Recommended action:** This is an `agent-handoff-mcp` enhancement, not a vendor solution. Add a `get_verification_freshness(task_ref, current_sha)` tool.

### P5: Contract Ownership Ambiguity at Boundaries

No blocking enforcement for boundary-touching diffs that lack matching contract proof.

- **agent-skills:** No contract model.
- **spec-kit:** The constitution concept could model contract surfaces as checkable constraints. **Adaptable pattern.**
- **Recommended action:** Define a `.specify/constitution.md` (or equivalent) that enumerates boundary contracts and wire spec-kit-style alignment checks into the pre-merge gate.

### P6: Skill Formality Varies Widely

`.claude/skills/` definitions range from terse checklists to multi-page playbooks.

- **agent-skills:** **Direct hit.** Every skill follows a consistent anatomy: metadata, overview, usage criteria, gated workflow, methodology, validation checkpoints, convergence criteria, maintenance guidance. **Primary extraction target.**
- **spec-kit:** Not relevant (commands, not skills).
- **Recommended action:** Adopt agent-skills' skill anatomy as the template for all `.claude/skills/` definitions. Add convergence criteria and context-budget fields to the existing skill template.

## Recommendation: Hybrid Extraction

### What to take from spec-kit

1. **The analysis engine (core extraction).** Port the six detection passes (duplication, ambiguity, underspecification, constitution alignment, coverage gaps, terminology drift) as a Python module under `packages/` or `scripts/`. Wire it as `make plan-analyze` against planning artifacts. Output findings in a format that `review_findings(operation="batch_record")` can ingest directly.

2. **The constitution concept.** Create a `docs/agentic/constitution.md` that formalizes this repo's `[sr-NNN]` and `[rg-NNN]` rules as machine-checkable constraints. This replaces prose rules with something the analysis engine can validate against.

3. **The extension/hook lifecycle pattern.** Adopt the `before/after` hook pattern for planning-stage transitions. Currently the exit gates in `planning-pipeline.md` are prose checklists; they should be hookable events that run automated checks.

### What to take from agent-skills

4. **Skill anatomy template.** Adopt the consistent skill structure (metadata, triggers, constraints, gated workflow, convergence criteria, context budget) as the standard for `.claude/skills/`. Retrofit existing skills over time.

5. **Context budget discipline.** Add a `context_budget_lines` field to the skill template. Skills that load too much context should be flagged by a linter, not discovered when agents hit window limits.

6. **Advisory-vs-execution skill distinction.** Tag each skill as `mode: advisory` or `mode: execution`. Advisory skills recommend; execution skills manage loops with convergence gates. This clarifies the current ambiguity where review guides (advisory) sit alongside the pre-merge gate (execution).

### What NOT to take

- **Agent-skills' stateless model.** The handoff DB is this repo's structural advantage. Do not adopt any pattern that treats conversation context as the source of truth for task state.
- **Spec-kit's command registration system.** The MCP tool surface is already the command vocabulary. Adding a parallel `CommandRegistrar` would create two competing discovery mechanisms.
- **Spec-kit's CLI as a runtime dependency.** Extract the analysis logic; do not vendor the Typer/Click/Rich CLI wrapper. The repo's Makefile targets are the user-facing interface.
- **Agent-skills' Claude-specific slash commands.** The repo already has `.claude/commands/` definitions that are MCP-backed. Do not replace them with agent-skills' prompts-as-commands pattern.

### What to preserve unconditionally

- **`agent-handoff-mcp` as the canonical state store.** Decisions, findings, blockers, test results, and close checks stay in the handoff DB. Neither candidate offers anything comparable.
- **`agent-orchestrator-mcp` for lane/worker orchestration.** Neither candidate has a multi-agent dispatch model.
- **The pre-merge gate (`handoff_close_check`).** Neither candidate offers blocking enforcement of review completeness.
- **Agent-agnostic MCP handoff for multi-model collaboration.** The user's stated priority — Claude and Codex collaborating seamlessly — is served by the current MCP-backed, model-agnostic handoff protocol. Neither candidate improves this; both would degrade it if adopted wholesale.

## Implementation Sketch

If this evaluation leads to a spec, the work would decompose roughly as:

| Phase | Work | Source |
|-------|------|--------|
| 1 | Formalize constitution from `[sr/rg-NNN]` rules | spec-kit pattern |
| 2 | Port spec analysis engine as `scripts/plan-analyze.py` | spec-kit extraction |
| 3 | Wire analysis output to `review_findings(batch_record)` | Integration adapter |
| 4 | Add `make plan-analyze` target and hook into planning exit gates | spec-kit hook pattern |
| 5 | Define skill anatomy template with convergence criteria + context budget | agent-skills pattern |
| 6 | Retrofit highest-friction skills (`review`, `commit2git`, `investigate`) | Incremental |
| 7 | Add `mode: advisory|execution` tag to all skills | agent-skills pattern |
| 8 | Add verification-freshness tool to `agent-handoff-mcp` | Internal enhancement |

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Spec-kit analysis engine is tightly coupled to its CLI | Extract detection logic as pure functions; leave CLI wrapper behind |
| Constitution concept adds another doc surface to maintain | Constitution replaces scattered `[sr/rg-NNN]` rules, not adds to them |
| Skill formalization creates bureaucratic overhead for simple skills | Apply only to skills with `mode: execution`; advisory skills stay lightweight |
| Agent-skills patterns assume Claude-only context | Adapt patterns for MCP-backed, model-agnostic invocation |

## Conclusion

The current system's strength is durable, model-agnostic state management — and that is exactly what makes Claude-Codex collaboration work. Neither candidate should replace that foundation. But both candidates expose real gaps: this repo validates plans manually (spec-kit automates it) and defines skills inconsistently (agent-skills standardizes them). The hybrid extraction gets both improvements without sacrificing the MCP substrate that makes multi-model handoff possible.
