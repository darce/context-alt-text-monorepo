# Task Plan

> **Metadata**
>
> - **Date**: 2026-03-29 23:50 EDT
> - **Author**: GPT-5.4
> - **Owning Epic**: [../../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md](../../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: E12
> - **Scope Note**: Review-coverage infrastructure (review-run ledger, global-scope findings, exact-id lookup) is part of E12 ("task-reference prefixing and handoff enforcement"). The E12 epic should be amended to include this task if it does not already reference review-run ledger work. If re-parenting to a future epic is preferred, update the Owning Epic link at that time.

---

# E12-8. Review Run Ledger and Global Review Coverage Queries

## Objective

Make review coverage a first-class handoff concept instead of an inferred heuristic. When complete, operators should be able to query how many review passes a task plan received, which review run opened which findings, and fetch a finding by `finding_id` without relying on the currently active task.

## Problem Statement

Review coverage is currently inferred from a loose mix of decisions and review findings. That breaks down in two concrete ways. First, `list_review_findings(finding_id=...)` claims to support single-finding lookup, but the implementation resolves `task_ref` through the active-task fallback and then filters by that task, so a lookup such as `{"finding_id": "REVIEW-COVERAGE-E12-3-001", "status": "all", "limit": 10}` can fail with `Finding not found for task.` even when the row exists on another task. Second, repo-level review coverage gaps cannot be represented cleanly because review findings are effectively task-scoped; the current workaround is a pseudo-task (`REVIEW-COVERAGE`), which proves the schema is missing a real global review scope.

Third, `generate_current_task_md(task_ref=...)` produces an empty stub when the requested task is not the currently active task and has no row in `task_archives`. The function falls back to the archive table, but tasks that were never activated (e.g., review-only task refs like `E12-8` or `REVIEW-COVERAGE`) have no archive, so the renderer receives `active=None` and writes "No active handoff state found." instead of assembling available context (decisions, findings, blockers, actions) for that task ref.

Operators also lack a direct review-run surface. They can see findings and decisions, but not a first-class answer to: how many review passes has this plan had, what was each run's verdict, and how many issues were raised in each run. Putting mutable counts directly into task-plan metadata would drift; the durable source of truth needs to live in handoff DB and be queried or rendered from there.

## Constraints

- Keep existing task-scoped review finding flows working during rollout; new global/repo-scoped support must be additive first.
- Do not rely on ambient active-task fallback for single-finding lookup when `finding_id` or `finding_db_id` is provided.
- Stable identifiers belong in docs metadata; mutable review counts and latest issue totals belong in generated handoff surfaces, not hand-edited task plans.
- Historical rows and older task plans are grandfathered; backfill should target the minimum metadata and review-linkage needed to make coverage queryable.

## Workflow Principles

- Single-row lookup by stable id must not depend on caller memory about the active task.
- Review coverage should be computed from first-class review-run records, not reverse-engineered from unrelated decisions.
- Task plans should carry stable identity and review expectations only; volatile coverage summaries should be generated from MCP state.
- Repo-level planning/review debt must not be forced onto an unrelated active implementation task just because the schema lacks a neutral scope.

## Terminology

- **Review run**: One completed review pass over a bounded subject, identified by a stable `review_run_id` and linked to its verdict, findings, and optional decision record.
- **Review subject**: The artifact being reviewed; for this task the main subject is a planning document path plus an optional `task_ref`.
- **Repo-scoped finding**: A review finding that applies to a planning/process artifact but is not owned by one active implementation task.
- **Coverage target**: The expected minimum number of review runs for a subject, such as `2` for task plans.
- **Single-finding lookup**: `list_review_findings(finding_id=...)` or `list_review_findings(finding_db_id=...)` used as an exact-id fetch rather than a paginated task-scoped listing.

## Current State Analysis

- [review_findings.py](../../../../packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py) currently resolves `task_ref` even for single-finding lookup, then executes `SELECT * FROM review_findings WHERE finding_id = ? AND task_ref = ?`, which makes the result depend on the active task when `task_ref` is omitted.
- [agent-handoff-mcp.md](../../../agentic/contracts/agent-handoff-mcp.md) documents `list_review_findings` as supporting single-finding lookup by `finding_id`, but it does not state that the caller must also know the owning task ref.
- Review coverage for planning docs is currently inferred from decisions and review findings instead of stored as a first-class review-run ledger.
- The `REVIEW-COVERAGE` pseudo-task workaround is now being used to keep repo-level planning coverage gaps out of unrelated active tasks, which is a strong signal that the current schema cannot express repo-level review subjects honestly.
- [TASK_PLAN.template.md](../../../agentic/templates/TASK_PLAN.template.md) makes the task ref visible in the title, but it does not provide a dedicated metadata field for machine-readable review coverage policy such as `Review Coverage Target` or explicit stable task-ref backfill guidance for older plans.
- `generate_current_task_md` in [api.py](../../../../packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py) handles non-active task refs by looking up `task_archives`, but tasks that were only used as scoping targets (never activated via `set_handoff_state`) have no archive row. The renderer then receives `active=None` and emits a near-empty file. The task's decisions, findings, blockers, and actions are all queryable but never assembled into the output.

## Target Outcome

The handoff DB stores review runs explicitly, review findings can be linked to a review run and to either a task-scoped or repo-scoped subject, and operators can query review coverage directly. `list_review_findings(finding_id=...)` becomes a true exact-id fetch: if the caller omits `task_ref`, the tool finds the row globally or returns an explicit ambiguity error if the id is not unique. Task-plan metadata carries stable identity and optional coverage expectations, but review counts and issue totals come from generated handoff surfaces such as `get_review_coverage(...)` or `list_review_runs(...)`.

## Context Loading

- Rules: [../../../agentic/instructions.md](../../../agentic/instructions.md), [../../../agentic/rules/planning-review-guide.md](../../../agentic/rules/planning-review-guide.md)
- Contracts: [../../../agentic/contracts/agent-handoff-mcp.md](../../../agentic/contracts/agent-handoff-mcp.md)
- Handoff/MCP state: `task_ref="E12-8"` (implementation task) and `task_ref="__repo__"` (repo-scoped findings migrated from the retired `REVIEW-COVERAGE` pseudo-task per decision #1043). The `REVIEW-COVERAGE` pseudo-task is retired; repo-level coverage gaps now use the `__repo__` sentinel scope.
- External docs via `ctx7` only if: SQLite constraint/backfill behavior or MCP pagination semantics require upstream clarification beyond repo-local code

## Contract and Boundary Impact

| Boundary                          | Owner                | Current Contract                                                                                     | Expected Change                                                                                | Compatibility Needed?                                                | Verification                            |
| --------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | --------------------------------------- |
| Review finding query semantics    | agentic-tooling      | [../../../agentic/contracts/agent-handoff-mcp.md](../../../agentic/contracts/agent-handoff-mcp.md)   | Clarify exact-id lookup semantics and explicit ambiguity behavior                              | yes; keep task-scoped list behavior for callers that pass `task_ref` | contract doc + pytest                   |
| Handoff review ledger             | agentic-tooling      | `handoff.db` review-finding storage                                                                  | Add first-class `review_runs` plus repo/global review subject support                          | yes; additive schema with grandfathered historical rows              | schema tests + backfill tests           |
| Planning task metadata            | agentic-process docs | [../../../agentic/templates/TASK_PLAN.template.md](../../../agentic/templates/TASK_PLAN.template.md) | Add stable metadata for review coverage targeting and backfill-friendly task identity guidance | yes; existing plans remain valid until backfilled                    | template update + parser fallback tests |
| Operator review coverage surfaces | agentic-tooling      | ad hoc inference via decisions/findings                                                              | Add explicit `get_review_coverage` / `list_review_runs` query surfaces                         | yes; additive only                                                   | pytest + handoff smoke checks           |

## Proposed Solution

Introduce a dedicated `review_runs` ledger and a real repo/global review subject model. Keep task plans responsible only for stable identifiers and coverage targets, while the DB owns mutable review-run counts and issue totals. Fix `list_review_findings` so exact-id lookup is global by default and only task-scoped when `task_ref` is explicitly provided.

## Files and Surfaces to Change

| Surface    | File                                                                                  | Change                                                                                              |
| ---------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| docs       | `docs/agentic/templates/TASK_PLAN.template.md`                                        | Add optional `Review Coverage Target` metadata guidance and explicit stable task-ref backfill notes |
| docs       | `docs/agentic/contracts/agent-handoff-mcp.md`                                         | Document review-run schema, repo-scoped review subjects, and exact-id lookup semantics              |
| backend    | `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py`                 | Remove active-task fallback from exact-id lookup and add repo/global scope support                  |
| backend    | `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` (schema definitions and migration helpers) | Add `review_runs` table and review-subject schema helpers; `core.py` remains pure CRUD per rg-013 |
| backend    | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`                             | Register additive review coverage query surfaces                                                    |
| backend    | `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`                             | Add CLI fallback commands for review coverage queries                                               |
| tests      | `packages/agent-handoff-mcp/tests/test_review_findings.py` or targeted existing files | Add exact-id lookup, ambiguity, repo-scope, and coverage-summary tests                              |
| docs/tasks | `docs/tasks/12.0/**`                                                                  | Backfill stable task-ref metadata on legacy planning docs where needed                              |

## Related Files

| File                                                                  | Note                                                                                   |
| --------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py` | Current single-finding lookup bug is here                                              |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`            | Existing schema/bootstrap helpers likely absorb new review-run table creation          |
| `docs/tasks/12.0/accurate-token-and-context-metrics-task-plan.md`     | Example of a task-scoped review coverage finding                                       |
| `docs/tasks/12.0/portable-handoff-mcp-server-task-plan.md`            | Example of a legacy plan that currently needs repo-level coverage tracking             |
| `CURRENT_TASK.md`                                                     | Must not become the review coverage dashboard; generated coverage should stay separate |

## Verification Strategy

- Deterministic tests:
  - `pyenv exec python -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q` (existing; covers schema bootstrap and state helpers)
  - `pyenv exec python -m pytest packages/agent-handoff-mcp/tests/test_review_findings.py packages/agent-handoff-mcp/tests/test_handoff_state.py -q` (target command once `test_review_findings.py` is created in Slice 1/2; a checklist item tracks creation of that file)
- Runtime-parity / environment checks:
  - Query `list_review_findings` with `{"finding_id": "REVIEW-COVERAGE-E12-3-001", "status": "all", "limit": 10}` and confirm the row is returned without requiring `task_ref`.
  - Query repo-scoped findings with `list_review_findings(task_ref="__repo__")` to confirm legacy `REVIEW-COVERAGE` rows were migrated (see decision #1043). The pseudo-task retirement is complete; the `__repo__` sentinel is the canonical scope going forward.
- Contract/fixture verification:
  - Assert the contract documents that exact-id lookup is global unless `task_ref` is explicitly provided.
  - Assert repo-scoped findings and task-scoped findings serialize with unambiguous scope metadata.
- Manual verification:
  - Inspect one task plan and confirm operators can answer: review count, latest review run id, open findings by severity, and latest verdict from MCP without reading decision prose.

## Slice Delivery

### Slice 1: Review Subject and Run Schema

**Goal**: Add first-class review-run storage and a real non-task review scope.

Changes:

- Add a `review_runs` table with at minimum: `review_run_id`, `task_ref`, `subject_path`, `subject_kind`, `review_mode` (CHECK allows `branch`, `release_audit`, `planning`), `verdict_decision` (TEXT — the stable decision string from `record_decision`, not the integer PK), `verdict`, `reviewed_at`, and actor provenance. The `review_mode` value set is expanded here relative to `review_findings.review_mode`; also add a `_shared.py` migration to expand the `review_findings.review_mode` CHECK to include `planning`.
- Extend `review_findings` with a nullable `review_run_id` link and explicit scope metadata so repo/global review findings do not need the `REVIEW-COVERAGE` pseudo-task workaround.
- Use the sentinel value `"__repo__"` for repo-scoped findings. This avoids removing the `task_ref TEXT NOT NULL` constraint (which would require a non-trivial migration). `record_review_finding` should accept `task_ref="__repo__"` explicitly, and task-scoped listing queries must exclude `task_ref = '__repo__'` rows unless repo-scope is explicitly requested. Document this sentinel in the contract.
- Backfill historical rows conservatively: existing task-scoped findings remain valid; repo-level coverage gaps can migrate later from the pseudo-task bucket.

Proof:

- Schema migration/bootstrap tests prove new rows can be inserted and historical rows still read correctly.

### Slice 2: Exact-ID Lookup Fix

**Goal**: Make `list_review_findings(finding_id=...)` behave like a true exact-id fetch.

Changes:

- When `finding_id` or `finding_db_id` is provided and `task_ref` is omitted, skip `_resolve_task_ref(...)` and query globally — applies to both `list_review_findings` (read path) and `update_review_finding` (write path).
- If exactly one row matches, return it with its real `task_ref` or repo/global scope metadata.
- If multiple rows match the same `finding_id`, return an explicit ambiguity error listing candidate scopes instead of silently binding to the active task.
- Keep current task-scoped behavior when `task_ref` is explicitly provided.
- Document the `finding_id` naming convention: values should be prefixed with the owning task-ref or review scope (e.g., `E12-3-001`, `REVIEW-COVERAGE-E12-3-001`) to minimize cross-scope ambiguity. Global uniqueness is not guaranteed by the schema; ambiguity errors are the intended safety net for the collision case.

Proof:

- Regression test for `{"finding_id": "REVIEW-COVERAGE-E12-3-001", "status": "all", "limit": 10}` returns the E12-3 finding without a `task_ref` parameter.
- Regression test for `update_review_finding` with a bare `finding_id` and no `task_ref` resolves globally and applies the update correctly.
- Ambiguity tests prove duplicate ids across scopes fail loudly and informatively.

### Slice 2b: Non-Active Task Rendering

**Goal**: Make `generate_current_task_md` useful for any valid `task_ref`, not just the active or archived task.

Changes:

- Fix `_render_current_task_md` in `_shared.py` (around line 1910): when `active` is `None` but `state` contains non-empty `decisions`, `findings_open`, `blockers_open`, or `actions_pending` lists, render a useful markdown document from those lists rather than emitting "No active handoff state found." The query layer (`get_handoff_state`) already fetches this data correctly for any `task_ref`; the bug is in the renderer's early-exit on `active` being falsy.

Proof:

- Regression test for `generate_current_task_md(task_ref="E12-8")` when E12-8 is not the active task and has no archive row; output must contain the task's decisions, findings, and actions instead of "No active handoff state found."

### Slice 3: Review Coverage Query Surfaces

**Goal**: Give operators a direct coverage/readiness surface instead of forcing inference from unrelated records.

Changes:

- Add `get_review_coverage(task_ref=None, subject_path=None)` that returns review count, latest review run ids, latest verdict, open findings by severity, and reopened-finding count.
- Add `list_review_runs(...)` for detailed review-run inspection and audit history.
- Link `record_review_finding` and review verdict decisions to `review_run_id` so issue counts per run are queryable.

Proof:

- Query tests prove operators can fetch review count and per-run issue totals directly from MCP.

### Slice 4: Template and Backfill Policy

**Goal**: Make future planning docs coverage-queryable without embedding mutable counters in the docs.

Changes:

- Update [../../../agentic/templates/TASK_PLAN.template.md](../../../agentic/templates/TASK_PLAN.template.md) with optional stable metadata such as `Review Coverage Target: 2` and explicit guidance that dynamic review counts remain DB-generated.
- Define the minimum backfill policy for older plans that need stable task-ref metadata or repo/global scope migration.
- Retire the `REVIEW-COVERAGE` pseudo-task once repo/global scope is supported natively.

Proof:

- Template and backfill tests show new plans are queryable by stable identity and older plans degrade gracefully until migrated.

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before drafting.
- [x] Confirmed no external dependency context is required for the draft itself.
- [x] Scoped the change as a handoff schema/API/task-template issue rather than an ADPH-4 implementation defect.

## Slice 1: Review Subject and Run Schema

- [x] Add a first-class `review_runs` ledger.
- [x] Add repo/global review scope metadata so non-task findings do not need a pseudo-task.
- [x] Update `record_review_finding` write path to accept nullable/repo-scoped `task_ref`.
- [x] Create `packages/agent-handoff-mcp/tests/test_review_findings.py` for exact-id, ambiguity, and repo-scope tests.
- [ ] Backfill historical rows conservatively.

## Slice 2: Exact-ID Lookup Fix

- [x] Remove active-task fallback from exact-id review-finding lookup when `task_ref` is omitted.
- [x] Apply the same global-lookup fix to `update_review_finding` write path.
- [x] Return explicit ambiguity errors for duplicate `finding_id` matches across scopes.
- [x] Document `finding_id` naming convention (task-ref prefix) in contract doc.
- [x] Add regression tests for the failing `finding_id` payload.

## Slice 2b: Non-Active Task Rendering

- [x] Fix `_render_current_task_md` in `_shared.py` to render available context when `active` is None but data exists.
- [x] Add regression test for `generate_current_task_md` with a non-active task ref that has decisions/findings but no archive.

## Slice 3: Review Coverage Query Surfaces

- [x] Add review coverage and review-run query surfaces.
- [x] Link review findings and verdict decisions to `review_run_id`.
- [x] Prove operators can query review count and issue totals directly.

## Slice 4: Template and Backfill Policy

- [x] Update task-plan template metadata guidance for stable review coverage targeting.
- [x] Document that mutable review counts stay in MCP-generated surfaces, not hand-edited task plans.
- [x] Retire the `REVIEW-COVERAGE` pseudo-task after native repo/global scope lands.

## Review Readiness

- [x] No review-coverage behavior is left dependent on the active-task fallback.
- [x] Single-finding lookup semantics are documented and tested.
- [x] Handoff records the schema/API/template changes and any migration policy.

## Stretch Goals

- [x] Add generated review coverage summaries to `CURRENT_TASK.md` via `generate_current_task_md` (the `## Review Coverage` section). Dashboard and operator overview surfaces (`get_handoff_dashboard_view`) are out of scope for this task; that extension is deferred to a future task if needed.

## Success Criteria

- [x] `list_review_findings(finding_id=...)` works without `task_ref` for unique findings and fails explicitly on ambiguity.
- [x] Operators can query review count, latest review run, and issue totals directly from MCP state.
- [x] Repo/global planning findings no longer require the `REVIEW-COVERAGE` pseudo-task workaround.
- [x] `generate_current_task_md(task_ref=...)` renders task context (decisions, findings, actions) for any valid task ref, even when that task was never activated or archived. Fix is in `_render_current_task_md` (_shared.py), not the query layer.
