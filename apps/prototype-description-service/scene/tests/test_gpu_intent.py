"""C1 operator intent persistence tests."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scene.application.gpu_intent import (
    DEFAULT_INTENT_TTL_SECONDS,
    IntentAction,
    read_gpu_intent,
    resolve_gpu_intent_path,
    write_gpu_intent,
)

NOW = datetime(2026, 9, 6, 22, 10, tzinfo=UTC)


def test_write_read_round_trip_clamps_ttl_and_publishes_atomic_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "gpu-intent.json"

    written = write_gpu_intent(
        target,
        action=IntentAction.START,
        ttl_seconds=1,
        requested_by="operator@example.test",
        now=NOW,
    )

    assert written.schema_version == 1
    assert written.action is IntentAction.START
    assert written.ttl_seconds == 60
    assert written.requested_at == NOW
    assert written.expires_at == NOW + timedelta(seconds=60)
    assert target.is_file()
    assert target.stat().st_mode & 0o777 == 0o660
    assert target.with_name(f"{target.name}.lock").stat().st_mode & 0o777 == 0o660
    assert not list(target.parent.glob("*.tmp"))

    loaded = read_gpu_intent(target)
    assert loaded == written
    assert json.loads(target.read_text(encoding="utf-8"))["nonce"] == written.nonce


@pytest.mark.parametrize(
    ("ttl_seconds", "expected"),
    [
        (None, DEFAULT_INTENT_TTL_SECONDS),
        (1, 60),
        (7201, 7200),
    ],
)
def test_write_gpu_intent_clamps_ttl(
    tmp_path: Path,
    ttl_seconds: int | None,
    expected: int,
) -> None:
    intent = write_gpu_intent(
        tmp_path / f"{expected}.json",
        action="auto",
        ttl_seconds=ttl_seconds,
        requested_by="operator",
        now=NOW,
    )

    assert intent.ttl_seconds == expected
    assert intent.expires_at == NOW + timedelta(seconds=expected)


def test_malformed_intent_returns_none_and_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    target = tmp_path / "gpu-intent.json"
    target.write_text(json.dumps({"schema_version": 1, "action": "invalid"}), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="scene.application.gpu_intent"):
        assert read_gpu_intent(target) is None

    assert any("malformed GPU intent" in record.getMessage() for record in caplog.records)


def test_intent_path_defaults_to_load_path_sibling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    load_path = tmp_path / "describe-load.json"
    monkeypatch.setenv("ACX_DESCRIBE_LOAD_PATH", str(load_path))
    monkeypatch.delenv("ACX_GPU_INTENT_PATH", raising=False)

    assert resolve_gpu_intent_path() == str(tmp_path / "gpu-intent.json")


def test_intent_path_honours_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "configured" / "operator.json"
    monkeypatch.setenv("ACX_GPU_INTENT_PATH", str(target))

    assert resolve_gpu_intent_path() == str(target)
