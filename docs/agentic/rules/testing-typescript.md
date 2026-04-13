# TypeScript / React Testing (Vitest) -- Project Conventions

> **Library reference**: Use ctx7 to fetch current docs for `vitest`, `@testing-library/react`,
> `@tanstack/react-query`, and `msw` listed in
> [../maps/tech-stack.md](../maps/tech-stack.md#frontend-reactts) before starting work.
> This file covers only project-specific conventions.

> Load this document when writing or reviewing tests in `apps/prototype-wp-alt-context/js/`. Start with [testing-principles.md](testing-principles.md) for universal concepts.

---

## High-Risk Regression Traps (Recent Branch Reviews)

### Provider Harness Parity Is Mandatory

Tests must render with matching providers for hooks used:

- `useSearchParams` / `useLocation` / `useNavigate` -> `MemoryRouter`
- `useQuery` / `useMutation` / `useQueryClient` -> `QueryClientProvider`

### Ban `unknown as ReturnType<...>` Test Mocks

Use typed builders/factories (e.g., `createMockQuery<T>()`) so missing fields fail at compile time. No `unknown`/`any` casts.

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

Use hoisted `vi.mock` with a mutable ref object for statically-imported modules.

### Aftereach Query Cancellation (Mandatory)

```tsx
afterEach(() => {
  queryClient?.cancelQueries();
  queryClient?.clear();
  cleanup();
});
```

### QueryClient Must Use `retry: false` in Tests

Always pass `defaultOptions: { queries: { retry: false } }` to the test `QueryClient`.

### Light Integration Tests Validate Hook Wiring

One integration-lite test per major page using real hooks with mocked network calls.

### MSW: Use RFC 2606 Domains for Test URLs

Use `http://example.test/` (RFC 2606) for all MSW handler URLs, not `localhost`. Mock handlers follow the shared stub-fidelity rules in [testing-principles.md](testing-principles.md).

---

## Sovereign Sync Test Patterns

### Testing overlay panels (ConflictInbox, DeadLetterPanel)

Overlay panels read visibility from the `panel` query param. Render inside `MemoryRouter` with appropriate initial entries:

```tsx
render(
  <MemoryRouter initialEntries={["/workbench?tab=scan&panel=conflicts"]}>
    <WorkbenchPage />
  </MemoryRouter>,
);
```

### Testing sync health surfaces

Mock `useSyncStatus()` to return each `SyncHealth` state (`healthy`, `queued`, `stale`, `conflicts`, `failures`, `offline`) and assert correct badge, copy, and links.

### Testing conflict resolution flows

Conflict accept/dismiss invalidates `queryKeys.conflicts.all`, `queryKeys.outbox.all`, `queryKeys.sync.all`, the conflict detail key, and affected cluster data. Dead-letter retry/discard invalidates `queryKeys.outbox.all` and `queryKeys.sync.all`. Assert expected invalidations after the mutation settles.
