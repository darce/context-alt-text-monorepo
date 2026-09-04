# GPUUX-1 E2 toast lane report

## Change summary

- Added a `useSyncExternalStore` active-run store for the submitted run id and the progress-zone mounted signal.
- Published successful submissions from `useBulkDescribe`, cleared the active signal at terminal status, and wired `BulkDescribeProgress` mount/unmount visibility.
- Mounted one `useGpuStateToasts` observer in the application shell. It reuses `useDescribeRunProgress` and its existing `['bulkDescribeRun', runId]` query, so two observers share one React Query fetch loop.
- Implemented the frozen edge table: unknown edges and first observations are silent; stopped/starting to warming and warming to ready are suppressed on the progress screen; degraded always alerts; edge memory is per run id.
- Extended the existing toast API additively with actions and duration options. Actionable toasts do not auto-dismiss; close/unmount clears timer bookkeeping.
- Empirically verified Radix Toast 1.2.15 in the RED test: its default live region is `role=status` with `aria-live=assertive`. Info now uses Radix `type="background"` for polite announcement; errors use `type="foreground"` plus the authorized `role="alert"` fallback.

## Final toast ASCII

```text
away from Workbench                         role=status / aria-live=polite
                                      ┌───────────────────────────────┐
                                      │ ℹ Info                        │
                                      │ GPU warming — CPU drafts first│
                                      └───────────────────────────────┘
                                      default 5 s

away from Workbench                         role=status / aria-live=polite
                                      ┌───────────────────────────────┐
                                      │ ℹ Info                        │
                                      │ GPU ready — Final descriptions│
                                      │ in progress · [Back to run]   │
                                      └───────────────────────────────┘
                                      persistent until action/close

any page, including mounted progress        role=alert / assertive
                                      ┌───────────────────────────────┐
                                      │ ✖ Error                       │
                                      │ GPU unavailable — CPU drafts  │
                                      │ kept · [Review results]       │
                                      └───────────────────────────────┘
                                      persistent until action/close
```

## RED evidence

Tests were written before their implementation.

`cd apps/prototype-wp-alt-context && npx vitest run js/admin/hooks/__tests__/useGpuStateToasts.test.tsx`

```text
FAIL  js/admin/hooks/__tests__/useGpuStateToasts.test.tsx [ js/admin/hooks/__tests__/useGpuStateToasts.test.tsx ]
Error: Failed to resolve import "../activeDescribeRun"
Test Files  1 failed (1)
Tests  no tests
Duration  1.41s
```

`cd apps/prototype-wp-alt-context && npx vitest run js/admin/context/__tests__/ToastContext.test.tsx`

```text
FAIL  js/admin/context/__tests__/ToastContext.test.tsx (7 tests | 3 failed)
× renders an action and invokes it exactly once
× announces errors assertively and info politely
× keeps actionable toasts present beyond the default timeout
Test Files  1 failed (1)
Tests  3 failed | 4 passed (7)
Duration  2.07s
```

The role failure exposed the pinned Radix behavior: the generated announcement node was `role="status" aria-live="assertive"`; there was no alert role and the Root itself was a list item.

## tests_run

`cd apps/prototype-wp-alt-context && npx vitest run js/admin/hooks/__tests__/useGpuStateToasts.test.tsx`

```text
Test Files  1 passed (1)
Tests  30 passed (30)
Duration  6.76s
```

`cd apps/prototype-wp-alt-context && npx vitest run js/admin/context/__tests__/ToastContext.test.tsx`

```text
Test Files  1 passed (1)
Tests  7 passed (7)
Duration  5.67s
```

`cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/__tests__/BulkDescribeProgress.test.tsx js/admin/hooks/__tests__/useBulkDescribe.test.tsx`

```text
Test Files  2 passed (2)
Tests  10 passed (10)
Duration  13.63s
```

`cd apps/prototype-wp-alt-context && npx tsc --noEmit --project tsconfig.type-check.json`

```text
exit 0
```

`cd apps/prototype-wp-alt-context && npx eslint js/admin/context/ToastContext.tsx js/admin/context/__tests__/ToastContext.test.tsx js/admin/hooks/activeDescribeRun.ts js/admin/hooks/useGpuStateToasts.ts js/admin/hooks/__tests__/useGpuStateToasts.test.tsx js/admin/hooks/useBulkDescribe.ts js/admin/pages/workbench/MediaSelection.tsx js/admin/pages/workbench/gpuStatePresentation.ts js/admin/App.tsx`

```text
exit 0
```

## Mutants

All mutations were temporary and reverted with patches after their run.

### (a) Swap warming and ready in the edge map — KILLED

```diff
- nextState === GPU_STATE.WARMING
+ nextState === GPU_STATE.READY
- previousState === GPU_STATE.WARMING && nextState === GPU_STATE.READY
+ previousState === GPU_STATE.READY && nextState === GPU_STATE.WARMING
```

```text
FAIL useGpuStateToasts.test.tsx (25 tests | 4 failed)
× stopped transitions to warming
× starting transitions to warming
× warming to ready
× re-arms edge memory
Test Files 1 failed; Tests 4 failed | 21 passed
```

### (b) Drop run-id reset — KILLED

```diff
- if (rememberedRunIdRef.current !== runId) {
-   rememberedRunIdRef.current = runId;
-   previousStateRef.current = null;
-   emittedEdgesRef.current.clear();
- }
```

```text
FAIL re-arms edge memory for a new run id
expected info toast 2 times, received 1
Test Files 1 failed; Tests 1 failed | 24 passed
```

### (c) Drop progress-mounted suppression — KILLED

```diff
- if (progressMounted) return;
```

```text
FAIL useGpuStateToasts.test.tsx (25 tests | 3 failed)
× suppresses stopped to warming while progress is mounted
× suppresses starting to warming while progress is mounted
× suppresses warming to ready while progress is mounted
Test Files 1 failed; Tests 3 failed | 22 passed
```

### (d) Fire on first observation — KILLED

```diff
- if (previousState === null || previousState === GPU_STATE.UNKNOWN || nextState === GPU_STATE.UNKNOWN)
+ if (previousState === GPU_STATE.UNKNOWN || nextState === GPU_STATE.UNKNOWN)
```

```text
FAIL useGpuStateToasts.test.tsx (30 tests | 2 failed)
× never toasts a degraded to unknown transition
× does not toast first observation degraded
Test Files 1 failed; Tests 2 failed | 28 passed
```

### (e) Auto-dismiss actionable toasts at 5000 ms — KILLED

```diff
- const duration = options.durationMs ?? (options.action ? null : 5000);
+ const duration = options.durationMs ?? 5000;
```

```text
FAIL keeps actionable toasts present beyond the default timeout
Unable to find an element with the text: GPU ready
Test Files 1 failed; Tests 1 failed | 6 passed
```

### (f) Drop Radix action altText — KILLED

```diff
- <RadixToast.Action asChild altText={t.action.altText}>
+ <RadixToast.Action asChild>
```

```text
FAIL ToastContext.test.tsx (7 tests | 3 failed)
TypeError: Cannot read properties of undefined (reading 'trim')
Test Files 1 failed; Tests 3 failed | 4 passed
```

### (g) Swap error and info politeness — KILLED

```diff
- type={t.type === 'info' ? 'background' : 'foreground'}
+ type={t.type === 'error' ? 'background' : 'foreground'}
```

```text
FAIL announces errors assertively and info politely
Expected aria-live="assertive"; Received aria-live="polite"
Test Files 1 failed; Tests 1 failed | 6 passed
```

## Blockers

None.

## Findings outside ownership

None.

```json
{"findings":[],"blockers":[],"tests_run":"useGpuStateToasts: 30 passed; ToastContext: 7 passed; BulkDescribeProgress + useBulkDescribe: 10 passed; tsc: exit 0; changed-file eslint: exit 0; mutants a-g: KILLED","handoff_action":"merge_ready"}
```
