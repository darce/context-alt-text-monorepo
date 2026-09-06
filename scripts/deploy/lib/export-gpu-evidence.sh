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
oci_connection_timeout="${OCI_CONNECTION_TIMEOUT:-15}"
oci_read_timeout="${OCI_READ_TIMEOUT:-60}"
curl_connection_timeout="${EVIDENCE_CURL_CONNECTION_TIMEOUT:-10}"
curl_max_time="${EVIDENCE_CURL_MAX_TIME:-60}"

for timeout_value in "$oci_connection_timeout" "$oci_read_timeout" "$curl_connection_timeout" "$curl_max_time"; do
    case "$timeout_value" in
        ''|*[!0-9]*) fail_usage "timeouts must be positive integer seconds" ;;
        0) fail_usage "timeouts must be positive integer seconds" ;;
    esac
done

is_forbidden_oci_token() {
    local token="$1"
    case "$token" in
        --*) token="${token#--}" ;;
        -*) token="${token#-}" ;;
    esac
    token="$(printf '%s' "$token" | tr '[:upper:]' '[:lower:]')"
    case "$token" in
        start|stop|terminate|action|update|delete|create|launch|attach|detach|reboot|reset|softstop|softreset)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_allowed_oci_read() {
    [ "$#" -ge 3 ] || return 1
    case "$1:$2:$3" in
        compute:instance:get|audit:event:list)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

run_oci() {
    local arg
    if ! is_allowed_oci_read "$@"; then
        echo "ERROR: refusing non-read-only OCI command: $*" >&2
        return 3
    fi
    for arg in "$@"; do
        if is_forbidden_oci_token "$arg"; then
            echo "ERROR: refusing forbidden OCI operation token: $arg" >&2
            return 3
        fi
    done
    "$oci_bin" "$@" \
        --connection-timeout "$oci_connection_timeout" \
        --read-timeout "$oci_read_timeout" \
        --output json
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

oci_timeout_command="--connection-timeout ${oci_connection_timeout} --read-timeout ${oci_read_timeout}"
instance_command="$(quote_for_manifest "$oci_bin") compute instance get --instance-id $(quote_for_manifest "$instance_id") ${oci_timeout_command} --output json"
audit_command="$(quote_for_manifest "$oci_bin") audit event list --compartment-id $(quote_for_manifest "$compartment_id") --start-time $(quote_for_manifest "$since") --end-time $(quote_for_manifest "$until") --all ${oci_timeout_command} --output json"

# Both OCI calls below are read verbs.  Do not call the configured binary
# anywhere else in this script; run_oci is the single safety boundary.
run_oci compute instance get --instance-id "$instance_id" >"$instance_file"
run_oci audit event list \
    --compartment-id "$compartment_id" \
    --start-time "$since" \
    --end-time "$until" \
    --all >"$audit_file"

# Build state history from the shared strict Audit parser.  Only successful
# transitions and explicit prior-state fields are copied; no window boundary
# or post-window current-state observation is fabricated.
checker_dir="${lane_root}/scripts"
"$resolved_python" - "$audit_file" "$history_file" "$instance_id" "$since" "$until" "$checker_dir" <<'PY'
import json
import sys
from pathlib import Path


audit_path, output_path, instance_id, since, until, checker_dir = sys.argv[1:]
sys.path.insert(0, checker_dir)
from gpu_burst_evidence import build_state_history_document


with Path(audit_path).open(encoding="utf-8") as handle:
    audit = json.load(handle)
document = build_state_history_document(audit, instance_id=instance_id, since=since, until=until)
with Path(output_path).open("w", encoding="utf-8") as handle:
    json.dump(document, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

history_command="derived from successful OCI Audit transitions; no boundary states synthesized"

snapshot_command=""
if [ -n "$state_snapshot_source" ]; then
    case "$state_snapshot_source" in
        *://*)
            curl --fail --silent --show-error --location \
                --connect-timeout "$curl_connection_timeout" \
                --max-time "$curl_max_time" \
                --output "$snapshot_file" "$state_snapshot_source"
            snapshot_command="curl --fail --silent --show-error --location --connect-timeout ${curl_connection_timeout} --max-time ${curl_max_time} --output state_snapshot.json <redacted-url>"
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
