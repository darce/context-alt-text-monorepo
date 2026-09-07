"""C1 controller semantics and C2 lifecycle snapshot fields."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController
from infra.oci.gpu_lifecycle.intent import EffectiveIntent, IntentAction, IntentStatus
from infra.oci.gpu_lifecycle.reaper import (
    RunningSinceLeaseStore,
    StaticJobLoadSource,
    run_reap_cycle,
    run_start_cycle,
)

NOW = datetime(2026, 9, 6, 22, 30, tzinfo=UTC)
BOOT_ID = "intent-test-boot"


@dataclass
class RecordingActuator:
    started: list[str]
    stopped: list[str]

    def start_instance(self, instance_id: str) -> None:
        self.started.append(instance_id)

    def stop_instance(self, instance_id: str) -> None:
        self.stopped.append(instance_id)


def _intent(action: IntentAction, *, nonce: str = "nonce-1") -> EffectiveIntent:
    return EffectiveIntent(
        action=action,
        requested_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        nonce=nonce,
    )


def _stopped() -> GpuInstance:
    return GpuInstance(instance_id="ocid1.gpu", state="STOPPED", idle_for_seconds=0)


def _running(age: int = 90) -> GpuInstance:
    return GpuInstance(instance_id="ocid1.gpu", state="RUNNING", idle_for_seconds=age)


def _store(path: Path) -> RunningSinceLeaseStore:
    return RunningSinceLeaseStore(
        path=path,
        now=lambda: NOW,
        monotonic=lambda: 1000.0,
        boot_id=BOOT_ID,
    )


def test_auto_preserves_work_start_and_idle_stop() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    start_actuator = RecordingActuator([], [])

    start_result = run_start_cycle(
        controller=controller,
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=start_actuator,
        intent=EffectiveIntent(),
    )

    assert start_result.decided == [("START", "ocid1.gpu")]
    assert start_actuator.started == ["ocid1.gpu"]

    reap_actuator = RecordingActuator([], [])
    reap_result = run_reap_cycle(
        controller=controller,
        instances=[_running()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=reap_actuator,
        fence_delay_seconds=0,
        intent=EffectiveIntent(),
    )

    assert reap_result.decided == [("STOP", "ocid1.gpu")]
    assert reap_actuator.stopped == ["ocid1.gpu"]


def test_start_intent_allows_start_without_work_and_suppresses_idle_stop(tmp_path: Path) -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    start_actuator = RecordingActuator([], [])
    store = _store(tmp_path / "running-since.json")

    start_result = run_start_cycle(
        controller=controller,
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=start_actuator,
        running_since_store=store,
        intent=_intent(IntentAction.START),
        now=NOW,
    )
    reap_actuator = RecordingActuator([], [])
    reap_result = run_reap_cycle(
        controller=controller,
        instances=[_running()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=reap_actuator,
        fence_delay_seconds=0,
        running_since_store=store,
        intent=_intent(IntentAction.START),
        now=NOW,
    )

    assert start_result.actuated == [("START", "ocid1.gpu")]
    assert start_result.intent_status is IntentStatus.HONOURED
    assert reap_result.decided == []
    assert reap_actuator.stopped == []


def test_stop_intent_suppresses_start_even_when_work_waits(tmp_path: Path) -> None:
    actuator = RecordingActuator([], [])

    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
        running_since_store=_store(tmp_path / "running-since.json"),
        intent=_intent(IntentAction.STOP),
    )

    assert result.decided == []
    assert result.actuated == []
    assert actuator.started == []
    assert result.intent_status is IntentStatus.PENDING


def test_stop_intent_stops_idle_instance_and_reports_operator_reason(tmp_path: Path) -> None:
    actuator = RecordingActuator([], [])
    path = tmp_path / "gpu-state.json"

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        gpu_state_path=path,
        running_since_store=_store(tmp_path / "running-since.json"),
        intent=_intent(IntentAction.STOP),
    )

    assert result.actuated == [("STOP", "ocid1.gpu")]
    assert result.intent_status is IntentStatus.HONOURED
    assert json.loads(path.read_text())["last_transition_reason"] == "operator"


def test_lease_cap_wins_over_start_intent(tmp_path: Path) -> None:
    store = _store(tmp_path / "running-since.json")
    store.record_start("ocid1.gpu")
    actuator = RecordingActuator([], [])

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running()],
        load_source=StaticJobLoadSource(queue_depth=5, in_flight=1),
        actuator=actuator,
        fence_delay_seconds=0,
        max_lease_seconds=1,
        running_since_store=store,
        use_recorded_lease_age=False,
        intent=_intent(IntentAction.START),
    )

    assert result.lease_expired == [("STOP", "ocid1.gpu")]
    assert actuator.stopped == ["ocid1.gpu"]
    assert result.last_transition_reason.value == "lease_cap"


def test_stop_with_work_is_deferred_then_re_evaluated(tmp_path: Path) -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    intent = _intent(IntentAction.STOP)
    actuator = RecordingActuator([], [])
    instances = [_running()]

    blocked = run_reap_cycle(
        controller=controller,
        instances=instances,
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        intent=intent,
    )
    drained = run_reap_cycle(
        controller=controller,
        instances=instances,
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        intent=intent,
    )

    assert blocked.intent_status is IntentStatus.BLOCKED_WORK_IN_FLIGHT
    assert blocked.actuated == []
    assert drained.actuated == [("STOP", "ocid1.gpu")]
    assert actuator.stopped == ["ocid1.gpu"]


def test_start_nonce_is_honoured_once_across_cycles(tmp_path: Path) -> None:
    store = _store(tmp_path / "running-since.json")
    intent = _intent(IntentAction.START, nonce="once")
    controller = GpuLifecycleController(idle_seconds=60)
    actuator = RecordingActuator([], [])

    first = run_start_cycle(
        controller=controller,
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        running_since_store=store,
        intent=intent,
    )
    second = run_start_cycle(
        controller=controller,
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        running_since_store=store,
        intent=intent,
    )

    assert first.actuated == [("START", "ocid1.gpu")]
    assert second.decided == []
    assert second.intent_status is IntentStatus.HONOURED
    assert actuator.started == ["ocid1.gpu"]
    assert json.loads(store.path.read_text())["instances"]["ocid1.gpu"]["honoured_nonce"] == "once"


def test_honoured_start_nonce_does_not_block_work_driven_start(tmp_path: Path) -> None:
    store = _store(tmp_path / "running-since.json")
    intent = _intent(IntentAction.START, nonce="once")
    controller = GpuLifecycleController(idle_seconds=60)
    actuator = RecordingActuator([], [])

    first = run_start_cycle(
        controller=controller,
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        running_since_store=store,
        intent=intent,
    )
    second = run_start_cycle(
        controller=controller,
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
        running_since_store=store,
        intent=intent,
    )

    assert first.actuated == [("START", "ocid1.gpu")]
    assert second.decided == [("START", "ocid1.gpu")]
    assert second.actuated == [("START", "ocid1.gpu")]
    assert actuator.started == ["ocid1.gpu", "ocid1.gpu"]


def test_honoured_start_nonce_survives_lease_removal_and_reboot(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    store = _store(path)
    store.record_start("ocid1.gpu", honoured_nonce="once")
    store.remove("ocid1.gpu")
    restarted_store = RunningSinceLeaseStore(
        path=path,
        now=lambda: NOW,
        monotonic=lambda: 1000.0,
        boot_id="new-boot",
    )
    actuator = RecordingActuator([], [])

    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        running_since_store=restarted_store,
        intent=_intent(IntentAction.START, nonce="once"),
    )

    assert result.decided == []
    assert result.actuated == []
    assert result.intent_status is IntentStatus.HONOURED
    assert actuator.started == []
    assert restarted_store.honoured_nonces_path.exists()


def test_corrupt_honoured_nonce_marker_is_treated_as_already_honoured(tmp_path: Path) -> None:
    store = _store(tmp_path / "running-since.json")
    store.honoured_nonces_path.write_text("{not-json", encoding="utf-8")
    actuator = RecordingActuator([], [])

    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        running_since_store=store,
        intent=_intent(IntentAction.START, nonce="once"),
    )

    assert result.decided == []
    assert result.actuated == []
    assert result.intent_status is IntentStatus.HONOURED
    assert actuator.started == []


def test_reap_does_not_honour_start_intent_without_actuation(tmp_path: Path) -> None:
    path = tmp_path / "running-since.json"
    store = _store(path)
    store.record_start("ocid1.gpu")
    actuator = RecordingActuator([], [])

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        gpu_state_path=tmp_path / "gpu-state.json",
        running_since_store=store,
        intent=_intent(IntentAction.START, nonce="fresh"),
    )

    assert result.decided == []
    assert result.actuated == []
    assert result.intent_status is IntentStatus.PENDING
    assert result.honoured_nonce is None
    assert not store.honoured_nonces_path.exists()


def test_start_intent_does_not_override_boot_failure_fallback() -> None:
    class FailingActuator(RecordingActuator):
        def start_instance(self, instance_id: str) -> None:
            raise RuntimeError("start failed")

    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=FailingActuator([], []),
        intent=_intent(IntentAction.START),
    )

    assert result.fallbacks[0].reason == "start_failed"
    assert result.last_transition_reason.value == "start_failed"


def test_legacy_cycle_snapshot_has_c2_auto_defaults(tmp_path: Path) -> None:
    path = tmp_path / "gpu-state.json"

    run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator([], []),
        gpu_state_path=path,
    )

    payload = json.loads(path.read_text())
    assert payload["intent"] == "auto"
    assert payload["intent_status"] == "none"
    assert payload["intent_expires_at"] is None
    assert payload["last_transition_reason"] == "unknown"
