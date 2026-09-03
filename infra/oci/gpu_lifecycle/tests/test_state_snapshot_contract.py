"""Cross-package contract between the lifecycle writer and API reader."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from scene.application import gpu_state
from scene.application.gpu_state import GpuState, read_gpu_state

from infra.oci.gpu_lifecycle.state_snapshot import (
    GpuLifecycleState,
    write_gpu_state_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "gpu-lifecycle-install.sh"
DEPLOYED_COMPOSE = (
    REPO_ROOT / "apps" / "prototype-description-service" / "docker-compose.env.yml"
)


@pytest.mark.parametrize("state", list(GpuLifecycleState))
def test_each_writer_state_round_trips_through_real_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: GpuLifecycleState,
) -> None:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    assert write_gpu_state_snapshot(state, now=1_788_390_000.0) is True

    assert json.loads(path.read_text()) == {
        "state": state.value,
        "written_at": 1_788_390_000.0,
    }
    assert read_gpu_state(now=1_788_390_179.0) is GpuState(state.value)


def test_real_reader_fails_closed_when_snapshot_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(tmp_path / "missing.json"))

    assert read_gpu_state(now=1_788_390_000.0) is GpuState.UNKNOWN


@pytest.mark.parametrize("configured_path", ["", " \t"])
def test_reader_blank_path_env_uses_default(
    monkeypatch: pytest.MonkeyPatch, configured_path: str
) -> None:
    monkeypatch.setenv(gpu_state.GPU_STATE_PATH_ENV, configured_path)

    assert gpu_state.resolve_gpu_state_path() == gpu_state.DEFAULT_GPU_STATE_PATH


def test_lifecycle_unit_users_can_write_provisioned_snapshot_directory() -> None:
    script = INSTALL_SCRIPT.read_text(encoding="utf-8")
    service_bodies = re.findall(
        r"tee /etc/systemd/system/acx-gpu-(?:start|reap)\.service.*?<<UNIT\n(.*?)\nUNIT",
        script,
        flags=re.DOTALL,
    )
    assert len(service_bodies) == 2

    chown_match = re.search(r"sudo chown ([^:\s]+):([^\s]+) /run/acx", script)
    tmpfiles_match = re.search(
        r"^d /run/acx (\d+) ([^\s]+) ([^\s]+) -$", script, flags=re.MULTILINE
    )
    assert chown_match is not None
    assert tmpfiles_match is not None
    directory_owner, directory_group = chown_match.groups()
    mode, boot_owner, boot_group = tmpfiles_match.groups()
    assert (boot_owner, boot_group) == (directory_owner, directory_group)
    assert int(mode[-2]) & 0o2, "the provisioned group must have write permission"

    for body in service_bodies:
        user_match = re.search(r"^User=(\S+)$", body, flags=re.MULTILINE)
        groups_match = re.search(r"^SupplementaryGroups=(.+)$", body, flags=re.MULTILINE)
        assert user_match is not None
        unit_user = user_match.group(1)
        supplementary_groups = groups_match.group(1).split() if groups_match else []
        assert unit_user == directory_owner or directory_group in supplementary_groups


def test_deployed_compose_keeps_load_writable_and_gpu_state_read_only() -> None:
    compose = DEPLOYED_COMPOSE.read_text(encoding="utf-8")
    api_match = re.search(
        r"^  api:\n(.*?)(?=^  [\w-]+:|\Z)",
        compose,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert api_match is not None
    api = api_match.group(1)

    assert "ACX_GPU_STATE_PATH=/run/acx/gpu-state.json" in api
    assert "ACX_DESCRIBE_LOAD_PATH=/run/acx-write/describe-load.json" in api
    assert "- /run/acx:/run/acx:ro" in api
    assert "- /run/acx:/run/acx-write" in api


def test_reader_accepts_snapshot_at_future_skew_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tolerance = gpu_state.GPU_STATE_FUTURE_SKEW_SECONDS
    path = tmp_path / "gpu-state.json"
    path.write_text(
        json.dumps({"state": "ready", "written_at": 1_000.0 + tolerance}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    assert read_gpu_state(now=1_000.0) is GpuState.READY


def test_reader_rejects_snapshot_beyond_future_skew_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tolerance = gpu_state.GPU_STATE_FUTURE_SKEW_SECONDS
    path = tmp_path / "gpu-state.json"
    path.write_text(
        json.dumps({"state": "ready", "written_at": 1_000.0 + tolerance + 0.001}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    assert read_gpu_state(now=1_000.0) is GpuState.UNKNOWN
