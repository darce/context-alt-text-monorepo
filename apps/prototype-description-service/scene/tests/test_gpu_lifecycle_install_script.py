"""F1: gpu-lifecycle-install.sh must own /run/acx as container uid 10001.

The api container writes describe-load.json as uid 10001 gid 999, so a
root:10001 directory is not writable and GPU start/reap timers stall.
"""

from __future__ import annotations

from pathlib import Path

_INSTALLER_REL = Path("scripts/deploy/gpu-lifecycle-install.sh")
_CLOUD_INIT_REL = Path("infra/oci/cloud-init.yaml")


def _repo_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        marker = candidate / _INSTALLER_REL
        if marker.is_file():
            return candidate
    raise FileNotFoundError(
        "could not locate repo root containing "
        f"{_INSTALLER_REL} (walked up from {start})"
    )


def _non_comment_command_lines(text: str) -> list[str]:
    commands: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        commands.append(stripped)
    return commands


_ROOT = _repo_root()
SCRIPT = _ROOT / _INSTALLER_REL
CLOUD_INIT = _ROOT / _CLOUD_INIT_REL


def test_gpu_lifecycle_install_owns_run_acx_as_container_uid() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    commands = _non_comment_command_lines(text)

    assert any("chown 10001:10001 /run/acx" in line for line in commands), (
        "non-comment installer command must include 'chown 10001:10001 /run/acx'"
    )
    assert any("chmod 0775 /run/acx" in line for line in commands), (
        "non-comment installer command must include 'chmod 0775 /run/acx'"
    )
    assert any("d /run/acx 0775 10001 10001 -" in line for line in commands), (
        "non-comment tmpfiles.d line must be 'd /run/acx 0775 10001 10001 -'"
    )
    assert any("echo" in line and "0775 10001:10001" in line for line in commands), (
        "dry-run echo must contain '0775 10001:10001'"
    )
    root_owned = [line for line in commands if "root:10001" in line]
    assert root_owned == [], (
        "non-comment installer lines must not contain 'root:10001'; "
        f"found {root_owned!r}"
    )


def test_cloud_init_owns_run_acx_as_container_uid() -> None:
    """HARM-F2: cloud-init must match installer ownership of /run/acx."""
    text = CLOUD_INIT.read_text(encoding="utf-8")
    commands = _non_comment_command_lines(text)

    assert any("d /run/acx 0775 10001 10001 -" in line for line in commands), (
        "cloud-init must contain tmpfiles.d line 'd /run/acx 0775 10001 10001 -'"
    )
    assert any("chown 10001:10001 /run/acx" in line for line in commands), (
        "cloud-init must include 'chown 10001:10001 /run/acx'"
    )
    assert any("chmod 0775 /run/acx" in line for line in commands), (
        "cloud-init must include 'chmod 0775 /run/acx'"
    )
