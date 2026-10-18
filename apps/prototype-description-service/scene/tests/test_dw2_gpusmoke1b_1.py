"""Regression checks for DEFWAVE-2 GPU smoke findings."""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "scripts/deploy/gpu-lifecycle-install.sh").is_file():
            return candidate
    raise FileNotFoundError("could not locate repository root")


_ROOT = _repo_root()


def test_gpu_installer_checks_running_api_container_gid() -> None:
    installer = (_ROOT / "scripts/deploy/gpu-lifecycle-install.sh").read_text(
        encoding="utf-8"
    )
    remote_payload = installer.replace(r'\"', '"').replace(r"\$", "$")

    assert "docker ps --filter 'label=com.docker.compose.service=api'" in remote_payload
    assert "while IFS= read -r api_container_id; do" in remote_payload
    assert 'docker exec "$api_container_id" id -g' in remote_payload
    assert "if [ \"$api_container_gid\" != '${ACX_API_GID}' ]; then" in remote_payload
    assert "api container gid" in remote_payload.lower()
