# Review Guide Hardening Source Crosswalk

## Purpose

Identify which ideas from `agentfactory-book`, `product-deploy-agents`, `gstack`, and the previously reviewed `superpowers` review/verification skills should be incorporated into:

- `docs/agentic/rules/branch-review-guide.md`
- `docs/agentic/rules/branch-review-typescript.md`
- `docs/agentic/rules/branch-review-php.md`
- `docs/agentic/rules/planning-review-guide.md`

This note is scoped to process improvements, not direct rule edits.

## Executive Summary

The strongest opportunities are not new checklists for their own sake. They are sharper review intake rules, stronger evidence gates, more explicit escalation between review modes, and better separation between planning review and branch review.

The current guides are already strong on correctness, contract drift, and MCP logging. The external sources mainly help in four areas:

1. make review inputs smaller and more deliberate
2. require fresh verification evidence before positive claims
3. distinguish normal branch review from higher-cost multi-lens audits
4. make plan review more spec-bound, slice-based, and proof-oriented

## What The Repo Already Does Well

- `branch-review-guide.md` already prioritizes correctness, regressions, missing tests, and contract boundaries.
- `planning-review-guide.md` already checks real code paths, ownership, greenfield policy, and stale assumptions.
- The language-specific modules already encode useful repo-local heuristics instead of generic language advice.

The gap is less about missing categories and more about workflow discipline around when review starts, what context is loaded, what evidence is required, and when the process must escalate.

## Source-Grounded Recommendations

### 1. Tighten Review Intake And Context Loading

**Why**

- `agentfactory-book` Chapter 15 argues that always-loaded context should be rare and that each workflow should load the smallest high-signal context surface needed for correctness.
- `superpowers` `requesting-code-review` explicitly passes a bounded review packet: what changed, what it should do, and the git range, instead of handing the reviewer the whole session history.

**Apply to `branch-review-guide.md`**

Add a required `Review Intake` section near the top:

- branch or commit range under review
- intended scope or task-plan reference
- authoritative contracts/ADRs/rules touched by the diff
- exact verification commands already run, if any
- whether the review is branch-level or release-audit escalation

This should make the guide explicit that reviewers load:

1. the intended change
2. the actual diff
3. the boundary contracts
4. the proof artifacts

And nothing else by default.

**Apply to `planning-review-guide.md`**

Add a parallel `Planning Intake` section:

- planning document under review
- prerequisite spec/ADR/contracts
- current implementation surfaces that the plan claims to change
- already-completed slices or dependencies

This helps prevent speculative plan review against stale or invented context.

**Sources**

- `docs/literature/process/agentfactory-book/ch-15-context-engineering-drilldown-v3.md`
- `docs/literature/process/agentfactory-book/ch-68-agent-skills-mcp-code-execution-drilldown-v2.md`
- `https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md`
- `https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/code-reviewer.md`

**MCP Tools**

| Tool | Role |
|---|---|
| `get_handoff_state` | Load active task objective, open blockers, and latest decisions at intake; the "intended scope" half of the review packet. |
| `list_review_findings(task_ref=...)` | Surface all open findings before loading the diff; prevents the reviewer from re-raising already-tracked issues. |
| `search_handoff(queries=[...], record_types=["decision"])` | Retrieve prior boundary-ownership decisions without loading the full history; replaces speculative context reconstruction. |
| `get_plan_cursor` | Confirm which slice is the subject of review; prevents reviewing a superseded slice. |
| `get_handoff_dashboard` | Quick health summary (open findings count, blocker count, latest test result) to assess whether the branch is even at a reviewable state before loading detailed context. |

### 2. Add A Fresh-Evidence Rule To Branch Review

**Why**

- The `superpowers` verification skill is unusually crisp: no completion or passing claims without fresh verification evidence.
- `agentfactory-book` Chapter 99 reinforces the same operational idea: releases need explicit thresholds and saved evidence, not confidence language.

**Apply to `branch-review-guide.md`**

Add a blocking rule:

- reviewers should treat any “done”, “fixed”, “passing”, or “ready” claim without fresh command evidence as unproven
- branch reviews must call out stale or partial verification as a finding when it changes the merge/readiness verdict

Add a small reviewer checklist:

- what command would prove the claim?
- was that command run on the current branch state?
- was the result complete or partial?
- does the output actually support the claim?

This would help catch “tests passed earlier”, “typecheck was not rerun”, or “manual spot check implies correctness” drift before merge.

**Apply to language-specific modules**

- `branch-review-typescript.md`: require fresh evidence for `typecheck`, `lint`, architecture compliance, and targeted UI tests when UI behavior is claimed fixed
- `branch-review-php.md`: require fresh evidence for PHPUnit and PHPStan, and when runtime/bootstrap behavior is touched, require a runtime-parity check in addition to unit tests

**Sources**

- `https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md`
- `docs/literature/process/agentfactory-book/ch-99-evaluation-quality-gates-drilldown-v2.md`

**MCP Tools**

| Tool | Role |
|---|---|
| `record_test_result` | The canonical evidence artifact. Every "passes" or "fixed" claim must be backed by a `record_test_result` call on the current branch state with `commit_sha` populated. |
| `get_handoff_state` | Check the `latest_verification` snapshot before accepting a review-ready status claim from another agent. |
| `record_review_finding(category="GAP", severity="HIGH")` | The correct response when evidence is stale or missing; the `fix` field should name the exact command that would close the gap. |
| `handoff_close_check` | Terminal enforcement: open HIGH findings block task close; catches missing evidence as a hard gate at merge time. |

**Gap:** No tool currently validates whether the most recent `record_test_result` for a suite was recorded on the current `commit_sha`. Evidence stamping exists, but freshness comparison requires manual agent judgment. *(Addressed in "Proposed MCP Tool Upgrades" below.)*

### 3. Distinguish Branch Review From Release-Audit Escalation

**Why**

- `product-deploy-agents` is valuable less as a day-to-day coding workflow and more as a model for multi-lens audit escalation.
- `gstack` similarly distinguishes planning, review, QA, and release-readiness instead of flattening them into one generic “review”.

**Apply to `branch-review-guide.md`**

Add an escalation section that says branch review should be upgraded to a multi-lens audit when the branch touches any of:

- security/compliance boundaries
- release/deploy paths
- major architecture transitions
- multi-service state machines
- high-risk migrations or persistence changes
- broad UI/UX surface changes with many states

The guide should name the audit lenses to pull in:

- architecture/reliability
- QA/state-matrix
- UX/state-surface
- compliance/claims, when applicable

This avoids overloading normal branch review while preserving a path for higher-risk work.

**Apply to `planning-review-guide.md`**

Require large plans to state whether they need:

- ordinary branch review only
- branch review plus specialized module review
- release-style audit before merge/release

**Sources**

- `docs/literature/process/product-deploy-agents/README.md`
- `docs/literature/process/gstack/README.md`

**MCP Tools**

| Tool | Role |
|---|---|
| `record_review_finding` | `severity=HIGH` findings are the primary escalation signal. `category=GAP` on a security or contract boundary is a natural upgrade trigger. |
| `get_review_findings_summary` | `open_high_count > 0` is a structural signal that ordinary branch sign-off is insufficient and the review must escalate. |
| `reconcile_review_findings` | Designed for batch-updating findings after a multi-pass review; in a multi-lens audit, each lens records independently and `reconcile` merges the result set. |
| `handoff_close_check` | Already hard-fails on unresolved HIGH findings, functioning as a merge gate without additional ceremony. |

**Gap:** There is no escalation-tier tag on findings. The distinction between a branch-level finding and a release-audit finding is not first-class in the schema and must be encoded narratively, which is lossy across sessions. *(Addressed in "Proposed MCP Tool Upgrades" below.)*

### 4. Make Planning Review More Spec-Bound And Slice-Oriented

**Why**

- `superpowers` separates design/spec work from execution planning.
- `agentfactory-book` Chapter 68 emphasizes that workflows are reliable when triggers, outputs, and convergence criteria are explicit.

**Apply to `planning-review-guide.md`**

Strengthen the guide to reject plans that lack:

- an upstream spec/ADR for large or cross-boundary work
- executable slices that each produce behavior plus proof
- explicit contract/doc/test changes in the same slice as the behavior
- stated stop conditions and completion evidence for each slice

Suggested additions:

- replace “phase ordering” language with “slice ordering” where the guide refers to task-plan execution
- explicitly flag scaffold-only or placeholder slices as a planning smell
- require each slice to name the files/contracts/tests it expects to touch
- require the plan to say what would constitute proof that the slice is complete

This aligns review with the repo’s current task-plan template and avoids plans that are temporally vague or verification-light.

**Sources**

- `https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md`
- `/tmp/superpowers/skills/writing-plans/SKILL.md`
- `docs/literature/process/agentfactory-book/ch-68-agent-skills-mcp-code-execution-drilldown-v2.md`

**MCP Tools**

| Tool | Role |
|---|---|
| `upsert_plan_cursor` / `get_plan_cursor` | Tracks the current slice explicitly. Every planning review should verify the cursor matches the slice being reviewed and that prior cursors have closed findings and test results. |
| `record_decision(decision="plan_authorized")` | Record the spec/ADR reference before implementation starts; creates a durable anchor for later review sessions that can be searched by boundary name. |
| `search_handoff(queries=[...], record_types=["decision"])` | Find prior boundary-ownership decisions the plan must be consistent with before implementation begins. |
| `list_review_findings(task_ref=..., status="open")` | Verify no open planning-review findings from the current plan remain unresolved before the next slice starts. |

**Gap:** `upsert_plan_cursor` currently advances without checking whether the outgoing slice has open HIGH findings or at least one recorded test result. The plan cursor is advisory only. *(Addressed in "Proposed MCP Tool Upgrades" below.)*

### 5. Formalize Review Resolution Discipline

**Why**

- `superpowers` does a good job not only on requesting review but on acting on it: fix critical items, do not proceed with important issues, push back with evidence if the reviewer is wrong.
- This is useful process language that is mostly absent from the current guides.

**Apply to `branch-review-guide.md`**

Add a `Resolving Findings` section:

- fix correctness/security/data-loss issues before proceeding
- do not hand-wave important findings into follow-up debt without an explicit rationale
- when pushing back on a finding, cite code/tests/contracts, not preference
- if a finding is deferred, log the decision and residual risk in MCP

This would give the repo a clearer norm for what happens after review, not just during review.

**Sources**

- `https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md`
- `/tmp/superpowers/skills/receiving-code-review/SKILL.md`

**MCP Tools**

The tool surface is already complete for this recommendation. The missing piece is a rule in the guide making these calls **mandatory** rather than optional.

| Tool | Role |
|---|---|
| `update_review_finding(finding_id=..., status="fixed", fix=...)` | Required action for every resolved finding. Agents who close the review without calling this are bypassing the process; the guide should state this explicitly. |
| `reopen_review_finding` | Correct call when a fix was partial or regressed; prevents silent duplicate findings accumulating over multiple review passes. |
| `record_decision(decision="finding_deferred")` | For deferred findings, with `rationale` stating explicit residual risk and the follow-up slice; replaces hand-waving into future debt. |
| `reconcile_review_findings` | Batch-close or re-open findings after a focused remediation pass; avoids N individual `update_review_finding` calls after a rapid-fix sprint. |
| `get_review_findings_summary` | Pre-close verification: confirm `open_high = 0` (or all deferrals have decision records) before accepting a merge. |

### 6. Strengthen Language-Specific Modules Around Boundary Proof

The external sources are general, but the local failures in this repo show where the modules should become sharper.

#### TypeScript / React module

Recommended additions to `branch-review-typescript.md`:

- require explicit review of empty/loading/error/degraded/offline states for changed UI surfaces
- require evidence that abort/cancel behavior does not produce noisy false warnings for expected cancellation
- require API-boundary checks for malformed JSON, partial payloads, and fallback rendering
- require proof that query invalidation/refetch behavior cannot silently regress the visible state after successful mutation

These recommendations fit the repo’s recent issues around stale polling, hidden errors, placeholder thumbnails, and disappearing projection state.

#### PHP / WordPress module

Recommended additions to `branch-review-php.md`:

- require runtime-parity review when bootstrap, controller composition, or autoload paths change
- require boundary adapter checks for header propagation, status preservation, payload metadata provenance, and no fabricated contract fields
- require explicit review of degradation semantics: when to return empty data, when to surface unavailable, and when to block

These additions would have caught several of the proxy/controller regressions earlier.

**Sources**

- `docs/literature/process/agentfactory-book/ch-99-evaluation-quality-gates-drilldown-v2.md`
- `docs/literature/process/gstack/README.md`
- `docs/literature/process/product-deploy-agents/README.md`
- previously reviewed `superpowers` verification and review skills

**MCP Tools**

These map directly onto Recs 2 and 5; no novel tool surface is needed here.

| Tool | Role |
|---|---|
| `record_test_result` | Golden payload tests, PHPUnit runtime-bootstrap checks, and TypeScript API-boundary tests each produce a `record_test_result` entry with command, output snippet, and `commit_sha`. |
| `record_review_finding(category="GAP", severity="HIGH")` | For absent boundary tests (e.g., no runtime-parity check for a changed PHP autoload path); the `fix` field names the exact test or command that would close the gap. |
| `search_handoff(queries=[...])` | Before reviewing a boundary change, search for prior decisions and findings about that boundary to avoid re-raising already-resolved issues and to locate existing contract rationale. |

### 7. Use Hooks As Lightweight Prompts, Not As The Review System

**Why**

- The upstream `superpowers` hooks are helpful as harness nudges, especially at session start.
- They are not a substitute for durable rules, contracts, handoff, or saved review evidence.

**Recommendation**

If this repo adds hooks, use them for small reminders such as:

- session start: load current task, open findings, and applicable review modules
- pre-completion: remind the agent to run verification and log MCP decisions
- pre-review: remind the agent to load intended scope plus diff plus contracts

Do not use hooks as the canonical storage for findings, evidence, or merge gates.

This maps well to the epic’s Phase 4 direction without duplicating `agent-handoff-mcp`.

**Sources**

- `docs/literature/process/agentfactory-book/ch-15-context-engineering-drilldown-v3.md`
- `docs/literature/process/agentfactory-book/ch-68-agent-skills-mcp-code-execution-drilldown-v2.md`
- previously reviewed `superpowers` hook patterns

**MCP Tools**

| Tool | Role |
|---|---|
| `get_handoff_state` | Session-start hook: load active task, open findings, and latest decisions; replaces any ad hoc session reconstruction. |
| `list_review_findings(status="open")` | Pre-review hook: surface all unresolved findings before the reviewer loads the diff. |
| `generate_current_task_md` | Post-change hook: regenerate the human-readable mirror so the next session starts from an accurate `CURRENT_TASK.md`. |
| `handoff_close_check` | Pre-completion hook: enforce the evidence gate before claiming work done; the lightest-weight placement for this call is a reminder at session end, not during review. |

## Recommended Concrete Edits By Guide

### `branch-review-guide.md`

Highest-value changes:

1. add `Review Intake`
2. add `Fresh Verification Evidence` blocking rule
3. add `Escalate To Multi-Lens Audit When...`
4. add `Resolving Findings`
5. distinguish branch review verdict from release-readiness verdict

### `planning-review-guide.md`

Highest-value changes:

1. add `Planning Intake`
2. require spec/ADR reference for larger plans
3. replace vague phase language with slice-oriented review where task plans are concerned
4. require per-slice proof surfaces
5. require the plan to declare whether branch review or release-audit escalation is expected

### `branch-review-typescript.md`

Highest-value changes:

1. explicit UI state-matrix review requirement
2. API-boundary malformed/partial-payload review requirement
3. query invalidation and polling-stability proof requirement
4. fresh evidence rule for UI fixes

### `branch-review-php.md`

Highest-value changes:

1. runtime bootstrap/autoload parity check
2. adapter provenance check for headers/status/body metadata
3. explicit degraded-vs-empty-vs-unavailable behavior review
4. fresh evidence rule for runtime-sensitive fixes

## What Not To Import Directly

- Do not copy `product-deploy-agents` into normal branch review. Its value is escalation structure, not day-to-day review weight.
- Do not copy `gstack` as a whole framework. Borrow readiness and workflow-stage language, not the entire operating model.
- Do not replace MCP handoff with hooks or prompt-only skills. Use those as wrappers and reminders around the durable process.

## Proposed MCP Tool Upgrades

Three structural gaps were identified in the current tool surface. Each is a small, backward-compatible addition. None require breaking changes to existing tool schemas.

### 1. Commit-SHA Freshness Validation on `handoff_close_check` (Gap from Rec 2)

**Problem:** `record_test_result` stamps `commit_sha` but no tool enforces that the stamped SHA matches the current branch. Evidence can be legitimately present but silently stale.

**Proposed change:** Add an optional `require_fresh_tests` parameter to `handoff_close_check`.

```
handoff_close_check(
    task_ref: str | None = None,
    require_fresh_tests: bool = False,
    current_commit_sha: str | None = None,
)
```

When `require_fresh_tests=True`, the tool fails close-check if any required test suite's latest `record_test_result` entry carries a `commit_sha` that does not match `current_commit_sha`. When `current_commit_sha` is omitted but `require_fresh_tests=True`, the tool should return an error requiring the caller to supply the SHA rather than silently skipping the check.

**Behavioral rule addition for `branch-review-guide.md`:** Before accepting a "passing" claim, the reviewer should call `handoff_close_check(require_fresh_tests=True, current_commit_sha=<HEAD>)`. A `stale_test` result is a GAP/HIGH finding.

### 2. `review_mode` Field on Review Findings (Gap from Rec 3)

**Problem:** Branch-level findings and release-audit findings are stored identically. Escalation queries require narrative parsing rather than a filter, so multi-lens audits are indistinguishable from normal review output in `get_review_findings_summary`.

**Proposed change:** Add an optional `review_mode: "branch" | "release_audit"` field to `record_review_finding`. Propagate it as a filter parameter to `list_review_findings` and `get_review_findings_summary`.

```
record_review_finding(
    ...,
    review_mode: str | None = None,   # "branch" or "release_audit"
)

list_review_findings(
    ...,
    review_mode: str | None = None,
)

get_review_findings_summary(
    ...,
    review_mode: str | None = None,
)
```

Existing findings default to `review_mode=null`, treated as `"branch"` for summary purposes. This allows `list_review_findings(review_mode="release_audit", status="open")` to return only the findings that require audit-level resolution without touching normal branch review output.

**Behavioral rule addition for `branch-review-guide.md`:** When escalating to multi-lens audit, record findings with `review_mode="release_audit"`. The merge gate should fail if `get_review_findings_summary(review_mode="release_audit")` returns `open_high > 0`.

### 3. Slice-Completion Gate on `upsert_plan_cursor` (Gap from Rec 4)

**Problem:** `upsert_plan_cursor` advances the plan position unconditionally. A reviewer cannot distinguish a cursor that moved after verified slice completion from one that moved speculatively or by mistake.

**Proposed change:** Add an optional `require_clean_slice` parameter to `upsert_plan_cursor`.

```
upsert_plan_cursor(
    ...,
    require_clean_slice: bool = False,
)
```

When `require_clean_slice=True`, the tool checks that:
1. `open_high_count == 0` for findings tagged to the current plan position
2. At least one `record_test_result` exists with a label or note referencing the current slice

If either condition fails, the tool returns `ok: false` with a structured error naming the missing gate. The caller can override by omitting the flag, which preserves existing behavior for agents that are not operating in enforced-slice mode.

**Behavioral rule addition for `planning-review-guide.md`:** Agents implementing a plan slice should call `upsert_plan_cursor(require_clean_slice=True)` when moving to the next slice. A failure is a blocking signal to run the missing verification before continuing.

## Suggested Next Step

The most effective follow-up would be a direct patch to:

1. `docs/agentic/rules/branch-review-guide.md`
2. `docs/agentic/rules/planning-review-guide.md`
3. `docs/agentic/rules/branch-review-typescript.md`
4. `docs/agentic/rules/branch-review-php.md`

using this note as the source-grounded change list. The patches to the branch-review guide should include one- or two-line mandatory tool callouts in each applicable section (e.g., "call `update_review_finding` before claiming a finding fixed; call `record_decision` before deferring one") so the MCP tool surface becomes a required step, not optional prose.

The three proposed MCP tool upgrades should be logged as next-action items against `packages/agent-handoff-mcp` once the guide patches are done: `require_fresh_tests` on `handoff_close_check` first (highest safety leverage), then `review_mode` on findings, then `require_clean_slice` on `upsert_plan_cursor`.

## Sources

- `docs/literature/process/agentfactory-book/ch-15-context-engineering-drilldown-v3.md`
- `docs/literature/process/agentfactory-book/ch-68-agent-skills-mcp-code-execution-drilldown-v2.md`
- `docs/literature/process/agentfactory-book/ch-75-augmented-memory-summary.md`
- `docs/literature/process/agentfactory-book/ch-99-evaluation-quality-gates-drilldown-v2.md`
- `docs/literature/process/product-deploy-agents/README.md`
- `docs/literature/process/gstack/README.md`
- `https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md`
- `https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md`
- `https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/code-reviewer.md`

---

## Implementation Audit

> Added 2026-03-27. Records the implementation status of every crosswalk recommendation against the actual rules files, plus an expanded audit of all `docs/agentic/rules/` files for process hardening gaps not originally covered by the crosswalk.

### Recommendation Implementation Status

Every recommendation from the crosswalk was implemented by task plan `docs/tasks/11.0/review-guide-hardening-task-plan.md` (Slices 1-5, all checked complete).

| Rec | Recommendation | Target File | Status | Implementation |
|-----|----------------|-------------|--------|----------------|
| 1 | Review Intake section | `branch-review-guide.md` | Done | `## Review Intake` added before Common Checklist; four required load surfaces |
| 1 | Planning Intake section | `planning-review-guide.md` | Done | `## Planning Intake` added before checklist; four required load surfaces |
| 2 | Fresh-evidence blocking rule | `branch-review-guide.md` | Done | `## Fresh Verification Evidence` with reviewer prompts and GAP/HIGH protocol |
| 2 | TS fresh-evidence rule | `branch-review-typescript.md` | Done | Automated Checks requires fresh `typecheck`, `lint`, and targeted Vitest evidence |
| 2 | PHP fresh-evidence rule | `branch-review-php.md` | Done | Automated Checks requires fresh PHPUnit and PHPStan for runtime-sensitive changes |
| 3 | Escalation trigger list | `branch-review-guide.md` | Done | `## Escalate To Multi-Lens Audit When` with trigger conditions and named lenses |
| 3 | Audit declaration in planning | `planning-review-guide.md` | Done | Rollout and Testability checklist item |
| 4 | Spec/ADR citation for large plans | `planning-review-guide.md` | Done | Checklist item under Rollout and Testability |
| 4 | Scaffold-only slice rejection | `planning-review-guide.md` | Done | Checklist item flagging scaffold-only slices |
| 4 | Per-slice proof surfaces | `planning-review-guide.md` | Done | Checklist items for file/contract/test naming and completion evidence |
| 5 | Resolving Findings section | `branch-review-guide.md` | Done | `## Resolving Findings` with mandatory `update_review_finding` calls per status |
| 6 | TS state-surface items (4) | `branch-review-typescript.md` | Done | `## State Surface Correctness`: UI state matrix, abort/cancel, API-boundary, query invalidation |
| 6 | PHP boundary items (4) | `branch-review-php.md` | Done | `## Boundary and Runtime Correctness`: bootstrap parity, adapter provenance, header preservation, degradation |
| 7 | Hooks as lightweight prompts | deferred | Deferred | Phase 4 guidance; not in review-guide-hardening scope |
| MCP-1 | `require_fresh_tests` on `handoff_close_check` | `core.py` | Done | Optional parameter with SHA freshness check; `test_hardening.py` |
| MCP-2 | `review_mode` on finding tools | `core.py` | Done | `review_mode TEXT` column; filter on `record/list/summary`; `test_review_mode.py` |
| MCP-3 | `require_clean_slice` on `upsert_plan_cursor` | `core.py` | Done | Optional parameter with open-HIGH and test-result gates; `test_plan_cursor_gate.py` |

### Expanded Rules File Audit

The original crosswalk scoped recommendations to four files: `branch-review-guide.md`, `planning-review-guide.md`, `branch-review-typescript.md`, and `branch-review-php.md`. The following audit covers the remaining rules files against the same process improvement themes (bounded context loading, fresh evidence, escalation paths, resolution discipline, runtime parity, boundary ownership, performance evidence).

#### `branch-review-python.md`

**Coverage**: Type safety, architecture boundaries, error handling, code duplication, metric thresholds (Radon), automated check commands.

**Gaps**:

- No fresh-evidence requirement for `pytest`, `mypy`, or `ruff` when correctness is claimed fixed. The TS and PHP guides now require this; Python does not.
- No escalation path when boundary violations (e.g., DTO in domain layer) are found.
- No resolution discipline for complexity findings (grade C flagged but no required disposition).
- No runtime-parity check for deployment vs test behavior.

**Recommendation**: Add fresh-evidence rules and resolution discipline parallel to the TS and PHP modules. Scope as follow-on in Phase 3.

#### `development-workflow.md`

**Coverage**: Slice checklists, scaffolding definition of done, TDD, commit conventions, orchestrated task execution, MCP handoff protocol.

**Gaps**:

- No blocker escalation SLA or timeline when MCP tools are unavailable or blockers go unanswered.
- No cross-lane schema/contract parity verification step before integration.
- Scaffolding verification is stated but not gated by CI or automation.

**Recommendation**: Phase 1 should address blocker SLA and cross-lane verification.

#### `testing-principles.md`

**Coverage**: Test pyramid, deterministic data, behavioral assertions, shared fakes, performance targets (150ms endpoint, Lighthouse > 90).

**Gaps**:

- Performance targets stated but no measurement gate or regression detection.
- No flaky-test escalation protocol.
- No environment parity requirements (test DB version vs production, CI vs local).
- No isolation verification between tests.

**Recommendation**: Phase 3 should address environment parity and measurement enforcement.

#### `testing-python.md`

**Coverage**: pytest async patterns, exact assertions, mock defaults, FastAPI DI patterns, test directory structure.

**Gaps**:

- No automated DI parameter-collision detection (manual grep only).
- No async test pollution detection (event loop reuse, session leaks).
- No test execution time budgets.

**Recommendation**: Phase 3 should add async isolation and DI collision automation.

#### `testing-typescript.md`

**Coverage**: Provider harness parity, hoisted mocks, mutable refs, QueryClient cleanup, MSW patterns, sovereign sync test patterns.

**Gaps**:

- No automated provider parity verification (missing MemoryRouter/QueryClientProvider).
- No QueryClient inter-test isolation detection.
- No test execution time budgets.
- MSW handlers have no timeout budgets.

**Recommendation**: Phase 3 should add provider parity and isolation gates.

#### `testing-php.md`

**Coverage**: PHPUnit framework, interface compliance, response shape enforcement, WP_Mock patterns, sovereign sync test patterns.

**Gaps**:

- No automated interface change detection (manual search for `implements`).
- No autoload validation gate after new file creation.
- WP_Mock cleanup discipline undocumented.

**Recommendation**: Phase 3 should add autoload and interface-change automation.

#### `frontend-guidelines.md`

**Coverage**: Component size limits, TypeScript safety rules, design tokens, URL state, accessibility (WCAG 2.1 AA, axe-core).

**Gaps**:

- No automated enforcement of `no non-null assertions` or design token usage.
- No Lighthouse measurement gate in CI.
- No query key centralization validation.

**Recommendation**: Phase 4 should evaluate CI guards for these.

#### `backend-python-guidelines.md`

**Coverage**: Hexagonal architecture, layer rules, standards, async patterns, Pydantic patterns, FastAPI DI, coverage targets.

**Gaps**:

- Coverage targets (80% overall, 95% critical) not CI-enforced.
- No dependency drift detection for `pyproject.toml`.
- No endpoint latency SLA.
- No definition of "critical" for the 95% coverage target.

**Recommendation**: Phase 3 should define "critical" and add measurement.

#### `backend-php-guidelines.md`

**Coverage**: Security patterns, WordPress plugin rules, sovereign sync layer, repository patterns, trait extraction, taxonomy model.

**Gaps**:

- No symmetric create/destroy CI verification.
- No automated schema-key parity validation.
- No N+1 detection automation.
- No conflict resolution latency SLA.

**Recommendation**: Phase 3 and Phase 4 should address schema parity automation and performance budgets.

### Cross-Cutting Gap Summary

| Theme | Severity | Files Affected | Epic Phase |
|-------|----------|---------------|------------|
| Fresh evidence for Python review | HIGH | `branch-review-python.md` | Phase 3 |
| Escalation SLAs across all guides | MEDIUM | `development-workflow.md`, all review guides | Phase 1 |
| CI/automated enforcement of stated rules | MEDIUM | All testing guides, `frontend-guidelines.md` | Phase 4 |
| Environment/runtime parity in tests | MEDIUM | `testing-principles.md`, all testing guides | Phase 3 |
| Performance measurement gates | MEDIUM | `testing-principles.md`, `frontend-guidelines.md`, backend guides | Phase 3 or Phase 5 |
| Cross-lane contract parity verification | MEDIUM | `development-workflow.md` | Phase 1 |
| Boundary violation escalation protocols | LOW | `branch-review-python.md`, backend guides | Phase 1 |
