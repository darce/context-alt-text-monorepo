# Component Architecture Patterns

Rules for React component design in the Alt Context frontend (`apps/prototype-wp-alt-context/js/`).

---

## Size Limits

| Layer            | Max lines | Examples                                    |
| ---------------- | --------- | ------------------------------------------- |
| Smart container  | 300       | Route-level pages that wire hooks to UI     |
| Presentational   | 200       | Tables, toolbars, modal orchestrators       |
| Leaf component   | 80        | Inputs, badges, action menus                |
| Custom hook      | 150       | State reducers, data-fetching coordinators  |
| Utility module   | 100       | Normalizers, formatters, validators         |

If a file crosses its limit, extract before continuing. Do not wait for a "refactoring pass."

---

## Component Layering

```
Route container (smart)
  -- reads hooks, passes props down, no direct DOM beyond layout
  |
  +-- Presentational sections (toolbar, table, modal orchestrator)
  |     -- receive data + callbacks via props, no API awareness
  |
  +-- Leaf components (row, badge, input)
        -- stateless or locally-stateful, fully Storybook-ready
```

### Rules

1. **One smart container per route.** It calls custom hooks and distributes props. It must not contain inline JSX for modals, tables, or forms.
2. **Presentational components receive all data via props.** They never call `useRoster`, `useClusters`, or other API hooks directly.
3. **Leaf components own only local UI state** (hover, focus, open/closed). They must not call `dispatch` on a parent reducer.

---

## State Management

### Prefer `useReducer` over multiple `useState`

When a component needs 4+ related state variables, consolidate into a single `useReducer` exposed via a custom hook.

**Why:** Explicit action types make state transitions testable and prevent scattered `useEffect` chains that synchronize one `useState` to another.

### Rules

- State + dispatch live in a custom hook (e.g., `useClusterListState`).
- The reducer is a pure function exportable for unit testing.
- Maximum 1 `useEffect` in the hook (typically for debounce). If you need more, the abstraction is wrong.
- Related state transitions (filter change resetting page to 1) belong in the reducer, not in an effect.
- Internal impossible states belong in hook/util assertion helpers (`asserts ...`, `assertNever(...)`), not as non-null assertions on raw API data inside presentational components.

---

## Data Fetching

### Wrap coordinated queries in a custom data hook

When a container needs data from 2+ API hooks, create a single data hook that:

1. Calls the underlying query hooks
2. Derives combined `isLoading` / `isError` state
3. Transforms/normalizes response data via `useMemo`
4. Exposes a single `refetch()` that refreshes all queries

**Why:** The container should not know about individual endpoints, manual loading-state coordination, or data normalization.

### Rules

- Data hooks return `{ data, isLoading, isError, error, refetch }` — a uniform shape.
- Transformations go in `useMemo` inside the data hook, not in the component render body.
- If a data hook exceeds 150 lines, split the underlying queries into smaller hooks first.

---

## File Structure Convention

```
js/src/components/<feature>/
  <Feature>Page.tsx            -- Smart container (route-level)
  <Feature>Toolbar.tsx         -- Presentational
  <Feature>Table.tsx           -- Presentational
  <Feature>Modals.tsx          -- Modal orchestrator
  components/
    <LeafComponent>.tsx        -- Leaf components
  hooks/
    use<Feature>State.ts       -- useReducer + dispatch
    use<Feature>Data.ts        -- API coordination
  utils/
    <feature>-normalizers.ts   -- Data transforms
```

---

## Anti-Pattern Checklist

Before merging, verify NONE of these exist in the diff:

- [ ] File > 300 lines (container) or > 200 lines (presentational)
- [ ] More than 3 `useState` in a single component (use `useReducer`)
- [ ] More than 1 `useEffect` in a custom hook
- [ ] API hook (`useRoster`, `useClusters`, etc.) called directly in a presentational component
- [ ] Data transformation logic in a component's render body instead of a data hook
- [ ] Modal/dialog JSX inline in a container instead of in a dedicated component

---

## Summary Principles

1. **Single Responsibility** -- each file does ONE thing well.
2. **Composition Over Monoliths** -- build complex UIs from small pieces.
3. **Extract Early** -- refactor at the limit, not after doubling it.
4. **State in Hooks** -- complex state lives in `useReducer` + custom hook.
5. **Data Isolation** -- API calls wrapped in custom hooks that coordinate and transform.
6. **Presentational/Container Split** -- smart containers wire data; dumb components render it.
7. **Test Boundaries** -- every extracted piece is independently testable.
