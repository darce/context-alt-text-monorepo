# SLR-2. Circuit Breaker and Bulkhead Unblock

> **Metadata**
>
> - **Date**: 2026-04-09
> - **Author**: GPT-5
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Project**: prototype-description-service
> - **Task ID**: SLR-2
> - **Review Coverage Target**: 2
> - **Status**: Done on `main` — ADR-006 review complete and Tier 3 follow-on plans generated

---

## Objective

Translate the ADR-006 decisions into spec updates and implementation-ready Tier 3 task plans. When this task is complete, the session-lifecycle spec reflects the approved circuit-breaker and bulkhead direction, and the next resilience tasks exist as concrete implementation plans under `docs/tasks/15.0/`.

## Problem Statement

The session lifecycle spec originally stopped at SLR-1 for implementation-ready work. ADR-006 has now been reviewed and its planning findings were resolved, but the spec and task-plan tree still needed to be updated to reflect that approved direction:

- The Tier 3 section in the spec still described the work as ADR-blocked.
- No implementation-ready task plans existed for the approved circuit-breaker and bulkhead split.
- This unblock plan itself still described ADR review closure as future work instead of completed groundwork.

Leaving those docs stale would keep the resilience roadmap artificially blocked even though the architecture choices are already review-clean.

## Constraints

- Scope is limited to planning, spec updates, and task decomposition. No production code changes belong to this task.
- Planning artifacts are written and reviewed on `main`; no dedicated feature branch is needed for this task.
- The output must stay inside `docs/` plus handoff/planning bookkeeping.
- The resulting implementation-ready direction must preserve the SLR-1 ownership model: HTTP dependencies remain the owner of request-scoped session lifecycle.

## Workflow Principles

- Design before implementation. This task closes the documentation/planning gap rather than starting code.
- One concept, one owner. Circuit breaker state and observability pool ownership must each stay explicit in both the ADR and the follow-on task plans.
- Every implementation-ready claim needs explicit proof, contracts, and failure-mode expectations.

## Terminology

- **Circuit breaker**: A guard that opens after repeated dependency failures and short-circuits subsequent attempts until a recovery window elapses.
- **Bulkhead**: A separate resource boundary that keeps observability and diagnostic traffic from consuming the same pool capacity as business requests.
- **Tier 3 unblock**: The planning step that converts ADR-approved architecture into implementation-ready tasks.

## Current State Analysis

- [session-lifecycle-resilience-spec.md](../../specs/session-lifecycle-resilience-spec.md) originally marked `SLR-CB` and `SLR-BH` as Tier 3 items blocked on ADR-006.
- [ADR-006-session-circuit-breaker-and-pool-bulkheading.md](../../agentic/adrs/ADR-006-session-circuit-breaker-and-pool-bulkheading.md) is now review-clean via decision `#1521`, with all `ADR-006-PLAN-*` findings fixed.
- SLR-1 addressed the immediate HTTP lifecycle and timeout risks, so the remaining resilience work is architectural and operational rather than bug triage.
- This unblock task exists to finish the transition from reviewed ADR to implementation-ready task plans on `main`.

## Target Outcome

The spec no longer describes Tier 3 as ADR-blocked, and the next implementation-ready resilience tasks exist with stable choices for:

- circuit breaker ownership and failure accounting
- breaker thresholds and half-open recovery
- observability engine/pool ownership and sizing
- health and diagnostic behavior when the breaker or bulkhead engages

## Context Loading

- Rules: `docs/agentic/rules/planning-review-guide.md`
- Rules: `docs/agentic/rules/planning-pipeline.md`
- Rules: `docs/agentic/rules/development-workflow.md`
- Spec: `docs/specs/session-lifecycle-resilience-spec.md`
- ADR: `docs/agentic/adrs/ADR-006-session-circuit-breaker-and-pool-bulkheading.md`
- Assessment: `docs/assessment/infailed-sql-transaction-investigation-2026-04-09.md`
- Handoff/MCP state: reuse `SESSION-LIFECYCLE-RESILIENCE` for the Tier 3 planning/unblock phase

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| -------- | ----- | ---------------- | --------------- | --------------------- | ------------ |
| ADR-006 | Planning / Backend | Reviewed design artifact | Treat ADR-006 as the source of truth for Tier 3 resilience ownership | n/a | ADR review closure already recorded |
| Session lifecycle spec | Planning | Tier 3 text still says blocked on ADR | Update spec with ADR-backed design references and next implementation split | n/a | planning review |
| Future implementation task plans | Planning | none | Create implementation-ready follow-on tasks from the approved ADR direction | n/a | task-plan review |

## Proposed Solution

1. Keep this unblock plan aligned with the completed ADR review state.
2. Update the session-lifecycle spec so Tier 3 no longer says "blocked on ADR" and instead names the approved implementation split.
3. Generate the implementation-ready follow-on task plans for the approved circuit-breaker and bulkhead work.

## Files and Surfaces to Change

| Surface | File | Change |
| ------- | ---- | ------ |
| ADR status alignment | `docs/agentic/adrs/ADR-006-session-circuit-breaker-and-pool-bulkheading.md` | Keep ADR metadata aligned with its now-approved planning role |
| Spec update | `docs/specs/session-lifecycle-resilience-spec.md` | Replace blocked Tier 3 notes with ADR-backed implementation direction |
| Task planning | `docs/tasks/15.0/` | Add implementation-ready SLR task plans for circuit breaker and bulkhead work |

## Related Files

| File | Note |
| ---- | ---- |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` | SLR-1 established the request-boundary ownership that Tier 3 work must preserve |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/health.py` | Future consumer of breaker and bulkhead state exposure |
| `apps/prototype-description-service/db/session.py` | Future bulkhead design adds a second engine or pool path here |
| `CURRENT_TASK.md` | Must stay aligned with the planning review and unblock decisions |

## Verification Strategy

- Planning verification:
  - `python3 scripts/hooks/guard-task-plan-findings.py --scan-paths docs/tasks/15.0/slr-2-circuit-breaker-and-bulkhead-unblock-task-plan.md`
  - `python3 scripts/hooks/guard-task-plan-findings.py --scan-paths docs/tasks/15.0/slr-3-session-dependency-circuit-breaker-task-plan.md`
  - `python3 scripts/hooks/guard-task-plan-findings.py --scan-paths docs/tasks/15.0/slr-4-observability-pool-bulkhead-task-plan.md`
- Review verification:
  - planning review on the updated spec and follow-on implementation task plans
- Handoff verification:
  - decisions and review findings recorded under `SESSION-LIFECYCLE-RESILIENCE`
  - no claim of implementation readiness without a clean ADR/spec review state

## Slice Delivery

### Slice 1: ADR-006 Review Closure Alignment

**Goal**: Keep this unblock plan aligned with the fact that ADR-006 review is already complete.

Changes:

- Remove the feature-branch assumption from this planning-only task.
- Update the status and narrative so Slice 1 reflects completed ADR review closure rather than pending work.
- Clarify that this planning phase continues under `SESSION-LIFECYCLE-RESILIENCE` in handoff.

Proof:

- Decision `#1521` records ADR-006 planning review closure.
- All `ADR-006-PLAN-*` findings are fixed.

### Slice 2: Spec Unblock

**Goal**: Convert the session-lifecycle spec from "Tier 3 blocked on ADR" to "Tier 3 ready for implementation planning."

Changes:

- Update [session-lifecycle-resilience-spec.md](../../specs/session-lifecycle-resilience-spec.md) with the ADR-backed direction.
- Replace the generic blocked note with the approved implementation split and dependencies.

Proof:

- Planning review of the updated spec is clean.
- The spec no longer instructs readers to stop at ADR review for the Tier 3 items.

### Slice 3: Follow-On Implementation Plan Generation

**Goal**: Produce the next implementation-ready SLR task plans from the now-unblocked spec.

Changes:

- Generate implementation task plans for the approved circuit-breaker and bulkhead work.
- Ensure the plans carry explicit proof bundles, ownership boundaries, and contract surfaces.

Proof:

- The new implementation task plans pass the task-plan guard.
- The plans explicitly trace back to the approved ADR and updated spec.

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the spec, ADR, planning rules, and current handoff state before editing.
- [x] Confirmed the next work is spec/task generation on `main`, not code implementation.
- [x] Named the intended owner for breaker state and observability-pool lifecycle in the ADR.

### Checklist for Slice 1: ADR-006 Review Closure Alignment

- [x] Remove feature-branch assumptions from the unblock plan.
- [x] Update the status and Slice 1 wording to reflect completed ADR review closure.
- [x] Clarify the handoff task ref used for the Tier 3 planning phase.

### Checklist for Slice 2: Spec Unblock

- [x] Update the session-lifecycle spec with the approved Tier 3 direction.
- [x] Remove or rewrite the blocked note so it reflects the reviewed ADR outcome.
- [x] Re-run planning validation on the updated spec/task-plan set.

### Checklist for Slice 3: Follow-On Implementation Plan Generation

- [x] Generate the implementation-ready Tier 3 task plans.
- [x] Include proof bundles, boundary ownership, and contract notes in each plan.
- [x] Log planning decisions and any remaining blockers in handoff.

## Review Readiness

- [x] No implementation task is opened while ADR-006 still has unresolved review gaps.
- [x] The updated spec and follow-on task plans cite the approved ADR directly.
- [x] Handoff clearly records whether Tier 3 is still blocked or fully unblocked.

## Stretch Goals

- [x] Split circuit-breaker and bulkhead implementation into separate task plans because they have different rollout surfaces.

## Success Criteria

- [x] ADR-006 is review-clean and implementation-direction complete.
- [x] The session-lifecycle spec is updated to reflect the approved Tier 3 path.
- [x] Implementation-ready follow-on SLR task plans exist after the unblock work is complete.
