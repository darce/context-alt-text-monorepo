# Frontend Guidelines -- Project Conventions

> **Library reference**: Use ctx7 to fetch current docs for React, TypeScript, TanStack Query,
> Radix UI, Vite, and Vitest listed in
> [../maps/tech-stack.md](../maps/tech-stack.md#frontend-reactts) before starting work.
> This file covers only project-specific conventions.

> Load this document when working on React/TypeScript frontend code in `apps/prototype-wp-alt-context/js/`. See [testing-typescript.md](testing-typescript.md) for test conventions.

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

3. **Use assertion helpers for internal invariants.** Prefer `asserts value is ...` helpers or `assertNever(...)` for impossible states and exhaustive switches. Do not use `console.assert` or assertion helpers as a substitute for API/input validation.

4. **Centralize query keys.** All React Query keys must go through a `queryKeys` factory. Ad-hoc `['resource', id]` arrays create stale-data risk when other components invalidate via the factory but miss the ad-hoc key.

5. **No inline styles for layout.** If a grid/flex pattern is used more than once, it belongs in a SCSS class. Inline `style={{ display: 'grid', ... }}` objects are not reusable, not inspectable in DevTools by class name, and duplicate easily.

6. **No `!important` in SCSS.** Increase selector specificity instead (nest under a root `.acx-` container). WordPress admin styles have high specificity, but `!important` creates an arms race.

7. **Use design tokens for colors.** Hex literals (`#fef2f2`) must be CSS custom properties (`var(--acx-color-error-bg)`). Magic colors diverge silently across components.

8. **API calls go through the API module.** Components must not import `fetchApi` directly and build URLs with string interpolation. All API calls should go through a dedicated function in the relevant API module (e.g., `clusterApi.ts`) for mockability and consistency.

9. **Use `URLSearchParams` for query strings.** String interpolation (`` `?limit=${n}&tenant_id=${id}` ``) fails on special characters. Use `new URLSearchParams({ limit: String(n), tenant_id: id })` instead.

10. **No REST transport in page or hook layers.** Pages (`js/admin/pages/`) and hooks (`js/admin/hooks/`) must not construct their own `fetch()` calls with custom nonce/base-URL plumbing. All HTTP calls go through `js/admin/api/` modules.

11. **Browser API capability guards.** Code using `crypto.randomUUID`, `BroadcastChannel`, `navigator.locks`, or other APIs not universally available must check for availability and degrade gracefully.

12. **No origin-derived admin URLs.** Do not construct WordPress admin links via `window.location.origin + '/wp-admin/...'`. Localize the canonical admin URL from PHP via `wp_localize_script`.

13. **Complete barrel exports.** If an API module uses a barrel file (`index.ts`), all public functions must be re-exported from it. Deep imports that bypass the barrel break the module boundary.

14. **API types must match payload reality.** If the backend sends both `thumb_url` and legacy `thumbnail_url`, the TypeScript interface must declare both. Normalize variant shapes once in the API layer.

---

## Workbench Overlay and URL State

The Workbench page uses URL-synced overlay state via the `panel` query param to drive which secondary panel is visible (`conflicts`, `dead-letter`).

### Rules

- **URL is the source of truth.** Read overlay state from `useOverlayParam` / `useSearchParams`, not from component state. Setting `panel=conflicts` opens the conflict inbox; removing `panel` closes the overlay.
- **No stale closure captures.** Overlay open/close handlers must use the functional form of `setSearchParams` to avoid capturing stale param snapshots.
- **Panel hooks stay local.** `ConflictInbox` and `DeadLetterPanel` own their query/mutation hooks; `WorkbenchPage` and `WorkbenchContext` only coordinate visibility and chrome.

---

## Accessibility Requirements

Meet WCAG 2.1 AA; test with axe-core (zero critical violations). Query elements by accessible role (`getByRole`), not by test ID.

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
