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

### Path Parameter Names Must Not Collide With Dependency Query Parameters

FastAPI validates parameter sources across the **entire transitive dependency tree** of each route at module-load time. If any dependency (or sub-dependency) declares `param_name` as `Query` and the route URL contains `{param_name}` as a path segment, all test files that import the app will fail with:

```
AssertionError: Cannot use `Query` for path param 'param_name'
```

**Common trigger:** `get_session` depends on `get_tenant_id_optional`, which declares `tenant_id: Query`. Any route with `{tenant_id}` in its path that transitively depends on `get_session` (e.g., through `get_cluster_repository`) will collide -- even if the route never directly calls `get_tenant_id`.

**Fix:** Rename the path segment to avoid the reserved name:

```python
# BAD: {tenant_id} collides with tenant_id: Query in get_session dep chain
@router.get("/tenants/{tenant_id}/clusters/snapshot")
async def snapshot(tenant_id: str, repo=Depends(get_cluster_repository)): ...
#                                        ^^ get_cluster_repository -> get_session
#                                           -> get_tenant_id_optional(tenant_id: Query)

# GOOD: {tenant_uuid} avoids the reserved name
@router.get("/tenants/{tenant_uuid}/clusters/snapshot")
async def snapshot(tenant_uuid: str, repo=Depends(get_cluster_repository)):
    tenant_id = tenant_uuid  # alias for internal use
    ...
```

**Rule of thumb:** Before adding `{name}` to a route path, grep for `name.*Query` in `recognition/interface_adapters/http/deps/` to check for collisions.

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
