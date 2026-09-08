#!/usr/bin/env bash
# Capture read-only OCI and application receipts for one GPU burst.
#
# The bundle is intentionally a collection of immutable JSON receipts.  This
# script never changes OCI state: every OCI invocation goes through run_oci,
# whose operation allowlist is the safety boundary against accidentally adding
# an actuator command here.

set -euo pipefail

# Evidence receipts include raw Audit identity/request metadata. Keep the
# transaction directory and every generated file private regardless of the
# caller's umask.
umask 077

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

# Keep the transaction sibling to the final bundle so the final move stays on
# one filesystem. Normalising the path also prevents a user-supplied basename
# beginning with '-' from being interpreted as an option by filesystem tools.
while [ "${out_dir%/}" != "$out_dir" ]; do
    out_dir="${out_dir%/}"
done
[ -n "$out_dir" ] || fail_usage "--out must name a bundle directory"
out_parent="${out_dir%/*}"
out_name="${out_dir##*/}"
if [ "$out_parent" = "$out_dir" ]; then
    out_parent="."
fi
case "$out_parent" in
    .|..|./*|../*|/*)
        ;;
    *)
        out_parent="./$out_parent"
        ;;
esac
out_dir="${out_parent}/${out_name}"

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
# REF-33: checker/python root comes from this script path, not git or cwd.
# Relative --out stays cwd-relative. RLSE-05: fail fast if the path is missing.
script_path="${BASH_SOURCE[0]:-}"
if [ -z "$script_path" ]; then
    echo "ERROR: cannot resolve exporter script path" >&2
    exit 1
fi
script_dir="$(cd "$(dirname "$script_path")" && pwd)" || {
    echo "ERROR: cannot resolve exporter script directory" >&2
    exit 1
}
lane_root="$(cd "${script_dir}/../../.." && pwd)" || {
    echo "ERROR: cannot resolve repository root from exporter path" >&2
    exit 1
}
required_python_major=3
required_python_minor=12
resolved_python=""
found_python=""
found_python_version=""

python_meets_floor() {
    "$1" -c "import sys; raise SystemExit(0 if sys.version_info >= (${required_python_major}, ${required_python_minor}) else 1)" >/dev/null 2>&1
}

python_version_text() {
    local reported
    reported="$("$1" -c "import sys; print('%d.%d.%d' % (sys.version_info.major, sys.version_info.minor, sys.version_info.micro))" 2>/dev/null)" || reported=""
    if [ -n "$reported" ]; then
        printf '%s\n' "$reported"
    else
        printf 'unknown\n'
    fi
}

consider_python() {
    local candidate="$1"
    [ -n "$candidate" ] || return 1
    [ -x "$candidate" ] || return 1
    if python_meets_floor "$candidate"; then
        resolved_python="$candidate"
        return 0
    fi
    if [ -z "$found_python" ]; then
        found_python="$candidate"
        found_python_version="$(python_version_text "$candidate")"
    fi
    return 1
}

if ! consider_python "$lane_root/.venv/bin/python"; then
    for python_name in python3.13 python3.12 python3; do
        python_candidate="$(command -v "$python_name" || true)"
        if consider_python "$python_candidate"; then
            break
        fi
    done
fi
if [ -z "$resolved_python" ]; then
    if [ -n "$found_python" ]; then
        echo "ERROR: $found_python is Python ${found_python_version}; gpu evidence requires >= ${required_python_major}.${required_python_minor}" >&2
        exit 1
    fi
    echo "ERROR: python3 is required to validate the evidence window" >&2
    exit 1
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

oci_bin="${OCI_BIN:-oci}"
oci_connection_timeout="${OCI_CONNECTION_TIMEOUT:-15}"
oci_read_timeout="${OCI_READ_TIMEOUT:-60}"
curl_connection_timeout="${EVIDENCE_CURL_CONNECTION_TIMEOUT:-10}"
curl_max_time="${EVIDENCE_CURL_MAX_TIME:-60}"
copy_max_time="${EVIDENCE_COPY_MAX_TIME:-$curl_max_time}"
lock_max_time="${EVIDENCE_LOCK_MAX_TIME:-60}"

for timeout_value in \
    "$oci_connection_timeout" \
    "$oci_read_timeout" \
    "$curl_connection_timeout" \
    "$curl_max_time" \
    "$copy_max_time" \
    "$lock_max_time"; do
    case "$timeout_value" in
        ''|0*|*[!0-9]*) fail_usage "timeouts must be positive integer seconds" ;;
    esac
    case "$timeout_value" in
        *[1-9]*) ;;
        *) fail_usage "timeouts must be positive integer seconds" ;;
    esac
done
# The checker is the source of truth for the manifest contract.  Keep the
# shell boundary free of a second copy of these values so a checker upgrade
# cannot silently make every newly exported bundle unverifiable.
checker_dir="${lane_root}/scripts"
schema_values="$("$resolved_python" - "$checker_dir" <<'PY'
import sys


sys.path.insert(0, sys.argv[1])
from gpu_burst_evidence import MANIFEST_FORMAT, SCHEMA_VERSION


print(SCHEMA_VERSION)
print(MANIFEST_FORMAT)
PY
)" || {
    echo "ERROR: could not read the evidence schema from gpu_burst_evidence.py" >&2
    exit 1
}
schema_version="$(printf '%s\n' "$schema_values" | sed -n '1p')"
manifest_format="$(printf '%s\n' "$schema_values" | sed -n '2p')"
[ -n "$schema_version" ] && [ -n "$manifest_format" ] || {
    echo "ERROR: gpu_burst_evidence.py returned an empty evidence schema" >&2
    exit 1
}

sync_paths() {
    "$resolved_python" - "$@" <<'PY'
import os
import sys


for raw_path in sys.argv[1:]:
    flags = os.O_RDONLY
    if os.path.isdir(raw_path):
        flags |= getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(raw_path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY
}

mkdir -p "$out_parent"
[ -d "$out_parent" ] || {
    echo "ERROR: output path is not a directory: $out_dir" >&2
    exit 1
}

if [ -L "$out_dir" ]; then
    fail_usage "output path must not be a symlink: $out_dir"
fi
if [ -e "$out_dir" ] && [ ! -d "$out_dir" ]; then
    fail_usage "output path is not a directory: $out_dir"
fi

lock_dir="${out_dir}.lock"
transaction_dir=""
work_dir=""
backup_dir=""
previous_moved=0
lock_acquired=0
lock_host="$(hostname 2>/dev/null || printf 'unknown')"
lock_owner_file=""
lock_owner_pid=""
lock_owner_host=""
lock_owner_start_time=""

cleanup() {
    local exit_status=$?
    trap - EXIT HUP INT TERM

    # If the second commit move failed, put the old bundle back before
    # removing the transaction directory. A failed capture must never leave
    # callers with an empty or half-written destination.
    if [ "$previous_moved" -eq 1 ] && [ ! -e "$out_dir" ] && [ -e "$backup_dir" ]; then
        if ! mv -- "$backup_dir" "$out_dir"; then
            echo "ERROR: could not restore the previous evidence bundle: $out_dir" >&2
            exit_status=1
        else
            sync_paths "$out_parent" || exit_status=1
        fi
    fi
    if [ -n "$transaction_dir" ] && [ -d "$transaction_dir" ]; then
        rm -rf -- "$transaction_dir" || true
    fi
    if [ "$lock_acquired" -eq 1 ]; then
        if [ -n "$lock_owner_file" ]; then
            rm -f -- "$lock_owner_file" || true
        fi
        rmdir -- "$lock_dir" 2>/dev/null || true
    fi
    exit "$exit_status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

recover_pending_publishes() {
    for candidate in "${out_parent}/.${out_name}.tmp."*; do
        [ -d "$candidate" ] || continue
        intent_file="${candidate}/.publish-intent"
        if [ ! -f "$intent_file" ]; then
            echo "INFO: removing abandoned evidence transaction without a publish intent: $candidate" >&2
            rm -rf -- "$candidate"
            continue
        fi
        intent_value="$(sed -n '1p' "$intent_file")"
        if [ "$intent_value" != "publish-intent-v1" ]; then
            echo "ERROR: refusing to recover an invalid evidence publish intent: $intent_file" >&2
            return 1
        fi

        candidate_backup="${candidate}/previous"
        if [ -e "$out_dir" ] || [ -L "$out_dir" ]; then
            echo "INFO: completing cleanup of an already-published evidence transaction: $candidate" >&2
            rm -rf -- "$candidate"
            continue
        fi

        if [ -d "$candidate_backup" ] && [ ! -L "$candidate_backup" ]; then
            echo "INFO: restoring the previous evidence bundle from an interrupted publish: $out_dir" >&2
            mv -- "$candidate_backup" "$out_dir"
            sync_paths "$out_parent"
        else
            echo "INFO: discarding an interrupted first publish with no previous bundle: $candidate" >&2
        fi
        rm -rf -- "$candidate"
        sync_paths "$out_parent"
    done
}

# Serialise same-destination captures. Atomic replacement protects readers
# from partial files, while this bounded lock also prevents two OCI captures
# from racing and publishing an arbitrary last-writer result. Never steal an
# existing lock: age and a prior PID observation cannot fence a paused writer
# or atomically identify the directory being removed. Crash recovery requires
# operator confirmation that all writers stopped before clearing the lock.
lock_attempts=$((10#$lock_max_time * 10))
lock_attempt=0
if [ -L "$lock_dir" ]; then
    fail_usage "lock path must not be a symlink: $lock_dir"
fi
if [ -e "$lock_dir" ] && [ ! -d "$lock_dir" ]; then
    fail_usage "lock path is not a directory: $lock_dir"
fi
while ! mkdir "$lock_dir" 2>/dev/null; do
    if [ "$lock_attempt" -ge "$lock_attempts" ]; then
        echo "ERROR: timed out waiting for evidence bundle lock: $out_dir; lock retained. Stop all writers before operator recovery, or choose another output path." >&2
        exit 1
    fi
    lock_attempt=$((lock_attempt + 1))
    sleep 0.1
done
lock_acquired=1
lock_owner_file="${lock_dir}/owner"
lock_owner_pid="$$"
lock_owner_host="$lock_host"
lock_owner_start_time="$(date +%s)"
printf 'pid=%s\nhost=%s\nstart_time=%s\n' \
    "$lock_owner_pid" "$lock_owner_host" "$lock_owner_start_time" >"$lock_owner_file"
chmod 600 "$lock_owner_file"
sync_paths "$lock_owner_file" "$lock_dir"
recover_pending_publishes

# Re-exporting into an existing bundle is supported, but only generated
# artifacts may be replaced. Rejecting unknown entries keeps a hand-edited
# directory from silently producing a manifest that cannot be checked. The
# old directory itself is not modified; it is moved aside only at commit time.
for existing in "$out_dir"/* "$out_dir"/.[!.]* "$out_dir"/..?*; do
    if [ ! -e "$existing" ] && [ ! -L "$existing" ]; then
        continue
    fi
    existing_name="${existing##*/}"
    case "$existing_name" in
        instance.json|audit-events.json|state_history.json|state_snapshot.json|wp_describe_receipts.json|manifest.json)
            ;;
        *)
            fail_usage "output directory contains an unrecognized entry: $existing_name"
            ;;
    esac
done
for artifact in instance.json audit-events.json state_history.json state_snapshot.json wp_describe_receipts.json manifest.json; do
    artifact_path="${out_dir}/${artifact}"
    if [ -e "$artifact_path" ] || [ -L "$artifact_path" ]; then
        [ -f "$artifact_path" ] || fail_usage "output artifact is not a regular file: $artifact"
    fi
done

transaction_dir="$(mktemp -d "${out_parent}/.${out_name}.tmp.XXXXXXXXXX")"
chmod 700 "$transaction_dir"
work_dir="${transaction_dir}/bundle"
mkdir "$work_dir"
chmod 700 "$work_dir"

# OCI Audit's --end-time is exclusive. Extend the API query by one
# microsecond while retaining the operator's original inclusive bound in the
# manifest and checker window.
audit_until="$("$resolved_python" - "$until" <<'PY'
import datetime as dt
import math
import sys


value = sys.argv[1].strip()
try:
    numeric = float(value)
except ValueError:
    numeric = None
if numeric is not None and math.isfinite(numeric):
    print(format(numeric + 0.000001, ".6f"))
else:
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SystemExit("timestamp must include a timezone")
    extended = parsed + dt.timedelta(microseconds=1)
    print(extended.astimezone(dt.UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"))
PY
)" || {
    echo "ERROR: could not extend --until for the OCI Audit query" >&2
    exit 2
}

is_allowed_oci_read() {
    [ "$#" -ge 3 ] || return 1
    case "$1:$2:$3" in
        compute:instance:get)
            [ "$#" -eq 5 ] && [ "$4" = "--instance-id" ]
            ;;
        audit:event:list)
            [ "$#" -eq 10 ] \
                && [ "$4" = "--compartment-id" ] \
                && [ "$6" = "--start-time" ] \
                && [ "$8" = "--end-time" ] \
                && [ "${10}" = "--all" ]
            ;;
        *)
            return 1
            ;;
    esac
}

run_oci() {
    if ! is_allowed_oci_read "$@"; then
        echo "ERROR: refusing non-read-only OCI command: $*" >&2
        return 3
    fi
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

strip_url_query_for_manifest() {
    local url="$1"
    case "$url" in
        *\?*)
            # Keep only the object path. Query credentials, expiry, and
            # signature parameters must never enter a persisted manifest.
            printf '%s' "${url%%\?*}"
            ;;
        *)
            printf '%s' "$url"
            ;;
    esac
}

bounded_copy() {
    local source="$1"
    local destination="$2"
    local copy_pid=""
    local elapsed=0

    if command -v timeout >/dev/null 2>&1; then
        timeout "$copy_max_time" cp -- "$source" "$destination"
        return $?
    fi

    # Keep a bounded fallback for hosts without coreutils timeout.  A
    # stubborn filesystem may outlive the TERM/KILL request, but the
    # exporter itself does not wait indefinitely for an ordinary cp process.
    cp -- "$source" "$destination" &
    copy_pid="$!"
    while kill -0 "$copy_pid" 2>/dev/null; do
        if [ "$elapsed" -ge "$copy_max_time" ]; then
            echo "ERROR: timed out copying evidence input: $source" >&2
            kill "$copy_pid" 2>/dev/null || true
            sleep 1
            kill -KILL "$copy_pid" 2>/dev/null || true
            wait "$copy_pid" 2>/dev/null || true
            return 124
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    wait "$copy_pid"
}

instance_file="${work_dir}/instance.json"
audit_file="${work_dir}/audit-events.json"
history_file="${work_dir}/state_history.json"
snapshot_file="${work_dir}/state_snapshot.json"
receipts_file="${work_dir}/wp_describe_receipts.json"

oci_timeout_command="--connection-timeout ${oci_connection_timeout} --read-timeout ${oci_read_timeout}"
instance_command="$(quote_for_manifest "$oci_bin") compute instance get --instance-id $(quote_for_manifest "$instance_id") ${oci_timeout_command} --output json"
audit_command="$(quote_for_manifest "$oci_bin") audit event list --compartment-id $(quote_for_manifest "$compartment_id") --start-time $(quote_for_manifest "$since") --end-time $(quote_for_manifest "$audit_until") --all ${oci_timeout_command} --output json"

# Both OCI calls below are read verbs.  Do not call the configured binary
# anywhere else in this script; run_oci is the single safety boundary.
run_oci compute instance get --instance-id "$instance_id" >"$instance_file"
run_oci audit event list \
    --compartment-id "$compartment_id" \
    --start-time "$since" \
    --end-time "$audit_until" \
    --all >"$audit_file"

# Build state history from the shared strict Audit parser. Only successful
# transitions with observed current states and explicit prior-state fields are
# copied; no window boundary or post-window current-state observation is
# fabricated.
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
            snapshot_url_without_query="$(strip_url_query_for_manifest "$state_snapshot_source")"
            snapshot_command="curl --fail --silent --show-error --location --connect-timeout ${curl_connection_timeout} --max-time ${curl_max_time} --output state_snapshot.json ${snapshot_url_without_query}"
            ;;
        *)
            bounded_copy "$state_snapshot_source" "$snapshot_file"
            snapshot_command="cp $(quote_for_manifest "$state_snapshot_source") state_snapshot.json"
            ;;
    esac
fi

receipts_command=""
if [ -n "$wp_receipts_source" ]; then
    bounded_copy "$wp_receipts_source" "$receipts_file"
    receipts_command="cp $(quote_for_manifest "$wp_receipts_source") wp_describe_receipts.json"
fi

# `cp` can retain a permissive source mode even under a restrictive umask;
# explicitly enforce the bundle's private receipt modes before hashing them.
for artifact_path in "$instance_file" "$audit_file" "$history_file"; do
    chmod 600 "$artifact_path"
done
if [ -n "$state_snapshot_source" ]; then
    chmod 600 "$snapshot_file"
fi
if [ -n "$wp_receipts_source" ]; then
    chmod 600 "$receipts_file"
fi
chmod 700 "$work_dir"

capture_time="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
"$resolved_python" - "$work_dir" "$schema_version" "$manifest_format" "$instance_id" "$compartment_id" "$since" "$until" "$capture_time" \
    "$instance_command" "$audit_command" "$history_command" "$snapshot_command" "$receipts_command" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


(
    out_dir,
    schema_version_text,
    manifest_format,
    instance_id,
    compartment_id,
    since,
    until,
    capture_time,
    instance_command,
    audit_command,
    history_command,
    snapshot_command,
    receipts_command,
) = sys.argv[1:]
try:
    schema_version = int(schema_version_text)
except ValueError:
    raise SystemExit("manifest generation: checker schema version is not an integer") from None
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
    "schema_version": schema_version,
    "format": manifest_format,
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

chmod 600 "$work_dir/manifest.json"

# A directory rename cannot replace a non-empty directory in place. Write and
# fsync a durable intent before moving the old bundle, then fsync each parent
# after the two renames. A later invocation can use the intent to restore the
# previous bundle if this process dies between the moves.
publish_intent="${transaction_dir}/.publish-intent"
printf '%s\n' 'publish-intent-v1' >"$publish_intent"
chmod 600 "$publish_intent"
sync_paths "$publish_intent" "$transaction_dir" "$out_parent"
if [ -e "$out_dir" ]; then
    backup_dir="${transaction_dir}/previous"
    mv -- "$out_dir" "$backup_dir"
    previous_moved=1
    sync_paths "$out_parent" "$transaction_dir"
fi
mv -- "$work_dir" "$out_dir"
sync_paths "$out_parent"
work_dir=""
if [ -n "$transaction_dir" ]; then
    rm -rf -- "$transaction_dir" || true
    sync_paths "$out_parent"
    transaction_dir=""
fi

echo "GPU evidence bundle: $out_dir"
