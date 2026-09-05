#!/usr/bin/env bash
# Validate the complete producer-to-demo GPU flip before deployment.
# Docker Compose env files are data, not shell; never source either input file.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/gpu-env-contract.sh
source "${script_dir}/lib/gpu-env-contract.sh"

check_reaper=0
if [[ "${1:-}" == --check-reaper ]]; then
    check_reaper=1
    shift
fi

if [[ $# -ne 2 ]]; then
    echo "Usage: scripts/deploy/preflight-gpu-env.sh [--check-reaper] <producer-env-file> <demo-env-file>" >&2
    exit 2
fi

producer_env="$1"
demo_env="$2"

for env_file in "$producer_env" "$demo_env"; do
    if [[ ! -r "$env_file" || ! -f "$env_file" ]]; then
        echo "ERROR [0] both env files must be readable regular files. Pass producer first, then demo." >&2
        exit 2
    fi
done

relevant_keys=(
    ACX_DESCRIPTION_ADAPTER
    ACX_GPU_ENDPOINT_URL
    ACX_GPU_ENDPOINT_API_KEY
    ACX_GPU_ENDPOINT_ALLOWLIST
    ACX_GPU_CONNECT_TIMEOUT_SECONDS
    ACX_GPU_READ_TIMEOUT_SECONDS
    ACX_GPU_MAX_CONCURRENT_CALLS
    ACX_GPU_WARMUP_TIMEOUT_SECONDS
    ACX_GPU_PROMPT_VERSION
    ACX_GPU_SNAPSHOT_DIR
    ACX_GPU_STATE_PATH
    ACX_GPU_STATE_STALE_SECONDS
    ACX_RECOGNITION_URL
    ACX_RECOGNITION_API_KEY
    ACX_RECOGNITION_TENANT_ID
    RECOGNITION_SECRET_BACKEND
    RECOGNITION_VAULT_SECRET_MAP
    WORDPRESS_CONFIG_EXTRA
)

# The contract deliberately uses a strict Compose-dotenv subset. This keeps the
# value checked here byte-identical to the value Compose deploys: no whitespace
# around '=', export prefix, interpolation, or inline comments. Quotes around a
# complete value are supported. Count non-canonical assignments too so they
# cannot conceal an earlier safe-looking value.
validate_contract_assignments() {
    local role="$1" file="$2" key line count value
    # Inspect every assignment before scanning contract keys. Compose permits
    # quoted values to span lines, including lines that look like assignments.
    # Reject that syntax even for unrelated keys so it cannot hide a contract.
    python3 - "$role" "$file" <<'PY'
import re
import sys

with open(sys.argv[2], encoding="utf-8") as document:
    for line in document:
        assignment = re.match(r"^\s*(?:export\s+)?[^\s=:#]+\s*[=:]\s*(.*)$", line.rstrip("\r\n"))
        if not assignment:
            continue
        value = assignment.group(1)
        if not value or value[0] not in ("'", '"'):
            continue
        quote = value[0]
        escaped = False
        for character in value[1:]:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                break
        else:
            print(f"ERROR [7] {sys.argv[1]} env has unsupported multiline or unterminated dotenv quoting (value redacted).", file=sys.stderr)
            raise SystemExit(1)
PY
    for key in "${relevant_keys[@]}"; do
        count=0
        while IFS= read -r line || [[ -n "$line" ]]; do
            line="${line%$'\r'}"
            if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*= ]]; then
                count=$((count + 1))
                if [[ "$line" != "${key}="* ]]; then
                    echo "ERROR [7] ${role} env ${key} assignment is not canonical KEY=value syntax. Remove whitespace/export ambiguity before deployment." >&2
                    exit 1
                fi
                value="${line#*=}"
                if ! acx_env_literal_value "$value" >/dev/null; then
                    echo "ERROR [7] ${role} env ${key} has invalid dotenv quoting (value redacted)." >&2
                    exit 1
                fi
                if [[ "$value" == *'$'* || "$value" =~ [[:space:]]# ]]; then
                    echo "ERROR [7] ${role} env ${key} must not use interpolation or an inline comment. Store the exact deployed value." >&2
                    exit 1
                fi
            fi
        done < "$file"
        if (( count > 1 )); then
            echo "ERROR [7] ${role} env contains duplicate ${key} assignments. Keep only the final effective assignment before deployment (count=${count})." >&2
            exit 1
        fi
    done
}

validate_contract_assignments producer "$producer_env"
validate_contract_assignments demo "$demo_env"

# Return the final exact KEY= entry without evaluating shell syntax.
env_get() {
    local file="$1" key="$2" line value=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        case "$line" in
            "${key}="*)
                value="$(acx_env_literal_value "${line#*=}")"
                ;;
        esac
    done < "$file"
    printf '%s' "$value"
}

is_placeholder() {
    printf '%s' "$1" | python3 -c '
import sys

value = "".join(character for character in sys.stdin.read() if not character.isspace()).casefold()
placeholders = ("replace", "placeholder", "change-me", "changeme", "paste-key", "paste_secret")
raise SystemExit(0 if not value or any(marker in value for marker in placeholders) or value.startswith(("<", ">")) else 1)
' 2>/dev/null
}

is_http_url() {
    python3 -c '
import sys
import ipaddress
import re
from urllib.parse import urlsplit

raw = sys.argv[1]
if not raw or any(char.isspace() for char in raw):
    raise SystemExit(1)
try:
    parsed = urlsplit(raw)
    port = parsed.port
except ValueError:
    raise SystemExit(1)
if parsed.scheme not in {"http", "https"}:
    raise SystemExit(1)
if "?" in raw or "#" in raw or parsed.query or parsed.fragment:
    raise SystemExit(1)
host = parsed.hostname
if not parsed.netloc or host is None or parsed.username is not None or parsed.password is not None:
    raise SystemExit(1)
if parsed.netloc.endswith(":"):
    raise SystemExit(1)
if port is not None and not 1 <= port <= 65535:
    raise SystemExit(1)
if ":" in host:
    try:
        ipaddress.IPv6Address(host)
    except ValueError:
        raise SystemExit(1)
else:
    labels = host.split(".")
    if any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels):
        raise SystemExit(1)
raise SystemExit(0)
' "$1" 2>/dev/null
}

hostname_matches_allowlist() {
    local host="$1" allowlist="$2" entry
    host="$(printf '%s' "$host" | LC_ALL=C tr '[:upper:]' '[:lower:]')"
    allowlist="${allowlist:-localhost,acx-gpu-burst,*.oraclevcn.com}"
    while IFS= read -r entry || [[ -n "$entry" ]]; do
        entry="$(printf '%s' "$entry" | tr -d '[:space:]' | LC_ALL=C tr '[:upper:]' '[:lower:]')"
        [[ -n "$entry" ]] || continue
        [[ "$host" == $entry ]] && return 0
    done < <(printf '%s' "$allowlist" | tr ',' '\n')
    return 1
}

ip_address_class() {
    python3 -c '
import ipaddress
import sys
try:
    address = ipaddress.ip_address(sys.argv[1])
    address = getattr(address, "ipv4_mapped", None) or address
except ValueError:
    raise SystemExit(2)
raise SystemExit(0 if address.is_private and not (address.is_link_local or address.is_loopback or address.is_unspecified or address.is_multicast) else 1)
' "$1" 2>/dev/null
}

resolved_addresses_are_private() {
    local host="$1" addresses
    addresses="$(getent ahosts "$host" 2>/dev/null | awk 'NF { print $1 }' | sort -u)" || return 1
    [[ -n "$addresses" ]] || return 1
    printf '%s\n' "$addresses" | python3 -c '
import ipaddress
import sys
addresses = [line.strip() for line in sys.stdin if line.strip()]
if not addresses:
    raise SystemExit(1)
for raw in addresses:
    try:
        address = ipaddress.ip_address(raw)
        address = getattr(address, "ipv4_mapped", None) or address
    except ValueError:
        raise SystemExit(1)
    if not address.is_private or address.is_link_local or address.is_loopback or address.is_unspecified or address.is_multicast:
        raise SystemExit(1)
' 2>/dev/null
}

is_private_gpu_endpoint() {
    local url="$1" allowlist="$2" authority host address_status
    is_http_url "$url" || return 1
    authority="${url#*://}"
    authority="${authority%%/*}"
    [[ "$authority" != *@* ]] || return 1
    if [[ "$authority" == \[*\]* ]]; then
        host="${authority#\[}"
        host="${host%%\]*}"
        ip_address_class "$host"
        return
    fi
    host="${authority%%:*}"
    if ip_address_class "$host"; then
        return 0
    else
        address_status=$?
        [[ "$address_status" -eq 2 ]] || return 1
    fi
    hostname_matches_allowlist "$host" "$allowlist" || return 1
    resolved_addresses_are_private "$host"
}

is_tenant_uuid() {
    printf '%s' "$1" | LC_ALL=C grep -Eq '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'
}

vault_map_value() {
    local map="$1" key="$2"
    printf '%s' "$map" | python3 -c '
import json
import sys

class DuplicateKey(ValueError):
    pass

def object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey(key)
        result[key] = value
    return result

try:
    mapping = json.load(sys.stdin, object_pairs_hook=object_without_duplicates)
except (json.JSONDecodeError, DuplicateKey):
    raise SystemExit(1)
if not isinstance(mapping, dict) or not mapping:
    raise SystemExit(1)
if any(not isinstance(key, str) or not key or not isinstance(value, str) or not value for key, value in mapping.items()):
    raise SystemExit(1)
value = mapping.get(sys.argv[1])
if not isinstance(value, str):
    raise SystemExit(1)
sys.stdout.write(value)
' "$key" 2>/dev/null
}

is_finite_positive_number() {
    python3 -c '
import math
import sys
try:
    value = float(sys.argv[1])
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if math.isfinite(value) and value > 0 else 1)
' "$1" 2>/dev/null
}

validate_runtime_gpu_settings() {
    local file="$1" key value entry
    for key in ACX_GPU_CONNECT_TIMEOUT_SECONDS ACX_GPU_READ_TIMEOUT_SECONDS; do
        value="$(env_get "$file" "$key")"
        if ! is_finite_positive_number "$value"; then
            echo "ERROR [10] producer ${key} must be a finite positive number (redacted length=${#value})." >&2
            exit 1
        fi
    done

    value="$(env_get "$file" ACX_GPU_MAX_CONCURRENT_CALLS)"
    if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
        echo "ERROR [10] producer ACX_GPU_MAX_CONCURRENT_CALLS must be a positive integer (redacted length=${#value})." >&2
        exit 1
    fi

    value="$(env_get "$file" ACX_GPU_WARMUP_TIMEOUT_SECONDS)"
    if ! is_finite_positive_number "$value" \
        || ! python3 -c 'import sys; raise SystemExit(0 if float(sys.argv[1]) <= 3600 else 1)' "$value" 2>/dev/null; then
        echo "ERROR [10] producer ACX_GPU_WARMUP_TIMEOUT_SECONDS must be finite and in (0, 3600] (redacted length=${#value})." >&2
        exit 1
    fi

    value="$(env_get "$file" ACX_GPU_ENDPOINT_ALLOWLIST)"
    [[ -n "$value" ]] || {
        echo "ERROR [10] producer ACX_GPU_ENDPOINT_ALLOWLIST must be a non-empty comma-separated hostname pattern list." >&2
        exit 1
    }
    while IFS= read -r entry || [[ -n "$entry" ]]; do
        if [[ -z "$entry" || "$entry" =~ [[:space:]] || ! "$entry" =~ ^(\*\.)?[A-Za-z0-9][A-Za-z0-9._?-]*$ ]]; then
            echo "ERROR [10] producer ACX_GPU_ENDPOINT_ALLOWLIST contains an invalid hostname pattern; values are redacted." >&2
            exit 1
        fi
    done < <(printf '%s' "$value" | tr ',' '\n')

    value="$(env_get "$file" ACX_GPU_PROMPT_VERSION)"
    if is_placeholder "$value"; then
        echo "ERROR [10] producer ACX_GPU_PROMPT_VERSION must be non-empty and non-placeholder." >&2
        exit 1
    fi
}

reaper_execstart_is_structural() {
    python3 -c '
import shlex
import sys
import math
from pathlib import Path

raw = sys.argv[1].strip()
if raw.startswith("{"):
    # systemd permits @ to make argv[0] differ from the executable. Check
    # both, and reject multiple ExecStart records rather than certifying one.
    if (raw.split(" ; ", 1)[0].strip() != "{ path=/usr/bin/python3"
            or raw.count("argv[]=") != 1 or not raw.endswith("}")):
        raise SystemExit(1)
    marker = "argv[]="
    start = raw.find(marker)
    if start < 0:
        raise SystemExit(1)
    argv_text = raw[start + len(marker):]
    argv_text = argv_text.split(" ; ", 1)[0]
else:
    argv_text = raw
try:
    argv = shlex.split(argv_text)
except ValueError:
    raise SystemExit(1)
if argv[:4] != ["/usr/bin/python3", "-m", "infra.oci.gpu_lifecycle", "--mode"]:
    raise SystemExit(1)
if len(argv) < 5 or argv[4] != "reap":
    raise SystemExit(1)
if [index for index, token in enumerate(argv) if token == "--mode"] != [3]:
    raise SystemExit(1)

required = {
    "--instance-id": "${GPU_INSTANCE_ID}",
    "--max-lease-seconds": "${MAX_LEASE_SECONDS}",
}
for option, expected in required.items():
    positions = [index for index, token in enumerate(argv) if token == option]
    if len(positions) != 1 or positions[0] + 1 >= len(argv) or argv[positions[0] + 1] != expected:
        raise SystemExit(1)
# Only the installer option surface is permitted. Exact spellings and one
# occurrence prevent argparse abbreviations, overrides and no-op/test flags.
allowed = {"--mode", "--instance-id", "--max-lease-seconds", "--load-dir",
           "--load-stale-grace-seconds", "--gpu-state-json", "--running-since-path",
           "--idle-seconds", "--fence-delay-seconds", "--probe-oci", "--oci-bin"}
seen = set()
i = 3
while i < len(argv):
    option = argv[i]
    if option not in allowed or option in seen:
        raise SystemExit(1)
    seen.add(option)
    i += 1 if option == "--probe-oci" else 2
    if i > len(argv):
        raise SystemExit(1)

# Use the parser shipped with the effective service, without invoking main or
# any actuator. Never silently import a different checkout from ambient PATH.
root = Path(sys.argv[2]).resolve(strict=True)
sys.path.insert(0, str(root))
from infra.oci.gpu_lifecycle import reaper
Path(reaper.__file__).resolve().relative_to(root)
parser = reaper._build_parser()
parser.allow_abbrev = False
values = dict(zip(("GPU_INSTANCE_ID", "MAX_LEASE_SECONDS", "IDLE_SECONDS",
                   "ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS"), sys.argv[3:7]))
resolved = []
for token in argv[3:]:
    if token.startswith("${") and token.endswith("}"):
        token = values.get(token[2:-1], "")
    resolved.append(token)
args = parser.parse_args(resolved)
if args.mode != "reap" or args.max_lease_seconds <= 0 or args.dry_run:
    raise SystemExit(1)
if args.instance_ids != [sys.argv[3]]:
    raise SystemExit(1)
# Parser success alone does not make main runnable: production requires the
# aggregate load source, and main rejects non-finite/negative lifecycle delays.
if args.load_dir != Path("/run/acx-write"):
    raise SystemExit(1)
if (args.oci_timeout_seconds <= 0 or args.max_wait_seconds <= 0
        or not math.isfinite(args.fence_delay_seconds) or args.fence_delay_seconds < 0
        or not math.isfinite(args.ready_sleep_seconds) or args.ready_sleep_seconds < 0):
    raise SystemExit(1)
# Probe only CLI help, never an OCI API or lifecycle command. Use the service
# identity and a clean system-service environment, not the operators PATH.
import os
import pwd
import subprocess
try:
    account = pwd.getpwnam(sys.argv[7] or "root")
    runtime_env = {
        "HOME": account.pw_dir,
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LC_ALL": "C",
    }
    binary = args.oci_bin or "oci"
    command = [binary, "--help"]
    if account.pw_uid != os.geteuid():
        command = ["/usr/bin/sudo", "-n", "-u", account.pw_name, "--",
                   "/usr/bin/env", "-i",
                   *[f"{key}={value}" for key, value in runtime_env.items()],
                   *command]
    result = subprocess.run(command, cwd=root, env=runtime_env,
                            capture_output=True, text=True, timeout=10)
    if result.returncode or "Oracle Cloud Infrastructure" not in result.stdout:
        raise ValueError("not OCI CLI help")
except (KeyError, OSError, ValueError, subprocess.SubprocessError):
    print("ERROR [11] OCI executable must run as the service user and identify "
          "the Oracle Cloud Infrastructure CLI via --help.", file=os.fdopen(3, "w"))
    raise SystemExit(1)
# Exercise the installed lease store in the actual parent directory, with a
# unique disposable state file. Do not reset or lock the live GPU lease.
lease_probe = """
import os
import sys
import tempfile
from pathlib import Path
root, raw_path = sys.argv[1:]
sys.path.insert(0, root)
from infra.oci.gpu_lifecycle.reaper import RunningSinceLeaseStore
path = Path(raw_path)
if not path.is_absolute() or path.name in ("", ".", ".."):
    raise ValueError("lease path must be an absolute file path")
# Existing runtime files must also support the stores read/update contract.
for candidate, access in (
    (path, os.R_OK | os.W_OK),
    (path.with_name(f".{path.name}.lock"), os.R_OK | os.W_OK),
    (path.with_name(f".{path.name}.tmp"), os.W_OK),
):
    if candidate.is_symlink() or (candidate.exists() and
            (not candidate.is_file() or not os.access(candidate, access))):
        raise ValueError("unusable lease state, lock or temporary file")
# Require the runtime directory to exist: systemd provisions it at service
# startup. Preflight must not silently create a misconfigured directory.
fd, probe_name = tempfile.mkstemp(prefix=".acx-lease-preflight-", dir=path.parent)
os.close(fd)
probe = Path(probe_name)
try:
    probe.unlink()
    store = RunningSinceLeaseStore(path=probe)
    store.write("preflight", source="first_observed")
    store.write("preflight", source="first_observed")
    assert store.read("preflight") is not None
    store.remove("preflight")
finally:
    for candidate in (probe, probe.with_name(f".{probe.name}.lock"),
                      probe.with_name(f".{probe.name}.tmp")):
        candidate.unlink(missing_ok=True)
"""
# Validate the interpreter the service actually executes, independently of
# whether changing to the service account is necessary.
probe_python = argv[0]
def run_python_probe(code, *arguments):
    command = [probe_python, "-c", code, str(root), *arguments]
    if account.pw_uid != os.geteuid():
        command = ["/usr/bin/sudo", "-n", "-u", account.pw_name, "--",
                   "/usr/bin/env", "-i",
                   *[f"{key}={value}" for key, value in runtime_env.items()], *command]
    return subprocess.run(command, cwd=root, env=runtime_env,
                          capture_output=True, text=True, timeout=10)

import_probe = """
import sys
from pathlib import Path
print(sys.version.split()[0], flush=True)
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
from infra.oci.gpu_lifecycle import reaper
Path(reaper.__file__).resolve().relative_to(root)
"""
probe_version = "unavailable"
try:
    result = run_python_probe(import_probe)
    probe_version = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "unavailable"
    if result.returncode:
        raise ValueError("reaper import failed")
except (OSError, ValueError, subprocess.SubprocessError):
    print(f"ERROR [11] probe interpreter {probe_python} (version {probe_version}) "
          "cannot import the installed infra.oci.gpu_lifecycle.reaper as the service user.",
          file=os.fdopen(3, "w"))
    raise SystemExit(1)
try:
    result = run_python_probe(lease_probe, str(args.running_since_path))
    if result.returncode:
        raise ValueError("lease store probe failed")
except (OSError, ValueError, subprocess.SubprocessError):
    print("ERROR [11] running-since lease path must support lifecycle state, lock "
          "and atomic replacement writes as the service user.", file=os.fdopen(3, "w"))
    raise SystemExit(1)
# Use exactly the production constructor inputs: this validates the deployment
# registry shipped with the effective service checkout. Construction reads no
# snapshots and performs no actuation.
reaper.AggregateJobLoadSource(
    directory=args.load_dir,
    stale_seconds=args.load_max_age_seconds,
    stale_grace_seconds=args.load_stale_grace_seconds,
)
' "$@" 3>&2 2>/dev/null
}

validate_reaper_environment_file() {
    # Deliberately accept only an unambiguous subset of systemd syntax. This
    # makes env_get byte-equivalent to runtime parsing (including last-wins).
    # Reject continuations, embedded quotes, whitespace and unknown keys.
    python3 - "$1" <<'PY'
import re
import sys
from pathlib import Path

keys = {"GPU_INSTANCE_ID", "MAX_LEASE_SECONDS", "IDLE_SECONDS",
        "ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS", "READY_URL"}
with Path(sys.argv[1]).open(newline="") as stream:
    lines = stream.read().split("\n")
for line in lines:
    line = line.removesuffix("\r")
    if not line.strip() or line.lstrip().startswith(("#", ";")):
        continue
    key, separator, value = line.partition("=")
    if not separator or key not in keys:
        raise SystemExit(1)
    if value.startswith(("\"", "'")):
        if len(value) < 2 or value[-1] != value[0]:
            raise SystemExit(1)
        value = value[1:-1]
    if re.search(r"[\s\x00-\x1f\x7f\"'\\$]", value):
        raise SystemExit(1)
PY
}

preflight_gpu_reaper() {
    local timer unit_properties exec_start fragment_path environment_files working_directory
    local timer_target unset_environment parsed_environment_files
    local idle_seconds="" stale_grace="" service_user
    local environment_file optional_file instance_id="" max_lease="" value
    local environment_file_count=0
    command -v systemctl >/dev/null 2>&1 || {
        echo "ERROR [11] GPU lifecycle timers cannot be verified because systemctl is unavailable." >&2
        exit 1
    }

    for timer in acx-gpu-reap.timer acx-gpu-start.timer; do
        systemctl is-enabled --quiet "$timer" \
            && systemctl is-active --quiet "$timer" || {
            echo "ERROR [11] ${timer} must be enabled and active before the GPU flip." >&2
            exit 1
        }
    done

    timer_target="$(systemctl show acx-gpu-reap.timer --property=Unit 2>/dev/null)" || {
        echo "ERROR [11] acx-gpu-reap.timer effective Unit could not be read." >&2
        exit 1
    }
    [[ "$timer_target" == "Unit=acx-gpu-reap.service" ]] || {
        echo "ERROR [11] acx-gpu-reap.timer must activate acx-gpu-reap.service." >&2
        exit 1
    }

    unit_properties="$(systemctl show acx-gpu-reap.service \
        --property=User \
        --property=ExecStart \
        --property=WorkingDirectory \
        --property=FragmentPath \
        --property=DropInPaths \
        --property=UnsetEnvironment \
        --property=EnvironmentFiles 2>/dev/null)" || {
        echo "ERROR [11] acx-gpu-reap.service effective properties could not be read." >&2
        exit 1
    }
    service_user="$(printf '%s\n' "$unit_properties" | sed -n 's/^User=//p')"
    exec_start="$(printf '%s\n' "$unit_properties" | sed -n 's/^ExecStart=//p')"
    fragment_path="$(printf '%s\n' "$unit_properties" | sed -n 's/^FragmentPath=//p')"
    environment_files="$(printf '%s\n' "$unit_properties" | sed -n 's/^EnvironmentFiles=//p')"
    working_directory="$(printf '%s\n' "$unit_properties" | sed -n 's/^WorkingDirectory=//p')"
    [[ "$working_directory" == /* && "$fragment_path" == /* && "$fragment_path" != /dev/null ]] || {
        echo "ERROR [11] acx-gpu-reap.service must structurally target GPU_INSTANCE_ID and MAX_LEASE_SECONDS." >&2
        exit 1
    }

    unset_environment="$(printf '%s\n' "$unit_properties" | sed -n 's/^UnsetEnvironment=//p')"
    # Unsetting is applied after every EnvironmentFile. Reject removals of
    # validated variables, including value-specific removals, conservatively.
    python3 -c '
import shlex, sys
required = {"GPU_INSTANCE_ID", "MAX_LEASE_SECONDS", "IDLE_SECONDS",
            "ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS"}
try:
    entries = shlex.split(sys.argv[1])
except ValueError:
    raise SystemExit(1)
if any(entry.split("=", 1)[0] in required for entry in entries):
    raise SystemExit(1)
' "$unset_environment" || {
        echo "ERROR [11] reaper UnsetEnvironment may remove a required lifecycle variable." >&2
        exit 1
    }

    [[ -n "$environment_files" ]] || {
        echo "ERROR [11] acx-gpu-reap.service has no effective EnvironmentFiles." >&2
        exit 1
    }
    # Keep systemctl metadata attached to its path. Unknown/ambiguous rendered
    # syntax fails closed instead of silently skipping a possibly required file.
    parsed_environment_files="$(python3 -c '
import re, sys
raw = sys.argv[1]
pattern = re.compile(r"(-?/[^\s]+)(?: +\(ignore_errors=(yes|no)\))?(?: +|$)")
while raw:
    match = pattern.match(raw)
    if not match:
        raise SystemExit(1)
    path, optional = match.groups()
    print(("-" if optional == "yes" and not path.startswith("-") else "") + path)
    raw = raw[match.end():]
' "$environment_files")" || {
        echo "ERROR [11] reaper EnvironmentFiles rendering is ambiguous." >&2
        exit 1
    }
    while IFS= read -r environment_file; do
        case "$environment_file" in
            /*|'-/'*) ;;
            *) continue ;;
        esac
        optional_file=0
        if [[ "$environment_file" == -/* ]]; then
            optional_file=1
            environment_file="${environment_file#-}"
        fi
        if [[ ! -r "$environment_file" || ! -f "$environment_file" ]]; then
            if (( optional_file )); then
                continue
            fi
            echo "ERROR [11] acx-gpu-reap.service EnvironmentFile is missing or unreadable." >&2
            exit 1
        fi
        environment_file_count=$((environment_file_count + 1))
        validate_reaper_environment_file "$environment_file" 2>/dev/null || {
            echo "ERROR [11] reaper EnvironmentFile must use canonical recognised KEY=value assignments with optional whole-value quotes; values are redacted." >&2
            exit 1
        }
        if LC_ALL=C grep -q '^GPU_INSTANCE_ID=' "$environment_file"; then
            value="$(env_get "$environment_file" GPU_INSTANCE_ID)"
            instance_id="$value"
        fi
        if LC_ALL=C grep -q '^MAX_LEASE_SECONDS=' "$environment_file"; then
            value="$(env_get "$environment_file" MAX_LEASE_SECONDS)"
            max_lease="$value"
        fi
        if LC_ALL=C grep -q '^IDLE_SECONDS=' "$environment_file"; then
            idle_seconds="$(env_get "$environment_file" IDLE_SECONDS)"
        fi
        if LC_ALL=C grep -q '^ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS=' "$environment_file"; then
            stale_grace="$(env_get "$environment_file" ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS)"
        fi
    done < <(printf '%s\n' "$parsed_environment_files")

    (( environment_file_count > 0 )) || {
        echo "ERROR [11] acx-gpu-reap.service has no readable effective EnvironmentFiles." >&2
        exit 1
    }
    [[ "$instance_id" =~ ^ocid1\.instance\.oc[0-9]+\.[A-Za-z0-9._-]+$ \
        && "$max_lease" =~ ^[1-9][0-9]{0,4}$ ]] \
        && (( max_lease <= 86400 )) || {
        echo "ERROR [11] reaper GPU_INSTANCE_ID must be an instance OCID and MAX_LEASE_SECONDS must be in 1..86400." >&2
        exit 1
    }
    reaper_execstart_is_structural "$exec_start" "$working_directory" "$instance_id" "$max_lease" "$idle_seconds" "$stale_grace" "$service_user" || {
        echo "ERROR [11] acx-gpu-reap.service ExecStart must be the structurally valid GPU lifecycle reaper." >&2
        exit 1
    }
    printf "MANUAL STOP fallback: oci compute instance action --action STOP --instance-id '%s'\n" "$instance_id"
}

validate_side() {
    local role="$1" file="$2"
    local adapter endpoint_url endpoint_api_key snapshot_dir state_path stale_seconds
    local recognition_url recognition_api_key recognition_tenant_id wordpress_config_extra
    local secret_backend vault_map vault_gpu_ref normalized_snapshot_dir state_dir endpoint_allowlist
    local missing_recognition=()

    adapter="$(env_get "$file" ACX_DESCRIPTION_ADAPTER)"
    endpoint_url="$(env_get "$file" ACX_GPU_ENDPOINT_URL)"
    endpoint_api_key="$(env_get "$file" ACX_GPU_ENDPOINT_API_KEY)"
    endpoint_allowlist="$(env_get "$producer_env" ACX_GPU_ENDPOINT_ALLOWLIST)"
    snapshot_dir="$(env_get "$file" ACX_GPU_SNAPSHOT_DIR)"
    state_path="$(env_get "$file" ACX_GPU_STATE_PATH)"
    stale_seconds="$(env_get "$file" ACX_GPU_STATE_STALE_SECONDS)"

    if ! acx_is_trusted_describe_profile "$adapter"; then
        echo "ERROR [1] ${role} ACX_DESCRIPTION_ADAPTER must be florence_small, gpu_qwen30b, or gpu_qwen30b_ensemble. Set one validated live adapter (redacted length=${#adapter})." >&2
        exit 1
    fi

    if [[ "$adapter" == gpu_* ]] && ! is_http_url "$endpoint_url"; then
        echo "ERROR [2] ${role} ACX_GPU_ENDPOINT_URL must be a valid http:// or https:// URL for a gpu_* adapter (redacted length=${#endpoint_url})." >&2
        exit 1
    fi
    if [[ "$adapter" == gpu_* ]] && ! is_private_gpu_endpoint "$endpoint_url" "$endpoint_allowlist"; then
        echo "ERROR [9] ${role} ACX_GPU_ENDPOINT_URL must use a private/loopback IP or an ACX_GPU_ENDPOINT_ALLOWLIST hostname (redacted length=${#endpoint_url})." >&2
        exit 1
    fi

    secret_backend="$(env_get "$file" RECOGNITION_SECRET_BACKEND)"
    if [[ "$role" == producer ]]; then
        case "$secret_backend" in
            env|oci_vault) ;;
            *)
                echo "ERROR [3] producer RECOGNITION_SECRET_BACKEND must be exactly env or oci_vault (redacted length=${#secret_backend})." >&2
                exit 1
                ;;
        esac
    elif [[ -n "$secret_backend" ]]; then
        case "$secret_backend" in
            env|oci_vault) ;;
            *)
                echo "ERROR [3] demo RECOGNITION_SECRET_BACKEND, when present, must be exactly env or oci_vault (redacted length=${#secret_backend})." >&2
                exit 1
                ;;
        esac
    fi
    if [[ "$role" == producer && "$secret_backend" == oci_vault ]]; then
        vault_map="$(env_get "$file" RECOGNITION_VAULT_SECRET_MAP)"
        if ! vault_gpu_ref="$(vault_map_value "$vault_map" ACX_GPU_ENDPOINT_API_KEY)"; then
            vault_gpu_ref=""
        fi
        if is_placeholder "$vault_gpu_ref" || ! printf '%s' "$vault_gpu_ref" | LC_ALL=C grep -Eq '^ocid1\.vaultsecret\.oc[0-9]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9._-]+$'; then
            echo "ERROR [3] producer oci_vault backend requires a non-placeholder ACX_GPU_ENDPOINT_API_KEY OCID in RECOGNITION_VAULT_SECRET_MAP (redacted length=${#vault_gpu_ref})." >&2
            exit 1
        fi
        if [[ -n "$endpoint_api_key" ]]; then
            echo "ERROR [3] producer oci_vault backend requires ACX_GPU_ENDPOINT_API_KEY to be blank; Vault is the only credential source (redacted length=${#endpoint_api_key})." >&2
            exit 1
        fi
    elif [[ "$role" == producer && -n "$endpoint_url" ]] && is_placeholder "$endpoint_api_key"; then
        echo "ERROR [3] ${role} env backend requires a non-placeholder ACX_GPU_ENDPOINT_API_KEY while ACX_GPU_ENDPOINT_URL is set (redacted length=${#endpoint_api_key})." >&2
        exit 1
    elif [[ "$role" == demo && -n "$endpoint_api_key" ]]; then
        echo "ERROR [3] demo ACX_GPU_ENDPOINT_API_KEY must be absent; only the producer consumes this secret (redacted length=${#endpoint_api_key})." >&2
        exit 1
    fi

    if [[ "$snapshot_dir" != /run/acx || "$state_path" != /run/acx/gpu-state.json ]]; then
        echo "ERROR [4] ${role} ACX_GPU_SNAPSHOT_DIR and ACX_GPU_STATE_PATH must be /run/acx and /run/acx/gpu-state.json, respectively, as required by the compose mount and lifecycle units." >&2
        exit 1
    fi

    case "$stale_seconds" in
        ''|*[!0-9]*)
            echo "ERROR [5] ${role} ACX_GPU_STATE_STALE_SECONDS must be a positive integer (redacted length=${#stale_seconds})." >&2
            exit 1
            ;;
    esac
    if [[ -z "${stale_seconds//0/}" ]] || ! is_finite_positive_number "$stale_seconds"; then
        echo "ERROR [5] ${role} ACX_GPU_STATE_STALE_SECONDS must be a positive integer (redacted length=${#stale_seconds})." >&2
        exit 1
    fi

    if [[ "$role" == demo ]]; then
        recognition_url="$(env_get "$file" ACX_RECOGNITION_URL)"
        recognition_api_key="$(env_get "$file" ACX_RECOGNITION_API_KEY)"
        recognition_tenant_id="$(env_get "$file" ACX_RECOGNITION_TENANT_ID)"
        wordpress_config_extra="$(env_get "$file" WORDPRESS_CONFIG_EXTRA)"
        if [[ -n "$recognition_url" || -n "$recognition_api_key" || -n "$recognition_tenant_id" ]]; then
            echo "ERROR [6] demo standalone ACX_RECOGNITION_* entries are ambiguous. Remove them and edit only WORDPRESS_CONFIG_EXTRA PHP constants." >&2
            exit 1
        fi
        recognition_url="$(php_define_value ACX_RECOGNITION_URL "$wordpress_config_extra")"
        recognition_api_key="$(php_define_value ACX_RECOGNITION_API_KEY "$wordpress_config_extra")"
        recognition_tenant_id="$(php_define_value ACX_RECOGNITION_TENANT_ID "$wordpress_config_extra")"

        [[ -n "$recognition_url" ]] || missing_recognition+=(ACX_RECOGNITION_URL)
        [[ -n "$recognition_api_key" ]] || missing_recognition+=(ACX_RECOGNITION_API_KEY)
        [[ -n "$recognition_tenant_id" ]] || missing_recognition+=(ACX_RECOGNITION_TENANT_ID)
        if (( ${#missing_recognition[@]} > 0 )); then
            printf 'ERROR [6] demo recognition config is incomplete. Set:' >&2
            printf ' %s' "${missing_recognition[@]}" >&2
            printf '. Secret values remain redacted; ACX_RECOGNITION_API_KEY length=%s.\n' "${#recognition_api_key}" >&2
            exit 1
        fi
        if ! is_http_url "$recognition_url"; then
            echo "ERROR [6] demo ACX_RECOGNITION_URL must be a valid http:// or https:// URL (redacted length=${#recognition_url})." >&2
            exit 1
        fi
        if is_placeholder "$recognition_api_key"; then
            echo "ERROR [6] demo ACX_RECOGNITION_API_KEY must not be a documented placeholder (redacted length=${#recognition_api_key})." >&2
            exit 1
        fi
        if ! is_tenant_uuid "$recognition_tenant_id" \
            || is_placeholder "$recognition_tenant_id" \
            || [[ "$recognition_tenant_id" == 00000000-0000-4000-8000-000000000001 ]]; then
            echo "ERROR [6] demo ACX_RECOGNITION_TENANT_ID must be an explicit RFC 4122 UUID (redacted length=${#recognition_tenant_id})." >&2
            exit 1
        fi
    fi
}

if (( check_reaper )); then
    preflight_gpu_reaper
fi

validate_runtime_gpu_settings "$producer_env"
validate_side producer "$producer_env"
validate_side demo "$demo_env"

shared_keys=(
    ACX_DESCRIPTION_ADAPTER
    ACX_GPU_ENDPOINT_URL
    ACX_GPU_SNAPSHOT_DIR
    ACX_GPU_STATE_PATH
    ACX_GPU_STATE_STALE_SECONDS
)
for key in "${shared_keys[@]}"; do
    if [[ "$(env_get "$producer_env" "$key")" != "$(env_get "$demo_env" "$key")" ]]; then
        echo "ERROR [8] producer and demo ${key} values differ. Make the two halves of the flip identical; values are redacted." >&2
        exit 1
    fi
done
adapter="$(env_get "$producer_env" ACX_DESCRIPTION_ADAPTER)"
printf 'OK: GPU env preflight passed (producer+demo, adapter=%s).\n' "$adapter"
