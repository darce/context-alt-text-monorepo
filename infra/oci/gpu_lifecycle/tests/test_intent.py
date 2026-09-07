"""C1 operator-intent aggregate reader tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController
from infra.oci.gpu_lifecycle.intent import (
    IntentAuthorityStore,
    IntentAction,
    IntentStatus,
    MIN_INTENT_SEQUENCE,
    MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS,
    read_effective_intent,
)
from infra.oci.gpu_lifecycle.reaper import StaticJobLoadSource, run_reap_cycle

NOW = datetime(2026, 9, 6, 22, 30, tzinfo=UTC)
VALID_NONCE = "123e4567-e89b-42d3-a456-426614174000"
NEW_NONCE = "123e4567-e89b-42d3-a456-426614174001"


def _write_payload(root: Path, environment: str, payload: dict[str, object]) -> Path:
    path = root / environment / "gpu-intent.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_intent(
    root: Path,
    environment: str,
    *,
    action: str = "start",
    requested_at: datetime = NOW - timedelta(minutes=5),
    expires_at: datetime = NOW + timedelta(minutes=5),
    nonce: str = VALID_NONCE,
    sequence: int = 1,
    **extra: object,
) -> Path:
    payload: dict[str, object] = {
        "schema_version": 1,
        "action": action,
        "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "ttl_seconds": 300,
        "requested_by": "test",
        "nonce": nonce,
        "sequence": sequence,
    }
    payload.update(extra)
    return _write_payload(root, environment, payload)


def _assert_malformed(
    effective: object,
    caplog: pytest.LogCaptureFixture,
    path: Path,
    field: str,
) -> None:
    assert effective.action is IntentAction.AUTO
    assert effective.status is IntentStatus.NONE
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(path) in warnings[0].message
    assert field in warnings[0].message


def test_reads_a_valid_intent_file_from_each_environment(tmp_path: Path) -> None:
    path = _write_intent(tmp_path, "prod", action="start", nonce=VALID_NONCE)

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.START
    assert effective.nonce == VALID_NONCE
    assert effective.source == path
    assert effective.expires_at == NOW + timedelta(minutes=5)


def test_newest_unexpired_intent_wins(tmp_path: Path) -> None:
    _write_intent(
        tmp_path,
        "dev",
        action="start",
        requested_at=NOW - timedelta(minutes=10),
        nonce=VALID_NONCE,
    )
    _write_intent(
        tmp_path,
        "prod",
        action="stop",
        requested_at=NOW - timedelta(minutes=1),
        nonce=NEW_NONCE,
    )

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.STOP
    assert effective.nonce == NEW_NONCE


def test_highest_sequence_wins_over_newer_wall_clock_timestamp(tmp_path: Path) -> None:
    _write_intent(
        tmp_path,
        "dev",
        action="stop",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        sequence=1,
        nonce=VALID_NONCE,
    )
    _write_intent(
        tmp_path,
        "prod",
        action="start",
        requested_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(minutes=5),
        sequence=2,
        nonce=NEW_NONCE,
    )

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.START
    assert effective.sequence == 2
    assert effective.nonce == NEW_NONCE


def test_missing_sequence_is_malformed_and_fails_closed(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = _write_intent(tmp_path, "prod")
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["sequence"]
    _write_payload(tmp_path, "prod", payload)

    effective = read_effective_intent(tmp_path, NOW)

    _assert_malformed(effective, caplog, path, "sequence")


@pytest.mark.parametrize("sequence", [0, -1, True, False])
def test_non_positive_or_boolean_sequence_is_malformed(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    sequence: object,
) -> None:
    path = _write_intent(tmp_path, "prod", sequence=1)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sequence"] = sequence
    _write_payload(tmp_path, "prod", payload)

    effective = read_effective_intent(tmp_path, NOW)

    _assert_malformed(effective, caplog, path, "sequence")
    assert f">= {MIN_INTENT_SEQUENCE}" in caplog.text


def test_intent_authority_does_not_rearm_an_expired_sequence_after_ntp_rollback(
    tmp_path: Path,
) -> None:
    monotonic_values = iter((100.0, 161.0, 162.0))
    authority = IntentAuthorityStore(
        tmp_path / "intent-authority.json",
        monotonic=lambda: next(monotonic_values),
        boot_id="boot-a",
    )
    _write_intent(
        tmp_path,
        "prod",
        requested_at=NOW,
        expires_at=NOW + timedelta(seconds=60),
        sequence=7,
    )

    first = read_effective_intent(tmp_path, NOW, authority_store=authority)
    expired = read_effective_intent(
        tmp_path,
        NOW - timedelta(seconds=1),
        authority_store=authority,
    )
    after_rollback = read_effective_intent(
        tmp_path,
        NOW - timedelta(seconds=30),
        authority_store=authority,
    )

    assert first.action is IntentAction.START
    assert expired.action is IntentAction.AUTO
    assert expired.status is IntentStatus.EXPIRED
    assert after_rollback.action is IntentAction.AUTO
    assert after_rollback.status is IntentStatus.EXPIRED


def test_equal_requested_at_tie_resolves_to_stop(tmp_path: Path) -> None:
    _write_intent(tmp_path, "dev", action="start", requested_at=NOW, nonce=VALID_NONCE)
    _write_intent(tmp_path, "staging", action="stop", requested_at=NOW, nonce=NEW_NONCE)

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.STOP
    assert effective.nonce == NEW_NONCE


def test_expired_intent_is_auto_and_logs_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = _write_intent(
        tmp_path,
        "prod",
        expires_at=NOW - timedelta(seconds=1),
    )

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.AUTO
    assert effective.status is IntentStatus.EXPIRED
    assert str(path) in caplog.text
    assert "expired" in caplog.text


@pytest.mark.parametrize(
    "contents",
    [
        "{not-json",
        json.dumps({"schema_version": 2}),
        json.dumps({"schema_version": 1, "action": "sideways"}),
        json.dumps({"schema_version": 1, "action": "start", "requested_at": "2026-09-06T22:00:00Z"}),
    ],
)
def test_malformed_intent_is_auto_and_warns(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    contents: str,
) -> None:
    path = tmp_path / "prod" / "gpu-intent.json"
    path.parent.mkdir(parents=True)
    path.write_text(contents, encoding="utf-8")

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.AUTO
    assert effective.status is IntentStatus.NONE
    assert str(path) in caplog.text
    assert "operator intent invalid file" in caplog.text


def test_missing_ttl_seconds_is_auto_and_names_the_field(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = _write_intent(tmp_path, "prod")
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["ttl_seconds"]
    _write_payload(tmp_path, "prod", payload)

    effective = read_effective_intent(tmp_path, NOW)

    _assert_malformed(effective, caplog, path, "ttl_seconds")


def test_bad_nonce_is_auto_and_names_the_field(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = _write_intent(tmp_path, "prod", nonce="not-a-uuid")

    effective = read_effective_intent(tmp_path, NOW)

    _assert_malformed(effective, caplog, path, "nonce")


def test_missing_requested_by_is_auto_and_names_the_field(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = _write_intent(tmp_path, "prod")
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["requested_by"]
    _write_payload(tmp_path, "prod", payload)

    effective = read_effective_intent(tmp_path, NOW)

    _assert_malformed(effective, caplog, path, "requested_by")


def test_bad_action_is_auto_and_names_the_field(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = _write_intent(tmp_path, "prod", action="restart")

    effective = read_effective_intent(tmp_path, NOW)

    _assert_malformed(effective, caplog, path, "action")


def test_wrong_schema_version_is_auto_and_names_the_field(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = _write_intent(tmp_path, "prod", schema_version=2)

    effective = read_effective_intent(tmp_path, NOW)

    _assert_malformed(effective, caplog, path, "schema_version")


def test_overlong_expiry_is_clamped_to_two_hours(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = _write_intent(
        tmp_path,
        "prod",
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=10),
    )

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.START
    assert effective.expires_at == NOW + timedelta(hours=2)
    assert str(path) in caplog.text
    assert "clamped" in caplog.text


def test_far_future_requested_at_is_ignored_so_it_cannot_pin_newer_intents(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_intent(
        tmp_path,
        "skewed",
        action="start",
        requested_at=NOW + timedelta(days=7),
        expires_at=NOW + timedelta(days=7, minutes=30),
        nonce=VALID_NONCE,
    )
    _write_intent(
        tmp_path,
        "prod",
        action="stop",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        nonce=NEW_NONCE,
    )

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.STOP
    assert effective.nonce == NEW_NONCE
    assert "future" in caplog.text
    assert effective.reason is None


def test_requested_at_at_skew_tolerance_is_still_honoured(tmp_path: Path) -> None:
    requested_at = NOW + timedelta(seconds=MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS)
    _write_intent(
        tmp_path,
        "prod",
        requested_at=requested_at,
        expires_at=requested_at + timedelta(minutes=5),
    )

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.START
    assert effective.requested_at == requested_at
    assert effective.reason == "requested_at within clock-skew tolerance"


def test_near_future_expiry_clamp_is_anchored_to_read_time(tmp_path: Path) -> None:
    requested_at = NOW + timedelta(seconds=1)
    _write_intent(
        tmp_path,
        "prod",
        requested_at=requested_at,
        expires_at=requested_at + timedelta(hours=10),
    )

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.START
    assert effective.expires_at == NOW + timedelta(hours=2)


def test_missing_or_disabled_intent_is_silent_auto(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert read_effective_intent(None, NOW).action is IntentAction.AUTO

    effective = read_effective_intent(tmp_path / "missing", NOW)

    assert effective.action is IntentAction.AUTO
    assert effective.status is IntentStatus.NONE
    assert "gpu-intent.json" in caplog.text


def test_reaper_call_site_uses_sequence_precedence(tmp_path: Path) -> None:
    _write_intent(
        tmp_path,
        "dev",
        action="start",
        requested_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(minutes=5),
        nonce=VALID_NONCE,
        sequence=2,
    )
    _write_intent(
        tmp_path,
        "prod",
        action="stop",
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        nonce=NEW_NONCE,
        sequence=1,
    )

    class Recorder:
        stopped: list[str]

        def __init__(self) -> None:
            self.stopped = []

        def stop_instance(self, instance_id: str) -> None:
            self.stopped.append(instance_id)

    actuator = Recorder()
    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance(instance_id="ocid1.gpu", state="RUNNING", idle_for_seconds=90)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        intent_dir=tmp_path,
        durable_state_dir=tmp_path / "durable",
        now=NOW,
    )

    assert result.intent.action is IntentAction.START
    assert result.intent.sequence == 2
    assert result.decided == []
    assert actuator.stopped == []
