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
