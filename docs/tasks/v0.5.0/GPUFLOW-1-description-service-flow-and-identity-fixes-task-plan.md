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

- **Ramp-up time**: from the first request that finds the GPU not ready to the first moment the service observes `ready`. It covers OCI start, boot, model load and health.
- **Processing time**: per image, from dispatch to the realizer until a result is returned (inference plus transport), excluding the ramp-up wait.
- **Queue time**: from enqueue until the worker picks up the item.
- **End-to-end time**: from the operator's action (Suggest or a run submit) until the result is rendered. It equals queue + ramp-up + Σ processing + poll/transport overhead.
- **Demand tick**: a `describe-load.json` publication showing pending work, which is what the lifecycle controller reads as `has_work`.

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

Suggest on a stopped GPU returns within a few seconds with `503 description_service_starting` and `Retry-After`, and it publishes a demand tick. The SPA shows "Description Service is starting — about N s" using the service's warmup ETA and retries on its own until ready or until the 120 s public ceiling. It then renders the draft with a timing line: "Started in 1 m 42 s · described in 6.1 s". Bulk runs show run-level ramp-up once plus per-image processing (median and slowest).

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
  - `packages/shared-contracts/schemas/` describe multipart response
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
| `POST /scene/describe/multipart` error envelope | description-service | 500 on GPU adapter failure | `503` + `code=description_service_starting` + `Retry-After` + `warmup_eta_seconds` when the GPU is not ready; `502 description_service_error` on a realizer failure after ready | no (greenfield) | pytest route tests + schema fixture |
| `describe-load.json` producer set | description-service → lifecycle controller | async routes only | sync path publishes a demand tick (single writer unchanged: still the service) | no | `test_describe_load.py` + controller `has_work` test |
| `timing` object on describe responses | description-service → PHP → SPA | absent | `timing{queue_ms, ramp_up_ms, processing_ms, end_to_end_ms}` on multipart; run-level `timing{queue_ms, ramp_up_ms, processing_ms_p50, processing_ms_max, items_timed}` plus per-item `processing_ms` on describe-run | no | shared-schema test on the real builder; PHP passthrough test |
| WP describe proxy → SPA | PHP plugin | opaque `Could not generate a draft` | pass the status, `code`, `Retry-After` and `timing` through verbatim | no | PHPUnit passthrough |
| PHP circuit-breaker key | PHP plugin | per base URL | per base URL + route family (`describe`, `ui_read`, `control`) | no | PHPUnit: describe failures do not open `ui_read` |
| Suggestion details payload | recognition-service | representative may equal candidate | representative excludes the candidate identity; null when none exists | no | pytest repository test + SPA placeholder test |

## Proposed Solution

The work is five tracks and one release gate.

- **P0 — promote.** The operator promotes `main` through dev → staging → prod. An agent then verifies routes and `/ready` read-only and re-checks each live defect, and any defect that disappears is closed as deploy skew.
- **Track A — Description Service flow.**
  - Typed GPU errors on the sync path.
  - Demand tick plus a fail-fast warming response.
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
- **Release gate.** Plugin bump, `make deploy-demo`, operator GPU smoke (Start from SPA → Suggest cold → Suggest warm → bulk run of 5 → Stop) with the timing evidence, then `handoff_close_check(enforce=True)`.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py` | catch `GpuRemoteAdapterError`; not-ready → 503 typed + demand tick; timing capture on the sync path |
| backend | `apps/prototype-description-service/scene/application/describe_load.py` | demand-tick helper for the sync path (in-flight registration released in `finally`) |
| backend | `apps/prototype-description-service/scene/application/describe_run_worker.py` | record queue/ramp-up/per-item processing timestamps around `_wait_for_gpu_ready` and item dispatch |
| backend | `apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py` | expose run `timing` + per-item `processing_ms` |
| contracts | `packages/shared-contracts/schemas/scene-describe-run.schema.json` (+ multipart schema) | `timing` object, error `code` enum |
| docs | `docs/workbay/contracts/gpu-lifecycle.md` | sync-path demand tick as a documented producer |
| PHP | `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | route-family breaker key |
| PHP | `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php` | pass through status/code/Retry-After/timing |
| PHP | `apps/prototype-wp-alt-context/src/api/services/class-person-merge-service.php` | cap `cluster_count` + PHPUnit |
| SPA | `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx` (+ test) | "Description Service" title and copy |
| SPA | Suggest action component + describe API client (lane locates via codemap) | warming state, auto-retry within 120 s, timing line |
| SPA | describe-run progress (`MediaSelection.tsx` / `useDescribeRunProgress`) | ramp-up vs processing summary |
| SPA | `apps/prototype-wp-alt-context/js/admin/pages/retention/RetentionPage.tsx` | Retry shows fetching state and last error |
| SPA | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx` (+ new test) | `useState(false)`; group preview fallback chain |
| SPA | `.../identity-clusters/SuggestionCards.tsx` (+ new test) | null-representative placeholder; `isCroppableBbox` gate |
| SPA | `.../identity-clusters/IdentityClusterItem.tsx` | anchor picker disabled with reason |
| SPA | undo banner component (IDCHIP-1 merge undo) | dismissible while retryable; token persisted past 30 s |
| backend | `apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py` | representative excludes candidate identity |
| backend | `recognition/application/assignment/quality.py`, `recognition/application/settings/clustering.py` | calibrated occlusion/sharpness factor in representative ranking |
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

- **Deterministic tests** (description-service pytest runs on the remote VM through lane `test_cmd`):
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
  - GPU stopped → Suggest on one image; record `ramp_up_ms` and `processing_ms`.
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
- Agent re-checks defects 3, 5, 7 and 8 and records which ones persist.
- Analysis lane (luna max): classify persisting defects and pull the live Trudeau/Watson suggestion row (similarity, band, representative identity id, quality, occlusion score) into the calibration report.

Proof:

- Decision records the image SHA and route status codes.
- Re-baseline table in a handoff decision (not in this plan).

### Slice A1: Typed cold-GPU response and demand tick (backend)

**Goal**: A stopped GPU yields a fast, typed, retryable response and a start signal instead of a 500.

Changes:

- Sync multipart reads `gpu_state`. When the GPU is not `ready`, it publishes a demand tick and returns `503 description_service_starting` with `Retry-After` and `warmup_eta_seconds`.
- A `GpuRemoteAdapterError` after `ready` returns `502 description_service_error`.
- The demand tick is released in `finally`.
- Contract doc and schema updated in the same slice.

Proof:

- Route tests cover stopped, warming, ready-success, ready-adapter-failure and timeout.
- A controller test shows a sync demand tick sets `has_work`.
- `test_describe_load.py` covers atomic publish under concurrency.

### Slice A2: Route-family breaker and verbatim error passthrough (PHP)

**Goal**: Describe failures cannot blank retention or settings reads, and the SPA receives the typed error.

Changes:

- The breaker key includes the route family.
- The describe media service passes status, `code`, `Retry-After` and `timing` through.
- The naming-agreement read reports the upstream status and code.

Proof:

- PHPUnit: two describe 5xx leave `ui_read` closed.
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

- Monotonic timestamps at enqueue, worker pickup, GPU wait start, GPU ready observed, and per-item dispatch and result.
- `timing` on the multipart and describe-run responses.
- The adapter histogram is split into `description_gpu_wait_seconds` and `description_processing_seconds`.
- Schema updated.

Proof:

- Fake-clock tests assert each phase boundary, and ramp-up is 0 when the GPU is already ready.
- The schema test runs on the real builders.

### Slice B2: Timing display and evidence (PHP passthrough + SPA)

**Goal**: The operator can tell ramp-up from processing for a single Suggest and for a run.

Changes:

- PHP passthrough of `timing`.
- The SPA timing line on the Suggest result and run summary shows ramp-up once, plus median and slowest per-image processing. Values come only from the wire.
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

- `_to_details` chooses the best representative identity other than the suggestion's identity, or null.
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
- Include the multiplier in `recompute_representatives` ranking. Pinned representatives are preserved.
- Update the five contract tests deliberately to the new ranking contract.
- A threshold change, if C3 recommends one, goes in the same slice with its evidence.

Proof:

- Tests show an occluded high-confidence face loses to a clear face, and that a newly uploaded clearer face replaces the representative on recompute.
- Pinned representatives are unchanged.

### Slice D1: Anchor picker and undo persistence (SPA)

**Goal**: IDCHIP-1 picker and undo mediums are closed.

Changes:

- `IdentityClusterItem` anchor picker is disabled with a visible reason (FORM-09).
- The undo banner can be dismissed while retryable.
- The undo token persists beyond 30 s for its server-side validity window.

Proof:

- vitest: disabled reason text and `aria-describedby`; banner dismiss; token survives a 30 s fake-timer advance.

### Slice D2: Merge cluster-count cap (PHP)

**Goal**: `PersonMergeService` rejects merges beyond the declared cluster cap.

Changes:

- Cap `cluster_count` with a typed error.

Proof:

- PHPUnit at the boundary: cap accepted, cap + 1 rejected.

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

Routing (user order 2026-09-13):

- Implementation lanes: codex-remote `gpt-6-astra` effort `low`.
- Grunt, classification, analysis and per-lane slice reviews: codex-remote `gpt-5.6-luna` effort `max`, dispatched from a subprocess with `WORKBAY_CODEX_MODEL=gpt-5.6-luna` exported before import, with the lane row pinned to match and no `tier`/`speed`.
- One codex-remote `gpt-6-astra` MEDIUM harmonizing review of this plan before any implementation dispatch.
- Local host: harmonizing, tsc/vitest/phpunit verification, and integration.

### Lanes

| Lane ID | Slice | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- | --- |
| `rebaseline` (analysis, luna max) | 0 | `docs/assessments/GPUFLOW-1-wrong-match-and-occlusion-calibration-20260913.md` (live section) | operator promotion | none (report) |
| `svc-cold-gpu` | A1 | `scene/interface_adapters/http/routers/describe.py`, `scene/application/describe_load.py`, `docs/workbay/contracts/gpu-lifecycle.md` + tests | rebaseline | `python3 -m pytest .../scene/tests -k "describe or describe_load"` |
| `php-breaker-passthrough` | A2 | `class-abstract-recognition-proxy-controller.php`, `class-describe-media-service.php`, `class-settings-controller.php` + tests | svc-cold-gpu (error contract) | `vendor/bin/phpunit --filter "Proxy|DescribeMedia|Settings"` |
| `svc-timing` | B1 | `scene/application/describe_run_worker.py`, `scene/interface_adapters/http/routers/describe_run.py`, `packages/shared-contracts/schemas/scene-describe-run.schema.json` + tests | svc-cold-gpu (shares multipart timing field) | `python3 -m pytest .../scene/tests -k "describe_run or timing"` |
| `spa-description-service` | A3 | `GpuControlCard.tsx`, `RetentionPage.tsx`, ux-map `gpu-operator-control.md` + tests | none (rename/retry) | `npx vitest run js/admin/pages/settings js/admin/pages/retention` |
| `spa-suggest-warming-timing` | A3 + B2 | Suggest action component, describe API client, `MediaSelection.tsx`, ux-map `describe-gpu-tier.md` + tests | php-breaker-passthrough, svc-timing | `npx vitest run <suggest + describe paths>` |
| `spa-naming-control` | C1 | `NameFaceControl.tsx`, `buildNamingOptions` + new test | none | `npx vitest run js/admin/pages/workbench/identity-clusters` |
| `svc-suggestion-rep` | C2 backend | `suggestion_repository.py` + tests | none | `python3 -m pytest .../recognition/tests -k suggestion` |
| `spa-suggestion-cards` | C2 SPA | `SuggestionCards.tsx` + new test | svc-suggestion-rep (null contract) | `npx vitest run js/admin/pages/workbench/identity-clusters` |
| `calibration` (analysis, luna max) | C3 | same assessment file (calibration section) | rebaseline | none (report) |
| `svc-rep-quality` | C4 | `quality.py`, `clustering.py`, `assignment_writer.py` + five contract tests | calibration + operator acceptance | `python3 -m pytest .../recognition/tests -k "representative or assignment_writer or postmerge"` |
| `spa-picker-undo` | D1 | `IdentityClusterItem.tsx`, undo banner component + tests | spa-naming-control (shared test fixtures) | `npx vitest run js/admin/pages/workbench/identity-clusters` |
| `php-merge-cap` | D2 | `class-person-merge-service.php` + test | none | `vendor/bin/phpunit --filter PersonMerge` |

Each implementation lane has a luna-max review twin (`lane_kind: review`) run on its delta as soon as it finishes. Only high findings block. Lints are recorded as low findings and deferred per sr-011.

### Collision map

- **`rebaseline` and `calibration` share one assessment file.** They run in sequence, and each owns a named section.
- **The four `js/admin/pages/workbench/identity-clusters` lanes share a vitest directory.** Owned source files are disjoint (`NameFaceControl`, `SuggestionCards`, `IdentityClusterItem`/undo). They integrate in sequence: naming-control → suggestion-cards → picker-undo.
- **`svc-cold-gpu` and `svc-timing` both touch describe response shapes.** svc-cold-gpu owns `describe.py`, including the multipart `timing` capture. svc-timing owns the run worker, the run router and the schema. svc-timing starts after svc-cold-gpu merges into the feature branch.
- **`spa-suggest-warming-timing` consumes both backend contracts.** It is the last Track A/B lane.

### Merge Order

1. Wave 1 (after operator promotion):
   - rebaseline (analysis)
   - spa-description-service
   - spa-naming-control
   - svc-suggestion-rep
   - php-merge-cap
   - svc-cold-gpu
2. Wave 2:
   - php-breaker-passthrough
   - svc-timing
   - spa-suggestion-cards
   - calibration (analysis)
   - spa-picker-undo
3. Wave 3:
   - spa-suggest-warming-timing
   - svc-rep-quality (after the operator accepts the calibration decision)
4. Release gate R.

Every lane merges into `feature/gpuflow-1` as soon as its review twin passes (continuous consolidation). `main` receives one merge at the end.

### Manifest

```bash
make lane-manifest-init TASK=GPUFLOW-1 LANE_IDS='rebaseline svc-cold-gpu php-breaker-passthrough svc-timing spa-description-service spa-suggest-warming-timing spa-naming-control svc-suggestion-rep spa-suggestion-cards calibration svc-rep-quality spa-picker-undo php-merge-cap' TASK_PLAN=docs/tasks/v0.5.0/GPUFLOW-1-description-service-flow-and-identity-fixes-task-plan.md
```

After materialize, re-pin `config/lane-orchestration/GPUFLOW-1.json` (materialize rewrites pins) and validate with `lane_dag`.

### Orchestration Mode

- **Remote lanes**: `run_offload_pass` from a ROOT subprocess, one lane per detached process, staggered 60 s or more behind the breaker. Refresh each lane branch from `feature/gpuflow-1` before dispatch.
- **Local**: vitest, tsc and phpunit verification from lane worktrees, then integration merges.

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

### Checklist for Slice A1: Typed cold-GPU response and demand tick

- [ ] Sync path returns typed 503/502 with `Retry-After` and ETA.
- [ ] Demand tick published and released; controller sees `has_work`.
- [ ] Contract doc and schema updated.

### Checklist for Slice A2: Route-family breaker and passthrough

- [ ] Breaker keyed by route family.
- [ ] Describe errors and timing passed through verbatim.

### Checklist for Slice A3: Description Service UI

- [ ] Card and copy renamed.
- [ ] Suggest warming state with bounded auto-retry.
- [ ] Retention Retry shows progress.
- [ ] UX maps updated and parity check passes.

### Checklist for Slice B1: Phase timing capture

- [ ] Queue, ramp-up and per-item processing captured with a monotonic clock.
- [ ] `timing` on both response shapes; histogram split.

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

- [ ] Calibrated factors applied; pinned representatives preserved.
- [ ] Contract tests updated to the new ranking.

### Checklist for Slice D1: Picker and undo

- [ ] Anchor picker disabled with a reason.
- [ ] Undo dismissible while retryable; token persists.

### Checklist for Slice D2: Merge cap

- [ ] `cluster_count` capped with a PHPUnit boundary case.

### Checklist for Slice R: Release gate

- [ ] Plugin bumped and deployed to demo.
- [ ] Operator smoke with cold and warm timing evidence recorded.
- [ ] Final integration review and enforced close check pass.

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
