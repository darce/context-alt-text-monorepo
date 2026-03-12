# Frontend Context Map (React/TypeScript)

> Quick reference for agents working on the React admin UI.

## Critical Files (Read First)

| Priority | File                                                 | Purpose                          |
| -------- | ---------------------------------------------------- | -------------------------------- |
| 1        | `apps/prototype-wp-alt-context/js/admin/App.tsx`     | React app entry, routing         |
| 2        | `apps/prototype-wp-alt-context/js/admin/pages/`      | Page components                  |
| 3        | `apps/prototype-wp-alt-context/js/admin/hooks/`      | Job, media, and sync hooks       |
| 4        | `apps/prototype-wp-alt-context/js/admin/api/`        | API client layer                 |
| 5        | `docs/agentic/contracts/clustering-api.md`           | WP REST API contract             |
| 6        | `docs/agentic/contracts/curation-sync-api.md`        | Outbox replay contract           |

## Page / Component Architecture

| Page / Component          | Path                                               | Purpose                                        |
| ------------------------- | -------------------------------------------------- | ---------------------------------------------- |
| `DashboardPage`           | `js/admin/pages/DashboardPage.tsx`                 | Guidance, stats, sync health card              |
| `WorkbenchPage`           | `js/admin/pages/WorkbenchPage.tsx`                 | Scan, clustering, sync coordination            |
| `RosterPage`              | `js/admin/pages/RosterPage.tsx`                    | Identity roster grid/table                     |
| `SyncStatusIndicator`     | `js/admin/pages/workbench/SyncStatusIndicator.tsx` | Sync health badge with state-driven UX         |
| `ConflictInbox`           | `js/admin/pages/workbench/ConflictInbox.tsx`       | Conflict list, detail, resolution actions      |
| `DeadLetterPanel`         | `js/admin/pages/workbench/DeadLetterPanel.tsx`     | Failed outbox operations, retry/discard        |
| `WorkbenchContext`        | `js/admin/pages/workbench/WorkbenchContext.tsx`     | `activeOverlay` state synced with `panel` URL param |

### Sync Health States (`SyncHealth` union type)

`offline` | `stale` | `queued` | `conflicts` | `failures` | `healthy`

Transient states (projecting, acknowledging, trigger pending) override `sync_health` while active.

## API Client Layer

| Module                    | Path                                        | Purpose                                  |
| ------------------------- | ------------------------------------------- | ---------------------------------------- |
| `clusterApi`              | `js/admin/api/recognition/clusterApi.ts`    | Cluster queries                          |
| `clusterApiMutations`     | `js/admin/api/recognition/clusterApiMutations.ts` | Label, merge, split, person binding  |
| `conflictApi`             | `js/admin/api/recognition/conflictApi.ts`   | Conflict list/detail/resolve, dead-letter retry/discard |
| `syncApi`                 | `js/admin/api/recognition/syncApi.ts`       | Sync status, trigger sync                |
| `scanApi`                 | `js/admin/api/recognition/scanApi.ts`       | Media scanning                           |
| `identityApi`             | `js/admin/api/recognition/identityApi.ts`   | Identity queries                         |

### API Types

| File                      | Key Types                                             |
| ------------------------- | ----------------------------------------------------- |
| `types/sync.ts`           | `SyncHealth`, `SyncStatusResponse`, `SyncTriggerResponse`, `TopologyCommandStatus` |
| `types/conflict.ts`       | `ConflictRecord`, `ConflictListResponse`, `OutboxOperation`, `OutboxListResponse` |
| `types/cluster.ts`        | `IdentityCluster`, `ClusterMember`, `TopUnlabeledCluster` |

## Test Entry Points

| Scope       | Path                                              | When to Use                     |
| ----------- | ------------------------------------------------- | ------------------------------- |
| Component   | `js/components/__tests__/`                        | Reusable UI behavior            |
| Hook        | `js/admin/hooks/__tests__/`                       | Data fetching, state management |
| Page        | `js/admin/pages/__tests__/`                       | Full page flows                 |
| Workbench   | `js/admin/pages/workbench/__tests__/`             | Conflict inbox, dead-letter, sync indicator |
| Cluster     | `js/admin/pages/workbench/identity-clusters/__tests__/` | Cluster review, merge, labeling |

## Key Diagrams

- [frontend-uml/workbench-flow-v2.mmd](../diagrams/frontend-uml/workbench-flow-v2.mmd) — Workbench user flow
- [frontend-uml/media-selection-workflow.mmd](../diagrams/frontend-uml/media-selection-workflow.mmd) — Media selection UX
- [frontend-uml/sequence-complete-workflow.mmd](../diagrams/frontend-uml/sequence-complete-workflow.mmd) — End-to-end sequence
- [../diagrams/sovereign-data-flow.mmd](../diagrams/sovereign-data-flow.mmd) — Sovereign sync data flow

## Guidelines

Full frontend rules: [rules/frontend-guidelines.md](../rules/frontend-guidelines.md)

Key limits: max 300 lines/component, max 5 `useState`, max 3 `useEffect`, max 10 props. Always use Radix UI primitives for accessibility.

## Common Tasks

### Add a new page

1. Create page component in `js/admin/pages/`
2. Add route in `App.tsx`
3. Create hooks for data fetching in `hooks/`
4. Write component tests

### Add API integration

1. Define request/response types in `js/admin/api/recognition/types/`
2. Create API client in `js/admin/api/recognition/`
3. Create React Query hook in component or `hooks/`
4. Connect to component via hook

### Add workbench overlay panel

1. Create panel component in `js/admin/pages/workbench/`
2. Add overlay variant to `WorkbenchOverlay` type in `WorkbenchContext.tsx`
3. Render panel conditionally in `WorkbenchPage.tsx` when `activeOverlay` matches
4. Link from `SyncStatusIndicator` badge or `DashboardPage` card via `?panel=<name>`

### Fix accessibility issue

1. Check [RADIX_UI_COMPONENT_GUIDE.md](../rules/RADIX_UI_COMPONENT_GUIDE.md)
2. Use `getByRole` in tests, not `getByTestId`
3. Ensure keyboard navigation works
4. Run axe-core for violations
