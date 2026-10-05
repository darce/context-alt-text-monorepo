#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo 'Usage: materialize_remote.sh <env> <target> [--check|--apply] [--adopt]' >&2
    exit 2
}

[[ $# -ge 2 && -n $1 && -n $2 && $1 != --* && $2 != --* ]] || usage
environment=$1
target=$2
shift 2
mode=--check
adopt=false
for flag in "$@"; do
    case "$flag" in
        --check|--apply) mode=$flag ;;
        --adopt) adopt=true ;;
        *) usage ;;
    esac
done
[[ $adopt == false || $mode == --apply ]] || usage

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
manifest_root=${ENV_MANIFEST_ROOT:-$repo_root/config/env}
remote_path=$(python3 - "$repo_root" "$manifest_root" "$environment" "$target" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "scripts/env"))
from manifest import ManifestError, load_manifest

try:
    manifest = load_manifest(Path(sys.argv[2]))
except (ManifestError, OSError):
    print("Cannot load environment manifest", file=sys.stderr)
    sys.exit(2)
environment, target_name = sys.argv[3:5]
target = manifest.targets.get(target_name)
if target is None or environment not in target.remote_paths:
    print(f"No remote path for target {target_name} in {environment}", file=sys.stderr)
    sys.exit(2)
print(target.remote_paths[environment])
PY
)

printf -v arguments ' --env %q --target %q --into %q' "$environment" "$target" "$remote_path"
[[ $mode != --check ]] || arguments+=' --check'
[[ $adopt != true ]] || arguments+=' --adopt'
stage_nonce=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
remote_command='set -eu; tmp=; stage_file=; trap '\''status=$?; trap - EXIT; if [ -n "$stage_file" ] && [ -e "$stage_file" ]; then stage=materialize; else stage=bootstrap; fi; printf "__MATERIALIZE_REMOTE_STAGE_'"$stage_nonce"'__:%s:%s\n" "$stage" "$status" >&2; if [ -n "$tmp" ]; then rm -rf -- "$tmp"; fi; exit "$status"'\'' EXIT; tmp=$(mktemp -d); stage_file=$tmp/.materialize-stage; tar -xf - -C "$tmp"; sudo python3 -B -c '\''import importlib, sys; marker, script = sys.argv[1:3]; (sys.stderr.write("Python 3.11 or newer is required\n"), sys.exit(2)) if sys.version_info < (3, 11) else None; sys.argv = [script, *sys.argv[3:]]; namespace = {"__name__": "_materialize_remote", "__file__": script}; exec(compile(open(script, "rb").read(), script, "exec"), namespace); importlib.import_module("env.materialize"); open(marker, "x").close(); raise SystemExit(namespace["main"]())'\'' "$stage_file" "$tmp/scripts/env/render_env.py" materialize --root "$tmp/config/env"'
remote_command+=$arguments

# tarfile maps an arbitrary manifest directory without platform-specific tar transforms.
ssh_options=(
    -o "ConnectTimeout=${ENV_MATERIALIZE_SSH_CONNECT_TIMEOUT:-15}"
    -o "ServerAliveInterval=${ENV_MATERIALIZE_SSH_SERVER_ALIVE_INTERVAL:-15}"
    -o "ServerAliveCountMax=${ENV_MATERIALIZE_SSH_SERVER_ALIVE_COUNT_MAX:-4}"
    -o "BatchMode=yes"
)
# Keep the remote wrapper's stage marker separate from streamed stdout. The nonce makes
# incidental or malformed diagnostic text insufficient to classify a remote exit.
ssh_stderr_file=$(mktemp) || {
    local_status=$?
    printf 'materialize_remote.sh: cannot capture ssh diagnostics (mktemp exited with status %d)\n' \
        "$local_status" >&2
    exit "$local_status"
}
trap 'rm -f -- "$ssh_stderr_file"' EXIT
set +e
python3 - "$repo_root" "$manifest_root" <<'PY' | ssh "${ssh_options[@]}" "${OCI_USER:-ubuntu}@${OCI_HOST:-acx-backend.tail1a44b8.ts.net}" "$remote_command" 2>"$ssh_stderr_file"
import sys
import tarfile
from pathlib import Path

repo = Path(sys.argv[1])
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
    for path in sorted((repo / "scripts/env").glob("*.py")):
        archive.add(path, arcname=str(path.relative_to(repo)))
    archive.add(sys.argv[2], arcname="config/env")
PY
statuses=("${PIPESTATUS[@]}")
marker_prefix="__MATERIALIZE_REMOTE_STAGE_${stage_nonce}__"
marker_regex="^${marker_prefix}:(bootstrap|materialize):([0-9]{1,3})$"
marker_count=0
marker_stage=''
marker_status=''
while IFS= read -r ssh_line || [[ -n $ssh_line ]]; do
    if [[ $ssh_line == "$marker_prefix"* ]]; then
        marker_count=$((marker_count + 1))
        if [[ $ssh_line =~ $marker_regex ]]; then
            marker_stage=${BASH_REMATCH[1]}
            marker_status=${BASH_REMATCH[2]}
            continue
        fi
    fi
    printf '%s\n' "$ssh_line" >&2
done < "$ssh_stderr_file"
marker_valid=false
if (( marker_count == 1 )) && [[ $marker_status == "${statuses[1]}" ]]; then
    marker_valid=true
fi
if (( statuses[1] != 0 )); then
    if (( statuses[1] == 255 )); then
        if (( statuses[0] != 0 )); then
            printf 'materialize_remote.sh: ssh failed with status %d (tar producer also exited with status %d)\n' \
                "${statuses[1]}" "${statuses[0]}" >&2
        else
            printf 'materialize_remote.sh: ssh failed with status %d\n' "${statuses[1]}" >&2
        fi
    else
        if [[ $marker_valid == true && $marker_stage == bootstrap ]]; then
            printf -v remote_error 'remote bootstrap failed with status %d' "${statuses[1]}"
        elif [[ $marker_valid != true || $marker_stage != materialize ]]; then
            printf -v remote_error 'remote command exited with status %d (stage marker missing or invalid)' \
                "${statuses[1]}"
        else
            case "${statuses[1]}" in
                1)
                    if [[ $mode == --check ]]; then
                        remote_error='drift found (remote check exit 1)'
                    else
                        remote_error='remote materialize exited with status 1'
                    fi
                    ;;
                2) remote_error='remote materialize refused with status 2' ;;
                4) remote_error='required host secret is missing (remote materialize exit 4)' ;;
                75) remote_error='remote materialize lock or lease busy (exit 75)' ;;
                *) printf -v remote_error 'remote materialize exited with status %d' "${statuses[1]}" ;;
            esac
        fi
        if (( statuses[0] != 0 )); then
            printf 'materialize_remote.sh: %s (tar producer also exited with status %d)\n' \
                "$remote_error" "${statuses[0]}" >&2
        else
            printf 'materialize_remote.sh: %s\n' "$remote_error" >&2
        fi
    fi
    exit "${statuses[1]}"
fi
if (( statuses[0] != 0 )); then
    printf 'materialize_remote.sh: tar producer failed with status %d\n' "${statuses[0]}" >&2
    exit "${statuses[0]}"
fi
exit 0
