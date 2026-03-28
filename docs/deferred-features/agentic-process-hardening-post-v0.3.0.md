# Deferred: Agentic Process Hardening Post-v0.3.0

## Source

Deferred from [agentic-development-process-hardening-epic.md](../epics/v0.3.0/agentic-development-process-hardening-epic.md) (v0.3.0), `Deferred (Post-v0.3.0)` section.

## Why Deferred

The v0.3.0 process-hardening work is focused on repo-local execution discipline: startup context, contract ownership, runtime parity, review automation, selective memory, and process-quality metrics. The items below are valuable, but they either exceed the current release boundary or depend on the Phase 4/5 active work settling first.

**Prerequisite state that must exist before revisiting:**

- Phase 4 selective-memory MCP surfaces and Phase 5 remaining evaluation metrics completed and stable.
- The repo’s review-readiness, handoff, and ACE metrics patterns used long enough to show which externalized tooling is still worth building.

## Deferred Items

### Deep MCP Productization Beyond Repo Needs

> **Item**: Generalized dashboards, broader packaging/distribution changes, or external-product surfaces not required to enforce this repo’s workflow.

The current epic is about making this repo safer and easier for agents to work in. External-facing MCP productization should wait until the repo-local workflow stabilizes enough to prove which pieces are genuinely portable.

**Dependency**: active Phase 4/5 work needs to settle first so packaging efforts are based on real durable seams rather than interim repo-specific helpers.

**Likely home when activated**: a dedicated MCP productization epic or package-extraction task plan.

---

### TUI Monitoring Follow-On

> **Item**: Resume the orchestration TUI work once the review-readiness and MCP-surface patterns are stable.

The epic already notes that the TUI monitoring task has open findings and should be revisited only after Phase 4 establishes the review-readiness and MCP-surface patterns the TUI needs to reflect.

**Dependency**: completion of the remaining Phase 4/5 process-tooling work so the TUI is built on stable semantics rather than moving targets.

**Likely home when activated**: a refreshed `docs/tasks/9.0/orchestration-tui-monitoring-task-plan.md` or a follow-on orchestration UX epic.

---

### Repo-Wide Model-Quality Eval Infrastructure

> **Item**: Broader eval infrastructure that measures model quality, not just process quality.

The current epic intentionally measures workflow health, review discipline, and evidence quality. Repo-wide model evals are a different layer of work and should not be smuggled into process-hardening tasks.

**Dependency**: the process-quality layer should be stable first, so model-eval work can build on trustworthy handoff, review, and verification artifacts.

**Likely home when activated**: a dedicated eval-infrastructure epic or experimentation program.
