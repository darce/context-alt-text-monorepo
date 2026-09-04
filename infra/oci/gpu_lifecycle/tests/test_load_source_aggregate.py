"""Per-environment describe-load aggregation for the shared GPU lifecycle."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from infra.oci.gpu_lifecycle.controller import JobLoadSnapshot
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
    path.parent.mkdir(parents=True)
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
    return AggregateJobLoadSource(
        directory=root,
        stale_seconds=120,
        stale_grace_seconds=600,
    )


def test_two_fresh_files_one_busy_aggregates_all_environments(tmp_path: Path) -> None:
    _write_load(tmp_path, "dev", queue_depth=0, in_flight=0)
    _write_load(tmp_path, "prod", queue_depth=3, in_flight=1)

    snapshot = _source(tmp_path).snapshot()

    assert snapshot == JobLoadSnapshot(queue_depth=3, in_flight=1)
    assert snapshot.has_work is True


def test_two_fresh_idle_files_are_idle(tmp_path: Path) -> None:
    _write_load(tmp_path, "dev", queue_depth=0, in_flight=0)
    _write_load(tmp_path, "staging", queue_depth=0, in_flight=0)

    snapshot = _source(tmp_path).snapshot()

    assert snapshot == JobLoadSnapshot(queue_depth=0, in_flight=0)
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
    assert snapshot.has_work is True


def test_future_dated_file_within_clock_skew_is_fresh(tmp_path: Path) -> None:
    _write_load(
        tmp_path,
        "dev",
        queue_depth=0,
        in_flight=0,
        written_at=NOW + LOAD_SNAPSHOT_FUTURE_SKEW_SECONDS,
    )

    snapshot = _source(tmp_path).snapshot()

    assert snapshot == JobLoadSnapshot(queue_depth=0, in_flight=0)
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
    assert snapshot.has_work is True


def test_stale_within_grace_is_busy_while_fresh_busy_is_aggregated(tmp_path: Path) -> None:
    _write_load(tmp_path, "dev", queue_depth=0, in_flight=0, written_at=NOW - 121)
    _write_load(tmp_path, "prod", queue_depth=2, in_flight=0)

    snapshot = _source(tmp_path).snapshot()

    # The stale environment contributes the existing fail-closed sentinel,
    # while the fresh environment is still scanned and included.
    assert snapshot.queue_depth == 3
    assert snapshot.in_flight == 1
    assert snapshot.untrustworthy is True
    assert snapshot.has_work is True


def test_stale_beyond_grace_is_ignored_when_a_fresh_idle_file_exists(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_load(tmp_path, "dev", queue_depth=9, in_flight=4, written_at=NOW - 601)
    _write_load(tmp_path, "staging", queue_depth=0, in_flight=0)

    with caplog.at_level(logging.WARNING, logger="infra.oci.gpu_lifecycle.load_source"):
        snapshot = _source(tmp_path).snapshot()

    assert snapshot == JobLoadSnapshot(queue_depth=0, in_flight=0)
    assert snapshot.has_work is False
    assert "dev" in caplog.text
    assert "ignored" in caplog.text.lower()
    assert "grace" in caplog.text.lower()


@pytest.mark.parametrize("directory_exists", [False, True])
def test_missing_directory_or_no_files_preserves_fail_closed_outcome(
    tmp_path: Path,
    directory_exists: bool,
) -> None:
    root = tmp_path / "loads"
    if directory_exists:
        root.mkdir()

    snapshot = _source(root).snapshot()

    assert snapshot == JobLoadSnapshot(
        queue_depth=1,
        in_flight=1,
        batch_in_progress=True,
        untrustworthy=True,
    )
    assert snapshot.has_work is True


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

    # One fail-closed sentinel plus prod's real load proves the scan continued.
    assert snapshot.queue_depth == 4
    assert snapshot.in_flight == 1
    assert snapshot.untrustworthy is True
    assert "dev" in caplog.text
    assert "unreadable" in caplog.text.lower()


def test_only_beyond_grace_files_remains_fail_closed(tmp_path: Path) -> None:
    _write_load(tmp_path, "prod", queue_depth=0, in_flight=0, written_at=NOW - 601)

    snapshot = _source(tmp_path).snapshot()

    assert snapshot.untrustworthy is True
    assert snapshot.has_work is True


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
