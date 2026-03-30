from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from fastmcp.client import Client, StreamableHttpTransport


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_http_server_lists_handoff_tools(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()
    port = _free_port()

    proc = subprocess.Popen(
        [
            sys.executable,
            str(launcher),
            "--workspace-root",
            str(repo_root),
            "serve-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(repo_root),
    )

    url = f"http://127.0.0.1:{port}/mcp"

    try:
        # Wait for the server to be ready (up to 10 seconds)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                httpx.get(f"http://127.0.0.1:{port}/", timeout=0.5)
                # Any response means the server is listening
                break
            except (httpx.ConnectError, httpx.ReadError):
                time.sleep(0.2)
        else:
            proc.kill()
            raise TimeoutError(f"HTTP server did not start within 10s. stderr: {proc.stderr.read()!r}")

        async def _run() -> list[str]:
            transport = StreamableHttpTransport(url=url)
            async with Client(transport) as client:
                tools = await client.list_tools()
                return sorted(tool.name for tool in tools)

        tool_names = asyncio.run(_run())
        assert "get_handoff_state" in tool_names
        assert "record_review_finding" in tool_names
        assert "handoff_close_check" in tool_names
        # orchestrator tools moved to agent-orchestrator-mcp server
        assert "orchestrator_start" not in tool_names
        assert "load_session" in tool_names
    finally:
        proc.terminate()
        proc.wait(timeout=5)
