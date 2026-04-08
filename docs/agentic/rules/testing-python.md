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

This rule is part of the broader stub-fidelity requirements in [testing-principles.md](testing-principles.md). Matching default values is not enough when the real dependency also raises errors or transitions state; use a behavioral fake when the test depends on that behavior.

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

## In-Monorepo Package Test Invocation (MANDATORY)

For tests under `packages/agent-handoff-mcp/` and `packages/agent-orchestrator-mcp/`,
**always invoke pytest via the package Makefile target**, never via a direct
`pytest` command:

```bash
cd packages/agent-handoff-mcp && make test-handoff
cd packages/agent-orchestrator-mcp && make test-orchestrator
```

The Makefile sets `PYTHONPATH` to the **current worktree's** `src/` directory
before invoking pytest. Direct `pytest` invocations rely on whatever editable
install (`pip install -e .`) is currently registered in the Python environment,
and editable installs are environment-wide: a single `pip install -e packages/agent-handoff-mcp`
from one checkout makes every Python interpreter in the venv resolve
`import agent_handoff_mcp` to that path, regardless of which git worktree the
test session is running from. Linked worktrees inherit that same install
pointer, so a refactor that lives only in the linked worktree's source will
silently NOT be exercised by tests run inside that worktree — pytest runs
against the root worktree's source instead, producing false-positive
verification reports.

### Enforcement

Both packages' `tests/conftest.py` files contain a `pytest_sessionstart`
guard that imports the package, compares its resolved `__file__` against
the expected worktree-local source path, and aborts the session with a
`pytest.UsageError` if they differ. The guard cannot be bypassed without
editing the conftest. The guard message names the Makefile target the
caller should use instead.

### Background

This enforcement was added in `AHMCP-13` after `AHMCP-10` regressed 65
orchestrator tests because the original verification ran inside a linked
worktree but the editable install resolved to the root checkout's
pre-refactor source. The resulting "586 passed" claim was a false positive
and the regression was not caught until the merge landed and the root
worktree updated.

### If you must invoke pytest directly

Set `PYTHONPATH` explicitly so the worktree's `src/` precedes the editable
install in import resolution:

```bash
PYTHONPATH=packages/agent-handoff-mcp/src:packages/agent-orchestrator-mcp/src \
  pyenv exec python -m pytest packages/agent-handoff-mcp/tests -q
```

The conftest guard verifies this anyway and will fail the session if the
imported package still resolves to the wrong path.

## Commit SHA Provenance Discipline (MANDATORY)

Whenever a handoff write path accepts a `commit_sha` (`record_event(actor=...)`,
`set_handoff_state(actor=...)`, `update_review_finding(verified_commit_sha=...)`,
`handoff_close_check(current_commit_sha=...)`, etc.):

- **Pass the canonical 40-character SHA**, not an abbreviation.
- **Get the SHA from `git rev-parse <abbrev>` or `git rev-parse HEAD`**, never
  by typing the suffix from memory after seeing a 7-char abbreviation in
  `git commit` output.
- The MCP write path validates every `commit_sha` against the active git
  repo via `git rev-parse --verify <sha>^{commit}`. If the SHA does not
  resolve to a real commit, the write is rejected with an error message
  pointing at this rule. Abbreviated SHAs (4-40 hex chars) that resolve
  uniquely are auto-expanded to the full 40-char form before being stored.
- Validation is bypassed inside the test suites via the
  `AGENT_HANDOFF_SKIP_SHA_VALIDATION` env var (set in both packages'
  `tests/conftest.py`); production callers always run with validation
  enabled.

### Background

This enforcement was added in `AHMCP-13` after several `AHMCP-10` and
`AHMCP-11` audit-trail rows ended up tagged with SHA suffixes that were
typed from memory rather than via `git rev-parse`. The pre-existing
`handoff_close_check` gate compared the passed `current_commit_sha` against
the recorded slice decision's `commit_sha` as opaque strings, so a
fabricated SHA that matched itself sailed through the gate. The validator
closes that hole at the MCP write boundary so fabricated SHAs cannot enter
the audit trail in the first place.
