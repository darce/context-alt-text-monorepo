"""Cross-package contract between the lifecycle writer and API reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from infra.oci.gpu_lifecycle.state_snapshot import (
    GpuLifecycleState,
    write_gpu_state_snapshot,
)

gpu_state = pytest.importorskip("scene.application.gpu_state")
GpuState = gpu_state.GpuState
read_gpu_state = gpu_state.read_gpu_state


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
