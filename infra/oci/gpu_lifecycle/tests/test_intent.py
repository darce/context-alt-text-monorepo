"""C1 operator-intent aggregate reader tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from infra.oci.gpu_lifecycle.intent import (
    IntentAction,
    IntentStatus,
    read_effective_intent,
)

NOW = datetime(2026, 9, 6, 22, 30, tzinfo=UTC)


def _write_intent(
    root: Path,
    environment: str,
    *,
    action: str = "start",
    requested_at: datetime = NOW - timedelta(minutes=5),
    expires_at: datetime = NOW + timedelta(minutes=5),
    nonce: str = "nonce-1",
    **extra: object,
) -> Path:
    path = root / environment / "gpu-intent.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "schema_version": 1,
        "action": action,
        "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "ttl_seconds": 300,
        "requested_by": "test",
        "nonce": nonce,
    }
    payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_reads_a_valid_intent_file_from_each_environment(tmp_path: Path) -> None:
    path = _write_intent(tmp_path, "prod", action="start", nonce="abc")

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.START
    assert effective.nonce == "abc"
    assert effective.source == path
    assert effective.expires_at == NOW + timedelta(minutes=5)


def test_newest_unexpired_intent_wins(tmp_path: Path) -> None:
    _write_intent(
        tmp_path,
        "dev",
        action="start",
        requested_at=NOW - timedelta(minutes=10),
        nonce="old",
    )
    _write_intent(
        tmp_path,
        "prod",
        action="stop",
        requested_at=NOW - timedelta(minutes=1),
        nonce="new",
    )

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.STOP
    assert effective.nonce == "new"


def test_equal_requested_at_tie_resolves_to_stop(tmp_path: Path) -> None:
    _write_intent(tmp_path, "dev", action="start", requested_at=NOW, nonce="start")
    _write_intent(tmp_path, "staging", action="stop", requested_at=NOW, nonce="stop")

    effective = read_effective_intent(tmp_path, NOW)

    assert effective.action is IntentAction.STOP
    assert effective.nonce == "stop"


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


def test_missing_or_disabled_intent_is_silent_auto(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert read_effective_intent(None, NOW).action is IntentAction.AUTO

    effective = read_effective_intent(tmp_path / "missing", NOW)

    assert effective.action is IntentAction.AUTO
    assert effective.status is IntentStatus.NONE
    assert "gpu-intent.json" in caplog.text
