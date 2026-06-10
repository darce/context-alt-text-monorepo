# REFA-4. Decompose `class-analysis-jobs-controller.php`

> **Metadata**
>
> - **Date**: 2026-06-08
> - **Author**: Claude (claude-opus-4-8)
> - **Owning Epic**: `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`
> - **Epic Short ID**: REFA
> - **Target Branch**: `feature/refa-4`
> - **Review Coverage Target**: 2
>
> **Review coverage note:** Finding/coverage state is DB-generated. Query with
> `review_findings(operation=list, task_ref=REFA-4)` / `review_runs(operation=coverage, task_ref=REFA-4)`.
> Claims verified vs `main` HEAD `19589e8` (2026-06-08).

## Objective

Reduce `src/api/class-analysis-jobs-controller.php` (1144 LOC, 35 declared methods, 8 `acx/v1` routes) to a thin composition root that delegates each operation group to a focused service under `src/api/services/`, applying **Extract Class** + **Split Phase** (fetch/transform/persist on the analyze flow), **without changing observable behavior**. Phase 3 of epic REFA.

## Problem Statement

The controller concentrates 8 route handlers plus media intake, transport switching, SSE progress streaming, batch-run lifecycle, projection-sync orchestration, and a web of transient-key helpers in one 1144-LOC class. Unlike REFA-1, it has **no inline DB transactions** (verified: zero `START TRANSACTION`/`COMMIT`/`ROLLBACK`), so the risk is not transaction timing — it is the **transport seam**, the **SSE stream shape**, the **facade delegation**, and numerous **transient/side-effect** behaviors that must survive extraction byte-for-byte.

The 8 routes (verified, all under `/recognition/`):

| Method | Route | Handler |
| --- | --- | --- |
| POST | `/recognition/analyze` | `analyze_media` |
| GET | `/recognition/batch-runs` | `get_recent_batch_runs` |
| GET | `/recognition/batch-runs/{run_id}` | `get_batch_run_status` |
| POST | `/recognition/batch-runs/{run_id}/client-failures` | `record_client_batch_failure` |
| GET | `/recognition/jobs/{job_id}` | `get_job_status` |
| GET | `/recognition/jobs/{job_id}/stream` | `stream_job_progress` *(SSE)* |
| POST | `/recognition/jobs/{job_id}/cancel` | `cancel_job` |
| POST | `/recognition/jobs/{job_id}/acknowledge-projection` | `acknowledge_projection` |

## Constraints

- **Behavior-preserving**; `acx/v1` response shapes unchanged (rg-002; no contract change).
- **Preserve the transport seam (rg-015).** `analyze_media` switches transport via the `acx_recognition_transport` filter — default `multipart` (ships bytes to `/recognition/analyze/multipart`), `url` restores the legacy JSON path. This is the exact behavior pinned by `AnalysisJobsControllerTransportTest`; the extracted analyze service must keep the filter read and both paths identical.
- **Preserve SSE stream semantics (PA-01).** `stream_job_progress` (lines 538-659) declares `WP_REST_Response|WP_Error` but sets `text/event-stream` headers, `ob_end_flush()`es, then runs a `while (! connection_aborted())` loop that **echoes SSE frames directly to output and `@flush()`es — it never returns inside the loop**. It also internally re-dispatches the job-status route (`/recognition/jobs/{job_id}`) and calls `record_observed_job_status_from_response`. Therefore it is **not** characterizable via `rest_do_request` (that would hang and capture nothing — frames are echoed, not returned). Preserve frame ordering, event names, headers, flush cadence, the `connection_aborted()` exit, and `build_stream_progress_payload` output.
- **Route-registration callbacks stay controller-resident (PA-02).** `validate_media_ids` (line 1053) is wired as a route arg `validate_callback => array( $this, 'validate_media_ids' )`, so it must remain a public method *on the controller* (a thin delegate to the service if its logic moves) — it cannot move wholesale into a service. `can_manage_recognition` is **inherited from `AbstractRecognitionProxyController`** and stays automatically; do not move or re-implement it.
- **No scattered status strings (sr-007, PA-04).** Extraction moves job-status string handling (`record_observed_job_status_from_response`, `build_offline_job_status_response`). Do not introduce new magic status-string literals across the new services; reuse an existing status constant/enum if one exists, else preserve the current comparisons verbatim (behavior-preserving).
- **Preserve facade delegation.** `class-recognition-controller.php` is a controller-of-controllers facade that injects `AnalysisJobsController` and delegates `analyze_media`/`get_job_status`/`stream_job_progress`/`cancel_job`/… The facade calls `getAnalysisJobsController()->method($request)`; those public handler signatures must remain on the controller (services sit behind them).
- **Preserve side effects exactly**: transient keys (`projection_sync_transient_key`, `job_batch_run_transient_key`, `job_media_ids_transient_key`), `BatchRunRepository` writes, projection-sync triggers (`maybe_trigger_projection_sync`), and observed-status recording. Move with their operation; do not add/drop or re-order.
- **Autoload (rg-016).** New `class-*-service.php` files are loaded two ways in this repo: the composer `classmap` (`src/`) picks them up after `composer dump-autoload`, and — matching the **actual REFA-1 implementation** — the consuming class adds explicit `require_once __DIR__ . '/services/class-…-service.php'`. Put the `require_once` in `class-analysis-jobs-controller.php` (where cluster-mutations-controller requires its host interface + services, lines 7-13), **not** `class-api.php`.
- **sr-008**: service constructors group >8 collaborators into typed objects. The controller already constructor-injects 4 deps (`SyncStateRepository`, `SyncPullJob`, `SyncPullJobFactory`, `BatchRunRepository`) via the nullable-default idiom — services reuse it.
- **Sequencing**: PHP child tasks share `src/api/` (rg-002 churn). REFA-1/REFA-2 are merged; REFA-4 shares `src/api/services/`, `class-recognition-controller.php` (facade), and the `services/` autoload block with them — no live PHP REFA task should run concurrently.

## Workflow Principles

- Safety net first: characterization for every route before extraction (Fowler Ch4) — golden-JSON for the 7 JSON routes, frame-capture for the SSE route.
- Two Hats; one cohesive service per extraction step; `composer test` + `phpstan` + `cs` green after each.
- Per-slice stop rule: any behavior diff in a golden/frame assertion, or 2 consecutive red steps with unclear cause → revert and re-plan smaller.
- Format before lint (`composer cs-fix`); never relax a gate (sr-001).
- Each slice decision cites `docs/tasks/tech-debt/refactoring-evaluation.md` (Fowler Ch7 Extract Class, Ch6 Split Phase).

## Terminology

- **Composition root**: controller keeps route registration + request parsing + the public handler signatures the facade calls, delegating logic to injected services. Mirror the nullable-constructor idiom (`?Dep $x = null` → `$x ?? new Dep()`) already used here and by `class-recognition-controller.php`.
- **Host interface (`AnalysisJobsHostInterface`)**: the seam through which extracted services call back into the controller's inherited recognition-proxy capability (`proxy_recognition_request`, `get_tenant_id`, proxy helpers). The controller `implements` it; services depend on the interface, not on `AbstractRecognitionProxyController`. Direct port of REFA-1's `ClusterMutationHostInterface`.
- **Split Phase (Fowler Ch6)**: separate `analyze_media` into fetch (resolve media → mime), transform (build/sanitize media items), persist/dispatch (store job media ids, transport-switch to recognition). Each phase becomes a method/collaborator with a clear data hand-off.
- **Characterization**: JSON routes (7) — `WP_REST_Request` via `rest_do_request()`, response serialized to a committed fixture, asserted byte-equal pre/post. SSE route (1) — **not** via `rest_do_request` (it streams + loops); instead unit-test `build_stream_progress_payload` in isolation and drive the emit loop through a bounded/abortable harness (stub `connection_aborted()` to terminate after N iterations, capture the echoed output buffer) and assert frame-equal.

## Current State Analysis

- Works: all 8 routes function; `AnalysisJobsControllerTest` + `AnalysisJobsControllerTransportTest` cover analyze transport switching.
- Insufficient: 7 of 8 routes lack full characterization; intake, streaming, batch-run lifecycle, and projection-sync logic are co-located in one 1144-LOC class with ~25 private helpers.
- Misleading: existing tests focus on analyze transport; they do not pin batch-run, job-status, stream, or projection-sync responses, giving false "covered" confidence.
- No inline transactions (verified) — simpler than REFA-1; the dominant risk is the transport/SSE/facade/transient surface, not commit timing.

## Target Outcome

`class-analysis-jobs-controller.php` shrinks to route registration + parsing + delegation, keeping the public handler signatures the facade depends on. The ~35 methods move into ~5 cohesive, unit-tested services under `src/api/services/` (`AltContext\Api\Services\`). Every route returns byte-identical `acx/v1` responses (SSE byte-identical frames); transport seam, projection-sync, and transient side effects unchanged; all existing + new tests green.

## Context Loading

- Rules: `docs/workstate/rules/backend-php-guidelines.md`, constitution (sr-008, rg-002/rg-015/rg-016).
- Injection-idiom + facade precedent: `src/api/class-recognition-controller.php`; sibling pattern: `src/api/class-cluster-mutations-controller.php` (REFA-1) + `src/api/services/`.
- Transport seam: `AnalysisJobsControllerTransportTest`, `class-recognition-proxy-policy.php` (rg-015).
- Technique: `docs/tasks/tech-debt/refactoring-evaluation.md` (Fowler Ch6/Ch7).
- Handoff: epic `REFA`; this task `REFA-4`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `acx/v1` recognition routes (8) | backend | response shapes in this controller | **none** (behavior-preserving) | no | golden-JSON parity (7) via `rest_do_request` + SSE frame parity (1) via `build_stream_progress_payload` isolation + bounded emit-loop harness (PA-01); existing analyze tests |
| recognition-controller facade | backend | delegates to `AnalysisJobsController` public handlers | **none** — handler signatures preserved | no | facade delegation tests still green |
| recognition proxy transport seam (rg-015) | backend/proxy | `acx_recognition_transport` filter (multipart/url) | **none** | no | `AnalysisJobsControllerTransportTest` byte-identical |

## Proposed Solution

Characterize all 8 routes first (JSON golden + SSE frames), then Extract Class per cohesive group into `AltContext\Api\Services\` collaborators injected via the existing nullable-constructor idiom, keeping route registration, request parsing, and the facade-facing public handlers in the controller. Services reach the inherited recognition-proxy capability through an `AnalysisJobsHostInterface` the controller implements (PR-01; mirrors REFA-1's `ClusterMutationHostInterface`), receiving `$this` as their first ctor arg. Apply Split Phase inside the analyze flow. Each new service + the host interface is `require_once`-d from `class-analysis-jobs-controller.php` (rg-016) and verified.

Service grouping (covers all 8 routes + the ~25 private helpers):

| Service | Routes / responsibility |
| --- | --- |
| `AnalyzeMediaService` | `analyze_media` + Split-Phase helpers (`analyze_media_multipart`, `resolve_image_mime_type`, `build_media_items`, `sanitize_media_item`, `extract_media_ids_from_analyze_payload`, `extract_requested_media_ids`, `diff_media_ids`, `store_job_media_ids`, `job_media_ids_transient_key`). **Owns the transport seam** (via the host's proxy wrapper — PR-01). `validate_media_ids` stays a controller-resident `validate_callback` (PA-02), delegating here if its body moves. |
| `JobStatusService` | `get_job_status`, `cancel_job`, `acknowledge_projection`, `build_offline_job_status_response`; **owns** `record_observed_job_status_from_response`. |
| `JobProgressStreamService` | `stream_job_progress`, `build_stream_progress_payload` (SSE). **Depends on `JobStatusService`** (PA-03): the stream re-dispatches the job-status route and reuses `record_observed_job_status_from_response`; inject `JobStatusService`, no duplication. |
| `BatchRunService` | `get_recent_batch_runs`, `get_batch_run_status`, `record_client_batch_failure`, `record_batch_run_success(_from_response)`, `record_batch_run_failure`, `lookup_batch_run_id_for_job`, `refresh_stale_batch_run_children`, `extract_batch_run_context`, `job_batch_run_transient_key` |
| `ProjectionSyncService` | `maybe_trigger_projection_sync`, `projection_sync_job_id`, `build_inline_projection_payload`, `projection_sync_transient_key`, `resolve_sync_pull_job` |

> **Proxy-capability access (PR-01).** Every backend-talking service reaches the inherited recognition-proxy capability through an **`AnalysisJobsHostInterface`** that `AnalysisJobsController` implements — mirroring REFA-1's `ClusterMutationHostInterface` (`src/api/interface-cluster-mutation-host.php`; `ClusterMutationsController implements …`, services take `$this` as their first ctor arg). The host exposes the inherited methods the services use: a public `proxy_recognition_request($method, $path, $body)` wrapper over the parent's protected `proxy_request`, plus `get_tenant_id()` and the proxy helpers in play (`is_proxy_unavailable`, `backend_overloaded_response`, `get_retry_after_seconds`, `should_use_local_projection_gate`, `get_proxy_policy`, `get_recognition_base_url/source/api_key`, `get_current_tier_batch_limit`). Services are constructed `new XService($this /* host */, …collaborators)` via the nullable-default idiom. This keeps `proxy_request` on `AbstractRecognitionProxyController` (no change to the parent or sibling proxy controllers) while giving services typed access — so "AnalyzeMediaService owns the transport seam" means it owns the *call sequence*, not the proxy primitive.

> **Shared-helper note (PA-03):** `record_observed_job_status_from_response` is invoked by both `get_job_status` and `stream_job_progress`. It is owned by `JobStatusService` and injected into `JobProgressStreamService`. Map any other cross-route helper before Slice 3 rather than copying it into two services.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `src/api/class-analysis-jobs-controller.php` | reduce to composition root; `implements AnalysisJobsHostInterface`; keep facade-facing public handlers; `require_once` host interface + each new service |
| backend (new) | `src/api/interface-analysis-jobs-host.php` | `AnalysisJobsHostInterface` exposing `proxy_recognition_request` + `get_tenant_id` + proxy helpers (PR-01) |
| backend (new) | `src/api/services/class-analyze-media-service.php`, `…-job-status-service.php`, `…-job-progress-stream-service.php`, `…-batch-run-service.php`, `…-projection-sync-service.php` | extracted services (`AltContext\Api\Services\`), each taking the host as first ctor arg |
| tests | `tests/Unit/AnalysisJobsController*` + new per-service tests + golden/SSE fixtures | characterization + unit coverage |

## Related Files

| File | Note |
| --- | --- |
| `src/api/class-recognition-controller.php` | facade injecting this controller — delegation must stay green; do not refactor here |
| `src/api/class-recognition-proxy-policy.php` / `class-abstract-recognition-proxy-controller.php` | rg-015 resilience seam — transport switch must not regress |
| `BatchRunRepository`, `SyncStateRepository`, `SyncPullJob(Factory)` | injected collaborators — move references, not behavior |

## Verification Strategy

- Deterministic: `cd apps/prototype-wp-alt-context && composer test && composer phpstan && composer cs-check`.
- Autoload (rg-016) per new service: `composer dump-autoload && php -l <file> && php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\\\Api\\\\Services\\\\AnalyzeMediaService'));"`.
- Contract (JSON, 7 routes): golden-JSON fixtures asserted byte-equal before vs after each extraction, with volatile fields normalized (frozen clock / stubbed ids, or masked `run_id`/timestamps — PR-04) so the assertion is deterministic.
- Contract (SSE, `stream_job_progress`): **not** via `rest_do_request` (it streams + loops). Unit-test `build_stream_progress_payload` in isolation, and drive the emit loop via a bounded/abortable harness (stub `connection_aborted()` to exit after N iterations, capture the echoed output buffer); assert event names + payload frames frame-equal pre/post.
- Transport seam: `AnalysisJobsControllerTransportTest` green for both `multipart` (default) and `url` filter values.
- Full gate before review-ready: root `make check-all`.

## Slice Delivery

### Slice 1: Characterization safety net (JSON + SSE)

**Goal**: Pin current behavior of all 8 routes before touching structure; settle the SSE characterization approach.

Changes:
- Golden-JSON fixtures via `rest_do_request()` for the 7 JSON routes (incl. side effects: transients, batch-run writes, projection-sync triggers). **Normalize non-determinism (PR-04)**: freeze the clock + stub id generation, or mask volatile fields (`run_id`, timestamps, `updated_at`) before byte-equal assertion.
- SSE: characterize `stream_job_progress` **without** `rest_do_request` (PA-01) — unit-test `build_stream_progress_payload` and a bounded/abortable emit-loop harness (stub `connection_aborted()`, capture echoed buffer); pin event names + frames.
- Map cross-route shared helpers (esp. `record_observed_job_status_from_response`) and confirm callback ownership (`validate_media_ids` controller-resident; `can_manage_recognition` inherited) before any extraction.
- **Define `AnalysisJobsHostInterface` (PR-01)**: enumerate which inherited proxy methods (`proxy_request` wrapper, `get_tenant_id`, proxy-policy/overload helpers) each service needs; `AnalysisJobsController implements` it. This precedes the first extraction.

Proof: new characterization tests green against the current controller (incl. the SSE harness + deterministic golden fixtures); host interface declared + controller implements it; existing analyze/transport tests green; `composer test` green.

### Slice 2: Extract `BatchRunService` + `ProjectionSyncService`

**Goal**: Move the two lowest-risk, side-effect-bearing groups first (no transport/SSE coupling).

Changes:
- `BatchRunService` (batch-run routes + helpers) and `ProjectionSyncService` (projection-sync helpers), each taking the host (`$this`) as first ctor arg for proxy access (PR-01); controller delegates; `require_once` host interface + services, verify (rg-016).

Proof: batch-run + projection golden fixtures byte-identical; per-service tests; phpstan/cs green.

### Slice 3: Extract `JobStatusService` + `JobProgressStreamService`

**Goal**: Move job status/cancel/acknowledge and the SSE stream (stream extracted separately due to shape).

Changes:
- `JobStatusService` (`get_job_status`, `cancel_job`, `acknowledge_projection` + `build_offline_job_status_response`); it **owns** `record_observed_job_status_from_response`.
- `JobProgressStreamService` (`stream_job_progress`, `build_stream_progress_payload`) **injects `JobStatusService`** for the shared helper + re-dispatch (PA-03) — no duplication; controller delegates both.

Proof: job-status golden fixtures byte-identical; SSE frames frame-identical via the bounded harness (not `rest_do_request`); per-service tests; phpstan/cs green.

### Slice 4: Extract `AnalyzeMediaService` (Split Phase) + thin controller

**Goal**: Move the analyze flow with Split Phase (fetch/transform/persist), preserving the transport seam; controller becomes thin dispatch.

Changes:
- `AnalyzeMediaService` owning `analyze_media` + intake/transport helpers, internally structured as fetch → transform → persist/dispatch; controller reduced to registration + parsing + delegation.

Proof: analyze golden fixtures byte-identical; `AnalysisJobsControllerTransportTest` green for `multipart` + `url`; all 8 routes characterized green; `make check-all` green.

---

## Consolidated Checklist

> Describe work delivered, not finding status (query `review_findings(operation=list, status=open, task_ref=REFA-4)`).

## Context and Ownership

- [ ] Loaded backend-php guidelines + constitution (sr-008, rg-002/rg-015/rg-016) and the Fowler evaluation.
- [ ] Confirmed `ctx7` not required.
- [ ] Recorded `acx/v1` + facade + transport-seam boundary ownership = backend, expected change = none.

### Checklist for Slice 1: Characterization safety net

- [ ] Golden-JSON fixtures for the 7 JSON routes (incl. side effects) committed, with volatile fields normalized for deterministic byte-equal (PR-04).
- [ ] SSE characterized via `build_stream_progress_payload` + bounded emit-loop harness (not `rest_do_request`); event names + frames pinned.
- [ ] Shared helpers mapped (`record_observed_job_status_from_response`) + callback ownership confirmed (`validate_media_ids` controller-resident; `can_manage_recognition` inherited).
- [ ] `AnalysisJobsHostInterface` defined (proxy surface enumerated per service); `AnalysisJobsController implements` it (PR-01).
- [ ] Characterization + existing transport tests green against the current controller.

### Checklist for Slice 2: Extract batch-run + projection-sync services

- [ ] `BatchRunService` + `ProjectionSyncService` under `src/api/services/`; controller delegates; `require_once` added + verified (rg-016).
- [ ] batch-run + projection golden fixtures byte-identical; per-service tests green.

### Checklist for Slice 3: Extract job-status + stream services

- [ ] `JobStatusService` (owns `record_observed_job_status_from_response`) + `JobProgressStreamService` (injects `JobStatusService`, no helper duplication) extracted; SSE frames preserved.
- [ ] job-status golden fixtures byte-identical; SSE frames frame-identical via the bounded harness; per-service tests green.

### Checklist for Slice 4: Extract analyze service (Split Phase); thin controller

- [ ] `AnalyzeMediaService` extracted with fetch/transform/persist phases; transport seam preserved; controller reduced to composition root.
- [ ] analyze golden fixtures byte-identical; transport test green (multipart + url); all 8 routes green; `make check-all` green.

## Review Readiness

- [ ] Every extracted route has golden-JSON (or SSE-frame) + unit evidence; no behavior-touching change without proof.
- [ ] rg-016 autoload checks run for each new service.
- [ ] Facade delegation + transport seam verified intact.
- [ ] Handoff decision records moves, verification, citation, and confirms no `acx/v1` shape change.

## Stretch Goals

- [ ] Note any `run_transactional` opportunity for the epic's deferred wrapper slice (none expected — controller has no inline transactions; record if found).

## Success Criteria

- [ ] Controller reduced to a thin composition root implementing `AnalysisJobsHostInterface`; all 8 routes delegated to ~5 unit-tested services (each receiving the host); facade-facing handler signatures preserved.
- [ ] All 8 `acx/v1` routes return byte-identical responses (7 golden JSON + 1 SSE frame parity); transport seam unchanged.
- [ ] `make check-all` green at HEAD.
