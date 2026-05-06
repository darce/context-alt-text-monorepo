# E15-16. Dashboard Durable Activity and Diagnostics

> **Metadata**
>
> - **Date**: 2026-05-05 21:15 EST
> - **Author**: GitHub Copilot
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-16
> - **Target Branch**: `feature/e15-16-dashboard-durable-activity-and-diagnostics`
> - **Review Coverage Target**: 2

---

## Objective

Replace misleading browser-local dashboard activity with durable job state and add sync diagnostics only where existing fields are insufficient. When this task is complete, Recent Activity has an authoritative local source or is explicitly labeled as browser-local fallback, and any new diagnostic fields have a named owner and tests.

## Problem Statement

Dashboard Tier 1 can improve hierarchy using existing fields, but [docs/specs/alt-context-dashboard-operator-triage-spec.md](../../specs/alt-context-dashboard-operator-triage-spec.md) Tier 2 identifies two deeper gaps: Recent Activity is currently based on browser local storage, and Sync Health may need diagnostics beyond existing `last_*` timestamps and topology counts. A primary dashboard activity feed that forgets known server-side jobs can mislead operators during E15 public-demo verification.

## Constraints

- Depends on E15-15 or an equivalent Tier 1 dashboard priority model.
- Use existing WordPress batch-run/job state before adding a new authority.
- Add an ADR only if durable activity or diagnostics introduce new cross-service ownership.
- Do not mix E15-13 curriculum queue contracts into this task unless E15-13 chooses dashboard entry ownership.

## Workflow Principles

- Durable dashboard facts need authoritative inputs and refresh semantics.
- Browser-local memory can be useful only when labeled as current-browser context.
- New diagnostic metadata must come from real source data, not inferred counts.

## Terminology

- **Durable recent activity**: recognition job or batch-run history backed by WordPress/local records or another named authoritative source.
- **Browser-local fallback**: job history remembered only by the current browser's local storage.
- **Sync diagnostic summary**: optional additive metadata such as oldest failure time, latest failure time, dominant operation/entity type, and failure trend.

## Current State Analysis

- `useRecognitionJobHistory` reads remembered job IDs from local storage and fetches status only for those IDs.
- `DashboardPage` renders Recent Activity as if it represents system activity.
- The plugin has job and batch-run status endpoints by ID, but no clearly named dashboard job index in the current spec packet.
- `wp_acx_batch_runs`, persisted through `AltContext\Sovereign\Repositories\BatchRunRepository`, is the first durable source to evaluate because it already stores `created_at`, `updated_at`, `terminal_state`, aggregate totals, and child job IDs, even though it does not yet expose a recent-runs list helper or REST endpoint.
- Existing sync status exposes `last_curation_acknowledged_at`, `last_curation_conflict_at`, `last_curation_failed_at`, and topology counts; it does not expose oldest failure age, dominant entity/operation, or failure trend.

## Target Outcome

Recent Activity is either backed by durable WordPress/local job records or clearly presented as current-browser history below authoritative dashboard bands. Sync diagnostics are additive, owner-named, and only added after Tier 1 proves existing fields are insufficient.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/frontend-guidelines.md`
- Rules: `docs/agentic/rules/backend-php-guidelines.md`
- Rules: `docs/agentic/rules/testing-typescript.md`
- Spec: `docs/specs/alt-context-dashboard-operator-triage-spec.md`
- Assessment: `docs/assessments/current/alt-context-dashboard-ux-assessment-2026-05-05.md`
- Prerequisite task: `docs/tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md`
- Handoff/MCP state: active task `E15-16`, open findings for dashboard spec/task plans
- External docs via `ctx7` only if: WordPress REST, React Query, or test-library behavior blocks a concrete implementation decision.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Dashboard -> activity source | plugin REST + frontend | browser local storage plus by-ID job status fetches | durable job list or explicitly labeled browser-local fallback | Additive; no existing callers should break | PHP REST tests + Vitest |
| Sync status diagnostics | plugin REST | existing counts and `last_*` timestamps | optional additive diagnostic summary only if needed | Additive; no replacement of existing counts | PHP REST tests + TypeScript render tests |
| Dashboard job types | frontend + shared local types | hook-local job state | typed source/provenance metadata for activity rows | Yes, current hook consumers must migrate together | Vitest for Dashboard and Workbench consumers |

## Proposed Solution

First inspect existing job and batch-run persistence to choose a durable local source. If it can support Recent Activity, add a narrow dashboard activity endpoint or hook that lists recent jobs with provenance and status. If it cannot, demote and label the local-storage feed while recording a follow-on. Add sync diagnostics only as an explicit extension with PHP tests and TypeScript rendering tests.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| job REST/controller | `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php` | Add or expose durable recent job list if source exists |
| sync REST/controller | `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | Add optional diagnostics only after source validation |
| job history hook | `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts` | Distinguish durable source from browser-local fallback |
| dashboard view | `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx` | Render authoritative activity or labeled fallback |
| tests | `apps/prototype-wp-alt-context/js/admin/**/__tests__`, `apps/prototype-wp-alt-context/tests/Unit` | Cover durable/fallback diagnostics behavior |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx` | Consumer of job history hook that must migrate safely |
| `apps/prototype-wp-alt-context/src/sovereign/` | Potential durable local job/batch source |
| `docs/tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md` | Prerequisite priority model |
| `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md` | Only relevant if curriculum queues become dashboard activity inputs |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/__tests__/DashboardPage.test.tsx js/admin/hooks/__tests__/useRecognitionJobHistory.test.tsx js/admin/hooks/__tests__/useSyncStatus.test.tsx`
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/SyncStatusControllerTest.php tests/Unit/AnalysisJobsControllerTest.php`
- Runtime-parity / environment checks:
  - Open `http://localhost:10010/wp-admin/admin.php?page=alt-context-dashboard#/dashboard` after a known batch run and verify Recent Activity does not contradict durable state.
- Contract/fixture verification:
  - PHP tests prove diagnostic fields come from outbox/dead-letter/topology rows or remain absent.
- Manual verification:
  - Browser-local-only history is labeled and lower priority when no durable source exists.

## Slice Delivery

### Slice 1: Durable Activity Source Decision

**Goal**: Decide and prove whether current WordPress/local job state can back Recent Activity.

Changes:

- Inspect current job/batch-run persistence and controller capabilities, starting with `wp_acx_batch_runs` via `BatchRunRepository` as the first durable-source candidate.
- Add tests around the chosen source or demote local-storage history if no durable source exists.
- Record an implementation decision in handoff before changing the dashboard activity contract.

Decision rubric:

- A durable source is acceptable only if it exposes `(a)` `created_at` plus current/terminal status, `(b)` per-tenant scoping consistent with the existing REST handlers, and `(c)` at least the 10 most-recent rows without relying on browser-local memory.
- Evaluate sources in order: existing `wp_acx_batch_runs` storage via `BatchRunRepository`, an additive recent-runs controller surface layered on that storage, then a new authority only if both options fail.
- If no durable source satisfies the rubric, Slice 1 must choose the labeled browser-local fallback path and record that decision in handoff before any UI change demotes or repaints Recent Activity.

Proof:

- PHP or TypeScript tests prove the chosen source/fallback behavior.

### Slice 2: Recent Activity Migration

**Goal**: Make the dashboard activity feed authoritative or explicitly browser-local.

Changes:

- Add a durable recent activity endpoint/hook if source exists.
- Add source/provenance metadata for activity rows.
- Migrate Dashboard and Workbench consumers without losing current result links.
- Preserve the Workbench dependency inventory during migration: `jobHistory`, `jobStatuses`, `rememberJob`, `selectJob`, `forgetJob`, `clearHistory`, and `handleSelectJobFromHistory` must all move to the new source/provenance shape together.

Proof:

- Vitest covers durable history present, durable history empty, local fallback present, and local fallback empty.

### Slice 3: Optional Sync Diagnostics Extension

**Goal**: Add diagnostic metadata only where existing fields cannot satisfy operator triage.

Changes:

- Name the diagnostic owner and source rows before adding fields.
- Add optional `SyncDiagnosticSummary` payload fields if justified.
- Render diagnostics only when present; keep counts and existing links intact.

Proof:

- PHPUnit covers diagnostic field derivation.
- Vitest covers rendering with and without diagnostics.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the dashboard spec, dashboard assessment, E15-15 plan, and handoff state before editing.
- [ ] Confirmed whether a new ADR is required for durable job or diagnostic ownership.
- [ ] Named the source of every new activity/diagnostic field before implementation.

### Checklist for Slice 1: Durable Activity Source Decision

- [ ] Existing job/batch-run persistence inspected.
- [ ] Activity source or browser-local fallback decision recorded in handoff.
- [ ] The recorded decision applies the explicit durability rubric (`created_at` + status, tenant scoping, 10 recent rows).
- [ ] Initial source/fallback tests captured.

### Checklist for Slice 2: Recent Activity Migration

- [ ] Recent Activity renders durable job state or explicit browser-local fallback.
- [ ] Dashboard and Workbench hook consumers migrate together, including `jobHistory`, `jobStatuses`, `rememberJob`, `selectJob`, `forgetJob`, `clearHistory`, and `handleSelectJobFromHistory`.
- [ ] Tests cover durable, empty, fallback, and unavailable states.

### Checklist for Slice 3: Optional Sync Diagnostics Extension

- [ ] Existing fields proved insufficient before adding diagnostics.
- [ ] Diagnostic owner and source rows documented.
- [ ] PHP and TypeScript tests cover optional diagnostics.

## Review Readiness

- [ ] No dashboard metadata is fabricated from convenience guesses such as `count(payload)` unless the contract says so.
- [ ] Any new payload fields are additive and source-backed.
- [ ] Handoff decision records activity source, diagnostics decision, and verification.

## Stretch Goals

- [ ] Add a small operator copy distinction between active jobs, recent durable jobs, and this-browser remembered jobs.

## Success Criteria

- [ ] Dashboard Recent Activity no longer presents local storage as authoritative system history.
- [ ] Sync diagnostics, if added, are source-backed and optional.
- [ ] Tests cover both authoritative and fallback activity behavior.
