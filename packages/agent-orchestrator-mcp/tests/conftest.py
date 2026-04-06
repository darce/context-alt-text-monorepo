from __future__ import annotations

import sys
from pathlib import Path

# Add the local orchestrator package src to path for direct test imports.
REPO_ROOT = Path(__file__).resolve().parents[3]
src = REPO_ROOT / "packages" / "agent-orchestrator-mcp" / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))
