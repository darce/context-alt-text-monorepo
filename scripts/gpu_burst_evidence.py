#!/usr/bin/env python3
"""Check that a read-only OCI GPU evidence bundle proves one complete burst.

The exporter deliberately keeps the OCI responses as JSON receipts.  This
checker therefore accepts the small schema variations emitted by OCI Audit,
the lifecycle reaper, and the WordPress describe route while keeping the
verdict independent of third-party Python packages.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


UTC = dt.timezone.utc
SCHEMA_VERSION = 1


class EvidenceError(ValueError):
    """An evidence document cannot be used for a proof check."""


def _result(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _parse_time(value: Any) -> float | None:
    """Return an epoch timestamp for an ISO-8601 or numeric value."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None and math.isfinite(numeric):
        return numeric
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.timestamp()


def _format_time(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return dt.datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def _as_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalise_state(value: Any) -> str | None:
    text = _as_text(value)
    if text is None:
        return None
    return text.replace("_", "-").replace(" ", "-").upper()


def _safe_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvidenceError(f"missing JSON receipt: {path.name}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"unreadable JSON receipt {path.name}: {exc}") from exc


def _manifest_entries(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = manifest.get("files")
    if raw is None:
        raw = manifest.get("artifacts", manifest.get("entries"))
    entries: list[dict[str, Any]] = []
    if isinstance(raw, Mapping):
        for path, metadata in raw.items():
            if isinstance(metadata, Mapping):
                entries.append({"path": path, **metadata})
            else:
                entries.append({"path": path, "sha256": metadata})
    elif isinstance(raw, list):
        entries = [dict(item) for item in raw if isinstance(item, Mapping)]
    return entries


def _resolve_manifest_path(bundle: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or relative in {"", "."} or ".." in path.parts:
        raise EvidenceError(f"manifest path is not a safe relative file: {relative!r}")
    candidate = (bundle / path).resolve()
    root = bundle.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise EvidenceError(f"manifest path escapes bundle: {relative!r}") from exc
    return candidate


def _verify_manifest(bundle: Path, manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    entries = _manifest_entries(manifest)
    failures: list[str] = []
    if not entries:
        return [], ["manifest has no file entries"]

    listed: set[str] = set()
    verified: list[dict[str, Any]] = []
    for entry in entries:
        relative = entry.get("path")
        digest = entry.get("sha256", entry.get("digest"))
        if not isinstance(relative, str) or not relative:
            failures.append("manifest contains an entry without a path")
            continue
        if relative in listed:
            failures.append(f"manifest lists {relative!r} more than once")
            continue
        listed.add(relative)
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
            failures.append(f"manifest has invalid sha256 for {relative}")
            continue
        try:
            target = _resolve_manifest_path(bundle, relative)
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except (EvidenceError, OSError) as exc:
            failures.append(str(exc))
            continue
        if actual.lower() != digest.lower():
            failures.append(f"sha256 mismatch for {relative}: expected {digest}, got {actual}")
        verified.append({"path": relative, "file": target, **entry})

    # A receipt that is not named by the manifest is not part of the proof.
    # Ignore the manifest itself, which cannot contain its own final digest.
    try:
        actual_files = {
            str(path.relative_to(bundle.resolve()))
            for path in bundle.resolve().rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
    except OSError as exc:
        failures.append(f"cannot enumerate bundle files: {exc}")
        actual_files = set()
    unlisted = sorted(actual_files - listed)
    if unlisted:
        failures.append("unlisted bundle file(s): " + ", ".join(unlisted))
    return verified, failures


def _entry_path(entries: Sequence[Mapping[str, Any]], *names: str, contains: Sequence[str] = ()) -> Path | None:
    wanted = {name.casefold() for name in names}
    for entry in entries:
        path = entry.get("file")
        relative = entry.get("path")
        if not isinstance(path, Path) or not isinstance(relative, str):
            continue
        basename = Path(relative).name.casefold()
        if basename in wanted:
            return path
    for entry in entries:
        path = entry.get("file")
        relative = entry.get("path")
        if not isinstance(path, Path) or not isinstance(relative, str):
            continue
        basename = Path(relative).name.casefold()
        if all(fragment.casefold() in basename for fragment in contains):
            return path
    return None


def _payload_items(payload: Any, keys: Sequence[str]) -> list[Any]:
    """Extract a list from common OCI/API envelope keys."""

    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _nested_values(value: Any, keys: Sequence[str], *, depth: int = 3) -> Iterable[Any]:
    if depth < 0:
        return
    if isinstance(value, Mapping):
        for key in keys:
            if key in value:
                yield value[key]
        if depth:
            for child in value.values():
                if isinstance(child, Mapping):
                    yield from _nested_values(child, keys, depth=depth - 1)


def _first_value(value: Any, keys: Sequence[str]) -> Any:
    for candidate in _nested_values(value, keys):
        if candidate is not None:
            return candidate
    return None


def _instance_id_from_payload(payload: Any) -> str | None:
    value = _first_value(payload, ("id", "instance_id", "instanceId"))
    return _as_text(value)


def _state_from_mapping(value: Mapping[str, Any]) -> str | None:
    for key in (
        "lifecycle-state",
        "lifecycle_state",
        "lifecycleState",
        "gpu_state",
        "gpuState",
        "state",
    ):
        state = _normalise_state(value.get(key))
        if state is not None:
            return state
    return None


def _instance_state(payload: Any) -> str | None:
    candidates: list[Any] = []
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, Mapping):
            candidates.append(data)
        elif isinstance(data, list):
            candidates.extend(reversed(data))
        candidates.append(payload)
    elif isinstance(payload, list):
        candidates.extend(reversed(payload))
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            state = _state_from_mapping(candidate)
            if state is not None:
                return state
    return None


def _state_observations(payload: Any) -> list[tuple[float, str, str]]:
    """Read ``(timestamp, state, source)`` triples from state history JSON."""

    if isinstance(payload, Mapping):
        for key in ("observations", "states", "state_history", "state-history", "history", "transitions"):
            value = payload.get(key)
            if isinstance(value, list):
                return _state_observations(value)
        data = payload.get("data")
        if isinstance(data, list):
            return _state_observations(data)
        for key in ("instance", "history", "state_history", "data", "value"):
            value = payload.get(key)
            if isinstance(value, Mapping | list):
                observations = _state_observations(value)
                if observations:
                    return observations
        state = _state_from_mapping(payload)
        timestamp = _parse_time(
            next(
                (
                    payload.get(key)
                    for key in (
                        "timestamp",
                        "time",
                        "observed_at",
                        "observedAt",
                        "eventTime",
                        "event_time",
                        "at",
                        "written_at",
                        "writtenAt",
                    )
                    if payload.get(key) is not None
                ),
                None,
            )
        )
        if state is not None and timestamp is not None:
            return [(timestamp, state, "state-history")]
        return []
    if isinstance(payload, list):
        result: list[tuple[float, str, str]] = []
        for item in payload:
            result.extend(_state_observations(item))
        return result
    return []


def _audit_items(payload: Any) -> list[Mapping[str, Any]]:
    items = _payload_items(payload, ("events", "items", "audit_events", "audit-events"))
    return [item for item in items if isinstance(item, Mapping)]


def _event_time(event: Mapping[str, Any]) -> float | None:
    for key in ("eventTime", "event_time", "timestamp", "time", "created_at", "createdAt"):
        if event.get(key) is not None:
            value = _parse_time(event[key])
            if value is not None:
                return value
    return _parse_time(_first_value(event, ("eventTime", "event_time", "timestamp", "time")))


def _event_resource_id(event: Mapping[str, Any]) -> str | None:
    value = _first_value(event, ("resourceId", "resource_id", "instanceId", "instance_id"))
    return _as_text(value)


def _event_actions(event: Mapping[str, Any]) -> set[str]:
    values: list[Any] = []
    for key in ("eventName", "event_name", "eventType", "event_type", "action", "operation"):
        if key in event:
            values.append(event[key])
    values.extend(_nested_values(event, ("action", "actionName", "action_name", "operation"), depth=3))
    actions: set[str] = set()
    for value in values:
        if isinstance(value, list):
            values.extend(value)
            continue
        text = _as_text(value)
        if text is None:
            continue
        upper = text.upper()
        if "STARTINSTANCE" in upper or upper in {"START", "START_INSTANCE"}:
            actions.add("START")
        if "STOPINSTANCE" in upper or upper in {"STOP", "STOP_INSTANCE"}:
            actions.add("STOP")
    return actions


def _event_phase(event: Mapping[str, Any]) -> str | None:
    value = event.get("eventType", event.get("event_type"))
    text = _as_text(value)
    if text is None:
        return None
    lower = text.casefold()
    if lower.endswith(".end") or lower.endswith("_end") or lower.endswith("-end"):
        return "end"
    if lower.endswith(".begin") or lower.endswith("_begin") or lower.endswith("-begin"):
        return "begin"
    return None


def _event_identity(event: Mapping[str, Any], action: str) -> str:
    value = _first_value(event, ("eventId", "event_id", "requestId", "request_id", "id"))
    text = _as_text(value)
    if text is not None:
        return f"id:{text}"
    timestamp = _event_time(event)
    resource = _event_resource_id(event) or ""
    return f"fallback:{action}:{resource}:{timestamp!r}"


def _authoritative_audit_events(
    payload: Any,
    *,
    instance_id: str | None,
    since: float,
    until: float,
) -> list[tuple[str, Mapping[str, Any], float]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for event in _audit_items(payload):
        resource = _event_resource_id(event)
        if instance_id is not None and resource is not None and resource != instance_id:
            continue
        for action in _event_actions(event):
            grouped.setdefault((action, _event_identity(event, action)), []).append(event)

    authoritative: list[tuple[str, Mapping[str, Any], float]] = []
    for (action, _identity), events in grouped.items():
        completed = [event for event in events if _event_phase(event) == "end"]
        # OCI emits begin/end pairs for an action.  A completed record is the
        # authoritative receipt; simple fixtures without a phase are already
        # complete and remain eligible.
        candidates = completed or [event for event in events if _event_phase(event) is None]
        if not candidates:
            continue
        event = sorted(candidates, key=lambda item: _event_time(item) or float("-inf"))[-1]
        timestamp = _event_time(event)
        if timestamp is not None and since <= timestamp <= until:
            authoritative.append((action, event, timestamp))
    authoritative.sort(key=lambda item: item[2])
    return authoritative


def _principal(event: Mapping[str, Any]) -> str | None:
    principals = _principal_values(event)
    return next(iter(principals), None)


def _principal_values(event: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in (
        "principalName",
        "principal_name",
        "principalId",
        "principal_id",
        "principal",
        "userName",
        "username",
        "actor",
        "createdBy",
        "created_by",
    ):
        for value in _nested_values(event, (key,)):
            text = _as_text(value)
            if text is not None:
                values.add(text)
    return values


def _running_intervals(observations: Sequence[tuple[float, str, str]]) -> list[tuple[float, float]]:
    ordered = sorted(observations, key=lambda item: item[0])
    intervals: list[tuple[float, float]] = []
    running_since: float | None = None
    for timestamp, state, _source in ordered:
        if state == "RUNNING" and running_since is None:
            running_since = timestamp
        elif state == "STOPPED" and running_since is not None:
            intervals.append((running_since, timestamp))
            running_since = None
    return intervals


def _description_value(item: Mapping[str, Any]) -> str | None:
    for key in ("description", "alt_text", "alt-text", "alt_text_draft", "altText", "caption", "text"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            nested = _first_value(value, ("text", "value", "content"))
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _receipt_items(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("receipts", "items", "descriptions", "results", "data", "value"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            nested = _receipt_items(value)
            if nested:
                return nested
    return [payload]


def _receipt_time(item: Mapping[str, Any]) -> float | None:
    for key in (
        "timestamp",
        "time",
        "created_at",
        "createdAt",
        "completed_at",
        "completedAt",
        "described_at",
        "describedAt",
        "updated_at",
        "updatedAt",
        "finished_at",
        "finishedAt",
    ):
        if item.get(key) is not None:
            value = _parse_time(item[key])
            if value is not None:
                return value
    return _parse_time(
        _first_value(
            item,
            (
                "timestamp",
                "created_at",
                "createdAt",
                "completed_at",
                "completedAt",
                "finished_at",
                "finishedAt",
            ),
        )
    )


def _window_from_args(manifest: Mapping[str, Any], since: str | None, until: str | None) -> tuple[float | None, float | None, str | None, str | None, str | None]:
    since_value = since if since is not None else manifest.get("since")
    until_value = until if until is not None else manifest.get("until")
    since_text = since_value if isinstance(since_value, str) else str(since_value) if since_value is not None else None
    until_text = until_value if isinstance(until_value, str) else str(until_value) if until_value is not None else None
    since_epoch = _parse_time(since_text)
    until_epoch = _parse_time(until_text)
    error: str | None = None
    if since_epoch is None or until_epoch is None:
        error = "since and until must be timezone-aware ISO-8601 timestamps or epoch seconds"
    elif since_epoch > until_epoch:
        error = "since must not be later than until"
    return since_epoch, until_epoch, since_text, until_text, error


def check_bundle(
    bundle: str | Path,
    *,
    since: str | None = None,
    until: str | None = None,
    expected_stop_principal: str,
    min_descriptions: int = 1,
) -> dict[str, Any]:
    """Return a machine-readable verdict for one evidence bundle."""

    bundle_path = Path(bundle)
    checks: list[dict[str, Any]] = []
    manifest: Mapping[str, Any] = {}
    entries: list[dict[str, Any]] = []
    if not bundle_path.is_dir():
        checks.append(_result("bundle_directory", False, f"bundle directory is missing: {bundle_path}"))
        return _verdict(bundle_path, checks)

    manifest_path = bundle_path / "manifest.json"
    try:
        loaded_manifest = _safe_json(manifest_path)
        if not isinstance(loaded_manifest, Mapping):
            raise EvidenceError("manifest.json must contain an object")
        manifest = loaded_manifest
        entries, manifest_failures = _verify_manifest(bundle_path, manifest)
        checks.append(
            _result(
                "manifest_sha256",
                not manifest_failures,
                "all listed files match their sha256" if not manifest_failures else "; ".join(manifest_failures),
            )
        )
    except EvidenceError as exc:
        checks.append(_result("manifest_sha256", False, str(exc)))
        return _verdict(bundle_path, checks)

    since_epoch, until_epoch, since_text, until_text, window_error = _window_from_args(manifest, since, until)
    checks.append(
        _result(
            "capture_window",
            window_error is None,
            (
                f"{since_text} .. {until_text}"
                if window_error is None
                else window_error
            ),
        )
    )
    if window_error is not None or since_epoch is None or until_epoch is None:
        return _verdict(bundle_path, checks, since=since_text, until=until_text)

    instance_path = _entry_path(entries, "instance.json", "oci-instance.json", "instance-state.json", contains=("instance",))
    history_path = _entry_path(
        entries,
        "state_history.json",
        "state-history.json",
        "instance-state-history.json",
        "oci-instance-state-history.json",
        contains=("state", "history"),
    )
    audit_path = _entry_path(
        entries,
        "audit-events.json",
        "audit_events.json",
        "audit.json",
        "oci-audit-events.json",
        contains=("audit",),
    )
    snapshot_path = _entry_path(
        entries,
        "state_snapshot.json",
        "state-snapshot.json",
        "reaper-state-snapshot.json",
        "reaper_snapshot.json",
        "gpu-state.json",
        contains=("snapshot",),
    )
    receipts_path = _entry_path(
        entries,
        "wp_describe_receipts.json",
        "wp-describe-receipts.json",
        "wp-receipts.json",
        "describe-receipts.json",
        "describe_receipts.json",
        "receipts.json",
        contains=("receipt",),
    )

    instance_payload: Any = None
    if instance_path is None:
        checks.append(_result("oci_instance_receipt", False, "instance.json receipt is missing"))
    else:
        try:
            instance_payload = _safe_json(instance_path)
            checks.append(_result("oci_instance_receipt", True, f"loaded {instance_path.name}"))
        except EvidenceError as exc:
            checks.append(_result("oci_instance_receipt", False, str(exc)))

    manifest_instance_id = _as_text(manifest.get("instance_id", manifest.get("instanceId")))
    instance_id = manifest_instance_id or _instance_id_from_payload(instance_payload)
    if manifest_instance_id and instance_payload is not None:
        payload_id = _instance_id_from_payload(instance_payload)
        checks.append(
            _result(
                "instance_identity",
                payload_id is None or payload_id == manifest_instance_id,
                f"manifest instance_id={manifest_instance_id}" if payload_id in {None, manifest_instance_id} else f"instance receipt identifies {payload_id}, expected {manifest_instance_id}",
            )
        )

    state_payload: Any = None
    observations: list[tuple[float, str, str]] = []
    if history_path is not None:
        try:
            state_payload = _safe_json(history_path)
            observations = _state_observations(state_payload)
        except EvidenceError as exc:
            checks.append(_result("state_history_receipt", False, str(exc)))
    else:
        checks.append(_result("state_history_receipt", False, "state_history.json receipt is missing"))

    in_window_observations = [
        item for item in observations if since_epoch <= item[0] <= until_epoch
    ]
    states: list[str] = []
    for _timestamp, state, _source in sorted(in_window_observations, key=lambda item: item[0]):
        if not states or states[-1] != state:
            states.append(state)
    sequence_ok = any(states[index : index + 3] == ["STOPPED", "RUNNING", "STOPPED"] for index in range(max(0, len(states) - 2)))
    checks.append(
        _result(
            "state_history_burst",
            sequence_ok,
            "observed STOPPED -> RUNNING -> STOPPED inside capture window"
            if sequence_ok
            else f"observed state sequence {states or ['none']}; expected STOPPED -> RUNNING -> STOPPED",
        )
    )
    intervals = _running_intervals(in_window_observations)

    final_state = _instance_state(instance_payload)
    checks.append(
        _result(
            "oci_final_state",
            final_state == "STOPPED",
            f"final OCI lifecycle state is {final_state or 'missing'}" if final_state != "STOPPED" else "final OCI lifecycle state is STOPPED",
        )
    )

    audit_payload: Any = None
    if audit_path is None:
        checks.append(_result("audit_receipt", False, "audit-events.json receipt is missing"))
        audit_events: list[tuple[str, Mapping[str, Any], float]] = []
    else:
        try:
            audit_payload = _safe_json(audit_path)
            audit_events = _authoritative_audit_events(
                audit_payload,
                instance_id=instance_id,
                since=since_epoch,
                until=until_epoch,
            )
            checks.append(_result("audit_receipt", True, f"loaded {audit_path.name}"))
        except EvidenceError as exc:
            checks.append(_result("audit_receipt", False, str(exc)))
            audit_events = []

    starts = [(event, timestamp) for action, event, timestamp in audit_events if action == "START"]
    stops = [(event, timestamp) for action, event, timestamp in audit_events if action == "STOP"]
    checks.append(
        _result(
            "exactly_one_start_instance",
            len(starts) == 1,
            "exactly one StartInstance audit event"
            if len(starts) == 1
            else f"observed {len(starts)} StartInstance audit events",
        )
    )
    matching_stops = [
        (event, timestamp)
        for event, timestamp in stops
        if expected_stop_principal in _principal_values(event)
    ]
    checks.append(
        _result(
            "expected_stop_principal",
            bool(matching_stops),
            f"observed StopInstance by {expected_stop_principal}"
            if matching_stops
            else f"no StopInstance audit event matched principal {expected_stop_principal!r} (observed {len(stops)})",
        )
    )

    if snapshot_path is None:
        checks.append(_result("reaper_snapshot", True, "state snapshot not supplied (optional)"))
    else:
        try:
            snapshot = _safe_json(snapshot_path)
            written_at = _parse_time(
                _first_value(snapshot, ("written_at", "writtenAt", "timestamp", "captured_at", "capturedAt"))
            )
            snapshot_state = _normalise_state(
                _first_value(snapshot, ("gpu_state", "gpuState", "lifecycle-state", "lifecycle_state", "state"))
            )
            written_ok = written_at is not None and since_epoch <= written_at <= until_epoch
            state_ok = snapshot_state == final_state == "STOPPED"
            checks.append(
                _result(
                    "reaper_snapshot",
                    written_ok and state_ok,
                    (
                        f"written_at={_format_time(written_at)} and gpu_state=STOPPED agree with final OCI state"
                        if written_ok and state_ok
                        else f"written_at={_format_time(written_at)}, gpu_state={snapshot_state or 'missing'}, final OCI state={final_state or 'missing'}"
                    ),
                )
            )
        except EvidenceError as exc:
            checks.append(_result("reaper_snapshot", False, str(exc)))

    if receipts_path is None:
        checks.append(
            _result(
                "wp_descriptions",
                True,
                "WP describe receipts not supplied (optional)",
            )
        )
    else:
        try:
            receipts_payload = _safe_json(receipts_path)
            receipt_items = _receipt_items(receipts_payload)
            valid_receipts = []
            for item in receipt_items:
                description = _description_value(item)
                timestamp = _receipt_time(item)
                in_running = timestamp is not None and any(start <= timestamp <= stop for start, stop in intervals)
                if description is not None and in_running:
                    valid_receipts.append(item)
            descriptions_ok = len(valid_receipts) >= min_descriptions
            checks.append(
                _result(
                    "wp_descriptions",
                    descriptions_ok,
                    f"{len(valid_receipts)} description receipt(s) inside RUNNING interval; required {min_descriptions}",
                )
            )
        except EvidenceError as exc:
            checks.append(_result("wp_descriptions", False, str(exc)))

    return _verdict(
        bundle_path,
        checks,
        since=since_text,
        until=until_text,
        instance_id=instance_id,
    )


def _verdict(
    bundle: Path,
    checks: Sequence[Mapping[str, Any]],
    *,
    since: str | None = None,
    until: str | None = None,
    instance_id: str | None = None,
) -> dict[str, Any]:
    failed = [dict(check) for check in checks if not check.get("passed")]
    passed = not failed
    return {
        "verdict": "PASS" if passed else "FAIL",
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "ok": passed,
        "bundle": str(bundle),
        "since": since,
        "until": until,
        "instance_id": instance_id,
        "checks": [dict(check) for check in checks],
        "failures": failed,
    }


def _positive_or_zero(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_positional", nargs="?", help="bundle directory (or use --bundle)")
    parser.add_argument("--bundle", "--bundle-dir", dest="bundle", help="evidence bundle directory")
    parser.add_argument("--since", help="inclusive UTC/ISO-8601 capture-window start (defaults to manifest)")
    parser.add_argument("--until", help="inclusive UTC/ISO-8601 capture-window end (defaults to manifest)")
    parser.add_argument("--expected-stop-principal", required=True, help="principal expected to stop the instance")
    parser.add_argument("--min-descriptions", type=_positive_or_zero, default=1, help="minimum valid WP descriptions (default: 1)")
    parser.add_argument("--json", action="store_true", help="emit only the JSON verdict")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    bundle = args.bundle or args.bundle_positional
    if not bundle:
        parser.error("one of --bundle or a bundle directory positional argument is required")
    if not args.expected_stop_principal.strip():
        parser.error("--expected-stop-principal must not be empty")
    verdict = check_bundle(
        bundle,
        since=args.since,
        until=args.until,
        expected_stop_principal=args.expected_stop_principal,
        min_descriptions=args.min_descriptions,
    )
    if args.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))
    else:
        print("Check                                      Result  Detail")
        print("----------------------------------------- ------- ----------------------------------------")
        for check in verdict["checks"]:
            result = "PASS" if check["passed"] else "FAIL"
            print(f"{check['name']:<41} {result:<7} {check['detail']}")
        print(f"\nVERDICT: {verdict['verdict']}")
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
