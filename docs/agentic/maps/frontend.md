# Frontend Context Map (React/TypeScript)

> Quick reference for agents working on the React admin UI.

## Critical Files (Read First)

| Priority | File                                                 | Purpose              |
| -------- | ---------------------------------------------------- | -------------------- |
| 🔥 1     | `apps/prototype-wp-alt-context/js/admin/App.tsx`     | React app entry      |
| 🔥 2     | `apps/prototype-wp-alt-context/js/admin/pages/`      | Page components      |
| 🔥 3     | `apps/prototype-wp-alt-context/js/admin/hooks/`      | Data fetching hooks  |
| 🔥 4     | `apps/prototype-wp-alt-context/js/admin/api/`        | API client layer     |
| 🔥 5     | `docs/agentic/contracts/clustering-api.md`           | WP REST API contract |

## Test Entry Points

| Scope       | Path                        | When to Use                     |
| ----------- | --------------------------- | ------------------------------- |
| Component   | `js/components/__tests__/`  | Reusable UI behavior            |
| Hook        | `js/admin/hooks/__tests__/` | Data fetching, state management |
| Integration | `js/admin/pages/__tests__/` | Full page flows                 |

## Key Diagrams

- [frontend-uml/workbench-flow-v2.mmd](../diagrams/frontend-uml/workbench-flow-v2.mmd) — Workbench user flow
- [frontend-uml/media-selection-workflow.mmd](../diagrams/frontend-uml/media-selection-workflow.mmd) — Media selection UX
- [frontend-uml/sequence-complete-workflow.mmd](../diagrams/frontend-uml/sequence-complete-workflow.mmd) — End-to-end sequence

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
2. Create API client in `js/admin/api/`
3. Create React Query hook in `js/admin/hooks/`
4. Connect to component via hook

### Fix accessibility issue

1. Check [RADIX_UI_COMPONENT_GUIDE.md](../rules/RADIX_UI_COMPONENT_GUIDE.md)
2. Use `getByRole` in tests, not `getByTestId`
3. Ensure keyboard navigation works
4. Run axe-core for violations
