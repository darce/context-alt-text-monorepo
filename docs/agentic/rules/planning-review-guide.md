# Planning Review Guide

> **Purpose:** Structured review checklist for task plans, epics, roadmaps, ADRs, and other planning documents before implementation or approval.
> Planning reviews are document-and-codebase reviews, not branch-diff reviews.

## Quick Navigation

Use this guide when reviewing:

- task plans
- epics
- roadmaps
- ADRs
- implementation plans
- scope/dependency/deferred-work documents

For code diffs and working tree reviews, use [branch-review-guide.md](branch-review-guide.md) instead.

---

## How to Use This Guide

### Scope

Review the planning document against:

1. the current codebase
2. adjacent planning docs and contracts
3. already-completed prerequisite phases
4. the stated success criteria and rollout expectations

The goal is to catch stale assumptions, impossible scope, contradictory sequencing, and unnecessary complexity before implementation starts.

### Agent Procedure

1. Read the planning document.
2. Check the referenced code paths and adjacent plans/contracts that the document depends on.
3. Record each finding in MCP handoff before mentioning it in chat.
4. Cite concrete file and line references for both the plan and the current implementation it contradicts.
5. Prefer findings about correctness, scope realism, and architecture ownership over stylistic doc feedback.

Hard rule for agent responses:

- Do not present a planning-review finding in chat unless it has already been recorded in MCP with a stable `finding_id`.

---

## Planning Review Checklist

### Current-State Accuracy

- [ ] Current-state claims match the actual codebase.
- [ ] "Already implemented" items are actually implemented.
- [ ] "Missing" items are still actually missing.
- [ ] Existing contracts, schemas, and service ownership are described accurately.

### Internal Consistency

- [ ] Problem statement, current-state section, checklist, and success criteria do not contradict each other.
- [ ] Deferred/stretch items do not conflict with "done" or success-criteria language.
- [ ] Phase ordering matches stated prerequisites and dependencies.
- [ ] Terminology is consistent with current ADRs/contracts.

### Architecture and Ownership

- [ ] Proposed changes belong to the named service/layer and do not duplicate existing ownership.
- [ ] New handlers/endpoints are added to the correct boundary.
- [ ] The plan does not re-implement behavior that already exists in another service or adapter.
- [ ] Compound operations have an explicit contract for atomicity, idempotency, and conflict ownership.

### Contract and Data Model Realism

- [ ] Proposed request/response fields exist or are explicitly added in the same scope.
- [ ] Proposed conflict/version semantics match the current storage model.
- [ ] Multi-entity operations define which entity/version drives conflict detection.
- [ ] Schema changes are sufficient for the reporting/metrics the plan promises.

### Rollout and Testability

- [ ] The plan can be implemented incrementally without leaving impossible intermediate states.
- [ ] Tests validate real behavior, not placeholder scaffolding.
- [ ] Manual/E2E-only steps are not used to hide core correctness gaps.
- [ ] Success criteria are objectively testable from code and tests.

### Complexity Control

- [ ] The plan reuses existing abstractions where appropriate.
- [ ] New abstractions are justified by real seams, not hypothetical future flexibility.
- [ ] Scope is minimal for the stated phase goal.
- [ ] Stretch work is truly optional and not required for the phase to be honestly complete.

---

## Finding Categories

Use the same categories as branch review:

- **ANTIPATTERN**: works conceptually but pushes the system toward the wrong structure
- **DEAD_CODE**: obsolete doc paths, stale assumptions, or plans for code paths that no longer exist
- **COMPLEXITY**: unnecessary abstraction or over-scoped implementation
- **GAP**: missing contract, test, migration, dependency, or rollout detail

---

## Severity Guidance

- **HIGH**: the plan cannot be implemented correctly as written, or it assigns work to the wrong architectural owner
- **MEDIUM**: the plan is implementable but likely to cause regressions, churn, or contradictory completion status
- **LOW**: cleanup, wording drift, or minor sequencing/documentation gaps

---

## MCP Handoff Integration (MANDATORY for Agents)

For every finding:

1. Record it with `record_review_finding` / `review-record`.
2. Use the planning doc path as `file_path`.
3. Set `line_start`/`line_end` to the plan lines that contain the stale assumption or contradictory scope.
4. Include a concrete `fix` describing how to rewrite the plan.

After the review:

1. Confirm findings with `list_review_findings` or `get_review_findings_summary`.
2. If requested, patch the plan to resolve the findings.
3. Include `Handoff updated: yes` in the final response.

---

## Output Expectations

Prioritize findings in this order:

1. obsolete assumptions
2. architecture/ownership mistakes
3. contract gaps
4. contradictory scope or checklist logic
5. unnecessary complexity

Do not spend review time on prose polish unless it affects implementation correctness.
