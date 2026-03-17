# Daemon 7: Codex App-Server Subagent Bridge

## Problem Statement

The `codex-subagent` backend seam now exists in the orchestration layer, but it is not usable because no runtime provides the required `codex_subagent_bridge` module. Worker daemons that select `BACKEND=codex-subagent` fail on the first execution attempt before any lane work can begin. The orchestrator daemon also accepts `--backend` for future orchestrator-invoked review/execution flows, but the orchestrator loop currently coordinates only via MCP and Make, so the missing bridge is not an immediate blocker on that side.

We need to implement Option A: a host-provided bridge that speaks `codex app-server` over stdio, preserves the current prompt-in/schema-out contract, and keeps the orchestration package portable enough to support other agent runtimes later.

## Workflow Principles

- **Bridge, not platform rewrite.** This task provisions a Codex-specific adapter behind the existing `run_subagent()` seam. It must not pull agent-runtime details up into MCP, manifests, task-plan routing, or worktree orchestration.
- **Prompt in, structured JSON out.** The stable contract remains `prompt + output schema + cwd (+ env hints) -> validated object`. Whether the runtime is `codex exec`, `codex app-server`, or a future non-Codex adapter is an implementation detail below that seam.
- **Optional packaging with loud failure.** The bridge is an optional module or package that can be injected into the daemon runtime. Missing bridge, protocol failure, or invalid structured output must fail explicitly rather than silently falling back to another backend.
- **No direct MCP access from the bridge.** The bridge may launch subagents, stream events, and return structured output, but it must not write handoff state, dispatch messages, reviews, or task status directly.
- **Agent-agnostic trajectory.** File layout, naming, and docs should make it easy to add sibling adapters later (for example Claude or Kimi hosts) without renaming the orchestration concepts around Codex-specific terms.

## Terminology

- **Execution seam**: The narrow interface already used by [`lane_exec.py`](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/lane_exec.py) and [`review_runner.py`](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/review_runner.py) to invoke an agent runtime.
- **Bridge module**: A Python module named `codex_subagent_bridge` exposing `run_subagent(prompt, schema, cwd, env=None)`.
- **Host runtime**: The environment that can actually talk to Codex app-server, whether embedded in the desktop app or forwarded through another local transport.
- **App-server lifecycle**: The initialize -> thread/start -> turn/start -> stream -> turn/completed flow used to obtain structured results from Codex app-server.
- **Adapter package**: A small optional Python package that implements one bridge without becoming a dependency of the orchestration core.

## Current State Analysis

- [`scripts/mcp/lane_exec.py`](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/lane_exec.py) and [`scripts/mcp/review_runner.py`](/Users/daniel/Development/context-alt-text-monorepo/scripts/mcp/review_runner.py) already import `codex_subagent_bridge` and call `run_subagent(...)`, but no in-repo implementation exists.
- The execution seam is already narrow and workable: prompt rendering, schema generation, result validation, MCP recording, and worktree routing stay outside the bridge.
- The current bridge contract already carries the right inputs for portability:
  - `prompt`: fully rendered task/review prompt
  - `schema`: JSON schema object
  - `cwd`: target worktree
  - `env`: optional runtime hints mirroring the CLI path
- `codex app-server` is available locally and supports stdio transport, but it is marked experimental. That argues for an isolated adapter package and explicit protocol tests instead of deeper coupling to daemon code.
- The missing pieces are operational rather than architectural:
  - no package/module to satisfy the import
  - no stdio session manager for the app-server protocol
  - no event-to-result extraction path for structured output
  - no docs telling operators how to provision the bridge into the daemon runtime

## Proposed Solution

Create a small optional package that exports `codex_subagent_bridge.run_subagent()` and implements Option A by spawning `codex app-server --listen stdio://`, driving the app-server lifecycle over stdin/stdout, and returning the final structured payload as a Python dict.

The bridge should live outside the orchestration core so that `agent-handoff-mcp` and the daemon scripts remain agent-agnostic. The orchestration layer continues to depend only on the existing bridge contract. The new package owns:

- app-server process startup and teardown
- JSON-RPC/session message handling
- thread/turn lifecycle management
- structured output extraction and protocol error handling
- optional translation of `env` hints into app-server configuration or execution context

This task does not add a plugin registry or a generalized adapter framework. It only makes the current Codex bridge real while keeping the file layout and docs friendly to future sibling adapters.

## Patterns to Follow

### Thin Adapter Boundary

```python
def run_subagent(prompt: str, schema: dict, cwd: str, env: dict | None = None) -> dict | str:
    client = AppServerClient(cwd=cwd, env=env)
    try:
        client.start()
        client.initialize()
        thread_id = client.start_thread()
        return client.run_structured_turn(
            thread_id=thread_id,
            prompt=prompt,
            output_schema=schema,
        )
    finally:
        client.close()
```

### Single-Turn Structured Execution

```python
def run_structured_turn(self, *, thread_id: str, prompt: str, output_schema: dict) -> dict:
    turn_id = self.turn_start(
        thread_id=thread_id,
        prompt=prompt,
        output_schema=output_schema,
    )
    for event in self.stream_until_completed(turn_id):
        if event.type == "turn.completed":
            return extract_structured_output(event)
    raise RuntimeError("app-server stream ended before turn.completed")
```

### Backward-Compatible Provisioning

```python
try:
    import codex_subagent_bridge
except ImportError as exc:
    raise RuntimeError(
        "codex-subagent backend is unavailable in this runtime. "
        "Install or inject the optional codex_subagent_bridge package."
    ) from exc
```

## Functions to Change

| File | Target | Change |
| --- | --- | --- |
| `packages/codex-subagent-bridge/pyproject.toml` | new package metadata | Create an optional installable package for the bridge so the orchestration core does not gain a hard dependency on app-server transport code. Use `py-modules = ["codex_subagent_bridge"]` since the bridge is a single flat module under `src/`, not a package directory. |
| `packages/codex-subagent-bridge/src/codex_subagent_bridge.py` | `run_subagent` | Implement the public bridge contract currently expected by `lane_exec.py` and `review_runner.py`. |
| `packages/codex-subagent-bridge/src/codex_subagent_bridge.py` | `AppServerClient` | Add a small stdio client that launches `codex app-server`, sends initialize/thread/start/turn/start messages, streams events, and extracts structured output. |
| `packages/codex-subagent-bridge/src/codex_subagent_bridge.py` | protocol helpers | Add request id management, JSON line parsing, timeout/error handling, and process cleanup helpers. |
| `packages/codex-subagent-bridge/tests/test_bridge.py` | new tests | Add unit coverage for startup, lifecycle sequencing, structured output extraction, invalid payload errors, and process cleanup. |
| `packages/codex-subagent-bridge/tests/test_bridge_contract.py` | integration-style contract tests | Verify the bridge returns objects compatible with the existing `lane_exec.py` and `review_runner.py` expectations using mocked app-server streams. |
| `docs/agentic/worktree-codex-playbook.md` | backend provisioning section | Document how to install or inject the optional bridge package and what runtime guarantees the bridge provides. |
| `docs/tasks/6.0/daemon-6-autonomous-orchestrator-task-plan.md` | Phase 5 bridge notes | Update the bridge wording to point at this task as the concrete implementation plan for the app-server-backed adapter. |

## Related Files

| File | Note |
| --- | --- |
| `scripts/mcp/lane_exec.py` | Already contains the `codex-subagent` backend seam and lane-result validation. |
| `scripts/mcp/review_runner.py` | Already contains the review-side bridge seam and output validation. |
| `packages/agent-handoff-mcp/tests/test_lane_exec.py` | Existing subagent-backend tests should remain green once the real bridge package is provisioned. |
| `packages/agent-handoff-mcp/tests/test_review_runner.py` | Existing review backend tests define the contract the bridge must satisfy. |
| `docs/tasks/6.0/daemon-6-autonomous-orchestrator-task-plan.md` | Defines why the backend seam exists and why worktree orchestration stays unchanged. |
| `docs/tasks/6.0/phase-5-retention-export-and-audit-controls-task-plan.md` | One concrete beneficiary once `BACKEND=codex-subagent` becomes operational. |

---

# Consolidated Checklist

## Completed

- [x] The execution seam for `codex-subagent` already exists in `lane_exec.py` and `review_runner.py`.
- [x] Worker daemon and Make surfaces thread `BACKEND=codex-subagent` through worker entrypoints, and the orchestrator CLI also accepts `--backend` for future orchestrator-invoked review/execution flows.
- [x] Result validation remains outside the bridge and already guards the lane/review contracts.

## Phase 0: Scaffolding

- [ ] Create `packages/codex-subagent-bridge/` as an optional installable package with `src/` layout.
- [ ] Add public `run_subagent(prompt, schema, cwd, env=None)` signature and docstring.
- [ ] Add internal client/protocol helper stubs with `NotImplementedError("TODO: ...")`.
- [ ] Run `codex app-server generate-json-schema` and vendor a snapshot of the protocol schema as a test fixture and reference document.
- [ ] Add bridge test files with scaffolded mocked app-server fixtures.
- [ ] Verify the package imports cleanly in editable mode.

## Phase 1: App-Server Session Management

- [ ] Launch `codex app-server --listen stdio://` in the requested `cwd`.
- [ ] Verify that the `cwd` placement ensures the spawned app-server discovers the worktree's agent instruction file (currently `CLAUDE.md`, a symlink to `docs/agentic/instructions.md`). This repo has no `AGENTS.md`; instruction routing relies on `CLAUDE.md` and `GEMINI.md` symlinks at the repo root.
- [ ] Implement request/response correlation and event streaming over stdio.
- [ ] Send the `initialize` handshake and validate server readiness before starting work.
- [ ] Ensure process shutdown is deterministic on success, protocol failure, timeout, and caller interruption.

## Phase 2: Structured Turn Execution

- [ ] Implement `thread/start` followed by `turn/start` using the caller-provided prompt and output schema.
- [ ] Stream events until the turn reaches its terminal completed state.
- [ ] Extract the structured output payload from the terminal turn result and normalize it to a Python `dict`.
- [ ] Raise clear runtime errors for protocol failures, incomplete turns, invalid JSON payloads, or missing structured content.

## Phase 3: Runtime Hints And Portability

- [ ] Decide and document which `env` hints are forwarded to app-server configuration versus ignored as CLI-only details.
- [ ] Decide whether `env` hints can forward a reasoning level (`low`/`medium`/`high`) to the app-server session, and if so, how the bridge maps that to the protocol.
- [ ] MCP server config (tool endpoints, credentials) is NOT forwarded through the bridge. Any required context must be baked into the rendered prompt or handled by the parent daemon process. This follows from the Workflow Principles rule that the bridge must have no direct MCP access. If read-only tool access is ever desired, scope that as a separate follow-up that explicitly revisits the ownership principle.
- [ ] Keep the bridge API Codex-specific but package layout adapter-friendly so sibling non-Codex bridges can be added later.
- [ ] Document supported provisioning paths: editable install, wheel install, or host injection via `PYTHONPATH`/`sys.modules`.
- [ ] Document that the worktree's agent instruction file (`CLAUDE.md` / `GEMINI.md`, symlinked to `docs/agentic/instructions.md`) is the instruction surface for spawned agents. This repo does not use `AGENTS.md`.
- [ ] Document that build and test commands must be discoverable by the spawned agent, either through the instruction file or explicitly included in the rendered prompt.
- [ ] Keep orchestration-layer imports unchanged so the core package remains unaware of adapter packaging details.

## Phase 4: Tests

- [ ] Add unit tests for process startup, handshake sequencing, request id routing, and teardown.
- [ ] Add contract tests for lane execution payloads compatible with `lane_exec.py`.
- [ ] Add contract tests for review payloads compatible with `review_runner.py`.
- [ ] Add failure-path tests for timeouts, malformed event streams, missing `turn.completed`, and invalid structured output.
- [ ] Add a concurrency-safety test or note: document whether `run_subagent` is safe for parallel calls (multiple concurrent app-server processes) or requires external serialization by the caller.
- [ ] Verify existing daemon/backend regression tests still pass when the bridge package is present.

## Stretch Goals

- [ ] Add an opt-in long-lived host connection mode if repeated one-turn calls show startup cost is materially high.
- [ ] ~~Generate or vendor a minimal protocol schema snapshot~~ (promoted to Phase 0).
- [ ] Add a second adapter package example or interface note showing how a non-Codex bridge would fit the same seam.

## Success Criteria

- [ ] Installing or injecting `codex_subagent_bridge` makes `BACKEND=codex-subagent` usable without changing daemon orchestration code.
- [ ] A worker lane execution can complete through app-server and return a valid lane-result JSON object.
- [ ] A review execution can complete through app-server and return a valid review-result JSON object.
- [ ] The bridge fails loudly and diagnostically when app-server is unavailable or returns invalid structured output.
- [ ] The orchestration package remains agent-agnostic above the existing execution seam.
