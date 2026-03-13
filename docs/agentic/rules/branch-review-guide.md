# Branch Review Guide

> **Purpose:** Structured checklist and metrics for reviewing feature branches before merge.
> Checklist items reference canonical rules in [`instructions.md`](../instructions.md).

## Quick Navigation

**Start here:** This file covers universal process, common checklist, severity classification, and report template.

For task plans, epics, roadmaps, ADRs, and other planning documents, use [planning-review-guide.md](planning-review-guide.md) instead of this guide.

**Then load the relevant stack guide(s):**

- Python / FastAPI / SQLAlchemy → [branch-review-python.md](branch-review-python.md)
- TypeScript / React / Vitest → [branch-review-typescript.md](branch-review-typescript.md)
- PHP / WordPress / PHPUnit → [branch-review-php.md](branch-review-php.md)

Load only the guides relevant to files in the branch diff. Most branches touch one or two stacks.

---

## How to Use This Guide

### When

Run this review on every feature branch **before merge to `main`**.
For multi-worktree orchestration in this repo, perform the review from the orchestrator root and log findings into MCP there before routing them to worker lanes.

### Who

The reviewer can be human or agentic. When an agent performs the review:

1. Walk through each checklist section, citing specific files and line numbers
2. Classify findings using the severity guide and categories below
3. Record each finding into MCP via `record_review_finding` (see MCP Handoff Integration)
4. Do **not** produce a report file unless the user explicitly requests one
5. If the task is split into worktrees, have the orchestrator run `make review-dispatch TASK=<task-ref>` after findings are logged so open issues are stamped to the correct lane and delivered through MCP lane messages.

Hard rule for agent responses:
- Do not present a finding in chat unless it has already been recorded in MCP with a stable `finding_id`.
- If a finding is discussed before recording, immediately record it and then reference its `finding_id`.

### Scope

Review only **uncommitted working-directory changes** (`git status` / `git diff --name-only`), not the full branch history against `main`. The goal is to review what will be in the next commit, not re-review already-committed work.

For a full branch audit before merge, use `git diff --name-only main...HEAD` instead.

### Dev Tooling (Lightweight Review)

Files under `scripts/mcp/`, MCP test files, and other dev tooling do **not** require the full checklist treatment. Apply a lightweight review:

- Correctness: does the tool do what it claims?
- Obvious bugs: off-by-one, missing error handling, SQL injection
- Skip: metric thresholds, architecture boundary checks, Protocol typing

Dev tooling findings should still be recorded via `record_review_finding` but are never HIGH severity unless they corrupt production data or state.

---

## Common Checklist

These items apply regardless of language. Stack-specific items are in the language guides linked above.

### Correctness

- [ ] **Migration ↔ Model parity** — constraints match between migration and ORM model.
- [ ] **Schema-column parity** — SQL `WHERE`/`JOIN` keys match actual schema columns (no stale key names).
- [ ] **No unreachable code** — dead branches inside conditionals.
- [ ] **No duplicate field declarations** — Pydantic models, dataclasses.
- [ ] **API contract alignment** — response schemas match `docs/agentic/contracts/`. New fields have tests.
- [ ] **Assertion intent matches layer** — assertions are used only for internal invariants/unreachable states, never as a substitute for boundary validation.
- [ ] **Runtime dependency integrity** — no local type-only shims masking missing runtime packages; verify new imports with real build/test execution.
- [ ] **Atomic mutation path preserved** — avoid splitting an existing atomic backend write flow into multiple client mutations without explicit architecture sign-off.
- [ ] **Primary control reachability** — primary actions (for example select-all) are reachable from initial zero-state UI.
- [ ] **Stale/offline path remains user-recoverable** — automation flags/defaults cannot remove an explicit manual recovery action.
- [ ] **Interactive timeout parity** — related remote calls use a shared timeout helper and consistent timeout budgets.
- [ ] **Import/restore payload validation** — malformed snapshot shapes fail fast with explicit errors (never silent success).
- [ ] **Provenance preservation** — status/update operations do not overwrite original creator metadata.

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
- [ ] **Planning-doc consistency** — "What works", "What's missing", checklist state, and success criteria do not contradict.
- [ ] **ADR terminology alignment** — accepted domain terms are used consistently (no regressions to retired naming).
- [ ] **Command invocability** — documented commands run as written (no broken copy-paste syntax).
- [ ] **No debug/large artifact commits** — logs and generated output files are ignored and excluded from Git.
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

**Retry lifecycle traps:** For visibility/focus/interval retries, verify both sides:

- [ ] Per-cycle retry guards prevent duplicate concurrent attempts.
- [ ] Guard reset happens only on intentional state transitions (for example fresh -> stale), so retries are neither infinite nor permanently disabled.

**Import strictness check:** Feed one malformed import payload variant during review (`snapshot` wrong type or required shape missing) and verify the tool returns `ok: false` with an explicit error.

**Mutable-record provenance:** For lifecycle/status updates, confirm updater context does not erase original creator metadata (`agent`, `branch`, `commit_sha`).

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

## MCP Handoff Integration (MANDATORY for Agents)

After completing the review, every finding **must** be recorded into the MCP handoff database for cross-agent visibility. Do not rely solely on the markdown report.

### After Each Finding

Call `record_review_finding` with:

| Parameter      | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| `session`      | Current session identifier (e.g., `2026-02-20-copilot-review`)  |
| `finding_id`   | Short ID matching the report (e.g., `H-1`, `M-2`, `L-3`)       |
| `severity`     | `high`, `medium`, or `low`                                      |
| `file_path`    | Relative path from monorepo root                                |
| `description`  | One-paragraph description with code references                  |
| `details`      | Optional object: `{ "line_start"?: int, "line_end"?: int, "fix"?: str }` |
| `actor`        | Optional object: `{ "agent"?: str, "branch"?: str, "commit_sha"?: str }` |

### After All Findings Recorded

1. Call `get_review_findings_summary` to confirm severity/status counts for the task.
2. Use `list_review_findings(status="all")` if you need full finding-by-finding verification.
3. Call `record_decision` summarizing the review (finding count by severity, session ID).
4. Call `generate_current_task_md` to regenerate `CURRENT_TASK.md` with findings visible.
5. If this review concludes the task, run `handoff_close_check(enforce=True)` before final handoff.
6. Include `Handoff updated: yes` in the response.

Do not use direct `sqlite3` shell queries for MCP handoff verification when these tools are available.

### Severity Mapping

The MCP `severity` field maps directly to this guide's severity levels:

- `HIGH` -> `high` -- must fix before merge
- `MEDIUM` -> `medium` -- should fix; defer only with justification
- `LOW` -> `low` -- fix if easy; otherwise next pass

---

## Review Report Template

> **Only produce this file when the user explicitly requests a written report.** Findings recorded via `record_review_finding` are the canonical store.

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
