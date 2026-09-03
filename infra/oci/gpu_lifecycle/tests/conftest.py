"""Make the repo root importable when pytest is launched from the description service."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_root = str(_REPO_ROOT)
if _root not in sys.path:
    sys.path.insert(0, _root)

# The snapshot contract crosses from the repo-root lifecycle package into the
# description-service package.  Put that real project root on sys.path so a
# missing reader import fails collection instead of being silently skipped.
_DESCRIPTION_SERVICE_ROOT = _REPO_ROOT / "apps" / "prototype-description-service"
_description_service_root = str(_DESCRIPTION_SERVICE_ROOT)
if _description_service_root not in sys.path:
    sys.path.insert(0, _description_service_root)


@pytest.fixture(autouse=True)
def _isolate_gpu_state_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep lifecycle cycles from publishing to the host's /run/acx in tests."""
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(tmp_path / "gpu-state.json"))
