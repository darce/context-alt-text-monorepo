# Task Plan — DESCAUTH-1

> **Date:** 2026-10-16
> **Author:** claude (Opus 5.5)
> **Owning Epic:** none. The governing decision is [ADR-017](../../adrs/ADR-017-description-authority-wordpress-curation-service-generation.md) (Proposed), which extends [ADR-003](../../adrs/ADR-003-wordpress-local-authority-and-durable-outbox-replay.md) to descriptions.
> **Task ID:** DESCAUTH-1
> **Target Branch:** feature/descauth-1
> **Base SHA:** 2d2af05031978c29d4e4eda8d359dd32bbe73c46
> **Revision:** 2
> **Review Coverage Target:** description read path, both histories, reset/purge outbox. UI copy has targeted UI tests and independently generated ux-map parity. Browser evidence remains operator-gated.
> **Depends on:** operator acceptance of ADR-017 (S0). There is no code dependency on WBTRUST-7. WBTRUST-7 owns the provenance badge, seeded gating and naming gating, and this plan must not edit those behaviours. Both plans touch `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAltSuggest.tsx`; S11 and S14a3 start only after the coordinator pins the merged WBTRUST-7 output and rebase onto it.
> **Executor:** `claude-remote` `claude-haiku-5-5`, effort `xhigh`, for implementation and grunt work (operator order 2026-10-16).
> - Brief each slice separately. Inline the slice text and the codemap snippets for every symbol named.
> - Each lane owns only the files listed in its slice. If a fix needs another file, return a scope proposal; do not edit it.
> - If the remote harness is denied, record a blocker and stop. Do not fall back to another model.
>
> **Review loop:** Sol xhigh reviews once per wave, with one harmonizing review and no per-delta re-review. Only HIGH findings block; fix high and medium, defer low. Lint findings follow sr-011.
> **Prior art:** handoff decisions 17526 (reset/history analysis) and 17527 (sovereign alignment) on MAINT-DESCRESET-20261016. Also the [recognition-state-reconciliation epic](../../epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md), `docs/workbay/contracts/image-description-api.md`, `docs/workbay/contracts/curation-sync-api.md`, and the FIRBENCH private-DB rules in `benchmarks/protocols/firbench-1-private-db-v0-usage.md`.
> **Carried findings (by ID only):** none. Query with `review_findings(list, task_ref="DESCAUTH-1")`.

## DESCAUTH-1. Description authority, history and reset

Service paths are relative to `apps/prototype-description-service/`. Plugin paths are relative to `apps/prototype-wp-alt-context/`; `js/…` is under the plugin, and `docs/…` is at the repo root.

## Objective

- Operators review and apply drafts from WordPress-local data only.
- Every generation and every curation action is recorded append-only and joined by `generation_id` within the stated history retention periods.
- An operator can reset one image, or all descriptions, safely, including while the service is offline.

## Problem Statement

**Gap 1: live draft reads.** This breaks ADR-003 rule 1.
- `class-describe-controller.php` `get_describe_run_items` proxies `/scene/describe/run/{id}/items` live. Four callers depend on it: the Review Queue `?run=` filter (`hooks/useQueueDrafts.ts`), the activity strip (`hooks/useActivityStatus.ts`), bulk apply (`hooks/useDescribeRunApply.ts`), and the guided demo (`guidedPrototype/useGuidedLiveDescription.ts`).
- `apply_describe_run_drafts` also reads both the run status and the items live before writing alt text.
- With the service down, drafts that were already generated cannot be reviewed or applied.

**Gap 2: no decision record.** ADR-003 covers recognition only, so there is no description authority decision (AGT-13). ADR-017 fills this gap and is a gate.

**Also covered:**
- There is no history: `audit_events` has three fields, no retention and no purge.
- There is no reset: purge scopes ignore descriptions, and Regenerate returns the cached draft.
- `DescriptionBulkRunService` and its tables are dead code, and run membership lives in options.
- The "Description Runs" admin page is a dead redirect.

## Constraints

- **Greenfield.**
  - Edit `db/migrations/versions/001_identity_schema.py` and `LifeCycleManager::build_projection_schema_statements` directly. No migrations, no shims; delete over flag.
  - The deploy needs the greenfield schema wipe (S15).
- Project rules:
  - sr-007: new status values are Python `StrEnum` or PHP backed enums.
  - sr-008: at most 8 parameters.
  - sr-009: PHP transactions use `run_transactional`.
  - rg-015: pass `generation_id` and provenance through verbatim.
  - rg-007: the pull job has a bounded no-progress limit.
  - rg-005: SQL column names must match the real DDL.
  - sr-004: CSS uses `--acx-*` tokens.
- **Privacy.**
  - The generation log never stores the woven named draft, `names_applied`, injected names or cluster ids.
  - The benchmark SQLite, its path and real exports stay out of Git, commits, prompts, logs and MCP, as in FIRBENCH.
- Never touch `~/Local Sites/` or LocalWP config. Never actuate the GPU.
- **Test execution.**
  - Implementation checks run on the assigned VM with the exact commands in each slice. Use the service-local `.venv` with the locked dependencies. Provision that runtime before dispatch; do not substitute an unrelated shared runtime.
  - Set OMP/MKL/OPENBLAS threads to 1. Use an outer timeout of at most 300 s and `pytest --timeout=60`.
  - Run only the listed tests, never the full suite.
  - Run each slice command before its fix and after its fix. The named new cases must fail causally for RED, then pass. Collection, dependency and fixture failures are separate errors.
  - Exit 0 is the acceptance condition for each command. Record executed, failed, skipped and fixture-error counts. A source read does not establish runtime acceptance.
  - This planning adjudication runs no test runners, deployments, databases, network requests, email, credentials, GPU or OCI actions.

## Workflow Principles

- RED test first in every code slice. Commit the RED test, then the fix.
- One slice is one lane of 1–3 implementation files plus its listed tests. Generated documentation files count toward the limit. Do not widen.
- Slice ownership and every command below use repo-relative paths. A NEW file is created by its owner. Existing tests keep unrelated coverage.
- Shared files serialize in Wave Order. No code lane starts before S0.
- Keep the wire contract stable unless a slice says otherwise. The items response keeps its current keys; this plan only adds keys.

## Terminology

**Projection**
: WordPress copies of run rows and run-item drafts, derived from the service.

**Terminal run**
: A run whose status is `completed`, `completed_with_errors`, `failed` or `cancelled` (`DescribeRunStatus`).

**Projected-complete**
: A terminal status plus the items, as pulled after that status was seen.

**Generation**
: One describe outcome (`generated` or `cache_hit`), identified by `generation_id`.

**Curation event**
: One WordPress action on a description: `applied`, `corrected`, `discarded` or `reset`.

## Current State Analysis

These are observations at the base SHA, given as symbols rather than line numbers.

- **Plugin**
  - `src/api/class-describe-controller.php`:
    - `submit_describe_run` stores membership with `store_run_media_ids`, `load_run_media_ids` and `remember_run_media_ids_index`, in options with the prefix `acx_describe_run_media_ids_`.
    - `get_describe_run_status` is a live proxy (`post_scan_read`).
    - `get_describe_run_items` is a live proxy plus the `existing_alt`, `thumbnail_url` and `thumbnail_srcset` enrichment.
    - `apply_describe_run_drafts` uses the live status gate and live items, then `build_run_apply_provenance`, the outcome buckets, and the `_acx_description_provenance_pending` marker.
  - `src/support/class-life-cycle-manager.php` defines `acx_description_runs`, `acx_description_run_items` and `acx_description_usage`. The usage ledger is the precedent for an append-only table.
  - `src/sovereign/repositories/class-description-run-repository.php` is used only by `src/api/services/class-description-bulk-run-service.php` and `tests/Unit/DescriptionBulkRunServiceTest.php`, and all three are dead.
  - Outbox:
    - `src/sovereign/sync/class-outbox-writer.php` provides `OutboxWriter::enqueue`.
    - `class-outbox-dispatcher.php` routes ops through `TOPOLOGY_ROUTES` and `build_topology_request_body`.
    - `src/support/trait-runs-transactional.php`.
  - Scheduling precedent: `class-split-topology-command-drain.php` (`register`, `maybe_schedule_drain`: Action Scheduler async with a WP-cron fallback). It is wired in `src/api/class-api.php`.
  - Retention: `src/api/class-retention-controller.php` `trigger_purge` purges on the service first, synchronously, then re-pulls. `ALLOWED_PURGE_SCOPES` is `disposed` and `all`. The dialog copy is in `js/admin/pages/retention/retentionDialogCopy.ts`.
  - Describe meta keys: `_wp_attachment_image_alt`, `_acx_description_provenance`, `_acx_description_human_edit`, `_acx_description_provenance_pending`, `_acx_description_run_status`, `acx_alt_decorative`. Their writers are the controller apply path, `class-describe-media-service.php`, `class-description-history-service.php` `record_correction`, and `src/cli/class-description-command.php`.
  - "Regenerate" in `js/admin/pages/workbench/MediaAltSuggest.tsx` calls the same `generate` as the first draft, so it gets a cache hit.
- **Service**
  - `scene/application/visual_facts_service.py` `VisualFactsService.describe` is the single generation entry point. Generated outcomes persist through `ImageDescriptionRepository.insert_or_get_existing` and audit `description.generated`; cache hits go through `_cache_hit_response` and `_record_cache_hit`. `_cached_unnamed_base(row)` returns the unnamed caption.
  - Run-item provenance dicts are built in `scene/interface_adapters/http/routers/describe_run.py`. Search for `"prompt_or_task_version": response`.
  - Purge: `recognition/interface_adapters/http/routers/retention.py` (`PURGE_SCOPES`), `recognition/interface_adapters/http/schemas/requests.py` (`PurgeRequest`), and `recognition/application/services/purge_service.py`, which covers recognition tables only.
  - Retention: `scene/application/describe_run_repository.py` `run_startup_retention_purge`.

## Target Outcome

| Situation | Behavior |
| --- | --- |
| Service stopped, retained completed run | Review Queue `?run=` shows its drafts; bulk apply works; no proxy call is made |
| Run in progress, service reachable | Drafts appear within one pull (≤ 30 s, or on the next items read) |
| Run in progress, service down | Local drafts shown with "Drafts saved at {time}. Live progress unavailable." |
| Regenerate on one image | New draft from the adapter (cache bypassed); new `generation_id` |
| Reset this description (#116) | Draft discarded; unedited AI alt text and its provenance cleared; `reset` event |
| Reset all descriptions | Preview counts → confirm → local clear + outbox op; service erased on drain; describe blocked until acknowledged |
| Purge scope `all` | Recognition **and** description data, including the generation log |
| Benchmark | `generation_id` joins service lineage to WordPress outcome in a private SQLite file |

## Context Loading

Read the ADR-017 rules first.

Canon (read-only, v0.26.2):

| Row | Anchor | Used for |
| --- | --- | --- |
| AGT-13 | `lexicons/engineering.md#agt-13` | S0 gate |
| DATA-14 | `#data-14` | Projection is derived (S3–S6) |
| DOM-06 | `#dom-06` | Reset outbox (S13) |
| RES-17 | `#res-17` | Reset outbox (S13) |
| PROV-01 | `lexicons/ml-systems.md#prov-01` | Generation log (S1–S2) |
| PROV-09 | `#prov-09` | Generation log (S1–S2) |
| MLDATA-15 | `#mldata-15` | Retention (S12) |
| HAI-06 | `lexicons/interaction-ux.md#hai-06` | Events (S8) |
| HAI-02 | `#hai-02` | Events (S8) |
| INT-11 | `#int-11` | Regenerate and reset one (S9–S11) |
| INT-07 | `#int-07` | Purge preview (S13) |
| INT-06 | `#int-06` | Labels (S10, S13) |
| STOR-07 | `lexicons/engineering.md#stor-07` | Export (S14) |
| STOR-05 | `#stor-05` | Export (S14) |

## Contract and Boundary Impact

- **`image-description-api.md`**
  - `VisualFactsResponse` and run-item `provenance` gain `generation_id: str | null` (S2).
  - The describe envelope gains `fresh: bool = false` (S9a).
  - A new `GET /scene/describe/generations` route is added (S14).
- **Retention purge:** a `scope` of `descriptions` is added, and `all` is extended (S12). Document these in `docs/workbay/contracts/security.md` (S12d). Closed Python and TypeScript contracts land in S12a, S2c and S13c before their callers.
- **WordPress REST**
  - The items response gains `projection: {source:"local", pulled_at, stale}` (S5). Existing keys are unchanged.
  - New `POST /acx/v1/recognition/describe/{media_id}/reset` (S10).
  - New `GET /acx/v1/retention/purge/preview?scope=descriptions` (S13).
- **Outbox:** new op `descriptions_purged`, routed to `POST /recognition/retention/purge` (S13).

## Proposed Solution

1. The service logs every generation (S1–S2).
2. WordPress projects runs and drafts locally with a pull job (S3–S4).
3. All draft reads switch to local (S5–S6).
4. WordPress logs curation events (S7–S8).
5. Per-image Regenerate and Reset are added (S9–S11).
6. A tenant-wide reset uses outbox replay (S12–S13).
7. The dead "Description Runs" page is removed (S14a), and an optional benchmark export is added (S14).

## Files and Surfaces to Change

| Slice | Owned files, including tests and deletions |
| --- | --- |
| S0 | Operator gate; no file ownership |
| S1 | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`; `apps/prototype-description-service/db/models/scene.py`; `apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py` |
| S2 | NEW `apps/prototype-description-service/scene/application/description_generation_log.py`; `apps/prototype-description-service/scene/application/visual_facts_service.py`; `apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py`; `apps/prototype-description-service/scene/tests/test_visual_facts_service.py`; NEW `apps/prototype-description-service/scene/tests/test_description_generation_log.py` |
| S2b | `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py`; `apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py`; `docs/workbay/contracts/image-description-api.md`; `apps/prototype-description-service/scene/tests/test_describe_route.py`; `apps/prototype-description-service/scene/tests/test_describe_run_worker_naming.py` |
| S2c | `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts`; `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts` |
| S3 | `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`; `apps/prototype-wp-alt-context/src/sovereign/repositories/class-description-run-repository.php`; NEW `apps/prototype-wp-alt-context/src/sovereign/enums/class-description-event-type.php`; `apps/prototype-wp-alt-context/tests/Unit/DescriptionRunRepositoryTest.php`; `apps/prototype-wp-alt-context/tests/Unit/SchemaVerificationTest.php` |
| S3b | `apps/prototype-wp-alt-context/src/api/services/class-description-bulk-run-service.php`; `apps/prototype-wp-alt-context/tests/Unit/DescriptionBulkRunServiceTest.php` |
| S3c | `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`; NEW `apps/prototype-wp-alt-context/src/sovereign/repositories/class-description-admission-repository.php`; NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionAdmissionRepositoryTest.php`; `apps/prototype-wp-alt-context/tests/Unit/SchemaVerificationTest.php` |
| S4 | NEW `apps/prototype-wp-alt-context/src/sovereign/sync/class-description-draft-pull-job.php`; `apps/prototype-wp-alt-context/src/api/class-api.php`; `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`; NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionDraftPullJobTest.php`; `apps/prototype-wp-alt-context/tests/Unit/DescribeRunControllerTest.php`; `apps/prototype-wp-alt-context/tests/Unit/PublicDemoDescribeControllerTest.php` |
| S5 | `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`; `apps/prototype-wp-alt-context/tests/Unit/DescribeRunControllerTest.php`; `apps/prototype-wp-alt-context/tests/Unit/DescribeRunItemsThumbnailTest.php` |
| S6 | `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts`; `apps/prototype-wp-alt-context/js/admin/hooks/useQueueDrafts.ts`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx`; `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts`; `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useQueueDrafts.test.tsx`; NEW `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaSelection.projection.test.tsx` |
| S7 | NEW `apps/prototype-wp-alt-context/src/sovereign/repositories/class-description-event-repository.php`; `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`; `apps/prototype-wp-alt-context/src/api/services/class-description-history-service.php`; NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionEventRepositoryTest.php`; `apps/prototype-wp-alt-context/tests/Unit/DescribeRunControllerTest.php`; `apps/prototype-wp-alt-context/tests/Unit/DescriptionHistoryServiceTest.php` |
| S8 | `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php`; `apps/prototype-wp-alt-context/src/cli/class-description-command.php`; `apps/prototype-wp-alt-context/tests/Unit/DescribeMediaServiceTest.php`; `apps/prototype-wp-alt-context/tests/Unit/DescriptionCommandGenerateTest.php` |
| S9a | `apps/prototype-description-service/scene/interface_adapters/http/schemas/requests.py`; NEW `apps/prototype-description-service/scene/tests/test_describe_fresh_envelope.py` |
| S9 | `apps/prototype-description-service/scene/application/visual_facts_service.py`; `apps/prototype-description-service/scene/application/description_repository.py`; `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py`; `apps/prototype-description-service/scene/tests/test_visual_facts_service.py`; `apps/prototype-description-service/scene/tests/test_description_repository.py`; `apps/prototype-description-service/scene/tests/test_describe_route.py` |
| S10 | NEW `apps/prototype-wp-alt-context/src/api/services/class-description-reset-service.php`; `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`; `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php`; NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionResetServiceTest.php`; `apps/prototype-wp-alt-context/tests/Unit/DescribeRunControllerTest.php`; `apps/prototype-wp-alt-context/tests/Unit/DescribeMediaServiceTest.php` |
| S11a | `apps/prototype-wp-alt-context/js/admin/hooks/useDescribeMedia.ts`; `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts`; `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useDescribeMedia.test.tsx`; `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts` |
| S11 | `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAltSuggest.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx`; `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx` |
| S12a | `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py`; NEW `apps/prototype-description-service/recognition/tests/api/test_description_purge_response.py` |
| S12b | `apps/prototype-description-service/recognition/application/services/purge_service.py`; NEW `apps/prototype-description-service/recognition/tests/unit/test_description_purge_transaction.py` |
| S12f | NEW `apps/prototype-description-service/scene/application/description_admission.py`; `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py`; `apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py`; NEW `apps/prototype-description-service/scene/tests/test_description_admission.py` |
| S12 | NEW `apps/prototype-description-service/scene/application/description_purge_service.py`; `apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py`; `apps/prototype-description-service/recognition/interface_adapters/http/schemas/requests.py`; NEW `apps/prototype-description-service/scene/tests/test_description_purge_service.py`; `apps/prototype-description-service/recognition/tests/api/test_retention_api.py` |
| S12c | `apps/prototype-description-service/scene/application/describe_run_repository.py`; `apps/prototype-description-service/api/main.py`; NEW `apps/prototype-description-service/scene/application/description_retention_job.py`; NEW `apps/prototype-description-service/scene/tests/test_description_retention_job.py` |
| S12d | `docs/workbay/contracts/security.md` |
| S12e | NEW `apps/prototype-wp-alt-context/src/sovereign/sync/class-description-retention-job.php`; `apps/prototype-wp-alt-context/src/api/class-api.php`; NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionRetentionJobTest.php` |
| S13c | `apps/prototype-wp-alt-context/js/admin/api/recognition/types/retention.ts`; `apps/prototype-wp-alt-context/js/admin/pages/retention/useRetentionPageState.ts`; `apps/prototype-wp-alt-context/js/admin/pages/retention/__tests__/useRetentionPageState.test.ts`; NEW `apps/prototype-wp-alt-context/js/admin/api/recognition/__tests__/retentionPurgeRequest.test.ts` |
| S13d | `apps/prototype-wp-alt-context/js/admin/api/recognition/retentionApi.ts`; `apps/prototype-wp-alt-context/js/admin/api/recognition/__tests__/retentionPurgeRequest.test.ts` |
| S13e | `apps/prototype-wp-alt-context/js/admin/pages/retention/useRetentionPageState.ts`; `apps/prototype-wp-alt-context/js/admin/pages/retention/__tests__/useRetentionPageState.test.ts` |
| S13 | `apps/prototype-wp-alt-context/src/api/class-retention-controller.php`; `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php`; NEW `apps/prototype-wp-alt-context/src/sovereign/sync/class-description-purge-gate.php`; `apps/prototype-wp-alt-context/tests/Unit/RetentionControllerTest.php`; NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionPurgeGateTest.php`; NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionPurgeReplayTest.php` |
| S13a | `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php`; `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`; `apps/prototype-wp-alt-context/src/api/class-api.php`; `apps/prototype-wp-alt-context/tests/Unit/DescribeMediaServiceTest.php`; `apps/prototype-wp-alt-context/tests/Unit/DescriptionCommandGenerateTest.php`; `apps/prototype-wp-alt-context/tests/Unit/DescribeRunControllerTest.php`; NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionApiCompositionTest.php` |
| S13b | `apps/prototype-wp-alt-context/js/admin/pages/retention/retentionDialogCopy.ts`; `apps/prototype-wp-alt-context/js/admin/pages/retention/RetentionDialogs.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/__tests__/RetentionPage.test.tsx` |
| S14a | `apps/prototype-wp-alt-context/src/admin/class-menu.php`; `apps/prototype-wp-alt-context/src/admin/class-description-history-page.php`; `apps/prototype-wp-alt-context/src/admin/class-admin.php`; `apps/prototype-wp-alt-context/tests/Unit/MenuTest.php`; `apps/prototype-wp-alt-context/tests/Unit/AdminPageAutoloadTest.php` |
| S14a2 | `apps/prototype-wp-alt-context/js/admin/App.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/DescriptionHistoryPage.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/DescribeRunApplyView.tsx`; `apps/prototype-wp-alt-context/js/admin/__tests__/App.test.tsx`; `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/__tests__/menuHeadingParity.test.ts`; `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DescribeRunApplyView.test.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/syncVocabulary.test.ts`; `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DescriptionHistoryPage.test.tsx`; `apps/prototype-wp-alt-context/tests/e2e/smoke/deep-links.spec.ts`; `apps/prototype-wp-alt-context/tests/e2e/fixtures/acx-routes.ts` |
| S14a3 | `apps/prototype-wp-alt-context/js/admin/hooks/useQueueDrafts.ts`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelectionTableBody.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAltSuggest.tsx`; `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useQueueDrafts.test.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaSelectionTableBody.test.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx` |
| S14a4 | `apps/prototype-wp-alt-context/src/api/services/class-description-history-service.php`; `apps/prototype-wp-alt-context/tests/Unit/DescriptionHistoryServiceTest.php` |
| S14a5 | `apps/prototype-wp-alt-context/docs/ux-maps/dashboard.uxmap.json`; `apps/prototype-wp-alt-context/docs/ux-maps/dashboard.md`; `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json` |
| S14a9 | `docs/workbay/contracts/controlled-vocabulary.json`; `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx` |
| S14a6 | `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json`; `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.md`; `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json` |
| S14a7 | `apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.uxmap.json`; `apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.md`; `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json` |
| S14a8 | `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.uxmap.json`; `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.md`; `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json` |
| S14b | NEW `apps/prototype-description-service/scene/interface_adapters/http/routers/description_generations.py`; `apps/prototype-description-service/api/main.py`; NEW `apps/prototype-description-service/scene/tests/test_description_generations_route.py` |
| S14c | `apps/prototype-wp-alt-context/src/cli/class-description-command.php`; NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionCommandHistoryExportTest.php` |
| S14 | NEW `apps/prototype-description-service/scripts/eval_harness/description_history_db.py`; NEW `apps/prototype-description-service/scene/tests/test_description_history_db.py` |
| S15 | Operator gate; no file ownership |

## Verification Strategy

- Unit tests: RED first, as named in each slice.
- **Offline proof (S5):**
  - Use a PHP unit test with the proxy transport stubbed to throw.
  - The items and apply routes still succeed from local rows.
  - Assert zero transport calls for a projected-complete run.
- **Replay proof (S13):**
  - Reset with the dispatcher stubbed to fail.
  - Local state is cleared, the outbox row is `pending`, and describe submit returns 409.
  - After a stubbed 2xx, the row is `acknowledged` and describe is allowed again.
- **Live verification (S15):** after the operator deploys.
- **Planning gate:** source-read the owned diff and verify the ownership/dependency table. No implementation, task, E2E or quality PASS follows from that check.
- **Implementation gate:** execute the exact commands below in the provisioned lane, then obtain the parent review and the operator-gated S15 evidence.

## Slice Delivery

### Slice S0: adr-017-acceptance

Operator gate. No code.
- The operator reads ADR-017 and records acceptance in the parent handoff.
- Only the operator changes ADR-017 from Proposed and supplies the acceptance decision.
- The coordinator verifies that record before dispatching S1 through S15.
- This planning correction leaves ADR-017 Proposed.
Acceptance: operator acceptance and its decision pointer exist before any implementation command runs.

### Slice S1: generation-log-schema

Add the service history table.
Canon: PROV-01, PROV-09, MLDATA-04.
Design decision (binding):
- In `001_identity_schema.py`, create the table `image_description_generations` and add it to `TENANT_TABLES`, `EXPECTED_SCHEMA_TABLES` and `DOWNGRADE_TABLE_ORDER`. Place it before `image_descriptions` in the downgrade order. Enable and force RLS exactly as for `image_descriptions`.
- Columns:
  - `id uuid PK`
  - `tenant_id uuid NOT NULL`, with the same FK and RLS policy as `image_descriptions`
  - `created_at timestamptz NOT NULL DEFAULT now()`
  - `media_id int NOT NULL`
  - `image_hash varchar(64) NOT NULL`
  - `context_hash varchar(64) NOT NULL`
  - `run_id uuid NULL`, with **no FK**, because runs are purged and history stays
  - `outcome varchar(16) NOT NULL`, with `CHECK IN ('generated','cache_hit')`
  - `adapter varchar(32) NOT NULL`
  - `model_id varchar(128) NOT NULL`
  - `model_version varchar(32) NOT NULL`
  - `prompt_or_task_version varchar(64) NOT NULL`
  - `tier varchar(16) NULL`
  - `adapter_caption text NULL`
  - `adapter_alt_text text NULL`
  - `draft_sha256 varchar(64) NULL`
  - `naming_status varchar(32) NULL`
  - `named_person_count int NOT NULL DEFAULT 0`
  - `duration_ms int NOT NULL`
  - `processing_ms int NULL`
- Indexes: `(tenant_id, created_at)`, `(tenant_id, image_hash)` and `(tenant_id, run_id)`.
- Add the ORM model `ImageDescriptionGeneration` to `db/models/scene.py`. `outcome` is a plain `String(16)` column; the `GenerationOutcome(StrEnum)` lives in the S2 module.

- Also create `description_purge_receipts` with `tenant_id uuid NOT NULL`, `idempotency_key varchar(128) NOT NULL`, `scope varchar(16) NOT NULL`, `request_sha256 char(64) NOT NULL`, `acknowledgement jsonb NOT NULL` and `created_at timestamptz NOT NULL DEFAULT now()`.
- Its primary key is `(tenant_id, idempotency_key)`. Use a tenant FK with `ON DELETE CASCADE` and forced tenant RLS. Register schema, downgrade and RLS parity exactly as for the generation table.
- Add ORM model `DescriptionPurgeReceipt` in the same model file.
- Receipts survive `descriptions`, `all` and age retention. They contain counts and request identity, never drafts. Tenant deletion is their reclaimer; retain them for the tenant lifetime to preserve arbitrarily late replay safety.
- RED cases: `test_generation_log_schema_rls_indexes` and `test_purge_receipt_unique_tenant_key_rls_and_lifecycle`. Assert a duplicate tenant/key is rejected and a different tenant can use that key.

Test files:
- Existing `apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/recognition/tests/test_identity_schema_migration.py
```

### Slice S2: generation-log-writes

Write one generation record at the final naming boundary.
- NEW `apps/prototype-description-service/scene/application/description_generation_log.py` defines `GenerationOutcome(StrEnum)`, frozen `DescribeOptions(run_id=None, fresh=False)`, frozen `PendingGeneration`, `GenerationLogSink` and `DescriptionGenerationRepository.append`.
- `VisualFactsService.__init__` accepts an optional `generation_log` sink. `describe` accepts only one new keyword, `options: DescribeOptions | None = None`; keep the eight-parameter bound.
- For generated output, stage the raw `AdapterResult.caption` and `AdapterResult.alt_text_draft`, lineage, timing and run id in `PendingGeneration` after cache persistence succeeds. Stage generated output even when an insert race returns the winning cached row; use the winning response's unnamed text and label that returned outcome `cache_hit`.
- For both cache-hit branches, stage `adapter_caption=_cached_unnamed_base(row)` and `adapter_alt_text=None`, with `outcome=cache_hit`.
- Carry that pending record as a Pydantic private attribute on the response. It is never serialized, shared between responses or stored in a service-global slot.
- Add nullable `generation_id: str | None = None` to `VisualFactsResponse`.
- Add `VisualFactsService.finalize_generation(response)`. Call it exactly once after final naming enrichment, before any response, operation-result or run-item serialization. Consume the private pending record so repeated calls do not append twice.
- At finalization, set `draft_sha256` from the consumer-visible `named_draft` when present; otherwise hash `alt_text_draft`. Set `naming_status` and `named_person_count` from the final `naming_provenance`. If naming is disabled, store `naming_status=disabled` and count zero.
- Persist only unnamed adapter text and the final naming summary. Never persist names, cluster ids, woven drafts or `names_applied`.
- `DescriptionGenerationRepository.append` inserts and flushes inside `async with session.begin_nested()`. A database failure rolls back that savepoint before the exception reaches the fail-open caller. Never roll back the outer cache/run transaction for optional history.
- Append failure logs a bounded error with request/run correlation, increments a counter and leaves `generation_id=None`. A missing sink also leaves it None; never synthesize an id.
- RED cases: `test_generation_staged_until_final_naming`, `test_cache_hit_stages_unnamed_base`, `test_finalization_appends_once`, `test_history_never_stores_person_name`, `test_real_append_flush_failure_preserves_outer_commit`. The last uses the repository and a real transactional session, causes an insert/flush failure and proves the outer cache/run write still commits.

Test files:
- Existing `apps/prototype-description-service/scene/tests/test_visual_facts_service.py`.
- NEW `apps/prototype-description-service/scene/tests/test_description_generation_log.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/scene/tests/test_visual_facts_service.py apps/prototype-description-service/scene/tests/test_description_generation_log.py
```

### Slice S2b: generation-log-wiring

Wire every sink and finalization boundary.
- Construct the repository-backed sink beside every `_DescriptionAuditSink` in `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py` and `apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py`.
- Pass `DescribeOptions(run_id=run_id)` in bulk workers.
- Finalize sync, multipart, background and bulk responses after their final naming step. Finalize generated and cache-hit outcomes at that same boundary, including naming-disabled paths.
- Set run-item `provenance["generation_id"]` from `response.generation_id` verbatim, before committing the result.
- Update `docs/workbay/contracts/image-description-api.md` with the nullable id, every history column and the naming finalization boundary. No names enter the log.
- RED cases: `test_generated_named_outcome_history_matches_response`, `test_cached_named_outcome_history_matches_response`, `test_bulk_item_uses_finalized_generation_id`. Use one confirmed person and compare stored status/count with returned naming provenance. Cover background serialization as well as the multipart path.

Test files:
- Existing `apps/prototype-description-service/scene/tests/test_describe_route.py`.
- Existing `apps/prototype-description-service/scene/tests/test_describe_run_worker_naming.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/scene/tests/test_describe_route.py apps/prototype-description-service/scene/tests/test_describe_run_worker_naming.py
```

### Slice S2c: generation-id-typescript-contract

After S2b, add `generation_id: string | null` to `VisualFactsResponse` in `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts`.
- The parser preserves a supplied id, preserves null and normalizes an omitted legacy key to null. It rejects a non-string non-null value.
- Do not add `generation_id` to content-identity equality; it identifies a call, not content.
- RED cases: `preserves generation id`, `normalizes missing generation id`, `rejects malformed generation id`.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/api/__tests__/describeApi.test.ts
```

### Slice S3: wp-projection-schema

Replace the dead run tables with the projection and the event table.
Canon: DATA-14, HAI-06.
Design decision (binding): in `build_projection_schema_statements`, rewrite the DDL as follows.

- **`acx_description_runs`:**
  - `run_id varchar(64) PK`
  - `status varchar(24) NOT NULL DEFAULT 'pending'`
  - `run_kind varchar(16) NOT NULL DEFAULT 'bulk'`
  - `total_items int unsigned NOT NULL DEFAULT 0`
  - `last_pulled_at datetime NULL`
  - `projected_complete_at datetime NULL`
  - `pull_no_progress int unsigned NOT NULL DEFAULT 0`
  - `pull_last_error varchar(128) NULL`
  - `pull_lease_token varchar(36) NULL`, `pull_lease_until datetime NULL`
  - `pull_last_attempt_at datetime NULL`, `pull_stalled_at datetime NULL`
  - `created_at`, `updated_at`
  - `KEY idx_status_created`
- **`acx_description_run_items`:**
  - `id`, `run_id`, `media_id`, `status varchar(20)`
  - `alt_text_draft text NULL`
  - `caption text NULL`
  - `provenance longtext NULL`, holding JSON stored verbatim
  - `tier varchar(16) NULL`
  - `result_generation int unsigned NOT NULL DEFAULT 0`
  - `processing_ms int unsigned NULL`
  - `error_message text NULL`
  - `generation_id varchar(36) NULL`
  - `discarded_at datetime NULL`
  - `created_at`, `updated_at`
  - Keep `uq_run_media`, `idx_run_status` and `idx_media`.
- **New `acx_description_events`:**
  - `id bigint AUTO_INCREMENT PK`
  - `occurred_at datetime NOT NULL`
  - `media_id bigint unsigned NOT NULL`
  - `event_type varchar(16) NOT NULL`
  - `generation_id varchar(36) NULL`
  - `run_id varchar(64) NULL`
  - `actor_user_id bigint unsigned NOT NULL DEFAULT 0`
  - `draft_sha256 char(64) NULL`
  - `final_alt_sha256 char(64) NULL`
  - `final_alt text NULL`
  - `human_edited tinyint(1) NOT NULL DEFAULT 0`
  - `KEY idx_media_occurred`, `KEY idx_generation`
  - Register it in the keys map.
- NEW `apps/prototype-wp-alt-context/src/sovereign/enums/class-description-event-type.php` defines PHP backed enum `DescriptionEventType` with `applied`, `corrected`, `discarded` and `reset`. Match the repository namespace/autoload convention.
- Rewrite `DescriptionRunRepository` with these methods:
  - `create_run(run_id, run_kind, media_ids)`, which inserts the run and `pending` items in one `run_transactional` call;
  - `create_run_in_transaction(run_id, run_kind, media_ids)` for a caller-owned transaction; `create_run` is its standalone transactional wrapper;
  - `get_run`;
  - `list_items(run_id)`;
  - `upsert_items(run_id, items)`, which updates service-owned draft/result columns only when incoming `result_generation` is at least the stored value. It never clears `discarded_at`, even for a newer generation;
  - `update_run_pull_state`;
  - `list_unfinished_runs(limit)`, selecting non-complete, non-stalled rows with no live lease, ordered by `pull_last_attempt_at` ascending (NULL first), then `created_at`, then `run_id`;
  - `discard_item`.
- Add atomic `claim_pull(run_id, token, expires_at)`, token-checked `finish_pull` and `resume_pull(run_id)`. A claim sets the attempt timestamp. Lease duration is 60 s; each remote request has a 20 s timeout. Expired workers cannot write items, counters or terminal state after another token wins.
- Add `purge_expired_batch(now, limit)` for events older than 180 days and projected-complete runs older than 30 days. Delete items with their run in the same transaction. Preserve unfinished runs, their items, active reservations and unacknowledged reset state.
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescriptionRunRepositoryTest.php` must be rewritten from the old `create_run`/`get_run_status` API. Keep schema coverage and replace obsolete API assertions explicitly.
- RED cases: `testCreateRunAndMembership`, `testStaleGenerationIgnored`, `testEqualAndNewerPullPreserveDiscard`, `testConcurrentClaimHasOneWinner`, `testExpiredWorkerCannotWrite`, `testEleventhRunSelectedAfterTenStall`, `testProjectionSchemaColumns`.

Test files:
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescriptionRunRepositoryTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/SchemaVerificationTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionRunRepositoryTest|SchemaVerificationTest' tests/Unit
```

### Slice S3b: remove-dead-bulk-service

After S3, delete `apps/prototype-wp-alt-context/src/api/services/class-description-bulk-run-service.php` and its obsolete `apps/prototype-wp-alt-context/tests/Unit/DescriptionBulkRunServiceTest.php`.
- The existing repository suite is the maintained replacement. It must pass before the deletion commit.
- The reference gate searches active source only. Tests naming the removed symbol are deleted, not counted as live consumers.

- Delete the obsolete test file listed in ownership; do not execute that deleted path.
- RED characterization: `testCreateRunAndMembership` in the S3 repository suite protects the replacement before removal.
Acceptance commands (worktree root):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionRunRepositoryTest' tests/Unit
if rg -n 'DescriptionBulkRunService' apps/prototype-wp-alt-context/src; then exit 1; else rc=$?; test "$rc" -eq 1; fi
```

### Slice S3c: atomic-description-admission

After S3b, create a shared durable admission repository.
- Add `acx_description_admission` (`tenant_id varchar(64) PRIMARY KEY`, `reset_outbox_id bigint unsigned NULL`) and `acx_description_submissions` (`tenant_id`, `request_key varchar(128)`, `kind varchar(16)`, `state varchar(16)`, nullable `run_id` and `operation_id`, request fingerprint, `created_at`, `updated_at`, `terminal_at`; PRIMARY KEY `(tenant_id,request_key)`). Use InnoDB; register both schema keys. Use the configured tenant id, never a request-supplied tenant.
- NEW `apps/prototype-wp-alt-context/src/sovereign/repositories/class-description-admission-repository.php` implements `reserve_submission`, `bind_remote`, `bind_remote_in_transaction`, `mark_terminal`, `lock_and_check_reset_in_transaction`, `begin_reset_in_transaction`, `bind_reset_in_transaction` and `is_reset_pending`.
- Use `INSERT IGNORE` to ensure the tenant row, then `SELECT ... FOR UPDATE` under `run_transactional`. The row lock is shared by bulk submission, single-image submission and reset. Do not use transients for exclusion.
- A submission reserves its stable existing idempotency key before file reads, budget reservation or transport. Commit the reservation before transport. Reusing the key requires the same fingerprint; conflicting input returns 409.
- A definitive local validation failure before any dispatch releases its new reservation. A documented pre-admission service rejection with no accepted operation also marks terminal. An error after dispatch is uncertain unless the service proves terminal; never infer non-admission from a timeout.
- Preserve reservations across warming, operation polling and uncertain transport failure. Bind the returned run/operation id; mark terminal only on a verified terminal response. Never expire an uncertain reservation just because a timer elapsed.
- An uncertain submission exposes `description_submission_uncertain`; its recovery is retrying the original command with the original key and input. The service's existing idempotency contract recovers the accepted run. No new key is minted for that recovery.
- Reset acquires the same row lock, checks every non-terminal reservation and local run, checks pending reset outbox state, then reserves its reset before any clear. Active/uncertain work returns 409 with zero deletes.
- `lock_and_check_reset_in_transaction` locks the tenant row and checks pending reset, non-terminal reservations and active local runs without reserving a tenant purge. Per-image reset uses it too.
- Admission methods used inside reset and `bind_remote_in_transaction` never start another transaction. Public standalone mutation methods own one `run_transactional` call.
- Define backed enum `DescriptionAdmissionState` in the admission repository module for reserved, active, uncertain and terminal. Add `purge_terminal_batch(now, limit)` to reclaim only verified-terminal reservations.
- Keep terminal reservations for 30 days. S12e reclaims them in batches. Keep unresolved reservations visible and gated until verified terminal; report their age/count.
- RED cases: `testSubmitReservationPrecedesTransport`, `testResetInterleavingCannotPassReservation`, `testResetReservationBlocksSubmission`, `testUncertainSubmissionRetainsKey`, `testNoNestedTransactionInReset`. Exercise competing connections against an InnoDB fixture for the lock invariant; a missing fixture is an infrastructure error, never a causal RED.

Test files:
- NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionAdmissionRepositoryTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/SchemaVerificationTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionAdmissionRepositoryTest|SchemaVerificationTest' tests/Unit
```

### Slice S4: draft-pull-job

Derive the projection from the service after S3c.
- `submit_describe_run` calls `reserve_submission` before sending bytes. On service acceptance, use one controller-owned `run_transactional` call with `bind_remote_in_transaction` and `create_run_in_transaction` to bind its reservation and create local membership from the submitted readable media ids. Neither inner method starts a transaction. On projection persistence failure, retain the reservation, return `description_submission_uncertain` and recover using the same submit key.
- In this same slice, change only the membership lookup in `apply_describe_run_drafts` from `load_run_media_ids` to the submitted local items in `DescriptionRunRepository`. Preserve its missing-membership failure behavior. S5 owns its remaining status/draft read changes.
- Delete `store_run_media_ids`, `load_run_media_ids`, `remember_run_media_ids_index`, their constants and the option index. Update existing apply tests to seed repository membership now. Rewrite option-storage/failure assertions in `DescribeRunControllerTest.php` and `PublicDemoDescribeControllerTest.php` to repository persistence/admission assertions; do not retain obsolete option expectations.
- NEW `DescriptionDraftPullJob::pull(run_id): PullOutcome` and backed enum `PullOutcome` live in `apps/prototype-wp-alt-context/src/sovereign/sync/class-description-draft-pull-job.php`.
- Every scheduled, items-read and apply-triggered pull must win the repository's atomic 60 s lease. A losing claimant returns busy without transport. Use a 20 s timeout per service request; do not hold a database transaction across transport.
- Fetch status, then items using `post_scan_read`. Commit item upserts and pull state only if the lease token still matches. A terminal status is projected-complete only after fetching and committing its items. Mark the submission terminal at that boundary.
- Measure progress by newly terminal items, increased `result_generation`, changed draft/result hashes or a run-status transition. Reset the consecutive failure/no-progress counter only on such progress.
- Each unchanged attempt and each transport error consumes one of 40 consecutive attempts. At 40, set `pull_stalled_at`, record the reason and stop automatic retry. Keep all local rows on error. Exceptions consume budget and are logged with run id.
- Hook `acx_description_draft_pull` through Action Scheduler, with WP-cron fallback. Select at most 10 eligible rows in the repository's oldest-last-attempt order. Reschedule eligible backlog after 30 s. Exclude stalled rows so ten stalled runs cannot starve an eleventh.
- Register the job in `apps/prototype-wp-alt-context/src/api/class-api.php`. Scheduler deduplication is not mutual exclusion; all entry points use the database lease.
- Add capability-checked `POST /acx/v1/recognition/describe/runs/{run_id}/resume-pull` in the controller. It clears the consecutive counter/stall under the lease rules and schedules one pull. Completed runs are unchanged.
- RED cases: `testTerminalItemsCommitCompletesProjection`, `testTwoPullsForActiveThenTerminal`, `testFortyTransportErrorsStall`, `testProgressResetsFailureBudget`, `testConcurrentReadAndSchedulePullOnce`, `testEleventhRunNotStarved`, `testResumeSchedulesStalledRun`, `testApplyUsesRepositoryMembershipAfterHelperRemoval`.

Test files:
- NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionDraftPullJobTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescribeRunControllerTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/PublicDemoDescribeControllerTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionDraftPullJobTest|DescribeRunControllerTest|PublicDemoDescribeControllerTest' tests/Unit
if rg -n 'acx_describe_run_media_ids|store_run_media_ids|load_run_media_ids|remember_run_media_ids_index' apps/prototype-wp-alt-context/src/api/class-describe-controller.php; then exit 1; else rc=$?; test "$rc" -eq 1; fi
```

### Slice S5: local-draft-reads

Switch all bulk draft reads to the local repository after S4.
- `get_describe_run_items` reads local rows only. For a non-complete, non-stalled run older than 5 s, attempt one leased refresh, then read local rows again. A pull failure retains rows and reports stale state; it is not a successful refresh.
- Keep existing response keys and thumbnail/existing-alt enrichment. Add `projection: {source:"local", pulled_at, stale, stalled, backlog, last_error, resume_url}`. Unknown run returns 404.
- `get_describe_run_status` may proxy progress only while the run is not projected-complete. On failure, return the local row with `projection.stale=true`; keep an error if there is no local row. A projected-complete run returns locally with zero transport calls.
- `apply_describe_run_drafts` gates on the local run. For a non-complete run, attempt one leased pull; if still incomplete return 409 `describe_run_not_projected`.
- Membership was migrated in S4. Drafts now come from local items, excluding every `discarded_at` row as `skipped_no_draft`. Keep existing buckets, CAS and provenance-pending marker logic.
- Add `generation_id` to `build_run_apply_provenance` verbatim. Do not add it to content-identity comparison.
- RED cases: `testCompletedItemsAndApplyWorkWithThrowingTransport`, `testCompletedStatusNeverCallsService`, `testStatusFallbackUsesLocalRow`, `testDiscardSurvivesEqualAndNewerPullAndCannotApply`, `testUnknownRun404`, `testIncompleteApply409`.
- The only production GET of service run items must be in the pull job; verify the exact active source inventory below.

Test files:
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescribeRunControllerTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescribeRunItemsThumbnailTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescribeRunControllerTest|DescribeRunItemsThumbnailTest' tests/Unit
python3 - <<'CHECK'
from pathlib import Path
import re
pattern = re.compile(r'''['"]/scene/describe/run/[^'"\n]+/items['"]''')
hits = sorted(p.as_posix() for p in Path('apps/prototype-wp-alt-context/src').rglob('*.php') if pattern.search(p.read_text()))
assert hits == ['apps/prototype-wp-alt-context/src/sovereign/sync/class-description-draft-pull-job.php'], hits
CHECK
```

### Slice S6: stale-projection-notice

Show stale and stalled state after S5 and S2c.
- In `DescribeRunItemsResponse`, parse `projection` leniently; absent legacy projection is not stale. Preserve the additional S5 fields.
- Add `resumeDescribeRunPull(run_id)` in the owned API file for the S4 resume endpoint. The resume control uses that function and invalidates only that run query.
- `useQueueDrafts` returns `projectionStale`, `projectionPulledAt`, stalled/backlog state and the resume action URL.
- `MediaSelection` renders `role=status` with an icon and tokens. With a known pull time, use "Drafts saved at {time}. Live progress unavailable." With no pull time, use "Drafts are refreshing. Live progress unavailable." Never invent a timestamp or announce zero counts as successful empty state on a failed pull.
- A stalled notice includes a "Resume draft refresh" control which invokes the returned capability-checked route. Hide it for completed runs.
- RED cases: `parses local projection`, `shows stale notice`, `shows stalled resume`, `hides notice for fresh projection`, `failed first pull does not announce empty success`.
- S14a6 owns the later workbench ux-map update; do not change it in this slice.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts`.
- Existing `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useQueueDrafts.test.tsx`.
- NEW `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaSelection.projection.test.tsx`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/api/__tests__/describeApi.test.ts js/admin/hooks/__tests__/useQueueDrafts.test.tsx js/admin/pages/workbench/__tests__/MediaSelection.projection.test.tsx
```

### Slice S7: curation-events-apply-and-correct

Start WordPress curation history after S5 and S6.
- NEW `DescriptionEventRepository::append(event)` in `apps/prototype-wp-alt-context/src/sovereign/repositories/class-description-event-repository.php` is insert-only and returns the source event id. It never starts a nested transaction.
- Bulk apply appends `applied` for `applied` and `partial` outcomes, preserving `generation_id`, run id, draft hash, final alt/hash and `human_edited=0`.
- `DescriptionHistoryService::record_correction` appends `corrected` with `human_edited=1` and nullable generation id from existing provenance.
- Optional history append failure does not change an already determined outcome bucket. Log correlated failures. Preserve the required reset transaction's rollback on authoritative state/outbox failure.
- RED cases: `testAppendIsInsertOnlyAndReturnsDistinctIds`, `testApplyAndPartialAppendOneEvent`, `testCorrectionKeepsGenerationId`, `testOptionalHistoryFailureKeepsOutcome`.

Test files:
- NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionEventRepositoryTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescribeRunControllerTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescriptionHistoryServiceTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionEventRepositoryTest|DescribeRunControllerTest|DescriptionHistoryServiceTest' tests/Unit
```

### Slice S8: curation-events-other-writers

Cover single-image and CLI writers after S7.
- `DescribeMediaService` and the CLI append `applied` for actual alt writes, with the response's nullable generation id. Add it to the generated provenance whitelist verbatim.
- If CLI delegates the write to the shared service, record once in that shared writer; the CLI must not append a second event for it.
- Keep `generation_id` outside `matches_generated_provenance`; it is call-scoped. On content identity match, keep the existing `alt_text_draft` healing behavior.
- RED cases: `testSingleImageWriteAppendsGenerationEvent`, `testCliWriteAppendsExactlyOnce`, `testDifferentGenerationIdDoesNotChangeContentIdentity`, `testMatchingContentStillHealsDraft`.
- Inventory every active alt-meta writer and include the matching event test in the slice report. The grep below is an inventory and must exit 0 with at least one writer; it is not alone a coverage proof.

Test files:
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescribeMediaServiceTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescriptionCommandGenerateTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescribeMediaServiceTest|DescriptionCommandGenerateTest' tests/Unit
rg -n "update_post_meta.*_wp_attachment_image_alt|_wp_attachment_image_alt" apps/prototype-wp-alt-context/src/api/class-describe-controller.php apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php apps/prototype-wp-alt-context/src/api/services/class-description-history-service.php apps/prototype-wp-alt-context/src/cli/class-description-command.php
```

### Slice S9a: fresh-envelope-contract

Before S9, add `fresh: bool = False` to `DescribeImageEnvelope` in `apps/prototype-description-service/scene/interface_adapters/http/schemas/requests.py`.
- Keep `extra=forbid` and all existing request validation.
- RED cases: `test_fresh_envelope_defaults_false`, `test_fresh_envelope_accepts_true`, `test_unknown_envelope_key_still_rejected`.

Test files:
- NEW `apps/prototype-description-service/scene/tests/test_describe_fresh_envelope.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/scene/tests/test_describe_fresh_envelope.py
```

### Slice S9: regenerate-fresh-service

After S9a and S2b, bypass the cache only for an explicit fresh command.
- `_validated_describe_multipart_submission` passes the parsed `fresh` into `DescribeOptions`, already defined by S2. Do not add another `describe` keyword.
- `fresh=True` skips `get_by_cache_key`, calls the adapter and uses new `ImageDescriptionRepository.replace_for_cache_key(row)` in the same session. Delete and insert atomically; rollback restores the old cache row on insert failure.
- Finalize a new generated history outcome after naming. Bulk commands always pass `fresh=False`.
- Do not fetch WordPress media on the service; the existing multipart command carries the bytes.
- RED cases: `test_fresh_cached_key_calls_adapter_and_replaces`, `test_nonfresh_uses_cache`, `test_replace_failure_restores_old_cache`, `test_route_propagates_fresh_and_finalizes_history`.

Test files:
- Existing `apps/prototype-description-service/scene/tests/test_visual_facts_service.py`.
- Existing `apps/prototype-description-service/scene/tests/test_description_repository.py`.
- Existing `apps/prototype-description-service/scene/tests/test_describe_route.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/scene/tests/test_visual_facts_service.py apps/prototype-description-service/scene/tests/test_description_repository.py apps/prototype-description-service/scene/tests/test_describe_route.py
```

### Slice S10: reset-one-description-wp

Per-image recovery after S8 and S9.
- Add capability-checked `POST /acx/v1/recognition/describe/(?P<media_id>\d+)/reset` with `{include_human_edit?: bool}` and the apply capability.
- NEW `DescriptionResetService::reset` in `apps/prototype-wp-alt-context/src/api/services/class-description-reset-service.php` owns one `run_transactional` call.
- Expose `reset_in_transaction(media_id, include_human_edit)` for tenant reset. It requires a caller-owned transaction and never issues START TRANSACTION, COMMIT or ROLLBACK. Event append also never starts a transaction.
- The standalone reset calls `lock_and_check_reset_in_transaction` before changes. A pending tenant reset returns 409 `description_purge_pending`; active/uncertain work returns 409 `description_work_active`. A tenant reset already owns that lock/check when calling the inner helper.
- Reset marks every existing projection item for that media discarded. It clears alt/provenance/pending only if the current alt equals the provenance draft and `_acx_description_human_edit` is unset, unless `include_human_edit=true` explicitly authorizes clearing.
- Keep a human alt otherwise and return `{media_id, discarded_drafts, alt_cleared, alt_kept_human_edit}`. Append one reset event with the old generation id.
- Pulls never clear a discard, even for a newer result. A user Regenerate action starts a new generation with a new generation id. Its successful single-image command may display the returned draft, but old bulk rows remain discarded and cannot apply. Never revive an old bulk row from a pull.
- `DescribeMediaService` forwards `fresh` into its existing multipart envelope.
- RED cases: `testResetClearsUneditedAiAlt`, `testResetKeepsHumanAlt`, `testExplicitHumanOptInClears`, `testResetHasNoTransport`, `testResetInTransactionDoesNotNest`, `testPerImageResetRefusesPendingOrActiveWork`, `testOldDiscardCannotReviveAfterRegenerate`.

Test files:
- NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionResetServiceTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescribeRunControllerTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescribeMediaServiceTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionResetServiceTest|DescribeRunControllerTest|DescribeMediaServiceTest' tests/Unit
```

### Slice S11a: fresh-mutation-hook

After S10, update the maintained mutation path before its UI caller.
- Add `fresh?: boolean` to `DescribeMediaWriteOptions` in `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts` and serialize it as body `fresh` when supplied.
- `useDescribeMedia` preserves `fresh` in `writeOptionsOf`, initial dispatch, warming retry and operation mismatch/expiry retry. Keep the user-action idempotency key stable across those retries.
- Normal Generate omits fresh. Regenerate will pass `{mediaId, fresh:true}` in S11.
- RED cases: `real hook preserves fresh in first request`, `warming retry preserves fresh and request key`, `operation retry preserves fresh`, `normal generate omits fresh`. Use the real hook and API serializer with a stubbed HTTP boundary; do not mock the hook.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useDescribeMedia.test.tsx`.
- Existing `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/hooks/__tests__/useDescribeMedia.test.tsx js/admin/api/__tests__/describeApi.test.ts
```

### Slice S11: regenerate-and-reset-ui

After S11a, implement Regenerate and Reset UI.
- Only Regenerate calls `mutate({mediaId, fresh:true}, callbacks)`. Keep normal Generate on its normal cache path and keep retry on the same mutation input.
- Add "Reset this description" with a confirmation describing the clear. For a human edit, offer "Also clear my edited alt text". Serialize that checkbox as `include_human_edit`.
- After reset, clear the draft. Clear the displayed saved alt only when `alt_cleared=true`. When `alt_kept_human_edit=true`, retain/refetch the saved human alt and announce that it was kept.
- Keep existing focus, error, loading and token styles. On reset failure preserve both saved alt and draft; return focus to the invoking control after dismissal.
- RED cases: `regenerate sends fresh through real hook`, `reset clears ai alt`, `reset retains saved human alt and announces it`, `human opt in clears saved alt`, `reset failure preserves content`.
- The hook/request tests in S11a remain the retry-path gate. Do not claim freshness from a mocked-hook component test alone.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx`.
- Existing `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx js/admin/__tests__/banned-vocabulary.test.tsx
```

### Slice S12a: purge-response-contract

Before S12, extend `PurgeResponse.scope` in `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py` to `Literal["disposed","descriptions","all"]`.
- Add nullable `idempotency_key` to the response. A descriptions/all replay returns the same stored key, timestamp and deleted counts.
- RED cases: `test_descriptions_purge_response_validates`, `test_unknown_purge_response_scope_rejected`. Use the actual response model.

Test files:
- NEW `apps/prototype-description-service/recognition/tests/api/test_description_purge_response.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/recognition/tests/api/test_description_purge_response.py
```

### Slice S12b: recognition-purge-transaction-boundary

Before S12, expose `RetentionPurgeService.purge_tenant_data_in_transaction` in `apps/prototype-description-service/recognition/application/services/purge_service.py`.
- It performs recognition deletion, audit and last-purge timestamp updates in the caller's session. It never commits, rolls back the caller or performs a concurrent materialized-view refresh inside that transaction.
- Keep `purge_tenant_data` as the existing standalone wrapper for disposed. It owns its commit and runs centroid refresh after commit. The all coordinator also refreshes after commit; refresh failure is reported as repair backlog and never reruns deletion.
- Preserve the existing explicit empty-scope sentinel. Never interpret an empty scope as tenant-wide deletion. `descriptions` never enters recognition deletion.
- RED cases: `test_in_transaction_purge_has_no_commit`, `test_outer_rollback_restores_recognition_rows`, `test_empty_scope_never_widens`, `test_disposed_wrapper_commits_once`.

Test files:
- NEW `apps/prototype-description-service/recognition/tests/unit/test_description_purge_transaction.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/recognition/tests/unit/test_description_purge_transaction.py
```

### Slice S12f: service-description-admission-lock

Before S12, serialize service-side admission and purge.
- NEW `apps/prototype-description-service/scene/application/description_admission.py` defines `lock_description_tenant(session, tenant_id)`. On PostgreSQL, take `pg_advisory_xact_lock(hashtextextended('descriptions:' || :tenant_id, 0))`; set a local 5 s lock timeout. The tenant id comes from authentication.
- In `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py` and `apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py`, acquire that lock in the transaction that durably reserves the single operation/run. Commit its active record before dispatching compute. Release the transaction lock before adapter work.
- Purge uses the same lock before its active-work check and deletes. This prevents a direct service caller from entering the check/delete gap.
- Lock timeout is a retryable 503 with zero deletion/reservation. Do not use process-local exclusion for this cross-worker invariant.
- RED cases: `test_direct_submit_and_purge_serialized`, `test_active_reservation_visible_before_compute`, `test_tenant_lock_timeout_has_no_side_effect`. Use competing PostgreSQL connections in the transaction fixture; missing fixtures are separate errors.

Test files:
- NEW `apps/prototype-description-service/scene/tests/test_description_admission.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/scene/tests/test_description_admission.py
```

### Slice S12: descriptions-purge-service

Implement the service reset after S1, S12a, S12b and S12f.
- NEW `DescriptionPurgeService.purge(tenant_id, scope, idempotency_key)` in `apps/prototype-description-service/scene/application/description_purge_service.py` coordinates descriptions and all.
- `PurgeRequest` accepts descriptions/all and requires a non-empty key for them. Preserve disposed's existing request behavior. Validate keys at at most 128 characters.
- In one transaction: take `lock_description_tenant`; look up `(tenant_id,idempotency_key)` before the active-work check. A stored matching request returns its stored acknowledgement with no deletes, even if newer work exists. A different scope/fingerprint for that key returns 409 `idempotency_key_mismatch`.
- For a new key, reject non-terminal runs/describe operations with 409 `description_work_active` and no receipt. Claim the unique receipt key, delete items, runs, cache and terminal operations, then store the final serialized `PurgeResponse` in the receipt. Commit deletion and receipt together. Concurrent copies return the one committed acknowledgement.
- descriptions keeps generation history and all recognition rows. all additionally deletes generations and calls `purge_tenant_data_in_transaction` for recognition in that same transaction. Exclude receipts from both scopes.
- Route `PURGE_SCOPES` includes descriptions. Disposed uses its existing service; descriptions/all use the new coordinator. Forward the exact key and return the stored response through the actual `PurgeResponse` model.
- The retention route returns active-work 409 as a JSON response with top-level `error_code="description_work_active"` and a bounded message. Key/fingerprint mismatch uses top-level `error_code="idempotency_key_mismatch"`. Keep successful responses validated through `PurgeResponse`.
- Do not use SKIP LOCKED for a requested tenant reset. A lock timeout returns a retryable error and rolls back all deletions; never acknowledge a partial purge.
- RED cases: `test_descriptions_keeps_generations_and_recognition`, `test_all_deletes_both_domains_atomically`, `test_active_work_409_has_no_receipt`, `test_purge_k_new_description_replay_k_preserves_newer_row_and_original_ack`, `test_concurrent_same_key_deletes_once`, `test_scope_mismatch_conflicts`, `test_descriptions_router_serializes_real_response`, `test_locked_rows_never_report_complete`.

Test files:
- NEW `apps/prototype-description-service/scene/tests/test_description_purge_service.py`.
- Existing `apps/prototype-description-service/recognition/tests/api/test_retention_api.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/scene/tests/test_description_purge_service.py apps/prototype-description-service/recognition/tests/api/test_retention_api.py
```

### Slice S12c: periodic-service-history-retention

After S12, ship retention while the service remains running.
- Extend `run_startup_retention_purge` in `apps/prototype-description-service/scene/application/describe_run_repository.py` to run the same bounded generation expiration pass used by the periodic job. Keep `GENERATION_LOG_RETENTION_DAYS=365` and the existing terminal-single-run policy.
- NEW `apps/prototype-description-service/scene/application/description_retention_job.py` runs at startup and hourly. Delete generations older than 365 days in batches of 500, at most 10 batches per tick. With backlog, schedule the next tick in 60 s; after completion, wait one hour.
- Register and supervise it in `apps/prototype-description-service/api/main.py` lifespan; cancel and await it at shutdown. Each tick uses its own short-lived RLS-bypassed maintenance session, with explicit tenant predicates per batch. No active run is deleted.
- Publish deleted rows, remaining expired count, oldest expired age, last successful tick and failures. A failed/locked batch is incomplete and retried next tick, never reported as complete. Alert on expired backlog older than 24 h or no successful tick for 2 h.
- Generation logical expiration is 365 days; physical deletion SLA is within 24 h after expiration. Leave receipts out of this job.
- RED cases: `test_generations_expire_without_restart`, `test_more_than_one_batch_drains_on_followup_ticks`, `test_locked_or_failed_batch_keeps_backlog`, `test_shutdown_cancels_retention_job`, `test_receipts_survive_history_retention`.

Test files:
- NEW `apps/prototype-description-service/scene/tests/test_description_retention_job.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/scene/tests/test_description_retention_job.py
```

### Slice S12d: purge-and-retention-contract-documentation

After S12c, update `docs/workbay/contracts/security.md`.
- Specify descriptions/all/disposed boundaries, required stable keys, durable receipts, exact replay acknowledgement, request mismatch conflict and description-work busy retry.
- Specify 365-day service generation expiration and its 24 h deletion SLA, 180-day WordPress events, 30-day completed projections and terminal reservations, and both periodic jobs/backlog signals.
- Record the receipt exception: no description/all/age deletion; tenant-lifetime retention of non-content replay metadata, reclaimed by tenant deletion.
Acceptance: every behavior below is present; the bounded source gate must exit 0.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
python3 - <<'CHECK'
from pathlib import Path
s = Path('docs/workbay/contracts/security.md').read_text()
for term in ('descriptions', 'idempotency_key', 'description_purge_receipts', '365', '180', '30', '24', 'backlog'):
    assert term in s, term
CHECK
```

### Slice S12e: periodic-wordpress-history-retention

After S12c and S4, ship the WordPress reclaimer.
- NEW `apps/prototype-wp-alt-context/src/sovereign/sync/class-description-retention-job.php` registers `acx_description_retention` through Action Scheduler with WP-cron fallback in `apps/prototype-wp-alt-context/src/api/class-api.php`.
- Run hourly with an atomic per-tenant admission-row lock for each short batch. Delete events older than 180 days, completed run projections/items older than 30 days and verified-terminal admission reservations older than 30 days. S3 and S3c own the repository primitives.
- Bound each tick to 10 batches of 500. With backlog, requeue in 60 s. Never delete unfinished projections, active/uncertain reservations or reset/outbox replay metadata.
- Persist one bounded status record per tenant with completion/backlog counts, oldest expired age, failures and last success. `get_status` exposes it for diagnostics; emit an actionable warning after 24 h of expired backlog or 2 h without success.
- Retained alt/provenance meta remains WordPress curation authority after projection history expires. No cron attempt clears it.
- RED cases: `testExpiredEventsAndCompletedProjectionReclaimed`, `testMultipleBatchesDrainWithoutRestart`, `testActiveAndPendingRowsSurvive`, `testFailedBatchRemainsBacklog`, `testHistoryExpiryDoesNotClearAltMeta`.

Test files:
- NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionRetentionJobTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionRetentionJobTest' tests/Unit
```

### Slice S13c: typescript-purge-scope-contract

Before S13b, centralize `PurgeScope = 'disposed' | 'descriptions' | 'all'` in `apps/prototype-wp-alt-context/js/admin/api/recognition/types/retention.ts`.
- `PurgeTenantDataRequest.scope`, retention state and `SET_PURGE_SCOPE` reuse that type. Add optional `include_human_edit` to the request and optional `service_pending: boolean` to the existing response type alongside `deleted_counts`.
- No duplicate disposed/all unions remain in these owners. S13b reuses this type in the dialog props/options/mutation path.
- RED cases: `descriptions selection persists in reducer`, `purge request preserves descriptions and human opt in`.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/pages/retention/__tests__/useRetentionPageState.test.ts`.
- NEW `apps/prototype-wp-alt-context/js/admin/api/recognition/__tests__/retentionPurgeRequest.test.ts`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/pages/retention/__tests__/useRetentionPageState.test.ts js/admin/api/recognition/__tests__/retentionPurgeRequest.test.ts
```

### Slice S13d: purge-preview-client-api

After S13c, add `fetchDescriptionPurgePreview(scope)` to `apps/prototype-wp-alt-context/js/admin/api/recognition/retentionApi.ts`.
- Define/export `DescriptionPurgePreview` in that module with local counts and nullable service counts. Import `PurgeScope` directly from the existing types module.
- Use the existing configured retention purge URL and a URL helper that inserts `/preview` into the REST route. Preserve WordPress query-style `rest_route` routing and nonce behavior; do not append a string after an existing query.
- Request only descriptions/all. A failed request rejects; it never fabricates zero counts.
- RED cases: `preview uses configured pretty permalink route`, `preview preserves query style rest_route`, `preview failure remains error`.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/api/recognition/__tests__/retentionPurgeRequest.test.ts`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/api/recognition/__tests__/retentionPurgeRequest.test.ts
```

### Slice S13e: purge-preview-state-and-submit

After S13d, wire preview and submit state in `apps/prototype-wp-alt-context/js/admin/pages/retention/useRetentionPageState.ts`.
- Import the preview function/type directly from `retentionApi.ts`. Add `useQuery` keyed by scope and dialog-open state, enabled only for descriptions/all while the dialog is open. Expose loading, data, error and refetch to the page.
- Add `include_human_edit` checkbox state/action, default false. Clear it when the dialog closes. `confirmPurge` refuses loading/error/no-preview descriptions/all state and serializes that checkbox with the selected scope.
- A scope change invalidates the previous preview for confirmation. After 202, keep service-pending state visible; do not announce service erasure. Disposed keeps the existing synchronous confirmation path.
- RED cases: `scope change cannot confirm stale preview`, `preview failure prevents mutation`, `human opt in reaches request`, `accepted reset retains service pending notice`.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/pages/retention/__tests__/useRetentionPageState.test.ts`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/pages/retention/__tests__/useRetentionPageState.test.ts
```

### Slice S13: descriptions-reset-wp-outbox

WordPress-first tenant reset after S10, S12, S12e and S13c.
- `GET /acx/v1/retention/purge/preview?scope=descriptions` reports local projected drafts, clearable AI alts, retained human alts, active/uncertain reservations and active runs. The same endpoint accepts all for local description counts. Label recognition deletion as pending service replay; do not require a live recognition read for confirmation and do not invent recognition counts.
- For descriptions and all, `trigger_purge` owns one `run_transactional` call. Acquire the admission-row lock and call `begin_reset_in_transaction` before any mutation. Active runs/reservations or an unacknowledged/undiscarded reset return 409 with zero clears.
- In that transaction, call `DescriptionResetService::reset_in_transaction` for affected attachments while their old rows/provenance still supply lineage, then delete projection rows and enqueue `descriptions_purged` with the exact requested scope and a stable writer-generated key. Bind its outbox id in the admission row. An enqueue error rolls back every local clear/event/reservation.
- Do not call the standalone `reset` wrapper inside this transaction. Do not synchronously purge all before local mutation. Disposed keeps its existing synchronous behavior.
- In the dispatcher, add optional `SyncPullJobInterface` injection. For a successful all response, call `perform_bypass_cooldown(tenant_id)` before returning the acknowledged result. If recognition projection refresh fails, return failed/retryable `description_all_projection_refresh_failed`; the outbox remains gated and retries the same stored purge key/receipt. Descriptions-only never invokes recognition refresh.
- For default dispatchers created outside `Api`, lazily construct `SyncPullJobFactory(new ClustersRepository(), new IdentityMembersRepository(), new SyncStateRepository(), new SnapshotClient())->create()`. Composition failure is retryable and never acknowledges all. This preserves the existing all-purge recognition refresh without another destructive POST.
- Return 202 with `{deleted_counts, service_pending:true}`. Local description counts are final; service counts are reported only after acknowledgement. While all is pending, recognition follows its existing reconciliation behavior, and description admission remains blocked.
- Add `descriptions_purged` to dispatcher routes for `POST /recognition/retention/purge`. Body is `{confirm:true, scope, idempotency_key}` with the stored key. Replay must never mint another key.
- NEW `DescriptionPurgeGate::is_pending` in `apps/prototype-wp-alt-context/src/sovereign/sync/class-description-purge-gate.php` delegates pending state to the admission repository/outbox. Only acknowledged or explicitly discarded reset ops release admission, under the same tenant lock. A conflict/dead-letter stays visible and gated; recovery uses the existing explicit retry/discard controls.
- Pass the operation context into `normalize_single_response` and update its in-file callers. Read the top-level `error_code` defined by S12; do not guess a version-conflict code from an active-work response.
- Only for `descriptions_purged`, map 409 `description_work_active` to the existing failed/retryable result shape, with `retryable=true` and that error code. Use the unchanged OutboxDrain limits: 60 s base backoff, 3600 s cap, existing jitter, 24 h retry window and 40-attempt hard cap. Exhaustion stays visible as dead-letter/pending gate until explicit operator retry/discard. Do not map it to a version conflict. All other 409 mappings stay unchanged.
- RED cases: `testPendingResetBlocksGeneration`, `testAckReleasesAdmission`, `testActiveOrUncertainWorkRejectsBeforeClear`, `test409BusyThenSuccessReplaysSameKey`, `testAllUsesLocalFirstOutbox`, `testAllRefreshFailureRetriesStoredReceipt`, `testDefaultDispatcherCanRefreshAll`, `testEnqueueFailureRollsBackAllLocalChanges`, `testTenantResetIssuesOnlyOneStartAndCommit`.

Test files:
- Existing `apps/prototype-wp-alt-context/tests/Unit/RetentionControllerTest.php`.
- NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionPurgeGateTest.php`.
- NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionPurgeReplayTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'RetentionControllerTest|DescriptionPurgeGateTest|DescriptionPurgeReplayTest' tests/Unit
```

### Slice S13a: shared-single-image-purge-admission

After S13 and S11, wire the remaining writer through the shared admission mechanism.
- At the start of `DescribeMediaService::describe_media`, before file reads, budget reservation and transport, reserve the stable single-image request key under the same admission-row lock. Pending reset returns 409 `description_purge_pending` with no service request.
- In `apps/prototype-wp-alt-context/src/api/class-api.php`, compose the default `OutboxDrain` with `new OutboxDispatcher(null, $this->resolve_bootstrap_sync_pull_job())`; set the bootstrap job field before resolving it. Keep a supplied drain injection unchanged. Register scheduled handlers at plugin load, including cron requests.
- Keep the reservation through warming and operation retries, bind remote ids and mark terminal only when the service operation is terminal. The CLI already calls this shared method and receives the same gate.
- Bulk `submit_describe_run` already reserves in S4. Verify its refusal and key reuse against the completed reset gate. Do not replace reservation with a separate `is_pending` check.
- RED cases: `testApiCronDrainReceivesRecognitionRefreshJob`, `testCliPendingResetMakesZeroServiceRequests`, `testSingleImageGateBeforeReadsAndBudget`, `testBulkResetInterleavingCannotClear`, `testSingleImageRetryReusesReservation`, `testAckPermitsBothWriters`.

Test files:
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescribeMediaServiceTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescriptionCommandGenerateTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescribeRunControllerTest.php`.

- NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionApiCompositionTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescribeMediaServiceTest|DescriptionCommandGenerateTest|DescribeRunControllerTest|DescriptionApiCompositionTest' tests/Unit
```

### Slice S13b: purge-gate-and-dialog

After S13a and S13e, complete the reset dialog.
- In `retentionDialogCopy.ts`, `RetentionDialogs.tsx` and `apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx`, import `PurgeScope` for options, props, actions and requests. Remove every remaining disposed/all-only union on this path.
- In `RetentionPage.tsx`, replace the retired-page note/link with the maintained Review Queue destination. Pass preview and checkbox state/actions from S13e to the dialog.
- Add `PURGE_SCOPE_DESCRIPTIONS_LABEL = 'All descriptions'`. The all label is "All recognition and description data".
- On selecting descriptions/all, fetch preview, show the local counts and pending-service meaning before Confirm. If preview fails, keep Confirm disabled and show the error. Do not present unknown service counts as zero.
- Submit the selected scope and explicit human-edit checkbox. On 202, show local completion and service replay pending; do not announce service erasure before acknowledgement.
- RED cases: `selects and submits descriptions scope`, `preview precedes confirm`, `preview failure disables confirm`, `all reset reports pending service replay`. Use actual state/mutation/request serialization with an HTTP stub.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/pages/__tests__/RetentionPage.test.tsx`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/pages/__tests__/RetentionPage.test.tsx
```

### Slice S14a: remove-description-runs-page

Remove the PHP page after S13a. This slice owns only the PHP removal lane.
- Remove both `alt-context-description-history` submenu entries in `apps/prototype-wp-alt-context/src/admin/class-menu.php`.
- Delete `apps/prototype-wp-alt-context/src/admin/class-description-history-page.php` and its loading in `apps/prototype-wp-alt-context/src/admin/class-admin.php`.
- Rewrite existing menu/autoload tests to require the retired page to be absent.
- RED cases: `testDescriptionHistoryMenuAbsent`, `testRemovedDescriptionPageNotLoaded`.
- S14a2 through S14a8 are distinct dependent lanes below. All JS/docs lanes start after S11 and rebase onto its output. No two owners edit a shared file concurrently.

Test files:
- Existing `apps/prototype-wp-alt-context/tests/Unit/MenuTest.php`.
- Existing `apps/prototype-wp-alt-context/tests/Unit/AdminPageAutoloadTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'MenuTest|AdminPageAutoloadTest' tests/Unit
```

### Slice S14a2: remove-description-history-react-route

After S14a and S11, remove the retired redirect and entry from `apps/prototype-wp-alt-context/js/admin/App.tsx`.
- Change the back link in `apps/prototype-wp-alt-context/js/admin/pages/DescribeRunApplyView.tsx` to the maintained Review Queue destination and label it "Back to Review Queue".
- Delete `apps/prototype-wp-alt-context/js/admin/pages/DescriptionHistoryPage.tsx` and its existing component test.
- Update the listed route, vocabulary, heading and apply-view tests. Keep route names out of newly active assertions by testing the maintained Review Queue route.
- Update `apps/prototype-wp-alt-context/tests/e2e/smoke/deep-links.spec.ts` and `apps/prototype-wp-alt-context/tests/e2e/fixtures/acx-routes.ts` to use Review Queue. These are test ownership only; browser execution belongs to S15.
- Update `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/syncVocabulary.test.ts` to the maintained vocabulary.
- RED cases: `review queue is the description landing page`, `retired page absent from menu headings`.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/__tests__/App.test.tsx`.
- Existing `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx`.
- Existing `apps/prototype-wp-alt-context/js/admin/pages/__tests__/menuHeadingParity.test.ts`.
- Existing `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DescribeRunApplyView.test.tsx`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/__tests__/App.test.tsx js/admin/__tests__/banned-vocabulary.test.tsx js/admin/pages/__tests__/menuHeadingParity.test.ts js/admin/pages/__tests__/DescribeRunApplyView.test.tsx js/admin/pages/workbench/__tests__/syncVocabulary.test.ts
```

### Slice S14a3: remove-retired-history-ui-links

After S14a2, S6 and S11, remove only retired page links/references from `useQueueDrafts.ts`, `MediaSelectionTableBody.tsx` and `MediaAltSuggest.tsx` at the exact owned paths.
- Keep local history data and projection lookup. Removing a page must not remove the Review Queue's draft source or its human-alt reset behavior.
- Rebase onto S11 before editing `MediaAltSuggest.tsx`.
- RED cases: `queue draft lookup works without retired page`, `saved human alt remains after reset`, `no retired page link rendered`.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useQueueDrafts.test.tsx`.
- Existing `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaSelectionTableBody.test.tsx`.
- Existing `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/hooks/__tests__/useQueueDrafts.test.tsx js/admin/pages/workbench/__tests__/MediaSelectionTableBody.test.tsx js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx
```

### Slice S14a4: remove-retired-history-service-links

After S14a3 and S7, remove retired-page links/references from `apps/prototype-wp-alt-context/src/api/services/class-description-history-service.php`.
- Preserve local curation history, correction recording and event append. The retired page does not own those data paths.
- RED case: `testHistoryAndCorrectionsRemainWithoutRetiredPage`.

Test files:
- Existing `apps/prototype-wp-alt-context/tests/Unit/DescriptionHistoryServiceTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionHistoryServiceTest' tests/Unit
```

### Slice S14a5: dashboard-description-navigation-docs

After S14a4 and S13b, remove the retired page from `apps/prototype-wp-alt-context/docs/ux-maps/dashboard.uxmap.json`.
- Generate `apps/prototype-wp-alt-context/docs/ux-maps/dashboard.md` with the exact renderer below; never edit rendered Markdown by hand.
- Keep unrelated navigation. S14a9 owns the vocabulary file before the final gate.
- The renderer also writes `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json`; this lane owns it and serializes that shared file. It is generated parity data, never evidence of loaded UI or an executed browser flow. Preserve the independent retained-contract authority; never backfill an expected pin from current output.
Acceptance: the renderer and parity commands exit 0. Renderer dependencies must be provisioned before dispatch; missing dependencies are fixture errors.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-description-service/.venv/bin/python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py dashboard
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-description-service/.venv/bin/python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py --check dashboard
```

### Slice S14a9: description-navigation-vocabulary

After S14a5 and before S14a6, remove the retired page path from `docs/workbay/contracts/controlled-vocabulary.json`.
- Preserve all unrelated vocabulary and the maintained Review Queue destination. No code/map lane edits this file in parallel.
Acceptance: vocabulary tests exit 0; S14a8 owns the final active-reference gate.

Test files:
- Existing `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/__tests__/banned-vocabulary.test.tsx
```

### Slice S14a6: workbench-projection-reset-map

After S14a5, update `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json`.
- Remove retired navigation. Describe the S6 stale/stalled/resume states, S11 Regenerate/reset/human-alt states and S13b pending reset state.
- Generate only its sibling Markdown with the commands below.
- The renderer also writes `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json`; this lane owns it and serializes that shared file. It is generated parity data, never evidence of loaded UI or an executed browser flow. Preserve the independent retained-contract authority; never backfill an expected pin from current output.
Acceptance: rendering and the independent code/map parity checks exit 0.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-description-service/.venv/bin/python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py workbench-2pane
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-description-service/.venv/bin/python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py --check workbench-2pane
```

### Slice S14a7: operator-loop-navigation-map

After S14a6, remove retired navigation from `apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.uxmap.json`.
- Generate only its sibling Markdown. Keep the current operator loop and remaining pages.
- The renderer also writes `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json`; this lane owns it and serializes that shared file. It is generated parity data, never evidence of loaded UI or an executed browser flow. Preserve the independent retained-contract authority; never backfill an expected pin from current output.
Acceptance: both commands exit 0.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-description-service/.venv/bin/python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py workbench-operator-loop
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-description-service/.venv/bin/python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py --check workbench-operator-loop
```

### Slice S14a8: roster-navigation-map-and-removal-gate

After S14a7, remove retired navigation from `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.uxmap.json` and generate its sibling Markdown.
- The final zero-reference gate lists active source and the exact maintained documentation. Historical plans/reviews and tests asserting absence are outside that list.
- `rg` exit 1 means the zero-match gate succeeds; exit 2 is an error. Never mask a search failure.
- The renderer also writes `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json`; this lane owns it and serializes that shared file. It is generated parity data, never evidence of loaded UI or an executed browser flow. Preserve the independent retained-contract authority; never backfill an expected pin from current output.
Acceptance: all commands below exit 0; no hand-edited rendered artifacts.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-description-service/.venv/bin/python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py roster-people
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-description-service/.venv/bin/python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py --check roster-people
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/__tests__/uxmap-parity.test.ts js/admin/__tests__/banned-vocabulary.test.tsx
if rg -n 'alt-context-description-history|DescriptionHistoryPage|Description Runs' apps/prototype-wp-alt-context/src apps/prototype-wp-alt-context/js/admin/App.tsx apps/prototype-wp-alt-context/js/admin/hooks/useQueueDrafts.ts apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelectionTableBody.tsx apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAltSuggest.tsx apps/prototype-wp-alt-context/docs/ux-maps/dashboard.uxmap.json apps/prototype-wp-alt-context/docs/ux-maps/dashboard.md apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.md apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.uxmap.json apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.md apps/prototype-wp-alt-context/docs/ux-maps/roster-people.uxmap.json apps/prototype-wp-alt-context/docs/ux-maps/roster-people.md apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx apps/prototype-wp-alt-context/js/admin/pages/DescribeRunApplyView.tsx docs/workbay/contracts/controlled-vocabulary.json; then exit 1; else rc=$?; test "$rc" -eq 1; fi
```

### Slice S14b: generation-history-export-route

Optional export starts only after S8, S12c and S14a8.
- NEW `apps/prototype-description-service/scene/interface_adapters/http/routers/description_generations.py` serves tenant-scoped `GET /scene/describe/generations` with ascending `(created_at,id)` keyset cursor, limit 1..500 and matching tenant RLS. Register it in `apps/prototype-description-service/api/main.py`.
- Include generation id, tenant id, image hash, unnamed fields, lineage and timing. Never export named drafts or identity details from the service.
- RED cases: `test_generation_export_tenant_isolation`, `test_keyset_pagination_has_no_duplicates`, `test_export_limit_rejected_above_500`.

Test files:
- NEW `apps/prototype-description-service/scene/tests/test_description_generations_route.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/scene/tests/test_description_generations_route.py
```

### Slice S14c: wordpress-history-jsonl-export

After S14b, add `wp acx description export-history` in `apps/prototype-wp-alt-context/src/cli/class-description-command.php`.
- Emit JSONL records with explicit `record_type`, `tenant_id` and source `generation_id` or source WordPress `event_id`. Keep event `generation_id` nullable and non-unique. Fetch generations through the proxy; read curation events locally.
- Keep stdout machine-readable with no banners. Stub all export content in tests. No real exports, paths, names or emails enter Git, logs, MCP or prompts.
- RED cases: `testJsonlPreservesSourceEventIdsAndNullableGeneration`, `testExportStdoutContainsOnlyRecords`.

Test files:
- NEW `apps/prototype-wp-alt-context/tests/Unit/DescriptionCommandHistoryExportTest.php`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionCommandHistoryExportTest' tests/Unit
```

### Slice S14: history-export (optional, after S8)

Optional importer runs after S14c. This slice owns only the importer lane.
- NEW `apps/prototype-description-service/scripts/eval_harness/description_history_db.py` accepts `import --jsonl - --db <private-path>` for derived benchmark data.
- SQLite `generations` has PRIMARY KEY `(tenant_id,generation_id)` and an index on `image_hash`. SQLite `events` has PRIMARY KEY `(tenant_id,event_id)` preserving the source WordPress event id. Event `generation_id` is nullable, non-unique and indexed with tenant id for joins.
- Upsert by those source keys. Preserve applied/corrected/reset events sharing a generation and multiple events with no generation. Reimport cannot collapse them.
- Reject a database path inside any Git worktree, including linked worktrees, before creating it. Use mode 0700 for its private directory and 0600 for the file. Never store image bytes. Keep this DB separate from FIRBENCH.
- Only synthetic temp-directory records are test data. Never execute the importer against a real private export during implementation verification.
- RED cases: `test_three_curation_events_share_generation_without_loss`, `test_multiple_null_generation_events_survive`, `test_repeat_import_preserves_every_event`, `test_tenant_keys_do_not_collide`, `test_worktree_path_rejected`, `test_private_permissions`.
- S14b, S14c and S14 are distinct one-file export lanes, in that order.

Test files:
- NEW `apps/prototype-description-service/scene/tests/test_description_history_db.py`.

RED/acceptance commands (worktree root; each must exit 0 after the fix):
```sh
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=apps/prototype-description-service timeout 300s apps/prototype-description-service/.venv/bin/python -m pytest --timeout=60 -q -c apps/prototype-description-service/pyproject.toml apps/prototype-description-service/scene/tests/test_description_history_db.py
```

### Slice S15: deploy-and-browser-reverify (operator-gated)

Operator-gated deployment and browser evidence. No automated lane actuates deployment, database, GPU or OCI operations.
- Parent prerequisite: all required slice commands passed with explicit counts and parent review resolved. Optional S14b/S14c/S14 may be omitted together.
- The operator owns the greenfield wipe/build/activation procedure in the deployment runbook. This document grants no permission to execute it.
- After operator deployment, record browser evidence for completed-run offline review/apply, non-terminal refresh failure, Regenerate cache bypass, per-image human-alt preservation, and descriptions/all reset replay.
- For replay, demonstrate service outage, pending local reset, both UI and CLI describe refusal, then acknowledgement after service recovery. Replaying the old key after a newer generation must preserve that generation.
- Include projection stalled/resume and periodic-retention backlog visibility in the operator checklist.
Acceptance: parent/operator evidence includes observed counts and pointers for every scenario. Offline source reads and unit tests never establish task, E2E or quality PASS.

## Wave Order

| Wave | Slices | Parallel |
| --- | --- | --- |
| 0 | S0 | Operator acceptance only |
| 1 | S1 → S2 → S2b → S2c; S3 → S3b → S3c → S4 | Service and WordPress chains are file-disjoint; S2c waits for S2b |
| 2 | S5 → S6 → S7 → S8 | Serialize the chain; preserve all previous tests |
| 3 | S9a → S9 → S10 → S11a → S11; S12a → S12b → S12f → S12 → S12c → S12d | S12f starts after S9 (shared routes). S12c starts after S12 and S4. No shared-file parallelism |
| 3b | S12e → S13c → S13d → S13e → S13 → S13a → S13b | S12e waits for S12c. S13 waits for S10 and S12d. S13a waits for S11. S13c may run beside service work only before any dialog edits |
| 3c | S14a → S14a2 → S14a3 → S14a4 → S14a5 → S14a9 → S14a6 → S14a7 → S14a8 | S14a waits for S13a; every JS/docs lane waits for S11 and rebases onto it; S14a5 also waits for S13b |
| 4 | S14b → S14c → S14 (optional together); S15 | S14b waits for S8, S12c and S14a8. S15 waits for all required work and parent/operator gates |

- One owner at a time per shared file. Rebase each dependent lane onto its predecessor before its RED commit.
- No implementation lane starts while ADR-017 is Proposed.
