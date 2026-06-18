# Frontend Guidelines -- Project Conventions

> **Library reference**: Review current docs for React, TypeScript, TanStack Query,
> Radix UI, Vite, and Vitest listed in
> [../maps/tech-stack.md](../maps/tech-stack.md#frontend-reactts) before starting work.
> This file covers only project-specific conventions.

> Load this document when working on React/TypeScript frontend code in `apps/prototype-wp-alt-context/js/`. See [testing-typescript.md](testing-typescript.md) for test conventions.

---

## Component Rules

Before building custom UI, check [RADIX_UI_COMPONENT_GUIDE.md](RADIX_UI_COMPONENT_GUIDE.md) for pre-vetted accessible patterns.

**Size limits:** 300 lines/component, 5 `useState`, 3 `useEffect`, 10 props max.

**Extract when:** JSX block > 50 lines, pattern appears 2+ times, conditional nesting > 2 levels, or 6+ `useState` hooks.

See [component-architecture-patterns.md](component-architecture-patterns.md) for detailed patterns.

---

## TypeScript Safety Rules

1. **No non-null assertions (`!`) on API data.** Narrow with a guard instead.

   ```tsx
   // BAD
   <Img src={item.url!} />;

   // GOOD
   const url = item.url;
   if (url) {
     <Img src={url} />;
   }
   ```

2. **No `undefined as T` or `x as T` for API return types.** If `fetchApi` can return `undefined`, the return type must be `Promise<T | undefined>`.

3. **Use assertion helpers for internal invariants.** `asserts value is ...` / `assertNever(...)` for impossible states. Not for API/input validation.

4. **Centralize query keys.** All React Query keys through a `queryKeys` factory. No ad-hoc `['resource', id]` arrays.

5. **No inline styles for layout.** Reusable grid/flex patterns belong in SCSS classes.

6. **No `!important` in SCSS.** Increase selector specificity instead (nest under `.acx-` container).

7. **Use design tokens for colors.** Hex literals must be `var(--acx-*)` custom properties.

8. **API calls go through the API module.** No direct `fetchApi` imports in components. Use dedicated functions in `clusterApi.ts` etc.

9. **Use `URLSearchParams` for query strings.** No string interpolation for query params.

10. **No REST transport in page or hook layers.** All HTTP calls go through `js/admin/api/` modules.

11. **Browser API capability guards.** `crypto.randomUUID`, `BroadcastChannel`, `navigator.locks`, etc. must check availability and degrade gracefully.

12. **No origin-derived admin URLs.** Localize the canonical admin URL from PHP via `wp_localize_script`.

13. **Complete barrel exports.** All public functions in an API module must be re-exported from its `index.ts`.

14. **API types must match payload reality.** Declare all backend field variants; normalize once in the API layer.

---

## Workbench Overlay and URL State

The `panel` query param drives which secondary panel is visible (`conflicts`, `dead-letter`).

### Rules

- **URL is the source of truth.** Read overlay state from `useOverlayParam` / `useSearchParams`, not component state.
- **No stale closure captures.** Use the functional form of `setSearchParams`.
- **Panel hooks stay local.** `ConflictInbox` and `DeadLetterPanel` own their own hooks; `WorkbenchPage` only coordinates visibility.

---

## Sovereign Read Model

All UI state derives from local projection tables (`wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`, `wp_acx_persons`), not live backend reads.

- Dashboard/roster/conflict UX queries local projection via `acx/v1/` REST endpoints.
- Backend snapshots imported into local projection, not proxied at read time.
- Degrade gracefully if local projection is unavailable. No fallback to live backend reads.
- See [ADR-003](../adrs/ADR-003-wordpress-local-authority-and-durable-outbox-replay.md).

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
