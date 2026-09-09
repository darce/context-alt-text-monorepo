"""C1 operator intent persistence tests."""

from __future__ import annotations

import fcntl
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scene.application.gpu_intent import (
    DEFAULT_INTENT_TTL_SECONDS,
    IntentAction,
    read_gpu_intent,
    resolve_gpu_intent_path,
    resolve_gpu_intent_durable_path,
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
    assert written.sequence == 1
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
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["nonce"] == written.nonce
    assert payload["sequence"] == written.sequence


def test_sequence_is_monotonic_and_lifecycle_reader_accepts_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_target = tmp_path / "runtime" / "prod" / "gpu-intent.json"
    durable_target = tmp_path / "durable" / "prod" / "gpu-intent.json"

    first = write_gpu_intent(
        runtime_target,
        durable_path=durable_target,
        action=IntentAction.START,
        requested_by="operator",
        now=NOW,
    )
    second = write_gpu_intent(
        runtime_target,
        durable_path=durable_target,
        action=IntentAction.STOP,
        requested_by="operator",
        now=NOW,
    )

    # This cross-package contract must also run from the service directory.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4]))
    from infra.oci.gpu_lifecycle.intent import _read_one, read_effective_intent

    lifecycle_intent = _read_one(runtime_target)
    effective_intent = read_effective_intent(tmp_path / "runtime", NOW)

    assert lifecycle_intent is not None
    assert lifecycle_intent.sequence == 2
    assert lifecycle_intent.action.value == "stop"
    assert effective_intent.sequence == second.sequence
    assert effective_intent.action.value == "stop"
    assert first.sequence == 1
    assert second.sequence == first.sequence + 1


def test_runtime_mount_publication_has_no_implicit_var_lib_durable_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API must not default its durable copy into the controller state dir.

    In production the API container runs as ``acx`` (10001) with exactly one
    writable host bind mount, ``/run/acx-write/<env>``. ``/var/lib/acx-gpu`` is
    the lifecycle controller's ``StateDirectory`` at mode 0700 and is not
    mounted into the container at all, so a defaulted durable write there
    raises ``PermissionError`` before the runtime publication and turns every
    operator intent into a 503. Durability is the controller's own copy-before-
    evaluate step; the service opts in explicitly or not at all.
    """
    monkeypatch.delenv("ACX_GPU_INTENT_DURABLE_PATH", raising=False)

    resolved = resolve_gpu_intent_durable_path(Path("/run/acx-write/prod/gpu-intent.json"))

    assert resolved is None


def test_durable_mirror_survives_runtime_publication_removal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_target = tmp_path / "runtime" / "prod" / "gpu-intent.json"
    durable_target = tmp_path / "durable" / "prod" / "gpu-intent.json"
    monkeypatch.setenv("ACX_GPU_INTENT_DURABLE_PATH", str(durable_target))

    written = write_gpu_intent(
        runtime_target,
        durable_path=durable_target,
        action=IntentAction.START,
        requested_by="operator",
        now=NOW,
    )
    runtime_target.unlink()

    loaded = read_gpu_intent(runtime_target)

    assert durable_target.is_file()
    assert loaded == written


def test_contended_lock_times_out_without_publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "gpu-intent.json"
    lock_path = target.with_name(f"{target.name}.lock")
    lock_path.touch()
    monkeypatch.setenv("ACX_GPU_INTENT_LOCK_TIMEOUT_SECONDS", "0.05")

    with lock_path.open("r", encoding="utf-8") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="GPU intent lock"):
            write_gpu_intent(target, action=IntentAction.START, now=NOW)
        elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert not target.exists()


def test_sequence_allocation_failure_does_not_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "runtime" / "gpu-intent.json"
    durable_target = tmp_path / "durable" / "gpu-intent.json"

    def fail_allocation(_path: Path) -> int:
        raise OSError("sequence ledger unavailable")

    monkeypatch.setattr("scene.application.gpu_intent._read_persisted_sequence", fail_allocation)

    with pytest.raises(OSError, match="sequence ledger unavailable"):
        write_gpu_intent(
            target,
            durable_path=durable_target,
            action=IntentAction.START,
            now=NOW,
        )

    assert not target.exists()
    assert not durable_target.exists()


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


def test_parseable_timestamp_overflow_is_malformed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    target = tmp_path / "gpu-intent.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "action": "start",
                "requested_at": "9999-12-31T23:59:59Z",
                "expires_at": "9999-12-31T23:59:59Z",
                "ttl_seconds": 60,
                "requested_by": "operator",
                "nonce": "8f8d2f40-39c0-4a91-8e4b-7e4d1e7b7d6a",
            }
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="scene.application.gpu_intent"):
        assert read_gpu_intent(target) is None

    assert any("malformed GPU intent" in record.getMessage() for record in caplog.records)


def test_timezone_naive_timestamps_are_malformed(tmp_path: Path) -> None:
    target = tmp_path / "gpu-intent.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "action": "start",
                "requested_at": "2026-09-06T22:00:00",
                "expires_at": "2026-09-06T22:30:00",
                "ttl_seconds": 1800,
                "requested_by": "operator",
                "nonce": "8f8d2f40-39c0-4a91-8e4b-7e4d1e7b7d6a",
            }
        ),
        encoding="utf-8",
    )

    assert read_gpu_intent(target) is None


def test_service_and_lifecycle_readers_agree_on_naive_timestamp_payload(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from infra.oci.gpu_lifecycle.intent import read_effective_intent

    payload = {
        "schema_version": 1,
        "action": "start",
        "requested_at": "2026-09-06T22:00:00",
        "expires_at": "2026-09-06T22:30:00",
        "ttl_seconds": 1800,
        "requested_by": "operator",
        "nonce": "parity-test",
    }
    target = tmp_path / "prod" / "gpu-intent.json"
    target.parent.mkdir()
    target.write_text(json.dumps(payload), encoding="utf-8")

    service_intent = read_gpu_intent(target)
    lifecycle_intent = read_effective_intent(tmp_path, NOW)

    assert service_intent is None
    assert lifecycle_intent.action.value == "auto"


def test_intent_path_defaults_to_load_path_sibling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    load_path = tmp_path / "describe-load.json"
    monkeypatch.setenv("ACX_DESCRIBE_LOAD_PATH", str(load_path))
    monkeypatch.delenv("ACX_GPU_INTENT_PATH", raising=False)

    assert resolve_gpu_intent_path() == str(tmp_path / "gpu-intent.json")


def test_intent_path_honours_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "configured" / "operator.json"
    monkeypatch.setenv("ACX_GPU_INTENT_PATH", str(target))

    assert resolve_gpu_intent_path() == str(target)
