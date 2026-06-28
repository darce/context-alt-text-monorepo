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

Extract at the limit, not after exceeding it.

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

4+ related state variables -> consolidate into `useReducer` via a custom hook.

### Rules

- State + dispatch live in a custom hook (e.g., `useClusterListState`).
- Reducer is a pure function exportable for unit testing.
- Maximum 1 `useEffect` per hook (typically debounce).
- Related state transitions (filter change resetting page) belong in the reducer, not effects.
- Internal impossible states use hook/util assertion helpers, not non-null assertions on API data.

---

## Data Fetching

### Wrap coordinated queries in a custom data hook

When a container needs 2+ API hooks, create a single data hook that calls them, derives combined loading/error state, transforms via `useMemo`, and exposes a single `refetch()`.

### Rules

- Data hooks return `{ data, isLoading, isError, error, refetch }`.
- Transformations in `useMemo` inside the data hook, not in the render body.
- Data hook > 150 lines -> split underlying queries first.

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

## Overlay Panel Pattern (WorkbenchOverlay)

URL-synced overlay for secondary panels (`ConflictInbox`, `DeadLetterPanel`).

```
WorkbenchContext
  +-- useOverlayParam("panel")
WorkbenchPage
  +-- overlay chrome / dismiss control
  +-- ConflictInbox (owns conflict hooks + mutation flows)
  +-- DeadLetterPanel (owns outbox hooks + mutation flows)
  +-- SyncStatusIndicator
```

### Rules

1. **URL param is source of truth.** `panel` search param selects which overlay renders. No mirroring in component state.
2. **Context owns routing, panels own data.** `WorkbenchContext` / `useOverlayParam` manage visibility; panels call their own hooks.
3. **Overlay components stay feature-local.** `WorkbenchPage` only handles container chrome and routing.

---

## Summary Principles

1. **Single Responsibility** -- each file does ONE thing well.
2. **Composition Over Monoliths** -- build complex UIs from small pieces.
3. **Extract Early** -- refactor at the limit, not after doubling it.
4. **State in Hooks** -- complex state lives in `useReducer` + custom hook.
5. **Data Isolation** -- API calls wrapped in custom hooks that coordinate and transform.
6. **Presentational/Container Split** -- smart containers wire data; dumb components render it.
7. **Test Boundaries** -- every extracted piece is independently testable.
