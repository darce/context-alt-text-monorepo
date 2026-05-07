# E15 App Refactoring Preimplementation Assessment

Date: 2026-05-06

## Question

What surfaces in `apps/` need to be updated, refactored, or culled before implementing:

- `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md`
- `docs/tasks/15.0/E15-14-localwp-batch-smoke-argument-plumbing-task-plan.md`
- `docs/tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md`
- `docs/tasks/15.0/E15-16-dashboard-durable-activity-and-diagnostics-task-plan.md`
- `docs/tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md`

Goal: reduce unnecessary complexity, correct the local projection of remote/local DB facts, reduce latency, and stabilize the codebase before feature work expands these paths.

## Executive Decision

Do the P0 refactors before implementing the task files. They are not aesthetic cleanup; they are boundary repairs that keep later implementation from encoding false state, duplicating contracts, or depending on misleading verification.

The highest leverage work is:

1. Fix the LocalWP smoke harness argument parser and payload before any runtime proof uses it.
2. Split person authority from roster review projections and make projection freshness/source explicit.
3. Make post-curation suggestion refresh durable, idempotent, bounded, and status-backed before adding roster queues.
4. Bound suggestion scanning before curriculum queues or person review surfaces depend on refresh latency.
5. Replace dashboard-local job memory as an authoritative activity source before dashboard triage polish.
6. Extract small priority/projection builders from large UI/controller files before adding new states.

This follows the refactoring texts directly: manage complexity by removing accidental complexity and tangled dependencies (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:1521`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:1534`), refactor in behavior-preserving steps before adding behavior (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:332`, `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:505`), keep dataflow boundaries explicit (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15700`), and measure latency as a distribution rather than trusting averages or happy-path smoke output (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`).

Spec output: [docs/specs/e15-app-refactoring-preimplementation-spec.md](../../specs/e15-app-refactoring-preimplementation-spec.md) translates this assessment into stable preimplementation requirements, ownership mapping, ADR gates, and validation commands.

## P0 Before Implementation

### 1. Fix and harden the LocalWP smoke harness

Surface:

- `apps/prototype-wp-alt-context/Makefile`
- `apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php`

Why before implementation:

E15-14 identifies this as priority 1 because the current smoke command can silently pass a false proof: the Makefile still forwards `--` into `eval-file` (`apps/prototype-wp-alt-context/Makefile:320`), and the PHP script casts positional args with `(int)` plus `max()` (`apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php:12`). The task plan says this can convert an operator's requested `SMOKE_LIMIT=10 BATCH_SIZE=5` into a one-image pass (`docs/tasks/15.0/E15-14-localwp-batch-smoke-argument-plumbing-task-plan.md:21`, `docs/tasks/15.0/E15-14-localwp-batch-smoke-argument-plumbing-task-plan.md:25`).

Refactor/update:

- Remove the leaked separator from the Makefile target.
- Replace positional `(int)` coercion with a tiny explicit parser that rejects `--`, missing required values, non-integers, and out-of-range values.
- Add `limit` and `batch_size` to the final smoke payload; it already emits `timeout_seconds` and `poll_interval_ms` (`apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php:150`).
- Add `scripts/test_localwp_batch_smoke.py` before any LocalWP/public-demo proof depends on this target.

Literature basis:

- Operability means predictable behavior and visibility into runtime internals (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:1504`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:1513`).
- Refactoring should preserve behavior while improving structure; this is the smallest safe repair before wider feature work (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:332`).

### 2. Establish the roster projection boundary before roster UI work

Surface:

- `apps/prototype-wp-alt-context/src/api/class-api.php`
- `packages/shared-contracts/schemas/roster-entry.schema.json`
- `apps/prototype-wp-alt-context/js/admin/api/rosterApi.ts`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx`

Why before implementation:

E15-13 and E15-17 both depend on a person-first review projection. Today `get_roster_entries()` returns a count-only person list via a correlated cluster count (`apps/prototype-wp-alt-context/src/api/class-api.php:329`, `apps/prototype-wp-alt-context/src/api/class-api.php:336`), while the shared schema requires only `id`, `name`, `tags`, `cluster_count`, and `updated_at`. The task plans explicitly call this out as insufficient (`docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md:54`, `docs/tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md:44`).

Refactor/update:

- Split the write model (`wp_acx_persons`, local person authority) from the canonical RCL-004 enriched roster-entry projection defined through `packages/shared-contracts/schemas/roster-entry.schema.json`.
- Add projection fields before UI work consumes them: `person_uuid`, representative evidence, clusters, face instances, media IDs/URLs, bboxes, queue memberships, projection freshness, and allowed actions.
- Keep `RosterEntry` compatibility only as a narrow legacy/list shape if needed; avoid overloading it with both write and review semantics.
- Move projection assembly out of `class-api.php` into a small repository/mapper, because `class-api.php` is already a 1,015-line mixed controller and curation writer.

Dependencies and owner:

- Hard prerequisite: ADR-009 remains `Status: Proposed`; accept or conditional-accept it before contract-changing event/projection work starts (`docs/adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md:7`, `docs/adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md:72`).
- Spec owner: RCL-004 in [docs/specs/recognition-roster-curation-loop-spec.md](../../specs/recognition-roster-curation-loop-spec.md) is the canonical projection contract, not the RSU TypeScript sketch.
- Task owner: E15-13 Slice 3 lands the shared projection/schema and API. E15-17 Slice 1 may parse routes early, but it must not render the person workspace until the RCL-004 fields exist (`docs/tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md:81`).

Literature basis:

- DDIA's system-of-record versus derived-data distinction maps directly: person rows are authoritative, roster review is derived and rebuildable (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15680`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15688`).
- Materialized views speed repeated reads but must be updated from source changes (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4733`).
- Context-specific read/write models reduce coupling; CQRS is useful where business logic grows (`literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:1874`, `literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:1880`).

### 3. Make post-curation refresh a durable bounded workflow

Surface:

- `apps/prototype-description-service/roster/application/curation_sync_service.py`
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py`
- `apps/prototype-wp-alt-context/src/api/class-api.php`
- `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php`
- local projection tables that will expose refresh status

Why before implementation:

E15-13 requires `cluster_person_bound` to trigger durable post-curation suggestion refresh and per-event status (`docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md:44`, `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md:160`). The current WordPress payload queues `cluster_uuid` and `person_uuid`, but not the resolved person label (`apps/prototype-wp-alt-context/src/api/class-api.php:492`, `apps/prototype-wp-alt-context/src/api/class-api.php:498`). The backend replay mutates cluster `roster_id` and label state but does not create a durable refresh event/status (`apps/prototype-description-service/roster/application/curation_sync_service.py:113`). `refresh_for_cluster()` only updates existing pending suggestions and returns early when none exist (`apps/prototype-description-service/recognition/application/suggestions/refresh_service.py:377`, `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py:395`).

Refactor/update:

- Introduce a single post-curation refresh use case that records `queued/running/completed/no_candidates/timed_out/failed` per operation.
- Make the WordPress outbox payload carry or resolve the authoritative person label at the boundary.
- Keep operation IDs/idempotency keys flowing from WordPress outbox to backend refresh status.
- Replace "logs imply status" with durable status rows projected back to WordPress.
- Put concurrency, timeout, retry, and batch limits on refresh work before queue UI exists.

Dependencies and owner:

- Hard prerequisite: ADR-009 must decide the local-authority, derived-refresh, and derived-projection boundary before this work changes replay semantics (`docs/adrs/ADR-009-recognition-curation-refresh-and-person-review-projection.md:72`).
- Spec owners: RCL-001 owns the post-curation event contract; RCL-002 owns durable per-event refresh status.
- Task owner: E15-13 Slice 2 owns event/status contract implementation before E15-13 Slice 4 queue UI or E15-17 refresh badges consume it (`docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md:277`).

Literature basis:

- Derived data integrity matters more than timeliness; async lag is tolerable, corrupted or missing derivations are not (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:21356`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:21374`).
- Event processing preserves integrity through atomic messages, deterministic derivation, operation IDs, idempotence, and reprocessing (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:21415`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:21421`).
- Timeouts are mandatory for networked systems; "wait forever" is not a design (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4322`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4330`).

### 4. Bound suggestion scanning before curriculum queues use it

Surface:

- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py`
- `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`
- suggestion repository APIs and tests

Why before implementation:

`surface_for_newly_labeled_cluster()` can scan up to 1,000 clusters when no candidate IDs are provided (`apps/prototype-description-service/recognition/application/suggestions/refresh_service.py:527`), then loops identities and performs gate checks per identity (`apps/prototype-description-service/recognition/application/suggestions/refresh_service.py:587`, `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py:620`). This may be fine for small fixtures, but E15-13 adds queue semantics and E15-17 adds low-latency scrub/review surfaces. Letting the UI depend on unbounded refresh would bake tail latency into the product.

Refactor/update:

- Require candidate partitioning for post-curation refresh where possible; reserve full tenant scans for explicit backfill jobs.
- Emit metrics for candidate count, identities scanned, suggestions created, p95/p99 runtime, timeout count, and no-candidate outcomes.
- Keep gate/constraint checks deterministic and testable by moving concurrency to the workflow edge.
- Make "create missing suggestions" and "refresh existing scores" separate named steps under one orchestration status.

Dependencies and owner:

- Spec owner: RCL-002 owns create-missing versus refresh-existing behavior; RCL-007 owns aggregate latency/queue metrics; RCL-008 must not define queue membership using frontend-only scans.
- Task owner: E15-13 Slice 2 must introduce bounded refresh execution with status; E15-13 Slice 5 may add aggregate metrics. Slice 4 curriculum queues must wait until scan bounds and projection-backed queue predicates exist (`docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md:211`, `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md:215`).

Literature basis:

- Latency work should start with expected bounds and measurement; optimizing without bounds wastes effort (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:702`).
- Tail latency dominates when a request waits on fanout work (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:799`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:801`).
- Concurrent code is hard to test; keep it at controlled edges (`literature/extracted/refactoring/modern-software-engineering.txt:8641`, `literature/extracted/refactoring/modern-software-engineering.txt:8644`).

### 5. Replace dashboard-local activity as authoritative system state

Surface:

- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts`
- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php`
- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php`
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx`

Why before implementation:

E15-16 states that Recent Activity currently reads browser local storage and can mislead operators (`docs/tasks/15.0/E15-16-dashboard-durable-activity-and-diagnostics-task-plan.md:21`, `docs/tasks/15.0/E15-16-dashboard-durable-activity-and-diagnostics-task-plan.md:44`). The hook confirms this: it reads `window.localStorage` and fetches only remembered job IDs (`apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts:7`, `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts:19`, `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts:57`). Meanwhile `BatchRunRepository` already records durable batch run rows, child job IDs, status totals, and timestamps (`apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php:51`, `apps/prototype-wp-alt-context/src/sovereign/repositories/class-batch-run-repository.php:148`), but only exposes status by run ID.

Refactor/update:

- Add a narrow `list_recent_for_tenant(limit=10)` repository method and REST endpoint before dashboard claims durable activity.
- Return source/provenance metadata: `durable_batch_run`, `remote_job_status`, or `browser_local_fallback`.
- Demote or label local storage as "this browser" until durable records are available.
- Migrate Dashboard and Workbench consumers together so the hook shape does not fork.

Dependencies and owner:

- Spec owner: DASH-007 owns durable Recent Activity semantics in [docs/specs/alt-context-dashboard-operator-triage-spec.md](../../specs/alt-context-dashboard-operator-triage-spec.md).
- Task owner: E15-16 Slice 1 records the durable-source decision; E15-16 Slice 2 migrates or demotes the hook. E15-15 may only use existing fields and must not present browser-local activity as system history (`docs/tasks/15.0/E15-16-dashboard-durable-activity-and-diagnostics-task-plan.md:111`, `docs/tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md:131`).

Literature basis:

- Systems of record and derived data must be explicit, or architecture becomes confusing (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15700`).
- Explicit dataflow improves provenance, integrity checking, and debugging (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:21656`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:21662`).

### 6. Extract a dashboard priority model before UI rearrangement

Surface:

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/`
- `apps/prototype-wp-alt-context/js/admin/hooks/useSyncStatus.ts`
- `apps/prototype-wp-alt-context/js/admin/api/recognition/types/sync.ts`

Why before implementation:

E15-15 requires deterministic priority ordering using existing fields only (`docs/tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md:17`, `docs/tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md:32`). Today `DashboardPage` renders orientation before operational panels (`apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:100`), calculates state inline (`apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:42`), renders sync health through nested ternaries (`apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:218`), and duplicates generic Workbench navigation (`apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:345`).

Refactor/update:

- Extract `buildDashboardPriorityModel(inputs)` as a pure function covered by tests before visual rearrangement.
- Extract small render components for Sync Health, Activity, and Utility Actions.
- Cull duplicate generic navigation cards when no durable current work exists.
- Keep Tier 1 to existing REST fields; do not add diagnostics until E15-16 proves the source rows.

Dependencies and owner:

- Spec owner: DASH-002 owns priority ordering; DASH-003/DASH-005/DASH-006/DASH-008/DASH-009 own existing-field triage and utility demotion.
- Task owner: E15-15 Slice 1 extracts the priority model; E15-15 Slices 2-3 apply state-aware utilities and partial-state rendering without new REST fields (`docs/tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md:110`).

Literature basis:

- Visual hierarchy depends on de-emphasizing secondary content, not making everything compete (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:574`).
- Data labels are a last resort; naive label/value output gives every datum equal emphasis (`literature/extracted/refactoring/Refactoring-UI.txt:588`, `literature/extracted/refactoring/Refactoring-UI.txt:596`).
- Poor structure increases the chance of bugs during change; refactor first when the structure is not convenient for the feature (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:502`, `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:505`).

### 7. Keep raw clusters as evidence, not the default identity model

Surface:

- `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterGrid.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx`
- roster route parsing and tests

Why before implementation:

E15-17 is explicit: roster should open on people and review queues, with clusters as evidence (`docs/tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md:17`, `docs/tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md:32`). Today the app still has only `entries` and `clusters` tabs (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:18`), uses the Entries tab as default (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:26`), and the drawer presents "Cluster Identity" plus similarity/media labels as the primary context (`apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx:150`, `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx:205`).

Refactor/update:

- Add route parsing for `person`, `queue`, `face`, and `cluster` before rendering the new workspace.
- Keep old entries/clusters routes reachable as compatibility views, but stop adding new behavior to them as primary identity surfaces.
- Move cluster assignment controls behind person/evidence context once the projection exists.
- Cull duplicate named cluster cards as primary identities after E15-13 lands person grouping.

Dependencies and owner:

- Spec owner: RSU-001 through RSU-004 consume RCL-004 projection fields; the RCL-004 schema remains canonical when RSU needs UI-only fields.
- Task owner: E15-17 Slice 1 owns route parsing and compatibility routes; Slices 2-4 must wait on the E15-13 projection, grouping, refresh-status, and queue-membership contracts (`docs/tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md:79`).

Literature basis:

- Keep business concepts separate by context, even when raw data overlaps (`literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:1857`, `literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:1870`).
- UI hierarchy should highlight what matters and de-emphasize secondary evidence (`literature/extracted/refactoring/Refactoring-UI.txt:472`).

## P1 Enabling Refactors

### 8. Split large PHP controllers along use-case seams

Surface:

- `apps/prototype-wp-alt-context/src/api/class-api.php` (1,015 lines)
- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php` (1,109 lines)
- `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` (406 lines)

Recommendation:

- Extract roster person write operations, roster review projection reads, and curation outbox enqueueing from `class-api.php`.
- Extract batch run listing/projection acknowledgement helpers from `class-analysis-jobs-controller.php`.
- Keep `class-sync-status-controller.php` focused on status payload assembly; diagnostics should come from named repository methods.

This is P1, not P0, except for the projection and durable activity pieces above. Fowler supports small extractions, not sweeping rewrites (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:333`, `literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:417`).

### 9. Add local projection freshness/integrity checks

Surface:

- `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php`
- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php`
- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php`

Recommendation:

- Expose projection freshness and source version in the person review projection.
- Keep `mirror-integrity` as an operator check, but add targeted tests for person-review projection rebuild correctness.
- Avoid expanding reset behavior until projection/read contracts are clear.

DDIA frames derived state as reprocessable from source events/data, which is exactly the correctness property this local projection needs (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:22226`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:22234`).

### 10. Promote operational metrics only after source ownership is named

Surface:

- `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php`
- `apps/prototype-description-service/recognition/observability/`
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py`

Recommendation:

- Add refresh queue depth, p95/p99 refresh latency, failure rate, recovery time, and label-to-visible-suggestion lead time only when each metric has a named source.
- Preserve existing circuit-breaker, timeout, and resource-pool controls.

Release It! calls out circuit-breaker state, timeouts, request counts, response time, resource pool health, and cache health as operational surfaces (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4560`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:11181`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:11195`).

## Cull or Defer

Cull before implementation:

- Treat browser-local Recent Activity as non-authoritative. Either label it as current-browser fallback or remove it from primary dashboard hierarchy until durable batch-run listing exists.
- Remove duplicate dashboard utility cards when they do not represent current work.
- Stop expanding raw cluster grid behavior as the primary roster identity model after person projection exists.
- Remove false-positive smoke coercion and any "Unknown" status copy that masks a missing source.

Defer deliberately:

- Broad `apps/prototype-description-service` refactoring. E15-13 already says only enabling refactors are allowed (`docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md:29`).
- New similarity score semantics in the scrubber. E15-17 says not to invent them before E15-13/RCL-009 supplies fields (`docs/tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md:27`).
- Dashboard ownership of curriculum queues unless E15-13 explicitly chooses dashboard entry ownership (`docs/tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md:28`, `docs/tasks/15.0/E15-16-dashboard-durable-activity-and-diagnostics-task-plan.md:28`).

## Recommended Preimplementation Order

1. E15-14 smoke harness repair.
2. Roster projection contract split: person write model vs person review projection.
3. Post-curation refresh event/status use case with idempotency and bounded execution.
4. Bound suggestion scanning with candidate partitions, timeout/status outcomes, and no-candidate tests.
5. Recent activity durable source decision and `BatchRunRepository` recent list.
6. Dashboard priority model extraction using existing fields.
7. Roster route model extraction for person/queue/face/cluster.
8. Metrics and diagnostics only after the source rows are named.

This order preserves stable verification first, then data integrity, then latency controls, then UI hierarchy. It also keeps refactoring and feature work separately reviewable, matching Fowler's guidance to commit refactors separately from feature additions (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:10124`).

## Minimal Acceptance Gate

Before starting the task implementations, require:

- `make localwp-batch-run-smoke` cannot silently coerce malformed arguments. Verification anchor: `pyenv exec python -m pytest scripts/test_localwp_batch_smoke.py -q`, plus a LocalWP run with explicit `SMOKE_LIMIT=10 BATCH_SIZE=5 TIMEOUT_SECONDS=60 POLL_INTERVAL_MS=500`.
- The RCL-004 enriched roster-entry projection contract exists in `packages/shared-contracts/schemas/roster-entry.schema.json` and distinguishes source facts from derived fields. Verification anchor: shared-contract schema/codegen checks plus WordPress roster API tests that prove `person_uuid`, evidence, and projection status are present.
- `cluster_person_bound` carries/resolves the person label and maps to durable refresh status. Verification anchor: backend curation sync tests and replay/idempotency tests for repeated outbox delivery.
- Suggestion refresh has candidate bounds, timeout/status reporting, and tests for no-candidate/timeout/failure. Verification anchor: `pyenv exec pytest apps/prototype-description-service/recognition/tests apps/prototype-description-service/roster`.
- Dashboard activity rows include provenance or are explicitly local-browser fallback. Verification anchor: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/AnalysisJobsControllerTest.php` and Vitest coverage for durable, empty, fallback, and unavailable activity states.
- Dashboard priority is tested as a pure model, independent of rendering. Verification anchor: `cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/__tests__/DashboardPage.test.tsx js/admin/pages/dashboard`.
