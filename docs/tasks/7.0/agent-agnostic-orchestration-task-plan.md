# Agent-Agnostic Orchestration Refactor

> **Scope:** Tooling/infrastructure; successor to `mcp-orchestration-reliability`. Not tracked in a product roadmap or epic.
> **Status:** complete -- all phases (0-5) implemented; checklist fully checked.

## Problem Statement

The MCP daemon orchestration layer is tightly coupled to OpenAI Codex primitives. Backend selection, model configuration, effort tuning, process lifecycle, and binary discovery are all wired to Codex-specific assumptions. This prevents the orchestrating agent from being anything other than Codex, blocks model selection at dispatch time, and creates maintenance burden from duplicated Codex-specific code across multiple modules. The goal is an agent-agnostic orchestration surface where MCP owns "what work to do and when" while pluggable backend adapters own "how to execute it," enabling Claude, Codex, local models, or future agents to serve as workers.

## Evidence

Coupling-point audit across the orchestration codebase. Items are numbered AAO-001 through AAO-007.

### AAO-001: Backend registry is a flat dict with no execution contract

**Location:** `scripts/mcp/backend_registry.py` -- `BACKENDS` dict, `resolve_bridge()`, `get_backend_spec()`

**Problem:** The registry maps backend names to `BackendSpec(kind, module, capabilities)` but `kind` is just a string (`"cli"` or `"bridge"`) with no formal execution interface. `lane_exec.py` branches on `kind` with `if/elif` blocks. Adding a new backend (e.g., Claude Code CLI, a local model server) requires editing `lane_exec.py`, `review_runner.py`, and `worker_daemon.py` in addition to the registry.

**Impact:** Every new agent runtime requires cross-cutting changes instead of a single adapter module.

### AAO-002: Codex binary discovery leaks into generic execution path

**Location:** `scripts/mcp/lane_exec.py` -- `find_codex()` (line 47), hardcoded search paths (lines 41-42); duplicated in `mk/lane-worker.mk` (lines 52-56)

**Problem:** `find_codex()` contains hardcoded macOS paths (`/Applications/Codex.app/Contents/Resources/codex`, `~/.local/bin/codex`) and is called unconditionally in `run_lane_exec()` even for non-Codex backends. The same paths are duplicated in `mk/lane-worker.mk`'s `lane-run` target. This function is Codex-specific infrastructure that belongs inside a codex-cli adapter, not in the shared execution module.

**Impact:** Non-Codex backends fail or warn about missing Codex binaries. Platform-specific paths prevent Linux and CI execution.

### AAO-003: Reasoning effort heuristic is hardcoded in worker daemon

**Location:** `scripts/mcp/worker_daemon.py` -- `_resolve_reasoning_effort()` (lines 508-563)

**Problem:** This function auto-tunes `CODEX_REASONING_EFFORT` based on lane name patterns and cycle number (e.g., "frontend" lanes get lower effort on early cycles). The heuristic is Codex-specific (the `reasoning_effort` parameter is a Codex API concept), embeds domain knowledge about lane names that belongs in manifests, and cannot be overridden by an orchestrating agent that wants to make its own cost/quality tradeoffs.

**Impact:** Model selection and cost controls are baked into the worker daemon instead of being decidable by the orchestrating agent at dispatch time.

### AAO-004: Environment variable stamping assumes Codex runtime

**Location:** `scripts/mcp/_env.py` -- `apply_codex_runtime_hints()` (lines 89-102)

**Problem:** This function unconditionally stamps `CODEX_REASONING_EFFORT` and `CODEX_SUBAGENT_BRIDGE_SESSION_MODE` into the process environment. These are Codex-specific env vars that have no meaning for Claude, local models, or other runtimes.

**Impact:** Non-Codex backends inherit meaningless environment variables. The function name itself indicates the coupling.

### AAO-005: Review runner duplicates backend dispatch logic

**Location:** `scripts/mcp/review_runner.py` -- `_codex_exec()`, `_find_codex_path()`

**Problem:** The review runner has its own copy of Codex binary discovery (`_find_codex_path()`) and its own `_codex_exec()` function that duplicates the CLI-vs-bridge branching from `lane_exec.py`. Both modules independently import from `backend_registry` and implement the same dispatch pattern.

**Impact:** Bug fixes to execution dispatch must be applied in two places. Adding a new backend requires changes in both modules.

### AAO-006: Owner-agent defaults to "codex" in orchestrator guidance

**Location:** `scripts/mcp/orchestrator_guidance.py` -- line 379

**Problem:** `owner_agent=... or "codex"` hardcodes the fallback agent identity. If a Claude or local-model worker produces guidance, the attribution is wrong.

**Impact:** Minor; cosmetic attribution error. But symptomatic of the Codex-first assumption throughout the codebase.

### AAO-007: No dispatch-time model/effort selection via MCP

**Location:** MCP tool surface (`packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`)

**Problem:** `worker_start` and `orchestrator_start` accept `backend` and `reasoning_effort` as static config. There is no MCP tool that lets an orchestrating agent say "dispatch this lane with Claude Opus at high effort" or "use Codex with medium effort for this review." Model selection is a boot-time decision, not a per-dispatch decision.

**Impact:** An orchestrating agent cannot dynamically choose the best worker runtime per lane based on lane complexity, cost budget, or model availability.

### AAO-008: Codex CLI `--model` flag is never used; all lanes run the default (most expensive) model

**Location:** `scripts/mcp/lane_exec.py` -- `run_lane_exec()` CLI command construction

**Problem:** `codex exec` supports `--model gpt-5.4-mini` (and other models) as a first-class per-invocation flag, but `run_lane_exec()` never passes `--model`. Every lane execution pays for the default `gpt-5.4` (or whatever `~/.codex/config.toml` sets) regardless of lane complexity. The `CODEX_ARGS` passthrough exists in `make lane-run` but is not wired through the daemon path. Meanwhile, OpenAI explicitly recommends `gpt-5.4-mini` "for subagents" which is exactly the lane-worker use case.

**Available Codex models (March 2026):**

| Model                 | Use case                                                   | Relative speed |
| --------------------- | ---------------------------------------------------------- | -------------- |
| `gpt-5.4`             | Flagship frontier; complex reasoning + coding              | Moderate       |
| `gpt-5.4-mini`        | Fast, efficient; recommended for subagents                 | Very fast      |
| `gpt-5.3-codex`       | Industry-leading coding; powers gpt-5.4                    | Moderate       |
| `gpt-5.3-codex-spark` | Near-instant real-time coding (Pro only, research preview) | Fastest        |

**Impact:** Every worker turn burns full-model tokens regardless of task complexity. Docs-only lanes, early-cycle exploratory runs, and bounded review passes could use `gpt-5.4-mini` at a fraction of the cost. The CLI also supports `--oss` for local Ollama models and `--profile` for preset config bundles; neither is exposed.

## Architecture Principle

**MCP orchestration owns "what/when." Backend adapters own "how."**

The boundary is a `BackendAdapter` Protocol. Everything above the adapter (lane selection, merge ordering, stall detection, review routing, MCP state persistence, prompt generation, result validation) stays in MCP orchestration. Everything below the adapter (binary discovery, process lifecycle, API authentication, env var stamping, model-specific parameters) moves into per-backend adapter modules.

```
Orchestrating Agent (Claude / Codex / local model / human)
    |
    v  MCP tools: dispatch_lane_work, worker_start, orchestrator_start ...
    |
MCP Orchestration Layer (what/when)
    - lane manifests, plan cursors, merge order
    - stall/escalation tracking
    - review-route-fix cycle
    - prompt generation (lane_prompt.py)
    - result validation (lane_result.py)
    |
    v  BackendAdapter.execute(prompt, schema, cwd, model, effort) -> result_path
    |
Backend Adapters (how)
    - codex-cli: find_codex(), subprocess, CLI flags
    - codex-subagent: AppServerClient, JSON-RPC stdio
    - claude-code: claude CLI, --output-format json
    - local-model: ollama/vllm HTTP, structured output
```

## Features to Keep in MCP Orchestration

These features have no equivalent in any agent runtime API and must remain in the orchestration layer:

1. **Git worktree isolation** -- lane-per-worktree with `scripts/worktree-lane`
2. **MCP handoff state** -- decisions, actions, findings, test results, blockers across sessions
3. **Merge-order intake** -- dependency-aware cherry-pick with `lane-intake`
4. **Lane manifest and routing** -- `config/lane-orchestration/*.json` with owned paths and test commands
5. **Plan-cursor dispatch** -- `get_plan_cursor` / `upsert_plan_cursor` for multi-phase task state
6. **Review-route-fix cycle** -- orchestrator reviews, records findings, dispatches to owning lane
7. **Stall and escalation tracking** -- guidance stalls, attention stalls, bounded retry
8. **Cross-session continuity** -- `CURRENT_TASK.md` generation, `lane-inbox`/`handoff-inbox` polling
9. **Prompt generation** -- `lane_prompt.py` reads MCP state to build worker prompts
10. **Structured result contract** -- 5-field JSON schema in `lane_result.py` (agent-agnostic today)

## Features to Collapse into Backend Adapters

These features duplicate or conflict with agent runtime capabilities and should move into per-backend adapters:

1. **Binary discovery** -- `find_codex()` and `_find_codex_path()` move into codex-cli adapter
2. **Process lifecycle** -- `subprocess.run` for CLI, `AppServerClient` for bridge; each adapter owns its own
3. **Environment stamping** -- `apply_codex_runtime_hints()` moves into codex adapters
4. **Effort heuristic** -- `_resolve_reasoning_effort()` replaced by orchestrating-agent decision at dispatch time
5. **Review dispatch duplication** -- `review_runner.py` uses `BackendAdapter.execute()` instead of its own dispatch
6. **Agent identity default** -- `owner_agent` derived from backend name, not hardcoded "codex"

## Proposed Solution

### Phase 0: Codex CLI setup and immediate `--model` plumbing

**Objective:** Establish the Codex CLI as a properly installed, version-pinned dependency and immediately unlock per-dispatch model selection via `--model` before the full adapter refactor.

**Setup steps:**

1. **Install Codex CLI globally:** `npm i -g @openai/codex@latest`
2. **Authenticate:** `codex login` (ChatGPT OAuth) or `printenv OPENAI_API_KEY | codex login --with-api-key` (API key)
3. **Verify:** `codex login status` (exit 0 = authenticated)
4. **Pin default config** in `~/.codex/config.toml`:

   ```toml
   model = "gpt-5.4"

   [profile.mini]
   model = "gpt-5.4-mini"

   [profile.full]
   model = "gpt-5.4"
   ```

5. **Verify model access:** `codex exec -m gpt-5.4-mini "echo hello"` should complete without error

**Functions to change:**

- `scripts/mcp/lane_exec.py` -- `run_lane_exec()`: thread `model` parameter through to `--model` flag on the `codex exec` subprocess command. Also thread `--profile` when a profile name is provided.
- `scripts/mcp/worker_daemon.py` -- `worker_loop()`: accept `model` parameter (from CLI arg or MCP dispatch state) and pass it through to `run_lane_exec()`
- `scripts/mcp/review_runner.py` -- `_codex_exec()`: accept and pass `--model` when provided

**Wrapper/API surfaces that must also thread `model` (or remain on `CODEX_ARGS` until this is done):**

- `mk/lane-worker.mk` -- `lane-run` target (line 46): add `$(if $(MODEL),--model "$(MODEL)",)` to the `lane_exec.py` invocation; `worker-daemon` target: add `$(if $(MODEL),--model "$(MODEL)",)` to the `worker_daemon.py` invocation
- `mk/handoff.mk` -- `orchestrator-daemon` target (line 120): add `$(if $(MODEL),--model "$(MODEL)",)` to the `orchestrator_daemon.py` invocation
- `scripts/mcp/orchestrator_daemon.py` -- CLI argparse and `orchestrator_loop()`: accept `--model` and thread it through to `_ensure_lane_workers()` / per-lane dispatch
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` -- `orchestrator_start()` (line 284): add `model` parameter; `worker_start()` (line 519): add `model` parameter; `worker_start_all()` (line 629): add `model` parameter

Until all wrapper surfaces above are wired, users can still pass `CODEX_ARGS='--model gpt-5.4-mini'` through the existing passthrough; Phase 0 replaces that with first-class `MODEL=` only for the surfaces it actually touches.

**Model selection heuristic (replaces `_resolve_reasoning_effort()` in Phase 2):**

| Lane type                            | Suggested model              | Rationale                            |
| ------------------------------------ | ---------------------------- | ------------------------------------ |
| Docs-only or early-cycle exploratory | `gpt-5.4-mini`               | Bounded scope, low risk              |
| Review pass (structured output)      | `gpt-5.4-mini`               | Schema-constrained, reads-only       |
| Backend domain / complex logic       | `gpt-5.4` or `gpt-5.3-codex` | Needs strong reasoning               |
| Fix-prompt after failed review       | `gpt-5.4`                    | Needs to reason about prior failures |

The orchestrating agent makes this decision at dispatch time (Phase 3); Phase 0 only wires the plumbing so `--model` reaches `codex exec`.

**CLI advantages over app-server bridge for model selection:**

| Concern          | `codex exec` (CLI)                               | `codex app-server` (bridge)                                         |
| ---------------- | ------------------------------------------------ | ------------------------------------------------------------------- |
| Model selection  | `--model gpt-5.4-mini` per invocation            | `CODEX_MODEL` env var at thread creation; cannot change per-turn    |
| Local/OSS models | `--oss` flag (Ollama) built in                   | Not supported                                                       |
| Config profiles  | `--profile mini` loads preset from `config.toml` | No equivalent                                                       |
| Session resume   | `codex exec resume --last "fix the issue"`       | Must manage thread lifecycle manually                               |
| Process overhead | One subprocess per dispatch                      | App-server lifecycle (initialize, thread/start, turn/start, stream) |

**Verification:**

- `codex exec -m gpt-5.4-mini` completes a trivial prompt on the dev machine
- `run_lane_exec(model="gpt-5.4-mini")` produces a CLI invocation containing `--model gpt-5.4-mini`
- Existing tests pass (model parameter is optional; `None` means no `--model` flag, preserving current default behavior)

### Phase 1: BackendAdapter Protocol and registry refactor

**Objective:** Define the formal execution contract and refactor the registry to use it.

**Functions to create:**

- `scripts/mcp/backend_adapter.py` -- `BackendAdapter` Protocol class, `BackendResult` dataclass
- `scripts/mcp/adapters/codex_cli.py` -- Codex CLI adapter implementing `BackendAdapter`
- `scripts/mcp/adapters/codex_subagent.py` -- Codex subagent bridge adapter implementing `BackendAdapter`

**Functions to change:**

- `scripts/mcp/backend_registry.py` -- `BACKENDS` dict entries reference adapter classes; `resolve_backend()` returns a `BackendAdapter` instance instead of a `BackendSpec`
- `scripts/mcp/lane_exec.py` -- `run_lane_exec()` calls `adapter.execute()` instead of branching on `kind`; `find_codex()` removed (moved to codex-cli adapter)

**BackendAdapter Protocol:**

```python
from typing import Protocol

class BackendResult:
    result_path: Path
    exit_code: int
    runtime_seconds: float

class BackendAdapter(Protocol):
    name: str
    def execute(
        self,
        prompt: str,
        output_schema: str,
        cwd: Path,
        *,
        model: str | None = None,
        effort: str | None = None,
        timeout_seconds: int = 0,
    ) -> BackendResult: ...

    def available(self) -> bool: ...
```

**Verification:**

- Existing tests in `test_lane_exec.py` pass with refactored dispatch
- Existing tests in `test_backend_registry.py` pass with new registry shape
- New unit tests for each adapter's `execute()` and `available()` methods
- `run_lane_exec()` no longer contains `if kind == "cli"` / `elif kind == "bridge"` branches

### Phase 2: Extract Codex-specific code into adapters

**Objective:** Move all Codex-specific logic out of shared modules into adapter modules.

**Functions to change:**

- `scripts/mcp/lane_exec.py` -- remove `find_codex()`, `_run_subagent()`; these become internal to their respective adapters
- `scripts/mcp/review_runner.py` -- remove `_find_codex_path()`, `_codex_exec()`; use `BackendAdapter.execute()` via registry
- `scripts/mcp/_env.py` -- remove `apply_codex_runtime_hints()`; each adapter applies its own env setup in `execute()`
- `scripts/mcp/worker_daemon.py` -- remove `_resolve_reasoning_effort()` heuristic; accept `effort` as a pass-through parameter from orchestrator dispatch
- `scripts/mcp/orchestrator_guidance.py` -- replace `"codex"` default with backend-derived agent identity

**Verification:**

- `grep -rn "find_codex\|_find_codex_path\|codex_runtime_hints\|_resolve_reasoning_effort" scripts/mcp/` returns zero hits outside `scripts/mcp/adapters/`
- Review runner tests pass using adapter dispatch
- Worker daemon tests pass without reasoning-effort heuristic
- All 368+ existing daemon/orchestration tests pass

### Phase 3: Per-dispatch model and effort selection via MCP

**Objective:** Let an orchestrating agent choose the backend, model, and effort per dispatch rather than at boot time.

**Functions to create:**

- `packages/agent-handoff-mcp` -- new MCP tool `dispatch_lane_work(lane_id, backend, model, effort)` that records dispatch parameters in MCP state and starts the worker with those parameters
- `packages/agent-handoff-mcp` -- new MCP tool `list_available_backends()` that queries the adapter registry and returns available backends with their capabilities

**Functions to change:**

- `scripts/mcp/worker_daemon.py` -- `worker_loop()` reads dispatch parameters from MCP state (lane record or dispatch message) instead of CLI args
- `scripts/mcp/orchestrator_daemon.py` -- `_ensure_lane_workers()` uses per-lane dispatch parameters when available; falls back to global defaults

**Verification:**

- MCP tool `dispatch_lane_work` successfully starts a worker with specified backend/model/effort
- MCP tool `list_available_backends` returns correct adapter inventory
- Dispatching the same lane with different parameters on consecutive cycles uses the updated parameters
- Orchestrator single-cycle test with mixed backends (one lane codex-cli, one lane codex-subagent) completes without error

### Phase 4: New backend adapters and manifest-to-config generation

**Objective:** Add non-Codex backends and support auto-generating agent config from lane manifests.

**Functions to create:**

- `scripts/mcp/adapters/claude_code.py` -- Claude Code CLI adapter (`claude --output-format json`)
- `scripts/mcp/adapters/local_model.py` -- local model adapter (HTTP to ollama/vllm with structured output)
- Manifest-to-agent-config utility that generates Codex custom agent TOML or Claude agent config from `config/lane-orchestration/*.json`

**Functions to change:**

- `scripts/mcp/backend_registry.py` -- register new adapters via `register_backend()`
- Lane manifests in `config/lane-orchestration/` -- add optional `preferred_backend` and `preferred_model` fields

**Verification:**

- `register_backend("claude-code", ClaudeCodeAdapter)` succeeds; `list_available_backends` includes it
- `register_backend("local-model", LocalModelAdapter)` succeeds
- `available()` returns `False` when the binary/server is not found (no crash)
- Manifest-to-config generates valid TOML for a sample lane manifest
- End-to-end: a lane dispatched with `backend="claude-code"` completes and produces a valid 5-field result payload

### Phase 5: Documentation updates (instructions.md and worktree-codex-playbook.md)

**Objective:** Update the agent instruction surface and playbook to reflect model selection, new backends, and the `BackendAdapter` boundary.

**Changes to `docs/agentic/instructions.md`:**

1. **Tool Selection Discipline table (Codex agents section):** Update the description from "OpenAI Codex harness, `codex exec`, `codex-subagent-bridge`" to include model selection context. Add note that `codex exec -m <model>` is the preferred per-dispatch model control.

2. **Multi-Agent Worktree Orchestration section:**
   - Update `make worker-daemon` bullet to document `MODEL=gpt-5.4-mini` as an available parameter alongside `BACKEND=`.
   - Update `make orchestrator-daemon` bullet likewise.
   - Update `make lane-run` bullet to document `MODEL=` parameter (replacing raw `CODEX_ARGS='--model ...'` passthrough).
   - Add guidance: "For cost-sensitive lanes (docs-only, review passes, early-cycle exploration), prefer `MODEL=gpt-5.4-mini`. For complex domain/logic lanes, use the default or `MODEL=gpt-5.4`."
   - Update MCP orchestration commands list to include `model` parameter on `worker_start()`, `worker_start_all()`, and `dispatch_lane_work()`.

3. **Backend Python lanes note:** Replace "prefer `PYENV_VERSION=description-service <command>`" note with a model-aware variant that also mentions passing `MODEL=` for non-interactive verification.

4. **Execution backends section (if referenced inline):** Update to reference `BackendAdapter` Protocol as the canonical dispatch boundary instead of raw `backend_registry.py` `BACKENDS` dict.

**Changes to `docs/agentic/worktree-codex-playbook.md`:**

1. **Quick Reference -- Orchestrator one-liners:** Add `MODEL=` parameter to `make orchestrator-daemon` and `make lane-run`:

   ```bash
   make orchestrator-daemon [TASK=<task>] [BACKEND=codex-cli|codex-subagent] [MODEL=gpt-5.4-mini]
   make lane-run TASK=<task> LANE=<lane> [MODEL=gpt-5.4-mini]
   ```

2. **Quick Reference -- Worker one-liners:** Add `MODEL=` parameter to `make worker-daemon`:

   ```bash
   make worker-daemon TASK=<task> LANE=<lane> [BACKEND=codex-cli|codex-subagent] [MODEL=gpt-5.4-mini]
   ```

3. **Execution backends section:** Expand to cover model selection:
   - Add a "Model selection" sub-section documenting `MODEL=` parameter, available models, and the `--profile` config.toml approach.
   - Update the backend description to note that `codex-cli` supports per-invocation `--model` while `codex-subagent` uses `CODEX_MODEL` env var at thread creation.
   - Add model selection guidance table (same as Phase 0 heuristic above).
   - Document `~/.codex/config.toml` profiles for preset model bundles.

4. **MCP orchestration commands section:** Add `model` parameter to `worker_start()`, `worker_start_all()`, `orchestrator_start()`, and the new `dispatch_lane_work()` tool signature.

5. **Recipe: Run a continuous worker daemon:** Add `MODEL=` example:

   ```bash
   make worker-daemon TASK=<task-ref> LANE=<lane> MODEL=gpt-5.4-mini
   ```

6. **Recipe: Automated worker run (Codex CLI):** Replace `CODEX_ARGS='--model o3'` example with the new `MODEL=gpt-5.4-mini` parameter. Add model selection guidance note.

7. **Recipe: In-app orchestration via MCP:** Update `worker_start()` call examples to include `model="gpt-5.4-mini"` parameter.

8. **New Recipe: Codex CLI setup:** Add a recipe for first-time CLI setup:
   - Install: `npm i -g @openai/codex@latest`
   - Authenticate: `codex login`
   - Verify: `codex login status`
   - Configure profiles: edit `~/.codex/config.toml`
   - Verify model access: `codex exec -m gpt-5.4-mini "echo hello"`

**Verification:**

- All `make` command examples in both docs include the `MODEL=` parameter where applicable
- No stale `CODEX_ARGS='--model ...'` passthrough patterns remain (replaced by `MODEL=`)
- Backend description accurately reflects `BackendAdapter` Protocol (not raw `BACKENDS` dict)
- Codex CLI setup recipe is copy-paste-runnable
- Model selection guidance table appears in the playbook's execution backends section

## Patterns to Follow

### BackendAdapter registration

```python
# scripts/mcp/adapters/codex_cli.py
from backend_adapter import BackendAdapter, BackendResult

class CodexCliAdapter:
    name = "codex-cli"

    def execute(self, prompt, output_schema, cwd, *, model=None, effort=None, timeout_seconds=0):
        codex_bin = self._find_binary()
        cmd = [codex_bin, "exec", "--prompt", prompt, "--output-schema", output_schema]
        if model:
            cmd.extend(["--model", model])
        if effort:
            cmd.extend(["--reasoning-effort", effort])
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout_seconds or None)
        return BackendResult(result_path=..., exit_code=result.returncode, runtime_seconds=...)

    def available(self):
        return self._find_binary() is not None

    def _find_binary(self):
        # Codex-specific discovery; moved from lane_exec.find_codex()
        ...
```

### Dispatch-time model selection via MCP

```python
# Orchestrating agent calls MCP tool:
dispatch_lane_work(
    lane_id="backend-http",
    backend="claude-code",
    model="claude-sonnet-4-20250514",
    effort="high",
)

# Worker daemon reads from lane dispatch state:
def worker_loop(lane_id, ...):
    dispatch = get_lane_dispatch(lane_id)
    backend = dispatch.get("backend") or default_backend
    model = dispatch.get("model")
    effort = dispatch.get("effort")
    adapter = resolve_backend(backend)
    result = adapter.execute(prompt, schema, cwd, model=model, effort=effort)
```

### Unified review dispatch

```python
# review_runner.py -- after refactor
def run_review(lane_id, backend, ...):
    adapter = resolve_backend(backend)
    result = adapter.execute(
        prompt=review_prompt,
        output_schema=REVIEW_OUTPUT_SCHEMA,
        cwd=worktree_path,
        model=model,
        effort=effort,
    )
    return parse_review_result(result.result_path)
```

## Dependencies

- **Depends on:** `mcp-orchestration-reliability` (ORD fixes) should be complete first; the reliability fixes establish the stable execution paths that this refactor restructures.
- **No product-code changes:** This task modifies only tooling under `scripts/mcp/`, `packages/agent-handoff-mcp/`, `packages/codex-subagent-bridge/`, `mk/` (Make include files), `config/lane-orchestration/` (lane manifest schema), and `docs/agentic/`. No changes to `apps/prototype-description-service/` or `apps/prototype-wp-alt-context/`.
- **Phase 0 is standalone:** The `--model` plumbing and CLI setup can be done immediately, independent of the full adapter refactor. This is the quickest path to token cost savings.
- **Codex CLI install:** Requires `npm i -g @openai/codex@latest` and authentication via `codex login`. ChatGPT Plus/Pro/Business/Edu/Enterprise plans include Codex access.
- **Codex Subagents API alignment:** Phase 4 may leverage Codex custom agent TOML definitions (`agents/*.toml`) and `spawn_agents_on_csv` for batch operations. These are additive; the refactor does not depend on them.
- **Session resume potential:** `codex exec resume --last` can retry failed lanes without replaying the full prompt; this is a token-savings path to wire in Phase 1's `CodexCliAdapter` but does not block any phase.

## Verification

**Phase 0:**

- `codex login status` exits 0
- `codex exec -m gpt-5.4-mini` completes a trivial prompt
- `run_lane_exec(model="gpt-5.4-mini")` produces CLI invocation containing `--model gpt-5.4-mini`
- Existing tests pass (model parameter is optional; `None` preserves current default)
- Worker daemon accepts `MODEL=gpt-5.4-mini` CLI parameter and threads it to `run_lane_exec()`
- `make lane-run TASK=... LANE=... MODEL=gpt-5.4-mini` passes `--model` to `lane_exec.py`
- `make worker-daemon TASK=... LANE=... MODEL=gpt-5.4-mini` passes `--model` to `worker_daemon.py`
- MCP `worker_start(model="gpt-5.4-mini")` and `orchestrator_start(model="gpt-5.4-mini")` thread the parameter to the underlying daemon

**Phase 1:**

- `BackendAdapter` Protocol type-checks with `mypy`
- Both Codex adapters pass `available()` on a macOS dev machine with Codex installed
- `run_lane_exec()` dispatches correctly through `adapter.execute()`
- No `if kind ==` branches remain in `lane_exec.py`

**Phase 2:**

- `grep -rn` for Codex-specific functions returns zero hits outside `scripts/mcp/adapters/`
- Review runner uses adapter dispatch; all review tests pass
- Worker daemon accepts `effort` as pass-through; heuristic function is deleted
- All 368+ existing tests pass

**Phase 3:**

- `dispatch_lane_work` MCP tool is callable and records parameters in state
- `list_available_backends` returns correct inventory
- Worker reads dispatch parameters from MCP state
- Mixed-backend single-cycle test completes

**Phase 4:**

- Claude Code adapter passes `available()` on a machine with `claude` CLI
- Local model adapter passes `available()` when server is reachable
- Manifest-to-config generates valid agent config
- End-to-end lane execution with a non-Codex backend produces valid result

**Phase 5:**

- All `make` command examples in docs include `MODEL=` parameter where applicable
- No stale `CODEX_ARGS='--model ...'` patterns remain in docs
- Codex CLI setup recipe is copy-paste-runnable
- Model selection guidance table appears in the playbook

## Checklist

- [x] Phase 0: Install and authenticate Codex CLI (`npm i -g @openai/codex@latest`, `codex login`)
- [x] Phase 0: Configure `~/.codex/config.toml` with `mini` and `full` profiles
- [x] Phase 0: Wire `--model` flag through `lane_exec.py` `run_lane_exec()`
- [x] Phase 0: Wire `--model` flag through `review_runner.py` `_codex_exec()`
- [x] Phase 0: Wire `model` parameter through `worker_daemon.py` `worker_loop()`
- [x] Phase 0: Wire `MODEL=` through `mk/lane-worker.mk` (`lane-run`, `worker-daemon` targets)
- [x] Phase 0: Wire `MODEL=` through `mk/handoff.mk` (`orchestrator-daemon` target)
- [x] Phase 0: Wire `model` parameter through `orchestrator_daemon.py` CLI + `orchestrator_loop()`
- [x] Phase 0: Wire `model` parameter through `api.py` (`orchestrator_start`, `worker_start`, `worker_start_all`)
- [x] Phase 0: Verify `codex exec -m gpt-5.4-mini` completes on dev machine
- [x] Phase 1: Define `BackendAdapter` Protocol and `BackendResult` dataclass
- [x] Phase 1: Implement `CodexCliAdapter` with moved `find_codex()` logic and `--model`/`--profile` support
- [x] Phase 1: Implement `CodexSubagentAdapter` wrapping bridge module
- [x] Phase 1: Refactor `backend_registry.py` to return adapter instances
- [x] Phase 1: Refactor `lane_exec.py` to use `adapter.execute()`
- [x] Phase 2: Remove `find_codex()` and `_run_subagent()` from `lane_exec.py`
- [x] Phase 2: Remove `_find_codex_path()` and `_codex_exec()` from `review_runner.py`
- [x] Phase 2: Remove `apply_codex_runtime_hints()` from `_env.py`
- [x] Phase 2: Remove `_resolve_reasoning_effort()` from `worker_daemon.py`
- [x] Phase 2: Replace `"codex"` default in `orchestrator_guidance.py`
- [x] Phase 3: Add `dispatch_lane_work` MCP tool with `model` parameter
- [x] Phase 3: Add `list_available_backends` MCP tool
- [x] Phase 3: Worker daemon reads dispatch parameters (including `model`) from MCP state
- [x] Phase 4: Implement `ClaudeCodeAdapter`
- [x] Phase 4: Implement `LocalModelAdapter`
- [x] Phase 4: Manifest-to-agent-config generation utility
- [x] Phase 4: Add `preferred_backend` and `preferred_model` to lane manifest schema
- [x] Phase 5: Update `instructions.md` -- model selection in worker/orchestrator daemon commands
- [x] Phase 5: Update `instructions.md` -- MCP orchestration commands with `model` parameter
- [x] Phase 5: Update `worktree-codex-playbook.md` -- Quick Reference with `MODEL=` parameter
- [x] Phase 5: Update `worktree-codex-playbook.md` -- Execution backends section with model guidance table
- [x] Phase 5: Update `worktree-codex-playbook.md` -- Replace `CODEX_ARGS='--model o3'` with `MODEL=`
- [x] Phase 5: Add new "Recipe: Codex CLI setup" to playbook
- [x] Phase 5: Update playbook MCP orchestration commands with `model` parameter
