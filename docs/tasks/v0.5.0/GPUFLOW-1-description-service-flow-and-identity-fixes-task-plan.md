# Task Plan — GPUFLOW-1

> **Metadata**
>
> - **Date**: 2026-09-13
> - **Author**: Claude Opus 5 (claude-opus-5)
> - **Owning Epic**: [E23 GPU Operator Control and Named Captions](../../epics/v0.5.0/gpu-operator-control-and-named-captions-epic.md)
> - **Epic Short ID**: GPUOPS
> - **Task ID**: `GPUFLOW-1`
> - **Target Branch**: `feature/gpuflow-1`
> - **Review Coverage Target**: 1 (one harmonizing plan review before implementation)
> - **Prior art**: GPUUX-1 (lifecycle state + toasts), GPUOPS-1 (intent file, SPA card, naming flag), IDCHIP-1 (identity chips, deferred mediums), GPU-LAUNCH-1 research §5–§10, FIR v11 report `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`
> - **Triage decisions**: `GPUFLOW-1-D-TRIAGE-STALE-API-20260913`, `GPUFLOW-1-D-TRIAGE-IDENTITY-UI-20260913` (handoff)

## GPUFLOW-1. Description Service flow, ramp-up timing, and identity review fixes

## Objective

An operator on demo.altcontext.com can press Suggest on a cold system and see the Description Service start, warm, and describe, with ramp-up time shown separately from per-image processing time. The live identity defects from plugin 0.0.21 and the five IDCHIP-1 deferred mediums are fixed in the same wave.

## Problem Statement

Plugin 0.0.21 on the demo shows eight live defects. Three causes explain most of them.

1. **Stale API image.** The deployed description-service image is `f66c5335` (2026-09-03), 609 service commits behind `main`. `/scene/gpu/status`, `/scene/gpu/intent` and `/recognition/tenant/naming-agreement` return 404, and `/ready` is unhealthy (centroid dim −1, already fixed on main by `34924c344`). This produces the Settings "HTTP 404" alert, the disabled "Include named people" checkbox and the missing GPU control.
2. **The GPU never learns there is work, and failures are opaque.**
   - The sync `/scene/describe/multipart` path used by WP Suggest never writes a load snapshot. Only the async routes call `_maybe_dump_describe_load`, so the lifecycle controller's `has_work` stays false and a stopped GPU is never started.
   - `describe_image_multipart` (`scene/interface_adapters/http/routers/describe.py:333-442`) catches `TimeoutError`, `DescriptionAdapterUnavailableError` and `HostedProviderError` but not `GpuRemoteAdapterError`. A cold-GPU connection failure therefore becomes an opaque 500.
   - The PHP recognition circuit breaker is keyed only by base URL (`AbstractRecognitionProxyController::build_circuit_breaker_key`). Two describe 500s trip it for 60 s, so the retention reads short-circuit and Retry looks inert. Retry also shows no fetching feedback.
3. **Identity quality is blind to occlusion.**
   - The representative score (`compute_identity_quality`) uses only confidence and bbox. The enrollment floors default to no-op, so a microphone-occluded face can become the avatar.
   - The suggestion card can render the candidate as its own representative (the `stale_accepted_without_membership` replay in `suggestion_repository.list_pending_with_details`), which shows two identical avatars.
   - Wrong-person suggestions (Trudeau → Watson) sit inside the 0.35–0.55 suggestion band.
   - The name listbox opens on page load (`NameFaceControl.tsx:247`, `useState(true)`).

No measured cold-start or per-image latency exists anywhere. `ACX_GPU_WARMUP_TIMEOUT_SECONDS=510` and the 180 s generation cap are ceilings, not observations. The GPU-LAUNCH-1 §8 acceptance metric (queue, warmup, inference and poll split) is unimplemented.

## Constraints

- **E23 hard constraints hold.**
  - One writer per file: the lifecycle unit owns `gpu-state.json` and the service owns `gpu-intent.json` and `describe-load.json`.
  - The cost backstop (`--max-lease-seconds`) always wins.
  - No agent performs live GPU actuation; the live smoke is operator-run.
- **Production promotion is operator-confirmed.**
  - The path is `make deploy-dev` (REMOTE_BUILD=1) → `make deploy-promote-staging` → `make deploy-promote-prod CONFIRM=...`, then `make deploy-demo` for the plugin zip.
  - No lane runs these targets.
- **Keep the public demo ceiling.** The 120 s client ceiling is unchanged, and no PHP request is held open for a cold boot (about 104 s to health 200 per GPUUX-1).
- **Pass boundaries through verbatim (rg-015).** PHP and SPA never synthesize GPU state, tier or timing. Every displayed timing field comes from the service.
- **Take tier labels from `description_tier`, never `gpu_state`.**
- **Suggestion thresholds are evidence-gated.** `suggestion_floor` and `similarity_threshold` change only with a recorded repro and calibration evidence (FIR D-08: no declared acceptance threshold; rank-1 margin is inadmissible for an open gallery).
- **The occlusion signal is weak.** FIR v11 calls the occlusion proxy an eye-patch heuristic, so any representative-quality change must be calibrated, and the postmerge contract tests that pin the current behaviour are updated deliberately in the same slice.
- **Greenfield rules apply.** Schema changes go in `001_identity_schema.py`, with no migrations and no shims.
- **Design tokens only (sr-004); centralized status vocabularies (sr-007).**
- **Lanes stay narrow.** Each owns 1–3 files plus its tests; wide briefs exhaust the remote wall clock.

## Workflow Principles

- **Promote before patching.** Routes that exist on main but 404 live are a deploy defect, not a code defect. Re-verify each live symptom after promotion before spending a lane on it.
- **Fail fast, register demand.** A cold GPU produces a typed, retryable response plus a demand signal. It never produces a long-held request or an opaque 500.
- **Measure, then budget.** Timing instrumentation lands before any latency target is asserted. Budgets from `gpu-detailed-tier-oci-bursty-scope.md` (warm-start p95 ≤ 90 s) are checked against the operator smoke evidence, not assumed.
- **Plain operator language.** The UI says "Description Service", never "Burst GPU", "A10" or "lease" in primary copy.

## Terminology

- **Ramp-up time** (`ramp_up_ms`): this operation's wait from first eligible GPU demand to first service-observed readiness, retained across retries. Whole startup duration (`startup_ms`) belongs to the shared startup_id and may be longer for callers joining late; it is null if startup start was not observed.
- **Processing time**: per image, from dispatch to the realizer until a result is returned (inference plus transport), excluding the ramp-up wait.
- **Queue time**: run enqueue to worker pickup, counted once; per-item scheduling delay is separate from run readiness wait.
- **Server elapsed time** (`server_elapsed_ms`): service operation acceptance to response completion, including gaps between correlated retries. It excludes client action-to-receipt and response-to-render. Concurrent item durations are not summed into elapsed time; client action-to-render telemetry is out of scope.
- **Demand lease**: expiring service-owned durable demand retained beyond a warming response and aggregated into every `describe-load.json` publication.

## Current State Analysis

**Works on main:**

- GPU lifecycle controller, intent file and `GpuControlCard` (Start/Stop/Auto, warmup ETA, lease).
- `gpu_state` passthrough and toasts (GPUUX-1).
- Async describe routes that publish load snapshots.
- `recompute_representatives` runs at 13 call sites, so avatars already update when membership changes.

**Broken live:**

- Stale image (P0).
- Sync Suggest cannot wake the GPU and returns 500.
- A shared breaker couples describe failures to retention reads.
- Retention Retry gives no feedback.
- "Burst GPU" jargon in the card title and copy.
- Listbox open on load.
- Occluded representative avatars.
- Duplicate suggestion avatars.
- A possible wrong-person suggestion.

**Misleading today:**

- Timeout caps read as if they were latencies.
- `description_adapter_duration_seconds` merges GPU wait and inference into one histogram.
- `test_fir2_br_postmerge_contracts.py` and `test_fir_final_postmerge_runtime_contracts.py` pin occlusion-blind representative ranking as intended behaviour.

## Target Outcome

Suggest requiring GPU compute on a stopped GPU under Auto intent returns within a few seconds with `503 description_service_starting` and `Retry-After`, and it publishes a demand lease. The SPA shows "Description Service is starting — about N s" when the service supplies a warmup ETA (otherwise omit the estimate) and retries on its own until ready or until the 120 s public ceiling. It then renders the draft with a timing line: "Waited for service 1 m 42 s · described in 6.1 s". Bulk runs show run-level ramp-up once plus per-image processing (median and slowest).

Settings shows "Description Service" with live state. The naming toggle is enabled when the tenant flag is readable, and retention loads independently of describe failures.

In the identity UI:

- The name listbox is closed on load.
- Representatives prefer unoccluded, sharp faces and change as better images arrive.
- A suggestion card never shows the candidate as its own representative.
- Wrong-match evidence decides any threshold change.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `frontend-guidelines.md`, `backend-php-guidelines.md`, `testing-python.md`, `testing-typescript.md`, `testing-php.md`
- Contracts:
  - `docs/workbay/contracts/gpu-lifecycle.md`
  - `packages/shared-contracts/schemas/scene-describe-run.schema.json`
  - `packages/shared-contracts/schemas/scene-describe-multipart.schema.json` (new)
- UX maps:
  - `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.md`
  - `gpu-operator-control.md`
  - `public-demo-describe.uxmap.json`
- Scopes: `docs/scopes/gpu-detailed-tier-oci-bursty-scope.md` (PA-01 budgets), `docs/scopes/cpu-gpu-lane-control-plane.md`
- Assessment: `docs/assessments/GPU-LAUNCH-1-research-and-ux-20260909.md` §5–§10 (guided-live states, §8 latency split)
- Handoff:
  - GPUFLOW-1 triage decisions.
  - IDCHIP-1 deferred mediums, by id in handoff: INTFIX-AV-R-04/05/06, INTFIX-UI-R-01, API-R-23.
  - GPU-LAUNCH-1 open highs (query live; do not mirror).

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `POST /scene/describe/multipart` error envelope | description-service | 500 on GPU adapter failure | `503` + `code=description_service_starting` + `Retry-After` + `warmup_eta_seconds` when actual GPU compute is eligible for startup; `502 description_service_error` on a realizer failure after ready | no (greenfield) | pytest route tests + schema fixture |
| `describe-load.json` producer set | description-service → lifecycle controller | async routes only | sync path publishes a demand lease (single writer unchanged: still the service) | no | `test_describe_load.py` + controller `has_work` test |
| `timing` object on describe responses | description-service → PHP → SPA | absent | `timing{queue_ms, ramp_up_ms, processing_ms, startup_ms, server_elapsed_ms}` on multipart; run-level `timing{queue_ms, ramp_up_ms, processing_ms_p50, processing_ms_max, items_timed, startup_ms, server_elapsed_ms}` plus per-item `processing_ms` on describe-run | no | shared-schema test on the real builder; PHP passthrough test |
| WP describe proxy → SPA | PHP plugin | opaque `Could not generate a draft` | pass the status, `code`, `Retry-After`, `warmup_eta_seconds`, `operation_id`, `startup_id` and `timing` through verbatim | no | PHPUnit passthrough |
| PHP circuit-breaker key | PHP plugin | per base URL | per base URL + route family (`describe`, `ui_read`, `control`) | no | PHPUnit: describe failures do not open `ui_read` |
| Suggestion details payload | recognition-service | representative may equal candidate | representative excludes the candidate identity; null when none exists | no | pytest repository test + SPA placeholder test |

### Open decisions

The operator/API-R-23 owner decides the D2 cap and whether it bounds admission or stored undo payloads; default: preserve existing behavior and block D2 dispatch until the brief is accepted. The lifecycle operator supplies deployed polling/freshness/jitter bounds for A1; default: do not claim guaranteed startup or dispatch the lease consumer without them. The operator accepts C3 calibration; default: retain assignment thresholds and representative policy until accepted evidence exists.

The orchestrator preserves review commit `59ced8b` (report-only, `docs/workbay/reports/GPUFLOW-1-plan-review.md`) as review evidence, not implementation. GPUFLO-L-01 is resolved by this provenance and incorporation of its contract findings; its static checks prove no runtime behavior. The handoff IDs are authoritative: the inlined review uses different numbering. Re-review the revised plan with luna max before freezing/materializing implementation lanes.

## Proposed Solution

The work is five tracks and one release gate.

- **P0 — promote.** The operator promotes `main` through dev → staging → prod. An agent then verifies nonactuating routes and `/ready` read-only and classifies operator-recorded defect reproductions, and any defect that disappears is closed as deploy skew.
- **Track A — Description Service flow.**
  - Typed GPU errors on the sync path.
  - Demand lease plus a fail-fast warming response.
  - Breaker scoping per route family.
  - SPA warming/retry state for Suggest.
  - "Description Service" rename.
  - Retention retry feedback.
- **Track B — timing.** Phase timestamps are captured in the service (sync path and describe-run worker), exposed as a `timing` object, passed through PHP, and rendered in the SPA as ramp-up versus processing. The operator smoke records a cold run and a warm run as an evidence bundle.
- **Track C — identity fixes.**
  - Listbox closed on load.
  - Suggestion representative excludes the candidate.
  - Wrong-match repro analysis.
  - Calibrated occlusion/sharpness-aware representative selection.
- **Track D — IDCHIP-1 mediums.** Anchor picker disabled reason, group preview fallback chain, FaceThumbnail croppable gate, persistent/dismissible undo, `cluster_count` cap.
- **Release gate.** Plugin bump, `make deploy-demo`, operator GPU smoke (stopped/Auto → Suggest cold without preceding Start → Suggest warm → bulk run of 5 → Stop; explicit Start tested separately) with the timing evidence, then `handoff_close_check(enforce=True)`.

## Files and Surfaces to Change

The Lane Decomposition is the authoritative exhaustive ownership list, including storage, response models, instrumentation and canonical UX JSON omitted from this surface summary.

| Surface | File | Change |
| --- | --- | --- |
| backend | `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py` | catch `GpuRemoteAdapterError`; eligible GPU startup → typed 503 + retained demand lease; timing capture on the sync path |
| backend | `apps/prototype-description-service/scene/application/describe_load.py` | demand-lease helper for the sync path (durable expiring registration aggregated by every publisher) |
| backend | `apps/prototype-description-service/scene/application/describe_run_worker.py` | record queue/ramp-up/per-item processing timestamps around `_wait_for_gpu_ready` and item dispatch |
| backend | `apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py` | expose run `timing` + per-item `processing_ms` |
| contracts | `packages/shared-contracts/schemas/scene-describe-run.schema.json` and `packages/shared-contracts/schemas/scene-describe-multipart.schema.json` | `timing` object, error `code` enum |
| docs | `docs/workbay/contracts/gpu-lifecycle.md` | sync-path demand lease as a documented producer |
| PHP | `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | route-family breaker key |
| PHP | `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php` | pass through status/code/Retry-After/timing |
| PHP | `apps/prototype-wp-alt-context/src/api/services/class-person-merge-service.php` | cap `cluster_count` + PHPUnit |
| SPA | `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx` (+ test) | "Description Service" title and copy |
| SPA | `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAltSuggest.tsx`, `js/admin/hooks/useDescribeMedia.ts`, `js/admin/api/describeApi.ts` (separate lanes below) | warming state, auto-retry within 120 s, timing line |
| SPA | describe-run progress (`MediaSelection.tsx` / `useDescribeRunProgress`) | ramp-up vs processing summary |
| SPA | `apps/prototype-wp-alt-context/js/admin/pages/retention/RetentionPage.tsx` | Retry shows fetching state and last error |
| SPA | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx` (+ new test) | `useState(false)`; group preview fallback chain |
| SPA | `.../identity-clusters/SuggestionCards.tsx` (+ new test) | null-representative placeholder; `isCroppableBbox` gate |
| SPA | `.../identity-clusters/IdentityClusterItem.tsx` | anchor picker disabled with reason |
| SPA | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/MergeUndoBanner.tsx` | dismissible while retryable; token persisted past 30 s |
| backend | `apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py` | representative excludes candidate identity |
| backend | `recognition/application/persistence/representative_selector.py`, `recognition/application/settings/clustering.py`, `recognition/application/persistence/assignment_writer.py` | calibrated occlusion/sharpness factor in representative ranking |
| tests | `test_representative_quality_gate.py`, `test_representative_selector.py`, `test_assignment_writer.py`, `test_fir2_br_postmerge_contracts.py`, `test_fir_final_postmerge_runtime_contracts.py` | deliberate update to the new ranking contract |
| docs | `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.md`, `gpu-operator-control.md` | warming/retry/timing states; rename |
| reports | `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` | analysis-lane output |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scene/interface_adapters/http/deps.py:91-118` | GPU adapter resolution |
| `apps/prototype-description-service/scene/infrastructure/.../gpu_remote_adapter.py:180,260-313` | wraps every failure as `GpuRemoteAdapterError` |
| `apps/prototype-description-service/scene/interface_adapters/http/routers/gpu.py:130-143` | `GpuStatusResponse` (warmup ETA source) |
| `infra/oci/gpu_lifecycle/controller.py:87-92` | `has_work` gate |
| `apps/prototype-wp-alt-context/src/api/class-settings-controller.php:371-447` | naming-agreement read (bypasses shared proxy) |
| `apps/prototype-wp-alt-context/src/api/class-retention-controller.php:175-207,380-386` | degraded status payload |
| `recognition/application/persistence/representative_selector.py:130-137,498-541` | no-op multiplier, preserve set |
| `recognition/application/persistence/assignment_writer.py:567-653` | `recompute_representatives` |
| `recognition/interface_adapters/http/routers/suggestions.py:321-364,835-871` | accept / merge target |
| `mk/deploy.mk:120-160,243` | promote and demo deploy targets |

## Verification Strategy

- **Deterministic tests**: run the exact lane-local commands in the Lanes table first, using the lane-root interpreter and import-origin check specified there. The following broad Python `-k` commands are optional aggregate verification after lane-local tests (same interpreter setup); they are not dispatch `test_cmd` values:
  - `python3 -m pytest apps/prototype-description-service/scene/tests -k "describe or describe_load or describe_run or gpu"`
  - `python3 -m pytest apps/prototype-description-service/recognition/tests -k "representative or suggestion or assignment_writer or postmerge"`
  - `npx vitest run js/admin/pages/settings js/admin/pages/retention js/admin/pages/workbench/identity-clusters` (from `apps/prototype-wp-alt-context`)
  - `vendor/bin/phpunit --filter "Proxy|DescribeMedia|PersonMerge|Retention"` (local, per worktree composer provisioning)
- **Contract checks:**
  - The shared-schema test validates the real multipart and describe-run response builders, including `timing` and error `code`.
  - `render_ux_maps.py --check` runs after the ux-map edits.
- **Runtime parity (read-only agent checks after promotion):**
  - `curl` `/ready`, `/scene/gpu/status` and `/recognition/tenant/naming-agreement` on each environment's `127.0.0.1:8000` and expect 200.
  - Confirm the image SHA matches the promoted `main` SHA.
- **Operator smoke (release gate, operator-run):**
  - GPU stopped with Auto intent → Suggest on one image without preceding Start; record `ramp_up_ms` and `processing_ms`.
  - Immediately Suggest again warm; `ramp_up_ms` ≈ 0.
  - Describe run of 5 images; record run `timing`.
  - Stop from the SPA.
  - Export the EVID-1 bundle and record it as `test_result` on the merge SHA.
  - Compare against PA-01 (warm-start p95 ≤ 90 s) and report the gap. The budget is not asserted with n = 1.
- **Manual UI checks:**
  - Workbench: listbox closed; suggestion avatars distinct; representative avatars.
  - Settings: "Description Service" card and naming toggle enabled.
  - Retention: loads after a describe failure; Retry shows progress.

## Slice Delivery

### Slice 0: Promote main and re-baseline live defects (operator + read-only agent)

**Goal**: The live API matches `main`, and every remaining defect is reproduced on current code.

Changes:

- Operator runs the promotion chain.
  - Precondition: VM disk below 70% (OPS-1 hygiene) so the remote build does not fail.
- Agent verifies routes, `/ready` and image SHA read-only.
- Operator reproduces all live Suggest/run/Start/Stop actions, including rebaseline. Agents inspect only nonactuating routes and recorded evidence, and classify defects 3, 5, 7 and 8 from that evidence.
- Analysis lane (luna max): classify persisting defects and pull the live Trudeau/Watson suggestion row (similarity, band, representative identity id, quality, occlusion score) into the calibration report.

Proof:

- Decision records the image SHA and route status codes.
- Re-baseline table in a handoff decision (not in this plan).

### Slice A1: Typed cold-GPU response and demand lease (backend)

**Goal**: A stopped GPU yields a fast, typed, retryable response and a start signal instead of a 500.

Changes:

- After validation, adapter selection and cache/decorative bypass handling, the `before_compute` boundary registers demand only for actual GPU compute. CPU, hosted and non-GPU default adapters remain usable without demand or readiness checks.
- Stopped/Auto and a known policy-permitted startup return fast `503 description_service_starting`; operator STOP, stopping, unavailable or stale/unknown state return `503 description_service_unavailable` without automatic-start promises or ETA. STOP and max-lease always win.
- Persist each tenant-scoped operation lease in the shared service database before publishing or responding. A 503 does not release it in `finally`. Retries renew the same operation lease; concurrent operations have separate leases. Every periodic, async and sync publication aggregates unexpired leases with queued/running async GPU work under the existing service writer/fence. The demand publisher also persists the first observed ready transition for active startup/operation records on its periodic pass, so readiness between HTTP retries is retained. Serialize database snapshot and file publication so an older snapshot cannot overwrite newer demand; never introduce a lifecycle writer.
- Lease lifetime L must exceed controller poll period P + worst scheduling jitter J + publication delay D; refresh interval R + D must remain below load-reader freshness F. The contract producer records deployed P/J/D/F and an explicit bounded L before dispatch; unavailable bounds block startup implementation. Lease expiry removes abandoned demand; renewal cannot extend lifecycle max-lease or override STOP.
- A `GpuRemoteAdapterError` after ready returns `502 description_service_error`. Contract/schema producers land before route implementation.

Proof:

- Route tests cover CPU/hosted/default selection, cache/decorative bypass, STOP, stopping, unknown, eligible cold GPU, warm success, adapter failure and timeout.
- Fake-clock controller tests complete the 503 before the next controller poll, interleave periodic/async publication and concurrent requests, and verify retained `has_work`, renewal, expiry and stale-publication rejection across processes.

### Slice A2: Route-family breaker and verbatim error passthrough (PHP)

**Goal**: Describe failures cannot blank retention or settings reads, and the SPA receives the typed error.

Changes:

- All failure counters, locks, open state and success resets use the same canonical base-URL/route-family key. Classify explicit route paths into describe, ui_read and control (not HTTP method). Validate status 503 plus the typed `description_service_starting` envelope before failure accounting: warming never increments or opens the breaker; malformed warming and real 502/5xx still count.
- The describe media service passes status, `code`, `Retry-After`, `warmup_eta_seconds`, `operation_id`, `startup_id` and `timing` through.
- The naming-agreement read reports the upstream status and code.

Proof:

- PHPUnit: repeated warming beyond the failure threshold leaves describe closed and preserves Retry-After/ETA/code on every retry; real describe failures open only describe; cross-family counters and success resets remain isolated.
- PHPUnit: passthrough of every error code and absent fields.

### Slice A3: Description Service UI (SPA)

**Goal**: Operators see plain-language service state, and Suggest recovers from a cold start by itself.

Changes:

- `GpuControlCard` title becomes "Settings › Description Service", and copy drops GPU jargon from primary text.
- Suggest maps `description_service_starting` to a warming state with the ETA and auto-retries honouring `Retry-After`. It stops at the 120 s ceiling with a clear "still starting — try again" action.
- Retention Retry shows fetching state.
- UX maps updated.

Proof:

- vitest covers the rename, warming/retry/ceiling, retention refetch feedback and toast suppression while warming (GPUUX-1 policy).
- uxmap parity check passes.

### Slice B1: Phase timing capture (backend)

**Goal**: Every describe response carries measured queue, ramp-up and processing time.

Changes:

- The contract producer defines `scene-describe-multipart.schema.json`, `scene-describe-run.schema.json` and strict `VisualFactsResponse`, `DescribeRunResponse`, `DescribeRunItemResponse` and `DescribeRunItemsResponse` in `scene/interface_adapters/http/schemas/responses.py`. The multipart schema covers both success and error envelopes. Errors use `detail: {code, message, operation_id, startup_id, warmup_eta_seconds, timing}`; Retry-After is an HTTP header. PHP and SPA preserve this nesting. IDs are opaque strings; startup_id and ETA are nullable; unavailable responses omit ETA. Success carries IDs and timing at top level. Unknown/untimed values are null, never invented zeroes; older responses may omit timing entirely.
- A service-minted operation_id is returned on first acceptance and resubmitted by retries, bound to tenant and request digest. Mismatched tokens are rejected; expired tokens return a typed operation_expired response and require a new operation. Persist operation acceptance, expiry, startup association and first readiness observation in the database. Retain completed timing for the existing async-job retention window; active renewal is bounded by that window. Distinct callers join one startup_id but keep individual operation readiness waits. Service restart preserves correlation; cross-process durations use stored UTC observations with nonnegative validation, while adapter attempts use local monotonic clocks.
- `ramp_up_ms` measures this operation's readiness wait; `startup_ms` measures the whole startup only when its start was observed, otherwise null. Warm/cache responses have zero readiness wait, no startup association, and cache has zero processing. A retry after readiness reads the retained first-ready observation rather than resetting its clock.
- Add durable run/item timing and the operation/lease tables in `db/migrations/versions/001_identity_schema.py` and `db/models/scene.py`; repository and domain producers follow, then worker/router consumers. No additional migrations or shims. Builders read persisted values including failed, cancelled and untimed items.
- Capture run queue once at worker pickup; readiness checks on warm runs do not imply cold ramp-up. Measure each adapter attempt at actual dispatch in `visual_facts_service.py`, excluding naming lookup, preview and retry backoff. Item processing is the sum of its measured attempts; run p50/max and items_timed cover measured items only, never substitute summed parallel work for wall elapsed.
- Split the histogram in `recognition/interface_adapters/http/middleware/metrics.py` into readiness wait and adapter processing with nonoverlapping observations.

Proof:

- Fake-clock tests cover 503 then successful retry, concurrent callers joining startup, late readiness, warm/cache paths, expiry, restart, retries, parallel runs, failed/cancelled/untimed items and no double-counting.
- Validate actual multipart and run/item serialized builders against shared schemas after database round trips; strict response models accept the declared fields. PHP consumers start only after these fixtures are final.

### Slice B2: Timing display and evidence (PHP passthrough + SPA)

**Goal**: The operator can tell ramp-up from processing for a single Suggest and for a run.

Changes:

- PHP passthrough of `timing`.
- The SPA timing line labels operation ramp-up as waiting for service, reserving “Started in” for a known startup_ms; the run summary shows ramp-up once, plus median and slowest per-image processing. Values come only from the wire.
- The evidence-bundle field mapping is documented for the operator smoke.

Proof:

- PHPUnit passthrough.
- vitest formatting covers absent timing (renders nothing), zero ramp-up and multi-item runs.

### Slice C1: Listbox closed on load and group preview fallback (SPA)

**Goal**: The naming control opens only on user intent, and the group preview never renders empty.

Changes:

- `NameFaceControl` initial `listOpen=false`.
- Group preview fallback order: `representative_face` → first member → placeholder (IDCHIP-1 AV-R-04).

Proof:

- New `NameFaceControl.test.tsx`: closed on mount, opens on typing and ArrowDown, preview fallback order.

### Slice C2: Suggestion representative never equals candidate (backend + SPA)

**Goal**: Suggestion cards show two different people or an explicit placeholder.

Changes:

- `_to_details` loads tenant-scoped target members and chooses the best representative identity other than the suggestion's identity, or null when no noncandidate exists.
- The stale replay path uses the same rule.
- `SuggestionCards` renders a placeholder for a null representative and gates `FaceThumbnail` on `isCroppableBbox` (IDCHIP-1 AV-R-06).

Proof:

- Repository test for the replay path where the representative equals the candidate.
- vitest for the placeholder and non-croppable bbox.

### Slice C3: Wrong-match and occlusion calibration analysis (analysis lane)

**Goal**: Decide from evidence whether the suggestion band or representative quality is wrong.

Changes:

- Report on the live row from Slice 0.
- FIR v11 occlusion/sharpness distributions.
- Proposed `factor_ceiling_occlusion` and `factor_floor_sharpness` values with the precision cost.
- Recommendation on `suggestion_floor` (keep, raise, or quality-adaptive margin per FIR PFE/MLS).
- No code.

Proof:

- The report file exists with numbers and a recommendation, recorded as a decision the operator accepts before C4 starts.

### Slice C4: Quality-aware representative selection (backend)

**Goal**: Cluster avatars prefer the clearest face and update as better images arrive.

Changes:

- Apply the calibrated occlusion ceiling and sharpness floor from C3 in `clustering.py` defaults.
- Use representative-only scoring across eligible existing and new members in `representative_selector.py` and `assignment_writer.py`. Preserve explicit pins and pose diversity, but do not let preservation of an unpinned pose-bucket representative force it to remain the primary avatar. Choose the primary by calibrated rank across the eligible union, with deterministic ties. Settings propagation has its own bounded producer lane.
- Update the five contract tests deliberately to the new ranking contract.
- Leave shared assignment `quality.py` and assignment thresholds unchanged. Any threshold change needs separate accepted evidence, a frozen bounded lane and its assignment tests before dispatch.

Proof:

- Tests show an occluded high-confidence face loses to a clear face, and that a newly uploaded clearer face replaces the representative on recompute.
- Pinned representatives are unchanged; test both an existing unpinned pose-bucket avatar versus a clearer newcomer and pose-free data. Keep unrelated assignment contracts intact.

### Slice D1: Anchor picker and undo persistence (SPA)

**Goal**: IDCHIP-1 picker and undo mediums are closed.

Changes:

- `IdentityClusterItem` anchor picker is disabled with a visible reason (FORM-09).
- The undo banner can be dismissed while retryable.
- The undo token persists beyond 30 s for its server-side validity window.

Proof:

- vitest: disabled reason text and `aria-describedby`; banner dismiss; token survives a 30 s fake-timer advance.

### Slice D2: Merge cluster-count cap (PHP)

**Goal**: Enforce the authoritative API-R-23 bound at its specified boundary; merge admission and stored undo payload size are distinct contracts.

Changes:

- D2 is blocked until the operator/API-R-23 contract owner supplies a compact accepted brief with numeric cap, bounded field, admission versus undo-storage scope, typed status/code and boundary cases. Do not infer a cap from nonnegative undo-record validation.

Proof:

- PHPUnit uses the accepted brief: zero, cap, cap + 1, malformed counts, and separate merge/undo behavior; no guessed numeric contract.

### Slice R: Release gate

**Goal**: A verified release on demo with a timing evidence bundle.

Changes:

- Plugin version bump and `make deploy-demo`.
- Operator smoke per the Verification Strategy.
- Final integration review.
- `handoff_close_check(enforce=True)`.

Proof:

- `?ver=` on `/guide/` matches the release.
- EVID-1 bundle recorded as `test_result` on the merge SHA.

## Lane Decomposition (Multi-Agent)

Routing (standing user order):

- Implementation lanes: codex-remote `gpt-6-astra` effort `low`.
- Analysis lanes and per-lane review twins: codex-remote `gpt-5.6-luna` effort `max`. Export `WORKBAY_CODEX_MODEL=gpt-5.6-luna` before subprocess import for these jobs and pin manifest and row identically. No tier/speed fields on lane rows.
- Plan re-review: codex-remote `gpt-5.6-luna` effort `max`; freeze the reviewed plan before any implementation lane is materialized (GRPH-39).
- Final merge-gate harmonizing review: local codex agent, checked against the heuristics canon. Local host also runs tsc/vitest/phpunit and integrates.
- Optimize time-to-verified-release: review each committed delta once, integrate each reviewed slice as it lands, then retire its worktree once its commit and evidence are preserved. Later reviews cover only fixes and integration boundaries, not unchanged deltas.

### Lanes

Paths beginning `scene/`, `recognition/` or `db/` are under `apps/prototype-description-service/`; `src/` and `js/` are under `apps/prototype-wp-alt-context/`. Other paths are repository-relative. Each lane owns at most three source/artifact files plus its tests and test fixtures. New files are explicitly marked. The exact Python test files below are owned by their row's lane; no wildcard ownership or unresolved test placeholder may be dispatched.

Run Python commands from the lane root. In each shell, resolve `lane_root="$(git rev-parse --show-toplevel)" || exit 1`, then `resolved_python="$lane_root/.venv/bin/python"`; stop if it is not executable. After `cd "$lane_root"`, repeat that resolution and bind `python3() { "$resolved_python" "$@"; }` in the same shell so the allow-listed `python3 -m pytest` commands resolve to the provisioned lane-root interpreter, never ambient Python. For service package lanes set `PYTHONPATH="$lane_root/apps/prototype-description-service"` and export it. Before trusting tests and again after the last edit, run `python3 -c "import scene, sys; print(scene.__file__)"`; stop if the printed origin is outside this lane. Package-less documentation lanes skip this package check.

In every dependency cell, the prefix names the producer and the row names the read-only consumer. Paths identify the committed artifacts transferred, including existing schema/API modules and new test fixtures that the producer must commit before consumption. New fixture ownership is explicit below; downstream lanes may read but never edit producer tests or fixtures. Operator promotion, P/J/D/F bounds and API-R-23 acceptance remain dispatch gates, not artifact-free DAG edges. Assessment and contract-document edges retain their canonical repository paths outside the application trees.

| Lane ID | Slice | Owned Paths | Upstream Dependencies (artifact transferred) | Required Tests |
| --- | --- | --- | --- | --- |
| `rebaseline` | 0 | `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` | — (operator promotion gate) | recorded SHA/routes and symptom evidence |
| `contracts` | A1/B1 | `packages/shared-contracts/schemas/scene-describe-multipart.schema.json (new)`, `packages/shared-contracts/schemas/scene-describe-run.schema.json`, `docs/workbay/contracts/gpu-lifecycle.md` | rebaseline: `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` | schema fixtures; lease/freshness contract review |
| `timing-models` | B1 | `db/migrations/versions/001_identity_schema.py`, `db/models/scene.py`; `apps/prototype-description-service/scene/tests/test_gpuflow_timing_models.py` (new test) | contracts: `packages/shared-contracts/schemas/scene-describe-run.schema.json`, `docs/workbay/contracts/gpu-lifecycle.md` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_gpuflow_timing_models.py -q -p no:cacheprovider` |
| `timing-repository` | B1 | `scene/application/describe_run_repository.py`, `scene/domain/describe_run.py`, `scene/application/describe_operation_repository.py (new)`; `apps/prototype-description-service/scene/tests/test_gpuflow_operation_repository.py` (new test) | timing-models: `apps/prototype-description-service/db/models/scene.py`; contracts: `packages/shared-contracts/schemas/scene-describe-run.schema.json` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_describe_run_repository.py apps/prototype-description-service/scene/tests/test_gpuflow_operation_repository.py -q -p no:cacheprovider` |
| `response-models` | B1 | `scene/interface_adapters/http/schemas/responses.py`; `apps/prototype-description-service/scene/tests/test_gpuflow_response_models.py` (new test) | contracts: `packages/shared-contracts/schemas/scene-describe-multipart.schema.json`, `packages/shared-contracts/schemas/scene-describe-run.schema.json` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_gpuflow_response_models.py -q -p no:cacheprovider` |
| `svc-demand` | A1 | `scene/application/describe_load.py` | timing-repository: `apps/prototype-description-service/scene/application/describe_operation_repository.py`; contracts: `docs/workbay/contracts/gpu-lifecycle.md` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_describe_load.py -q -p no:cacheprovider` |
| `svc-instrumentation` | B1 | `scene/application/visual_facts_service.py`, `recognition/interface_adapters/http/middleware/metrics.py` | contracts: `packages/shared-contracts/schemas/scene-describe-run.schema.json`, `docs/workbay/contracts/gpu-lifecycle.md` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_visual_facts_service.py apps/prototype-description-service/recognition/tests/api/test_metrics.py -q -p no:cacheprovider` |
| `svc-cold-gpu` | A1/B1 | `scene/interface_adapters/http/routers/describe.py`, `apps/prototype-description-service/scene/tests/fixtures/gpuflow-multipart.json` (new test fixture) | svc-demand: `apps/prototype-description-service/scene/application/describe_load.py`; svc-instrumentation: `apps/prototype-description-service/scene/application/visual_facts_service.py`, `apps/prototype-description-service/recognition/interface_adapters/http/middleware/metrics.py`; response-models: `apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py`; timing-repository: `apps/prototype-description-service/scene/application/describe_operation_repository.py`, `apps/prototype-description-service/scene/domain/describe_run.py` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_describe_route.py apps/prototype-description-service/scene/tests/test_describe_eligibility.py -q -p no:cacheprovider` |
| `svc-run-timing` | B1 | `scene/application/describe_run_worker.py`, `scene/interface_adapters/http/routers/describe_run.py`, `apps/prototype-description-service/scene/tests/fixtures/gpuflow-run-items.json` (new test fixture) | svc-demand: `apps/prototype-description-service/scene/application/describe_load.py`; svc-instrumentation: `apps/prototype-description-service/scene/application/visual_facts_service.py`, `apps/prototype-description-service/recognition/interface_adapters/http/middleware/metrics.py`; response-models: `apps/prototype-description-service/scene/interface_adapters/http/schemas/responses.py`; timing-repository: `apps/prototype-description-service/scene/application/describe_run_repository.py`, `apps/prototype-description-service/scene/domain/describe_run.py` | `python3 -m pytest apps/prototype-description-service/scene/tests/test_describe_run_worker_phases.py apps/prototype-description-service/scene/tests/test_describe_run_routes.py apps/prototype-description-service/scene/tests/test_describe_run_items.py apps/prototype-description-service/scene/tests/test_describe_run_contract.py -q -p no:cacheprovider` |
| `php-breaker-passthrough` | A2/B2 | `src/api/class-abstract-recognition-proxy-controller.php`, `src/api/services/class-describe-media-service.php`, `src/api/class-settings-controller.php`, `apps/prototype-wp-alt-context/src/api/tests/fixtures/gpuflow-describe-wire.json` (new test fixture) | svc-cold-gpu: `apps/prototype-description-service/scene/tests/fixtures/gpuflow-multipart.json`; svc-run-timing: `apps/prototype-description-service/scene/tests/fixtures/gpuflow-run-items.json` | vendor/bin/phpunit --filter "Proxy\|DescribeMedia\|Settings" |
| `spa-description-service` | A3 | `js/admin/pages/settings/GpuControlCard.tsx`, `js/admin/pages/retention/RetentionPage.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/fixtures/gpuflow-service-states.json` (new test fixture) | rebaseline: `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` | npx vitest run js/admin/pages/settings js/admin/pages/retention |
| `spa-describe-client` | A3/B2 | `js/admin/api/describeApi.ts` | php-breaker-passthrough: `apps/prototype-wp-alt-context/src/api/tests/fixtures/gpuflow-describe-wire.json` | describe API passthrough/nullable timing vitest |
| `spa-suggest-warming-timing` | A3/B2 | `js/admin/hooks/useDescribeMedia.ts`, `js/admin/pages/workbench/MediaAltSuggest.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/fixtures/gpuflow-suggest-states.json` (new test fixture) | spa-describe-client: `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts` | npx vitest run js/admin/hooks/__tests__/useDescribeMedia.test.tsx js/admin/pages/workbench/__tests__/MediaAltSuggest.test.tsx |
| `spa-bulk-timing` | B2 | `js/admin/hooks/useDescribeRunProgress.ts`, `js/admin/pages/workbench/MediaSelection.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/fixtures/gpuflow-bulk-timing.json` (new test fixture) | spa-describe-client: `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts` | npx vitest run js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx |
| `spa-naming-control` | C1 | `js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx`, `js/admin/pages/workbench/identity-clusters/buildNamingOptions.ts`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/fixtures/gpuflow-naming-preview.json` (new test fixture) | rebaseline: `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` | npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/NameFaceControl.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/buildNamingOptions.test.ts |
| `svc-suggestion-rep` | C2 | `recognition/infrastructure/repositories/suggestion_repository.py`, `apps/prototype-description-service/recognition/tests/fixtures/gpuflow-suggestion-representatives.json` (new test fixture) | rebaseline: `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` | `python3 -m pytest apps/prototype-description-service/recognition/tests/integration/test_suggestion_repository.py -q -p no:cacheprovider` |
| `spa-suggestion-cards` | C2 | `js/admin/pages/workbench/identity-clusters/SuggestionCards.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/fixtures/gpuflow-candidate-preview.json` (new test fixture) | svc-suggestion-rep: `apps/prototype-description-service/recognition/tests/fixtures/gpuflow-suggestion-representatives.json`; spa-naming-control: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/fixtures/gpuflow-naming-preview.json` | npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx |
| `calibration` | C3 | `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` | rebaseline: `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` | numeric calibration report review |
| `svc-rep-settings` | C4 | `recognition/application/settings/clustering.py` | calibration: `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_recognition_settings_env.py -q -p no:cacheprovider` |
| `svc-rep-quality` | C4 | `recognition/application/persistence/representative_selector.py`, `recognition/application/persistence/assignment_writer.py` | svc-rep-settings: `apps/prototype-description-service/recognition/application/settings/clustering.py` | `python3 -m pytest apps/prototype-description-service/recognition/tests/unit/test_representative_quality_gate.py apps/prototype-description-service/recognition/tests/unit/test_representative_selector.py apps/prototype-description-service/recognition/tests/unit/test_fir2_br_postmerge_contracts.py apps/prototype-description-service/recognition/tests/unit/test_fir_final_postmerge_runtime_contracts.py apps/prototype-description-service/recognition/tests/integration/test_assignment_writer.py -q -p no:cacheprovider` |
| `spa-picker-undo` | D1 | `js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx`, `js/admin/pages/workbench/identity-clusters/MergeUndoBanner.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/fixtures/gpuflow-picker-undo.json` (new test fixture) | spa-suggestion-cards: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/fixtures/gpuflow-candidate-preview.json` | npx vitest run js/admin/pages/workbench/identity-clusters |
| `php-merge-cap` | D2 | `src/api/services/class-person-merge-service.php` | rebaseline: `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` | vendor/bin/phpunit --filter PersonMerge |
| `ux-service` | A3/B2/C/D | `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.uxmap.json`, `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md` | spa-description-service: `apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/fixtures/gpuflow-service-states.json` | render_ux_maps.py --check |
| `ux-suggest` | A3/B2/C/D | `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.json`, `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.md` | spa-suggest-warming-timing: `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/fixtures/gpuflow-suggest-states.json`; spa-bulk-timing: `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/fixtures/gpuflow-bulk-timing.json` | render_ux_maps.py --check |
| `ux-identity` | A3/B2/C/D | `apps/prototype-wp-alt-context/docs/ux-maps/workbench-identity-chips.uxmap.json`, `apps/prototype-wp-alt-context/docs/ux-maps/workbench-identity-chips.md` | spa-picker-undo: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/fixtures/gpuflow-picker-undo.json` | render_ux_maps.py --check |
| `ux-public` | A3/B2/C/D | `apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.uxmap.json`, `apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.md` | spa-suggest-warming-timing: `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/fixtures/gpuflow-suggest-states.json` | render_ux_maps.py --check |

The five C4 tests are recognition `unit/test_representative_quality_gate.py`, `unit/test_representative_selector.py`, `unit/test_fir2_br_postmerge_contracts.py`, `unit/test_fir_final_postmerge_runtime_contracts.py`, and `integration/test_assignment_writer.py`. Settings tests belong to svc-rep-settings; selector/writer contract tests belong to svc-rep-quality. The fixture producer owns edits to its tests; downstream lanes consume committed fixtures read-only and add their own component tests. Copy the exact test ownership and fixture paths above into the dispatch manifest without deferring path selection.

Each implementation lane has one luna max review twin (`lane_kind: review`) per committed delta. Only high findings block; lints are low and deferred per sr-011. Operator decisions and missing contracts are dispatch gates even when no high finding is attached.

### Collision map

- Rebaseline produces the assessment consumed by calibration; calibration edits its own section only after that artifact is integrated.
- Naming-control → suggestion-cards → picker-undo carries `js/admin/pages/workbench/identity-clusters/__tests__/fixtures/gpuflow-naming-preview.json` then `js/admin/pages/workbench/identity-clusters/__tests__/fixtures/gpuflow-candidate-preview.json` (WordPress-relative); the table identifies each producer and read-only consumer. Shared-directory location alone creates no edge. The producer owns each fixture; downstream tests must not rewrite it concurrently.
- Contract schemas → durable models → repositories → route/worker consumers carry concrete typed fields and persistence APIs. Response models and instrumentation are independent producers consumed by both route lanes. Only svc-cold-gpu owns describe.py; only svc-run-timing owns describe_run.py/worker. PHP consumes both final serialized fixtures; the SPA API client carries them to separate Suggest and bulk consumers.
- Representative settings → selector/writer carries calibrated representative-only configuration; assignment quality is outside those lanes.
- Each UX lane owns its canonical JSON and generated Markdown as a pair and consumes final UI fixtures. No component lane edits those files. Each shared writer is serialized by its exact artifact dependency in the table. Before dispatch, `lane_dag` validates those producer/path/read-only-consumer dependencies; shared directories and operator gates create no ordering-only edges.

### Merge Order

1. Gate 0: preserve prior review evidence, complete luna max plan re-review and freeze, then operator promotion and rebaseline. Persisting-defect assessment is a dispatch gate for all fixes; no implementation starts alongside unfinished rebaseline.
2. Wave 1: contracts, naming-control, suggestion-rep, description-service UI, calibration; merge-cap only after the accepted API-R-23 brief.
3. Wave 2: timing-models, response-models and instrumentation after contracts; suggestion-cards after both fixture producers; rep-settings after accepted calibration; ux-service after UI fixtures.
4. Wave 3: timing-repository after models; demand after repository; cold-GPU and run-timing after all their table inputs. Picker-undo follows suggestion fixtures; rep-quality follows settings; ux-identity follows picker fixtures.
5. Wave 4: PHP after both service fixture producers, then SPA describe client, then Suggest and bulk consumers, then ux-suggest/ux-public. These are explicit intra-wave sequences, not concurrent dispatch permission.
6. Release gate R: all reviewed slices and tests integrated, operator smoke, local codex harmonization against the heuristics canon and enforced close check.

Waves describe earliest availability; the artifact DAG is authoritative. Integrate continuously into `feature/gpuflow-1`, preserve evidence and retire worktrees promptly; `main` receives one final merge.

### Manifest

```bash
make lane-manifest-init TASK=GPUFLOW-1 LANE_IDS='rebaseline contracts timing-models timing-repository response-models svc-demand svc-instrumentation svc-cold-gpu svc-run-timing php-breaker-passthrough spa-description-service spa-describe-client spa-suggest-warming-timing spa-bulk-timing spa-naming-control svc-suggestion-rep spa-suggestion-cards calibration svc-rep-settings svc-rep-quality spa-picker-undo php-merge-cap ux-service ux-suggest ux-identity ux-public' TASK_PLAN=docs/tasks/v0.5.0/GPUFLOW-1-description-service-flow-and-identity-fixes-task-plan.md
```

Only after freeze/re-review: materialize, re-pin `config/lane-orchestration/GPUFLOW-1.json` (materialize rewrites pins), verify row/model/effort match and validate the artifact dependencies with `lane_dag` before dispatch. The frozen table already pins every artifact path, producer, read-only consumer and exact Python test command; copy these into the manifest and reject missing or mismatched dependencies before dispatch. This plan-revision lane edits only this document, not the manifest or sibling reports.

### Orchestration Mode

- Remote: `run_offload_pass` from a ROOT subprocess, one lane per detached process, staggered at least 60 s behind the breaker. Refresh from the feature branch and verify all artifact inputs before dispatch.
- Local: tsc/vitest/phpunit in lane worktrees, integration and the final harmonizing review. No agent runs live Suggest/run/Start/Stop or deployment.

## Highest-Leverage Next Items (from docs sweep, not in this wave)

| Item | Source | Why next |
| --- | --- | --- |
| CPU-provisional degrade and supersede (PA-03) | `docs/scopes/gpu-detailed-tier-oci-bursty-scope.md` | Lets Suggest return a CPU draft while the service ramps up, instead of waiting; needs the GPUFLOW-1 timing numbers to set the switch threshold |
| Quality-adaptive acceptance margin | FIR v11 report (PFE/MLS, AdaFace norm) | Replaces the fixed 0.35–0.55 suggestion band if C3 shows band errors |
| VM retention hygiene | `docs/tech-debt/OPS-1-vm-host-retention-hygiene.md` | VM disk at 75%, which blocks remote builds and promotions |
| E21 workbench UX polish | `docs/epics/` E21 | Remaining identity workbench polish after C/D tracks land |
| GPU-LAUNCH-1 open highs | handoff (query live) | Bootstrap and reaper overlay items gate unattended cold starts |

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded rules, gpu-lifecycle contract, describe schemas, UX maps and GPU-LAUNCH-1 §8 before editing.
- [ ] Operator confirmed the production promotion; image SHA recorded.

### Checklist for Slice 0: Promote and re-baseline

- [ ] VM disk hygiene precondition met.
- [ ] Routes and `/ready` return 200 on dev, staging and prod.
- [ ] Persisting defects and the live suggestion row captured in the assessment file.

### Checklist for Slice A1: Typed cold-GPU response and demand lease

- [ ] Actual GPU compute eligibility gates typed startup 503; CPU/cache bypass and STOP/unknown/unavailable semantics tested; ETA only when known.
- [ ] Durable lease survives 503, aggregates every publisher, renews/expires across processes, and meets measured polling/freshness bounds; STOP/max-lease remain authoritative.
- [ ] Contract doc and schema updated.

### Checklist for Slice A2: Route-family breaker and passthrough

- [ ] Counters/locks/open/reset share route-family key; validated warming is excluded before accounting.
- [ ] Describe errors and timing passed through verbatim.

### Checklist for Slice A3: Description Service UI

- [ ] Card and copy renamed.
- [ ] Suggest warming state with bounded auto-retry.
- [ ] Retention Retry shows progress.
- [ ] UX maps updated and parity check passes.

### Checklist for Slice B1: Phase timing capture

- [ ] Durable operation/startup correlation survives retries/restart; queue/readiness/adapter boundaries are nonoverlapping; server elapsed excludes client rendering.
- [ ] Storage/domain/repository/models and both shared schemas precede consumers; real builders round-trip timing, nulls and failures; histogram split.

### Checklist for Slice B2: Timing display and evidence

- [ ] Timing line on Suggest and the run summary, from wire values only.
- [ ] Evidence-bundle mapping documented.

### Checklist for Slice C1: Naming control

- [ ] Listbox closed on mount.
- [ ] Group preview fallback chain.
- [ ] New component test.

### Checklist for Slice C2: Suggestion representative

- [ ] Representative excludes candidate in the normal and replay paths.
- [ ] Placeholder and croppable gate in `SuggestionCards`.

### Checklist for Slice C3: Calibration analysis

- [ ] Wrong-match row analysed.
- [ ] Occlusion/sharpness factors proposed with precision cost.
- [ ] Operator accepts the recommendation as a decision.

### Checklist for Slice C4: Quality-aware representatives

- [ ] Accepted representative-only factors propagated; clearer newcomers replace unpinned pose-bucket and pose-free avatars; pins/diversity and assignment thresholds preserved.
- [ ] Contract tests updated to the new ranking.

### Checklist for Slice D1: Picker and undo

- [ ] Anchor picker disabled with a reason.
- [ ] Undo dismissible while retryable; token persists.

### Checklist for Slice D2: Merge cap

- [ ] API-R-23 owner accepts numeric cap, bounded field, admission/undo scope and typed error before D2 dispatch; boundary tests follow that brief.

### Checklist for Slice R: Release gate

- [ ] Plugin bumped and deployed to demo.
- [ ] Operator smoke with cold and warm timing evidence recorded.
- [ ] Local codex merge-gate review against the heuristics canon and enforced close check pass; each committed delta received one luna max review and its worktree is retired after preservation.

## Review Readiness

- [ ] Every boundary change in the contract table has a schema, fixture or passthrough test.
- [ ] Runtime parity verified after promotion; no symptom closed without a live re-check.
- [ ] Handoff decisions record each lane, verification and contract change.

## Stretch Goals

- [ ] `Server-Timing` header on the multipart route mirroring `timing`.
- [ ] Settings card shows the last observed ramp-up time from the most recent run.

## Success Criteria

- [ ] On a stopped GPU, Suggest from WP admin starts the Description Service and returns a draft without a 500, showing a warming state meanwhile.
- [ ] Every describe result shows ramp-up time separately from per-image processing time, and the operator smoke records cold and warm figures.
- [ ] Settings shows "Description Service", the naming toggle is usable, and retention loads after describe failures.
- [ ] The name listbox is closed on load, suggestion cards never duplicate an avatar, and representatives prefer clear faces.
- [ ] All five IDCHIP-1 deferred mediums are closed.
