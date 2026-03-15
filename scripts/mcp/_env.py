from __future__ import annotations

import os
from pathlib import Path


def pythonpath_env(orchestrator_root: Path) -> dict[str, str]:
    """Return an env dict with PYTHONPATH pointing at the repo-local MCP package."""
    env = os.environ.copy()
    mcp_src = str(orchestrator_root / "packages" / "agent-handoff-mcp" / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{mcp_src}:{existing}" if existing else mcp_src
    return env
