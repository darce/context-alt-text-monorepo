# Agent Handoff MCP Tool Surface: Context Budget Evaluation

> Assessment of how much prompt/context budget the `agent-handoff-mcp` surface consumes, what the prior consolidation work already achieved, which tools appear to deliver the most value, and which parts of the surface should likely move out of the default profile.

**Date:** 2026-03-30
**Scope:** `packages/agent-handoff-mcp`, handoff contracts, related consolidation plans, and durable handoff ledger signals available in `.task-state/handoff.db`
**Method:** Review the live MCP registry, contract docs, prior consolidation plans, and current handoff/review-coverage state to separate high-frequency ledger workflows from specialist or maintenance-only surfaces.

---

## Executive Summary

The primary context-budget problem is not the attached package folder itself. The larger fixed prompt cost comes from exposing the full MCP tool surface and its descriptions to every session, even when most sessions need only a narrow subset.

This repo already completed the highest-payoff consolidation pass: the original monolithic server exposed 62 MCP tools, and the post-split `agent-handoff-mcp` contract now exposes 27 tools while moving orchestration, lane management, daemon lifecycle, and turn metrics to `agent-orchestrator-mcp`.

The next payoff is not another large semantic merge. Most obvious duplicates have already been removed. The better next move is profile-based exposure:

- Keep a small default ledger profile for hot-path work.
- Move maintenance and artifact tooling out of the default profile.
- Keep compound ceremony tools because they reduce round trips and prompt churn.
- Add real tool-invocation telemetry if future pruning decisions need hard usage data instead of inference.

---

## Findings

### F1: The biggest remaining context cost is the default tool surface, not the package attachment

Attaching `packages/agent-handoff-mcp` provides structure and targeted-read access, but it does not inject the full contents of the package into prompt context. The more expensive recurring payload is the MCP tool catalog itself: names, descriptions, and argument shapes that must be available to the model each session.

The repo already identified this exact cost during the server-split work:

- the old monolith exposed 62 MCP tools and cost roughly 2,500 tokens per session in tool descriptions
- the split targeted a focused core ledger server under 22 tools and a separate orchestration server
- the shipped contract now documents 27 tools for `agent-handoff-mcp`

**Implication:** Further context-budget gains should focus on reducing which tools are exposed by default, not on avoiding package-folder attachments when the work is actually about this package.

### F2: The repo already performed the highest-value consolidation pass

The split-and-consolidation task merged or removed the most obvious redundancies:

- `reopen_review_finding` was absorbed into `update_review_finding`
- `get_review_finding` behavior was absorbed into `list_review_findings`
- dashboard reads were folded into `get_handoff_state(view="dashboard")`
- artifact read/list helpers were merged into `get_artifact` and `search_artifacts`
- two compound tools were added: `load_session` and `close_slice`

This matters because it changes the pruning question. The remaining tool count is not mostly accidental duplication. It is mostly the deliberate core ledger surface after the large split was already done.

**Implication:** Another broad merge wave would likely blur semantics more than it would save context.

### F3: Durable historical data records outcomes, not MCP tool invocations

The handoff schema stores durable workflow artifacts:

- task state
- decisions
- blockers
- next actions
- verified tests
- review findings
- task archives
- review runs
- artifact sources and search indexes

It does **not** currently store a canonical `tool_invocations` ledger or equivalent per-tool call counters. As a result, historical tool use can only be inferred indirectly from rows written by specific workflows.

Examples:

- high decision/finding/test row counts imply heavy use of the core ledger workflow
- review-run rows imply adoption of `record_review_run` and `get_review_coverage`
- artifact rows imply adoption of artifact indexing/search
- zero or near-zero rows in a table imply low practical adoption of that workflow

This is directionally useful, but it cannot answer precise questions such as:

- how often agents chose `load_session` instead of separate reads
- whether `search_handoff` replaced broad state reloads
- how often maintenance tools were actually used versus merely documented

**Implication:** Hard pruning decisions are currently evidence-informed, not telemetry-driven.

### F4: Core ledger workflows still dominate the durable evidence

The prior consolidation plan captured strong evidence that the core ledger is where almost all durable value lives:

- 992 decisions
- 1383 findings
- 530 tests
- 0 turn-metrics rows at that time

That evidence justified moving orchestration and metrics out of the core server. Current repo-scoped state still shows active use of decisions and tests, and no open findings on `__repo__`, while review coverage is only partially adopted depending on subject.

Recent live signals remain uneven:

- `__repo__` currently has recent decisions and tests but no review-run coverage rows
- newer planning subjects such as `E12-8` do have review-run coverage
- repo-level historical planning documents often still have zero review coverage unless explicitly backfilled

**Implication:** Decisions, tests, findings, and state reads are the safest “always-on” surfaces. Review coverage tools are valuable, but adoption is newer and less universal.

### F5: Compound tools deliver outsized value relative to their surface cost

Two tools stand out as strong context savers rather than context consumers:

- `load_session(task_ref=None)` combines `get_handoff_state` and open-findings lookup into one call
- `close_slice(...)` combines decision recording, handoff-state update, and markdown regeneration into one call

These compound tools replace repeated multi-call ceremony that would otherwise cost more prompt space, more tool selection overhead, and more opportunities for partial or inconsistent state updates.

**Implication:** Compound tools should stay in the default surface. They pay for their own description cost.

### F6: `search_handoff` is high-value because it prevents full-history replay

Workflow guidance in the repo explicitly tells agents to prefer targeted handoff search over replaying full task history into the prompt during mid-task re-entry.

That makes `search_handoff` strategically important even if it is not the most frequently called tool. It serves the exact problem this report is about: context budget control.

**Implication:** `search_handoff` should remain in the default surface, and future telemetry should specifically measure whether it is displacing repeated broad `get_handoff_state` loads.

### F7: Maintenance and artifact tools are the best candidates to leave the default profile

Some tools are useful but not hot-path for ordinary implementation, review, or documentation sessions.

The strongest candidates to remove from the default profile are:

- `export_handoff_state`
- `import_handoff_state`
- `archive_task_state`
- `record_artifact`
- `search_artifacts`
- `get_artifact`
- `purge_artifacts`

These are not bad tools. They are specialized tools. Their main issue is opportunity cost: they take tool-description budget in sessions that will never touch exports, archival, or artifact indexing.

**Implication:** These tools likely belong in a maintenance or artifact profile instead of the always-on default profile.

### F8: Review-run and review-coverage tools are valuable, but they are not yet universal

The review-run ledger (`record_review_run`, `list_review_runs`, `get_review_coverage`) solves real problems:

- explicit review coverage
- exact-id finding lookup support
- subject-level review visibility without reading decision prose

However, current live usage suggests the pattern is still spreading rather than universal. Newer tasks use it; older repo-scoped review subjects often do not.

**Implication:** These tools should remain available, but a split between a default ledger profile and a review-enhanced profile is justified if context budget becomes more constrained.

---

## What To Keep In The Default Surface

These tools appear to provide the highest value per description byte:

- `set_handoff_state`
- `get_handoff_state`
- `record_decision`
- `update_next_actions`
- `list_next_actions`
- `record_test_result`
- `report_blocker`
- `record_review_finding`
- `batch_record_review_findings`
- `update_review_finding`
- `list_review_findings`
- `load_session`
- `close_slice`
- `search_handoff`
- `generate_current_task_md`
- `handoff_close_check`

Rationale:

- they cover the dominant ledger workflows already visible in durable state
- they are required for normal task execution, review, and handoff hygiene
- several of them reduce rather than increase total ceremony (`load_session`, `close_slice`, `batch_record_review_findings`, `search_handoff`)

---

## What To Move Out Of The Default Surface

### Maintenance Profile

- `export_handoff_state`
- `import_handoff_state`
- `archive_task_state`
- `audit_decision_ids`

These are valuable for migrations, cleanup, audits, and operator workflows, but they are not required in most day-to-day coding sessions.

### Artifact Profile

- `record_artifact`
- `search_artifacts`
- `get_artifact`
- `purge_artifacts`

These are best when the workflow actively deals with large logs, long outputs, or retained analysis blobs. They are not necessary in typical code-edit sessions.

### Optional Review-Enhanced Profile

- `record_review_run`
- `list_review_runs`
- `get_review_coverage`

These should remain available somewhere because they add real structure, but they could be separated from the lean default profile if minimizing tool-schema size becomes a hard requirement.

---

## Recommended Profile Split

### 1. `agent-handoff-mcp-lean`

Default for most coding sessions.

Suggested contents:

- task state
- decisions
- actions
- blockers
- tests
- review findings
- `load_session`
- `close_slice`
- `search_handoff`
- `generate_current_task_md`
- `handoff_close_check`

### 2. `agent-handoff-mcp-review`

Opt-in for planning review, branch review, and coverage tracking.

Suggested additions:

- `record_review_run`
- `list_review_runs`
- `get_review_coverage`

### 3. `agent-handoff-mcp-maintenance`

Opt-in for migrations, exports, archival, and artifact workflows.

Suggested contents:

- export/import/archive tools
- artifact tools
- decision-id audit tools

This approach preserves semantics while reducing default context load.

---

## Missing Telemetry

The main remaining blind spot is the lack of first-class tool-invocation history.

If future pruning decisions need hard evidence instead of inference, add one of these:

### Option A: Worker JSONL aggregation

Record MCP tool calls in worker/orchestrator JSONL logs and periodically aggregate them into reports.

Benefits:

- no schema changes to handoff DB
- useful for short-term operator analysis

Limitations:

- logs are less canonical than DB state
- historical retention may vary

### Option B: `tool_invocations` ledger in `handoff.db`

Add a minimal table such as:

- `tool_name`
- `task_ref`
- `lane_id`
- `session`
- `invoked_at`
- optional `success`

Benefits:

- canonical durable usage history
- exact ranking of hot-path versus cold-path tools
- direct evidence for future consolidation work

Limitations:

- adds schema and write volume
- should stay intentionally small and avoid payload logging

---

## Recommended Next Steps

1. Keep the current semantic surface intact for core ledger tools; do not pursue another large merge cycle.
2. Introduce profile-based MCP registration so maintenance and artifact tools are not loaded into every session by default.
3. Preserve `load_session`, `close_slice`, `batch_record_review_findings`, and `search_handoff` in the lean/default profile.
4. Add explicit tool-usage telemetry before any further major pruning, ideally through worker JSONL aggregation first and a DB ledger only if needed.
5. Re-run this evaluation after enough review-run adoption exists to determine whether review coverage should stay default or move to a review-only profile.

---

## Evidence Sources

- Live tool registry: `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`
- Core compound/search implementations: `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`
- Review-run/coverage implementations: `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py`
- Core contract: `docs/agentic/contracts/agent-handoff-mcp.md`
- Prior split/consolidation plan: `docs/tasks/12.0/12.1/E12-5-mcp-server-split-and-tool-consolidation-task-plan.md`
- Repo workflow guidance on targeted handoff search: `docs/agentic/instructions.md`
- Historical evaluation prompt on search-vs-state reload behavior: `docs/tasks/11.0-closed/evaluation-and-release-audit-layer-task-plan.md`