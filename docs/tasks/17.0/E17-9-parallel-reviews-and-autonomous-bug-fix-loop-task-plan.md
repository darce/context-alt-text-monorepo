# E17-9. Parallel Branch Reviews + Autonomous Bug Fix Loop

- **Date**: 2026-04-16
- **Author**: Claude Opus 4.7
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-9`
- **Review Coverage Target**: 2

---

## Objective

Land the two new workflows identified in [docs/assessments/parallel-reviews-and-autonomous-debug-assessment-2026-04-16.md](../../assessments/parallel-reviews-and-autonomous-debug-assessment-2026-04-16.md):

1. A parallel-branch-review coordinator that fans out to N ephemeral reviewers via the host subagent primitive (Claude Code Agent tool, `codex exec` subprocess, or `run_structured_turn` copilot bridge) and merges their findings under one coordinator `task_ref` via `review_findings(operation="merge", ...)`.
2. An autonomous bug-fix loop that uses Bounded Handoff Reads, `handoff_close_check(enforce=True, require_fresh_tests=True)` as the convergence gate, and cache-TTL-aware cadence to iterate on a failing test until the fix lands without spending a task-plan's worth of tokens per iteration.

Also close one loose CI back-reference from E17-7 Slice 4: a drift guard that prevents `DASHBOARD.md` from reappearing in tracked non-archive paths.

## Why This Is Separate

This plan was split out of E17-7 to keep E17-7's charter focused on evolving _existing_ primitives (schema, traces, tool compression, Codex portability). The parallel-review and auto-fix workflows add _new_ user-facing workflow surface — two skills, two portable commands, a coordinator protocol, cross-vendor adapter tests. Folding them into E17-7 would roughly double that plan's scope and delay its merge. This plan depends on E17-7 Slices 2 (multi-active-task registry), 4 (tool compression), and 5 (`review_findings.merge` + `(lane, status)` index); once E17-7 merges, this plan can start.

E17-8 is a different task (branch-isolation edit-guard hardening). This plan is independent of E17-8.

## Problem Statement

Three gaps remain after E17-7 lands:

1. **Parallel review is not a first-class workflow**: today's branch reviews serialize — one reviewer, one pass, one finding set. The motivating assessment identified the host subagent primitive (Agent tool / `codex exec` / `run_structured_turn`) as the correct fan-out mechanism for bounded ephemeral reviews — 1-2 orders of magnitude cheaper than worker-daemon orchestration for the same work — but no skill or portable command wraps it. Parent coordination, reviewer `task_ref` scoping, and merge fan-in are ad-hoc and prone to race or silent-drop when agents improvise.

2. **Autonomous bug fixing leaks tokens**: `handoff_close_check(enforce=True, require_fresh_tests=True)` is already a sound convergence gate for an auto-fix loop, but without Bounded Handoff Reads (`sections="identity"`, `detail="summary"`, low `top_n_*`) and cache-TTL-aware cadence each iteration pays a 5-30K token tax that compounds across tens of iterations. No skill or portable command codifies the bounded loop, so agents repeatedly re-invent it under-disciplined.

3. **`DASHBOARD.md` drift has no CI home**: E17-7 Slice 4 Proof references a guard that "lives in E17-9 Slice 4" — this plan supplies that home, so the drift cannot silently reappear after the rename lands.

## Constraints

- The host subagent primitive is the default fan-out mechanism for this plan's workflows. Worker daemons (`dispatch_lane_work(start_worker=True)`) remain available on `agent-orchestrator-mcp` for long-running continuous-polling scenarios the assessment explicitly identified (multi-hour operator pipelines, not bounded reviews).
- The pattern must be vendor-agnostic at the skill level. Per-vendor adapters live behind one `SubagentAdapter` protocol interface. A skill does not know which adapter fulfils it; only the adapter knows the vendor-specific primitive (Claude Agent tool, Codex `codex exec`, Copilot `run_structured_turn`).
- Each parallel reviewer writes findings under its own scoped `task_ref` (convention: `<coordinator-task-ref>-REV-<letter>`). The coordinator calls `review_findings(review={"operation":"merge","source_task_refs":[...],"target_task_ref":"<coordinator>"})` (added in E17-7 Slice 5) to unify them. No reviewer writes directly under the coordinator `task_ref` while another reviewer is still running.
- Auto-fix loop must call `get_handoff_state(sections="identity")` between iterations, per CLAUDE.md Bounded Handoff Reads rule. `detail="full"` mid-loop is a rule violation.
- Auto-fix loop cadence must respect Anthropic prompt-cache TTL: `ScheduleWakeup(delaySeconds<270)` when actively polling a near-term signal; `delaySeconds>=1200` for idle waits; 300s is explicitly forbidden (worst-of-both: cache miss without amortization).
- Convergence gate for auto-fix loop is `handoff_close_check(enforce=True, require_fresh_tests=True)` — not test-command exit status alone. A loop that exits on green tests without the close-check can pass in isolation but fail the pre-merge gate.
- New skills and commands flow through the existing `config/agent-workflows/portable_commands.json` contract; Claude, VS Code, and Codex adapters are regenerated via `scripts/generate_agent_workflows.py` (extended in E17-7 Slice 1).
- No new MCP servers. Coordination is a skill, not a daemon.
- No expansion of the advertised MCP tool count. The coordinator and auto-fix loop use existing compound tools (after E17-7 Slice 4 compression); `review_findings` gains `operation="merge"` in E17-7 Slice 5 but the tool count is unchanged.

## Current State Analysis

- `dispatch_lane_work(start_worker=True)` polls at 30s intervals and re-reads full handoff state per cycle ([packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon.py:817](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon.py)); per-cycle overhead makes it unsuitable for bounded ephemeral reviews.
- `open_handoff_items_kwargs()` in [packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/handoff_read_shapes.py:15](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/handoff_read_shapes.py) defaults `top_n_*=500` — a real token sink if invoked per loop iteration.
- `run_structured_turn` exists on `agent-orchestrator-mcp` as a synchronous bridge primitive usable from any harness.
- The host subagent primitive differs per vendor: Claude Code exposes the `Agent` tool built in; Codex exposes `codex exec` as a subprocess CLI; Copilot exposes `run_structured_turn` over MCP.
- `.claude/skills/branch-review/SKILL.md` exists but runs sequentially under one `task_ref`.
- `.claude/skills/investigate/SKILL.md` exists but has no bounded-loop or convergence-gate discipline — each iteration is agent-driven with whatever reads the agent chooses.
- `review_findings.merge` and `idx_review_findings_lane_status` land in E17-7 Slice 5 (prerequisite).
- `handoff_close_check(enforce=True, require_fresh_tests=True)` already enforces the pre-merge convergence criteria an auto-fix loop needs to treat as "done".
- `config/agent-workflows/portable_commands.json` already drives eight commands; adding two more follows the existing pattern.
- E17-7 Slice 4 Proof at [docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md:303](E17-7-handoff-evolution-and-portable-workflow-task-plan.md) points forward to "E17-9 Slice 4" for the `DASHBOARD.md` CI guard.

## Target Outcome

- `/review-parallel` skill + portable command fan out to N reviewers via the host subagent primitive, scope each reviewer to its own `task_ref`, and synthesize via `review_findings.merge` under the coordinator `task_ref`.
- `/auto-fix` skill + portable command execute a bounded loop around a failing test: write the smallest candidate fix, run the test, record the result, check `handoff_close_check`; exit on pass or after a configurable iteration cap. Per-iteration reads stay bounded.
- Cross-vendor adapter tests prove equivalence: the same MCP state results whether the reviewer subagents come from Claude Code Agent tool, `codex exec`, or `run_structured_turn`.
- A CI guard (`make lint-dashboard-txt` or similar) fails on `DASHBOARD.md` re-introduction in tracked non-archive paths. Archived plans and test fixtures are excluded.

## Context Loading

- Motivating assessment: [docs/assessments/parallel-reviews-and-autonomous-debug-assessment-2026-04-16.md](../../assessments/parallel-reviews-and-autonomous-debug-assessment-2026-04-16.md)
- Prerequisite plan: [docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md](E17-7-handoff-evolution-and-portable-workflow-task-plan.md) (Slices 2, 4, 5)
- Worker-daemon cost evidence: [packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon.py](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon.py), [handoff_read_shapes.py](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/handoff_read_shapes.py)
- Bounded-read levers: [packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md](../../../packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md)
- Cache-TTL cadence rules: CLAUDE.md `ScheduleWakeup` guidance (Anthropic prompt cache 5-minute TTL)
- Existing skills: [.claude/skills/branch-review/](../../../.claude/skills/branch-review/), [.claude/skills/investigate/](../../../.claude/skills/investigate/)
- Portable workflow manifest: [config/agent-workflows/portable_commands.json](../../../config/agent-workflows/portable_commands.json)
- Workflow generator: [scripts/generate_agent_workflows.py](../../../scripts/generate_agent_workflows.py)

## Proposed Solution

Four slices deliver the workflows and close the E17-7 back-reference:

1. Parallel-review coordinator skill + portable command
2. Auto-fix loop skill + portable command
3. Cross-vendor subagent adapter equivalence tests
4. `DASHBOARD.md` drift CI guard (closes E17-7 Slice 4 back-reference)

Slice 1 can land independently of Slices 2-3 once E17-7 Slice 5 is in place. Slice 2 depends on the Bounded Reads lever set already in place. Slice 3 exercises both Slice 1 and Slice 2 adapters, so it lands after them. Slice 4 is orthogonal and can land first or last.

## Contract and Boundary Impact

| Boundary                             | Owner                              | Current Contract                                                            | Expected Change                                                      | Compatibility Needed?        | Verification                                   |
| ------------------------------------ | ---------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------- | ---------------------------- | ---------------------------------------------- |
| `portable_commands.json`             | `config/agent-workflows/`          | 8 managed commands                                                          | add `/review-parallel` and `/auto-fix` entries                       | non-breaking manifest add    | `make check-agent-workflows` passes            |
| `scripts/generate_agent_workflows.py`| scripts                            | emits Claude + VS Code + Codex adapters (post E17-7 S1)                     | emits the two new command adapters                                   | non-breaking generator       | regenerated outputs match                      |
| `.claude/skills/`                    | skills dir                         | existing skills                                                             | add `review-parallel/`, `auto-fix/` skill dirs                       | non-breaking                 | skills discoverable                            |
| Host subagent primitive              | vendor-specific                    | Claude Agent tool / `codex exec` / `run_structured_turn`                    | wrapped behind one `SubagentAdapter` protocol                        | vendor-agnostic pattern      | cross-vendor adapter test                      |
| `review_findings` merge              | `core.py` (from E17-7 S5)          | single-task find + batch record                                             | coordinator merges per-reviewer `task_ref`s                          | depends on E17-7 S5          | merge roundtrip test                           |
| `handoff_close_check` gate           | `agent-handoff-mcp` API            | already enforces pre-merge criteria                                         | auto-fix loop uses as convergence gate                               | no API change                | convergence test                               |
| Dashboard-filename lint              | `Makefile` / `mk/`                 | none                                                                        | new `make lint-dashboard-txt` target fails on `DASHBOARD.md` hits    | non-breaking CI addition     | drift sample fails the gate                    |

## Files and Surfaces to Change

| Surface                  | File                                                                                                                      | Change                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Portable manifest        | `config/agent-workflows/portable_commands.json`                                                                           | add `/review-parallel` and `/auto-fix` command entries                              |
| Review-parallel skill    | `.claude/skills/review-parallel/SKILL.md` (new)                                                                           | coordinator protocol: fan-out, per-reviewer task_ref scoping, merge fan-in          |
| Auto-fix skill           | `.claude/skills/auto-fix/SKILL.md` (new)                                                                                  | bounded-reads loop, convergence gate, cadence, iteration cap                        |
| Subagent adapter         | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/subagent/adapter.py` (new)                                    | `SubagentAdapter` protocol + three concrete adapters                                |
| Generated adapters       | `.claude/commands/*.md`, `.github/prompts/*.prompt.md`, Codex router artifact                                             | regenerated from manifest                                                           |
| Cross-vendor tests       | `packages/agent-orchestrator-mcp/tests/test_cross_vendor_subagent_equivalence.py` (new)                                   | exercise all three adapters through one reviewer prompt                             |
| Dashboard guard          | `Makefile` (new `lint-dashboard-txt` target) + supporting script if needed                                                | grep tracked non-archive paths for `DASHBOARD.md`, fail on match                    |
| Documentation            | [docs/agentic/rules/branch-review-guide.md](../../agentic/rules/branch-review-guide.md), [docs/agentic/rules/development-workflow.md](../../agentic/rules/development-workflow.md) | link to new skills; note the host-subagent-primitive default for fan-out            |
| E17-7 back-reference     | [docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md](E17-7-handoff-evolution-and-portable-workflow-task-plan.md) | update Slice 4 Proof to reference this plan's Slice 4 guard (housekeeping)          |

## Verification Strategy

- `make check-agent-workflows` passes after manifest updates (Claude + VS Code + Codex adapters regenerate cleanly, drift gate green).
- Parallel-review happy path test: two synthetic reviewers each write 3 findings under scoped `task_ref`s; coordinator `operation="merge"` produces 6 rows under the coordinator `task_ref` with `merged_from` provenance on every row.
- Auto-fix convergence test: a deliberately failing test (e.g. an arithmetic off-by-one in a fixture module) is repaired by the loop; `handoff_close_check(enforce=True, require_fresh_tests=True)` reports `ok=true` at loop exit; loop exits within the iteration cap.
- Auto-fix bounded-reads test: each iteration's `get_handoff_state(sections="identity")` response fits in under 2 KB (asserted via `len(payload.encode("utf-8"))`).
- Auto-fix cadence test: no `ScheduleWakeup` call at exactly 300s; all recorded waits are `<270` or `>=1200`.
- Cross-vendor equivalence test: three adapters invoke the same reviewer prompt against the same synthetic diff; resulting MCP rows match structurally (same finding count, same severity distribution, same `verified_commit_sha`). Missing-adapter tests skip cleanly when the vendor CLI is absent; `StructuredTurnAdapter` always runs because it's in-repo.
- Dashboard guard test: an intentional `DASHBOARD.md` reference in a tracked non-archive markdown file fails `make lint-dashboard-txt`; archived plans and test fixtures are excluded by path pattern.
- `make test-handoff` and `make test-orchestrator` stay green after each slice.

## Slice Delivery

### Slice 1: Parallel-Review Coordinator Skill + Portable Command

**Goal**: land a skill that fans out a branch review to N ephemeral reviewers and merges their findings atomically under the coordinator `task_ref`.

Changes:

- Add `/review-parallel` to [config/agent-workflows/portable_commands.json](../../../config/agent-workflows/portable_commands.json) with argument schema: `reviewers_count` (int, default 2), `reviewer_prompt_template` (optional string id pointing to a prompt in `.claude/skills/review-parallel/prompts/`), `merge_strategy` (default `"union"`).
- Create `.claude/skills/review-parallel/SKILL.md` defining the coordinator protocol:
  1. Coordinator opens task_ref `<task>`; for each reviewer index, assigns a scoped task_ref `<task>-REV-<letter>` (A, B, C, …).
  2. Coordinator invokes N subagents via the host subagent primitive (Agent tool on Claude; `codex exec` on Codex; `run_structured_turn` on Copilot). Each subagent receives the reviewer prompt + its scoped task_ref and records findings under that scope. Each returns a short summary.
  3. Coordinator calls `review_findings(review={"operation":"merge","source_task_refs":[<REV-A>, <REV-B>, …], "target_task_ref":"<task>"})` to unify.
  4. Coordinator records a `review_run(review_mode="code_review",verdict=...)` for the combined pass; reviewer sub-runs remain under their own `task_ref`s as audit trail.
- Define a `SubagentAdapter` protocol at `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/subagent/adapter.py` with one method `invoke(prompt: str, task_ref: str, timeout_seconds: int) -> SubagentResult`. Provide three implementations: `ClaudeAgentAdapter` (no-op stub that documents the Claude-Code-only primitive; real invocation happens in the host), `CodexExecAdapter` (subprocess), `StructuredTurnAdapter` (wraps `run_structured_turn`).
- Regenerate host-specific adapters via `make generate-agent-workflows`.

Proof:

- Happy-path test records 2 reviewers × 3 findings each under scoped task_refs; merged rows under coordinator task_ref = 6 with `merged_from` provenance on every row; reviewer source rows remain intact.
- Token envelope check: coordinator-side work (not counting reviewer subagent interiors, which are isolated) stays under 50K total tokens for a 2-reviewer review of a ~500-line diff. Measured via turn-metrics summary.
- `.claude/commands/review-parallel.md` and `.github/prompts/review-parallel.prompt.md` regenerate without drift; `make check-agent-workflows` green.

### Slice 2: Auto-Fix Loop Skill + Portable Command

**Goal**: iterate a bounded, cache-aware fix loop with a durable convergence gate.

Changes:

- Add `/auto-fix` to `portable_commands.json` with argument schema: `failing_test_cmd` (required string), `max_iterations` (int, default 5), `scope_hint` (optional string — file path, module, or keyword to bound the search space).
- Create `.claude/skills/auto-fix/SKILL.md` defining the loop:
  1. Record investigation opening via `review_findings(review={"operation":"record","review_mode":"investigation", ...})`.
  2. Per iteration:
     - `get_handoff_state(sections="identity")` — never `detail="full"`.
     - Read only the files implicated by `scope_hint` + the failing test's output.
     - Propose smallest candidate fix (one localized edit, not a refactor).
     - Run `failing_test_cmd`; capture stdout/stderr.
     - `record_event(event={"event_kind":"test_result", ...})` with the result.
     - `handoff_close_check(enforce=True, require_fresh_tests=True)`.
  3. If `handoff_close_check.ok == true`, close the investigation finding with outcome and exit successfully.
  4. If iteration count exceeded without convergence, record a blocker via `record_event(event={"event_kind":"blocker", ...})` and escalate — do not silently exit.
  5. Between iterations, use `ScheduleWakeup(delaySeconds<270)` only if waiting on an external signal (e.g. CI). Otherwise iterate inline. Never `delaySeconds=300`.
- Document anti-patterns in the skill file: no `detail="full"` mid-loop; no 300s cache-miss waits; no silent skip of `require_fresh_tests`; no iteration cap bypass.
- Regenerate host-specific adapters.

Proof:

- Convergence test on a fixture failing test (deliberate off-by-one): loop converges within 3 iterations; final `handoff_close_check.ok == true`; investigation finding closed with outcome.
- Bounded-reads test: each iteration's identity response `len(payload.encode("utf-8")) < 2048`.
- Cadence test: captured wait durations across a multi-iteration run contain no `300` value; all are `<270` or `>=1200`.
- Iteration-cap test: an unfixable failing test triggers the blocker path at exactly `max_iterations + 1` and does not exit green.

### Slice 3: Cross-Vendor Subagent Adapter Equivalence Tests

**Goal**: prove the parallel-review pattern works identically across the three subagent primitives, so the pattern is vendor-agnostic in practice, not just in design.

Changes:

- Create `packages/agent-orchestrator-mcp/tests/test_cross_vendor_subagent_equivalence.py`.
- Parametrize a test matrix over `[ClaudeAgentAdapter, CodexExecAdapter, StructuredTurnAdapter]` with per-adapter `skip` guards: `ClaudeAgentAdapter` skipped when not running under Claude Code; `CodexExecAdapter` skipped when `codex` CLI is not on `$PATH`; `StructuredTurnAdapter` always runs (in-repo primitive).
- Each test case: invoke the same reviewer prompt through the adapter against the same synthetic diff; assert resulting MCP rows match on `(count, severity_distribution, verified_commit_sha)` across adapters. A deliberate drift test (an adapter wrapper that silently drops severity) must fail the equivalence assertion.
- Publish one skill-level note in `review-parallel/SKILL.md` linking to the adapter protocol as the canonical contract for vendor-agnostic fan-out.

Proof:

- Matrix test passes or skips cleanly for each adapter.
- Drift test fails when an adapter deviates from the protocol contract.
- No in-repo code forks per vendor — all three adapters implement the same protocol.

### Slice 4: DASHBOARD.md Drift CI Guard

**Goal**: close the home-less CI guard back-reference from E17-7 Slice 4 Proof so the `DASHBOARD.md → DASHBOARD.txt` rename cannot silently regress.

Changes:

- Add `make lint-dashboard-txt` target in the root `Makefile` (or include it under an existing `make lint-docs`/`make check-all` chain if one exists). The target greps tracked files (via `git ls-files`) for `DASHBOARD.md`, excludes `docs/tasks/archive/**`, `**/test_fixtures/**`, and `**/tests/**/fixtures/**`, and fails with a clear message on any match.
- Wire `lint-dashboard-txt` into `make check-all` so CI catches regressions on every branch.
- Update [docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md](E17-7-handoff-evolution-and-portable-workflow-task-plan.md) Slice 4 Proof line so the back-reference points at this guard's final path (housekeeping edit; no code change).

Proof:

- Guard fires on a deliberately-reintroduced `DASHBOARD.md` reference in a tracked non-archive markdown file.
- Guard does not flag archived task plans or test fixtures.
- `make check-all` stays green post-landing.

---

## Consolidated Checklist

### Slice 1: Parallel-Review Coordinator Skill + Portable Command

- [ ] `/review-parallel` entry exists in `portable_commands.json` with documented argument schema
- [ ] `.claude/skills/review-parallel/SKILL.md` defines coordinator protocol with scoped per-reviewer `task_ref`s
- [ ] `SubagentAdapter` protocol defined at `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/subagent/adapter.py`
- [ ] Three adapters implemented (`ClaudeAgentAdapter`, `CodexExecAdapter`, `StructuredTurnAdapter`)
- [ ] Generated host adapters updated via `make generate-agent-workflows`
- [ ] `make check-agent-workflows` green
- [ ] Happy-path test: merged findings count equals reviewer-sum; every merged row has `merged_from` provenance
- [ ] Reviewer source rows remain intact after merge (additive, not destructive)
- [ ] Coordinator-side token envelope check passes for a 2-reviewer review of ~500-line diff

### Slice 2: Auto-Fix Loop Skill + Portable Command

- [ ] `/auto-fix` entry exists in `portable_commands.json` with documented argument schema
- [ ] `.claude/skills/auto-fix/SKILL.md` defines bounded loop + convergence gate + cadence + iteration cap
- [ ] Loop calls `get_handoff_state(sections="identity")` per iteration; never `detail="full"`
- [ ] Loop uses `handoff_close_check(enforce=True, require_fresh_tests=True)` as convergence gate
- [ ] Cadence rule enforced: `<270` warm, `>=1200` idle, never `300`
- [ ] Generated host adapters updated
- [ ] Convergence test passes on fixture failing test within iteration cap
- [ ] Bounded-reads test: iteration identity response stays under 2 KB
- [ ] Cadence test: no `300`s recorded in a multi-iteration run
- [ ] Iteration-cap test: unfixable test triggers blocker path, does not silently exit

### Slice 3: Cross-Vendor Subagent Adapter Equivalence

- [ ] `packages/agent-orchestrator-mcp/tests/test_cross_vendor_subagent_equivalence.py` exists
- [ ] Matrix parametrized over all three adapters with per-adapter `skip` guards
- [ ] Equivalence assertion covers `(count, severity_distribution, verified_commit_sha)`
- [ ] Drift test fails an intentionally-broken adapter
- [ ] `review-parallel/SKILL.md` links to `SubagentAdapter` as the canonical fan-out contract
- [ ] No per-vendor code forks — all three adapters implement the same protocol

### Slice 4: DASHBOARD.md Drift CI Guard

- [ ] `make lint-dashboard-txt` target exists in the root `Makefile`
- [ ] Archived plans and test fixtures excluded via path patterns
- [ ] Wired into `make check-all`
- [ ] E17-7 Slice 4 Proof back-reference updated to point at this guard
- [ ] Guard fires on intentional `DASHBOARD.md` reintroduction in a tracked non-archive path
- [ ] `make check-all` stays green post-landing

## Review Readiness

- [ ] E17-7 Slice 2 (multi-active-task registry) merged
- [ ] E17-7 Slice 4 (tool compression) merged
- [ ] E17-7 Slice 5 (`review_findings.merge` + `(lane, status)` index) merged
- [ ] `make check-agent-workflows` green
- [ ] `make test-handoff` green after each schema-adjacent slice
- [ ] `make test-orchestrator` green after each orchestrator-adjacent slice

## Success Criteria

- [ ] `/review-parallel` and `/auto-fix` resolve through one manifest across all three hosts (Claude Code, VS Code/Copilot, Codex)
- [ ] Parallel-review coordinator fan-out uses the host subagent primitive (not worker daemons) and stays bounded in token cost for typical ~500-line diff reviews
- [ ] Auto-fix loop converges using `handoff_close_check` as the gate, with bounded reads per iteration and cache-TTL-respecting cadence
- [ ] Cross-vendor adapter tests prove the pattern is not Claude-Code-specific
- [ ] `DASHBOARD.md` re-introduction in tracked non-archive paths fails CI
