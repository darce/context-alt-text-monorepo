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

