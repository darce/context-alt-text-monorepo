#!/usr/bin/env bash
# Capture read-only OCI and application receipts for one GPU burst.
#
# The bundle is intentionally a collection of immutable JSON receipts.  This
# script never changes OCI state: every OCI invocation goes through run_oci,
# whose deny-list is a second line of defence against accidentally adding an
# actuator command here.

set -euo pipefail

usage() {
    cat >&2 <<'EOF'
Usage: export-gpu-evidence.sh --instance-id <ocid> --compartment-id <ocid> \
    --since <iso> --until <iso> --out <dir> \
    [--state-snapshot <path-or-url>] [--wp-receipts <path>]
EOF
}

fail_usage() {
    echo "ERROR: $*" >&2
    usage
    exit 2
}

instance_id=""
compartment_id=""
since=""
until=""
out_dir=""
state_snapshot_source=""
wp_receipts_source=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --instance-id)
            [ "$#" -ge 2 ] || fail_usage "--instance-id requires a value"
            instance_id="$2"
            shift 2
            ;;
        --compartment-id)
            [ "$#" -ge 2 ] || fail_usage "--compartment-id requires a value"
            compartment_id="$2"
            shift 2
            ;;
        --since)
            [ "$#" -ge 2 ] || fail_usage "--since requires a value"
            since="$2"
            shift 2
            ;;
        --until)
            [ "$#" -ge 2 ] || fail_usage "--until requires a value"
            until="$2"
            shift 2
            ;;
        --out)
            [ "$#" -ge 2 ] || fail_usage "--out requires a value"
            out_dir="$2"
            shift 2
            ;;
        --state-snapshot)
            [ "$#" -ge 2 ] || fail_usage "--state-snapshot requires a value"
            state_snapshot_source="$2"
            shift 2
            ;;
        --wp-receipts)
            [ "$#" -ge 2 ] || fail_usage "--wp-receipts requires a value"
            wp_receipts_source="$2"
            shift 2
            ;;
        -h|--help)
            usage >&2
            exit 0
            ;;
        *)
            fail_usage "unknown argument: $1"
            ;;
    esac
done

[ -n "$instance_id" ] || fail_usage "--instance-id is required"
[ -n "$compartment_id" ] || fail_usage "--compartment-id is required"
[ -n "$since" ] || fail_usage "--since is required"
[ -n "$until" ] || fail_usage "--until is required"
[ -n "$out_dir" ] || fail_usage "--out is required"

if [ -n "$state_snapshot_source" ]; then
    case "$state_snapshot_source" in
        *://*)
            ;;
        *)
            [ -f "$state_snapshot_source" ] && [ -r "$state_snapshot_source" ] ||
                fail_usage "state snapshot is not a readable file: $state_snapshot_source"
            ;;
    esac
fi
if [ -n "$wp_receipts_source" ]; then
    [ -f "$wp_receipts_source" ] && [ -r "$wp_receipts_source" ] ||
        fail_usage "WP receipts are not a readable file: $wp_receipts_source"
fi

# Check the window before making any external call.  This keeps malformed
# operator input from producing a partial bundle.  The Python helper is
# stdlib-only and is selected from this execution filesystem.
lane_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ -x "$lane_root/.venv/bin/python" ]; then
    resolved_python="$lane_root/.venv/bin/python"
else
    resolved_python="$(command -v python3)" || {
        echo "ERROR: python3 is required to validate the evidence window" >&2
        exit 1
    }
fi
"$resolved_python" - "$since" "$until" <<'PY'
import datetime as dt
import math
import sys


def parse(value: str) -> float:
    text = value.strip()
    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None and math.isfinite(number):
        return number
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.timestamp()


try:
    start = parse(sys.argv[1])
    end = parse(sys.argv[2])
except (IndexError, TypeError, ValueError) as exc:
    raise SystemExit(f"ERROR: invalid evidence window: {exc}") from None
if start > end:
    raise SystemExit("ERROR: --since must not be later than --until")
PY

mkdir -p "$out_dir"
[ -d "$out_dir" ] || {
    echo "ERROR: output path is not a directory: $out_dir" >&2
    exit 1
}

oci_bin="${OCI_BIN:-oci}"

is_forbidden_oci_token() {
    local token="$1"
    case "$token" in
        --*) token="${token#--}" ;;
        -*) token="${token#-}" ;;
    esac
    token="$(printf '%s' "$token" | tr '[:upper:]' '[:lower:]')"
    case "$token" in
        start|stop|terminate|action)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

run_oci() {
    local arg
    for arg in "$@"; do
        if is_forbidden_oci_token "$arg"; then
            echo "ERROR: refusing forbidden OCI operation token: $arg" >&2
            return 3
        fi
    done
    "$oci_bin" "$@" --output json
}

# Keep producer command strings human-readable while retaining shell quoting
# for unusual IDs or paths.  The values are metadata only; no string is ever
# evaluated as a command.
quote_for_manifest() {
    local value="$1"
    case "$value" in
        *[!A-Za-z0-9_./:@+-]*)
            value="$(printf '%s' "$value" | sed "s/'/'\\\\''/g")"
            printf "'%s'" "$value"
            ;;
        *)
            printf '%s' "$value"
            ;;
    esac
}

instance_file="${out_dir}/instance.json"
audit_file="${out_dir}/audit-events.json"
history_file="${out_dir}/state_history.json"
snapshot_file="${out_dir}/state_snapshot.json"
receipts_file="${out_dir}/wp_describe_receipts.json"

instance_command="$(quote_for_manifest "$oci_bin") compute instance get --instance-id $(quote_for_manifest "$instance_id") --output json"
audit_command="$(quote_for_manifest "$oci_bin") audit event list --compartment-id $(quote_for_manifest "$compartment_id") --start-time $(quote_for_manifest "$since") --end-time $(quote_for_manifest "$until") --all --output json"

# Both OCI calls below are read verbs.  Do not call the configured binary
# anywhere else in this script; run_oci is the single safety boundary.
run_oci compute instance get --instance-id "$instance_id" >"$instance_file"
run_oci audit event list \
    --compartment-id "$compartment_id" \
    --start-time "$since" \
    --end-time "$until" \
    --all >"$audit_file"

# Build a compact, explicit state history from the raw current-state and Audit
# receipts.  OCI exposes the current lifecycle state through instance get;
# Audit's completed START/STOP records provide the historical edges.  The
# window boundary is recorded as the claimed pre-burst STOPPED observation so
# the checker can require the complete transition rather than infer it from a
# final state alone.
"$resolved_python" - "$instance_file" "$audit_file" "$history_file" "$instance_id" "$since" "$until" <<'PY'
from __future__ import annotations

import datetime as dt
import json
import math
import sys
from collections import defaultdict
from collections.abc import Mapping


def parse_time(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.timestamp()


def nested(value, keys, depth=3):
    if depth < 0:
        return
    if isinstance(value, Mapping):
        for key in keys:
            if key in value:
                yield value[key]
        if depth:
            for child in value.values():
                if isinstance(child, Mapping):
                    yield from nested(child, keys, depth - 1)


def first(value, keys):
    for candidate in nested(value, keys):
        if candidate is not None:
            return candidate
    return None


def text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def items(payload, keys):
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
    return []


def event_time(event):
    for key in ("eventTime", "event_time", "timestamp", "time"):
        if event.get(key) is not None:
            value = parse_time(event[key])
            if value is not None:
                return value
    return parse_time(first(event, ("eventTime", "event_time", "timestamp", "time")))


def actions(event):
    values = [event[key] for key in ("eventName", "event_name", "eventType", "event_type", "action") if key in event]
    values.extend(nested(event, ("action", "actionName", "action_name")))
    result = set()
    while values:
        value = values.pop()
        if isinstance(value, list):
            values.extend(value)
            continue
        value = text(value)
        if value is None:
            continue
        upper = value.upper()
        if "STARTINSTANCE" in upper or upper in {"START", "START_INSTANCE"}:
            result.add("START")
        if "STOPINSTANCE" in upper or upper in {"STOP", "STOP_INSTANCE"}:
            result.add("STOP")
    return result


def phase(event):
    value = text(event.get("eventType", event.get("event_type")))
    if value is None:
        return None
    lower = value.casefold()
    if lower.endswith((".end", "_end", "-end")):
        return "end"
    if lower.endswith((".begin", "_begin", "-begin")):
        return "begin"
    return None


def identity(event, action):
    value = first(event, ("eventId", "event_id", "requestId", "request_id", "id"))
    value = text(value)
    if value is not None:
        return f"id:{value}"
    return f"fallback:{action}:{event_time(event)!r}:{first(event, ('resourceId', 'resource_id'))!r}"


def resource_id(event):
    value = first(event, ("resourceId", "resource_id", "instanceId", "instance_id"))
    return text(value)


def current_state(payload):
    candidates = []
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
        if not isinstance(candidate, Mapping):
            continue
        for key in ("lifecycle-state", "lifecycle_state", "lifecycleState", "state"):
            value = text(candidate.get(key))
            if value is not None:
                return value.replace("_", "-").replace(" ", "-").upper()
    return "UNKNOWN"


instance_path, audit_path, output_path, expected_instance, since_text, until_text = sys.argv[1:]
with open(instance_path, encoding="utf-8") as handle:
    instance = json.load(handle)
with open(audit_path, encoding="utf-8") as handle:
    audit = json.load(handle)

start = parse_time(since_text)
end = parse_time(until_text)
if start is None or end is None:
    raise SystemExit("evidence history generation received an invalid window")

groups = defaultdict(list)
for event in items(audit, ("events", "items", "audit_events", "audit-events")):
    if not isinstance(event, Mapping):
        continue
    resource = resource_id(event)
    if resource is not None and resource != expected_instance:
        continue
    timestamp = event_time(event)
    if timestamp is None or not start <= timestamp <= end:
        continue
    for action in actions(event):
        groups[(action, identity(event, action))].append(event)

observations = [{"state": "STOPPED", "timestamp": since_text, "source": "window_start"}]
for (action, _event_identity), grouped in sorted(
    groups.items(), key=lambda item: min(event_time(event) for event in item[1] if event_time(event) is not None)
):
    completed = [event for event in grouped if phase(event) == "end"]
    candidates = completed or [event for event in grouped if phase(event) is None]
    if not candidates:
        continue
    event = max(candidates, key=lambda item: event_time(item) or float("-inf"))
    timestamp = event_time(event)
    if timestamp is None:
        continue
    observations.append(
        {
            "state": "RUNNING" if action == "START" else "STOPPED",
            "timestamp": event.get("eventTime", event.get("event_time", timestamp)),
            "source": "oci_audit",
            "event_id": first(event, ("eventId", "event_id", "requestId", "request_id")),
        }
    )
observations.append({"state": current_state(instance), "timestamp": until_text, "source": "oci_compute_instance_get"})
document = {
    "schema_version": 1,
    "instance_id": expected_instance,
    "since": since_text,
    "until": until_text,
    "observations": observations,
}
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(document, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

history_command="derived from instance.json and audit-events.json"

snapshot_command=""
if [ -n "$state_snapshot_source" ]; then
    case "$state_snapshot_source" in
        *://*)
            curl --fail --silent --show-error --location \
                --output "$snapshot_file" "$state_snapshot_source"
            snapshot_command="curl --fail --silent --show-error --location --output state_snapshot.json $(quote_for_manifest "$state_snapshot_source")"
            ;;
        *)
            cp "$state_snapshot_source" "$snapshot_file"
            snapshot_command="cp $(quote_for_manifest "$state_snapshot_source") state_snapshot.json"
            ;;
    esac
fi

receipts_command=""
if [ -n "$wp_receipts_source" ]; then
    cp "$wp_receipts_source" "$receipts_file"
    receipts_command="cp $(quote_for_manifest "$wp_receipts_source") wp_describe_receipts.json"
fi

capture_time="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
"$resolved_python" - "$out_dir" "$instance_id" "$compartment_id" "$since" "$until" "$capture_time" \
    "$instance_command" "$audit_command" "$history_command" "$snapshot_command" "$receipts_command" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


out_dir, instance_id, compartment_id, since, until, capture_time, instance_command, audit_command, history_command, snapshot_command, receipts_command = sys.argv[1:]
root = Path(out_dir)
artifacts = [
    ("instance.json", instance_command),
    ("audit-events.json", audit_command),
    ("state_history.json", history_command),
]
if snapshot_command:
    artifacts.append(("state_snapshot.json", snapshot_command))
if receipts_command:
    artifacts.append(("wp_describe_receipts.json", receipts_command))

files = []
for relative, command in artifacts:
    target = root / relative
    if not target.is_file():
        raise SystemExit(f"manifest generation: missing artifact {relative}")
    files.append(
        {
            "path": relative,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "command": command,
            "capture_time": capture_time,
            "captured_at": capture_time,
        }
    )

manifest = {
    "schema_version": 1,
    "format": "oci-gpu-burst-evidence-v1",
    "instance_id": instance_id,
    "compartment_id": compartment_id,
    "since": since,
    "until": until,
    "captured_at": capture_time,
    "files": files,
}
temporary = root / f".manifest.json.tmp.{os.getpid()}"
with temporary.open("w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
os.replace(temporary, root / "manifest.json")
PY

echo "GPU evidence bundle: $out_dir"
