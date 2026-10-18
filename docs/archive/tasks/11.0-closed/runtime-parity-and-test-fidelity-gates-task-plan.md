# Task Plan Template

> Use this template for all implementation plans under `docs/tasks/`.
> Task plans describe executable work for one bounded objective.
> Task plans use **slices**, not phases:
>
> - **Phases** belong to epics and describe coarse-grained temporal delivery across multiple task plans.
> - **Slices** are reviewable implementation increments that can be completed, verified, and logged independently.
>
> Favor slices that each produce behavior plus proof. Avoid scaffold-only slices that add placeholders, skipped tests, or empty abstractions without executable value.
> See `docs/agentic/instructions.md` and `docs/agentic/rules/planning-review-guide.md` for repo-wide planning rules.

---

# Runtime Parity and Test Fidelity Gates

## Objective

Catch production-only breakage earlier by aligning tests, stubs, review gates, and documentation with real runtime behavior. Add runtime-parity requirements, stub-fidelity rules, performance-evidence guidance, and property-based tests for FTS5 sanitization so boundary regressions are detected at test time instead of during manual debugging.

## Problem Statement

Four process-level gaps remain after Phases 1 and 2:

1. **Python review guide lacks fresh-evidence requirements.** The TypeScript and PHP review guides both require fresh command evidence on the current branch state before accepting behavior-fix claims. `branch-review-python.md` has automated-check commands but no equivalent blocking rule, creating an asymmetric evidence standard across stacks.
2. **No stub-fidelity guidance.** Stubs and fakes in the PHP test suite (`NullClustersRepository`, `NullIdentityMembersRepository`, etc.) correctly implement interface types, but no guidance ensures they match real runtime behavior. A stub that silently succeeds where the real implementation would throw masks production failures. `testing-principles.md` documents the fake hierarchy but not behavioral fidelity expectations.
3. **No performance-evidence guidance.** Review and testing guides mention latency targets (`testing-principles.md` has a Performance Targets section with sync endpoint p50 <150ms) but no guidance requires latency distributions, queue depth, connection-pool wait, or retry behavior to be captured as verifiable evidence on high-risk changes. Incident history shows average-latency metrics masking tail-latency and saturation problems.
4. **FTS5 sanitization has zero property-based test coverage.** Two separate sanitization strategies exist (`core.py` phrase-quotes terms; `artifact_index.py` strips metacharacters via regex) with only 3 handwritten test cases covering double-quote, colon, and hyphen-prefix inputs. No Hypothesis tests exercise Unicode edge cases, injection sequences, or the full FTS5 special-character set. A motivated or accidental bad input could bypass the existing coverage.

Additionally, the review-guide-hardening task already completed one Phase 3 checklist item (masking/bootstrap drift heuristics in TS and PHP review guides), but the remaining items need implementation.

## Constraints

- Guide edits are additive. Do not rewrite existing checklist sections; add new sections alongside them.
- FTS5 property-based tests require adding `hypothesis` as a test dependency to `packages/agent-handoff-mcp/pyproject.toml`. Hypothesis is not currently used anywhere in the repo.
- Stub-fidelity guidance applies across PHP, Python, and TypeScript; test-specific rules go in the per-language testing guides, with the universal principle in `testing-principles.md`.
- Performance-evidence guidance is documentation-only in this task; no new tooling or MCP helpers (those are Phase 4 scope).
- Default scope is docs plus tests only. If the new property-based tests expose an invalid FTS5 MATCH expression in the live sanitizers, a narrow runtime hardening patch to `core.py` or `artifact_index.py` is allowed in the same slice so the proof can pass honestly.
- The two FTS5 sanitization strategies (phrase-quoting vs regex stripping) are intentionally distinct; the tests should verify each strategy independently against the full special-character set, not unify them.

## Workflow Principles

- Runtime parity over test-only confidence: when a test stub silently succeeds but the real runtime would fail, the test is a false positive.
- Behavioral fidelity for fakes: stubs must match the real implementation's error-raising, exception, and empty-state behavior, not just its type signature.
- Performance evidence as a distribution, not an average: p50/p95/p99, queue depth, connection-pool wait, and retry counts are required for high-risk changes; a passing average can mask tail-latency regressions.
- Property-based testing for input sanitization: hand-written cases cannot exhaustively cover the input space; Hypothesis-driven fuzz testing provides confidence against novel character combinations.

## Terminology

- **Runtime parity**: Verification that production bootstrap, class loading, and adapter behavior match the paths exercised in tests.
- **Stub fidelity**: The degree to which a test stub reproduces the real implementation's behavioral contract (errors, side effects, state transitions), not just its type interface.
- **Performance evidence**: Measurable runtime data (latency distributions, queue depths, pool waits, retry counts) attached to a handoff decision or test result, not narrative claims.
- **Property-based testing**: Generating random inputs against a property invariant (e.g., "sanitized output never contains unquoted FTS5 metacharacters") to find edge cases that hand-written tests miss.

## Current State Analysis

- `branch-review-python.md` has an Automated Checks table (`make check`, `radon cc`) but no fresh-evidence blocking rule. The TS and PHP guides both have paragraphs requiring fresh command evidence on current branch state.
- `testing-principles.md` has a Hierarchical TDD section (fake vs real resources) and Performance Targets (sync <150ms, Lighthouse >90, CWV), but no stub-fidelity rules, no performance-distribution guidance, and no runtime-parity section.
- `testing-python.md` has "Test Mock Defaults Match Production Defaults" (line 22) which partially addresses stub fidelity for Python, but the rule is narrow (mock return values) and not generalized to behavioral contracts.
- `testing-php.md` has "Anonymous Test Classes for Interfaces" (line 87) documenting the existing `Null*` stub pattern, but no guidance on when a null stub masks real runtime behavior.
- `development-workflow.md` has a Cross-Boundary Change Protocol step 4 ("Run a runtime-parity check") but no detailed guidance on what runtime-parity verification looks like for each stack.
- FTS5 sanitization in `core.py` (phrase-quoting) and `artifact_index.py` (regex stripping) has 3 hand-written test cases in `test_search_handoff.py` tagged `P-FTS-SANITIZE-01`, plus basic FTS5 availability tests in `test_artifact_index.py`. No property-based coverage.
- Hypothesis is not a dependency of any package in this repo.
- `branch-review-guide.md` already has "Import/restore payload validation" and "malformed snapshot shapes fail fast" checklist items from Phase 2.
- The review-guide-hardening task completed: TS `State Surface Correctness` section (API-boundary malformed payload tolerance) and PHP `Boundary and Runtime Correctness` section (bootstrap parity, adapter provenance, degradation semantics).

## Target Outcome

Every branch review guide has symmetrical fresh-evidence requirements. Testing guides document stub-fidelity rules so agents know when a null stub must be replaced with a behavioral fake. Performance evidence is defined as distributions plus queue/pool/retry metrics rather than averages. FTS5 sanitization has Hypothesis-driven property-based tests that exercise the full special-character set and Unicode edge cases against both sanitization strategies. A reviewer can tell, from the guides alone, when a passing test suite is insufficient because stubs, bootstrap paths, or performance measurements do not match production.

## Context Loading

> List the minimum authoritative context an agent should load before implementation.

- Rules: `docs/agentic/rules/testing-principles.md`, `docs/agentic/rules/branch-review-python.md`, `docs/agentic/rules/testing-python.md`
- Rules: `docs/agentic/rules/branch-review-guide.md` (Common Checklist, Fresh Verification Evidence), `docs/agentic/rules/development-workflow.md` (Cross-Boundary Change Protocol step 4)
- Testing guides: `docs/agentic/rules/testing-php.md`, `docs/agentic/rules/testing-typescript.md` (for symmetry comparison)
- FTS5 sources: `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` (search_handoff phrase-quoting), `packages/agent-handoff-mcp/src/agent_handoff_mcp/artifact_index.py` (_build_fts5_match_query)
- FTS5 tests: `packages/agent-handoff-mcp/tests/test_search_handoff.py` (P-FTS-SANITIZE-01 section), `packages/agent-handoff-mcp/tests/test_artifact_index.py`
- Handoff/MCP state: task ref `agentic-development-process-hardening-epic`; Phase 3 checklist status
- Epic: `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md` Phase 3 deliverables and exit criteria
- External docs via `ctx7` only if: Hypothesis API or FTS5 query syntax semantics need verification

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| MCP handoff FTS5 search | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md` | No contract change; tests only | No | Hypothesis tests pass |
| Review guide process surfaces | agentic-tooling | `docs/agentic/rules/branch-review-*.md` | Additive sections | No | Manual review |
| Testing guide process surfaces | agentic-tooling | `docs/agentic/rules/testing-*.md` | Additive sections | No | Manual review |

## Proposed Solution

Five slices, each producing behavior plus proof. Slices 1-3 are documentation-only (review/testing guide additions). Slice 4 adds Hypothesis as a test dependency and writes property-based tests. Slice 5 adds performance-evidence guidance. All slices are independent and can be implemented in any order.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| review | `docs/agentic/rules/branch-review-python.md` | Add fresh-evidence paragraph to Automated Checks section |
| testing | `docs/agentic/rules/testing-principles.md` | Add "Stub and Fake Fidelity" section; add "Runtime-Parity Verification" section |
| testing | `docs/agentic/rules/testing-python.md` | Add stub-fidelity cross-reference; add Hypothesis usage guidance |
| testing | `docs/agentic/rules/testing-php.md` | Add stub-fidelity guidance for Null* stubs |
| testing | `docs/agentic/rules/testing-typescript.md` | Add stub-fidelity cross-reference |
| testing | `docs/agentic/rules/testing-principles.md` | Add "Performance Evidence Requirements" section |
| review | `docs/agentic/rules/branch-review-python.md` | Add "Boundary and Runtime Correctness" section (parallel to PHP guide) |
| tests | `packages/agent-handoff-mcp/tests/test_fts5_property.py` | New: Hypothesis property-based tests for both sanitization strategies |
| config | `packages/agent-handoff-mcp/pyproject.toml` | Add `hypothesis` to test dependencies |
| epic | `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md` | Update Phase 3 checklist items |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Contains `search_handoff` phrase-quoting logic (~L1769-1780); not modified, only tested |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/artifact_index.py` | Contains `_FTS5_SPECIAL_RE` and `_build_fts5_match_query` (~L90-109); not modified, only tested |
| `packages/agent-handoff-mcp/tests/test_search_handoff.py` | Existing P-FTS-SANITIZE-01 hand-written tests; new property tests supplement these |
| `packages/agent-handoff-mcp/tests/test_artifact_index.py` | Existing FTS5 availability tests; new property tests supplement these |
| `docs/agentic/rules/branch-review-typescript.md` | Already has fresh-evidence and State Surface Correctness; reference for symmetry |
| `docs/agentic/rules/branch-review-php.md` | Already has fresh-evidence and Boundary and Runtime Correctness; reference for symmetry |
| `docs/agentic/rules/development-workflow.md` | Cross-Boundary Change Protocol step 4 (runtime-parity check); not modified |
| `apps/prototype-wp-alt-context/tests/stubs/` | PHP Null* stubs; referenced in stub-fidelity guidance but not modified |

## Verification Strategy

- Deterministic tests:
  - `PYTHONPATH=packages/agent-handoff-mcp/src python3 -m pytest packages/agent-handoff-mcp/tests/test_fts5_property.py -q 2>&1 | tee /tmp/pytest_fts5_property.txt`
  - Existing test suites still pass: `make test-handoff 2>&1 | tee /tmp/pytest_handoff_all.txt`
- Contract/fixture verification:
  - No contract changes; existing golden fixture tests unaffected
- Manual verification:
  - `branch-review-python.md` has fresh-evidence paragraph parallel to TS and PHP guides
  - `testing-principles.md` has Stub and Fake Fidelity, Runtime-Parity Verification, and Performance Evidence Requirements sections
  - Per-language testing guides cross-reference the universal stub-fidelity rules
  - `branch-review-python.md` has Boundary and Runtime Correctness section parallel to PHP guide
  - Property-based tests exercise both FTS5 sanitization strategies against the full metacharacter set

## Slice Delivery

### Slice 1: Python Review Guide Fresh-Evidence and Boundary Parity

**Goal**: Bring `branch-review-python.md` to parity with the TS and PHP review guides by adding a fresh-evidence blocking rule and a boundary/runtime-correctness section.

Changes:

- Add a fresh-evidence paragraph to the Automated Checks section in `branch-review-python.md`, parallel to the existing paragraphs in `branch-review-typescript.md` and `branch-review-php.md`. The paragraph should state that behavior-fix and performance claims require fresh `make check` or targeted `pytest` evidence on the current branch state, and that stale or absent evidence warrants a `GAP` finding.
- Add a "Boundary and Runtime Correctness" section to `branch-review-python.md` covering:
  - FastAPI dependency-injection parity between test overrides and production startup
  - SQLAlchemy session/transaction lifecycle matching production (not test-only autocommit)
  - Pydantic model validation in adapters matching the canonical contract schema
  - Degradation semantics for upstream service failures (explicit error vs silent empty-state)

Proof:

- `branch-review-python.md` has a fresh-evidence paragraph mentioning `make check`, `pytest`, and `GAP` finding for missing evidence
- `branch-review-python.md` has a "Boundary and Runtime Correctness" section with at least 4 checklist items

### Slice 2: Stub and Fake Fidelity Rules

**Goal**: Define stub-fidelity expectations so agents know when a null stub masks real runtime behavior, with universal guidance in `testing-principles.md` and per-language cross-references.

Changes:

- Add a "Stub and Fake Fidelity" section to `testing-principles.md` after the existing "Hierarchical TDD" section. Rules:
  - A stub must reproduce the real implementation's error-raising behavior for invalid inputs, not silently succeed
  - Null stubs (stubs that do nothing) are acceptable only for dependencies whose behavior is irrelevant to the test; when the test depends on the dependency's success/failure semantics, use a behavioral fake
  - When a production interface throws on invalid state, the stub must throw on the same inputs
  - Inline anonymous spy classes (as used in PHP tests) must extend the canonical null stub, not re-implement the interface from scratch
  - When a new stub is created, verify it against the real implementation's constructor signature and error paths
- Add a "Runtime-Parity Verification" section to `testing-principles.md` after Stub and Fake Fidelity. Rules:
  - For each high-risk boundary class (custom bootstrap, proxy forwarding, environment-specific loading), at least one test must exercise the real runtime path or explicitly document why it cannot
  - The cross-boundary change protocol step 4 in `development-workflow.md` already requires a runtime-parity check; this section defines what counts: class loading, dependency injection, transaction lifecycle, header/protocol forwarding, and error-shape preservation
  - If runtime-parity cannot be verified locally, record a `GAP` finding in MCP instead of claiming full verification
- Add a short cross-reference to `testing-python.md` noting the stub-fidelity rules in `testing-principles.md` and expanding "Test Mock Defaults Match Production Defaults" to reference behavioral fidelity
- Add a short cross-reference to `testing-php.md` noting that `Null*` stubs under `tests/stubs/` must follow the fidelity rules in `testing-principles.md`; when a real repository method throws on invalid cluster UUIDs, the null stub should too
- Add a short cross-reference to `testing-typescript.md` noting that MSW handlers and vi.mock factories must follow the fidelity rules in `testing-principles.md`

Proof:

- `testing-principles.md` has "Stub and Fake Fidelity" section with at least 5 rules
- `testing-principles.md` has "Runtime-Parity Verification" section with at least 3 rules
- `testing-python.md`, `testing-php.md`, `testing-typescript.md` each have a cross-reference to the stub-fidelity rules

### Slice 3: Performance Evidence Requirements

**Goal**: Define performance evidence as distributions plus queue/pool/retry metrics so agents know when an average-only claim is insufficient.

Changes:

- Add a "Performance Evidence Requirements" section to `testing-principles.md` after the existing "Performance Targets" section. This section addresses the process of capturing and reporting performance evidence, not the target values themselves. Rules:
  - Performance claims on high-risk changes must include latency distributions (p50/p95/p99), not just averages
  - Queue depth, connection-pool wait time, and retry counts must be observable and reportable for flows that involve external services or shared resources
  - Backpressure and saturation behavior must be documented: what happens when the system is overloaded, not just what happens under normal load
  - Performance evidence should be attached to MCP test results or handoff decisions with specific numbers, not narrative claims like "performance improved"
  - Incident and remediation work must distinguish between average-latency improvements and tail-latency or saturation improvements
- Add review guidance to `branch-review-python.md` (new subsection in or after Metric Thresholds): for changes touching database queries, external HTTP calls, or background task scheduling, require evidence of query execution time, connection pool metrics, or retry behavior rather than only unit-test pass/fail

Proof:

- `testing-principles.md` has "Performance Evidence Requirements" section with at least 5 rules
- `branch-review-python.md` references performance-evidence requirements for high-risk changes

### Slice 4: FTS5 Property-Based Tests

**Goal**: Add Hypothesis-driven property-based tests for both FTS5 sanitization strategies to cover the input space that hand-written tests cannot.

Changes:

- Add `hypothesis` to `packages/agent-handoff-mcp/pyproject.toml` as a test dependency in `[project.optional-dependencies]` (create the section if it does not exist, using a `test` extra)
- Create `packages/agent-handoff-mcp/tests/test_fts5_property.py` with property-based tests covering:
  - **Phrase-quoting strategy** (`core.py`): for any string input, the sanitized output must be a valid FTS5 match expression that does not raise when executed against a real FTS5 table. Properties to verify:
    - For any non-blank input, the sanitized output is a valid FTS5 phrase expression that executes without error against a real FTS5 table
    - Output never contains unquoted FTS5 metacharacters (`"`, `*`, `+`, `-`, `^`, `(`, `)`, `:`, `NEAR`)
    - Double-quotes in input are escaped by doubling (`""`)
    - Blank or whitespace-only inputs do not produce a query; the `search_handoff` caller contract returns `{ok: false, error: "All query strings are empty after stripping."}` instead
    - Unicode characters (CJK, emoji, combining marks, RTL) in non-blank inputs are preserved or safely stripped
  - **Regex-stripping strategy** (`artifact_index.py`): for any string input, `_build_fts5_match_query` produces output that does not raise when executed against a real FTS5 table. Properties to verify:
    - All FTS5 special characters from `_FTS5_SPECIAL_RE` are removed from output
    - Multi-word inputs produce AND-joined terms
    - Multiple queries produce OR-joined groups
    - Empty or whitespace-only inputs produce no match terms
  - Tests should use a real in-memory SQLite FTS5 table to verify that generated queries execute without errors
  - Use `@given(st.text())` as the primary strategy, with supplementary strategies for specific character classes (FTS5 metacharacters, Unicode categories)
  - Import the real sanitization functions; do not re-implement them in tests
  - If a property test finds an invalid live MATCH expression, harden the corresponding sanitizer in the same slice instead of weakening the property to fit the bug

Proof:

- `PYTHONPATH=packages/agent-handoff-mcp/src python3 -m pytest packages/agent-handoff-mcp/tests/test_fts5_property.py -q 2>&1 | tee /tmp/pytest_fts5_property.txt`
- Existing tests still pass: `make test-handoff 2>&1 | tee /tmp/pytest_handoff_all.txt`
- Property tests exercise at least 100 random inputs per property (Hypothesis default)

### Slice 5: Epic Status and Checklist Update

**Goal**: Update the epic Phase 3 checklist to reflect completed items and ensure consistency with implementation.

Changes:

- Check off completed Phase 3 items in the epic consolidated checklist
- Update Phase 3 status line if all items are complete
- Add this task to the Completed Tasks table if all slices are done

Proof:

- Epic Phase 3 checklist items accurately reflect completed work
- No unchecked items remain that were actually implemented
- Completed Tasks table includes this task if fully done

## Lane Decomposition (Multi-Agent)

> This task mixes documentation (Slices 1-3, 5) and test code (Slice 4).
> Single-lane execution is appropriate; the slices are sequential documentation edits plus one test-code addition.
> Multi-agent decomposition is not recommended unless the operator explicitly requests it.

---

# Consolidated Checklist

## Context and Ownership

- [x] Loaded `testing-principles.md`, `branch-review-python.md`, `testing-python.md`
- [x] Loaded TS and PHP review/testing guides for symmetry comparison
- [x] Loaded FTS5 sanitization source in `core.py` and `artifact_index.py`
- [x] Loaded existing FTS5 tests in `test_search_handoff.py` and `test_artifact_index.py`
- [x] Loaded epic Phase 3 deliverables and exit criteria

## Slice 1: Python Review Guide Fresh-Evidence and Boundary Parity

- [x] Added fresh-evidence paragraph to `branch-review-python.md` Automated Checks section
- [x] Added "Boundary and Runtime Correctness" section to `branch-review-python.md`
- [x] Section has at least 4 checklist items (DI parity, session lifecycle, Pydantic validation, degradation semantics)

## Slice 2: Stub and Fake Fidelity Rules

- [x] Added "Stub and Fake Fidelity" section to `testing-principles.md` with at least 5 rules
- [x] Added "Runtime-Parity Verification" section to `testing-principles.md` with at least 3 rules
- [x] Added stub-fidelity cross-reference to `testing-python.md`
- [x] Added stub-fidelity cross-reference to `testing-php.md`
- [x] Added stub-fidelity cross-reference to `testing-typescript.md`

## Slice 3: Performance Evidence Requirements

- [x] Added "Performance Evidence Requirements" section to `testing-principles.md` with at least 5 rules
- [x] Added performance-evidence review guidance to `branch-review-python.md`

## Slice 4: FTS5 Property-Based Tests

- [x] Added `hypothesis` to `pyproject.toml` test dependencies
- [x] Created `test_fts5_property.py` with phrase-quoting property tests
- [x] Created `test_fts5_property.py` with regex-stripping property tests
- [x] Tests use a real in-memory SQLite FTS5 table for validation
- [x] Tests exercise Unicode, FTS5 metacharacters, whitespace, and empty inputs
- [x] Existing test suite still passes after Hypothesis addition
- [x] Property tests pass: `python -m pytest tests/test_fts5_property.py`

## Slice 5: Epic Status and Checklist Update

- [x] Epic Phase 3 checklist items checked for completed work
- [x] Epic Phase 3 status updated if all items are complete
- [x] Completed Tasks table updated if all slices are done

## Review Readiness

- [x] No boundary-touching implementation is left without matching contract/doc/fixture evidence
- [x] Handoff decision records the change, verification, and any contract implications
- [x] Epic status and consolidated checklist reflect completed work

## Success Criteria

- [x] `branch-review-python.md` has fresh-evidence and boundary-parity sections matching TS and PHP guide depth
- [x] `testing-principles.md` has stub-fidelity, runtime-parity, and performance-evidence sections
- [x] Per-language testing guides cross-reference the universal stub-fidelity rules
- [x] FTS5 sanitization has Hypothesis property-based tests covering both `core.py` and `artifact_index.py` strategies
- [x] A reviewer can determine from the guides alone when a passing test suite is insufficient due to stub masking, bootstrap divergence, or average-only performance claims
