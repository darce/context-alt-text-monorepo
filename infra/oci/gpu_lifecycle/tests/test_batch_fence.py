"""GPU-01c: STOP is fenced for an in-flight batch; fence expiry fails closed."""

from __future__ import annotations

import json
from pathlib import Path

from infra.oci.gpu_lifecycle.controller import (
    GpuInstance,
    GpuLifecycleController,
    JobLoadSnapshot,
)
from infra.oci.gpu_lifecycle.reaper import (
    JsonFileJobLoadSource,
    StaticJobLoadSource,
    _build_parser,
    run_reap_cycle,
)


class RecordingActuator:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    def stop_instance(self, instance_id: str) -> None:
        self.stopped.append(instance_id)


def test_reap_does_not_stop_idle_instance_while_batch_in_progress() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu",
        state="RUNNING",
        idle_for_seconds=90,
    )

    actions = controller.reap_idle_instances(
        [instance], queue_depth=0, in_flight=0, batch_in_progress=True
    )

    assert actions == []


def test_fence_covers_in_flight_batch_never_stopped() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    fenced = controller.fence_stop_actions(
        [("STOP", "ocid1.instance.oc1..gpu")],
        pre_stop_load=JobLoadSnapshot(
            queue_depth=0, in_flight=0, batch_in_progress=True
        ),
    )
    assert fenced == []


def test_fence_expiry_falls_back_closed() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    fenced = controller.fence_stop_actions(
        [("STOP", "ocid1.instance.oc1..gpu")],
        pre_stop_load=JobLoadSnapshot(queue_depth=0, in_flight=0),
        fence_expired=True,
    )
    assert fenced == []


def test_run_reap_cycle_never_stops_fenced_batch() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu",
        state="RUNNING",
        idle_for_seconds=90,
    )
    actuator = RecordingActuator()
    result = run_reap_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(
            queue_depth=0, in_flight=0, batch_in_progress=True
        ),
        actuator=actuator,
        fence_delay_seconds=0.0,
    )
    assert result.decided == []
    assert result.actuated == []
    assert actuator.stopped == []


def test_json_batch_in_progress_is_has_work(tmp_path: Path) -> None:
    path = tmp_path / "load.json"
    path.write_text(
        json.dumps({"queue_depth": 0, "in_flight": 0, "batch_in_progress": True})
    )
    snap = JsonFileJobLoadSource(path=path).snapshot()
    assert snap.batch_in_progress is True
    assert snap.has_work is True


def test_malformed_batch_flag_is_busy_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "load.json"
    path.write_text(
        json.dumps({"queue_depth": 0, "in_flight": 0, "batch_in_progress": "yes"})
    )
    snap = JsonFileJobLoadSource(path=path).snapshot()
    assert snap.has_work is True


def test_absent_batch_key_idle_allows_stop(tmp_path: Path) -> None:
    """Absent batch_in_progress is not protection; idle snapshot may STOP."""
    path = tmp_path / "load.json"
    path.write_text(json.dumps({"queue_depth": 0, "in_flight": 0}))
    snap = JsonFileJobLoadSource(path=path).snapshot()
    assert snap.batch_in_progress is False
    assert snap.has_work is False

    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu",
        state="RUNNING",
        idle_for_seconds=90,
    )
    actuator = RecordingActuator()
    result = run_reap_cycle(
        controller=controller,
        instances=[instance],
        load_source=JsonFileJobLoadSource(path=path),
        actuator=actuator,
        fence_delay_seconds=0.0,
    )
    assert result.decided == [("STOP", "ocid1.instance.oc1..gpu")]
    assert result.actuated == [("STOP", "ocid1.instance.oc1..gpu")]
    assert actuator.stopped == ["ocid1.instance.oc1..gpu"]


def test_absent_batch_key_still_fences_on_in_flight(tmp_path: Path) -> None:
    """Absent batch key does not disable queue/in_flight STOP protection."""
    path = tmp_path / "load.json"
    path.write_text(json.dumps({"queue_depth": 0, "in_flight": 1}))
    snap = JsonFileJobLoadSource(path=path).snapshot()
    assert snap.batch_in_progress is False
    assert snap.has_work is True

    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu",
        state="RUNNING",
        idle_for_seconds=90,
    )
    actuator = RecordingActuator()
    result = run_reap_cycle(
        controller=controller,
        instances=[instance],
        load_source=JsonFileJobLoadSource(path=path),
        actuator=actuator,
        fence_delay_seconds=0.0,
    )
    assert result.decided == []
    assert result.actuated == []
    assert actuator.stopped == []


def test_load_json_help_and_source_warn_bulk_unprotected() -> None:
    help_text = _build_parser().format_help()
    assert "batch_in_progress" in help_text
    assert "unprotected" in help_text.lower()
    assert "unprotected" in JsonFileJobLoadSource.__doc__.lower()
