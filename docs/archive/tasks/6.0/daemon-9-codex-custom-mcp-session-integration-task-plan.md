# Daemon 9: Codex Custom MCP Session Integration

## Problem Statement

The repository now contains a portable `agent-handoff-mcp` server and daemon-oriented MCP tools, but this Codex harness still does not see that MCP as a first-class tool inside the current session. Instead, the project MCP is only reachable indirectly through local Python imports, CLI calls, or stdio tests. That means orchestration code can be validated, but the live Codex agent cannot directly call `agent-handoff-mcp` tools the way it can call built-in harness tools.

The missing layer is not only code inside the repo. We also need a repeatable deployment and connection path for Codex custom MCP so a future Codex session can attach to the project's authoritative `agent-handoff-mcp` server as a real MCP connector. This task should make that connection path concrete, documented, and automatable enough that a new Codex session can use `agent-handoff-mcp` as a first-class tool rather than a local library workaround.

## Workflow Principles

- **Treat custom MCP as an external integration boundary.** Repo code can prepare, validate, and document the MCP endpoint, but attaching it to a Codex session is ultimately a host-app configuration step.
- **Server-owned state stays server-owned.** The attached MCP must point at an authoritative checkout host that owns `.task-state`, `CURRENT_TASK.md`, exports, logs, and worktrees.
- **No fake "live hot-plug" promise.** This task must not imply that the current already-running Codex thread can dynamically gain new first-class tools without reconnecting or starting a new session.
- **Prefer one supported transport.** Reuse `agent-handoff-mcp serve-http` as the custom-MCP endpoint for Codex. Do not create a second server implementation.
- **Make setup reproducible.** A human should not need tribal knowledge to start the MCP server, verify it, and point Codex at it.
- **Keep secrets and local paths out of committed defaults.** Checked-in docs and scripts may use placeholders or env vars, but must not assume one developer's machine-specific secrets.

## Terminology

- **Custom MCP**: A user-configured MCP server connection added to Codex/ChatGPT settings so the host app exposes that server's tools to a session.
- **First-class tool**: An MCP tool that appears to the Codex session through the host app's MCP connection layer, rather than being accessed indirectly through shell commands or direct Python imports.
- **Authoritative checkout host**: The machine or container running `agent-handoff-mcp serve-http` against the real repo checkout and file-backed orchestration state.
- **Session attachment**: The host-app act of connecting a Codex session to a configured custom MCP server. This is distinct from implementing the MCP server itself.

## Relationship to Daemon 8

Daemon 8 (portable orchestration backend) established the backend registry, orchestration MCP tools, and `serve-http` transport surface. D8 Phases 4 (Remote HTTP MCP Deployment) and 5 (Documentation and Playbook) originally scoped the remote deployment model and doc updates, but those items have been **deferred to daemon-9** in the D8 consolidated checklist. D9 is now the canonical owner of:

- Remote `serve-http` deployment model and CLI UX (D8 Phase 4 items)
- Authoritative-checkout documentation, `BOOTSTRAP.md` cold-start updates (D8 Phase 4/5 items)
- Remote endpoint security posture (D8 Phase 4 item)
- Readiness/verification contract for remote custom-MCP (D8 Phase 4 item)
- Remote MCP smoke test (D8 Phase 6 deferred item)
- Remote custom-MCP success criterion (D8 success criteria deferred item)

D9 should not duplicate D8 Phase 1-3 work (backend registry, orchestrator lifecycle tools, `run_structured_turn`). Those are complete.

## Current State Analysis

- `agent-handoff-mcp` already exposes both `serve-stdio` and `serve-http` through [cli.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py).
- The MCP now exposes orchestration-facing tools such as `orchestrator_start`, `orchestrator_status`, `orchestrator_stop`, `orchestrator_pause`, `orchestrator_resume`, and `run_structured_turn` through [api.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py).
- The repo already has a local VS Code MCP config in [.vscode/mcp.json](/Users/daniel/Development/context-alt-text-monorepo/.vscode/mcp.json), but that is not a Codex custom-MCP attachment path.
- The current Codex harness session does not have `agent-handoff-mcp` attached as a live MCP tool. The only reliable ways to use it inside the thread today are indirect: local imports, CLI, or tests.
- The `serve-http` subparser currently has no `--host` or `--port` arguments and no help text. FastMCP's `run(transport="streamable-http")` uses framework defaults, which are undocumented and unconfigurable from the CLI. This must be addressed before remote attachment is practical.
- The repo does not yet provide a complete "deploy, verify, and attach" playbook for Codex custom MCP.
- The gap is partly operational: Codex custom MCP must point at a reachable server URL and likely requires opening a new session after configuration so the new tools appear in the harness.

## Constraints and Non-Goals

- **Out of scope**: making the current already-running Codex thread magically gain a new first-class MCP connector mid-session if the host product does not support hot attachment.
- **Out of scope**: redesigning `agent-handoff-mcp` into a stateless multi-tenant cloud service.
- **Out of scope**: moving `.task-state`, `CURRENT_TASK.md`, or worktree ownership off the authoritative host.
- **Out of scope**: HTTP authentication or API-key middleware. The default security posture for D9 is localhost-only binding. If remote network access is needed, operators should use SSH tunneling or a reverse proxy with auth. A first-class auth layer may be added in a future task.
- **In scope**: everything needed so a fresh Codex session can attach the project MCP as a custom connector with minimal manual work.

## Proposed Solution

### Phase 1: Codex Custom-MCP Attachment Playbook

Create a dedicated operator guide for attaching `agent-handoff-mcp` to Codex as a custom MCP:

- prerequisites for the authoritative checkout host
- exact `serve-http` startup command
- expected runtime args (`workspace_root`, `state_dir`, `current_task_path`, `exports_dir`)
- how to verify the server is reachable before adding it in Codex
- how to attach it in Codex custom MCP settings
- how to confirm a new Codex session sees the MCP tools
- explicit note that an already-running session may need to be restarted or recreated

This guide should live in the repo and be linked from the daemon/orchestration docs.

### Phase 2: Repo-Local Startup Wrapper and CLI UX

Add `--host` and `--port` arguments to the `serve-http` subparser in `cli.py` so operators can control the bind address and port from the command line. The defaults should be `127.0.0.1` (localhost-only) and a documented port (e.g., `8741`).

Add a small checked-in launcher for the authoritative host so developers do not need to reconstruct the HTTP command by hand. This can be a Make target, shell script, or small Python wrapper, but it should:

- resolve the repo root cleanly
- require or infer the standard runtime paths
- pass `--host` and `--port` through to the CLI (defaulting to localhost)
- launch `agent_handoff_mcp_launcher.py ... serve-http`
- fail with a clear error if required directories are missing

The wrapper should be aimed at reliability and clarity rather than being a general deployment framework.

### Phase 3: Verification Surface

Add a lightweight verification flow for the custom-MCP endpoint:

- local smoke command for starting the server
- HTTP/server readiness check (e.g., FastMCP client ping or HTTP GET against the streamable-http endpoint)
- tool-list verification confirming the minimum expected tool set: `get_handoff_state`, `set_handoff_state`, `record_decision`, `update_next_actions`, `record_review_finding`, `orchestrator_start`, `orchestrator_status`, `run_structured_turn`
- explicit success criteria for "Codex custom MCP is attachable": the server starts, the readiness probe succeeds, and the tool list includes all minimum tools regardless of whether the handoff DB is empty or populated

This phase should prove the MCP server is healthy before a user tries to connect Codex to it.

### Phase 4: Codex-Facing Documentation Integration

Update the agentic docs so the custom-MCP path is discoverable from the existing orchestration and bridge docs:

- how `agent-handoff-mcp` fits with daemon-8 portability
- why `serve-http` is the correct transport for Codex custom MCP
- what "first-class tool in Codex" does and does not mean
- the fact that session attachment is a host-app step outside the repo

## Implementation Shape

### Remote MCP Launch Pattern

```bash
python3 packages/agent-handoff-mcp/src/agent_handoff_mcp_launcher.py \
  --workspace-root /srv/context-alt-text-monorepo \
  --state-dir /srv/context-alt-text-monorepo/.task-state \
  --current-task-path /srv/context-alt-text-monorepo/CURRENT_TASK.md \
  --exports-dir /srv/context-alt-text-monorepo/.task-state/exports \
  serve-http
```

### Recommended Success Check

1. Start the server on the authoritative checkout host.
2. Verify the server exposes the expected MCP tool list.
3. Add the server as a Codex custom MCP connector.
4. Open a new Codex session.
5. Confirm that session sees `get_handoff_state`, `orchestrator_status`, `run_structured_turn`, and related tools as first-class MCP tools.

## Files to Change

| File                                                                        | Target                        | Change                                                                                                                                                                         |
| --------------------------------------------------------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `docs/tasks/6.0/daemon-9-codex-custom-mcp-session-integration-task-plan.md` | new                           | Track the full task plan, scope, constraints, and checklist for Codex custom-MCP attachment.                                                                                   |
| `docs/agentic/playbooks/worktree-codex-playbook.md`                         | custom MCP section            | Add a concrete "attach `agent-handoff-mcp` to Codex" flow and clarify that a fresh session may be required.                                                                    |
| `docs/agentic/instructions.md`                                              | operator guidance             | Link to the custom-MCP setup path so it is discoverable from the main agentic docs.                                                                                            |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`                   | `serve-http` subparser        | Add `--host` and `--port` arguments to the `serve-http` subparser. Add help text describing the authoritative-checkout requirement. Pass host/port through to `FastMCP.run()`. |
| `docs/agentic/BOOTSTRAP.md`                                                 | serve-http cold-start section | Add `serve-http` startup, host/port configuration, and readiness verification instructions alongside the existing `serve-stdio` content.                                       |
| `mk/handoff.mk` or `scripts/mcp/`                                           | new startup wrapper           | Add a repo-supported command for launching `serve-http` with the standard runtime arguments.                                                                                   |
| `packages/agent-handoff-mcp/tests/`                                         | verification coverage         | Add or extend tests for the HTTP/CLI readiness path including `--host`/`--port` argument parsing and remote MCP smoke test.                                                    |

## Related Files

| File                                                                                                                                                                            | Note                                                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| [api.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py)                                                           | Exposes the MCP tools Codex should eventually see as first-class tools.                  |
| [cli.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py)                                                           | Owns `serve-http`, which should remain the custom-MCP transport surface.                 |
| [config.py](/Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp/src/agent_handoff_mcp/config.py)                                                     | Defines the authoritative runtime paths the remote MCP server binds to.                  |
| [daemon-8-portable-orchestration-backend-task-plan.md](/Users/daniel/Development/context-alt-text-monorepo/docs/tasks/6.0/daemon-8-portable-orchestration-backend-task-plan.md) | Established the backend registry and orchestration MCP tool surface this task builds on. |
| [.vscode/mcp.json](/Users/daniel/Development/context-alt-text-monorepo/.vscode/mcp.json)                                                                                        | Useful comparison point, but not the Codex custom-MCP attachment mechanism.              |

## Risks

- **Host-product mismatch**: Codex custom MCP may have product-level limits or UI behavior not controlled by this repo.
- **Session lifecycle confusion**: users may expect an existing live thread to gain tools immediately after connector setup.
- **Local-path leakage**: setup examples may accidentally assume one workstation's absolute paths unless carefully parameterized.
- **Authority drift**: if users point Codex at a non-authoritative checkout, MCP actions may appear healthy while mutating the wrong state.
- **Unauthenticated HTTP endpoint**: `serve-http` has no auth layer. If bound to a non-localhost interface, anyone with network access can call handoff tools. The default localhost-only binding and documented SSH tunneling posture mitigate this for D9; a proper auth layer is deferred.

## Success Criteria

- The repo documents one supported path for attaching `agent-handoff-mcp` to Codex as a custom MCP.
- A developer can launch the remote MCP server from the repo with one supported command or wrapper.
- A developer can verify the MCP endpoint before attempting Codex attachment.
- A new Codex session can attach to that MCP and see the expected handoff/orchestration tools as first-class tools.
- The docs clearly state any required reconnect/new-session behavior instead of implying unsupported live hot-plugging.

## Consolidated Checklist

- [x] Add `--host` and `--port` arguments to the `serve-http` subparser in `cli.py` (default: `127.0.0.1`, documented port).
- [x] Add Codex custom-MCP setup documentation to the repo.
- [x] Add a supported authoritative-host launcher for `agent-handoff-mcp serve-http`.
- [x] Add or extend verification coverage for the startup and readiness path, including minimum tool set assertion.
- [x] Update `BOOTSTRAP.md` with `serve-http` cold-start instructions.
- [x] Update the worktree/Codex docs to link the custom-MCP flow.
- [x] Document the difference between "MCP server implemented" and "MCP attached to a live Codex session."
- [x] Document the security posture: localhost-only default, SSH tunneling for remote, auth deferred.
- [ ] Validate the documented flow end to end with a fresh Codex session.
