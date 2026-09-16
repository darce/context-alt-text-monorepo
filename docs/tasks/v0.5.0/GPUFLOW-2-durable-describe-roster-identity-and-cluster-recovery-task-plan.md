# Task Plan — GPUFLOW-2

> **Metadata**
>
> - **Date**: 2026-09-16
> - **Author**: Claude Fable 5.1 (claude-fable-5-1)
> - **Owning Epic**: [E23 GPU Operator Control and Named Captions](../../epics/v0.5.0/gpu-operator-control-and-named-captions-epic.md)
> - **Epic Short ID**: GPUOPS
> - **Task ID**: `GPUFLOW-2`
> - **Target Branch**: `feature/gpuflow-2`
> - **Base SHA**: `ab9cee1d500fbf3b38b62d341842e1464e343a07`
> - **Revision**: 2 — revised after astra/high plan review run `gpuflow2-plan-review-02-p1` (findings `GPUFLOW-2-PLAN-R-01`…`R-11` in handoff; verdict fail). One local Claude review against the heuristics canon (semantic prior art + codemap, no second astra pass) precedes freeze.
> - **Review Coverage Target**: 1 adversarial plan review (codex-remote `gpt-6-astra`, effort `high`, against the heuristics canon) before any implementation lane is materialized; one review per committed delta afterwards.
> - **Prior art**: GPUFLOW-1 (typed cold-GPU envelope, demand lease, timing, deferred C4/D1/D2), FIR v11 `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` + `fir-executive-summary-20260728.md`, archived recognition 4.2.3 (`ClusterMerger.merge_similar`, `revert_merge`, `decide_representative_acceptance`, `GET /clusters/labels` typeahead), archived WP plugin (`ClusterConfirmationModal`, "Best match at %d%% similarity"), heuristics canon lexicons (`~/Development/heuristics-canon-research/lexicons/`).
> - **Carried findings** (bodies live in handoff, not here): `GPUFLOW1-FIN-01`, `GPUFLOW1-FIN-02`, `SVCCOL-M-04` (lint), `UXSCRE-M-05`/`UXSCRE-M-06`/`UXSCRE-M-07` (C4/D1/D2 deferrals).

## GPUFLOW-2. Durable describe operations, roster identity UX, and constrained cluster recovery

## Objective

An operator on demo.altcontext.com presses Suggest (or runs a bulk describe), navigates anywhere in the plugin, comes back, and still sees the same operation warming, then describing, then done — with descriptions actually arriving from the burst GPU. The People page reads as one surface: one heading, a large best-quality avatar per person, a row that opens that person's faces and media, a merge dialog that ranks survivors by match and undoes cleanly, and no "face groups" arithmetic. The same photograph of one person is never shown as three "Unnamed person" cards, and a stale failed sync operation never sits in the timeline forever.

## Problem Statement

Plugin 0.0.22 on the demo shows eleven live defects. Four causes explain them.

1. **The describe operation is not durable on the client, and the service cannot say why the GPU is absent.**
   - `useDescribeMedia.ts` keeps `leaseOperationIdRef`, `warmingStartedAtRef` and the retry timer in component refs (`:98-104`, `:185-191`); a route change unmounts the hook and the retry loop dies with no resume path. `useBulkDescribe.ts:77` derives `runId` from `useMutation` state, so remounting `MediaSelection` drops the chip to `data-gpu-state="unknown"` even though `activeDescribeRun.ts` (module singleton, no storage) still holds the run id for toasts and `GET /describe/run/{run_id}` would answer.
   - `/health/detailed` (`api/main.py:543-608`) reports `description_adapter` as the profile string captured once at startup (`:429`). It never asks `deps.get_gpu_description_adapter()` (`deps.py:91-119`), which fails closed to `UnavailableDescriptionAdapter` whenever `ACX_GPU_ENDPOINT_URL` is unset, non-private, or off the allowlist. Retention and the GPU chip therefore say "Backend unavailable" / "Could not reach the description service" with no named cause.
   - `_ensure_gpu_ready()` (`routers/describe.py:765-849`) returns `description_service_unavailable` for `UNKNOWN`/`DEGRADED` without a reason field, and the PHP open-circuit envelope (`class-abstract-recognition-proxy-controller.php:770-791`) carries neither `Retry-After` nor a reason (`GPUFLOW1-FIN-02`). The lifecycle start cycle already handles probe exhaustion: `probe.py:111-120` marks timed-out instances, `reaper.py:3066-3095` turns them into `readiness_timeout`/`readiness_stall` fallbacks, and `reaper.py:3280-3310` publishes `DEGRADED` with `_state_reason(...)` into `gpu-state.json`. The `reason` stops at the snapshot: the describe envelope never carries it, and whether the deployed unit runs this code is unknown until Slice 0 records the deployed `gpu_lifecycle` version and the last start-cycle journal.
   - The prior "controller only emits STOP" hypothesis is refuted: `GpuLifecycleController.start_needed_instances()` (`controller.py:71-97`), `OciCliStartActuator` (`reaper.py:404-455`) and `acx-gpu-start.timer` (`gpu-lifecycle-install.sh:275`) exist. The remaining live candidates are provisioning (OCI A10 quota defaults to 0, `infra/oci/GPU-BURST-PROVISIONING.md`), an unset/non-private endpoint on the API host, or a ready probe that never passes. Only live evidence separates these; the plan front-loads that evidence.
2. **Roster surfaces expose implementation arithmetic and hide the useful action.**
   - "People" renders four times (`RosterPage.tsx:198,201,210`; `RosterEntriesSection.tsx:375-377`).
   - Column 4 (`RosterEntriesTable.tsx:287-309`) shows `cluster_count` as a button that opens the person workspace; the count only matters for undoing a wrong merge, and undo is a 24 h banner that disappears on dismiss (`RosterEntriesSection.tsx:562-689`, `PersonMergeService::undo`).
   - Column 1 (`:264-283`) picks the avatar cluster by `identity_count` (`selectRepresentativeIdentity`, `:40-58`), not quality; the wire type carries no quality field, so the occluded Katy Perry face wins ties. The backend quality gate (`representative_selector.py:111-203`, `quality.py:25-119`) already computes confidence, bbox, sharpness and occlusion but weights occlusion by an adjustment coefficient that defaults to 0 (GPUFLOW-1 C4 deferred; calibration row not captured, `UXSCRE-M-05`).
   - `PersonMergeDialog.tsx:39-45` filters by substring and lists survivors in backend `name ASC`; `PersonMergePreview` has no similarity, although `ClusterMergeSuggestion.similarity` and the roster-candidates band already exist server-side.
   - The decorative control label ("Mark as decorative — screen readers will announce nothing", `MediaAltSuggest.tsx:100`) is a full sentence on a per-row button.
3. **Clustering leaves same-person residue and the client renders each residue as a person.** `run_singleton_hac_refinement` (`discovery_pipeline.py:699-822`) and the complete-link verification (`graph/verification.py`) split borderline members into singletons; `groupIdentitiesByClusters` (`identity-clusters/utils.ts:48-114`) then keys each unclustered identity as its own `identity:` group, so `emma_watson_14-scaled.jpeg` becomes three "Unnamed person" cards. FIR v11 verdicts: 512D is the ceiling, embedder retraining is not authorized, no numeric auto-merge threshold is declared, and the recommended remedy is a constrained recovery/merge pass requiring multiple independent exemplars plus a calibrated margin.
4. **Errors reach the operator raw, and failed sync rows never leave.** `resolveDescribeErrorMessage` (`describeApi.ts:1459-1470`) and `resolveWpErrorMessage` (`wpErrorMessage.ts:27-46`) return upstream `detail`/`message` verbatim ("invalid api key"). `OutboxMaintenanceService` purges only `ACKNOWLEDGED` rows (`class-outbox-maintenance-service.php:77-201`); `failed` rows (four "Cluster label update" rows from 2026-07-08) accumulate until an operator discards each one.

## Constraints

- **E23 hard constraints hold.** One writer per file (`gpu-state.json` lifecycle-owned; `gpu-intent.json`, `describe-load.json` service-owned). Cost backstop always wins. No agent actuates the live GPU; the live smoke is operator-run.
- **Provisioning is operator-owned.** OCI quota, Terraform apply and deployed env values are read by agents only through recorded evidence. No lane edits `infra/oci/*.tf` or deployed `.env` files.
- **Keep the public demo ceiling.** The 120 s client ceiling and the `_PUBLIC_RETRY_AFTER_CEILING` (120 s, matched by the PHP validator range `[1,120]`) are unchanged. Resume must never hold a PHP request open.
- **Pass boundaries through verbatim (rg-015).** PHP and SPA never synthesize state, tier, reason, similarity or quality. Every displayed reason/similarity/quality field comes from the service or a contract-documented fallback.
- **No client-side visual dedupe.** The SPA never groups identities by thumbnail or embedding; grouping is a server fact (GRPH-18, rg-015).
- **Thresholds are evidence-gated.** Any auto-merge, margin, occlusion coefficient or representative-quality weight changes only with the calibration artifact from Slice C1 (FIR D-08, D3 criterion). Embedder retraining is out of scope.
- **Greenfield rules apply.** Schema in `001_identity_schema.py`; no migrations, no shims.
- **Design tokens only (sr-004); centralized vocabularies (sr-007).** New reason codes and similarity bands are enums on every tier.
- **Lanes stay narrow.** 1–3 owned files plus tests; wide briefs exhaust the remote wall clock.
- **Routing (user order, 2026-09-16).** Implementation and grunt lanes: codex-remote `gpt-5.6-luna` effort `max`. Plan review and per-delta review twins: codex-remote `gpt-6-astra` effort `high`. No implementation on the local host; the local host integrates, runs tsc/vitest/phpunit on integrated worktrees, and performs the merge-gate harmonization.

## Workflow Principles

- **Evidence before lanes.** Slice 0 classifies the live GPU symptom into one of the named causes with recorded evidence. Provisioning causes go to the operator, not to a lane.
- **Resumable unit = (state, context) (GRPH-29).** The client persists the smallest pair needed to rehydrate — operation/run id plus start timestamp — never the derived UI state.
- **Silence is not success (OBS-08, RLSE-05).** Every unavailable state names its boundary and reason; every Retry/Refresh control shows that it acted (INT-01).
- **Partition plus verification, not threshold plus closure (GRPH-22).** Recovery merges require independent exemplars and a margin, and every automatic merge is reversible (INT-09).
- **Quality gates the pick (CAL-11).** A representative score that exists but does not select is decoration; the score selects, and it is re-derived when facts change (REF-09).
- **Same-rate reclaimer (RES-07).** Anything that accumulates ships with its purge in the same slice.
- **Plain operator language.** "Description Service", "Recognition Service", never "burst", "A10", "lease", "cluster_count".

## Terminology

- **Operation context**: versioned command, not just an id — `{version: 1, kind: 'suggest'|'run', id: operation_id|run_id, media_id?, startup_id?, started_at, request: {writeAlt: boolean, force: boolean}}` persisted client-side (sessionStorage, tenant-scoped key). A resumed Suggest replays the persisted `request` verbatim on the POST (the WP route defaults both flags to false, `class-describe-controller.php:168-178`); a resumed run only polls. A context whose `version` is unknown is discarded, never partially applied.
- **Unavailable reason**: enum on the `description_service_unavailable` envelope — `endpoint_unconfigured`, `endpoint_not_private`, `endpoint_resolution_pending`, `state_missing`, `state_stale`, `degraded`, `operator_stop`, `circuit_open`, `auth_rejected`. When the lifecycle snapshot carries its own `reason` (e.g. `readiness_timeout`), the envelope forwards it as `detail.lifecycle_reason` verbatim.
- **Adapter readiness**: block in `/health/detailed.description_adapter` — `{profile, kind, endpoint_configured, endpoint_allowlisted, endpoint_private, checked_at, fresh, usable, reason}`. `endpoint_configured`/`endpoint_allowlisted` are pure configuration reads; `endpoint_private` comes from a bounded, cached resolution (executor thread, 500 ms timeout, 60 s TTL) — the health handler never calls `socket.getaddrinfo` inline. `usable` is true only when `fresh` is true; a stalled or timed-out resolution yields `usable: false, reason: endpoint_resolution_pending`, never a stale "healthy".
- **Representative quality**: service-computed scalar in [0,1] per representative identity (`representative_quality`) with its components (`confidence`, `bbox_area`, `sharpness`, `occlusion_severity`) — the composite always ships with its parts (UXR-15). It is persisted on `identity_cluster_representatives`, exported in the cluster snapshot, stored by the WP projection, and read by the roster; no tier recomputes it.
- **Recovery merge**: post-clustering pass that attaches a residual singleton/small cluster to an existing cluster only when the *pairwise* admission rule holds for every moved member (see C2); anything short of that emits a merge suggestion. Numbers come only from the accepted C1 artifact.
- **Merge receipt**: one row in `cluster_merge_receipts` per merge (automatic or operator): `{receipt_id, survivor_cluster_id, source_cluster_id, source_label, moved_identity_ids, rule_version, kind: auto|operator, created_at, expires_at, reverted_at}`. Receipts for a survivor form an ordered stack; only the newest unreverted receipt is undoable (LIFO), and expired or reverted receipts are purged by the clustering run's own housekeeping step (same-rate reclaimer).
- **Calibration policy**: the accepted C1 artifact, expressed as a machine-readable block that seeds `settings/clustering.py`: per-stratum admission floors, FAR/FRR per stratum, the false-name acceptance gate, unsupported-stratum abstention, and the suggestion-band thresholds. Every lane that decides a merge, a band, or a representative reads this block; none invents a number.

## Current State Analysis

| Surface | Current behaviour | Anchor (main `ab9cee1d5`) |
| --- | --- | --- |
| Single Suggest lease | In-memory refs; cleared on unmount; 120 s ceiling | `js/admin/hooks/useDescribeMedia.ts:32,98-104,185-191` |
| Bulk run id | `useMutation` state; singleton only for toasts; no storage | `js/admin/hooks/useBulkDescribe.ts:65-105`, `hooks/activeDescribeRun.ts:1-50` |
| GPU chip | `data-gpu-state` from `progress.gpuState`; hidden when `runId===null` | `js/admin/pages/workbench/MediaSelection.tsx:560-564,761-818,864` |
| Service GPU gate | Reads `gpu-state.json`; UNKNOWN/DEGRADED → unavailable, no reason; STOPPED/STARTING/WARMING → starting + `dump_load_snapshot` | `scene/interface_adapters/http/routers/describe.py:765-849` |
| Health adapter field | Static profile string | `api/main.py:429,606`; `scene/interface_adapters/http/deps.py:65-119` |
| PHP open circuit | 503 `description_service_unavailable`, null ids, no Retry-After | `src/api/class-abstract-recognition-proxy-controller.php:770-791` |
| Lifecycle ready probe | Exhaustion → `readiness_timeout`/`readiness_stall` fallbacks → `DEGRADED` with `reason` in `gpu-state.json`; reason not forwarded past the snapshot | `infra/oci/gpu_lifecycle/probe.py:111-120`, `reaper.py:3066-3095,3280-3310`, `state_snapshot.py:233-257` |
| Cluster snapshot export | Emits `representative_thumb_path`, `representative_id`, `is_pinned`; no quality, media id, or merge receipt | `recognition/interface_adapters/http/routers/clusters_snapshot.py:80-120`; `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json` |
| WP projection ingest | Fixed column list on upsert; table from `dbDelta` in the lifecycle manager; mapper exposes the same list | `src/sovereign/repositories/class-cluster-snapshot-merger.php`, `class-clusters-repository.php:143`, `class-cluster-projection-writer.php:118-154`, `src/support/class-life-cycle-manager.php`, `src/sovereign/mappers/class-cluster-response-mapper.php` |
| Route registries | Explicit `include_router` list; explicit `require_once` + `register_routes` calls; no discovery | `recognition/interface_adapters/http/router.py:30-43`; `src/api/class-api.php:7-28,184-322` |
| Endpoint privacy check | Allowlisted hostnames resolve via synchronous `socket.getaddrinfo`, no timeout | `scene/interface_adapters/http/deps.py:46-86` |
| Retention panel | `isError || !available` → generic copy; Retry = `refetch()` with no fetching state | `js/admin/pages/RetentionPage.tsx:48-69`, `hooks/useRetentionStatus.ts:29-33` |
| GPU control chip | 15 s auto-poll; Refresh pre-empts the tick | `js/admin/pages/settings/GpuControlCard.tsx:149-154,214-266`, `settings/useGpuControl.ts:71-77` |
| Error copy | Upstream `detail.message` verbatim | `js/admin/api/describeApi.ts:1459-1470`, `js/admin/api/wpErrorMessage.ts:27-46` |
| Roster headings | h1 + subtitle + h2 + nested header h2 | `js/admin/pages/RosterPage.tsx:195-210`, `roster/RosterEntriesSection.tsx:375-377` |
| Roster row | col 1 opens workspace when person UUID present; col 4 same handler with `cluster_count` label | `js/admin/pages/roster/RosterEntriesTable.tsx:151,264-309` |
| Avatar choice | Largest cluster by `identity_count`, tie by `cluster_id` | `RosterEntriesTable.tsx:40-100` |
| Merge dialog | Substring filter; survivors in `name ASC` | `roster/PersonMergeDialog.tsx:39-45`, `src/sovereign/repositories/class-roster-entry-projection-repository.php:37` |
| Merge undo | 24 h token; banner TTL then gone | `src/api/services/class-person-merge-service.php:22,157-218`; `RosterEntriesSection.tsx:562-689` |
| Representative quality | `representative_quality_multiplier`, `_compute_identity_quality`; occlusion coefficient default 0 | `recognition/application/persistence/representative_selector.py:111-203`; `recognition/application/assignment/quality.py:25-119` |
| Recompute | `AssignmentWriter.recompute_representatives` (13 call sites) | `recognition/application/persistence/assignment_writer.py:567-653,821-827` |
| Singleton residue | HAC refinement + complete-link verify split borderline members | `recognition/application/orchestration/clustering/discovery_pipeline.py:699-822`; `recognition/application/discovery/graph/verification.py:13-65` |
| Merge suggestions | `MergeSuggestionService.generate_singleton_merge_suggestions`; `ClusterMergeSuggestion.similarity` | `recognition/application/suggestions/merge_suggestions.py:72-134,372-416`; `recognition/infrastructure/services/suggestion_extension_service.py:161-193` |
| Client grouping | `person:` → `cluster:` → `identity:` key fallback | `js/admin/pages/workbench/identity-clusters/utils.ts:48-114` |
| Outbox GC | Purges `ACKNOWLEDGED` only; failed rows manual | `src/sovereign/sync/class-outbox-maintenance-service.php:77-201,240-410` |
| Decorative control | Per-image post-meta `acx_alt_decorative`; sentence label | `js/admin/pages/workbench/MediaAltSuggest.tsx:100,240-243,1014-1029,1083-1098` |

## Target Outcome

- A Suggest or bulk run survives SPA navigation and a page reload: on mount the client rehydrates the operation context and resumes polling/retrying; the chip shows the live phase; descriptions arrive.
- `/health/detailed.description_adapter` says whether the GPU adapter is usable and why not. Retention and the GPU chip show that reason in operator language, and Retry/Refresh visibly act.
- The lifecycle `DEGRADED` reason that already lands in `gpu-state.json` reaches the operator: the describe envelope forwards it, and Slice 0 proves the deployed unit runs the code that writes it.
- People page: one heading; large best-quality avatar that re-selects as media arrives; row opens faces + media; merge dialog ranks survivors by match with typeahead; "Merged from N groups · Undo" appears only while undo is possible.
- The Emma Watson triple collapses server-side into one cluster (or one merge suggestion) with a merge receipt; the Perry/Trudeau mixed group is explained by the calibration artifact and, where a wrong-name risk exists, split into suggestions rather than silently joined. Two successive automatic merges into one survivor undo in LIFO order.
- Failed outbox rows older than the purge window are reclaimed automatically; the timeline shows age and a bulk discard.
- Errors map to operator copy; no upstream string is shown raw.

## Context Loading

- `docs/tasks/v0.5.0/GPUFLOW-1-description-service-flow-and-identity-fixes-task-plan.md` (A1 lease contract, C4/D1/D2 deferrals)
- `docs/workbay/contracts/gpu-lifecycle.md`, `packages/shared-contracts/schemas/scene-describe-multipart.schema.json`, `scene-describe-run.schema.json`, `roster-entry.schema.json`, `roster-candidates-response.schema.json`
- `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`, `benchmarks/reports/fir-executive-summary-20260728.md`, `benchmarks/reports/fir-issuedag-1-measurement-gates.md`
- `infra/oci/GPU-BURST-PROVISIONING.md`, `scripts/deploy/preflight-gpu-env.sh`, `scripts/deploy/gpu-lifecycle-install.sh`
- `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.uxmap.json`, `workbench-identity-chips.uxmap.json`, `describe-gpu-tier.uxmap.json`, `gpu-operator-control.uxmap.json`
- Heuristics canon rules cited per slice: GRPH-18/22/29/31/32/33/39, API-05/07/08, RES-01/02/06/07/15, RLSE-05, OBS-05/08, DIAG-07, INT-01/09, HAI-15, UXR-15, LAY-01, REF-09/25, STOR-07, FLOW-06, CAL-01/11.

## Contract and Boundary Impact

- `scene-describe-multipart.schema.json`: `description_service_unavailable` gains required `detail.reason` (enum above) and optional `detail.lifecycle_reason` (verbatim from the snapshot). Additive for `starting`.
- New `packages/shared-contracts/schemas/scene-health-detailed.schema.json` documenting the `description_adapter` readiness block including `checked_at`/`fresh`.
- `recognition-cluster-snapshot.schema.json`: `clusters[]` gains `representative_quality` (number|null), `quality_components` (object|null), `representative_media_id` (string|null), `undoable_merge_receipt_id` (string|null). This is the only path by which quality and undo availability reach WordPress; the WP projection stores exactly these four fields and nothing derived.
- `roster-entry.schema.json`: `clusters[].representative_identity` gains `representative_quality` and `quality_components`; `clusters[]` gains `representative_media_id` and `undoable_merge_receipt_id` — read from the projection columns, never computed in PHP (rg-015).
- New `roster-merge-candidates-response.schema.json`: for a loser person, ranked survivors `{person_id, name, similarity, band, shared_media_count}` computed from cluster centroids (`centroid_utils.compute_similarity`) and existing `ClusterMergeSuggestion` rows; `band` thresholds come from the calibration policy block. PHP proxies verbatim.
- `docs/workbay/contracts/gpu-lifecycle.md`: documents the existing `DEGRADED` + `reason` publication on probe exhaustion and the new forwarding rule into the describe envelope; `describe-load.json` unchanged.
- `docs/workbay/contracts/identity-merge.md` (new): `cluster_merge_receipts` table, LIFO revert semantics (`receipt_not_top` refusal), undo window `ACX_MERGE_UNDO_WINDOW_DAYS` (default 7), housekeeping purge, pairwise admission rule, and the merge-request `operator_initial_choice` field (HAI-15 audit).
- Recognition HTTP: `GET /recognition/persons/{id}/merge-candidates`, `POST /recognition/clusters/{id}/revert-merge` (body `{receipt_id}`), both mounted through `router.py` by an owning lane.
- WP REST: `GET acx/v1/roster/persons/{id}/media` (paged media via `IdentityMembersReadRepository`/`list_projected_cluster_rows_by_person`), `GET acx/v1/roster/persons/{id}/merge-candidates` (proxy), `POST acx/v1/workbench/clusters/{id}/revert-merge` (proxy); all three registered in `class-api.php` by an owning lane and asserted through the real `rest_api_init` bootstrap.

### Open decisions

- **Decorative control scope.** Recommendation: keep decorative per-image (post-meta invariant with non-empty alt) and add a selection-scoped bulk action in `MediaSelection` rather than a global config; a global "all images decorative" contradicts the alt/decorative exclusivity invariant. Operator confirms before B6 dispatch.
- **Auto-merge admission numbers and suggestion bands** come only from the accepted C1 policy block; C2 ships gated behind `ACX_RECOVERY_MERGE_ENABLED=false`, and B6's band lane does not dispatch until the policy is accepted by decision.
- **Merge dialog ordering (user ask vs HAI-15).** The user asked for `#merge-survivor` sorted by % match. The dialog delivers that at step 2: step 1 records the operator's own pick from an unranked, score-free, typeahead-filtered list; step 2 reveals the ranked list with scores and bands, highlighting the pick, and the operator confirms or changes. The initial pick is sent as `operator_initial_choice` and stored on the merge record.
- **Resume storage** is `sessionStorage` (tab-scoped, survives reload, cleared on tab close) rather than `localStorage`, to avoid resurrecting foreign tenants' operations in shared browsers.

## Proposed Solution

1. **Diagnose the live GPU (Slice 0).** Operator captures evidence; agent classifies cause; provisioning gaps go to an operator runbook checklist, code gaps to Slice A.
2. **Make unavailability legible (A1–A3).** Health reports adapter usability with bounded, fresh evidence; service and PHP envelopes carry `reason`, the lifecycle reason, and `Retry-After`; the existing lifecycle `DEGRADED` path is verified on the deployed unit before any infra change.
3. **Make the operation durable on the client (A4–A5).** Persist the versioned operation command (ids + request options); rehydrate on mount; resume polling or the typed retry loop with the same options; chip reads the live phase.
4. **Map every error to copy (A6–A7).** Reason → operator sentence with the named service and the next action; Retry/Refresh show activity and countdown.
5. **Roster surfaces (B1–B8).** One heading; representative quality produced by the service, exported in the snapshot, stored by the WP projection, read by the roster; large quality avatar; row opens faces + media; two-step merge dialog (own pick, then ranked reveal); undo affordance tied to undo availability; compact decorative control; every new route registered by an owning lane.
6. **Clustering (C0–C5).** Land the receipt/quality schema first; calibrate on the demo ground truth into a policy block; ship a gated pairwise recovery merge with receipts and LIFO revert; collapse client-side ungrouped residue into one "Not yet grouped" section instead of N cards.
7. **Outbox hygiene (D1–D2).** Bounded auto-retry for retryable failures, purge for terminal failures, timeline age + bulk discard.
8. **UX maps and release gate (E, R).**

## Files and Surfaces to Change

Paths beginning `scene/`, `recognition/`, `api/` or `db/` are under `apps/prototype-description-service/`; `src/` and `js/` are under `apps/prototype-wp-alt-context/`.

| Area | Files |
| --- | --- |
| Contracts | `packages/shared-contracts/schemas/scene-describe-multipart.schema.json`, `scene-health-detailed.schema.json` (new), `recognition-cluster-snapshot.schema.json`, `roster-entry.schema.json`, `roster-merge-candidates-response.schema.json` (new), `docs/workbay/contracts/gpu-lifecycle.md`, `docs/workbay/contracts/identity-merge.md` (new) |
| Service — describe | `scene/interface_adapters/http/routers/describe.py`, `scene/interface_adapters/http/schemas/responses.py`, `api/main.py` |
| Service — identity | `db/models/identity.py` (`cluster_merge_receipts`, representative quality columns), `db/migrations/versions/001_identity_schema.py`, `recognition/application/persistence/representative_selector.py`, `recognition/application/assignment/quality.py`, `recognition/application/settings/clustering.py`, `recognition/application/orchestration/clustering/recovery_merge.py` (new), `recognition/application/orchestration/clustering/discovery_pipeline.py`, `recognition/application/orchestration/cluster_merge.py`, `recognition/interface_adapters/http/routers/clusters_snapshot.py`, `recognition/interface_adapters/http/routers/person_merge_candidates.py` (new), `recognition/interface_adapters/http/routers/cluster_revert.py` (new), `recognition/interface_adapters/http/router.py` |
| Infra | `infra/oci/gpu_lifecycle/reaper.py`, `infra/oci/gpu_lifecycle/state_snapshot.py` — only if Slice 0 shows the deployed unit lacks the `DEGRADED`/`reason` path (A3 gate) |
| PHP | `src/api/class-abstract-recognition-proxy-controller.php`, `src/support/class-life-cycle-manager.php`, `src/sovereign/repositories/interface-clusters-repository.php`, `class-cluster-projection-writer.php`, `class-clusters-repository.php`, `class-cluster-snapshot-merger.php`, `src/sovereign/mappers/class-cluster-response-mapper.php`, `src/sovereign/repositories/class-roster-entry-projection-repository.php`, `src/api/class-person-media-controller.php` (new), `src/api/class-cluster-revert-controller.php` (new), `src/api/class-person-merge-controller.php`, `src/api/class-api.php`, `src/sovereign/sync/class-outbox-maintenance-service.php` |
| SPA — describe | `js/admin/hooks/activeDescribeRun.ts`, `js/admin/hooks/useBulkDescribe.ts`, `js/admin/hooks/describeOperationStore.ts` (new), `js/admin/hooks/useDescribeMedia.ts`, `js/admin/pages/workbench/MediaSelection.tsx`, `js/admin/api/describeApi.ts`, `js/admin/api/wpErrorMessage.ts`, `js/admin/api/errorCopy.ts` (new) |
| SPA — settings/retention | `js/admin/pages/settings/GpuControlCard.tsx`, `js/admin/pages/RetentionPage.tsx`, `js/admin/hooks/useRetentionStatus.ts` |
| SPA — roster | `js/admin/pages/RosterPage.tsx`, `js/admin/pages/roster/RosterEntriesSection.tsx`, `js/admin/pages/roster/RosterEntriesTable.tsx`, `js/admin/pages/roster/PersonMergeDialog.tsx`, `js/admin/pages/roster/PersonWorkspacePanel.tsx`, `js/admin/pages/roster/PersonMediaGrid.tsx` (new), `js/admin/api/personMergeApi.ts`, `js/admin/api/personMediaApi.ts` (new), `js/admin/api/generated/roster-entry.ts` |
| SPA — workbench | `js/admin/pages/workbench/MediaAltSuggest.tsx`, `js/admin/pages/workbench/identity-clusters/utils.ts`, `identity-clusters/IdentityClusterList.tsx`, `js/admin/pages/workbench/DeadLetterPanel.tsx` |
| UX maps | `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.{uxmap.json,md}`, `describe-gpu-tier.*`, `gpu-operator-control.*`, `workbench-identity-chips.*` |
| Assessments | `docs/assessments/GPUFLOW-2-gpu-online-diagnosis-20260916.md` (new), `docs/assessments/GPUFLOW-2-cluster-recovery-calibration-20260916.md` (new) |

## Verification Strategy

- Service: pytest per lane (exact commands in the lane table), run in the lane's VM sandbox `.venv` for DB-backed suites; contract example documents validated by `test_shared_schema_documents.py`. Route registration is proven through the real app: `TestClient(create_app())` route table contains the new paths (not a per-file `include_router` in the test).
- Health: a stalled-resolver stub (executor function that sleeps 5 s) must yield a `/health/detailed` response in < 1 s with `usable: false, reason: endpoint_resolution_pending`; a fresh cached result yields `usable: true`; an expired cache yields `fresh: false, usable: false`.
- Infra: `python3 -m pytest infra/oci/gpu_lifecycle/tests -q -p no:cacheprovider`; A3 runs only if Slice 0 shows the deployed unit does not publish `DEGRADED`/`reason` on exhaustion.
- PHP: `vendor/bin/phpunit` filtered suites per lane; runtime autoload parity check (rg-016) for each new controller; route registration proven through `rest_api_init` → `rest_get_server()->get_routes()` containing the three new routes (extends `ApiBootstrapSyncTest` pattern).
- Projection propagation: a PHPUnit test feeds a snapshot fixture carrying `representative_quality`/`representative_media_id`/`undoable_merge_receipt_id` through `ClusterSnapshotMerger` → `ClustersRepository` → the projection table → `RosterEntryProjectionRepository`, asserting the roster row carries the same values and that a pre-export snapshot (fields absent) yields nulls, never fabricated values.
- SPA: `npx vitest run` per lane; a jsdom reload test that seeds `sessionStorage`, mounts `MediaSelection`, and asserts one `GET /describe/run/{id}` before any mutation; a fake-timer test that unmounts `useDescribeMedia` mid-warm, remounts, and asserts the retry POST reuses the persisted `operation_id` **and** the persisted `writeAlt`/`force` for each of the four option combinations, with the resulting alt persistence asserted for `writeAlt=true`.
- Calibration: the C1 artifact contains pair precision/recall and FAR/FRR on the labelled demo set per quality stratum (CAL-01), per-stratum admission floors, an explicit abstention list for strata with fewer than the declared minimum labelled pairs, the false-name acceptance gate, the suggestion-band thresholds, and the occlusion coefficient — as a machine-readable policy block. Acceptance is a handoff decision; a stratum missing its floor fails acceptance regardless of the aggregate.
- Recovery merge: fixtures replay the C1 ground truth plus a mixed-unnamed residual (two people in one residual) and a borderline chain; assertions are pair-level — every moved member individually passes against ≥ k distinct-media destination exemplars, the residual is internally coherent, and the mixed residual is abstained (suggestion), never attached. Two successive merges into one survivor undo LIFO; reverting a non-top receipt is refused; expired receipts are purged by the housekeeping step.
- Operator smoke (release gate): cold Suggest → navigate → return → description; bulk run reload; People page walkthrough; merge + undo; outbox purge count in `/sync/health`.
- Aggregate: `make check-all` on the integrated branch; `handoff_close_check(enforce=True)`.

## Slice Delivery

### Slice 0: Live GPU diagnosis (operator + read-only agent)

**Goal**: The "GPU never comes online" symptom is classified into one named cause with evidence, before any GPU lane runs.

Changes:

- Operator captures, in order: OCI instance list for `acx_gpu_burst` and the A10 service-limit value; the deployed `gpu_lifecycle` version (`git -C <install> rev-parse HEAD` or the package stamp) and whether `reaper.py` on the host contains the `readiness_timeout` fallback path; `systemctl status acx-gpu-start.timer acx-gpu-reap.timer` plus the last two start-cycle journal excerpts; `/run/acx/gpu-state.json` (state **and** `reason`) and `/run/acx-write/<env>/describe-load.json` before and 30 s after one Suggest; `ACX_GPU_ENDPOINT_URL` presence and `preflight-gpu-env.sh` exit code on the API host; `/health/detailed` body; the WP transient circuit key state; the outbox `failed` row count by age.
- Agent lane (luna max, read-only against evidence) writes `docs/assessments/GPUFLOW-2-gpu-online-diagnosis-20260916.md`: cause classification (provisioning / endpoint env / ready probe / breaker / stale lifecycle deploy / snapshot publication failure), a trace of the deployed timeout → fallback → `DEGRADED` → snapshot path with the journal lines that prove or refute it, the Katy Perry representative row (identity id, `representative_quality`, occlusion score, media id) and the Emma Watson triple (identity ids, embeddings' pairwise cosine, refinement decision), and the Perry/Trudeau mixed group membership.
- The assessment sets `a3_required: true|false`. A3 dispatches only when true.
- Provisioning or env causes produce an operator checklist appended to the assessment; they are not lane work.

Proof: assessment committed; handoff decision references it; Slice A dispatch gate reads the cause field.

### Slice A1: Adapter readiness in health (backend)

**Goal**: `/health/detailed.description_adapter` says whether the GPU adapter is usable and why.

Changes: `api/main.py` replaces the static profile echo with a readiness block. Configuration fields (`endpoint_configured`, `endpoint_allowlisted` via the pure `_hostname_matches_allowlist`, profile/kind) are computed per request. `endpoint_private` is never resolved inline: an `EndpointPrivacyCache` in `api/main.py` runs `_resolved_addresses_are_private` in the default executor under `asyncio.wait_for(..., 0.5)` at most once per 60 s and stores `{value, checked_at}`; the handler reads the cache, sets `fresh` from the TTL, and reports `usable` only when `fresh` and every configuration field passes. Timeout or `gaierror` leaves the last value with `fresh: false` (or null with `reason: endpoint_resolution_pending` when there is none). `deps.py` is untouched. New `scene-health-detailed.schema.json` example. Test `scene/tests/test_health_detailed_adapter.py` (new) covers unset, non-private, allowlisted-fresh, allowlisted-stale, CPU-profile, and stalled-resolver cases.

Proof: schema example validates; six readiness cases pinned; stalled resolver → response < 1 s and `usable: false`.

### Slice A2: Unavailable reason on the describe envelope (backend)

**Goal**: Every `description_service_unavailable` response names why.

Changes: `responses.py` adds `UnavailableReason` StrEnum and the field; `routers/describe.py::_ensure_gpu_ready` maps missing/stale snapshot, DEGRADED, operator STOP and unconfigured endpoint to reasons and forwards the snapshot's own `reason` as `detail.lifecycle_reason` verbatim; `GpuRemoteAdapterError` after ready keeps `502 description_service_error`. Contract example updated. Lint deferral `SVCCOL-M-04` fixed here.

Proof: route tests assert reason per state and `lifecycle_reason` passthrough for a `DEGRADED`/`readiness_timeout` snapshot; multipart schema example round-trips.

### Slice A3: Ready-probe exhaustion reason on the deployed unit (infra, evidence-gated)

**Goal**: The `DEGRADED` + `reason` that `reaper.py:3280-3310` already publishes on `readiness_timeout`/`readiness_stall` is proven to run on the deployed host; code changes only where Slice 0 shows a gap.

Changes: none by default. The `contracts-service` lane documents the existing transition in `gpu-lifecycle.md`. If the assessment sets `a3_required: true` (deployed unit older than the fallback path, or `reason` dropped between `_state_reason` and the written snapshot), `infra-ready-degrade` fixes exactly the named gap in `reaper.py`/`state_snapshot.py` with a fake-clock test reproducing the recorded journal.

Proof: assessment trace; when dispatched, the reproducing test passes and `test_state_snapshot_contract.py` still passes.

### Slice A4: Durable operation context and run resume (SPA)

**Goal**: A bulk run survives navigation and reload.

Changes: new `describeOperationStore.ts` (sessionStorage-backed `(state, context)` pair, tenant-keyed, `useSyncExternalStore`); `activeDescribeRun.ts` delegates to it; `useBulkDescribe.ts` derives `runId` from the store, not mutation state, and clears it on terminal status; `MediaSelection.tsx` `isRunRelevant` reads the store. `GpuTierStatus` shows `data-gpu-state` from the run's `gpu_state` and, while resuming, "Checking a run that was already in progress…".

Proof: reload test (seeded storage → one status GET → chip visible); terminal status clears storage; foreign-tenant key ignored.

### Slice A5: Suggest lease resume (SPA)

**Goal**: A single-image Suggest mid-warm survives remount.

Changes: `useDescribeMedia.ts` persists the full versioned command `{version, kind: 'suggest', media_id, operation_id, startup_id, warming_started_at, request: {writeAlt, force}}` through the store on the first `starting` response, taking `writeAlt`/`force` from the same arguments `describeMedia` sends (`useDescribeMedia.ts:15-43,65-79`); on mount with a matching media id, resumes the retry loop honouring `Retry-After` and the remaining ceiling from the persisted start, and replays `request` verbatim on the POST. `clearLease()` also clears storage. An unknown `version` is discarded. Resolves `GPUFLOW1-FIN-01` correlation by reusing the persisted `operation_id` on manual retry.

Proof: fake-timer unmount/remount test table over `{writeAlt, force} ∈ {false,true}²` asserts the resumed POST carries the persisted `operation_id` and the same flags, and that `writeAlt=true` ends in the alt-persistence mutation; ceiling computed from persisted start, not remount time.

### Slice A6: Open-circuit Retry-After and reason (PHP)

**Goal**: `GPUFLOW1-FIN-02` closed; circuit-open is distinguishable from service-unavailable.

Changes: `open_circuit_response()` sets `Retry-After` to the remaining open window and `detail.reason: circuit_open`; passthrough of upstream `detail.reason` verbatim; `RecognitionProxyRetryPolicyTest` extended.

Proof: PHPUnit asserts header and reason; existing warming validation unchanged.

### Slice A7: Error copy map and service status controls (SPA)

**Goal**: No raw upstream string; Retry/Refresh visibly act.

Changes: new `errorCopy.ts` maps `{http_status, code, reason}` → operator sentence naming the service and the next step (401/403 → "The Recognition Service rejected this site's API key. Check Settings → Service API key."); `describeApi.ts`/`wpErrorMessage.ts` route through it and fall back to a generic sentence, never `detail.message`. `RetentionPage.tsx` shows the named service, the reason, `isFetching` state and "Last checked HH:MM"; `GpuControlCard.tsx` replaces the redundant Refresh with "Checking again in N s · Check now" (resets the poll timer) and renders `reason`.

Proof: vitest table over all reasons; no test fixture message string appears in rendered output; countdown resets on click.

### Slice B1: One "People" heading (SPA)

Changes: `RosterPage.tsx` keeps the `h1`; subtitle rewritten without repeating the noun as a label; the page `h2` removed; `RosterEntriesSection.tsx` header becomes "Named people (N)" with the count from the entries query. UX map `roster-people` regenerated.

Proof: `RosterPage.test.tsx` asserts exactly one accessible heading named "People"; render_ux_maps `--check` passes.

### Slice B2: Representative quality travels service → snapshot → WP projection → roster (schema + backend + PHP)

Three producers, in order, each a separate lane; no tier fabricates a value (rg-015).

- **B2a service export** (`svc-rep-export`): `clusters_snapshot.py::_build_cluster_responses` emits `representative_quality`, `quality_components`, `representative_media_id` from the persisted representative row (columns landed by C0) and `undoable_merge_receipt_id` from the newest unreverted, unexpired receipt; `recognition-cluster-snapshot.schema.json` example updated by `contracts-roster`.
- **B2b WP storage** (`php-projection-schema`): `class-life-cycle-manager.php` adds the four columns to the projection table via `dbDelta`; `interface-clusters-repository.php` + `class-cluster-projection-writer.php::upsert_projection_cluster` accept and persist them (null when absent from the snapshot). Rows written before the export lands stay null until the next snapshot replay; the bootstrap/targeted sync (`ApiBootstrapSyncTest` path) is the replay, and no backfill is invented.
- **B2c WP ingest + read** (`php-projection-ingest`, then `php-roster-projection`): `class-cluster-snapshot-merger.php` and `class-clusters-repository.php` pass the fields from the snapshot payload to the writer; `class-cluster-response-mapper.php` exposes them to the workbench; `class-roster-entry-projection-repository.php` reads the columns into `roster-entry.schema.json` shape; `roster-entry.ts` regenerated.

Proof: snapshot schema example validates; projection-propagation PHPUnit test (Verification Strategy) passes for present and absent fields; `RosterEntryProjectionRepositoryTest` covers null and non-null rows; generated type diff reviewed.

### Slice B3: Roster row — large quality avatar, working row action, undo-only count (SPA)

Changes: `RosterEntriesTable.tsx` selects the representative by `representative_quality` (fallback: current `identity_count` rule when null, with no quality claim rendered); avatar size token `--acx-avatar-lg`; column 1 opens the person workspace and is disabled with a tooltip only when no person UUID exists; column 4 shows "Merged from N groups · Undo" only while `merge.undoAvailable` (token unexpired) and nothing otherwise.

Proof: `RosterEntriesTable.clickthrough.test.tsx` extended; undo cell hidden after token expiry.

### Slice B4: Person media endpoint (PHP)

Changes: new `class-person-media-controller.php` `GET acx/v1/roster/persons/{id}/media?offset&limit` backed by `IdentityMembersReadRepository`/`list_projected_cluster_rows_by_person`; pagination metadata from the query, not `count()` (rg-015). Registration is **not** in this lane: `php-route-registry` adds the `require_once` and the `register_routes` call in `class-api.php` after every new PHP controller has landed (B4, B6 proxy, C3 revert proxy), and proves each route through the real `rest_api_init` bootstrap (rg-016).

Proof: PHPUnit for paging, unknown person 404, tenant scoping; autoload runtime check; `ApiRouteRegistryTest` (owned by `php-route-registry`) lists all three routes from `rest_get_server()->get_routes()`.

### Slice B5: Person workspace shows media (SPA)

Changes: new `personMediaApi.ts` + `PersonMediaGrid.tsx` (infinite query, thumbnails link to the media item, "Suggest for this image" deep link); `PersonWorkspacePanel.tsx` adds a "Media" tab beside faces.

Proof: `PersonWorkspacePanel.test.tsx` asserts grid renders pages and empty state.

### Slice B6: Ranked merge candidates (backend + PHP + SPA)

Changes: recognition route file `routers/person_merge_candidates.py` `GET /recognition/persons/{id}/merge-candidates` ranks other persons by centroid cosine (`centroid_utils.compute_similarity`) merged with pending `ClusterMergeSuggestion` similarity, returns `{similarity, band, shared_media_count}` with `band` cut from the accepted calibration policy block in `settings/clustering.py` (no literal thresholds in the route); `svc-route-registry` mounts it in `router.py`. PHP proxy in `class-person-merge-controller.php`, which also accepts `operator_initial_choice` on the merge POST and stores it on the merge record. `PersonMergeDialog.tsx` is two-step (HAI-15): **step 1** shows `#merge-survivor` as an unranked, score-free list in `name ASC`, filtered by `#merge-search` typeahead, and requires a pick; the pick is committed to dialog state and sent as `operator_initial_choice`. **Step 2** (only after the pick) fetches candidates and re-renders `#merge-survivor` sorted by similarity desc (name asc within band) with labels "Name — 87% match (likely)" from `similarityCopy.ts`, highlighting the operator's pick and, when it differs from the top candidate, showing both; the operator confirms or changes, and the merge request carries both `operator_initial_choice` and the final survivor.

Proof: service unit test on ranking and band cuts read from the policy block; PHPUnit passthrough and `operator_initial_choice` persistence; vitest asserts no score, band, or similarity ordering is rendered or fetched before a pick, that step 2 ordering is by similarity, and that both choices are in the submitted payload.

### Slice B7: Compact decorative control (SPA)

Changes: `MediaAltSuggest.tsx` renders an icon toggle labelled "Decorative" with the full sentence as tooltip/`aria-describedby`; pressed state uses tokens; no width change to the suggestion column (LAY-01). Bulk "Mark selected decorative" is a stretch item pending the open decision.

Proof: `MediaAltSuggest.test.tsx` asserts accessible name and description; snapshot of row width.

### Slice C0: Merge receipts and representative quality schema (backend)

Changes: `db/models/identity.py` + `001_identity_schema.py` add the `cluster_merge_receipts` table (Terminology) and `representative_quality` (Float, nullable) + `quality_components` (JSONB, nullable) on `identity_cluster_representatives`; ORM relationships `IdentityCluster.merge_receipts` (ordered by `created_at` desc). New `recognition/tests/unit/test_identity_schema_receipts.py` asserts the columns, the ordering, and that reverting a non-top receipt is impossible at the repository layer. Greenfield: no migration.

Proof: schema test passes; `001_identity_schema.py` is the only migration touched.

### Slice C1: Cluster recovery calibration (analysis lane)

Changes: `docs/assessments/GPUFLOW-2-cluster-recovery-calibration-20260916.md`: labelled demo ground truth (Watson ×3, Perry, Trudeau, press group), pairwise cosine matrix, refinement/verification decisions per pair, and per quality stratum: pair precision/recall, FAR/FRR, labelled-pair count, and the admission floor. The artifact ends in a machine-readable **calibration policy block** (`τ_pair`, `τ_intra`, margin δ, k ≥ 2, per-stratum floors, abstained strata with fewer than `min_pairs` labelled pairs, false-name acceptance gate, suggestion-band cuts, occlusion coefficient `k_occ`, quality weights) with the Katy Perry row as the representative acceptance example. Acceptance fails if any non-abstained stratum lacks a floor or exceeds the false-name gate, regardless of the aggregate (CAL-01, CAL-11).

Proof: numeric report with the policy block; handoff decision accepts or rejects it; `svc-recovery-merge`, `svc-merge-candidates` and `svc-rep-quality` dispatch only after acceptance and copy the block into `settings/clustering.py` verbatim.

### Slice C2: Pairwise recovery merge with receipts (backend)

Changes: new `recovery_merge.py` runs after `run_singleton_hac_refinement`. For each residual singleton/small cluster R and candidate destination D (by centroid cosine): admit only if (i) every member of R individually has cosine ≥ `τ_pair` to ≥ k destination exemplars from k distinct source media, (ii) R is internally coherent (all intra-R pairs ≥ `τ_intra`), (iii) the runner-up destination's best pairwise score trails by ≥ δ for every member, (iv) neither R nor D is bound to a different named person, and (v) the member's quality stratum is not abstained. Any member failing any clause → the whole residual is abstained and a merge suggestion is emitted via `MergeSuggestionService`; there is no partial move. On admission it writes one `cluster_merge_receipts` row (`kind: auto`, `rule_version`, `expires_at = now + ACX_MERGE_UNDO_WINDOW_DAYS`) and, as the run's last step, purges reverted or expired receipts (RES-07). Feature-flagged `ACX_RECOVERY_MERGE_ENABLED` in `settings/clustering.py`; defaults off until C1 is accepted.

Proof: fixture replay from C1; mixed-unnamed residual (Perry+Trudeau members in one residual) is abstained with a pair-level assertion naming the failing member; borderline chain is abstained; no merge across two named persons; two runs merging two residuals into one survivor produce two receipts; expired receipts purged; flag off → no-op.

### Slice C3: LIFO revert and undo surface (backend + PHP + SPA)

Changes: `cluster_merge.py` gains `revert_merge(receipt_id)`: refuses with `receipt_not_top` unless the receipt is the survivor's newest unreverted one, refuses with `receipt_expired` past `expires_at`, otherwise restores `moved_identity_ids` to a cluster labelled `source_label` or "<name> (restored)" (4.2.3 semantics) and sets `reverted_at`. New route file `routers/cluster_revert.py` `POST /recognition/clusters/{id}/revert-merge` (mounted by `svc-route-registry`); new `class-cluster-revert-controller.php` proxies it (registered by `php-route-registry`); `IdentityClusterItem` shows "Merged automatically · Undo" only while the projected `undoable_merge_receipt_id` is non-null (arrives through B2's snapshot → projection path) and calls the proxy with that id.

Proof: revert test restores the exact prior partition; two successive merges undo in LIFO order and the non-top revert is refused; UI test toggles on `undoable_merge_receipt_id` and submits the receipt id.

### Slice C4: Quality-aware representatives, re-selected on new media (backend)

Changes (GPUFLOW-1 C4 carried, gated on C1): `quality.py` composite = geometric mean(confidence, bbox term with `min_bbox_area`) × (1 − occlusion_severity·k_occ) × sharpness term; `representative_selector.py` selects by composite; `assignment_writer.recompute_representatives` invoked on every new identity for the cluster (already 13 call sites; add the ingest path if missing); the five C4 contract tests updated deliberately.

Proof: Katy Perry row from Slice 0 no longer wins; five C4 tests pass with recorded new expectations.

### Slice C5: Ungrouped residue section (SPA)

Changes: `utils.ts` returns `identity:`-keyed groups under a single `ungrouped` bucket; `IdentityClusterList.tsx` renders "Not yet grouped (N)" once, with the faces inside, never N "Unnamed person" cards. No visual dedupe.

Proof: `utils.test.ts` and `IdentityClusterList.test.tsx` with the Watson fixture.

### Slice D1: Outbox reclaimer (PHP)

Changes: `class-outbox-maintenance-service.php` purge pass also deletes `failed` rows with `retryable=false` older than `acx_sync_purge_failed_days` (default 7) and auto-retries `retryable=true` rows with exponential backoff up to `acx_sync_max_auto_attempts` (default 3) before marking terminal; counts emitted in `/sync/health` (OBS-05).

Proof: `OutboxMaintenanceServicePurgeTest` covers both branches and the health counters.

### Slice D2: Timeline age and bulk discard (SPA)

Changes: `DeadLetterPanel.tsx` shows age per failed row, "Will not retry" for terminal rows, and "Discard failed older than 7 days".

Proof: `DeadLetterPanel.test.tsx`.

### Slice E: UX maps

Each map lane owns its `.uxmap.json` + `.md` pair and consumes final UI fixtures; `render_ux_maps.py --check` must pass (no extra H2 under Screens).

### Slice R: Release gate

Integrated branch `make check-all`; operator smoke per Verification Strategy; local codex harmonizing review against the canon; `handoff_close_check(enforce=True)`; plugin zip via `make deploy-demo`.

## Lane Decomposition (Multi-Agent)

Routing (user order 2026-09-16): implementation and analysis lanes codex-remote `gpt-5.6-luna` effort `max`; plan review and per-delta review twins codex-remote `gpt-6-astra` effort `high`. Export `WORKBAY_CODEX_MODEL` to the lane's model before subprocess import; no tier/speed fields on lane rows. Freeze this plan after the astra review and the one local Claude canon review before materializing (GRPH-39). Local host integrates and harmonizes only.

### Lanes

Path conventions and the lane-root Python resolution rules from the GPUFLOW-1 plan apply unchanged. Each lane owns at most three source/artifact files plus its tests. In every dependency cell the prefix names the producer and the row is the read-only consumer (GRPH-32: an edge exists only where a named artifact moves).

| Lane ID | Slice | Owned Paths | Upstream Dependencies (artifact transferred) | Required Tests |
| --- | --- | --- | --- | --- |
| `diagnosis` | 0 | `docs/assessments/GPUFLOW-2-gpu-online-diagnosis-20260916.md` (new) | — (operator evidence gate) | `python3 -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` |
| `contracts-service` | A1/A2/A3 | `packages/shared-contracts/schemas/scene-describe-multipart.schema.json`, `packages/shared-contracts/schemas/scene-health-detailed.schema.json` (new), `docs/workbay/contracts/gpu-lifecycle.md` | diagnosis: assessment | `python3 -m pytest apps/prototype-description-service/scene/tests/test_shared_schema_documents.py -q -p no:cacheprovider` |
| `contracts-roster` | B2/B6/C3 | `packages/shared-contracts/schemas/roster-entry.schema.json`, `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json`, `packages/shared-contracts/schemas/roster-merge-candidates-response.schema.json` (new), `docs/workbay/contracts/identity-merge.md` (new) | diagnosis: assessment | `python3 -m pytest apps/prototype-description-service/scene/tests/test_shared_schema_documents.py -q -p no:cacheprovider` |
| `svc-health-adapter` | A1 | `api/main.py`; `apps/prototype-description-service/scene/tests/test_health_detailed_adapter.py` (new test) | contracts-service: `scene-health-detailed.schema.json` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_health_detailed_adapter.py -q -p no:cacheprovider` |
| `svc-unavailable-reason` | A2 | `scene/interface_adapters/http/routers/describe.py`, `scene/interface_adapters/http/schemas/responses.py`, `apps/prototype-description-service/scene/tests/fixtures/gpuflow2-unavailable.json` (new test fixture) | contracts-service: `scene-describe-multipart.schema.json` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_describe_route.py apps/prototype-description-service/scene/tests/test_describe_eligibility.py apps/prototype-description-service/scene/tests/test_shared_schema_multipart.py -q -p no:cacheprovider` |
| `infra-ready-degrade` | A3 (gated on `a3_required: true`) | `infra/oci/gpu_lifecycle/reaper.py`, `infra/oci/gpu_lifecycle/state_snapshot.py` | diagnosis: assessment (`a3_required`, named gap); contracts-service: `docs/workbay/contracts/gpu-lifecycle.md` | `python3 -m pytest infra/oci/gpu_lifecycle/tests/test_start_actuator.py infra/oci/gpu_lifecycle/tests/test_state_snapshot.py infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q -p no:cacheprovider` |
| `php-circuit-reason` | A6 | `src/api/class-abstract-recognition-proxy-controller.php`, `apps/prototype-wp-alt-context/src/api/tests/fixtures/gpuflow2-unavailable-wire.json` (new test fixture) | svc-unavailable-reason: `scene/tests/fixtures/gpuflow2-unavailable.json` | vendor/bin/phpunit --filter "RecognitionProxyRetryPolicy\|Proxy" |
| `spa-error-copy` | A7 | `js/admin/api/errorCopy.ts` (new), `js/admin/api/describeApi.ts`, `js/admin/api/wpErrorMessage.ts` | php-circuit-reason: `src/api/tests/fixtures/gpuflow2-unavailable-wire.json` | npx vitest run js/admin/api/__tests__/describeApi.test.ts js/admin/api/__tests__/wpErrorMessage.test.ts |
| `spa-service-status` | A7 | `js/admin/pages/settings/GpuControlCard.tsx`, `js/admin/pages/RetentionPage.tsx`, `js/admin/hooks/useRetentionStatus.ts` | spa-error-copy: `js/admin/api/errorCopy.ts` | npx vitest run js/admin/pages/settings js/admin/pages/__tests__/RetentionPage.test.tsx |
| `spa-operation-store` | A4 | `js/admin/hooks/describeOperationStore.ts` (new), `js/admin/hooks/activeDescribeRun.ts`, `js/admin/hooks/useBulkDescribe.ts` | contracts-service: `scene-describe-multipart.schema.json` (read-only, resume contract) | npx vitest run js/admin/hooks/__tests__/useBulkDescribe.test.tsx js/admin/hooks/__tests__/describeOperationStore.test.ts |
| `spa-run-resume-chip` | A4 | `js/admin/pages/workbench/MediaSelection.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/fixtures/gpuflow2-resume.json` (new test fixture) | spa-operation-store: `js/admin/hooks/describeOperationStore.ts` | npx vitest run js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx js/admin/pages/workbench/__tests__/MediaSelection.resume.test.tsx |
| `spa-suggest-resume` | A5 | `js/admin/hooks/useDescribeMedia.ts` | spa-operation-store: `js/admin/hooks/describeOperationStore.ts`; spa-error-copy: `js/admin/api/describeApi.ts` | npx vitest run js/admin/hooks/__tests__/useDescribeMedia.test.tsx |
| `spa-roster-headings` | B1 | `js/admin/pages/RosterPage.tsx`, `js/admin/pages/roster/RosterEntriesSection.tsx` | diagnosis: assessment | npx vitest run js/admin/pages/__tests__/RosterPage.test.tsx js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx |
| `svc-identity-schema` | C0 | `db/models/identity.py`, `db/migrations/versions/001_identity_schema.py`; `apps/prototype-description-service/recognition/tests/unit/test_identity_schema_receipts.py` (new test) | contracts-roster: `docs/workbay/contracts/identity-merge.md` | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_identity_schema_receipts.py -q -p no:cacheprovider` |
| `svc-rep-export` | B2a | `recognition/interface_adapters/http/routers/clusters_snapshot.py`; `apps/prototype-description-service/recognition/tests/unit/test_clusters_snapshot_quality_export.py` (new test) | svc-identity-schema: `db/models/identity.py` (receipt + quality columns); contracts-roster: `recognition-cluster-snapshot.schema.json` | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_clusters_snapshot_quality_export.py apps/prototype-description-service/recognition/tests/unit/test_curation_sync_router.py -q -p no:cacheprovider` |
| `php-projection-schema` | B2b | `src/support/class-life-cycle-manager.php`, `src/sovereign/repositories/interface-clusters-repository.php`, `src/sovereign/repositories/class-cluster-projection-writer.php` | contracts-roster: `recognition-cluster-snapshot.schema.json` | vendor/bin/phpunit --filter "ClusterProjectionWriter\|LifeCycleManager" |
| `php-projection-ingest` | B2c | `src/sovereign/sync/class-cluster-snapshot-merger.php`, `src/sovereign/repositories/class-clusters-repository.php`, `src/sovereign/mappers/class-cluster-response-mapper.php`; `apps/prototype-wp-alt-context/tests/Unit/ClusterProjectionQualityPropagationTest.php` (new test) | php-projection-schema: `class-cluster-projection-writer.php`; svc-rep-export: `recognition/tests/unit/test_clusters_snapshot_quality_export.py` (wire shape) | vendor/bin/phpunit --filter "ClusterProjectionQualityPropagation\|ClusterSnapshotMerger\|ApiBootstrapSync" |
| `php-roster-projection` | B2c | `src/sovereign/repositories/class-roster-entry-projection-repository.php`, `js/admin/api/generated/roster-entry.ts` | contracts-roster: `roster-entry.schema.json`; php-projection-ingest: `tests/Unit/ClusterProjectionQualityPropagationTest.php` (columns populated) | vendor/bin/phpunit --filter RosterEntryProjectionRepository |
| `spa-roster-table` | B3 | `js/admin/pages/roster/RosterEntriesTable.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/roster/__tests__/fixtures/gpuflow2-roster-rows.json` (new test fixture) | php-roster-projection: `js/admin/api/generated/roster-entry.ts` | npx vitest run js/admin/pages/roster/__tests__/RosterEntriesTable.clickthrough.test.tsx js/admin/pages/roster/__tests__/RosterEntriesTable.reservedLabel.test.tsx |
| `php-person-media` | B4 | `src/api/class-person-media-controller.php` (new), `apps/prototype-wp-alt-context/tests/Unit/PersonMediaControllerTest.php` (new test) | contracts-roster: `roster-entry.schema.json` | vendor/bin/phpunit --filter PersonMediaController |
| `spa-person-media` | B5 | `js/admin/api/personMediaApi.ts` (new), `js/admin/pages/roster/PersonMediaGrid.tsx` (new), `js/admin/pages/roster/PersonWorkspacePanel.tsx` | php-person-media: `tests/Unit/PersonMediaControllerTest.php` (wire shape); php-route-registry: `tests/Unit/ApiRouteRegistryTest.php` (route mounted) | npx vitest run js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx |
| `svc-merge-candidates` | B6 | `recognition/interface_adapters/http/routers/person_merge_candidates.py` (new), `recognition/application/suggestions/merge_candidates.py` (new); `apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py` (new test) | contracts-roster: `roster-merge-candidates-response.schema.json`; calibration: policy block (band cuts) | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py -q -p no:cacheprovider` |
| `svc-route-registry` | B6/C3 | `recognition/interface_adapters/http/router.py`; `apps/prototype-description-service/recognition/tests/unit/test_recognition_route_table.py` (new test) | svc-merge-candidates: `routers/person_merge_candidates.py`; svc-merge-revert: `routers/cluster_revert.py` | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_recognition_route_table.py -q -p no:cacheprovider` |
| `php-merge-candidates` | B6 | `src/api/class-person-merge-controller.php` | svc-merge-candidates: `recognition/tests/unit/test_merge_candidates.py` (wire shape); svc-route-registry: `test_recognition_route_table.py` (route mounted) | vendor/bin/phpunit --filter PersonMergeController |
| `php-cluster-revert` | C3 | `src/api/class-cluster-revert-controller.php` (new); `apps/prototype-wp-alt-context/tests/Unit/ClusterRevertControllerTest.php` (new test) | svc-merge-revert: `recognition/tests/unit/test_cluster_merge_revert.py` (wire shape); svc-route-registry: `test_recognition_route_table.py` (route mounted) | vendor/bin/phpunit --filter ClusterRevertController |
| `php-route-registry` | B4/B6/C3 | `src/api/class-api.php`; `apps/prototype-wp-alt-context/tests/Unit/ApiRouteRegistryTest.php` (new test) | php-person-media: `class-person-media-controller.php`; php-merge-candidates: `class-person-merge-controller.php`; php-cluster-revert: `class-cluster-revert-controller.php` | vendor/bin/phpunit --filter "ApiRouteRegistry\|ApiBootstrapSync" |
| `spa-merge-dialog` | B6 | `js/admin/pages/roster/PersonMergeDialog.tsx`, `js/admin/api/personMergeApi.ts` | php-merge-candidates: `src/api/class-person-merge-controller.php`; php-route-registry: `tests/Unit/ApiRouteRegistryTest.php` (route mounted) | npx vitest run js/admin/pages/roster/__tests__/PersonMergeDialog.test.tsx js/admin/api/__tests__/personMergeApi.test.ts |
| `spa-decorative-control` | B7 | `js/admin/pages/workbench/MediaAltSuggest.tsx` | diagnosis: assessment (operator decision recorded) | npx vitest run js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx |
| `calibration` | C1 | `docs/assessments/GPUFLOW-2-cluster-recovery-calibration-20260916.md` (new) | diagnosis: assessment | numeric calibration report review |
| `svc-recovery-merge` | C2 | `recognition/application/orchestration/clustering/recovery_merge.py` (new), `recognition/application/orchestration/clustering/discovery_pipeline.py`, `recognition/application/settings/clustering.py`; `apps/prototype-description-service/recognition/tests/unit/test_recovery_merge.py` (new test) | calibration: policy block (accepted); svc-identity-schema: `db/models/identity.py` (`cluster_merge_receipts`); contracts-roster: `docs/workbay/contracts/identity-merge.md` | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_recovery_merge.py apps/prototype-description-service/recognition/tests/unit/test_merge_suggestions.py -q -p no:cacheprovider` |
| `svc-merge-revert` | C3 | `recognition/application/orchestration/cluster_merge.py`, `recognition/interface_adapters/http/routers/cluster_revert.py` (new); `apps/prototype-description-service/recognition/tests/unit/test_cluster_merge_revert.py` (new test) | svc-identity-schema: `db/models/identity.py` (`cluster_merge_receipts`); contracts-roster: `docs/workbay/contracts/identity-merge.md` | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_cluster_merge_revert.py -q -p no:cacheprovider` |
| `svc-rep-quality` | C4 | `recognition/application/assignment/quality.py`, `recognition/application/persistence/representative_selector.py` | calibration: policy block (accepted; `k_occ`, weights); svc-identity-schema: `db/models/identity.py` (quality columns) | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_representative_quality_gate.py apps/prototype-description-service/recognition/tests/unit/test_representative_selector.py apps/prototype-description-service/recognition/tests/unit/test_fir2_br_postmerge_contracts.py apps/prototype-description-service/recognition/tests/unit/test_fir_final_postmerge_runtime_contracts.py apps/prototype-description-service/recognition/tests/unit/test_identity_quality.py -q -p no:cacheprovider` |
| `svc-rep-recompute` | C4 | `recognition/application/persistence/assignment_writer.py` | svc-rep-quality: `representative_selector.py` | `python3 -m pytest apps/prototype-description-service/recognition/tests/integration/test_assignment_writer.py -q -p no:cacheprovider` |
| `spa-cluster-ungrouped` | C5 | `js/admin/pages/workbench/identity-clusters/utils.ts`, `js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx` | diagnosis: assessment | npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx |
| `spa-cluster-undo` | C3 | `js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx`, `js/admin/api/clusterRevertApi.ts` (new) | contracts-roster: `docs/workbay/contracts/identity-merge.md` (read-only); php-projection-ingest: `class-cluster-response-mapper.php` (`undoable_merge_receipt_id` on the wire); php-cluster-revert: `tests/Unit/ClusterRevertControllerTest.php` (wire shape); php-route-registry: `tests/Unit/ApiRouteRegistryTest.php` (route mounted) | npx vitest run js/admin/pages/workbench/identity-clusters js/admin/api/__tests__/clusterRevertApi.test.ts |
| `php-outbox-reclaimer` | D1 | `src/sovereign/sync/class-outbox-maintenance-service.php` | — | vendor/bin/phpunit --filter "OutboxMaintenanceService" |
| `spa-deadletter` | D2 | `js/admin/pages/workbench/DeadLetterPanel.tsx` | php-outbox-reclaimer: `class-outbox-maintenance-service.php` (health counters) | npx vitest run js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx |
| `ux-roster` | E | `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.uxmap.json`, `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.md` | spa-roster-table: `gpuflow2-roster-rows.json` | render_ux_maps.py --check |
| `ux-describe` | E | `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.json`, `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.md` | spa-run-resume-chip: `gpuflow2-resume.json` | render_ux_maps.py --check |
| `ux-service` | E | `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.uxmap.json`, `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md` | spa-service-status: `GpuControlCard.tsx` | render_ux_maps.py --check |
| `ux-identity` | E | `apps/prototype-wp-alt-context/docs/ux-maps/workbench-identity-chips.uxmap.json`, `apps/prototype-wp-alt-context/docs/ux-maps/workbench-identity-chips.md` | spa-cluster-ungrouped: `IdentityClusterList.tsx` | render_ux_maps.py --check |

Every implementation lane has one astra high review twin (`lane_kind: review`) per committed delta; only high findings block; lints are low and deferred per sr-011. Missing operator evidence, an unaccepted calibration rule, or the undecided decorative scope are dispatch gates even with no finding attached.

### Collision map

- `routers/describe.py` and `responses.py` are owned only by `svc-unavailable-reason`; `api/main.py` only by `svc-health-adapter`. No GPU lane touches `deps.py`.
- `class-abstract-recognition-proxy-controller.php` is owned only by `php-circuit-reason`; `class-person-merge-controller.php` only by `php-merge-candidates`.
- `MediaSelection.tsx` is owned only by `spa-run-resume-chip`; `useDescribeMedia.ts` only by `spa-suggest-resume`; both consume the committed store file read-only.
- `RosterEntriesSection.tsx` belongs to `spa-roster-headings`; `RosterEntriesTable.tsx` to `spa-roster-table`; `PersonWorkspacePanel.tsx` to `spa-person-media`; `PersonMergeDialog.tsx` to `spa-merge-dialog`. None overlap.
- `representative_selector.py`/`quality.py` belong to `svc-rep-quality`; `assignment_writer.py` to `svc-rep-recompute`; `discovery_pipeline.py` and `settings/clustering.py` to `svc-recovery-merge`; `cluster_merge.py` and `routers/cluster_revert.py` to `svc-merge-revert`; `clusters_snapshot.py` to `svc-rep-export`. Schema edits in `001_identity_schema.py`/`db/models/identity.py` happen only in `svc-identity-schema`.
- Route registries have exactly one writer each: `recognition/interface_adapters/http/router.py` → `svc-route-registry`; `src/api/class-api.php` → `php-route-registry`. Handler lanes never touch them.
- WP projection storage and ingest are split by layer: `class-life-cycle-manager.php`, `interface-clusters-repository.php`, `class-cluster-projection-writer.php` → `php-projection-schema`; `class-cluster-snapshot-merger.php`, `class-clusters-repository.php`, `class-cluster-response-mapper.php` → `php-projection-ingest`; `class-roster-entry-projection-repository.php` → `php-roster-projection`.
- `svc-merge-candidates`, `svc-recovery-merge` and `svc-rep-quality` copy the accepted policy block into `settings/clustering.py` through `svc-recovery-merge`'s ownership: the other two read the constants; only `svc-recovery-merge` writes the file.
- Each UX lane owns its JSON+MD pair; component lanes never edit maps.
- `lane_dag` validates producer/path/consumer edges before dispatch; shared directories create no edges.

### Merge Order

1. Gate 0: astra high plan review and the local Claude canon review recorded; plan frozen; operator evidence captured; `diagnosis` lane lands. Cause classification decides whether Slice A lanes run at all (provisioning/env causes route to the operator checklist first) and whether `infra-ready-degrade` dispatches (`a3_required`).
2. Wave 1 (parallel, GRPH-31 longest chains first): `contracts-service`, `contracts-roster`, `calibration`, `spa-roster-headings`, `spa-cluster-ungrouped`, `php-outbox-reclaimer`, `spa-decorative-control` (after the operator decision).
3. Wave 2: `svc-health-adapter`, `svc-unavailable-reason`, `spa-operation-store` after `contracts-service`; `infra-ready-degrade` only when gated in; `svc-identity-schema`, `php-projection-schema`, `php-person-media` after `contracts-roster`; `svc-merge-candidates` after `contracts-roster` and accepted `calibration`; `svc-rep-quality` after accepted `calibration` and `svc-identity-schema`; `spa-deadletter` after the reclaimer.
4. Wave 3: `php-circuit-reason` after `svc-unavailable-reason`; `spa-run-resume-chip` after the store; `svc-rep-export`, `svc-recovery-merge`, `svc-merge-revert` after `svc-identity-schema`; `php-merge-candidates` after `svc-merge-candidates`; `svc-rep-recompute` after `svc-rep-quality`.
5. Wave 4: `spa-error-copy` after `php-circuit-reason`; `php-projection-ingest` after `php-projection-schema` and `svc-rep-export`; `svc-route-registry` after `svc-merge-candidates` and `svc-merge-revert`; `php-cluster-revert` after `svc-merge-revert` and `svc-route-registry`.
6. Wave 5: `spa-service-status` and `spa-suggest-resume` after `spa-error-copy`; `php-roster-projection` after `php-projection-ingest`; `php-route-registry` after `php-person-media`, `php-merge-candidates`, `php-cluster-revert`.
7. Wave 6: `spa-roster-table` after `php-roster-projection`; `spa-person-media`, `spa-merge-dialog`, `spa-cluster-undo` after `php-route-registry`.
8. Wave 7: UX map lanes after their fixtures.
9. Release gate R.

Critical path: `contracts-roster → svc-identity-schema → svc-merge-revert → svc-route-registry → php-cluster-revert → php-route-registry → spa-cluster-undo → ux-identity`. Integrate continuously into `feature/gpuflow-2`; retire each worktree once its commit and evidence are preserved; `main` receives one final merge.

### Manifest

```bash
make lane-manifest-init TASK=GPUFLOW-2 LANE_IDS='diagnosis contracts-service contracts-roster svc-health-adapter svc-unavailable-reason infra-ready-degrade php-circuit-reason spa-error-copy spa-service-status spa-operation-store spa-run-resume-chip spa-suggest-resume spa-roster-headings svc-identity-schema svc-rep-export php-projection-schema php-projection-ingest php-roster-projection spa-roster-table php-person-media spa-person-media svc-merge-candidates svc-route-registry php-merge-candidates php-cluster-revert php-route-registry spa-merge-dialog spa-decorative-control calibration svc-recovery-merge svc-merge-revert svc-rep-quality svc-rep-recompute spa-cluster-ungrouped spa-cluster-undo php-outbox-reclaimer spa-deadletter ux-roster ux-describe ux-service ux-identity' TASK_PLAN=docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md
```

Only after both reviews and the freeze: materialize, re-pin `config/lane-orchestration/GPUFLOW-2.json` to `gpt-5.6-luna`/`max` for implementation lanes and `gpt-6-astra`/`high` for review twins (materialize rewrites pins), verify row/model/effort match, validate with `lane_dag`, and reject any unresolved test path before dispatch.

### Orchestration Mode

- Remote: `run_offload_pass` from a ROOT subprocess, one lane per detached process, staggered ≥ 60 s behind the breaker; refresh each lane branch from `feature/gpuflow-2` before dispatch; every brief inlines the semantic reinjection packet and codemap snippets for its owned symbols; review briefs embed the diff inline (history-stripped sandbox) and forbid whole-file reads.
- Local: integration, tsc/vitest/phpunit on integrated worktrees, harmonizing merge-gate review. No local implementation. No agent runs live Suggest/run/Start/Stop or deployment.

## Highest-Leverage Next Items (not in this wave)

| Item | Why deferred |
| --- | --- |
| CPU-provisional degrade (PA-03, `docs/scopes/gpu-detailed-tier-oci-bursty-scope.md`) | Needs Slice 0 cause and A3 loud DEGRADED first |
| Bulk "Mark selected decorative" in `MediaSelection` | Open decision; `MediaSelection.tsx` already owned by A4 |
| Quality-adaptive suggestion margin | Needs C1 strata evidence |
| VM retention hygiene (`docs/tech-debt/OPS-1-vm-host-retention-hygiene.md`) | Operator-owned |
| GPUFLOW-1 highs on `scripts/deploy/recognition-service.sh` (`GPUFLO-H-01/02`) | Deploy-script scope, separate task |

## Consolidated Checklist

### Context and Ownership

- [ ] Astra high plan review and one local Claude canon review recorded as review runs with findings in handoff; plan frozen
- [ ] Operator evidence captured (incl. deployed `gpu_lifecycle` version); `diagnosis` assessment committed with `a3_required`; cause recorded as a handoff decision
- [ ] Decorative scope decision recorded
- [ ] Manifest materialized, re-pinned, `lane_dag` valid

### Slice A

- [ ] Health readiness block with schema example, six cases, bounded cached resolution (< 1 s under a stalled resolver)
- [ ] Unavailable `reason` + `lifecycle_reason` on service and PHP envelopes; `Retry-After` on circuit-open
- [ ] Deployed lifecycle DEGRADED path traced; `infra-ready-degrade` run only if `a3_required`
- [ ] Operation store with versioned `request` options; run and Suggest resume tests over four flag combos; chip reads live phase
- [ ] Error copy map; retention and GPU chip show reason, activity and countdown

### Slice B

- [ ] One "People" heading; UX map parity
- [ ] Representative quality exported by the snapshot, stored and ingested by the WP projection, read by the roster; large quality avatar; row opens workspace; undo-only count
- [ ] Person media endpoint and grid; route registered in `class-api.php` and asserted through `rest_api_init`
- [ ] Two-step merge dialog: unranked pick recorded as `operator_initial_choice`, then ranked reveal; bands from the policy block; service route mounted in `router.py`
- [ ] Compact decorative control

### Slice C

- [ ] Receipts + quality schema landed in `001_identity_schema.py` with its test
- [ ] Calibration policy block accepted or rejected by decision (per-stratum floors, FAR/FRR, abstention, false-name gate, bands)
- [ ] Pairwise recovery merge writing receipts; LIFO revert with `receipt_not_top`; expiry purge; undo surface keyed on `undoable_merge_receipt_id`
- [ ] Quality-aware representative selection with recompute on ingest; five C4 tests updated deliberately
- [ ] Ungrouped residue section

### Slice D and E

- [ ] Outbox reclaimer and health counters; timeline age and bulk discard
- [ ] Four UX maps regenerated with `--check` passing

### Release gate

- [ ] Every delta reviewed once; zero open highs; lints deferred to a named next wave
- [ ] Operator smoke recorded; `make check-all`; `handoff_close_check(enforce=True)`; slice-complete decision

## Review Readiness

- Adversarial plan review (astra high, run `gpuflow2-plan-review-02-p1`) inlined this plan, the canon rule IDs in Context Loading, the FIR verdicts, and the Slice 0 evidence list; findings `GPUFLOW-2-PLAN-R-NN` are in handoff and drove Revision 2.
- One local Claude review follows (no second astra pass, user order 2026-09-16): prior art via `find_related_prior_work`/`semantic_reinjection_packet` against the handoff DB and archived recognition repos, code anchors via the codemap (`search_graph`/`get_code_snippet`/`trace_path`), rules from the canon lexicons. Findings are recorded under `GPUFLOW-2-PLAN-L-NN`; highs block the freeze; a freeze decision closes the gate.

## Stretch Goals

- Bulk decorative action; `localStorage` cross-tab resume with tenant fencing; per-stratum FAR/FRR dashboard in `/sync/health`.

## Success Criteria

- Cold Suggest → navigate → return → description arrives, with the chip never showing `unknown` while a run exists.
- `/health/detailed` explains any absent adapter; Retention and GPU controls name the cause and visibly act.
- People page passes the walkthrough: one heading, quality avatar fed from the snapshot (not computed in PHP), row action, unranked pick then ranked merge, undo.
- Watson triple resolved server-side; no automatic merge across two named people; no residual member moved without its own pairwise support; every automatic merge reversible in LIFO order within the undo window.
- Failed outbox rows reclaimed within the purge window; no raw upstream error string rendered.
