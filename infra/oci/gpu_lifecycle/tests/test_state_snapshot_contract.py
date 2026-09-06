"""Cross-package contract between the lifecycle writer and API reader."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from infra.oci.gpu_lifecycle.state_snapshot import (
    DEFAULT_PREVIOUS_GPU_STATE_MAX_AGE_SECONDS,
    DEFAULT_PREVIOUS_GPU_STATE_MAX_FUTURE_SKEW_SECONDS,
    GpuLifecycleState,
    write_gpu_state_snapshot,
)

from scene.application import gpu_state
from scene.application.gpu_state import (
    DEFAULT_GPU_STATE_STALE_SECONDS,
    GPU_STATE_FUTURE_SKEW_SECONDS,
    GpuState,
    read_gpu_state,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "gpu-lifecycle-install.sh"
DEPLOYED_COMPOSE = (
    REPO_ROOT / "apps" / "prototype-description-service" / "docker-compose.env.yml"
)


def test_previous_snapshot_freshness_defaults_match_real_reader() -> None:
    assert (
        DEFAULT_PREVIOUS_GPU_STATE_MAX_AGE_SECONDS
        == DEFAULT_GPU_STATE_STALE_SECONDS
        == 180.0
    )
    assert (
        DEFAULT_PREVIOUS_GPU_STATE_MAX_FUTURE_SKEW_SECONDS
        == GPU_STATE_FUTURE_SKEW_SECONDS
        == 5.0
    )


@pytest.mark.parametrize("state", list(GpuLifecycleState))
def test_each_writer_state_round_trips_through_real_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: GpuLifecycleState,
) -> None:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    reason = "test_degraded" if state is GpuLifecycleState.DEGRADED else None
    assert write_gpu_state_snapshot(
        state,
        instance_id="ocid1.gpu",
        reason=reason,
        now=1_788_390_000.0,
    ) is True

    assert json.loads(path.read_text()) == {
        "state": state.value,
        "instance_id": "ocid1.gpu",
        "written_at": 1_788_390_000.0,
        "reason": reason,
        "since": 1_788_390_000.0,
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


def test_snapshot_directories_enforce_distinct_writer_ownership() -> None:
    script = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert re.search(
        r"(?m)^\s*(?:sudo\s+)?tee\s+(?:\\?['\"]?)/etc/systemd/system/acx-gpu-[^'\"\s]+\.service(?:\\?['\"]?).*<<",
        script,
    ) is None, "lifecycle services must be rendered into the private staged generation"
    service_bodies = re.findall(
        r'tee \\\"\\\$unit_stage/acx-gpu-(?:start|reap)\.service\\\".*?<<UNIT\n(.*?)\nUNIT',
        script,
        flags=re.DOTALL,
    )
    assert len(service_bodies) == 2

    state_chown_match = re.search(
        r"^sudo chown ([^:\s]+):([^\s]+) /run/acx$", script, flags=re.MULTILINE
    )
    state_tmpfiles_match = re.search(
        r"^d /run/acx (\d+) ([^\s]+) ([^\s]+) -$", script, flags=re.MULTILINE
    )
    load_chown_match = re.search(
        r"^sudo chown ([^:\s]+):([^\s]+) /run/acx-write$",
        script,
        flags=re.MULTILINE,
    )
    load_tmpfiles_match = re.search(
        r"^d /run/acx-write (\d+) ([^\s]+) ([^\s]+) -$",
        script,
        flags=re.MULTILINE,
    )
    environment_load_tmpfiles_match = re.search(
        r"d /run/acx-write/\$\{environment\} (\d+) ([^\s]+) ([^\s]+) -",
        script,
    )
    state_chmod_match = re.search(
        r"^sudo chmod (\d+) /run/acx$", script, flags=re.MULTILINE
    )
    load_chmod_match = re.search(
        r"^sudo chmod (\d+) /run/acx-write$", script, flags=re.MULTILINE
    )
    environment_load_chmod_match = re.search(
        r"^sudo chmod (\d+) \$\{LOAD_ENVIRONMENT_DIRS\}$",
        script,
        flags=re.MULTILINE,
    )
    lock_tmpfiles_match = re.search(
        r"^f /run/acx/gpu-state\.json\.lock (\d+) ([^\s]+) ([^\s]+) -$",
        script,
        flags=re.MULTILINE,
    )
    assert state_chown_match is not None
    assert state_tmpfiles_match is not None
    assert load_chown_match is not None
    assert load_tmpfiles_match is not None
    assert environment_load_tmpfiles_match is not None
    assert state_chmod_match is not None
    assert load_chmod_match is not None
    assert environment_load_chmod_match is not None
    assert lock_tmpfiles_match is not None
    state_owner, state_group = state_chown_match.groups()
    state_mode, state_boot_owner, state_boot_group = state_tmpfiles_match.groups()
    load_owner, load_group = load_chown_match.groups()
    load_mode, load_boot_owner, load_boot_group = load_tmpfiles_match.groups()
    environment_load_mode, environment_load_owner, environment_load_group = (
        environment_load_tmpfiles_match.groups()
    )
    state_chmod_mode = state_chmod_match.group(1)
    load_chmod_mode = load_chmod_match.group(1)
    environment_load_chmod_mode = environment_load_chmod_match.group(1)
    lock_mode, lock_owner, lock_group = lock_tmpfiles_match.groups()
    assert (state_boot_owner, state_boot_group) == (state_owner, state_group)
    assert state_mode == "0755"
    assert state_chmod_mode == state_mode
    assert int(state_mode[-3]) & 0o2, "the lifecycle owner must be able to write"
    assert (load_boot_owner, load_boot_group) == (load_owner, load_group)
    assert load_group == "10001"
    assert load_mode == environment_load_mode == "0775"
    assert load_chmod_mode == load_mode
    assert environment_load_chmod_mode == environment_load_mode
    assert int(load_mode[-2]) & 0o2, "API gid 10001 must be able to write load dumps"
    assert (environment_load_owner, environment_load_group) == (load_owner, load_group)
    assert int(environment_load_mode[-2]) & 0o2, (
        "API gid 10001 must be able to write per-environment load dumps"
    )
    assert (state_owner, state_group) != (load_owner, load_group)
    assert (lock_owner, lock_group) == (state_owner, state_group)
    assert lock_mode == "0600"
    assert int(lock_mode, 8) & 0o600 == 0o600

    for body in service_bodies:
        user_match = re.search(r"^User=(\S+)$", body, flags=re.MULTILINE)
        groups_match = re.search(r"^SupplementaryGroups=(.+)$", body, flags=re.MULTILINE)
        assert user_match is not None
        unit_user = user_match.group(1)
        supplementary_groups = groups_match.group(1).split() if groups_match else []
        assert unit_user == state_owner or state_group in supplementary_groups
        assert load_group in supplementary_groups


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
    assert "- /run/acx:/run/acx:ro" in api
    assert "- /run/acx:/run/acx-write" not in api

    load_path_match = re.search(
        r"^\s*- ACX_DESCRIBE_LOAD_PATH=([^\s]+)$", api, flags=re.MULTILINE
    )
    assert load_path_match is not None
    load_path = load_path_match.group(1)
    expected_load_dir = "/run/acx-write/${ACX_ENV}"
    assert load_path == f"{expected_load_dir}/describe-load.json"

    mount_matches = re.findall(
        r"^\s*- ([^:\s]+):([^:\s]+)(?::([^\s]+))?$", api, flags=re.MULTILINE
    )
    load_mounts = [mount for mount in mount_matches if mount[1] == expected_load_dir]
    assert load_mounts == [(expected_load_dir, expected_load_dir, "")]
    assert load_path.rsplit("/", 1)[0] == load_mounts[0][1]

    # H-04: mounting the shared parent restores cross-environment overwrite access.
    assert not any(
        source == "/run/acx-write" or target == "/run/acx-write"
        for source, target, _options in mount_matches
    )


def test_atomic_writer_replaces_inode_instead_of_updating_bound_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gpu-state.json"
    pinned_inode = tmp_path / "file-bind-inode"
    assert write_gpu_state_snapshot(GpuLifecycleState.STARTING, now=1.0, path=path)
    pinned_inode.hardlink_to(path)
    original_inode = path.stat().st_ino

    assert write_gpu_state_snapshot(GpuLifecycleState.READY, now=2.0, path=path)

    assert path.stat().st_ino != original_inode
    assert json.loads(path.read_text())["state"] == "ready"
    assert json.loads(pinned_inode.read_text())["state"] == "starting"


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
