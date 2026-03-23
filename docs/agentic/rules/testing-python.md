# Python Testing (pytest) -- Project Conventions

> **Library reference**: Use ctx7 to fetch current docs for `pytest`, `pytest-asyncio`,
> `httpx`, and `sqlalchemy` listed in
> [../maps/tech-stack.md](../maps/tech-stack.md#backend-python) before starting work.
> This file covers only project-specific conventions.

> Load this document when writing or reviewing tests in `apps/prototype-description-service/`. Start with [testing-principles.md](testing-principles.md) for universal concepts.

---

## pytest-Specific Rules

### Explicit Synchronization Over Sleep

Use `asyncio.wait_for(coro, timeout=N)` instead of `asyncio.sleep()`. Timing-based waits are flaky and non-deterministic.

### Exact Assertions in Integration Tests

Use deterministic fixtures for exact counts: `assert clusters_created == 3`, not `>= 1`.

### Test Mock Defaults Match Production Defaults

Mock return values must match production defaults. For example: `AsyncMock(return_value=0.5)` not `0.0`; the `curriculum_t` field defaults to `0.5` in the schema.

---

## Python Fake Pattern (Project Standard)

Use in-memory fakes for service layer tests. Keep fakes configurable, not hardcoded:

```python
class FakeClusterRepository:
    def __init__(self) -> None:
        self._clusters: dict[UUID, IdentityCluster] = {}

    async def get(self, cluster_id: UUID) -> IdentityCluster | None:
        return self._clusters.get(cluster_id)

    async def save(self, cluster: IdentityCluster) -> None:
        self._clusters[cluster.id] = cluster
```

Bad pattern -- always-None fakes produce false-positive passing tests:

```python
# BAD
async def get(self, *a, **kw): return None

# GOOD: configurable
class FakeSession:
    def __init__(self, data=None): self._data = data
    async def get(self, *a, **kw): return self._data
```

---

## FastAPI Dependency Injection in Tests

### Use One Injection Strategy Per Dependency

Do not use both `app.dependency_overrides[dep]` and `monkeypatch.setattr(module, "dep", ...)` for the same dependency. Prefer FastAPI's `dependency_overrides` for endpoint-injected deps.

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
