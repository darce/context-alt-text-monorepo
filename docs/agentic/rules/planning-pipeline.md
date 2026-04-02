# Planning Pipeline

> **Purpose:** Defines the repeatable process for turning observed problems into
> reviewed specs, design decisions, and implementation task plans.
>
> Load this document when creating, reviewing, or sequencing planning artifacts.
> For review procedures, see [planning-review-guide.md](planning-review-guide.md).
> For implementation workflow (TDD, slices, commits), see [development-workflow.md](development-workflow.md).

---

## Pipeline Overview

```
Assessment ──→ Spec ──→ [ADR] ──→ Task Plan ──→ Implementation
  report        spec     ADR      task plan     code + tests
```

Each stage produces a distinct artifact type. Not every stage is required for
every piece of work — small, well-understood changes can skip the assessment
and go directly to a spec or task plan. The pipeline exists to prevent
premature implementation of complex or contract-breaking work.

**When to use the full pipeline:**
- Contract or output format changes
- Tool surface changes (add, remove, rename, consolidate)
- Cross-service or cross-package boundary changes
- Architectural decisions with multiple viable approaches
- Work that will take more than one task plan to complete

**When to skip stages:**
- Bug fixes with an obvious root cause → task plan or direct implementation
- Small additive features with no contract impact → task plan
- Documentation-only changes → direct implementation

---

## Stage 1: Assessment

**Artifact:** `*-report.md`, `*-investigation.md`, or `*-audit.md`
**Template:** [ASSESSMENT.template.md](../templates/ASSESSMENT.template.md)
**Location:** Package-local `docs/tech-debt/` or `docs/assessments/`, or monorepo `docs/assessments/`

### Purpose

Surface problems and verify them against code. An assessment inventories what
is wrong, traces findings to the codebase, and recommends directions — without
prescribing solutions.

### Required content

- **Findings** with stable IDs (F1, F2, ...) citing `file:line` in the current codebase
- **Code-verified critique** that challenges the initial findings
- **Priority ordering** (P0-P3) based on impact-to-effort
- **Suggested spec direction** — what should be in scope, deferred, or rejected

### Exit gate → Spec

| Criterion | Required? |
|-----------|-----------|
| Every finding cites current code | Yes |
| Critique section challenges findings honestly | Yes |
| Priority ordering reflects impact-to-effort | Yes |
| Owner has reviewed and resolved disagreements | Recommended |
| Deferred items are named explicitly | Yes |

An assessment that passes this gate can feed into a spec. Findings that fail
code verification must be corrected or removed before spec work begins.

---

## Stage 2: Spec

**Artifact:** `*-spec.md`
**Template:** [SPEC.template.md](../templates/SPEC.template.md)
**Location:** Package-local `docs/specs/`

### Purpose

Define concrete, testable changes derived from assessment findings. Each spec
item has a stable identifier, traceability to findings, before/after code
anchored by function name, and a done-when definition that is machine-verifiable.

### Required content

- **Spec items** with stable IDs (e.g. OC-001) tracing back to assessment findings
- **Before/After** anchored by `file_path::function_name` (line numbers optional, non-durable)
- **Done when** criteria that are testable, not subjective
- **Implementation tiers** grouping items by readiness and dependency
- **Validation snippets** verified against the current package
- **Spec-review gate** section (mandatory in every spec)

### Tier structure

| Tier | Readiness | Action |
|------|-----------|--------|
| **Tier 1** | High certainty, code-verified, independent | Create task plans immediately |
| **Tier 2** | Mechanical but depends on Tier 1 | Create task plans after Tier 1 lands |
| **Tier 3** | Blocked on a design decision | Create an ADR first (Stage 2.5) |

### Exit gate → Task Plan

| Criterion | Required? |
|-----------|-----------|
| At least one planning review pass with findings in MCP | Yes |
| All review findings resolved (fixed, deferred with rationale, or wontfix) | Yes |
| Validation snippets verified against current package | Yes |
| Tier 3 items explicitly marked as ADR-gated | Yes |

**No implementation tasks may be created from a spec until this gate is passed.**
This gate was established after the output-contract-v2 spec review caught invented
field names, broken validation commands, and under-specified consolidation models.

---

## Stage 2.5: ADR (conditional)

**Artifact:** `ADR-NNN-[kebab-case-topic].md`
**Template:** [ADR.template.md](../templates/ADR.template.md)
**Location:** `docs/agentic/adrs/`

### When required

Only when a spec item is explicitly design-uncertain — multiple viable approaches
exist and the choice has architectural consequences. The spec marks these items
as "Tier 3 — Blocked on ADR."

ADRs are **not** created:
- Before a spec exists (design uncertainty is flagged within the spec)
- For implementation choices that don't affect contracts or architecture
- As a substitute for assessment work

### Purpose

Resolve design uncertainty that a spec explicitly marks as blocked. The ADR
chooses one approach, rejects alternatives with rationale, and sets guardrails
for the follow-on implementation task.

### Required content

- **Context** referencing the blocked spec item and assessment findings
- **Constraints** from prior spec review that bound the design space
- **Current state inventory** grounded in live code, not memory
- **Decision** with chosen design rules and target outcome
- **Alternatives considered** with concrete rejection reasons
- **Consequences** (positive and negative)
- **Guardrails** for the follow-on implementation task

### Relationship to task plans

The ADR is reviewed first. Any implementation task plan is then derived from
the approved ADR. The ADR is the durable design artifact; the task plan is the
execution plan that implements it.

If the ADR itself needs structured investigation (tool inventory, schema
evaluation), that work belongs in the assessment or spec — not in a wrapper
task plan around the ADR.

### Exit gate → Task Plan

| Criterion | Required? |
|-----------|-----------|
| Planning review with findings in MCP | Yes |
| All review findings resolved | Yes |
| Spec updated to reference the ADR and replace unresolved placeholders | Yes |
| Rejected alternatives documented with rationale | Yes |

---

## Stage 3: Task Plan

**Artifact:** `*-task-plan.md`
**Template:** [TASK_PLAN.template.md](../templates/TASK_PLAN.template.md)
**Location:** Package-local `docs/tasks/` or monorepo `docs/tasks/`

### Purpose

Decompose spec items into implementation slices with proof commands, lane
ownership, and merge order. Task plans are execution artifacts — they describe
how to build and verify, not what to build (that's the spec's job).

### Required content

- **Spec item references** — trace each slice back to a spec item ID
- **Slices** with goal, changes, and proof (not phases — see template)
- **Verification strategy** with deterministic test commands
- **Lane decomposition** (optional, for multi-agent work)

### Key principle: reference the spec, don't duplicate it

Task plans should reference spec items for code-level detail rather than
restating what the spec already says. The Current State Analysis section in
a task plan should add only task-specific context (test-surface observations,
lane constraints) not already in the spec.

### Task plan variants

| Variant | Deliverable | Example |
|---------|-------------|---------|
| **Implementation task** | Code + tests + contract docs | AHMCP-2, AHMCP-3 |
| **Design task** | A reviewed ADR | AHMCP-4 |

Design tasks follow the same template structure but their slices produce
investigation and design artifacts instead of code.

### Package-local tasks

For tasks scoped to a single package (not owned by a monorepo epic), replace
the template's "Owning Epic" with "Project" and "Epic Short ID" with "Task ID".
The task ID prefix should be the package short name (e.g. `AHMCP` for
`agent-handoff-mcp`).

### Exit gate → Implementation

| Criterion | Required? |
|-----------|-----------|
| Slices trace back to reviewed spec items | Yes |
| Proof commands verified against current test suite | Yes |
| Contract/docs changes included in same slices as behavior changes | Yes |

---

## Stage 4: Implementation

Implementation follows the standard [development workflow](development-workflow.md):
TDD cycle, slice checklist, MCP handoff decisions, and review findings.

Each completed slice records a `slice_complete_*` decision in MCP with:
- Changes made
- Verification evidence
- Schema/contract changes (if any)
- Open threads

---

## Pipeline Traceability

Every artifact should trace back to its upstream source:

```
Assessment finding F2
  └── Spec item OC-001 (Trace: F2)
        └── Task plan AHMCP-2 / Slice 1 (implements OC-001)
              └── Decision #1234 (references OC-001)
```

This chain makes it possible to answer:
- Why was this change made? → Spec item → Assessment finding
- Is the design decision reviewed? → ADR review run in MCP
- Is the spec fully implemented? → Spec items → Task plan checklists → MCP decisions

---

## Exemplars

These artifacts from the output-contract-v2 work demonstrate the pipeline:

| Stage | Artifact | Path |
|-------|----------|------|
| Assessment | Output state-keeping report | `packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-output-state-keeping-report.md` |
| Spec | Output contract v2 spec | `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md` |
| ADR | Typed tool surface consolidation | `docs/agentic/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md` |
| Task plan (Tier 1) | Bounded rendering + mutation output | `packages/agent-handoff-mcp/docs/tasks/AHMCP-2-bounded-current-task-rendering-and-mutation-output-task-plan.md` |
| Task plan (Tier 2) | Response envelope rollout | `packages/agent-handoff-mcp/docs/tasks/AHMCP-3-response-envelope-and-output-contract-v2-rollout-task-plan.md` |
| Task plan (design) | Tool surface consolidation ADR | `packages/agent-handoff-mcp/docs/tasks/AHMCP-4-typed-tool-surface-consolidation-adr-task-plan.md` |
