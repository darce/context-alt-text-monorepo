# Frontend Context Map (React/TypeScript)

> Quick reference for agents working on the React admin UI.

## Critical Files (Read First)

| Priority | File                                                 | Purpose              |
| -------- | ---------------------------------------------------- | -------------------- |
| 🔥 1     | `apps/prototype-wp-alt-context/js/src/admin/App.tsx` | React app entry      |
| 🔥 2     | `apps/prototype-wp-alt-context/js/src/admin/pages/`  | Page components      |
| 🔥 3     | `apps/prototype-wp-alt-context/js/src/admin/hooks/`  | Data fetching hooks  |
| 🔥 4     | `apps/prototype-wp-alt-context/js/src/admin/api/`    | API client layer     |
| 🔥 5     | `docs/agentic/contracts/clustering-api.md`           | WP REST API contract |

## Component Architecture

```
js/admin/
├── App.tsx                      # Router + providers + QueryClient
├── pages/                       # Route-level components
│   ├── DashboardPage.tsx        # Coverage stats, quick actions
│   ├── WorkbenchPage.tsx        # Media + clustering UI (primary)
│   └── RosterPage.tsx           # Identity management
├── components/                  # Reusable UI components
│   ├── clusters/                # Cluster cards, lists
│   ├── media/                   # Media grid, selection
│   └── shared/                  # Buttons, dialogs, etc.
├── hooks/                       # React Query hooks + state management
│   ├── useRecognitionHooks.ts   # Scan, cluster operations
│   ├── useMediaIdentities.ts    # Media identity queries
│   ├── useJobProgressStream.ts  # SSE progress (v4.10.3+)
│   ├── useJobPersistence.ts     # localStorage job tracking (v4.10.3+)
│   └── useJobCoordination.ts    # Multi-tab BroadcastChannel (v4.10.3+)
└── api/                         # Typed API clients
    ├── scanApi.ts               # POST /analyze
    ├── clusterApi.ts            # Cluster CRUD
    └── recognition/types/       # Shared TypeScript types
```

## New Hooks (v4.10.3)

| Hook                    | Purpose                                       |
| ----------------------- | --------------------------------------------- |
| `useJobProgressStream`  | SSE connection for real-time progress updates |
| `useJobPersistence`     | Persist job IDs to localStorage for refresh   |
| `useJobCoordination`    | BroadcastChannel for multi-tab sync           |

## Test Entry Points

| Scope       | Path                           | When to Use                     |
| ----------- | ------------------------------ | ------------------------------- |
| Component   | `js/**/*.test.tsx`             | UI behavior, user interactions  |
| Hook        | `js/admin/hooks/__tests__/`    | Data fetching, state management |
| Integration | `js/tests/`                    | Full page flows                 |

## Key Diagrams

- [frontend-uml/workbench-flow-v2.mmd](../diagrams/frontend-uml/workbench-flow-v2.mmd) — Workbench user flow
- [frontend-uml/media-selection-workflow.mmd](../diagrams/frontend-uml/media-selection-workflow.mmd) — Media selection UX
- [frontend-uml/sequence-complete-workflow.mmd](../diagrams/frontend-uml/sequence-complete-workflow.mmd) — End-to-end sequence

## Component Rules (from instructions.md)

- Max **300 lines** per component file
- Max **5 useState** hooks (use `useReducer` for complex state)
- Max **3 useEffect** hooks (prefer derived state)
- Max **10 props** (split component if exceeded)
- Always use Radix UI primitives for accessibility

## Common Tasks

### Add a new page

1. Create page component in `js/admin/pages/`
2. Add route in `App.tsx`
3. Create hooks for data fetching in `hooks/`
4. Write component tests

### Add API integration

1. Define types in `js/src/types/`
2. Create API client in `js/src/admin/api/`
3. Create React Query hook in `js/src/admin/hooks/`
4. Connect to component via hook

### Fix accessibility issue

1. Check [RADIX_UI_COMPONENT_GUIDE.md](../rules/RADIX_UI_COMPONENT_GUIDE.md)
2. Use `getByRole` in tests, not `getByTestId`
3. Ensure keyboard navigation works
4. Run axe-core for violations
