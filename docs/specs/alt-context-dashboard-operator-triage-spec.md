# Alt Context Dashboard Operator Triage Specification

> **Metadata**
>
> - **Date**: 2026-05-05
> - **Author**: Codex
> - **Status**: Draft
> - **Assessment**: [docs/assessments/current/alt-context-dashboard-ux-assessment-2026-05-05.md](../assessments/current/alt-context-dashboard-ux-assessment-2026-05-05.md)
> - **Owning epic**: Unscheduled follow-on; create or link an epic before implementation
> - **Package version target**: n/a

This spec turns the dashboard assessment into a dashboard operator-triage contract. The dashboard should remain the Alt Context home surface, but it should prioritize blocking health, review queues, and durable activity over generic onboarding and broad navigation cards.

**Constraints:** Greenfield admin SPA policy applies. The dashboard is an authenticated WordPress admin surface. It may aggregate existing admin REST endpoints, but implementation is blocked until this spec and a task plan pass planning review with findings resolved. No ADR is required for the default direction because WordPress remains the local operator surface and the dashboard consumes existing local/proxy state. An ADR is required only if the implementation introduces a new cross-service authority for job history, replay diagnostics, or review-queue ownership.

**Literature anchors:** Refactoring UI drives the priority model and data-label treatment (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:617`, `literature/extracted/refactoring/Refactoring-UI.txt:639`). Release It! drives the Sync Health requirement that dashboard checks reflect real processing health and expose actionable diagnostics (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:888`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:3272`). Latency drives recency, queue, and tail-latency reasoning for replay status (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:699`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`). DDIA drives the durable activity requirement by treating job history as a derived read model that needs a source and update contract (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4733`). Modern Software Engineering supplies the feedback-loop guardrail: the dashboard should shorten learning and recovery loops, not just summarize data (`literature/extracted/refactoring/modern-software-engineering.txt:799`, `literature/extracted/refactoring/modern-software-engineering.txt:805`).

---

## Spec Items

### DASH-001: Preserve environment and recognition-mode notice as a global operator signal

**Trace:** F1  
**Priority:** P0  
**ADR gate:** No

The local/hosted recognition notice is useful and must remain visible on supported Alt Context admin pages. It explains the active backend mode and links to Settings, preventing confusion between local recognition, hosted recognition, and demo environments.

**Current anchors:**

- `apps/prototype-wp-alt-context/src/admin/class-admin.php:277` renders the recognition config notice.
- `apps/prototype-wp-alt-context/src/admin/class-admin.php:282` limits the notice to local recognition mode.
- `apps/prototype-wp-alt-context/src/admin/class-admin.php:286` builds the settings link.
- `apps/prototype-wp-alt-context/src/admin/class-admin.php:290` names local mode and hosted-service switching.

**Done when:**

- The dashboard still shows the local-mode notice when recognition source is local.
- The notice remains outside the React dashboard grid so it is not hidden by SPA loading failures.
- Tests or PHP coverage verify the local-mode notice and hosted/non-local suppression behavior.

---

### DASH-002: Establish a dashboard priority model

**Trace:** F2, F3, F4, F8, R-MISS-1  
**Priority:** P0  
**ADR gate:** No

The dashboard must order content by operator urgency instead of static page sections. Blocking sync/replay failures and conflicts come first, review queues come second, library/coverage context comes third, and onboarding/governance/utilities come after current work.

Refactoring UI is the design anchor for this rule: visual hierarchy must make the important element look important, and dashboard labels should support the data rather than compete with it (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:639`).

**Priority order:**

1. Blocking health: sync failures, conflicts, offline/stale state, mirror divergence.
2. Review queues: pending identity clusters, unassigned persons, curriculum queues if E15-13 makes them available.
3. Progress context: library coverage, media with faces, assigned/known person stats.
4. Utilities: retention posture, batch launch, generic navigation, onboarding.

**Current anchors:**

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:100` renders orientation before all operational panels.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:103` renders Library Coverage.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:131` renders Identity Recognition.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:191` renders Sync Health after coverage and identity.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:317` renders Batch Operations.

**Done when:**

- Sync failures, conflicts, offline state, or stale mirror warnings are visually and semantically above onboarding and generic navigation.
- Pending identity review has higher prominence than static people/assigned totals.
- The page has a deterministic priority rule that can be tested from mocked hook data.
- Empty or healthy states do not reserve excessive space above actionable review queues.

---

### DASH-003: Make Sync Health diagnostic using existing fields first

**Trace:** F3, F8  
**Priority:** P0  
**ADR gate:** No for existing fields; yes if new cross-service failure ownership is introduced.

Sync Health is the most important operator panel when failures or conflicts exist. It should continue to show counts and remediation links, but it must also explain recency and available cause context from the existing sync-status contract before requesting new backend fields.

Release It!'s monitoring guidance is the planning anchor: a health panel must prove the system can process real work, not merely that a component responds (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:888`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:3233`). Latency's tail-latency guidance supports adding recency and age details because averages or single counts hide operator pain (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:796`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`).

**Current anchors:**

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:218` maps sync health to summary copy.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:231` renders pending replay, conflicts, and failed replay counts.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:245` renders topology backlog counts.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:266` links failures to `#/workbench?tab=scan&panel=dead-letter`.
- `apps/prototype-wp-alt-context/js/admin/api/recognition/types/sync.ts:21` already exposes `last_curation_acknowledged_at`, `last_curation_conflict_at`, and `last_curation_failed_at`.
- `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php:301` builds the sync-status payload.

**Done when:**

- Failure and conflict summaries include available recency fields, such as last curation failure and last conflict timestamps.
- Topology backlog is grouped with the replay counts instead of appearing as unstructured paragraph text.
- Dead-letter and conflict links remain visible only when counts make them actionable.
- Tests cover healthy, queued, conflict, failure, offline, stale, and topology-backlog states.

---

### DASH-004: Add a sync diagnostics extension only if existing fields are insufficient

**Trace:** F3  
**Priority:** P1  
**ADR gate:** Yes if the extension introduces a new cross-service owner; no if it is local projection from existing outbox/dead-letter tables.

The assessment asks for oldest failure age, latest failure, affected entity type, replay owner, and whether failures are growing. Existing sync-status fields support last failure/conflict timestamps, but not dominant operation type, oldest failure age, or growth trend. Those fields should be added only after the UI exhausts existing payloads.

**Potential additive contract:**

```ts
interface SyncDiagnosticSummary {
  oldest_failed_at: string | null;
  latest_failed_at: string | null;
  dominant_operation_type: string | null;
  dominant_entity_type: string | null;
  failure_trend: 'increasing' | 'stable' | 'decreasing' | 'unknown';
}
```

**Done when:**

- A contract owner is named before adding any new sync diagnostic fields.
- The diagnostic summary is additive to `SyncStatusResponse` and does not replace existing counts.
- PHP unit tests cover the new payload fields from representative outbox/dead-letter/topology rows.
- TypeScript tests assert the dashboard renders the diagnostic details only when present.

---

### DASH-005: Make onboarding state-aware and non-dominant

**Trace:** F4  
**Priority:** P1  
**ADR gate:** No

The orientation card is useful only for true first-run or empty installs. Once an operator has pending clusters, failed replay, conflicts, stale state, or durable job history, onboarding should collapse or move behind a help affordance.

**Current anchors:**

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:100` renders `OrientationCard`.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx:6` controls visibility with `localStorage`.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx:20` renders the large getting-started region.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx:88` links to the first scan.

**Done when:**

- The large orientation card renders only when there is no actionable work: no pending clusters, no sync failures/conflicts, no stale mirror warning, and no recent/durable jobs.
- Dismissal still works, but product state can suppress onboarding even when local storage is unset.
- A compact help/onboarding link remains available after suppression.
- Tests cover first-run, active-work, and dismissed states.

---

### DASH-006: Make Retention posture actionable or demote it

**Trace:** F5  
**Priority:** P2  
**ADR gate:** No

Retention posture is valuable governance context, but the unavailable state must not sit as a dead dashboard card. If retention status is unavailable, the panel should explain the failure category if known and link to Retention Controls or Settings. If no action is possible, the panel should be demoted below blocking health and review work.

**Current anchors:**

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:277` renders Retention posture.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:279` renders unavailable status as plain text.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:307` links to Retention Controls when status is available.
- `apps/prototype-wp-alt-context/js/admin/hooks/useRetentionStatus.ts:28` fetches retention status.

**Done when:**

- Unavailable retention status includes an actionable link or a clear reason that no action is currently available.
- Retention posture does not outrank active sync failure or review queue work.
- Tests cover available, unavailable, and backend-error states.

---

### DASH-007: Replace authoritative Recent Activity with durable job state

**Trace:** F6, F7, R-MISS-2  
**Priority:** P1  
**ADR gate:** No if using existing WordPress batch-run/job state; yes if introducing a new cross-service job-history authority.

Recent Activity must not imply authoritative job history when it is derived from browser local storage. The dashboard should either replace it with a durable recent-job source or label/demote it as current-browser history.

DDIA's materialized-view model is the contract anchor: if Recent Activity is displayed as an authoritative read model, it needs an authoritative input set and refresh/update semantics (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4733`).

**Current anchors:**

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:361` renders Recent Activity.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:363` renders "No recent recognition jobs found."
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:367` maps local job history into rows.
- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts:13` reads from local storage.
- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts:56` fetches only remembered job IDs.
- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:105` exposes batch-run status by run ID.
- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:125` exposes job status by job ID.

**Done when:**

- Primary Recent Activity is backed by durable WordPress/local job or batch-run records, not only local storage.
- If local storage remains, it is labeled as current-browser recent jobs and moved out of the primary triage band.
- Empty activity states do not contradict known durable batch runs.
- Tests cover durable history present, durable history empty, and current-browser fallback.

---

### DASH-008: Narrow Batch Operations into current work plus compact navigation

**Trace:** F6, F7  
**Priority:** P2  
**ADR gate:** No

Batch Operations currently duplicates Workbench navigation. It should become a current-job/status area when there is durable job work, and a compact action row when there is not.

**Current anchors:**

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:317` renders Batch Operations.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:325` renders latest job only when local job history has an ID.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:345` always renders Analysis Queue, Review Hub, and Managed Identities links.

**Done when:**

- Batch Operations does not occupy a large card just to show generic navigation.
- Active/recent durable jobs, if present, are grouped with Recent Activity or a job-status panel.
- Analysis Queue, Review Hub, and Managed Identities remain accessible as compact actions.
- Tests assert that no-job state is concise and active-job state is informative.

---

### DASH-009: Preserve panel independence while adding page-level partial-state rules

**Trace:** F8  
**Priority:** P1  
**ADR gate:** No

The dashboard may continue loading media stats, identity stats, sync status, retention status, and job data independently. However, partial failures must not flatten urgent signals into a generic grid, and panel failures must expose retry or navigation when action is possible.

**Current anchors:**

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:30` loads media stats.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:31` loads recognition job history.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:32` loads sync status.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:34` loads retention status.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:35` loads identity stats.

**Done when:**

- Dashboard tests cover mixed loaded/error/loading states.
- Failed optional panels do not hide loaded blocking-health or review-queue signals.
- Retry affordances exist where retry is supported by the hook.
- Loading placeholders do not reserve first-priority space once blocking health has loaded.

---

## Data and Contract Notes

### Existing data to use first

```ts
interface SyncStatusResponse {
  sync_health: 'healthy' | 'queued' | 'stale' | 'conflicts' | 'failures' | 'offline';
  pending_curation_operations?: number;
  failed_curation_operations?: number;
  conflict_count?: number;
  last_curation_acknowledged_at?: string | null;
  last_curation_conflict_at?: string | null;
  last_curation_failed_at?: string | null;
  topology_commands?: {
    pending: number;
    applied: number;
    failed: number;
    conflict: number;
    last_reconciled_at: string | null;
  };
}
```

```ts
interface DashboardStats {
  people_count: number;
  assigned_clusters_count: number;
  pending_clusters_count: number;
  media_with_faces_count: number;
  unassigned_persons_count: number;
}
```

### Contract extensions to avoid until needed

- Do not add sync diagnostic fields until existing `last_*` fields and topology counts have been rendered.
- Do not add a new job-history authority if existing WordPress batch-run records can provide durable recent jobs.
- Do not mix E15-13 curriculum queue contracts into the dashboard unless that task explicitly chooses the dashboard as the queue entry point.

---

## Implementation Tiers

### Tier 1 - Layout and existing-field triage

Task plan: to be authored under `docs/tasks/` before implementation.

```text
DASH-001  Preserve recognition-mode notice
DASH-002  Dashboard priority model using existing hook data
DASH-003  Sync Health recency and topology rendering from existing fields
DASH-005  State-aware onboarding suppression
DASH-006  Retention unavailable action/demotion
DASH-008  Compact generic batch navigation
DASH-009  Partial-state rules
```

Tier 1 must not introduce new REST response fields. Implementation remains blocked until this spec and its task plan complete planning review with findings resolved.

### Tier 2 - Durable activity and optional diagnostics

Task plan: to be authored under `docs/tasks/` before implementation.

```text
DASH-004  Optional sync diagnostics extension
DASH-007  Durable Recent Activity/job history
```

Tier 2 may touch PHP REST contracts and TypeScript types. It should use existing WordPress batch-run/job state before adding new backend authority. An ADR is required only if the durable activity or sync diagnostics source changes cross-service ownership.

---

## Deferred or Rejected Directions

- Do not remove the dashboard; preserve it as the operator landing page.
- Do not add more generic navigation cards as a substitute for status and next action.
- Do not treat browser-local job history as an authoritative activity feed.
- Do not make Retention posture block the dashboard unless retention is part of the active operator task.
- Do not fold this dashboard work into E15-13 unless curriculum review queues or refresh status explicitly need a dashboard entry point.
- Do not add new sync diagnostic contract fields before rendering available `SyncStatusResponse` fields.

---

## Review and Planning Gates

1. This spec must pass planning review.
2. A task plan under `docs/tasks/` must be created before implementation.
3. If Tier 2 changes cross-service ownership for job history or sync diagnostics, author an ADR before the task plan moves into implementation.
4. If this work is folded into E15-13, update [docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md](../tasks/15.0/E15-13-roster-curation-loop-task-plan.md) and the recognition roster spec to name the dashboard as an owned surface.

---

## Validation Commands

Current-state checks:

```bash
rg -n "OrientationCard|Sync Health|Retention posture|Batch Operations|Recent Activity" apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx
rg -n "last_curation_failed_at|topology_commands|failed_curation_operations" apps/prototype-wp-alt-context/js/admin/api/recognition/types/sync.ts apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php
rg -n "useRecognitionJobHistory|localStorage|fetchBatchRunStatus|fetchScanStatus" apps/prototype-wp-alt-context/js/admin apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php
```

Implementation validation targets:

```bash
cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/__tests__/DashboardPage.test.tsx js/admin/pages/dashboard js/admin/hooks/__tests__/useRecognitionJobHistory.test.tsx js/admin/hooks/__tests__/useSyncStatus.test.tsx
cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/SyncStatusControllerTest.php tests/Unit/AnalysisJobsControllerTest.php tests/Unit/DashboardApiTest.php
```

Manual/browser verification:

```text
Open http://localhost:10010/wp-admin/admin.php?page=alt-context-dashboard#/dashboard.
Verify that a state with sync failures or pending review shows blocking health and review work before onboarding/generic navigation.
Verify that healthy/empty first-run state can still show onboarding.
```

---

## Traceability

| Assessment item | Spec items |
| --- | --- |
| F1 | DASH-001 |
| F2 | DASH-002, DASH-009 |
| F3 | DASH-002, DASH-003, DASH-004 |
| F4 | DASH-002, DASH-005 |
| F5 | DASH-006 |
| F6 | DASH-007, DASH-008 |
| F7 | DASH-007, DASH-008 |
| F8 | DASH-002, DASH-003, DASH-009 |
| R-MISS-1 | DASH-002 |
| R-MISS-2 | DASH-007 |
