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
remote_command='set -eu; tmp=$(mktemp -d); trap '\''rm -rf -- "$tmp"'\'' EXIT; tar -xf - -C "$tmp"; sudo python3 -B "$tmp/scripts/env/render_env.py" materialize --root "$tmp/config/env"'
remote_command+=$arguments

# tarfile maps an arbitrary manifest directory without platform-specific tar transforms.
ssh_options=(
    -o "ConnectTimeout=${ENV_MATERIALIZE_SSH_CONNECT_TIMEOUT:-15}"
    -o "ServerAliveInterval=${ENV_MATERIALIZE_SSH_SERVER_ALIVE_INTERVAL:-15}"
    -o "ServerAliveCountMax=${ENV_MATERIALIZE_SSH_SERVER_ALIVE_COUNT_MAX:-4}"
    -o "BatchMode=yes"
)
set +e
python3 - "$repo_root" "$manifest_root" <<'PY' | ssh "${ssh_options[@]}" "${OCI_USER:-ubuntu}@${OCI_HOST:-acx-backend.tail1a44b8.ts.net}" "$remote_command"
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
if (( statuses[0] != 0 )); then
    printf 'materialize_remote.sh: tar producer failed with status %d\n' "${statuses[0]}" >&2
    exit "${statuses[0]}"
fi
exit "${statuses[1]}"
