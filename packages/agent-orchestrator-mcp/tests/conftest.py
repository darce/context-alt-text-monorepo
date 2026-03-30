from __future__ import annotations

import sys
from pathlib import Path

# Add agent-handoff-mcp src to path (dependency)
REPO_ROOT = Path(__file__).resolve().parents[3]
for pkg in ("agent-handoff-mcp", "agent-orchestrator-mcp"):
    src = REPO_ROOT / "packages" / pkg / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
