# Branch Review — TypeScript / React / Vitest

> Load this guide when the branch diff includes files under `apps/prototype-wp-alt-context/js/`.
> For universal process, severity definitions, and report template see [branch-review-guide.md](branch-review-guide.md).

---

## Automated Checks

| Check                   | Command                                                                             |
| ----------------------- | ----------------------------------------------------------------------------------- |
| TypeScript types        | `cd apps/prototype-wp-alt-context && npm run typecheck`                             |
| Tests                   | `cd apps/prototype-wp-alt-context && npm run test -- --run`                         |
| ESLint                  | `cd apps/prototype-wp-alt-context && npm run lint`                                  |
| Architecture compliance | `cd apps/prototype-wp-alt-context && node scripts/check-architecture-compliance.js` |

When a UI-behavior fix is claimed, require fresh command evidence on the current branch state for:

- `typecheck`
- `lint`
- the targeted Vitest coverage for the changed behavior

Do not accept "UI fix is done" claims based on screenshots, manual browsing, or stale test output alone.

---

## Type Safety

- [ ] No non-null assertions (`!`) on API data — use type guards.
- [ ] Assertion helpers, not `console.assert` — internal invariants use `asserts ...` / exhaustive helpers, while API/input validation stays explicit.
- [ ] No `undefined as T` or `x as T` casts — use proper union return types.
- [ ] No ad-hoc query keys — all keys through `queryKeys` factory.

---

## Frontend Patterns

- [ ] **No `!important` in SCSS** — increase selector specificity.
- [ ] **Design tokens for colors** — hex literals as CSS custom properties.
- [ ] **No inline styles for layout** — grid/flex patterns in SCSS classes.
- [ ] **API calls go through API modules** — no direct `fetchApi` imports in components.
- [ ] **`URLSearchParams` for query strings** — no string interpolation for URL params.

---

## State Surface Correctness

- [ ] **UI state matrix** — changed UI surfaces explicitly cover empty, loading, error, degraded, and offline states.
- [ ] **Abort/cancel semantics** — expected cancellation does not surface noisy console warnings or error UI; only unexpected cancellation should behave like failure.
- [ ] **API-boundary payload validation** — components tolerate malformed JSON, partial payloads, and missing optional fields without white-screen or unhandled-rejection behavior.
- [ ] **Query invalidation regression** — after successful mutation, invalidation/refetch cannot silently restore stale pre-mutation UI state.

---

## Code Duplication

- [ ] **Frontend components** — shared algorithms in reusable components, not inlined.
- [ ] **`retry: false` in QueryClient** — test QueryClients disable retries.
- [ ] **Adequate coverage for new components** — render, loading, error, and primary interaction.

---

## SCSS Metric Thresholds

| Metric                                     | Threshold | Resolution                      |
| ------------------------------------------ | --------- | ------------------------------- |
| `!important` count                         | 0         | Increase selector specificity   |
| Raw hex colors (outside `var()` fallbacks) | 0         | Use `--acx-*` custom properties |
| Max selector nesting depth                 | 4         | Flatten or restructure          |

Component size limits and hook counts are enforced by `check-architecture-compliance.js`.

---

## Sovereign Sync UI (Overlay / Conflicts / Dead-Letter)

When the diff touches `js/admin/pages/workbench/`, overlay hooks, or sync-status surfaces:

- [ ] **URL param source of truth** — overlay visibility is driven by the `panel` query param via `useOverlayParam`, not duplicated in React state.
- [ ] **No stale closure captures** — `setSearchParams` uses the functional updater form to avoid capturing stale params.
- [ ] **Query invalidation on mutation settle** — conflict resolution invalidates `conflicts`, `outbox`, `sync`, and affected cluster queries; dead-letter retry/discard invalidates `outbox` and `sync`.
- [ ] **Sync health coverage** — UI branches on the `SyncHealth` union cover all states (`healthy`, `queued`, `stale`, `conflicts`, `failures`, `offline`) without falling back to stale copy.
