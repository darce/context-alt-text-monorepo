# Task Plan — DESCAUTH-1

> **Date:** 2026-10-16
> **Author:** claude (Opus 5.5)
> **Owning Epic:** none. The governing decision is [ADR-017](../../adrs/ADR-017-description-authority-wordpress-curation-service-generation.md) (Proposed), which extends [ADR-003](../../adrs/ADR-003-wordpress-local-authority-and-durable-outbox-replay.md) to descriptions.
> **Task ID:** DESCAUTH-1
> **Target Branch:** feature/descauth-1
> **Base SHA:** 2d2af05031978c29d4e4eda8d359dd32bbe73c46
> **Revision:** 1
> **Review Coverage Target:** description read path, both histories, reset/purge outbox. UI copy is reviewed via ux-map parity only.
> **Depends on:** operator acceptance of ADR-017 (S0). There is no code dependency on WBTRUST-7. WBTRUST-7 owns the provenance badge, seeded gating and naming gating, and this plan must not edit those behaviours. Both plans touch `MediaAltSuggest.tsx`; S9/S10 rebase onto whichever lands first.
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
- Every generation and every curation action is recorded append-only and joined by `generation_id`.
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
  - Checks run only on the assigned VM: service pytest via the lane `test_cmd` (`uv run --directory apps/prototype-description-service …`), PHP via composer in the lane worktree, and `vitest run --maxWorkers=1`.
  - Set OMP/MKL/OPENBLAS threads to 1. Use an outer timeout of at most 300 s and `pytest --timeout=60`.
  - Run only the changed tests, never the full suite.

## Workflow Principles

- RED test first in every code slice. Commit the RED test, then the fix.
- One slice is one lane of 1–3 owned files plus their tests. Do not widen.
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
| Service stopped, completed run | Review Queue `?run=` shows its drafts; bulk apply works; no proxy call is made |
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
  - The describe envelope gains `fresh: bool = false` (S9).
  - A new `GET /scene/describe/generations` route is added (S14).
- **Retention purge:** a `scope` of `descriptions` is added, and `all` is extended (S12). Document these in `docs/workbay/contracts/security.md`, where purge is described today.
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

| Slice | Owned files (and their tests) |
| --- | --- |
| S1 | `db/migrations/versions/001_identity_schema.py`, `db/models/scene.py`, `recognition/tests/test_identity_schema_migration.py` |
| S2 | new `scene/application/description_generation_log.py`, `scene/application/visual_facts_service.py`, `scene/interface_adapters/http/schemas/responses.py` |
| S2b | `scene/interface_adapters/http/routers/describe.py`, `scene/interface_adapters/http/routers/describe_run.py`, `docs/workbay/contracts/image-description-api.md` |
| S3 | `src/support/class-life-cycle-manager.php`, `src/sovereign/repositories/class-description-run-repository.php`; delete `src/api/services/class-description-bulk-run-service.php` and `tests/Unit/DescriptionBulkRunServiceTest.php` |
| S4 | new `src/sovereign/sync/class-description-draft-pull-job.php`, `src/api/class-api.php`, `src/api/class-describe-controller.php` (submit and membership helpers only) |
| S5 | `src/api/class-describe-controller.php` (status, items, apply) |
| S6 | `js/admin/api/describeApi.ts`, `js/admin/hooks/useQueueDrafts.ts`, `js/admin/pages/workbench/MediaSelection.tsx` |
| S7 | new `src/sovereign/repositories/class-description-event-repository.php`, `src/api/class-describe-controller.php` (apply), `src/api/services/class-description-history-service.php` |
| S8 | `src/api/services/class-describe-media-service.php`, `src/cli/class-description-command.php` |
| S9 | `scene/application/visual_facts_service.py`, `scene/application/description_repository.py`, `scene/interface_adapters/http/routers/describe.py` (+ `DescribeOptions` in `description_generation_log.py`) |
| S10 | new `src/api/services/class-description-reset-service.php`, `src/api/class-describe-controller.php` (route), `src/api/services/class-describe-media-service.php` (`fresh` passthrough) |
| S11 | `js/admin/api/describeApi.ts`, `js/admin/pages/workbench/MediaAltSuggest.tsx` |
| S12 | new `scene/application/description_purge_service.py`, `recognition/interface_adapters/http/routers/retention.py`, `recognition/interface_adapters/http/schemas/requests.py` |
| S13 | `src/api/class-retention-controller.php`, `src/sovereign/sync/class-outbox-dispatcher.php`, new `src/sovereign/sync/class-description-purge-gate.php` |
| S13b | `src/api/class-describe-controller.php` (gate calls only), `js/admin/pages/retention/retentionDialogCopy.ts`, `js/admin/pages/retention/RetentionDialogs.tsx` |
| S14a | Description Runs removal list in the slice |
| S14 | optional export: service route, WP-CLI subcommand, `scripts/eval_harness/description_history_db.py` |

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
- **Plan checks:** `make plan-analyze DOC=<this file>` and `make lint-task-plans` on every plan revision.

## Slice Delivery

### Slice S0: adr-017-acceptance

Operator gate. No code.
Canon: AGT-13.
Design decision (binding): the operator reads ADR-017 and accepts it (or amends it). Then the coordinator sets its status to `Accepted` and records a decision. **No lane for S1–S14 is dispatched before then.**
Acceptance: the ADR-017 status is Accepted, and the handoff decision id is quoted in the ADR.

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

RED: extend the parametrized table list in `test_identity_schema_migration.py` so that it expects the table, RLS enabled and forced, and the three indexes.
Acceptance: the schema test is green on the VM, and the `EXPECTED_SCHEMA_TABLES` parity test is green.

### Slice S2: generation-log-writes

Write one row per describe outcome and return its id.
Canon: PROV-01, HAI-06.
Design decision (binding):
- **Repository and sink.** The new module `description_generation_log.py` holds:
  - `GenerationOutcome(StrEnum)` with `generated` and `cache_hit`;
  - `DescribeOptions` (frozen dataclass), with `run_id: uuid.UUID | None = None` (S9 adds `fresh`);
  - `DescriptionGenerationRepository.append(row) -> uuid`, which is insert-only (no update method exists);
  - a `GenerationLogSink` Protocol, following the `AuditSink` pattern.
- **Constructor.** `VisualFactsService.__init__` gains an optional `generation_log: GenerationLogSink | None`.
- **Generated outcome.** After a successful `insert_or_get_existing` with `inserted=True`, append:
  - `outcome="generated"`;
  - `adapter_caption=result.caption` and `adapter_alt_text=result.alt_text_draft`, both from the `AdapterResult`, **before** naming;
  - `draft_sha256=sha256(final response.alt_text_draft)`;
  - `naming_status` and `named_person_count` taken from the response naming provenance (`len(names_applied)`);
  - lineage fields from the response.
- **Cache hit.** In both cache-hit branches, append:
  - `outcome="cache_hit"`;
  - `adapter_caption=_cached_unnamed_base(row)`;
  - `adapter_alt_text=None`.
- **What is never stored:** the woven draft, names or cluster ids.
- **`generation_id` field.** Add `generation_id: str | None = None` to `VisualFactsResponse` in `responses.py`. Set it to the appended row id. If there is no sink (no DB session), it stays `None`; never synthesize one (rg-015).
- **Failure rule.** An append failure must not fail the describe. Log it, increment a counter, and leave `generation_id` as `None`.
- **Run id.** `describe` gains one keyword, `options: DescribeOptions | None = None`, which brings it to 8 parameters (sr-008 limit). `run_id` is read from `options`; there is no separate keyword.

RED tests in `scene/tests/test_visual_facts_service.py`:
- a generated outcome writes one row, with the adapter caption and the unnamed text;
- a cache hit writes one `cache_hit` row;
- a sink that raises still returns the response, with `generation_id=None`;
- a test with one confirmed named person asserts that no stored column contains the name.

Acceptance: the four tests are green, and the existing visual-facts tests are unchanged.

### Slice S2b: generation-log-wiring

Wire the sink into the routes and propagate the id.
Design decision (binding):
- Construct the repository-backed sink beside each `_DescriptionAuditSink(...)` construction in `routers/describe.py` (sync, multipart and background sinks) and `routers/describe_run.py`.
- Pass `run_id` from the run worker.
- Add `"generation_id": response.generation_id` to every run-item provenance dict.
- Update `image-description-api.md`: document `generation_id` (nullable; it identifies the generation log row) and list the log columns.

RED: a router test that a bulk run item's provenance carries a non-null `generation_id` equal to a stored row id.
Acceptance: the test is green, and the contract documents the field.

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
- Add a PHP backed enum `DescriptionEventType` with `applied`, `corrected`, `discarded` and `reset`.
- Rewrite `DescriptionRunRepository` with these methods:
  - `create_run(run_id, run_kind, media_ids)`, which inserts the run and `pending` items in one `run_transactional` call;
  - `get_run`;
  - `list_items(run_id)`;
  - `upsert_items(run_id, items)`, where a row is replaced only when the incoming `result_generation` is at least the stored one;
  - `update_run_pull_state`;
  - `list_unfinished_runs(limit)`;
  - `discard_item`.
- Delete `DescriptionBulkRunService` and its test.

RED: a new `tests/Unit/DescriptionRunRepositoryTest.php` covering create, upsert, the stale-generation ignore, and discard. A schema parity test asserts the new columns. Follow `SchemaVerificationTest.php`.
Acceptance: the tests are green, and no reference to `DescriptionBulkRunService` remains (`grep`).

### Slice S4: draft-pull-job

Derive the projection from the service.
Canon: DATA-14; rule rg-007.
Design decision (binding):
- **Submit.** `submit_describe_run`: after the service accepts, call `DescriptionRunRepository::create_run`, which replaces `store_run_media_ids`. Then schedule the pull. Delete `store_run_media_ids`, `load_run_media_ids`, `remember_run_media_ids_index` and their option constants.
- **`DescriptionDraftPullJob::pull(run_id): PullOutcome`**
  1. `GET /scene/describe/run/{id}`, then `GET …/items`, both with the `post_scan_read` class.
  2. `upsert_items`, then update the run status and `last_pulled_at`.
  3. When the status is terminal **and** the items were fetched after seeing it, set `projected_complete_at`.
  4. If the counts are unchanged, increment `pull_no_progress`. At 40, set `pull_last_error='stalled'` and stop rescheduling.
  5. On a transport error, store `pull_last_error` and keep the local rows.
- **Scheduling.**
  - Hook `acx_description_draft_pull`, using the async scheduling of `SplitTopologyCommandDrain::maybe_schedule_drain`.
  - The handler pulls every row returned by `list_unfinished_runs(10)`. It reschedules itself 30 s later while any run is unfinished and not stalled.
  - Wire it in `class-api.php` like the split-topology drain.

RED (`tests/Unit/DescriptionDraftPullJobTest.php`):
- a terminal run is projected-complete after one pull;
- a run that is non-terminal and then terminal needs two pulls;
- 40 no-progress pulls end in stalled, with no reschedule;
- a transport error keeps the rows.

Acceptance: the tests are green, and the options code is gone (`grep acx_describe_run_media_ids`).

### Slice S5: local-draft-reads

Close Gap 1.
Canon: DATA-14; ADR-003 rules 1 and 9.
Design decision (binding):
- **`get_describe_run_items`**
  - Read `list_items` only.
  - If the run is not projected-complete and `last_pulled_at` is older than 5 s, call `pull()` once (bounded, errors swallowed), then read again.
  - Return the same keys plus the existing enrichment, and add `projection: {source:"local", pulled_at, stale}`.
  - `stale=true` when the last pull errored or the run is stalled.
  - An unknown run returns 404, and the route never proxies.
- **`get_describe_run_status`**
  - Keep the live proxy.
  - On a transport error or unavailable response, return the local run row with the same keys and `projection.stale=true`. If no local row exists, keep the error.
- **`apply_describe_run_drafts`**
  - Gate on the local run.
  - If the run is not projected-complete, call `pull()` once. If it is still not complete, return 409 `describe_run_not_projected`.
  - Membership comes from local items.
  - Drafts come from local rows, skipping `discarded_at` rows as `skipped_no_draft`.
  - All buckets, CAS and marker logic stay unchanged.
  - Add `generation_id` to the `build_run_apply_provenance` whitelist.

RED (`DescribeRunControllerTest.php`, `DescribeRunItemsThumbnailTest.php`):
- with the proxy transport stubbed to throw, the items and apply routes succeed for a projected-complete run;
- zero transport calls are made for that run;
- the status route falls back to local;
- a discarded item is skipped.

Acceptance: the tests are green; nothing proxies `/scene/describe/run/%s/items` except the pull job (`grep`).

### Slice S6: stale-projection-notice

Make staleness visible.
Design decision (binding):
- `describeApi.ts`: add an optional `projection?: {source: 'local'; pulled_at: string | null; stale: boolean}` to `DescribeRunItemsResponse`, and parse it leniently. If it is absent, treat it as not stale.
- `useQueueDrafts` returns `projectionStale` and `projectionPulledAt`.
- `MediaSelection.tsx` shows a status notice beside the `?run=` filter when `projectionStale` is set: "Drafts saved at {time}. Live progress unavailable." It uses `role="status"` and an icon, not colour alone (sr-004).

RED: vitest for the parser and for notice render/no-render.
Acceptance: the tests are green, and `render_ux_maps.py --check` passes. If the workbench ux-map lists notices, return a scope proposal for the map rather than editing it.

### Slice S7: curation-events-apply-and-correct

Start the WordPress history.
Canon: HAI-06, HAI-02.
Design decision (binding):
- `DescriptionEventRepository::append(event)` is insert-only.
- Bulk apply appends `applied` per item in `applied` or `partial`. The event carries `generation_id` from the item provenance, `run_id`, `draft_sha256`, `final_alt` and its sha256, and `human_edited=0`.
- `record_correction` appends `corrected`, with `human_edited=1` and `generation_id` taken from the stored provenance when present.
- An event append failure never changes the outcome bucket. Log it only, because history is not the authority.

RED: a repository test, an apply test asserting one event per applied item, and a correction test.
Acceptance: the tests are green.

### Slice S8: curation-events-other-writers

Cover the remaining alt writers.
Design decision (binding): the single-image write path in `DescribeMediaService` and the CLI write in `class-description-command.php` append `applied` events with `generation_id` from the response. Add `generation_id` to the single-image provenance whitelist.
RED: one test per writer.
Acceptance: every `update_post_meta(…'_wp_attachment_image_alt'…)` site in the plugin src has a matching event append (`grep` list in the slice report).

### Slice S9: regenerate-fresh-service

Regenerate bypasses the cache.
Canon: INT-11, RES-08.
Design decision (binding):
- Add `fresh: bool = False` to the describe envelope model parsed by `_validated_describe_multipart_submission`, and to the S2 `DescribeOptions` dataclass. Do not add a new `describe` parameter.
- When `fresh` is set:
  - skip `get_by_cache_key`;
  - after generation, call the new `ImageDescriptionRepository.replace_for_cache_key(row)`, a delete-then-insert in the same session, instead of `insert_or_get_existing`;
  - append a `generated` log row.
- Bulk runs never set `fresh`.

RED: fresh on a cached key calls the adapter once and replaces the row; non-fresh still hits the cache.
Acceptance: the tests are green.

### Slice S10: reset-one-description-wp

Per-image reset for cases like #116.
Canon: INT-11, INT-06, HAI-12.
Design decision (binding):
- Add the route `POST /acx/v1/recognition/describe/(?P<media_id>\d+)/reset` with body `{include_human_edit?: bool}` and the same capability as apply.
- `DescriptionResetService::reset(media_id, include_human_edit)` runs inside `run_transactional`:
  1. Mark every non-discarded projection item for the media as discarded.
  2. If `_wp_attachment_image_alt` equals the stored provenance draft and `_acx_description_human_edit` is not set (or `include_human_edit` is true), delete the alt, `_acx_description_provenance` and `_acx_description_provenance_pending`.
  3. Otherwise, keep the alt and report `alt_kept_human_edit`.
  4. Append a `reset` event.
- The response is `{media_id, discarded_drafts, alt_cleared, alt_kept_human_edit}`.
- `DescribeMediaService` forwards `fresh` from its request to the envelope.

RED: an unedited AI alt is cleared; a human-edited alt is kept unless opted in; drafts are discarded; the event is written.
Acceptance: the tests are green, and no service call happens during reset. It is local only, because the generation log keeps the history.

### Slice S11: regenerate-and-reset-ui

Design decision (binding):
- "Regenerate" sends `fresh: true`.
- Add a control labelled "Reset this description". It opens a confirm that states what will be cleared, using the response fields; if the alt is human-edited, the confirm offers a checkbox "Also clear my edited alt text".
- After the reset, the cell shows no draft and an empty alt.
- Use existing button styles and tokens.

RED: vitest that Regenerate posts `fresh: true`, and that the reset flow covers confirm, the call, and the empty state, with a human-edit variant.
Acceptance: the tests are green, `render_ux_maps.py --check` passes, and the copy has no banned vocabulary (`banned-vocabulary.test.tsx`).

### Slice S12: descriptions-purge-service

Service side of the tenant reset.
Canon: MLDATA-15.
Design decision (binding):
- **`DescriptionPurgeService.purge(tenant_id, scope)`**
  - If any non-terminal `image_description_runs` row or non-terminal `describe_operations` row exists, raise 409 `description_work_active`.
  - Otherwise, in one transaction, delete the tenant rows of `image_description_run_items`, `image_description_runs`, `image_descriptions` and terminal `describe_operations`.
  - For scope `all`, also delete `image_description_generations`.
  - Return the deleted counts per table.
- **Scopes.** `PURGE_SCOPES` gains `descriptions`. Scope `all` now runs the recognition purge **and** `DescriptionPurgeService(scope="all")`.
- **Request.** `PurgeRequest` accepts an optional `idempotency_key`, which is echoed back; the purge itself is idempotent.
- **Retention.** `run_startup_retention_purge` also deletes generation rows older than 365 days (fixed constant `GENERATION_LOG_RETENTION_DAYS`).

RED:
- the descriptions scope deletes the four tables and keeps the generations;
- `all` deletes the generations too;
- active work gives 409;
- a repeat purge gives zero counts;
- age retention.

Acceptance: the tests are green, and `security.md` documents the scopes.

### Slice S13: descriptions-reset-wp-outbox

WordPress-first tenant reset.
Canon: DOM-06, RES-17, INT-07, INT-06.
Design decision (binding):
- **Preview.** `GET /retention/purge/preview?scope=descriptions` returns local counts: projected drafts, AI alt texts that would be cleared, human-edited alts kept, and runs active.
- **`trigger_purge` with scope `descriptions`.**
  - Refuse with 409 when local runs are active or a `descriptions_purged` outbox row is not yet `acknowledged` or `discarded`.
  - Otherwise, in one `run_transactional` call:
    1. Delete all projection rows.
    2. Run the S10 alt/provenance clear for every attachment with AI provenance (`include_human_edit` from the request, default false).
    3. Append `reset` events.
    4. `OutboxWriter::enqueue(tenant, 'descriptions_purged', 'tenant', tenant_id, 0, 0, {scope:'descriptions'})`.
  - Return 202 with the counts.
- **Dispatcher.** `TOPOLOGY_ROUTES` gains `descriptions_purged → POST /recognition/retention/purge`, and its body is `{confirm:true, scope, idempotency_key}`.
- **Purge gate.** New `DescriptionPurgeGate::is_pending(): bool` is true while a `descriptions_purged` outbox row is neither `acknowledged` nor `discarded` (`OutboxStatus`).
- **Other scopes.** `disposed` and `all` keep today's synchronous flow. For `all`, run the local description clear after the service succeeds.

RED (PHP):
- reset with the dispatcher failing leaves local state cleared and the row pending, and `is_pending()` is true;
- after a 2xx, the row is acknowledged and `is_pending()` is false;
- an active run gives 409.

Acceptance: the tests are green.

### Slice S13b: purge-gate-and-dialog

Design decision (binding):
- `submit_describe_run` and `describe_media` return 409 `description_purge_pending` when `DescriptionPurgeGate::is_pending()` is true.
- Copy: add `PURGE_SCOPE_DESCRIPTIONS_LABEL = 'All descriptions'`, and change the `all` label to "All recognition and description data".
- The dialog fetches the preview and shows its counts before Confirm. If the preview fails, Confirm stays disabled and the reason is shown.

RED: a PHP test that describe gets 409 while the purge is pending and is allowed after acknowledgement; vitest that the preview counts render before confirm and that Confirm is disabled on preview failure.
Acceptance: the tests are green, and `render_ux_maps.py --check` passes.

### Slice S14a: remove-description-runs-page

Delete over flag.
Design decision (binding):
- Remove the `alt-context-description-history` submenu (`src/admin/class-menu.php`, both entries), `src/admin/class-description-history-page.php` and its loading in `src/admin/class-admin.php`.
- Remove from `js/admin/App.tsx` the redirect route and its entry. Delete `js/admin/pages/DescriptionHistoryPage.tsx` and `js/admin/pages/__tests__/DescriptionHistoryPage.test.tsx`.
- Update the following:
  - `js/admin/__tests__/App.test.tsx`
  - `js/admin/__tests__/banned-vocabulary.test.tsx`
  - `js/admin/pages/__tests__/menuHeadingParity.test.ts`
  - `js/admin/pages/__tests__/DescribeRunApplyView.test.tsx`
  - `tests/Unit/MenuTest.php`
  - `tests/Unit/AdminPageAutoloadTest.php`
  - `tests/e2e/smoke/deep-links.spec.ts`
  - `tests/e2e/fixtures/acx-routes.ts`
  - plugin `docs/ux-maps/dashboard.uxmap.json`; regenerate `dashboard.md` with `docs/ux-maps/render_ux_maps.py`, never by hand
  - `docs/workbay/contracts/controlled-vocabulary.json`
- Remove the remaining references in `useQueueDrafts.ts`, `MediaSelectionTableBody.tsx`, `MediaAltSuggest.tsx` and the history service. Do not edit historical reviews, assessments or old task plans.
- Split this into two lanes: PHP/tests, then JS/docs.

Acceptance: `grep -rn "alt-context-description-history\|DescriptionHistoryPage\|Description Runs" apps docs/ux-maps docs/workbay/contracts` returns nothing. Ux-map parity is green.

### Slice S14: history-export (optional, after S8)

Derived benchmark data.
Canon: STOR-07, STOR-05; FIRBENCH privacy rules.
Design decision (binding):
- Service `GET /scene/describe/generations?after=<created_at,id>&limit≤500`, tenant-scoped.
- WP-CLI `wp acx description export-history` writes JSONL to stdout. It reads the WordPress events locally and fetches generations through the proxy; this is an operator CLI, not an admin read.
- `scripts/eval_harness/description_history_db.py import --jsonl - --db PRIVATE_DB`:
  - it creates the `generations` and `events` tables keyed by `generation_id`, with an index on `image_hash` (sha256);
  - the upsert is idempotent;
  - the DB path must resolve outside every Git worktree, with mode 0700 for the directory and 0600 for the file, as in the FIRBENCH v0 rules;
  - it never stores image bytes.
- This is three lanes, one per file.

Acceptance: an importer test using a temp dir is green, the path guard refuses a path inside the repo, and a repeat import is a no-op. No real export appears in Git, logs or MCP.

### Slice S15: deploy-and-browser-reverify (operator-gated)

Design decision (binding):
- **Deploy.** The operator deploys with the greenfield schema-drift wipe: DROP SCHEMA, remove `describe-load.json`, boot the new image, `ACX_VERIFY_ATTEMPTS=12`. Then activate the plugin build.
- **Browser checks.** Verify each of the following in the browser:
  1. A run's drafts stay visible after stopping the service.
  2. Bulk apply writes `applied` events carrying `generation_id`.
  3. Regenerate gives a new draft.
  4. Reset #116 clears its AI alt.
  5. Reset all leaves the outbox pending while the service is down, then acknowledged once it is back.
- No GPU actuation by agents.

Acceptance: an evidence summary with counts only, and a slice-complete decision per the template.

## Wave Order

| Wave | Slices | Parallel |
| --- | --- | --- |
| 0 | S0 | — |
| 1 | S1 → S2 → S2b (service); S3 → S4 (WordPress) | service ∥ WordPress |
| 2 | S5 → (S6 ∥ S7) → S8 | S7 waits for S5 (shared controller) |
| 3 | S9 → S10 → S11; S12 → S13 → S13b; S14a | three chains; S13b waits for S10 (shared controller) |
| 4 | S14 (optional); S15 | — |
