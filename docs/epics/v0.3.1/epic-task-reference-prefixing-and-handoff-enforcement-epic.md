# E12. Epic and Task Reference Prefixing and Handoff Enforcement (v0.3.1)

> **Epic Short ID**: E12

## Objective

Introduce a compact, deterministic reference scheme for epics, task plans, roadmaps, and handoff decisions so agents and reviewers can refer to work unambiguously without long opaque IDs. The scheme must be documented in the repo guidance, reflected in the planning templates, and enforced by `agent-handoff-mcp` for new handoff decisions and context-routing helpers.

## Problem Statement

Epics and task plans currently have human-readable titles but no guaranteed short references. That makes cross-agent review, handoff search, and decision archaeology more brittle than necessary: one agent may cite a path, another may cite a task ref, and a third may rely on an informal shorthand that is not globally unique.

Handoff decisions have the same ambiguity. The current `slice_complete_<short_label>` convention is useful for packet derivation, but it does not carry a stable work reference or an author tag in the decision id itself. As the repo grows, that makes it harder to scan decision history, grep for related work across docs and MCP state, and verify that guidance and runtime naming rules are aligned.

## UX Vision

When a new epic is created, its title starts with the next global epic number using the compact `E**` form, for example `E12. Epic and Task Reference Prefixing and Handoff Enforcement`. Each epic also declares the compact id used for local task references, and every task plan under that epic uses a compact local task reference in its title, for example `E12-1. Define the naming schema`.

When an agent records a handoff decision, the decision string itself is compact but self-describing. Reviewers can immediately see who authored it and which work item it belongs to, for example `cdx_slice_complete_E12-1_gate-validation`. MCP validation rejects malformed new decision ids, and the repo guidance/templates teach the same format the runtime enforces. When an agent reviews or creates planning docs, the workflow also deterministically routes it to the correct guide or template based on intent and target path.

## Constraints

- Prefixes must remain compact and human-scannable. Global epic numbering is acceptable; UUID-like identifiers are not.
- Epic numbering is global across all `docs/epics/**/**-epic.md` files. Task numbering is local to the owning epic and must be paired with that epic's short id.
- Slice review packet derivation and current `slice_complete_*` handoff semantics must continue to work after the decision format evolves.
- The repo must enforce loading the correct review guide or planning template based on context, not rely on memory or best effort.
- Guidance, templates, and MCP enforcement must land together; documentation-only naming rules are not sufficient.
- Existing historical docs and decisions should be grandfathered where practical. The enforcement target is new work, not a repo-wide rename-first migration.

## Terminology

- **Epic index**: The next global sequential number across all prior epic files, rendered in the epic title as `E<number>`, for example `E12.`.
- **Epic short id**: The compact identifier used for local task references under one epic, typically the epic id itself, for example `E12`.
- **Task reference**: A local task identifier composed of the epic short id and a per-epic sequence number, for example `E12-1`.
- **Decision author tag**: A short lowercase tag derived from the authoring agent, for example `cdx`, `cop`, `cla`, or `gem`.
- **Slice reference**: An optional task-local reference such as `E12-1/S1`. This epic evaluates slice prefixes and recommends keeping them optional rather than mandatory in headings/titles.
- **Context router**: The rule or MCP helper that selects the correct review guide or planning template based on request intent and target artifact path.

## Current State

- Epic titles are descriptive but not globally numbered.
- Task plans often use file paths or directory numbers as de facto identifiers, but those are not consistently reflected in the title.
- Handoff decision ids rely on local freeform labels and do not consistently embed author or work references.
- `slice_review_packet.py` and close/review gates currently assume a `slice_complete_*` decision prefix.
- Templates exist for epics, task plans, and roadmaps, but they do not encode a reference scheme today.
- The repo relies on instruction text to tell agents when to load `branch-review-guide.md`, `planning-review-guide.md`, `EPIC.template.md`, `TASK_PLAN.template.md`, or `ROADMAP.template.md`, but there is no explicit context-routing helper or audit surface that proves the correct guide/template was loaded.

## Target Architecture

The repo uses one compact naming stack across planning docs and handoff:

- Epic titles: `E<number>. <Title>`
- Epic metadata near the top of the doc: `Epic Short ID: <SID>`
- Task plan titles: `<SID>-N. <Title>`
- Roadmap titles remain versioned titles, but roadmap creation must explicitly load `ROADMAP.template.md` through the same context-routing flow.
- Slice headings: keep existing `Slice 1`, `Slice 2`, etc. Optional compact references such as `<SID>-N/S1` may be used when cross-doc or handoff citation is needed, but they are not mandatory in every slice heading or filename.
- Handoff decisions:
  - slice-complete decisions: `<agent_tag>_slice_complete_<work_ref>_<slug>`
  - other structured decisions: `<agent_tag>_<work_ref>_<slug>`

This preserves the existing semantic signal that a decision is a slice completion while adding compact provenance and work linkage. MCP becomes the enforcement layer for decision strings and context routing, while docs/templates become the authoring layer for epic/task naming.

### Design Decisions

| Decision | Rationale |
| --- | --- |
| `E<number>` prefix for epic titles | Epics are few enough that one repo-wide sequential number stays compact and meaningful, and the `E` prefix makes the token visually distinct from task refs. |
| Local task numbering with epic short id | Tasks need uniqueness without repeating long prose labels everywhere. `E12-1` is short, grep-friendly, and directly tied to the owning epic id. |
| No mandatory slice prefix in titles/headings | Task plans already organize slices locally. Requiring `E12-1/S1` on every slice heading would add noise with limited value. Keep slice references optional for cross-doc and handoff citation only. |
| Decision ids carry both author and work reference | Review history becomes easier to scan, and decisions become more self-describing outside the immediate task context. |
| Preserve `slice_complete` semantics inside the decision id | Existing slice review packet and close-check flows depend on detecting completion decisions; the new format should extend that behavior, not replace it with an unrelated grammar. |
| Enforce guide/template loading through context routing | The right planning surface should be selected from request intent and target path, not from chat memory. This keeps review and doc-authoring behavior auditable and consistent. |
| Grandfather old records; enforce new writes | Retro-renaming all prior docs and handoff rows would be expensive and noisy. New work should follow the scheme, while historical data remains readable. |

### Data Model

- **Epic source of truth**: the checked-in epic document title plus a required short-id field near the top of the epic.
- **Task source of truth**: the checked-in task plan title plus the owning epic short id and local task number.
- **Roadmap source of truth**: the checked-in roadmap title, backed by the roadmap template when a new roadmap is created.
- **Decision source of truth**: the `decisions.decision` field in `handoff.db`, validated on write for new records and parsed by downstream review helpers.
- **Context-routing source of truth**: request intent (`review` vs `create/update`) plus target artifact path (`docs/epics/`, `docs/tasks/`, `docs/roadmaps/`, or code review scope).
- **Enforcement flow**:
  - templates and rules tell authors how to create epic/task titles and decision ids
  - a context router loads the correct review guide or template for the active request
  - MCP validates new decision ids and exposes lint/audit output for malformed new writes
  - slice review packet logic recognizes the new prefixed `slice_complete` pattern

## Phased Delivery

### Phase 1: Naming Spec and Template Update -- not-started

> **Status**: not-started
> **Task plans**: [E12-1. Naming Spec and Template Update](../../tasks/12.0/12.1/E12-1-naming-spec-and-template-update-task-plan.md)

**Goal**: Define the compact naming scheme and make new epic/task/roadmap authoring follow it by default.

Deliverables:

- Define the canonical epic title format (`E<number>.`), epic short-id rule, and task title format.
- Update [EPIC.template.md](../../agentic/templates/EPIC.template.md) to require the global epic number in the title and a declared epic short id.
- Update [TASK_PLAN.template.md](../../agentic/templates/TASK_PLAN.template.md) to require the `<epic_short_id>-<local_index>. <Title>` task title format.
- Update [ROADMAP.template.md](../../agentic/templates/ROADMAP.template.md) so roadmap creation is routed through an explicit template load, even though roadmap titles do not adopt the task-ref scheme.
- Document the slice-prefix evaluation and explicitly state that slice references are optional, not mandatory, in titles/headings.

Exit criteria:

- New epic authors have one documented title pattern and one short-id rule to follow.
- New task plan authors have one documented title pattern tied to the owning epic short id.
- The templates no longer allow unnumbered new epic titles or unprefixed new task titles by omission.

### Phase 2: Guidance Rollout -- not-started

> **Status**: not-started
> **Task plans**: [E12-2. Guidance Rollout and Context Routing](../../tasks/12.0/12.1/E12-2-guidance-rollout-and-context-routing-task-plan.md)

**Goal**: Synchronize the repo rules and author guidance with the naming scheme.

Deliverables:

- Update [instructions.md](../../agentic/instructions.md) with the new epic/task naming rules and decision-id grammar.
- Update [development-workflow.md](../../agentic/rules/development-workflow.md) so planning and execution guidance reference the same naming scheme.
- Update any planning-review guidance that needs to check for missing or malformed epic/task references.
- Add explicit context-routing rules that require loading:
  - [branch-review-guide.md](../../agentic/rules/branch-review-guide.md) for code/diff review requests
  - [planning-review-guide.md](../../agentic/rules/planning-review-guide.md) for epic/task/roadmap/ADR review requests
  - [EPIC.template.md](../../agentic/templates/EPIC.template.md), [TASK_PLAN.template.md](../../agentic/templates/TASK_PLAN.template.md), or [ROADMAP.template.md](../../agentic/templates/ROADMAP.template.md) when creating those artifact types
- Add a short examples section showing one numbered epic title, one task title, one valid handoff decision id, and one context-routing decision table.

Exit criteria:

- The docs tell agents how to compute the next epic index, how to form a task title, and how to name a decision.
- Guidance no longer implies that `slice_complete_<short_label>` alone is the full target format for new work.
- The correct review guide or planning template can be chosen deterministically from the request type and target path.

### Phase 3: MCP Enforcement and Parsing -- not-started

> **Status**: not-started
> **Task plans**: [E12-3. MCP Decision Enforcement and Context Router](../../tasks/12.0/12.1/E12-3-mcp-decision-enforcement-and-context-router-task-plan.md)

**Goal**: Enforce the new decision-id format and make guide/template routing auditable.

Deliverables:

- Extend `record_decision` validation so new decision ids must include an author tag and work reference.
- Preserve or update slice-completion detection so `handoff_close_check` and `get_latest_slice_review_packet` recognize the new prefixed `slice_complete` pattern.
- Add helper validation/parsing utilities for decision author tags, work references, and slice-complete detection.
- Add a context-routing helper or equivalent MCP-visible audit surface that can answer "which guide/template is required for this request?" from intent + target path.
- Add doctor/audit output that reports malformed new decision ids or missing/incorrect context-routing evidence where enforcement is not yet hard-fail.

Exit criteria:

- New malformed decision ids are rejected or clearly surfaced by MCP.
- Slice packet generation still resolves the latest completed slice under the new decision format.
- Close/review gates still work for valid new slice-complete decisions.
- Review/doc-authoring flows have one deterministic guide/template selection rule instead of relying on freeform prompt memory.

### Phase 4: Migration Policy and Audit Pass -- not-started

> **Status**: not-started
> **Task plans**: [E12-4. Migration Policy and Audit Pass](../../tasks/12.0/12.1/E12-4-migration-policy-and-audit-pass-task-plan.md)

**Goal**: Prevent partial rollout drift with one explicit grandfathering rule and one lightweight compliance checklist.

Deliverables:

- Add one explicit rule that historical docs and historical decision rows are grandfathered by default unless a concrete artifact blocks review or tooling.
- Add a lightweight audit checklist for new epics/task plans so reviewers can verify the numbering rules were followed.
- Update any contract text that still documents the old decision-only naming rule for new work.

Exit criteria:

- The repo has a clear old-vs-new rule without planning a broad backfill.
- Reviewers can tell whether a new epic/task/decision is compliant without reading tribal-memory notes.

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| Decision on epic short-id style (manual choice vs constrained derivation) | @daniel | Not started | Phase 1 template finalization |
| Agreement on grandfathering scope for historical docs/decisions | @daniel | Resolved by E12-4 plan (grandfathered by default) | none |

## Code Anchors

| Layer | File | Note |
| --- | --- | --- |
| Epic template | `docs/agentic/templates/EPIC.template.md` | New `E<number>` epic title and short-id requirements live here |
| Task template | `docs/agentic/templates/TASK_PLAN.template.md` | New task title format lives here |
| Roadmap template | `docs/agentic/templates/ROADMAP.template.md` | Context router must load this for roadmap creation |
| Agent guidance | `docs/agentic/instructions.md` | Primary author guidance for epic/task/decision naming |
| Workflow rule | `docs/agentic/rules/development-workflow.md` | Execution-time rule surface for consistent use |
| Review guides | `docs/agentic/rules/branch-review-guide.md`, `docs/agentic/rules/planning-review-guide.md` | Context router must choose between these based on review intent |
| MCP decision writes | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | `record_decision` validation and close-check semantics |
| Slice packet parsing | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/slice_review_packet.py` | Must recognize the new prefixed slice-complete decision format |
| MCP contract | `docs/agentic/contracts/agent-handoff-mcp.md` | Documents the decision-id contract agents are expected to satisfy |

---

# Consolidated Checklist

## Phase 1: Naming Spec and Template Update -- not-started

- [ ] Define the canonical `E<number>` epic title, epic short id, and task title formats
- [ ] Update `EPIC.template.md`
- [ ] Update `TASK_PLAN.template.md`
- [ ] Update `ROADMAP.template.md`
- [ ] Document the slice-prefix recommendation as optional-only

## Phase 2: Guidance Rollout -- not-started

- [ ] Update `instructions.md`
- [ ] Update `development-workflow.md`
- [ ] Update any planning-review guidance that checks planning-doc hygiene
- [ ] Add explicit context-routing rules for review guides and planning templates
- [ ] Add examples for epic, task, decision, and context-routing cases

## Phase 3: MCP Enforcement and Parsing -- not-started

- [ ] Validate new decision ids in `record_decision`
- [ ] Preserve slice-complete detection for close/review flows
- [ ] Add parsing helpers for author tag and work reference
- [ ] Add a context-routing helper or audit surface
- [ ] Add doctor or audit output for malformed new decision ids and missing context routing

## Phase 4: Migration Policy and Audit Pass -- not-started

- [ ] Decide grandfathering scope for historical docs and decisions
- [ ] Update any stale contract/rule text that still documents the old format
- [ ] Add a reviewer audit checklist for new epics/task plans

## Deferred (Post-v0.3.1)

- [ ] Auto-generate the next epic index and task index through a dedicated MCP helper instead of computing them manually from checked-in docs.
- [ ] Add an optional slice-reference field to slice review packets if cross-doc slice citation becomes common enough to justify it.
