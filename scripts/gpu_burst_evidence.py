#!/usr/bin/env python3
"""Check that a read-only OCI GPU evidence bundle proves one complete burst.

The exporter keeps the OCI responses as JSON receipts.  This checker accepts
the small schema variations emitted by OCI Audit, the lifecycle reaper, and
the WordPress describe route while keeping the verdict independent of
third-party Python packages.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

UTC = dt.UTC
SCHEMA_VERSION = 1
MANIFEST_FORMAT = "oci-gpu-burst-evidence-v1"


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
    numeric_text: float | None
    try:
        numeric_text = float(text)
    except ValueError:
        numeric_text = None
    if numeric_text is not None and math.isfinite(numeric_text):
        return numeric_text
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


def _nested_values(value: Any, keys: Sequence[str], *, depth: int = 4) -> Iterable[Any]:
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
    return next((candidate for candidate in _nested_values(value, keys) if candidate is not None), None)


def _manifest_entries(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = manifest.get("files")
    if raw is None:
        raw = manifest.get("artifacts", manifest.get("entries"))
    if isinstance(raw, Mapping):
        return [
            {"path": path, **metadata} if isinstance(metadata, Mapping) else {"path": path, "sha256": metadata}
            for path, metadata in raw.items()
        ]
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, Mapping)]
    return []


def _resolve_manifest_path(bundle: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or relative in {"", "."} or ".." in path.parts:
        raise EvidenceError(f"manifest path is not a safe relative file: {relative!r}")
    candidate = (bundle / path).resolve()
    try:
        candidate.relative_to(bundle.resolve())
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
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in digest)
        ):
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
        if isinstance(path, Path) and isinstance(relative, str) and Path(relative).name.casefold() in wanted:
            return path
    for entry in entries:
        path = entry.get("file")
        relative = entry.get("path")
        if isinstance(path, Path) and isinstance(relative, str):
            basename = Path(relative).name.casefold()
            if all(fragment.casefold() in basename for fragment in contains):
                return path
    return None


def _payload_items(payload: Any, keys: Sequence[str]) -> list[Any]:
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


def _instance_id_from_payload(payload: Any) -> str | None:
    return _as_text(_first_value(payload, ("id", "instance_id", "instanceId")))


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
            if isinstance(value, (Mapping, list)):
                observations = _state_observations(value)
                if observations:
                    return observations
        data = payload.get("data")
        if isinstance(data, list):
            return _state_observations(data)
        if _observation_is_inferred(payload):
            return []
        state = _state_from_mapping(payload)
        timestamp = _parse_time(
            _first_value(
                payload,
                (
                    "timestamp",
                    "time",
                    "observed_at",
                    "observedAt",
                    "eventTime",
                    "event_time",
                    "at",
                    "written_at",
                    "writtenAt",
                    "generated_at",
                    "generatedAt",
                ),
            )
        )
        return [(timestamp, state, "state-history")] if state is not None and timestamp is not None else []
    if isinstance(payload, list):
        result: list[tuple[float, str, str]] = []
        for item in payload:
            result.extend(_state_observations(item))
        return result
    return []


def _observation_is_inferred(value: Mapping[str, Any]) -> bool:
    """Return whether a state observation was synthesized rather than observed."""

    for key in ("inferred", "is_inferred", "synthetic", "synthesized"):
        flag = value.get(key)
        if flag is True:
            return True
        if isinstance(flag, str) and flag.strip().casefold() in {"true", "yes", "1", "inferred", "synthetic"}:
            return True
    source = _as_text(value.get("source"))
    return source is not None and source.casefold() in {"inferred", "inferred_boundary", "synthetic", "synthesized"}


def _inferred_observation_count(payload: Any) -> int:
    if isinstance(payload, Mapping):
        own = int(_state_from_mapping(payload) is not None and _observation_is_inferred(payload))
        return own + sum(_inferred_observation_count(child) for child in payload.values())
    if isinstance(payload, list):
        return sum(_inferred_observation_count(child) for child in payload)
    return 0


def _audit_items(payload: Any) -> list[Mapping[str, Any]]:
    return [
        item
        for item in _payload_items(payload, ("events", "items", "audit_events", "audit-events"))
        if isinstance(item, Mapping)
    ]


def _event_time(event: Mapping[str, Any]) -> float | None:
    keys = ("eventTime", "event_time", "timestamp", "time", "created_at", "createdAt")
    for key in keys:
        if event.get(key) is not None:
            value = _parse_time(event[key])
            if value is not None:
                return value
    return _parse_time(_first_value(event, keys))


def _event_resource_id(event: Mapping[str, Any]) -> str | None:
    return _as_text(_first_value(event, ("resourceId", "resource_id")))


def _action_from_value(value: Any) -> str | None:
    text = _as_text(value)
    if text is None:
        return None
    text = re.sub(r"[._ -]+(?:BEGIN|END)$", "", text, flags=re.IGNORECASE)
    action = re.sub(r"[._ -]+", "", text).upper()
    if action in {"START", "STARTINSTANCE"}:
        return "START"
    if action in {"STOP", "STOPINSTANCE"}:
        return "STOP"
    return None


def _event_actions(event: Mapping[str, Any]) -> set[str]:
    values: list[Any] = []
    action_keys = ("eventName", "event_name", "eventType", "event_type", "action", "operation")
    for key in action_keys:
        if key in event:
            values.append(event[key])
    values.extend(_nested_values(event, action_keys))
    actions: set[str] = set()
    while values:
        value = values.pop()
        if isinstance(value, list):
            values.extend(value)
            continue
        action = _action_from_value(value)
        if action is not None:
            actions.add(action)
    return actions


def _event_phase(event: Mapping[str, Any]) -> str | None:
    text = _as_text(_first_value(event, ("eventType", "event_type")))
    if text is None:
        return None
    lower = text.casefold()
    if lower.endswith((".end", "_end", "-end")):
        return "end"
    if lower.endswith((".begin", "_begin", "-begin")):
        return "begin"
    return None


def _event_identity(event: Mapping[str, Any], action: str, occurrence: int) -> str:
    value = _as_text(_first_value(event, ("eventId", "event_id", "requestId", "request_id", "id")))
    if value is not None:
        return f"id:{value}"
    return f"fallback:{action}:{_event_resource_id(event) or ''}:{_event_time(event)!r}:{occurrence}"


def _response_status_values(value: Any) -> Iterable[Any]:
    """Yield status values only from fields that identify an OCI response."""

    if not isinstance(value, Mapping):
        return
    for key in ("responseStatus", "response_status"):
        candidate = value.get(key)
        if candidate is not None:
            yield candidate
    for key in ("response", "responseData", "response_data"):
        response = value.get(key)
        if isinstance(response, Mapping):
            for status_key in ("status", "statusCode", "status_code", "code", "result"):
                candidate = response.get(status_key)
                if candidate is not None:
                    yield candidate
        elif response is not None:
            yield response
    for child in value.values():
        if isinstance(child, Mapping):
            yield from _response_status_values(child)
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, Mapping):
                    yield from _response_status_values(item)


def _event_status(event: Mapping[str, Any]) -> Any:
    """Return one unambiguous OCI response status, or ``None``."""

    values = list(_response_status_values(event))
    return values[0] if len(values) == 1 else None


def _status_success(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 200 <= value < 300
    if isinstance(value, Mapping):
        return _status_success(_first_value(value, ("status", "statusCode", "status_code", "code", "result")))
    text = _as_text(value)
    if text is None:
        return False
    upper = text.upper()
    if upper in {"OK", "SUCCESS", "SUCCEEDED", "COMPLETE", "COMPLETED"}:
        return True
    match = re.search(r"\b([2-9][0-9]{2})\b", upper)
    return match is not None and 200 <= int(match.group(1)) < 300


def _authoritative_audit_events(
    payload: Any,
    *,
    instance_id: str | None,
    since: float,
    until: float,
) -> list[tuple[str, Mapping[str, Any], float]]:
    """Return successful, completed audit transitions for exactly one instance."""

    if instance_id is None:
        return []
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for occurrence, event in enumerate(_audit_items(payload)):
        if _event_resource_id(event) != instance_id:
            continue
        for action in _event_actions(event):
            grouped.setdefault((action, _event_identity(event, action, occurrence)), []).append(event)

    authoritative: list[tuple[str, Mapping[str, Any], float]] = []
    for (action, _identity), events in grouped.items():
        completed = [event for event in events if _event_phase(event) == "end"]
        candidates = completed or [event for event in events if _event_phase(event) is None]
        if not candidates:
            continue

        def event_sort_key(item: Mapping[str, Any]) -> float:
            timestamp = _event_time(item)
            return timestamp if timestamp is not None else float("-inf")

        event = max(candidates, key=event_sort_key)
        timestamp = _event_time(event)
        if timestamp is None or not since <= timestamp <= until or not _status_success(_event_status(event)):
            continue
        authoritative.append((action, event, timestamp))
    authoritative.sort(key=lambda item: item[2])
    return authoritative


def _successful_audit_action_sequence(
    payload: Any,
    *,
    instance_id: str | None,
    since: float,
    until: float,
) -> list[str]:
    """Read the raw successful action order before event identities are collapsed."""

    if instance_id is None:
        return []
    ordered: list[tuple[float, int, str]] = []
    for position, event in enumerate(_audit_items(payload)):
        if _event_resource_id(event) != instance_id:
            continue
        timestamp = _event_time(event)
        if timestamp is None or not since <= timestamp <= until or not _status_success(_event_status(event)):
            continue
        for action in sorted(_event_actions(event)):
            ordered.append((timestamp, position, action))
    ordered.sort(key=lambda item: (item[0], item[1]))
    return [action for _timestamp, _position, action in ordered]


def _principal_values(event: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    keys = (
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
    )
    for value in _nested_values(event, keys):
        text = _as_text(value)
        if text is not None:
            values.add(text)
    return values


def _running_intervals(observations: Sequence[tuple[float, str, str]]) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    running_since: float | None = None
    for timestamp, state, _source in sorted(observations, key=lambda item: item[0]):
        if state == "RUNNING" and running_since is None:
            running_since = timestamp
        elif state == "STOPPED" and running_since is not None:
            intervals.append((running_since, timestamp))
            running_since = None
    return intervals


def _state_sequence(observations: Sequence[tuple[float, str, str]]) -> list[str]:
    sequence: list[str] = []
    for _timestamp, state, _source in sorted(observations, key=lambda item: item[0]):
        if not sequence or sequence[-1] != state:
            sequence.append(state)
    return sequence


def _state_order_is_valid(observations: Sequence[tuple[float, str, str]]) -> bool:
    """Validate lifecycle phases from raw observations before state collapsing."""

    phase = 0
    for _timestamp, state, _source in sorted(observations, key=lambda item: item[0]):
        if phase == 0:
            if state == "STOPPED":
                continue
            if state == "RUNNING":
                phase = 1
                continue
            return False
        if phase == 1:
            if state == "RUNNING":
                continue
            if state == "STOPPED":
                phase = 2
                continue
            return False
        if state != "STOPPED":
            return False
    return phase == 2


def _state_action_sequence(payload: Any) -> list[tuple[float, str]]:
    """Read transition actions in raw receipt order when the history records them."""

    sequence: list[tuple[float, str]] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if _state_from_mapping(value) is not None and not _observation_is_inferred(value):
                timestamp = _parse_time(
                    _first_value(
                        value,
                        (
                            "timestamp",
                            "time",
                            "observed_at",
                            "observedAt",
                            "eventTime",
                            "event_time",
                            "at",
                        ),
                    )
                )
                if timestamp is not None:
                    sequence.extend((timestamp, action) for action in sorted(_event_actions(value)))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return sequence


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
    keys = (
        "timestamp",
        "time",
        "generated_at",
        "generatedAt",
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
    )
    for key in keys:
        if item.get(key) is not None:
            value = _parse_time(item[key])
            if value is not None:
                return value
    return _parse_time(_first_value(item, keys))


def _window_from_args(
    manifest: Mapping[str, Any], since: str | None, until: str | None
) -> tuple[float | None, float | None, str | None, str | None, str | None]:
    since_value = since if since is not None else manifest.get("since")
    until_value = until if until is not None else manifest.get("until")
    since_text = since_value if isinstance(since_value, str) else str(since_value) if since_value is not None else None
    until_text = until_value if isinstance(until_value, str) else str(until_value) if until_value is not None else None
    since_epoch = _parse_time(since_text)
    until_epoch = _parse_time(until_text)
    if since_epoch is None or until_epoch is None:
        return (
            since_epoch,
            until_epoch,
            since_text,
            until_text,
            "since and until must be timezone-aware ISO-8601 timestamps or epoch seconds",
        )
    if since_epoch > until_epoch:
        return since_epoch, until_epoch, since_text, until_text, "since must not be later than until"
    return since_epoch, until_epoch, since_text, until_text, None


def _manifest_schema_check(manifest: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    version = manifest.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version != SCHEMA_VERSION:
        failures.append(f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}")
    manifest_format = manifest.get("format")
    if manifest_format != MANIFEST_FORMAT:
        failures.append(f"unsupported format {manifest_format!r}; expected {MANIFEST_FORMAT!r}")
    return _result(
        "manifest_schema", not failures, "supported manifest schema" if not failures else "; ".join(failures)
    )


def _receipt_paths(entries: Sequence[Mapping[str, Any]]) -> dict[str, Path | None]:
    return {
        "instance": _entry_path(
            entries, "instance.json", "oci-instance.json", "instance-state.json", contains=("instance",)
        ),
        "history": _entry_path(
            entries,
            "state_history.json",
            "state-history.json",
            "instance-state-history.json",
            "oci-instance-state-history.json",
            contains=("state", "history"),
        ),
        "audit": _entry_path(
            entries,
            "audit-events.json",
            "audit_events.json",
            "audit.json",
            "oci-audit-events.json",
            contains=("audit",),
        ),
        "snapshot": _entry_path(
            entries,
            "state_snapshot.json",
            "state-snapshot.json",
            "reaper-state-snapshot.json",
            "reaper_snapshot.json",
            "gpu-state.json",
            contains=("snapshot",),
        ),
        "receipts": _entry_path(
            entries,
            "wp_describe_receipts.json",
            "wp-describe-receipts.json",
            "wp-receipts.json",
            "describe-receipts.json",
            "describe_receipts.json",
            "receipts.json",
            contains=("receipt",),
        ),
    }


def _load_required(path: Path | None, name: str) -> tuple[Any, dict[str, Any]]:
    if path is None:
        missing_names = {
            "oci_instance_receipt": "instance.json",
            "state_history_receipt": "state_history.json",
            "audit_receipt": "audit-events.json",
        }
        return None, _result(name, False, f"{missing_names.get(name, name)} receipt is missing")
    try:
        payload = _safe_json(path)
    except EvidenceError as exc:
        return None, _result(name, False, str(exc))
    return payload, _result(name, True, f"loaded {path.name}")


def _instance_checks(
    path: Path | None, manifest_instance_id: str | None
) -> tuple[Any, str | None, list[dict[str, Any]]]:
    payload, receipt_check = _load_required(path, "oci_instance_receipt")
    payload_id = _instance_id_from_payload(payload)
    if manifest_instance_id is None:
        identity_check = _result("instance_identity", False, "manifest instance_id is required")
    elif payload_id is None:
        identity_check = _result("instance_identity", False, "instance receipt is missing an instance id")
    elif payload_id != manifest_instance_id:
        identity_check = _result(
            "instance_identity",
            False,
            f"instance receipt identifies {payload_id}, expected {manifest_instance_id}",
        )
    else:
        identity_check = _result("instance_identity", True, f"manifest instance_id={manifest_instance_id}")
    return payload, payload_id, [receipt_check, identity_check]


def _history_instance_id(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    for key in ("instance_id", "instanceId"):
        value = _as_text(payload.get(key))
        if value is not None:
            return value
    data = payload.get("data")
    if isinstance(data, Mapping):
        return _as_text(data.get("id", data.get("instance_id", data.get("instanceId"))))
    return None


def _state_checks(
    path: Path | None, *, since: float, until: float, expected_instance_id: str | None
) -> tuple[Any, list[tuple[float, str, str]], list[dict[str, Any]]]:
    payload, receipt_check = _load_required(path, "state_history_receipt")
    observations = _state_observations(payload)
    in_window = [item for item in observations if since <= item[0] <= until]
    raw_order_ok = _state_order_is_valid(in_window)
    sequence = _state_sequence(in_window)
    history_actions = [action for timestamp, action in _state_action_sequence(payload) if since <= timestamp <= until]
    action_order_ok = not history_actions or (
        history_actions[0] == "START" and any(action == "STOP" for action in history_actions[1:])
    )
    inferred_count = _inferred_observation_count(payload)
    history_id = _history_instance_id(payload)
    identity_ok = history_id is None or history_id == expected_instance_id
    identity_detail = (
        "state history has no explicit instance id"
        if history_id is None
        else f"state history identifies {history_id}, expected {expected_instance_id}"
    )
    passed = raw_order_ok and action_order_ok and sequence == ["STOPPED", "RUNNING", "STOPPED"]
    detail = (
        "observed STOPPED -> RUNNING -> STOPPED inside capture window"
        if passed
        else (
            f"observed state sequence {sequence or ['none']}; expected STOPPED -> RUNNING -> STOPPED"
            + (f"; ignored {inferred_count} inferred observation(s)" if inferred_count else "")
            + ("; state history transition order is invalid" if not action_order_ok else "")
        )
    )
    return (
        payload,
        in_window,
        [
            receipt_check,
            _result("state_history_identity", identity_ok, identity_detail),
            _result("state_history_burst", passed, detail),
        ],
    )


def _audit_checks(
    path: Path | None,
    *,
    instance_id: str | None,
    since: float,
    until: float,
    expected_stop_principal: str,
) -> tuple[list[tuple[str, Mapping[str, Any], float]], list[dict[str, Any]]]:
    payload, receipt_check = _load_required(path, "audit_receipt")
    events = (
        _authoritative_audit_events(payload, instance_id=instance_id, since=since, until=until)
        if payload is not None
        else []
    )
    starts = [(event, timestamp) for action, event, timestamp in events if action == "START"]
    stops = [(event, timestamp) for action, event, timestamp in events if action == "STOP"]
    start_check = _result(
        "exactly_one_start_instance",
        len(starts) == 1,
        "exactly one StartInstance audit event"
        if len(starts) == 1
        else f"observed {len(starts)} StartInstance audit events",
    )
    matching_stops = [
        (event, timestamp) for event, timestamp in stops if expected_stop_principal in _principal_values(event)
    ]
    principal_check = _result(
        "expected_stop_principal",
        bool(matching_stops),
        f"observed StopInstance by {expected_stop_principal}"
        if matching_stops
        else f"no StopInstance audit event matched principal {expected_stop_principal!r} (observed {len(stops)})",
    )
    actions = _successful_audit_action_sequence(
        payload,
        instance_id=instance_id,
        since=since,
        until=until,
    )
    order_ok = bool(actions) and actions[0] == "START" and any(action == "STOP" for action in actions[1:])
    order_check = _result(
        "audit_transition_order",
        order_ok,
        "successful StartInstance precedes a successful StopInstance"
        if order_ok
        else "audit transition order must begin with StartInstance and include a later StopInstance",
    )
    return events, [receipt_check, start_check, principal_check, order_check]


def _snapshot_check(
    path: Path | None,
    *,
    since: float,
    until: float,
    final_state: str | None,
    expected_instance_id: str | None,
) -> dict[str, Any]:
    if path is None:
        return _result("reaper_snapshot", True, "state snapshot not supplied (optional)")
    try:
        snapshot = _safe_json(path)
    except EvidenceError as exc:
        return _result("reaper_snapshot", False, str(exc))
    written_at = _parse_time(
        _first_value(snapshot, ("written_at", "writtenAt", "timestamp", "captured_at", "capturedAt"))
    )
    snapshot_state = _normalise_state(
        _first_value(snapshot, ("gpu_state", "gpuState", "lifecycle-state", "lifecycle_state", "state"))
    )
    snapshot_instance_id = _as_text(_first_value(snapshot, ("instance_id", "instanceId")))
    written_ok = written_at is not None and since <= written_at <= until
    state_ok = snapshot_state == final_state == "STOPPED"
    identity_ok = expected_instance_id is not None and snapshot_instance_id == expected_instance_id
    if identity_ok:
        identity_detail = f"instance_id={snapshot_instance_id}"
    elif snapshot_instance_id is None:
        identity_detail = f"snapshot is missing instance_id; expected {expected_instance_id or 'selected instance'}"
    else:
        identity_detail = f"snapshot identifies {snapshot_instance_id}, expected {expected_instance_id or 'selected instance'}"
    passed = written_ok and state_ok and identity_ok
    return _result(
        "reaper_snapshot",
        passed,
        f"written_at={_format_time(written_at)}, gpu_state=STOPPED, {identity_detail} agree with final OCI state"
        if passed
        else f"written_at={_format_time(written_at)}, gpu_state={snapshot_state or 'missing'}, "
        f"final OCI state={final_state or 'missing'}, {identity_detail}",
    )


def _receipts_check(
    path: Path | None, *, intervals: Sequence[tuple[float, float]], min_descriptions: int
) -> dict[str, Any]:
    if path is None:
        return _result("wp_descriptions", True, "WP describe receipts not supplied (optional)")
    try:
        payload = _safe_json(path)
    except EvidenceError as exc:
        return _result("wp_descriptions", False, str(exc))
    valid: list[Mapping[str, Any]] = []
    for item in _receipt_items(payload):
        description = _description_value(item)
        timestamp = _receipt_time(item)
        in_running = timestamp is not None and any(start <= timestamp <= stop for start, stop in intervals)
        if description is not None and in_running:
            valid.append(item)
    return _result(
        "wp_descriptions",
        len(valid) >= min_descriptions,
        f"{len(valid)} description receipt(s) inside RUNNING interval; required {min_descriptions}",
    )


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
    if not bundle_path.is_dir():
        return _verdict(
            bundle_path, [_result("bundle_directory", False, f"bundle directory is missing: {bundle_path}")]
        )
    try:
        manifest = _safe_json(bundle_path / "manifest.json")
        if not isinstance(manifest, Mapping):
            raise EvidenceError("manifest.json must contain an object")
    except EvidenceError as exc:
        return _verdict(bundle_path, [_result("manifest_sha256", False, str(exc))])

    entries, manifest_failures = _verify_manifest(bundle_path, manifest)
    checks: list[dict[str, Any]] = [
        _manifest_schema_check(manifest),
        _result(
            "manifest_sha256",
            not manifest_failures,
            "all listed files match their sha256" if not manifest_failures else "; ".join(manifest_failures),
        ),
    ]
    since_epoch, until_epoch, since_text, until_text, window_error = _window_from_args(manifest, since, until)
    checks.append(
        _result(
            "capture_window",
            window_error is None,
            f"{since_text} .. {until_text}" if window_error is None else window_error,
        )
    )
    if window_error is not None or since_epoch is None or until_epoch is None:
        return _verdict(bundle_path, checks, since=since_text, until=until_text)

    paths = _receipt_paths(entries)
    manifest_instance_id = _as_text(manifest.get("instance_id", manifest.get("instanceId")))
    instance_payload, payload_instance_id, instance_checks = _instance_checks(paths["instance"], manifest_instance_id)
    checks.extend(instance_checks)
    target_instance_id = (
        manifest_instance_id if manifest_instance_id and payload_instance_id == manifest_instance_id else None
    )
    _history_payload, observations, history_checks = _state_checks(
        paths["history"],
        since=since_epoch,
        until=until_epoch,
        expected_instance_id=target_instance_id,
    )
    checks.extend(history_checks)
    _audit_events, audit_checks = _audit_checks(
        paths["audit"],
        instance_id=target_instance_id,
        since=since_epoch,
        until=until_epoch,
        expected_stop_principal=expected_stop_principal,
    )
    checks.extend(audit_checks)
    final_state = _instance_state(instance_payload)
    checks.append(
        _result(
            "oci_final_state",
            final_state == "STOPPED",
            "final OCI lifecycle state is STOPPED"
            if final_state == "STOPPED"
            else f"final OCI lifecycle state is {final_state or 'missing'}",
        )
    )
    checks.append(
        _snapshot_check(
            paths["snapshot"],
            since=since_epoch,
            until=until_epoch,
            final_state=final_state,
            expected_instance_id=target_instance_id,
        )
    )
    checks.append(
        _receipts_check(
            paths["receipts"], intervals=_running_intervals(observations), min_descriptions=min_descriptions
        )
    )
    return _verdict(bundle_path, checks, since=since_text, until=until_text, instance_id=target_instance_id)


def build_state_history_document(
    audit_payload: Any,
    *,
    instance_id: str,
    since: str,
    until: str,
) -> dict[str, Any]:
    """Build history from successful Audit transitions without inventing boundaries."""

    start = _parse_time(since)
    end = _parse_time(until)
    if start is None or end is None or start > end:
        raise EvidenceError("evidence history generation received an invalid window")
    observations: list[dict[str, Any]] = []
    for action, event, timestamp in _authoritative_audit_events(
        audit_payload,
        instance_id=instance_id,
        since=start,
        until=end,
    ):
        if action == "START":
            previous_value = _first_value(
                event,
                (
                    "previousState",
                    "previous_state",
                    "previousLifecycleState",
                    "previous_lifecycle_state",
                    "priorState",
                    "prior_state",
                    "fromState",
                    "from_state",
                ),
            )
            previous = _normalise_state(previous_value)
            if previous is None and isinstance(previous_value, Mapping):
                previous = _state_from_mapping(previous_value)
            previous_mapping = _first_value(event, ("previous",))
            if previous is None and isinstance(previous_mapping, Mapping):
                previous = _state_from_mapping(previous_mapping)
            if previous is not None:
                observations.append(
                    {
                        "state": previous,
                        "timestamp": event.get("eventTime", event.get("event_time", timestamp)),
                        "source": "oci_audit_previous_state",
                        "action": "StartInstance",
                    }
                )
            state = "RUNNING"
        else:
            state = "STOPPED"
        observations.append(
            {
                "state": state,
                "timestamp": event.get("eventTime", event.get("event_time", timestamp)),
                "source": "oci_audit_transition",
                "action": "StartInstance" if action == "START" else "StopInstance",
                "event_id": _first_value(event, ("eventId", "event_id", "requestId", "request_id")),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": instance_id,
        "since": since,
        "until": until,
        "observations": observations,
    }


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
    parser.add_argument(
        "--min-descriptions", type=_positive_or_zero, default=1, help="minimum valid WP descriptions (default: 1)"
    )
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
