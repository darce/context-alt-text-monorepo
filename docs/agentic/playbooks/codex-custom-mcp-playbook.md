# Codex Custom MCP Playbook

Attach `agent-handoff-mcp` to a Codex session as a custom MCP so handoff and orchestration tools appear as first-class tools.

## Prerequisites

- A machine with the authoritative repo checkout (the "authoritative checkout host")
- Python 3.11+ with `fastmcp` and dependencies installed
- The `packages/agent-handoff-mcp/` package source available (either installed or on `PYTHONPATH`)
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
python3 packages/agent-handoff-mcp/src/agent_handoff_mcp_launcher.py \
  --workspace-root "$(pwd)" \
  serve-http --host 127.0.0.1 --port 8741
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

Expected minimum tool list:

- `get_handoff_state`
- `set_handoff_state`
- `record_decision`
- `update_next_actions`
- `record_review_finding`
- `handoff_close_check`
- `orchestrator_start`
- `orchestrator_status`
- `run_structured_turn`

## 3. Attach in Codex

For same-machine development, prefer the checked-in project-scoped Codex config in
[`../../../.codex/config.toml`](../../../.codex/config.toml).
It registers the stdio adapter as `altcontext-mcp` and pins the launcher to the
repo-local workspace state while exposing both the handoff MCP package and the
Codex subagent bridge on `PYTHONPATH`.

For the Codex / ChatGPT custom MCP settings UI over HTTP:

- **Name**: `altcontext-mcp`
- **Server URL**: `http://<host>:8741/mcp`
- **Transport**: Streamable HTTP

If the host is `localhost`, use `http://127.0.0.1:8741/mcp`. If the host is remote, use the SSH tunnel or reverse proxy address.

## 4. Start a new Codex session

Custom MCP tools are loaded at session start. An already-running session will **not** gain new tools mid-conversation. Start a new session after adding the custom MCP connector.

## 5. Confirm tools are visible

In the new Codex session, the MCP tools should appear as first-class tools. Verify by asking the session to call `orchestrator_status()` or `get_handoff_state()`.

## Security

The default bind address is `127.0.0.1` (localhost only). This means only processes on the same machine can reach the server. There is no authentication layer.

For remote access:

- **Recommended**: Use an SSH tunnel to forward the port from a remote machine: `ssh -L 8741:127.0.0.1:8741 user@host`
- **Alternative**: Use a reverse proxy with authentication in front of the MCP endpoint
- **Not recommended**: Binding to `0.0.0.0` without auth exposes handoff tools to the network

A first-class auth layer may be added in a future task.

## Difference: MCP server vs MCP attached

"MCP server implemented" means `agent-handoff-mcp serve-http` runs and exposes tools over HTTP. "MCP attached to Codex" means the Codex host product has been configured to connect to that server. This playbook covers both steps, but the attachment step is a host-app configuration action outside the repo.

## Related

- [BOOTSTRAP.md](../BOOTSTRAP.md) -- MCP server setup and testing commands
- [worktree-codex-playbook.md](worktree-codex-playbook.md) -- worktree lane orchestration
- [instructions.md](../instructions.md) -- cold-start development instructions
