"""Contract tests for the offline OCI GPU cost report."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import gpu_cost_report as report
import pytest


def _smoke_report() -> dict[str, object]:
    return {
        "instance_id": "ocid1.instance.oc1.iad.gpu",
        "run_status": "completed",
        "checks": [
            {"name": name, "passed": True}
            for name in (
                "run_terminal_success",
                "load_snapshot_observed_after_trigger",
                "exactly_one_start_action",
                "second_burst_no_enqueue",
                "no_orphan_running",
                "instance_stopped_finally",
                "stop_event_observed",
                "stop_principal_allowed",
                "stop_attribution",
            )
        ],
        "running_seconds_ongoing": False,
        "cost_estimate_ongoing": False,
        "measurements": {
            "running_seconds": 360.0,
            "running_seconds_ongoing": False,
            "cost_estimate_ongoing": False,
        },
        "transitions": [
            {"state": "STOPPED", "timestamp": "2026-01-01T00:00:00Z", "elapsed_seconds": 0.0},
            {"state": "RUNNING", "timestamp": "2026-01-01T00:00:10Z", "elapsed_seconds": 10.0},
            {"state": "STOPPING", "timestamp": "2026-01-01T00:06:10Z", "elapsed_seconds": 370.0},
            {"state": "STOPPED", "timestamp": "2026-01-01T00:06:12Z", "elapsed_seconds": 372.0},
        ],
        "start_action_evidence": {
            "window_start": "2026-01-01T00:00:00Z",
            "window_end": "2026-01-01T00:06:12Z",
        },
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_report_prints_running_cost_and_usage_amount(tmp_path: Path, capsys) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(
        usage,
        {
            "data": {
                "items": [
                    {
                        "computedAmount": 0.2,
                        "timeFrom": "2026-01-01T00:00:00Z",
                        "timeTo": "2026-01-01T00:06:12Z",
                        "resourceId": "ocid1.instance.oc1.iad.gpu",
                    }
                ]
            }
        },
    )
    _write_json(smoke, _smoke_report())

    exit_code = report.main(
        [
            "--usage-json",
            str(usage),
            "--smoke-report",
            str(smoke),
            "--hourly-rate",
            "2",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "running_seconds=360.000" in output
    assert "estimated_usd=0.200000" in output
    assert "usage_api_usd=0.200000" in output
    assert "within tolerance" in output


def test_report_sums_multiple_usage_exports_and_fails_on_mismatch(tmp_path: Path, capsys) -> None:
    usage_one = tmp_path / "usage-one.json"
    usage_two = tmp_path / "usage-two.json"
    smoke = tmp_path / "smoke.json"
    _write_json(
        usage_one,
        {"data": {"items": [{"computedAmount": 0.05, "resourceId": "ocid1.instance.oc1.iad.gpu"}]}},
    )
    _write_json(
        usage_two,
        {"data": {"items": [{"computedAmount": 0.05, "resourceId": "ocid1.instance.oc1.iad.gpu"}]}},
    )
    _write_json(smoke, _smoke_report())

    exit_code = report.main(
        [
            "--usage-json",
            str(usage_one),
            "--usage-json",
            str(usage_two),
            "--smoke-report",
            str(smoke),
            "--hourly-rate",
            "2",
        ]
    )

    assert exit_code == 2
    output = capsys.readouterr().out
    assert "usage_api_usd=0.100000" in output
    assert "exceeds tolerance" in output


def test_report_accepts_usage_exports_as_positionals(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(
        usage,
        {"data": {"items": [{"computedAmount": 0.2, "resourceId": "ocid1.instance.oc1.iad.gpu"}]}},
    )
    _write_json(smoke, _smoke_report())

    args = report.build_parser().parse_args([str(usage), "--smoke-report", str(smoke)])

    assert args.usage_json == [str(usage)]


def test_cost_report_imports_only_stdlib_modules() -> None:
    tree = ast.parse(Path(report.__file__).read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]

    modules = {
        alias.name.split(".")[0]
        for node in imports
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    modules.update(
        node.module.split(".")[0]
        for node in imports
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    assert modules <= {
        "argparse",
        "collections",
        "datetime",
        "json",
        "math",
        "pathlib",
        "sys",
        "typing",
        "__future__",
    }


def test_usage_rows_spanning_two_bursts_are_allocated_by_overlap(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(
        usage,
        {
            "data": {
                "items": [
                    {
                        "computedAmount": 1.0,
                        "timeFrom": "2026-01-01T00:00:00Z",
                        "timeTo": "2026-01-01T00:20:00Z",
                        "resourceId": "ocid1.instance.oc1.iad.gpu",
                    }
                ]
            }
        },
    )
    first = _smoke_report()
    second = {
        **_smoke_report(),
        "start_time": "2026-01-01T00:10:00Z",
        "end_time": "2026-01-01T00:20:00Z",
    }
    first["start_time"] = "2026-01-01T00:00:00Z"
    first["end_time"] = "2026-01-01T00:10:00Z"
    _write_json(smoke, {"bursts": [first, second]})

    comparisons = report.report_costs([str(usage)], str(smoke), hourly_rate=360.0)

    assert [comparison["usage_api_usd"] for comparison in comparisons] == [0.5, 0.5]


def test_usage_row_without_resource_id_is_rejected_for_identified_burst(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(usage, {"data": {"items": [{"computedAmount": 0.2}]}})
    _write_json(smoke, _smoke_report())

    with pytest.raises(report.CostReportError, match="resourceId"):
        report.report_costs([str(usage)], str(smoke))


@pytest.mark.parametrize("payload", [{"unexpected": []}, {"data": {"items": []}}, []])
def test_empty_or_unrecognized_usage_export_is_an_input_error(
    tmp_path: Path,
    payload: object,
) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(usage, payload)
    _write_json(smoke, _smoke_report())

    with pytest.raises(report.CostReportError, match="usage export"):
        report.report_costs([str(usage)], str(smoke))


@pytest.mark.parametrize(
    ("smoke_overrides", "message"),
    [
        ({"checks": [{"name": "flow_completed", "passed": False}]}, "failed check"),
        ({"checks": ["malformed"]}, "failed check"),
        ({"running_seconds_ongoing": True}, "still running"),
    ],
)
def test_cost_report_requires_a_closed_successful_smoke(
    tmp_path: Path,
    smoke_overrides: dict[str, object],
    message: str,
) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(usage, {"data": {"items": [{"computedAmount": 0.2, "resourceId": "ocid1.instance.oc1.iad.gpu"}]}})
    report_payload = _smoke_report()
    report_payload.update(smoke_overrides)
    _write_json(smoke, report_payload)

    with pytest.raises(report.CostReportError, match=message):
        report.report_costs([str(usage)], str(smoke))


def test_cost_report_requires_canonical_safety_checks(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(
        usage,
        {"data": {"items": [{"computedAmount": 0.2, "resourceId": "ocid1.instance.oc1.iad.gpu"}]}},
    )
    report_payload = _smoke_report()
    report_payload["checks"] = [{"name": "smoke_verdict", "passed": True}]
    _write_json(smoke, report_payload)

    with pytest.raises(report.CostReportError, match="required safety check"):
        report.report_costs([str(usage)], str(smoke))


def test_cost_report_rejects_open_or_nonmonotonic_transition_evidence(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(
        usage,
        {"data": {"items": [{"computedAmount": 0.0, "resourceId": "ocid1.instance.oc1.iad.gpu"}]}},
    )
    report_payload = _smoke_report()
    report_payload["transitions"] = [
        {"state": "STOPPED", "timestamp": "2026-01-01T00:00:00Z", "elapsed_seconds": 0.0},
        {"state": "RUNNING", "timestamp": "2026-01-01T00:00:10Z", "elapsed_seconds": 10.0},
        {"state": "STOPPING", "timestamp": "2026-01-01T00:00:09Z", "elapsed_seconds": 9.0},
    ]
    _write_json(smoke, report_payload)

    with pytest.raises(report.CostReportError, match="monotonic|STOPPED"):
        report.report_costs([str(usage)], str(smoke))


def test_cost_report_rejects_running_seconds_that_disagree_with_transitions(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(
        usage,
        {"data": {"items": [{"computedAmount": 0.2, "resourceId": "ocid1.instance.oc1.iad.gpu"}]}},
    )
    report_payload = _smoke_report()
    report_payload["measurements"] = {
        "running_seconds": 999.0,
        "running_seconds_ongoing": False,
        "cost_estimate_ongoing": False,
    }
    _write_json(smoke, report_payload)

    with pytest.raises(report.CostReportError, match="running_seconds"):
        report.report_costs([str(usage)], str(smoke))


@pytest.mark.parametrize(
    ("transitions", "message"),
    [
        (
            [
                {"state": "STOPPED", "elapsed_seconds": 0.0},
                {"state": "RUNNING", "elapsed_seconds": 10.0},
                {"state": "UNKNOWN", "elapsed_seconds": 20.0},
                {"state": "STOPPED", "elapsed_seconds": 30.0},
            ],
            "unknown lifecycle state",
        ),
        (
            [
                {"state": "STOPPED", "elapsed_seconds": -1.0},
                {"state": "RUNNING", "elapsed_seconds": 10.0},
                {"state": "STOPPED", "elapsed_seconds": 20.0},
            ],
            "non-negative",
        ),
        (
            [
                {"state": "STARTING", "elapsed_seconds": 0.0},
                {"state": "RUNNING", "elapsed_seconds": 10.0},
                {"state": "STOPPED", "elapsed_seconds": 20.0},
            ],
            "start in STOPPED",
        ),
    ],
)
def test_cost_report_rejects_unproven_lifecycle_timeline(
    tmp_path: Path,
    transitions: list[dict[str, object]],
    message: str,
) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(
        usage,
        {"data": {"items": [{"computedAmount": 0.2, "resourceId": "ocid1.instance.oc1.iad.gpu"}]}},
    )
    report_payload = _smoke_report()
    report_payload["transitions"] = transitions
    _write_json(smoke, report_payload)

    with pytest.raises(report.CostReportError, match=message):
        report.report_costs([str(usage)], str(smoke))


def test_cost_report_rejects_top_level_running_seconds_drift(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(
        usage,
        {"data": {"items": [{"computedAmount": 0.2, "resourceId": "ocid1.instance.oc1.iad.gpu"}]}},
    )
    report_payload = _smoke_report()
    report_payload["running_seconds"] = 1.0
    _write_json(smoke, report_payload)

    with pytest.raises(report.CostReportError, match="top-level running_seconds"):
        report.report_costs([str(usage)], str(smoke))


def test_cost_report_rejects_negative_usage_amount(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    smoke = tmp_path / "smoke.json"
    _write_json(
        usage,
        {"data": {"items": [{"computedAmount": -0.2, "resourceId": "ocid1.instance.oc1.iad.gpu"}]}},
    )
    _write_json(smoke, _smoke_report())

    with pytest.raises(report.CostReportError, match="non-negative"):
        report.report_costs([str(usage)], str(smoke))
