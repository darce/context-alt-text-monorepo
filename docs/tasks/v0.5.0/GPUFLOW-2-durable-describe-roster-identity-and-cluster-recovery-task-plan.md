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
   - `_ensure_gpu_ready()` (`routers/describe.py:765-849`) returns `description_service_unavailable` for `UNKNOWN`/`DEGRADED` without a reason field, and the PHP open-circuit envelope (`class-abstract-recognition-proxy-controller.php:770-791`) carries neither `Retry-After` nor a reason (`GPUFLOW1-FIN-02`). The lifecycle start cycle (`reaper.py`, `--ready-max-cycles 30 × --ready-sleep-seconds 10`) can leave `gpu-state.json` at `STARTING`/`WARMING` indefinitely when the ready probe never succeeds; nothing transitions to a loud `DEGRADED`.
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

- **Operation context**: `{kind: 'suggest'|'run', id: operation_id|run_id, media_id?, started_at}` persisted client-side (sessionStorage, tenant-scoped key) so a remount resumes polling or the typed retry loop.
- **Unavailable reason**: enum on the `description_service_unavailable` envelope — `endpoint_unconfigured`, `endpoint_not_private`, `state_missing`, `state_stale`, `degraded`, `operator_stop`, `circuit_open`, `auth_rejected`.
- **Adapter readiness**: live block in `/health/detailed.description_adapter` — `{profile, kind, endpoint_configured, endpoint_private, usable, reason}`.
- **Representative quality**: service-computed scalar in [0,1] per representative identity (`representative_quality`) with its components (`confidence`, `bbox_area`, `sharpness`, `occlusion_severity`) — the composite always ships with its parts (UXR-15).
- **Recovery merge**: post-clustering pass that attaches a residual singleton/small cluster to an existing cluster only when ≥ 2 independent exemplars (distinct source media) agree above a calibrated similarity with a calibrated margin over the runner-up; otherwise it emits a merge suggestion.
- **Merged-from**: `moved_identity_ids` recorded per merge (automatic or operator) so `revert_merge` restores the prior partition.

## Current State Analysis

| Surface | Current behaviour | Anchor (main `ab9cee1d5`) |
| --- | --- | --- |
| Single Suggest lease | In-memory refs; cleared on unmount; 120 s ceiling | `js/admin/hooks/useDescribeMedia.ts:32,98-104,185-191` |
| Bulk run id | `useMutation` state; singleton only for toasts; no storage | `js/admin/hooks/useBulkDescribe.ts:65-105`, `hooks/activeDescribeRun.ts:1-50` |
| GPU chip | `data-gpu-state` from `progress.gpuState`; hidden when `runId===null` | `js/admin/pages/workbench/MediaSelection.tsx:560-564,761-818,864` |
| Service GPU gate | Reads `gpu-state.json`; UNKNOWN/DEGRADED → unavailable, no reason; STOPPED/STARTING/WARMING → starting + `dump_load_snapshot` | `scene/interface_adapters/http/routers/describe.py:765-849` |
| Health adapter field | Static profile string | `api/main.py:429,606`; `scene/interface_adapters/http/deps.py:65-119` |
| PHP open circuit | 503 `description_service_unavailable`, null ids, no Retry-After | `src/api/class-abstract-recognition-proxy-controller.php:770-791` |
| Lifecycle ready probe | `STARTING/WARMING` until probe passes; no DEGRADED transition on exhaustion | `infra/oci/gpu_lifecycle/reaper.py` (`HttpReadinessProbe`, `run_start_cycle`), `state_snapshot.py:233-257` |
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
- The lifecycle unit reaches a loud `DEGRADED` (with reason) when the ready probe exhausts its budget, and the service's unavailable envelope carries `reason` end-to-end.
- People page: one heading; large best-quality avatar that re-selects as media arrives; row opens faces + media; merge dialog ranks survivors by match with typeahead; "Merged from N groups · Undo" appears only while undo is possible.
- The Emma Watson triple collapses server-side into one cluster (or one merge suggestion) with recorded `merged_from`; the Perry/Trudeau mixed group is explained by the calibration artifact and, where a wrong-name risk exists, split into suggestions rather than silently joined.
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

- `scene-describe-multipart.schema.json`: `description_service_unavailable` gains required `detail.reason` (enum above). Additive for `starting`.
- New `packages/shared-contracts/schemas/scene-health-detailed.schema.json` documenting the `description_adapter` readiness block.
- `roster-entry.schema.json`: `clusters[].representative_identity` gains `representative_quality` (number|null) and `quality_components` (object|null); `clusters[]` gains `representative_media_id`.
- New `roster-merge-candidates-response.schema.json`: for a loser person, ranked survivors `{person_id, name, similarity, band, shared_media_count}` computed from cluster centroids (`centroid_utils.compute_similarity`) and existing `ClusterMergeSuggestion` rows. PHP proxies verbatim.
- `docs/workbay/contracts/gpu-lifecycle.md`: `DEGRADED` transition on ready-probe exhaustion with `reason`; `describe-load.json` unchanged.
- `docs/workbay/contracts/identity-merge.md` (new): `moved_identity_ids`, `revert_merge` semantics, automatic-merge admission rule.
- WP REST: `GET acx/v1/roster/persons/{id}/media` (paged media linked to a person via `IdentityMembersReadRepository`/`list_projected_cluster_rows_by_person`), `GET acx/v1/roster/persons/{id}/merge-candidates` (proxy).

### Open decisions

- **Decorative control scope.** Recommendation: keep decorative per-image (post-meta invariant with non-empty alt) and add a selection-scoped bulk action in `MediaSelection` rather than a global config; a global "all images decorative" contradicts the alt/decorative exclusivity invariant. Operator confirms before B6 dispatch.
- **Auto-merge admission numbers** come only from C1; C2 ships with the pass gated behind `ACX_RECOVERY_MERGE_ENABLED=false` until C1 lands.
- **Resume storage** is `sessionStorage` (tab-scoped, survives reload, cleared on tab close) rather than `localStorage`, to avoid resurrecting foreign tenants' operations in shared browsers.

## Proposed Solution

1. **Diagnose the live GPU (Slice 0).** Operator captures evidence; agent classifies cause; provisioning gaps go to an operator runbook checklist, code gaps to Slice A.
2. **Make unavailability legible (A1–A3).** Health reports adapter usability; service and PHP envelopes carry `reason` and `Retry-After`; lifecycle degrades loudly.
3. **Make the operation durable on the client (A4–A5).** Persist operation context; rehydrate on mount; resume polling or the typed retry loop; chip reads the live phase.
4. **Map every error to copy (A6–A7).** Reason → operator sentence with the named service and the next action; Retry/Refresh show activity and countdown.
5. **Roster surfaces (B1–B7).** One heading; quality-driven large avatar from the service; row opens faces + media; merge dialog with ranked survivors and typeahead; undo affordance tied to undo availability; compact decorative control.
6. **Clustering (C1–C4).** Calibrate on the demo ground truth; ship a gated constrained recovery merge with `merged_from` and revert; collapse client-side ungrouped residue into one "Not yet grouped" section instead of N cards.
7. **Outbox hygiene (D1–D2).** Bounded auto-retry for retryable failures, purge for terminal failures, timeline age + bulk discard.
8. **UX maps and release gate (E, R).**

## Files and Surfaces to Change

Paths beginning `scene/`, `recognition/`, `api/` or `db/` are under `apps/prototype-description-service/`; `src/` and `js/` are under `apps/prototype-wp-alt-context/`.

| Area | Files |
| --- | --- |
| Contracts | `packages/shared-contracts/schemas/scene-describe-multipart.schema.json`, `scene-health-detailed.schema.json` (new), `roster-entry.schema.json`, `roster-merge-candidates-response.schema.json` (new), `docs/workbay/contracts/gpu-lifecycle.md`, `docs/workbay/contracts/identity-merge.md` (new) |
| Service — describe | `scene/interface_adapters/http/routers/describe.py`, `scene/interface_adapters/http/schemas/responses.py`, `api/main.py` |
| Service — identity | `recognition/application/persistence/representative_selector.py`, `recognition/application/assignment/quality.py`, `recognition/application/settings/clustering.py`, `recognition/application/orchestration/clustering/recovery_merge.py` (new), `recognition/application/orchestration/clustering/discovery_pipeline.py`, `recognition/application/orchestration/cluster_merge.py`, `recognition/interface_adapters/http/routers/` merge-candidates route (new file), `db/models/identity.py` (`merged_from` column), `db/migrations/versions/001_identity_schema.py` |
| Infra | `infra/oci/gpu_lifecycle/reaper.py`, `infra/oci/gpu_lifecycle/state_snapshot.py` |
| PHP | `src/api/class-abstract-recognition-proxy-controller.php`, `src/sovereign/repositories/class-roster-entry-projection-repository.php`, `src/api/class-person-media-controller.php` (new), `src/api/class-person-merge-controller.php`, `src/sovereign/sync/class-outbox-maintenance-service.php` |
| SPA — describe | `js/admin/hooks/activeDescribeRun.ts`, `js/admin/hooks/useBulkDescribe.ts`, `js/admin/hooks/describeOperationStore.ts` (new), `js/admin/hooks/useDescribeMedia.ts`, `js/admin/pages/workbench/MediaSelection.tsx`, `js/admin/api/describeApi.ts`, `js/admin/api/wpErrorMessage.ts`, `js/admin/api/errorCopy.ts` (new) |
| SPA — settings/retention | `js/admin/pages/settings/GpuControlCard.tsx`, `js/admin/pages/RetentionPage.tsx`, `js/admin/hooks/useRetentionStatus.ts` |
| SPA — roster | `js/admin/pages/RosterPage.tsx`, `js/admin/pages/roster/RosterEntriesSection.tsx`, `js/admin/pages/roster/RosterEntriesTable.tsx`, `js/admin/pages/roster/PersonMergeDialog.tsx`, `js/admin/pages/roster/PersonWorkspacePanel.tsx`, `js/admin/pages/roster/PersonMediaGrid.tsx` (new), `js/admin/api/personMergeApi.ts`, `js/admin/api/personMediaApi.ts` (new), `js/admin/api/generated/roster-entry.ts` |
| SPA — workbench | `js/admin/pages/workbench/MediaAltSuggest.tsx`, `js/admin/pages/workbench/identity-clusters/utils.ts`, `identity-clusters/IdentityClusterList.tsx`, `js/admin/pages/workbench/DeadLetterPanel.tsx` |
| UX maps | `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.{uxmap.json,md}`, `describe-gpu-tier.*`, `gpu-operator-control.*`, `workbench-identity-chips.*` |
| Assessments | `docs/assessments/GPUFLOW-2-gpu-online-diagnosis-20260916.md` (new), `docs/assessments/GPUFLOW-2-cluster-recovery-calibration-20260916.md` (new) |

## Verification Strategy

- Service: pytest per lane (exact commands in the lane table), run in the lane's VM sandbox `.venv` for DB-backed suites; contract example documents validated by `test_shared_schema_documents.py`.
- Infra: `python3 -m pytest infra/oci/gpu_lifecycle/tests -q -p no:cacheprovider` with fake-clock probe exhaustion.
- PHP: `vendor/bin/phpunit` filtered suites per lane; runtime autoload parity check (rg-016) for the new controller.
- SPA: `npx vitest run` per lane; a jsdom reload test that seeds `sessionStorage`, mounts `MediaSelection`, and asserts one `GET /describe/run/{id}` before any mutation; a fake-timer test that unmounts `useDescribeMedia` mid-warm, remounts, and asserts the retry POST reuses the persisted `operation_id`.
- Calibration: C1 report contains pair precision/recall on the labelled demo set by quality stratum (CAL-01), the chosen admission rule, and the false-name rate ceiling; C2 tests replay the fixture and assert no merge crosses two named people.
- Operator smoke (release gate): cold Suggest → navigate → return → description; bulk run reload; People page walkthrough; merge + undo; outbox purge count in `/sync/health`.
- Aggregate: `make check-all` on the integrated branch; `handoff_close_check(enforce=True)`.

## Slice Delivery

### Slice 0: Live GPU diagnosis (operator + read-only agent)

**Goal**: The "GPU never comes online" symptom is classified into one named cause with evidence, before any GPU lane runs.

Changes:

- Operator captures, in order: OCI instance list for `acx_gpu_burst` and the A10 service-limit value; `systemctl status acx-gpu-start.timer acx-gpu-reap.timer` plus the last two start-cycle journal excerpts; `/run/acx/gpu-state.json` and `/run/acx-write/<env>/describe-load.json` before and 30 s after one Suggest; `ACX_GPU_ENDPOINT_URL` presence and `preflight-gpu-env.sh` exit code on the API host; `/health/detailed` body; the WP transient circuit key state; the outbox `failed` row count by age.
- Agent lane (luna max, read-only against evidence) writes `docs/assessments/GPUFLOW-2-gpu-online-diagnosis-20260916.md`: cause classification (provisioning / endpoint env / ready probe / breaker), the Katy Perry representative row (identity id, `representative_quality`, occlusion score, media id) and the Emma Watson triple (identity ids, embeddings' pairwise cosine, refinement decision), and the Perry/Trudeau mixed group membership.
- Provisioning or env causes produce an operator checklist appended to the assessment; they are not lane work.

Proof: assessment committed; handoff decision references it; Slice A dispatch gate reads the cause field.

### Slice A1: Adapter readiness in health (backend)

**Goal**: `/health/detailed.description_adapter` says whether the GPU adapter is usable and why.

Changes: `api/main.py` replaces the static profile echo with a per-request readiness block computed from `deps._is_private_gpu_endpoint`/adapter selection (no network probe; configuration truth only). New `scene-health-detailed.schema.json` example. Test `scene/tests/test_health_detailed_adapter.py` (new) covers unset, non-private, allowlisted, and CPU-profile cases.

Proof: schema example validates; four readiness cases pinned.

### Slice A2: Unavailable reason on the describe envelope (backend)

**Goal**: Every `description_service_unavailable` response names why.

Changes: `responses.py` adds `UnavailableReason` StrEnum and the field; `routers/describe.py::_ensure_gpu_ready` maps missing/stale snapshot, DEGRADED, operator STOP and unconfigured endpoint to reasons; `GpuRemoteAdapterError` after ready keeps `502 description_service_error`. Contract example updated. Lint deferral `SVCCOL-M-04` fixed here.

Proof: route tests assert reason per state; multipart schema example round-trips.

### Slice A3: Loud DEGRADED on ready-probe exhaustion (infra)

**Goal**: A GPU that boots but never answers the ready probe is reported, not silently retried forever.

Changes: `reaper.py` start cycle counts consecutive exhausted ready budgets per instance; on exhaustion writes `DEGRADED` with `reason: ready_probe_exhausted` and `since`; `state_snapshot.py` carries `reason`. A later successful probe clears it. Contract doc updated.

Proof: fake-clock tests for exhaustion → DEGRADED → recovery; snapshot contract test updated.

### Slice A4: Durable operation context and run resume (SPA)

**Goal**: A bulk run survives navigation and reload.

Changes: new `describeOperationStore.ts` (sessionStorage-backed `(state, context)` pair, tenant-keyed, `useSyncExternalStore`); `activeDescribeRun.ts` delegates to it; `useBulkDescribe.ts` derives `runId` from the store, not mutation state, and clears it on terminal status; `MediaSelection.tsx` `isRunRelevant` reads the store. `GpuTierStatus` shows `data-gpu-state` from the run's `gpu_state` and, while resuming, "Checking a run that was already in progress…".

Proof: reload test (seeded storage → one status GET → chip visible); terminal status clears storage; foreign-tenant key ignored.

### Slice A5: Suggest lease resume (SPA)

**Goal**: A single-image Suggest mid-warm survives remount.

Changes: `useDescribeMedia.ts` persists `{media_id, operation_id, startup_id, warming_started_at}` through the store on the first `starting` response; on mount with a matching media id, resumes the retry loop honouring `Retry-After` and the remaining ceiling from the persisted start; `clearLease()` also clears storage. Resolves `GPUFLOW1-FIN-01` correlation by reusing the persisted `operation_id` on manual retry.

Proof: fake-timer unmount/remount test asserts POST reuses `operation_id`; ceiling computed from persisted start, not remount time.

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

### Slice B2: Roster projection carries representative quality (contracts + PHP)

Changes: `roster-entry.schema.json` additions; `class-roster-entry-projection-repository.php` passes `representative_quality`, `quality_components`, `representative_media_id` through from the recognition projection payload verbatim (rg-015), null when absent; `roster-entry.ts` regenerated.

Proof: `RosterEntryProjectionRepositoryTest` covers present/absent fields; generated type diff reviewed.

### Slice B3: Roster row — large quality avatar, working row action, undo-only count (SPA)

Changes: `RosterEntriesTable.tsx` selects the representative by `representative_quality` (fallback: current `identity_count` rule when null); avatar size token `--acx-avatar-lg`; column 1 opens the person workspace and is disabled with a tooltip only when no person UUID exists; column 4 shows "Merged from N groups · Undo" only while `merge.undoAvailable` (token unexpired) and nothing otherwise.

Proof: `RosterEntriesTable.clickthrough.test.tsx` extended; undo cell hidden after token expiry.

### Slice B4: Person media endpoint (PHP)

Changes: new `class-person-media-controller.php` `GET acx/v1/roster/persons/{id}/media?offset&limit` backed by `IdentityMembersReadRepository`/`list_projected_cluster_rows_by_person`; pagination metadata from the query, not `count()` (rg-015); `require_once` wired (rg-016).

Proof: PHPUnit for paging, unknown person 404, tenant scoping; autoload runtime check.

### Slice B5: Person workspace shows media (SPA)

Changes: new `personMediaApi.ts` + `PersonMediaGrid.tsx` (infinite query, thumbnails link to the media item, "Suggest for this image" deep link); `PersonWorkspacePanel.tsx` adds a "Media" tab beside faces.

Proof: `PersonWorkspacePanel.test.tsx` asserts grid renders pages and empty state.

### Slice B6: Ranked merge candidates (backend + PHP + SPA)

Changes: recognition route `GET /recognition/persons/{id}/merge-candidates` ranks other persons by centroid cosine (`centroid_utils.compute_similarity`) merged with pending `ClusterMergeSuggestion` similarity, returns `{similarity, band, shared_media_count}`; PHP proxy in `class-person-merge-controller.php`; `PersonMergeDialog.tsx` fetches candidates on open, `#merge-search` typeahead filters and reorders `#merge-survivor` by similarity desc (name asc within band), option label "Name — 87% match (likely)" from `similarityCopy.ts`, and the confirm step asks the operator to pick before showing the top score badge (HAI-15: badge revealed after selection).

Proof: service unit test on ranking and band; PHPUnit passthrough; vitest ordering and typeahead.

### Slice B7: Compact decorative control (SPA)

Changes: `MediaAltSuggest.tsx` renders an icon toggle labelled "Decorative" with the full sentence as tooltip/`aria-describedby`; pressed state uses tokens; no width change to the suggestion column (LAY-01). Bulk "Mark selected decorative" is a stretch item pending the open decision.

Proof: `MediaAltSuggest.test.tsx` asserts accessible name and description; snapshot of row width.

### Slice C1: Cluster recovery calibration (analysis lane)

Changes: `docs/assessments/GPUFLOW-2-cluster-recovery-calibration-20260916.md`: labelled demo ground truth (Watson ×3, Perry, Trudeau, press group), pairwise cosine matrix, refinement/verification decisions per pair, pair precision/recall by quality stratum, recommended admission rule (τ_auto, margin δ, min independent exemplars k≥2), suggestion band, false-name rate ceiling, and the occlusion coefficient/quality weights for B/C4 with the Katy Perry row as the acceptance example.

Proof: numeric report; handoff decision accepts or rejects the rule.

### Slice C2: Constrained recovery merge with merged-from (backend)

Changes: new `recovery_merge.py` runs after `run_singleton_hac_refinement`: for each residual singleton/small cluster, candidates by centroid cosine; auto-attach only if ≥ k independent exemplars (distinct media) exceed τ_auto and the margin over the runner-up ≥ δ and neither side is bound to a different named person; else emit a merge suggestion via `MergeSuggestionService`. Writes `merged_from` (`moved_identity_ids`, `source_cluster_id`, `rule_version`) on the cluster. Feature-flagged `ACX_RECOVERY_MERGE_ENABLED` in `settings/clustering.py`; defaults off until C1 accepted.

Proof: fixture replay from C1; no merge across two named persons; flag off → no-op.

### Slice C3: Revert merge and undo surface (backend + SPA)

Changes: `cluster_merge.py` gains `revert_merge(cluster_id)` restoring `moved_identity_ids` to a cluster labelled "<name> (restored)" (4.2.3 semantics); `identity-merge.md` contract; `IdentityClusterItem` shows "Merged automatically · Undo" while `merged_from` is present.

Proof: revert test restores the exact prior partition; UI test toggles on `merged_from`.

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

Routing (user order 2026-09-16): implementation and analysis lanes codex-remote `gpt-5.6-luna` effort `max`; plan review and per-delta review twins codex-remote `gpt-6-astra` effort `high`. Export `WORKBAY_CODEX_MODEL` to the lane's model before subprocess import; no tier/speed fields on lane rows. Freeze this plan after the astra review before materializing (GRPH-39). Local host integrates and harmonizes only.

### Lanes

Path conventions and the lane-root Python resolution rules from the GPUFLOW-1 plan apply unchanged. Each lane owns at most three source/artifact files plus its tests. In every dependency cell the prefix names the producer and the row is the read-only consumer (GRPH-32: an edge exists only where a named artifact moves).

| Lane ID | Slice | Owned Paths | Upstream Dependencies (artifact transferred) | Required Tests |
| --- | --- | --- | --- | --- |
| `diagnosis` | 0 | `docs/assessments/GPUFLOW-2-gpu-online-diagnosis-20260916.md` (new) | — (operator evidence gate) | `python3 -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` |
| `contracts-service` | A1/A2/A3 | `packages/shared-contracts/schemas/scene-describe-multipart.schema.json`, `packages/shared-contracts/schemas/scene-health-detailed.schema.json` (new), `docs/workbay/contracts/gpu-lifecycle.md` | diagnosis: assessment | `python3 -m pytest apps/prototype-description-service/scene/tests/test_shared_schema_documents.py -q -p no:cacheprovider` |
| `contracts-roster` | B2/B6/C3 | `packages/shared-contracts/schemas/roster-entry.schema.json`, `packages/shared-contracts/schemas/roster-merge-candidates-response.schema.json` (new), `docs/workbay/contracts/identity-merge.md` (new) | diagnosis: assessment | `python3 -m pytest apps/prototype-description-service/scene/tests/test_shared_schema_documents.py -q -p no:cacheprovider` |
| `svc-health-adapter` | A1 | `api/main.py`; `apps/prototype-description-service/scene/tests/test_health_detailed_adapter.py` (new test) | contracts-service: `scene-health-detailed.schema.json` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_health_detailed_adapter.py -q -p no:cacheprovider` |
| `svc-unavailable-reason` | A2 | `scene/interface_adapters/http/routers/describe.py`, `scene/interface_adapters/http/schemas/responses.py`, `apps/prototype-description-service/scene/tests/fixtures/gpuflow2-unavailable.json` (new test fixture) | contracts-service: `scene-describe-multipart.schema.json` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_describe_route.py apps/prototype-description-service/scene/tests/test_describe_eligibility.py apps/prototype-description-service/scene/tests/test_shared_schema_multipart.py -q -p no:cacheprovider` |
| `infra-ready-degrade` | A3 | `infra/oci/gpu_lifecycle/reaper.py`, `infra/oci/gpu_lifecycle/state_snapshot.py` | contracts-service: `docs/workbay/contracts/gpu-lifecycle.md` | `python3 -m pytest infra/oci/gpu_lifecycle/tests/test_start_actuator.py infra/oci/gpu_lifecycle/tests/test_state_snapshot.py infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py -q -p no:cacheprovider` |
| `php-circuit-reason` | A6 | `src/api/class-abstract-recognition-proxy-controller.php`, `apps/prototype-wp-alt-context/src/api/tests/fixtures/gpuflow2-unavailable-wire.json` (new test fixture) | svc-unavailable-reason: `scene/tests/fixtures/gpuflow2-unavailable.json` | vendor/bin/phpunit --filter "RecognitionProxyRetryPolicy\|Proxy" |
| `spa-error-copy` | A7 | `js/admin/api/errorCopy.ts` (new), `js/admin/api/describeApi.ts`, `js/admin/api/wpErrorMessage.ts` | php-circuit-reason: `src/api/tests/fixtures/gpuflow2-unavailable-wire.json` | npx vitest run js/admin/api/__tests__/describeApi.test.ts js/admin/api/__tests__/wpErrorMessage.test.ts |
| `spa-service-status` | A7 | `js/admin/pages/settings/GpuControlCard.tsx`, `js/admin/pages/RetentionPage.tsx`, `js/admin/hooks/useRetentionStatus.ts` | spa-error-copy: `js/admin/api/errorCopy.ts` | npx vitest run js/admin/pages/settings js/admin/pages/__tests__/RetentionPage.test.tsx |
| `spa-operation-store` | A4 | `js/admin/hooks/describeOperationStore.ts` (new), `js/admin/hooks/activeDescribeRun.ts`, `js/admin/hooks/useBulkDescribe.ts` | contracts-service: `scene-describe-multipart.schema.json` (read-only, resume contract) | npx vitest run js/admin/hooks/__tests__/useBulkDescribe.test.tsx js/admin/hooks/__tests__/describeOperationStore.test.ts |
| `spa-run-resume-chip` | A4 | `js/admin/pages/workbench/MediaSelection.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/fixtures/gpuflow2-resume.json` (new test fixture) | spa-operation-store: `js/admin/hooks/describeOperationStore.ts` | npx vitest run js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx js/admin/pages/workbench/__tests__/MediaSelection.resume.test.tsx |
| `spa-suggest-resume` | A5 | `js/admin/hooks/useDescribeMedia.ts` | spa-operation-store: `js/admin/hooks/describeOperationStore.ts`; spa-error-copy: `js/admin/api/describeApi.ts` | npx vitest run js/admin/hooks/__tests__/useDescribeMedia.test.tsx |
| `spa-roster-headings` | B1 | `js/admin/pages/RosterPage.tsx`, `js/admin/pages/roster/RosterEntriesSection.tsx` | diagnosis: assessment | npx vitest run js/admin/pages/__tests__/RosterPage.test.tsx js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx |
| `php-roster-projection` | B2 | `src/sovereign/repositories/class-roster-entry-projection-repository.php`, `js/admin/api/generated/roster-entry.ts` | contracts-roster: `roster-entry.schema.json` | vendor/bin/phpunit --filter RosterEntryProjectionRepository |
| `spa-roster-table` | B3 | `js/admin/pages/roster/RosterEntriesTable.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/roster/__tests__/fixtures/gpuflow2-roster-rows.json` (new test fixture) | php-roster-projection: `js/admin/api/generated/roster-entry.ts` | npx vitest run js/admin/pages/roster/__tests__/RosterEntriesTable.clickthrough.test.tsx js/admin/pages/roster/__tests__/RosterEntriesTable.reservedLabel.test.tsx |
| `php-person-media` | B4 | `src/api/class-person-media-controller.php` (new), `apps/prototype-wp-alt-context/tests/Unit/PersonMediaControllerTest.php` (new test) | contracts-roster: `roster-entry.schema.json` | vendor/bin/phpunit --filter PersonMediaController |
| `spa-person-media` | B5 | `js/admin/api/personMediaApi.ts` (new), `js/admin/pages/roster/PersonMediaGrid.tsx` (new), `js/admin/pages/roster/PersonWorkspacePanel.tsx` | php-person-media: `tests/Unit/PersonMediaControllerTest.php` (wire shape) | npx vitest run js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx |
| `svc-merge-candidates` | B6 | `recognition/interface_adapters/http/routers/person_merge_candidates.py` (new), `recognition/application/suggestions/merge_candidates.py` (new); `apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py` (new test) | contracts-roster: `roster-merge-candidates-response.schema.json` | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_merge_candidates.py -q -p no:cacheprovider` |
| `php-merge-candidates` | B6 | `src/api/class-person-merge-controller.php` | svc-merge-candidates: `recognition/tests/unit/test_merge_candidates.py` (wire shape) | vendor/bin/phpunit --filter PersonMergeController |
| `spa-merge-dialog` | B6 | `js/admin/pages/roster/PersonMergeDialog.tsx`, `js/admin/api/personMergeApi.ts` | php-merge-candidates: `src/api/class-person-merge-controller.php` | npx vitest run js/admin/pages/roster/__tests__/PersonMergeDialog.test.tsx js/admin/api/__tests__/personMergeApi.test.ts |
| `spa-decorative-control` | B7 | `js/admin/pages/workbench/MediaAltSuggest.tsx` | diagnosis: assessment (operator decision recorded) | npx vitest run js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx |
| `calibration` | C1 | `docs/assessments/GPUFLOW-2-cluster-recovery-calibration-20260916.md` (new) | diagnosis: assessment | numeric calibration report review |
| `svc-recovery-merge` | C2 | `recognition/application/orchestration/clustering/recovery_merge.py` (new), `recognition/application/orchestration/clustering/discovery_pipeline.py`, `recognition/application/settings/clustering.py`; `apps/prototype-description-service/recognition/tests/unit/test_recovery_merge.py` (new test) | calibration: assessment; contracts-roster: `docs/workbay/contracts/identity-merge.md` | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_recovery_merge.py apps/prototype-description-service/recognition/tests/unit/test_merge_suggestions.py -q -p no:cacheprovider` |
| `svc-merge-revert` | C3 | `recognition/application/orchestration/cluster_merge.py`, `db/models/identity.py`, `db/migrations/versions/001_identity_schema.py` | contracts-roster: `docs/workbay/contracts/identity-merge.md` | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_cluster_merge_revert.py -q -p no:cacheprovider` (new test, owned here) |
| `svc-rep-quality` | C4 | `recognition/application/assignment/quality.py`, `recognition/application/persistence/representative_selector.py` | calibration: assessment | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_representative_quality_gate.py apps/prototype-description-service/recognition/tests/unit/test_representative_selector.py apps/prototype-description-service/recognition/tests/unit/test_fir2_br_postmerge_contracts.py apps/prototype-description-service/recognition/tests/unit/test_fir_final_postmerge_runtime_contracts.py apps/prototype-description-service/recognition/tests/unit/test_identity_quality.py -q -p no:cacheprovider` |
| `svc-rep-recompute` | C4 | `recognition/application/persistence/assignment_writer.py` | svc-rep-quality: `representative_selector.py` | `python3 -m pytest apps/prototype-description-service/recognition/tests/integration/test_assignment_writer.py -q -p no:cacheprovider` |
| `spa-cluster-ungrouped` | C5 | `js/admin/pages/workbench/identity-clusters/utils.ts`, `js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx` | diagnosis: assessment | npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx |
| `spa-cluster-undo` | C3 | `js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx` | svc-merge-revert: `docs/workbay/contracts/identity-merge.md` (read-only) | npx vitest run js/admin/pages/workbench/identity-clusters |
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
- `representative_selector.py`/`quality.py` belong to `svc-rep-quality`; `assignment_writer.py` to `svc-rep-recompute`; `discovery_pipeline.py` and `settings/clustering.py` to `svc-recovery-merge`; `cluster_merge.py` and the schema files to `svc-merge-revert`. Schema edits in `001_identity_schema.py`/`db/models/identity.py` happen only in `svc-merge-revert`.
- Each UX lane owns its JSON+MD pair; component lanes never edit maps.
- `lane_dag` validates producer/path/consumer edges before dispatch; shared directories create no edges.

### Merge Order

1. Gate 0: astra high plan review recorded; plan frozen; operator evidence captured; `diagnosis` lane lands. Cause classification decides whether Slice A lanes run at all (provisioning/env causes route to the operator checklist first).
2. Wave 1 (parallel, GRPH-31 longest chains first): `contracts-service`, `contracts-roster`, `calibration`, `spa-roster-headings`, `spa-cluster-ungrouped`, `php-outbox-reclaimer`, `spa-decorative-control` (after the operator decision).
3. Wave 2: `svc-health-adapter`, `svc-unavailable-reason`, `infra-ready-degrade`, `spa-operation-store` after `contracts-service`; `php-roster-projection`, `php-person-media`, `svc-merge-candidates`, `svc-merge-revert` after `contracts-roster`; `svc-recovery-merge`, `svc-rep-quality` after accepted `calibration`; `spa-deadletter` after the reclaimer.
4. Wave 3: `php-circuit-reason` after `svc-unavailable-reason`; `spa-run-resume-chip` after the store; `spa-roster-table` after the projection; `spa-person-media` after the PHP controller; `php-merge-candidates` after the service route; `svc-rep-recompute` after `svc-rep-quality`; `spa-cluster-undo` after `svc-merge-revert`.
5. Wave 4: `spa-error-copy` after `php-circuit-reason`; `spa-merge-dialog` after `php-merge-candidates`; then `spa-service-status` and `spa-suggest-resume` after `spa-error-copy`.
6. Wave 5: UX map lanes after their fixtures.
7. Release gate R.

Critical path: `contracts-service → svc-unavailable-reason → php-circuit-reason → spa-error-copy → spa-suggest-resume → ux-describe`. Integrate continuously into `feature/gpuflow-2`; retire each worktree once its commit and evidence are preserved; `main` receives one final merge.

### Manifest

```bash
make lane-manifest-init TASK=GPUFLOW-2 LANE_IDS='diagnosis contracts-service contracts-roster svc-health-adapter svc-unavailable-reason infra-ready-degrade php-circuit-reason spa-error-copy spa-service-status spa-operation-store spa-run-resume-chip spa-suggest-resume spa-roster-headings php-roster-projection spa-roster-table php-person-media spa-person-media svc-merge-candidates php-merge-candidates spa-merge-dialog spa-decorative-control calibration svc-recovery-merge svc-merge-revert svc-rep-quality svc-rep-recompute spa-cluster-ungrouped spa-cluster-undo php-outbox-reclaimer spa-deadletter ux-roster ux-describe ux-service ux-identity' TASK_PLAN=docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md
```

Only after the astra review and freeze: materialize, re-pin `config/lane-orchestration/GPUFLOW-2.json` to `gpt-5.6-luna`/`max` for implementation lanes and `gpt-6-astra`/`high` for review twins (materialize rewrites pins), verify row/model/effort match, validate with `lane_dag`, and reject any unresolved test path before dispatch.

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

- [ ] Astra high plan review recorded as a review run with findings in handoff; plan frozen
- [ ] Operator evidence captured; `diagnosis` assessment committed; cause recorded as a handoff decision
- [ ] Decorative scope decision recorded
- [ ] Manifest materialized, re-pinned, `lane_dag` valid

### Slice A

- [ ] Health readiness block with schema example and four cases
- [ ] Unavailable `reason` on service and PHP envelopes; `Retry-After` on circuit-open
- [ ] Lifecycle DEGRADED on probe exhaustion with recovery
- [ ] Operation store; run and Suggest resume tests; chip reads live phase
- [ ] Error copy map; retention and GPU chip show reason, activity and countdown

### Slice B

- [ ] One "People" heading; UX map parity
- [ ] Projection carries representative quality; large quality avatar; row opens workspace; undo-only count
- [ ] Person media endpoint and grid
- [ ] Ranked merge candidates end-to-end; typeahead; sorted survivor
- [ ] Compact decorative control

### Slice C

- [ ] Calibration report accepted or rejected by decision
- [ ] Gated recovery merge with `merged_from`; revert; undo surface
- [ ] Quality-aware representative selection with recompute on ingest; five C4 tests updated deliberately
- [ ] Ungrouped residue section

### Slice D and E

- [ ] Outbox reclaimer and health counters; timeline age and bulk discard
- [ ] Four UX maps regenerated with `--check` passing

### Release gate

- [ ] Every delta reviewed once; zero open highs; lints deferred to a named next wave
- [ ] Operator smoke recorded; `make check-all`; `handoff_close_check(enforce=True)`; slice-complete decision

## Review Readiness

- Adversarial plan review brief inlines this plan, the canon rule IDs in Context Loading, the FIR verdicts, and the Slice 0 evidence list; it asks for contradictions with the canon, missing edges (GRPH-32/33), unfrozen topology (GRPH-39), and any threshold asserted without evidence.
- Findings are recorded in handoff under `GPUFLOW-2-PLAN-R-NN`; highs block the freeze.

## Stretch Goals

- Bulk decorative action; `localStorage` cross-tab resume with tenant fencing; per-stratum FAR/FRR dashboard in `/sync/health`.

## Success Criteria

- Cold Suggest → navigate → return → description arrives, with the chip never showing `unknown` while a run exists.
- `/health/detailed` explains any absent adapter; Retention and GPU controls name the cause and visibly act.
- People page passes the walkthrough: one heading, quality avatar, row action, ranked merge, undo.
- Watson triple resolved server-side; no automatic merge across two named people; every automatic merge reversible.
- Failed outbox rows reclaimed within the purge window; no raw upstream error string rendered.
