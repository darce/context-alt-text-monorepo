"""F1: gpu-lifecycle-install.sh must own /run/acx as container uid 10001.

The api container writes describe-load.json as uid 10001 gid 999, so a
root:10001 directory is not writable and GPU start/reap timers stall.
"""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts/deploy/gpu-lifecycle-install.sh"


def test_gpu_lifecycle_install_owns_run_acx_as_container_uid() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "chown 10001:10001 /run/acx" in text
    assert "root:10001" not in text
    assert "d /run/acx 0775 10001 10001 -" in text
