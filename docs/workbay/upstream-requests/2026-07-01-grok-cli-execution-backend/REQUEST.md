# Upstream implementation request — `grok-cli` execution backend (Composer-2.5 junior worker)

**Target repo:** `agentic-protocol-monorepo` (WorkBay orchestrator mechanism).
**Consumer:** `context-alt-text-monorepo`.
**Spike evidence:** `MAINT-grok-backend-spike-20260701` (handoff decisions #1107, #1108; verified tests #344–#346).
**Consumer-side harness (acceptance oracle):** `scripts/spike/grok-backend-probe.sh` + `make grok-backend-probe`.

## Motivation

We want a senior/junior split: a frontier planner (Opus or Codex) authors task plans + records handoff state; a **Composer 2.5** implementer executes under that guidance — with **zero pasted context** (the junior pulls its plan/findings from the shared WorkBay MCP DB by `task_ref`). Grok Build ships a headless CLI (`grok 0.2.81`) that reaches WorkBay MCP natively, so Composer 2.5 can be a first-class lane worker. The orchestrator has **no grok backend today** — `backend_registry.py` declares only `codex-cli`, `codex-subagent`, `copilot-host`, `claude-code`, `structured-turn`, `local-model-openai`.

## Evidence (what the spike proved)

| # | Result | Evidence |
|---|--------|----------|
| 1 | Headless grok reaches WorkBay MCP | `grok mcp doctor`: handoff **25 tools**, orchestrator **16 tools**, handshake OK (protocol 2025-06-18) |
| 2 | grok pulls a specific task's state, zero paste | `grok -p … -m grok-composer-2.5-fast` called `get_handoff_state(task_ref=…)` → returned the task's exact objective+status |
| 3 | **Write-back works**; provenance guard accepts | grok wrote `test_result` rows **345, 346** via `record_event`; `get_verified_tests` confirms `passed=true`, branch+commit derived server-side |
| 4 | **Composer 2.5 = grok's `grok-composer-2.5-fast`** | session metadata labels it *"Cursor's latest coding model", agentType `cursor`*; `grok-build` = *"xAI's latest coding model"* (the model the consumer bans) |
| 5 | `-m` alone does **not** guarantee Composer-only output | `[ui] fork_secondary_model="grok-build"` makes grok-build emit its own `AssistantItem`s into the turn (`--debug-file`: `AssistantItem model_id=grok-build`) |
| 6 | Enforcement works | `-m grok-composer-2.5-fast` + `--no-plan --no-subagents` + repoint `fork_secondary_model→grok-composer-2.5-fast` ⇒ **4/4 AssistantItems Composer-2.5, 0 grok-build** |
| 7 | `--json-schema` does not populate the structured channel | grok narrates + fences JSON into `text`; `structuredOutput:null`, `structuredOutputError:"expected value at line 1 column 1"` |
| 8 | Writes without explicit actor are **misattributed** | rows 345/346 recorded `agent="Claude Opus 4.8 high"` (runtime default), not grok |

## Goal

Ship a `grok-cli` `BackendAdapter` (a sibling of `adapters/codex_cli.py`) so the orchestrator can dispatch lane work to a headless **Composer-2.5** worker that pulls context from MCP and writes results back correctly attributed — with a hard guarantee that **no grok-build output** enters the work product.

---

## Part A — the `grok-cli` BackendAdapter

Clone `adapters/codex_cli.py`; register in `backend_registry.py` as `kind:"cli"`, availability probe `command -v grok`.

### A1. Invocation contract

`execute(prompt, schema, worktree_path, model, reasoning_effort, session_mode, env, …) → BackendResult`, mapped to grok flags:

| Adapter arg | grok flag | Notes |
|---|---|---|
| prompt | `--prompt-file <path>` | write the rendered lane prompt to a temp file — **do not** pass via `-p` inline (avoids quote/newline mangling). |
| worktree_path | `--cwd <path>` | use the orchestrator's existing lane worktree; **do not** use grok `--worktree` (it would double-create). |
| model | `-m grok-composer-2.5-fast` | pinned; see Part B. |
| reasoning_effort | `--reasoning-effort <low\|medium\|high\|xhigh\|max>` | grok **supports** reasoning effort — declare `supports_reasoning_effort:true` (unlike `codex-cli`). |
| schema | `--json-schema <schema>` | see A2. |
| (bound) | `--max-turns <N>` | bound the integration point. |
| (unattended) | `--always-approve` | auto-approve MCP tool calls. |

### A2. Structured-output parsing (Evidence #7)

`--json-schema` does **not** reliably populate grok's structured-output channel when the agent narrates; the JSON lands (often fenced) inside `text`, and `structuredOutput` is `null`. The adapter must **extract JSON from `text`** (fenced-block first, then first balanced `{…}`) — the same parse `codex_cli.py` already performs — and only then fall back to `structuredOutput`. Optionally append a final "emit JSON only, no prose" turn. Populate `BackendResult` (`handoff_action`, `summary`, `changed_files`, `merge_ready`, `tests_run`, `blockers`, `token_usage`, `response_model`) from the parsed object.

### A3. MCP wiring

The consumer registers the two WorkBay servers via `grok mcp add` (see Appendix). The adapter should prefer a **worktree-scoped** `./.grok/config.toml` (grok reads project-scope config from `cwd`) so MCP servers + model pins travel with the lane and never depend on the operator's global `~/.grok/config.toml`.

---

## Part B — Composer-2.5-only enforcement (Evidence #4–6) — **hard requirement**

The consumer bans `grok-build` (lower quality). Interpretation, per the consumer's engineering-heuristics literature (Fowler *observable behavior*; Farley *essential vs accidental complexity*; information-hiding at integration points): **"grok-build must never author output"** — i.e. zero `grok-build` `AssistantItem`s / task tokens. Residual grok-build/`grok-4.20-multi-agent` references in grok's **startup credential + prefetch warmup** are non-observable vendor internals (no task output) and are out of scope here (see Part D).

The adapter MUST, per lane session:
1. Pin `-m grok-composer-2.5-fast`.
2. Pass `--no-plan --no-subagents` (grok's plan role / subagents can select other models).
3. Ensure the effective grok config has `fork_secondary_model = "grok-composer-2.5-fast"` — via the worktree-scoped `./.grok/config.toml` from A3, **not** by mutating the operator's global config (the spike mutated `~/.grok/config.toml` as a shortcut; the real adapter must session-scope it).
4. Hard-fail if the resolved model is `grok-build`.
5. **Verify** after the turn: assert `0` `AssistantItem model_id=grok-build` (a `--debug-file` scan, or a token-usage-by-model check). Treat any grok-build-authored item as a failed turn.

---

## Part C — provenance / actor attribution (Evidence #8) — **required for a correct audit trail**

grok's MCP writes without an explicit `actor` are attributed to the WorkBay runtime's default identity (observed: `"Claude Opus 4.8 high"`), silently misattributing junior-worker writes to the orchestrator.

1. The adapter must inject an explicit `actor` into every worker MCP write: `actor.model = "grok-composer-2.5-fast"`, plus the lane's `branch` / `commit_sha` / `lane_id`. (The lane prompt or a wrapper policy must instruct the worker to pass it, or the orchestrator must post-attribute.)
2. WorkBay's identity/model registry must **recognize `grok-composer-2.5-fast`** (canonical slug + label) so `actor.model` validation passes and `model_label` derives correctly. Add the grok/Composer model identities to the registry.

---

## Part D — informational: xAI / grok-CLI note (out of scope for WorkBay)

There is currently **no CLI/config knob** to suppress grok's startup credential/prefetch warmup of `grok-build` and `grok-4.20-multi-agent`. These produce **no task output** (Part B item 5 holds), so they do not affect the work product and are explicitly **not** a WorkBay deliverable. If a consumer needs literal "grok-build process never initialized," that is a **grok-CLI feature request to xAI** (a flag to disable startup model prefetch / pin all internal roles to one model). Track separately; do not block this adapter on it.

---

## Acceptance criteria

The consumer harness is the oracle — reuse it upstream:

1. `list_available_backends(probe=true)` includes `grok-cli` with `is_available:true` when `grok` is on PATH, `supports_reasoning_effort:true`.
2. A lane dispatched to `backend="grok-cli"` completes a real slice: pulls its plan from MCP (no pasted context), edits within `owned_paths`, passes `lane_exec.py`'s post-turn scope gate, and records `test_result` + a slice report back to MCP.
3. Debug-log assertion: **0** `AssistantItem model_id=grok-build` across the turn.
4. The worker's MCP writes are attributed to `grok-composer-2.5-fast`, not the orchestrator identity.
5. Structured `BackendResult` is populated even when grok narrates around the JSON.

## Appendix — reference facts from the spike

- Backend registry: `.workbay/remote/packages/mcp-workbay-orchestrator/src/workbay_orchestrator_mcp/orchestration/backend_registry.py`
- Adapter protocol: `…/orchestration/backend_adapter.py`; reference impl: `…/orchestration/adapters/codex_cli.py`
- grok: `grok 0.2.81`; MCP registration (consumer, user scope):
  ```
  grok mcp add --scope user workbay-handoff-mcp uv -- run --no-sync \
    --project <root>/.workbay/remote/packages/mcp-workbay-handoff \
    mcp-workbay-handoff --workspace-root <root> serve-stdio
  # …and workbay-orchestrator-mcp analogously
  grok mcp doctor   # -> handoff 25 tools, orchestrator 16 tools, handshake OK
  ```
- Model identities: `grok-composer-2.5-fast` (Composer 2.5, Cursor's model, 200k ctx) vs `grok-build` (xAI, 512k ctx, **banned by consumer**).
- Scope/provenance: the orchestrator's `lane_exec.py` post-turn diff gate covers scope + provenance regardless of host, so headless grok needs **no** host guard-hooks.
