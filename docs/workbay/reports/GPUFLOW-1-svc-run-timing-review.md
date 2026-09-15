# GPUFLOW-1 svc-run-timing review

FINDINGS: [{"id":"GPUFLOW-1-SVCRUNTIMING-R-01","severity":"high","file_path":"apps/prototype-description-service/scene/application/describe_run_worker.py","line":270,"summary":"Cold bulk readiness mints a per-run startup and fabricates startup duration.","evidence":"_record_run_readiness() generates a fresh uuid4 startup_id for each cold run and computes startup_ms from run.started_at, which record_pickup() sets at worker pickup; it never observes or joins the durable shared startup record."},{"id":"GPUFLOW-1-SVCRUNTIMING-R-02","severity":"high","file_path":"apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py","line":174,"summary":"New run timing fields are rejected by the strict SPA status parser.","evidence":"_run_response() emits operation_id, startup_id, and timing after pickup, while describeApi.ts allows only the legacy core keys plus deadline_seconds and rejects any unexpected key; the PHP status endpoint forwards the upstream body unchanged."},{"id":"GPUFLOW-1-SVCRUNTIMING-R-03","severity":"medium","file_path":"apps/prototype-description-service/scene/application/describe_run_worker.py","line":370,"summary":"Cancellation before a retry loses already measured attempt time.","evidence":"The retry loop stores measured attempts locally, but its cancellation check is outside the try and raises before returning an outcome; the outer cancellation handler receives processing_ms=None and persists no timing for the skipped item."},{"id":"GPUFLOW-1-SVCRUNTIMING-R-04","severity":"medium","file_path":"apps/prototype-description-service/scene/application/describe_async_worker.py","line":247,"summary":"Async processing_ms includes executor queue time rather than adapter dispatch time.","evidence":"_describe_adapter() starts perf_counter() before asyncio.to_thread(), so cpu_duration_ms/gpu_duration_ms include waiting for the default executor; the delta persists those values as item processing timing."},{"id":"GPUFLOW-1-SVCRUNTIMING-R-05","severity":"low","file_path":"apps/prototype-description-service/scene/application/describe_run_worker.py","line":639,"summary":"The new no-progress abort guard is unreachable for normal item paths.","evidence":"Every branch that reaches the post-item check sets progressed=True, while cancellation continues before the check; mark_item() return values are ignored, so a no-op or missing terminal transition is also counted as progress."}]

Verdict: fail

| Base | Tip | Files |
| --- | --- | --- |
| `5470fe815` | `cf8645899` | `apps/prototype-description-service/scene/application/describe_async_worker.py`; `apps/prototype-description-service/scene/application/describe_run_worker.py`; `apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py`; `apps/prototype-description-service/scene/tests/fixtures/gpuflow-run-items.json`; `apps/prototype-description-service/scene/tests/test_describe_run_items.py`; `apps/prototype-description-service/scene/tests/test_describe_run_routes.py`; `apps/prototype-description-service/scene/tests/test_describe_run_worker_phases.py` |

## FINDINGS

### GPUFLOW-1-SVCRUNTIMING-R-01 — high

File: `apps/prototype-description-service/scene/application/describe_run_worker.py:270-285`; regression coverage is in `apps/prototype-description-service/scene/tests/test_describe_run_worker_phases.py:312-350`.

Evidence: `_record_run_readiness()` mints `startup_id = uuid.uuid4().hex` independently for every cold run, then derives `startup_ms` from `run.started_at`. The repository's pickup operation sets `started_at` at worker pickup, not at an observed GPU startup; no `DescribeStartup` association or first-ready observation is consulted. The new cold test asserts this fabricated value is non-null without seeding a startup observation.

Impact: Concurrent callers cannot join one shared startup, and the API reports a startup duration even when startup start was never observed. This violates the durable correlation and “startup_ms only when observed” contract in `gpu-lifecycle.md:349-353` and `image-description-api.md:309-313`, and conflicts with fail-closed metadata rule `[rg-015]`.

Fix: Associate the run/operation with the durable lifecycle startup record and reuse its startup ID under concurrency. Derive `startup_ms` only from persisted observed startup and first-ready UTC timestamps; otherwise leave it null. Keep each operation's own readiness wait as `ramp_up_ms`.

### GPUFLOW-1-SVCRUNTIMING-R-02 — high

File: `apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py:159-176`; consumer evidence is `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts:1053-1092` and the pass-through is `apps/prototype-wp-alt-context/src/api/class-describe-controller.php:472-489`.

Evidence: `_run_response()` now emits `operation_id`, `startup_id`, and `timing` once the worker records timing. The PHP status endpoint returns the recognition response unchanged, but `validateDescribeRunResponse()` permits only the required legacy keys plus `deadline_seconds` and returns an unexpected-key error for the first new field. A normal post-pickup poll therefore fails as soon as `timing` is present.

Impact: The SPA bulk status path cannot parse a run after pickup or completion, so operators lose live status and the new timing contract is unusable at the downstream boundary. This is a release-facing contract break despite the shared run schema permitting the fields.

Fix: Extend the SPA wire interface, allow-list, and runtime validator for opaque `operation_id`, nullable `startup_id`, the nested run timing object, and item `processing_ms`; add a PHP-to-TS fixture test that polls a measured run and preserves the nested shape.

### GPUFLOW-1-SVCRUNTIMING-R-03 — medium

File: `apps/prototype-description-service/scene/application/describe_run_worker.py:367-399,695-723`.

Evidence: `_describe_with_transient_retry()` accumulates measured attempt durations locally. After a transient failure it sleeps, then checks cancellation at line 370 before producing an outcome. That `_RunCancelledError` reaches the outer handler while the per-item `processing_ms` variable is still null, so the handler records no timing before marking the item skipped. A 503/timeout with measured adapter work followed by cancellation during retry backoff loses the measured attempt.

Impact: Cancelled items undercount measured work, reducing `processing_ms_p50`, `processing_ms_max`, and `items_timed`; consumers cannot distinguish this from genuinely untimed work. The required failed/skipped/cancelled retention behavior is not met.

Fix: Carry the retry accumulator on cancellation (for example, a typed cancellation exception carrying cumulative timing) and persist it in the cancellation branch. Add a fake-clock regression that cancels during retry backoff after one measured attempt.

### GPUFLOW-1-SVCRUNTIMING-R-04 — medium

File: `apps/prototype-description-service/scene/application/describe_async_worker.py:115-123,247-252,291-307`.

Evidence: `_describe_adapter()` starts its monotonic clock before `asyncio.to_thread()`, so a saturated executor contributes queue delay to the returned duration. The delta writes `cpu_duration_ms` and `cpu_duration_ms + gpu_duration_ms` directly into durable `processing_ms`, even though B1 requires adapter-attempt timing at actual dispatch with queue and non-adapter phases excluded.

Impact: Async item and run timing are inflated under concurrency and are not comparable with the synchronous visual-facts attempt measurements. Downstream timing displays and p50/max aggregation can report executor contention as model processing.

Fix: Expose a typed adapter-attempt timing measured inside the dispatched callable (and on failures), then persist only that dispatch-to-return interval. Keep queue/readiness and adapter processing as separate observations.

### GPUFLOW-1-SVCRUNTIMING-R-05 — low

File: `apps/prototype-description-service/scene/application/describe_run_worker.py:637-648,709-798`.

Evidence: `progressed` is initialized false, but every reachable cancellation, exception, and success branch sets it true; the cancellation branch at line 648 skips the guard entirely. In addition, each `mark_item()` result is discarded, so a false/no-op terminal transition still resets `no_progress`.

Impact: The added `rg-007` fail-safe does not detect the no-terminal-progress condition it claims to protect. A repository race or missing item can leave a run nonterminal without invoking the intended abort path, potentially keeping batch demand active.

Fix: Treat progress as the successful terminal transition (or re-read the item status), handle false transitions explicitly, and add a regression that exercises three consecutive no-op transitions.

## Verification

- Changed paths in the supplied delta: 7; all are within the lane's stated owned-path list.
- Mandated composer-lock test: passed (`1 passed`).
- The lane service test command was attempted with the lane `.venv` interpreter; it emitted one dot and then hung in this sandbox, so its result is not trusted.
