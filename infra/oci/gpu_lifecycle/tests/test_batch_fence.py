"""GPU-01c: STOP is fenced for an in-flight batch; fence expiry fails closed."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from infra.oci.gpu_lifecycle import reaper as reaper_mod
from infra.oci.gpu_lifecycle.state_snapshot import (
    DEFAULT_PREVIOUS_GPU_STATE_MAX_AGE_SECONDS,
)
from infra.oci.gpu_lifecycle.controller import (
    GpuInstance,
    GpuLifecycleController,
    JobLoadSnapshot,
)
from infra.oci.gpu_lifecycle.reaper import (
    _BUSY_LOAD,
    JsonFileJobLoadSource,
    StaticJobLoadSource,
    _build_parser,
    run_reap_cycle,
)


class RecordingActuator:
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.stopped: list[str] = []
        self.fail_for = set() if fail_for is None else fail_for

    def stop_instance(self, instance_id: str) -> None:
        if instance_id in self.fail_for:
            raise RuntimeError(f"STOP failed for {instance_id}")
        self.stopped.append(instance_id)


def _snapshot(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_reap_does_not_stop_idle_instance_while_batch_in_progress() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu",
        state="RUNNING",
        idle_for_seconds=90,
    )

    actions = controller.reap_idle_instances([instance], queue_depth=0, in_flight=0, batch_in_progress=True)

    assert actions == []


def test_fence_covers_in_flight_batch_never_stopped() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    fenced = controller.fence_stop_actions(
        [("STOP", "ocid1.instance.oc1..gpu")],
        pre_stop_load=JobLoadSnapshot(queue_depth=0, in_flight=0, batch_in_progress=True),
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
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0, batch_in_progress=True),
        actuator=actuator,
        fence_delay_seconds=0.0,
    )
    assert result.decided == []
    assert result.actuated == []
    assert actuator.stopped == []


def test_partial_stop_publishes_state_of_still_running_instance(tmp_path: Path) -> None:
    path = tmp_path / "gpu-state.json"
    # A FRESH prior snapshot. read_previous_gpu_state fails closed on stale
    # evidence, so an ancient written_at would quietly convert this into a test
    # of the stale path rather than of partial-stop reduction. The stale path
    # has its own test directly below.
    path.write_text(
        json.dumps({"state": "ready", "written_at": time.time()}) + "\n",
        encoding="utf-8",
    )
    idle = GpuInstance("ocid1.idle", "RUNNING", 90)
    busy = GpuInstance("ocid1.busy", "RUNNING", 0)
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[idle, busy],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0.0,
        gpu_state_path=path,
    )

    assert result.actuated == [("STOP", "ocid1.idle")]
    assert actuator.stopped == ["ocid1.idle"]
    assert _snapshot(path) | {"written_at": 0, "since": 0} == {
        "state": "ready",
        "instance_id": None,
        "written_at": 0,
        "reason": None,
        "since": 0,
    }
    # The defect this test exists for: a partial stop must never publish
    # STOPPED while another instance is still RUNNING.
    assert _snapshot(path)["state"] != "stopped"


def test_partial_stop_with_stale_previous_state_degrades_instead_of_reusing(
    tmp_path: Path,
) -> None:
    """A stale prior snapshot must not be reused, and must not become STOPPED."""
    path = tmp_path / "gpu-state.json"
    stale_written_at = time.time() - (
        DEFAULT_PREVIOUS_GPU_STATE_MAX_AGE_SECONDS + 60.0
    )
    path.write_text(
        json.dumps({"state": "ready", "written_at": stale_written_at}) + "\n",
        encoding="utf-8",
    )
    idle = GpuInstance("ocid1.idle", "RUNNING", 90)
    busy = GpuInstance("ocid1.busy", "RUNNING", 0)
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[idle, busy],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0.0,
        gpu_state_path=path,
    )

    assert result.actuated == [("STOP", "ocid1.idle")]
    published = _snapshot(path)
    # Stale readiness evidence is discarded rather than republished as ready.
    assert published["state"] == "warming"
    # And the partial-stop guarantee still holds on the stale path.
    assert published["state"] != "stopped"


def test_failed_stop_remains_in_full_state_reduction(
    tmp_path: Path, monkeypatch,
) -> None:
    path = tmp_path / "gpu-state.json"
    failed = GpuInstance("ocid1.failed", "RUNNING", 90)
    stopped = GpuInstance("ocid1.stopped", "RUNNING", 90)
    actuator = RecordingActuator(fail_for={failed.instance_id})
    reduced_states: list[list[str]] = []
    real_state_for_instances = reaper_mod.state_for_instances

    def recording_reducer(instance_states: list[str], **kwargs):
        reduced_states.append(instance_states)
        return real_state_for_instances(instance_states, **kwargs)

    monkeypatch.setattr(reaper_mod, "state_for_instances", recording_reducer)

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[failed, stopped],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0.0,
        gpu_state_path=path,
    )

    assert result.actuated == [("STOP", "ocid1.stopped")]
    assert len(result.errors) == 1
    assert reduced_states == [["RUNNING", "STOPPED"]]
    assert _snapshot(path)["state"] == "degraded"
    assert _snapshot(path)["reason"] == "lifecycle_error"


def test_all_targeted_stops_succeed_publishes_stopped(tmp_path: Path) -> None:
    path = tmp_path / "gpu-state.json"
    instances = [
        GpuInstance("ocid1.first", "RUNNING", 90),
        GpuInstance("ocid1.second", "RUNNING", 90),
    ]

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=instances,
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator(),
        fence_delay_seconds=0.0,
        gpu_state_path=path,
    )

    assert result.actuated == [
        ("STOP", "ocid1.first"),
        ("STOP", "ocid1.second"),
    ]
    assert _snapshot(path)["state"] == "stopped"
    assert _snapshot(path)["reason"] is None


def test_failed_lease_expiry_stop_does_not_publish_stopped(tmp_path: Path) -> None:
    path = tmp_path / "gpu-state.json"
    instance = GpuInstance("ocid1.expired", "RUNNING", 3601)

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingActuator(fail_for={instance.instance_id}),
        fence_delay_seconds=0.0,
        max_lease_seconds=3600,
        gpu_state_path=path,
    )

    assert result.lease_expired == []
    assert len(result.errors) == 1
    assert _snapshot(path)["state"] == "degraded"
    assert _snapshot(path)["reason"] == "lifecycle_error"


def test_json_batch_in_progress_is_has_work(tmp_path: Path) -> None:
    path = tmp_path / "load.json"
    path.write_text(json.dumps({"queue_depth": 0, "in_flight": 0, "batch_in_progress": True}))
    snap = JsonFileJobLoadSource(path=path).snapshot()
    assert snap.batch_in_progress is True
    assert snap.has_work is True


def test_malformed_batch_flag_is_busy_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "load.json"
    path.write_text(json.dumps({"queue_depth": 0, "in_flight": 0, "batch_in_progress": 0}))
    snap = JsonFileJobLoadSource(path=path).snapshot()
    assert snap == _BUSY_LOAD
    assert snap.queue_depth == 1
    assert snap.in_flight == 1
    assert snap.batch_in_progress is True
    assert snap.untrustworthy is True
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


def test_run_reap_cycle_second_snapshot_raise_is_fenced() -> None:
    class RaiseOnSecond:
        def __init__(self) -> None:
            self.calls = 0

        def snapshot(self) -> JobLoadSnapshot:
            self.calls += 1
            if self.calls >= 2:
                raise RuntimeError("resample boom")
            return JobLoadSnapshot(queue_depth=0, in_flight=0)

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
        load_source=RaiseOnSecond(),
        actuator=actuator,
        fence_delay_seconds=0.0,
    )
    assert result.decided == [("STOP", "ocid1.instance.oc1..gpu")]
    assert result.actuated == []
    assert result.fenced_off is True
    assert actuator.stopped == []


def test_load_json_help_and_source_warn_bulk_unprotected() -> None:
    help_text = _build_parser().format_help()
    assert "batch_in_progress" in help_text
    assert "unprotected" in help_text.lower()
    assert "unprotected" in JsonFileJobLoadSource.__doc__.lower()


def test_absent_batch_key_warns_once_across_two_snapshots(tmp_path: Path, caplog: logging.LogCaptureFixture) -> None:
    reaper_mod._ABSENT_BATCH_KEY_WARNED = False
    path = tmp_path / "load.json"
    path.write_text(json.dumps({"queue_depth": 0, "in_flight": 0}))
    source = JsonFileJobLoadSource(path=path)
    with caplog.at_level(logging.WARNING, logger="infra.oci.gpu_lifecycle.reaper"):
        source.snapshot()
        source.snapshot()
    missing = [
        rec
        for rec in caplog.records
        if rec.levelno == logging.WARNING and "missing batch_in_progress" in rec.getMessage()
    ]
    assert len(missing) == 1


def test_malformed_batch_flag_still_warns_every_snapshot(tmp_path: Path, caplog: logging.LogCaptureFixture) -> None:
    path = tmp_path / "load.json"
    path.write_text(json.dumps({"queue_depth": 0, "in_flight": 0, "batch_in_progress": 0}))
    source = JsonFileJobLoadSource(path=path)
    with caplog.at_level(logging.WARNING, logger="infra.oci.gpu_lifecycle.reaper"):
        source.snapshot()
        source.snapshot()
    malformed = [
        rec
        for rec in caplog.records
        if rec.levelno == logging.WARNING and "batch_in_progress not bool" in rec.getMessage()
    ]
    assert len(malformed) == 2
