FINDINGS: [{"id":"GPUFLOW-1-SVCINSTRUMENTATION-R-04","severity":"medium","file_path":"apps/prototype-description-service/scene/application/describe_async_worker.py","line":121,"summary":"The live async describe worker still reports executor-queue time as adapter processing.","evidence":"_describe_adapter() starts perf_counter() before awaiting asyncio.to_thread(adapter.describe(...)) at lines 121-123, and the result is sent to the shared adapter-duration sink at lines 219-224 and 261-266. The delta's inside-worker timing wrapper in visual_facts_service.py does not cover this /describe/async path."},{"id":"GPUFLOW-1-SVCINSTRUMENTATION-R-05","severity":"low","file_path":"apps/prototype-description-service/recognition/tests/api/test_metrics.py","line":216,"summary":"lint(ruff): the added instrumentation tests fail configured Ruff checks and formatting.","evidence":"ruff check reports I001 in the newly added import block at recognition/tests/api/test_metrics.py:216 and in the new test import block at scene/tests/test_visual_facts_service.py:412, plus ASYNC110 for its polling sleep at :442; ruff format --check reports formatting changes on the delta's modified service and test lines."}]
Verdict: pass_with_findings

# GPUFLOW-1 svc-instrumentation review

| scope | value |
| --- | --- |
| base | `15c55e8854dddae6261b3f75f45a5cad5aaf0e8e` |
| tip | `fc30e30308d30a91b493a7de6d1dee8eef2587bd` |
| files | `apps/prototype-description-service/recognition/tests/api/test_metrics.py`; `apps/prototype-description-service/scene/application/visual_facts_service.py`; `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py`; `apps/prototype-description-service/scene/tests/test_visual_facts_service.py` |

The four changed paths are within the supplied five-path svc-instrumentation owned list; no sibling-lane implementation path appears. Previously submitted svc-instrumentation findings remain open in the handoff database and are intentionally not repeated here.

## FINDINGS

### GPUFLOW-1-SVCINSTRUMENTATION-R-04 — medium

- **File:line:** `apps/prototype-description-service/scene/application/describe_async_worker.py:121-123`, `:219-224`, `:261-266`.
- **Evidence:** The production `/describe/async` worker starts its timer before `await asyncio.to_thread(adapter.describe(...))`, then publishes the resulting wall interval to the same `acx_description_adapter_duration_seconds` sink used by the new service seam. That interval includes any executor queue delay. The delta's wrapper starts its timer inside the executor in `visual_facts_service.py:280-287`, but that code is not used by this async worker path.
- **Impact:** The shared adapter-processing histogram mixes scheduler queue time with actual adapter work, so processing latency is overstated and cannot be compared across sync and async descriptions under the slice's nonoverlap rule.
- **Fix:** Measure the async adapter attempt inside its executor-side wrapper (or route the path through the common service), and add a gated-executor regression test proving queue delay is excluded.

### GPUFLOW-1-SVCINSTRUMENTATION-R-05 — low

- **File:line:** `apps/prototype-description-service/recognition/tests/api/test_metrics.py:216`; `apps/prototype-description-service/scene/tests/test_visual_facts_service.py:412`, `:442`.
- **Evidence:** Configured `ruff check` reports I001 in the newly added import blocks and `ASYNC110` for the new test's `asyncio.sleep` polling loop; `ruff format --check` reports formatting changes on the delta's modified service and test lines.
- **Impact:** The delta fails the repository's configured lint/format checks even though the functional tests are intended to cover the timing seam.
- **Fix:** Apply Ruff's import sorting and formatter, and replace the polling loop with a synchronization primitive or a narrowly justified test-only wait.

## Verification

- The mandatory repository lock test passed (`1 passed`).
- The new cancellation-race test passed individually, and the new readiness/processing histogram test passed individually.
- The full lane-local service/metrics command was attempted with a 30-second bound but could not complete in this sandbox. A faulthandler dump showed `asyncio.run()` waiting for the default `asyncio.to_thread` executor to shut down; a standalone `asyncio.to_thread(lambda: None)` reproduces the same hang. This is an environment verification blocker, not a source edit made by this review.
- The owned package import resolves to this lane worktree.
