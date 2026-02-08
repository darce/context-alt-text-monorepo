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

> [!IMPORTANT]
> This is a **greenfield project** with NO production users and NO existing data that must be preserved.

- **No Data Migrations**: Storage surfaces (database tables, options, caches) are disposable.
- **Baseline Only**: All schema changes must be applied directly to the baseline migration file ([001_identity_schema.py](file:///Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/db/migrations/versions/001_identity_schema.py)).
- **Clean Rewrites**: Prefer clean rewrites of logic and schema over backward-compatibility shims.
- **No Feature Flags**: Full latitude to delete experimental features. Prefer removal over long-lived feature flags.

### Remove Over Flag

Delete-over-flag is the default. Re-introduce features behind tests only when truly needed.

### Consolidated Checklists in Task Documents

All task/planning documents MUST consolidate checklists at the **bottom** of the document.

**Why:**

- Prevents checklist sprawl across sections
- Single source of truth for progress tracking
- Easier to scan completion status
- Agents can read checklist state without parsing entire document

**Structure:**

```markdown
# Task Document Title

## Problem Statement

(narrative content)

## Proposed Solution

(narrative content, code examples, diagrams)

## Related Files

(reference table)

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [ ] Scaffold item 1
- [ ] Scaffold item 2

## Phase N: [Description]

- [ ] Task 1
- [ ] Task 2

## Success Criteria

- [ ] Criterion 1
- [ ] Criterion 2
```

**Do NOT include time estimates** on phases. They are difficult to calculate accurately and add no value to implementation.

**Enforcement:** Do not scatter `- [ ]` items throughout narrative sections. Move all to consolidated checklist.

### Naming Convention: acx\_\* Prefix

> [!WARNING]
> The `cat_*` prefix (e.g., `cat_roster_entries`, `wp cat-roster`) is **legacy** from a previous implementation.
>
> Current prefixes are:
>
> - **WordPress options/meta**: `acx_*` (e.g., `acx_roster_entries`)
> - **REST API namespace**: `acx/v1/`
> - **PHP namespace**: `AltContext\`
> - **Text domain / slug**: `alt-context`
>
> If you encounter `cat_*` references in documentation, they may be outdated.

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
- **Verify scaffolds compile/type-check** before moving to implementation
- Test scaffolding is required first: create test files, fixtures, and failing test stubs before any implementation

**This applies to ALL new code**:

- Backend: Python functions, classes, methods
- Frontend: TypeScript functions, React components, hooks
- Tests: Test function signatures and fixtures
- Cross-layer contracts: Define API schemas in `docs/agentic/contracts/` before implementing endpoints

**Why scaffolding first? (Agentic Coding Rationale)**

| Benefit                        | Why It Matters for Agents                                                                                                                        |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Prevents context rot**       | Agent context windows are finite. Scaffolding while problem is fresh ensures contracts are defined before 50+ implementation files dilute focus. |
| **Cheap reversibility**        | Changing a signature costs ~10 tokens; changing an implementation costs ~500. Get the API right first.                                           |
| **Token-efficient references** | Agents can reference `ClusterService.merge()` signature without re-reading 200-line implementation.                                              |
| **Parallel work enablement**   | Human can review API design in PR while agent implements. Multiple agents can work on different implementations once interfaces exist.           |
| **Incremental verification**   | `mypy`/`tsc` on scaffolds catches type mismatches before implementation obscures them.                                                           |
| **Cross-layer contracts**      | In monorepos (PHP↔Python↔TS), scaffolding both sides of an API boundary prevents integration drift.                                              |

**Scaffolding Checklist (Definition of Done)**

A scaffold is complete when:

- [ ] All public function/method signatures exist with full type hints
- [ ] Docstrings describe Args, Returns, Raises (no implementation details)
- [ ] Bodies contain only `raise NotImplementedError("TODO: <specific task>")`
- [ ] `PYENV_VERSION=description-service mypy .` from `apps/prototype-description-service/` (or `PYENV_VERSION=description-service mypy --config-file apps/prototype-description-service/pyproject.toml apps/prototype-description-service` from repo root) or `npm run type-check` (TS) passes with zero errors
- [ ] Test file exists with `@pytest.mark.skip("scaffold")` or `it.todo()` stubs
- [ ] Cross-layer contracts (if any) are documented in `docs/agentic/contracts/`

**Enforcement**: Task checklists MUST include a "Phase 0: Scaffolding" section that is completed and verified before implementation phases begin.

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

### Curation-First Precedence

**User curation decisions are ground truth. Never use time-based heuristics to override them.**

- A user's rejection, acceptance, or label is curated ground truth — the backend must not autonomously reverse it.
- Do not use time-based cooldowns, expiry windows, or TTLs to gate re-evaluation of curated state. Time assumes constant usage cadence, which cannot be guaranteed — users engage in bursts separated by weeks or months.
- The correct gate is always a **data delta**: did the underlying evidence (representative set, embeddings, cluster composition) change since the user's decision? If yes → surface as a new proposal. If no → respect the decision indefinitely.
- When re-surfacing after changed evidence, create a **new record** (not mutate the original). The user's prior decision must remain visible in the audit trail.
- Avoid adding settings fields for time-based gates. They consume cognitive space for a trivial decision with no correct universal default.

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

### Hook Architecture Anti-Patterns

```tsx
// BAD: "God Hook" (>150 lines, multiple concerns)
const useEverything = () => {
  // Mutations, derived state, SSE tracking, status text, progress aggregation...
  const [state1, setState1] = useState();
  const [state2, setState2] = useState();
  // ... 20 more hooks
  return { mutation1, mutation2, phase, status, progress, isOnline, ... };
};

// GOOD: Compose focused hooks
const useScanMutation = (options) => useMutation({...});
const useJobPhase = (activeJobs) => useMemo(() => derivePhase(activeJobs), [activeJobs]);
const useStatusText = (phase, progress) => useMemo(() => formatStatus(phase, progress), [phase, progress]);

const useJobStateMachine = () => {
  const scan = useScanMutation();
  const phase = useJobPhase(scan.activeJobs);
  const status = useStatusText(phase, scan.progress);
  return { scan: scan.mutate, phase, status };
};
```

**Signs of a God Hook:**

- More than 150 lines
- More than 5 `useState` calls
- More than 3 `useEffect` calls
- Returns more than 8 values
- Mixes mutation orchestration with derived state

**Refactoring strategy:**

1. Extract each `useMemo` into a focused hook
2. Group related mutations into a single hook
3. Keep the "orchestration" hook thin (compose, don't implement)

### Data Fetching

Use React Query for all API calls:

```tsx
const { data, isLoading, error, refetch } = useQuery({
  queryKey: ["clusters", tenantId],
  queryFn: () => fetchClusters(tenantId),
  staleTime: 60_000,
});
```

### TypeScript Safety Rules (Lessons Learned)

> These rules were distilled from the 4.12.0 branch audit.

1. **No non-null assertions (`!`) on API data.** Fields typed `T | null | undefined` from an API response must be narrowed with a guard, not suppressed with `!`. Use a local const and an `if` check.

   ```tsx
   // BAD
   <Img src={item.url!} />

   // GOOD
   const url = item.url;
   if (url) { <Img src={url} /> }
   ```

2. **No `undefined as T` or `x as T` for API return types.** If `fetchApi` can return `undefined` (204, empty body), the return type must be `Promise<T | undefined>`. Casting `undefined as T` gives callers a lie.

3. **Centralize query keys.** All React Query keys must go through a `queryKeys` factory. Ad-hoc `['resource', id]` arrays create stale-data risk when other components invalidate via the factory but miss the ad-hoc key.

4. **No inline styles for layout.** If a grid/flex pattern is used more than once, it belongs in a SCSS class. Inline `style={{ display: 'grid', ... }}` objects are not reusable, not inspectable in DevTools by class name, and duplicate easily.

5. **No `!important` in SCSS.** Increase selector specificity instead (nest under a root `.acx-` container). WordPress admin styles have high specificity, but `!important` creates an arms race.

6. **Use design tokens for colors.** Hex literals (`#fef2f2`) must be CSS custom properties (`var(--acx-color-error-bg)`). Magic colors diverge silently across components.

7. **API calls go through the API module.** Components must not import `fetchApi` directly and build URLs with string interpolation. All API calls should go through a dedicated function in the relevant API module (e.g., `clusterApi.ts`) for mockability and consistency.

8. **Use `URLSearchParams` for query strings.** String interpolation (`` `?limit=${n}&tenant_id=${id}` ``) fails on special characters. Use `new URLSearchParams({ limit: String(n), tenant_id: id })` instead.

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
- **Always sanitize superglobal access** — use `sanitize_key()`, `sanitize_text_field()`, or `absint()` on `$_GET`/`$_POST`/`$_REQUEST` even when comparing against allowlists
- **One transport per parameter** — do not send the same value (e.g., `tenant_id`) in both the POST body and query params; pick one per your API contract

**REST API:**

- Routes registered under `acx/v1/` namespace
- Return WP_REST_Response with appropriate status codes
- Include helpful error messages with WP_Error codes

### Recognition Service (Python/FastAPI)

**Environment Setup:**

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

**Architecture:**

- Hexagonal boundaries: adapters separate from domain logic
- Domain logic in `recognition/domain/`
- Application layer in `recognition/application/`
- Infrastructure adapters in `recognition/infrastructure/`
- Interface adapters (HTTP) in `recognition/interface_adapters/`
- Services orchestrate domain operations

**Hexagonal Layer Rules (Lessons Learned):**

> These rules were distilled from the 4.12.0 branch audit. Violating them creates coupling, suppresses errors, and defeats type safety.

1. **No raw SQL in the application layer.** Use `text()` / raw queries only in `infrastructure/repositories/`. The application layer must call repository methods.
2. **No `contextlib.suppress(Exception)`.** Bare suppression hides real bugs. Catch specific exceptions and log at `WARNING` level at minimum.
3. **No `getattr()` duck-typing on service protocols.** If a method is used at a call site, declare it on the Protocol interface. Never use `getattr(service, "method_name", None)` + `callable()` guards — this defeats mypy entirely.
4. **No presentation DTOs in the domain or application layer.** Types shaped for API responses (`FaceBox`, `SuggestionDetails`) belong in `interface_adapters/http/schemas/`. Neither `domain/` nor `application/` should import or return them. Application services must return domain types; the interface adapter maps to DTOs at the HTTP boundary.
5. **No `object` parameters.** Use the domain type or a Protocol. `getattr(cluster, "label", None)` silently returns `None` on typos.
6. **No default-instantiating settings.** `ClusteringSettings()` inside a function bypasses DI. Always inject settings as a parameter.
7. **Escape LIKE wildcards.** Any user-supplied string used in `ilike()` must escape `%` and `_` before interpolation.
8. **Migration ↔ model parity.** After any schema change, verify the migration and ORM model define identical constraints. Run `alembic check` to detect drift.
9. **No duplicate definitions.** Exceptions, constants, and helpers must have exactly one canonical location. Cross-layer duplication (e.g., `ClusterNotFoundError` in both domain and application) causes import confusion.
10. **Extract shared repository utilities.** UUID coercion, media-identity bootstrap, and similar boilerplate must live in a shared module (e.g., `infrastructure/repositories/_helpers.py`), not be copy-pasted across repository files.
11. **Scope `except` clauses to the exact operation they guard.** A broad `except ValueError` (or any typed catch) that wraps an entire method body will catch unrelated errors from downstream calls — turning real bugs into silent "not found" responses. Wrap only the single call you intend to guard and let other exceptions propagate. *Discovered when `reject()` caught a `ValueError` from an incomplete enum in `_to_domain()` because the `except` wrapped `update_status()`, `create_cannot_link()`, and `add_block()` together.*
12. **No redundant router/dependency wiring.** When a parent router already `include_router`s its sub-routers, do not also register those sub-routers individually on the app. Duplicate registration multiplies endpoint handlers (3× in the suggestion case), wastes memory, and produces confusing `/docs` output. Audit `include_router` calls to ensure every router is registered exactly once.

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
PYENV_VERSION=description-service mypy .  # Type checking (run from apps/prototype-description-service/)
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

**Database Shell:**

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

## MCP/LSP Tooling for Agents

> [!IMPORTANT]
> **Agents MUST use MCP tools** when available for code intelligence tasks. This includes searching code, finding definitions, tracing API endpoints, and getting diagnostics. Direct grep/file reading should only be used when MCP is unavailable.

This monorepo includes a unified MCP (Model Context Protocol) server that provides code intelligence tools for agents working across all parts of the codebase.

### Quick Start

```bash
# From monorepo root - start the unified MCP server
~/.pyenv/versions/description-service/bin/python scripts/mcp/unified_server.py
```

### Client Support and Fallbacks

MCP tools require an MCP-capable client (e.g., Gemini for VS Code). GitHub Copilot MCP support is
version/feature-flag dependent; if `mcp.servers` is shown as an unknown setting, MCP is not enabled for
your Copilot build and MCP tools are unavailable there. When MCP is unavailable, use `.agent/workflows/`
as manual runbooks and direct shell commands (rg, make targets, etc.). When MCP is available, use MCP
tools for code intelligence tasks.

#### MCP Availability Checklist

MCP is available only when **all** of the following are true:

- An MCP-capable client is in use with MCP enabled (e.g., Gemini for VS Code).
- The unified MCP server is running locally.
- The client can access the server process (local permissions/path).
- The workspace is the same repo root as the server `cwd`.

If any of these are false (e.g., Copilot, Codex CLI, or no server running), MCP tools are unavailable.

### Installation

**Backend (Python):**

```bash
cd apps/prototype-description-service
make setup  # Installs fastmcp + all dependencies
```

**Frontend (TypeScript):**

```bash
cd apps/prototype-wp-alt-context
npm install  # Includes TypeScript LSP dependencies
```

**PHP:** No additional installation required. The unified MCP server uses ripgrep and PHPStan (already in composer dependencies).

### Available MCP Tools (18 total)

Tools are prefixed with `mcp_context-alt-t_` when invoked by agents.

| Category        | Tool                   | Args                                      | When to Use                                   |
| --------------- | ---------------------- | ----------------------------------------- | --------------------------------------------- |
| **Search**      | `search_code`          | `query`, `language?`, `path?`             | Find code patterns across monorepo            |
|                 | `find_definition`      | `symbol`, `language?`                     | Locate symbol definitions                     |
|                 | `semantic_search`      | `query`, `language?`, `limit?`            | Natural language search (keyword fallback)    |
| **Navigation**  | `read_file`            | `file_path`, `start_line?`, `end_line?`   | Read file with line numbers                   |
|                 | `list_directory`       | `dir_path?`                               | Browse directory structure                    |
| **Context**     | `get_context_map`      | `domain`                                  | Load backend/frontend/php/integration context |
|                 | `get_api_contract`     | `contract_name?`                          | Load API contract (default: clustering-api)   |
|                 | `get_instructions`     | (none)                                    | Load engineering instructions                 |
| **Cross-Layer** | `trace_api_endpoint`   | `endpoint`                                | Trace endpoint across PHP→Python→TS           |
| **Diagnostics** | `get_diagnostics`      | `file_path`                               | Run ruff/eslint/phpstan on file               |
|                 | `get_type_info`        | `file_path`, `line`, `character`, `lang?` | Get type info via Pyright/tsc                 |
| **React/TS**    | `find_react_component` | `component_name`                          | Find React component definitions              |
|                 | `find_react_hook`      | `hook_name`                               | Find custom React hooks                       |
|                 | `list_frontend_tests`  | `component?`                              | List test files by component                  |
| **PHP/WP**      | `find_wp_action`       | `action_name`                             | Find add_action/do_action calls               |
|                 | `find_wp_rest_route`   | `route`                                   | Find register_rest_route calls                |
|                 | `find_php_class`       | `class_name`                              | Find PHP class definitions                    |
| **Debug**       | `debug_subprocess`     | (none)                                    | Test subprocess timing                        |

**Example usage in agent context:**

```
# Search for ClusterService in Python files
mcp_context-alt-t_search_code(query="ClusterService", language="python")

# Trace an API endpoint across all layers
mcp_context-alt-t_trace_api_endpoint(endpoint="/clusters")

# Get diagnostics for a file
mcp_context-alt-t_get_diagnostics(file_path="apps/prototype-description-service/api/main.py")
```

### Optional MCP Servers

- **Pylance MCP**: Not required for this repo. The unified MCP server already provides Python type info via Pyright/tsc. Use Pylance locally for editor features, but it does not add MCP-only capabilities here.
- **Prisma MCP**: Only useful if the codebase uses Prisma (`schema.prisma`). This monorepo does not, so Prisma MCP is not recommended.

### Slash Commands (Workflows)

Agents can use slash commands defined in `.agent/workflows/` to execute standardized multi-step workflows. These optimize token usage by encoding common operations.

| Command             | Description                            |
| ------------------- | -------------------------------------- |
| `/context-backend`  | Load backend Python context            |
| `/context-frontend` | Load frontend React/TS context         |
| `/test-unit`        | Run Python unit tests                  |
| `/test-integration` | Run integration tests (requires DB)    |
| `/lint`             | All linters (ruff/mypy/eslint/phpstan) |
| `/check-all`        | Full CI validation                     |
| `/scaffold`         | Create new service/component skeleton  |
| `/api-trace`        | Trace endpoint across PHP→Python→TS    |
| `/db-reset`         | Reset dev database (DESTRUCTIVE)       |
| `/db-migrate`       | Run Alembic migrations                 |
| `/db-rollback`      | Rollback last migration                |
| `/db-query`         | Run ad-hoc SQL via `db_shell.sh`       |
| `/db-schema`        | Show database schema                   |
| `/git-status`       | Atomic commit suggestions by feature   |

### WordPress Development MCP

For WordPress plugin development, the following resources are available:

- **Automattic MCP Adapter**: [github.com/Automattic/wordpress-mcp](https://github.com/Automattic/wordpress-mcp) — Exposes WordPress REST API to AI agents
- **WP MCP Boilerplate**: For creating custom MCP tools that interact with WordPress functions
- **Abilities API**: WordPress.org plugin for defining custom AI-accessible abilities

Our unified MCP server includes PHP-specific tools (`find_wp_action`, `find_wp_rest_route`, `find_php_class`) that help navigate the WordPress plugin codebase without requiring a separate WordPress instance.

### Session State with CURRENT_TASK.md

For multi-session tasks, use a lightweight `CURRENT_TASK.md` file at the monorepo root to preserve context across agent sessions.

**When to use:**

- Tasks spanning multiple sessions (> 1 hour of work)
- Complex debugging where findings need to be preserved
- Multi-phase implementations with dependencies between phases
- When conversation summary alone isn't sufficient

**When NOT to use:**

- Single-session tasks that complete quickly
- Simple bug fixes or documentation updates
- Tasks fully tracked by a `docs/tasks/` plan document

**Workflow:**

1. Copy template: `cp docs/agentic/templates/CURRENT_TASK.template.md CURRENT_TASK.md`
2. Fill in objective, context, and initial task breakdown
3. Update progress at end of each session
4. Add session log entry with discoveries/blockers
5. Delete file when task is complete

**Template location:** [docs/agentic/templates/CURRENT_TASK.template.md](templates/CURRENT_TASK.template.md)

**Key sections:**

| Section | Purpose |
|---------|---------|
| **Objective** | 1-2 sentences so agent immediately knows the goal |
| **Progress** | Checkboxes with `← ACTIVE` marker on current item |
| **Key Files** | Table of relevant files with context-specific notes |
| **Verification Commands** | Copy-paste commands to check current state |
| **Next Agent Instructions** | Specific steps for the next session to pick up |
| **Session Log** | Append-only log of what each session discovered |

**Example usage:**

```markdown
## Progress

### Completed
- [x] Added batch fetch method to ClusterRepository
- [x] Unit tests passing

### In Progress
- [ ] Integration test with real database ← **ACTIVE**

### Remaining
- [ ] Frontend investigation if UI hang persists
```

> [!TIP]
> The `← ACTIVE` marker tells the next agent exactly where to resume without reading the entire file.

**Gitignore consideration:** Add `CURRENT_TASK.md` to `.gitignore` if you don't want task state in version control. For team visibility, commit it.

---

## Testing Standards

### Test Writing Rules (TDD Best Practices)

These rules ensure tests are deterministic, maintainable, and test behavior over implementation.

#### 1. Deterministic Data Over Randomness

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

#### 2. Explicit Synchronization Over Sleep

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

#### 3. Behavioral Assertions Over Call Counts

```python
# BAD: Brittle coupling to internal calls
mock_repo.recompute_centroid.assert_called_once()

# GOOD: Assert observable outcomes
assert cluster.identity_count == 5
assert cluster.centroid_updated_at > original_timestamp

# ACCEPTABLE: One or two critical side-effect assertions
mock_event_bus.emit.assert_called_with(ClusterMergedEvent(...))
```

#### 4. Import Settings, Don't Hardcode

```python
# BAD: Magic numbers that can diverge from production
assert result.threshold == 0.65

# GOOD: Reference the source of truth
from recognition.application.settings import ClusteringSettings

settings = ClusteringSettings()
assert result.threshold == settings.suggestion_floor
```

#### 5. Mock Async Side Effects in React Tests

```tsx
// BAD: Async updates after test ends cause act() warnings
// (polling hooks, query invalidations continue running)

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

#### 6. Light Integration Tests Validate Hook Wiring

```tsx
// Unit tests mock hooks heavily, which can mask wiring bugs.
// Add one "integration-lite" test per major page that uses real hooks
// with mocked network calls.

describe("WorkbenchPage (integration-lite)", () => {
  // Mock network, not hooks
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

#### 7. Exact Assertions in Integration Tests

```python
# BAD: Broad assertions allow regressions
assert clusters_created >= 1

# GOOD: Use deterministic fixtures for exact counts
# (with fixed embeddings, cluster count is predictable)
assert clusters_created == 3
```

#### 8. Test Mock Defaults Match Production Defaults

```python
# BAD: Mock returns different default than production
repo.get_curriculum_t = AsyncMock(return_value=0.0)  # Production default is 0.5!

# GOOD: Match production defaults explicitly
repo.get_curriculum_t = AsyncMock(return_value=0.5)  # Matches schema default
```

#### 9. No Permanently Skipped Tests

Tests marked `@pytest.mark.skip` or `it.skip()` without a linked issue or TODO date are dead code that creates false coverage confidence. Either:
- Remove the test (if the feature is abandoned)
- Complete the test (if the feature shipped)
- Add a comment with an issue reference and expected resolution (if blocked)

Empty test bodies (`pass`, `...`) that run green are worse — they inflate pass counts.

#### 10. Extract Shared Test Stubs

If a Protocol stub (e.g., `NullClusterRepository`) is copy-pasted across 3+ test files, extract it to a shared test utility module (`tests/fakes.py` or `tests/stubs.py`). Copy-pasted stubs drift when the Protocol changes, causing some tests to miss new required methods.

```python
# BAD: 100-line ClusterRepoStub defined independently in 4 test files
class ClusterRepoStub:
    async def get(self, id): return None
    async def save(self, c): pass
    # ... 20 more methods, copy-pasted

# GOOD: Shared null implementation
# tests/stubs.py
class NullClusterRepository:
    """No-op implementation of ClusterRepository for unit tests."""
    async def get(self, cluster_id): return None
    async def save(self, cluster): pass
    # full Protocol surface in one place
```

#### 11. One Canonical Fake Per Protocol

Do not maintain multiple divergent fake implementations of the same Protocol across test files. When three files each define their own `FakeClusterRepository` with different stored types and method sets, a Protocol change requires updates in all three places — and the divergence means they test subtly different contracts.

```python
# BAD: FakeClusterRepository defined in conftest.py, api/conftest.py, and fakes.py
# with different stored types (FakeClusterForRepo vs ClusterResponse vs _FakeClusterRecord)

# GOOD: One configurable fake in tests/fakes.py
class FakeClusterRepository:
    """Configurable fake for ClusterRepository protocol."""
    def __init__(self, clusters: list[IdentityCluster] | None = None):
        self._clusters = {c.id: c for c in (clusters or [])}
    async def get(self, cluster_id: str) -> IdentityCluster | None:
        return self._clusters.get(cluster_id)
```

The same applies to inline stubs repeated within a single test file — extract to a file-local fixture or `conftest.py` instead of redefining the class multiple times.

#### 12. No False-Positive Fakes

Test fakes that always return `None`/`0`/empty can make tests pass for the wrong reason. If a route checks `if cluster is None: return 404`, a fake that always returns `None` will always take the 404 path — the happy path is never tested.

Design fakes to be configurable:

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

#### 13. `QueryClient` Must Use `retry: false` in Tests

```tsx
// BAD: retry: 1 adds non-deterministic timing
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, retryDelay: 1 } },
});

// GOOD: Disable retries entirely
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});
```

Retries in tests cause flaky timing, extra network calls, and `act()` warnings from async updates after test teardown.

#### 14. Use One Injection Strategy Per Dependency

Do not use both `app.dependency_overrides[dep]` and `monkeypatch.setattr(module, "dep", ...)` for the same dependency. If the resolution path changes, one strategy silently becomes dead code. Pick one — prefer FastAPI's `dependency_overrides` for endpoint-injected deps.

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
- Use descriptive filenames for implementation plans and related docs (avoid generic names like `implementation-plan.md`; include the feature/context in the filename).

### Implementation Plan Requirements

All implementation plans in `docs/tasks/` MUST include:

1. **Problem Statement** — What user-visible behavior needs to change
2. **Current State Analysis** — What works, what's broken, what's missing
3. **Patterns to Follow** — Code snippets showing the pattern to implement
4. **Functions to Change** — Table with file paths, line numbers, and specific changes
5. **Related Files** — Complete list of files that will be touched
6. **Consolidated Task Checklist** — Phased checkboxes with time estimates:
   - `### Completed` — Already done items
   - `### Phase N: Description (~X min)` — Grouped by logical phase
   - `### Stretch Goals` — Nice-to-haves that won't block completion

**Example structure:**

````markdown
## Patterns to Follow

### Backend: Repository Method Pattern

```python
# 1. Add method to Protocol
# 2. Implement in SqlAlchemy adapter
# 3. Add to Fake for tests
```
````

## Functions to Change

| File                                 | Line | Change                         |
| ------------------------------------ | ---- | ------------------------------ |
| `recognition/domain/repositories.py` | -    | Add `new_method()` to Protocol |
| `recognition/infrastructure/...`     | ~50  | Implement `new_method()`       |

## Consolidated Task Checklist

### Completed

- [x] Analyze current state

### Phase 1: Scaffolding (~10 min)

- [ ] Add method signature to Protocol
- [ ] Add NotImplementedError stub

### Phase 2: Implementation (~20 min)

- [ ] Implement SqlAlchemy version
- [ ] Implement Fake version

### Phase 3: Tests (~15 min)

- [ ] Unit test for happy path
- [ ] Unit test for edge cases

````

**Why this structure?**
- Enables incremental progress with clear checkpoints
- Supports handoff between sessions
- Makes time estimates visible for planning
- Separates "must do" from "nice to have"

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
PYENV_VERSION=description-service mypy .  # Type checking (run from apps/prototype-description-service/)
ruff check .                     # Linting (replaces flake8)
ruff format .                    # Formatting (replaces black)
ruff check --fix .               # Auto-fix linting issues

# PHP
composer test        # PHPUnit
composer phpstan     # Static analysis
composer phpcs       # Code style
````

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
