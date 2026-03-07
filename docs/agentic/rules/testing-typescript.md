# TypeScript / React Testing (Vitest)

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
mockedHook.mockReturnValue({ data: value } as unknown as ReturnType<typeof useSomething>);

// GOOD
mockedHook.mockReturnValue(createMockQuery<MyType>({ data: value }));
```

---

## Vitest-Specific Rules

### Never Use `vi.doMock` With Statically-Imported Modules

`vi.doMock` only affects _subsequent_ dynamic `import()` calls. If the component under test is imported statically at the top of the file, `vi.doMock` inside individual tests has **no effect** — the original module is already resolved.

Use hoisted `vi.mock` with a mutable ref object instead:

```tsx
// BAD: vi.doMock with static import — mock never takes effect
import { MyComponent } from '../MyComponent';

it('shows loading', () => {
  vi.doMock('../hooks/useData', () => ({
    useData: () => ({ data: null, isLoading: true }),
  }));
  render(<MyComponent />); // Still uses real useData!
});

// GOOD: Hoisted vi.mock + mutable ref — mock is wired at module load
const mockReturn = { data: null, isLoading: false, isError: false };

vi.mock('../hooks/useData', () => ({
  useData: () => mockReturn,
}));

import { MyComponent } from '../MyComponent';

beforeEach(() => {
  mockReturn.data = null;
  mockReturn.isLoading = false;
  mockReturn.isError = false;
});

it('shows loading', () => {
  mockReturn.isLoading = true;
  render(<MyComponent />); // Correctly sees mocked state
});
```

### Explicit Synchronization Over Sleep

```tsx
// BAD: Timer coupling is brittle
vi.advanceTimersByTime(SAVE_SUCCESS_DELAY_MS);

// GOOD: Wait for UI state changes
await waitFor(() => expect(button).toHaveTextContent("Saved"));
```

---

## React Testing Library Patterns

### Mock Async Side Effects

```tsx
// BAD: Async updates after test ends cause act() warnings

// GOOD: Mock hooks that cause async side effects
vi.mock("../hooks/useRecognitionHooks", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useCombinedScanStatus: () => ({
      scanStatusQuery: { data: null, isLoading: false },
    }),
  };
});

// GOOD: Cancel queries in afterEach
afterEach(() => {
  queryClient?.cancelQueries();
  queryClient?.clear();
  cleanup();
});
```

### Light Integration Tests Validate Hook Wiring

Unit tests mock hooks heavily, which can mask wiring bugs. Add one "integration-lite" test per major page that uses real hooks with mocked network calls.

```tsx
describe("WorkbenchPage (integration-lite)", () => {
  vi.mock("../api/recognition", async () => {
    const actual = await vi.importActual("../api/recognition");
    return { ...actual, scanFacesBatched: vi.fn() };
  });

  it("scan action triggers query invalidation", async () => {
    // Uses real useJobStateMachine, useScanMutation, etc.
    // Only network calls are mocked
  });
});
```

---

## TanStack Query Rules

### QueryClient Must Use `retry: false` in Tests

```tsx
// GOOD: Disable retries entirely
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});
```

Retries in tests cause flaky timing, extra network calls, and `act()` warnings.

---

## MSW (Mock Service Worker)

Use RFC 2606 domains for test URLs:

```tsx
// GOOD: RFC 2606 reserved domain
http.get('http://example.test/api/clusters', () => {
  return HttpResponse.json({ clusters: [] });
});
```
