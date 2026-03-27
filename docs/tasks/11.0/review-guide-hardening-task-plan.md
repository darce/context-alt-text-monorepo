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

# Review Guide Hardening

## Objective

Harden the four review guides (`branch-review-guide.md`, `planning-review-guide.md`, `branch-review-typescript.md`, `branch-review-php.md`) to enforce bounded intake, fresh-evidence requirements, escalation paths, spec-bound planning review, and explicit resolution discipline. Add three backward-compatible MCP tool upgrades to `packages/agent-handoff-mcp` that automate the evidence gates the guides now require.

## Problem Statement

The review guides are strong on correctness categories but under-specify workflow discipline. Agents currently start reviews from unbounded context, accept self-certified "passing" or "fixed" claims without stamped evidence, flatten all reviews into a single mode regardless of risk level, advance plan cursors without verifying slice completion, and resolve findings without calling the mandatory MCP update tools. This produces stale evidence in handoff, undetected regressions after merge, and lossy escalation paths for high-risk work.

The root source and crosswalk analysis is `docs/epics/v0.3.0/review-guide-hardening-source-crosswalk.md`.

## Constraints

- All guide edits are additive. Do not rewrite existing checklist sections that are already correct; add new sections alongside them.
- MCP tool changes must be backward-compatible. Existing callers without the new parameters must behave identically to today.
- `handoff_close_check`, `upsert_plan_cursor`, `record_review_finding`, `list_review_findings`, and `get_review_findings_summary` are the only MCP surfaces touched.
- The guides serve as both human-readable rules and machine-readable prompt input to `review_runner.py`. Changes must remain structured and scannable.
- No changes to `docs/agentic/instructions.md` or `CLAUDE.md` in this task; those belong to a separate Phase 1 epic deliverable.

## Workflow Principles

- Evidence before claims: every "done", "fixed", or "passing" assertion requires a `record_test_result` call with `commit_sha` on the current branch state.
- Bounded intake: reviewers load the minimum four surfaces (change intent, diff, boundary contracts, proof artifacts) and nothing else by default.
- Single resolution path: every finding lifecycle change calls `update_review_finding`; `record_decision` may add rationale but is not a substitute for the finding status update; no silent closures.
- Backward-compatible gates: new MCP enforcement flags are opt-in; existing callers are unaffected.

## Terminology

- **Review Intake**: The minimum pre-review context load: active task state, open findings, the diff, and relevant boundary contracts.
- **Fresh evidence**: A `record_test_result` entry whose `commit_sha` matches the current branch HEAD.
- **Release-audit escalation**: Upgrading from normal branch review to a multi-lens audit when the branch touches security, architecture, persistence, or multi-service state boundaries.
- **Slice-completion gate**: A check that `open_high_count == 0` across all open findings for the current lane (or task if no lane context) and at least one `verified_tests` row exists for the active task since the cursor was last set.

## Current State Analysis

- `branch-review-guide.md` starts at "Common Checklist" with no intake section. Reviewers have no required sequence for loading context before walking the checklist.
- `branch-review-guide.md` has no "Resolving Findings" section. The guide covers what to look for but not what is required after findings are recorded.
- `branch-review-guide.md` has a single review mode with no escalation path for high-risk branches.
- `planning-review-guide.md` has no Planning Intake section; reviewers have no required sequence before walking the checklist.
- `planning-review-guide.md` evaluates plans but does not require per-slice proof surfaces, explicitly reject scaffold-only slices, or require spec/ADR references for large cross-boundary plans.
- `branch-review-typescript.md` has no fresh-evidence requirement for `typecheck`, `lint`, or UI-behavior claims.
- `branch-review-typescript.md` has no explicit review items for empty/loading/error/degraded states, abort/cancel behavior, API-boundary malformed payloads, or query invalidation regression.
- `branch-review-php.md` has no fresh-evidence requirement for PHPUnit and PHPStan when runtime-sensitive behavior is claimed fixed.
- `branch-review-php.md` has no explicit runtime-parity review item for bootstrap/autoload path changes or adapter provenance checks.
- `packages/agent-handoff-mcp`: `handoff_close_check` does not validate test-result freshness against current HEAD. `record_review_finding` has no `review_mode` field. `upsert_plan_cursor` advances unconditionally without a slice-completion gate.

## Target Outcome

After this task:

1. Every review starts from a defined four-surface intake load: no ambiguous "load everything" entry point.
2. Any "passing" or "fixed" claim in a review is treated as unproven unless backed by a `record_test_result` entry on the current commit; `handoff_close_check` can enforce this as a hard gate.
3. Branch review has an explicit escalation trigger list and audit-lens catalog for high-risk branches; planning review has a parallel audit-declaration requirement.
4. Planning review explicitly rejects plans that lack per-slice proof surfaces, spec/ADR anchors for cross-boundary work, or scaffold-only slices masquerading as progress.
5. Every review session ends with a defined resolution path: `update_review_finding(status="fixed"...)` for fixed, `update_review_finding(status="deferred", resolution_notes=...)` for deferred (with optional `record_decision` for extra rationale), `reopen_review_finding` for partial or regressed fixes.
6. TypeScript review covers the four historically-regressed surface areas: UI state matrices, API-boundary malformed payloads, query invalidation stability, and abort/cancel semantics.
7. PHP review covers runtime bootstrap/autoload parity, adapter provenance, and explicit degradation semantics.
8. Three new optional MCP parameters are available: `require_fresh_tests` + `current_commit_sha` on `handoff_close_check`, `review_mode` on finding tools, and `require_clean_slice` on `upsert_plan_cursor`.

## Context Loading

- Rules: `docs/agentic/rules/branch-review-guide.md`
- Rules: `docs/agentic/rules/planning-review-guide.md`
- Rules: `docs/agentic/rules/branch-review-typescript.md`
- Rules: `docs/agentic/rules/branch-review-php.md`
- Crosswalk source: `docs/epics/v0.3.0/review-guide-hardening-source-crosswalk.md`
- Contract: `docs/agentic/contracts/agent-handoff-mcp.md`
- Tooling: `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` (for `handoff_close_check` implementation)
- Tooling: `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` (tool description strings in `TOOL_DESCRIPTIONS` dict; FastMCP derives schemas from core.py signatures)
- External docs via `ctx7` only if: inspecting the MCP Python SDK types for optional parameter declaration patterns

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `handoff_close_check` MCP tool | `packages/agent-handoff-mcp` | `docs/agentic/contracts/agent-handoff-mcp.md` | Add optional `require_fresh_tests: bool`, `current_commit_sha: str` | yes — new params are optional, default to existing behavior | `pytest packages/agent-handoff-mcp/tests/test_hardening.py` |
| `record_review_finding` MCP tool | `packages/agent-handoff-mcp` | `docs/agentic/contracts/agent-handoff-mcp.md` | Add optional `review_mode: str` field (`"branch"` or `"release_audit"`) | yes — existing callers omit the field, row defaults to `null` | `pytest packages/agent-handoff-mcp/tests/test_review_mode.py` |
| `list_review_findings` MCP tool | `packages/agent-handoff-mcp` | `docs/agentic/contracts/agent-handoff-mcp.md` | Add optional `review_mode` filter parameter | yes | same test file |
| `get_review_findings_summary` MCP tool | `packages/agent-handoff-mcp` | `docs/agentic/contracts/agent-handoff-mcp.md` | Add optional `review_mode` filter parameter | yes | same test file |
| `upsert_plan_cursor` MCP tool | `packages/agent-handoff-mcp` | `docs/agentic/contracts/agent-handoff-mcp.md` | Add optional `require_clean_slice: bool` | yes — default `False` preserves existing behavior | `pytest packages/agent-handoff-mcp/tests/test_plan_cursor_gate.py` |

## Proposed Solution

Four guide doc patches (Slice 1–4) followed by three MCP tool additions (Slice 5). Guide patches are independent of each other and of the MCP changes; MCP changes are independent of each other. All five slices can be implemented in any order, but the guide patches should land first so the behavioral rules give the MCP changes their rationale.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Process rules | `docs/agentic/rules/branch-review-guide.md` | Add `Review Intake`, `Fresh Verification Evidence`, `Escalate To Multi-Lens Audit When`, `Resolving Findings` sections |
| Process rules | `docs/agentic/rules/planning-review-guide.md` | Add `Planning Intake` section; strengthen Planning Review Checklist with spec/ADR, per-slice proof, and scaffold-smell items; add audit-declaration requirement |
| Process rules | `docs/agentic/rules/branch-review-typescript.md` | Add 4 new checklist items: UI state matrix, API boundary malformed/partial payloads, query invalidation regression, abort/cancel semantics; add fresh-evidence rule |
| Process rules | `docs/agentic/rules/branch-review-php.md` | Add 4 new checklist items: runtime bootstrap/autoload parity, adapter provenance, degradation semantics, fresh-evidence rule for runtime-sensitive fixes |
| MCP implementation | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Add freshness check in `handoff_close_check`; add `review_mode` column to `review_findings` and filter propagation; add `require_clean_slice` guard in `upsert_plan_cursor` |
| MCP API surface | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Update `TOOL_DESCRIPTIONS` dict entries to mention new optional parameters; no explicit schema changes needed since FastMCP derives schemas from `core.py` function signatures |
| MCP contract doc | `docs/agentic/contracts/agent-handoff-mcp.md` | Document new parameters in the Tool Surface section |
| MCP tests | `packages/agent-handoff-mcp/tests/test_hardening.py` | Add tests for `require_fresh_tests` behavior |
| MCP tests | `packages/agent-handoff-mcp/tests/` | Add `test_review_mode.py` for `review_mode` filter behaviors |
| MCP tests | `packages/agent-handoff-mcp/tests/` | Add `test_plan_cursor_gate.py` for `require_clean_slice` behaviors |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` (schema + migration) | `review_mode TEXT` column must be added to **both** `HANDOFF_SCHEMA_SQL` (fresh DBs) and `_apply_handoff_migrations` (existing DBs, guarded by `_has_column` check). No data backfill needed; `NULL` is valid and treated as `"branch"` mode. No separate migration file or Alembic step required — the existing `_apply_handoff_migrations` mechanism handles it automatically on first connection. Greenfield policy: older `handoff.db` rows may have `NULL`; no retroactive fill required. |
| `docs/agentic/instructions.md` | References both guides; no changes here but verify cross-references remain accurate after guide edits |
| `docs/agentic/rules/branch-review-python.md` | Not in scope; does not need fresh-evidence or boundary-proof changes in this task |
| `CLAUDE.md` | References branch-review and planning-review triggers; verify trigger patterns still match updated guide structure |

## Verification Strategy

- Deterministic tests:
  - `cd packages/agent-handoff-mcp && pyenv exec python -m pytest tests/test_hardening.py tests/test_review_mode.py tests/test_plan_cursor_gate.py -q`
- Guide structural check (no automation; agent manual review):
  - Confirm `branch-review-guide.md` has all four new sections in logical order (Intake before Checklist, Resolving Findings after Checklist)
  - Confirm `planning-review-guide.md` has Planning Intake before the checklist and audit-declaration in the Rollout section
  - Confirm `branch-review-typescript.md` new items include command evidence requirements, not just checklist text
  - Confirm `branch-review-php.md` new items cite the bootstrap runtime path explicitly
- Contract/fixture verification:
  - `agent-handoff-mcp --workspace-root $(pwd) doctor` — verify schema migration applied, FTS5 still healthy
  - `grep_search(query="require_fresh_tests|review_mode|require_clean_slice", includePattern="docs/agentic/contracts/agent-handoff-mcp.md")` — verify contract doc updated (Codex fallback: `grep -n 'require_fresh_tests\|review_mode\|require_clean_slice' docs/agentic/contracts/agent-handoff-mcp.md`)
- Manual verification:
  - Call `handoff_close_check(require_fresh_tests=True, current_commit_sha="abc123")` in a test session and confirm it fails when no `record_test_result` with that SHA exists

---

## Slice Delivery

### Slice 1: Branch Review Guide — Intake, Evidence Gate, Escalation, Resolution

**Goal**: Add four new sections to `branch-review-guide.md` that bound the review entry point, enforce a fresh-evidence rule, define an escalation trigger list, and codify a resolution discipline.

Changes:

- Add `## Review Intake` section at the top of `branch-review-guide.md` (after "How to Use This Guide", before "Common Checklist") requiring reviewers to load: branch/commit range, task-plan or intended-scope reference, touched contracts/ADRs, commands already run, and escalation mode
- Add `## Fresh Verification Evidence` blocking rule: any "done", "fixed", "passing", or "ready" claim without a `record_test_result` entry on the current commit is treated as unproven; stale or partial verification is a `GAP/HIGH` finding
- Add `## Escalate To Multi-Lens Audit When` section listing the trigger conditions (security/compliance, release/deploy paths, major architecture, multi-service state machines, high-risk persistence, broad UX surfaces) and the named audit lenses (architecture/reliability, QA/state-matrix, UX/state-surface, compliance/claims)
- Add `## Resolving Findings` section specifying: `update_review_finding(status="fixed", ...)` is mandatory for every fixed finding; `update_review_finding(status="deferred", resolution_notes=...)` is mandatory for deferrals (an optional `record_decision` call may add extra rationale but does not replace the status update); `reopen_review_finding` for partial or regressed fixes; `get_review_findings_summary` as the pre-close verification step

Proof:

- `grep_search(query="Review Intake|Fresh Verification Evidence|Escalate To Multi-Lens Audit|Resolving Findings", includePattern="docs/agentic/rules/branch-review-guide.md")` returns four matches (Codex fallback: `grep -n` with the same pattern)

### Slice 2: Planning Review Guide — Intake, Slice-Orientation, Audit Declaration

**Goal**: Add Planning Intake to `planning-review-guide.md` and strengthen the checklist to reject temporally vague, scaffold-heavy, or evidence-light plans.

Changes:

- Add `## Planning Intake` section before the checklist requiring: planning document under review, prerequisite spec/ADR/contracts, current implementation surfaces the plan claims to change, already-completed slices or dependencies; load these four surfaces and nothing else before walking the checklist
- Add to Planning Review Checklist under "Rollout and Testability": require spec/ADR citation for cross-boundary or large-surface plans; flag scaffold-only or placeholder slices as a planning smell; require each slice to name files/contracts/tests expected to change; require the plan to state completion evidence per slice
- Add audit-declaration item to the Rollout and Testability checklist: the plan must declare whether it requires ordinary branch review, branch review plus specialized module review, or release-style audit before merge
- Replace "phase ordering" language with "slice ordering" in any existing rollout/sequencing items

Proof:

- `grep_search(query="Planning Intake|spec/ADR|scaffold-only|audit", includePattern="docs/agentic/rules/planning-review-guide.md")` returns at least five matches (Codex fallback: `grep -n` with the same pattern)

### Slice 3: TypeScript Review Guide — UI States, API Boundary, Query Stability, Fresh Evidence

**Goal**: Add four checklist items and a fresh-evidence rule to `branch-review-typescript.md` covering the surface areas that produced the most regressions in recent handoff history.

Changes:

- Add fresh-evidence rule to the Automated Checks section: when a UI-behavior fix is claimed, `typecheck` + `lint` + targeted Vitest run must each have a `record_test_result` entry on the current branch commit before the fix claim is accepted
- Add to a new `## State Surface Correctness` section (or append to Frontend Patterns):
  - `[ ] **UI state matrix** — changed UI surfaces must explicitly cover empty, loading, error, degraded, and offline states; a state with no rendering branch is a GAP/MEDIUM`
  - `[ ] **Abort/cancel semantics** — abort or cancel paths must not produce console warnings or error UI for expected cancellation; only unexpected cancellations should surface errors`
  - `[ ] **API-boundary payload validation** — components receiving API payloads must handle malformed JSON, partial payloads, and missing optional fields without producing white-screen or unhandled-rejection behavior`
  - `[ ] **Query invalidation regression** — after a successful mutation, verify that query invalidation and refetch cannot silently leave the UI showing stale pre-mutation state`

Proof:

- `grep_search(query="UI state matrix|Abort/cancel|API-boundary payload|Query invalidation regression", includePattern="docs/agentic/rules/branch-review-typescript.md")` returns four matches (Codex fallback: `grep -n` with the same pattern)

### Slice 4: PHP Review Guide — Bootstrap Parity, Adapter Provenance, Degradation, Fresh Evidence

**Goal**: Add four checklist items and a fresh-evidence rule to `branch-review-php.md` covering the boundary failure patterns seen in the 502 audit and proxy regression work.

> **Common-checklist overlap note**: `branch-review-guide.md` already has "PHP runtime autoload parity" (line 81) and "Boundary metadata preservation" (line 78) as general-principle items. The items below are **not duplicates**; they add PHP-specific WordPress runtime verification steps, PHPStan + PHPUnit fresh-evidence rules tied to runtime-parity claims, and concrete controller/proxy header-propagation checks that the common checklist does not detail. The implementing agent should frame these as "stack-specific expansions" that reference the common principle.

Changes:

- Add fresh-evidence rule to the Automated Checks section: when runtime-sensitive behavior is claimed fixed (bootstrap paths, controller composition, proxy forwarding), PHPUnit and PHPStan must have `record_test_result` entries on the current commit; a unit-test pass alone is not sufficient when the fix affects a runtime load path
- Add to a new `## Boundary and Runtime Correctness` section (or append to existing Sovereign Sync section):
  - `[ ] **Runtime bootstrap/autoload parity** — when bootstrap, controller composition, or autoload paths change, verify the behavior matches under the real WordPress load path, not only under the PHPUnit bootstrap fallback`
  - `[ ] **Adapter provenance** — boundary adapters must not invent envelope fields (`limit`, `offset`, `total`, `data_source`, status metadata); every field must trace to the request, the upstream payload, or a documented fallback; fabricated fields are a GAP/HIGH finding`
  - `[ ] **Header and status preservation** — proxy controllers must propagate the upstream HTTP status code and relevant headers without normalizing or suppressing them; check forwarded `Content-Type`, `X-*` headers, and error status codes`
  - `[ ] **Degradation semantics** — for each error path, verify explicitly whether the contract requires returning empty data, surfacing unavailable, or blocking; returning `[]` when the upstream is 502 is not the same as returning `unavailable`; the choice must match the downstream consumer's contract`

Proof:

- `grep_search(query="Runtime bootstrap|Adapter provenance|Header and status preservation|Degradation semantics", includePattern="docs/agentic/rules/branch-review-php.md")` returns four matches (Codex fallback: `grep -n` with the same pattern)

### Slice 5: MCP Tool Upgrades — Fresh-Evidence Gate, Review Mode, Slice-Completion Guard

**Goal**: Implement three backward-compatible additions to `packages/agent-handoff-mcp` that automate the evidence gates the guide patches describe.

Changes:

- **`handoff_close_check` freshness gate** (`core.py` + `api.py`):
  - Add optional `require_fresh_tests: bool = False` and `current_commit_sha: str | None = None` parameters
  - When `require_fresh_tests=True` and `current_commit_sha` is supplied, check that at least one `verified_tests` row for the active task exists with `commit_sha = current_commit_sha`; if none exists, return `ok: false` with a structured `stale_test` error; older rows with different SHAs are ignored and do not cause failure — only the absence of any fresh row on the current commit does
  - When `require_fresh_tests=True` but `current_commit_sha` is omitted, return `ok: false` with `error: "current_commit_sha required when require_fresh_tests=True"` rather than silently skipping the check
  - Tests: verify pass when at least one row with current SHA exists (even if older rows also exist with prior SHAs), fail when no row with current SHA exists, error when SHA omitted with flag set, and no change in behavior when flag omitted

- **`review_mode` field on findings** (`core.py` + `api.py`):
  - Add `review_mode TEXT` column to `review_findings` table (nullable; existing rows default to `null`, treated as `"branch"`)
  - Propagate as an optional parameter to `record_review_finding`, `list_review_findings`, and `get_review_findings_summary`
  - `list_review_findings(review_mode="release_audit")` returns only findings with `review_mode = "release_audit"`
  - `get_review_findings_summary(review_mode="release_audit")` counts only audit-mode findings
  - Tests: verify `review_mode=null` rows appear in unfiltered list but not in `review_mode="release_audit"` filtered list; verify summary counts are separated

- **`require_clean_slice` guard on `upsert_plan_cursor`** (`core.py` + `api.py`):
  - Add optional `require_clean_slice: bool = False` parameter
  - When `True`, check two conditions using data the schema can actually query: (a) `open_high_count == 0` among open `review_findings` rows scoped to the cursor's `lane_id` if present, otherwise scoped to the active `task_ref`; (b) at least one `verified_tests` row exists for the active task since the cursor's `updated_at` timestamp
  - No plan-item-to-finding linkage is added; the gate is intentionally coarse — lane-wide or task-wide — because the current schema has no per-slice finding bucketing
  - If either condition fails, return `ok: false` with a structured error listing the missing gate(s); the caller can override by omitting the flag
  - Tests: verify pass when both conditions met (lane-scoped and task-wide variants), fail with structured error for each missing gate independently, and no change in behavior when flag omitted

- Update `docs/agentic/contracts/agent-handoff-mcp.md` Tool Surface section to document the three new parameter groups

Proof:

- `cd packages/agent-handoff-mcp && pyenv exec python -m pytest tests/test_hardening.py tests/test_review_mode.py tests/test_plan_cursor_gate.py -q` passes with all new test cases
- `grep_search(query="require_fresh_tests|review_mode|require_clean_slice", includePattern="docs/agentic/contracts/agent-handoff-mcp.md")` returns at least three matches (Codex fallback: `grep -n` with the same pattern)

---

## Lane Decomposition (Multi-Agent)

> The five slices decompose cleanly by ownership. Slices 1–4 are docs-only and can run in parallel. Slice 5 is `packages/agent-handoff-mcp` only. No lane needs files from another lane.

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `docs-guides` | `docs/agentic/rules/branch-review-guide.md`, `docs/agentic/rules/planning-review-guide.md`, `docs/agentic/rules/branch-review-typescript.md`, `docs/agentic/rules/branch-review-php.md` | None | String-search verification per slice (`grep_search` or terminal `grep`) |
| `mcp-upgrades` | `packages/agent-handoff-mcp/src/**`, `packages/agent-handoff-mcp/tests/**`, `docs/agentic/contracts/agent-handoff-mcp.md` | None | `pytest` per test file above |

### Merge Order

1. `docs-guides` (no code risk; provides rationale for reviewers of MCP changes)
2. `mcp-upgrades` (depends on guide behavioral rules being readable before code review)

### Manifest

```bash
make lane-manifest-init TASK=review-guide-hardening LANE_IDS='docs-guides mcp-upgrades' TASK_PLAN=docs/tasks/11.0/review-guide-hardening-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries above.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

---

# Consolidated Checklist

## Context and Ownership

- [x] Loaded branch-review-guide.md, planning-review-guide.md, branch-review-typescript.md, branch-review-php.md, and agent-handoff-mcp.md before editing.
- [x] Confirmed external `ctx7` not required; all changes are local to this repo's rule surface and MCP package.
- [x] Recorded boundary ownership in Contract and Boundary Impact table (all five MCP tool changes declared).

## Slice 1: Branch Review Guide — Intake, Evidence Gate, Escalation, Resolution

- [x] `## Review Intake` section added before Common Checklist; lists the four required load surfaces.
- [x] `## Fresh Verification Evidence` blocking rule added; defines "unproven" and the GAP/HIGH finding protocol.
- [x] `## Escalate To Multi-Lens Audit When` section added with trigger list and named audit lenses.
- [x] `## Resolving Findings` section added with mandatory `update_review_finding`, `record_decision`, `reopen_review_finding`, and `get_review_findings_summary` steps.
- [x] String-search verification (`grep_search` or terminal `grep`): four section headers present in the file.

## Slice 2: Planning Review Guide — Intake, Slice-Orientation, Audit Declaration

- [x] `## Planning Intake` section added before the checklist with four required load surfaces.
- [x] Checklist items added for spec/ADR citation, scaffold-only smell, per-slice file/contract/test naming, and slice completion evidence.
- [x] Audit-declaration item added to Rollout and Testability checklist.
- [x] "Phase ordering" language replaced with "slice ordering" where present.
- [x] String-search verification (`grep_search` or terminal `grep`): at least five new strings present.

## Slice 3: TypeScript Review Guide — UI States, API Boundary, Query Stability, Fresh Evidence

- [x] Fresh-evidence rule added to Automated Checks section.
- [x] Four new state-surface checklist items added: UI state matrix, abort/cancel semantics, API-boundary payload validation, query invalidation regression.
- [x] String-search verification (`grep_search` or terminal `grep`): four checklist item labels present.

## Slice 4: PHP Review Guide — Bootstrap Parity, Adapter Provenance, Degradation, Fresh Evidence

- [x] Fresh-evidence rule added to Automated Checks section.
- [x] Four new boundary/runtime checklist items added: runtime bootstrap/autoload parity, adapter provenance, header and status preservation, degradation semantics.
- [x] String-search verification (`grep_search` or terminal `grep`): four checklist item labels present.

## Slice 5: MCP Tool Upgrades

- [x] `handoff_close_check` accepts `require_fresh_tests` and `current_commit_sha`; fails on stale SHA; errors cleanly when SHA omitted with flag set.
- [x] `review_findings` table has `review_mode` column; `record_review_finding`, `list_review_findings`, and `get_review_findings_summary` accept and filter on it.
- [x] `upsert_plan_cursor` accepts `require_clean_slice`; fails with structured error when open HIGH findings or no test result exist for current slice.
- [x] `docs/agentic/contracts/agent-handoff-mcp.md` updated with all three new parameter groups.
- [x] All new pytest tests pass: `test_hardening.py`, `test_review_mode.py`, `test_plan_cursor_gate.py`.
- [x] `agent-handoff-mcp doctor` passes after schema change.

## Review Readiness

- [x] No guide section added that contradicts existing checklist items; new sections are additive.
- [x] MCP changes have backward-compatible defaults verified by tests that invoke each tool without the new parameters.
- [x] Handoff decision records the change, verification, and contract implications for the MCP slice.

## Stretch Goals

- [x] Add a new `.agent/workflows/review-intake.md` shortcut that calls `get_handoff_state` + `list_review_findings(status="open")` + `get_plan_cursor` in one step as the canonical pre-review hook.

## Success Criteria

- [x] A reviewer following `branch-review-guide.md` loads exactly four context surfaces before the checklist; nothing in the guide implies loading more.
- [x] A claim of "tests are passing" on a branch with a stale `record_test_result` SHA is either automatically caught by `handoff_close_check(require_fresh_tests=True)` or manually flagged as GAP/HIGH by the reviewer using the guide's blocking rule.
- [x] A plan with scaffold-only slices or no per-slice proof surfaces is flagged as a planning smell by the updated checklist.
- [x] The PHP and TypeScript guides provide specific, named checklist items for the four boundary failure categories each (not generic "check boundary" language).
- [x] All new MCP pytest tests pass; `doctor` is clean; existing tests are unaffected.
