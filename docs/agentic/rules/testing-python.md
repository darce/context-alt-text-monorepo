# Python Testing (pytest)

> Load this document when writing or reviewing tests in `apps/prototype-description-service/`. Start with [testing-principles.md](testing-principles.md) for universal concepts.

---

## Framework Stack

- **Test runner**: pytest
- **Async testing**: pytest-asyncio
- **HTTP client testing**: httpx.AsyncClient with FastAPI TestClient
- **Database**: SQLAlchemy with in-memory SQLite or PostgreSQL test container

---

## pytest-Specific Rules

### Explicit Synchronization Over Sleep

```python
# BAD: Timing-based waits are flaky
await asyncio.sleep(0.05)
assert subscriber.received_event

# GOOD: Wait for explicit condition with timeout
await asyncio.wait_for(event_queue.get(), timeout=1.0)
```

### Exact Assertions in Integration Tests

```python
# BAD: Broad assertions allow regressions
assert clusters_created >= 1

# GOOD: Use deterministic fixtures for exact counts
assert clusters_created == 3
```

### Test Mock Defaults Match Production Defaults

```python
# BAD: Mock returns different default than production
repo.get_curriculum_t = AsyncMock(return_value=0.0)  # Production default is 0.5!

# GOOD: Match production defaults explicitly
repo.get_curriculum_t = AsyncMock(return_value=0.5)  # Matches schema default
```

---

## Python Fake Pattern

### Domain Interface

```python
# Domain interface (in domain/repositories.py)
class ClusterRepository(Protocol):
    async def get(self, cluster_id: UUID) -> IdentityCluster | None: ...
    async def save(self, cluster: IdentityCluster) -> None: ...
```

### Fake for Service Tests

```python
# Fake for service tests (in tests/fakes.py)
class FakeClusterRepository:
    def __init__(self) -> None:
        self._clusters: dict[UUID, IdentityCluster] = {}

    async def get(self, cluster_id: UUID) -> IdentityCluster | None:
        return self._clusters.get(cluster_id)

    async def save(self, cluster: IdentityCluster) -> None:
        self._clusters[cluster.id] = cluster
```

### Configurable Fakes, Not False Positives

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

---

## FastAPI Dependency Injection in Tests

### Use One Injection Strategy Per Dependency

Do not use both `app.dependency_overrides[dep]` and `monkeypatch.setattr(module, "dep", ...)` for the same dependency. Prefer FastAPI's `dependency_overrides` for endpoint-injected deps.

```python
# GOOD: Override via FastAPI dependency system
app.dependency_overrides[get_cluster_repo] = lambda: FakeClusterRepository()

# AVOID mixing with monkeypatch for the same dependency
```

---

## Test Organization

```text
recognition/
  tests/
    unit/           # Pure functions, no I/O
    service/        # Fake repositories, domain services
    integration/    # Real database, real HTTP client
    api/            # HTTP endpoints with test client
```

---

## Commands

```bash
cd apps/prototype-description-service
make test           # Run pytest
make ruff           # Linting with Ruff
make mypy           # Type checking
make check          # All checks (ruff + mypy + pytest)
```
