# Development Instructions

The goal is to build and evolve a maintainable, readable, testable WordPress plugin (Context Alt Text) using strict Test‑Driven and incremental architecture practices aligned with the roadmap (`docs/architecture/rules/roadmap-v3.md`).

## Monorepo Layout

- `context-alt-text/` — WordPress plugin + MCP adapter (frontend delivery surface)
- `__hugging-face/entity-identifier-api/` — Hugging Face Spaces recognition + roster API (backend service)
- `docs/architecture/` — shared planning rules, roadmaps, UML diagrams, and research prompts

All architectural decisions, contracts, and diagrams land in `docs/architecture` first to keep frontend and backend contributions in sync.

## Core Engineering Principles

> Current Distribution Status
>
> There is **no existing public install base or previously shipped version** of this plugin. That means we have full latitude to *delete or aggressively refactor unshipped / experimental features* instead of carrying legacy flags or migration shims. If a capability (e.g., local face tagging, discovery scans) is not needed for the presently validated roadmap slice, remove it cleanly and re‑introduce later behind tests when truly required. Prefer removal over long‑lived feature flags unless a near‑term reinstatement is already scheduled.

1. TDD Always: Red → Green → Refactor for every meaningful change (PHP + JS/TS. TS for all newly generated browser code).
2. Small Vertical Slices: Implement only the minimum portion of an epic needed to make the current failing (or newly added) test pass.
3. Explicit Interfaces: Introduce interfaces/abstractions (providers, services) before integrating remote or hard-to-mock concerns.
4. Deterministic Tests: No network calls, random, or time-based flakiness without controlled seams/mocks.
5. Update the Model: UML + roadmap status tags must reflect reality immediately after a slice merges.
6. Mirror Contracts: when one side updates DTOs or OpenAPI specs, update shared fixtures under `docs/architecture` and notify the counterpart team via the weekly integration check-in.

**Accuracy & Metrics**

- Never fabricate benchmark numbers, latency claims, or accuracy metrics. Document the collection method and timestamp in commit messages or accompanying docs when sharing measurements.
- All public reports or markdown summaries produced from scripts must source their values directly from the most recent benchmark run.

## Context Alt Text — Abilities + MCP Adapter Integration Guide (macOS + LocalWP)

This repo follows the **WordPress AI Building Blocks**:

- **Abilities API** → declare what this plugin can do (schemas, permissions, execute callbacks)
- **MCP Adapter** → exposes those abilities as MCP tools over **Streamable HTTP** and **REST**
- **PHP AI Client SDK** → provider-agnostic LLM/SLM access for captioning, embeddings
- **WordPress REST API** → canonical transport for admin surfaces; all SPA data flows through REST routes (registered under `context-alt-text/v1/**`) and localized boot payloads.

## 1) Local Setup (LocalWP)

```bash
# Inside the LocalWP site shell
wp plugin install https://github.com/WordPress/abilities-api/releases/latest/download/abilities-api.zip --activate
wp plugin install https://github.com/WordPress/mcp-adapter/releases/latest/download/mcp-adapter.zip --activate
```

Then activate Context Alt Text (this plugin). MCP endpoints (Streamable HTTP) will be under:
http://<local-domain>/wp-json/<your-namespace>/server/streamable.

## Standard Slice Checklist

1. Identify roadmap epic + sub-capability you are advancing.
2. Add/adjust a failing test describing the desired behavior (PHPUnit; Vitest/RTL for UI; contract tests for remote schemas).
3. If remote dependency is involved, add/refine a provider interface + mock implementation.
4. Implement the minimal production code to pass tests.
5. Refactor for clarity and duplication removal while tests stay green.
6. Update UML (Mermaid) and roadmap status tags, ensuring every diagram renders without syntax errors.
7. Security & A11y pass: nonce/cap checks; escape + sanitize; keyboard/ARIA (when UI slice).
8. Do **not** stage or commit files until the feature slice is fully implemented, reviewed locally, and all relevant tests pass—use the worktree for WIP only.
9. Commit with Conventional Commits (e.g., feat(abilities): add cat/generate_alt_text). Use feat only when the slice is functionally complete.
10. All user-visible strings follow WordPress i18n patterns.
11. UI changes must meet WCAG 2.1 AA.

### Frontend SPA Engineering Principles

1. Build every admin SPA slice from small, composable components. Favor composition over inheritance; resist copy/paste UI.
2. Centralize shared UI primitives (buttons, cards, charts) and reuse them aggressively; new views assemble existing pieces before introducing bespoke variants.
3. Prefer declarative data hooks and derived state; only add `useEffect` when responding to external side-effects (subscriptions, imperative APIs). No `useEffect` purely to sync props → state.
4. Component state flows top-down; use context sparingly, and only for cross-cutting concerns (theme, router, notifications).
5. Co-locate styling with components (CSS modules, CSS-in-JS, or SCSS) while keeping tokens in a shared design file.
6. Storybook (or similar component workbench) is recommended. It accelerates developing reusable primitives, documents UX contracts, and provides visual regression targets—schedule adoption alongside the first React dashboard slice.
7. The Vite dev server URL comes from `.env` (`CAT_VITE_DEV_SERVER`) so local, tunnelled, or containerised setups can override `localhost:5173` without code changes.
8. All front-end code is authored in TypeScript (`.ts/.tsx`) with strict compiler settings; no new plain JavaScript modules without explicit architectural approval.
9. Use 4 spaces for indentation across frontend TypeScript/SCSS files; tabs or alternative spacing styles are not permitted.
10. Prefer arrow functions for all frontend JavaScript/TypeScript modules (components, hooks, utilities) to keep the style consistent.
11. Alternative front-end runtimes (Svelte, Ripple, etc.) were evaluated: React remains the default because it aligns with WordPress’ Gutenberg ecosystem, existing WP packages (`@wordpress/components`, data), and team familiarity. Revisit only if performance profiling shows React/SPAs cannot meet targets.

## Roadmap Usage & Status Tagging

Each epic in `roadmap-v3.md` is authoritative for scope. Maintain lightweight progress tags inline:

```text
[DONE] – user-visible + tests + docs
[PARTIAL] – some endpoints/flows; more slices planned
[PLANNED] – no implementation yet
[BLOCKED:<reason>] – awaiting dependency (brief reason)

```

Example:
`### Epic C — Recognition Pipeline [PARTIAL]`

Never claim [DONE] until:

- All acceptance bullets are covered by tests (or documented exceptions),
- UML participants for the epic are updated,
- Security + performance acceptance notes are satisfied.

## UML Diagram Guidelines

Location:

- Backend: `docs/architecture/backend-uml/` (Mermaid `.md`/`.mermaid` or fenced code blocks)
- Frontend: `docs/architecture/frontend-uml/`
- Systems: `docs/architecture/backend-uml/unified_architecture.mermaid` (source diagram for end-to-end flows)

Conventions:

- Use language‑agnostic primitive types (`string`, `int`, `float`, `bool`, `array<T>`, `Map<K,V>`).
- Sequence diagrams for flows (face tagging, generation jobs).
- Class diagrams only for stable domain surfaces (Roster, FaceCache, GenerationJob). Avoid premature micro-classes.
- Update only changed fragments; keep earlier diagrams (version by filename suffix if a major structural shift occurs).

Quality Heuristics:

- Max 12 classes per diagram (split if larger).
- Show only public methods; internal helpers omitted unless clarifying domain invariants.
- Add brief legends when using stereotypes (e.g., «provider», «entity»).

## Abilities Conventions

1. Naming (prefix with cat/):

    - cat/generate_alt_text
    - cat/regenerate_alt_texts (batch)
    - cat/start_tagging_session
    - cat/persist_observations
    - cat/finalize_session
    - cat/create_roster_entry
    - cat/propagate
    - cat/first_run_scan (optional: discovery; legacy name cat/magic_import_scan)

2. Schemas:

    - Inputs/outputs MUST have JSON Schemas under /schemas, loaded at runtime.
    - Example enum: scope = "alt_text" | "people_tags".

3. Permissions:

    - Media library read/write; ability-specific caps registered at activation.

4. Error handling:

    - Provide actionable WP_Error codes; include HTTP status passthrough for remote failures.

## Providers & Mock Strategy

1. Abstractions (PHP):

    - `CaptionProviderInterface` → `generateCaption(ImageContext $ctx): CaptionResult`
    - `FaceRecognitionProviderInterface` → `embed(FaceCrop $crop): Embedding`, `match(Embedding $probe): MatchSet`

2. JS (Browser) Face Detection:

    - Local-only detector (TFJS / WASM) wrapped in `faceDetection.ts` exposing `detect(image: HTMLImageElement): DetectedBox[]`

3. Mock Implementations:

    - Deterministic outputs seeded by image hash or fixture ID.
    - Error simulation toggled via env var or test flag.

4. Test Layers:

    - Unit: provider mocks
    - Contract: real HTTP surfaced through a mock server (e.g., MSW / local PHP stub) asserting request/response schema
    - Integration (optional, manual): real remote model endpoints (skipped in CI)

## Testing Paradigm (TDD - 2025 Standards)

### 1. Unit Tests

**PHP (PHPUnit 10+)**:
- `AltTextService::composePrompt()` — golden snapshot tests
- `RecognitionClient` — mock HTTP; simulate 200/429/5xx; exponential backoff with jitter
- Repositories — stub WP functions (`WP_Mock`); zero hidden global state
- Data providers for edge cases (empty, null, malformed input)

**Frontend (Vitest + Testing Library)**:
- Component behavior tests — user interactions, not implementation
- Query by accessible roles: `getByRole('button')`, not `getByTestId()`
- Mock API responses with MSW (Mock Service Worker)
- Test loading states, error boundaries, suspense fallbacks
- Snapshot tests only for stable, non-dynamic output

### 2. Integration Tests

**API Contract Tests**:
- Call each ability via MCP REST and assert JSON shape + side effects
- Validate against JSON Schema fixtures in `docs/architecture/contracts/`
- Test authentication (valid/invalid nonces, capability checks)
- Test rate limiting and error responses

**Component Integration**:
- Mount full feature slices (e.g., Dashboard with real React Query)
- Test data fetching, caching, refetching, error recovery
- Verify optimistic updates and cache invalidation

### 3. Accessibility Tests (Required)

**Automated**:
- Run `axe-core` on every component in tests (`jest-axe`)
- Assert zero critical violations before merge
- Test keyboard navigation paths explicitly
- Verify ARIA attributes and screen reader announcements

**Manual**:
- Test with screen readers (NVDA, JAWS, VoiceOver)
- Verify focus management and skip links
- Test with keyboard only (no mouse)
- Check color contrast with DevTools

### 4. E2E Tests (Playwright)

**Critical User Flows**:
- First-run scan → Workbench → Generate alt text → Review → Approve
- Recognition flow → Review matches → Accept/reject
- Bulk operations → Queue monitoring → Error handling
- Settings changes → Data persistence → Effect on UI

**Test Matrix**:
- Browsers: Chromium, Firefox, WebKit
- Viewports: Mobile (375px), Tablet (768px), Desktop (1920px)
- Accessibility: Test with screen reader extensions

### 5. Performance Tests

**Frontend**:
- Lighthouse CI in PR checks (>90 performance score)
- Core Web Vitals: LCP <2.5s, FID <100ms, CLS <0.1
- Bundle size limits enforced in CI
- React Profiler for render performance

**Backend**:
- Response time <150ms for synchronous endpoints
- Database query monitoring (Query Monitor plugin)
- Memory profiling for bulk operations

### 6. Visual Regression Tests

**Storybook + Chromatic**:
- Snapshot every Storybook story
- Catch unintended visual changes in PR reviews
- Test responsive breakpoints and theme variations
- Archive visual history for documentation

### 7. CI Pipeline (GitHub Actions)

```yaml
1. Lint (PHP_CodeSniffer, ESLint, Prettier)
2. Type check (TypeScript strict mode)
3. Unit tests (PHPUnit + Vitest) with coverage reports
4. Integration tests (LocalWP + Playwright)
5. Accessibility audit (axe-core + pa11y)
6. Bundle size check (size-limit)
7. Lighthouse CI (performance budget)
8. Visual regression (Chromatic)
9. Coverage gate (90% threshold)
```

**Caching Strategy**:
- Cache Composer and npm dependencies
- Cache WordPress installation and plugins
- Cache test fixtures and screenshots
- Parallel test execution where possible

## Security & Capability Patterns

- Nonce required for state mutation (create/update/delete/bulk), named cat_{action} (placeholder).
- Centralize capability mapping in Security (e.g., can_generate_alt_text()); controllers shouldn’t inline current_user_can.
- Rate limiting via keyed transients cat_rate_limit_{scope}_{user}. Provide helpers to reset in tests.
- Escape, sanitize, and validate on all I/O boundaries.

## MCP Client Setup (Local)

- Streamable HTTP: `http://<local-domain>/wp-json/cat-mcp/server/streamable`
- VS Code `.vscode/mcp.json` with `Authorization: Basic <base64(user:app_pwd)>`.
- Use MCP Inspector to smoke-test `initialize`, `tools/list`, and each ability.

## Performance Guardrails

- Any synchronous controller path should complete < 150ms locally (excluding WP bootstrap). If risky, switch to a job pattern.
- Batch operations: chunk IDs (default 25) to protect memory; backoff on 429.
- Timeouts: AI 30–60s, Recognition 20–40s. Abort + surface partials.
- Refactoring Rules
- Allowed without new tests: purely internal renames, docblock improvements, dead code removal.
- Otherwise, write characterization tests first.

## Indexing & Discoverability of `docs/architecture`

1. Reference architecture docs explicitly from `README.md` with a short description of their purpose.
2. Add a `PROMPTS_INDEX.md` at repo root linking each architecture doc for tools that skip dot-folders.
3. CI doc check: fail if roadmap or instructions are missing mandatory sections.
4. Optionally mirror key architecture files into generated docs during build so external contributors can browse them easily.

## Code Style & Tooling (2025 Standards)

### PHP
- **PSR-12** coding standard via PHP_CodeSniffer
- **WordPress Coding Standards** (WPCS) enforced
- **PHP 8.1+** features: typed properties, named arguments, readonly properties
- **PHPStan level 8** for static analysis
- Docblocks on all public methods (PHPDoc 5.0 format)
- Domain exceptions caught at ability boundaries
- **Composer 2.6+** for dependency management

### TypeScript/JavaScript
- **TypeScript 5.3+** with `strict: true`, `noUncheckedIndexedAccess: true`
- **ESLint 9+** with TypeScript parser and React hooks plugin
- **Prettier 3+** for automatic formatting (enforced in pre-commit)
- **Functional components** with hooks (no class components)
- **Import sorting**: automatic via `eslint-plugin-import`
- **4-space indentation** (enforced by Prettier config)
- **Arrow functions** for consistency across all modules

### CSS/SCSS
- **SCSS** with shared design token files
- **CSS Modules** or scoped styles (no global CSS leaks)
- **PostCSS** for autoprefixing and modern CSS features
- **BEM naming** for utility classes (when not using modules)
- **Mobile-first** media queries
- **Container queries** for component-level responsiveness

### Tooling Stack
- **Vite 5+**: Build tool and dev server
- **Vitest**: Unit and component testing
- **Playwright**: E2E testing
- **Storybook 8+**: Component development and documentation
- **MSW 2+**: API mocking in tests and development
- **React Query 5+**: Data fetching and caching
- **Radix UI**: Accessible headless components
- **Husky**: Git hooks for pre-commit checks
- **lint-staged**: Run linters on staged files only

### Commits & Branching

- **Conventional Commits** (enforced by `commitlint`):
  - `feat(dashboard): add coverage trend sparkline`
  - `fix(workbench): correct filter reset behavior`
  - `docs(architecture): update face recognition flow diagram`
  - `test(coverage-card): add accessibility tests`
  - `refactor(api): simplify error handling pattern`
  - `chore(deps): update react-query to v5.18.0`
- **Semantic versioning**: Major.Minor.Patch based on commit types
- **Branch naming**: `feat/dashboard-cards`, `fix/alt-text-escaping`
- **PR labels**: Auto-generated from conventional commits
- **Roadmap sync**: Update epic status tags when PR merges

### Pre-commit Checks (Automated)

```bash
1. Prettier formatting (auto-fix)
2. ESLint (with auto-fix where possible)
3. PHP_CodeSniffer (WordPress CS)
4. PHPStan static analysis
5. TypeScript type checking
6. Unit tests for changed files
7. Commit message linting (commitlint)
```

### Editor Configuration (.editorconfig)

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

[*.{ts,tsx,js,jsx,css,scss}]
indent_style = space
indent_size = 4

[*.{json,yml,yaml,md}]
indent_style = space
indent_size = 2

[*.php]
indent_style = space
indent_size = 4
```

## Recognition Service (FastAPI) Guidelines

- **Hexagonal boundaries**: keep adapters in `analysis/adapters` or `recognition_core/adapters`, with pure orchestration in `analysis/services` and `recognition_core/domain`. Avoid importing archived modules or bypassing ports.
- **Python style**: every FastAPI path handler and service method must include type hints and either a Google-style docstring or inline comment that describes side effects. Target < 40 logical lines per function; decompose when flows grow larger.
- **Configuration**: read model paths, cache dirs, ports, and feature toggles from `pydantic` settings backed by environment variables. Hard-coded hostnames (e.g., `/Volumes/...`) are considered violations.
- **Failure on missing configuration**: services must fail fast when required settings are absent. Provide cache/model paths via `settings.yaml` (or explicit env vars) and avoid baking in fallbacks inside the codebase.
- **Static checks**: `flake8` and `mypy` must pass locally and in CI. Maintain ≥ 80% overall coverage, ≥ 95% on critical pipelines (recognition adapters, roster sync). Document justified exceptions.
- **Performance validation**: capture real latency metrics (cold vs warm) from benchmark scripts and store results under `reports/`. Include model, device, and timestamp metadata; do not extrapolate.
- **UML parity**: keep `docs/architecture/backend-uml/*.mermaid` synchronized with the active adapters, ports, and endpoints. Update diagrams when models or API shapes change.

## Suggested Layout

```text
context-alt-text/
    apps/
        wp-context-alt-text/
        recognition-service/
    packages/
        shared-contracts/
        wp-testing-helpers/
    docs/architecture/
        rules/
        backend-uml/
        frontend-uml/
    tools/
        scripts/
```

## Documentation Sources (use as supplemental guidance)

- WordPress Plugin Development Cookbook
- Professional WordPress Plugin Development
- Test-Driven Development with PHP 8

## Literature Digest:
- `docs/wp-plugin-literature-digest.md` Use it as a launch pad for best practices, coding recipes, and cross-references when implementing new slices of the plugin.
