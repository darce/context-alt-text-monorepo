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

### 2. Small Vertical Slices

Implement only the minimum needed to make the current test pass. Avoid speculative features.

### 3. Explicit Interfaces

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

### 4. Deterministic Tests

No network calls, randomness, or time-based logic without controlled seams/mocks. Tests must produce identical results on every run.

### 5. User Consent for Remote Operations

Never call remote recognition services or sync operations without explicit user action. Provide immediate feedback on success/failure.

### 6. No Fabricated Data

Never fabricate benchmark numbers, latency claims, or metrics. If data is unavailable, return an explicit empty state or error. Document measurement methods and timestamps.

---

## Development Workflow

### Slice Checklist

1. Identify the roadmap epic you are advancing
2. **Write failing tests first** (PHPUnit, Vitest, or integration)
3. If remote dependencies exist, add a provider interface + mock
4. Implement minimal production code to pass tests
5. Refactor for clarity while tests stay green
6. Update UML diagrams if architecture changed
7. Security pass: nonce/capability checks, escape/sanitize
8. Accessibility pass: keyboard navigation, ARIA labels
9. Run full test suite locally before committing
10. Commit with Conventional Commits format

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

**Architecture:**

- Hexagonal boundaries: adapters separate from domain logic
- Adapters in `recognition_core/adapters/`
- Domain logic in `recognition_core/domain/`
- Services orchestrate adapters

**Standards:**

- Type hints on all functions
- Google-style docstrings describing side effects
- Target < 40 lines per function
- `mypy` and `flake8` must pass

**Configuration:**

- All settings via pydantic Settings backed by environment variables
- No hard-coded paths or hostnames
- Fail fast on missing required configuration

**Coverage:**

- 80% overall minimum
- 95% on critical pipelines (recognition, clustering)

---

## Testing Standards

### Test Pyramid

```text
         /\
        /E2E\        <- Few, slow, high confidence
       /------\
      /Integr-\      <- Some, medium speed
     /--ation--\
    /------------\
   /    Unit      \  <- Many, fast, isolated
  /________________\
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
- `black` for formatting
- `isort` for import ordering

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

- `.mmd` files: raw Mermaid syntax only (no code fences)
- `.md` files: use fenced code blocks
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

# Backend (Python)
pytest               # Run tests
mypy .               # Type checking
flake8               # Linting

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
