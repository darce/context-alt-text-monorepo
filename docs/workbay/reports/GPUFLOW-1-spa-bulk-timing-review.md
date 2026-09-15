FINDINGS: [{"id":"GPUFLOW-1-SPABULKTIMING-R-01","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx","line":1030,"summary":"The bulk progress surface never renders the run timing fields required by B2.","evidence":"The changed production code references only timing.server_elapsed_ms and timing.startup_ms (lines 870-885); queue_ms, ramp_up_ms, processing_ms_p50, processing_ms_max, and items_timed are never rendered. The new fixture supplies queue_ms=10, ramp_up_ms=0, processing_ms_p50=12.5, processing_ms_max=30, and items_timed=2, while the new terminal assertion checks only server elapsed (MediaSelection.statusAnnouncement.test.tsx:414-425)."},{"id":"GPUFLOW-1-SPABULKTIMING-R-02","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx","line":870,"summary":"The terminal announcement presents server elapsed as processing latency and hides independent known timing fields.","evidence":"formatTerminalTimingAnnouncement() returns null whenever server_elapsed_ms is null, then labels that field as '%d described ... in %s s' and appends 'GPU startup' for startup_ms. The B2 mapping defines server_elapsed_ms as evidence-only, requires ramp_up_ms as 'Waited for service', and reserves 'Started in' for an independently known startup_ms; timing fields are nullable independently (docs/workbay/reports/GPUFLOW-1-ux-screens.md:455-466)."},{"id":"GPUFLOW-1-SPABULKTIMING-R-03","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/hooks/useDescribeRunProgress.ts","line":186,"summary":"Warming is inferred from global GPU telemetry and run ETA rather than the run phase, causing false warmup states and a fabricated fallback estimate.","evidence":"isWarming becomes true for any nonterminal run with gpu_state='starting' and eta_seconds=null, including queued or already-describing runs; the component returns before phase handling at MediaSelection.tsx:989-1000. The run API describes eta_seconds as remaining run ETA, while gpu_state is a global lifecycle snapshot, and the worker records the authoritative run WARMING phase before waiting (scene-describe-run.schema.json:71-89; gpu-lifecycle.md:262-302; describe_run_worker.py:731-749). When the actual phase is warming but the heuristic is false, MediaSelection.tsx:1015-1021 still says 'about 2 min, first run only'."},{"id":"GPUFLOW-1-SPABULKTIMING-R-04","severity":"low","file_path":"apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/fixtures/gpuflow-bulk-timing.json","line":86,"summary":"The new timing proof uses a timing:null payload that the real run parser rejects and does not assert the B2 field mapping.","evidence":"The fixture's run_warming object contains timing:null, but describeApi.ts:1320-1328 validates a present timing key as an object with the seven required fields; the backend omits the timing object when no observation exists. The hook test mocks fetchBulkDescribeRun directly (useDescribeRunProgress.test.tsx:602-610), and the component tests manually force isWarming (MediaSelection.statusAnnouncement.test.tsx:391-410), so the invalid wire shape and the missing queue/ramp-up/median/max/items_timed rendering can both remain green. [GRPH-26]"}]
Verdict: pass_with_findings

# GPUFLOW-1 spa-bulk-timing review

| Base | Tip | Files |
| --- | --- | --- |
| `39332bdba81751e68e4dd881eaad9aee05c1487c` | `f9cc4c8faebb16b16eed684e63eae10e0de84823` | Five changed paths; all are within the declared `spa-bulk-timing` owned list. |

## FINDINGS

### GPUFLOW-1-SPABULKTIMING-R-01 — medium

File: `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:1030-1053,1056-1077`

Evidence: The changed production code references only `timing.server_elapsed_ms` and `timing.startup_ms` in `formatTerminalTimingAnnouncement()` (`:870-885`). It never renders `queue_ms`, `ramp_up_ms`, `processing_ms_p50`, `processing_ms_max`, or `items_timed`. The new fixture supplies `queue_ms=10`, `ramp_up_ms=0`, `processing_ms_p50=12.5`, `processing_ms_max=30`, and `items_timed=2` (`gpuflow-bulk-timing.json:18-27`), but the new terminal assertion checks only server elapsed (`MediaSelection.statusAnnouncement.test.tsx:414-425`). The queued, warming, and describing returns also have no timing row.

Impact: The operator cannot distinguish service ramp-up from image processing or inspect the required median/slowest run evidence. This leaves the B2 run summary absent even though the timing object is successfully passed through the hook, contrary to the wire-only mapping and the progress disclosure expected by `[INT-08]` and `[GRPH-26]`.

Fix: Add a run timing row to the live and terminal surfaces. Render each non-null wire field independently: queue once, `Waited for service` once (including zero), median/slowest only with their measured-item scope, and `Started in` only for a non-null startup value. Omit absent/unknown values and do not calculate replacements in the SPA.

### GPUFLOW-1-SPABULKTIMING-R-02 — medium

File: `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:864-885`

Evidence: `formatTerminalTimingAnnouncement()` returns `null` whenever `server_elapsed_ms` is null, then labels that field as `'%d described ... in %s s'` and appends `GPU startup` for `startup_ms`. The B2 evidence mapping defines `server_elapsed_ms` as service acceptance-to-completion evidence only, requires `ramp_up_ms` to be shown as `Waited for service`, and reserves `Started in` for an independently known `startup_ms` (`docs/workbay/reports/GPUFLOW-1-ux-screens.md:455-466`). The seven timing fields are nullable independently, so a known startup or ramp-up value must not depend on server elapsed being present. This violates `[rg-015]` by changing the meaning of an upstream value in presentation.

Impact: Screen readers receive a misleading processing duration that can include correlated retry gaps, while valid startup/readiness evidence disappears whenever server elapsed is unknown. Operators may treat server time as per-image processing and misread cold-start behavior.

Fix: Remove server elapsed from user-facing processing copy (retain it only in evidence details). Format ramp-up and per-image aggregates from their own wire fields, and append the exact `Started in` copy only when `startup_ms` is non-null; unknown fields remain omitted.

### GPUFLOW-1-SPABULKTIMING-R-03 — medium

File: `apps/prototype-wp-alt-context/js/admin/hooks/useDescribeRunProgress.ts:182-186`; rendering branch `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:989-1025`

Evidence: `isWarming` becomes true for any nonterminal run with `gpu_state === 'starting'` and `eta_seconds === null`, including a queued run or a run already in the authoritative `describing` phase. `BulkDescribeProgress` returns on this heuristic before handling `run.phase` (`:989-1000`), which suppresses the progress bar and stall state. The run schema describes `eta_seconds` as remaining run ETA and `gpu_state` as a lifecycle snapshot (`packages/shared-contracts/schemas/scene-describe-run.schema.json:71-89`); the lifecycle contract says that snapshot is global and carried verbatim (`docs/workbay/contracts/gpu-lifecycle.md:262-302`). The worker persists `WARMING` before waiting and `DESCRIBING` after readiness (`apps/prototype-description-service/scene/application/describe_run_worker.py:731-749`). Conversely, when the actual phase is `warming` but this heuristic is false, the existing branch still emits `Warming GPU (about 2 min, first run only)…` (`MediaSelection.tsx:1015-1021`).

Impact: A run can be announced as service-starting while it is queued or processing because another/global lifecycle snapshot is starting, and a real warmup path still shows an unmeasured two-minute estimate. This misleads the operator and can hide genuine progress, violating the no-fabricated-data rule and `[INT-08]`.

Fix: Gate the warmup presentation on the run's authoritative phase and a dedicated wire warmup estimate when one exists. If no warmup estimate is supplied, say the service is starting without a duration; never use the run's processing ETA or a hard-coded duration to label ramp-up.

### GPUFLOW-1-SPABULKTIMING-R-04 — low

File: `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/fixtures/gpuflow-bulk-timing.json:74-86`; tests `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx:602-610` and `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx:391-410`

Evidence: `run_warming` contains `timing: null`, but `describeApi.ts:1320-1328` validates a present `timing` key as an object with all seven required fields. The real backend omits the timing object when no observation exists. The hook test mocks `fetchBulkDescribeRun` directly, bypassing that parser, and the component helper manually sets `isWarming` rather than deriving it from the hook. The only measured terminal assertion checks server elapsed/startup, not queue, ramp-up, median, slowest, or measured-item scope. `[GRPH-26]` requires missing wire values to remain absent rather than being represented by an invalid null shape.

Impact: The new proof can pass while the actual parsed wire payload is rejected and while the required B2 mapping is still absent; it also does not protect the zero-ramp-up and multi-item behaviors named by the slice proof.

Fix: Use an omitted `timing` key for the absent case and a valid timing object with independent null fields for partial observations. Exercise the parser/boundary fixture, assert every mapped field (including zero ramp-up and `items_timed` scope), and add a phase-aware warming case without forcing derived hook state.

## Verification

- Changed-path audit: 5 paths from `.review/CHANGE.diff`; all match the declared `spa-bulk-timing` owned paths.
- Required lane test: `.venv/bin/python -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` — 1 passed.
- Requested Vitest command was attempted from `apps/prototype-wp-alt-context`; this sandbox has no local `node_modules/.bin/vitest`, and `npx` did not resolve an executable within the timeout, so its result is not trusted.
