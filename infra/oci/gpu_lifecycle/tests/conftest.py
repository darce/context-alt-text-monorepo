"""Make the repo root importable when pytest is launched from the description service."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_root = str(_REPO_ROOT)
if _root not in sys.path:
    sys.path.insert(0, _root)
