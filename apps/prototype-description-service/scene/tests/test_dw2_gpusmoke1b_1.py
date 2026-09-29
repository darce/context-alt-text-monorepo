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


def test_gpu_burst_plan_uses_installer_gpu_state_path() -> None:
    plan = (_ROOT / "docs/tasks/vlm/GPUSMOKE-1-burst-e2e-proof-task-plan.md").read_text(
        encoding="utf-8"
    )

    assert "/run/acx/gpu-state.json" in plan
    assert "/run/acx-write/<environment>/gpu-state.json" not in plan


def test_gpu_timer_checks_query_the_system_manager() -> None:
    plan = (_ROOT / "docs/tasks/vlm/GPUSMOKE-1-burst-e2e-proof-task-plan.md").read_text(
        encoding="utf-8"
    )
    activation = (_ROOT / "docs/tasks/vlm/VLM-3-7c-activation-evidence.md").read_text(
        encoding="utf-8"
    )

    assert "systemctl list-timers" in plan
    assert "systemctl list-timers" in activation
    assert "systemctl --user/list-timers" not in plan
    assert "systemctl --user list-timers" not in activation


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
