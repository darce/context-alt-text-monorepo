"""Per-environment describe-load aggregation for the shared GPU lifecycle."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest
from infra.oci.gpu_lifecycle.load_source import (
    LOAD_SNAPSHOT_FUTURE_SKEW_SECONDS,
    AggregateJobLoadSource,
)
from infra.oci.gpu_lifecycle.reaper import _build_parser

NOW = 10_000.0


def _write_load(
    root: Path,
    env: str,
    *,
    queue_depth: int,
    in_flight: int,
    written_at: float = NOW,
    batch_in_progress: bool = False,
) -> None:
    path = root / env / "describe-load.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "queue_depth": queue_depth,
                "in_flight": in_flight,
                "batch_in_progress": batch_in_progress,
                "written_at": written_at,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _fixed_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("infra.oci.gpu_lifecycle.load_source.time.time", lambda: NOW)


def _source(root: Path) -> AggregateJobLoadSource:
    expected_environments = (
        tuple(sorted(path.name for path in root.iterdir() if path.is_dir())) if root.is_dir() else ()
    )
    return AggregateJobLoadSource(
        directory=root,
        stale_seconds=120,
        stale_grace_seconds=600,
        expected_environments=expected_environments or ("dev",),
    )


def test_two_fresh_files_one_busy_aggregates_all_environments(tmp_path: Path) -> None:
    _write_load(tmp_path, "dev", queue_depth=0, in_flight=0)
    _write_load(tmp_path, "prod", queue_depth=3, in_flight=1)

    snapshot = _source(tmp_path).snapshot()

    assert snapshot.queue_depth == 3
    assert snapshot.in_flight == 1
    assert snapshot.evidence == "trustworthy"
    assert snapshot.has_work is True


def test_two_fresh_idle_files_are_idle(tmp_path: Path) -> None:
    _write_load(tmp_path, "dev", queue_depth=0, in_flight=0)
    _write_load(tmp_path, "staging", queue_depth=0, in_flight=0)

    snapshot = _source(tmp_path).snapshot()

    assert snapshot.queue_depth == 0
    assert snapshot.in_flight == 0
    assert snapshot.evidence == "trustworthy"
    assert snapshot.has_work is False


def test_future_dated_file_beyond_clock_skew_fails_closed(tmp_path: Path) -> None:
    _write_load(
        tmp_path,
        "dev",
        queue_depth=0,
        in_flight=0,
        written_at=NOW + LOAD_SNAPSHOT_FUTURE_SKEW_SECONDS + 0.001,
    )

    snapshot = _source(tmp_path).snapshot()

    assert snapshot.untrustworthy is True
    assert snapshot.evidence == "unknown"
    assert snapshot.has_work is False


def test_future_dated_file_within_clock_skew_is_fresh(tmp_path: Path) -> None:
    _write_load(
        tmp_path,
        "dev",
        queue_depth=0,
        in_flight=0,
        written_at=NOW + LOAD_SNAPSHOT_FUTURE_SKEW_SECONDS,
    )

    snapshot = _source(tmp_path).snapshot()

    assert snapshot.queue_depth == 0
    assert snapshot.in_flight == 0
    assert snapshot.evidence == "trustworthy"
    assert snapshot.has_work is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("written_at", str(NOW)),
        ("queue_depth", "0"),
        ("queue_depth", False),
        ("in_flight", False),
    ],
)
def test_non_native_load_numbers_fail_closed(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {
        "queue_depth": 0,
        "in_flight": 0,
        "batch_in_progress": False,
        "written_at": NOW,
    }
    payload[field] = value
    path = tmp_path / "dev" / "describe-load.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    snapshot = _source(tmp_path).snapshot()

    assert snapshot.untrustworthy is True
    assert snapshot.evidence == "unknown"
    assert snapshot.has_work is False


def test_stale_within_grace_is_unknown_while_observed_counts_are_aggregated(tmp_path: Path) -> None:
    _write_load(tmp_path, "dev", queue_depth=0, in_flight=0, written_at=NOW - 121)
    _write_load(tmp_path, "prod", queue_depth=2, in_flight=0)

    snapshot = _source(tmp_path).snapshot()

    assert snapshot.queue_depth == 2
    assert snapshot.in_flight == 0
    assert snapshot.evidence == "unknown"
    assert snapshot.untrustworthy is True
    assert snapshot.has_work is True


def test_stale_beyond_grace_remains_unknown_when_a_fresh_idle_file_exists(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_load(tmp_path, "dev", queue_depth=9, in_flight=4, written_at=NOW - 601)
    _write_load(tmp_path, "staging", queue_depth=0, in_flight=0)

    with caplog.at_level(logging.WARNING, logger="infra.oci.gpu_lifecycle.load_source"):
        snapshot = _source(tmp_path).snapshot()

    assert snapshot.queue_depth == 9
    assert snapshot.in_flight == 4
    assert snapshot.evidence == "unknown"
    assert snapshot.untrustworthy is True
    assert snapshot.has_work is True
    assert "dev" in caplog.text
    assert "stale" in caplog.text.lower()


@pytest.mark.parametrize("directory_exists", [False, True])
def test_missing_directory_or_no_files_preserves_fail_closed_outcome(
    tmp_path: Path,
    directory_exists: bool,
) -> None:
    root = tmp_path / "loads"
    if directory_exists:
        root.mkdir()

    snapshot = _source(root).snapshot()

    assert snapshot.queue_depth == 0
    assert snapshot.in_flight == 0
    assert snapshot.batch_in_progress is False
    assert snapshot.untrustworthy is True
    assert snapshot.evidence == "unknown"
    assert snapshot.has_work is False


def test_malformed_environment_fails_closed_without_hiding_other_files(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    malformed = tmp_path / "dev" / "describe-load.json"
    malformed.parent.mkdir()
    malformed.write_text("not-json", encoding="utf-8")
    _write_load(tmp_path, "prod", queue_depth=3, in_flight=0)

    with caplog.at_level(logging.WARNING, logger="infra.oci.gpu_lifecycle.load_source"):
        snapshot = _source(tmp_path).snapshot()

    assert snapshot.queue_depth == 3
    assert snapshot.in_flight == 0
    assert snapshot.evidence == "unknown"
    assert snapshot.untrustworthy is True
    assert "dev" in caplog.text
    assert "malformed" in caplog.text.lower()


def test_only_beyond_grace_files_remains_fail_closed(tmp_path: Path) -> None:
    _write_load(tmp_path, "prod", queue_depth=0, in_flight=0, written_at=NOW - 601)

    snapshot = _source(tmp_path).snapshot()

    assert snapshot.untrustworthy is True
    assert snapshot.evidence == "unknown"
    assert snapshot.has_work is False


@pytest.mark.parametrize(
    ("stale_seconds", "stale_grace_seconds"),
    [(0, 600), (120, 0), (120, 119)],
)
def test_invalid_age_configuration_is_rejected_at_load_time(
    tmp_path: Path,
    stale_seconds: float,
    stale_grace_seconds: float,
) -> None:
    with pytest.raises(ValueError):
        AggregateJobLoadSource(
            directory=tmp_path,
            stale_seconds=stale_seconds,
            stale_grace_seconds=stale_grace_seconds,
        )


def test_cli_replaces_single_file_flag_and_accepts_grace_configuration(tmp_path: Path) -> None:
    args = _build_parser().parse_args(
        [
            "--instance-id",
            "ocid1.example",
            "--load-dir",
            str(tmp_path),
            "--load-stale-grace-seconds",
            "900",
        ]
    )

    assert args.load_dir == tmp_path
    assert args.load_stale_grace_seconds == 900
    assert "--load-json" not in _build_parser().format_help()

    with pytest.raises(SystemExit):
        _build_parser().parse_args(["--instance-id", "ocid1.example", "--load-json", str(tmp_path / "load.json")])


def test_cli_grace_default_is_environment_configurable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS", "750")

    args = _build_parser().parse_args(["--instance-id", "ocid1.example", "--load-dir", str(tmp_path)])

    assert args.load_stale_grace_seconds == 750


def test_missing_expected_producer_is_unknown_not_idle(tmp_path: Path) -> None:
    _write_load(tmp_path, "dev", queue_depth=0, in_flight=0)

    snapshot = AggregateJobLoadSource(
        directory=tmp_path,
        stale_seconds=120,
        stale_grace_seconds=600,
        expected_environments=("dev", "prod"),
    ).snapshot()

    assert snapshot.evidence == "unknown"
    assert snapshot.untrustworthy is True
    assert snapshot.has_work is False


def test_stale_producer_remains_unknown_after_stale_grace(tmp_path: Path) -> None:
    _write_load(tmp_path, "dev", queue_depth=0, in_flight=0)
    _write_load(tmp_path, "prod", queue_depth=0, in_flight=1, written_at=NOW - 601)

    snapshot = AggregateJobLoadSource(
        directory=tmp_path,
        stale_seconds=120,
        stale_grace_seconds=600,
        expected_environments=("dev", "prod"),
    ).snapshot()

    assert snapshot.evidence != "trustworthy"
    assert snapshot.untrustworthy is True
    assert snapshot.in_flight == 1


def test_omitted_batch_state_is_unknown_but_explicit_false_is_trustworthy(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "dev" / "describe-load.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"queue_depth": 0, "in_flight": 0, "written_at": NOW}),
        encoding="utf-8",
    )
    source = AggregateJobLoadSource(
        directory=tmp_path,
        stale_seconds=120,
        stale_grace_seconds=600,
        expected_environments=("dev",),
    )

    with caplog.at_level(logging.WARNING, logger="infra.oci.gpu_lifecycle.load_source"):
        missing_batch = source.snapshot()
        _write_load(tmp_path, "dev", queue_depth=0, in_flight=0, batch_in_progress=False)
        explicit_idle = source.snapshot()

    assert missing_batch.evidence == "unknown"
    assert missing_batch.untrustworthy is True
    assert missing_batch.has_work is False
    assert explicit_idle.evidence == "trustworthy"
    assert explicit_idle.untrustworthy is False
    assert explicit_idle.has_work is False
    assert "environment=dev reason=malformed" in caplog.text
    assert "recovered environment=dev" in caplog.text


def test_malformed_snapshot_unknown_quarantine_expires_to_escalated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = [NOW]
    monkeypatch.setattr("infra.oci.gpu_lifecycle.load_source.time.time", lambda: now[0])
    malformed = tmp_path / "dev" / "describe-load.json"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("not-json", encoding="utf-8")
    os.utime(malformed, (NOW, NOW))
    _write_load(tmp_path, "prod", queue_depth=0, in_flight=0)
    source = AggregateJobLoadSource(
        directory=tmp_path,
        stale_seconds=120,
        stale_grace_seconds=600,
        unknown_grace_seconds=60,
        expected_environments=("dev", "prod"),
    )

    with caplog.at_level(logging.WARNING, logger="infra.oci.gpu_lifecycle.load_source"):
        quarantined = source.snapshot()
        now[0] += 61
        escalated = source.snapshot()

    assert quarantined.evidence == "unknown"
    assert quarantined.untrustworthy is True
    assert quarantined.has_work is False
    assert escalated.evidence == "escalated"
    assert escalated.untrustworthy is True
    assert escalated.escalated_environments == ("dev",)
    assert "environment=dev reason=malformed" in caplog.text
    assert "evidence escalated" in caplog.text


@pytest.mark.parametrize("unknown_grace_seconds", [0, -1, float("inf"), float("nan")])
def test_invalid_unknown_grace_is_rejected(
    tmp_path: Path,
    unknown_grace_seconds: float,
) -> None:
    with pytest.raises(ValueError, match="unknown_grace_seconds"):
        AggregateJobLoadSource(
            directory=tmp_path,
            stale_seconds=120,
            unknown_grace_seconds=unknown_grace_seconds,
            expected_environments=("dev",),
        )


@pytest.mark.parametrize("contents", ["", "dev\ndev\n", "dev/gpu\n"])
def test_malformed_deployment_registry_is_rejected(tmp_path: Path, contents: str) -> None:
    registry = tmp_path / "deployments.conf"
    registry.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match="deployment registry"):
        AggregateJobLoadSource(
            directory=tmp_path / "loads",
            stale_seconds=120,
            deployments_file=registry,
        )


def test_missing_deployment_registry_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing or unreadable"):
        AggregateJobLoadSource(
            directory=tmp_path / "loads",
            stale_seconds=120,
            deployments_file=tmp_path / "absent.conf",
        )


def test_default_registry_supplies_the_expected_producer_set(tmp_path: Path) -> None:
    source = AggregateJobLoadSource(directory=tmp_path, stale_seconds=120)

    assert source.expected_environments == ("dev", "dev-fir", "prod", "staging")
