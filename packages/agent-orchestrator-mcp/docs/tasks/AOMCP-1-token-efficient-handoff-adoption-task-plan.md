# AOMCP-1. Token-Efficient Handoff Read Adoption

> **Metadata**
>
> - **Date**: 2026-04-07 16:10 EST
> - **Author**: GPT-5.4
> - **Project**: `agent-orchestrator-mcp`
> - **Task ID**: `AOMCP-1`
> - **Target Branch**: `feature/aomcp-1-token-efficient-handoff-adoption` (merged to `main`; commits `c474286d` and `8b7e6252`; feature branch deleted post-merge)
> - **Review Coverage Target**: 2
> - **Status**: Implemented and merged. Sections below are retained as historical context for the work that landed.

## Objective

Reduce unnecessary MCP payload volume on the `agent-orchestrator-mcp` side by adopting the lightweight `agent-handoff-mcp` read parameters that already exist, without changing handoff server defaults or weakening review/close-check behavior. When complete, orchestrator code should ask for only the handoff sections and detail level it actually consumes, and the package should have tests proving those narrower reads preserve behavior.

## Problem Statement

> Historical motivation: this section describes the situation **before** AOMCP-1 landed. See Current State Analysis for the post-implementation state.

The token-optimization assessment in `packages/agent-orchestrator-mcp/docs/tech-debt/mcp-token-optimization-assessment.md` correctly concluded that much of the remaining waste was caller-side, not server-side. `agent-handoff-mcp` already exposed `sections=`, `detail=`, `fields=`, and `top_n_*` / `limit=` shaping controls, but several orchestrator call sites still fetched full handoff payloads even when they only needed `task_ref`, `tests_recent`, or a bounded subset of open items. That wasted context budget in daemon loops, prompt-building paths, and review tooling, and it made the assessment's recommendations non-actionable until a package-local implementation plan existed.

## Constraints

- This task is owned by `agent-orchestrator-mcp`; envelope-format work stays with `AHMCP-7`, and summary-mode field-shaping changes stay with `AHMCP-1`.
- The task must preserve current behavior for review, close-check, lane dispatch, and task resolution. Token savings are not allowed to come from dropping required state.
- The plan should prefer explicit parameterization at the call site over changing `agent-handoff-mcp` defaults, because the current contract keeps full-detail reads as the default behavior.

## Workflow Principles

- Use the smallest read surface that answers the current question.
- Keep hot-state and review flows truthful: if a path genuinely needs full detail, the plan should say so and leave it full.
- Do not duplicate handoff-package usage guidance in multiple places; orchestrator-facing docs should reference the package-owned guide rather than fork it.

## Terminology

- **Shaped read**: A handoff read that passes `sections`, `detail`, `fields`, `top_n_*`, or `limit` to request only the needed payload.
- **Routine state check**: A read used only to determine the active task or a small piece of status, not to render a full review or hot-state view.
- **Hot-state load**: A broader read used at task start, review time, or close-check preparation where multiple sections are legitimately needed together.

## Current State Analysis

- Slices 1-3 are implemented and merged to `main` (commits `c474286d` and `8b7e6252`); the original `feature/aomcp-1-token-efficient-handoff-adoption` branch has been deleted post-merge. The package-owned handoff guide is present at `packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md`.
- `agent-handoff-mcp` already supports `sections="identity"`, `detail="summary"`, and bounded list parameters, and `AHMCP-7` already landed the compact envelope and dict-return transport changes.
- The preferred caller guidance now lives in package-owned `agent-handoff-mcp` docs, and this task references that guide instead of re-documenting parameter semantics locally.
- The orchestrator runtime no longer has accidental full-state reads in `_resolve_task_ref()` (`orchestrator_daemon.py`), `_load_open_handoff_items()` (`review_dispatch.py`), `_task_global_context()` (`lane_prompt.py`), or `review_ready.main()`.
- `ace_metrics.py` still performs a broad bounded handoff read, but that is now an intentional metric-definition choice with code comments, a dedicated helper bundle, and regression coverage.
- This package-local task plan now maps every actionable recommendation from the assessment to implemented slices or explicit upstream ownership.

## Target Outcome

The orchestrator package consistently uses shaped handoff reads where the call site only needs a narrow slice of state, while leaving true hot-state and review flows on fuller reads when necessary. The result is lower token usage in orchestrator-triggered MCP interactions, explicit documentation of which recommendations belong to orchestrator versus handoff-server tasks, and focused tests that lock in the slimmer read patterns.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Rules: `docs/agentic/rules/testing-python.md`
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`
- Package docs: `packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md` (canonical caller guidance, present on this checkout) and `docs/agentic/contracts/agent-handoff-mcp.md` for the contract surface
- Handoff/MCP state: `AOMCP-1`, `AHMCP-1`, `AHMCP-7`, latest assessment decision for `packages/agent-orchestrator-mcp/docs/tech-debt/mcp-token-optimization-assessment.md`
- External docs via `ctx7` only if: upstream FastMCP runtime behavior changes again and the local contract/tests are insufficient to decide a caller-shaping strategy

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `agent-orchestrator-mcp` -> `agent-handoff-mcp` read calls | shared tooling boundary | `docs/agentic/contracts/agent-handoff-mcp.md` | No schema change; orchestrator callers adopt existing read-shaping parameters | Yes; behavior must stay identical while payloads get smaller | Unit tests on orchestrator call sites plus focused command-path assertions |
| Token-usage guidance ownership | `agent-handoff-mcp` docs | package-owned guide is the target steady-state; until that lands, AOMCP tracks it as an upstream dependency | Orchestrator docs reference package-owned guidance instead of re-documenting parameter semantics | Yes; avoid conflicting guidance surfaces and false assumptions about current files | Doc review and dependency-path checks |

## Proposed Solution

Implement the assessment follow-up in three slices. First, classify orchestrator handoff reads by purpose and update the obviously narrow paths to use `sections="identity"` or targeted section lists. Second, apply explicit `detail="summary"` and bounded `top_n_*` values only where the call sites consume truncated or capped data safely, leaving true hot-state flows unchanged. Third, add targeted tests and a small orchestrator-local documentation/reference pass so the adoption is durable and aligned with the handoff package’s canonical guidance.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| orchestrator runtime | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/orchestrator_daemon.py` | Narrow `_resolve_task_ref()` to an identity-only handoff read |
| review tooling | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/review_ready.py` | Request only `identity` + `tests_recent` from handoff state, with explicit caps/detail where safe |
| lane routing | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/review_dispatch.py` | Request only open-item sections needed for dispatch stamping |
| worker prompt assembly | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/lane_prompt.py` | Keep global-context reads bounded and section-scoped to the prompt builder’s actual needs |
| shared helper | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/handoff_read_shapes.py` | Stretch-goal helper bundling the common shaped-read kwargs (e.g. `active_task_identity_kwargs()`) imported by every migrated call site |
| orchestrator tests | `packages/agent-orchestrator-mcp/tests/test_orchestrator_daemon.py` | Add/adjust tests for identity-only task resolution reads |
| orchestrator tests | `packages/agent-orchestrator-mcp/tests/test_review_ready.py` | Assert narrowed handoff-state query usage and preserved readiness behavior |
| orchestrator tests | `packages/agent-orchestrator-mcp/tests/test_review_dispatch.py` | Assert open-item dispatch still works with section-scoped reads |
| orchestrator tests | `packages/agent-orchestrator-mcp/tests/test_lane_prompt.py` | Cover bounded global-context reads if prompt assembly changes |
| planning/docs | `packages/agent-orchestrator-mcp/docs/tasks/AOMCP-1-token-efficient-handoff-adoption-task-plan.md` | Record ownership, slice boundaries, and verification expectations |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-orchestrator-mcp/docs/tech-debt/mcp-token-optimization-assessment.md` | Source assessment and recommendation inventory |
| `packages/agent-handoff-mcp/docs/tasks/AHMCP-1-parameterize-handoff-mcp-read-surfaces-task-plan.md` | Owns server-side summary shaping and default semantics |
| `packages/agent-handoff-mcp/docs/tasks/AHMCP-7-response-envelope-token-optimization-task-plan.md` | Owns compact envelope and transport-side token reductions |
| `packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md` | Canonical package-owned caller guidance now present on this branch |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/ace_metrics.py` | Likely intentional full-read path; verify before changing |

## Verification Strategy

- Deterministic tests:
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-orchestrator-mcp/tests/test_orchestrator_daemon.py packages/agent-orchestrator-mcp/tests/test_review_ready.py packages/agent-orchestrator-mcp/tests/test_review_dispatch.py packages/agent-orchestrator-mcp/tests/test_lane_prompt.py -q`
- Runtime-parity / environment checks:
  - Run the narrowed orchestrator entrypoints against a tmp runtime fixture to confirm active-task resolution, review-ready output, and lane dispatch behavior remain unchanged
- Contract/fixture verification:
  - Confirm every new shaped read uses parameters documented in `docs/agentic/contracts/agent-handoff-mcp.md`
  - Confirm no orchestrator call site assumes legacy top-level mirrors instead of the canonical `data` payload
- Manual verification:
  - Inspect the diffed call sites to verify that full-detail reads remain only where the path genuinely consumes multi-section or untruncated payloads

## Slice Delivery

### Slice 1: Narrow Routine Reads

**Goal**: Replace obviously over-broad handoff reads in routine orchestrator paths with the smallest valid query shape.

Changes:

- Update `_resolve_task_ref()` to use `get_handoff_state(sections="identity")` because it only needs the active `task_ref`
- Update `review_dispatch._load_open_handoff_items()` to request only `findings_open`, `blockers_open`, and `actions_pending`
- Leave `ace_metrics.py` unchanged unless inspection proves the current hot-state read is not part of the metric being measured

Proof:

- Focused orchestrator tests still resolve the active task and still dispatch open issues correctly

### Slice 2: Adopt Explicit Summary and Bounded Reads

**Goal**: Apply `detail="summary"` and bounded `top_n_*` values where the orchestrator only needs compact history slices.

Changes:

- Update `review_ready.main()` to request only the handoff sections it actually consumes (`identity`, `tests_recent`) and cap `top_n_tests`
- Update `lane_prompt._task_global_context()` to keep its existing bounded-item behavior aligned with explicit section selection: `sections="blockers_open,actions_pending,findings_open,decisions_recent,tests_recent"` plus the existing `MAX_GLOBAL_ITEMS` caps
- Verify each narrowed path still gets enough structure for downstream formatting and decision logic

Proof:

- `test_review_ready.py` and `test_lane_prompt.py` pass with assertions covering the narrowed handoff request shapes and unchanged rendered behavior

### Slice 3: Documentation, Auditability, and Follow-Up Boundaries

**Goal**: Make the optimization ownership explicit so future work does not drift back across package boundaries.

Changes:

- Add or update orchestrator-local documentation/comments only where needed to explain why a call site intentionally uses a shaped read
- Reference `packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md` as the canonical caller guidance from any new orchestrator-facing docs; do not duplicate parameter semantics locally
- Record any remaining server-side or contract-default recommendations as dependencies on `AHMCP-1` / `AHMCP-7`, not as orchestrator work

Proof:

- Doc and code review shows a clear split between caller-side adoption and handoff-server ownership
- Handoff decision records the dependency split and the verification bundle

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [x] Confirmed that server-envelope changes remain owned by `AHMCP-7` and summary-shaping/default changes remain owned by `AHMCP-1`.
- [x] Referenced the package-owned `agent-handoff-mcp` usage guide (`packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md`) as the canonical caller guidance instead of duplicating it.

### Checklist for Slice 1: Narrow Routine Reads

- [x] `_resolve_task_ref()` uses an identity-only handoff read.
- [x] `review_dispatch` requests only the open-item sections it consumes.
- [x] Tests prove the narrower reads preserve task resolution and dispatch behavior.

### Checklist for Slice 2: Adopt Explicit Summary and Bounded Reads

- [x] `review_ready` requests only the sections it consumes and caps recent-test reads.
- [x] `lane_prompt` uses explicit section selection consistent with `MAX_GLOBAL_ITEMS`.
- [x] Tests prove the rendered outputs and readiness decisions remain unchanged.

### Checklist for Slice 3: Documentation, Auditability, and Follow-Up Boundaries

- [x] Any new orchestrator-facing guidance references the package-owned token-efficiency guide (`packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md`).
- [x] Remaining server-owned recommendations are captured as dependencies rather than silently folded into orchestrator work.
- [x] Handoff decision records the verification evidence and any intentionally unchanged full-read paths.

## Review Readiness

- [x] No narrowed handoff read drops data that a downstream formatter or gate still consumes.
- [x] All changed orchestrator call sites are covered by deterministic tests or focused runtime fixtures.
- [x] The final implementation notes which full-read paths are intentional and why.

## Stretch Goals

- [x] Add a small helper for common shaped handoff reads if multiple orchestrator call sites converge on the same parameter bundle without obscuring the underlying contract.

## Success Criteria

- [x] Routine orchestrator handoff reads use explicit shaping parameters instead of full-state defaults when they only need identity or bounded subsets.
- [x] Review-ready, lane-dispatch, and prompt-building behavior remain unchanged under the narrower reads.
- [x] The orchestrator package has a clear implementation plan and ownership boundary for the assessment recommendations.
