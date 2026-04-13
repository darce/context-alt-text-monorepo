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

Require fresh evidence (`typecheck`, `lint`, targeted Vitest coverage) for any claimed UI fix. Screenshots, manual browsing, or stale output alone are insufficient.

---

## Type Safety

- [ ] No non-null assertions (`!`) on API data — use type guards.
- [ ] Assertion helpers (`asserts ...`), not `console.assert` — API/input validation stays explicit.
- [ ] No `undefined as T` or `x as T` casts — use union return types.
- [ ] No ad-hoc query keys — all keys through `queryKeys` factory.

---

## Frontend Patterns

- [ ] **No `!important` in SCSS** — increase specificity instead.
- [ ] **Design tokens for colors** — hex literals → CSS custom properties.
- [ ] **No inline styles for layout** — use SCSS classes.
- [ ] **API calls through API modules** — no direct `fetchApi` in components.
- [ ] **`URLSearchParams` for query strings** — no string interpolation.

---

## State Surface Correctness

- [ ] **UI state matrix** — changed surfaces cover empty, loading, error, degraded, and offline states.
- [ ] **Abort/cancel semantics** — expected cancellation produces no console warnings or error UI.
- [ ] **API-boundary payload validation** — components tolerate malformed JSON, partial payloads, missing optional fields without white-screen crashes.
- [ ] **Query invalidation regression** — post-mutation invalidation/refetch cannot silently restore stale UI state.

---

## Code Duplication

- [ ] **Shared algorithms** in reusable components, not inlined.
- [ ] **`retry: false`** in test QueryClients.
- [ ] **New component coverage** — render, loading, error, and primary interaction.

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

- [ ] **URL param source of truth** — overlay visibility driven by `panel` query param via `useOverlayParam`, not React state.
- [ ] **No stale closure captures** — `setSearchParams` uses functional updater form.
- [ ] **Query invalidation on mutation settle** — conflict resolution invalidates `conflicts`, `outbox`, `sync`, and affected cluster queries; dead-letter retry/discard invalidates `outbox` and `sync`.
- [ ] **Sync health coverage** — UI covers all `SyncHealth` states (`healthy`, `queued`, `stale`, `conflicts`, `failures`, `offline`).
