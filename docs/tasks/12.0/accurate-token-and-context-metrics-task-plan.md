# ADPH-3. Accurate Token and Context Metrics Instrumentation

> **Metadata**
>
> - **Date**: 2026-03-28 15:55 EDT
> - **Author**: codex

## Objective

Replace rough token and context heuristics with a durable metrics pipeline that records exact provider-reported post-execution usage when available, uses exact preflight tokenization only for explicitly supported backend/model paths, clearly labels every remaining estimate, and exposes retrospective-ready MCP surfaces for comparing the impact of ACE, artifact retrieval, slice packets, lane-history loading, and any `ctx7` usage that is explicitly reported through a structured runtime protocol. This task also makes ACE process health visible so the repo can distinguish "defined", "detecting", and "applied" states without assuming that ACE is actively running.

## Problem Statement

`agent-handoff-mcp` already captures some token telemetry, but the current system mixes exact and estimated values without a strong contract. Some backend adapters normalize provider usage, `worker_daemon.py` emits per-turn token events, and `ace_metrics.py` can aggregate token burn. But context pressure still depends on the rough `chars / 4` approximation in `lane_prompt.py`, token usage is mirrored into handoff as free-form `token_usage_*` decisions, and there is no durable normalized table or MCP query surface for per-turn metrics.

That makes retrospectives weak. We can answer "roughly how many tokens did a lane burn" but not "which turns used exact provider counts versus estimates", "how much prompt budget was spent on artifact retrieval vs ACE guidance vs lane history", or "did a tooling change reduce review cycles or merely shift tokens into another bucket". Without that distinction, the repo cannot honestly measure the impact of ACE, structured retrieval, or other context-loading strategies.

ACE itself is also only partially observable today. The reflection code exists, but operators can still end up in a misleading state where ACE is configured in docs and code yet never actually enters the detect/apply cycle because no qualifying findings have been processed through the daemon hook. The repo needs an explicit process-health model, a low-friction backfill path for historical findings, and metrics that show whether ACE is merely defined or actively producing/refining evidence.

## Constraints

- Prefer exact provider-reported token usage over local heuristics whenever the backend exposes it.
- Promise exact preflight token counts only for backend/model combinations with an explicitly supported tokenizer path; all other preflight measurements remain labeled estimates.
- If exact token counts are not available, metrics must be explicitly labeled as estimated; do not present estimates as exact measurements.
- Additive changes only for MCP surfaces; existing dashboards and `get_metrics_summary` must keep working during rollout.
- Token/context instrumentation must work across the current orchestration backends (`codex-cli`, `claude-code`, and any bridge-backed worker path that can report usage).
- Tool-impact metrics must be captured from structured runtime events or prompt composition metadata, not inferred later from free-form decision prose.
- `ctx7` usage cannot be inferred from package internals alone; any turn-level `ctx7` attribution must come from an explicit caller/runtime reporting protocol until direct instrumentation exists.
- ACE must stay low-token by default: rule detection, pending-state checks, and counter application should remain local/file-based unless a later explicitly budgeted LLM-assisted reflection mode is added.

## Workflow Principles

- Separate observed usage from estimated usage in both storage and presentation.
- Record attribution at execution time; retrospective reports should not guess which tools influenced a turn.
- Preserve enough raw per-turn detail for later analysis, then derive summaries from that structured ledger.
- Keep preflight pressure checks honest: exact where possible, explicitly approximate where not.
- Prefer cheap local ACE automation for every review cycle and reserve any future model-backed ACE curation for explicit threshold-triggered batch runs.

## Terminology

- **Observed token usage**: Provider-reported input/output/cached/reasoning/total token counts from a backend response.
- **Estimated prompt usage**: A pre-execution prompt-size estimate used only when exact tokenization is unavailable before dispatch.
- **Turn metrics record**: One durable structured record for an orchestrated worker turn, plus any review turn that is explicitly instrumented in a later slice. It includes usage, context-budget fields, backend/model metadata, and attribution flags.
- **Tool attribution**: Structured indicators showing whether a turn used ACE guidance, caller-reported `ctx7`, artifact retrieval, slice packets, lane history expansion, or other context sources.
- **Context pressure**: The budget classification for a rendered prompt relative to the model context window. After this task, the pressure source must indicate whether it came from exact tokenization or a labeled estimate.
- **ACE process health**: A small status model showing whether ACE is only configured (`defined`), has written detection records (`detecting`), or has also applied counter updates (`applied`).

## Current State Analysis

- Exact token usage already exists in some adapters:
  - [codex_cli.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/codex_cli.py) extracts and normalizes provider usage.
  - [claude_code.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/claude_code.py) does the same for Claude CLI responses.
- Backend coverage is incomplete today:
  - [codex_subagent.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/codex_subagent.py) is currently a bridge pass-through and does not yet define a shared token-normalization contract of its own.
  - [local_model.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/local_model.py) extracts message content from the OpenAI-compatible response but currently discards the upstream `usage` block instead of normalizing it.
  - [backend_registry.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/backend_registry.py) registers all supported backends, so Slice 2 must account for the full adapter set rather than only the two adapters that already normalize usage.
- `worker_daemon.py` already writes per-turn observability state and emits `SUBAGENT_TURN_OBSERVED` events with token totals.
- `ace_metrics.py` already reports `token_burn` and `context_pressure`, but `token_burn` reads JSONL worker events rather than a durable structured DB ledger, and `context_pressure` only aggregates warning events.
- `lane_prompt.py` currently estimates prompt tokens as `len(prompt) // 4`, which is explicitly approximate and backend-agnostic.
- The current handoff-facing token record is a free-form decision string (`token_usage_c{cycle}_{phase}`), which is useful for humans but poor for queryability and retrospective breakdowns.
- No current metrics surface attributes token usage to ACE guidance, artifact retrieval, slice-packet scope, or lane-history expansion in a durable structured ledger, and `ctx7` attribution is limited to coarse decision-text heuristics rather than turn-level telemetry.
- ACE reflection exists in `ace_reflect.py`, `worker_daemon.py`, and `orchestrator_daemon.py`, but there is no durable MCP-visible health summary that tells operators whether ACE has ever created `.task-state/ace_reflect_log.jsonl`, whether pending entries exist, whether counters were last applied successfully, or whether historical rule-tagged findings need a one-time backfill.

## Target Outcome

`agent-handoff-mcp` should expose a first-class turn-metrics ledger and summary surfaces. Each orchestrated worker turn should record exact observed token usage when the backend provides it, plus a clearly labeled context-budget measurement source (`observed`, `tokenizer_estimate`, or `char_estimate`). Prompt composition should capture structured section sizes and tool-attribution flags so retrospectives can compare token burn and convergence across ACE guidance, artifact retrieval, slice packets, lane history, and any explicitly caller-reported `ctx7` usage. `get_metrics_summary` should continue to work, but it should be backed by stronger structured data instead of mostly JSONL scans and rough pressure warnings.

ACE should also have an explicit operational health surface. Operators should be able to tell whether ACE is configured but idle, actively logging rule references, blocked on `make ace-reflect`, or fully applied. Historical findings with valid `[sr-NNN]` / `[rg-NNN]` references should be backfillable without requiring another full review cycle, and the default ACE path should remain local and near-zero-token.

## Context Loading

- Rules: [instructions.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/instructions.md), [development-workflow.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/rules/development-workflow.md)
- Contracts: [agent-handoff-mcp.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/agent-handoff-mcp.md)
- Handoff/MCP state: inspect recent `get_metrics_summary` output, token-usage decision records, and open findings under `agentic-development-process-hardening-epic`
- External docs via `ctx7` only if: official tokenizer/model-usage documentation is needed for a backend-specific exact-tokenization path

## Contract and Boundary Impact

| Boundary                     | Owner                         | Current Contract                                                                                                        | Expected Change                                                                                                                                                 | Compatibility Needed?                                           | Verification            |
| ---------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------- |
| Worker observability ledger  | agentic-tooling               | [agent-handoff-mcp.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/agent-handoff-mcp.md) | Add a durable turn-metrics schema and MCP read surfaces for per-turn token/context usage                                                                        | Yes; additive schema and additive MCP tools only                | pytest + contract doc   |
| Adapter token normalization  | orchestration backends        | Current adapter-local usage normalization in `codex_cli.py` and `claude_code.py`                                        | Tighten the normalized token-usage contract and mark exactness/source explicitly                                                                                | Yes; retain existing normalized fields while extending metadata | unit tests              |
| Context-pressure measurement | orchestration prompt builder  | `lane_prompt.py` approximate `chars / 4` estimator                                                                      | Replace unlabeled rough estimates with exact tokenization only on explicitly supported backend/model paths and explicit estimate source labels otherwise        | Yes; pressure output remains available but gets source metadata | pytest                  |
| Retrospective metrics        | ACE / orchestration reporting | `ace_metrics.py` snapshot sections                                                                                      | Add structured token/context and tool-attribution sections that can support retrospective analysis, including caller-reported `ctx7` attribution when available | Yes; additive snapshot keys                                     | pytest + smoke snapshot |
| ACE process health           | review/observability tooling  | daemon-local `ace_reflect_log.jsonl` writes plus manual `make ace-reflect` apply step                                   | Surface defined/detecting/applied status, pending counts, last-apply evidence, and a backfill path for historical rule-tagged findings                          | Yes; additive reporting and helper commands only                | pytest + smoke check    |

## Proposed Solution

Implement this in five slices. First, create a durable per-turn metrics ledger in handoff state so token/context data is not stranded in JSONL logs or decision prose. Second, tighten token normalization and context measurement so exact post-execution counts are used whenever a backend exposes them, preflight exactness is used only on supported tokenizer paths, and all remaining estimates are explicitly labeled. Third, record tool-attribution and prompt-composition breakdowns so retrospectives can measure the impact of ACE, artifact retrieval, slice packets, lane-history helpers, and any `ctx7` usage that callers report through a structured protocol. Fourth, update the metrics/reporting surfaces and docs so operators can query these metrics directly through MCP and use them in retrospectives without parsing logs by hand. Fifth, add ACE process-health reporting and a historical-backfill path so ACE can be activated, audited, and operated without hidden token cost.

## Files and Surfaces to Change

| Surface  | File                                                                                        | Change                                                                                                                                                                             |
| -------- | ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`                                  | Add durable turn-metrics storage/query helpers and export support                                                                                                                  |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`                                   | Expose MCP read surfaces for turn metrics and retrospective summaries                                                                                                              |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py`             | Replace unlabeled rough context measurement with exact-or-labeled-estimate metrics and section attribution                                                                         |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_metrics.py`             | Aggregate from structured turn metrics and add tool-impact retrospective sections                                                                                                  |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_reflect.py`             | Add a backfill/helper path and status helpers for ACE detection/apply health                                                                                                       |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/codex_cli.py`      | Ensure normalized usage includes exactness/source metadata and context-window fields                                                                                               |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/claude_code.py`    | Same normalization/metadata tightening for Claude                                                                                                                                  |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/codex_subagent.py` | Define bridge-compatible token-usage normalization or explicitly preserve pass-through usage metadata under the shared contract                                                    |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/local_model.py`    | Extract and normalize the OpenAI-compatible `usage` block alongside message content parsing                                                                                        |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/backend_adapter.py`         | Keep the shared result contract aligned with richer token-usage metadata                                                                                                           |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/backend_registry.py`        | Keep Slice 2 backend coverage aligned with the full registered backend set                                                                                                         |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_runner.py`           | Verification-only unless review-turn instrumentation is explicitly added in a later slice                                                                                          |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/orchestrator_daemon.py`     | Surface ACE pending/apply advisories through a clearer health summary if needed                                                                                                    |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`           | Write structured per-turn metrics records, reduce reliance on free-form token-usage decisions, and keep ACE detection cheap/local while emitting enough state for health reporting |
| test     | `packages/agent-handoff-mcp/tests/test_handoff_state.py`                                    | Add DB storage/query tests for turn metrics                                                                                                                                        |
| test     | `packages/agent-handoff-mcp/tests/test_ace_metrics.py`                                      | Add retrospective summary and exact-vs-estimate tests                                                                                                                              |
| test     | `packages/agent-handoff-mcp/tests/test_ace_reflect.py`                                      | Add ACE health/backfill tests and pending-state coverage                                                                                                                           |
| test     | `packages/agent-handoff-mcp/tests/test_lane_prompt.py`                                      | Add context-measurement and pressure-source tests                                                                                                                                  |
| test     | `packages/agent-handoff-mcp/tests/test_backend_registry.py`                                 | Verify backend coverage assumptions and registry-backed Slice 2 support remain aligned                                                                                             |
| test     | `packages/agent-handoff-mcp/tests/test_codex_subagent.py`                                   | Verify bridge-backed token-usage normalization or pass-through metadata handling                                                                                                   |
| test     | `packages/agent-handoff-mcp/tests/test_local_model.py`                                      | Verify OpenAI-compatible `usage` extraction and normalization                                                                                                                      |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md`                                               | Document the turn-metrics schema, exactness rules, and new MCP surfaces                                                                                                            |
| docs     | `docs/agentic/playbooks/ace-pruning-playbook.md`                                            | Update the ACE/ctx7 retrospective section to reference measurable tool-attribution metrics and ACE process-health signals                                                          |
| docs     | `docs/agentic/instructions.md`                                                              | Add or preserve only a short pointer to the playbook if workflow routing needs it; avoid re-bloating the cold-start file                                                           |
| docs     | `docs/agentic/rules/branch-review-guide.md`                                                 | Clarify ACE activation prerequisites, backfill path, and low-token operating model                                                                                                 |

## Related Files

| File                                                                               | Note                                                                                                                                                    |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/dashboard_live.py` | Current one-line metrics footer should stay aligned with richer token/context summaries                                                                 |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/dashboard_tui.py`  | Existing lane-token display may later consume the new ledger                                                                                            |
| `docs/tasks/8.0/ace-ctx7-documentation-evolution-task-plan.md`                     | Earlier ACE/ctx7 metrics work that explicitly narrowed token-cost claims due to missing prompt telemetry                                                |
| `docs/tasks/12.0/selective-memory-and-evaluation-metrics-task-plan.md`             | Prior metrics hardening task that added derivable ACE metrics but did not solve prompt-level measurement accuracy                                       |
| `packages/codex-subagent-bridge/src/codex_subagent_bridge.py`                      | Potential future source for richer usage metadata on bridge-backed turns                                                                                |
| `.task-state/ace_reflect_log.jsonl`                                                | Existing ACE detection log path whose absence should now be represented explicitly in process-health reporting rather than silently implying inactivity |

## Verification Strategy

- Deterministic tests:
  - `PYTHONPATH="packages/agent-handoff-mcp/src:packages/codex-subagent-bridge/src" python3 -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py packages/agent-handoff-mcp/tests/test_ace_metrics.py packages/agent-handoff-mcp/tests/test_lane_prompt.py -q`
- Runtime-parity / environment checks:
  - Run one worker turn through a backend that reports exact usage and confirm the stored record marks `usage_source="observed"`
  - Run one preflight path without exact tokenizer support and confirm the stored pressure record marks `usage_source="char_estimate"` or `usage_source="tokenizer_estimate"`
  - If review-turn instrumentation is added later, run one review path and confirm review turns enter the same ledger with an explicit phase/source label
  - Run one ACE-tagged review finding through the daemon path and confirm `.task-state/ace_reflect_log.jsonl` is created and reported as `detecting`
  - Run `make ace-reflect TASK=<task-ref>` and confirm the process-health surface reports `applied` with pending count cleared
  - Run one historical backfill path for existing rule-tagged findings and confirm ACE can transition from `defined` to `detecting`/`applied` without a new review cycle
- Contract/fixture verification:
  - Verify [agent-handoff-mcp.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/contracts/agent-handoff-mcp.md) documents which fields are exact, which are estimated, and how attribution flags are populated
- Manual verification:
  - Use MCP to inspect the latest turn metrics for a task and confirm tool-attribution fields show whether ACE guidance, `ctx7`, artifact retrieval, and slice packets were involved

## Slice Delivery

### Slice 1: Durable Turn Metrics Ledger

**Goal**: Store token/context metrics as structured handoff data instead of relying on JSONL scans and free-form token-usage decisions.

Changes:

- Add a durable turn-metrics table or equivalent first-class ledger in `handoff.db` with fields for:
  - `task_ref`, `lane_id`, `session`, `cycle`, `phase`, `backend`, `model`
  - `thread_id`, `turn_id`
  - `input_tokens`, `output_tokens`, `cached_input_tokens`, `reasoning_output_tokens`, `total_tokens`
  - `model_context_window`
  - `usage_source` (`observed`, `tokenizer_estimate`, `char_estimate`)
  - `pressure_level`
  - `prompt_tokens`, `prompt_chars`
  - structured attribution payload / section-size payload
- Add MCP read surfaces for recent turn metrics and aggregated summaries by task/lane/backend/model.
- Keep the human-readable decision trail optional or reduce it to summary-only; the durable ledger becomes the canonical metrics source.

Proof:

- Storage/query tests pass for inserts, lane/task filtering, and empty-state behavior
- MCP responses expose the exact-vs-estimate distinction without parsing prose

### Slice 2: Exactness and Context Measurement Upgrade

**Goal**: Replace unlabeled rough estimates with exact measurements where supported and explicit estimate labels otherwise.

Changes:

- Tighten the backend token-usage normalization contract so every backend returns:
  - normalized counts
  - `usage_source`
  - `model_context_window` when known
- Upgrade `lane_prompt.py` context measurement:
  - use backend/model-specific tokenization only when an explicit supported tokenizer path exists
  - otherwise keep the estimate path, but mark it explicitly as `tokenizer_estimate` or `char_estimate`
  - stop presenting `chars / 4` as if it were an exact token count
- When a turn later returns observed `input_tokens`, preserve both the preflight pressure source and the post-execution observed counts so drift can be measured.

Proof:

- Tests cover exact normalized usage from adapters
- Tests cover explicit estimate labeling when exact tokenization is unavailable
- Pressure metrics distinguish source type instead of silently collapsing to one number

### Slice 3: Tool Attribution and Prompt Breakdown

**Goal**: Make retrospectives capable of measuring the impact of ACE, artifact retrieval, and other context helpers, while giving `ctx7` a clear structured reporting path instead of implied package-native visibility.

Changes:

- Record structured attribution flags on each turn, such as:
  - `used_ace_guidance`
  - `used_artifact_context`
  - `used_slice_packet`
  - `used_recent_lane_history`
  - `used_ctx7` when an explicit caller/runtime protocol reports it
  - `ctx7_query_count` when that same protocol reports query counts
- Record prompt section-size breakdowns so token/context pressure can be analyzed by source category rather than only as one total.
- Ensure attribution is produced from actual runtime/prompt-building paths, plus explicit caller/runtime reports for `ctx7`, not from later decision text scans.

Proof:

- Tests verify attribution flags are present when the relevant context sources are used
- Stored metrics can distinguish prompt growth from artifact context vs guidance vs history

### Slice 4: Retrospective Surfaces and Documentation

**Goal**: Expose the new metrics through MCP and document how to use them in ACE/`ctx7` retrospectives.

Changes:

- Update `ace_metrics.py` and `get_metrics_summary` to aggregate from the new ledger and add sections for:
  - exact vs estimated token-usage coverage
  - token burn by backend/model/lane
  - pressure by source type
  - tool-attributed token/context usage for ACE, artifact retrieval, slice-packet flows, and caller-reported `ctx7` where present
- Update the MCP contract doc to define the new metrics schema and read surfaces.
- Update [ace-pruning-playbook.md](/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/playbooks/ace-pruning-playbook.md) so retrospective guidance references measurable signals rather than vague token-savings claims, and keep any `instructions.md` change to a minimal pointer only if routing needs it.

Proof:

- Snapshot tests verify the new sections and empty-state semantics
- A smoke run shows retrospective summaries can answer tool-impact questions directly

### Slice 5: ACE Process Health and Backfill

**Goal**: Make ACE activation visible, backfillable, and cheap enough to run continuously without unreasonable token cost.

Changes:

- Add an ACE process-health summary that reports at least:
  - whether ACE rules are defined in the instruction file
  - whether `.task-state/ace_reflect_log.jsonl` exists
  - pending unprocessed entry count
  - last successful counter-apply evidence
  - whether historical rule-tagged findings exist in handoff without any reflect-log history
- Add or document a backfill helper for historical findings whose descriptions already include `[sr-NNN]` / `[rg-NNN]`, so operators can seed ACE without waiting for another daemon review cycle.
- Update branch-review/operator guidance so ACE’s default path is clearly local and low-token:
  - daemon detection is local
  - `make ace-reflect` is local
  - any future model-backed ACE curation must be optional, budgeted, and batch-triggered rather than per-review

Proof:

- Tests cover the health-state transitions `defined -> detecting -> applied`
- A smoke check shows a repo with rule-tagged findings but no reflect log reports an actionable backfill-needed state
- ACE health surfaces make it obvious why a repo is not actively reflecting, without requiring operators to inspect logs by hand

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [x] Confirmed whether backend/model exact-tokenization behavior requires `ctx7`.
- [x] Recorded compatibility expectations for new metrics storage and MCP read surfaces.

## Slice 1: Durable Turn Metrics Ledger

- [x] Added a durable turn-metrics schema and query helpers.
- [x] Exposed additive MCP read surfaces for turn metrics.
- [x] Reduced canonical dependence on token-usage decision prose.
- [x] Added storage/query tests.

## Slice 2: Exactness and Context Measurement Upgrade

- [x] Tightened backend token-usage normalization contract with explicit source metadata.
- [x] Included `codex_subagent.py`, `local_model.py`, and `backend_registry.py` in Slice 2 backend coverage.
- [x] Replaced unlabeled rough context estimates with exact-or-labeled-estimate measurement.
- [x] Preserved both preflight pressure data and post-execution observed counts where available.
- [x] Added adapter and lane-prompt tests.

## Slice 3: Tool Attribution and Prompt Breakdown

- [x] Added structured attribution fields for ACE, artifact retrieval, slice packets, lane history, and caller-reported `ctx7`.
- [x] Added prompt section-size breakdowns to durable metrics storage.
- [x] Verified attribution comes from runtime/prompt-building paths rather than prose inference.

## Slice 4: Retrospective Surfaces and Documentation

- [x] Updated `ace_metrics.py` / `get_metrics_summary` to use the stronger metrics ledger.
- [x] Documented exact vs estimated semantics in the MCP contract.
- [x] Updated retrospective guidance in `playbooks/ace-pruning-playbook.md`, with only a minimal `instructions.md` pointer if needed.
- [x] Verified retrospectives can answer tool-impact questions directly from MCP data.

## Slice 5: ACE Process Health and Backfill

- [x] Added ACE process-health reporting for defined/detecting/applied states.
- [x] Added or documented a historical backfill path for rule-tagged findings.
- [x] Updated operator guidance so ACE’s default path is explicitly local and low-token.
- [x] Verified health surfaces can explain a missing `ace_reflect_log.jsonl`.

## Stretch Goals

- [x] Add backend-specific exact tokenizers for preflight prompt measurement where official model-tokenization support exists and is safe to depend on.
- [x] Add variance/drift reporting between preflight prompt estimates and post-execution observed input tokens.
- [x] Add an optional, explicitly budgeted model-backed ACE curation mode that runs only on threshold-triggered batch schedules and records its own token cost separately from the default local ACE path.

## Success Criteria

- [x] `agent-handoff-mcp` exposes durable per-turn token/context metrics instead of relying on JSONL scans and free-form decision prose.
- [x] Exact provider token usage is surfaced when available, and every remaining estimate is clearly labeled as an estimate.
- [x] Retrospective summaries can compare ACE, artifact retrieval, and other instrumented tool choices using structured token/context attribution rather than narrative guesswork, with `ctx7` included when callers report it through the new protocol.
- [x] Operators can tell whether ACE is merely defined, actively detecting, or fully applied, and can activate/backfill it without guessing or incurring hidden model-token cost.
- [x] `WriteActor.agent` carries the unified model identity (concatenated from model label + reasoning level) so decisions and metrics surfaces identify the actual model, not the harness.
- [x] Template `Author` fields use model identity (e.g., "Opus 4.6 high") as the canonical author convention.
- [x] Separate `model`, `model_label`, and `reasoning_level` fields on `WriteActor` provide granular metrics breakdowns while feeding the unified `agent` string.

---

## Addendum: Agent Model Identity and Decision Enrichment

> **Date**: 2026-03-28
> **Author**: Opus 4.6 high

### Problem

`WriteActor.agent` is a free-form string with no validation beyond whitespace trimming. Different MCP clients pass inconsistent values: "copilot-chat", "Github Copilot", "codex", etc. These identify the **harness** (the tool/IDE surface dispatching the call), not the **model** (the LLM actually reasoning). The distinction matters because:

- The same harness runs different models over time (Copilot runs Opus 4.6, Sonnet 4, GPT-5.4, etc.)
- Reasoning level (high/medium/low) dramatically affects token burn and output quality
- Retrospectives that group by harness cannot distinguish model-driven performance differences
- Runtime model provenance is not carried in a structured way through handoff write surfaces, and token data still lives in separate JSONL events or `token_usage_c{cycle}_{phase}` decision prose

Additionally, `BackendResult` has no `model` field. The model name used during execution is tracked only as a loop variable in `worker_daemon.py` and never flows back from the adapter response. Adapters currently discard the response-reported model (which may differ from the requested model).

### Current State

| Surface                   | What is recorded                                   | What is missing                                                |
| ------------------------- | -------------------------------------------------- | -------------------------------------------------------------- |
| `WriteActor.agent`        | Free-form harness string ("codex", "copilot-chat") | Model name, reasoning level                                    |
| `BackendResult`           | `token_usage` (opaque dict), `raw_payload`         | `model`, `reasoning_effort`, `response_model`                  |
| `_record_observability`   | model (from dispatch variable), reasoning effort   | Response-reported model, per-decision token link               |
| Decision records          | `agent` column (caller identity)                   | Separate model/reasoning provenance or linked turn metrics     |
| Planning templates        | `[agent-name or handle]` placeholder               | Optional separate runtime-provenance field only where needed   |
| Generated runtime reports | Agent-oriented placeholders                        | Separate model-provenance field where runtime identity matters |
| `codex_cli.py`            | Normalized token counts                            | Response model name                                            |
| `claude_code.py`          | Partial token counts (reasoning hardcoded 0)       | `response["model"]`, extended thinking tokens                  |
| `local_model.py`          | Nothing; `data["usage"]` discarded                 | All token/model fields                                         |
| `codex_subagent.py`       | Pass-through from bridge                           | No fallback extraction                                         |

### Target Convention

**Unified model identity: `WriteActor.agent` and template `Author` = model + reasoning level.**

Separate fields (`model`, `model_label`, `reasoning_level`) exist on `WriteActor` for granular metrics queries, but the canonical `agent` value is a concatenated string derived from them: `"{model_label} {reasoning_level}"`. This gives both:

- **Unified identity** in decision records, templates, and handoff provenance ("Opus 4.6 high", "gpt-5.4 high")
- **Granular breakdowns** for metrics surfaces that need to filter by model or reasoning level independently

Derivation rule:

- When `model_label` and `reasoning_level` are both available, `agent = f"{model_label} {reasoning_level}"` (e.g., "Opus 4.6 high")
- When only `model_label` is available, `agent = model_label` (e.g., "Opus 4.6")
- When neither is available (legacy or non-instrumented callers), `agent` falls back to the caller-provided string or the env default

Examples:

- Copilot Chat running Claude Opus 4: `model = "claude-opus-4-0520"`, `model_label = "Opus 4.6"`, `reasoning_level = "high"` => `agent = "Opus 4.6 high"`
- Codex running GPT-5.4: `model = "gpt-5.4"`, `model_label = "gpt-5.4"`, `reasoning_level = "high"` => `agent = "gpt-5.4 high"`
- Legacy caller with no model info: `agent = "codex"` (unchanged fallback)

Template `Author` in all planning docs (EPIC, TASK_PLAN, ROADMAP) and generated reports uses the same convention: the unified model identity string, not the harness name.

For orchestrated worker turns, `worker_daemon.py` resolves the model from the adapter response (preferred) or from the dispatch config (fallback) and populates both the separate fields and the derived `agent` string.

### Proposed Changes

#### Slice 6: Agent Model Identity and Decision Enrichment

**Goal**: Populate `WriteActor.agent` with a unified model identity string (concatenated from granular model + reasoning fields) and update all template `Author` fields to use this convention. Keep separate fields for metrics granularity. Link decisions to turn-level token metrics without duplicating the ledger.

**6a. Extend `WriteActor` and `BackendResult`**

- Add optional fields to `WriteActor`:
  - `model: str | None` ; the LLM model name (e.g., "claude-opus-4-0520", "gpt-5.4")
  - `model_label: str | None` ; human-friendly label (e.g., "Opus 4.6")
  - `reasoning_level: str | None` ; one of "high", "medium", "low"
- Add fields to `BackendResult`:
  - `response_model: str | None` ; the model reported by the backend response
  - `reasoning_effort: str | None` ; the reasoning level used for this execution
- Update `build_write_actor` to derive `agent` from `model_label` and `reasoning_level` when both are provided: `agent = f"{model_label} {reasoning_level}"`. When only `model_label` is available, `agent = model_label`. When neither is available, preserve the caller-provided `agent` string as today.
- Add a `normalize_model_identity(model_label, reasoning_level) -> str` helper used by both `build_write_actor` and template rendering.

**6b. Extract response model from each adapter**

- `codex_cli.py`: Extract model from result JSON if present; fall back to dispatch model.
- `claude_code.py`: Extract `response["model"]` from Claude CLI JSON output.
- `local_model.py`: Extract `data["model"]` from OpenAI-compatible response (alongside the `usage` fix from Slice 2).
- `codex_subagent.py`: Extract model from bridge response payload if present.

**6c. Enrich decision provenance with unified model identity**

- `agent` on decision records carries the unified model identity string (e.g., "Opus 4.6 high"), not the harness name. The separate `model`, `model_label`, and `reasoning_level` fields remain available for granular queries.
- **Persistence path for granular fields:**
  - **decisions table**: add nullable columns `model TEXT`, `model_label TEXT`, `reasoning_level TEXT` alongside the existing `agent` column. These are populated by `_resolve_write_actor` at write time. The `agent` column value is derived from these fields; storing all three allows independent filtering/grouping in metrics queries.
  - **Slice 1 turn-metrics ledger**: each turn record already carries model and reasoning_effort from the adapter response. The ledger is the canonical source for per-turn token consumption linked to model identity.
  - **`BackendResult`**: `response_model` and `reasoning_effort` fields (added in 6a) flow from adapters through `worker_daemon` into both the turn-metrics ledger and the decision write path.
- Do **not** add `token_total`, `token_input`, or `token_output` to `decisions`; route token consumption into the Slice 1 turn-metrics ledger and link decisions to that ledger when correlation is needed.
- `_resolve_write_actor` populates the separate model fields from the adapter response and then derives the unified `agent` string via `normalize_model_identity`.
- `worker_daemon._record_token_usage_to_handoff` should evolve toward ledger linkage or aggregate read surfaces rather than per-decision token columns.

**6d. Update all template `Author` fields to use unified model identity**

- Replace the `[agent-name or handle]` placeholder in all templates with `{{MODEL_IDENTITY}}` (the unified model identity string).
- Templates affected: `EPIC.template.md`, `TASK_PLAN.template.md`, `ROADMAP.template.md`, `WORKTREE_LANE_BRIEF.template.md`, `WORKTREE_LANE_REPORT.template.md`, and any `DECISION_*.template.md` files.
- The convention: `Author` in templates = the model and reasoning level that produced the document (e.g., "Opus 4.6 high"), not the harness or human handle.

**6e. Add `AgentModel` reference registry (optional normalization)**

- Add a lightweight mapping in `enums.py` or a new `models.py` for known model label normalization:
  - `"claude-opus-4-0520"` -> `"Opus 4.6"`
  - `"claude-sonnet-4-20250514"` -> `"Sonnet 4"`
  - `"gpt-5.4"` -> `"gpt-5.4"`
  - `"o3"` -> `"o3"`
- This is not an exhaustive allowlist; unknown models pass through as-is. The registry only provides human-friendly labels for known models.

### Files to Change (Slice 6)

| Surface  | File                                                                                        | Change                                                                                                                                                       |
| -------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`                                  | Extend `WriteActor` with model fields; `build_write_actor` derives unified `agent` from model_label + reasoning_level; add `normalize_model_identity` helper |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/backend_adapter.py`         | Add `response_model` and `reasoning_effort` to `BackendResult`                                                                                               |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/codex_cli.py`      | Extract response model from result JSON                                                                                                                      |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/claude_code.py`    | Extract `response["model"]`                                                                                                                                  |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/local_model.py`    | Extract `data["model"]`                                                                                                                                      |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/adapters/codex_subagent.py` | Extract model from bridge payload                                                                                                                            |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`           | Populate model fields from adapter response; derive unified `agent` via `normalize_model_identity`; link to turn-metrics ledger                              |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/enums.py`                                 | Add known model label registry                                                                                                                               |
| template | `docs/agentic/templates/EPIC.template.md`                                                   | Replace `Author` placeholder with `{{MODEL_IDENTITY}}`                                                                                                       |
| template | `docs/agentic/templates/TASK_PLAN.template.md`                                              | Replace `Author` placeholder with `{{MODEL_IDENTITY}}`                                                                                                       |
| template | `docs/agentic/templates/ROADMAP.template.md`                                                | Replace `Author` placeholder with `{{MODEL_IDENTITY}}`                                                                                                       |
| template | `docs/agentic/templates/WORKTREE_LANE_BRIEF.template.md`                                    | Replace `Author` placeholder with `{{MODEL_IDENTITY}}`                                                                                                       |
| template | `docs/agentic/templates/WORKTREE_LANE_REPORT.template.md`                                   | Replace `Author` placeholder with `{{MODEL_IDENTITY}}`                                                                                                       |
| template | `docs/agentic/templates/DECISION_*.template.md`                                             | Replace `Author` placeholder with `{{MODEL_IDENTITY}}` if present                                                                                            |
| test     | `packages/agent-handoff-mcp/tests/test_enums.py`                                            | Update `build_write_actor` tests for unified identity derivation and model field population                                                                  |
| test     | `packages/agent-handoff-mcp/tests/test_handoff_state.py`                                    | Unified model identity in decision records; legacy fallback; decision-to-metrics linkage                                                                     |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md`                                               | Document unified model identity derivation, granular field semantics, and decision-to-ledger linkage                                                         |

### Slice 6 Checklist

- [x] Extended `WriteActor` with `model`, `model_label`, `reasoning_level` fields.
- [x] Extended `BackendResult` with `response_model` and `reasoning_effort` fields.
- [x] `build_write_actor` derives unified `agent` string from `model_label` + `reasoning_level`.
- [x] `normalize_model_identity` helper produces the concatenated identity string.
- [x] Known-model label registry added for human-friendly model name normalization.
- [x] Each adapter extracts response model from backend output.
- [x] `agent` on decision records carries the unified model identity, not the harness name.
- [x] Token consumption remains canonical in the turn-metrics ledger, with linkage instead of per-decision token columns.
- [x] All template `Author` fields updated to use `{{MODEL_IDENTITY}}` (unified model identity).
- [x] Contract doc updates describe unified model identity derivation and granular field semantics.
- [x] Tests cover model normalization, identity concatenation, legacy fallback, and unknown-model pass-through.
