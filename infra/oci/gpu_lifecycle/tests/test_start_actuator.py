"""GPU-01a: start actuator emission is the stop path's twin."""

from __future__ import annotations

from pathlib import Path

from infra.oci.gpu_lifecycle.controller import (
    GpuInstance,
    GpuLifecycleController,
)
from infra.oci.gpu_lifecycle.reaper import (
    JsonFileJobLoadSource,
    OciCliStartActuator,
    OciCliStopActuator,
    StaticJobLoadSource,
    run_reap_cycle,
    run_start_cycle,
)


class RecordingStartActuator:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start_instance(self, instance_id: str) -> None:
        self.started.append(instance_id)


def test_controller_emits_start_for_stopped_instance_when_work_waiting() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu",
        state="STOPPED",
        idle_for_seconds=0,
    )

    actions = controller.start_needed_instances(
        [instance], queue_depth=1, in_flight=0
    )

    assert actions == [("START", "ocid1.instance.oc1..gpu")]


def test_controller_does_not_emit_start_when_idle() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu",
        state="STOPPED",
        idle_for_seconds=0,
    )

    assert (
        controller.start_needed_instances([instance], queue_depth=0, in_flight=0)
        == []
    )


def test_controller_does_not_emit_start_for_running_instance() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu",
        state="RUNNING",
        idle_for_seconds=0,
    )

    assert (
        controller.start_needed_instances([instance], queue_depth=4, in_flight=0)
        == []
    )


def test_start_stop_cli_commands_are_symmetric() -> None:
    start = OciCliStartActuator(oci_bin="/usr/bin/oci", auth="instance_principal")
    stop = OciCliStopActuator(oci_bin="/usr/bin/oci", auth="instance_principal")
    start_cmd = start.build_cmd("ocid1.i")
    stop_cmd = stop.build_cmd("ocid1.i")

    assert start_cmd.count("START") == 1
    assert stop_cmd.count("STOP") == 1
    normalized_start = [
        "STOP" if part == "START" else "STOPPED" if part == "RUNNING" else part
        for part in start_cmd
    ]
    assert normalized_start == stop_cmd


def test_run_start_cycle_actuates_start_and_isolates_per_instance_errors() -> None:
    class BoomThenOk:
        def __init__(self) -> None:
            self.started: list[str] = []

        def start_instance(self, instance_id: str) -> None:
            if instance_id.endswith(".a"):
                raise RuntimeError(f"start failed {instance_id}")
            self.started.append(instance_id)

    controller = GpuLifecycleController(idle_seconds=60)
    instances = [
        GpuInstance(instance_id="ocid1.a", state="STOPPED", idle_for_seconds=0),
        GpuInstance(instance_id="ocid1.b", state="STOPPED", idle_for_seconds=0),
    ]
    actuator = BoomThenOk()
    result = run_start_cycle(
        controller=controller,
        instances=instances,
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
    )

    assert result.decided == [("START", "ocid1.a"), ("START", "ocid1.b")]
    assert result.actuated == [("START", "ocid1.b")]
    assert actuator.started == ["ocid1.b"]
    assert len(result.errors) == 1
    assert "ocid1.a" in result.errors[0]


def test_start_actuator_subprocess_timeout_covers_max_wait() -> None:
    actuator = OciCliStartActuator(timeout_seconds=120, max_wait_seconds=600)
    assert actuator._timeout_seconds >= 600
    cmd = actuator.build_cmd("ocid1.i")
    max_wait = int(cmd[cmd.index("--max-wait-seconds") + 1])
    assert actuator._timeout_seconds >= max_wait
    assert max_wait == 600


def test_start_failure_emits_fallback_with_empty_actuated() -> None:
    class Boom:
        def start_instance(self, instance_id: str) -> None:
            raise RuntimeError("oci down")

    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.gpu", state="STOPPED", idle_for_seconds=0
    )
    result = run_start_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=Boom(),
    )
    assert result.actuated == []
    assert result.decided == [("START", "ocid1.gpu")]
    assert len(result.fallbacks) == 1
    assert result.fallbacks[0].reason == "start_failed"
    assert result.fallbacks[0].profile == "florence_small"
    assert result.fallbacks[0].instance_id == "ocid1.gpu"


class RecordingStopActuator:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    def stop_instance(self, instance_id: str) -> None:
        self.stopped.append(instance_id)


def test_corrupt_load_json_yields_zero_start_and_zero_stop(tmp_path: Path) -> None:
    path = tmp_path / "load.json"
    path.write_text("{not-json")
    source = JsonFileJobLoadSource(path=path)
    controller = GpuLifecycleController(idle_seconds=60)
    stopped = GpuInstance(
        instance_id="ocid1.gpu", state="STOPPED", idle_for_seconds=0
    )
    running = GpuInstance(
        instance_id="ocid1.gpu", state="RUNNING", idle_for_seconds=90
    )
    start_actuator = RecordingStartActuator()
    start_result = run_start_cycle(
        controller=controller,
        instances=[stopped],
        load_source=source,
        actuator=start_actuator,
    )
    assert start_result.decided == []
    assert start_result.actuated == []
    assert start_actuator.started == []
    assert start_result.errors

    stop_actuator = RecordingStopActuator()
    stop_result = run_reap_cycle(
        controller=controller,
        instances=[running],
        load_source=source,
        actuator=stop_actuator,
        fence_delay_seconds=0.0,
    )
    assert stop_result.actuated == []
    assert stop_actuator.stopped == []


def test_run_start_cycle_is_quiet_when_no_work() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu",
        state="STOPPED",
        idle_for_seconds=0,
    )
    actuator = RecordingStartActuator()
    result = run_start_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
    )
    assert result.decided == []
    assert result.actuated == []
    assert actuator.started == []
