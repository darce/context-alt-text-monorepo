# Planning Review Guide

> **Purpose:** Structured review checklist for task plans, epics, roadmaps, ADRs, and other planning documents before implementation or approval.
> Planning reviews are document-and-codebase reviews, not branch-diff reviews.

## Quick Navigation

Use this guide when reviewing:

- assessment reports
- specs
- task plans
- epics
- roadmaps
- ADRs
- implementation plans
- scope/dependency/deferred-work documents

For code diffs and working tree reviews, use [branch-review-guide.md](branch-review-guide.md) instead.

---

## How to Use This Guide

### Scope

Review the planning document against:

1. the current codebase
2. adjacent planning docs and contracts
3. already-completed prerequisite phases
4. the stated success criteria and rollout expectations

The goal is to catch stale assumptions, impossible scope, contradictory sequencing, and unnecessary complexity before implementation starts.

Project-wide constraint to apply during review:

- This repo is currently treated as a greenfield project unless a task explicitly documents an exception.
- Plans should prefer clean rewrites over backward-compatibility shims.
- Schema changes should target the baseline migration file rather than adding follow-on migrations unless an exception is documented.
- Storage migration/preservation work should be treated as suspect by default because there is no production data to preserve.

### Agent Procedure

1. Read the planning document.
2. Check the referenced code paths and adjacent plans/contracts that the document depends on.
3. Record each finding in MCP handoff before mentioning it in chat.
4. Cite concrete file and line references for both the plan and the current implementation it contradicts.
5. Prefer findings about correctness, scope realism, and architecture ownership over stylistic doc feedback.

Hard rule for agent responses:

- Do not present a planning-review finding in chat unless it has already been recorded in MCP with a stable `finding_id`.
- **Never paste a finding list into the planning document under review.** Findings live in `agent-handoff-mcp` (`review_findings(review={"operation":"record"|"batch_record", ...})`); the document under review is not a place to mirror them. The `scripts/hooks/guard-task-plan-findings.py` PreToolUse hook rejects any Edit/Write that introduces three or more consecutive bulleted lines opening with a finding-style identifier. See [branch-review-guide.md § Review Findings Placement](branch-review-guide.md#review-findings-placement-mandatory) for the full rule and the AHMCP-14 incident that motivated enforcement.

---

## Planning Intake

Before walking the checklist, load only the minimum planning packet:

1. the planning document under review
2. the prerequisite spec, ADR, and contract surfaces it depends on
3. the current implementation surfaces the plan claims to change
4. the already-completed slices, dependencies, or adjacent plans that constrain sequencing

Required intake details:

- planning document path
- prerequisite assessment/spec/ADR/contracts
- current implementation anchors
- completed slices or dependency state
- expected review mode after implementation: ordinary branch review, specialized module review, or release-style audit
- scope source: `slice_packet` when reviewing the latest completed planning slice, otherwise a direct doc/codebase review

Avoid speculative review against broad repo context. If the plan cannot be evaluated from these surfaces, name the missing dependency as the finding.

### Latest Planning Slice Review

When the ask is "review the latest completed planning slice", prefer the MCP-backed slice packet over ad hoc git or chat archaeology:

1. Request the latest slice packet with `review_kind="planning"`.
2. Use packet `changed_files` as the planning review scope when the packet returns `scope_source="slice_packet"`.
3. Confirm the packet is docs-only before treating it as a planning slice; mixed doc-plus-code slices should fall back to branch review.
4. If no valid planning packet exists, say the review is using fallback scope instead of implying deterministic latest-slice coverage.

Planning review is still a document-and-codebase review, but the packet-backed file set should define which planning surfaces belong to the latest completed slice.

---

## Planning Review Checklist

### Current-State Accuracy

- [ ] Current-state claims match the actual codebase.
- [ ] "Already implemented" items are actually implemented.
- [ ] "Missing" items are still actually missing.
- [ ] Existing contracts, schemas, and service ownership are described accurately.

### Internal Consistency

- [ ] Problem statement, current-state section, checklist, and success criteria do not contradict each other.
- [ ] Deferred/stretch items do not conflict with "done" or success-criteria language.
- [ ] Slice ordering matches stated prerequisites and dependencies.
- [ ] Terminology is consistent with current ADRs/contracts.
- [ ] Review findings and handoff action items are tracked exclusively in MCP handoff state, not duplicated into the task plan. Task plans define scope and checklists; MCP is the single source of truth for review findings, blockers, and agent-recorded decisions. Embedding handoff items in the plan creates drift when findings are resolved or reopened.

### Architecture and Ownership

- [ ] Proposed changes belong to the named service/layer and do not duplicate existing ownership.
- [ ] New handlers/endpoints are added to the correct boundary.
- [ ] The plan does not re-implement behavior that already exists in another service or adapter.
- [ ] Compound operations have an explicit contract for atomicity, idempotency, and conflict ownership.
- [ ] Boundary-touching slices identify the owning contract and the canonical boundary owner explicitly.
- [ ] Plans state whether compatibility is actually required; greenfield default is no compatibility shim unless an exception is documented.

### Contract and Data Model Realism

- [ ] Proposed request/response fields exist or are explicitly added in the same scope.
- [ ] Proposed conflict/version semantics match the current storage model.
- [ ] Multi-entity operations define which entity/version drives conflict detection.
- [ ] Schema changes are sufficient for the reporting/metrics the plan promises.
- [ ] Migration strategy matches the repo's greenfield policy: baseline schema edits, no preservation-only data migrations, and no backward-compatibility shims unless the task explicitly justifies an exception.
- [ ] If a slice changes a boundary field or payload shape, the plan updates the shared schema/fixture and owning contract in the same slice.
- [ ] If a remediation plan cites a `finding_id`, that id resolves to a real MCP finding or a concrete code site before implementation begins.

### Interface and API Realism

- [ ] Pseudocode functions and helper references map to actual existing APIs/imports or are explicitly marked as new code to create.
- [ ] Enum values, status strings, and filter parameters used in the plan exist in the actual API/schema (not invented names that the API will reject).
- [ ] API capabilities assumed by the plan (e.g., server-side filtering by a specific field) actually exist; client-side workarounds are noted if not.
- [ ] Files listed for modification actually require code changes; verification-only files are flagged as such.
- [ ] Code location references use function/target names, not brittle line numbers.

### Naming and Reference Compliance

- [ ] Epic title uses the `E<number>. <Title>` format with the correct global sequential index.
- [ ] Epic declares an `Epic Short ID` near the top of the document.
- [ ] Task plan title uses the `<EpicShortID>-<N>. <Title>` format matching the owning epic's short id, or a documented package/project-local task id when the plan is not epic-owned.
- [ ] Decision ids referenced in the plan follow the `<author_tag>_<kind>_<work_ref>_<slug>` grammar.
- [ ] Historical docs and decisions are treated as grandfathered; the plan does not mandate retroactive renames unless a concrete artifact blocks tooling or review.

### Planning Pipeline and Lifecycle Compliance

Full pipeline reference: [planning-pipeline.md](planning-pipeline.md). Epic lifecycle reference: [development-workflow.md](development-workflow.md#planning-pipeline-and-document-lifecycle).

- [ ] **Pipeline stage appropriate.** The artifact matches its pipeline position: assessments surface problems without prescribing solutions, specs define testable changes, ADRs resolve design uncertainty, task plans define executable slices. Artifacts that mix responsibilities across stages should be split.
- [ ] **Upstream traceability present.** Spec items trace to assessment findings. Task plan slices trace to spec items or epic phase deliverables. ADRs reference the blocked spec item. If the plan skips stages (e.g., direct task plan without spec), the justification is stated or the work is small/well-understood enough that the skip is self-evident.
- [ ] **Exit gates satisfied for upstream stages.** A task plan derived from a spec should not be created until the spec's review gate has been passed. A task plan derived from an ADR should not be created until the ADR is reviewed. Check MCP for review evidence if claimed.
- [ ] **Epic-to-task decomposition sound.** Each epic phase maps to one or more task plans. Task plans do not span multiple epic phases unless explicitly justified. Phase ordering in the epic matches task plan dependency ordering.
- [ ] **Target branch declared.** Task plans declare a `Target Branch` in metadata (e.g., `feature/e15-1-security-baseline`). Code implementation must happen on this branch, not on `main`. Plans that omit a target branch should be flagged.
- [ ] **Version directory consistent.** Epics are filed under `docs/epics/v<version>/` matching their target release milestone. Task plans reference the correct epic path. Carry-forward notes are present when work migrated from an older epic.

### Rollout and Testability

- [ ] The plan can be implemented incrementally without leaving impossible intermediate states.
- [ ] Cross-boundary or large-surface work cites the governing spec/ADR, not just the task plan itself.
- [ ] Each slice names the files, contracts, and tests it expects to touch.
- [ ] Each slice states what proof makes that slice honestly complete.
- [ ] Scaffold-only or placeholder slices are rejected as progress theater unless they deliver executable value in the same slice.
- [ ] The plan declares the expected review path: ordinary branch review, specialized module review, or release-style audit.
- [ ] Tests validate real behavior, not placeholder scaffolding.
- [ ] Manual/E2E-only steps are not used to hide core correctness gaps.
- [ ] Success criteria are objectively testable from code and tests.

### Complexity Control

- [ ] The plan reuses existing abstractions where appropriate.
- [ ] New abstractions are justified by real seams, not hypothetical future flexibility.
- [ ] Scope is minimal for the stated phase goal.
- [ ] Stretch work is truly optional and not required for the phase to be honestly complete.

### Tech Debt Awareness

These items prevent plans from compounding known structural debt documented in `docs/tasks/tech-debt/refactoring-*.md`.

- [ ] **God-object growth budgeted.** If the plan adds logic to a class/component already exceeding ~400 lines (e.g., `cluster_repository.py`, `ClusterMutationsController.php`, `SyncStatusIndicator.tsx`), it must either (a) include extraction work to keep the file under threshold, or (b) explicitly note the debt increase with a follow-up reference.
- [ ] **New domain concepts typed, not stringly.** Plans introducing new status values, operation types, or domain identifiers must define them as enums / value objects / `as const` types, not raw strings. If the plan's pseudocode uses bare string comparisons, flag it.
- [ ] **Transaction/boilerplate duplication avoided.** Plans adding new PHP mutation endpoints must specify using the shared `run_transactional()` wrapper, not inlining transaction management.
- [ ] **Hook/component decomposition considered.** Plans adding significant UI logic to a single component or hook should verify the target is not already flagged as a god component; if so, the plan should scope the new logic into a focused sub-hook or sub-component.
- [ ] **Design token surfaces used.** Plans specifying new UI elements with explicit visual properties (colors, shadows, font sizes, radii) must reference `--acx-*` design tokens, not raw values. If the plan invents a new visual property, it should include adding the token to the shared surface.

---

## Finding Categories

Use the same categories as branch review:

- **ANTIPATTERN**: works conceptually but pushes the system toward the wrong structure
- **DEAD_CODE**: obsolete doc paths, stale assumptions, or plans for code paths that no longer exist
- **COMPLEXITY**: unnecessary abstraction or over-scoped implementation
- **GAP**: missing contract, test, migration, dependency, or rollout detail

---

## Severity Guidance

- **HIGH**: the plan cannot be implemented correctly as written, or it assigns work to the wrong architectural owner
- **MEDIUM**: the plan is implementable but likely to cause regressions, churn, or contradictory completion status
- **LOW**: cleanup, wording drift, or minor sequencing/documentation gaps

---

## MCP Handoff Integration (MANDATORY for Agents)

For every finding, call `record_review_finding` / `review-record` with:

| Parameter     | Value                                                                                                                               |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `finding_id`  | Short ID matching the report (e.g., `E12-PLAN-01`)                                                                                  |
| `severity`    | `high`, `medium`, or `low`                                                                                                          |
| `file_path`   | Planning doc path (monorepo-relative)                                                                                               |
| `description` | One-paragraph description with evidence from the plan. **ACE rule citation:** if the finding confirms or contradicts a `[sr-NNN]` or `[rg-NNN]` rule from `instructions.md`, include the rule ID in the description (e.g., "contradicts [rg-009] no task-specific logic in generic modules"). |
| `session`     | Current session identifier                                                                                                          |
| `task_ref`    | The task ref owning the plan (may differ from the currently active task; pass explicitly)                                           |
| `details`     | Nested object: `{ "line_start"?: int, "line_end"?: int, "fix"?: str }` -- **must be nested, NOT top-level parameters**              |
| `actor`       | Nested object: `{ "agent"?: str, "model"?: str, "model_label"?: str, "reasoning_level"?: str, "branch"?: str, "commit_sha"?: str }` |

> **Schema contract**: `line_start`, `line_end`, and `fix` MUST be inside the `details` object. Passing them as top-level parameters fails with a schema validation error ("must NOT have additional properties").

After the review:

1. Confirm findings with `list_review_findings` or `get_review_findings_summary`.
2. Record a verdict decision with `record_decision` summarizing the review (finding count by severity, verdict). **The verdict decision must cite the decision number of the artifact under review** (e.g., "review of decision #966") so the reviewed artifact and its review are bidirectionally linked in handoff search.
3. If requested, patch the plan to resolve the findings.
4. Regenerate `CURRENT_TASK.md` using `generate_current_task_md(task_ref=<active-task-ref>)`. Always pass the **currently active** task's ref, NOT the reviewed plan's task ref. If findings were recorded against a non-active task (using explicit `task_ref` on write tools), still regenerate with the active task's ref so `CURRENT_TASK.md` reflects the live working state.
5. Include `Handoff updated: yes` in the final response.

---

## Output Expectations

Prioritize findings in this order:

1. obsolete assumptions
2. architecture/ownership mistakes
3. greenfield-policy violations (unnecessary migrations, compatibility shims, preservation work)
4. contradictory scope or checklist logic
5. contract gaps
6. unnecessary complexity

Do not spend review time on prose polish unless it affects implementation correctness.
