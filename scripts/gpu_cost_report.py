#!/usr/bin/env python3
"""Compare GPU smoke estimates with OCI Usage API cost exports.

The export is deliberately a file input: this report never calls OCI or any
other network service.  Create a request body for the window recorded by the
smoke, then export it with the OCI CLI::

    cat > usage-request.json <<'JSON'
    {
      "tenantId": "<tenancy-ocid>",
      "timeFrom": "2026-01-01T00:00:00Z",
      "timeTo": "2026-01-01T01:00:00Z",
      "granularity": "HOURLY",
      "queryType": "COST",
      "groupBy": ["resourceId", "resourceName", "service"]
    }
    JSON
    oci usage-api usage-summary request-summarized-usages \
      --request-summarized-usages-details file://usage-request.json \
      --output json > usage.json

Then select the timestamped evidence artifact and run ``python3
scripts/gpu_cost_report.py usage.json --smoke-report "$SMOKE_REPORT"``::

    SMOKE_REPORT="$(find .workbay/tmp/gpu-burst-smoke -maxdepth 1 -type f \
      -name 'GPUSMOKE-1-evidence-*.json' -print -quit)"
    test -n "$SMOKE_REPORT"
    python3 scripts/gpu_cost_report.py usage.json --smoke-report "$SMOKE_REPORT"

One or more usage exports may be supplied with repeated ``--usage-json`` options
or as positional paths.  Exit status 2 means the Usage API amount differs from
the smoke estimate by more than the configured tolerance.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_HOURLY_RATE = 2.0
DEFAULT_TOLERANCE_PCT = 25.0
GPU_LIFECYCLE_STATES = frozenset({"STOPPED", "STARTING", "RUNNING", "STOPPING"})
REQUIRED_SAFETY_CHECKS = frozenset(
    {
        "run_terminal_success",
        "load_snapshot_observed_after_trigger",
        "exactly_one_start_action",
        "second_burst_no_enqueue",
        "no_orphan_running",
        "instance_stopped_finally",
        "stop_event_observed",
        "stop_principal_allowed",
        "stop_attribution",
    }
)


class CostReportError(ValueError):
    """An input export or smoke report cannot support a cost comparison."""


def _read_json(path: str) -> Any:
    target = Path(path)
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CostReportError(f"JSON file does not exist: {path}") from exc
    except OSError as exc:
        raise CostReportError(f"cannot read JSON file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CostReportError(f"invalid JSON in {path}: {exc}") from exc


def _number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or value is None:
        raise CostReportError(f"{field} must be a finite number")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise CostReportError(f"{field} must be a finite number") from exc
    if not math.isfinite(converted):
        raise CostReportError(f"{field} must be a finite number")
    return converted


def _moment(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CostReportError(f"{field} must be an ISO-8601 timestamp")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CostReportError(f"{field} is not a valid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _first_value(mapping: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _usage_items(payload: Any) -> list[dict[str, Any]]:
    """Extract OCI ``data.items`` while accepting small fixture variants."""

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            items = payload["items"]
        elif isinstance(payload.get("usageItems"), list):
            items = payload["usageItems"]
        elif isinstance(payload.get("usage_items"), list):
            items = payload["usage_items"]
        elif isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("items"), list):
            items = payload["data"]["items"]
        elif isinstance(payload.get("data"), list):
            items = payload["data"]
        elif "computedAmount" in payload or "computed_amount" in payload:
            items = [payload]
        else:
            raise CostReportError("usage export has no recognized items list")
    else:
        raise CostReportError("usage export must be an object or list")
    if not all(isinstance(item, dict) for item in items):
        raise CostReportError("usage export items must be objects")
    if not items:
        raise CostReportError("usage export contains no usage items")
    return items


def _coerce_smoke_bursts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        bursts = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("bursts"), list):
            bursts = payload["bursts"]
        elif isinstance(payload.get("reports"), list):
            bursts = payload["reports"]
        else:
            bursts = [payload]
    else:
        raise CostReportError("smoke report must be an object or list")
    if not bursts or not all(isinstance(burst, dict) for burst in bursts):
        raise CostReportError("smoke report must contain one or more object bursts")
    return bursts


def _validate_smoke_checks(burst: dict[str, Any], index: int) -> None:
    checks = burst.get("checks")
    if not isinstance(checks, list) or not checks:
        raise CostReportError(f"smoke report burst {index} has no smoke checks/verdict")
    failed_checks: list[str] = []
    check_names: set[str] = set()
    for check_index, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            failed_checks.append(f"check-{check_index}")
            continue
        name = check.get("name")
        if isinstance(name, str) and name.strip():
            check_names.add(name)
        if check.get("passed") is not True:
            failed_checks.append(str(name or f"check-{check_index}"))
    if failed_checks:
        raise CostReportError(f"smoke report burst {index} has failed check(s): {', '.join(failed_checks)}")
    missing_checks = sorted(REQUIRED_SAFETY_CHECKS - check_names)
    if missing_checks:
        raise CostReportError(
            f"smoke report burst {index} is missing required safety check(s): " + ", ".join(missing_checks)
        )


def _validate_smoke_measurements(burst: dict[str, Any], index: int) -> None:
    run_status = burst.get("run_status")
    if run_status != "completed":
        raise CostReportError(f"smoke report burst {index} is not completed: run_status={run_status!r}")
    if burst.get("running_seconds_ongoing") is not False:
        raise CostReportError(f"smoke report burst {index} is still running or has no closed duration")
    measurements = burst.get("measurements")
    if not isinstance(measurements, dict) or "running_seconds" not in measurements:
        raise CostReportError(f"smoke report burst {index} has no closed running_seconds measurements")
    if measurements.get("running_seconds_ongoing") is not False:
        raise CostReportError(f"smoke report burst {index} is still running according to measurements")
    if measurements.get("cost_estimate_ongoing") is not False:
        raise CostReportError(f"smoke report burst {index} has an ongoing measurement cost estimate")
    _number(measurements["running_seconds"], field="measurements.running_seconds")
    if float(measurements["running_seconds"]) < 0:
        raise CostReportError(f"smoke report burst {index} has negative running_seconds")
    if "cost_estimate_usd" in measurements:
        cost_estimate = _number(measurements["cost_estimate_usd"], field="measurements.cost_estimate_usd")
        if cost_estimate < 0:
            raise CostReportError(f"smoke report burst {index} has negative cost_estimate_usd")
    if burst.get("cost_estimate_ongoing") is not False:
        raise CostReportError(f"smoke report burst {index} has an ongoing cost estimate")


def _validate_smoke_burst(burst: dict[str, Any], index: int) -> None:
    _validate_smoke_checks(burst, index)
    _validate_smoke_measurements(burst, index)


def _smoke_bursts(payload: Any) -> list[dict[str, Any]]:
    bursts = _coerce_smoke_bursts(payload)
    for index, burst in enumerate(bursts, start=1):
        _validate_smoke_burst(burst, index)
    return bursts


def _transition_timeline(burst: dict[str, Any]) -> list[tuple[str, float]]:
    transitions = burst.get("transitions")
    if not isinstance(transitions, list):
        raise CostReportError("smoke report has no transitions list")
    if not transitions:
        raise CostReportError("smoke report has no transitions")
    previous_elapsed = -math.inf
    previous_timestamp: datetime | None = None
    timeline: list[tuple[str, float]] = []
    for _index, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            raise CostReportError("smoke transitions must be objects")
        current_elapsed = _number(transition.get("elapsed_seconds"), field="transition elapsed_seconds")
        if current_elapsed < 0:
            raise CostReportError("smoke transition elapsed_seconds must be non-negative")
        if current_elapsed < previous_elapsed:
            raise CostReportError("smoke transition elapsed_seconds must be monotonic")
        previous_elapsed = current_elapsed
        state = str(transition.get("state") or "").upper()
        if state not in GPU_LIFECYCLE_STATES:
            raise CostReportError(f"smoke transition has unknown lifecycle state: {state!r}")
        timestamp = transition.get("timestamp")
        if timestamp is not None:
            parsed_timestamp = _moment(timestamp, field="transition timestamp")
            if previous_timestamp is not None and parsed_timestamp < previous_timestamp:
                raise CostReportError("smoke transition timestamps must be monotonic")
            previous_timestamp = parsed_timestamp
        timeline.append((state, current_elapsed))
    return timeline


def _running_interval_seconds(
    burst: dict[str, Any],
    timeline: Sequence[tuple[str, float]],
) -> float:
    total = 0.0
    for index, (state, current_elapsed) in enumerate(timeline):
        if state != "RUNNING":
            continue
        if index + 1 < len(timeline):
            following_elapsed = timeline[index + 1][1]
        else:
            measurements = burst.get("measurements")
            measurement = measurements if isinstance(measurements, dict) else burst
            if "final_elapsed_seconds" not in measurement:
                raise CostReportError("RUNNING transition has no closing STOPPED transition")
            following_elapsed = _number(measurement["final_elapsed_seconds"], field="final_elapsed_seconds")
        if following_elapsed < current_elapsed:
            raise CostReportError("running_seconds evidence is not monotonic")
        total += following_elapsed - current_elapsed
    return total


def _validate_lifecycle_timeline(states: Sequence[str]) -> None:
    if states[0] != "STOPPED":
        raise CostReportError("smoke transition evidence must start in STOPPED")
    if states[-1] != "STOPPED":
        raise CostReportError("smoke transition evidence must end in STOPPED")
    if "RUNNING" not in states:
        raise CostReportError("smoke transition evidence has no RUNNING interval")
    allowed_successors = {
        # Some OCI exports omit a transient STARTING observation, so a direct
        # STOPPED -> RUNNING pair is valid when the elapsed/timestamp proof is
        # otherwise complete.
        "STOPPED": {"STOPPED", "STARTING", "RUNNING"},
        "STARTING": {"STARTING", "RUNNING", "STOPPING", "STOPPED"},
        "RUNNING": {"RUNNING", "STOPPING", "STOPPED"},
        "STOPPING": {"STOPPING", "STOPPED"},
    }
    for current, following in zip(states, states[1:], strict=False):
        if following not in allowed_successors[current]:
            raise CostReportError(f"invalid smoke lifecycle transition: {current} -> {following}")


def _running_seconds_from_transitions(burst: dict[str, Any]) -> float:
    timeline = _transition_timeline(burst)
    states = [state for state, _elapsed in timeline]
    _validate_lifecycle_timeline(states)
    total = _running_interval_seconds(burst, timeline)
    return round(total, 3)


def _burst_running_seconds(burst: dict[str, Any]) -> float:
    transition_seconds = _running_seconds_from_transitions(burst)
    measurements = burst.get("measurements")
    measured_seconds: float | None = None
    if isinstance(measurements, dict) and measurements.get("running_seconds") is not None:
        measured_seconds = round(_number(measurements["running_seconds"], field="measurements.running_seconds"), 3)
        if not math.isclose(measured_seconds, transition_seconds, abs_tol=0.001):
            raise CostReportError(
                "measurements.running_seconds disagrees with transition running_seconds "
                f"({measured_seconds} != {transition_seconds})"
            )
    if measured_seconds is not None and burst.get("running_seconds") is not None:
        reported_seconds = round(_number(burst["running_seconds"], field="running_seconds"), 3)
        if not math.isclose(reported_seconds, measured_seconds, abs_tol=0.001):
            raise CostReportError(
                "top-level running_seconds disagrees with measurements.running_seconds "
                f"({reported_seconds} != {measured_seconds})"
            )
    if measured_seconds is not None:
        return measured_seconds
    if burst.get("running_seconds") is not None:
        reported_seconds = round(_number(burst["running_seconds"], field="running_seconds"), 3)
        if not math.isclose(reported_seconds, transition_seconds, abs_tol=0.001):
            raise CostReportError(
                "running_seconds disagrees with transition running_seconds "
                f"({reported_seconds} != {transition_seconds})"
            )
        return reported_seconds
    return transition_seconds


def _burst_window(burst: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    start_evidence = burst.get("start_action_evidence")
    stop_evidence = burst.get("stop_action_evidence")
    start_evidence = start_evidence if isinstance(start_evidence, dict) else {}
    stop_evidence = stop_evidence if isinstance(stop_evidence, dict) else {}
    start_raw = _first_value(
        burst,
        ("window_start", "start_time", "started_at"),
    ) or start_evidence.get("window_start")
    end_raw = (
        _first_value(
            burst,
            ("window_end", "end_time", "ended_at"),
        )
        or stop_evidence.get("window_end")
        or burst.get("stop_event_time")
        or burst.get("generated_at")
    )
    start = _moment(start_raw, field="smoke window_start") if start_raw is not None else None
    end = _moment(end_raw, field="smoke window_end") if end_raw is not None else None
    if start is not None and end is not None and end < start:
        raise CostReportError("smoke report window_end precedes window_start")
    return start, end


def _target_resource_ids(burst: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in (
        "instance_id",
        "instanceId",
        "instance_ocid",
        "instanceOcid",
        "gpu_instance_id",
        "gpuInstanceId",
    ):
        value = burst.get(key)
        if isinstance(value, str) and value.strip():
            values.add(value)
    return values


def _usage_resource_id(item: dict[str, Any]) -> str | None:
    value = _first_value(item, ("resourceId", "resource_id"))
    return value if isinstance(value, str) and value.strip() else None


def _usage_window(item: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    start_raw = _first_value(item, ("timeFrom", "time_from", "timeFromUtc", "time_from_utc"))
    end_raw = _first_value(item, ("timeTo", "time_to", "timeToUtc", "time_to_utc"))
    start = _moment(start_raw, field="usage timeFrom") if start_raw is not None else None
    end = _moment(end_raw, field="usage timeTo") if end_raw is not None else None
    if start is not None and end is not None and end < start:
        raise CostReportError("usage timeTo precedes timeFrom")
    return start, end


def _windows_overlap(
    usage_start: datetime | None,
    usage_end: datetime | None,
    smoke_start: datetime | None,
    smoke_end: datetime | None,
) -> bool:
    if usage_start is None or usage_end is None or smoke_start is None or smoke_end is None:
        return True
    return usage_start < smoke_end and usage_end > smoke_start


def _overlap_seconds(
    usage_start: datetime | None,
    usage_end: datetime | None,
    smoke_start: datetime | None,
    smoke_end: datetime | None,
) -> float | None:
    """Return the intersection duration, or ``None`` when a window is absent."""

    if usage_start is None or usage_end is None or smoke_start is None or smoke_end is None:
        return None
    start = max(usage_start, smoke_start)
    end = min(usage_end, smoke_end)
    return max(0.0, (end - start).total_seconds())


def _usage_amount_for_bursts(
    usage_items: Iterable[dict[str, Any]],
    bursts: Sequence[dict[str, Any]],
) -> list[float]:
    amounts = [0.0 for _ in bursts]
    windows = [_burst_window(burst) for burst in bursts]
    target_ids = [_target_resource_ids(burst) for burst in bursts]
    for item in usage_items:
        raw_amount = _first_value(item, ("computedAmount", "computed_amount"))
        if raw_amount is None:
            raise CostReportError("usage item has no computedAmount")
        amount = _number(raw_amount, field="usage computedAmount")
        if amount < 0:
            raise CostReportError("usage computedAmount must be non-negative")
        usage_start, usage_end = _usage_window(item)
        resource_id = _usage_resource_id(item)
        matching_bursts: list[int] = []
        overlap_weights: dict[int, float] = {}
        for index, ((smoke_start, smoke_end), identifiers) in enumerate(zip(windows, target_ids, strict=True)):
            if identifiers:
                if resource_id is None:
                    if _windows_overlap(usage_start, usage_end, smoke_start, smoke_end):
                        raise CostReportError("usage item overlapping an identified burst has no resourceId")
                    continue
                if resource_id not in identifiers:
                    continue
            elif resource_id is not None:
                continue
            if _windows_overlap(usage_start, usage_end, smoke_start, smoke_end):
                matching_bursts.append(index)
                overlap_weights[index] = (
                    _overlap_seconds(
                        usage_start,
                        usage_end,
                        smoke_start,
                        smoke_end,
                    )
                    or 0.0
                )
        if matching_bursts:
            # A Usage API line can cover an entire granularity bucket. Allocate
            # it across every matching burst by the overlap duration instead of
            # assigning the whole bucket to whichever burst appears first.
            weights = [overlap_weights[index] for index in matching_bursts]
            weight_total = sum(weights)
            if weight_total <= 0:
                weight_total = float(len(matching_bursts))
                weights = [1.0] * len(matching_bursts)
            for index, weight in zip(matching_bursts, weights, strict=True):
                amounts[index] += amount * weight / weight_total
    return [round(amount, 6) for amount in amounts]


def _difference_pct(estimated: float, actual: float) -> float:
    if estimated == 0.0:
        return 0.0 if actual == 0.0 else math.inf
    return abs(actual - estimated) / abs(estimated) * 100.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "usage_json",
        nargs="*",
        metavar="USAGE_JSON",
        help="OCI usage-api JSON export path(s)",
    )
    parser.add_argument(
        "--usage-json",
        "--usage-export",
        "--usage-api-json",
        dest="usage_json_options",
        action="append",
        default=[],
        metavar="PATH",
        help="OCI usage-api JSON export; repeat for multiple exports",
    )
    parser.add_argument(
        "--smoke-report",
        "--smoke-json",
        dest="smoke_report",
        required=True,
        metavar="PATH",
        help="GPU burst smoke JSON evidence report",
    )
    parser.add_argument(
        "--hourly-rate",
        type=float,
        default=DEFAULT_HOURLY_RATE,
        metavar="USD",
        help=f"A10 running rate in USD/hour (default: {DEFAULT_HOURLY_RATE:g})",
    )
    parser.add_argument(
        "--tolerance-pct",
        type=float,
        default=DEFAULT_TOLERANCE_PCT,
        metavar="PERCENT",
        help=f"maximum estimate/ledger disagreement percentage (default: {DEFAULT_TOLERANCE_PCT:g})",
    )
    return parser


def _validate_options(args: argparse.Namespace, usage_paths: Sequence[str]) -> None:
    if not usage_paths:
        raise CostReportError("at least one OCI usage JSON export is required")
    if args.hourly_rate < 0 or not math.isfinite(args.hourly_rate):
        raise CostReportError("--hourly-rate must be finite and non-negative")
    if args.tolerance_pct < 0 or not math.isfinite(args.tolerance_pct):
        raise CostReportError("--tolerance-pct must be finite and non-negative")


def report_costs(
    usage_paths: Sequence[str],
    smoke_path: str,
    *,
    hourly_rate: float = DEFAULT_HOURLY_RATE,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> list[dict[str, Any]]:
    """Return one cost comparison mapping per burst in a smoke report."""

    smoke_bursts = _smoke_bursts(_read_json(smoke_path))
    usage_items: list[dict[str, Any]] = []
    for path in usage_paths:
        usage_items.extend(_usage_items(_read_json(path)))
    usage_amounts = _usage_amount_for_bursts(usage_items, smoke_bursts)
    comparisons: list[dict[str, Any]] = []
    for index, (burst, usage_amount) in enumerate(zip(smoke_bursts, usage_amounts, strict=True), start=1):
        running_seconds = _burst_running_seconds(burst)
        estimated_amount = round(running_seconds * hourly_rate / 3600.0, 6)
        difference_pct = _difference_pct(estimated_amount, usage_amount)
        comparisons.append(
            {
                "burst": index,
                "running_seconds": running_seconds,
                "hourly_rate_usd": hourly_rate,
                "estimated_usd": estimated_amount,
                "usage_api_usd": usage_amount,
                "difference_pct": difference_pct,
                "within_tolerance": difference_pct <= tolerance_pct,
            }
        )
    return comparisons


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        usage_paths = [*args.usage_json, *args.usage_json_options]
        _validate_options(args, usage_paths)
        comparisons = report_costs(
            usage_paths,
            args.smoke_report,
            hourly_rate=args.hourly_rate,
            tolerance_pct=args.tolerance_pct,
        )
    except CostReportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    estimated_total = sum(float(comparison["estimated_usd"]) for comparison in comparisons)
    usage_total = sum(float(comparison["usage_api_usd"]) for comparison in comparisons)
    for comparison in comparisons:
        verdict = "within tolerance" if comparison["within_tolerance"] else "exceeds tolerance"
        difference = comparison["difference_pct"]
        difference_text = "infinite" if math.isinf(difference) else f"{difference:.2f}%"
        print(
            f"Burst {comparison['burst']}: "
            f"running_seconds={comparison['running_seconds']:.3f} "
            f"hourly_rate_usd={comparison['hourly_rate_usd']:.6f} "
            f"estimated_usd={comparison['estimated_usd']:.6f} "
            f"usage_api_usd={comparison['usage_api_usd']:.6f} "
            f"difference_pct={difference_text} {verdict}"
        )
    print(f"Estimated total: ${estimated_total:.6f}")
    print(f"Usage API total: ${usage_total:.6f}")
    return 0 if all(comparison["within_tolerance"] for comparison in comparisons) else 2


if __name__ == "__main__":
    raise SystemExit(main())
