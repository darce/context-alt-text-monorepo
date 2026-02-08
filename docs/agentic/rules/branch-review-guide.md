# Branch Review Guide

> **Purpose:** Structured checklist and metrics for reviewing feature branches before merge.
> Distilled from the 4.12.0 branch audit (52 findings) and existing project standards.

---

## Table of Contents

1. [How to Use This Guide](#how-to-use-this-guide)
2. [Automated Checks (Gate)](#automated-checks-gate)
3. [Manual Review Checklist](#manual-review-checklist)
4. [Metric Thresholds](#metric-thresholds)
5. [Finding Categories](#finding-categories)
6. [Severity Classification](#severity-classification)
7. [Review Report Template](#review-report-template)

---

## How to Use This Guide

### When

Run this review on every feature branch **before merge to `main`**. The automated gate (Section 2) should pass with zero errors. The manual checklist (Section 3) is a structured sweep for issues automation cannot catch.

### Who

The reviewer can be human or agentic. When an agent performs the review, it must:

1. Run all automated checks and report results
2. Walk through each manual checklist section, citing specific files and line numbers
3. Classify findings using the severity guide (Section 6)
4. Produce a report using the template (Section 7)

### Scope

Review only files in the branch diff (`git diff --name-only main...HEAD`). Do not audit the entire codebase.

---

## Automated Checks (Gate)

All automated checks must pass with zero errors before manual review begins. Run from the monorepo root using the CI pipeline:

### Python (Backend)

```bash
cd apps/prototype-description-service && make check 2>&1 | tail -30
```

This runs `ruff check .`, `mypy .`, and `pytest` in sequence. All three must pass.

### Frontend (TypeScript)

```bash
cd apps/prototype-wp-alt-context && npm run typecheck 2>&1 | tail -20
cd apps/prototype-wp-alt-context && npm run test -- --run 2>&1 | tail -30
cd apps/prototype-wp-alt-context && npm run lint 2>&1 | tail -20
```

### Frontend Architecture

```bash
cd apps/prototype-wp-alt-context && node scripts/check-architecture-compliance.js 2>&1
```

Zero errors required. Warnings are informational.

### PHP

```bash
cd apps/prototype-wp-alt-context && composer phpstan 2>&1 | tail -20
```

### Cyclomatic Complexity (Python)

```bash
cd apps/prototype-description-service
PYENV_VERSION=description-service python -m radon cc --min C --show-complexity --average recognition/ 2>&1
```

Any function scoring **C or worse** (complexity > 10) must be reviewed. See [Metric Thresholds](#cyclomatic-complexity) below.

> **Setup:** If `radon` is not installed, add it to dev dependencies: `pip install radon` and add `"radon>=6.0.0"` to `pyproject.toml` `[project.optional-dependencies] dev`.

---

## Manual Review Checklist

Work through each section sequentially. Check the box when the section is clean.

### 3.1 — Correctness

- [ ] **Migration ↔ Model parity**: Any schema changes in `001_identity_schema.py` must have matching constraints in `db/models/identity.py`. Run `alembic check` to detect drift.
- [ ] **No unreachable code**: Dead branches inside conditionals (e.g., `if x:` inside `else` where `x` is known `None`).
- [ ] **No duplicate field declarations**: Pydantic models, dataclasses — no field declared twice (second silently wins).
- [ ] **API contract alignment**: Response schemas match the contract in `docs/agentic/contracts/`. New fields have tests.

### 3.2 — Type Safety

**Python:**
- [ ] No `object` parameters — use the domain type or a Protocol.
- [ ] No `getattr()` + `callable()` guards on service protocols — declare methods on the Protocol.
- [ ] No `contextlib.suppress(Exception)` — catch specific exceptions and log.

**TypeScript:**
- [ ] No non-null assertions (`!`) on API data — use type guards.
- [ ] No `undefined as T` or `x as T` casts — use proper union return types.
- [ ] No ad-hoc query keys — all keys through `queryKeys` factory.

### 3.3 — Architecture Boundaries

- [ ] **No raw SQL in the application layer** — `text()` calls only in `infrastructure/repositories/`.
- [ ] **No presentation DTOs in the domain or application layer** — API response shapes belong in `interface_adapters/schemas/`. Application services must return domain types; the interface adapter maps to DTOs at the HTTP boundary.
- [ ] **No default-instantiating settings** — `ClusteringSettings()` inside a function bypasses DI. Inject as parameter.
- [ ] **No cross-layer exception duplication** — each exception class has exactly one canonical definition.
- [ ] **No redundant router/dependency wiring** — when a parent router already `include_router`s its sub-routers, those sub-routers must not also be registered individually on the app. Each router registered exactly once.
- [ ] **No time-based gates on curated state** — do not use cooldown windows, TTLs, or expiry timers to gate re-evaluation of user curation decisions (rejections, acceptances, labels). The gate must be a data delta (e.g., representative set changed), never elapsed time. Time assumes constant usage cadence which cannot be guaranteed.

### 3.4 — Code Duplication

- [ ] **Shared repository utilities** — UUID coercion, media-identity bootstrap, etc. live in `_helpers.py`, not copy-pasted.
- [ ] **Shared test stubs** — Protocol stubs used in 3+ files are extracted to `tests/stubs.py`.
- [ ] **One canonical fake per protocol** — no divergent fake implementations of the same Protocol across test files. Multiple fakes with different stored types drift independently and miss Protocol changes.
- [ ] **No duplicate methods** — Protocol interfaces have no aliased methods (e.g., both `block()` and `add_block()`).
- [ ] **Frontend components** — shared algorithms (face crop, badge styles) are in reusable components, not inlined.

### 3.5 — Error Handling

- [ ] **LIKE wildcard escaping** — any user-supplied string in `ilike()` escapes `%` and `_`.
- [ ] **No bare exception suppression** — every `except Exception` logs at `WARNING` minimum with `exc_info=True`.
- [ ] **Scoped exception clauses** — each `try/except` wraps only the single operation it guards, not the entire method body. A broad `except ValueError` (or similar typed catch) that spans multiple calls will silently swallow unrelated errors from downstream operations (e.g., enum conversion, domain mapping) and misreport them as "not found".
- [ ] **Consistent gate fallbacks** — all code paths that bypass the assignment gate apply the same checks (blocks AND constraints).

### 3.6 — Frontend Specific

- [ ] **No `!important` in SCSS** — increase selector specificity instead.
- [ ] **Design tokens for colors** — hex literals should be CSS custom properties with fallbacks.
- [ ] **No inline styles for layout** — grid/flex patterns belong in SCSS classes.
- [ ] **API calls go through API modules** — components don't import `fetchApi` directly.
- [ ] **`URLSearchParams` for query strings** — no string interpolation for URL params.

### 3.7 — PHP / WordPress

- [ ] **Superglobal sanitization** — `$_GET`/`$_POST` access uses `sanitize_key()`, `sanitize_text_field()`, or `absint()`.
- [ ] **One transport per parameter** — same value not sent in both POST body and query params.
- [ ] **Nonce verification** — all state-mutating endpoints check nonces.
- [ ] **Capability checks** — admin endpoints verify `current_user_can()`.

### 3.8 — Tests

- [ ] **No permanently skipped tests** — every `@pytest.mark.skip` / `it.skip()` has an issue reference or is removed.
- [ ] **No empty test bodies** — `pass`/`...` tests inflate pass counts and must be completed or deleted.
- [ ] **No false-positive fakes** — test fakes are configurable, not hardcoded to return `None`/empty.
- [ ] **`retry: false` in QueryClient** — test QueryClients disable retries.
- [ ] **Single injection strategy** — don't mix `dependency_overrides` and `monkeypatch.setattr` for the same dep.
- [ ] **Adequate coverage for new components** — each new UI component has tests for: render, loading, error, and primary interaction.

### 3.9 — Documentation & Cleanup

- [ ] **No stale comments** — "TODO", "assuming this", "will verify" comments resolved or removed.
- [ ] **No duplicate imports** — each symbol imported once per file.
- [ ] **Docstrings complete** — no empty `Raises:` or `Returns:` sections in docstrings.
- [ ] **Function-level imports justified** — standard deps (`numpy`, `json`) should be at module scope unless there's a genuine cold-start reason.

---

## Metric Thresholds

### File Size (Significant Lines)

Enforced by `check-architecture-compliance.js`. Significant lines = non-blank, non-comment.

| File Type | Max Lines | Enforcement |
|-----------|-----------|-------------|
| Component (`.tsx`) | 300 | Error |
| Route / Page | 400 | Error |
| Hook | 200 | Error |
| Utility | 150 | Error |
| API module | 175 | Error |
| Test file | No limit | — |
| Type definitions | No limit | — |

### Hook Usage (per component/route file)

Enforced by `check-architecture-compliance.js`.

| Metric | Max | Resolution |
|--------|-----|------------|
| `useState` calls | 5 | Use `useReducer` for complex state |
| `useEffect` calls | 3 | Extract to custom hooks |
| Custom hooks called | 8 | Split component or compose hooks |

### Python Function Size

| Metric | Target | Max | Resolution |
|--------|--------|-----|------------|
| Lines per function | < 30 | 40 | Extract helper functions |
| Parameters per function | < 5 | 7 | Use a parameter object / dataclass |

### Cyclomatic Complexity

Cyclomatic complexity measures the number of independent paths through a function. It directly correlates with the number of tests needed for full branch coverage and is the best single predictor of defects in a function.

**Tool:** [radon](https://radon.readthedocs.io/) for Python. ESLint `complexity` rule for TypeScript (not currently enabled — see note below).

**Thresholds (per function):**

| Grade | Range | Action |
|-------|-------|--------|
| **A** | 1–5 | No action needed. Simple, well-composed function. |
| **B** | 6–10 | Acceptable. Review if function could be simplified. |
| **C** | 11–15 | **Requires justification.** Flag in review — usually means the function does too much. |
| **D** | 16–20 | **Must refactor.** Extract branches into helper functions or use strategy pattern. |
| **E/F** | 21+ | **Block merge.** Function is untestable and unmaintainable. |

**Why these values?**

- **10 is the industry standard baseline** (McCabe's original 1976 paper, adopted by SEI/CERT, SonarQube, and most static analysis tools).
- **15 as a soft ceiling** because repository methods and FastAPI endpoint handlers with multiple query parameters often land at 11–13 legitimately — requiring all of those to be under 10 would force premature abstraction.
- **20 as a hard ceiling** because above 20 a function cannot be meaningfully unit-tested (too many paths) and even experienced developers struggle to hold the branching in their head.

**Typical offenders in this codebase:** Repository `_to_domain` converters, refresh service orchestration methods, and clustering dispatch functions. These are worth periodic review.

> **TypeScript note:** ESLint's `complexity` rule can be enabled in `eslint.config.mjs` with `'complexity': ['warn', 15]`. Not currently active — add when the team is ready to enforce.

### Test Coverage Delta

Not currently automated. Future CI integration should ensure:

| Metric | Threshold |
|--------|-----------|
| New code line coverage | ≥ 80% |
| New branch coverage | ≥ 70% |
| No untested public functions | 0 |

### SCSS Metrics

| Metric | Threshold | Resolution |
|--------|-----------|------------|
| `!important` count | 0 | Increase selector specificity |
| Raw hex colors (outside `var()` fallbacks) | 0 | Use `--acx-*` custom properties |
| Max selector nesting depth | 4 | Flatten or restructure |

---

## Finding Categories

Each finding is classified into one of four categories:

| Category | Icon | Description | Example |
|----------|------|-------------|---------|
| **ANTIPATTERN** | :warning: | Code that works but violates established patterns, creating maintenance risk | `contextlib.suppress(Exception)`, non-null assertions on API data |
| **DEAD_CODE** | :wastebasket: | Unreachable code, unused parameters, duplicate declarations, permanently skipped tests | Duplicate Pydantic field, `pass`-only test body |
| **COMPLEXITY** | :tangled: | Unnecessary duplication, overly complex functions, missing abstractions | Copy-pasted stubs across 4 test files, sequential mutation loop |
| **GAP** | :hole: | Missing functionality, incomplete contracts, missing tests | Protocol method not declared, missing pose fields in construction |

---

## Severity Classification

| Severity | Criteria | Action |
|----------|----------|--------|
| **HIGH** | Causes incorrect behavior, data corruption, type unsafety at build time, or > 200 lines of unnecessary duplication | Must fix before merge |
| **MEDIUM** | Violates architecture rules, creates maintenance burden, defeats type checking, or reduces test reliability | Should fix before merge; defer only with justification |
| **LOW** | Style issues, minor cleanup, small duplications, informational improvements | Fix in the same branch if easy; otherwise note for next pass |

---

## Review Report Template

Use this structure when producing a review report. Save to `docs/tasks/<version>/branch-audit-findings.md`.

```markdown
# Branch Audit — `feature/<branch-name>`

> **Date:** YYYY-MM-DD
> **Scope:** N files changed, +X / −Y lines vs `main`
> **Categories:** ANTIPATTERN · DEAD_CODE · COMPLEXITY · GAP

---

## Summary

| Severity | Count |
|----------|-------|
| **HIGH** | N |
| **MEDIUM** | N |
| **LOW** | N |
| **Total** | **N** |

---

## Automated Check Results

| Check | Result |
|-------|--------|
| `make check` (ruff + mypy + pytest) | :white_check_mark: / :x: |
| `npm run typecheck` | :white_check_mark: / :x: |
| `npm run test -- --run` | :white_check_mark: / :x: |
| `npm run lint` | :white_check_mark: / :x: |
| `check-architecture-compliance.js` | :white_check_mark: / :x: (N warnings) |
| `composer phpstan` | :white_check_mark: / :x: |
| Cyclomatic complexity (radon, grade C+) | N functions flagged |

---

## HIGH Severity

### H-1 · <Title>

| | |
|---|---|
| **Files** | `path/to/file.py` LN |
| **Category** | ANTIPATTERN / DEAD_CODE / COMPLEXITY / GAP |

<Description of finding with specific code references.>

<!-- Repeat for each HIGH finding -->

## MEDIUM Severity
<!-- Same structure -->

## LOW Severity
<!-- Same structure -->

---

## Recommended Fix Order

### Phase 1 — Correctness (before merge)
1. **H-1** — <one-line summary>

### Phase 2 — Robustness (soon after merge)
2. **H-N** — <one-line summary>

### Phase 3 — Maintainability (tech debt backlog)
3. **M-N** — <one-line summary>

---

# Consolidated Checklist

## Phase 1 — Correctness (before merge)
- [ ] **H-1** — <action item>

## Phase 2 — Robustness
- [ ] **M-1** — <action item>

## Phase 3 — Maintainability
- [ ] **L-1** — <action item>

## Success Criteria
- [ ] Zero HIGH findings remaining
- [ ] `make check` passes
- [ ] `npm run typecheck` passes with zero new errors
- [ ] All existing tests continue to pass
- [ ] Branch audit re-run shows no regressions
```

---

## Appendix: Adding Cyclomatic Complexity Tooling

### Python (radon)

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "radon>=6.0.0",
]
```

Add a Makefile target:

```makefile
complexity:
	$(ACTIVATE) && python -m radon cc --min C --show-complexity --average recognition/
```

### TypeScript (ESLint)

Add to `eslint.config.mjs` rules (when ready to enforce):

```js
rules: {
  'complexity': ['warn', 15],
  // ... existing rules
}
```

This produces warnings for functions exceeding 15 branches, complementing the architecture compliance checker's file-level metrics with function-level granularity.
