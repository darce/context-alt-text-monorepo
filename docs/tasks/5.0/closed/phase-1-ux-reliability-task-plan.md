# Phase 1: UX Reliability and Failure Clarity

## Problem Statement

Core workbench workflows have reliability defects that leave users in unrecoverable states: a render error in any cluster component crashes the entire SPA with no fallback; aborting a cluster label mutation permanently displays "Saving..." with no way to reset; scan completion force-navigates the user away from their current tab context. Secondary issues -- tab state lost on refresh, no scroll/page restoration, SyncStatusIndicator invisible outside Scan tab, and a god-component WorkbenchPage -- amplify the reliability gap.

## Workflow Principles

- **TDD**: write a failing test before each fix. Red -> Green -> Refactor.
- **Scaffolding first**: add component/hook signatures and `it.todo()` stubs before implementation.
- **Smallest vertical slice**: each sub-phase is independently shippable.
- **Curation-first**: user position, scroll state, and active tab are "curation context" -- never discard them silently.

## Terminology

- **SaveStatus**: `'idle' | 'queued' | 'saved'` lifecycle from `useClusterSaveStatus` hook.
- **AbortError**: `DOMException` with `name === 'AbortError'`, raised when an `AbortController.abort()` cancels a fetch or mutation.
- **God-component**: a component that orchestrates too many responsibilities (state, data-fetching, event handlers, rendering) in a single file.

## Current State Analysis

### What Works

- Sovereign local-first read path is live.
- TanStack React Query with centralized key factory and hierarchical invalidation.
- Job state machine (`useJobStateMachine`) with proper decomposition.
- Cluster edit state with `useReducer` pattern.
- 33 frontend test files covering hooks, pages, and components.
- `useClusterSaveStatus` provides clean `idle -> queued -> saved -> idle` lifecycle.

### What's Broken

- **No Error Boundaries**: zero `ErrorBoundary` wrappers anywhere in the app. A render error in any cluster component (e.g. `IdentityClusterItem`, `ClusterEditForm`, `SuggestionReviewPanel`) crashes the entire SPA to a white screen.
- **"Saving..." hang in label mutations (AP-2)**: In `useClusterLabelMutations.ts`, `renameMutation.onError` (L62-65) and `mergeMutation.onError` (L102-104) return early on `isAbortError(err)` without calling the upstream `onError` callback. The upstream callback (`handleMutationError` in `IdentityClusterItem.tsx` L111-117) is the only code path that calls `resetSaveStatus()`. Result: `saveStatus` stays `'queued'` permanently, displaying "Saving..." with no recovery path.
- **"Saving..." hang in action mutations (AP-2b)**: The same AbortError early-return pattern exists in `useClusterActionMutations.ts` for `reassign` (L62-64), `assignToCluster` (L89-91), `createClusterForIdentity` (L108-110), and `split` (L143-145). Two of these (`assignToCluster`, `createClusterForIdentity`) are reachable from the save flow via `useClusterSaveAction`, making AP-2b a direct save-lifecycle regression path.
- **Force-navigation on scan complete (AP-3)**: `onScanComplete` callback in `WorkbenchPage.tsx` L179 always calls `setActiveSection(TAB_IDS.confirm)`, ripping the user away from whatever tab they're on (e.g. reviewing clusters on Scan tab).

### What's Missing

- Tab state is `useState` only -- lost on refresh, not URL-synced (`WorkbenchPage.tsx` L102, `RosterPage.tsx` L23).
- No scroll/page position restoration across navigation round-trips.
- `SyncStatusIndicator` renders inside Scan tab content only (`WorkbenchPage.tsx` L326) -- invisible on Batch/Confirm tabs.
- `WorkbenchPage` is 428 lines. `MediaSelection` receives 18 props. No React Context for shared workbench state.

## Proposed Solution

Three independently shippable sub-phases, ordered by user-impact severity:

1. **Phase 1a -- Critical Fixes**: Add error boundaries, fix the saving hang, remove forced tab navigation.
2. **Phase 1b -- Navigation State Continuity**: Sync tab state to URL hash params, persist pagination, add scroll restoration.
3. **Phase 1c -- Structural Improvement**: Move SyncStatusIndicator above tabs, decompose WorkbenchPage into tab content components, introduce WorkbenchContext.

## Patterns to Follow

### Error Boundary Component

```tsx
// js/components/ErrorBoundary.tsx
import React from 'react';
import { __ } from '@wordpress/i18n';

interface Props {
    children: React.ReactNode;
    fallback?: React.ReactNode;
}

interface State {
    hasError: boolean;
    error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
    state: State = { hasError: false, error: null };

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    handleRetry = (): void => {
        this.setState({ hasError: false, error: null });
    };

    render(): React.ReactNode {
        if (this.state.hasError) {
            return this.props.fallback ?? (
                <div className="acx-error-boundary" role="alert">
                    <p>{__('Something went wrong.', 'alt-context')}</p>
                    <button type="button" className="button" onClick={this.handleRetry}>
                        {__('Try again', 'alt-context')}
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}
```

### AbortError Fix Pattern

```typescript
// useClusterLabelMutations.ts -- options
interface UseClusterLabelMutationsOptions {
    onError?: (error: string) => void;
    onAbort?: () => void; // status reset without surfacing a user-facing error
    // ...
}

// useClusterLabelMutations.ts -- renameMutation.onError (current, broken)
onError: (err: unknown) => {
    if (isAbortError(err)) {
        invalidateQueries();
        return; // <-- BUG: save status never resets
    }
    // ...
}

// useClusterLabelMutations.ts -- renameMutation.onError (fixed)
onError: (err: unknown) => {
    if (isAbortError(err)) {
        invalidateQueries();
        onAbort?.();
        return;
    }
    // ...
}
```

### URL-Synced Tab State Pattern

```tsx
// useTabParam hook
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

export const useTabParam = <T extends string>(
    paramName: string,
    defaultValue: T,
    validValues: readonly T[],
): [T, (value: T) => void] => {
    const [searchParams, setSearchParams] = useSearchParams();

    const rawParam = searchParams.get(paramName);
    const activeTab = rawParam && validValues.includes(rawParam as T) ? (rawParam as T) : defaultValue;

    const setTab = useCallback(
        (value: T) => {
            setSearchParams((prev) => {
                const next = new URLSearchParams(prev);
                next.set(paramName, value);
                return next;
            }, { replace: true });
        },
        [paramName, setSearchParams],
    );

    return [activeTab, setTab];
};
```

### WorkbenchContext Pattern

```tsx
// js/admin/pages/workbench/WorkbenchContext.tsx
import React from 'react';
import type { WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';

interface WorkbenchContextValue {
    // Media state
    mediaItems: WorkbenchMediaItem[];
    isLoading: boolean;
    isError: boolean;
    refetch: () => void;
    // Selection state
    selection: Record<string, boolean>;
    selectedMedia: WorkbenchMediaItem[];
    toggleRow: (item: WorkbenchMediaItem, checked: boolean) => void;
    toggleAll: (items: WorkbenchMediaItem[], checked: boolean) => void;
    // Pagination
    currentPage: number;
    totalPages: number;
    perPage: number;
    setCurrentPage: (page: number) => void;
    setPerPage: (perPage: number) => void;
    // Job state (subset)
    isScanRunning: boolean;
    statusText: string;
}

const WorkbenchContext = React.createContext<WorkbenchContextValue | null>(null);

export const useWorkbenchContext = (): WorkbenchContextValue => {
    const ctx = React.useContext(WorkbenchContext);
    if (!ctx) {
        throw new Error('useWorkbenchContext must be used within WorkbenchProvider');
    }
    return ctx;
};

export const WorkbenchProvider = WorkbenchContext.Provider;
```

## Functions to Change

### Phase 1a: Critical Fixes

| File | Line | Change |
| --- | --- | --- |
| `js/components/ErrorBoundary.tsx` | new | Create `ErrorBoundary` class component with retry |
| `js/admin/App.tsx` | L28-33 | Wrap each `<Route>` element in `<ErrorBoundary>` |
| `js/admin/pages/WorkbenchPage.tsx` | scan tab panel branch | Wrap `SuggestionReviewPanel`/`ClusterLabelingPanel`/`ClusterReviewPanel` block in `<ErrorBoundary>` |
| `js/admin/pages/workbench/identity-clusters/useClusterLabelMutations.ts` | abort paths | Add `onAbort?: () => void` option and call `onAbort?.()` in both rename/merge abort branches |
| `js/admin/pages/workbench/identity-clusters/useClusterActionMutations.ts` | abort paths | Add `onAbort?: () => void` option and call `onAbort?.()` in reassign/assignToCluster/createClusterForIdentity/split abort branches |
| `js/admin/pages/workbench/identity-clusters/useClusterMutations.ts` | options threading | Thread `onAbort` through composition hook to both label and action mutation hooks |
| `js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx` | mutation wiring | Pass `onAbort: resetSaveStatus` so cancellation clears "Saving..." without showing an error |
| `js/admin/pages/WorkbenchPage.tsx` | L179 | Remove `setActiveSection(TAB_IDS.confirm)` from `onScanComplete`; add toast/notification instead |

### Phase 1b: Navigation State Continuity

| File | Line | Change |
| --- | --- | --- |
| `js/admin/hooks/useTabParam.ts` | new | Create `useTabParam` hook (URL search param sync via `useSearchParams`) |
| `js/admin/pages/WorkbenchPage.tsx` | L108 | Replace `useState<WorkbenchTab>` with `useTabParam('tab', TAB_IDS.scan, ...)` |
| `js/admin/pages/RosterPage.tsx` | L23 | Replace `useState<RosterTab>` with `useTabParam('tab', 'entries', ...)` |
| `js/admin/pages/RosterPage.tsx` | L64-68 | Remove manual `useEffect` that reads `tab` from `url.searchParams` (replaced by `useTabParam`) |
| `js/admin/App.tsx` | `extractRouteFromHash`/`ensureHashInitialized` | Parse hash route path independent of query (do not clobber `#/workbench?tab=...` on boot) |
| `js/admin/hooks/useWorkbenchFilters.ts` | various | Persist `currentPage` and `perPage` as URL search params |
| `js/admin/hooks/useScrollRestoration.ts` | new | Create `useScrollRestoration` hook (save/restore from `sessionStorage` keyed by route + page) |
| `js/admin/pages/WorkbenchPage.tsx` | various | Integrate `useScrollRestoration` in Scan tab content |

### Phase 1c: Structural Improvement

| File | Line | Change |
| --- | --- | --- |
| `js/admin/pages/WorkbenchPage.tsx` | scan tab section | Move `<SyncStatusIndicator />` from inside `TabsContent[scan]` to above `<TabsList>` (inside `<Tabs>` but outside all `<TabsContent>`) |
| `js/admin/pages/workbench/ScanTabContent.tsx` | new | Extract Scan tab body from `WorkbenchPage` |
| `js/admin/pages/workbench/BatchTabContent.tsx` | new | Extract Batch tab body from `WorkbenchPage` |
| `js/admin/pages/workbench/ConfirmTabContent.tsx` | new | Extract Confirm tab body from `WorkbenchPage` |
| `js/admin/pages/WorkbenchPage.tsx` | tab content blocks | Replace inline tab bodies with extracted components |
| `js/admin/pages/workbench/WorkbenchContext.tsx` | optional | Add only if extraction still leaves repeated prop threading that harms readability/testability |

## Related Files

| File | Note |
| --- | --- |
| `js/admin/pages/workbench/identity-clusters/useClusterSaveStatus.ts` | Defines `SaveStatus` type and lifecycle. Not changed, but behavior depends on fix in `useClusterLabelMutations.ts`. |
| `js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx` | L111-117: `handleMutationError` callback that calls `resetSaveStatus()`. Not changed, but wiring is the root cause chain for AP-2. |
| `js/admin/pages/workbench/identity-clusters/useClusterMutations.ts` | Composition hook that passes `onError` through to both `useClusterLabelMutations` and `useClusterActionMutations`. |
| `js/admin/pages/workbench/identity-clusters/clusterMutationUtils.ts` | `isAbortError` utility used in the broken abort paths. |
| `js/admin/pages/workbench/identity-clusters/useClusterSaveAction.ts` | Save flow that calls `queueSaveStatus()` and wraps mutations including `assignToCluster` and `createClusterForIdentity` from action mutations. Save lifecycle depends on 1a fix. |
| `js/admin/pages/workbench/identity-clusters/useClusterSaveHandlers.ts` | Thin composition over `useClusterSaveAction` + `useClusterConfirmSuggestion`. Threading stays the same after fix. |
| `js/admin/hooks/useJobStateMachine.ts` | Provides `onScanComplete` callback. Not changed, but the callback wiring in `WorkbenchPage` changes. |
| `js/admin/pages/workbench/SyncStatusIndicator.tsx` | Moves position in DOM (1c) but component internals are unchanged. |
| `js/admin/App.tsx` | HashRouter bootstrapping currently parses only exact `#/route`; must preserve query-bearing hashes for tab deep-linking. |
| `js/components/ui/tabs.tsx` | Radix UI Tabs wrapper. Not changed. |
| `vitest.setup.ts` | Test setup with TanStack Query `act()` wrappers. Not changed. |
| `js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx` | Existing tests that must continue passing after all 3 sub-phases. |
| `js/admin/pages/workbench/__tests__/WorkbenchPage.integration.test.tsx` | Integration tests that assert tab behavior and scan flow. |
| `js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx` | Existing cluster labeling tests. |

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Create `js/components/ErrorBoundary.tsx` with class component skeleton and `handleRetry`.
- [x] Create `js/components/__tests__/ErrorBoundary.test.tsx` with `it.todo()` stubs for: renders children, catches error and shows fallback, retry resets error state.
- [x] Create `js/admin/hooks/useTabParam.ts` with type signature and `throw new Error('TODO')`.
- [x] Create `js/admin/hooks/__tests__/useTabParam.test.tsx` with `it.todo()` stubs for: reads param from URL, defaults when missing, sets param on change.
- [x] Create `js/admin/hooks/useScrollRestoration.ts` with type signature and TODO stub.
- [x] Create `js/admin/hooks/__tests__/useScrollRestoration.test.ts` with `it.todo()` stubs.
- [x] Create `js/admin/pages/workbench/ScanTabContent.tsx` as empty component skeleton.
- [x] Create `js/admin/pages/workbench/BatchTabContent.tsx` as empty component skeleton.
- [x] Create `js/admin/pages/workbench/ConfirmTabContent.tsx` as empty component skeleton.
- [x] Verify scaffolds compile: `npm run typecheck`.

## Phase 1a: Critical Fixes

- [x] **Test (red)**: `ErrorBoundary.test.tsx` -- error in child renders fallback UI with retry button.
- [x] **Implement**: `ErrorBoundary` class component with `getDerivedStateFromError` and `handleRetry`.
- [x] **Test (green)**: verify error boundary catches and retry resets.
- [x] **Test (red)**: `ErrorBoundary.test.tsx` -- renders children normally when no error.
- [x] **Implement**: add children pass-through in `render()`.
- [x] **Integrate**: wrap each `<Route>` in `App.tsx` with `<ErrorBoundary>`.
- [x] **Integrate**: wrap identity-cluster panel block in `WorkbenchPage.tsx` L330-350 with `<ErrorBoundary>`.
- [x] **Test (red)**: `useClusterLabelMutations` -- rename/merge abort triggers `onAbort`.
- [x] **Fix**: add `onAbort` callback to `useClusterLabelMutations` (rename + merge abort branches).
- [x] **Test (red)**: `useClusterActionMutations` -- assignToCluster/createClusterForIdentity abort triggers `onAbort`.
- [x] **Fix**: add `onAbort` callback to `useClusterActionMutations` (reassign, assignToCluster, createClusterForIdentity, split abort branches).
- [x] **Fix**: thread `onAbort` through `useClusterMutations` to both hooks; wire `onAbort: resetSaveStatus` in `IdentityClusterItem`.
- [x] **Test (green)**: abort resets `saveStatus` to idle without surfacing a user-facing error message.
- [x] **Test (red)**: `WorkbenchPage` -- scan complete does NOT change active tab.
- [x] **Fix**: `WorkbenchPage.tsx` L179 -- remove `setActiveSection(TAB_IDS.confirm)`, add toast/notification.
- [x] **Test (green)**: verify active tab unchanged after scan complete.
- [x] Run full test suite: `npm run test`.

## Phase 1b: Navigation State Continuity
 
- [x] **Test (red)**: `useTabParam` -- returns default when URL has no param.
- [x] **Implement**: `useTabParam` hook using `useSearchParams`.
- [x] **Test (green)**: default value and URL round-trip.
- [x] **Test (red)**: `useTabParam` -- setting tab updates URL search param.
- [x] **Implement**: `setTab` callback writes to search params with `replace: true`.
- [x] **Test (green)**: URL reflects new tab value.
- [x] **Test (red)**: `App.extractRouteFromHash` handles `#/workbench?tab=confirm` without stripping query params.
- [x] **Fix**: update hash-route parsing/bootstrap logic to preserve query-bearing hashes.
- [x] **Integrate**: replace `useState` in `WorkbenchPage.tsx` L108 with `useTabParam`.
- [x] **Integrate**: replace `useState` + manual `useEffect` in `RosterPage.tsx` L23, L64-68 with `useTabParam`.
- [x] **Test (red)**: `useScrollRestoration` -- saves scroll position keyed by route.
- [x] **Implement**: `useScrollRestoration` hook with `sessionStorage` persistence.
- [x] **Test (green)**: scroll position save/restore round-trip.
- [x] **Integrate**: wire `useScrollRestoration` into WorkbenchPage Scan tab content.
- [x] **Test**: deep-linking to `#/workbench?tab=confirm` renders Confirm tab.
- [x] **Test**: page refresh preserves `?tab=` param and active tab.
- [x] Run full test suite: `npm run test`.
 
## Phase 1c: Structural Improvement
 
- [x] Move `<SyncStatusIndicator />` from inside `TabsContent[scan]` to above `<TabsList>` in `WorkbenchPage.tsx`.
- [x] **Test**: SyncStatusIndicator visible when Batch or Confirm tab is active.
- [x] Extract `ScanTabContent` component from `WorkbenchPage` lines 310-362.
- [x] Extract `BatchTabContent` component from `WorkbenchPage` lines 364-385.
- [x] Extract `ConfirmTabContent` component from `WorkbenchPage` lines 387-415.
- [x] Evaluate prop threading after extraction; introduce `WorkbenchContext` only if it reduces real complexity without broad rerender churn.
- [x] Run full test suite: `npm run test`.
- [x] Run type check: `npm run typecheck`.

## Success Criteria

- [x] Render error in any cluster component shows fallback with retry, does not crash SPA.
- [x] Label mutation that aborts resets `saveStatus` to `'idle'` within bounded time (test-verified).
- [x] Scan completion does not move the user away from their current active tab.
- [x] Tab state survives page refresh and navigation round-trips.
- [x] Deep-linking to `#/workbench?tab=confirm` works.
- [x] `SyncStatusIndicator` is visible on all workbench tabs.
- [x] Structural decomposition improves readability/testability without introducing unnecessary global state.
- [x] All existing 33 test files continue passing.
