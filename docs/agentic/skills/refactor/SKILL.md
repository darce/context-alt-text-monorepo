---
name: refactor
description: Produce a structured refactoring evaluation for a codebase area and sequence the highest-value remediation work.
mode: advisory
context_budget: 200
makefile_target: null
mcp_tools:
  - review_findings
  - record_event
  - get_handoff_state
tdd_gate: false
disable-model-invocation: false
---

# Refactor

## Overview

Use this skill to produce a structured refactoring evaluation of a codebase area, identifying code smells, design-system gaps, and improvement opportunities with a prioritized remediation sequence.

## Trigger

Use this skill when the request matches any of:

- "refactoring evaluation", "code smell audit", "refactor assessment"
- "evaluate code health", "tech debt assessment"
- "design system audit", "UI token review", "CSS audit"
- "identify refactoring opportunities" on a specific module, package, or stack

Do **not** use this skill for:

- Fixing a specific known bug (use `investigate` instead).
- Reviewing a branch diff for merge readiness (use `review` instead).
- Security-focused auditing (use `security-audit` instead).

## Goal

Produce a document matching the format of the existing refactoring evaluations in `docs/tasks/tech-debt/`, with findings classified by impact, cross-referenced to canonical book methodology, and sequenced into a dependency-aware remediation plan. Record findings in MCP so they survive handoff.

## Canonical Policy

- Use [../../instructions.md](../../instructions.md) for startup, handoff, and evidence-logging policy.
- Use [../../rules/development-workflow.md](../../rules/development-workflow.md) for slice and testing conventions.
- Use this skill for evaluation methodology and output format only; broader process policy lives in the linked canonical docs.

## Reference Works

This skill synthesizes methodology from three complementary sources. Each addresses a distinct dimension of code health:

| Source | Dimension | Applicable stacks |
|---|---|---|
| Fowler/Beck, "Refactoring" 2nd Ed. (2019) | Code structure: smells + 52 named refactorings | All (Python, PHP, TypeScript) |
| Hickey, "Refactoring TypeScript" (2019) | TypeScript-specific patterns: null handling, conditionals, signatures, dumping grounds | TypeScript/React frontend |
| Wathan/Schoger, "Refactoring UI" (2018) | Visual design system: tokens, hierarchy, typography, color, depth | CSS/SCSS design tokens |

The existing evaluations in this repo serve as output format exemplars:

- `docs/tasks/tech-debt/refactoring-evaluation.md` — Fowler/Beck across all stacks
- `docs/tasks/tech-debt/refactoring-typescript-evaluation.md` — Hickey on TypeScript frontend
- `docs/tasks/tech-debt/refactoring-ui-evaluation.md` — Wathan/Schoger on CSS/SCSS

## Domain Detection

Determine which evaluation dimensions to apply based on the target scope. Do not ask — infer from the file paths and content.

### Code Structure (Fowler/Beck) — all languages

**Apply when**: target includes Python (`.py`), PHP (`.php`), or TypeScript (`.ts`, `.tsx`) source files.

**Smell catalog** (Chapter 3, 24 smells):

| Smell | Heuristic | Key refactorings |
|---|---|---|
| Mysterious Name | Names don't communicate intent | Change Function Declaration, Rename Variable/Field |
| Duplicated Code | Same structure in multiple places | Extract Function, Pull Up Method |
| Long Function | >50 lines worth examining, >100 smells strongly | Extract Function, Replace Temp with Query, Introduce Parameter Object |
| Long Parameter List | >4 parameters where a structure would clarify | Introduce Parameter Object, Preserve Whole Object, Remove Flag Argument |
| Global Data | Mutable module-level state | Encapsulate Variable |
| Mutable Data | Data changes in place when immutability safer | Encapsulate Variable, Split Variable, Change Reference to Value |
| Divergent Change | One module changed for multiple unrelated reasons | Split Phase, Extract Class |
| Shotgun Surgery | One change scattered across many modules | Move Function/Field, Combine Functions into Class |
| Feature Envy | Function uses another module's data more than its own | Move Function, Extract Function |
| Data Clumps | Same field groups travel together without a type | Extract Class, Introduce Parameter Object |
| Primitive Obsession | Raw primitives for domain concepts | Replace Primitive with Object, Replace Type Code with Subclasses |
| Repeated Switches | Same conditional dispatch in multiple places | Replace Conditional with Polymorphism |
| Loops | Imperative loops where pipelines would clarify | Replace Loop with Pipeline |
| Lazy Element | Class/function that doesn't justify existence | Inline Function/Class, Collapse Hierarchy |
| Speculative Generality | Abstractions for hypothetical future use | Collapse Hierarchy, Inline Function/Class, Remove Dead Code |
| Temporary Field | Fields set only in certain circumstances | Extract Class, Move Function |
| Message Chains | Long chains traversing object graphs | Hide Delegate, Extract Function |
| Middle Man | Class mostly delegates to another | Remove Middle Man, Inline Function |
| Insider Trading | Modules sharing too much internal knowledge | Move Function/Field, Hide Delegate |
| Large Class | Too many fields or too much code | Extract Class, Extract Superclass |
| Data Class | Fields and accessors but no behavior | Move Function, Extract Function, Encapsulate Record |
| Refused Bequest | Subclass doesn't use inherited behavior | Push Down Method/Field, Replace Subclass with Delegate |
| Comments as Deodorant | Comments masking unclear code | Extract Function, Change Function Declaration |

### TypeScript Patterns (Hickey) — frontend only

**Apply when**: target includes TypeScript/React files under `apps/prototype-wp-alt-context/js/`.

**Additional smell catalog** (Chapters 2-9):

| Chapter | Smell | Key remedies |
|---|---|---|
| Ch. 2 | Null Checks Everywhere | Null Object Pattern, Special Case Pattern, empty collections over null |
| Ch. 3 | Wordy Conditionals | Extract to named booleans, extract as methods, Pipe Classes |
| Ch. 4 | Nested Conditionals | Guard clauses (fail fast), Gate Classes |
| Ch. 5 | Primitive Overuse | Value Objects with immediate validation, replace booleans with enums, Strategy Pattern |
| Ch. 6 | Lengthy Method Signatures | Semantic wrapper methods, extract Data Objects, fluent builders |
| Ch. 7 | Methods That Never End | Extract method (give it a name), Strategy Pattern |
| Ch. 8 | Dumping Grounds | Context-specific classes over generic ones, SRP, CQRS |
| Ch. 9 | Messy Object Creation | Factory functions, Builder pattern |

When a finding overlaps between Fowler and Hickey catalogs, note it as `[Fowler overlap]` in the Hickey finding (or vice versa) and reference the canonical finding ID. Do not duplicate remediation work.

### Design System (Wathan/Schoger) — CSS/SCSS only

**Apply when**: target includes SCSS/CSS token files or component styles under `apps/prototype-wp-alt-context/js/admin/styles/`.

**Token surface evaluation** (7 sections):

| Section | What to evaluate | Maturity target |
|---|---|---|
| Hierarchy | Text hierarchy tiers, button variants, label usage | 3 text colors, 3 button variants, labels as last resort |
| Layout & Spacing | Spacing scale, canvas sizing, ambiguous spacing | 8-10 values, non-linear, 25%+ intervals, `--acx-space-*` tokens |
| Typography | Type scale tokens, font weights, line-height pairing, line length | 5-7 sizes with paired line-height, `--acx-text-*` tokens |
| Color | Gray scale, primary/accent shades, HSL usage | 8-10 shades per hue, semantic naming, `--acx-color-*` and `--acx-gray-*` |
| Depth | Elevation system, shadow tokens | 5 fixed levels (xs through xl), two-part shadows, `--acx-shadow-*` |
| Images | User content handling, icon scaling, aspect-ratio discipline | `object-fit: cover`, controlled aspect ratios, no oversized icons |
| Finishing Touches | Accent borders, empty states, status icon pairing, border reduction | Color + icon pairing, dashed empty state borders, shadows over borders |

**Design token naming**: this codebase uses `--acx-*` prefix for all CSS custom properties (per CLAUDE.md sr-004). Evaluate whether existing tokens follow this convention and whether ad-hoc values should become tokens.

## Codebase-Specific Rules

These rules from CLAUDE.md constrain remediation recommendations:

- **Greenfield policy**: no data migrations, no backward-compatibility shims. Clean rewrites over gradual deprecation.
- **sr-004**: CSS/SCSS must use `--acx-*` design tokens. No hex literals.
- **sr-005**: TypeScript assertion helpers for internal invariants.
- **sr-006**: Python `assert` only for narrow internal invariants; raise exceptions for production behavior.
- **sr-007**: Centralize domain status values as enums or `as const`. No scattered magic strings.
- **sr-008**: More than 8 destructured parameters? Group into 2-3 cohesive typed objects.
- **sr-009**: PHP transaction methods must use a shared `run_transactional(callable)` wrapper.
- **rg-013**: `core.py` must remain pure handoff-state CRUD. No orchestration imports.

When a finding aligns with an existing short rule or regression guard, cite the rule ID in the finding.

## Core Process

1. Determine the evaluation scope and the relevant dimensions to apply.
2. Load only the context needed for the target area and stack.
3. Run the structured evaluation phases below, recording durable findings when the review needs to survive handoff.
4. End with a prioritized remediation sequence that explains dependency order instead of a flat issue dump.

## Phase 1 — Scope and Context

1. Confirm MCP is available. Call `get_handoff_state` to identify the active task.
2. Determine which evaluation dimensions apply (code structure, TypeScript patterns, design system) based on the target files.
3. Read the target files. For a full-stack evaluation, organize by layer:
   - Python backend: `apps/prototype-description-service/`
   - PHP plugin: `apps/prototype-wp-alt-context/src/`
   - TypeScript frontend: `apps/prototype-wp-alt-context/js/admin/`
   - MCP packages: `packages/agent-handoff-mcp/`, `packages/agent-orchestrator-mcp/`
   - CSS/SCSS tokens: `apps/prototype-wp-alt-context/js/admin/styles/`
4. Check for existing evaluations: read `docs/tasks/tech-debt/refactoring-*.md` to avoid duplicating prior findings. Note whether prior findings have been resolved.

## Phase 2 — Systematic Evaluation

Walk the applicable smell catalogs against the target code. For each file:

1. **Measure** against heuristics (line counts, parameter counts, nesting depth, token coverage).
2. **Identify** which smell category applies.
3. **Cite evidence** with file paths and line numbers.
4. **Classify severity**:

| Severity | Code Structure | Design System |
|---|---|---|
| **High** | God object, pervasive primitive obsession, shotgun surgery | Missing token surface entirely, ad-hoc values throughout |
| **Medium** | Long function, feature envy, data clumps, duplicated code | Partial token coverage, inconsistent application |
| **Low** | Mysterious name, speculative generality, lazy element, comments | Missing variant, minor inconsistency |

5. **Prescribe remedy** citing the specific refactoring technique and book reference.

### Cross-document overlap

When the evaluation spans multiple dimensions (e.g., Fowler + Hickey for TypeScript), build an overlap index mapping related findings so refactoring work targets each code area once. Follow the format in the existing evaluations:

```
| This doc | Other doc | Overlap | Canonical action |
|---|---|---|---|
```

## Phase 3 — Architectural Observations

After individual findings, assess structural patterns:

1. **What the codebase does well** — cite specific patterns that align with book prescriptions and should be preserved.
2. **Where the architecture creates smell pressure** — identify structural forces that produce multiple smells (e.g., missing service layer, thin domain entities, no value objects at boundaries).

## Phase 4 — Remediation Sequence

Order recommendations by dependency chain and risk, following Fowler's principle: "refactor in small, tested steps; never refactor on a red bar."

Structure as numbered phases:

```
### Phase N: <Title> (eliminates <finding-ids>)

**Effort:** Small | Small-Medium | Medium | Medium-Large | Large
**Prerequisites:** Phase M (so that <dependency-reason>)

1. <Specific step>
2. <Specific step>
...
```

Include a checklist at the end:

```
## Checklist

- [ ] Phase 1: <item>
- [ ] Phase 1: <item>
- [ ] Phase 2: <item>
...
```

## Phase 5 — Record and Output

### MCP Recording

Record each finding in MCP:

```
record_review_finding(
  session="<session-id>",
  finding_id="REFACTOR-<severity-prefix><n>",
  severity="high|medium|low",
  file_path="<monorepo-relative-path>",
  description="<smell>: <one-paragraph with evidence and book reference>",
  task_ref="__repo__",
  review_mode="branch",
  details={ "line_start": N, "line_end": N, "fix": "<recommended refactoring>" }
)
```

Finding ID format: `REFACTOR-H<n>` for high, `REFACTOR-M<n>` for medium, `REFACTOR-L<n>` for low. This matches the existing evaluation document structure.

Use `batch_record_review_findings` when recording 3 or more findings.

Use `task_ref="__repo__"` for repo-scoped evaluation findings not tied to a single task. If the evaluation was requested as part of a specific task, use that task's ref instead.

### Document Output

Write the evaluation to `docs/tasks/tech-debt/refactoring-<scope>-evaluation.md` following the established format:

```markdown
# Refactoring Evaluation: <Scope Title>

> Cross-referencing <book(s)> against <target> to identify <dimension>.

**Date:** <YYYY-MM-DD>
**Scope:** <description>
**Method:** <catalogs applied>
**Cross-reference:** <links to companion evaluations if any>

---

## Table of Contents
## Executive Summary
## Methodology
## What the Codebase Does Well
## High-Impact Findings
## Medium-Impact Findings
## Low-Impact Findings
## Architectural Observations
## Recommended Refactoring Sequence
## Cross-Document Overlap Index (if multi-dimension)
## Checklist
```

### Decision Recording

Record the evaluation completion:

```
record_decision(
  session="<session-id>",
  decision="refactoring_evaluation_<scope>_<date>",
  rationale="## Changes\n- Evaluation document: docs/tasks/tech-debt/refactoring-<scope>-evaluation.md\n- Findings recorded: <count> (H:<n> M:<n> L:<n>)\n\n## Verification\n- Smell catalog coverage: <catalogs-applied>\n- Cross-reference with prior evaluations: <status>\n\n## Schema / Contract Changes\n- none.\n\n## Open Threads\n- <remediation phases for follow-on work>"
)
```

Regenerate task context: `render_handoff(kind='current_task', task_ref=<active-task-ref>)`.

## Recovery

- If MCP is unavailable, write the evaluation document directly and record findings when MCP returns.
- If a target file has been significantly refactored since a prior evaluation, note which prior findings are resolved and which persist. Update prior finding status with `update_review_finding`.
- If the scope is too broad for a single evaluation (e.g., "the whole monorepo"), recommend splitting by stack and produce one evaluation per dimension. Reference companion documents via the Cross-Document Overlap Index.

## Common Rationalizations

- "I can just list smells without sequencing them." A flat list loses the dependency order that makes a refactor plan actionable.
- "The UI and code-structure issues are basically the same." They are different dimensions and should be assessed separately unless the overlap is explicit.
- "This is only advisory, so MCP recording does not matter." Long-running refactor work frequently spans sessions; durable findings still help the next agent.

## Red Flags

- The target scope spans multiple stacks with no clear primary dimension.
- The proposed remediation sequence depends on code paths you have not actually inspected.
- Findings are drifting into bug review, security review, or branch review instead of refactoring guidance.

## Convergence Criteria

- Every finding is recorded in MCP before being mentioned in the document.
- The evaluation document follows the established format from the existing exemplars.
- High-impact findings include specific file paths, line numbers, and evidence.
- Each finding cites the specific smell name and book reference.
- The remediation sequence is ordered by dependency chain with effort estimates.
- A checklist summarizes all actionable items.
- A `record_decision` entry exists with the evaluation summary.
- Response includes `Handoff updated: yes`.

## See Also

- [../investigate/SKILL.md](../investigate/SKILL.md)
- [../review/SKILL.md](../review/SKILL.md)
- [../../rules/development-workflow.md](../../rules/development-workflow.md)
