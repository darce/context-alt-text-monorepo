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

ACTION_START = "START"
ACTION_STOP = "STOP"
STATE_RUNNING = "RUNNING"
STATE_STOPPED = "STOPPED"
STATE_STARTING = "STARTING"
STATE_STOPPING = "STOPPING"
ACTION_RESULT_STATE = {ACTION_START: STATE_RUNNING, ACTION_STOP: STATE_STOPPED}
ACTION_INTERMEDIATE_STATE = {ACTION_START: STATE_STARTING, ACTION_STOP: STATE_STOPPING}
ACTION_PREVIOUS_STATE = {ACTION_START: STATE_STOPPED, ACTION_STOP: STATE_RUNNING}
PROOF_STATUS_KEY = "proof_status"
PROOF_STATUS_COMPLETE = "complete"
PROOF_STATUS_UNKNOWN = "unknown"

# The checker only needs these lifecycle values to distinguish the two states
# that prove a burst from the other documented OCI lifecycle states.  UNKNOWN
# and arbitrary attacker-supplied strings are deliberately not members.
KNOWN_LIFECYCLE_STATES = frozenset(
    {
        STATE_RUNNING,
        STATE_STOPPED,
        STATE_STARTING,
        STATE_STOPPING,
        "CREATING",
        "TERMINATING",
        "TERMINATED",
        "RESTARTING",
        "MIGRATING",
    }
)
MAX_NESTED_DEPTH = 64


class EvidenceError(ValueError):
    """An evidence document cannot be used for a proof check."""


def _result(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _parse_time(value: Any) -> float | None:
    """Return an epoch timestamp for an ISO-8601 or numeric value."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            numeric = float(value)
        except (OverflowError, ValueError):
            return None
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
    try:
        return parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def _format_time(value: float | None) -> str:
    if value is None:
        return "unavailable"
    try:
        return dt.datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return "invalid timestamp"


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
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EvidenceError(f"unreadable JSON receipt {path.name}: {exc}") from exc


def _nested_values(value: Any, keys: Sequence[str], *, depth: int = 4) -> Iterable[Any]:
    """Yield nested values without allowing attacker-controlled recursion."""

    if depth < 0:
        return
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, current_depth = stack.pop()
        if isinstance(current, Mapping):
            for key in keys:
                if key in current:
                    yield current[key]
            if current_depth < depth:
                stack.extend(
                    (child, current_depth + 1)
                    for child in reversed(list(current.values()))
                    if isinstance(child, (Mapping, list))
                )
        elif isinstance(current, list) and current_depth < depth:
            stack.extend((child, current_depth + 1) for child in reversed(current))


def _bounded_nodes(value: Any, *, max_depth: int = MAX_NESTED_DEPTH) -> tuple[list[Any], bool]:
    """Return JSON nodes iteratively and report a depth-bound violation."""

    nodes: list[Any] = []
    exceeded = False
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, current_depth = stack.pop()
        if current_depth > max_depth:
            exceeded = True
            continue
        nodes.append(current)
        if isinstance(current, Mapping):
            children = list(current.values())
        elif isinstance(current, list):
            children = current
        else:
            continue
        if current_depth >= max_depth:
            if any(isinstance(child, (Mapping, list)) for child in children):
                exceeded = True
            continue
        stack.extend((child, current_depth + 1) for child in reversed(children))
    return nodes, exceeded


def _path_values(value: Any, paths: Sequence[Sequence[str]]) -> list[Any]:
    """Read values from an explicit set of paths; never search arbitrary JSON."""

    values: list[Any] = []
    for path in paths:
        current = value
        for key in path:
            if not isinstance(current, Mapping) or key not in current:
                current = None
                break
            current = current[key]
        if current is not None:
            values.append(current)
    return values


def _flatten_values(values: Iterable[Any]) -> list[Any]:
    flattened: list[Any] = []
    pending = list(values)
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(reversed(value))
        else:
            flattened.append(value)
    return flattened


def _text_report(values: Iterable[Any], label: str) -> tuple[str | None, str | None]:
    flattened = _flatten_values(values)
    texts = {_as_text(value) for value in flattened}
    texts.discard(None)
    if any(_as_text(value) is None for value in flattened):
        return None, f"invalid {label} value"
    if len(texts) > 1:
        return None, f"conflicting {label} values: {', '.join(sorted(texts))}"
    if len(texts) == 1:
        return next(iter(texts)), None
    return None, None


def _first_value(value: Any, keys: Sequence[str]) -> Any:
    return next((candidate for candidate in _nested_values(value, keys) if candidate is not None), None)


def _raw_manifest_entries(manifest: Mapping[str, Any]) -> Any:
    raw = manifest.get("files")
    return raw if raw is not None else manifest.get("artifacts", manifest.get("entries"))


def _manifest_entries(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = _raw_manifest_entries(manifest)
    if isinstance(raw, Mapping):
        return [
            {"path": path, **metadata} if isinstance(metadata, Mapping) else {"path": path, "sha256": metadata}
            for path, metadata in raw.items()
        ]
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, Mapping)]
    return []


def _resolve_manifest_path(bundle: Path, relative: str) -> Path:
    if "\x00" in relative:
        raise EvidenceError(f"manifest path contains NUL byte: {relative!r}")
    path = Path(relative)
    if path.is_absolute() or relative in {"", "."} or ".." in path.parts:
        raise EvidenceError(f"manifest path is not a safe relative file: {relative!r}")
    candidate = (bundle / path).resolve()
    try:
        candidate.relative_to(bundle.resolve())
    except ValueError as exc:
        raise EvidenceError(f"manifest path escapes bundle: {relative!r}") from exc
    return candidate


def _manifest_entry_shape_failures(raw_entries: Any) -> list[str]:
    if not isinstance(raw_entries, list):
        return []
    return [
        f"manifest file entry {index} must be an object"
        for index, entry in enumerate(raw_entries)
        if not isinstance(entry, Mapping)
    ]


def _manifest_entry_digest(entry: Mapping[str, Any]) -> str | None:
    digest = entry.get("sha256", entry.get("digest"))
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
        return None
    return digest


def _verify_manifest_entry(
    bundle: Path, entry: Mapping[str, Any], listed: set[str]
) -> tuple[dict[str, Any] | None, str | None]:
    relative = entry.get("path")
    if not isinstance(relative, str) or not relative:
        return None, "manifest contains an entry without a path"
    if relative in listed:
        return None, f"manifest lists {relative!r} more than once"
    listed.add(relative)
    digest = _manifest_entry_digest(entry)
    if digest is None:
        return None, f"manifest has invalid sha256 for {relative}"
    try:
        target = _resolve_manifest_path(bundle, relative)
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
    except (EvidenceError, OSError, ValueError) as exc:
        return None, str(exc)
    failure = None
    if actual.lower() != digest.lower():
        failure = f"sha256 mismatch for {relative}: expected {digest}, got {actual}"
    return {"path": relative, "file": target, **entry}, failure


def _verify_manifest_entries(
    bundle: Path, entries: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], set[str], list[str]]:
    listed: set[str] = set()
    verified: list[dict[str, Any]] = []
    failures: list[str] = []
    for entry in entries:
        verified_entry, failure = _verify_manifest_entry(bundle, entry, listed)
        if verified_entry is not None:
            verified.append(verified_entry)
        if failure is not None:
            failures.append(failure)
    return verified, listed, failures


def _bundle_files(bundle: Path) -> tuple[set[str], str | None]:
    try:
        root = bundle.resolve()
        return (
            {
                str(path.relative_to(root))
                for path in root.rglob("*")
                if path.is_file() and path.relative_to(root).as_posix() != "manifest.json"
            },
            None,
        )
    except OSError as exc:
        return set(), f"cannot enumerate bundle files: {exc}"


def _verify_manifest(bundle: Path, manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    raw_entries = _raw_manifest_entries(manifest)
    entries = _manifest_entries(manifest)
    failures = _manifest_entry_shape_failures(raw_entries)
    if not entries:
        return [], failures + ["manifest has no file entries"]

    verified, listed, entry_failures = _verify_manifest_entries(bundle, entries)
    failures.extend(entry_failures)
    actual_files, enumeration_failure = _bundle_files(bundle)
    if enumeration_failure is not None:
        failures.append(enumeration_failure)
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


_INSTANCE_ID_PATHS = (
    ("id",),
    ("instance_id",),
    ("instanceId",),
    ("data", "id"),
    ("data", "instance_id"),
    ("data", "instanceId"),
)


def _instance_id_report(payload: Any) -> tuple[str | None, str | None]:
    return _text_report(_path_values(payload, _INSTANCE_ID_PATHS), "instance id")


def _instance_id_from_payload(payload: Any) -> str | None:
    """Return the canonical instance id, or ``None`` on ambiguity."""

    return _instance_id_report(payload)[0]


_STATE_KEYS = (
    "lifecycle-state",
    "lifecycle_state",
    "lifecycleState",
    "gpu_state",
    "gpuState",
    "state",
)


def _state_from_mapping_report(value: Mapping[str, Any]) -> tuple[str | None, str | None]:
    raw_values = [value[key] for key in _STATE_KEYS if key in value]
    states: set[str] = set()
    for raw in _flatten_values(raw_values):
        state = _normalise_state(raw)
        if state is None:
            return None, "invalid lifecycle state value"
        states.add(state)
    if len(states) > 1:
        return None, f"conflicting lifecycle state values: {', '.join(sorted(states))}"
    return (next(iter(states)), None) if states else (None, None)


def _state_from_mapping(value: Mapping[str, Any]) -> str | None:
    return _state_from_mapping_report(value)[0]


def _state_is_known(state: str | None) -> bool:
    return state in KNOWN_LIFECYCLE_STATES


_INSTANCE_STATE_PATHS = tuple((key,) for key in _STATE_KEYS) + tuple(("data", key) for key in _STATE_KEYS)


def _instance_state_report(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, Mapping):
        return None, None
    raw_values = _path_values(payload, _INSTANCE_STATE_PATHS)
    data = payload.get("data")
    if isinstance(data, list):
        raw_values.extend(item[key] for item in data if isinstance(item, Mapping) for key in _STATE_KEYS if key in item)
    if not raw_values:
        return None, None
    states: set[str] = set()
    for raw in _flatten_values(raw_values):
        state = _normalise_state(raw)
        if state is None:
            return None, "invalid instance lifecycle state value"
        states.add(state)
    if len(states) > 1:
        return None, "conflicting instance lifecycle state values"
    return next(iter(states)), None


def _instance_state(payload: Any) -> str | None:
    return _instance_state_report(payload)[0]


_STATE_HISTORY_CONTAINER_KEYS = ("observations", "states", "state_history", "state-history", "history", "transitions")
_STATE_OBSERVATION_TIME_KEYS = (
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
)


def _state_observation_time(value: Mapping[str, Any]) -> float | None:
    return _state_observation_time_report(value)[0]


def _state_observation_time_report(value: Mapping[str, Any]) -> tuple[float | None, str | None]:
    raw_values = [value[key] for key in _STATE_OBSERVATION_TIME_KEYS if key in value]
    if not raw_values:
        return None, None
    parsed: list[float] = []
    for raw in raw_values:
        timestamp = _parse_time(raw)
        if timestamp is None:
            return None, "invalid or missing timestamp"
        parsed.append(timestamp)
    if len(set(parsed)) > 1:
        return None, "conflicting observation timestamps"
    return parsed[0], None


def _has_state_field(value: Mapping[str, Any]) -> bool:
    return any(key in value for key in _STATE_KEYS)


def _mapping_has_state_history_containers(value: Mapping[str, Any]) -> bool:
    if isinstance(value.get("data"), list):
        return True
    return any(isinstance(value.get(key), (list, Mapping)) for key in _STATE_HISTORY_CONTAINER_KEYS)


def _validate_state_observation(value: Any, label: str) -> tuple[tuple[float, str, str] | None, str | None]:
    if not isinstance(value, Mapping):
        return None, f"{label} must be an object"
    state, state_error = _state_from_mapping_report(value)
    if state_error is not None:
        return None, f"{label} has {state_error}"
    if state is None:
        if _observation_is_inferred(value):
            return None, None
        return None, f"{label} is missing a state"
    if not _state_is_known(state):
        return None, f"{label} has unsupported lifecycle state {state!r}"
    if _observation_is_inferred(value):
        return None, None
    timestamp, time_error = _state_observation_time_report(value)
    if time_error is not None or timestamp is None:
        return None, f"{label} has invalid or missing timestamp"
    return (timestamp, state, "state-history"), None


def _parse_state_observation_collection(
    payload: list[Any], label: str
) -> tuple[list[tuple[float, str, str]], list[str]]:
    observations: list[tuple[float, str, str]] = []
    failures: list[str] = []
    for index, item in enumerate(payload):
        observation, failure = _validate_state_observation(item, f"{label} observation {index}")
        if observation is not None:
            observations.append(observation)
        if failure is not None:
            failures.append(failure)
    return observations, failures


def _parse_state_observations(
    payload: Any, *, label: str = "state history"
) -> tuple[list[tuple[float, str, str]], list[str]]:
    observations: list[tuple[float, str, str]] = []
    failures: list[str] = []
    pending: list[tuple[Any, str, int]] = [(payload, label, 0)]
    while pending:
        current, current_label, depth = pending.pop()
        if depth > MAX_NESTED_DEPTH:
            failures.append(f"{current_label} exceeds maximum nested depth {MAX_NESTED_DEPTH}")
            continue
        if isinstance(current, list):
            nested_observations, nested_failures = _parse_state_observation_collection(current, current_label)
            observations.extend(nested_observations)
            failures.extend(nested_failures)
            continue
        if not isinstance(current, Mapping):
            if depth == 0:
                failures.append(f"{current_label} must be an object or list")
            continue

        queued = False
        for key in _STATE_HISTORY_CONTAINER_KEYS:
            nested = current.get(key)
            if isinstance(nested, list):
                nested_observations, nested_failures = _parse_state_observation_collection(nested, key)
                if nested_observations or nested_failures:
                    observations.extend(nested_observations)
                    failures.extend(nested_failures)
                    queued = True
                    break
            elif isinstance(nested, Mapping):
                pending.append((nested, key, depth + 1))
                queued = True
                break
        if queued:
            continue
        data = current.get("data")
        if isinstance(data, list):
            nested_observations, nested_failures = _parse_state_observation_collection(data, "data")
            observations.extend(nested_observations)
            failures.extend(nested_failures)
            continue
        if _has_state_field(current):
            observation, failure = _validate_state_observation(current, current_label)
            if observation is not None:
                observations.append(observation)
            if failure is not None:
                failures.append(failure)
    return observations, failures


def _state_observation_report(payload: Any) -> tuple[list[tuple[float, str, str]], list[str]]:
    """Read valid state observations and report malformed non-inferred entries."""

    return _parse_state_observations(payload)


def _state_observations(payload: Any) -> list[tuple[float, str, str]]:
    return _state_observation_report(payload)[0]


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
    return _inferred_observation_report(payload)[0]


def _inferred_observation_report(payload: Any) -> tuple[int, str | None]:
    nodes, exceeded = _bounded_nodes(payload)
    count = sum(
        int(isinstance(node, Mapping) and _state_from_mapping(node) is not None and _observation_is_inferred(node))
        for node in nodes
    )
    return count, f"state history exceeds maximum nested depth {MAX_NESTED_DEPTH}" if exceeded else None


def _audit_items(payload: Any) -> list[Mapping[str, Any]]:
    return [
        item
        for item in _payload_items(payload, ("events", "items", "audit_events", "audit-events"))
        if isinstance(item, Mapping)
    ]


_EVENT_TIME_KEYS = ("eventTime", "event_time", "event-time", "timestamp", "time", "created_at", "createdAt")
_EVENT_RESOURCE_ID_PATHS = (
    ("resourceId",),
    ("resource_id",),
    ("resource-id",),
    ("data", "resourceId"),
    ("data", "resource_id"),
    ("data", "resource-id"),
)


def _event_time_report(event: Mapping[str, Any]) -> tuple[float | None, str | None]:
    raw_values = [event[key] for key in _EVENT_TIME_KEYS if key in event]
    if not raw_values:
        return None, None
    parsed: list[float] = []
    for raw in raw_values:
        timestamp = _parse_time(raw)
        if timestamp is None:
            return None, "invalid or missing event timestamp"
        parsed.append(timestamp)
    if len(set(parsed)) > 1:
        return None, "conflicting event timestamps"
    return parsed[0], None


def _event_time(event: Mapping[str, Any]) -> float | None:
    return _event_time_report(event)[0]


def _event_resource_id_report(event: Mapping[str, Any]) -> tuple[str | None, str | None]:
    return _text_report(_path_values(event, _EVENT_RESOURCE_ID_PATHS), "event resource id")


def _event_resource_id(event: Mapping[str, Any]) -> str | None:
    return _event_resource_id_report(event)[0]


def _action_from_value(value: Any) -> str | None:
    text = _as_text(value)
    if text is None:
        return None
    tokens = [token.upper() for token in re.split(r"[^A-Za-z0-9]+", text) if token]
    compact = re.sub(r"[^A-Za-z0-9]+", "", text).upper()
    if compact in {ACTION_START, "STARTINSTANCE"}:
        return ACTION_START
    if compact in {ACTION_STOP, "STOPINSTANCE"}:
        return ACTION_STOP
    if "STARTINSTANCE" in tokens or "START" in tokens:
        return ACTION_START
    if "STOPINSTANCE" in tokens or "STOP" in tokens:
        return ACTION_STOP
    return None


def _event_actions_report(event: Mapping[str, Any]) -> tuple[set[str], str | None]:
    """Extract actions from documented OCI Audit locations only."""

    sources: list[tuple[str, Any, str | None]] = []
    unsupported: list[str] = []

    for key in ("eventName", "event_name", "event-name", "action", "operation"):
        if key not in event:
            continue
        for value in _flatten_values([event[key]]):
            action = _action_from_value(value)
            sources.append((key, value, action))
            if action is None and _as_text(value) is not None:
                unsupported.append(f"{key}={_as_text(value)!r}")

    for key in ("eventType", "event_type", "event-type"):
        if key not in event:
            continue
        for value in _flatten_values([event[key]]):
            action = _action_from_value(value)
            if action is not None:
                sources.append((key, value, action))

    request_paths = (
        ("request", "parameters", "action"),
        ("data", "request", "parameters", "action"),
    )
    for value in _flatten_values(_path_values(event, request_paths)):
        action = _action_from_value(value)
        sources.append(("request.parameters.action", value, action))
        if action is None and _as_text(value) is not None:
            unsupported.append(f"request.parameters.action={_as_text(value)!r}")

    actions = {action for _source, _value, action in sources if action is not None}
    if len(actions) > 1:
        return set(), "conflicting audit action values"
    if unsupported and actions:
        return set(), "conflicting audit action values: " + ", ".join(unsupported)
    if unsupported:
        return set(), "unsupported audit action value(s): " + ", ".join(unsupported)
    return actions, None


def _event_actions(event: Mapping[str, Any]) -> set[str]:
    return _event_actions_report(event)[0]


def _event_phase_report(event: Mapping[str, Any]) -> tuple[str | None, str | None]:
    text, error = _text_report(
        [event[key] for key in ("eventType", "event_type", "event-type") if key in event], "event type"
    )
    if error is not None:
        return None, error
    if text is None:
        return None, None
    lower = text.casefold()
    if lower.endswith((".end", "_end", "-end")):
        return "end", None
    if lower.endswith((".begin", "_begin", "-begin")):
        return "begin", None
    return None, None


def _event_phase(event: Mapping[str, Any]) -> str | None:
    return _event_phase_report(event)[0]


def _event_state_change_report(event: Mapping[str, Any], field: str) -> tuple[str | None, str | None]:
    """Return an observed lifecycle state from documented OCI ``stateChange`` paths."""

    state_changes = _path_values(
        event,
        (
            ("stateChange",),
            ("state_change",),
            ("state-change",),
            ("data", "stateChange"),
            ("data", "state_change"),
            ("data", "state-change"),
        ),
    )
    if not state_changes:
        return None, None
    values: list[str] = []
    for state_change in state_changes:
        if not isinstance(state_change, Mapping):
            return None, "stateChange must be an object"
        field_values = [
            state_change[key]
            for key in (field, f"{field}State", f"{field}_state", f"{field}-state")
            if key in state_change
        ]
        for raw in field_values:
            if isinstance(raw, Mapping):
                state, state_error = _state_from_mapping_report(raw)
            else:
                state, state_error = _normalise_state(raw), None
            if state_error is not None:
                return None, state_error
            if state is not None:
                values.append(state)
    if len(set(values)) > 1:
        return None, f"conflicting {field} lifecycle state values"
    if not values:
        return None, None
    if not _state_is_known(values[0]):
        return None, f"unsupported lifecycle state {values[0]!r}"
    return values[0], None


def _event_state_change(event: Mapping[str, Any], field: str) -> str | None:
    return _event_state_change_report(event, field)[0]


def _event_identity_report(event: Mapping[str, Any], action: str, occurrence: int) -> tuple[str, str | None]:
    grouping, grouping_error = _text_report(
        _path_values(
            event,
            (
                ("eventGroupingId",),
                ("event_grouping_id",),
                ("event-grouping-id",),
                ("data", "eventGroupingId"),
                ("data", "event_grouping_id"),
                ("data", "event-grouping-id"),
            ),
        ),
        "event grouping id",
    )
    if grouping_error is not None:
        return f"fallback:{action}:{occurrence}", grouping_error
    request, request_error = _text_report(
        _path_values(
            event,
            (
                ("requestId",),
                ("request_id",),
                ("request", "id"),
                ("data", "requestId"),
                ("data", "request_id"),
                ("data", "request", "id"),
            ),
        ),
        "request id",
    )
    if request_error is not None:
        return f"fallback:{action}:{occurrence}", request_error
    event_id, event_error = _text_report(
        [event[key] for key in ("eventId", "eventID", "event_id", "event-id") if key in event], "event id"
    )
    if event_error is not None:
        return f"fallback:{action}:{occurrence}", event_error
    if grouping is not None:
        return f"group:{grouping}", None
    if request is not None:
        return f"request:{request}", None
    if event_id is not None:
        return f"event:{event_id}", None
    return f"fallback:{action}:{occurrence}", None


def _event_identity(event: Mapping[str, Any], action: str, occurrence: int) -> str:
    return _event_identity_report(event, action, occurrence)[0]


def _response_status_values(value: Any) -> Iterable[Any]:
    """Yield status values from documented OCI response locations only."""

    if not isinstance(value, Mapping):
        return
    mappings = [value]
    data = value.get("data")
    if isinstance(data, Mapping):
        mappings.append(data)
    for mapping in mappings:
        for key in ("responseStatus", "response_status"):
            if key in mapping and mapping[key] is not None:
                yield mapping[key]
        for key in ("response", "responseData", "response_data"):
            response = mapping.get(key)
            if isinstance(response, Mapping):
                for status_key in ("status", "statusCode", "status_code", "code", "result"):
                    if status_key in response and response[status_key] is not None:
                        yield response[status_key]
            elif response is not None:
                yield response


def _event_status(event: Mapping[str, Any]) -> Any:
    """Return one unambiguous OCI response status, or ``None``."""

    return _event_status_report(event)[0]


_STATUS_SUCCESS_TOKENS = frozenset({"OK", "SUCCESS", "SUCCEEDED", "COMPLETE", "COMPLETED"})
_STATUS_FAILURE_TOKENS = frozenset({"ERROR", "FAILED", "FAILURE", "FAIL", "CANCELLED", "DENIED"})


def _status_signature(value: Any) -> tuple[str, int | str] | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            numeric = float(value)
            integer = int(value)
        except (OverflowError, ValueError):
            return None
        if not math.isfinite(numeric) or numeric != integer:
            return None
        return "code", integer
    text = _as_text(value)
    if text is None:
        return None
    upper = text.upper()
    if re.fullmatch(r"[0-9]{3}", upper):
        return "code", int(upper)
    if upper in _STATUS_SUCCESS_TOKENS or upper in _STATUS_FAILURE_TOKENS:
        return "token", upper
    return None


def _event_status_report(event: Mapping[str, Any]) -> tuple[Any, str | None]:
    values = list(_response_status_values(event))
    if not values:
        return None, "missing OCI response status"
    signatures = [_status_signature(value) for value in values]
    if any(signature is None for signature in signatures):
        return None, "response status must be an exact numeric code or a supported token"
    if len(set(signatures)) > 1:
        return None, "conflicting OCI response status values"
    return values[0], None


def _status_success(value: Any) -> bool:
    signature = _status_signature(value)
    if signature is None:
        return False
    kind, parsed = signature
    return (kind == "code" and 200 <= parsed < 300) or (kind == "token" and parsed in _STATUS_SUCCESS_TOKENS)


def _audit_event_group_report(
    payload: Any, *, instance_id: str | None
) -> tuple[dict[tuple[str, str], list[Mapping[str, Any]]], list[str]]:
    if instance_id is None:
        return {}, []
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    failures: list[str] = []
    for occurrence, event in enumerate(_audit_items(payload)):
        resource_id, resource_error = _event_resource_id_report(event)
        if resource_error is not None:
            failures.append(f"audit event {occurrence}: {resource_error}")
            continue
        if resource_id != instance_id:
            continue
        _phase, phase_error = _event_phase_report(event)
        if phase_error is not None:
            failures.append(f"audit event {occurrence}: {phase_error}")
            continue
        actions, action_error = _event_actions_report(event)
        if action_error is not None:
            failures.append(f"audit event {occurrence}: {action_error}")
            continue
        for action in actions:
            identity, identity_error = _event_identity_report(event, action, occurrence)
            if identity_error is not None:
                failures.append(f"audit event {occurrence}: {identity_error}")
                continue
            grouped.setdefault((action, identity), []).append(event)
    for (action, identity), events in grouped.items():
        completed = sum(_event_phase(event) == "end" for event in events)
        if completed > 1:
            failures.append(
                f"audit {action} identity {identity!r} has {completed} completed records; expected at most one"
            )
    return grouped, failures


def _audit_event_groups(payload: Any, *, instance_id: str | None) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    return _audit_event_group_report(payload, instance_id=instance_id)[0]


def _event_timestamp_key(event: Mapping[str, Any]) -> float:
    timestamp = _event_time(event)
    return timestamp if timestamp is not None else float("-inf")


def _representative_audit_event_report(
    events: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, str | None]:
    completed = [event for event in events if _event_phase(event) == "end"]
    if len(completed) > 1:
        return None, "multiple completed records for one logical audit identity"
    candidates = completed or [event for event in events if _event_phase(event) is None]
    return (max(candidates, key=_event_timestamp_key), None) if candidates else (None, None)


def _representative_audit_event(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return _representative_audit_event_report(events)[0]


def _audit_operation_events(
    payload: Any,
    *,
    instance_id: str | None,
    since: float,
    until: float,
    require_current_state: bool,
) -> list[tuple[str, Mapping[str, Any], float]]:
    """Return one successful Audit record per logical action for one instance."""

    operations: list[tuple[str, Mapping[str, Any], float]] = []
    groups, _group_failures = _audit_event_group_report(payload, instance_id=instance_id)
    for (action, _identity), events in groups.items():
        event, _representative_error = _representative_audit_event_report(events)
        if event is None:
            continue
        timestamp, time_error = _event_time_report(event)
        expected_state = STATE_RUNNING if action == ACTION_START else STATE_STOPPED
        status, status_error = _event_status_report(event)
        current_state, current_error = _event_state_change_report(event, "current")
        if (
            timestamp is None
            or time_error is not None
            or not since <= timestamp <= until
            or status_error is not None
            or not _status_success(status)
            or current_error is not None
            or (require_current_state and current_state != expected_state)
        ):
            continue
        operations.append((action, event, timestamp))
    operations.sort(key=lambda item: item[2])
    return operations


def _authoritative_audit_events(
    payload: Any,
    *,
    instance_id: str | None,
    since: float,
    until: float,
) -> list[tuple[str, Mapping[str, Any], float]]:
    """Return successful, state-backed audit transitions for exactly one instance."""

    return _audit_operation_events(
        payload,
        instance_id=instance_id,
        since=since,
        until=until,
        require_current_state=True,
    )


def _successful_audit_action_sequence(
    payload: Any,
    *,
    instance_id: str | None,
    since: float,
    until: float,
) -> list[str]:
    """Read successful logical actions before checking their lifecycle order."""

    return [
        action
        for action, _event, _timestamp in _audit_operation_events(
            payload,
            instance_id=instance_id,
            since=since,
            until=until,
            require_current_state=False,
        )
    ]


_PRINCIPAL_PATHS = (
    ("identity", "principalName"),
    ("identity", "principal_name"),
    ("identity", "principal-name"),
    ("data", "identity", "principalName"),
    ("data", "identity", "principal_name"),
    ("data", "identity", "principal-name"),
)


def _principal_report(event: Mapping[str, Any]) -> tuple[set[str], str | None]:
    principal, error = _text_report(_path_values(event, _PRINCIPAL_PATHS), "principal")
    return ({principal} if principal is not None and error is None else set()), error


def _principal_values(event: Mapping[str, Any]) -> set[str]:
    return _principal_report(event)[0]


def _running_intervals(observations: Sequence[tuple[float, str, str]]) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    running_since: float | None = None
    for timestamp, state, _source in sorted(observations, key=lambda item: item[0]):
        if state == STATE_RUNNING and running_since is None:
            running_since = timestamp
        elif state == STATE_STOPPED and running_since is not None:
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
            if state == STATE_STOPPED:
                continue
            if state == STATE_RUNNING:
                phase = 1
                continue
            return False
        if phase == 1:
            if state == STATE_RUNNING:
                continue
            if state == STATE_STOPPED:
                phase = 2
                continue
            return False
        if state != STATE_STOPPED:
            return False
    return phase == 2


def _state_action_records(payload: Any) -> tuple[list[tuple[Mapping[str, Any], str]], list[str]]:
    records: list[tuple[Mapping[str, Any], str]] = []
    failures: list[str] = []
    pending: list[tuple[Any, str, int]] = [(payload, "state history", 0)]
    while pending:
        current, label, depth = pending.pop()
        if depth > MAX_NESTED_DEPTH:
            failures.append(f"{label} exceeds maximum nested depth {MAX_NESTED_DEPTH}")
            continue
        if isinstance(current, list):
            for index, item in enumerate(current):
                item_label = f"{label} observation {index}"
                if isinstance(item, Mapping):
                    records.append((item, item_label))
                else:
                    failures.append(f"{item_label} must be an object")
            continue
        if not isinstance(current, Mapping):
            continue
        queued = False
        for key in _STATE_HISTORY_CONTAINER_KEYS:
            nested = current.get(key)
            if isinstance(nested, list):
                for index, item in enumerate(nested):
                    item_label = f"{key} observation {index}"
                    if isinstance(item, Mapping):
                        records.append((item, item_label))
                    else:
                        failures.append(f"{item_label} must be an object")
                queued = True
                break
            if isinstance(nested, Mapping):
                pending.append((nested, key, depth + 1))
                queued = True
                break
        if queued:
            continue
        if _has_state_field(current):
            records.append((current, label))
            continue
        data = current.get("data")
        if isinstance(data, list):
            for index, item in enumerate(data):
                item_label = f"data observation {index}"
                if isinstance(item, Mapping):
                    records.append((item, item_label))
                else:
                    failures.append(f"{item_label} must be an object")
    return records, failures


def _state_action_sequence_report(payload: Any) -> tuple[list[tuple[float, str]], list[str]]:
    sequence: list[tuple[float, str]] = []
    records, failures = _state_action_records(payload)
    for value, label in records:
        if _observation_is_inferred(value) or "action" not in value:
            continue
        raw_actions = _flatten_values([value["action"]])
        parsed_actions = [_action_from_value(item) for item in raw_actions]
        actions = {action for action in parsed_actions if action is not None}
        if not raw_actions or any(action is None for action in parsed_actions):
            failures.append(f"{label} has an unsupported or conflicting action")
            continue
        if len(actions) != 1:
            failures.append(f"{label} has conflicting actions")
            continue
        timestamp, time_error = _state_observation_time_report(value)
        if time_error is not None or timestamp is None:
            failures.append(f"{label} action has invalid or missing timestamp")
            continue
        sequence.append((timestamp, next(iter(actions))))
    return sequence, failures


def _state_action_sequence(payload: Any) -> list[tuple[float, str]]:
    """Read transition actions using the same bounded observation-time parser."""

    return _state_action_sequence_report(payload)[0]


def _history_action_order_is_valid(actions: Sequence[tuple[float, str]]) -> bool:
    """Require an explicitly recorded history action sequence of START then STOP."""

    if not actions:
        return True
    ordered = sorted(actions, key=lambda item: item[0])
    return [action for _timestamp, action in ordered] == [ACTION_START, ACTION_STOP] and ordered[0][0] < ordered[1][0]


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


def _receipt_items_report(payload: Any) -> tuple[list[Mapping[str, Any]], str | None]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)], None
    if not isinstance(payload, Mapping):
        return [], "WordPress receipt payload must be an object or list"
    pending: list[tuple[Mapping[str, Any], int]] = [(payload, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > MAX_NESTED_DEPTH:
            return [], f"WordPress receipt payload exceeds maximum nested depth {MAX_NESTED_DEPTH}"
        nested_mappings: list[Mapping[str, Any]] = []
        for key in ("receipts", "items", "descriptions", "results", "data", "value"):
            value = current.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)], None
            if isinstance(value, Mapping):
                nested_mappings.append(value)
        if nested_mappings:
            pending.extend((value, depth + 1) for value in reversed(nested_mappings))
            continue
        return [current], None
    return [], None


def _receipt_items(payload: Any) -> list[Mapping[str, Any]]:
    return _receipt_items_report(payload)[0]


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
    return _direct_time_report(item, keys, "receipt timestamp")[0]


def _receipt_time_report(item: Mapping[str, Any]) -> tuple[float | None, str | None]:
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
    return _direct_time_report(item, keys, "receipt timestamp")


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


def _manifest_checks(
    bundle: Path,
) -> tuple[Mapping[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Load and validate the manifest before interpreting any listed artifact."""

    try:
        manifest = _safe_json(bundle / "manifest.json")
        if not isinstance(manifest, Mapping):
            raise EvidenceError("manifest.json must contain an object")
    except EvidenceError as exc:
        return None, [], [_result("manifest_sha256", False, str(exc))]

    schema_check = _manifest_schema_check(manifest)
    if not schema_check["passed"]:
        return None, [], [schema_check]
    entries, manifest_failures = _verify_manifest(bundle, manifest)
    manifest_check = _result(
        "manifest_sha256",
        not manifest_failures,
        "all listed files match their sha256" if not manifest_failures else "; ".join(manifest_failures),
    )
    return manifest, entries, [schema_check, manifest_check]


def _window_checks(
    manifest: Mapping[str, Any], since: str | None, until: str | None
) -> tuple[float | None, float | None, str | None, str | None, list[dict[str, Any]]]:
    """Parse the capture window and return its check result."""

    since_epoch, until_epoch, since_text, until_text, window_error = _window_from_args(manifest, since, until)
    check = _result(
        "capture_window",
        window_error is None,
        f"{since_text} .. {until_text}" if window_error is None else window_error,
    )
    return since_epoch, until_epoch, since_text, until_text, [check]


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
    payload_id, id_error = _instance_id_report(payload)
    id_check = _result(
        "instance_id_extraction",
        id_error is None,
        "instance receipt uses one documented instance id" if id_error is None else id_error,
    )
    if manifest_instance_id is None:
        identity_check = _result("instance_identity", False, "manifest instance_id is required")
    elif payload_id is None:
        identity_check = _result(
            "instance_identity",
            False,
            id_error or "instance receipt is missing an instance id",
        )
    elif payload_id != manifest_instance_id:
        identity_check = _result(
            "instance_identity",
            False,
            f"instance receipt identifies {payload_id}, expected {manifest_instance_id}",
        )
    else:
        identity_check = _result("instance_identity", True, f"manifest instance_id={manifest_instance_id}")
    return payload, payload_id, [receipt_check, id_check, identity_check]


def _history_instance_id_report(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, Mapping):
        return None, None
    return _text_report(
        _path_values(
            payload,
            (
                ("instance_id",),
                ("instanceId",),
                ("data", "id"),
                ("data", "instance_id"),
                ("data", "instanceId"),
            ),
        ),
        "state history instance id",
    )


def _history_instance_id(payload: Any) -> str | None:
    return _history_instance_id_report(payload)[0]


def _state_history_envelope_check(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return _result("state_history_schema", False, "state history envelope must be an object")
    if _has_state_field(payload) and not _mapping_has_state_history_containers(payload):
        envelope_state, state_error = _state_from_mapping_report(payload)
        if state_error is not None:
            return _result("state_history_schema", False, state_error)
        if not _state_is_known(envelope_state):
            return _result(
                "state_history_schema",
                False,
                f"unsupported lifecycle state {envelope_state!r} in state history envelope",
            )
    version = payload.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version != SCHEMA_VERSION:
        return _result(
            "state_history_schema",
            False,
            f"unsupported state history schema_version {version!r}; expected {SCHEMA_VERSION}",
        )
    if not any(key in payload for key in _STATE_HISTORY_CONTAINER_KEYS) and not isinstance(payload.get("data"), list):
        return _result("state_history_schema", False, "state history envelope is missing observations")
    return _result("state_history_schema", True, "supported state history envelope")


def _state_action_order_is_valid(payload: Any, *, since: float, until: float) -> bool:
    history_actions = [item for item in _state_action_sequence(payload) if since <= item[0] <= until]
    return _history_action_order_is_valid(history_actions)


def _state_history_identity_check(history_id: str | None, expected_instance_id: str | None) -> dict[str, Any]:
    identity_ok = expected_instance_id is not None and history_id == expected_instance_id
    detail = (
        f"state history is missing instance_id; expected {expected_instance_id or 'selected instance'}"
        if history_id is None
        else f"state history identifies {history_id}, expected {expected_instance_id}"
    )
    return _result("state_history_identity", identity_ok, detail)


def _state_history_burst_check(
    observations: Sequence[tuple[float, str, str]],
    *,
    raw_order_ok: bool,
    action_order_ok: bool,
    observation_errors: Sequence[str],
    action_errors: Sequence[str],
    inferred_count: int,
) -> dict[str, Any]:
    sequence = _state_sequence(observations)
    passed = (
        not observation_errors
        and not action_errors
        and raw_order_ok
        and action_order_ok
        and sequence == [STATE_STOPPED, STATE_RUNNING, STATE_STOPPED]
    )
    if passed:
        detail = "observed STOPPED -> RUNNING -> STOPPED inside capture window"
    else:
        detail = f"observed state sequence {sequence or ['none']}; expected STOPPED -> RUNNING -> STOPPED"
        if observation_errors:
            detail += "; invalid observation(s): " + "; ".join(observation_errors)
        if action_errors:
            detail += "; invalid action record(s): " + "; ".join(action_errors)
        if inferred_count:
            detail += f"; ignored {inferred_count} inferred observation(s)"
        if not action_order_ok:
            detail += "; state history transition order is invalid"
    return _result("state_history_burst", passed, detail)


def _state_checks(
    path: Path | None, *, since: float, until: float, expected_instance_id: str | None
) -> tuple[Any, list[tuple[float, str, str]], list[dict[str, Any]]]:
    payload, receipt_check = _load_required(path, "state_history_receipt")
    envelope_check = _state_history_envelope_check(payload)
    if envelope_check["passed"]:
        observations, observation_errors = _state_observation_report(payload)
        action_sequence, action_errors = _state_action_sequence_report(payload)
        history_id, history_id_error = _history_instance_id_report(payload)
    else:
        observations = []
        observation_errors = [envelope_check["detail"]]
        action_sequence, action_errors = [], []
        history_id, history_id_error = _history_instance_id_report(payload)
    if history_id_error is not None:
        observation_errors.append(history_id_error)
    _inferred_count, inferred_error = _inferred_observation_report(payload)
    if inferred_error is not None:
        observation_errors.append(inferred_error)
    in_window = [item for item in observations if since <= item[0] <= until]
    identity_check = _state_history_identity_check(history_id, expected_instance_id)
    lifecycle_failures = [error for error in observation_errors if "lifecycle state" in error.casefold()]
    lifecycle_check = _result(
        "state_history_lifecycle",
        not lifecycle_failures,
        "state history lifecycle values are supported" if not lifecycle_failures else "; ".join(lifecycle_failures),
    )
    history_actions = [item for item in action_sequence if since <= item[0] <= until]
    action_order_ok = _history_action_order_is_valid(history_actions)
    action_check = _result(
        "state_history_actions",
        not action_errors and action_order_ok,
        "state history action sequence is START then STOP"
        if not action_errors and action_order_ok
        else "state history action records are invalid or not a strict START then STOP sequence"
        + ("; " + "; ".join(action_errors) if action_errors else ""),
    )
    burst_check = _state_history_burst_check(
        in_window,
        raw_order_ok=_state_order_is_valid(in_window),
        action_order_ok=action_order_ok,
        observation_errors=observation_errors,
        action_errors=action_errors,
        inferred_count=_inferred_count,
    )
    return (
        payload,
        in_window,
        [
            receipt_check,
            envelope_check,
            identity_check,
            lifecycle_check,
            action_check,
            burst_check,
        ],
    )


def _artifact_checks(
    entries: Sequence[Mapping[str, Any]],
    *,
    manifest_instance_id: str | None,
    since: float,
    until: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load required artifacts and prepare context for the sequence checks."""

    paths = _receipt_paths(entries)
    instance_payload, payload_instance_id, instance_checks = _instance_checks(paths["instance"], manifest_instance_id)
    target_instance_id = (
        manifest_instance_id if manifest_instance_id and payload_instance_id == manifest_instance_id else None
    )
    _history_payload, observations, history_checks = _state_checks(
        paths["history"],
        since=since,
        until=until,
        expected_instance_id=target_instance_id,
    )
    final_state, state_error = _instance_state_report(instance_payload)
    if instance_payload is None and state_error is None:
        state_error = "instance receipt payload is missing"
    state_check = _result(
        "instance_state_extraction",
        state_error is None,
        "instance receipt uses one documented lifecycle state" if state_error is None else state_error,
    )
    final_state_check = _result(
        "oci_final_state",
        final_state == STATE_STOPPED,
        "final OCI lifecycle state is STOPPED"
        if final_state == STATE_STOPPED
        else f"final OCI lifecycle state is {final_state or 'missing'}",
    )
    context = {
        "final_state": final_state,
        "final_state_check": final_state_check,
        "instance_id": target_instance_id,
        "observations": observations,
        "paths": paths,
    }
    return [*instance_checks, *history_checks, state_check], context


def _audit_transition_order_check(
    events: Sequence[tuple[str, Mapping[str, Any], float]],
    matching_stops: Sequence[tuple[Mapping[str, Any], float]],
) -> dict[str, Any]:
    """Require all successful logical actions to start before a matching stop."""

    ordered_actions = [action for action, _event, _timestamp in events]
    start_timestamps = [timestamp for action, _event, timestamp in events if action == ACTION_START]
    start_timestamp = start_timestamps[0] if start_timestamps else None
    has_later_matching_stop = start_timestamp is not None and any(
        timestamp > start_timestamp for _event, timestamp in matching_stops
    )
    order_ok = (
        ordered_actions[:1] == [ACTION_START]
        and any(action == ACTION_STOP for action in ordered_actions[1:])
        and has_later_matching_stop
    )
    return _result(
        "audit_transition_order",
        order_ok,
        "successful StartInstance precedes the matching reaper StopInstance"
        if order_ok
        else "audit transition order requires StartInstance before the matching reaper StopInstance",
    )


def _audit_payload_contract_check(
    payload: Any,
    *,
    instance_id: str | None,
    since: float,
    until: float,
) -> tuple[dict[tuple[str, str], list[Mapping[str, Any]]], dict[str, Any]]:
    """Validate documented audit fields before any operation is authoritative."""

    groups, failures = _audit_event_group_report(payload, instance_id=instance_id)
    for occurrence, event in enumerate(_audit_items(payload)):
        resource_id, resource_error = _event_resource_id_report(event)
        if resource_error is not None or resource_id != instance_id:
            continue
        actions, action_error = _event_actions_report(event)
        if action_error is not None:
            continue
        for action in actions:
            _identity, identity_error = _event_identity_report(event, action, occurrence)
            if identity_error is not None:
                continue
            _timestamp, time_error = _event_time_report(event)
            if time_error is not None:
                failures.append(f"audit event {occurrence}: {time_error}")
            _status, status_error = _event_status_report(event)
            if status_error is not None:
                failures.append(f"audit event {occurrence}: {status_error}")
            _principal, principal_error = _principal_report(event)
            if principal_error is not None:
                failures.append(f"audit event {occurrence}: {principal_error}")
            for field in ("previous", "current"):
                _state, state_error = _event_state_change_report(event, field)
                if state_error is not None:
                    failures.append(f"audit event {occurrence}: {field} state: {state_error}")
    detail = "documented OCI audit fields are unambiguous"
    if failures:
        detail = "; ".join(dict.fromkeys(failures))
    return groups, _result("audit_payload_contract", not failures, detail)


def _audit_current_state_check(
    groups: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]], *, since: float, until: float
) -> dict[str, Any]:
    failures: list[str] = []
    for (action, identity), events in groups.items():
        for event in events:
            timestamp, time_error = _event_time_report(event)
            status, status_error = _event_status_report(event)
            if (
                time_error is not None
                or timestamp is None
                or not since <= timestamp <= until
                or status_error is not None
                or not _status_success(status)
            ):
                continue
            current, current_error = _event_state_change_report(event, "current")
            if current_error is not None:
                failures.append(f"{action} {identity}: current state: {current_error}")
            elif current is not None:
                expected = ACTION_RESULT_STATE[action]
                intermediate = ACTION_INTERMEDIATE_STATE[action]
                phase = _event_phase(event)
                allowed = {expected, intermediate} if phase == "begin" else {expected}
                if current not in allowed:
                    failures.append(
                        f"{action} {identity}: current state {current!r} contradicts expected {expected!r}"
                    )
    return _result(
        "audit_current_state_consistency",
        not failures,
        "successful audit operations have action-consistent current states" if not failures else "; ".join(failures),
    )


def _audit_transition_states_check(
    groups: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]], *, since: float, until: float
) -> dict[str, Any]:
    failures: list[str] = []
    for (action, identity), events in groups.items():
        event, representative_error = _representative_audit_event_report(events)
        if representative_error is not None or event is None:
            continue
        timestamp, time_error = _event_time_report(event)
        status, status_error = _event_status_report(event)
        if (
            time_error is not None
            or timestamp is None
            or not since <= timestamp <= until
            or status_error is not None
            or not _status_success(status)
        ):
            continue
        current, current_error = _event_state_change_report(event, "current")
        if current_error is not None or current != ACTION_RESULT_STATE[action]:
            continue
        expected_previous = ACTION_PREVIOUS_STATE[action]
        intermediate = ACTION_INTERMEDIATE_STATE[action]
        begin = next((item for item in events if _event_phase(item) == "begin"), None)
        if begin is not None:
            begin_previous, begin_previous_error = _event_state_change_report(begin, "previous")
            if begin_previous_error is not None:
                failures.append(f"{action} {identity}: previous state: {begin_previous_error}")
            elif begin_previous is not None and begin_previous != expected_previous:
                failures.append(
                    f"{action} {identity}: previous state {begin_previous!r} contradicts expected {expected_previous!r}"
                )
        previous, previous_error = _event_state_change_report(event, "previous")
        if previous_error is not None:
            failures.append(f"{action} {identity}: previous state: {previous_error}")
        elif previous is not None and previous not in {expected_previous, intermediate}:
            failures.append(
                f"{action} {identity}: previous state {previous!r} contradicts expected {expected_previous!r}"
            )
    return _result(
        "audit_transition_states",
        not failures,
        "successful audit transitions have the required previous and current states"
        if not failures
        else "; ".join(failures),
    )


def _audit_checks(
    path: Path | None,
    *,
    instance_id: str | None,
    since: float,
    until: float,
    expected_stop_principal: str,
) -> list[dict[str, Any]]:
    payload, receipt_check = _load_required(path, "audit_receipt")
    groups, contract_check = (
        _audit_payload_contract_check(
            payload,
            instance_id=instance_id,
            since=since,
            until=until,
        )
        if payload is not None
        else ({}, _result("audit_payload_contract", False, "audit receipt payload is missing"))
    )
    successful_events = (
        _audit_operation_events(
            payload,
            instance_id=instance_id,
            since=since,
            until=until,
            require_current_state=False,
        )
        if payload is not None
        else []
    )
    events = (
        _authoritative_audit_events(payload, instance_id=instance_id, since=since, until=until)
        if payload is not None
        else []
    )
    stops = [(event, timestamp) for action, event, timestamp in events if action == ACTION_STOP]
    authoritative_start_count = sum(action == ACTION_START for action, _event, _timestamp in events)
    actions = _successful_audit_action_sequence(
        payload,
        instance_id=instance_id,
        since=since,
        until=until,
    )
    start_count = actions.count(ACTION_START)
    if start_count == 1 and authoritative_start_count == 0:
        start_detail = "observed 0 StartInstance audit events with the expected RUNNING state"
    elif start_count == 1:
        start_detail = "exactly one StartInstance audit event"
    else:
        start_detail = f"observed {start_count} StartInstance audit events"
    start_check = _result(
        "exactly_one_start_instance",
        start_count == 1 and authoritative_start_count == 1,
        start_detail,
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
    stop_cardinality_check = _result(
        "authoritative_stop_cardinality",
        len(matching_stops) == 1,
        "exactly one authoritative matching reaper StopInstance"
        if len(matching_stops) == 1
        else f"observed {len(matching_stops)} authoritative matching reaper StopInstance events; expected exactly one",
    )
    sequence_check = _result(
        "audit_action_sequence",
        actions == [ACTION_START, ACTION_STOP],
        "successful audit action sequence is exactly START then STOP"
        if actions == [ACTION_START, ACTION_STOP]
        else f"successful audit action sequence is {actions or ['none']}; expected exactly START then STOP",
    )
    order_check = _audit_transition_order_check(successful_events, matching_stops)
    return [
        receipt_check,
        contract_check,
        _audit_current_state_check(groups, since=since, until=until),
        _audit_transition_states_check(groups, since=since, until=until),
        start_check,
        principal_check,
        stop_cardinality_check,
        sequence_check,
        order_check,
    ]


def _direct_time_report(value: Mapping[str, Any], keys: Sequence[str], label: str) -> tuple[float | None, str | None]:
    raw_values = [value[key] for key in keys if key in value]
    if not raw_values:
        return None, None
    parsed: list[float] = []
    for raw in raw_values:
        timestamp = _parse_time(raw)
        if timestamp is None:
            return None, f"invalid or missing {label}"
        parsed.append(timestamp)
    if len(set(parsed)) > 1:
        return None, f"conflicting {label} values"
    return parsed[0], None


def _direct_state_report(value: Mapping[str, Any], label: str) -> tuple[str | None, str | None]:
    raw_values = [value[key] for key in _STATE_KEYS if key in value]
    states: set[str] = set()
    for raw in _flatten_values(raw_values):
        state = _normalise_state(raw)
        if state is None:
            return None, f"invalid {label}"
        states.add(state)
    if len(states) > 1:
        return None, f"conflicting {label} values"
    return (next(iter(states)), None) if states else (None, None)


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
    if not isinstance(snapshot, Mapping):
        return _result("reaper_snapshot", False, "snapshot must be an object")
    written_at, written_error = _direct_time_report(
        snapshot,
        ("written_at", "writtenAt", "timestamp", "captured_at", "capturedAt"),
        "snapshot timestamp",
    )
    snapshot_state, state_error = _direct_state_report(snapshot, "snapshot lifecycle state")
    snapshot_instance_id, identity_error = _text_report(
        _path_values(snapshot, (("instance_id",), ("instanceId",), ("data", "instance_id"), ("data", "instanceId"))),
        "snapshot instance id",
    )
    written_ok = written_at is not None and since <= written_at <= until
    state_ok = snapshot_state == final_state == STATE_STOPPED
    identity_ok = expected_instance_id is not None and snapshot_instance_id == expected_instance_id
    if identity_ok:
        identity_detail = f"instance_id={snapshot_instance_id}"
    elif snapshot_instance_id is None:
        identity_detail = f"snapshot is missing instance_id; expected {expected_instance_id or 'selected instance'}"
    else:
        identity_detail = (
            f"snapshot identifies {snapshot_instance_id}, expected {expected_instance_id or 'selected instance'}"
        )
    extraction_errors = [error for error in (written_error, state_error, identity_error) if error is not None]
    passed = written_ok and state_ok and identity_ok and not extraction_errors
    extraction_detail = "; " + "; ".join(extraction_errors) if extraction_errors else ""
    return _result(
        "reaper_snapshot",
        passed,
        f"written_at={_format_time(written_at)}, gpu_state=STOPPED, {identity_detail} agree with final OCI state"
        if passed
        else f"written_at={_format_time(written_at)}, gpu_state={snapshot_state or 'missing'}, "
        f"final OCI state={final_state or 'missing'}, {identity_detail}{extraction_detail}",
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
    items, items_error = _receipt_items_report(payload)
    if items_error is not None:
        return _result("wp_descriptions", False, items_error)
    valid: list[Mapping[str, Any]] = []
    timestamp_errors: list[str] = []
    for index, item in enumerate(items):
        description = _description_value(item)
        timestamp, timestamp_error = _receipt_time_report(item)
        if timestamp_error is not None:
            timestamp_errors.append(f"receipt {index}: {timestamp_error}")
            continue
        in_running = timestamp is not None and any(start < timestamp < stop for start, stop in intervals)
        if description is not None and in_running:
            valid.append(item)
    if timestamp_errors:
        return _result(
            "wp_descriptions",
            False,
            "; ".join(timestamp_errors)
            + f"; {len(valid)} description receipt(s) inside RUNNING interval; required {min_descriptions}",
        )
    return _result(
        "wp_descriptions",
        len(valid) >= min_descriptions,
        f"{len(valid)} description receipt(s) inside RUNNING interval; required {min_descriptions}",
    )


def _snapshot_checks(
    path: Path | None,
    *,
    since: float,
    until: float,
    final_state: str | None,
    expected_instance_id: str | None,
) -> list[dict[str, Any]]:
    """Return the optional snapshot check as a list for bundle composition."""

    return [
        _snapshot_check(
            path,
            since=since,
            until=until,
            final_state=final_state,
            expected_instance_id=expected_instance_id,
        )
    ]


def _receipt_checks(
    path: Path | None, *, intervals: Sequence[tuple[float, float]], min_descriptions: int
) -> list[dict[str, Any]]:
    """Return WordPress receipt checks as a list for bundle composition."""

    return [_receipts_check(path, intervals=intervals, min_descriptions=min_descriptions)]


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
    manifest, entries, checks = _manifest_checks(bundle_path)
    if manifest is None:
        return _verdict(bundle_path, checks)

    since_epoch, until_epoch, since_text, until_text, window_checks = _window_checks(manifest, since, until)
    checks.extend(window_checks)
    window_invalid = window_checks[0]["passed"] is False
    if window_invalid or since_epoch is None or until_epoch is None:
        return _verdict(bundle_path, checks, since=since_text, until=until_text)

    manifest_instance_id, manifest_id_error = _text_report(
        [manifest[key] for key in ("instance_id", "instanceId") if key in manifest],
        "manifest instance id",
    )
    if manifest_id_error is not None:
        checks.append(_result("manifest_instance_id", False, manifest_id_error))
    artifact_checks, context = _artifact_checks(
        entries,
        manifest_instance_id=manifest_instance_id,
        since=since_epoch,
        until=until_epoch,
    )
    checks.extend(artifact_checks)
    checks.extend(
        _audit_checks(
            context["paths"]["audit"],
            instance_id=context["instance_id"],
            since=since_epoch,
            until=until_epoch,
            expected_stop_principal=expected_stop_principal,
        )
    )
    checks.append(context["final_state_check"])
    checks.extend(
        _snapshot_checks(
            context["paths"]["snapshot"],
            since=since_epoch,
            until=until_epoch,
            final_state=context["final_state"],
            expected_instance_id=context["instance_id"],
        )
    )
    checks.extend(
        _receipt_checks(
            context["paths"]["receipts"],
            intervals=_running_intervals(context["observations"]),
            min_descriptions=min_descriptions,
        )
    )
    return _verdict(
        bundle_path,
        checks,
        since=since_text,
        until=until_text,
        instance_id=context["instance_id"],
    )


def _event_time_value(event: Mapping[str, Any], timestamp: float) -> Any:
    return event.get("eventTime", event.get("event_time", event.get("event-time", timestamp)))


def _proof_status_for_observations(observations: Sequence[Mapping[str, Any]]) -> tuple[str, str | None]:
    states = [item.get("state") for item in observations]
    if states == [STATE_STOPPED, STATE_RUNNING, STATE_STOPPED]:
        return PROOF_STATUS_COMPLETE, None
    if not states:
        reason = "no authoritative lifecycle transition was observed in the capture window"
    elif states[0] != STATE_STOPPED:
        reason = "the initial lifecycle state was not independently observed in the capture window"
    elif states[-1] != STATE_STOPPED:
        reason = "the final lifecycle state was not independently observed in the capture window"
    else:
        reason = "the capture window does not contain a complete authoritative lifecycle history"
    return PROOF_STATUS_UNKNOWN, reason


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
    groups, _group_failures = _audit_event_group_report(audit_payload, instance_id=instance_id)
    for (action, _identity), events in groups.items():
        event, representative_error = _representative_audit_event_report(events)
        if representative_error is not None or event is None:
            continue
        timestamp, time_error = _event_time_report(event)
        status, status_error = _event_status_report(event)
        current, current_error = _event_state_change_report(event, "current")
        if (
            timestamp is None
            or time_error is not None
            or not start <= timestamp <= end
            or status_error is not None
            or not _status_success(status)
            or current_error is not None
            or current != ACTION_RESULT_STATE[action]
        ):
            continue
        expected_previous = ACTION_PREVIOUS_STATE[action]
        begin = next((item for item in events if _event_phase(item) == "begin"), None)
        previous_event = begin if begin is not None else event
        previous, previous_error = _event_state_change_report(previous_event, "previous")
        if previous_error is not None or previous != expected_previous:
            previous_event = event
            previous, previous_error = _event_state_change_report(event, "previous")
        if previous_error is not None or previous != expected_previous:
            continue
        if action == ACTION_START:
            observations.append(
                {
                    "state": previous,
                    "timestamp": _event_time_value(previous_event, timestamp),
                    "source": "oci_audit_previous_state",
                }
            )
        event_id, _event_id_error = _text_report(
            [event[key] for key in ("eventId", "eventID", "event_id", "event-id") if key in event], "event id"
        )
        observations.append(
            {
                "state": current,
                "timestamp": _event_time_value(event, timestamp),
                "source": "oci_audit_transition",
                "action": "StartInstance" if action == ACTION_START else "StopInstance",
                "event_id": event_id,
            }
        )
    observations.sort(key=lambda item: _parse_time(item.get("timestamp")) or 0)
    proof_status, reason = _proof_status_for_observations(observations)
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": instance_id,
        "since": since,
        "until": until,
        "observations": observations,
        PROOF_STATUS_KEY: proof_status,
    }
    if reason is not None:
        document["reason"] = reason
    return document


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
