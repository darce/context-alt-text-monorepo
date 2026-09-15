FINDINGS: [{"id":"GPUFLOW-1-SVCINSTRUMENTATION-R-01","severity":"medium","file_path":"apps/prototype-description-service/recognition/interface_adapters/http/middleware/metrics.py","line":101,"summary":"The readiness-wait histogram has no production observation path.","evidence":"The delta registers acx_description_readiness_wait_seconds at metrics.py:101, but a production-tree scan finds no observe call or sink method; the only observation is the new test at recognition/tests/api/test_metrics.py:216. VisualFactsService's DescriptionMetrics protocol still exposes only observe_adapter_duration, and the route sink implements only that method."},{"id":"GPUFLOW-1-SVCINSTRUMENTATION-R-02","severity":"medium","file_path":"apps/prototype-description-service/scene/application/visual_facts_service.py","line":176,"summary":"Per-attempt processing timing is a write-only last-value side channel, so retries and failed items cannot be summed by the run consumer.","evidence":"last_processing_ms is overwritten at visual_facts_service.py:195 and :255. The real run adapter returns DescribeItemOutcome without this value (describe_run.py:268-275), while _describe_with_transient_retry returns only the latest outcome after each attempt (describe_run_worker.py:273-293); response.duration_ms remains the whole-service _elapsed_ms(start), not adapter processing."},{"id":"GPUFLOW-1-SVCINSTRUMENTATION-R-03","severity":"medium","file_path":"apps/prototype-description-service/scene/application/visual_facts_service.py","line":248,"summary":"Cancellation or timeout can race executor dispatch and leave an adapter attempt unmeasured.","evidence":"The delta submits asyncio.to_thread(dispatch) at visual_facts_service.py:244, then its cancellation/timeout finally block checks for the start marker at :248 and skips all recording when absent. If the executor future is already running but cancellation resumes the coroutine before dispatch executes its first marker assignment at :238, dispatch can still run and complete after the check without any metric or last_processing_ms publication; the added cancellation test starts only after that marker boundary."}]
Verdict: pass_with_findings

# GPUFLOW-1 svc-instrumentation review

| scope | value |
| --- | --- |
| base | `112f262cd` |
| tip | `1d251e12e` |
| files | `apps/prototype-description-service/recognition/interface_adapters/http/middleware/metrics.py`; `apps/prototype-description-service/recognition/tests/api/test_metrics.py`; `apps/prototype-description-service/scene/application/visual_facts_service.py`; `apps/prototype-description-service/scene/tests/test_visual_facts_service.py` |

The four changed paths are exactly the supplied svc-instrumentation owned list; no sibling-lane implementation path is part of this delta. The dispatch wrapper correctly moves the normal adapter start marker inside the executor and records ordinary failures without including the executor queue, but the handoff does not yet provide a complete, race-safe timing stream for downstream builders.

## FINDINGS

### GPUFLOW-1-SVCINSTRUMENTATION-R-01 — medium

- **File:line:** `apps/prototype-description-service/recognition/interface_adapters/http/middleware/metrics.py:101`.
- **Evidence:** `description_readiness_wait_seconds` is registered, but no production code observes it. The only `.observe(30)` is the new unit test; `VisualFactsService` and `_DescriptionMetricsSink` expose/implement adapter processing only.
- **Impact:** Prometheus reports no readiness waits, so the claimed readiness/processing histogram split is not operational and the nonoverlap invariant cannot be monitored. A downstream route that forgets to wire the property will silently leave the series empty.
- **Fix:** Add an explicit readiness-observation seam at the durable operation/readiness owner and emit one observation per operation (including the contract-defined zero for warm/cache paths). Test the production service/route seam rather than only manually observing both registry fields.

### GPUFLOW-1-SVCINSTRUMENTATION-R-02 — medium

- **File:line:** `apps/prototype-description-service/scene/application/visual_facts_service.py:176`.
- **Evidence:** `last_processing_ms` is overwritten on each invocation. The real run adapter currently constructs `DescribeItemOutcome` without it, and `_describe_with_transient_retry` returns the latest outcome after each attempt; failed final attempts have no outcome at all. The only value handed to the current run provenance is the legacy `response.duration_ms`, which is measured from the beginning of `describe` and includes non-adapter work.
- **Impact:** The run consumer cannot persist the schema's per-item `processing_ms` as the sum of measured attempts. Retries lose earlier attempt durations, and failed/cancelled items become indistinguishable from untimed items or receive the wrong whole-service duration, preventing honest `p50`, `max`, and `items_timed` values.
- **Fix:** Expose the measured attempt as a typed result/field that survives success and failure, accumulate it in the retry loop, and persist nullable sums (zero only for a true cache path and null when no dispatch occurred). Do not substitute `duration_ms` for adapter processing.

### GPUFLOW-1-SVCINSTRUMENTATION-R-03 — medium

- **File:line:** `apps/prototype-description-service/scene/application/visual_facts_service.py:248`.
- **Evidence:** The executor wrapper writes `attempt["start"]` only when `dispatch` begins, while the outer `finally` checks the dictionary immediately after cancellation/timeout. A running executor future can therefore be canceled from the awaiter's perspective before the wrapper executes that first assignment; the adapter still runs, but the outer block skips recording. The added cancellation test signals only after `dispatch` has crossed the start marker, so it does not exercise this boundary race.
- **Impact:** A real adapter attempt can consume compute and finish with no histogram observation and `last_processing_ms=None`, undercounting processing and making downstream timing aggregates falsely report an untimed item.
- **Fix:** Synchronize the dispatch-start/finish state and make exactly one publisher own the completed or canceled attempt, distinguishing a never-dispatched canceled future from work that actually entered the adapter. Add a forced executor-race test covering timeout/cancellation before the marker executes.

## Verification

- Repository lock test: passed (`1 passed`).
- Lane test collection: passed (`17 tests collected`).
- Lane test execution: blocked in this sandbox; the declared service/metrics invocation hung in the existing `asyncio.to_thread` path and was bounded/interrupted. No implementation files were changed by verification.
