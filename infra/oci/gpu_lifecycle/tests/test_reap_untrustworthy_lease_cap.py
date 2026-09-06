"""Regression tests for the absolute max-lease cost cap."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from infra.oci.gpu_lifecycle.controller import (
    GpuInstance,
    GpuLifecycleController,
    JobLoadSnapshot,
)
from infra.oci.gpu_lifecycle.reaper import RunningSinceLeaseStore, run_reap_cycle


class UntrustworthyLoadSource:
    def snapshot(self) -> JobLoadSnapshot:
        return JobLoadSnapshot(
            queue_depth=0,
            in_flight=0,
            untrustworthy=True,
        )


class RaisingLoadSource:
    def snapshot(self) -> JobLoadSnapshot:
        raise RuntimeError("describe-load unavailable")


class NonSnapshotLoadSource:
    def snapshot(self) -> object:
        return object()


class RecordingActuator:
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.stopped: list[str] = []
        self.fail_for = set() if fail_for is None else fail_for

    def stop_instance(self, instance_id: str) -> None:
        if instance_id in self.fail_for:
            raise RuntimeError(f"STOP failed for {instance_id}")
        self.stopped.append(instance_id)


def _running(instance_id: str, *, age_seconds: int = 7200) -> GpuInstance:
    return GpuInstance(
        instance_id=instance_id,
        state="RUNNING",
        idle_for_seconds=age_seconds,
    )


@pytest.mark.parametrize(
    "load_source",
    [UntrustworthyLoadSource(), RaisingLoadSource(), NonSnapshotLoadSource()],
    ids=["untrustworthy", "raises", "non-snapshot"],
)
def test_expired_lease_forces_stop_before_untrustworthy_load_return(load_source: object) -> None:
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running("expired")],
        load_source=load_source,  # type: ignore[arg-type]
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        use_recorded_lease_age=False,
    )

    assert actuator.stopped == ["expired"]
    assert result.lease_expired == [("STOP", "expired")]
    assert result.fenced_off is True
    assert any("load snapshot untrustworthy" in error for error in result.errors)


def test_running_lease_store_age_forces_stop_on_untrustworthy_load(tmp_path) -> None:
    clock = {
        "wall": datetime(2026, 9, 6, 12, 0, tzinfo=UTC) - timedelta(seconds=7200),
        "monotonic": 100.0,
    }
    store = RunningSinceLeaseStore(
        path=tmp_path / "running-since.json",
        now=lambda: clock["wall"],
        monotonic=lambda: clock["monotonic"],
        boot_id="test-boot",
    )
    store.record_start("expired")
    clock["wall"] += timedelta(seconds=7200)
    clock["monotonic"] += 7200
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running("expired", age_seconds=0)],
        load_source=UntrustworthyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=store,
    )

    assert actuator.stopped == ["expired"]
    assert result.lease_expired == [("STOP", "expired")]


def test_untrustworthy_load_keeps_running_lease_below_cap_running() -> None:
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running("young", age_seconds=120)],
        load_source=UntrustworthyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        use_recorded_lease_age=False,
    )

    assert actuator.stopped == []
    assert result.lease_expired == []
    assert result.fenced_off is True
    assert any("load snapshot untrustworthy" in error for error in result.errors)


def test_zero_max_lease_disables_cap_on_untrustworthy_load() -> None:
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running("expired")],
        load_source=UntrustworthyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=0,
        use_recorded_lease_age=False,
    )

    assert actuator.stopped == []
    assert result.lease_expired == []
    assert any("load snapshot untrustworthy" in error for error in result.errors)


def test_dry_run_records_expired_lease_without_actuating() -> None:
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running("expired")],
        load_source=UntrustworthyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        use_recorded_lease_age=False,
        dry_run=True,
    )

    assert actuator.stopped == []
    assert result.lease_expired == [("STOP", "expired")]
    assert any("load snapshot untrustworthy" in error for error in result.errors)


def test_lease_stop_failure_does_not_block_another_on_untrustworthy_load() -> None:
    actuator = RecordingActuator(fail_for={"bad"})

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running("bad"), _running("good")],
        load_source=UntrustworthyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        use_recorded_lease_age=False,
    )

    assert actuator.stopped == ["good"]
    assert result.lease_expired == [("STOP", "good")]
    assert any("STOP failed for bad" in error for error in result.errors)
    assert any("load snapshot untrustworthy" in error for error in result.errors)
