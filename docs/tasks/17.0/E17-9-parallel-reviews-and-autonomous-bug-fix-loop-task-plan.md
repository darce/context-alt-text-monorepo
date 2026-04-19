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

Also close one loose CI back-reference from E17-7 Slice 4: a drift guard that prevents `DASHBOARD.md` from reappearing in tracked non-archive paths. <!-- lint-dashboard-txt: allow -->

## Why This Is Separate

This plan was split out of E17-7 to keep E17-7's charter focused on evolving _existing_ primitives (schema, traces, tool compression, Codex portability). The parallel-review and auto-fix workflows add _new_ user-facing workflow surface — two skills, two portable commands, a coordinator protocol, cross-vendor adapter tests. Folding them into E17-7 would roughly double that plan's scope and delay its merge. This plan's prerequisites from E17-7 Slices 2 (multi-active-task registry), 4 (tool compression), and 5 (`review_findings.merge` + `(lane, status)` index) all landed in the E17-7 merge at commit `b7397615`, so this plan is ready to start.

E17-8 is a different task (branch-isolation edit-guard hardening). This plan is independent of E17-8.

## Problem Statement

Three gaps remain after E17-7 lands:

1. **Parallel review is not a first-class workflow**: today's branch reviews serialize — one reviewer, one pass, one finding set. The motivating assessment identified the host subagent primitive (Agent tool / `codex exec` / `run_structured_turn`) as the correct fan-out mechanism for bounded ephemeral reviews — 1-2 orders of magnitude cheaper than worker-daemon orchestration for the same work — but no skill or portable command wraps it. Parent coordination, reviewer `task_ref` scoping, and merge fan-in are ad-hoc and prone to race or silent-drop when agents improvise.

2. **Autonomous bug fixing leaks tokens**: `handoff_close_check(enforce=True, require_fresh_tests=True)` is already a sound convergence gate for an auto-fix loop, but without Bounded Handoff Reads (`sections="identity"`, `detail="summary"`, low `top_n_*`) and cache-TTL-aware cadence each iteration pays a 5-30K token tax that compounds across tens of iterations. No skill or portable command codifies the bounded loop, so agents repeatedly re-invent it under-disciplined.

3. **`DASHBOARD.md` drift has no CI home**: E17-7 Slice 4 Proof references a guard that "lives in E17-9 Slice 4" — this plan supplies that home, so the drift cannot silently reappear after the rename lands. <!-- lint-dashboard-txt: allow -->

## Constraints

- The host subagent primitive is the default fan-out mechanism for this plan's workflows. Worker daemons (`dispatch_lane_work(start_worker=True)`) remain available on `agent-orchestrator-mcp` for long-running continuous-polling scenarios the assessment explicitly identified (multi-hour operator pipelines, not bounded reviews).
- The pattern must be vendor-agnostic at the skill level. The `review-parallel` SKILL.md defines a harness-routing table (the "SubagentInvoker" routing) that tells the coordinator model which primitive to invoke based on the detected harness: Claude Code → in-process `Agent` tool; Codex harness → `run_structured_turn` (served by `agent-orchestrator-mcp`); Copilot/VS Code → `run_structured_turn` (same MCP tool, reachable over MCP). The `BackendAdapter` protocol + `backend_registry` (`claude-code`, `codex-subagent`, `codex-cli`, `copilot-host`) remain the canonical surface for *external* orchestration and for Slice 3's tests; they are not invoked from inside an active coordinator session because shelling out to `claude` CLI from a running Claude Code session inverts the cost premise. No parallel adapter stack is introduced.
- Each parallel reviewer writes findings under its own scoped `task_ref` (convention: `<coordinator-task-ref>-REV-<letter>`). The coordinator calls `review_findings(review={"operation":"merge","source_task_refs":[...],"target_task_ref":"<coordinator>"})` (landed in E17-7 Slice 5) to unify them. No reviewer writes directly under the coordinator `task_ref` while another reviewer is still running.
- Auto-fix loop must call `get_handoff_state(sections="identity")` between iterations, per CLAUDE.md Bounded Handoff Reads rule. `detail="full"` mid-loop is a rule violation.
- Auto-fix loop cadence is Claude-Code-specific: `ScheduleWakeup(delaySeconds<270)` for warm-cache polling, `delaySeconds>=1200` for idle waits, 300s forbidden. Codex and Copilot harnesses iterate inline (no equivalent primitive). The skill documents both paths; the portable command registers across all three hosts but the cadence discipline only applies where `ScheduleWakeup` exists.
- Convergence signal for an auto-fix iteration is a fresh `verified_tests` row with `passed=true` and `commit_sha == HEAD` on the active task — not `handoff_close_check.ok`. `handoff_close_check(enforce=True, require_fresh_tests=True, current_commit_sha=<HEAD>)` runs **once** at post-loop finalization, after the loop has committed the fix and recorded a canonical slice-complete decision; it is the pre-merge gate, not a loop-internal exit condition. Using it per-iteration is a design error because `ok=true` requires task `status=done` + canonical `slice_complete_*` decision + fresh test row on HEAD simultaneously (see [decisions.py:587](../../../packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py:587)).
- Auto-fix loop runs only when the active task's `target_branch` is a feature branch. The skill refuses to start when `target_branch` is `main`, `master`, or unset; the branch-isolation hooks ([scripts/hooks/guard-main-branch.sh](../../../scripts/hooks/guard-main-branch.sh), [.github/hooks/guard-main-branch.py](../../../.github/hooks/guard-main-branch.py)) would reject the first edit anyway, but the precondition check produces a clearer error.
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
- `review_findings.merge` and `idx_review_findings_lane_status` landed in E17-7 Slice 5 (commit `69ecdf73`, merged into `main` via `b7397615`).
- `handoff_close_check(enforce=True, require_fresh_tests=True)` already enforces the pre-merge convergence criteria an auto-fix loop needs to treat as "done".
- `config/agent-workflows/portable_commands.json` already drives eight commands; adding two more follows the existing pattern.
- E17-7 Slice 4 Proof at [docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md:303](E17-7-handoff-evolution-and-portable-workflow-task-plan.md) points forward to "E17-9 Slice 4" for the `DASHBOARD.md` CI guard. <!-- lint-dashboard-txt: allow -->

## Target Outcome

- `/review-parallel` skill + portable command fan out to N reviewers via the coordinator's in-harness cheapest subagent primitive (Claude Code `Agent` tool in-process; Codex + Copilot `run_structured_turn`; external orchestrator `BackendAdapter`), scope each reviewer to its own `task_ref`, and synthesize via `review_findings.merge` under the coordinator `task_ref`. All three harnesses produce the same MCP state.
- `/auto-fix` skill + portable command execute a bounded loop around a failing test: per iteration, write the smallest candidate fix, commit it on the feature branch, run the test, record the result; exit on the first `passed=true` test_result tied to HEAD, or record a blocker after the iteration cap. Finalization records a canonical slice-complete decision, sets task status to `done`, and calls `handoff_close_check(enforce=True, require_fresh_tests=True, current_commit_sha=<HEAD>)` exactly once as the pre-merge gate. Per-iteration reads stay bounded. Cadence discipline is Claude-Code-only; Codex / Copilot iterate inline with identical MCP state.
- Cross-vendor adapter tests cover an always-available in-repo backend (`StructuredTurnAdapter` via `run_structured_turn`) plus any host-supplied bridge backends that resolve at test time. Default CI proves equivalence for the in-repo backend and characterizes coverage for the others.
- A CI guard (`make lint-dashboard-txt` or similar) fails on `DASHBOARD.md` re-introduction in tracked non-archive paths. Archived plans and test fixtures are excluded. <!-- lint-dashboard-txt: allow -->

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
4. `DASHBOARD.md` drift CI guard (closes E17-7 Slice 4 back-reference) <!-- lint-dashboard-txt: allow -->

Slice 1 can land independently of Slices 2-3 once E17-7 Slice 5 is in place. Slice 2 depends on the Bounded Reads lever set already in place. Slice 3 exercises both Slice 1 and Slice 2 adapters, so it lands after them. Slice 4 is orthogonal and can land first or last.

## Contract and Boundary Impact

| Boundary                             | Owner                              | Current Contract                                                            | Expected Change                                                      | Compatibility Needed?        | Verification                                   |
| ------------------------------------ | ---------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------- | ---------------------------- | ---------------------------------------------- |
| `portable_commands.json`             | `config/agent-workflows/`          | 8 managed commands                                                          | add `/review-parallel` and `/auto-fix` entries                       | non-breaking manifest add    | `make check-agent-workflows` passes            |
| `scripts/generate_agent_workflows.py`| scripts                            | emits Claude + VS Code + Codex adapters (post E17-7 S1)                     | emits the two new command adapters                                   | non-breaking generator       | regenerated outputs match                      |
| `.claude/skills/`                    | skills dir                         | existing skills                                                             | add `review-parallel/`, `auto-fix/` skill dirs                       | non-breaking                 | skills discoverable                            |
| Host subagent primitive              | harness-specific                   | Claude `Agent` tool (in-process), Codex `run_structured_turn`, Copilot `run_structured_turn` | skill documents per-harness routing; in-process primitive is preferred when available; `BackendAdapter` stays the external-orchestration surface | harness-routing doc only     | cross-vendor adapter test covers registry path |
| `StructuredTurnAdapter`              | `agent-orchestrator-mcp`           | none                                                                        | new `BackendAdapter` wrapping `run_structured_turn` for always-available cross-vendor test coverage | additive, no existing behaviour changed | Slice 3 matrix includes this adapter as the always-runnable row |
| `review_findings` merge              | `core.py` (from E17-7 S5)          | single-task find + batch record                                             | coordinator merges per-reviewer `task_ref`s                          | E17-7 S5 prerequisite landed in `b7397615` | merge roundtrip test                           |
| `handoff_close_check` gate           | `agent-handoff-mcp` API            | already enforces pre-merge criteria                                         | auto-fix loop calls it **once post-loop** as the pre-merge gate, never as a per-iteration exit condition | no API change                | post-loop gate test; per-iteration signal test |
| Dashboard-filename lint              | `Makefile` / `mk/`                 | none                                                                        | new `make lint-dashboard-txt` target fails on `DASHBOARD.md` hits    | non-breaking CI addition     | drift sample fails the gate                    | <!-- lint-dashboard-txt: allow -->

## Files and Surfaces to Change

| Surface                  | File                                                                                                                      | Change                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Portable manifest        | `config/agent-workflows/portable_commands.json`                                                                           | add `/review-parallel` and `/auto-fix` command entries                              |
| Review-parallel skill    | `.claude/skills/review-parallel/SKILL.md` (new)                                                                           | coordinator protocol + per-harness routing table + per-reviewer task_ref scoping + merge fan-in |
| Reviewer prompt templates | `config/agent-workflows/prompts/review-parallel/` (new, harness-neutral)                                                 | reviewer prompt templates, referenced by `reviewer_prompt_template` arg; reachable from Claude, VS Code, and Codex adapters |
| Auto-fix skill           | `.claude/skills/auto-fix/SKILL.md` (new)                                                                                  | bounded reads, per-iteration fresh-test signal, commit-per-iteration discipline, harness-scoped cadence, post-loop close-check gate, iteration cap, branch-isolation precondition |
| Backend registry reuse   | [packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/backend_adapter.py](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/backend_adapter.py), [backend_registry.py](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/backend_registry.py) | reuse existing `BackendAdapter` protocol + `claude-code` / `codex-subagent` / `codex-cli` / `copilot-host` backends for external orchestration and tests; no new adapter layer |
| StructuredTurnAdapter    | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/adapters/structured_turn.py` (new)              | in-repo `BackendAdapter` that calls `run_structured_turn` directly — always available in CI, no host bridge required; registered in `backend_registry` as `structured-turn` |
| Generated adapters       | `.claude/commands/*.md`, `.github/prompts/*.prompt.md`, Codex router artifact                                             | regenerated from manifest                                                           |
| Cross-vendor tests       | `packages/agent-orchestrator-mcp/tests/test_cross_vendor_subagent_equivalence.py` (new)                                   | exercise `StructuredTurnAdapter` (always runs) plus any bridge-backed adapters that resolve at test time |
| Dashboard guard          | `Makefile` (new `lint-dashboard-txt` target) + supporting script if needed                                                | grep tracked non-archive paths for `DASHBOARD.md`, fail on match                    | <!-- lint-dashboard-txt: allow -->
| Documentation            | [docs/agentic/rules/branch-review-guide.md](../../agentic/rules/branch-review-guide.md), [docs/agentic/rules/development-workflow.md](../../agentic/rules/development-workflow.md) | link to new skills; note the host-subagent-primitive default for fan-out            |
| E17-7 back-reference     | [docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md](E17-7-handoff-evolution-and-portable-workflow-task-plan.md) | update Slice 4 Proof to reference this plan's Slice 4 guard (housekeeping)          |

## Verification Strategy

- `make check-agent-workflows` passes after manifest updates (Claude + VS Code + Codex adapters regenerate cleanly, drift gate green).
- Baseline capture (one-time, recorded as a fixture): current `/branch-review` token cost for a 500-line fixture diff and current `get_handoff_state(sections="identity")` payload size on a populated fixture task. Baselines are checked into the test tree so the Slice 1 / Slice 2 thresholds are regression-guards, not arbitrary numbers.
- Parallel-review happy path test: two synthetic reviewers each write 3 findings under scoped `task_ref`s; coordinator `operation="merge"` produces 6 rows under the coordinator `task_ref` with `merged_from` provenance on every row.
- Parallel-review token envelope test: coordinator-side work (excluding reviewer subagent interiors) stays under 50% of the captured `/branch-review` baseline for the same 500-line fixture.
- Auto-fix per-iteration signal test: each iteration, after the candidate fix is committed, the latest `verified_tests` row with `task_ref=<active>` and `commit_sha=<HEAD>` has `passed=true` → loop sets its exit flag. Loop never evaluates `handoff_close_check.ok` as the per-iteration signal.
- Auto-fix post-loop gate test: on a repaired fixture (off-by-one corrected within the iteration cap), the skill commits, records a canonical `<tag>_slice_complete_<task>_autofix` decision, then calls `handoff_close_check(enforce=True, require_fresh_tests=True, current_commit_sha=<HEAD>)` exactly once and observes `ok=true`. Without the commit + slice-complete, the same call observes `ok=false` with the expected failure reasons.
- Auto-fix bounded-reads test: each iteration's `get_handoff_state(sections="identity")` response fits within the captured baseline + 10% slack (asserted via `len(payload.encode("utf-8"))`).
- Auto-fix cadence test (Claude-Code-only, skipped on Codex/Copilot runtimes): no `ScheduleWakeup` call at exactly 300s; all recorded waits are `<270` or `>=1200`. On Codex/Copilot runtimes, the test asserts the skill iterated inline (zero `ScheduleWakeup` invocations) and the end-to-end MCP state still matches.
- Auto-fix branch-isolation precondition test: invoking `/auto-fix` with `active_task.target_branch in {main, master, None}` produces a clear precondition error and records no `verified_tests` rows.
- Cross-vendor equivalence test: `StructuredTurnAdapter` always runs (in-repo, no bridge required); `codex-cli` runs when `codex` is on `PATH`; `claude-code` runs when `claude` is on `PATH`; `codex-subagent` / `copilot-host` skip cleanly when their host bridge modules are absent. All running adapters produce MCP rows that match structurally on `(count, severity_distribution, verified_commit_sha)`. A deliberate drift adapter (drops severity) fails the equivalence assertion.
- Dashboard guard test: an intentional `DASHBOARD.md` reference in a tracked non-archive markdown file fails `make lint-dashboard-txt`; archived plans and test fixtures are excluded by path pattern. <!-- lint-dashboard-txt: allow -->
- `make test-handoff` and `make test-orchestrator` stay green after each slice.

## Slice Delivery

### Slice 1: Parallel-Review Coordinator Skill + Portable Command

**Goal**: land a skill that fans out a branch review to N ephemeral reviewers and merges their findings atomically under the coordinator `task_ref`. The skill defines a harness-routing table so each host uses its cheapest subagent primitive; all hosts produce the same MCP state.

Preamble (baseline capture, runs once before the rest of the slice):

- Record the current serial `/branch-review` token cost and MCP-row shape for the canonical 500-line fixture diff. Store the numbers as a test fixture under `packages/agent-orchestrator-mcp/tests/fixtures/review_baseline.json`. These baselines become the denominators for the Slice 1 token-envelope assertion; they are not re-measured per slice.

Changes:

- Add `/review-parallel` to [config/agent-workflows/portable_commands.json](../../../config/agent-workflows/portable_commands.json) with argument schema: `reviewers_count` (int, default 2) and `reviewer_prompt_template` (optional string id pointing to a prompt under `config/agent-workflows/prompts/review-parallel/`, harness-neutral). No `merge_strategy` argument — `review_findings(operation="merge")` is an unconditional union re-record under the target task_ref, and exposing a strategy knob without a downstream implementation would be dead configuration. Reintroduce later only if coordinator-side filter semantics (dedup, severity-threshold) are implemented alongside.
- Create `config/agent-workflows/prompts/review-parallel/` with the default reviewer prompt template. The Claude, VS Code/Copilot, and Codex adapters all resolve template ids through this directory via the workflow generator (`scripts/generate_agent_workflows.py`).
- Create `.claude/skills/review-parallel/SKILL.md` defining the coordinator protocol **and** the per-harness subagent-invocation routing table:

  | Harness detected | Primitive the coordinator uses | Why |
  | --- | --- | --- |
  | Claude Code (coordinator is an in-process Claude agent) | `Agent` tool with `subagent_type` + scoped `task_ref` in the prompt | In-process primitive; 1–2 orders of magnitude cheaper than a `claude` CLI subprocess. `ClaudeCodeAdapter` must **not** be used from inside an active Claude Code session. |
  | Codex (coordinator is a Codex agent) | `run_structured_turn` on `agent-orchestrator-mcp` | In-repo MCP tool; bounded ephemeral turn with the reviewer prompt + scoped `task_ref`. |
  | Copilot / VS Code | `run_structured_turn` on `agent-orchestrator-mcp` | Same MCP tool reachable over MCP from the Copilot host. |
  | External orchestrator (not inside an interactive harness) | `backend_registry.get_adapter(<kind>)` + `BackendAdapter.execute(...)` | CLI/bridge path; correct cost profile when no interactive session exists. |

  Coordinator protocol steps (all harnesses):
  1. Coordinator opens task_ref `<task>`; for each reviewer index, assigns a scoped task_ref `<task>-REV-<letter>` (A, B, C, …).
  2. Coordinator invokes N reviewer subagents via the primitive from the routing table. Each subagent receives the reviewer prompt + its scoped `task_ref` and records findings under that scope via `review_findings(review={"operation":"batch_record", ...})`. Each returns a short summary.
  3. Coordinator calls `review_findings(review={"operation":"merge","source_task_refs":[<REV-A>, <REV-B>, …], "target_task_ref":"<task>"})` to unify. Reviewer source rows remain intact; merged rows carry `merged_from` provenance.
  4. Coordinator records `review_runs(operation="record", review_mode="branch", verdict=...)` for the combined pass; reviewer sub-runs remain under their own `task_ref`s as audit trail.

- Do **not** introduce a new `SubagentAdapter` layer. The `SubagentInvoker` in the skill is a documented routing rule, not a new Python protocol — it tells the coordinator model which MCP/tool primitive to call and passes the scoped `task_ref` + prompt through. The existing `BackendAdapter` + `backend_registry` surfaces stay unchanged and remain the right abstraction for external orchestration and Slice 3 tests.
- Regenerate host-specific adapters via `make generate-agent-workflows`.

Proof:

- Baseline fixture recorded at `packages/agent-orchestrator-mcp/tests/fixtures/review_baseline.json` with documented measurement methodology.
- Happy-path test records 2 reviewers × 3 findings each under scoped task_refs; merged rows under coordinator task_ref = 6 with `merged_from` provenance on every row; reviewer source rows remain intact.
- Token envelope test: coordinator-side work (not counting reviewer subagent interiors, which are isolated) stays **under 50% of the recorded `/branch-review` baseline** for the same ~500-line diff. Measured via turn-metrics summary.
- Harness-routing table is present in `review-parallel/SKILL.md` and explicitly forbids using `ClaudeCodeAdapter` from inside a Claude Code coordinator session.
- `.claude/commands/review-parallel.md` and `.github/prompts/review-parallel.prompt.md` regenerate without drift; `make check-agent-workflows` green.
- `config/agent-workflows/prompts/review-parallel/` exists and is referenced by the generated adapters in all three harnesses.

### Slice 2: Auto-Fix Loop Skill + Portable Command

**Goal**: iterate a bounded, cache-aware fix loop whose per-iteration exit signal is a fresh passing test tied to HEAD, with `handoff_close_check` reserved as the final post-loop pre-merge gate.

Changes:

- Add `/auto-fix` to `portable_commands.json` with argument schema: `failing_test_cmd` (required string), `max_iterations` (int, default 5), `scope_hint` (optional string — file path, module, or keyword to bound the search space).
- Create `.claude/skills/auto-fix/SKILL.md` defining the loop:

  **Precondition (before any iteration runs):**
  - Query `get_handoff_state(sections="identity")`. If `active.task_ref` is absent, or `active.target_branch` is `main`, `master`, or `None`, abort with a clear precondition error: "auto-fix requires an active task with a feature `target_branch`; run `make task-start TASK=<id>` first." Record no MCP rows on precondition failure.
  - Record investigation opening as a **decision**, not a finding: `record_event(event={"event_kind":"decision","decision":"<tag>_auto_fix_open_<task>_<slug>","rationale":"..."})`. This mirrors the existing `investigate` skill's intent (preserve the investigation trail) while avoiding an invalid `review_mode`.

  **Per iteration (bounded, cache-aware):**
  1. `get_handoff_state(sections="identity")` — never `detail="full"`.
  2. Read only the files implicated by `scope_hint` + the failing test's output.
  3. Propose smallest candidate fix (one localized edit, not a refactor).
  4. **Commit the candidate fix** on the feature branch: `git commit -am "wip(auto-fix): iter <N>"`. This advances HEAD so the next step's `commit_sha` provenance ties `verified_tests` to the fix. Uncommitted-workspace iterations are an anti-pattern — test provenance would stay on the pre-fix SHA and the post-loop gate would see stale tests.
  5. Run `failing_test_cmd`; capture stdout/stderr.
  6. Record the result: `record_event(event={"event_kind":"test_result","command":failing_test_cmd,"passed":<bool>,"actor":{"commit_sha":<HEAD>}})`.
  7. **Per-iteration exit signal**: `passed == true` on step 6. If true, break out of the iteration loop and proceed to Finalization. If false and iteration count < `max_iterations`, continue.
  8. If `iteration == max_iterations` without a passing run: record a blocker via `record_event(event={"event_kind":"blocker","operation":"add","description":"auto-fix exhausted <N> iterations without convergence"})`, squash or leave WIP commits for human triage, and exit non-zero. Do not silently exit.

  **Finalization (runs once, only after a passing iteration):**
  1. Optionally squash the WIP iteration commits into a single clean commit (`git rebase -i` or `git reset --soft` + `git commit`). HEAD after this step is what the gate will verify.
  2. Record the canonical slice-complete decision: `record_event(event={"event_kind":"decision","decision":"<tag>_slice_complete_<task>_autofix","rationale":"<structured slice-complete summary>","actor":{"commit_sha":<HEAD>}})`. Grammar follows [development-workflow.md § Decision IDs](../../agentic/rules/development-workflow.md#decision-ids); without this the post-loop gate fails on the `current_commit_handoff` check.
  3. If the active task still has `status != "done"`, update it: `update_task_status(task_ref=<active>, status="done")`.
  4. Call `handoff_close_check(enforce=True, require_fresh_tests=True, current_commit_sha=<HEAD>)` exactly once. Expect `ok=true`. On `ok=false`, surface the failure list to the user; do not retry the loop.
  5. Any defects discovered mid-loop that deserve review tracking are recorded as `review_findings(review={"operation":"record","review_mode":"branch", ...})`. These must be closed or deferred before the post-loop gate; they count as open findings on the active task.

  **Cadence (harness-scoped):**
  - **Claude Code**: between iterations, use `ScheduleWakeup(delaySeconds<270)` only when waiting on an external signal (e.g. CI). Otherwise iterate inline. Never `delaySeconds=300` (cache miss without amortization per CLAUDE.md).
  - **Codex / Copilot**: no `ScheduleWakeup` primitive — iterate inline unconditionally. The skill detects the harness via the same routing it documents for `/review-parallel` and skips the cadence block where not applicable.
  - The MCP state produced is identical across all three harnesses. Only the wall-clock cadence differs.

- Document anti-patterns in the skill file: no `detail="full"` mid-loop; no 300s cache-miss waits (Claude Code only); no uncommitted-workspace iterations; no silent skip of `require_fresh_tests`; no iteration cap bypass; no running on `main`.
- Regenerate host-specific adapters.

Proof:

- Precondition test: invoking `/auto-fix` with `active_task.target_branch in {main, master, None}` produces the precondition error and records zero MCP rows.
- Per-iteration signal test: on a deliberate off-by-one fixture, each iteration commits, runs the test, records a `verified_tests` row tied to the new HEAD, and the loop exits on the first `passed=true` row. No `handoff_close_check` call happens until Finalization.
- Finalization / post-loop gate test: after the passing iteration, Finalization records the canonical `slice_complete` decision, sets status `done`, and `handoff_close_check(enforce=True, require_fresh_tests=True, current_commit_sha=<HEAD>)` returns `ok=true`. A negative test skips the slice-complete step and asserts `ok=false` with the expected failure reason (`A structured slice-completion summary for the current commit is required before close.`).
- Bounded-reads test: each iteration's identity response `len(payload.encode("utf-8"))` ≤ the Slice 1 baseline + 10% slack.
- Cadence test (Claude-Code runtime only): captured wait durations across a multi-iteration run contain no `300` value; all are `<270` or `>=1200`. On Codex/Copilot runtimes the test asserts zero `ScheduleWakeup` invocations and still-correct MCP state.
- Iteration-cap test: an unfixable failing test triggers the blocker path at exactly `max_iterations` and exits non-zero without recording a slice-complete decision.
- Branch-isolation enforcement is covered by the existing `guard-main-branch` hook tests; Slice 2 adds no duplicate hook, only the skill-level precondition.

### Slice 3: Cross-Vendor Backend Adapter Equivalence Tests

**Goal**: prove the parallel-review pattern produces the same MCP state across at least one *always-available* backend plus any host-supplied bridges that resolve at test time. Default CI always covers ≥1 backend; opportunistic coverage scales with what the test host provides.

Changes:

- Add a new `StructuredTurnAdapter` at `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/adapters/structured_turn.py` implementing `BackendAdapter`. It composes `agent_orchestrator_mcp.run_structured_turn(...)` directly (no host bridge), so it is always available in CI and local runs. Register it in `backend_registry` under the kind `structured-turn`. This adapter is the canonical always-on cross-vendor case — it exercises the same MCP primitive (`run_structured_turn`) that Codex and Copilot coordinators invoke at runtime, without depending on vendor-supplied bridge modules that don't ship in this repo.
- Create `packages/agent-orchestrator-mcp/tests/test_cross_vendor_subagent_equivalence.py`.
- Parametrize a test matrix over the registered backends resolved via `backend_registry.get_adapter(<kind>)`:

  | Kind | Skip guard | Default CI behaviour |
  | --- | --- | --- |
  | `structured-turn` | none (always available) | **always runs** — anchors cross-vendor coverage |
  | `codex-cli` | `codex` binary on `$PATH` | runs when `codex` is installed |
  | `claude-code` | `claude` binary on `$PATH` | runs when `claude` is installed |
  | `codex-subagent` | `resolve_bridge("codex-subagent")` succeeds (host-supplied `codex_subagent_bridge` module) | skips cleanly when bridge absent |
  | `copilot-host` | `resolve_bridge("copilot-host")` succeeds (host-supplied `vscode_copilot_bridge` module) | skips cleanly when bridge absent |

- Each test case: invoke the same reviewer prompt through `BackendAdapter.execute(...)` against the same synthetic diff; assert resulting MCP rows match on `(count, severity_distribution, verified_commit_sha)` across all running adapters. A deliberate drift test (an adapter wrapper that silently drops severity) must fail the equivalence assertion.
- Publish one skill-level note in `review-parallel/SKILL.md` linking to `BackendAdapter` + `backend_registry` as the canonical contract for external orchestration, and to the per-harness routing table as the contract for in-session fan-out.

Proof:

- `structured-turn` always runs; matrix test never degenerates to an all-skip green.
- Matrix test passes or skips cleanly for every other registered backend based on host availability.
- Drift test fails when an adapter wrapper deviates from the `BackendAdapter` contract.
- No in-repo code forks per vendor — all backends implement the same `BackendAdapter` protocol already in the tree.
- The Slice 3 Goal language explicitly distinguishes "prove" (for `structured-turn`) from "characterize" (for vendor-bridge backends whose availability depends on the test host).

### Slice 4: DASHBOARD.md Drift CI Guard <!-- lint-dashboard-txt: allow -->

**Goal**: close the home-less CI guard back-reference from E17-7 Slice 4 Proof so the `DASHBOARD.md → DASHBOARD.txt` rename cannot silently regress. <!-- lint-dashboard-txt: allow -->

Changes:

- Add `make lint-dashboard-txt` target in the root `Makefile` (or include it under an existing `make lint-docs`/`make check-all` chain if one exists). The target greps tracked files (via `git ls-files`) for `DASHBOARD.md`, excludes `docs/tasks/archive/**`, `**/test_fixtures/**`, and `**/tests/**/fixtures/**`, and fails with a clear message on any match. <!-- lint-dashboard-txt: allow -->
- Wire `lint-dashboard-txt` into `make check-all` so CI catches regressions on every branch.
- Update [docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md](E17-7-handoff-evolution-and-portable-workflow-task-plan.md) Slice 4 Proof line so the back-reference points at this guard's final path (housekeeping edit; no code change).

Proof:

- Guard fires on a deliberately-reintroduced `DASHBOARD.md` reference in a tracked non-archive markdown file. <!-- lint-dashboard-txt: allow -->
- Guard does not flag archived task plans or test fixtures.
- `make check-all` stays green post-landing.

---

## Consolidated Checklist

Retroactive status note (2026-04-18): E17-9's landed dashboard guard is `lint-dashboard-txt`, and it correctly treats `DASHBOARD.txt` as canonical via a tracked-file scan. The still-open `make check-all` failure comes from `check-harness-sync` sweeping untracked `.claude/worktrees/**`, which is tracked separately from this Slice 4 guard.

### Slice 1: Parallel-Review Coordinator Skill + Portable Command

- [x] Baseline fixture captured at `packages/agent-orchestrator-mcp/tests/fixtures/review_baseline.json` (serial `/branch-review` tokens + identity-response size; identity bytes are live, serial tokens remain provisional)
- [x] `/review-parallel` entry exists in `portable_commands.json` with `reviewers_count` and `reviewer_prompt_template` only (no dead `merge_strategy` knob)
- [x] Reviewer prompt templates live under `config/agent-workflows/prompts/review-parallel/` (harness-neutral path)
- [x] `.claude/skills/review-parallel/SKILL.md` defines coordinator protocol with scoped per-reviewer `task_ref`s AND a per-harness subagent-invocation routing table (Claude Code `Agent` tool, Codex/Copilot `run_structured_turn`, external orchestrator `BackendAdapter`)
- [x] Skill explicitly forbids calling `ClaudeCodeAdapter` (CLI subprocess) from inside an active Claude Code coordinator session
- [x] Generated host adapters updated via `make generate-agent-workflows`
- [x] `make check-agent-workflows` green
- [x] Happy-path test: merged findings count equals reviewer-sum; every merged row has `merged_from` provenance
- [x] Reviewer source rows remain intact after merge (additive, not destructive)
- [x] Coordinator-side token envelope ≤ 50% of recorded baseline for the 500-line fixture diff

### Slice 2: Auto-Fix Loop Skill + Portable Command

- [x] `/auto-fix` entry exists in `portable_commands.json` with documented argument schema (`failing_test_cmd`, `max_iterations`, `scope_hint`)
- [x] `.claude/skills/auto-fix/SKILL.md` defines Precondition (feature-branch check), Per-iteration (bounded reads + commit-per-iteration + test_result + exit on first passed=true), and Finalization (slice_complete decision + `update_task_status(done)` + single post-loop `handoff_close_check`) blocks
- [x] Loop calls `get_handoff_state(sections="identity")` per iteration; never `detail="full"`
- [x] Per-iteration exit signal is `verified_tests(passed=true, commit_sha=<HEAD>)`, not `handoff_close_check.ok`
- [x] `handoff_close_check(enforce=True, require_fresh_tests=True, current_commit_sha=<HEAD>)` runs exactly once post-loop and passes `current_commit_sha` explicitly
- [x] Each iteration commits its candidate fix on the feature branch before running the test (so test provenance matches HEAD)
- [x] Finalization records a canonical `<tag>_slice_complete_<task>_autofix` decision (matches grammar in development-workflow.md § Decision IDs)
- [x] Cadence rule scoped to Claude Code: `<270` warm, `>=1200` idle, never `300`; Codex/Copilot iterate inline with equivalent MCP state
- [x] Precondition refuses to run when `target_branch` is `main`, `master`, or unset
- [x] Generated host adapters updated
- [x] Per-iteration signal test passes on fixture failing test within iteration cap
- [x] Post-loop gate test: `ok=true` with slice_complete; `ok=false` without
- [x] Bounded-reads test: iteration identity response ≤ Slice 1 baseline + 10% slack
- [ ] Cadence test runs on Claude Code runtime; asserts inline iteration on Codex/Copilot
- [x] Iteration-cap test: unfixable test triggers blocker path, exits non-zero, records no slice_complete
- [x] Precondition test: `target_branch in {main, master, None}` surfaces precondition error with zero MCP writes

### Slice 3: Cross-Vendor Backend Adapter Equivalence

- [x] `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/adapters/structured_turn.py` exists and is registered in `backend_registry` under the kind `structured-turn`
- [x] `packages/agent-orchestrator-mcp/tests/test_cross_vendor_subagent_equivalence.py` exists
- [x] Matrix covers `structured-turn` (always runs), `codex-cli` / `claude-code` (skip when binary missing), `codex-subagent` / `copilot-host` (skip when bridge module missing)
- [x] Equivalence assertion covers `(count, severity_distribution, verified_commit_sha)` across all running adapters
- [x] Drift test fails an intentionally-broken adapter wrapper
- [x] `review-parallel/SKILL.md` links to `BackendAdapter` + `backend_registry` as the external-orchestration contract, and to the per-harness routing table as the in-session fan-out contract
- [x] No per-vendor code forks — all backends reuse the existing `BackendAdapter` protocol
- [x] Default CI always has ≥1 matrix row run (`structured-turn`); never degenerates to all-skip green

### Slice 4: DASHBOARD.md Drift CI Guard <!-- lint-dashboard-txt: allow -->

- [x] `make lint-dashboard-txt` target exists in the root `Makefile`
- [x] Archived plans and test fixtures excluded via path patterns
- [x] Wired into `make check-all`
- [x] E17-7 Slice 4 Proof back-reference updated to point at this guard
- [x] Guard fires on intentional `DASHBOARD.md` reintroduction in a tracked non-archive path <!-- lint-dashboard-txt: allow -->
- [ ] `make check-all` stays green post-landing (`lint-dashboard-txt` is green; current failure is the separate `check-harness-sync` worktree-scan bug)

## Review Readiness

- [x] E17-7 Slice 2 (multi-active-task registry) merged — `b7397615`
- [x] E17-7 Slice 4 (tool compression) merged — `b7397615`
- [x] E17-7 Slice 5 (`review_findings.merge` + `(lane, status)` index) merged — `b7397615`
- [x] `make check-agent-workflows` green
- [ ] `make test-handoff` green after each schema-adjacent slice
- [x] `make test-orchestrator` green after each orchestrator-adjacent slice

## Success Criteria

- [x] `/review-parallel` and `/auto-fix` portable commands **register** across all three hosts (Claude Code, VS Code/Copilot, Codex) via `portable_commands.json` + `scripts/generate_agent_workflows.py`; the generated Claude/VS Code/Codex adapters all resolve to the same skill + prompt templates
- [x] The same MCP state (findings, review runs, test_results, decisions) results from running each skill on any of the three supported harnesses — cross-harness equivalence is on MCP state, not on wall-clock cadence
- [x] Parallel-review coordinator fan-out uses the cheapest in-harness subagent primitive (Claude Code `Agent` tool in-process; Codex + Copilot `run_structured_turn`) and stays bounded to ≤50% of the recorded serial `/branch-review` baseline for a ~500-line diff
- [x] Auto-fix loop converges on the first `verified_tests(passed=true, commit_sha=HEAD)` row; Finalization records a canonical `slice_complete` decision, sets status `done`, and calls `handoff_close_check(enforce=True, require_fresh_tests=True, current_commit_sha=<HEAD>)` exactly once with `ok=true`
- [ ] Auto-fix cadence discipline is scoped to Claude Code only; Codex and Copilot runs iterate inline and still produce the same MCP state
- [x] Cross-vendor tests always run `structured-turn` (in-repo, no host bridge required) and opportunistically run `claude-code` / `codex-cli` / `codex-subagent` / `copilot-host` when their primitives resolve at test time
- [x] `DASHBOARD.md` re-introduction in tracked non-archive paths fails CI <!-- lint-dashboard-txt: allow -->
