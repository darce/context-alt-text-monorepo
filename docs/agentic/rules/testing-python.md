# Python Testing (pytest) -- Project Conventions

> **Library reference**: Use ctx7 to fetch current docs for `pytest`, `pytest-asyncio`,
> `httpx`, and `sqlalchemy` listed in
> [../maps/tech-stack.md](../maps/tech-stack.md#backend-python) before starting work.
> This file covers only project-specific conventions.

> Load this document when writing or reviewing tests in `apps/prototype-description-service/`. Start with [testing-principles.md](testing-principles.md) for universal concepts.

---

## pytest-Specific Rules

### Explicit Synchronization Over Sleep

Use `asyncio.wait_for(coro, timeout=N)` instead of `asyncio.sleep()`.

### Exact Assertions in Integration Tests

Use exact counts: `assert clusters_created == 3`, not `>= 1`.

### Test Mock Defaults Match Production Defaults

Mock return values must match production defaults (e.g., `AsyncMock(return_value=0.5)` not `0.0` when `curriculum_t` defaults to `0.5`). Part of the broader stub-fidelity requirements in [testing-principles.md](testing-principles.md).

---

## Python Fake Pattern (Project Standard)

Use configurable in-memory fakes for service layer tests:

```python
class FakeClusterRepository:
    def __init__(self) -> None:
        self._clusters: dict[UUID, IdentityCluster] = {}

    async def get(self, cluster_id: UUID) -> IdentityCluster | None:
        return self._clusters.get(cluster_id)

    async def save(self, cluster: IdentityCluster) -> None:
        self._clusters[cluster.id] = cluster
```

Always-None fakes produce false positives:

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

Do not mix `app.dependency_overrides[dep]` and `monkeypatch.setattr(module, "dep", ...)` for the same dependency. Prefer `dependency_overrides`.

### Path Parameter Names Must Not Collide With Dependency Query Parameters

FastAPI validates parameter sources across the entire transitive dependency tree at module-load time. If any dependency declares `param_name` as `Query` and the route URL contains `{param_name}` as a path segment, all test imports fail with `AssertionError: Cannot use 'Query' for path param 'param_name'`.

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

Before adding `{name}` to a route path, grep for `name.*Query` in `recognition/interface_adapters/http/deps/` to check for collisions.

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

## External MCP Package Verification (E17-13)

For the E17-13 cleanup path, verify `agent-handoff-mcp` and `agent-orchestrator-mcp` as packaged standalone installs, not via worktree-local package test targets.

```bash
python3 -m venv /tmp/e17-13-external-mcp
/tmp/e17-13-external-mcp/bin/pip install --quiet \
    "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2" \
    "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.3"
/tmp/e17-13-external-mcp/bin/agent-handoff-mcp --workspace-root . doctor
/tmp/e17-13-external-mcp/bin/agent-orchestrator-mcp --workspace-root . --help
```

This is the external-install verification convention that replaces the package-local conftest/Makefile guard guidance for the cleanup task. The proof must run in a scratch venv with no editable installs from this monorepo, so the result reflects the published `git+ssh://` artifacts rather than a worktree-local import path.

### Background

The older package-local guard model existed to keep linked worktrees from silently resolving to the wrong editable install. E17-13 now needs the stronger consumer-facing proof: validate the published refs directly and keep local package-source assumptions out of the verification path.

## Commit SHA Provenance Discipline (MANDATORY)

- **Pass the canonical 40-character SHA** from `git rev-parse HEAD`, never typed from memory.
- The MCP write path validates every `commit_sha` via `git rev-parse --verify <sha>^{commit}` and rejects fabricated SHAs. Abbreviated SHAs (4-40 hex chars) are auto-expanded.
- Validation is bypassed in test suites via `AGENT_HANDOFF_SKIP_SHA_VALIDATION` (set in both packages' `tests/conftest.py`).

### Background

Added in `AHMCP-13` after `AHMCP-10`/`AHMCP-11` audit-trail rows were tagged with SHAs typed from memory. The validator closes this hole at the MCP write boundary so fabricated SHAs cannot enter the audit trail.
