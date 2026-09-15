# GPUFLOW-1 spa-suggest-warming-timing review

## Re-review r1 (39332bdba..b16198ec3)

VERIFIED: {"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-02":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| `GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-02` | `fixed` | `useDescribeMedia` now retains the complete mutation input, routes the typed `detail.code` and `detail.operation_id` through the shared resolvers, and resubmits the retained input through `describeWithLease`, which sends the lease ID while preserving write options (`.review/CHANGE.diff:L349-L360,L375-L415,L426-L434`). The nested-error fixture and retry assertion cover the second call with `operationId` (`.review/CHANGE.diff:L173-L209`). |

### FINDINGS

FINDINGS: [{"id":"GPUFLOW-1-SPASUGGESTWARMINGTIMING-R-01","severity":"low","file_path":"apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts","line":605,"summary":"The delta changes API contract tests outside the supplied lane-owned paths.","evidence":"The lane row names the hook, Suggest component, and fixture as owned, with describeApi.ts as a read-only spa-describe-client dependency; it does not assign describeApi.test.ts or describeRunResponseContract.test.ts. The inlined delta nevertheless changes both API test paths (.review/CHANGE.diff:L1-L97), crossing the lane boundary."},{"id":"GPUFLOW-1-SPASUGGESTWARMINGTIMING-R-02","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAltSuggest.tsx","line":163,"summary":"Minute-boundary timing formatting can display an invalid 60-second remainder.","evidence":"formatMeasuredDuration rounds totalSeconds % 60 independently and emits the remainder without carrying 60 into minutes (.review/CHANGE.diff:L469-L478). A valid wire value of 119500 ms therefore renders as 1 m 60 s; the added tests cover only 1.2 s, 0 s, and 38 s (.review/CHANGE.diff:L780-L789,L813-L820)."}]

#### GPUFLOW-1-SPASUGGESTWARMINGTIMING-R-01 — low

- **File:line:** `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts:605`; `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeRunResponseContract.test.ts:3`
- **Evidence:** The supplied lane row assigns the hook, Suggest component, and fixture to this lane and names only `describeApi.ts` as the read-only `spa-describe-client` dependency. The delta also changes `describeApi.test.ts` and `describeRunResponseContract.test.ts` (`.review/CHANGE.diff:L1-L97`), which are outside that owned-path list.
- **Impact:** The fix commit crosses the lane ownership boundary, so the manifest cannot attribute or safely reconcile these API-test edits with the owning client lane.
- **Fix:** Move the API-test changes to `spa-describe-client`, or amend the lane ownership/dependency manifest before merge.

#### GPUFLOW-1-SPASUGGESTWARMINGTIMING-R-02 — medium

- **File:line:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAltSuggest.tsx:163`
- **Evidence:** `formatMeasuredDuration` computes `remainder = Math.round(totalSeconds % 60)` and emits it directly (`.review/CHANGE.diff:L469-L478`). Since the wire timing schema accepts nonnegative numeric milliseconds, `119500` is valid but produces `1 m 60 s`; the added assertions exercise only short values and do not cover the minute boundary (`.review/CHANGE.diff:L780-L789,L813-L820`).
- **Impact:** Operators can be shown an impossible duration at a normal rounding boundary, undermining the B2 timing display.
- **Fix:** Carry a rounded 60-second remainder into the minute count (or round total seconds before splitting), and add a `119500 ms` boundary regression.

Verdict: pass_with_findings

## Re-review r2 (b16198ec3..1d88cb512)

VERIFIED: {"GPUFLOW-1-SPASUGGESTWARMINGTIMING-R-02":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| `GPUFLOW-1-SPASUGGESTWARMINGTIMING-R-02` | `fixed` | `formatMeasuredDuration` now rounds milliseconds to whole seconds before deriving minutes and the seconds remainder, so a 119500 ms value carries into `2 m` rather than emitting `1 m 60 s` (`.review/CHANGE.diff:L89-L103`). The added regression assertions cover 119500 ms plus both sides of the minute boundary and a multi-minute value (`.review/CHANGE.diff:L122-L127`). |

### FINDINGS

FINDINGS: []

Verdict: pass
