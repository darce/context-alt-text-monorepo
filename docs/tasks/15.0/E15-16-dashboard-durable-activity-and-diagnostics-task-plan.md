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

## Disposition

E15-16 is **superseded by [E15-20](E15-20-preimpl-dashboard-authority-and-priority-task-plan.md)** as the canonical PREIMPL implementation track for dashboard priority, durable activity authority, and optional diagnostics. The supersession was recorded in handoff as `cdx_decision_E15-20_supersede_e15_15_e15_16_dashboard_preimpl_tracks` (decision `2823`).

The full E15-16 scope landed under E15-20 and is reachable from `main`:

- **Slice 1 (Durable Activity Source Decision)** and **Slice 2 (Recent Activity Migration)** were delivered by `feat(dashboard): durable recent activity from BatchRunRepository (Slice 3)` (`a3fbee3d`, merged via `006de8c0`). Implementation surfaces:
  - `BatchRunRepository::list_recent_runs( string $tenant_id, int $limit = 5 )` (`apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php`).
  - `AnalysisJobsController::get_recent_batch_runs` exposing `GET /acx/v1/recognition/batch-runs` returning `{ items: [...] }` (`apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php`).
  - `useRecognitionJobHistory` exposing `historySource` of `'durable' | 'browser_local_fallback' | 'unavailable'` and per-row `provenance: 'durable_batch_run' | 'browser_local_fallback'` (`apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts`).
  - `DashboardPage` rendering durable rows with `Durable batch run: <run_id>`, fallback rows with `Current browser memory`, and an explicit `Showing jobs remembered in this browser only.` notice (`apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx`).
- **Slice 3 (Optional Sync Diagnostics Extension)** was explicitly evaluated and **not implemented**. E15-20's checklist for Slice 4 records that existing `SyncStatusResponse` fields (`sync_health`, `is_stale`, `last_sync_result`, `pending/failed_curation_operations`, `conflict_count`, `last_curation_*_at`, `topology_commands`) proved sufficient for operator triage, so no `SyncDiagnosticSummary` was added. The optionality is preserved by Slice 3's plain-language rubric (`operator question -> existing-field gap -> source rows`) for any future need.
- **Verification**: `AnalysisJobsControllerTest::testGetRecentBatchRunsReturnsDurableItemsForCurrentTenant` covers tenant-scoped durable items; `useRecognitionJobHistory.test.tsx` covers the durable / browser-local fallback / unavailable states; `DashboardPage.test.tsx` covers the rendered Recent Activity surfaces. The covering branch review for E15-20 is review run `branch-review-e15-20-20260508-claude` (verdict `pass`, decision `claude_branch_review_e15_20_pass_after_fixes`) at SHA `df8ea24328cac8e5ae7a09e7cd2f1c48d7bfa788`.

The Consolidated Checklist below is therefore ticked against landed E15-20 evidence rather than fresh E15-16 work. Any residual follow-up should re-open the relevant E15-20 surface, not this superseded plan.

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
- `wp_acx_batch_runs`, persisted through `AltContext\Sovereign\Repositories\BatchRunRepository`, is the first durable source to evaluate because it already stores `created_at`, `updated_at`, `terminal_state`, aggregate totals, and child job IDs, and the repository already exposes `list_recent_runs( string $tenant_id, int $limit = 5 )`; the remaining open question is whether that helper meets the dashboard rubric and what REST shape should wrap it.
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

First confirm whether `BatchRunRepository::list_recent_runs()` already satisfies the durable-activity rubric and choose the REST shape that would wrap it. If that helper can support Recent Activity, add a narrow dashboard activity endpoint or hook that lists recent jobs with provenance and status. If it cannot, demote and label the local-storage feed while recording a follow-on. Add sync diagnostics only as an explicit extension with PHP tests and TypeScript rendering tests.

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

**Goal**: Confirm whether the existing recent-runs repository helper can back Recent Activity and choose the REST contract shape or fallback path.

Changes:

- Confirm `BatchRunRepository::list_recent_runs()` against the durability rubric, including tenant scoping, limit behavior, and the existing row fields it returns.
- Choose the REST response shape that would wrap the helper if it qualifies, including provenance labeling and any field omissions that remain unresolved.
- Record the implementation decision in handoff before changing the dashboard activity contract; if the helper fails the rubric, record the labeled browser-local fallback path instead.

Decision rubric:

- A durable source is acceptable only if it exposes `(a)` `created_at` plus current/terminal status, `(b)` per-tenant scoping consistent with the existing REST handlers, and `(c)` at least the 10 most-recent rows without relying on browser-local memory.
- Evaluate sources in order: existing `BatchRunRepository::list_recent_runs()` output, an additive recent-runs controller surface layered on that helper, then a new authority only if both options fail.
- If the helper meets the rubric, Slice 1 must choose the dashboard REST shape to build on top of it, including the row fields and provenance marker needed by the UI.
- If no durable source satisfies the rubric, Slice 1 must choose the labeled browser-local fallback path and record that decision in handoff before any UI change demotes or repaints Recent Activity.

Proof:

- Handoff decision cites the helper/rubric evaluation and records the chosen REST shape or fallback path.
- Slice 2 carries the PHP and TypeScript test obligation because Slice 1 lands a decision, not production code.

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
- For each proposed diagnostic field, document `operator question -> existing-field gap -> source rows / derivation owner` before adding the payload field.
- Add optional `SyncDiagnosticSummary` payload fields if justified.
- Render diagnostics only when present; keep counts and existing links intact.

Proof:

- PHPUnit covers diagnostic field derivation.
- Vitest covers rendering with and without diagnostics.

## Consolidated Checklist

> All boxes below are ticked against landed E15-20 evidence per the Disposition above. Code references in parentheses point to the landed surface; verification is anchored to E15-20 review run `branch-review-e15-20-20260508-claude` (verdict `pass`).

## Context and Ownership

- [x] Loaded the dashboard spec, dashboard assessment, E15-15 plan, and handoff state before editing. (Done in E15-20 PREIMPL planning; superseding decision `2823`.)
- [x] Confirmed whether a new ADR is required for durable job or diagnostic ownership. (E15-20 confirmed no new ADR; helper + narrow REST route stayed inside existing plugin ownership.)
- [x] Named the source of every new activity/diagnostic field before implementation. (Source named: `wp_acx_batch_runs` rows via `BatchRunRepository::list_recent_runs`. Diagnostics: none added; existing `SyncStatusResponse` fields proved sufficient.)

### Checklist for Slice 1: Durable Activity Source Decision

- [x] Existing job/batch-run persistence inspected. (`BatchRunRepository::list_recent_runs` evaluated and chosen as the durable source.)
- [x] Activity source or browser-local fallback decision recorded in handoff. (E15-20 Slice 2 decision named the durable source; superseding decision `2823`.)
- [x] The recorded decision applies the explicit durability rubric (`created_at` + status, tenant scoping, 10 recent rows). (Helper returns `created_at`/`updated_at`, `terminal_state`, `latest_job_status`, tenant-scoped rows; controller passes `MAX_JOB_HISTORY` from the UI.)
- [x] Slice 1 proof records the chosen REST shape or fallback path without promising tests for non-shipped code. (Chosen shape: `GET /acx/v1/recognition/batch-runs` -> `{ items: RecentBatchRunActivity[] }`; tests landed alongside Slice 2 in E15-20.)

### Checklist for Slice 2: Recent Activity Migration

- [x] Recent Activity renders durable job state or explicit browser-local fallback. (`DashboardPage.tsx` renders `Durable batch run: <run_id>` rows or the labeled `Showing jobs remembered in this browser only.` fallback.)
- [x] Dashboard and Workbench hook consumers migrate together, including `jobHistory`, `jobStatuses`, `rememberJob`, `selectJob`, `forgetJob`, `clearHistory`, and `handleSelectJobFromHistory`. (`useRecognitionJobHistory` returns the full inventory; Workbench `BatchTabContent`, `ConfirmTabContent`, panels, and `WorkbenchContext` migrated in `a3fbee3d`.)
- [x] Tests cover durable, empty, fallback, and unavailable states. (`useRecognitionJobHistory.test.tsx` exercises durable-with-rows, browser-local fallback, and unavailable; `AnalysisJobsControllerTest::testGetRecentBatchRunsReturnsDurableItemsForCurrentTenant` covers the empty/durable PHP path.)

### Checklist for Slice 3: Optional Sync Diagnostics Extension

- [x] Existing fields proved insufficient before adding diagnostics, using `operator question -> existing-field gap -> source rows / derivation owner` for each new field. (E15-20 Slice 4 evaluated the rubric and concluded existing `SyncStatusResponse` fields satisfy operator triage. No diagnostic field was added.)
- [x] Diagnostic owner and source rows documented. (N/A — none added; the rubric remains the gating contract for any future addition.)
- [x] PHP and TypeScript tests cover optional diagnostics. (N/A — none added; existing sync-status tests continue to cover the unchanged surface.)

## Review Readiness

- [x] No dashboard metadata is fabricated from convenience guesses such as `count(payload)` unless the contract says so. (Activity rows are mapped 1:1 from durable rows; provenance is set explicitly per source path.)
- [x] Any new payload fields are additive and source-backed. (`{ items: RecentBatchRunActivity[] }` is a new additive route; per-row fields come from `wp_acx_batch_runs` columns.)
- [x] Handoff decision records activity source, diagnostics decision, and verification. (Superseding decision `2823`; E15-20 review run `branch-review-e15-20-20260508-claude` records verdict `pass` at SHA `df8ea24328cac8e5ae7a09e7cd2f1c48d7bfa788`.)

## Stretch Goals

- [x] Add a small operator copy distinction between active jobs, recent durable jobs, and this-browser remembered jobs. (`DashboardPage.tsx` distinguishes `Durable batch run: <run_id>` vs `Current browser memory` per row, plus the section-level `Showing jobs remembered in this browser only.` notice.)

## Success Criteria

- [x] Dashboard Recent Activity no longer presents local storage as authoritative system history. (Durable path is preferred; browser-local rows are explicitly labeled as such.)
- [x] Sync diagnostics, if added, are source-backed and optional. (N/A vacuously — none added; rubric remains in the plan as gating for any future addition.)
- [x] Tests cover both authoritative and fallback activity behavior. (`useRecognitionJobHistory.test.tsx` plus `AnalysisJobsControllerTest::testGetRecentBatchRunsReturnsDurableItemsForCurrentTenant`.)
