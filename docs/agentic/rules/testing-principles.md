# Testing Principles

> Universal testing concepts that apply across all languages and test frameworks in the monorepo. Load this document first, then consult language-specific guides: [testing-typescript.md](testing-typescript.md), [testing-python.md](testing-python.md), [testing-php.md](testing-php.md).

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

**Principle**: Most tests at the bottom (fast unit tests), fewer at the top (slow E2E tests).

---

## Universal Test Writing Rules

### 1. Deterministic Data Over Randomness

Tests must produce identical results on every run. Use fixed fixtures or seeded random generators.

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

### 2. Behavioral Assertions Over Call Counts

Assert observable outcomes, not internal implementation details.

```python
# BAD: Brittle coupling to internal calls
mock_repo.recompute_centroid.assert_called_once()

# GOOD: Assert observable outcomes
assert cluster.identity_count == 5
assert cluster.centroid_updated_at > original_timestamp

# ACCEPTABLE: One or two critical side-effect assertions
mock_event_bus.emit.assert_called_with(ClusterMergedEvent(...))
```

### 3. Import Settings, Don't Hardcode

Reference configuration values from their source of truth, not hardcoded magic numbers.

```python
# BAD: Magic numbers that can diverge from production
assert result.threshold == 0.65

# GOOD: Reference the source of truth
from recognition.application.settings import ClusteringSettings

settings = ClusteringSettings()
assert result.threshold == settings.suggestion_floor
```

### 4. No Permanently Skipped Tests

Tests marked with skip annotations without a linked issue or TODO date are dead code. Either:

- Remove the test (if the feature is abandoned)
- Complete the test (if the feature shipped)
- Add a comment with an issue reference and expected resolution (if blocked)

Empty test bodies that run green are worse -- they inflate pass counts.

### 5. Test Removed Surfaces Explicitly

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

---

## Test Organization

### Directory Structure

```text
recognition/
  tests/
    unit/           # Layer 1: Pure functions, no I/O
    service/        # Layer 2: Fake repositories
    integration/    # Layer 3: Real database
    api/            # Layer 3: HTTP endpoints with test client
    e2e/            # Layer 4: Full stack (if applicable)
```

### Shared Test Utilities

If a Protocol stub or fake is copy-pasted across 3+ test files, extract it to a shared test utility module (`tests/fakes.py`, `tests/stubs.py`, `tests/helpers.ts`, etc.).

```python
# BAD: 100-line ClusterRepoStub defined independently in 4 test files

# GOOD: Shared null implementation in tests/stubs.py
class NullClusterRepository:
    """No-op implementation of ClusterRepository for unit tests."""
    async def get(self, cluster_id): return None
    async def save(self, cluster): pass
    # full Protocol surface in one place
```

### One Canonical Fake Per Protocol

Do not maintain multiple divergent fake implementations of the same Protocol across test files. Use a single configurable fake.

### 7. Fixture Data Over Live Config

Tests for generic infrastructure (manifest loaders, config readers, serializers) must use temporary fixture data created by the test, not hardcoded references to a specific live task config. If the live config is renamed or restructured, generic tests should not break.

```python
# BAD: Coupled to a specific live config file
def test_load_manifest():
    data = load_manifest("phase-5-retention-export-and-audit-controls")
    assert data["merge_order"] == ["backend-domain", ...]

# GOOD: Fixture manifest in tmp_path
def test_load_manifest(tmp_path):
    manifest = {"task_ref": "test-task", "merge_order": ["a", "b"], ...}
    (tmp_path / "test-task.json").write_text(json.dumps(manifest))
    data = load_manifest("test-task", manifest_dir=tmp_path)
    assert data["merge_order"] == ["a", "b"]
```

Keep at most one smoke test asserting the real config file loads without error.

---

## Performance Targets

- Synchronous endpoints: < 150ms response time
- Frontend: Lighthouse score > 90
- Core Web Vitals: LCP < 2.5s, FID < 100ms, CLS < 0.1

---

## Next Steps

Consult your language-specific testing guide:

- **TypeScript/React** → [testing-typescript.md](testing-typescript.md)
- **Python/FastAPI** → [testing-python.md](testing-python.md)
- **PHP/WordPress** → [testing-php.md](testing-php.md)
