#!/usr/bin/env bash
# Fail-closed deployment and freshness check for the two /run/acx snapshots.

if [ -z "${BASH_VERSION:-}" ]; then
    echo "ERROR: $0 must run under bash" >&2
    exit 2
fi
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
compose_file=${ACX_GPU_COMPOSE_FILE:-${repo_root}/apps/prototype-description-service/docker-compose.env.yml}
install_script=${ACX_GPU_INSTALL_SCRIPT:-${repo_root}/scripts/deploy/gpu-lifecycle-install.sh}
state_stale_seconds=${ACX_GPU_STATE_STALE_SECONDS:-180}
load_stale_seconds=${ACX_DESCRIBE_LOAD_STALE_SECONDS:-120}
reader_uid=${ACX_GPU_READER_UID:-10001}
now_epoch=${ACX_NOW_EPOCH:-$(date +%s)}
config_only=${ACX_GPU_SNAPSHOT_CONFIG_ONLY:-0}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

is_positive_number() {
    awk -v value="$1" 'BEGIN { exit !(value ~ /^[0-9]+([.][0-9]+)?$/ && value > 0) }'
}

unit_path_for_flag() {
    local flag=$1
    local -a paths
    local path
    local path_count=0
    [ -r "$install_script" ] || die "lifecycle install script is missing or unreadable: $install_script"
    while IFS= read -r path; do
        paths[$path_count]=$path
        path_count=$((path_count + 1))
    done < <(
        sed -nE "s/.*${flag}[[:space:]]+([^[:space:]\\\\]+).*/\\1/p" "$install_script" |
            sort -u
    )
    [ "$path_count" -eq 1 ] ||
        die "lifecycle units do not have exactly one agreeing ${flag} path in $install_script"
    printf '%s\n' "${paths[0]}"
}

# Unit ExecStart flags are the authority for what the host actually writes.
# Test fixtures may override them, but production adds no fifth path literal.
unit_state_path=${ACX_GPU_UNIT_STATE_PATH:-}
unit_load_path=${ACX_GPU_UNIT_LOAD_PATH:-}
[ -n "$unit_state_path" ] || unit_state_path=$(unit_path_for_flag --gpu-state-json)
[ -n "$unit_load_path" ] || unit_load_path=$(unit_path_for_flag --load-json)
state_path=${ACX_GPU_STATE_PATH:-$unit_state_path}
load_path=${ACX_DESCRIBE_LOAD_PATH:-$unit_load_path}
snapshot_dir=${ACX_GPU_SNAPSHOT_DIR:-${unit_state_path%/*}}

[ "$state_path" = "$unit_state_path" ] ||
    die "ACX_GPU_STATE_PATH disagrees with lifecycle units: $state_path != $unit_state_path"
[ "$load_path" = "$unit_load_path" ] ||
    die "ACX_DESCRIBE_LOAD_PATH disagrees with lifecycle units: $load_path != $unit_load_path"
[ "$snapshot_dir" = "${unit_state_path%/*}" ] ||
    die "ACX_GPU_SNAPSHOT_DIR disagrees with lifecycle units: $snapshot_dir != ${unit_state_path%/*}"
[ "$snapshot_dir" = "${unit_load_path%/*}" ] ||
    die "GPU state and describe-load units do not share one snapshot directory"
is_positive_number "$state_stale_seconds" ||
    die "ACX_GPU_STATE_STALE_SECONDS must be a positive number"
is_positive_number "$load_stale_seconds" ||
    die "ACX_DESCRIBE_LOAD_STALE_SECONDS must be a positive number"
[[ "$reader_uid" =~ ^[0-9]+$ ]] || die "ACX_GPU_READER_UID must be numeric"
[[ "$now_epoch" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "ACX_NOW_EPOCH must be numeric"
[[ "$config_only" =~ ^[01]$ ]] || die "ACX_GPU_SNAPSHOT_CONFIG_ONLY must be 0 or 1"

[ -r "$compose_file" ] || die "compose file is missing or unreadable: $compose_file"

api_block=$(awk '
    /^  api:$/ { in_api = 1; next }
    in_api && /^  [A-Za-z0-9_-]+:$/ { exit }
    in_api && $0 !~ /^[[:space:]]*#/ { print }
' "$compose_file")
[ -n "$api_block" ] || die "compose file has no api service: $compose_file"

# Require the concrete mount that deployment will use. A literal, unexpanded
# Compose variable is not evidence that the lifecycle path is mounted read-only.
rendered_mount="${snapshot_dir}:${snapshot_dir}:ro"
if ! grep -Fq -- "$rendered_mount" <<<"$api_block"; then
    die "compose api service has no agreeing read-only snapshot mount ($rendered_mount)"
fi
if ! grep -Fq -- "ACX_GPU_STATE_PATH=${state_path}" <<<"$api_block"; then
    die "compose api service does not pass the agreeing ACX_GPU_STATE_PATH"
fi

if [ "$config_only" -eq 1 ]; then
    echo "OK: GPU snapshot lifecycle and compose configuration agree"
    exit 0
fi

reader_can_read() {
    local path=$1 current_uid
    current_uid=$(id -u)
    if [ "$current_uid" = "$reader_uid" ]; then
        test -r "$path"
    elif [ "$current_uid" = 0 ] && command -v setpriv >/dev/null 2>&1; then
        setpriv --reuid="$reader_uid" --regid="$reader_uid" --clear-groups test -r "$path"
    else
        return 2
    fi
}

check_snapshot() {
    local label=$1 path=$2 budget=$3 readability_rc=0 written_at age
    [ -e "$path" ] || die "missing $label snapshot: $path"
    [ -f "$path" ] || die "$label snapshot is not a regular file: $path"
    reader_can_read "$path" || readability_rc=$?
    if [ "$readability_rc" -eq 2 ]; then
        die "cannot verify $label snapshot readability as uid $reader_uid; run as root"
    elif [ "$readability_rc" -ne 0 ]; then
        die "$label snapshot is unreadable by uid $reader_uid: $path"
    fi

    written_at=$(python3 -c \
        'import json, math, sys; value=json.load(open(sys.argv[1], encoding="utf-8")).get("written_at"); assert not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value), "written_at must be finite epoch seconds"; print(value)' \
        "$path" 2>/dev/null) || die "$label snapshot has no valid written_at: $path"
    age=$(awk -v now="$now_epoch" -v written="$written_at" 'BEGIN { printf "%.6f", now - written }')
    awk -v age="$age" 'BEGIN { exit !(age >= 0) }' ||
        die "$label snapshot written_at is in the future: $written_at"
    awk -v age="$age" -v budget="$budget" 'BEGIN { exit !(age <= budget) }' ||
        die "stale $label snapshot: age ${age}s exceeds ${budget}s budget ($path)"
}

check_snapshot "GPU state" "$unit_state_path" "$state_stale_seconds"
check_snapshot "describe load" "$unit_load_path" "$load_stale_seconds"

echo "OK: GPU state and describe-load snapshot deployment contract is fresh"
