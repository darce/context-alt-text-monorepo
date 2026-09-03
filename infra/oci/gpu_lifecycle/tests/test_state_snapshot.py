"""GPUUX-1: atomic lifecycle state snapshots consumed by the describe API."""

from __future__ import annotations

import fcntl
import json
import math
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
    DEFAULT_GPU_STATE_PATH,
    GpuLifecycleState,
    read_previous_gpu_state,
    resolve_gpu_state_path,
    state_for_instances,
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


SNAPSHOT_NOW = 1_700_000_000.0


def _write_previous_snapshot(
    path: Path,
    *,
    state: str = "ready",
    written_at: object = SNAPSHOT_NOW,
    instance_id: object = "ocid1.gpu",
    reason: object = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "state": state,
                "instance_id": instance_id,
                "written_at": written_at,
                "reason": reason,
                "since": SNAPSHOT_NOW - 10.0,
            }
        ),
        encoding="utf-8",
    )


def test_stale_ready_snapshot_is_not_preserved(tmp_path: Path) -> None:
    path = tmp_path / "gpu-state.json"
    _write_previous_snapshot(path, written_at=SNAPSHOT_NOW - 180.001)

    assert read_previous_gpu_state(path, now=SNAPSHOT_NOW) is None


def test_future_dated_ready_snapshot_is_not_preserved(tmp_path: Path) -> None:
    path = tmp_path / "gpu-state.json"
    _write_previous_snapshot(path, written_at=SNAPSHOT_NOW + 5.001)

    assert read_previous_gpu_state(path, now=SNAPSHOT_NOW) is None


def test_missing_written_at_is_not_preserved(tmp_path: Path) -> None:
    path = tmp_path / "gpu-state.json"
    _write_previous_snapshot(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["written_at"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_previous_gpu_state(path, now=SNAPSHOT_NOW) is None


@pytest.mark.parametrize("written_at", ["not-a-timestamp", True, math.inf])
def test_malformed_written_at_is_not_preserved(
    tmp_path: Path,
    written_at: object,
) -> None:
    path = tmp_path / "gpu-state.json"
    _write_previous_snapshot(path, written_at=written_at)

    assert read_previous_gpu_state(path, now=SNAPSHOT_NOW) is None


def test_fresh_ready_snapshot_is_preserved_for_running_instance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gpu-state.json"
    _write_previous_snapshot(path, written_at=SNAPSHOT_NOW - 180.0)

    previous_state = read_previous_gpu_state(path, now=SNAPSHOT_NOW)

    assert previous_state is GpuLifecycleState.READY
    assert state_for_instances(
        ["RUNNING"], previous_state=previous_state
    ) is GpuLifecycleState.READY


def test_written_snapshot_round_trips_to_previous_state_within_freshness_bound(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gpu-state.json"
    assert write_gpu_state_snapshot(
        GpuLifecycleState.READY,
        instance_id="ocid1.gpu",
        now=SNAPSHOT_NOW,
        path=path,
    )

    assert (
        read_previous_gpu_state(path, now=SNAPSHOT_NOW + 180.0)
        is GpuLifecycleState.READY
    )


@pytest.mark.parametrize(
    ("state", "instance_id", "reason"),
    [
        ("ready", "", None),
        ("ready", 42, None),
        ("ready", "ocid1.gpu", "unexpected"),
        ("degraded", "ocid1.gpu", None),
        ("degraded", "ocid1.gpu", ""),
    ],
)
def test_previous_snapshot_rejects_invalid_contract_metadata(
    tmp_path: Path,
    state: str,
    instance_id: object,
    reason: object,
) -> None:
    path = tmp_path / "gpu-state.json"
    _write_previous_snapshot(
        path,
        state=state,
        instance_id=instance_id,
        reason=reason,
    )

    assert read_previous_gpu_state(path, now=SNAPSHOT_NOW) is None


@pytest.mark.parametrize("configured_path", ["", " ", "\t"])
def test_writer_blank_path_env_uses_default(
    monkeypatch: pytest.MonkeyPatch,
    configured_path: str,
) -> None:
    monkeypatch.setenv("ACX_GPU_STATE_PATH", configured_path)

    assert resolve_gpu_state_path() == Path(DEFAULT_GPU_STATE_PATH)


def test_running_instance_does_not_preserve_previous_starting_state() -> None:
    assert state_for_instances(
        ["RUNNING"],
        previous_state=GpuLifecycleState.STARTING,
    ) is GpuLifecycleState.WARMING


def test_writer_emits_documented_metadata_and_tracks_state_change_time(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gpu-state.json"

    assert write_gpu_state_snapshot(
        GpuLifecycleState.WARMING,
        instance_id="ocid1.gpu",
        now=100.0,
        path=path,
    ) is True
    assert write_gpu_state_snapshot(
        GpuLifecycleState.WARMING,
        instance_id="ocid1.gpu",
        now=110.0,
        path=path,
    ) is True
    assert json.loads(path.read_text()) == {
        "state": "warming",
        "instance_id": "ocid1.gpu",
        "written_at": 110.0,
        "reason": None,
        "since": 100.0,
    }

    assert write_gpu_state_snapshot(
        GpuLifecycleState.DEGRADED,
        instance_id="ocid1.gpu",
        reason="readiness_timeout",
        now=120.0,
        path=path,
    ) is True
    assert json.loads(path.read_text()) == {
        "state": "degraded",
        "instance_id": "ocid1.gpu",
        "written_at": 120.0,
        "reason": "readiness_timeout",
        "since": 120.0,
    }


def test_writer_requires_reason_for_degraded_snapshot(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reason"):
        write_gpu_state_snapshot(
            GpuLifecycleState.DEGRADED,
            now=120.0,
            path=tmp_path / "gpu-state.json",
        )


@pytest.mark.parametrize("state", list(GpuLifecycleState))
def test_each_writer_state_uses_the_snapshot_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: GpuLifecycleState,
) -> None:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    reason = "test_degraded" if state is GpuLifecycleState.DEGRADED else None
    assert write_gpu_state_snapshot(
        state,
        reason=reason,
        now=1_788_390_000.0,
    ) is True

    assert json.loads(path.read_text()) == {
        "state": state.value,
        "instance_id": None,
        "written_at": 1_788_390_000.0,
        "reason": reason,
        "since": 1_788_390_000.0,
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
    assert json.loads(path.read_text()) == {
        "state": "ready",
        "instance_id": None,
        "written_at": 2.0,
        "reason": None,
        "since": 2.0,
    }


def test_write_failure_is_swallowed_and_cycle_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    def fail_tempfile(**_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(
        "infra.oci.gpu_lifecycle.state_snapshot.tempfile.NamedTemporaryFile",
        fail_tempfile,
    )
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
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelname == "WARNING"
    ]
    assert len(warnings) == 1
    assert "failed to write GPU state snapshot" in warnings[0]
    assert all(str(path) in message for message in warnings)


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


def test_steady_running_cycle_reprobes_warming_instance_to_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "gpu-state.json"
    path.write_text('{"state":"warming","written_at":1.0}\n')
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance("ocid1.gpu", "RUNNING", 0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator(),
        probe=AlwaysReady(),
        readiness_wait=WarmReadinessWait(
            max_cycles=1, stall_cycles=2, sleep_seconds=0.0
        ),
    )

    assert result.wait_result is not None
    assert result.wait_result.ready == ("ocid1.gpu",)
    assert json.loads(path.read_text())["state"] == "ready"


def test_steady_running_cycle_reprobes_ready_instance_to_degraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "gpu-state.json"
    path.write_text('{"state":"ready","written_at":1.0}\n')
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(path))

    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance("ocid1.gpu", "RUNNING", 0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator(),
        probe=NeverReady(),
        readiness_wait=WarmReadinessWait(
            max_cycles=1, stall_cycles=2, sleep_seconds=0.0
        ),
    )

    assert result.wait_result is not None
    assert result.wait_result.timed_out == ("ocid1.gpu",)
    payload = json.loads(path.read_text())
    assert payload["state"] == "degraded"
    assert payload["reason"] == "readiness_timeout"


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
    assert write_gpu_state_snapshot(
        GpuLifecycleState.READY,
        instance_id="ocid1.gpu",
        path=path,
    )
    previous_written_at = json.loads(path.read_text())["written_at"]
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
    assert payload["written_at"] >= previous_written_at


def test_lock_failure_aborts_snapshot_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "gpu-state.json"

    def fail_lock(_file_descriptor: int, _operation: int) -> None:
        raise OSError("simulated cross-unit permission failure")

    monkeypatch.setattr("infra.oci.gpu_lifecycle.reaper.fcntl.flock", fail_lock)

    with pytest.raises(OSError, match="simulated cross-unit permission failure"):
        run_reap_cycle(
            controller=GpuLifecycleController(idle_seconds=60),
            instances=[GpuInstance("ocid1.gpu", "RUNNING", 0)],
            load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
            actuator=RecordingActuator(),
            fence_delay_seconds=0.0,
            gpu_state_path=path,
        )

    assert not path.exists()


def test_snapshot_lock_creation_repairs_umask_to_group_writable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gpu-state.json"
    previous_umask = os.umask(0o027)
    try:
        run_reap_cycle(
            controller=GpuLifecycleController(idle_seconds=60),
            instances=[GpuInstance("ocid1.gpu", "RUNNING", 0)],
            load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
            actuator=RecordingActuator(),
            fence_delay_seconds=0.0,
            gpu_state_path=path,
        )
    finally:
        os.umask(previous_umask)

    lock_path = path.with_name("gpu-state.json.lock")
    assert lock_path.stat().st_mode & 0o777 == 0o660


def test_existing_snapshot_lock_only_requires_read_permission(tmp_path: Path) -> None:
    path = tmp_path / "gpu-state.json"
    lock_path = path.with_name("gpu-state.json.lock")
    lock_path.touch(mode=0o440)

    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance("ocid1.gpu", "RUNNING", 0)],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingActuator(),
        fence_delay_seconds=0.0,
        gpu_state_path=path,
    )

    assert json.loads(path.read_text())["state"] == "warming"


def test_snapshot_publish_locks_the_group_writable_sidecar_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "gpu-state.json"
    locked_inodes: list[tuple[int, int]] = []
    real_flock = fcntl.flock

    def record_flock(fd: int, operation: int) -> None:
        locked_inodes.append((os.fstat(fd).st_ino, operation))
        real_flock(fd, operation)

    monkeypatch.setattr("infra.oci.gpu_lifecycle.reaper.fcntl.flock", record_flock)

    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance("ocid1.gpu", "RUNNING", 0)],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingActuator(),
        fence_delay_seconds=0.0,
        gpu_state_path=path,
    )

    lock_inode = path.with_name("gpu-state.json.lock").stat().st_ino
    assert locked_inodes == [
        (lock_inode, fcntl.LOCK_EX),
        (lock_inode, fcntl.LOCK_UN),
    ]


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
