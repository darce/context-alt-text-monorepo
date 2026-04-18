# Backend Python Guidelines (FastAPI/Recognition Service) -- Project Conventions

> **Library reference**: Use ctx7 to fetch current docs for FastAPI, SQLAlchemy, Pydantic,
> and pytest listed in
> [../maps/tech-stack.md](../maps/tech-stack.md#backend-python) before starting work.
> This file covers only project-specific conventions.

> Load this document when working on Python code in `apps/prototype-description-service/`.

---

## Environment Setup

```bash
# Use pyenv for Python version + virtualenv management
pyenv shell description-service

# Full setup (recommended) - handles platform-specific dependencies
cd apps/prototype-description-service
make setup
```

**Alternative: Core dependencies only (no face detection)**

```bash
make install  # Faster, skips insightface
```

> [!IMPORTANT]
> **Never use `pip install <package>` directly.** Add dependencies to `pyproject.toml` and install via `make setup` or `make install`.

> [!NOTE]
> **macOS Apple Silicon**: `insightface` requires special SDK flags handled automatically by `make setup`. Do NOT install it directly via pip.

---

## Architecture

Hexagonal Architecture with clear layer boundaries:

```
recognition/
+-- interface_adapters/http/     # FastAPI routers (HTTP boundary)
+-- application/                 # Use cases / orchestration
+-- domain/                      # Core business entities
+-- infrastructure/              # External adapters (DB, embedding)
+-- worker/                      # Background job processing
```

**Naming boundary:** Infrastructure uses `Face*` (tied to InsightFace); domain uses `*Identity` (technology-agnostic). Seam: `EmbeddingService.to_media_identities()`. See [ADR-001](../adrs/ADR-001-face-identity-nomenclature.md).

---

## Hexagonal Layer Rules

1. **No raw SQL in the application layer.** Raw queries only in `infrastructure/repositories/`.
2. **No `contextlib.suppress(Exception)`.** Catch specific exceptions; log at `WARNING` minimum.
3. **No `getattr()` duck-typing on service protocols.** Declare methods on the Protocol interface. `getattr(service, "method_name", None)` + `callable()` guards defeat mypy.
4. **No presentation DTOs in domain or application layer.** API-shaped types belong in `interface_adapters/http/schemas/`. Application services return domain types.
5. **No `object` parameters.** Use the domain type or a Protocol.
6. **No default-instantiating settings.** `ClusteringSettings()` inside a function bypasses DI. Inject settings as a parameter.
7. **Escape LIKE wildcards.** User-supplied strings in `ilike()` must escape `%` and `_`.
8. **Migration <-> model parity.** Run `alembic check` after schema changes.
9. **No duplicate definitions.** Exceptions, constants, and helpers must have exactly one canonical location.
10. **Extract shared repository utilities.** Boilerplate (UUID coercion, media-identity bootstrap) lives in `infrastructure/repositories/_helpers.py`.
11. **Scope `except` clauses narrowly.** Wrap only the single call you intend to guard.
12. **No redundant router/dependency wiring.** Do not register sub-routers individually when a parent already `include_router`s them.
13. **No path/query parameter name collisions across the dependency tree.** FastAPI validates parameter sources across the transitive dependency chain at load time. Rename path segments to avoid reserved names (e.g., `{tenant_uuid}` instead of `{tenant_id}`).

---

## Standards

- Python 3.11+, type hints on all functions
- Google-style docstrings (Args, Returns, Raises, side effects)
- < 40 lines per function, 120 char line length
- `ruff check` and `mypy` must pass
- `assert` only for internal invariants/tests; raise explicit exceptions for request validation and production behavior

## Write Caller Ordering

For `agent-handoff-mcp` write paths, resolve `task_ref` before calling `collect_target_context_warnings(...)`.

Correct pattern:

```python
resolved_task_ref = _resolve_task_ref(conn, task_ref)
warnings = collect_target_context_warnings(conn, ctx, task_ref=resolved_task_ref)
```

Calling the guard first lets branch enforcement or workspace drift checks bind to the wrong task row and was the root cause of the multi-active review-finding regressions fixed in E17-11.

---

## Tooling (Ruff replaces flake8/black/isort)

```bash
ruff check .              # Lint (pycodestyle, pyflakes, isort, bugbear, etc.)
ruff format .             # Format (replaces black)
ruff check --fix .        # Auto-fix safe issues
PYENV_VERSION=description-service mypy .  # Type checking (run from apps/prototype-description-service/)
```

---

## Async Patterns

```python
# All database and I/O operations must be async
async def get_cluster(self, cluster_id: str) -> IdentityCluster | None:
    result = await self.session.execute(select(ClusterModel).where(...))
    return result.scalar_one_or_none()

# Use asyncio.gather for parallel operations
results = await asyncio.gather(
    self.get_cluster(id1),
    self.get_cluster(id2),
)
```

---

## Pydantic Patterns

```python
# Settings via pydantic BaseModel (hardcoded defaults, override in code)
from pydantic import BaseModel, ConfigDict, Field

class ClusteringSettings(BaseModel):
    """Threshold configuration with type-safe defaults."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    similarity_threshold: float = Field(default=0.85, description="Base threshold for matching.")
    min_cluster_size: int = Field(default=2, description="Minimum cluster members.")

# Request/Response models with validation
class ClusterResponse(BaseModel):
    id: str  # Short ID format
    label: str | None
    member_count: int = Field(ge=0)
```

> **Note:** Use `pydantic.BaseModel`, NOT `pydantic-settings.BaseSettings`. No `.env` files for algorithm thresholds.

---

## FastAPI Patterns

```python
# Dependency injection for services
from fastapi import Depends

def get_cluster_service(
    repo: ClusterRepository = Depends(get_repository),
) -> ClusterService:
    return ClusterService(repo)

@router.get("/clusters/{cluster_id}")
async def get_cluster(
    cluster_id: str,
    service: ClusterService = Depends(get_cluster_service),
) -> ClusterResponse:
    cluster = await service.get(cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return ClusterResponse.model_validate(cluster)
```

---

## Configuration

- All settings via `pydantic.BaseModel` with hardcoded defaults; override by instantiating with explicit values
- No `.env` files for algorithm thresholds
- `Field(default=..., description="...")` for self-documenting settings
- Fail fast on invalid configuration at startup

---

## Coverage

- 80% overall, 95% on critical pipelines (recognition, clustering)

---

## Database Shell

**Agents MUST use `db_shell.sh`** instead of raw `psql`:

```bash
./scripts/db_shell.sh              # App user (RLS-enabled)
./scripts/db_shell.sh --admin      # Admin (bypasses RLS)
./scripts/db_shell.sh --admin -c "SELECT * FROM identity_clusters LIMIT 5;"
```

---

## Commands

```bash
cd apps/prototype-description-service
pyenv shell description-service       # Activate virtualenv
make check                            # ruff + mypy + pytest (all three)
pytest                                # Run all tests
pytest recognition/tests/api/         # API tests only
pytest recognition/tests/integration/ # Integration tests (DB)
pytest recognition/tests/unit/        # Unit tests
ruff check .                          # Lint
ruff format .                         # Format
PYENV_VERSION=description-service mypy .  # Type checking
```
