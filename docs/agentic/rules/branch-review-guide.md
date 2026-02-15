# Branch Review Guide

> **Purpose:** Structured checklist and metrics for reviewing feature branches before merge.
> Distilled from the 4.12.0 branch audit (52 findings) and existing project standards.
>
> **Relationship to `instructions.md`:** This guide is a review _lens_ on the canonical rules in [`instructions.md`](../instructions.md). Checklist items reference instruction sections rather than restating them. Load this guide for reviews; load `instructions.md` for development.

---

## Table of Contents

1. [How to Use This Guide](#how-to-use-this-guide)
2. [Automated Checks (Precondition)](#automated-checks-precondition)
3. [Manual Review Checklist](#manual-review-checklist)
4. [Metric Thresholds](#metric-thresholds)
5. [Finding Categories](#finding-categories)
6. [Severity Classification](#severity-classification)
7. [Review Report Template](#review-report-template)

---

## How to Use This Guide

### When

Run this review on every feature branch **before merge to `main`**. Automated checks (Section 2) must have passed **before submitting for review**. The manual checklist (Section 3) is a structured sweep for issues automation cannot catch.

### Who

The reviewer can be human or agentic. When an agent performs the review, it must:

1. Confirm automated checks passed (do NOT re-run them — see Section 2)
2. Walk through each manual checklist section, citing specific files and line numbers
3. Classify findings using the severity guide (Section 6)
4. Produce a report using the template (Section 7)

### Scope

Review only files in the branch diff (`git diff --name-only main...HEAD`). Do not audit the entire codebase.

---

## Automated Checks (Precondition)

> **The developer/agent submitting the branch for review is responsible for running all automated checks and ensuring they pass with zero errors.** The reviewer does NOT re-run these during review — doing so consumes significant tokens/time for information the submitter already has.

### Submitter Responsibility

Before requesting review, the submitter must run and confirm zero errors on:

| Check                         | Command                                                                                                        | Notes                                                    |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Python (ruff + mypy + pytest) | `cd apps/prototype-description-service && make check`                                                          | All three must pass. Skip if no Python files in diff.    |
| TypeScript types              | `cd apps/prototype-wp-alt-context && npm run typecheck`                                                        |                                                          |
| Frontend tests                | `cd apps/prototype-wp-alt-context && npm run test -- --run`                                                    |                                                          |
| ESLint                        | `cd apps/prototype-wp-alt-context && npm run lint`                                                             |                                                          |
| Architecture compliance       | `cd apps/prototype-wp-alt-context && node scripts/check-architecture-compliance.js`                            | Zero errors; warnings are informational                  |
| PHP static analysis           | `cd apps/prototype-wp-alt-context && composer phpstan`                                                         | Skip if not configured in `composer.json`                |
| Cyclomatic complexity         | `cd apps/prototype-description-service && python -m radon cc --min C --show-complexity --average recognition/` | Grade C+ functions must be justified. Skip if no Python. |

### Reviewer Responsibility

- **Verify** the submitter reports all checks passed (commit message, PR description, or review request).
- **Spot-check only** if a specific finding during manual review suggests a check may have been missed (e.g., a type error visible in the diff implies `typecheck` wasn't run).
- **Do NOT re-run the full suite** — this is wasted work if checks already passed.

---

## Manual Review Checklist

Work through each section sequentially. Check the box when the section is clean. Each item references its canonical rule in [`instructions.md`](../instructions.md) — consult that document for full rationale and code examples.

### 3.1 — Correctness

- [ ] **Migration ↔ Model parity** — constraints match between migration and ORM model. _(Hexagonal Layer Rule #8)_
- [ ] **No unreachable code** — dead branches inside conditionals.
- [ ] **No duplicate field declarations** — Pydantic models, dataclasses. _(Hexagonal Layer Rule #9)_
- [ ] **API contract alignment** — response schemas match `docs/agentic/contracts/`. New fields have tests.

### 3.2 — Type Safety

**Python** _(Hexagonal Layer Rules #2, #3, #5)_:

- [ ] No `object` parameters — use the domain type or a Protocol.
- [ ] No `getattr()` + `callable()` guards — declare methods on the Protocol.
- [ ] No `contextlib.suppress(Exception)` — catch specific exceptions and log.

**TypeScript** _(TypeScript Safety Rules #1–3)_:

- [ ] No non-null assertions (`!`) on API data — use type guards.
- [ ] No `undefined as T` or `x as T` casts — use proper union return types.
- [ ] No ad-hoc query keys — all keys through `queryKeys` factory.

### 3.3 — Architecture Boundaries

_(Hexagonal Layer Rules #1, #4, #6, #9, #12; Curation-First Precedence)_

- [ ] **No raw SQL in the application layer** — `text()` calls only in `infrastructure/repositories/`.
- [ ] **No presentation DTOs in domain or application layer** — API response shapes in `interface_adapters/schemas/`.
- [ ] **No default-instantiating settings** — inject via DI, don't construct defaults inside functions.
- [ ] **No cross-layer exception duplication** — one canonical definition per exception.
- [ ] **No redundant router/dependency wiring** — each router registered exactly once.
- [ ] **No time-based gates on curated state** — gate on data deltas, never elapsed time.

### 3.4 — Code Duplication

_(Hexagonal Layer Rule #10; Testing Standards #10, #11)_

- [ ] **Shared repository utilities** — UUID coercion, media-identity bootstrap in `_helpers.py`.
- [ ] **Shared test stubs** — Protocol stubs used in 3+ files extracted to `tests/stubs.py`.
- [ ] **One canonical fake per protocol** — no divergent fakes across test files.
- [ ] **No duplicate methods** — Protocol interfaces have no aliased methods.
- [ ] **Frontend components** — shared algorithms in reusable components, not inlined.

### 3.5 — Error Handling

_(Hexagonal Layer Rules #2, #7, #11)_

- [ ] **LIKE wildcard escaping** — user-supplied strings in `ilike()` escape `%` and `_`.
- [ ] **No bare exception suppression** — `except Exception` logs at `WARNING` minimum.
- [ ] **Scoped exception clauses** — `try/except` wraps only the single operation it guards.
- [ ] **Consistent gate fallbacks** — all bypass paths apply the same checks (blocks AND constraints).

### 3.6 — Frontend Specific

_(TypeScript Safety Rules #4–8, #9–13)_

- [ ] **No `!important` in SCSS** — increase selector specificity.
- [ ] **Design tokens for colors** — hex literals as CSS custom properties.
- [ ] **No inline styles for layout** — grid/flex patterns in SCSS classes.
- [ ] **API calls go through API modules** — no direct `fetchApi` imports in components.
- [ ] **`URLSearchParams` for query strings** — no string interpolation for URL params.

### 3.7 — PHP / WordPress

_(Backend Guidelines → WordPress Plugin → Security; WordPress Plugin Rules)_

- [ ] **Superglobal sanitization** — `sanitize_key()`, `sanitize_text_field()`, or `absint()`.
- [ ] **One transport per parameter** — same value not in both POST body and query params.
- [ ] **Nonce verification** — all state-mutating endpoints check nonces.
- [ ] **Capability checks** — admin endpoints verify `current_user_can()`.

### 3.8 — Tests

_(Testing Standards #9–14)_

- [ ] **No permanently skipped tests** — every skip has an issue reference or is removed.
- [ ] **No empty test bodies** — `pass`/`...` tests must be completed or deleted.
- [ ] **No false-positive fakes** — test fakes are configurable, not hardcoded to return `None`/empty.
- [ ] **`retry: false` in QueryClient** — test QueryClients disable retries.
- [ ] **Single injection strategy** — don't mix `dependency_overrides` and `monkeypatch.setattr`.
- [ ] **Adequate coverage for new components** — render, loading, error, and primary interaction.

### 3.9 — Documentation & Cleanup

- [ ] **No stale comments** — "TODO", "assuming this", "will verify" resolved or removed.
- [ ] **No duplicate imports** — each symbol imported once per file.
- [ ] **Docstrings complete** — no empty `Raises:` or `Returns:` sections.
- [ ] **Function-level imports justified** — standard deps at module scope unless genuine cold-start reason.

### 3.10 — Bug-Finding Heuristics

Pattern-compliance checks (§3.1–3.9) catch structural violations. This section guides the reviewer to trace data flow and logic to find **runtime bugs** that automation misses. Work through each heuristic on every non-trivial function in the diff.

#### Variable identity after normalization

When a function normalizes an input early (e.g., `$normalized = trim($input)`), trace **every** subsequent reference to verify the normalized variable is used, never the original. Common failure: guard validates `$normalized`, but a downstream call or SQL binding still passes `$input`.

_Real example: `merge_snapshot_for_tenant()` trims `$tenant_id` into `$normalized_tenant_id` but a nested method call still received the raw `$tenant_id`._

#### Data-flow through SQL binding

For each SQL query with placeholders, verify the full chain: value origin → transformation → placeholder binding → database interpretation.

- [ ] Placeholder count matches argument count (especially with dynamic `$placeholders` strings).
- [ ] Arguments are in correct positional order matching their placeholders.
- [ ] Sentinel/default values survive the binding mechanism. If a function returns `'NULL'` (string) and it's bound via `%s`, the database receives the **string** `'NULL'`, not SQL `NULL`. Trace what the database actually stores.
- [ ] `NULLIF()`, `COALESCE()`, `IF()` wrappers use the correct comparison value for the sentinel (e.g., `NULLIF(%s, '')` requires the sentinel to be `''`, not `'NULL'`).

#### Guard condition vs business rule alignment

For each `WHERE` clause, `if` guard, or existence check, state the business rule in plain language, then verify the SQL/code implements exactly that rule — no more, no less.

- [ ] Curation guards protect the **correct scope**. A guard meant to protect cluster-level fields should not inadvertently block operations on related entities (e.g., blocking member inserts for confirmed clusters when only cluster label/state should be protected).
- [ ] Deletion guards exclude the correct rows. `NOT IN` vs `FIND_IN_SET` vs `NOT EXISTS` have different semantics for NULL, empty sets, and multi-value strings.
- [ ] Early returns match their stated purpose. An early return for "empty input" should not also skip cleanup operations that should always run.

#### SQL function semantic correctness

Audit SQL functions used with dynamic data for semantic edge cases:

- [ ] `FIND_IN_SET(col, %s)` — the set argument is a single comma-separated string; a data value containing a comma corrupts the set boundary. Prefer `NOT IN (...)` with individual placeholders.
- [ ] `GREATEST()` / `LEAST()` — any `NULL` argument makes the result `NULL` in MySQL.
- [ ] `IF(condition, a, b)` — verify the condition evaluates against the **current** row state, not the incoming `VALUES()`.
- [ ] `ON DUPLICATE KEY UPDATE` — verify which fields refresh unconditionally vs which are guarded. Accidentally guarding a field that should refresh (or vice versa) is a silent data bug.

#### Cross-method contract bugs

When method A transforms data and passes it to method B:

- [ ] Transformation output matches method B's expected input type and format.
- [ ] Error returns / null returns from B are checked by A.
- [ ] If A filters/validates a collection then passes a derivative (e.g., extracted IDs), verify the derivative is computed **from the filtered set**, not from the original unfiltered input.

#### Boundary value sweep

For each function accepting numeric or collection inputs, mentally substitute:

- [ ] **Empty** — empty array, empty string, zero. Does the function degrade gracefully or produce invalid SQL / divide-by-zero?
- [ ] **Single element** — array with one item. Does `implode()` produce valid SQL? Does a loop body work on first-and-only iteration?
- [ ] **Large input** — what happens at 10k+ items? Does a `NOT IN (...)` clause with 10k placeholders hit MySQL limits? Is there an unbounded `LEFT JOIN` scan on every call?

---

## Metric Thresholds

> Canonical size limits and hook counts are defined in [`instructions.md` → Frontend Guidelines → Component Rules](../instructions.md#component-rules) and enforced by `check-architecture-compliance.js`. This section covers thresholds the reviewer checks manually during review.

### Python Function Size

| Metric                  | Target | Max | Resolution                         |
| ----------------------- | ------ | --- | ---------------------------------- |
| Lines per function      | < 30   | 40  | Extract helper functions           |
| Parameters per function | < 5    | 7   | Use a parameter object / dataclass |

### Cyclomatic Complexity

**Tool:** [radon](https://radon.readthedocs.io/) for Python. ESLint `complexity` rule for TypeScript (not currently enabled).

| Grade   | Range | Action                                              |
| ------- | ----- | --------------------------------------------------- |
| **A**   | 1–5   | No action needed.                                   |
| **B**   | 6–10  | Acceptable. Review if function could be simplified. |
| **C**   | 11–15 | **Requires justification.** Flag in review.         |
| **D**   | 16–20 | **Must refactor.**                                  |
| **E/F** | 21+   | **Block merge.**                                    |

**Typical offenders:** Repository `_to_domain` converters, refresh service orchestration methods, clustering dispatch functions.

### SCSS Metrics

| Metric                                     | Threshold | Resolution                      |
| ------------------------------------------ | --------- | ------------------------------- |
| `!important` count                         | 0         | Increase selector specificity   |
| Raw hex colors (outside `var()` fallbacks) | 0         | Use `--acx-*` custom properties |
| Max selector nesting depth                 | 4         | Flatten or restructure          |

---

## Finding Categories

Each finding is classified into one of four categories:

| Category        | Icon          | Description                                                                            | Example                                                           |
| --------------- | ------------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| **ANTIPATTERN** | :warning:     | Code that works but violates established patterns, creating maintenance risk           | `contextlib.suppress(Exception)`, non-null assertions on API data |
| **DEAD_CODE**   | :wastebasket: | Unreachable code, unused parameters, duplicate declarations, permanently skipped tests | Duplicate Pydantic field, `pass`-only test body                   |
| **COMPLEXITY**  | :tangled:     | Unnecessary duplication, overly complex functions, missing abstractions                | Copy-pasted stubs across 4 test files, sequential mutation loop   |
| **GAP**         | :hole:        | Missing functionality, incomplete contracts, missing tests                             | Protocol method not declared, missing pose fields in construction |

---

## Severity Classification

| Severity   | Criteria                                                                                                           | Action                                                       |
| ---------- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| **HIGH**   | Causes incorrect behavior, data corruption, type unsafety at build time, or > 200 lines of unnecessary duplication | Must fix before merge                                        |
| **MEDIUM** | Violates architecture rules, creates maintenance burden, defeats type checking, or reduces test reliability        | Should fix before merge; defer only with justification       |
| **LOW**    | Style issues, minor cleanup, small duplications, informational improvements                                        | Fix in the same branch if easy; otherwise note for next pass |

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

| Severity   | Count |
| ---------- | ----- |
| **HIGH**   | N     |
| **MEDIUM** | N     |
| **LOW**    | N     |
| **Total**  | **N** |

---

## Automated Check Results (reported by submitter)

| Check                                   | Result                                |
| --------------------------------------- | ------------------------------------- |
| `make check` (ruff + mypy + pytest)     | :white_check_mark: / :x:              |
| `npm run typecheck`                     | :white_check_mark: / :x:              |
| `npm run test -- --run`                 | :white_check_mark: / :x:              |
| `npm run lint`                          | :white_check_mark: / :x:              |
| `check-architecture-compliance.js`      | :white_check_mark: / :x: (N warnings) |
| `composer phpstan`                      | :white_check_mark: / :x:              |
| Cyclomatic complexity (radon, grade C+) | N functions flagged                   |

---

## HIGH Severity

### H-1 · <Title>

|              |                                            |
| ------------ | ------------------------------------------ |
| **Files**    | `path/to/file.py` LN                       |
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
