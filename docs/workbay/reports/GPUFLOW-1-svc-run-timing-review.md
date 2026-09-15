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

## Re-review r2 (cf8645899..3601dc287)

VERIFIED: {"GPUFLOW-1-SVCRUNTIMING-R-01":"partially_fixed","GPUFLOW-1-SVCRUNTIMING-R-03":"fixed","GPUFLOW-1-SVCRUNTIMING-R-04":"partially_fixed","GPUFLOW-1-SVCRUNTIMING-R-05":"partially_fixed"}

FINDINGS: [{"id":"GPUFLOW-1-SVCRUNTIMING-R-06","severity":"high","file_path":"apps/prototype-description-service/scene/application/describe_run_worker.py","line":305,"summary":"Cold runs without a durable startup observation report zero readiness wait.","evidence":"The new cold path returns (None, None) when no retained DescribeStartup row is available (lines 270-290) and passes startup_id=None to record_readiness (lines 293-312). The existing repository maps that null association to ramp_up_ms=0, even though the worker just waited through a cold GPU gate. The added regression (test_describe_run_worker_phases.py:389-425) checks only null IDs and never checks ramp_up_ms."},{"id":"GPUFLOW-1-SVCRUNTIMING-R-07","severity":"medium","file_path":"apps/prototype-description-service/scene/tests/test_describe_run_worker_phases.py","line":518,"summary":"Retry-cancellation coverage injects timing instead of measuring an adapter attempt.","evidence":"The regression assigns exc.processing_ms = 42 to a synthetic ConnectError (lines 517-520) and then verifies propagation. It does not fake or assert the monotonic attempt clock, so a regression that leaves real adapter failures unmeasured can still pass this proof."}]

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-SVCRUNTIMING-R-01 | partially_fixed | `describe_run_worker.py:270-290` now reads a retained `DescribeStartup` row and leaves `startup_ms` null without observations, but it selects the newest retained global row rather than the run operation's durable `startup_id`; concurrent/restarted operations can still receive an unrelated startup correlation. |
| GPUFLOW-1-SVCRUNTIMING-R-03 | fixed | `describe_run_worker.py:393-434` carries the cumulative retry measurements on `_RunCancelledError`, and `:742-756` persists that value before marking the item skipped; the added backoff-cancellation regression exercises the propagation. |
| GPUFLOW-1-SVCRUNTIMING-R-04 | partially_fixed | `describe_async_worker.py:115-126` starts the clock inside the dispatched callable, removing executor queue delay on successful returns, but an adapter exception exits before `_elapsed_ms()` and no failure timing is attached or persisted. |
| GPUFLOW-1-SVCRUNTIMING-R-05 | partially_fixed | `describe_run_worker.py:673-815` now uses terminal `mark_item()` results for progress, but the production repository returns `current == status` for an already-terminal item and the regression stub (`test_describe_run_worker_phases.py:576-587`) bypasses that no-op behavior. |

### FINDINGS

#### GPUFLOW-1-SVCRUNTIMING-R-06 — high

File: `apps/prototype-description-service/scene/application/describe_run_worker.py:270-312`; regression coverage is `apps/prototype-description-service/scene/tests/test_describe_run_worker_phases.py:389-425`.

Evidence: `_observed_startup()` returns `(None, None)` when no retained startup row is found, and `_record_run_readiness()` forwards that null `startup_id` for a cold wait. `DescribeRunRepository.record_readiness()` treats a null startup association as the warm path and writes `ramp_up_ms = 0`, so an actually delayed cold readiness wait is silently reported as zero. The new test asserts only `startup_id` and `startup_ms` are null, leaving this contract break green. This violates the “own wait stays `ramp_up_ms`” and no-fabricated-metadata rule `[rg-015]`.

Impact: A cold run with an unobserved or temporarily unavailable startup underreports readiness latency and can make p50/max or operator diagnostics claim a warm path. The service must preserve the measured operation wait independently of whether whole-startup timing is available.

Fix: Keep the `cold` state separate from startup association when calling the repository; persist the measured readiness wait for cold runs, while leaving only `startup_id`/`startup_ms` null when the durable observation is unavailable. Add an assertion for positive/nonzero cold `ramp_up_ms` with no startup row.

#### GPUFLOW-1-SVCRUNTIMING-R-07 — medium

File: `apps/prototype-description-service/scene/tests/test_describe_run_worker_phases.py:510-573`.

Evidence: The cancellation regression sets `exc.processing_ms = 42` on a hand-built `httpx.ConnectError` before invoking the worker. It proves that an already-present timing attribute is carried through backoff cancellation, but it never advances or controls the monotonic clock and never measures a real adapter attempt. A failure in the adapter timing producer would therefore remain undetected. This leaves the required fake-clock/actual-attempt proof incomplete `[TEST-15]`.

Impact: The test suite can stay green while cancelled retries persist a synthetic or absent duration, so measured failed/cancelled work can still disappear from run timing aggregates.

Fix: Use a fake monotonic clock around a dispatched attempt (or the real adapter timing hook), raise a transient error after advancing it, cancel during backoff, and assert the persisted value is the measured elapsed duration.

Verdict: fail

## Re-review r3 (3601dc287..16a393fdc)

VERIFIED: {"GPUFLOW-1-SVCRUNTIMING-R-01":"fixed","GPUFLOW-1-SVCRUNTIMING-R-04":"fixed","GPUFLOW-1-SVCRUNTIMING-R-05":"fixed","GPUFLOW-1-SVCRUNTIMING-R-06":"fixed","GPUFLOW-1-SVCRUNTIMING-R-07":"fixed"}

FINDINGS: [{"id":"GPUFLOW-1-SVCRUNTIMING-R-08","severity":"high","file_path":"apps/prototype-description-service/scene/application/describe_run_worker.py","line":361,"summary":"A warm retry overwrites retained cold readiness timing.","evidence":"The new post-record repair calls _measured_ramp_up_ms(run, cold=cold) and assigns its result unconditionally (.review/CHANGE.diff:167-173). A restarted worker that finds the GPU immediately ready passes cold=False and writes 0.0 even when a prior cold invocation already persisted first_ready_at and a positive ramp_up_ms; no retry-after-readiness regression covers this path [TEST-15]."},{"id":"GPUFLOW-1-SVCRUNTIMING-R-09","severity":"medium","file_path":"apps/prototype-description-service/scene/application/describe_run_worker.py","line":454,"summary":"Retry fallback counts pre-dispatch failures as adapter processing.","evidence":"_measured_attempt_ms() falls back to elapsed wait_for time whenever _attempt_processing_ms() returns None (.review/CHANGE.diff:180-198). That also covers VisualFactsService errors before its adapter dispatch marker or plain pre-dispatch failures, so cache/DB/quota/setup time is persisted as adapter work instead of remaining untimed; the fallback never checks entered_adapter [TEST-15] [rg-015]."},{"id":"GPUFLOW-1-SVCRUNTIMING-R-10","severity":"medium","file_path":"apps/prototype-description-service/scene/application/describe_run_worker.py","line":293,"summary":"Startup association can race the run readiness write.","evidence":"The fix reads the operation and its startup in separate non-locking scalar queries (.review/CHANGE.diff:96-114), then records run readiness later (.review/CHANGE.diff:145-166). If associate_startup commits after the lookup sees no startup_id but before or during record_readiness, the run stores a null startup association and is never repaired; the test seeds an already-associated operation but does not interleave the association [CON-05]."}]

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-SVCRUNTIMING-R-01 | fixed | `describe_run_worker.py:281-314` now resolves the run's operation within its tenant, follows that durable operation's `startup_id`, and derives `startup_ms` only from observed startup timestamps; the added fixture seeds an older and newer startup and asserts the operation-bound older one (`.review/CHANGE.diff:84-114,336-384`). |
| GPUFLOW-1-SVCRUNTIMING-R-04 | fixed | `_describe_adapter()` starts `perf_counter()` inside the dispatched callable and attaches elapsed timing on ordinary adapter exceptions; the async failure path persists that measurement, and the new failure test holds dispatch behind a queue delay (`.review/CHANGE.diff:4-18,28-43,475-525`). |
| GPUFLOW-1-SVCRUNTIMING-R-05 | fixed | Terminal branches now retain each `mark_item()` result and derive progress only when the prior item was non-terminal; the replacement regression uses real terminal no-op behavior across three items (`.review/CHANGE.diff:79-81,211-274,432-466`). |
| GPUFLOW-1-SVCRUNTIMING-R-06 | fixed | The helper now restores a cold run's `ramp_up_ms` from persisted `started_at`/`first_ready_at` even when `startup_id` is null, and the regression asserts a positive value (`.review/CHANGE.diff:121-126,167-173,387-393`). |
| GPUFLOW-1-SVCRUNTIMING-R-07 | fixed | The retry path measures each attempt with the monotonic clock when no producer timing exists, carries the cumulative value through cancellation, and the test advances a fake clock rather than injecting `processing_ms` (`.review/CHANGE.diff:176-210,395-425`). |
| GPUFLOW-1-SVCRUNTIMING-R-08 | not_fixed | The same post-record assignment returns `0.0` for every `cold=False` invocation (`.review/CHANGE.diff:121-126,167-173`), overwriting a retained positive cold wait on a warm restart/retry. |
| GPUFLOW-1-SVCRUNTIMING-R-09 | not_fixed | The fallback treats missing producer timing as proof of an adapter attempt and measures the entire `wait_for` call (`.review/CHANGE.diff:180-198`); it has no `entered_adapter` guard for pre-dispatch errors. |
| GPUFLOW-1-SVCRUNTIMING-R-10 | not_fixed | Operation/startup lookup is non-locking and separated from the later readiness write (`.review/CHANGE.diff:96-114,145-166`), leaving a race in which a concurrently associated startup is omitted from the run. |

Scope check: the supplied fix delta contains only the three worker/test paths in this review scope; no additional out-of-scope path is changed.

### FINDINGS

#### GPUFLOW-1-SVCRUNTIMING-R-08 — high

File: `apps/prototype-description-service/scene/application/describe_run_worker.py:317-363`; changed hunk `.review/CHANGE.diff:121-173`.

Evidence: `_measured_ramp_up_ms()` returns `0.0` whenever `cold` is false, and `_record_run_readiness()` assigns that result after every `record_readiness()` call. `DescribeRunRepository.record_readiness()` is first-observation-only, so a later warm health probe can leave the existing `first_ready_at` and positive cold `ramp_up_ms` intact until this new assignment erases it. A retry after readiness must retain the operation's first observation under the published timing contract. This is a silent data-loss/contract failure [TEST-15].

Impact: Restarted or retried runs can report zero readiness wait after genuinely waiting for a cold GPU, making run timing and downstream p50/diagnostic data understate the operation's lifecycle.

Fix: Reconcile `ramp_up_ms` only when the first readiness observation is newly recorded, or preserve the persisted value when `first_ready_at` already exists; add a second invocation regression where the first call is cold and the retry is warm.

#### GPUFLOW-1-SVCRUNTIMING-R-09 — medium

File: `apps/prototype-description-service/scene/application/describe_run_worker.py:416-456`; changed hunk `.review/CHANGE.diff:180-210`.

Evidence: The new `_measured_attempt_ms()` uses local elapsed time whenever `_attempt_processing_ms()` returns null. The upstream `AdapterAttemptTiming` contract distinguishes `entered_adapter=False` for cache, quota, DB, and other pre-dispatch failures, but this fallback ignores that marker and records the whole `_call_describe_one()`/`wait_for()` interval as adapter processing. The result contaminates item processing totals with non-adapter work instead of preserving an untimed null [rg-015] [TEST-15].

Impact: Failed items can be counted in `items_timed` and run p50/max even though no model attempt ran, while cache/setup or database latency is mislabeled as GPU/CPU processing.

Fix: Fall back to a monotonic interval only for a call that proves adapter dispatch; otherwise preserve null. Add a pre-dispatch failure regression alongside the actual dispatched-failure timing test.

#### GPUFLOW-1-SVCRUNTIMING-R-10 — medium

File: `apps/prototype-description-service/scene/application/describe_run_worker.py:281-357`; changed hunk `.review/CHANGE.diff:84-114,145-166`.

Evidence: `_observed_startup()` performs an ordinary operation read and startup read, then `_record_run_readiness()` later persists the run observation. `DescribeOperationRepository.associate_startup()` can update the operation between those awaits. If the lookup observes `startup_id=None`, the worker records `startup_id=None` even when the operation is associated before readiness commits, and no later repair links the run to the shared startup. The added test covers only an already-associated operation, not this interleaving [CON-05].

Impact: Concurrent callers can lose durable startup correlation and `startup_ms` despite a valid shared startup observation, weakening the restart/concurrency timing contract for affected runs.

Fix: Coordinate startup association and run readiness in one locking/transaction protocol, or re-read and reconcile the operation association immediately before commit; add a concurrent association/readiness regression.

Verdict: fail

## Re-review r4 (16a393fdc..40985abd9)

VERIFIED: {"GPUFLOW-1-SVCRUNTIMING-R-08":"partially_fixed","GPUFLOW-1-SVCRUNTIMING-R-09":"fixed","GPUFLOW-1-SVCRUNTIMING-R-10":"partially_fixed"}

FINDINGS: []

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-SVCRUNTIMING-R-08 | partially_fixed | The post-record repair is now gated by `first_ready_before is None and run.first_ready_at is not None`, and the added sequential warm-retry regression preserves the first positive ramp (`.review/CHANGE.diff:82-99,163-193`). The snapshot is still captured before the locked repository write (`.review/CHANGE.diff:49-58`), so a concurrent cold invocation can persist first readiness after that snapshot; a warm invocation can then satisfy `newly_recorded` and write `0.0` through `_measured_ramp_up_ms(cold=False)` (`.review/CHANGE.diff:89-95`). |
| GPUFLOW-1-SVCRUNTIMING-R-09 | fixed | `_adapter_was_dispatched()` now gates elapsed-time fallback on `attempt_timing.entered_adapter` or an equivalent result marker, returning `None` for unmarked pre-dispatch failures (`.review/CHANGE.diff:102-125`). The new pre-dispatch regression asserts a failed item keeps `processing_ms` null and `items_timed == 0` (`.review/CHANGE.diff:196-227`). |
| GPUFLOW-1-SVCRUNTIMING-R-10 | partially_fixed | The delta adds a second operation/startup lookup and a dialect-gated `FOR UPDATE` operation read (`.review/CHANGE.diff:8-43,49-64`), which closes an association committed before that reread. The operation lock/read still occurs before `record_readiness()` (`.review/CHANGE.diff:59-79`), so an association committed after the reread can still be omitted; the added regression mutates the operation in the same session rather than interleaving a committed concurrent transaction (`.review/CHANGE.diff:230-298`). |

### FINDINGS

Verdict: pass_with_findings
