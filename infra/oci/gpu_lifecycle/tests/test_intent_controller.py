"""C1 controller semantics and C2 lifecycle snapshot fields."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController
from infra.oci.gpu_lifecycle.intent import (
    DeferredStopRecord,
    DeferredStopStore,
    EffectiveIntent,
    IntentAction,
    IntentAuthorityStore,
    IntentStatus,
)
from infra.oci.gpu_lifecycle.reaper import (
    RunningSinceLeaseStore,
    StaticJobLoadSource,
    run_reap_cycle,
    run_start_cycle,
)

NOW = datetime(2026, 9, 6, 22, 30, tzinfo=UTC)
BOOT_ID = "intent-test-boot"
VALID_NONCE = "123e4567-e89b-42d3-a456-426614174000"
SECOND_NONCE = "123e4567-e89b-42d3-a456-426614174001"


@pytest.fixture(autouse=True)
def _known_host_boot(monkeypatch):
    # These controller tests model a Linux boot even on a non-Linux test host.
    monkeypatch.setattr(IntentAuthorityStore, "_read_boot_id", staticmethod(lambda: BOOT_ID))


@dataclass
class RecordingActuator:
    started: list[str]
    stopped: list[str]

    def start_instance(self, instance_id: str) -> None:
        self.started.append(instance_id)

    def stop_instance(self, instance_id: str) -> None:
        self.stopped.append(instance_id)


def _intent(
    action: IntentAction,
    *,
    nonce: str = "nonce-1",
    sequence: int | None = None,
) -> EffectiveIntent:
    return EffectiveIntent(
        action=action,
        requested_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        nonce=nonce,
        sequence=sequence,
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


def _write_persisted_intent(
    root: Path,
    *,
    action: str,
    requested_at: datetime,
    expires_at: datetime,
    requested_by: str,
    sequence: int,
    nonce: str,
) -> Path:
    path = root / "prod" / "gpu-intent.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "action": action,
                "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
                "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
                "ttl_seconds": max(1, int((expires_at - requested_at).total_seconds())),
                "requested_by": requested_by,
                "nonce": nonce,
                "sequence": sequence,
            }
        ),
        encoding="utf-8",
    )
    return path


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


def test_malformed_authority_number_preserves_hard_lease_stop(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "durable"
    _write_persisted_intent(
        runtime_dir, action="start", requested_at=NOW,
        expires_at=NOW + timedelta(minutes=5), requested_by="operator",
        sequence=1, nonce=VALID_NONCE,
    )
    run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60), instances=[],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator([], []), intent_dir=runtime_dir,
        durable_state_dir=state_dir, now=NOW,
    )
    authority_path = state_dir / "intent-authority.json"
    state = json.loads(authority_path.read_text())
    state["intents"][VALID_NONCE]["monotonic_expires_at"] = 10 ** 400
    authority_path.write_text(json.dumps(state), encoding="utf-8")
    actuator = RecordingActuator([], [])
    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60), instances=[_running()],
        load_source=StaticJobLoadSource(queue_depth=5, in_flight=1),
        actuator=actuator, intent_dir=runtime_dir, durable_state_dir=state_dir,
        now=NOW, fence_delay_seconds=0, max_lease_seconds=1,
        use_recorded_lease_age=False,
    )
    assert result.intent.action is IntentAction.AUTO
    assert "authority unavailable" in result.intent.reason
    assert result.lease_expired == [("STOP", "ocid1.gpu")]
    assert actuator.stopped == ["ocid1.gpu"]


def test_rejected_equal_sequence_drops_deferred_stop(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "durable"
    original = _write_persisted_intent(
        runtime_dir, action="stop", requested_at=NOW,
        expires_at=NOW + timedelta(minutes=5), requested_by="operator",
        sequence=7, nonce=VALID_NONCE,
    )
    blocked = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60), instances=[_running(age=0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=1),
        actuator=RecordingActuator([], []), intent_dir=runtime_dir,
        durable_state_dir=state_dir, now=NOW, fence_delay_seconds=0,
    )
    assert blocked.intent_status is IntentStatus.BLOCKED_WORK_IN_FLIGHT
    conflicting = json.loads(original.read_text())
    conflicting.update(action="start", nonce=SECOND_NONCE, requested_by="other-environment")
    other_path = runtime_dir / "dev" / "gpu-intent.json"
    other_path.parent.mkdir()
    other_path.write_text(json.dumps(conflicting), encoding="utf-8")
    for seconds in (1, 2):
        actuator = RecordingActuator([], [])
        result = run_reap_cycle(
            controller=GpuLifecycleController(idle_seconds=60), instances=[_running(age=0)],
            load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
            actuator=actuator, intent_dir=runtime_dir, durable_state_dir=state_dir,
            now=NOW + timedelta(seconds=seconds), fence_delay_seconds=0,
        )
        assert result.intent.action is IntentAction.AUTO
        assert actuator.stopped == []
    assert not (state_dir / "deferred-stop.json").exists()
    records = [json.loads(line) for line in (state_dir / "decision-log.jsonl").read_text().splitlines()]
    assert any(row.get("event") == "dropped" and row.get("reason") == "rejected_by_authority_token"
               and row.get("nonce") == VALID_NONCE and row.get("requested_by") == "operator"
               for row in records)


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


def test_equal_sequence_with_a_new_nonce_supersedes_deferred_stop(tmp_path: Path) -> None:
    state_dir = tmp_path / "durable"
    stop_intent = _intent(IntentAction.STOP, nonce=VALID_NONCE, sequence=1)
    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running()],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingActuator([], []),
        fence_delay_seconds=0,
        durable_state_dir=state_dir,
        intent=stop_intent,
        now=NOW,
    )

    start_actuator = RecordingActuator([], [])
    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=start_actuator,
        fence_delay_seconds=0,
        durable_state_dir=state_dir,
        intent=_intent(IntentAction.START, nonce=SECOND_NONCE, sequence=1),
        now=NOW + timedelta(seconds=1),
    )

    assert result.intent.action is IntentAction.START
    assert result.decided == []
    assert result.actuated == []
    assert not (state_dir / "deferred-stop.json").exists()


def test_deferred_stop_rearm_failure_blocks_auto_actuation_and_is_audited(tmp_path: Path) -> None:
    state_dir = tmp_path / "durable"
    deferred_path = state_dir / "deferred-stop.json"
    deferred_store = DeferredStopStore(deferred_path)
    deferred_store.write(
        DeferredStopRecord(
            action=IntentAction.STOP,
            requested_at=NOW - timedelta(minutes=2),
            expires_at=NOW - timedelta(minutes=1),
            nonce=VALID_NONCE,
            requested_by="operator",
            ttl_seconds=30,
            sequence=7,
            deferred_until=NOW - timedelta(seconds=1),
            deferred_reason="STOP deferred while work is in flight",
        )
    )

    class FailingRearmStore(DeferredStopStore):
        def write(self, record: DeferredStopRecord) -> None:
            raise OSError("simulated deferred-stop rearm interruption")

    actuator = RecordingActuator([], [])
    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=90)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        deferred_stop_store=FailingRearmStore(deferred_path),
        intent=None,
        now=NOW,
    )

    assert result.intent.action is IntentAction.STOP
    assert result.intent_status is IntentStatus.BLOCKED_WORK_IN_FLIGHT
    assert result.actuated == []
    assert result.errors
    assert "rearm_failed" in result.errors[0]
    assert actuator.stopped == []
    records = [json.loads(line) for line in (state_dir / "decision-log.jsonl").read_text().splitlines()]
    assert any(
        record.get("event") == "dropped"
        and record.get("reason") == "rearm_failed"
        and record.get("nonce") == VALID_NONCE
        and record.get("sequence") == 7
        for record in records
    )


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


def test_reaper_call_site_uses_sequence_before_wall_clock(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "durable"
    _write_persisted_intent(
        runtime_dir,
        action="start",
        requested_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(minutes=5),
        requested_by="demo-operator",
        sequence=2,
        nonce=VALID_NONCE,
    )
    low_sequence_path = runtime_dir / "staging" / "gpu-intent.json"
    low_sequence_path.parent.mkdir(parents=True)
    low_sequence_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "action": "stop",
                "requested_at": NOW.isoformat().replace("+00:00", "Z"),
                "expires_at": (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                "ttl_seconds": 300,
                "requested_by": "newer-clock",
                "nonce": SECOND_NONCE,
                "sequence": 1,
            }
        ),
        encoding="utf-8",
    )
    actuator = RecordingActuator([], [])

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW,
    )

    assert result.intent.action is IntentAction.START
    assert result.intent.sequence == 2
    assert result.intent.requested_by == "demo-operator"
    assert result.decided == []
    assert actuator.stopped == []


def test_reaper_call_site_does_not_rearm_expired_start_after_clock_rollback(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "durable"
    _write_persisted_intent(
        runtime_dir,
        action="start",
        requested_at=NOW - timedelta(seconds=30),
        expires_at=NOW + timedelta(seconds=1),
        requested_by="demo-operator",
        sequence=1,
        nonce=VALID_NONCE,
    )
    run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator([], []),
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW,
    )

    first_actuator = RecordingActuator([], [])
    first = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=90)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=first_actuator,
        fence_delay_seconds=0,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW + timedelta(seconds=2),
    )
    rollback_actuator = RecordingActuator([], [])
    after_rollback = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=90)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=rollback_actuator,
        fence_delay_seconds=0,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW + timedelta(seconds=1),
    )

    assert first.intent.action is IntentAction.AUTO
    assert first.intent_status is IntentStatus.EXPIRED
    assert first_actuator.stopped == ["ocid1.gpu"]
    assert after_rollback.intent.action is IntentAction.AUTO
    assert after_rollback.intent_status is IntentStatus.EXPIRED
    assert rollback_actuator.stopped == ["ocid1.gpu"]


def test_reaper_call_site_rejects_start_below_persisted_authority_high_water(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "durable"
    _write_persisted_intent(
        runtime_dir,
        action="stop",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        requested_by="operator",
        sequence=5,
        nonce=VALID_NONCE,
    )
    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=90)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator([], []),
        fence_delay_seconds=0,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW,
    )
    durable_path = state_dir / "intents" / "prod" / "gpu-intent.json"
    durable_path.unlink()
    _write_persisted_intent(
        runtime_dir,
        action="start",
        requested_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=6),
        requested_by="stale-operator",
        sequence=4,
        nonce=SECOND_NONCE,
    )

    actuator = RecordingActuator([], [])
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW + timedelta(minutes=1),
    )

    assert result.intent.action is IntentAction.AUTO
    assert result.intent_status is IntentStatus.EXPIRED
    assert result.actuated == []
    assert actuator.started == []


def test_runtime_intent_survives_tmpfs_clear_via_durable_reload(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "durable"
    intent_path = _write_persisted_intent(
        runtime_dir,
        action="start",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        requested_by="demo-operator",
        sequence=1,
        nonce=VALID_NONCE,
    )
    run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator([], []),
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW,
    )
    intent_path.unlink()
    intent_path.parent.rmdir()

    actuator = RecordingActuator([], [])
    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW + timedelta(seconds=1),
    )

    assert result.intent.action is IntentAction.START
    assert result.intent.requested_by == "demo-operator"
    assert result.intent.sequence == 1
    assert result.decided == []
    assert actuator.stopped == []


def test_deferred_stop_is_rearmed_after_original_ttl_and_honoured(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "durable"
    _write_persisted_intent(
        runtime_dir,
        action="stop",
        requested_at=NOW - timedelta(seconds=10),
        expires_at=NOW + timedelta(seconds=1),
        requested_by="operator",
        sequence=1,
        nonce=VALID_NONCE,
    )
    blocked_actuator = RecordingActuator([], [])
    blocked = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=1),
        actuator=blocked_actuator,
        fence_delay_seconds=0,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW,
    )

    drained_actuator = RecordingActuator([], [])
    drained = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=drained_actuator,
        fence_delay_seconds=0,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW + timedelta(seconds=120),
    )

    assert blocked.intent_status is IntentStatus.BLOCKED_WORK_IN_FLIGHT
    assert blocked.intent.deferred_until is not None
    assert blocked.intent.deferred_until > blocked.intent.expires_at - timedelta(seconds=1)
    assert drained.intent.action is IntentAction.STOP
    assert drained.intent_status is IntentStatus.HONOURED
    assert drained.actuated == [("STOP", "ocid1.gpu")]
    assert drained_actuator.stopped == ["ocid1.gpu"]
    assert not (state_dir / "deferred-stop.json").exists()


def test_decision_log_reconstructs_start_and_idle_stop_cycle(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "durable"
    _write_persisted_intent(
        runtime_dir,
        action="start",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        requested_by="demo-operator",
        sequence=1,
        nonce=VALID_NONCE,
    )
    start_actuator = RecordingActuator([], [])
    start = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_stopped()],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=start_actuator,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW,
    )
    _write_persisted_intent(
        runtime_dir,
        action="stop",
        requested_at=NOW + timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=5),
        requested_by="scheduler",
        sequence=2,
        nonce=SECOND_NONCE,
    )
    stop_actuator = RecordingActuator([], [])
    stop = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=stop_actuator,
        fence_delay_seconds=0,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW + timedelta(seconds=2),
    )

    lines = (state_dir / "decision-log.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert len(records) == 2
    assert records[0]["mode"] == "start"
    assert records[0]["requested_by"] == "demo-operator"
    assert records[0]["sequence"] == 1
    assert records[0]["effective_intent"] == "start"
    assert records[0]["intent_status"] == "honoured"
    assert records[0]["actuation_outcome"] == "honoured"
    assert records[1]["mode"] == "reap"
    assert records[1]["requested_by"] == "scheduler"
    assert records[1]["sequence"] == 2
    assert records[1]["effective_intent"] == "stop"
    assert records[1]["intent_status"] == "honoured"
    assert records[1]["actuation_outcome"] == "honoured"
    assert start.actuated == [("START", "ocid1.gpu")]
    assert stop.actuated == [("STOP", "ocid1.gpu")]


def test_expired_supersession_does_not_resurrect_a_deferred_stop(tmp_path: Path) -> None:
    """R2-01: a newer intent fences a deferred STOP even after it expires.

    The superseding publication is only ever observed past its own TTL, so the
    live effective intent carries no sequence.  The durable high-water mark is
    the only surviving evidence of the supersession.
    """
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "durable"
    _write_persisted_intent(
        runtime_dir,
        action="stop",
        requested_at=NOW - timedelta(seconds=10),
        expires_at=NOW + timedelta(seconds=1),
        requested_by="operator",
        sequence=1,
        nonce=VALID_NONCE,
    )
    blocked = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=1),
        actuator=RecordingActuator([], []),
        fence_delay_seconds=0,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW,
    )
    assert blocked.intent_status is IntentStatus.BLOCKED_WORK_IN_FLIGHT
    assert (state_dir / "deferred-stop.json").exists()

    # The operator countermands the STOP, but the reaper does not run again
    # until after the replacement's own TTL has elapsed.
    _write_persisted_intent(
        runtime_dir,
        action="start",
        requested_at=NOW + timedelta(seconds=10),
        expires_at=NOW + timedelta(seconds=40),
        requested_by="operator",
        sequence=2,
        nonce=SECOND_NONCE,
    )

    drained_actuator = RecordingActuator([], [])
    drained = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[_running(age=0)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=drained_actuator,
        fence_delay_seconds=0,
        intent_dir=runtime_dir,
        durable_state_dir=state_dir,
        now=NOW + timedelta(seconds=120),
    )

    assert drained.intent.action is not IntentAction.STOP
    assert drained.actuated == []
    assert drained_actuator.stopped == []
    assert not (state_dir / "deferred-stop.json").exists()
