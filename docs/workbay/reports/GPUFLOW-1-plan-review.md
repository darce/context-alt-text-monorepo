# GPUFLOW-1 harmonizing plan review

Verdict: fail

Static snapshot review; resolve highs before implementation. Paths beginning `scene/` or `recognition/` are relative to `apps/prototype-description-service/`; PHP and SPA paths are relative to `apps/prototype-wp-alt-context/`.

## FINDINGS

### GPUFLOW-1-PR-01 — high
- **Section:** A1; demand contract; collision map.
- **Evidence:** `scene/application/describe_load.py:181-251` atomically replaces the current snapshot; `infra/oci/gpu_lifecycle/controller.py:87-92` decides from the current counts, with no memory of an earlier tick. Returning a fast 503 and releasing demand in `finally` can publish busy then idle entirely between controller reads. A later DB-derived refresh can erase a separately injected sync count even before release.
- **Fix:** Specify a service-owned, expiring demand lease retained beyond the response, with lifetime justified against controller polling, jitter and snapshot freshness. Aggregate it with async work in every publication through the existing service writer/fence; define cross-process visibility, expiry, renewal and concurrent publication ordering. Do not add a lifecycle writer or bypass STOP/max-lease. Test request completion before the next controller read, intervening periodic/async writes, concurrent requests, and eventual expiry.

### GPUFLOW-1-PR-02 — high
- **Section:** A2; route-family breaker contract.
- **Evidence:** `src/api/class-abstract-recognition-proxy-controller.php:117-118` creates separate circuit and failure keys, both base-URL scoped. Lines 197-210 count every 5xx before handling Retry-After; lines 484-507 open the circuit after the configured threshold. Scoping only the open key leaves counters coupled; expected warming 503s still trip the describe circuit for 60 seconds.
- **Fix:** Scope failure counters, locks, open state and success resets to the same canonical base-URL/route-family key; explicitly classify paths rather than equating family with HTTP method. Exclude the validated `503 description_service_starting` response from breaker failures while preserving counting for real 502/5xx failures. Test repeated warming responses beyond threshold, cross-family failures and resets, and preservation of Retry-After/ETA/code on every retry.

### GPUFLOW-1-PR-03 — high
- **Section:** Terminology; A1/B1/B2; multipart timing contract.
- **Evidence:** Internal contradiction: A1 ends the cold request with 503, but B1 captures request-local monotonic timestamps and Target Outcome expects the later successful retry to carry the whole cold ramp-up. There is no correlation or retained start observation across these requests. `scene/interface_adapters/http/routers/describe.py:333-442` handles one request. The service also cannot measure an operator click before receipt or rendering after response, despite the definition of `end_to_end_ms`.
- **Fix:** Define a service-authoritative operation/startup identifier and retained timing state across retries, including concurrent callers joining an existing startup, readiness observed mid-operation, expiry and warm/cache hits. Distinguish operation wait from whole startup duration. Rename service end-to-end to server elapsed, or specify separate client telemetry for action-to-render; do not have PHP/SPA fabricate service timing.

### GPUFLOW-1-PR-04 — high
- **Section:** B1; lane ownership and producer order.
- **Evidence:** `scene/interface_adapters/http/schemas/responses.py:162-210` forbids extra fields and has no run/item timing. `_run_response` and `_run_items_response` at `scene/interface_adapters/http/routers/describe_run.py:134-169` build from persisted run/item data; the worker writes results at `scene/application/describe_run_worker.py:598-617`. Neither response models nor timing storage/repository changes have an owner. The multipart shared schema is unnamed and absent from the shared-schema file listing. A1 promises a schema but owns none.
- **Fix:** Name every response model, schema, persistence and builder file, and choose persisted fields or another explicit durable timing representation. Assign a serial contract/storage producer, then multipart/run implementation, then PHP, then SPA. If adding DB fields, assign `001_identity_schema.py` and corresponding models/repositories under the greenfield rule. Gate PHP on the final timing contract. Validate actual serialized builders against schemas, including absent and failed-item values.

### GPUFLOW-1-PR-05 — high
- **Section:** A1; cold-GPU response eligibility.
- **Evidence:** `scene/interface_adapters/http/routers/describe.py:377-384` selects GPU, CPU or the default adapter; `scene/application/visual_facts_service.py:218-232` deliberately invokes `before_compute` only after cache/decorative bypasses. A1's unconditional rule “when GPU is not ready” would block CPU/hosted/cache work and start GPU capacity unnecessarily.
- **Fix:** Gate demand/readiness on actual GPU compute after validation and zero-compute/cache handling. Define unavailable/unknown/stopping/operator-STOP behavior separately from a startup that can proceed; do not promise an ETA or automatic start when the lifecycle policy forbids it. Test CPU/hosted/default adapter selection, cache and decorative bypasses, STOP and unknown state alongside cold GPU success.

### GPUFLOW-1-PR-06 — medium
- **Section:** B1 phase boundaries and histogram split.
- **Evidence:** `scene/application/describe_run_worker.py:480-499` probes readiness even on warm GPU runs, before item pickup. Lines 539-579 include naming lookup, transient retries and preview, so the existing `item_started` is not realizer dispatch. `scene/application/visual_facts_service.py:227-232` already measures adapter dispatch separately; the histogram declaration is in unowned `recognition/interface_adapters/http/middleware/metrics.py:99-105`.
- **Fix:** Specify nonoverlapping run enqueue-to-worker queue time, operation readiness wait, and adapter-attempt processing. Do not sum per-item queue waits with run ramp-up or use summed concurrent processing as elapsed time. Assign instrumentation/metrics files and test late readiness, concurrent runs, retries and cancelled/untimed items; measure actual dispatch rather than the whole naming envelope.

### GPUFLOW-1-PR-07 — high
- **Section:** C4; quality lane ownership and clearer-upload proof.
- **Evidence:** `recognition/application/persistence/representative_selector.py:498-541` preserves unpinned pose-bucket representatives as well as pins. `recognition/application/persistence/assignment_writer.py:609-650` ranks new candidates but selects the first preserved representative ahead of every new one. Thus a clearer upload need not replace an existing unpinned avatar. C4 does not own the selector. `recognition/application/assignment/quality.py:40-44` explicitly separates confidence/bbox score from occlusion threshold adjustment; changing that shared score can change assignment, not just avatar ranking.
- **Fix:** Define representative-only scoring and primary-avatar replacement across eligible old and new members, keeping explicit pins unchanged and preserving the intended diversity contract. Assign the selector and its settings propagation to a bounded lane; test an existing unpinned pose-bucket avatar against a clearer newcomer as well as pose-free data and pins. Keep assignment-score/threshold changes separately evidence-gated; do not loosen unrelated assignment contracts merely to pass avatar tests.

### GPUFLOW-1-PR-08 — medium
- **Section:** Lane table, sizing and merge order.
- **Evidence:** Internal plan inconsistencies: rebaseline and dependent svc-cold-gpu share Wave 1 without explicit intra-wave sequencing; the collision map requires naming-control → suggestion-cards → picker-undo, but the table omits those edges. `js/admin/hooks/useDescribeRunProgress.ts:1-26` is a separate progress consumer alongside the API client and MediaSelection; including it and the Suggest component exceeds three source files.
- **Fix:** Materialize exact paths and tests before dispatch. Encode the stated serialization in the DAG or explicitly remove unnecessary fixture coupling with disjoint ownership. Make rebaseline completion a real dispatch gate for persisting-defect lanes. Split contract/storage, instrumentation, Suggest retry, bulk display and representative policy into bounded 1–3-source-file units with individual tests/reviews; do not expect the expanded timing or calibration-plus-ranking work to fit a single 30-minute window.

### GPUFLOW-1-PR-09 — medium
- **Section:** A3/C1/C2/D1 UX maps; contract pass-through.
- **Evidence:** `docs/ux-maps/describe-gpu-tier.notes.md:3` names the `.uxmap.json` source of truth, but lane ownership lists only Markdown. `docs/ux-maps/workbench-identity-chips.uxmap.json` and `public-demo-describe.uxmap.json` exist without owners for the changed flows. Internal boundary inconsistency: the service emits `warmup_eta_seconds`, while the PHP passthrough checklist enumerates status/code/Retry-After/timing but omits ETA.
- **Fix:** Assign canonical UX JSON plus generated Markdown to serialized owners for Suggest, identity and other changed mapped flows, with the renderer check. Pin the precise error-envelope nesting and optional/null timing/ETA fields across service, PHP and SPA.

### GPUFLOW-1-PR-10 — medium
- **Section:** Slice 0; release proof; D2 cap contract.
- **Evidence:** Proposed Solution's smoke says Start from SPA before Suggest cold, while Verification Strategy says stopped → Suggest; the former cannot prove demand-triggered startup. Slice 0's agent symptom rechecks lack an explicit prohibition on calling the newly actuating describe path. D2 refers to a “declared cluster cap” without a value or authority; `src/api/services/class-person-merge-service.php:249-252` validates undo-record `cluster_count` as a nonnegative integer, so an undo-payload bound and rejecting a merge are distinct contracts.
- **Fix:** Assign all live Suggest/run/Start/Stop actions, including rebaseline reproduction, to the operator; agents inspect only nonactuating routes and recorded evidence. Require a stopped/Auto → Suggest smoke without a preceding Start, and test explicit Start separately. Obtain a compact API-R-23 brief defining the cap, bounded field, error and boundary cases before D2 dispatch.

## Verified alignments

C2's normal and stale-accepted replay both call `_to_details` (`recognition/infrastructure/repositories/suggestion_repository.py:195-221,282-326`), so the planned common exclusion rule is appropriate. Its fallback must load tenant-scoped target members (only the current representative is eager-loaded today), and return null when no noncandidate exists; no PHP/SPA replacement identity is needed. The producer → placeholder consumer dependency is present.

C3 → operator acceptance → C4 is correctly gated. All five named test files exist: unit `test_representative_quality_gate.py`, `test_representative_selector.py`, `test_fir2_br_postmerge_contracts.py`, `test_fir_final_postmerge_runtime_contracts.py`, and integration `test_assignment_writer.py`. No live GPU action or deployment was performed.

## Harmonization

1. Replace ephemeral demand ticks with a bounded, aggregated service-owned lease contract.
2. Publish exact error/timing/storage contracts before multipart/run, PHP and SPA consumers.
3. Assign missing response, persistence, schema and metrics paths; split expanded lanes.
4. Scope all breaker state by route family and exempt typed warming from failures.
5. Add explicit rebaseline and shared-fixture ordering to the executable DAG.
6. Give representative replacement/selector work an owner behind accepted calibration.
7. Assign canonical UX JSON and exact Suggest/progress/undo paths with serialized writers.
8. Make release and all live actuation operator-owned; prove Auto demand startup independently.
