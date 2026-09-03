"""GPUUX-1: atomic lifecycle state snapshots consumed by the describe API."""

from __future__ import annotations

import json
import os
import threading
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
    read_previous_gpu_state,
    write_gpu_state_snapshot,
)


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
def test_each_writer_state_uses_the_snapshot_schema(
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


def test_reap_publish_cannot_be_overwritten_by_stale_start_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "gpu-state.json"
    path.write_text('{"state":"ready","written_at":1.0}\n')
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))
    start_has_read = threading.Event()
    release_start = threading.Event()
    reap_finished = threading.Event()
    real_read = read_previous_gpu_state

    def pause_start_after_read(
        snapshot_path: str | Path | None = None,
    ) -> GpuLifecycleState | None:
        previous = real_read(snapshot_path)
        if threading.current_thread().name == "stale-start-cycle":
            start_has_read.set()
            assert release_start.wait(timeout=2.0)
        return previous

    monkeypatch.setattr(
        "infra.oci.gpu_lifecycle.reaper.read_previous_gpu_state",
        pause_start_after_read,
    )

    start_thread = threading.Thread(
        name="stale-start-cycle",
        target=run_start_cycle,
        kwargs={
            "controller": GpuLifecycleController(idle_seconds=60),
            "instances": [GpuInstance("ocid1.gpu", "RUNNING", 0)],
            "load_source": StaticJobLoadSource(queue_depth=0, in_flight=0),
            "actuator": RecordingActuator(),
            "gpu_state_path": path,
        },
    )

    def reap() -> None:
        run_reap_cycle(
            controller=GpuLifecycleController(idle_seconds=60),
            instances=[GpuInstance("ocid1.gpu", "RUNNING", 90)],
            load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
            actuator=RecordingActuator(),
            fence_delay_seconds=0.0,
            gpu_state_path=path,
        )
        reap_finished.set()

    reap_thread = threading.Thread(name="stopping-reap-cycle", target=reap)
    start_thread.start()
    assert start_has_read.wait(timeout=2.0)
    reap_thread.start()
    reap_finished.wait(timeout=0.25)
    release_start.set()
    start_thread.join(timeout=2.0)
    reap_thread.join(timeout=2.0)

    assert not start_thread.is_alive()
    assert not reap_thread.is_alive()
    assert json.loads(path.read_text())["state"] == "stopped"
