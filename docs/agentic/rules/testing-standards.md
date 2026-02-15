# Testing Standards

> Load this document when writing or reviewing tests in any layer of the monorepo.

---

## Test Pyramid

```text
          ^
         / \
        /E2E\       <- Few, slow, high confidence
       /-----\
      /Integr-\     <- Some, medium speed
     /--ation--\
    /-----------\
   /    Unit     \  <- Many, fast, isolated
  /_______________\
```

---

## Test Writing Rules

### 1. Deterministic Data Over Randomness

```python
# BAD: Random vectors make failures hard to reproduce
embedding = np.random.rand(512)

# GOOD: Fixed vectors with explicit values
def fixed_embedding(dim: int = 512, value: float = 0.1) -> np.ndarray:
    return np.full(dim, value, dtype=np.float32)

# GOOD: If randomness is needed, seed locally
rng = np.random.default_rng(seed=42)
embedding = rng.random(512, dtype=np.float32)
```

### 2. Explicit Synchronization Over Sleep

```python
# BAD: Timing-based waits are flaky
await asyncio.sleep(0.05)
assert subscriber.received_event

# GOOD: Wait for explicit condition with timeout
await asyncio.wait_for(event_queue.get(), timeout=1.0)
```

```tsx
// BAD: Timer coupling is brittle
vi.advanceTimersByTime(SAVE_SUCCESS_DELAY_MS);

// GOOD: Wait for UI state changes
await waitFor(() => expect(button).toHaveTextContent("Saved"));
```

### 3. Behavioral Assertions Over Call Counts

```python
# BAD: Brittle coupling to internal calls
mock_repo.recompute_centroid.assert_called_once()

# GOOD: Assert observable outcomes
assert cluster.identity_count == 5
assert cluster.centroid_updated_at > original_timestamp

# ACCEPTABLE: One or two critical side-effect assertions
mock_event_bus.emit.assert_called_with(ClusterMergedEvent(...))
```

### 4. Import Settings, Don't Hardcode

```python
# BAD: Magic numbers that can diverge from production
assert result.threshold == 0.65

# GOOD: Reference the source of truth
from recognition.application.settings import ClusteringSettings

settings = ClusteringSettings()
assert result.threshold == settings.suggestion_floor
```

### 5. Mock Async Side Effects in React Tests

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

### 6. Light Integration Tests Validate Hook Wiring

```tsx
// Unit tests mock hooks heavily, which can mask wiring bugs.
// Add one "integration-lite" test per major page that uses real hooks
// with mocked network calls.

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

### 7. Exact Assertions in Integration Tests

```python
# BAD: Broad assertions allow regressions
assert clusters_created >= 1

# GOOD: Use deterministic fixtures for exact counts
assert clusters_created == 3
```

### 8. Test Mock Defaults Match Production Defaults

```python
# BAD: Mock returns different default than production
repo.get_curriculum_t = AsyncMock(return_value=0.0)  # Production default is 0.5!

# GOOD: Match production defaults explicitly
repo.get_curriculum_t = AsyncMock(return_value=0.5)  # Matches schema default
```

### 9. No Permanently Skipped Tests

Tests marked `@pytest.mark.skip` or `it.skip()` without a linked issue or TODO date are dead code. Either:

- Remove the test (if the feature is abandoned)
- Complete the test (if the feature shipped)
- Add a comment with an issue reference and expected resolution (if blocked)

Empty test bodies (`pass`, `...`) that run green are worse -- they inflate pass counts.

### 10. Extract Shared Test Stubs

If a Protocol stub is copy-pasted across 3+ test files, extract it to a shared test utility module (`tests/fakes.py` or `tests/stubs.py`).

```python
# BAD: 100-line ClusterRepoStub defined independently in 4 test files

# GOOD: Shared null implementation in tests/stubs.py
class NullClusterRepository:
    """No-op implementation of ClusterRepository for unit tests."""
    async def get(self, cluster_id): return None
    async def save(self, cluster): pass
    # full Protocol surface in one place
```

### 11. One Canonical Fake Per Protocol

Do not maintain multiple divergent fake implementations of the same Protocol across test files.

```python
# GOOD: One configurable fake in tests/fakes.py
class FakeClusterRepository:
    """Configurable fake for ClusterRepository protocol."""
    def __init__(self, clusters: list[IdentityCluster] | None = None):
        self._clusters = {c.id: c for c in (clusters or [])}
    async def get(self, cluster_id: str) -> IdentityCluster | None:
        return self._clusters.get(cluster_id)
```

### 12. No False-Positive Fakes

Test fakes that always return `None`/`0`/empty can make tests pass for the wrong reason. Design fakes to be configurable:

```python
# BAD: Always returns None
class FakeSession:
    async def get(self, *a, **kw): return None

# GOOD: Configurable
class FakeSession:
    def __init__(self, data=None):
        self._data = data
    async def get(self, *a, **kw): return self._data
```

### 13. `QueryClient` Must Use `retry: false` in Tests

```tsx
// GOOD: Disable retries entirely
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});
```

Retries in tests cause flaky timing, extra network calls, and `act()` warnings.

### 14. Use One Injection Strategy Per Dependency

Do not use both `app.dependency_overrides[dep]` and `monkeypatch.setattr(module, "dep", ...)` for the same dependency. Prefer FastAPI's `dependency_overrides` for endpoint-injected deps.

### 15. Test Removed Surfaces Explicitly

When a route, hook, export, or runtime surface is intentionally removed, add an explicit test asserting its absence. This prevents accidental re-introduction during future refactors.

---

## Hierarchical TDD: Fake vs Real Resources

**Principle**: Use the fastest feedback loop that validates the behavior you care about.

| Resource      | Unit Test       | Service Test    | Integration Test  | E2E Test |
| ------------- | --------------- | --------------- | ----------------- | -------- |
| Database      | Fake repository | Fake repository | Real test DB      | Real DB  |
| HTTP/Network  | Never           | Fake client     | Mock server (MSW) | Real     |
| File System   | Never           | In-memory       | Temp directory    | Real     |
| Time/Clock    | Injected clock  | Injected clock  | Injected clock    | Real     |
| Random/UUID   | Seeded/fixed    | Seeded/fixed    | Seeded/fixed      | Real     |
| External APIs | Never           | Fake client     | Mock server       | Sandbox  |

### Python Fake Pattern

```python
# Domain interface (in domain/repositories.py)
class ClusterRepository(Protocol):
    async def get(self, cluster_id: UUID) -> IdentityCluster | None: ...
    async def save(self, cluster: IdentityCluster) -> None: ...

# Fake for service tests (in tests/fakes.py)
class FakeClusterRepository:
    def __init__(self) -> None:
        self._clusters: dict[UUID, IdentityCluster] = {}

    async def get(self, cluster_id: UUID) -> IdentityCluster | None:
        return self._clusters.get(cluster_id)

    async def save(self, cluster: IdentityCluster) -> None:
        self._clusters[cluster.id] = cluster
```

### TypeScript Fake Pattern

```typescript
// Fake for unit tests (in tests/fakes.ts)
export const createFakeRecognitionApi = (
  initialClusters: Cluster[] = [],
): RecognitionApi => {
  const clusters = new Map(initialClusters.map((c) => [c.id, c]));
  return {
    getClusters: async () => Array.from(clusters.values()),
    updateLabel: async (id, label) => {
      const cluster = clusters.get(id);
      if (cluster) clusters.set(id, { ...cluster, label });
    },
  };
};
```

---

## Test File Organization

```text
recognition/
  tests/
    unit/           # Layer 1: Pure functions, no I/O
    service/        # Layer 2: Fake repositories
    integration/    # Layer 3: Real database
    api/            # Layer 3: HTTP endpoints with test client
    e2e/            # Layer 4: Full stack (if applicable)
```

---

## Test Types

### Unit Tests (PHPUnit / Vitest / pytest)

- PHP: Mock HTTP responses, use WP_Mock for WordPress functions
- Frontend: Test behavior not implementation, use MSW for API mocking, use RFC 2606 domains (`http://example.test`)
- Python: Pure functions, no I/O

### Integration Tests

- Validate API contracts against JSON Schema fixtures in `docs/agentic/contracts/`
- Test authentication and authorization
- Test error responses and rate limiting

### Accessibility Tests

- Run axe-core on every component
- Assert zero critical violations
- Test keyboard navigation explicitly

---

## Performance Targets

- Synchronous endpoints: < 150ms response time
- Frontend: Lighthouse score > 90
- Core Web Vitals: LCP < 2.5s, FID < 100ms, CLS < 0.1
