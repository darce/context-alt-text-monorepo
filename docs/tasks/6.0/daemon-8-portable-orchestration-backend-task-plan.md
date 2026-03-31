# Daemon 8: Portable Orchestration Backend

## Problem Statement

The orchestration layer currently hard-codes two execution backends (`codex-cli` and `codex-subagent`) with duplicated dispatch logic in `lane_exec.py` and `review_runner.py`. Adding a third backend (for example an in-app Copilot host, a Claude adapter, or a future non-Codex runtime) requires modifying both files, updating parallel `BACKEND_CHOICES` tuples, and duplicating the validation/import pattern. The orchestrator and worker daemons also lack an in-app integration path: an Opus agent in VS Code Copilot cannot directly drive lane execution or daemon lifecycle through MCP tools. This task consolidates the backend dispatch surface, makes it extensible via a registry, and adds the MCP commands needed for in-app orchestration.

## Workflow Principles

- **Registry, not if/elif chains.** Backend dispatch moves from duplicated conditionals in `lane_exec.py` and `review_runner.py` to a single registry that both modules import. Adding a backend means registering a module name and an optional capability set, not editing dispatch code.
- **Same result contract everywhere.** All backends return the same `lane_result` or `review_result` schema. The registry validates shape after dispatch; backends are responsible only for producing it.
- **In-app harnesses are first-class.** An in-app host (VS Code Copilot MCP, Codex desktop, future Claude host) can register as a backend and be selected at runtime without spawning external processes.
- **CLI fallback stays default.** The `codex-cli` backend remains the default. In-app backends are opt-in via `--backend` or MCP command parameters.
- **No bridge writes MCP.** Bridges produce structured output. The parent daemon or MCP command records results. This ownership boundary (from D7) is preserved.
- **Remote MCP runs against an authoritative checkout.** The HTTP MCP server must run on a host that owns the orchestrator repo checkout, `.task-state`, `CURRENT_TASK.md`, exports, logs, and worktrees. Remote clients connect to that host; they do not become the storage authority.
- **No state-service rewrite in this phase.** Daemon 8 may make the MCP surface remotely reachable over HTTP, but it does not replace file-backed orchestration state with a new network-native state layer.
- **Live-session reuse is deferred.** Reusing the caller's already-running Codex session or sandbox is not part of Daemon 8. This phase stays within the existing server-reachable bridge seam and remote MCP control surface.
- **Deduplication over abstraction framework.** Extract exactly the duplicated code (`BACKEND_CHOICES`, `_validate_backend`, bridge import pattern) into a shared module. Do not build a plugin framework, discovery system, or metaclass registry.

## Terminology

- **Backend registry**: A shared Python module (`scripts/mcp/backend_registry.py`) that maps backend name strings to importable bridge module names and optional capability metadata.
- **In-app backend**: A backend whose execution happens within the host application process (e.g., Copilot MCP tool calling `run_subagent` via the bridge, or a future Claude host adapter) rather than shelling out to a subprocess.
- **CLI backend**: A backend that spawns an external process (e.g., `codex exec`, `codex app-server`). Both existing backends are CLI backends.
- **Orchestrator MCP commands**: New MCP tool surface exposed through `agent-handoff-mcp` that allows an in-app host agent to start/stop/poll the orchestrator daemon and invoke structured execution turns.
- **Authoritative checkout host**: The machine or container running the remote HTTP MCP server, which owns the repo checkout and all file-backed orchestration state for a task.
- **Execution turn**: One prompt-in/structured-output cycle through any registered backend. Corresponds to `run_subagent()` for bridge backends or `codex exec` for the CLI path.

## Current State Analysis

- `lane_exec.py` line 38 and `review_runner.py` line 21 both define identical `BACKEND_CHOICES = ("codex-cli", "codex-subagent")` tuples.
- Both files implement identical `_validate_backend()` functions.
- Both files have parallel `if backend_name == "codex-subagent": ... elif backend_name == "codex-cli": ...` dispatch blocks.
- The `_run_subagent()` helper in `lane_exec.py` uses `importlib.import_module("codex_subagent_bridge")` with runtime validation. `review_runner.py` has its own parallel `_subagent_exec()`. Both could call through a unified dispatch function.
- The `subagent-bridge-interface-note.md` contract already defines the host-agnostic bridge signature: `run_subagent(prompt, schema, cwd, env) -> dict | str`. Any new backend that implements this interface plugs in automatically.
- The `.vscode/mcp.json` exposes `agent-handoff-mcp` to Copilot, but no MCP commands exist for orchestrator lifecycle or direct execution turns.
- `agent-handoff-mcp` already exposes both `serve-stdio` and `serve-http`, so the missing piece for custom-MCP portability is deployment topology and remote-operation guidance, not a brand new transport surface.
- The orchestrator daemon runs as a Python subprocess via Make targets. An in-app Copilot agent (Opus) can start it via `run_in_terminal` but has no native MCP control over pause/resume/stop/status.
- The `codex-subagent` bridge (`packages/codex-subagent-bridge/`) is fully implemented and tested (D7 complete). It provides the proven pattern for new bridge packages.
- The current bridge seam is host-reachable rather than live-session-attached: bridges can be injected into the daemon runtime, but no code today attaches to or reuses a caller's already-running Codex session.

## Proposed Solution

### Phase 1: Backend Registry (Deduplicate)

Extract the duplicated backend dispatch surface into `scripts/mcp/backend_registry.py`:

```python
# backend_registry.py

BACKENDS: dict[str, BackendSpec] = {
    "codex-cli": BackendSpec(kind="cli", module=None, description="Shell out to codex exec"),
    "codex-subagent": BackendSpec(kind="bridge", module="codex_subagent_bridge", description="Codex app-server via stdio bridge"),
}

def validate_backend(name: str) -> str: ...
def get_backend_choices() -> tuple[str, ...]: ...
def resolve_bridge(name: str) -> Callable: ...
```

- `lane_exec.py` and `review_runner.py` import from `backend_registry` instead of defining their own tuples and validators.
- The `codex-cli` path remains inline in each module (it has module-specific subprocess logic). Only the bridge dispatch path (`kind="bridge"`) goes through the registry.
- Adding a backend means one `BACKENDS` dict entry and an installable bridge module.
- Reusing a caller's already-running Codex session is explicitly deferred. Daemon 8 only supports backends that are reachable from the server-side daemon process through the existing bridge seam.

### Phase 2: MCP Orchestrator Commands

Add new MCP tools to `agent-handoff-mcp` for in-app orchestration control:

| MCP Tool                                     | Input                                           | Output                                              | Purpose                                         |
| -------------------------------------------- | ----------------------------------------------- | --------------------------------------------------- | ----------------------------------------------- |
| `orchestrator_start`                         | `task_ref, backend, poll_interval, single_pass` | `{ok, pid, lock_path}`                              | Spawn orchestrator daemon in background         |
| `orchestrator_status`                        | (none)                                          | `{running, pid, task_ref, cycle_count, last_event}` | Poll daemon health                              |
| `orchestrator_stop`                          | `{force?}`                                      | `{ok, exit_code}`                                   | Graceful SIGTERM (or SIGKILL if force)          |
| `orchestrator_pause` / `orchestrator_resume` | (none)                                          | `{ok}`                                              | Toggle daemon pause state                       |
| `run_structured_turn`                        | `prompt, schema, cwd, backend, env?`            | `{ok, result}`                                      | Execute one turn through any registered backend |

The `run_structured_turn` command is the key enabler for in-app orchestration: an Opus agent in Copilot can render a prompt, call this MCP tool, and get structured output back without managing subprocess lifecycle.

### Phase 2.5: Remote HTTP MCP Topology

Make the remote-deployment model explicit for custom MCP clients, but keep the
implementation boundary narrow in daemon-8:

- Reuse the existing `serve-http` entrypoint instead of inventing a second MCP server surface.
- Run `serve-http` on a host that owns the authoritative orchestrator checkout.
- Keep `.task-state`, `CURRENT_TASK.md`, exports, logs, and worktrees file-backed on that host.
- Treat the remote MCP server as the control plane for that checkout, not as a stateless proxy to arbitrary client-local repos.
- Defer any redesign that moves orchestration state out of the checkout and into a separate service or database API.
- Defer Codex-specific custom-MCP attachment work to daemon-9, including host/port CLI UX, readiness verification, cold-start setup docs, and the session-attachment playbook.
- Do not split ownership with daemon-9: daemon-8 establishes the server-side orchestration MCP surface, while daemon-9 owns the remote custom-MCP attachment and deployment ergonomics.

### Phase 3: In-App Copilot Backend (optional, stretch)

Register a `copilot-host` backend that delegates execution to the VS Code Copilot `runSubagent` tool or equivalent in-process mechanism. This is stretch because the `runSubagent` API currently spawns a same-model sub-agent (not a sandboxed Codex worker), so the isolation guarantees differ from CLI/bridge backends.

## Patterns to Follow

### Registry Pattern

```python
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class BackendSpec:
    kind: str  # "cli" | "bridge"
    module: str | None  # importable module name for bridge backends
    description: str
    native_hint: bool = False  # True if this backend reuses the hosting harness

BACKENDS: dict[str, BackendSpec] = {}

def register_backend(name: str, spec: BackendSpec) -> None:
    BACKENDS[name] = spec

# detect_runtime() — DEFERRED. Live-session reuse (attaching to a running Codex
# sandbox) is explicitly out of scope for Daemon 8 (see Workflow Principles:
# "Live-session reuse is deferred"). This pseudocode was speculative; the
# implementation does not include it. Moved to daemon-9 scope.

def resolve_bridge(name: str) -> Callable[..., dict]:
    spec = BACKENDS.get(name)
    if spec is None or spec.kind != "bridge":
        raise RuntimeError(f"No bridge module for backend '{name}'")
    bridge = importlib.import_module(spec.module)
    runner = getattr(bridge, "run_subagent", None)
    if runner is None:
        raise RuntimeError(f"Bridge module '{spec.module}' has no run_subagent()")
    return runner
```

### Unified Bridge Dispatch (lane_exec.py after refactor)

```python
from backend_registry import validate_backend, resolve_bridge

# In run_lane_exec():
backend_name = validate_backend(backend)
if backend_name == "codex-cli":
    # ... existing subprocess path (unchanged)
else:
    # All bridge backends go through registry
    runner = resolve_bridge(backend_name)
    payload = _validate_lane_result_payload(
        _call_bridge(runner, prompt_text, schema_text, worktree_path, env, progress_callback)
    )
```

### MCP Daemon Control

```python
# In agent-handoff-mcp server

@mcp_tool("orchestrator_start")
def orchestrator_start(task_ref: str, backend: str = "codex-cli", single_pass: bool = False):
    proc = subprocess.Popen(
        [sys.executable, "scripts/mcp/orchestrator_daemon.py", "run",
         "--orchestrator-root", str(workspace_root),
         "--task-ref", task_ref,
         "--backend", backend,
         *(["--single-pass"] if single_pass else [])],
        cwd=workspace_root,
    )
    return {"ok": True, "pid": proc.pid}
```

### In-App Execution Turn

```python
@mcp_tool("run_structured_turn")
def run_structured_turn(prompt: str, schema: dict, cwd: str, backend: str = "codex-subagent", env: dict | None = None):
    runner = resolve_bridge(backend)
    result = runner(prompt=prompt, schema=schema, cwd=cwd, env=env)
    if isinstance(result, str):
        result = json.loads(result)
    return {"ok": True, "result": result}
```

### Remote HTTP Deployment

```bash
python3 packages/agent-handoff-mcp/src/agent_handoff_mcp_launcher.py \
  --workspace-root /srv/context-alt-text-monorepo \
  --state-dir /srv/context-alt-text-monorepo/.task-state \
  --current-task-path /srv/context-alt-text-monorepo/CURRENT_TASK.md \
  --exports-dir /srv/context-alt-text-monorepo/.task-state/exports \
  serve-http
```

This host owns the authoritative checkout and all file-backed orchestration state. Remote MCP clients connect to it; they do not supply their own local `.task-state` or `CURRENT_TASK.md`.

## Functions to Change

| File                                                           | Target                                                   | Change                                                                                                                                                                                                                    |
| -------------------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/mcp/backend_registry.py`                              | new module                                               | Create shared backend registry with `BackendSpec`, `BACKENDS` dict, `validate_backend()`, `get_backend_choices()`, and `resolve_bridge()`. Register `codex-cli` and `codex-subagent` as built-in entries.                 |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_exec.py`                                     | `BACKEND_CHOICES`, `_validate_backend`, `_run_subagent`  | Replace local `BACKEND_CHOICES` and `_validate_backend()` with imports from `backend_registry`. Replace the `_run_subagent()` dynamic import with `resolve_bridge()` call. Keep `codex-cli` subprocess path module-local. |
| `scripts/mcp/review_runner.py`                                 | `BACKEND_CHOICES`, `_validate_backend`, `_subagent_exec` | Same refactor as `lane_exec.py`: import from `backend_registry`, use `resolve_bridge()` for bridge dispatch. Keep `codex-cli` subprocess path module-local.                                                               |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py`                                 | `--backend` choices                                      | Import `get_backend_choices()` from registry for argparse `choices` instead of hardcoding.                                                                                                                                |
| `scripts/mcp/orchestrator_daemon.py`                           | `--backend` choices                                      | Same: import `get_backend_choices()` from registry.                                                                                                                                                                       |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`      | `serve-http` / runtime args                              | Reuse the existing HTTP server entrypoint as the remote MCP surface for in-app clients. Document and, if needed, harden the required runtime arguments so the remote server clearly binds to one authoritative checkout.  |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`      | tool implementations + registration                      | Add `orchestrator_start`, `orchestrator_status`, `orchestrator_stop`, `orchestrator_pause`, `orchestrator_resume`, `run_structured_turn` as functions in api.py and register them in `build_handoff_mcp()`.               |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` | public API exports                                       | Re-export all six new tool functions and add to `__all__`.                                                                                                                                                                |
| `docs/agentic/contracts/subagent-bridge-interface-note.md`     | backend registry reference                               | Update to reference the registry pattern and show how new adapters register.                                                                                                                                              |
| `docs/agentic/playbooks/worktree-codex-playbook.md`            | backend docs                                             | Update the "Execution backends" section with registry pattern, new MCP commands, and in-app orchestration usage.                                                                                                          |

## Related Files

| File                                                           | Note                                                                                                                                                                         |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_exec.py`                                     | Primary consumer of backend dispatch. Contains `BACKEND_CHOICES` (line 38), `_validate_backend` (line 205), `_run_subagent` (line 308), and the `codex-cli` subprocess path. |
| `scripts/mcp/review_runner.py`                                 | Secondary consumer. Contains duplicate `BACKEND_CHOICES` (line 21), `_validate_backend` (line 329), and `_subagent_exec`.                                                    |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_prompt.py`                                   | Prompt rendering (shared across backends, unchanged).                                                                                                                        |
| `scripts/mcp/lane_result.py`                                   | Result schema and recording (shared across backends, unchanged).                                                                                                             |
| `packages/codex-subagent-bridge/`                              | The proven bridge implementation from D7. Its `run_subagent()` signature is the interface contract.                                                                          |
| `docs/agentic/contracts/subagent-bridge-interface-note.md`     | Documents the bridge interface contract and non-Codex adapter guidance.                                                                                                      |
| `.vscode/mcp.json`                                             | VS Code MCP server config. New orchestrator tools are auto-exposed via the existing `agent-handoff-mcp` server entry.                                                        |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`      | Already exposes `serve-http`; Daemon 8 should treat this as the remote MCP deployment entrypoint rather than adding a parallel transport surface.                            |
| `docs/tasks/6.0/daemon-7-codex-app-server-bridge-task-plan.md` | D7 established the bridge package pattern and interface contract this task builds on.                                                                                        |
| `docs/tasks/6.0/daemon-6-autonomous-orchestrator-task-plan.md` | D6 established the daemon orchestration layer and `--backend` threading this task extends.                                                                                   |

---

> **Implementation note — phase mapping:** During implementation the Proposed Solution phases were split and renumbered. Proposed Solution Phase 2 was split into Checklist Phase 2 (lifecycle commands: start/status/stop/pause/resume) and Checklist Phase 3 (execution turn: `run_structured_turn`). Proposed Solution Phase 2.5 (Remote HTTP MCP Topology) became Checklist Phase 4, and was subsequently completed in daemon-9. Proposed Solution Phase 3 (copilot-host stretch) was deferred entirely and does not appear in the Consolidated Checklist.

# Consolidated Checklist

## Completed

- [x] The `codex-subagent` bridge package is fully implemented and tested (D7).
- [x] The orchestrator and worker daemons thread `--backend` through all execution paths (D6).
- [x] The bridge interface contract is documented in `subagent-bridge-interface-note.md`.
- [x] `.vscode/mcp.json` exposes `agent-handoff-mcp` to VS Code Copilot.

## Phase 1: Backend Registry

- [x] Create `scripts/mcp/backend_registry.py` with `BackendSpec` dataclass, `BACKENDS` dict, `validate_backend()`, `get_backend_choices()`, `resolve_bridge()`.
- [x] Register `codex-cli` (kind `cli`) and `codex-subagent` (kind `bridge`, module `codex_subagent_bridge`) as built-in entries.
- [x] Refactor `lane_exec.py`: replace `BACKEND_CHOICES`, `_validate_backend`, and `_run_subagent` dynamic import with registry imports. Keep `codex-cli` subprocess path inline.
- [x] Refactor `review_runner.py`: same extraction. Replace `_subagent_exec` bridge import with `resolve_bridge()`.
- [x] Update `worker_daemon.py` and `orchestrator_daemon.py` to import `get_backend_choices()` for argparse choices.
- [x] Verify all existing tests pass with no behavior change (281 tests pass across full suite).

## Phase 2: MCP Orchestrator Lifecycle Commands

- [x] Implement `orchestrator_start` MCP tool: spawn daemon subprocess, return PID and lock path.
- [x] Implement `orchestrator_status` MCP tool: read daemon lock file and JSONL log tail, return running state, task ref, cycle count, last event timestamp.
- [x] Implement `orchestrator_stop` MCP tool: send SIGTERM (or SIGKILL with `force=true`), wait for exit, return exit code.
- [x] Implement `orchestrator_pause` and `orchestrator_resume` MCP tools: write pause sentinel file (existing daemon convention).
- [x] Register all six tools in `agent-handoff-mcp` api.py `build_handoff_mcp()` and expose via `__init__.py`.
- [x] Add unit tests for each lifecycle command (mock subprocess, verify signal handling).
- [x] Add CLI subcommands for all six tools in cli.py.

## Phase 3: MCP Execution Turn Command

- [x] Implement `run_structured_turn` MCP tool: accept prompt, schema, cwd, backend, env; call `resolve_bridge(backend)` and return validated result.
- [x] Add guard: if `backend` is `codex-cli`, reject with clear error (CLI backend requires subprocess management not suitable for synchronous MCP call; use `orchestrator_start` or worker daemon instead).
- [x] Add timeout parameter with default matching bridge timeout (120s).
- [x] Add unit tests for the MCP tool (mock bridge call, verify result validation, verify timeout behavior).

## Phase 4: Remote HTTP MCP Deployment

- [x] Deferred to daemon-9, now complete: `serve-http` supports `--host` / `--port` CLI controls (default `127.0.0.1:8741`). See `cli.py` and `mk/handoff.mk` `mcp-serve-http` target.
- [x] Deferred to daemon-9, now complete: authoritative-checkout deployment model documented in `docs/agentic/playbooks/codex-custom-mcp-playbook.md`.
- [x] Deferred to daemon-9, now complete: startup examples and `BOOTSTRAP.md` cold-start section added for `serve-http`.
- [x] Deferred to daemon-9, now complete: security posture documented (localhost-only default, SSH tunneling for remote, auth deferred).
- [x] Deferred to daemon-9, now complete: readiness/verification contract defined with minimum tool set assertion and HTTP smoke test (`test_http.py`).
- [x] Deferred to daemon-9, now complete: non-goal documented in playbook ("Difference: MCP server vs MCP attached" section).

## Phase 5: Documentation and Playbook

- [x] Update `subagent-bridge-interface-note.md` to reference the backend registry and show how to register a new adapter.
- [x] Update `worktree-codex-playbook.md` with: backend registry, MCP orchestrator commands, remote HTTP MCP deployment model status, and an in-app orchestration workflow example.
- [x] Add orchestrator MCP command examples to `BOOTSTRAP.md` or equivalent cold-start reference.
- [x] Update `instructions.md` Multi-Agent Worktree Orchestration section to mention the MCP orchestrator commands as an alternative to Make targets for in-app agents.

## Phase 6: Tests

- [x] Backend registry unit tests: validate registration, resolve, unknown backend errors, and bridge loading behavior (`test_backend_registry.py`).
- [x] Integration tests: `lane_exec.py` and `review_runner.py` call through registry without regression (58 tests pass).
- [x] MCP tool tests: orchestrator lifecycle (start, status, stop, pause, resume) with mocked subprocess (test_orchestrator_tools.py).
- [x] MCP tool tests: `run_structured_turn` with mocked bridge, including timeout and error paths (test_orchestrator_tools.py).
- [x] Stdio smoke test: `test_stdio.py` verifies new tools are exposed via stdio transport.
- [x] Deferred to daemon-9, now complete: remote MCP smoke test in `test_http.py` verifies `serve-http` starts, binds to specified host/port, and exposes the expected tool surface via `StreamableHttpTransport`.
- [x] End-to-end smoke test: `test_e2e_orchestrator_lifecycle_through_mcp_tools` in `test_orchestrator_tools.py` covers start -> status -> pause -> resume -> single-cycle -> stop.

## Stretch Goals

- [~] Explore a separate client-side task for reusing the caller's already-running Codex session. Deferred -- requires attach/reuse API design beyond current scope.
- [x] Register a `copilot-host` backend with `detect_runtime()` probing for VS Code/Copilot host signals. Registered in `backend_registry.py` with `BackendCapabilities(supports_structured_output=False, supports_sandbox=False, supports_sync_turn=True)`. Bridge module `vscode_copilot_bridge` is a placeholder until the host bridge adapter is implemented.
- [x] `orchestrator_single_cycle` MCP tool implemented in `api.py`: spawns `orchestrator_daemon.py run --single-pass`, returns exit code and stderr. Tested in `test_orchestrator_tools.py`.
- [~] `run_review_turn` MCP tool deferred -- can be trivially added as a schema variant of `run_structured_turn` when review convergence workflow requires it.
- [x] Backend capability metadata: `BackendCapabilities` dataclass with `supports_structured_output`, `supports_sandbox`, `supports_sync_turn` fields. All three built-in backends have capabilities declared.

## Success Criteria

- [x] Adding a new bridge backend requires only: (1) a Python module implementing `run_subagent(prompt, schema, cwd, env) -> dict`, (2) one `register_backend()` call in `backend_registry.py`. Verified by `test_register_backend_adds_new_entry` in `test_backend_registry.py`. No changes needed to `lane_exec.py`, `review_runner.py`, daemon argparsers, or Make targets.
- [x] An Opus agent in VS Code Copilot can start, monitor, and stop the orchestrator daemon entirely through MCP tools without using `run_in_terminal`. All lifecycle tools (`orchestrator_start`, `orchestrator_status`, `orchestrator_pause`, `orchestrator_resume`, `orchestrator_single_cycle`, `orchestrator_stop`) are registered and tested. E2E lifecycle test covers the full sequence.
- [x] An Opus agent can execute a single structured turn through any registered bridge backend via the `run_structured_turn` MCP tool.
- [x] Deferred to daemon-9, now complete: a remote custom-MCP client connects to `agent-handoff-mcp serve-http` on an authoritative checkout host. Verified by `test_http.py` smoke test and documented in `codex-custom-mcp-playbook.md`.
- [x] All existing D6/D7 tests continue to pass (186 pre-D8 tests pass; total suite 297). Backend registry refactor introduced no regressions.
- [x] Full agent-handoff-mcp test suite passes (297 tests) including new orchestrator tool, backend capability, and e2e tests.
