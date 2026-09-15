# GPUFLOW-1 spa-description-service review

Verdict: pass_with_findings

| scope | value |
| --- | --- |
| base | `eff8e6025` |
| tip | `be5bbb5c1` |
| files | `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/fixtures/gpuflow-service-states.json`; `apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/__tests__/RetentionPage.test.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/GpuControlCard.test.tsx` |

The five changed paths are all within the lane-owned list; no sibling-lane path is changed. The six-state fixture remains aligned with the centralized `GPU_STATE`/`gpuStatePresentation` vocabulary and the retention change adds an announced fetching state while preventing duplicate retries. Suggest warming/retry and UX-map edits are separate downstream lanes in the plan and are not counted as findings against this delta.

## FINDINGS

### GPUFLOW-1-SPADESCRIPTIONSERVICE-R-01 — medium

- **File:line:** `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx:320,349`
- **Evidence:** The renamed operator copy still says `60 min lease cap` in the start confirmation and `separate lease cap` in the stop confirmation; the same card also renders `Lease: ...` at line 238. The GPUFLOW-1 plan's plain-language rule requires the UI to avoid `lease` in primary copy. This violates the controlled-vocabulary check in `[NAV-13]`.
- **Impact:** The card mixes the new “Description Service” language with lifecycle implementation jargon, so the A3 plain-language acceptance is incomplete and downstream UX-map copy can drift from the actual operator surface.
- **Fix:** Replace the visible terms consistently with operator language such as `60-minute maximum`/`service run limit`, including the lease row, and add a regression assertion that rendered primary copy contains none of `Burst GPU`, `A10`, or `lease`.

### GPUFLOW-1-SPADESCRIPTIONSERVICE-R-02 — medium

- **File:line:** `apps/prototype-wp-alt-context/js/admin/pages/RetentionPage.tsx:47-62`; `apps/prototype-wp-alt-context/js/admin/pages/__tests__/RetentionPage.test.tsx:380-395`
- **Evidence:** The fallback branch always renders `Backend unavailable — retention status cannot be loaded.` and never reads `retentionQuery.error`. The new test's `isError` table cases pass no error value and assert identical output for error and non-error states. The lane surface requirement calls for Retry to show fetching state and the last error; error handling should also identify the problem and correction per `[A11Y-17]`.
- **Impact:** When a refetch fails, the operator still receives no actionable last-error detail, making the Retry path opaque and leaving the promised retention recovery feedback unproved.
- **Fix:** Project the query error through the existing safe/localized error-message policy and render it after fetching completes alongside the retry action; add tests with an actual error payload and for the generic fallback when no safe detail exists.


## Re-review r2 (bff71580f..631795ff1)

Reviewer: gpt-5.6-luna (max), codex-remote run `spa-description-service-review-m6fvrblj`. The reviewer could not commit this section (report path outside its effective owned scope); appended verbatim by the orchestrator.

| finding | verdict | evidence |
| --- | --- | --- |
| `GPUFLOW-1-UXSERVICE-R-08` | `fixed` | `GpuControlCard.test.tsx` has_work case now keeps Stop enabled, confirms STOP is issued, and asserts the "Stopping after the current work finishes" copy; component only changed intent/stop-preview copy (no has_work gating). Sandbox vitest: 5 files / 60 tests passed after `npm ci`. |

### FINDINGS

#### GPUFLOW-1-SPADESCRIPTIONSERVICE-R-03 — low

- File: `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx:353`
- Evidence: `.review/CHANGE.diff:26-30` adds a 131-column literal; `.prettierrc:2` sets printWidth to 120.
- Impact: lint(prettier) only.

#### GPUFLOW-1-SPADESCRIPTIONSERVICE-R-04 — low

- File: `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx:357`
- Evidence: `.review/CHANGE.diff:31-35` reintroduces the 172-column literal; `.prettierrc:2` sets printWidth to 120.
- Impact: lint(prettier) only.

Verdict: pass_with_findings

## Re-review r3 (2b38de112..883ff5d3d)

| finding | verdict | evidence |
| --- | --- | --- |
| `UXSERV-M-05` | `partially_fixed` | The delta removes the locally derived 120-second countdown and polling text (`.review/CHANGE.diff:17-22`) and replaces it with a localized no-countdown message (`.review/CHANGE.diff:56-59`); the new test explicitly rejects digits in that message (`.review/CHANGE.diff:214-244`). This closes the invented-ETA/no-ETA half, but the diff adds no `eta_seconds` field or rendering path, so a valid upstream ETA would still be ignored. |
| `UXSERV-M-06` | `partially_fixed` | `useGpuControl` now gates `canStop` on the freshness-derived `effectiveState` (`.review/CHANGE.diff:388-398`), and the card hides the direct Start/Stop controls for stale or unknown display state (`.review/CHANGE.diff:76-153`), with tests for both cases (`.review/CHANGE.diff:264-307,352-385`). An already-open confirmation remains independent of that gate, so the stale/unknown action invariant is not complete. |

### FINDINGS

#### GPUFLOW-1-SPADESCRIPTIONSERVICE-R-05 — medium

- **File:line:** `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx:165-187,322-382`
- **Evidence:** The fix wraps the direct controls in `displayedState !== GPU_STATE.UNKNOWN` (`.review/CHANGE.diff:76-153`) but does not clear `confirmation` when a fresh response becomes stale/unknown. The unchanged `confirm` function still submits whichever action is stored (`GpuControlCard.tsx:181-187`), and both confirmation strips render from that state alone (`GpuControlCard.tsx:322-382`). The new stale/unknown tests render without an already-open confirmation (`.review/CHANGE.diff:264-307`), so they cannot catch a fresh-to-stale transition ([TEST-15]).
- **Impact:** A user can open Confirm start/stop on trusted telemetry, receive a stale/unknown update, and still submit the lifecycle intent from a confirmation that the safety gate intended to remove ([INT-10]).
- **Fix:** Clear pending confirmation when freshness or state becomes unknown, or guard/disable `confirm` unless the relevant snapshot is still fresh and known; add a transition test for both actions.

#### GPUFLOW-1-SPADESCRIPTIONSERVICE-R-06 — medium

- **File:line:** `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx:265-315`
- **Evidence:** The new fragment places `Return to automatic` inside the same `displayedState !== GPU_STATE.UNKNOWN` branch as Start/Stop and the added unknown test expects it absent even with `canReturnToAuto: true` (`.review/CHANGE.diff:76-153,295-307`). The read-only UX map's unknown action sketch retains `[secondary] Return to automatic` (`apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md:58-60`), while `useGpuControl` continues to report that recovery action independently of freshness (`useGpuControl.ts:110-125`). A stale/unknown snapshot with a non-automatic intent therefore loses the documented way to clear that intent ([HAI-04]).
- **Impact:** Manual Start/Stop intent can remain active with no in-card override until telemetry recovers; the implementation and map no longer agree on the recovery surface ([INT-10]).
- **Fix:** Keep Return to automatic available as the safe recovery action when `canReturnToAuto` is true, or revise the map and provide an equivalent recovery path; test stale/unknown non-AUTO intents.

Verdict: pass_with_findings

## Re-review r4 (87c03bd04..99cf1d247)

| finding | verdict | evidence |
| --- | --- | --- |
| `UXSERV-M-05` | `partially_fixed` | The r4 component hunks address confirmation safety and action placement only (`.review/CHANGE.diff:1-66`); they add no `eta_seconds` field, prop, or rendering branch. The existing no-countdown warming copy therefore remains, but a legitimate upstream ETA is still unavailable. |
| `UXSERV-M-06` | `fixed` | The confirmation effect and click-time guard now prevent Start/Stop submission after the effective state becomes unknown or the action is no longer allowed (`.review/CHANGE.diff:8-29`), while the direct controls remain hidden for unknown/stale display state in the resulting component. The new stale/unknown assertions cover the control boundary (`.review/CHANGE.diff:84-115,117-159`). |
| `GPUFLOW-1-SPADESCRIPTIONSERVICE-R-09` | `fixed` | The effect clears an open confirmation when the snapshot becomes unknown/stale or the selected action loses eligibility, and `confirm()` rechecks `canStart`/`canStop` before requesting an intent (`.review/CHANGE.diff:8-29`). Fresh-to-stale Start and Stop transition tests assert both strips disappear and no intent is sent (`.review/CHANGE.diff:117-159`). |
| `GPUFLOW-1-SPADESCRIPTIONSERVICE-R-10` | `fixed` | `Return to automatic` is moved outside the `displayedState !== GPU_STATE.UNKNOWN` block, so `canReturnToAuto` controls it independently on stale/unknown snapshots (`.review/CHANGE.diff:31-66`); card and hook tests cover non-AUTO stale/unknown recovery (`.review/CHANGE.diff:84-115,247-275`). |

### FINDINGS

FINDINGS: []

Verdict: pass_with_findings

## Re-review r4c (87c03bd04..99cf1d247)

VERIFIED: {"UXSERV-M-05":"partially_fixed","UXSERV-M-06":"fixed","GPUFLOW-1-SPADESCRIPTIONSERVICE-R-09":"fixed","GPUFLOW-1-SPADESCRIPTIONSERVICE-R-10":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| `UXSERV-M-05` | `partially_fixed` | The delta only changes confirmation safety and action placement (`.review/CHANGE.diff:4-66`); it adds no `eta_seconds` field, status-boundary plumbing, or ETA rendering branch. The pre-existing generic warming message therefore remains the only surface, so a legitimate upstream ETA is still unavailable. |
| `UXSERV-M-06` | `fixed` | The resulting card keeps the direct Start/Stop controls inside the known-state branch (`.review/CHANGE.diff:46-51`) and the new effect/click guard removes or rejects an open confirmation when the state becomes unknown or the action is no longer allowed (`.review/CHANGE.diff:9-29`). Stale and unknown card cases assert the controls are absent (`.review/CHANGE.diff:93-115`). |
| `GPUFLOW-1-SPADESCRIPTIONSERVICE-R-09` | `fixed` | The effect clears confirmation on an unknown/stale effective state or lost eligibility, and `confirm()` rechecks `canStart`/`canStop` before calling `requestIntent` (`.review/CHANGE.diff:9-29`). Fresh-to-stale Start and Stop transition tests assert both confirmation strips disappear and no intent is sent (`.review/CHANGE.diff:117-159`). |
| `GPUFLOW-1-SPADESCRIPTIONSERVICE-R-10` | `fixed` | `Return to automatic` is removed from the known-state-only fragment and re-rendered under the independent `canReturnToAuto` condition (`.review/CHANGE.diff:31-66`). Card stale/unknown cases and the hook stale non-AUTO case cover the recovery surface (`.review/CHANGE.diff:84-115,247-275`). |

### FINDINGS

FINDINGS: []

Verdict: pass_with_findings

## Re-review r5 (58ea6cfb6..2201468a6)

VERIFIED: {"GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-08":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| `GPUFLOW-1-PHPBREAKERPASSTHROUGH-R-08` | `fixed` | The fix adds `STARTING: 'starting'` to the canonical `TestConnectionOutcome` object, which feeds `KNOWN_TEST_CONNECTION_OUTCOMES` through `Object.values`, and adds a dedicated `STARTING` branch that renders an informational banner with ETA fallback handling (`.review/CHANGE.diff:50-66,227-231,382-396`). The added contract and banner tests exercise canonical recognition and ETA/no-ETA rendering (`.review/CHANGE.diff:25-46,113-152`). |

### FINDINGS

#### GPUFLOW-1-SPADESCRIPTIONSERVICE-R-11 — low

- File: `apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts:63`
- Evidence: The refactor adds the 140-column unknown-outcome string as a new line (`.review/CHANGE.diff:216-225`), while the lane Prettier configuration sets `printWidth` to 120 (`apps/prototype-wp-alt-context/.prettierrc:2`).
- Impact: `lint(prettier)` only; the changed file will fail formatting checks until the message is wrapped.
- Fix: Wrap the localized message at the configured print width.

FINDINGS: [{"id":"GPUFLOW-1-SPADESCRIPTIONSERVICE-R-11","severity":"low","file_path":"apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts","line":63,"summary":"lint(prettier): newly added unknown-outcome message exceeds the 120-column print width","evidence":".review/CHANGE.diff:216-225 adds the 140-column line; .prettierrc:2 sets printWidth to 120."}]

Verdict: pass_with_findings

## Re-review r6 (6192796d5..d10728f08)

VERIFIED: {"CALIBR-M-05":"fixed","SVCCOL-M-01":"fixed","SPADES-M-11":"fixed"}

| finding | verdict | evidence |
| --- | --- | --- |
| `CALIBR-M-05` | `fixed` | `GpuControlCard` factors Refresh into a control disabled by `isFetching` (`.review/CHANGE.diff:97-106`) and renders it for `isError && !data` outside the data branch (`.review/CHANGE.diff:176-184`); the added tests cover initial-error retry and the disabled fetching state (`.review/CHANGE.diff:307-341`). |
| `SVCCOL-M-01` | `fixed` | `intentLabel` now emits `Stopping after the current work finishes until idle` for blocked/deferred STOP state (`.review/CHANGE.diff:27-39`), while the has-work confirmation emits the distinct `Stop after the current run finishes?` question (`.review/CHANGE.diff:159-168`); tests assert both strings (`.review/CHANGE.diff:274-300`). |
| `SPADES-M-11` | `fixed` | The invalidation effect checks only the selected action's eligibility, records a reason, and clears that confirmation when it becomes disallowed (`.review/CHANGE.diff:68-89`). The added transition test changes Start from allowed to disallowed while Stop remains allowed and verifies the preview/request are absent (`.review/CHANGE.diff:344-370`). |

### FINDINGS

#### GPUFLOW-1-SPADESCRIPTIONSERVICE-R-12 — low

- File: `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx:278`
- Evidence: The fix collapses the load ternary into a 125-character line (`.review/CHANGE.diff:121-130`), while the lane Prettier configuration sets `printWidth` to 120 (`apps/prototype-wp-alt-context/.prettierrc:2`).
- Impact: lint(prettier) only; the changed card will fail the configured formatting check until the expression is wrapped.
- Fix: Wrap the load expression at the configured print width.

FINDINGS: [{"id":"GPUFLOW-1-SPADESCRIPTIONSERVICE-R-12","severity":"low","file_path":"apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx","line":278,"summary":"lint(prettier): the changed load-row expression exceeds the 120-column print width","evidence":".review/CHANGE.diff:121-130 adds the 125-character line; apps/prototype-wp-alt-context/.prettierrc:2 sets printWidth to 120."}]

Verdict: pass_with_findings
