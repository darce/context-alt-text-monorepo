"""GPUW-1: the max-lease cost backstop.

Everything else in this module fails closed *toward busy*: a missing, stale or
unparseable load dump cancels the STOP. That protects jobs and leaves cost
unbounded -- a dead load writer means nothing in the system will ever stop a
running A10 (~$2/hr). These pin the one path that stops on wall clock alone.
"""

from __future__ import annotations

import fcntl
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from infra.oci.gpu_lifecycle.controller import (
    GpuInstance,
    GpuLifecycleController,
    JobLoadSnapshot,
)
from infra.oci.gpu_lifecycle.reaper import (
    CorruptRunningSinceLeaseError,
    RunningSinceLeaseStore,
    StaticJobLoadSource,
    _build_parser,
    fetch_instance_idle_seconds,
    main,
    run_reap_cycle,
    run_start_cycle,
)


class RecordingActuator:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    def stop_instance(self, instance_id: str) -> None:
        self.stopped.append(instance_id)


class ExplodingActuator:
    def stop_instance(self, instance_id: str) -> None:
        raise RuntimeError("oci unavailable")


class BusyLoadSource:
    """The failure this backstop exists for: load always claims work."""

    def snapshot(self):
        from infra.oci.gpu_lifecycle.controller import JobLoadSnapshot

        return JobLoadSnapshot(queue_depth=5, in_flight=2, batch_in_progress=True)


class UntrustworthyLoadSource:
    def snapshot(self) -> JobLoadSnapshot:
        return JobLoadSnapshot(
            queue_depth=0,
            in_flight=0,
            untrustworthy=True,
        )


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TEST_MONOTONIC = 100_000.0
TEST_BOOT_ID = "test-boot"


@pytest.fixture(autouse=True)
def synthetic_host_boot_id(monkeypatch):
    """CLI tests must not depend on the execution host's Linux proc filesystem."""
    original_read_text = Path.read_text

    def read_text(path, *args, **kwargs):
        if path == Path("/proc/sys/kernel/random/boot_id"):
            return TEST_BOOT_ID
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)


def test_cli_missing_boot_identity_is_a_fatal_startup_error(tmp_path, monkeypatch, capsys):
    original_read_text = Path.read_text

    def read_text(path, *args, **kwargs):
        if path == Path("/proc/sys/kernel/random/boot_id"):
            raise FileNotFoundError("simulated host without Linux boot identity")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    lease_path = tmp_path / "lease.json"
    exit_code = main([
        "--instance-id", "instance-a",
        "--running-since-path", str(lease_path),
        "--dry-run",
    ])

    assert exit_code != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    assert captured.err.startswith("fatal: running-since boot identity unavailable:")
    assert "Traceback" not in captured.err
    assert not lease_path.exists()


def _lease_store(path: Path) -> RunningSinceLeaseStore:
    return RunningSinceLeaseStore(
        path=path,
        now=lambda: NOW,
        monotonic=lambda: TEST_MONOTONIC,
        boot_id=TEST_BOOT_ID,
    )


def _write_lease(
    path: Path,
    *,
    since: str,
    source: str = "start_actuator",
    instance_id: str = "instance-a",
    with_monotonic_origin: bool = True,
) -> None:
    record: dict[str, object] = {"since": since, "source": source}
    if with_monotonic_origin:
        parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
        record.update(
            monotonic_since=TEST_MONOTONIC - (NOW - parsed).total_seconds(),
            boot_id=TEST_BOOT_ID,
        )
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "instances": {instance_id: record},
            }
        )
    )


def _running(age: int, instance_id: str = "ocid1.instance.oc1..gpu") -> GpuInstance:
    return GpuInstance(instance_id=instance_id, state="RUNNING", idle_for_seconds=age)


# --- controller-level -------------------------------------------------------


def test_lease_expired_selects_running_instance_past_the_cap() -> None:
    controller = GpuLifecycleController(idle_seconds=300)
    actions = controller.lease_expired_instances([_running(3601)], max_lease_seconds=3600)
    assert actions == [("STOP", "ocid1.instance.oc1..gpu")]


def test_lease_not_expired_below_the_cap() -> None:
    """TEST-15: the cap must be able to *not* fire, or it kills every batch."""
    controller = GpuLifecycleController(idle_seconds=300)
    assert controller.lease_expired_instances([_running(60)], max_lease_seconds=3600) == []


def test_lease_cap_ignores_instances_that_are_not_running() -> None:
    controller = GpuLifecycleController(idle_seconds=300)
    stopped = GpuInstance(instance_id="ocid1.instance.oc1..gpu", state="STOPPED", idle_for_seconds=99_999)
    starting = GpuInstance(
        instance_id="ocid1.instance.oc1..gpu2",
        state="STARTING",
        idle_for_seconds=99_999,
    )
    assert controller.lease_expired_instances([stopped, starting], max_lease_seconds=60) == []


def test_lease_cap_disabled_by_zero() -> None:
    controller = GpuLifecycleController(idle_seconds=300)
    assert controller.lease_expired_instances([_running(99_999)], max_lease_seconds=0) == []


# --- cycle-level: the cap must beat the fence -------------------------------


def test_lease_expiry_stops_even_when_load_claims_a_batch_is_running() -> None:
    """The whole point: a busy-forever load signal cannot veto the backstop."""
    controller = GpuLifecycleController(idle_seconds=300)
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=controller,
        instances=[_running(7200)],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert actuator.stopped == ["ocid1.instance.oc1..gpu"]
    assert result.lease_expired == [("STOP", "ocid1.instance.oc1..gpu")]
    # Reported separately from a normal drain so an operator can tell the
    # backstop firing from the queue emptying.
    assert result.actuated == []


def test_lease_expiry_forces_stop_on_untrustworthy_load() -> None:
    controller = GpuLifecycleController(idle_seconds=300)
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=controller,
        instances=[_running(7200)],
        load_source=UntrustworthyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert actuator.stopped == ["ocid1.instance.oc1..gpu"]
    assert result.lease_expired == [("STOP", "ocid1.instance.oc1..gpu")]
    assert result.fenced_off is True
    assert "load snapshot untrustworthy" in result.errors[-1]


def test_within_lease_the_busy_fence_still_protects_the_batch() -> None:
    """The backstop must not become a blanket 'always stop'."""
    controller = GpuLifecycleController(idle_seconds=300)
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=controller,
        instances=[_running(120)],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert actuator.stopped == []
    assert result.lease_expired == []


def test_lease_expired_instance_is_not_stopped_twice_in_one_cycle() -> None:
    controller = GpuLifecycleController(idle_seconds=300)
    actuator = RecordingActuator()

    run_reap_cycle(
        controller=controller,
        instances=[_running(7200)],
        # Idle load would also select this instance via the normal path.
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert actuator.stopped == ["ocid1.instance.oc1..gpu"]


def test_lease_stop_failure_is_reported_not_swallowed() -> None:
    controller = GpuLifecycleController(idle_seconds=300)

    result = run_reap_cycle(
        controller=controller,
        instances=[_running(7200)],
        load_source=BusyLoadSource(),
        actuator=ExplodingActuator(),
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert result.lease_expired == []
    assert len(result.errors) == 1
    assert "oci unavailable" in result.errors[0]


def test_one_instances_lease_failure_does_not_block_another(  # rg-007
) -> None:
    controller = GpuLifecycleController(idle_seconds=300)

    class HalfBrokenActuator:
        def __init__(self) -> None:
            self.stopped: list[str] = []

        def stop_instance(self, instance_id: str) -> None:
            if instance_id.endswith("bad"):
                raise RuntimeError("boom")
            self.stopped.append(instance_id)

    actuator = HalfBrokenActuator()
    result = run_reap_cycle(
        controller=controller,
        instances=[_running(7200, "ocid1.bad"), _running(7200, "ocid1.good")],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
    )

    assert actuator.stopped == ["ocid1.good"]
    assert result.lease_expired == [("STOP", "ocid1.good")]
    assert len(result.errors) == 1


# --- controller-owned running-since lease ----------------------------------


def test_oci_probe_never_derives_lease_age_from_time_created(monkeypatch) -> None:
    """An old OCI creation timestamp is not a run lease."""

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "data": {
                        "lifecycle-state": "RUNNING",
                        "time-created": "2020-01-01T00:00:00Z",
                    }
                }
            )
        )

    monkeypatch.setattr("infra.oci.gpu_lifecycle.reaper.subprocess.run", fake_run)

    assert fetch_instance_idle_seconds(instance_id="instance-a") == ("RUNNING", 0)


def test_first_running_observation_starts_lease_without_expiring_it(
    tmp_path: Path,
) -> None:
    """The bounded compensation begins at first observation."""
    path = tmp_path / "running-since.json"
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running(210_000_000, "instance-a")],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=_lease_store(path),
    )

    assert actuator.stopped == []
    assert result.lease_expired == []
    assert json.loads(path.read_text()) == {
        "instances": {
            "instance-a": {
                "boot_id": TEST_BOOT_ID,
                "monotonic_since": TEST_MONOTONIC,
                "since": "2026-09-03T12:00:00Z",
                "source": "first_observed",
            }
        },
        "schema_version": 2,
    }


@pytest.mark.parametrize("wall_jump", [timedelta(hours=-1), timedelta(days=365)])
def test_lease_age_uses_monotonic_clock_across_wall_clock_steps(
    tmp_path: Path,
    wall_jump: timedelta,
) -> None:
    clock = {"wall": NOW, "monotonic": 100.0}
    store = RunningSinceLeaseStore(
        path=tmp_path / "running-since.json",
        now=lambda: clock["wall"],
        monotonic=lambda: clock["monotonic"],
        boot_id="boot-a",
    )
    store.record_start("instance-a")

    clock["wall"] = NOW + wall_jump
    clock["monotonic"] = 160.0
    record = store.read("instance-a")

    assert record is not None
    assert store.age_seconds(record) == 60


def test_future_skewed_lease_without_valid_monotonic_origin_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "running-since.json"
    _write_lease(
        path,
        since="2027-09-03T12:00:00Z",
        with_monotonic_origin=False,
    )
    store = RunningSinceLeaseStore(
        path=path,
        now=lambda: NOW,
        monotonic=lambda: 100.0,
        boot_id="boot-a",
    )

    with pytest.raises(CorruptRunningSinceLeaseError, match="future-dated"):
        store.read("instance-a")


def test_old_start_actuator_lease_forces_stop_despite_busy_load(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    _write_lease(path, since="2026-09-03T10:59:59Z")
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running(0, "instance-a")],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=_lease_store(path),
    )

    assert actuator.stopped == ["instance-a"]
    assert result.lease_expired == [("STOP", "instance-a")]


def test_young_running_lease_does_not_stop_busy_instance(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    _write_lease(path, since="2026-09-03T11:59:00Z")
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running(99_999, "instance-a")],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=_lease_store(path),
    )

    assert actuator.stopped == []
    assert result.lease_expired == []


def test_explicit_idle_override_remains_authoritative_for_tests(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    _write_lease(path, since="2026-09-03T10:00:00Z")
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running(60, "instance-a")],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=_lease_store(path),
        use_recorded_lease_age=False,
    )

    assert actuator.stopped == []
    assert result.lease_expired == []


def test_stopped_observation_removes_running_since_record(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    _write_lease(path, since="2026-09-03T11:00:00Z")

    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[GpuInstance(instance_id="instance-a", state="STOPPED", idle_for_seconds=0)],
        load_source=BusyLoadSource(),
        actuator=RecordingActuator(),
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=_lease_store(path),
    )

    assert not path.exists()


def test_two_running_instance_leases_expire_independently(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    _write_lease(path, since="2026-09-03T10:00:00Z")
    payload = json.loads(path.read_text())
    payload["instances"]["instance-b"] = {
        "since": "2026-09-03T10:30:00Z",
        "source": "first_observed",
        "monotonic_since": TEST_MONOTONIC - 5_400,
        "boot_id": TEST_BOOT_ID,
    }
    path.write_text(json.dumps(payload))
    actuator = RecordingActuator()

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running(0, "instance-a"), _running(0, "instance-b")],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=_lease_store(path),
    )

    assert actuator.stopped == ["instance-a", "instance-b"]
    assert result.lease_expired == [("STOP", "instance-a"), ("STOP", "instance-b")]


def test_stopped_sibling_does_not_reset_running_instance_lease(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    current = {
        "now": datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        "monotonic": TEST_MONOTONIC,
    }
    store = RunningSinceLeaseStore(
        path=path,
        now=lambda: current["now"],
        monotonic=lambda: current["monotonic"],
        boot_id=TEST_BOOT_ID,
    )
    actuator = RecordingActuator()
    instances = [
        _running(0, "instance-a"),
        GpuInstance(instance_id="instance-b", state="STOPPED", idle_for_seconds=0),
    ]

    first = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=instances,
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=store,
    )
    first_bytes = path.read_bytes()
    current["now"] = datetime(2026, 9, 3, 12, 30, tzinfo=UTC)
    current["monotonic"] += 1_800
    second = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=instances,
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=store,
    )
    second_bytes = path.read_bytes()
    current["now"] = datetime(2026, 9, 3, 13, 0, 1, tzinfo=UTC)
    current["monotonic"] += 1_801
    third = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=instances,
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=store,
    )

    assert first.lease_expired == []
    assert second.lease_expired == []
    assert first_bytes == second_bytes
    assert actuator.stopped == ["instance-a"]
    assert third.lease_expired == [("STOP", "instance-a")]


def test_reap_lease_write_failure_disables_cap_loudly(monkeypatch, caplog) -> None:
    def fail_observe(self, instance_id: str):
        raise PermissionError(f"cannot write lease for {instance_id}")

    monkeypatch.setattr(RunningSinceLeaseStore, "observe_running", fail_observe)

    exit_code = main(
        [
            "--instance-id",
            "instance-a",
            "--instance-state",
            "RUNNING",
            "--queue-depth",
            "1",
            "--in-flight",
            "1",
            "--fence-delay-seconds",
            "0",
        ]
    )

    assert exit_code != 0
    assert "lease cap disabled" in caplog.text


def test_one_lease_store_failure_does_not_abort_healthy_sibling_reap(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    _write_lease(
        path,
        instance_id="instance-good",
        since="2026-09-03T10:00:00Z",
    )

    class OneBrokenLeaseStore(RunningSinceLeaseStore):
        def observe_running(self, instance_id: str):
            if instance_id == "instance-bad":
                raise PermissionError("injected unreadable lease")
            return super().observe_running(instance_id)

    actuator = RecordingActuator()
    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running(0, "instance-bad"), _running(0, "instance-good")],
        load_source=BusyLoadSource(),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=OneBrokenLeaseStore(
            path=path,
            now=lambda: NOW,
            monotonic=lambda: TEST_MONOTONIC,
            boot_id=TEST_BOOT_ID,
        ),
    )

    assert actuator.stopped == ["instance-good"]
    assert result.lease_expired == [("STOP", "instance-good")]
    assert len(result.errors) == 1
    assert "instance-bad" in result.errors[0]


def test_concurrent_lease_writers_preserve_both_instance_records(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    rendezvous = threading.Barrier(2)

    class CoordinatedLeaseStore(RunningSinceLeaseStore):
        def _read_instances_for_update(self) -> dict[str, dict[str, str]]:
            instances = super()._read_instances_for_update()
            with suppress(threading.BrokenBarrierError):
                rendezvous.wait(timeout=0.25)
            return instances

    def write(instance_id: str) -> None:
        CoordinatedLeaseStore(path=path, now=lambda: NOW, boot_id=TEST_BOOT_ID).record_start(instance_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, instance_id) for instance_id in ("instance-a", "instance-b")]
        for future in futures:
            future.result()

    assert set(json.loads(path.read_text())["instances"]) == {"instance-a", "instance-b"}


def test_running_since_lock_has_a_deadline(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.touch()
    store = RunningSinceLeaseStore(
        path=path,
        now=lambda: NOW,
        monotonic=lambda: TEST_MONOTONIC,
        boot_id=TEST_BOOT_ID,
        lock_timeout_seconds=0.0,
    )

    with lock_path.open("r") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        with pytest.raises(TimeoutError, match="waiting for lifecycle lock"):
            store.record_start("instance-a")


def test_start_lease_write_failure_disables_cap_loudly(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "infra.oci.gpu_lifecycle.reaper.OciCliStartActuator.start_instance",
        lambda self, instance_id: None,
    )

    def fail_record(self, instance_id: str):
        raise PermissionError(f"cannot write lease for {instance_id}")

    monkeypatch.setattr(RunningSinceLeaseStore, "record_start", fail_record)

    exit_code = main(
        [
            "--mode",
            "start",
            "--instance-id",
            "instance-a",
            "--instance-state",
            "STOPPED",
            "--queue-depth",
            "1",
            "--in-flight",
            "0",
        ]
    )

    assert exit_code != 0
    assert "lease cap disabled" in caplog.text


def test_start_cycle_records_lease_after_start_is_issued(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"

    class AssertingStartActuator:
        def start_instance(self, instance_id: str) -> None:
            assert instance_id == "instance-a"
            assert not path.exists()

    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[GpuInstance(instance_id="instance-a", state="STOPPED", idle_for_seconds=0)],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=AssertingStartActuator(),
        running_since_store=_lease_store(path),
    )

    assert result.actuated == [("START", "instance-a")]
    assert json.loads(path.read_text()) == {
        "instances": {
            "instance-a": {
                "boot_id": TEST_BOOT_ID,
                "monotonic_since": TEST_MONOTONIC,
                "since": "2026-09-03T12:00:00Z",
                "source": "start_actuator",
            }
        },
        "schema_version": 2,
    }


def test_start_dry_run_leaves_existing_lease_file_byte_identical(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    _write_lease(path, since="2026-09-03T10:00:00Z")
    before = path.read_bytes()

    exit_code = main(
        [
            "--mode",
            "start",
            "--instance-id",
            "instance-a",
            "--instance-state",
            "STOPPED",
            "--queue-depth",
            "1",
            "--in-flight",
            "0",
            "--running-since-path",
            str(path),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert path.read_bytes() == before


def test_reap_dry_run_neither_creates_nor_removes_lease_records(tmp_path: Path) -> None:
    new_path = tmp_path / "new-running-since.json"
    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[_running(0, "instance-a")],
        load_source=BusyLoadSource(),
        actuator=RecordingActuator(),
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=_lease_store(new_path),
        dry_run=True,
    )
    assert not new_path.exists()

    existing_path = tmp_path / "existing-running-since.json"
    _write_lease(existing_path, since="2026-09-03T10:00:00Z")
    before = existing_path.read_bytes()
    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=300),
        instances=[GpuInstance(instance_id="instance-a", state="STOPPED", idle_for_seconds=0)],
        load_source=BusyLoadSource(),
        actuator=RecordingActuator(),
        fence_delay_seconds=0,
        max_lease_seconds=3600,
        running_since_store=_lease_store(existing_path),
        dry_run=True,
    )
    assert existing_path.read_bytes() == before


# --- CLI --------------------------------------------------------------------


def test_cli_defaults_the_cap_on_rather_than_off(tmp_path: Path) -> None:
    """A backstop that ships disabled is not a backstop [RES-07]."""
    load_dir = tmp_path / "load"
    load_dir.mkdir()
    args = _build_parser().parse_args(
        ["--instance-id", "ocid1.x", "--load-dir", str(load_dir)]
    )
    assert args.max_lease_seconds == 3600
    assert args.load_dir == load_dir


def test_cli_accepts_an_explicit_cap(tmp_path: Path) -> None:
    load_dir = tmp_path / "load"
    load_dir.mkdir()
    args = _build_parser().parse_args(
        [
            "--instance-id",
            "ocid1.x",
            "--load-dir",
            str(load_dir),
            "--max-lease-seconds",
            "900",
        ]
    )
    assert args.max_lease_seconds == 900
    assert args.load_dir == load_dir


def test_cli_accepts_running_since_path_override(tmp_path: Path) -> None:
    path = tmp_path / "lease.json"
    load_dir = tmp_path / "load"
    load_dir.mkdir()
    args = _build_parser().parse_args(
        [
            "--instance-id",
            "instance-a",
            "--load-dir",
            str(load_dir),
            "--running-since-path",
            str(path),
        ]
    )
    assert args.running_since_path == path
    assert args.load_dir == load_dir


def test_cli_state_override_uses_running_since_without_oci_age_probe(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "lease.json"

    def fail_probe(**_kwargs):
        raise AssertionError("OCI age probe must not run")

    monkeypatch.setattr("infra.oci.gpu_lifecycle.reaper.fetch_instance_idle_seconds", fail_probe)

    exit_code = main(
        [
            "--instance-id",
            "instance-a",
            "--instance-state",
            "RUNNING",
            "--queue-depth",
            "1",
            "--in-flight",
            "1",
            "--fence-delay-seconds",
            "0",
            "--running-since-path",
            str(path),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert not path.exists()
