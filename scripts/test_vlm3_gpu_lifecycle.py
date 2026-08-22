import json
from pathlib import Path

import pytest

from infra.oci.gpu_lifecycle.controller import (
    GpuInstanceState,
    GpuLifecycleAction,
    GpuInstance,
    GpuLifecycleController,
    GpuServingStatus,
    JobLoadSnapshot,
)
from infra.oci.gpu_lifecycle.reaper import (
    JsonFileJobLoadSource,
    StaticJobLoadSource,
    run_reap_cycle,
)


class RecordingActuator:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []

    def start_instance(self, instance_id: str) -> None:
        self.started.append(instance_id)

    def stop_instance(self, instance_id: str) -> None:
        self.stopped.append(instance_id)


class MutableLoadSource:
    def __init__(self, queue_depth: int, in_flight: int) -> None:
        self.queue_depth = queue_depth
        self.in_flight = in_flight
        self.calls = 0

    def snapshot(self) -> JobLoadSnapshot:
        self.calls += 1
        return JobLoadSnapshot(queue_depth=self.queue_depth, in_flight=self.in_flight)


def test_idle_reaper_stops_running_instance_when_queue_drained() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu", state="RUNNING", idle_for_seconds=90
    )

    actions = controller.reap_idle_instances([instance], queue_depth=0, in_flight=0)

    assert actions == [("STOP", "ocid1.instance.oc1..gpu")]


@pytest.mark.parametrize(
    ("state", "queue_depth", "in_flight", "idle_for_seconds", "expected"),
    [
        pytest.param(
            GpuInstanceState.RUNNING,
            0,
            0,
            60,
            [(GpuLifecycleAction.STOP, "gpu")],
            id="running-idle-stops",
        ),
        pytest.param(
            GpuInstanceState.RUNNING,
            1,
            0,
            60,
            [],
            id="running-with-queued-job-no-op",
        ),
        pytest.param(
            GpuInstanceState.RUNNING,
            0,
            1,
            60,
            [],
            id="running-with-in-flight-job-no-op",
        ),
        pytest.param(
            GpuInstanceState.RUNNING,
            0,
            0,
            59,
            [],
            id="running-below-idle-threshold-no-op",
        ),
        pytest.param(
            GpuInstanceState.STOPPED,
            1,
            0,
            600,
            [(GpuLifecycleAction.START, "gpu")],
            id="stopped-with-queued-job-starts",
        ),
        pytest.param(
            GpuInstanceState.STOPPED,
            0,
            0,
            600,
            [],
            id="stopped-without-job-no-op",
        ),
        pytest.param(
            GpuInstanceState.STARTING,
            1,
            0,
            600,
            [],
            id="already-starting-no-op",
        ),
    ],
)
def test_lifecycle_decision_truth_table(
    state: GpuInstanceState,
    queue_depth: int,
    in_flight: int,
    idle_for_seconds: int,
    expected: list[tuple[GpuLifecycleAction, str]],
) -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="gpu", state=state, idle_for_seconds=idle_for_seconds
    )

    assert controller.decide_actions(
        [instance],
        load=JobLoadSnapshot(queue_depth=queue_depth, in_flight=in_flight),
    ) == expected


def test_starting_instance_reports_gpu_warming_status() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="gpu",
        state=GpuInstanceState.STARTING,
        idle_for_seconds=0,
    )

    assert controller.serving_status([instance]) is GpuServingStatus.GPU_WARMING


def test_viewer_reading_for_four_minutes_is_not_reaped() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="gpu",
        state=GpuInstanceState.RUNNING,
        idle_for_seconds=4 * 60,
    )

    actions = controller.decide_actions(
        [instance],
        load=JobLoadSnapshot(queue_depth=0, in_flight=0, active_sessions=1),
    )

    assert actions == []


def test_idle_reaper_does_not_stop_with_in_flight_work() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu", state="RUNNING", idle_for_seconds=90
    )

    assert controller.reap_idle_instances([instance], queue_depth=0, in_flight=1) == []


def test_fence_cancels_stop_when_work_arrives_before_actuation() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    decided = [("STOP", "ocid1.instance.oc1..gpu")]

    fenced = controller.fence_stop_actions(
        decided,
        pre_stop_load=JobLoadSnapshot(queue_depth=0, in_flight=1),
    )

    assert fenced == []


def test_run_reap_cycle_actuates_stop_when_still_idle() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu", state="RUNNING", idle_for_seconds=90
    )
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0.0,
    )

    assert result.decided == [("STOP", "ocid1.instance.oc1..gpu")]
    assert result.actuated == [("STOP", "ocid1.instance.oc1..gpu")]
    assert actuator.stopped == ["ocid1.instance.oc1..gpu"]
    assert result.fenced_off is False


def test_run_reap_cycle_fences_stop_when_load_appears() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu", state="RUNNING", idle_for_seconds=90
    )
    load = MutableLoadSource(queue_depth=0, in_flight=0)
    actuator = RecordingActuator()

    def _snapshot_then_inject() -> JobLoadSnapshot:
        snap = JobLoadSnapshot(queue_depth=load.queue_depth, in_flight=load.in_flight)
        # After decision sample, inject in-flight work before fence re-sample.
        if load.calls == 0:
            load.calls += 1
            load.in_flight = 1
            return JobLoadSnapshot(queue_depth=0, in_flight=0)
        load.calls += 1
        return snap

    load.snapshot = _snapshot_then_inject  # type: ignore[method-assign]

    result = run_reap_cycle(
        controller=controller,
        instances=[instance],
        load_source=load,
        actuator=actuator,
        fence_delay_seconds=0.0,
    )

    assert result.decided == [("STOP", "ocid1.instance.oc1..gpu")]
    assert result.actuated == []
    assert result.fenced_off is True
    assert actuator.stopped == []


def test_json_file_job_load_source_mirrors_store_shape(tmp_path: Path) -> None:
    path = tmp_path / "load.json"
    path.write_text(json.dumps({"queue_depth": 2, "in_flight": 1}))
    snap = JsonFileJobLoadSource(path=path).snapshot()
    assert snap == JobLoadSnapshot(queue_depth=2, in_flight=1)


def test_json_file_stale_is_busy(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "load.json"
    path.write_text(json.dumps({"queue_depth": 0, "in_flight": 0, "written_at": 0}))
    # Force mtime ancient
    import os

    os.utime(path, (1, 1))
    snap = JsonFileJobLoadSource(path=path, max_age_seconds=60).snapshot()
    assert snap.queue_depth == 1 and snap.in_flight == 1  # busy fail-safe


def test_run_reap_cycle_isolates_actuator_errors() -> None:
    class BoomActuator:
        def stop_instance(self, instance_id: str) -> None:
            raise RuntimeError(f"stop failed {instance_id}")

    controller = GpuLifecycleController(idle_seconds=60)
    instances = [
        GpuInstance(instance_id="ocid1.a", state="RUNNING", idle_for_seconds=90),
        GpuInstance(instance_id="ocid1.b", state="RUNNING", idle_for_seconds=90),
    ]
    result = run_reap_cycle(
        controller=controller,
        instances=instances,
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=BoomActuator(),
        fence_delay_seconds=0.0,
    )
    assert len(result.errors) == 2
    assert result.actuated == []
