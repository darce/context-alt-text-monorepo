# E15 App Refactoring Preimplementation Specification

> **Metadata**
>
> - **Date**: 2026-05-06
> - **Author**: Codex
> - **Status**: Draft
> - **Assessment**: [docs/assessments/current/e15-app-refactoring-preimplementation-assessment-2026-05-06.md](../assessments/current/e15-app-refactoring-preimplementation-assessment-2026-05-06.md)
> - **Handoff decision**: `claude_planning_review_e15preimpl_pass_with_findings`
> - **Owning epic**: [E15 Phase 6 - Local Sync Correctness and Audit Closure](../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Package version target**: n/a

This spec turns the E15 preimplementation refactoring assessment into a stable contract for the work that must be handled before E15-13 through E15-17 implementation expands the affected app surfaces. It does not approve implementation by itself; each downstream task still needs its ADR, task-plan, slice, and review gates.

**Scope:** LocalWP smoke proof, roster/person review projection boundaries, durable post-curation refresh, bounded suggestion refresh latency, dashboard activity authority, dashboard priority extraction, person-first roster routing, local projection integrity, and bounded controller use-case extraction. These are preimplementation requirements because they prevent later feature work from depending on false smoke evidence, ambiguous derived data, browser-local state, unbounded refresh work, or oversized mixed-purpose controllers.

**Literature anchors:** This spec follows DDIA's system-of-record versus derived-data distinction for local person authority and projections (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15680`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15700`), Fowler's guidance to refactor in behavior-preserving steps before adding behavior (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:332`, `literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:505`), Latency's p95/p99 and fanout warnings for refresh work (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:801`), Release It!'s timeout and monitoring requirements (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4322`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4560`), and Refactoring UI's visual hierarchy guidance for dashboard and roster surfaces (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:588`).

---

## Findings Closure Map

| Handoff finding | Resolution in this spec / assessment |
| --- | --- |
| `E15-PREIMPL-PLAN-01` Scope/ownership ambiguity | Each requirement below names the owning task/slice and the upstream consumer it blocks. The assessment now adds dependencies and owner notes under each P0 item. |
| `E15-PREIMPL-PLAN-02` Missing ADR-009 dependency | PREIMPL-002 and PREIMPL-003 name ADR-009 as a hard gate; PREIMPL-004 names the RCL-002/RCL-007/RCL-008 dependency chain. |
| `E15-PREIMPL-PLAN-03` Projection naming inconsistency | PREIMPL-002 uses "RCL-004 enriched roster-entry projection" as the canonical contract and treats RSU shapes as UI consumption notes. |
| `E15-PREIMPL-PLAN-04` Missing verification commands | The Validation Commands section names deterministic current-state checks and implementation validation targets. The assessment Minimal Acceptance Gate now includes verification anchors per item. |
| `E15-PREIMPL-PLAN-05` Bound scanning omitted from order | PREIMPL-004 is a standalone P0 requirement, and the assessment Recommended Preimplementation Order now places it before durable activity/dashboard/roster UI work. |
| `E15-PREIMPL-SPEC-ANALYZE-01` Missing controller extraction item | PREIMPL-009 now scopes the P1 controller use-case extractions for `class-api.php`, `class-analysis-jobs-controller.php`, and `class-sync-status-controller.php`. |
| `E15-PREIMPL-SPEC-ANALYZE-02` Missing deferrals | Deferred directions now explicitly reject new scrubber score semantics before RCL-009 and dashboard ownership of curriculum queues unless E15-13 assigns it. |
| `E15-PREIMPL-SPEC-ANALYZE-03` Missing local projection integrity guard | PREIMPL-008 now includes projection freshness/source-version exposure, rebuild correctness tests, and a reset-behavior expansion guard. |
| `E15-PREIMPL-SPEC-ANALYZE-04` Terminology drift | Assessment and spec now use `face instances` for the RCL-004 projection field set. |
| `E15-PREIMPL-SPEC-ANALYZE-05` Dashboard ADR boundary ambiguity | PREIMPL-005 now pins the no-ADR and ADR-required durable-activity source boundaries. |

---

## Preimplementation Ownership Map

| Order | Requirement | Owner task / slice | Must land before |
| --- | --- | --- | --- |
| 1 | PREIMPL-001 LocalWP smoke proof | E15-18 Slice 1, then runtime confirmation in Slice 2 | Any LocalWP/public-demo proof that cites `make localwp-batch-run-smoke` |
| 2 | PREIMPL-002 RCL-004 projection boundary | E15-19 Slice 3 after ADR-009 | E15-21 Slice 1 person workspace rendering and Slice 2 projection rendering |
| 3 | PREIMPL-003 durable post-curation refresh | E15-19 Slice 2 after ADR-009 | E15-19 Slice 4 bounded refresh, E15-21 refresh/status badges |
| 4 | PREIMPL-004 bounded suggestion refresh | E15-19 Slice 4 for Tier 0 bounds/status; E15-19 Slice 5 for Tier 2 aggregate metrics | E15-21 queue UI and low-latency roster review |
| 5 | PREIMPL-005 durable dashboard activity | E15-20 Slice 2 source decision; Slice 3 migration/demotion | Any dashboard copy claiming system-level Recent Activity |
| 6 | PREIMPL-006 dashboard priority model | E15-20 Slice 1 | E15-20 visual rearrangement and partial-state polish |
| 7 | PREIMPL-007 person-first roster route model | E15-21 Slice 1 route parser only; rendering waits on PREIMPL-002 | E15-21 Slices 2-4 person evidence and cluster migration |
| 8 | PREIMPL-008 metrics/source ownership | E15-19 Slice 5 for roster metrics, E15-20 Slice 4 for dashboard diagnostics only after source rows are named | New diagnostics or SLO dashboard panels |
| 9 | PREIMPL-009 bounded controller use-case extraction | E15-19 Slice 5, E15-20 Slice 4, and E15-21 Slice 4 only when touching those surfaces | Any feature work that would add more unrelated logic to the named controllers |

The canonical preimplementation implementation tracks are E15-18, E15-19, E15-20, and E15-21. Each newer task should record its superseding decision before Slice 1 code edits begin. The displaced E15-14, E15-13, E15-15/E15-16, and E15-17 tasks stay on their documented lifecycle until their existing branch/worktree is closed, then retire through the normal done/archive flow.

---

## Spec Items

### PREIMPL-001: LocalWP smoke proof rejects malformed arguments and reports effective parameters

**Trace:** Assessment P0 #1; `E15-PREIMPL-PLAN-04`; [E15-14](../tasks/15.0/E15-14-localwp-batch-smoke-argument-plumbing-task-plan.md)  
**Priority:** P0  
**ADR gate:** No  
**Owner:** E15-18 Slice 1 for parser/command tests; E15-18 Slice 2 for runtime LocalWP proof.

`make localwp-batch-run-smoke` must not silently coerce malformed positional arguments or pass a literal `--` into the PHP smoke script. The smoke result must include the effective `limit`, `batch_size`, `timeout_seconds`, and `poll_interval_ms` values so operators can see what was actually exercised.

**Rationale:** False-positive smoke proof increases accidental complexity by making later debugging chase a misleading verification result. This is a behavior-preserving harness repair, matching Fowler's recommendation to improve structure before adding more behavior (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:332`).

**Done when:**

- The Makefile invocation passes only the intended smoke values to WP-CLI `eval-file`.
- The PHP parser rejects `--`, missing required values, non-integers, and out-of-range values before batch submission.
- The JSON payload reports effective smoke parameters.
- Regression tests cover command generation and parser mapping.

### PREIMPL-002: RCL-004 enriched roster-entry projection is the canonical person review contract

**Trace:** Assessment P0 #2; `E15-PREIMPL-PLAN-01`; `E15-PREIMPL-PLAN-02`; `E15-PREIMPL-PLAN-03`; RCL-004; RSU-001 through RSU-004  
**Priority:** P0  
**ADR gate:** Yes - ADR-009 must accept or conditionally accept the local-authority, derived-projection boundary.  
**Owner:** E15-19 Slice 3 for shared contract/API/projection; E15-21 consumes it only after the fields exist.

The canonical projection name is the RCL-004 enriched roster-entry projection represented through `packages/shared-contracts/schemas/roster-entry.schema.json`. UI specs may call the rendered object a person review surface, but they must not introduce an independent `RosterPersonReview` source of truth.

**Rationale:** `wp_acx_persons` is the authoritative local write model; roster review is derived and rebuildable. DDIA's materialized-view guidance requires explicit update and freshness behavior for this read model (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4733`).

**Done when:**

- `packages/shared-contracts/schemas/roster-entry.schema.json` distinguishes source fields from derived projection fields.
- The projection exposes `person_uuid`, representative evidence, clusters, face instances, media references, bboxes, queue memberships, projection freshness/status, and allowed actions.
- `apps/prototype-wp-alt-context/src/api/class-api.php` no longer owns a mixed curation write plus projection assembly path for this contract; a named repository/mapper owns projection reads.
- E15-21 route/workspace rendering refuses to imply a person workspace when the RCL-004 fields are absent.

### PREIMPL-003: Post-curation refresh is durable, idempotent, and status-backed

**Trace:** Assessment P0 #3; `E15-PREIMPL-PLAN-01`; `E15-PREIMPL-PLAN-02`; RCL-001; RCL-002; [E15-13](../tasks/15.0/E15-13-roster-curation-loop-task-plan.md)  
**Priority:** P0  
**ADR gate:** Yes - ADR-009 must settle replay/event semantics.  
**Owner:** E15-19 Slice 2.

Every curation path that affects a cluster/person binding must map to one post-curation event contract and one durable refresh lifecycle. `cluster_person_bound` must carry or resolve the authoritative person label, and refresh work must record per-event status instead of relying on logs or synchronous request behavior.

**Rationale:** Derived data can lag, but it must be correct, inspectable, and repairable. DDIA's event-processing guidance points to operation IDs, idempotence, and reprocessing as integrity tools (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:21415`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:21421`).

**Done when:**

- WordPress outbox replay carries or resolves the local person label for `cluster_person_bound`.
- Backend replay records a stable operation/idempotency key for refresh work.
- `SuggestionRefreshStatus` or equivalent records `queued`, `running`, `completed`, `no_candidates`, `timed_out`, and `failed`.
- Repeated outbox delivery does not duplicate refresh work.
- E15-19 queue UI and E15-21 refresh badges consume status rows, not log side effects.

### PREIMPL-004: Suggestion refresh has candidate bounds and explicit latency outcomes

**Trace:** Assessment P0 #4; `E15-PREIMPL-PLAN-05`; RCL-002; RCL-007; RCL-008  
**Priority:** P0  
**ADR gate:** No for internal bounds; yes if queue/replay ownership changes.  
**Owner:** E15-19 Slice 4 for bounded execution/status; E15-19 Slice 5 for aggregate metrics.

Post-curation refresh must use candidate partitioning where possible and reserve full-tenant scans for explicit backfill jobs. Queue UI must not depend on a hidden path that can scan up to 1,000 clusters and then fan out through identity checks without timeout/status outcomes.

**Rationale:** Tail latency dominates when work fans out and a user-visible path waits for all branches. Latency measurement must include distributions and bounds, not just averages or happy-path samples (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:799`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:801`).

**Done when:**

- Post-curation refresh accepts an explicit candidate partition or records why a full scan/backfill is being used.
- Refresh status distinguishes no candidates, timeout, failure, candidates created, and existing suggestions refreshed.
- Tests cover no-candidate, timeout, failure, and retry/idempotency paths.
- Aggregate metrics include candidate count, identities scanned, suggestions created, p95/p99 runtime, timeout count, and no-candidate outcomes.
- RCL-008 queue membership is projection-backed, not derived by frontend-only filtering over an unbounded scan.

### PREIMPL-005: Dashboard Recent Activity has a durable source or explicit browser-local fallback

**Trace:** Assessment P0 #5; DASH-007; `E15-PREIMPL-PLAN-01`; [E15-16](../tasks/15.0/E15-16-dashboard-durable-activity-and-diagnostics-task-plan.md)  
**Priority:** P0 for source decision; P1 for full migration  
**ADR gate:** No if the durable source is `BatchRunRepository` plus existing analysis-jobs rows; yes if a new cross-service emitter, new persistence table, or new tenancy/visibility scope is introduced.  
**Owner:** E15-20 Slice 2 source decision; E15-20 Slice 3 migration/demotion.

The dashboard must not present browser-local job memory as system-level history. It must either use durable WordPress/local job or batch-run records, or clearly label and demote the local-storage feed as this-browser history.

**Rationale:** A dashboard activity feed is a derived read model. DDIA's source/projection framing requires an authoritative input set and update contract before a derived view claims system truth (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15688`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:15700`).

**Done when:**

- E15-20 records a handoff decision naming the durable source or choosing labeled browser-local fallback.
- If durable, the source returns at least the 10 most recent tenant-scoped rows with creation time and current/terminal status.
- Dashboard rows include provenance such as `durable_batch_run`, `remote_job_status`, or `browser_local_fallback`.
- `useRecognitionJobHistory` and Workbench consumers do not fork incompatible history semantics.
- Tests cover durable present, durable empty, fallback present, fallback empty, and unavailable states.
- A new WordPress repository method on existing `wp_acx_batch_runs` rows does not require an ADR; a recognition-service-side activity emitter, new table, or cross-tenant visibility change does.

### PREIMPL-006: Dashboard priority is a pure model over existing fields before visual rearrangement

**Trace:** Assessment P0 #6; DASH-002; DASH-003; DASH-005; DASH-006; DASH-008; DASH-009; [E15-15](../tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md)  
**Priority:** P0  
**ADR gate:** No  
**Owner:** E15-20 Slice 1.

The dashboard priority order must be represented by a deterministic pure model before JSX layout changes. Tier 1 must use existing REST/hook fields only and must not add diagnostics or durable activity fields as a shortcut.

**Rationale:** Refactoring UI frames visual hierarchy as choosing what matters most and making secondary content recede (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:574`). Extracting the priority model keeps that decision testable while the UI is rearranged.

**Done when:**

- `buildDashboardPriorityModel(inputs)` or equivalent is covered by tests for sync failures, conflicts, stale/offline state, pending review work, healthy/empty state, and partial loading/failure states.
- Sync Health, Activity, and Utility Actions render from small components or equivalent named helpers.
- Generic navigation cards are compact when they do not represent current work.
- Tier 1 tests prove no new REST fields are required.

### PREIMPL-007: Roster routes are person-first, with clusters as evidence after projection exists

**Trace:** Assessment P0 #7; RSU-001 through RSU-004; [E15-17](../tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md)  
**Priority:** P0 for route parsing; P1 for cluster-grid migration after data contracts land  
**ADR gate:** Yes for projection semantics through ADR-009/RCL-004; no for route parsing alone.  
**Owner:** E15-21 Slice 1 for route model; E15-21 Slices 2-4 after E15-19 contracts land.

The Roster page must parse `person`, `queue`, `face`, and `cluster` routes deterministically, keep legacy entries/clusters routes reachable during migration, and make raw clusters supporting evidence instead of the default identity model once RCL-004 projection data exists.

**Rationale:** The same raw data serves different business contexts. Context-specific read/write models reduce coupling and make the UI hierarchy align with the operator's concept of a person rather than a machine cluster (`literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:1857`, `literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:1870`).

**Done when:**

- Route parsing covers default, queue, person, face, and unresolved cluster routes.
- The default person workspace does not render until `person_uuid`, representative evidence, counts, and projection status exist.
- Assigned clusters link to the person workspace by `person_uuid`.
- Unassigned clusters open unresolved/queue evidence mode without inventing a person link.
- Existing Entries/Clusters compatibility routes remain reachable during migration.

### PREIMPL-008: Diagnostics and metrics name their source rows before promotion

**Trace:** Assessment P1 #9/#10; `E15-PREIMPL-SPEC-ANALYZE-03`; DASH-004; RCL-007  
**Priority:** P1  
**ADR gate:** Yes if a new cross-service diagnostic or metric authority is introduced.  
**Owner:** E15-19 Slice 5 for refresh/projection metrics; E15-20 Slice 4 for optional sync diagnostics.

Projection freshness, refresh queue depth, p95/p99 refresh latency, failure rate, recovery time, and label-to-visible-suggestion lead time must not become dashboard claims until the source rows and ownership are named.

**Rationale:** Monitoring should expose actionable runtime internals, not decorative numbers. Release It! calls for visible timeout, circuit-breaker, response-time, and resource-health signals (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:4560`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:11181`).

**Done when:**

- Each promoted metric has a named source table/event/repository and owning task.
- Projection freshness includes source version or rebuild timestamp.
- Local projection freshness and source-version exposure are covered before any reset behavior expands.
- Projection rebuild correctness tests cover the RCL-004 enriched roster-entry projection.
- E15-12/E15-13 reset behavior remains unchanged unless a planning-reviewed projection/read contract explicitly requires it.
- Aggregate metrics remain separate from per-event `SuggestionRefreshStatus`.
- Optional sync diagnostics are additive and only added after existing fields are rendered.

### PREIMPL-009: Controller use-case extraction stays bounded to changed behavior

**Trace:** Assessment P1 #8; `E15-PREIMPL-SPEC-ANALYZE-01`  
**Priority:** P1  
**ADR gate:** No for internal controller extraction; yes if an extraction changes cross-service ownership or payload contracts.  
**Owner:** E15-19 for roster write/projection/outbox controller seams; E15-20 for batch-run listing/projection acknowledgement and sync-controller helpers; E15-21 only when roster UI implementation touches the named controller-adjacent surfaces.

Large PHP controllers must not absorb more unrelated orchestration while E15 adds projection, activity, and diagnostics behavior. Extraction is required only where the implementing task already changes the behavior: `class-api.php` roster person write operations, roster review projection reads, and curation outbox enqueueing; `class-analysis-jobs-controller.php` batch-run listing and projection acknowledgement helpers; and `class-sync-status-controller.php` diagnostics assembled from named repository methods.

**Rationale:** Fowler's refactoring guidance supports small extractions that make the next change easy, not sweeping rewrites detached from behavior (`literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt:333`, `literature/extracted/refactoring/Refactoring-TypeScript_Keeping-your-code-healthy.txt:417`). The controller split is therefore a guardrail against growing mixed-purpose controllers during implementation, not an independent modernization campaign.

**Done when:**

- E15-19 moves RCL-004 projection assembly and curation outbox enqueueing out of the broad `class-api.php` path into named repository/mapper/use-case helpers.
- E15-20 adds durable recent activity through a narrow `BatchRunRepository`/controller helper instead of expanding by-ID controller methods into dashboard-specific branching.
- Optional E15-20 diagnostics come from named repository methods before `class-sync-status-controller.php` renders them.
- No task performs broad controller decomposition outside the behavior it owns.
- Tests cover the extracted use case through the same public API surface the UI or replay path uses.

---

## Implementation Tiers

### Tier 0 - Proof and contract gates

```text
PREIMPL-001  LocalWP smoke proof
PREIMPL-002  RCL-004 projection boundary
PREIMPL-003  Durable post-curation refresh
PREIMPL-004  Bounded suggestion refresh
```

Tier 0 is the work most likely to invalidate implementation proof or cross-service contracts if skipped. PREIMPL-002 and PREIMPL-003 are blocked on ADR-009 acceptance or conditional acceptance.

### Tier 1 - App-surface stabilization

```text
PREIMPL-005  Dashboard durable activity source/fallback decision
PREIMPL-006  Dashboard priority model
PREIMPL-007  Person-first roster route model
```

Tier 1 may include frontend-only route/model extraction, but user-visible rendering must not outrun the data contracts named above.

### Tier 2 - Diagnostics after source ownership

```text
PREIMPL-008  Metrics and diagnostics source ownership
PREIMPL-009  Bounded controller use-case extraction
```

Tier 2 should land only when source rows and owners are named. It is not a reason to delay Tier 0 proof and contract repair.

---

## Deferred or Rejected Directions

- Do not fold broad `apps/prototype-description-service` modularization into E15-19. Only bounded use-case extractions needed for event, refresh, and projection contracts are in scope.
- Do not create a second person write model for roster review. Review data remains derived from local person authority and recognition state.
- Do not use browser local storage as authoritative dashboard activity.
- Do not add sync diagnostic fields before existing `SyncStatusResponse` recency/topology fields have been rendered and tested.
- Do not let curriculum queues depend on frontend-only scans or hidden refresh fanout.
- Do not introduce new similarity-score semantics in the scrubber before E15-19 and [RCL-009](recognition-roster-curation-loop-spec.md#rcl-009-add-enhanced-score-evidence-after-refresh-contracts-land) supply those fields.
- Do not give the dashboard ownership of curriculum queues unless E15-19 explicitly assigns dashboard entry ownership.
- Do not remove legacy Entries/Clusters routes until person and unresolved cluster cases are covered by the new roster workspace.

---

## Validation Commands

Current-state audit commands:

```bash
rg -n "localwp-batch-run-smoke|eval-file|batch-run-smoke.php" apps/prototype-wp-alt-context/Makefile apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php
rg -n "get_roster_entries|commit_roster_cluster|cluster_person_bound" apps/prototype-wp-alt-context/src/api/class-api.php
rg -n "surface_for_newly_labeled_cluster|refresh_for_cluster|1000|SuggestionRefreshStatus" apps/prototype-description-service/recognition apps/prototype-description-service/roster
rg -n "useRecognitionJobHistory|localStorage|Recent Activity|BatchRunRepository" apps/prototype-wp-alt-context/js/admin apps/prototype-wp-alt-context/src
rg -n "class-api.php|class-analysis-jobs-controller.php|class-sync-status-controller.php|class-snapshot-projector.php|class-sync-state-repository.php" apps/prototype-wp-alt-context/src
rg -n "RosterPersonReview|roster-entry.schema|RCL-004|ADR-009" docs/specs docs/tasks/15.0 packages/shared-contracts/schemas
```

Implementation validation targets:

```bash
python3 -m pytest scripts/test_localwp_batch_smoke.py -q
cd apps/prototype-description-service && VIRTUAL_ENV= uv run --locked --extra dev python -m pytest recognition/tests roster
cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit tests/Integration
cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/__tests__/DashboardPage.test.tsx js/admin/pages/dashboard js/admin/hooks/__tests__/useRecognitionJobHistory.test.tsx js/admin/pages/roster
```

Manual/runtime validation targets:

```text
Run LocalWP smoke with explicit SMOKE_LIMIT=10 BATCH_SIZE=5 TIMEOUT_SECONDS=60 POLL_INTERVAL_MS=500 and verify the final payload reports those effective values.
Open http://localhost:10010/wp-admin/admin.php?page=alt-context-dashboard#/dashboard after a known batch run and verify Recent Activity is durable or explicitly browser-local fallback.
Open http://localhost:10010/wp-admin/admin.php?page=alt-context-roster#/roster and verify the default person workspace renders only when RCL-004 projection data exists.
```

---

## Downstream Artifact Guidance

- ADR required: ADR-009 must be accepted or conditionally accepted before PREIMPL-002/PREIMPL-003 implementation changes contracts.
- Task plans: E15-18 is the canonical PREIMPL-001 implementation plan and supersedes E15-14; E15-19 is the canonical PREIMPL-002/PREIMPL-003/PREIMPL-004 and roster-owned PREIMPL-008/PREIMPL-009 plan and supersedes E15-13; E15-20 is the canonical PREIMPL-005/PREIMPL-006 and dashboard-owned PREIMPL-008/PREIMPL-009 plan and supersedes E15-15 plus E15-16; E15-21 is the canonical PREIMPL-007 and roster-UI guardrail plan and supersedes E15-17. Record the superseding decision first, keep the displaced task on its documented lifecycle while its existing branch/worktree is still active, then retire it through the normal done/archive flow once that branch/worktree is actually closed.
- Specs to keep aligned: [recognition-roster-curation-loop-spec.md](recognition-roster-curation-loop-spec.md), [alt-context-dashboard-operator-triage-spec.md](alt-context-dashboard-operator-triage-spec.md), and [roster-management-person-review-scrub-ui-spec.md](roster-management-person-review-scrub-ui-spec.md).
- Findings closed by this artifact: `E15-PREIMPL-PLAN-01`, `E15-PREIMPL-PLAN-02`, `E15-PREIMPL-PLAN-03`, `E15-PREIMPL-PLAN-04`, `E15-PREIMPL-PLAN-05`, `E15-PREIMPL-SPEC-ANALYZE-01`, `E15-PREIMPL-SPEC-ANALYZE-02`, `E15-PREIMPL-SPEC-ANALYZE-03`, `E15-PREIMPL-SPEC-ANALYZE-04`, and `E15-PREIMPL-SPEC-ANALYZE-05`.
