# GPUOPS-1 lane L5 — Settings › Burst GPU card

Branch `feature/gpuops-1-spa`, worktree `context-alt-text-monorepo-gpuops-1-spa`. Owns `apps/prototype-wp-alt-context/js/admin/api/gpuApi.ts`, `js/admin/api/queryKeys.ts`, `js/admin/pages/settings/GpuControlCard.tsx`, `js/admin/pages/settings/useGpuControl.ts`, `js/admin/pages/SettingsPage.tsx`, their tests, `js/admin/__tests__/uxmap-parity.test.ts`, `js/admin/__tests__/uxmap-render-parity.test.ts`, and `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md` (rendered).

## Goal

Implement contract C5 as designed in `docs/ux-maps/gpu-operator-control.uxmap.json` and the ASCII screens in `gpu-operator-control.notes.md`, and enrol that map in the parity gates.

## Current anchors

- `js/admin/pages/workbench/gpuStatePresentation.ts`: `GPU_STATE`, `GPU_STATE_VOCABULARY`, `GPU_STATE_PRESENTATION`, `gpuStatePresentation(state)`; the chip in `MediaSelection.tsx` ~:794 shows how it is rendered. Reuse, do not duplicate copy.
- `js/admin/pages/SettingsPage.tsx`: `<SettingsForm>` mounted ~:262, retention section ~:311. Mount the card as its own section after the form.
- `js/admin/api/settingsApi.ts` and `describeApi.ts` show the fetch wrapper, error mapping (`wpErrorMessage.ts`) and query-key conventions.
- Parity tests: `OWNED_MAPS`, `REQUIRED_OWNED_MAPS`, `REQUIRED_GENERATED_MAPS` in `uxmap-render-parity.test.ts` (~:89, ~:164, ~:180). The on-disk gate fails for a map that is on disk but not enrolled, so enrol `gpu-operator-control` in all three and render the markdown with `python3 apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py gpu-operator-control`. Never hand-edit the `.md`.

## Deliverables

1. `gpuApi.ts`: `fetchGpuStatus()` → `GET acx/v1/recognition/gpu/status`, `postGpuIntent({action, ttl_seconds?})` → `POST acx/v1/recognition/gpu/intent`; types mirror C2/C3 exactly, with `GpuIntentAction` and `GpuIntentStatus` as `as const` objects (sr-007). Unknown extra fields are ignored, never fabricated (rg-015).
2. `useGpuControl.ts`: react-query polling at 15 s, 5 s while `starting|warming`; mutation with optimistic `intent_status = pending` reverted on error; derived flags `canStart`, `canStop`, `stopBlockedReason`, `canReturnToAuto`.
3. `GpuControlCard.tsx`: zones from the ux-map (`z-gpu-state-chip`, `z-gpu-intent`, `z-gpu-lease`, `z-gpu-load`, `z-gpu-cost`, `z-gpu-controls`), inline confirm strips for start and stop, one `role="status" aria-live="polite"` region, relative times computed from `server_time`, stale snapshot rendered as `not reported` with age (CAL-02, OBS-08). Design tokens only (sr-004); status pairs icon with colour.
4. `SettingsPage.tsx`: mount the card; no other change.
5. Parity enrolment and rendered `gpu-operator-control.md`.

## Tests

`cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/settings js/admin/__tests__/uxmap-parity.test.ts js/admin/__tests__/uxmap-render-parity.test.ts && npx tsc --noEmit`

Cover every ASCII screen state: stopped/auto zero state with Start enabled; start confirm shows cost, warm-up and TTL; starting/warming polls at 5 s and shows ETA; ready with `has_work` disables Stop with the reason; `blocked_work_in_flight` renders the pending notice; stale snapshot; 502 error with retry; Return to automatic only when intent ≠ auto.

## Non-goals

`SettingsForm.tsx`, `settingsConstants.ts`, `useSettingsPageState.ts` (L6); `DescribeRunApplyView.tsx`, `describeApi.ts` (L8); toasts (already exist).
