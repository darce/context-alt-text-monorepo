# Codex Custom MCP Setup

> **Classification: host-specific adapter (Codex)**
> This document describes how to attach `workbay-handoff-mcp` to a Codex session. It is a platform setup guide, not a canonical portable playbook.

Attach `workbay-handoff-mcp` to a Codex session as a custom MCP so handoff and orchestration tools appear as first-class tools.

## Prerequisites

- A machine with the authoritative repo checkout (the "authoritative checkout host")
- Python 3.11+ with `fastmcp` and dependencies installed
- The installed `workbay-handoff-mcp` CLI available on the authoritative checkout host
- Network reachability between the Codex session and the host (localhost, SSH tunnel, or VPN)

## 1. Start the MCP server

From the repo root on the authoritative checkout host:

```bash
make mcp-serve-http
```

This binds to `127.0.0.1:8741` by default. Override with:

```bash
make mcp-serve-http HOST=0.0.0.0 PORT=9000
```

Or call the launcher directly:

```bash
mcp-workbay-handoff --workspace-root "$(pwd)" serve-http --host 127.0.0.1 --port 8741
```

The server binds to localhost only by default. See **Security** below if you need remote access.

## 2. Verify the server is reachable

From the machine that will run Codex, confirm the endpoint responds:

```bash
curl -s http://127.0.0.1:8741/ | head -c 200
```

Any response (even a 405) means the server is listening.

For a full tool-list check:

```bash
python3 -c "
import asyncio
from fastmcp.client import Client, StreamableHttpTransport
async def check():
    async with Client(StreamableHttpTransport(url='http://127.0.0.1:8741/mcp')) as c:
        tools = await c.list_tools()
        for t in sorted(tools, key=lambda t: t.name):
            print(t.name)
asyncio.run(check())
"
```

Expected minimum tool list (handoff server only):

- `get_handoff_state`
- `set_handoff_state`
- `record_decision`
- `update_next_actions`
- `record_review_finding`
- `handoff_close_check`

Orchestration tools (`orchestrator_start`, `orchestrator_status`, `run_structured_turn`,
`dispatch_lane_work`, `worker_start`, `worker_stop`, `switch_task`, etc.) are served by
`workbay-orchestrator-mcp`, not by `workbay-handoff-mcp`. Attach `workbay-orchestrator-mcp`
separately when orchestration control is needed.

## 3. Attach in Codex

For same-machine development, prefer the checked-in project-scoped Codex config in
[`../../../.codex/config.toml`](../../../.codex/config.toml).
It registers the stdio adapter as `mcp-workbay-handoff` and pins the launcher to the
repo-local workspace state while exposing both the handoff MCP package and the
Codex subagent bridge on `PYTHONPATH`.

For the Codex / ChatGPT custom MCP settings UI over HTTP:

- **Name**: `mcp-workbay-handoff`
- **Server URL**: `http://<host>:8741/mcp`
- **Transport**: Streamable HTTP

If the host is `localhost`, use `http://127.0.0.1:8741/mcp`. If the host is remote, use the SSH tunnel or reverse proxy address.

## 4. Start a new Codex session

Custom MCP tools are loaded at session start. An already-running session will **not** gain new tools mid-conversation. Start a new session after adding the custom MCP connector.

## 5. Confirm tools are visible

In the new Codex session, the MCP tools should appear as first-class tools. Verify by asking the session to call `get_handoff_state()`. If orchestration tools are also needed, confirm `workbay-orchestrator-mcp` is attached separately and call `orchestrator_status()` from that server.

## Security

The default bind address is `127.0.0.1` (localhost only). This means only processes on the same machine can reach the server. There is no authentication layer.

For remote access:

- **Recommended**: Use an SSH tunnel to forward the port from a remote machine: `ssh -L 8741:127.0.0.1:8741 user@host`
- **Alternative**: Use a reverse proxy with authentication in front of the MCP endpoint
- **Not recommended**: Binding to `0.0.0.0` without auth exposes handoff tools to the network

A first-class auth layer may be added in a future task.

## Difference: MCP server vs MCP attached

"MCP server implemented" means `mcp-workbay-handoff serve-http` runs and exposes tools over HTTP. "MCP attached to Codex" means the Codex host product has been configured to connect to that server. This playbook covers both steps, but the attachment step is a host-app configuration action outside the repo.

## Related

- [BOOTSTRAP.md](../../BOOTSTRAP.md) -- MCP server setup and testing commands
- [worktree-codex-playbook.md](worktree-codex-playbook.md) -- worktree lane orchestration
- [instructions.md](../../instructions.md) -- cold-start development instructions
