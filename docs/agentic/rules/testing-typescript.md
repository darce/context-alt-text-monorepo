# TypeScript / React Testing (Vitest) -- Project Conventions

> **Library reference**: Use ctx7 to fetch current docs for `vitest`, `@testing-library/react`,
> `@tanstack/react-query`, and `msw` listed in
> [../maps/tech-stack.md](../maps/tech-stack.md#frontend-reactts) before starting work.
> This file covers only project-specific conventions.

> Load this document when writing or reviewing tests in `apps/prototype-wp-alt-context/js/`. Start with [testing-principles.md](testing-principles.md) for universal concepts.

---

## High-Risk Regression Traps (Recent Branch Reviews)

### Provider Harness Parity Is Mandatory

If a hook/component uses React Router or React Query, tests must render with matching providers.

- `useSearchParams` / `useLocation` / `useNavigate` -> wrap with `MemoryRouter` (or equivalent router wrapper)
- `useQuery` / `useMutation` / `useQueryClient` -> wrap with `QueryClientProvider`

Do not rely on incidental provider context from unrelated helpers.

### Ban `unknown as ReturnType<...>` Test Mocks

Do not coerce partial hook responses with `unknown`/`any` casts.
Use typed builders/factories (for example `createMockQuery<T>()`) so missing fields fail at compile time.

```tsx
// BAD
mockedHook.mockReturnValue({ data: value } as unknown as ReturnType<
  typeof useSomething
>);

// GOOD
mockedHook.mockReturnValue(createMockQuery<MyType>({ data: value }));
```

---

## Project-Specific Testing Rules

### `vi.mock` Must Be Hoisted; Use Mutable Ref for Per-Test Variation

For statically-imported modules, use hoisted `vi.mock` with a mutable ref object (see ctx7 `vitest` docs for hoisting details).

### Aftereach Query Cancellation (Mandatory)

```tsx
afterEach(() => {
  queryClient?.cancelQueries();
  queryClient?.clear();
  cleanup();
});
```

### QueryClient Must Use `retry: false` in Tests

Retries cause flaky timing, extra network calls, and `act()` warnings.
Always pass `defaultOptions: { queries: { retry: false } }` to the test `QueryClient`.

### Light Integration Tests Validate Hook Wiring

Add one integration-lite test per major page using real hooks with mocked network calls (unit mocks can mask wiring bugs).

### MSW: Use RFC 2606 Domains for Test URLs

Use `http://example.test/` (RFC 2606 reserved domain) for all MSW handler URLs, not `localhost`.

---

## Sovereign Sync Test Patterns

### Testing overlay panels (ConflictInbox, DeadLetterPanel)

Overlay panels read their visibility from the `panel` query param. Tests must render inside a `MemoryRouter` with the appropriate initial entries:

```tsx
render(
  <MemoryRouter initialEntries={["/workbench?tab=scan&panel=conflicts"]}>
    <WorkbenchPage />
  </MemoryRouter>,
);
```

### Testing sync health surfaces

`SyncStatusIndicator` and `DashboardPage` read `sync_health` from `useSyncStatus()`. Mock the sync-status query to return each `SyncHealth` state (`healthy`, `queued`, `stale`, `conflicts`, `failures`, `offline`) and assert the UI renders the correct badge, copy, and links.

### Testing conflict resolution flows

Conflict accept/dismiss invalidates `queryKeys.conflicts.all`, `queryKeys.outbox.all`, `queryKeys.sync.all`, the conflict detail key, and affected cluster data. Dead-letter retry/discard invalidates `queryKeys.outbox.all` and `queryKeys.sync.all`. Assert the expected invalidations after the mutation settles.
