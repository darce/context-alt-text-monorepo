"""Fail-closed GPU lifecycle snapshot reader (GPUUX-1 lane C).

Reads /run/acx/gpu-state.json and never fabricates ``ready``. Freshness is
compared against a frozen ``now`` kwarg so tests do not sleep.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

import scene.application.gpu_state as gpu_state
from scene.application.gpu_state import (
    DEFAULT_GPU_STATE_PATH,
    DEFAULT_GPU_STATE_STALE_SECONDS,
    GPU_STATE_PATH_ENV,
    GPU_STATE_STALE_SECONDS_ENV,
    GpuState,
    read_gpu_state,
    reset_gpu_state_observation_for_tests,
    resolve_gpu_state_path,
    resolve_gpu_state_stale_seconds,
)

NOW = 1_700_000_000.0


@pytest.fixture(autouse=True)
def _reset_observation() -> None:
    reset_gpu_state_observation_for_tests()


@pytest.fixture
def snapshot_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv(GPU_STATE_PATH_ENV, str(path))
    return path


def _write_snapshot(path: Path, *, state: str, written_at: object) -> None:
    path.write_text(json.dumps({"state": state, "written_at": written_at}), encoding="utf-8")


def test_resolve_gpu_state_path_defaults_and_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(GPU_STATE_PATH_ENV, raising=False)
    assert resolve_gpu_state_path() == DEFAULT_GPU_STATE_PATH
    override = tmp_path / "custom-gpu-state.json"
    monkeypatch.setenv(GPU_STATE_PATH_ENV, str(override))
    assert resolve_gpu_state_path() == str(override)


def test_missing_file_is_unknown(snapshot_path: Path) -> None:
    assert not snapshot_path.exists()
    assert read_gpu_state(now=NOW) is GpuState.UNKNOWN


def test_fresh_ready_snapshot_is_ready(snapshot_path: Path) -> None:
    _write_snapshot(snapshot_path, state="ready", written_at=NOW - 5)
    assert read_gpu_state(now=NOW) is GpuState.READY


def test_stale_snapshot_is_unknown(snapshot_path: Path) -> None:
    _write_snapshot(snapshot_path, state="ready", written_at=NOW - 181)
    assert read_gpu_state(now=NOW) is GpuState.UNKNOWN


def test_stale_boundary_is_older_than_not_equal(snapshot_path: Path) -> None:
    """Age == stale window is still fresh; 'older than' 180s is unknown."""
    _write_snapshot(snapshot_path, state="ready", written_at=NOW - DEFAULT_GPU_STATE_STALE_SECONDS)
    assert read_gpu_state(now=NOW) is GpuState.READY
    _write_snapshot(snapshot_path, state="ready", written_at=NOW - 181)
    assert read_gpu_state(now=NOW) is GpuState.UNKNOWN


def test_corrupt_json_is_unknown(snapshot_path: Path) -> None:
    snapshot_path.write_text("{not json", encoding="utf-8")
    assert read_gpu_state(now=NOW) is GpuState.UNKNOWN


def test_bogus_state_is_unknown(snapshot_path: Path) -> None:
    _write_snapshot(snapshot_path, state="bogus", written_at=NOW - 5)
    assert read_gpu_state(now=NOW) is GpuState.UNKNOWN


def test_file_state_unknown_is_unknown(snapshot_path: Path) -> None:
    _write_snapshot(snapshot_path, state="unknown", written_at=NOW - 5)
    assert read_gpu_state(now=NOW) is GpuState.UNKNOWN


def test_unreadable_file_is_unknown(snapshot_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses file mode bits")
    _write_snapshot(snapshot_path, state="ready", written_at=NOW - 5)
    snapshot_path.chmod(0o000)
    if os.access(snapshot_path, os.R_OK):
        pytest.skip("process can still read mode 000")
    try:
        assert read_gpu_state(now=NOW) is GpuState.UNKNOWN
    finally:
        snapshot_path.chmod(0o644)


@pytest.mark.parametrize("raw", ["18O", "-1", "0", ""])
def test_gpu_state_settings_reject_explicit_invalid_stale_seconds(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv(GPU_STATE_STALE_SECONDS_ENV, raw)

    with pytest.raises(ValueError, match=GPU_STATE_STALE_SECONDS_ENV):
        gpu_state.GpuStateSettings.from_environment()


def test_gpu_state_settings_default_stale_seconds_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GPU_STATE_STALE_SECONDS_ENV, raising=False)

    settings = gpu_state.GpuStateSettings.from_environment()

    assert settings.stale_seconds == DEFAULT_GPU_STATE_STALE_SECONDS


def test_gpu_state_settings_honour_valid_explicit_stale_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GPU_STATE_STALE_SECONDS_ENV, "75.5")

    settings = gpu_state.GpuStateSettings.from_environment()

    assert settings.stale_seconds == 75.5


def test_gpu_state_settings_are_not_reparsed_after_construction(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_path: Path,
) -> None:
    monkeypatch.setenv(GPU_STATE_STALE_SECONDS_ENV, "75")
    settings = gpu_state.GpuStateSettings.from_environment()
    monkeypatch.setattr(gpu_state, "_GPU_STATE_SETTINGS", settings)

    monkeypatch.setenv(GPU_STATE_STALE_SECONDS_ENV, "10")
    _write_snapshot(snapshot_path, state="ready", written_at=NOW - 50)

    assert settings.stale_seconds == 75
    assert resolve_gpu_state_stale_seconds() == 75
    assert read_gpu_state(now=NOW) is GpuState.READY


def test_missing_or_non_numeric_written_at_is_unknown(snapshot_path: Path) -> None:
    snapshot_path.write_text(json.dumps({"state": "ready"}), encoding="utf-8")
    assert read_gpu_state(now=NOW) is GpuState.UNKNOWN
    _write_snapshot(snapshot_path, state="ready", written_at="1700000000")
    assert read_gpu_state(now=NOW) is GpuState.UNKNOWN


@pytest.mark.parametrize(
    "payload",
    [
        {"state": "degraded", "written_at": NOW},
        {"state": "ready", "written_at": NOW, "reason": "readiness_timeout"},
        {"state": "ready", "written_at": NOW, "instance_id": " \t"},
        {"state": "ready", "written_at": NOW, "since": NOW + 0.001},
    ],
)
def test_producer_invalid_shape_is_unknown(
    snapshot_path: Path,
    payload: dict[str, object],
) -> None:
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_gpu_state(now=NOW) is GpuState.UNKNOWN


def test_transition_logs_once_per_state_change(snapshot_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write_snapshot(snapshot_path, state="ready", written_at=NOW - 5)
    with caplog.at_level(logging.INFO, logger="scene.application.gpu_state"):
        assert read_gpu_state(now=NOW) is GpuState.READY
        assert read_gpu_state(now=NOW) is GpuState.READY
        transition_logs = [rec for rec in caplog.records if "gpu_state transition" in rec.getMessage()]
        assert len(transition_logs) == 1
        _write_snapshot(snapshot_path, state="warming", written_at=NOW - 5)
        assert read_gpu_state(now=NOW) is GpuState.WARMING
        transition_logs = [rec for rec in caplog.records if "gpu_state transition" in rec.getMessage()]
        assert len(transition_logs) == 2
