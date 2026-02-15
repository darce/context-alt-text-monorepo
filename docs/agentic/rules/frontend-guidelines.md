# Frontend Guidelines

> Load this document when working on React/TypeScript frontend code in `apps/prototype-wp-alt-context/js/`.

---

## Technology Stack

- **React 18+** with functional components and hooks
- **TypeScript 5.3+** with `strict: true`
- **Vite 5+** for build and dev server
- **React Query 5+** for data fetching
- **Radix UI** for accessible primitives
- **Vitest + Testing Library** for tests

---

## Component Rules

Before building custom UI, check [RADIX_UI_COMPONENT_GUIDE.md](RADIX_UI_COMPONENT_GUIDE.md) for pre-vetted accessible patterns.

**Size limits:**

- Maximum **300 lines** per component file
- Maximum **5 useState** hooks (use `useReducer` for complex state)
- Maximum **3 useEffect** hooks (prefer derived state)
- Maximum **10 props** (split component if exceeded)

**Extract when:**

- JSX block exceeds 50 lines
- Pattern appears 2+ times
- Conditional nesting exceeds 2 levels
- Component has 6+ useState hooks

For detailed architecture patterns and refactoring case studies, see [component-architecture-patterns.md](component-architecture-patterns.md).

---

## State Management Anti-Patterns

```tsx
// BAD: Syncing props to state
const [value, setValue] = useState(initialValue);
useEffect(() => setValue(initialValue), [initialValue]);

// GOOD: Use prop directly
const value = initialValue;

// BAD: Derived state in useState
const [filtered, setFiltered] = useState([]);
useEffect(() => setFiltered(items.filter((x) => x.active)), [items]);

// GOOD: Compute during render
const filtered = useMemo(() => items.filter((x) => x.active), [items]);

// BAD: Chained effects
useEffect(() => setB(a + 1), [a]);
useEffect(() => setC(b * 2), [b]);

// GOOD: Handle in event or derive
const handleChange = (newA: number) => {
  setA(newA);
  setC((newA + 1) * 2);
};
```

---

## Hook Architecture Anti-Patterns

```tsx
// BAD: "God Hook" (>150 lines, multiple concerns)
const useEverything = () => {
  // Mutations, derived state, SSE tracking, status text, progress aggregation...
  const [state1, setState1] = useState();
  const [state2, setState2] = useState();
  // ... 20 more hooks
  return { mutation1, mutation2, phase, status, progress, isOnline, ... };
};

// GOOD: Compose focused hooks
const useScanMutation = (options) => useMutation({...});
const useJobPhase = (activeJobs) => useMemo(() => derivePhase(activeJobs), [activeJobs]);
const useStatusText = (phase, progress) => useMemo(() => formatStatus(phase, progress), [phase, progress]);

const useJobStateMachine = () => {
  const scan = useScanMutation();
  const phase = useJobPhase(scan.activeJobs);
  const status = useStatusText(phase, scan.progress);
  return { scan: scan.mutate, phase, status };
};
```

**Signs of a God Hook:**

- More than 150 lines
- More than 5 `useState` calls
- More than 3 `useEffect` calls
- Returns more than 8 values
- Mixes mutation orchestration with derived state

**Refactoring strategy:**

1. Extract each `useMemo` into a focused hook
2. Group related mutations into a single hook
3. Keep the "orchestration" hook thin (compose, don't implement)

---

## Data Fetching

Use React Query for all API calls:

```tsx
const { data, isLoading, error, refetch } = useQuery({
  queryKey: ["clusters", tenantId],
  queryFn: () => fetchClusters(tenantId),
  staleTime: 60_000,
});
```

---

## TypeScript Safety Rules

> Distilled from the 4.12.0 and 4.13.0 branch audits.

1. **No non-null assertions (`!`) on API data.** Fields typed `T | null | undefined` from an API response must be narrowed with a guard, not suppressed with `!`. Use a local const and an `if` check.

   ```tsx
   // BAD
   <Img src={item.url!} />;

   // GOOD
   const url = item.url;
   if (url) {
     <Img src={url} />;
   }
   ```

2. **No `undefined as T` or `x as T` for API return types.** If `fetchApi` can return `undefined` (204, empty body), the return type must be `Promise<T | undefined>`. Casting `undefined as T` gives callers a lie.

3. **Centralize query keys.** All React Query keys must go through a `queryKeys` factory. Ad-hoc `['resource', id]` arrays create stale-data risk when other components invalidate via the factory but miss the ad-hoc key.

4. **No inline styles for layout.** If a grid/flex pattern is used more than once, it belongs in a SCSS class. Inline `style={{ display: 'grid', ... }}` objects are not reusable, not inspectable in DevTools by class name, and duplicate easily.

5. **No `!important` in SCSS.** Increase selector specificity instead (nest under a root `.acx-` container). WordPress admin styles have high specificity, but `!important` creates an arms race.

6. **Use design tokens for colors.** Hex literals (`#fef2f2`) must be CSS custom properties (`var(--acx-color-error-bg)`). Magic colors diverge silently across components.

7. **API calls go through the API module.** Components must not import `fetchApi` directly and build URLs with string interpolation. All API calls should go through a dedicated function in the relevant API module (e.g., `clusterApi.ts`) for mockability and consistency.

8. **Use `URLSearchParams` for query strings.** String interpolation (`` `?limit=${n}&tenant_id=${id}` ``) fails on special characters. Use `new URLSearchParams({ limit: String(n), tenant_id: id })` instead.

9. **No REST transport in page or hook layers.** Pages (`js/admin/pages/`) and hooks (`js/admin/hooks/`) must not construct their own `fetch()` calls with custom nonce/base-URL plumbing. All HTTP calls go through `js/admin/api/` modules.

10. **Browser API capability guards.** Code using `crypto.randomUUID`, `BroadcastChannel`, `navigator.locks`, or other APIs not universally available must check for availability and degrade gracefully.

11. **No origin-derived admin URLs.** Do not construct WordPress admin links via `window.location.origin + '/wp-admin/...'`. Localize the canonical admin URL from PHP via `wp_localize_script`.

12. **Complete barrel exports.** If an API module uses a barrel file (`index.ts`), all public functions must be re-exported from it. Deep imports that bypass the barrel break the module boundary.

13. **API types must match payload reality.** If the backend sends both `thumb_url` and legacy `thumbnail_url`, the TypeScript interface must declare both. Normalize variant shapes once in the API layer.

---

## Accessibility Requirements

- Query elements by accessible roles: `getByRole('button')`, not `getByTestId()`
- All interactive elements must be keyboard accessible
- Include ARIA labels for screen readers
- Test with axe-core (zero critical violations)
- Meet WCAG 2.1 AA standards

---

## Commands

```bash
cd apps/prototype-wp-alt-context
npm run dev          # Start Vite dev server
npm run build        # Production build
npm run test         # Run Vitest
npm run lint         # ESLint
npm run typecheck    # TypeScript type checking
```
