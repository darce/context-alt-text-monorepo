"""GPUUX-1: atomic lifecycle state snapshots consumed by the describe API."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController
from infra.oci.gpu_lifecycle.probe import ProbeSample, ProbeStatus, WarmReadinessWait
from infra.oci.gpu_lifecycle.reaper import (
    StaticJobLoadSource,
    run_reap_cycle,
    run_start_cycle,
)
from infra.oci.gpu_lifecycle.state_snapshot import (
    GpuLifecycleState,
    write_gpu_state_snapshot,
)
gpu_state = pytest.importorskip("scene.application.gpu_state")
GpuState = gpu_state.GpuState
read_gpu_state = gpu_state.read_gpu_state


class RecordingActuator:
    def __init__(self) -> None:
        self.instance_ids: list[str] = []

    def start_instance(self, instance_id: str) -> None:
        self.instance_ids.append(instance_id)

    def stop_instance(self, instance_id: str) -> None:
        self.instance_ids.append(instance_id)


class AlwaysReady:
    def probe(self, instance_id: str) -> ProbeSample:
        return ProbeSample(instance_id=instance_id, status=ProbeStatus.READY)


class NeverReady:
    def probe(self, instance_id: str) -> ProbeSample:
        return ProbeSample(instance_id=instance_id, status=ProbeStatus.NOT_READY)


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


def test_writer_rejects_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    with pytest.raises(ValueError, match="unknown"):
        write_gpu_state_snapshot("unknown")

    assert not path.exists()


def test_replace_is_atomic_and_target_is_never_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "gpu-state.json"
    path.write_text('{"state":"stopped","written_at":1.0}\n')
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))
    observed_during_replace: list[str] = []
    real_replace = os.replace

    def observing_replace(source: str | Path, target: str | Path) -> None:
        observed_during_replace.append(path.read_text())
        assert Path(source).parent == path.parent
        real_replace(source, target)

    monkeypatch.setattr(
        "infra.oci.gpu_lifecycle.state_snapshot.os.replace", observing_replace
    )

    assert write_gpu_state_snapshot(GpuLifecycleState.READY, now=2.0) is True

    assert observed_during_replace == [
        '{"state":"stopped","written_at":1.0}\n'
    ]
    assert json.loads(path.read_text()) == {"state": "ready", "written_at": 2.0}


def test_write_failure_is_swallowed_and_cycle_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("occupied")
    path = parent_file / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance("ocid1.gpu", "STOPPED", 0)

    result = run_start_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator(),
    )

    assert result.decided == []
    assert result.errors == []
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(path) in warnings[0].getMessage()


@pytest.mark.parametrize(
    ("instances", "queue_depth", "expected"),
    [
        ([GpuInstance("ocid1.gpu", "STOPPED", 0)], 0, "stopped"),
        ([GpuInstance("ocid1.gpu", "STOPPED", 0)], 1, "starting"),
        ([GpuInstance("ocid1.gpu", "RUNNING", 0)], 0, "warming"),
    ],
)
def test_start_cycle_writes_snapshot_for_no_action_and_start_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    instances: list[GpuInstance],
    queue_depth: int,
    expected: str,
) -> None:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=instances,
        load_source=StaticJobLoadSource(queue_depth=queue_depth, in_flight=0),
        actuator=RecordingActuator(),
    )

    assert json.loads(path.read_text())["state"] == expected


@pytest.mark.parametrize(
    ("probe", "expected"),
    [(AlwaysReady(), "ready"), (NeverReady(), "degraded")],
)
def test_start_cycle_writes_readiness_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probe: AlwaysReady | NeverReady,
    expected: str,
) -> None:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance("ocid1.gpu", "STOPPED", 0)],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingActuator(),
        probe=probe,
        readiness_wait=WarmReadinessWait(
            max_cycles=1, stall_cycles=2, sleep_seconds=0.0
        ),
    )

    assert json.loads(path.read_text())["state"] == expected


def test_reap_cycle_writes_stopped_after_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance("ocid1.gpu", "RUNNING", 90)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator(),
        fence_delay_seconds=0.0,
    )

    assert json.loads(path.read_text())["state"] == "stopped"


def test_reap_cycle_refreshes_ready_without_demoting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "gpu-state.json"
    path.write_text('{"state":"ready","written_at":1.0}\n')
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance("ocid1.gpu", "RUNNING", 0)],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingActuator(),
        fence_delay_seconds=0.0,
    )

    payload = json.loads(path.read_text())
    assert payload["state"] == "ready"
    assert payload["written_at"] > 1.0
