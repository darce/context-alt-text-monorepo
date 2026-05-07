---
name: specs
description: Draft or revise repository specs after a scope, assessment, ADR need, or planning-review finding. Use when Codex needs to create docs/specs artifacts, close spec findings, convert assessment findings into RCL-style requirements, or decide what belongs in spec versus ADR/task-plan.
---

# Specs

## Overview

Use this skill to turn reviewed intent and code-verified assessment findings into a spec that is ready for ADR and task-plan work. The skill owns requirement shape, traceability, and deferral boundaries; it does not approve implementation.

## Core Process

1. Load the source artifact first: scope, assessment, prior spec, ADR finding, or planning-review finding.
2. Load only the code anchors needed to verify each requirement. Every major requirement should trace to current code, an assessment finding, or an explicit user decision.
3. Choose the spec path under `docs/specs/` and use existing local spec style before inventing a new format.
4. Write requirements as stable IDs with trace, priority, ADR gate, rationale, and done-when criteria.
5. Separate implementation tiers from implementation permission. Specs may say which requirements are lower-risk, but code still waits for the required ADR/task-plan/review gates.
6. Add an explicit Deferred or Rejected section for tempting alternatives that should not quietly re-enter implementation.
7. End with validation commands and downstream artifact guidance: whether an ADR is required, which task plan should own implementation, and which findings the spec closes.

## Spec Boundaries

- Put user-visible behavior, contracts, constraints, done-when criteria, and deferrals in the spec.
- Put design decisions with alternatives in an ADR when authority, ownership, event semantics, or cross-boundary data models are uncertain.
- Put slice order, branch, lane ownership, and command evidence in a task plan.
- Put observations and code-verified problems in an assessment before writing a broad new spec.

## Review Readiness

Before declaring a spec ready for planning review, check:

- Every finding or assessment item is either mapped to a requirement or explicitly deferred.
- Requirement priorities do not conflict with stated implementation gates.
- Contract-changing items identify the owner and consumer surfaces.
- Fixture strategy is named for regression-critical examples.
- UI requirements define navigation and empty/error states, not just labels.
- Validation commands are deterministic enough for the next agent to run.

## See Also

- [../../../docs/agentic/rules/planning-pipeline.md](../../../docs/agentic/rules/planning-pipeline.md)
- [../../../docs/agentic/rules/planning-review-guide.md](../../../docs/agentic/rules/planning-review-guide.md)
- [../../../docs/agentic/templates/ADR.template.md](../../../docs/agentic/templates/ADR.template.md)
- [../../../docs/agentic/templates/TASK_PLAN.template.md](../../../docs/agentic/templates/TASK_PLAN.template.md)
