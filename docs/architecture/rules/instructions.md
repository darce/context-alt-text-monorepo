# Development Instructions

Build a maintainable, readable, testable WordPress plugin (Context Alt Text) using Test-Driven Development and incremental architecture practices.

**Roadmap**: `docs/roadmaps/roadmap-v3.hybrid.md`

---

## Table of Contents

1. [Monorepo Layout](#monorepo-layout)
2. [Critical Rules](#critical-rules)
3. [Core Engineering Principles](#core-engineering-principles)
4. [Development Workflow](#development-workflow)
5. [Frontend Guidelines](#frontend-guidelines)
6. [Backend Guidelines](#backend-guidelines)
7. [Testing Standards](#testing-standards)
8. [Security Patterns](#security-patterns)
9. [Code Style](#code-style)
10. [Documentation Standards](#documentation-standards)

---

## Monorepo Layout

```text
context-alt-text-monorepo/
    apps/
        prototype-wp-alt-context/     # WordPress plugin (frontend)
        prototype-description-service/ # FastAPI recognition service (backend)
    packages/
        shared-contracts/             # Shared API contracts and schemas
        wp-testing-helpers/           # Test utilities
    docs/
        architecture/
            rules/                    # This file and related guides
            backend-uml/              # Backend diagrams (Mermaid)
            frontend-uml/             # Frontend diagrams (Mermaid)
            contracts/                # API schemas and fixtures
        roadmaps/                     # Project roadmaps
        tasks/                        # Task breakdowns by version
    scripts/                          # Utility scripts
```

All architectural decisions, contracts, and diagrams land in `docs/architecture` first to keep frontend and backend in sync.

---

## Critical Rules

### Plugin Boundary Rule

> **You may ONLY modify files within this monorepo.**

**Allowed paths:**

- `apps/prototype-wp-alt-context/`
- `apps/prototype-description-service/`
- `packages/`
- `docs/`
- `scripts/`

**Never modify:**

- WordPress core files (`wp-config.php`, `.htaccess`, etc.)
- LocalWP configuration
- Files in `~/Local Sites/` or any WordPress installation directory
- System configuration files

If a task seems to require external changes, STOP and propose an alternative within plugin boundaries.

### Architecture Tooling Guardrail

- Do not relax or edit compliance/lint scripts (e.g., `scripts/check-architecture-compliance.js`) to silence violations. Fix the offending code or update the documented rules instead.

### Greenfield Policy

This plugin has no production users. Storage surfaces (database tables, options, caches) are disposable. Prefer clean rewrites over migrations or backward-compatibility shims. Keep tests in lockstep with schema changes.

### Remove Over Flag

No existing install base means full latitude to delete experimental features. Prefer removal over long-lived feature flags. Re-introduce features behind tests when truly needed.

---

## Core Engineering Principles

### 1. Test-Driven Development

**Red -> Green -> Refactor** for every meaningful change.

- Write failing tests first that define acceptance criteria
- Implement minimal code to pass
- Refactor while keeping tests green
- Do NOT write tests just to verify you wrote the code you wrote

### 2. Scaffolding First (MANDATORY)

**Before writing any implementation or tests, scaffold all interfaces and contracts.**

- Add function/method signatures with complete type hints
- Write comprehensive docstrings (Args, Returns, Raises, Examples)
- Use `raise NotImplementedError("TODO: ...")` as initial body
- Commit after scaffolding each class/function

**This applies to ALL new code**:

- Backend: Python functions, classes, methods
- Frontend: TypeScript functions, React components, hooks
- Tests: Test function signatures and fixtures

**Why scaffolding first?**

- Defines clear contracts before implementation details
- Enables test-writing without implementation dependencies
- Creates reviewable architecture (review signatures before logic)
- Supports parallel development (multiple devs working on different functions)
- Provides early feedback on API design

**Enforcement**: Task checklists MUST include a "Phase 0: Scaffolding" section that is completed before implementation phases.

### 3. Small Vertical Slices

Implement only the minimum needed to make the current test pass. Avoid speculative features.

### 4. Explicit Interfaces

Introduce abstractions (providers, services, interfaces) before integrating remote or hard-to-mock concerns:

```php
// PHP: Define interface before implementation
interface CaptionProviderInterface {
    public function generateCaption(ImageContext $ctx): CaptionResult;
}
```

```typescript
// TypeScript: Define types before implementation
interface RecognitionService {
  detectFaces(imageUrl: string): Promise<DetectedFace[]>;
}
```

### 5. Deterministic Tests

No network calls, randomness, or time-based logic without controlled seams/mocks. Tests must produce identical results on every run.

### 6. User Consent for Remote Operations

Never call remote recognition services or sync operations without explicit user action. Provide immediate feedback on success/failure.

### No Fabricated Data

Never fabricate benchmark numbers, latency claims, or metrics. If data is unavailable, return an explicit empty state or error. Document measurement methods and timestamps.

### No False Claims of Bug Fixes

**Never claim a bug is fixed without verifying in production/staging logs.**

- A unit test passing does NOT prove a bug is fixed in production
- A synthetic verification script does NOT prove real-world behavior changed
- If asked to verify a fix, check ACTUAL logs from the running system
- If the bug is still present in logs, the fix is NOT complete — period
- Do not mark tasks as "✅ COMPLETE" based on theoretical analysis

**The "Cam Grant domination" bug (December 2025) was falsely claimed as fixed when 21+ false positives were still appearing in production logs. This is unacceptable.**

---

## Development Workflow

### Slice Checklist

1. Identify the roadmap epic you are advancing
2. **Scaffold first**: Create class/function signatures with type hints and docstrings BEFORE implementation
3. **Write failing tests first** (PHPUnit, Vitest, or integration) - **TDD is mandatory, not optional**
4. If remote dependencies exist, add a provider interface + mock
5. Implement minimal production code to pass tests (Red → Green → Refactor)
6. Refactor for clarity while tests stay green
7. Update UML diagrams if architecture changed
8. Security pass: nonce/capability checks, escape/sanitize
9. Accessibility pass: keyboard navigation, ARIA labels
10. Run full test suite locally before committing
11. Commit with Conventional Commits format

**Development Approach: Gradual Layering**

- **DO NOT** implement top-to-bottom (entire feature at once)
- **DO** scaffold interfaces, classes, and function signatures first
- **DO** implement in thin layers: signature → tests → minimal implementation → refactor
- **DO** commit frequently (per-layer, not per-feature)

This ensures:

- Clear contracts before implementation details
- Testable interfaces from the start
- Incremental progress with working checkpoints
- Easier code review (smaller, focused diffs)

### Conventional Commits

```text
feat(dashboard): add coverage trend visualization
fix(workbench): correct filter reset behavior
docs(architecture): update face recognition flow
test(coverage-card): add accessibility tests
refactor(api): simplify error handling
chore(deps): update react-query to v5.18
```

### Branch Naming

```text
feat/dashboard-cards
fix/alt-text-escaping
refactor/clustering-pipeline
```

### Roadmap Status Tags

```text
[DONE]     - User-visible, tested, documented
[PARTIAL]  - Some flows complete, more slices planned
[PLANNED]  - No implementation yet
[BLOCKED]  - Awaiting dependency (include brief reason)
```

---

## Frontend Guidelines

### Technology Stack

- **React 18+** with functional components and hooks
- **TypeScript 5.3+** with `strict: true`
- **Vite 5+** for build and dev server
- **React Query 5+** for data fetching
- **Radix UI** for accessible primitives
- **Vitest + Testing Library** for tests

### Component Rules

Before building custom UI, check [RADIX_UI_COMPONENT_GUIDE.md](RADIX_UI_COMPONENT_GUIDE.md) for pre-vetted accessible patterns.

**Size limits:**

- Maximum **300 lines** per component file
- Maximum **5 useState** hooks (use `useReducer` for complex state)
- Maximum **3 useEffect** hooks (prefer derived state)
- Maximum **10 props** (split component if exceeded)

**Extract when:**

- JSX block exceeds 50 lines
- Pattern appears 2+ times
- Conditional nesting exceeds 2 levels
- Component has 6+ useState hooks

### State Management Anti-Patterns

```tsx
// BAD: Syncing props to state
const [value, setValue] = useState(initialValue);
useEffect(() => setValue(initialValue), [initialValue]);

// GOOD: Use prop directly
const value = initialValue;

// BAD: Derived state in useState
const [filtered, setFiltered] = useState([]);
useEffect(() => setFiltered(items.filter((x) => x.active)), [items]);

// GOOD: Compute during render
const filtered = useMemo(() => items.filter((x) => x.active), [items]);

// BAD: Chained effects
useEffect(() => setB(a + 1), [a]);
useEffect(() => setC(b * 2), [b]);

// GOOD: Handle in event or derive
const handleChange = (newA: number) => {
  setA(newA);
  setC((newA + 1) * 2);
};
```

### Data Fetching

Use React Query for all API calls:

```tsx
const { data, isLoading, error, refetch } = useQuery({
  queryKey: ["clusters", tenantId],
  queryFn: () => fetchClusters(tenantId),
  staleTime: 60_000,
});
```

### Accessibility Requirements

- Query elements by accessible roles: `getByRole('button')`, not `getByTestId()`
- All interactive elements must be keyboard accessible
- Include ARIA labels for screen readers
- Test with axe-core (zero critical violations)
- Meet WCAG 2.1 AA standards

---

## Backend Guidelines

### WordPress Plugin (PHP)

**Standards:**

- PSR-12 + WordPress Coding Standards
- PHP 8.1+ features (typed properties, readonly, named arguments)
- PHPStan level 8 for static analysis
- Docblocks on all public methods

**Security:**

- Nonce required for all state mutations
- Centralize capability checks in a Security class
- Escape all output, sanitize all input
- Rate limiting via keyed transients

**REST API:**

- Routes registered under `acx/v1/` namespace
- Return WP_REST_Response with appropriate status codes
- Include helpful error messages with WP_Error codes

### Recognition Service (Python/FastAPI)

**Environment Setup:**

```bash
# Use pyenv for Python version + virtualenv management
pyenv shell description-service

# Install dependencies
cd apps/prototype-description-service
pip install -e ".[dev,local]"  # dev tools + local ONNX runtime
```

**Architecture:**

- Hexagonal boundaries: adapters separate from domain logic
- Domain logic in `recognition/domain/`
- Application layer in `recognition/application/`
- Infrastructure adapters in `recognition/infrastructure/`
- Interface adapters (HTTP) in `recognition/interface_adapters/`
- Services orchestrate domain operations

**Standards:**

- Python 3.11+ required
- Type hints on all functions (gradual strictness via mypy overrides)
- Google-style docstrings describing Args, Returns, Raises, side effects
- Target < 40 lines per function
- 120 character line length
- `ruff check` and `mypy` must pass

**Tooling (Ruff replaces flake8/black/isort):**

```bash
ruff check .              # Lint (pycodestyle, pyflakes, isort, bugbear, etc.)
ruff format .             # Format (replaces black)
ruff check --fix .        # Auto-fix safe issues
mypy .                    # Type checking
```

**Async Patterns:**

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

**Pydantic Patterns:**

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

> **Note:** Use `pydantic.BaseModel` for settings, NOT `pydantic-settings.BaseSettings`. Avoid `.env` files for algorithm thresholds—keep them in code for type safety and version control.

**FastAPI Patterns:**

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

**Configuration:**

- All settings via `pydantic.BaseModel` with hardcoded defaults
- Override settings by instantiating with explicit values in code
- No `.env` files for algorithm thresholds (version control + type safety)
- Use `Field(default=..., description="...")` for self-documenting settings
- Fail fast on invalid configuration at startup

**Coverage:**

- 80% overall minimum
- 95% on critical pipelines (recognition, clustering)

---

## Testing Standards

### Test Pyramid

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

### Hierarchical TDD: Fake vs Real Resources

**Principle**: Use the fastest feedback loop that validates the behavior you care about.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Layer 4: E2E Tests (Real browser, real WP, real backend)                │
│   - Use when: Final validation of user flows                            │
│   - Resources: Real database, real network, real browser                │
│   - Speed: Slow (seconds per test)                                      │
│   - Count: < 20 critical path tests                                     │
├─────────────────────────────────────────────────────────────────────────┤
│ Layer 3: Integration Tests (Real database, mocked externals)            │
│   - Use when: Testing repository patterns, SQL queries, RLS policies    │
│   - Resources: Real PostgreSQL (test DB), mocked HTTP services          │
│   - Speed: Medium (100-500ms per test)                                  │
│   - Count: 50-100 tests                                                 │
├─────────────────────────────────────────────────────────────────────────┤
│ Layer 2: Service Tests (Fake repositories, real domain logic)           │
│   - Use when: Testing business rules, orchestration, edge cases         │
│   - Resources: In-memory fakes, no I/O                                  │
│   - Speed: Fast (< 50ms per test)                                       │
│   - Count: 100-300 tests                                                │
├─────────────────────────────────────────────────────────────────────────┤
│ Layer 1: Unit Tests (Pure functions, no dependencies)                   │
│   - Use when: Testing algorithms, calculations, transformations         │
│   - Resources: None                                                     │
│   - Speed: Instant (< 5ms per test)                                     │
│   - Count: 200+ tests                                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

**Decision Matrix: When to Use Real vs Fake**

| Resource      | Unit Test          | Service Test       | Integration Test     | E2E Test   |
| ------------- | ------------------ | ------------------ | -------------------- | ---------- |
| Database      | ❌ Fake repository | ❌ Fake repository | ✅ Real test DB      | ✅ Real DB |
| HTTP/Network  | ❌ Never           | ❌ Fake client     | ❌ Mock server (MSW) | ✅ Real    |
| File System   | ❌ Never           | ❌ In-memory       | ⚠️ Temp directory    | ✅ Real    |
| Time/Clock    | ❌ Injected clock  | ❌ Injected clock  | ❌ Injected clock    | ✅ Real    |
| Random/UUID   | ❌ Seeded/fixed    | ❌ Seeded/fixed    | ❌ Seeded/fixed      | ✅ Real    |
| External APIs | ❌ Never           | ❌ Fake client     | ❌ Mock server       | ⚠️ Sandbox |

**Python Fake Pattern (Backend)**

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

# Real for integration tests (in infrastructure/repositories.py)
class SqlAlchemyClusterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, cluster_id: UUID) -> IdentityCluster | None:
        result = await self._session.execute(
            select(ClusterModel).where(ClusterModel.id == cluster_id)
        )
        return result.scalar_one_or_none()
```

**TypeScript Fake Pattern (Frontend)**

```typescript
// Interface (in types/services.ts)
interface RecognitionApi {
  getClusters(tenantId: string): Promise<Cluster[]>;
  updateLabel(clusterId: string, label: string): Promise<void>;
}

// Fake for unit tests (in tests/fakes.ts)
export const createFakeRecognitionApi = (
  initialClusters: Cluster[] = []
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

// MSW handler for integration tests (in tests/mocks/handlers.ts)
export const handlers = [
  http.get("/api/clusters", () => {
    return HttpResponse.json({ clusters: mockClusters });
  }),
];
```

**Test File Organization**

```text
recognition/
  tests/
    unit/           # Layer 1: Pure functions, no I/O
      test_similarity.py
      test_clustering_algorithm.py
    service/        # Layer 2: Fake repositories
      test_cluster_service.py
      test_assignment_gate.py
    integration/    # Layer 3: Real database
      test_cluster_repository.py
      test_rls_policies.py
    api/            # Layer 3: HTTP endpoints with test client
      test_clusters_router.py
    e2e/            # Layer 4: Full stack (if applicable)
      test_clustering_flow.py
```

**RLS Testing Strategy**

Row Level Security requires real database tests:

```python
# integration/test_rls_policies.py
@pytest.mark.integration
async def test_tenant_isolation(db_session):
    """Tenant A cannot see Tenant B's clusters."""
    # Create clusters for two tenants
    await create_cluster(db_session, tenant_id=TENANT_A, label="Alice")
    await create_cluster(db_session, tenant_id=TENANT_B, label="Bob")

    # Query as Tenant A
    await set_tenant_context(db_session, TENANT_A)
    clusters = await list_clusters(db_session)

    # Should only see Tenant A's cluster
    assert len(clusters) == 1
    assert clusters[0].label == "Alice"
```

### Unit Tests

**PHP (PHPUnit 10+):**

- Mock HTTP responses for external services
- Use WP_Mock for WordPress functions
- Data providers for edge cases

**Frontend (Vitest + Testing Library):**

- Test behavior, not implementation
- Mock API with MSW (Mock Service Worker)
- Test loading, error, and success states
- Use RFC 2606 domains: `http://example.test`, not `http://localhost`

### Integration Tests

- Validate API contracts against JSON Schema fixtures in `docs/architecture/contracts/`
- Test authentication and authorization
- Test error responses and rate limiting

### E2E Tests (Playwright)

Test critical user flows:

- Workbench -> Generate alt text -> Review -> Approve
- Recognition flow -> Review matches -> Accept/reject
- Bulk operations with queue monitoring

### Accessibility Tests

- Run axe-core on every component
- Assert zero critical violations
- Test keyboard navigation explicitly
- Manual testing with screen readers

### Performance Targets

- Synchronous endpoints: < 150ms response time
- Frontend: Lighthouse score > 90
- Core Web Vitals: LCP < 2.5s, FID < 100ms, CLS < 0.1

---

## Security Patterns

### WordPress Security

```php
// Always verify nonces for mutations
if (!wp_verify_nonce($_POST['_wpnonce'], 'acx_action')) {
    wp_die('Security check failed');
}

// Check capabilities via centralized helper
if (!Security::can_generate_alt_text()) {
    return new WP_Error('forbidden', 'Insufficient permissions', ['status' => 403]);
}

// Escape output
echo esc_html($user_input);
echo esc_url($url);
echo esc_attr($attribute);

// Sanitize input
$clean = sanitize_text_field($_POST['input']);
$clean_array = array_map('absint', $_POST['ids']);
```

### API Security

- Tenant isolation: always scope queries by tenant_id
- Input validation: reject malformed requests early
- Rate limiting: protect against abuse
- Audit logging: log security-relevant actions

---

## Code Style

### Package Management

- **npm** for Node.js (not pnpm)
- **Composer** for PHP

### Formatting

- 4-space indentation (PHP, TypeScript, SCSS)
- 2-space indentation (JSON, YAML, Markdown)
- Prettier for auto-formatting (frontend)
- PHP_CodeSniffer for PHP

### TypeScript

- `strict: true` in tsconfig
- Arrow functions for components and utilities
- Function expressions: `export const Component = () => {}`
- No `any` types without documented justification

### Python

- Type hints on all functions
- Google-style docstrings
- 120 character line length
- `ruff format` for formatting (replaces black)
- `ruff check` for linting with `I` rule (replaces isort)
- Double quotes for strings
- 4-space indentation

### Pre-commit Checks

```text
1. Prettier formatting
2. ESLint with TypeScript rules
3. PHP_CodeSniffer
4. PHPStan static analysis
5. TypeScript type checking
6. Unit tests for changed files
7. Commit message linting
```

---

## Documentation Standards

### File Organization

- Architecture docs in `docs/architecture/`
- Task breakdowns in `docs/tasks/{version}/`
- Roadmaps in `docs/roadmaps/`

### Mermaid Diagrams

- **`.mmd` files: raw Mermaid syntax only — NO code fences (` ```mermaid `)** — fencing breaks rendering
- `.md` files: use fenced code blocks (these render correctly when embedded)
- Maximum 12 classes per diagram
- Use language-agnostic types: `string`, `int`, `bool`, `array<T>`

### ASCII Only

Use ASCII characters only in documentation:

- `[x]` instead of checkmark emoji
- `[ ]` instead of X emoji
- `WARNING` instead of warning emoji
- `->` instead of arrow emoji

Rationale: Emoji cause encoding issues across terminals and CI systems.

### Internationalization

- All user-facing strings through `__()`, `_x()`, `_n()`
- Text domain: `alt-context`
- Use `sprintf()` for interpolation with translator comments

---

## Quick Reference

### Common Commands

```bash
# Frontend
npm run dev          # Start Vite dev server
npm run build        # Production build
npm run test         # Run Vitest
npm run lint         # ESLint + type check

# Backend (Python) - run from apps/prototype-description-service/
pyenv shell description-service  # Activate virtualenv
pytest                           # Run tests
mypy .                           # Type checking
ruff check .                     # Linting (replaces flake8)
ruff format .                    # Formatting (replaces black)
ruff check --fix .               # Auto-fix linting issues

# PHP
composer test        # PHPUnit
composer phpstan     # Static analysis
composer phpcs       # Code style
```

### Key Files

| Purpose         | Location                                              |
| --------------- | ----------------------------------------------------- |
| Roadmap         | `docs/roadmaps/roadmap-v3.hybrid.md`                  |
| API Contracts   | `docs/architecture/contracts/`                        |
| Component Guide | `docs/architecture/rules/RADIX_UI_COMPONENT_GUIDE.md` |
| Backend UML     | `docs/architecture/backend-uml/`                      |
| Frontend UML    | `docs/architecture/frontend-uml/`                     |

### Getting Help

1. Check the roadmap for context on current work
2. Review existing patterns in the codebase
3. Consult architecture docs for design decisions
4. Ask for clarification before making assumptions
