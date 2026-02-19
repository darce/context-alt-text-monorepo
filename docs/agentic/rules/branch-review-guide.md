# Branch Review Guide

> **Purpose:** Structured checklist and metrics for reviewing feature branches before merge.
> Checklist items reference canonical rules in [`instructions.md`](../instructions.md).

## Quick Navigation

**Start here:** This file covers universal process, common checklist, severity classification, and report template.

**Then load the relevant stack guide(s):**

- Python / FastAPI / SQLAlchemy → [branch-review-python.md](branch-review-python.md)
- TypeScript / React / Vitest → [branch-review-typescript.md](branch-review-typescript.md)
- PHP / WordPress / PHPUnit → [branch-review-php.md](branch-review-php.md)

Load only the guides relevant to files in the branch diff. Most branches touch one or two stacks.

---

## How to Use This Guide

### When

Run this review on every feature branch **before merge to `main`**.

### Who

The reviewer can be human or agentic. When an agent performs the review:

1. Confirm automated checks passed (do NOT re-run them — see below)
2. Walk through each checklist section, citing specific files and line numbers
3. Classify findings using the severity guide below
4. Produce a report using the template at the end of this file

### Scope

Review only files in the branch diff (`git diff --name-only main...HEAD`).

---

## Automated Checks (Precondition)

> The submitter is responsible for running all checks and confirming zero errors before requesting review. The reviewer does NOT re-run these.

| Check                         | Command                                                                                | Notes                                 |
| ----------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------- |
| Python (ruff + mypy + pytest) | `cd apps/prototype-description-service && make check`                                  | Skip if no Python files in diff       |
| TypeScript types              | `cd apps/prototype-wp-alt-context && npm run typecheck`                                |                                       |
| Frontend tests                | `cd apps/prototype-wp-alt-context && npm run test -- --run`                            |                                       |
| ESLint                        | `cd apps/prototype-wp-alt-context && npm run lint`                                     |                                       |
| Architecture compliance       | `cd apps/prototype-wp-alt-context && node scripts/check-architecture-compliance.js`    | Zero errors; warnings informational   |
| PHP static analysis           | `cd apps/prototype-wp-alt-context && composer phpstan`                                 |                                       |
| Cyclomatic complexity         | `cd apps/prototype-description-service && python -m radon cc --min C --show-complexity --average recognition/` | Grade C+ must be justified |

Reviewer responsibility: **verify** the submitter reports all checks passed. **Spot-check only** if a finding during manual review suggests a check was missed.

---

## Common Checklist

These items apply regardless of language. Stack-specific items are in the language guides linked above.

### Correctness

- [ ] **Migration ↔ Model parity** — constraints match between migration and ORM model.
- [ ] **No unreachable code** — dead branches inside conditionals.
- [ ] **No duplicate field declarations** — Pydantic models, dataclasses.
- [ ] **API contract alignment** — response schemas match `docs/agentic/contracts/`. New fields have tests.

### Code Duplication

- [ ] **Shared test stubs** — Protocol stubs used in 3+ files extracted to shared location.
- [ ] **One canonical fake per protocol** — no divergent fakes across test files.
- [ ] **No duplicate methods** — interfaces have no aliased methods.

### Tests

- [ ] **No permanently skipped tests** — every skip has an issue reference.
- [ ] **No empty test bodies** — `pass`/`...` tests completed or deleted.
- [ ] **No false-positive fakes** — test fakes are configurable, not hardcoded to return `None`/empty.
- [ ] **Single injection strategy** — don't mix `dependency_overrides` and `monkeypatch.setattr`.
- [ ] **Adequate coverage for new components** — render, loading, error, and primary interaction.

### Documentation & Cleanup

- [ ] **No stale comments** — "TODO", "assuming this", "will verify" resolved or removed.
- [ ] **No duplicate imports** — each symbol imported once per file.
- [ ] **Docstrings complete** — no empty `Raises:` or `Returns:` sections.
- [ ] **Function-level imports justified** — standard deps at module scope unless genuine cold-start reason.

### Bug-Finding Heuristics (Universal)

**Variable identity after normalization:** When a function normalizes an input early, trace every subsequent reference to verify the normalized variable is used, never the original.

**Cross-method contract bugs:** When method A transforms data and passes it to method B:

- [ ] Transformation output matches method B's expected input type and format.
- [ ] Error/null returns from B are checked by A.
- [ ] Derivatives computed from the filtered set, not the original unfiltered input.

**Boundary value sweep:** For each function accepting numeric or collection inputs, mentally substitute empty, single element, and large (10k+) inputs.

---

## Finding Categories

| Category        | Icon          | Description                                                              |
| --------------- | ------------- | ------------------------------------------------------------------------ |
| **ANTIPATTERN** | :warning:     | Works but violates patterns, creating maintenance risk                   |
| **DEAD_CODE**   | :wastebasket: | Unreachable code, unused params, duplicate declarations, skipped tests   |
| **COMPLEXITY**  | :tangled:     | Unnecessary duplication, overly complex functions, missing abstractions  |
| **GAP**         | :hole:        | Missing functionality, incomplete contracts, missing tests               |

---

## Severity Classification

| Severity   | Criteria                                                                                         | Action                                            |
| ---------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| **HIGH**   | Incorrect behavior, data corruption, type unsafety, or >200 lines unnecessary duplication        | Must fix before merge                             |
| **MEDIUM** | Architecture violations, maintenance burden, defeated type checking, reduced test reliability     | Should fix; defer only with justification          |
| **LOW**    | Style, minor cleanup, small duplications                                                         | Fix if easy; otherwise next pass                  |

---

## Review Report Template

Save to `docs/tasks/<version>/<branch-name>-branch-audit-findings.md`.

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

<Description with specific code references.>

## MEDIUM Severity

<!-- Same structure -->

## LOW Severity

<!-- Same structure -->

---

## Recommended Fix Order

### Phase 1 — Correctness (before merge)

1. **H-1** — <one-line summary>

### Phase 2 — Robustness (soon after merge)

2. **M-1** — <one-line summary>

### Phase 3 — Maintainability (tech debt backlog)

3. **L-1** — <one-line summary>

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
