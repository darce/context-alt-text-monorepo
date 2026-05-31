# E15-20. Preimplementation Dashboard Authority and Priority

> **Metadata**
>
> - **Date**: 2026-05-06 16:10 EST
> - **Author**: Codex
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-20
> - **Target Branch**: `feature/e15-20-preimpl-dashboard-authority-and-priority`
> - **Review Coverage Target**: 2
> - **Start Command**: `make task-start TASK=E15-20 OBJECTIVE="Implement PREIMPL dashboard authority and priority gates"`

---

## Objective

Implement PREIMPL-005, PREIMPL-006, the dashboard-owned part of PREIMPL-008, and the dashboard-owned part of PREIMPL-009 from [docs/specs/e15-app-refactoring-preimplementation-spec.md](../../specs/e15-app-refactoring-preimplementation-spec.md). When complete, dashboard activity has a durable source or explicit browser-local fallback, and dashboard priority is a pure tested model over honest existing fields.

## Problem Statement

The dashboard currently mixes blocking health, onboarding, generic navigation, retention posture, and browser-local job history without a durable priority model. E15-15 and E15-16 already describe the work; this PREIMPL plan adds the source-decision gate, ADR boundary, provenance requirement, and bounded controller extraction needed before dashboard polish expands the surface.

This plan supersedes [E15-15](E15-15-dashboard-operator-triage-existing-fields-task-plan.md) and [E15-16](E15-16-dashboard-durable-activity-and-diagnostics-task-plan.md) as the canonical PREIMPL dashboard implementation track. Before Slice 1 code edits, record the superseding handoff decision for E15-20 so reviews have an explicit retirement link. Leave E15-15 and E15-16 on their documented lifecycle while their existing branch/worktree state remains active, then retire them through the normal done/archive flow after those branch/worktree states are actually closed.

## Constraints

- Tier 1 priority work must use existing REST/hook fields only.
- Browser-local history must not be presented as authoritative system state.
- No ADR is needed for `BatchRunRepository` plus existing analysis-jobs rows; an ADR is required for a new cross-service emitter, new persistence table, or new tenancy/visibility scope.
- Sync diagnostics are optional and must be source-backed.
- Do not give dashboard ownership of curriculum queues unless E15-13 explicitly assigns dashboard entry ownership.

## Workflow Principles

- Blocking health outranks review work, progress context, onboarding, and utilities.
- Durable activity requires source rows, tenant scoping, status, and provenance.
- Local-browser memory can remain only as labeled fallback.
- Diagnostics should explain real source state rather than decorate counts.

## Terminology

- **Durable recent activity**: Dashboard activity backed by WordPress/local job or batch-run rows.
- **Browser-local fallback**: Job history remembered only by the current browser's local storage.
- **Priority model**: Pure function that orders dashboard bands from hook/REST state without JSX side effects.
- **Activity provenance**: Row source such as `durable_batch_run`, `remote_job_status`, or `browser_local_fallback`.

## Current State Analysis

- `useRecognitionJobHistory` reads local storage and fetches only remembered IDs.
- `BatchRunRepository` stores durable run rows but lacks a recent-list dashboard helper.
- `DashboardPage` calculates state inline and renders orientation before operational panels.
- `class-analysis-jobs-controller.php` exposes by-ID status paths but no narrow recent activity index.
- Optional diagnostics risk expanding `class-sync-status-controller.php` unless source repository methods are named first.

## Target Outcome

Dashboard Recent Activity either reads recent tenant-scoped durable rows with provenance or is clearly labeled and demoted as current-browser fallback. Dashboard priority is computed by a pure model covered by tests, and optional diagnostics are added only after existing fields prove insufficient.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/frontend-guidelines.md`
- Rules: `docs/agentic/rules/backend-php-guidelines.md`
- Rules: `docs/agentic/rules/testing-typescript.md`
- Constitution: `docs/agentic/constitution.md`
- Spec: `docs/specs/e15-app-refactoring-preimplementation-spec.md`
- Spec: `docs/specs/alt-context-dashboard-operator-triage-spec.md`
- Related tasks: `docs/tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md`, `docs/tasks/15.0/E15-16-dashboard-durable-activity-and-diagnostics-task-plan.md`
- Handoff/MCP state: active task `E15-20`, dashboard spec planning findings, PREIMPL findings
- External docs via `ctx7` only if: React/Vitest or WordPress REST behavior blocks a concrete implementation decision.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Dashboard -> hooks | frontend | inline rendering from existing hook data | pure priority model and smaller render helpers | no REST change in priority slice | Vitest |
| Dashboard -> activity source | plugin REST + frontend | browser-local IDs plus by-ID fetches | durable recent list or labeled fallback with provenance | additive; migrate consumers together | PHPUnit + Vitest |
| Analysis jobs controller | plugin REST | by-ID status endpoints | narrow recent activity helper if durable source chosen | additive | PHP REST tests |
| Sync diagnostics | plugin REST | existing counts and `last_*` timestamps | optional additive diagnostics from named rows | additive, only if needed | PHP + TS tests |

## Proposed Solution

First extract the dashboard priority model using only existing fields. Then make the durable activity source decision, implement either the durable recent-list path or labeled fallback, and add optional diagnostics only if existing fields cannot satisfy operator triage.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| dashboard model/view | `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx` | Extract/apply priority model and render helpers |
| dashboard components | `apps/prototype-wp-alt-context/js/admin/pages/dashboard/` | State-aware onboarding, sync health, utility/action components |
| job history hook | `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts` | Add provenance and durable/fallback semantics |
| job repository | `apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php` | Add narrow recent-list helper if chosen |
| job controller | `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php` | Expose recent activity without broad branching |
| sync controller | `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | Optional diagnostics from named methods only |
| tests | `apps/prototype-wp-alt-context/js/admin/**/__tests__`, `apps/prototype-wp-alt-context/tests/Unit` | Cover priority, durable/fallback, diagnostics |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx` | Job history consumer that must migrate with Dashboard |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/sync.ts` | Existing sync status contract |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncStatus.ts` | Existing sync polling hook |
| `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md` | Only relevant if dashboard queue ownership is explicitly assigned |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/__tests__/DashboardPage.test.tsx js/admin/pages/dashboard js/admin/hooks/__tests__/useRecognitionJobHistory.test.tsx js/admin/hooks/__tests__/useSyncStatus.test.tsx`
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/AnalysisJobsControllerTest.php tests/Unit/SyncStatusControllerTest.php`
- Runtime-parity / environment checks:
  - Open `http://localhost:10010/wp-admin/admin.php?page=alt-context-dashboard#/dashboard` after a known batch run.
- Contract/fixture verification:
  - Tests prove activity provenance comes from durable rows or labeled fallback.
- Manual verification:
  - Failure/review states appear before onboarding; browser-local-only activity is labeled and lower priority.

## Slice Delivery

### Slice 1: Existing-Field Priority Model

**Goal**: Make dashboard hierarchy deterministic and testable without new REST fields.

Changes:

- Extract `buildDashboardPriorityModel(inputs)` or equivalent.
- Render blocking health/review work before orientation/utilities.
- Keep status indicators semantic with icon/text, not color alone.

Proof:

- Vitest covers healthy, queued, conflict, failure, offline, stale, topology backlog, and partial loading states.

### Slice 2: Durable Activity Source Decision

**Goal**: Decide whether current WordPress/local rows can back Recent Activity.

Changes:

- Evaluate `BatchRunRepository` and existing analysis-jobs rows against the durability rubric.
- Record a handoff decision before UI migration.
- Choose durable recent list or labeled browser-local fallback.

Proof:

- Decision names source/fallback and ADR requirement.

### Slice 3: Recent Activity Migration

**Goal**: Make Recent Activity authoritative or explicitly local-browser.

Changes:

- Add narrow recent-list repository/controller helper if durable source is chosen.
- Add provenance metadata to activity rows.
- Migrate Dashboard and Workbench consumers together.

Proof:

- PHP and Vitest cover the chosen path's initial contract, including durable present, durable empty, fallback present, fallback empty, and unavailable states.

### Slice 4: Optional Diagnostics and Controller Boundaries

**Goal**: Add diagnostics only when existing fields are insufficient and source rows are named.

Changes:

- Name diagnostics source rows/repositories before adding payload fields.
- Add optional diagnostics as additive fields only.
- Keep `class-sync-status-controller.php` focused on payload assembly from named helpers.

Proof:

- PHP derives diagnostics from source rows; TS renders diagnostics only when present.

## Consolidated Checklist

## Context and Ownership

- [x] Loaded PREIMPL spec, dashboard spec, E15-15/E15-16 related plans, frontend/backend rules, and handoff state.
- [x] Recorded the disposition of E15-15 and E15-16 (superseded by E15-20 with a handoff decision id) before Slice 1 implementation starts.
- [x] Confirmed no new REST fields are used in Slice 1.
- [x] Recorded durable activity source decision before Recent Activity UI migration.

### Checklist for Slice 1: Existing-Field Priority Model

- [x] Priority model implemented as pure function/helper.
- [x] Sync health, review work, onboarding, retention, and utility ordering covered.
- [x] Existing-field-only tests pass.

### Checklist for Slice 2: Durable Activity Source Decision

- [x] `BatchRunRepository` evaluated first.
- [x] Decision records no-ADR or ADR-required boundary.
- [x] Browser-local fallback selected only if durable rubric fails.

### Checklist for Slice 3: Recent Activity Migration

- [x] Activity rows include provenance.
- [x] Dashboard and Workbench consumers migrate together.
- [x] Durable/fallback/empty/unavailable tests pass.

### Checklist for Slice 4: Optional Diagnostics and Controller Boundaries

- [x] Existing fields proved insufficient before diagnostics. (Rubric evaluated: existing `SyncStatusResponse` fields proved sufficient — `sync_health`, `is_stale`, `last_sync_result`, `pending/failed_curation_operations`, `conflict_count`, `last_curation_*_at`, and `topology_commands` already drive the priority model and dashboard rendering. No insufficiency demonstrated, so no diagnostics added.)
- [x] Diagnostic fields are source-backed and additive. (N/A — none added; rubric not met.)
- [x] Controller extraction stays limited to named helpers. (Slice 3 added the one named helper `BatchRunRepository::list_recent_runs` and the narrow `AnalysisJobsController::get_recent_batch_runs` route; no further extraction in Slice 4.)

## Review Readiness

- [x] No dashboard metadata is fabricated from convenience guesses.
- [x] Runtime dashboard check confirms priority and activity provenance.
- [x] Handoff decision records source, ADR boundary, diagnostics decision, and verification.

## Stretch Goals

- [x] Add compact copy distinguishing active jobs, recent durable jobs, and this-browser remembered jobs. *Copy now appears in `DashboardRecentActivitySection.tsx`, `Panels.tsx`, and `recognitionJobHistoryUtils.ts`.*

## Success Criteria

- [x] Dashboard Recent Activity no longer presents local storage as system history. *Backed by `BatchRunRepository::list_recent_runs`, `AnalysisJobsController::get_recent_batch_runs`, `recognitionJobHistoryUtils.ts`, and dashboard tests.*
- [x] Dashboard priority is deterministic and test-covered. *Implemented in `buildDashboardPriorityModel.ts` with focused coverage in `buildDashboardPriorityModel.test.ts`.*
- [x] Optional diagnostics, if present, are source-backed and additive. *No new diagnostics were needed; existing `SyncStatusResponse` fields remained the source-backed surface.*
