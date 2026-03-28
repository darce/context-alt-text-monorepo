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

The `make setup` command runs `scripts/setup.sh`, which:

- Installs core dependencies from `pyproject.toml`
- Detects macOS Apple Silicon and uses specialized build flags for `insightface`
- Falls back to standard pip install on Linux

**Alternative: Core dependencies only (no face detection)**

```bash
make install  # Faster, skips insightface
```

> [!IMPORTANT]
> **Never use `pip install <package>` directly.** All Python dependencies MUST be added to `pyproject.toml` and installed via `make setup` or `make install`. This ensures reproducible environments and version control of dependencies.

> [!NOTE]
> **macOS Apple Silicon users**: The `insightface` package requires special SDK flags to compile. This is handled automatically by `make setup`. Do NOT try to install `insightface` directly via pip.

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

**Naming boundary:** Infrastructure uses `Face*` nomenclature (tied to InsightFace); domain uses `*Identity` nomenclature (technology-agnostic). The seam is `EmbeddingService.to_media_identities()`. See [ADR-001](../adrs/ADR-001-face-identity-nomenclature.md) for full rationale.

---

## Hexagonal Layer Rules

> Distilled from the 4.12.0 branch audit. Violating them creates coupling, suppresses errors, and defeats type safety.

1. **No raw SQL in the application layer.** Use `text()` / raw queries only in `infrastructure/repositories/`. The application layer must call repository methods.
2. **No `contextlib.suppress(Exception)`.** Bare suppression hides real bugs. Catch specific exceptions and log at `WARNING` level at minimum.
3. **No `getattr()` duck-typing on service protocols.** If a method is used at a call site, declare it on the Protocol interface. Never use `getattr(service, "method_name", None)` + `callable()` guards -- this defeats mypy entirely.
4. **No presentation DTOs in the domain or application layer.** Types shaped for API responses (`FaceBox`, `SuggestionDetails`) belong in `interface_adapters/http/schemas/`. Application services must return domain types; the interface adapter maps to DTOs at the HTTP boundary.
5. **No `object` parameters.** Use the domain type or a Protocol. `getattr(cluster, "label", None)` silently returns `None` on typos.
6. **No default-instantiating settings.** `ClusteringSettings()` inside a function bypasses DI. Always inject settings as a parameter.
7. **Escape LIKE wildcards.** Any user-supplied string used in `ilike()` must escape `%` and `_` before interpolation.
8. **Migration <-> model parity.** After any schema change, verify the migration and ORM model define identical constraints. Run `alembic check` to detect drift.
9. **No duplicate definitions.** Exceptions, constants, and helpers must have exactly one canonical location. Cross-layer duplication causes import confusion.
10. **Extract shared repository utilities.** UUID coercion, media-identity bootstrap, and similar boilerplate must live in a shared module (e.g., `infrastructure/repositories/_helpers.py`), not be copy-pasted across repository files.
11. **Scope `except` clauses to the exact operation they guard.** A broad `except ValueError` that wraps an entire method body will catch unrelated errors from downstream calls -- turning real bugs into silent "not found" responses. Wrap only the single call you intend to guard and let other exceptions propagate.
12. **No redundant router/dependency wiring.** When a parent router already `include_router`s its sub-routers, do not also register those sub-routers individually on the app. Duplicate registration multiplies endpoint handlers.
13. **No path/query parameter name collisions across the dependency tree.** FastAPI validates parameter sources across the entire transitive dependency chain of each route at module-load time. If any sub-dependency declares `param_name` as `Query` and the route URL contains `{param_name}`, the app fails to start. Rename the path segment to avoid the reserved name (e.g., `{tenant_uuid}` instead of `{tenant_id}` when `get_session` transitively depends on `get_tenant_id_optional`).

---

## Standards

- Python 3.11+ required
- Type hints on all functions (gradual strictness via mypy overrides)
- Google-style docstrings describing Args, Returns, Raises, side effects
- Target < 40 lines per function
- 120 character line length
- `ruff check` and `mypy` must pass
- Use `assert` only for narrow internal invariants and tests. For request validation, external data checks, and behavior that must always run in production, raise explicit exceptions or HTTP errors instead.

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

> **Note:** Use `pydantic.BaseModel` for settings, NOT `pydantic-settings.BaseSettings`. Avoid `.env` files for algorithm thresholds -- keep them in code for type safety and version control.

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

- All settings via `pydantic.BaseModel` with hardcoded defaults
- Override settings by instantiating with explicit values in code
- No `.env` files for algorithm thresholds (version control + type safety)
- Use `Field(default=..., description="...")` for self-documenting settings
- Fail fast on invalid configuration at startup

---

## Coverage

- 80% overall minimum
- 95% on critical pipelines (recognition, clustering)

---

## Database Shell

Use `scripts/db_shell.sh` for all database queries during development:

```bash
# Connect as app user (RLS-enabled)
./scripts/db_shell.sh

# Connect as admin (bypasses RLS)
./scripts/db_shell.sh --admin

# Run a query directly
./scripts/db_shell.sh --admin -c "SELECT * FROM identity_clusters LIMIT 5;"

# Disable pager for scripted queries
PAGER=cat ./scripts/db_shell.sh --admin -c "SELECT table_name FROM information_schema.tables;"
```

> [!IMPORTANT]
> **Agents MUST use `db_shell.sh`** for database queries instead of raw `psql` commands. This ensures correct credentials and connection settings are used.

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
