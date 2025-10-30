# Development Instructions

The goal is to build and evolve a maintainable, readable, testable WordPress plugin (Context Alt Text) using strict Test‑Driven and incremental architecture practices aligned with the roadmap (`docs/architecture/rules/roadmap-v3.md`).

## Monorepo Layout

- `context-alt-text/` — WordPress plugin + MCP adapter (frontend delivery surface)
- `__hugging-face/entity-identifier-api/` — Hugging Face Spaces recognition + roster API (backend service)
- `docs/architecture/` — shared planning rules, roadmaps, UML diagrams, and research prompts

All architectural decisions, contracts, and diagrams land in `docs/architecture` first to keep frontend and backend contributions in sync.

## Core Engineering Principles

> Greenfield Reset Policy
>
> This plugin has no production footprint yet. Treat every storage surface (database tables, options, caches) as disposable while building V3. If a better schema or implementation emerges, prefer rewriting the tables and corresponding code over introducing migrations or backwards-compatibility shims. Recreate structures in-place during activation and keep the test suite in lockstep.

> Current Distribution Status
>
> There is **no existing public install base or previously shipped version** of this plugin. That means we have full latitude to _delete or aggressively refactor unshipped / experimental features_ instead of carrying legacy flags or migration shims. If a capability (e.g., local face tagging, discovery scans) is not needed for the presently validated roadmap slice, remove it cleanly and re‑introduce later behind tests when truly required. Prefer removal over long‑lived feature flags unless a near‑term reinstatement is already scheduled.

1. TDD Always: Red → Green → Refactor for every meaningful change (PHP + JS/TS. TS for all newly generated browser code). DO NOT write tests to verify you wrote the code that you wrote. Tests must ensure the roadmap acceptance criteria are met.
2. Small Vertical Slices: Implement only the minimum portion of an epic needed to make the current failing (or newly added) test pass.
3. Explicit Interfaces: Introduce interfaces/abstractions (providers, services) before integrating remote or hard-to-mock concerns.
4. Deterministic Tests: No network calls, random, or time-based flakiness without controlled seams/mocks.
5. Update the Model: UML + roadmap status tags must reflect reality immediately after a slice merges.
6. Mirror Contracts: when one side updates DTOs or OpenAPI specs, update shared fixtures under `docs/architecture` and notify the counterpart team via the weekly integration check-in.
7. **User Consent for Remote Resources**: Never use remote recognition services, embeddings, or roster sync operations without explicit user confirmation. All operations that modify remote FAISS indexes, sync embeddings, or trigger background processing must be initiated by user action (button click, confirmation dialog) and provide immediate feedback on success/failure.

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

> **MANDATORY**: Before implementing any new UI component, consult [Radix UI Component Development Guide](RADIX_UI_COMPONENT_GUIDE.md) to identify if a Radix UI primitive should be used instead of building custom. This guide provides instant access to pre-vetted, accessible component patterns and eliminates the need for deep analysis on each implementation.

1. Build every admin SPA slice from small, composable components. Favor composition over inheritance; resist copy/paste UI.
2. Centralize shared UI primitives (buttons, cards, charts) and reuse them aggressively; new views assemble existing pieces before introducing bespoke variants.
3. **Use Radix UI primitives for common patterns**: Select dropdowns, forms with validation, modals/dialogs, tooltips, and other standard UI components should use Radix UI primitives (see [RADIX_UI_COMPONENT_GUIDE.md](RADIX_UI_COMPONENT_GUIDE.md)). Custom implementations require architectural approval with documented justification.
4. Prefer declarative data hooks and derived state; only add `useEffect` when responding to external side-effects (subscriptions, imperative APIs). No `useEffect` purely to sync props → state.
5. Component state flows top-down; use context sparingly, and only for cross-cutting concerns (theme, router, notifications).
6. Co-locate styling with components (CSS modules, CSS-in-JS, or SCSS) while keeping tokens in a shared design file.
7. Storybook (or similar component workbench) is recommended. It accelerates developing reusable primitives, documents UX contracts, and provides visual regression targets—schedule adoption alongside the first React dashboard slice.
8. The Vite dev server URL comes from `.env` (`CAT_VITE_DEV_SERVER`) so local, tunnelled, or containerised setups can override `localhost:5173` without code changes.
9. All front-end code is authored in TypeScript (`.ts/.tsx`) with strict compiler settings; no new plain JavaScript modules without explicit architectural approval.
10. Use 4 spaces for indentation across frontend TypeScript/SCSS files; tabs or alternative spacing styles are not permitted.
11. Prefer arrow functions for all frontend JavaScript/TypeScript modules (components, hooks, utilities) to keep the style consistent.
12. Alternative front-end runtimes (Svelte, Ripple, etc.) were evaluated: React remains the default because it aligns with WordPress' Gutenberg ecosystem, existing WP packages (`@wordpress/components`, data), and team familiarity. Revisit only if performance profiling shows React/SPAs cannot meet targets.
13. Apply declared prop interfaces to the component signature; do not leave props types unused or fall back to implicit `any`/`unknown` when rendering React components.
14. Declare every new React component as a function expression (`export const Component = () => {}`); do not use function declarations (`export function Component() {}`).

### Frontend Component Architecture Rules (Enforced Limits)

These concrete limits prevent the accumulation of technical debt and ensure maintainable React code.

**📚 See Visual Examples:**

- [Component Architecture Patterns Guide](../frontend-uml/component-architecture-patterns.md) - Complete guide with code examples
- [Ideal Component Structure Diagram](../frontend-uml/ideal-component-structure.mmd) - Layered architecture visualization
- [RosterRoute Refactoring Roadmap](../frontend-uml/roster-route-refactoring-roadmap.mmd) - Concrete refactoring plan for violations
- [Anti-Patterns vs Ideal Patterns](../frontend-uml/anti-patterns-vs-ideal.mmd) - Side-by-side visual comparisons

#### Component Size Limits

- **Maximum 300 lines per component file** (including imports, types, styles)
  - If a component exceeds 250 lines, begin extracting sub-components or hooks
  - Route components (pages) may reach 400 lines if they orchestrate multiple features, but must still follow state/effect limits below
  - Violation examples: `RosterRoute.tsx` (2,543 lines ❌), `App.tsx` (563 lines ❌)

#### State Management Limits

- **Maximum 5 `useState` hooks per component**
  - 3-5 is acceptable for complex form/modal components
  - 6+ is a refactoring trigger: extract a custom hook or use `useReducer`
  - Related state should be grouped in a single `useState` object or migrated to `useReducer`
  - Violation example: `RosterRoute.tsx` has 14+ `useState` ❌
- **Maximum 3 `useEffect` hooks per component**
  - 0-1 is ideal (prefer derived state, event handlers, React Query)
  - 2-3 is acceptable for components with external dependencies (DOM APIs, subscriptions)
  - 4+ is a code smell: you're synchronizing too much state or mixing concerns
  - Violation example: `RosterRoute.tsx` has 6+ `useEffect` ❌

#### Component Extraction Triggers

Extract a new component when:

1. **JSX block exceeds 50 lines** (e.g., form sections, modals, table rows)
2. **Reusable UI pattern appears 2+ times** (DRY principle)
3. **Conditional rendering creates deep nesting** (more than 2 levels of ternaries)
4. **Component has more than 10 props** (likely doing too much)

Extract a custom hook when:

1. **Stateful logic is reused across 2+ components** (data fetching, form state, subscriptions)
2. **Complex state requires coordination** (multiple `useState` that change together → `useReducer`)
3. **Side effects need cleanup or synchronization** (WebSocket, intervals, ResizeObserver)
4. **Component has 6+ `useState` hooks** (group related state into a hook)

#### State Anti-Patterns to Avoid

1. **Don't mirror props in state** unless you explicitly need an "uncontrolled" initial value:

   ```tsx
   // ❌ BAD: Syncing prop → state
   const [value, setValue] = useState(initialValue);
   useEffect(() => setValue(initialValue), [initialValue]);

   // ✅ GOOD: Use prop directly or rename to clarify intent
   const [value, setValue] = useState(defaultValue); // only reads once
   ```

2. **Don't use `useState` for derived values**:

   ```tsx
   // ❌ BAD: Storing computed value in state
   const [filteredItems, setFilteredItems] = useState([]);
   useEffect(() => {
     setFilteredItems(items.filter((i) => i.active));
   }, [items]);

   // ✅ GOOD: Compute during render
   const filteredItems = useMemo(() => items.filter((i) => i.active), [items]);
   ```

3. **Don't use `useEffect` to chain state updates**:

   ```tsx
   // ❌ BAD: Waterfall effects
   useEffect(() => setB(a + 1), [a]);
   useEffect(() => setC(b * 2), [b]);

   // ✅ GOOD: Derive or handle in event
   const handleChange = (newA) => {
     setA(newA);
     const newB = newA + 1;
     setC(newB * 2);
   };
   ```

4. **Don't prop drill beyond 2 levels**:
   - If passing props through 3+ intermediate components, use context or composition
   - Consider "component composition" (children, render props) before adding context

#### Refactoring Priorities

When a component violates multiple limits:

1. **Extract data fetching** → Move to custom hooks or React Query
2. **Extract sub-components** → Split large JSX blocks into named components
3. **Consolidate state** → Related `useState` calls → `useReducer` or custom hook
4. **Eliminate unnecessary effects** → Replace with derived state, event handlers, or `useMemo`
5. **Extract business logic** → Move complex calculations to utility functions
6. **Split by responsibility** → Separate "smart" (data) from "dumb" (presentation) components

#### Visual References

See comprehensive examples and refactoring guidance in:

- **`docs/architecture/frontend-uml/component-architecture-patterns.md`** — Detailed anti-patterns vs ideal patterns with code examples
- **`docs/architecture/frontend-uml/ideal-component-structure.mmd`** — Reference architecture diagram
- **`docs/architecture/frontend-uml/roster-route-refactoring-roadmap.mmd`** — Step-by-step refactoring plan for RosterRoute (2,543 → 250 lines)
- **`docs/architecture/frontend-uml/anti-patterns-vs-ideal.mmd`** — Side-by-side visual comparison of violations vs solutions

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

**Syntax for `.mmd` files:**

- `.mmd` files should contain **raw Mermaid syntax only**, not wrapped in code fences
- Do NOT begin files with ` ```mermaid ` or ` ```mermaid.radar `
- Code fences cause syntax errors when tools try to render the diagrams
- Correct format: Start directly with diagram type (e.g., `graph TD`, `sequenceDiagram`, `flowchart LR`)
- Markdown files can still use fenced code blocks: ` ```mermaid ... ``` `

## Abilities Conventions

1. Naming (prefix with cat/):

   - cat/generate_alt_text
   - cat/regenerate_alt_texts (batch)
   - cat/start_tagging_session
   - cat/persist_observations
   - cat/finalize_session
   - cat/create_roster_entry
   - cat/propagate
   - cat/scan_faces (face detection and clustering)
   - cat/cluster_faces (manual clustering trigger)
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
- **Use RFC 2606 reserved test domains**: Always use `http://example.test` or `https://example.com` for mock URLs in tests. Never use `http://localhost` as it can be confused with real local servers and may cause port conflicts. Reserved test domains clearly signal "this is a test" and will never resolve to real addresses.

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

- Nonce required for state mutation (create/update/delete/bulk), named cat\_{action} (placeholder).
- Centralize capability mapping in Security (e.g., can_generate_alt_text()); controllers shouldn’t inline current_user_can.
- Rate limiting via keyed transients cat*rate_limit*{scope}\_{user}. Provide helpers to reset in tests.
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

### Package Management

- Use `npm` for all Node-based tooling in this repository. `pnpm` is not installed or supported—pnpm commands will fail and should not be used.
- PHP dependencies continue to use Composer as described below.

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
- `npm run lint` enforces the TypeScript-first policy; ESLint blocks new `.js/.jsx` files inside `apps/wp-context-alt-text/js/`. Request architectural approval before adding exceptions and migrate legacy JavaScript modules to TypeScript when they are next touched.

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

### Internationalization Requirements

- All UI- or user-facing strings must pass through localized translation helpers (`__`, `_x`, `_n`, etc.) with the `context-alt-text` domain across PHP and TypeScript.
- Favor translation-ready string interpolation (e.g., `sprintf`) with translator comments instead of concatenation.
- Backend responses surfaced to administrators and structured logs intended for UI display must use translatable strings or map to localization-ready codes.
- Tests that assert on copy or aria labels should reference the translated helpers to remain resilient to locale changes.

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

## Documentation Standards

### Text Encoding and Character Set

- **ASCII-only documentation**: All markdown files, code comments, commit messages, and documentation must use only ASCII characters (0x00-0x7F).
- **No emoji characters**: Emoji and other Unicode symbols (including arrows, checkmarks, warning signs) are forbidden in all documentation files.
- **ASCII alternatives**: Use text equivalents instead:
  - ✅ → `[x]` or `PASS` or `OK`
  - ❌ → `[ ]` or `FAIL` or `ERROR`
  - ⚠️ → `WARNING` or `CAUTION`
  - 🔴 → `RED` or `CRITICAL`
  - 🟡 → `YELLOW` or `HIGH`
  - 🟢 → `GREEN` or `LOW`
  - → → `->` or `-->`
  - ⏳ → `IN PROGRESS` or `PENDING`
- **Rationale**: Emoji cause encoding issues across different terminals, editors, and CI systems. ASCII ensures universal compatibility and prevents corruption in version control diffs.
- **Enforcement**: Pre-commit hooks should reject commits containing non-ASCII characters in documentation files (`.md`, `.txt`, comments in code).

## Documentation Sources (use as supplemental guidance)

- WordPress Plugin Development Cookbook
- Professional WordPress Plugin Development
- Test-Driven Development with PHP 8

## Literature Digest

- `docs/wp-plugin-literature-digest.md` Use it as a launch pad for best practices, coding recipes, and cross-references when implementing new slices of the plugin.
