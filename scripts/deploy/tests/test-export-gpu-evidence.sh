#!/usr/bin/env bash
# Contract tests for the read-only GPU evidence exporter.

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL: this suite must run under bash" >&2
    exit 2
fi
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exporter="${root}/scripts/deploy/lib/export-gpu-evidence.sh"
fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT

fake_oci="${fixture_root}/oci"
call_log="${fixture_root}/oci-calls.log"
curl_call_log="${fixture_root}/curl-calls.log"
cat >"${fake_oci}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${OCI_CALL_LOG}"
case " $* " in
    *" compute instance get "*)
        printf '%s\n' '{"data":{"id":"ocid1.instance.example","compartment-id":"ocid1.compartment.example","lifecycle-state":"STOPPED"}}'
        ;;
    *" audit event list "*)
        printf '%s\n' '{"data":[{"event-type":"com.oraclecloud.computeapi.StartInstance.begin","event-time":"2026-09-01T00:09:59Z","event-id":"start-begin","event-grouping-id":"start-1","data":{"resource-id":"ocid1.instance.example","identity":{"principal-name":"burst-start"},"request":{"parameters":{"action":"START"}},"response":{"status":"200"},"state-change":{"previous":{"lifecycleState":"STOPPED"},"current":{"lifecycleState":"STARTING"}}}},{"event-type":"com.oraclecloud.computeapi.StartInstance.end","event-time":"2026-09-01T00:10:00Z","event-id":"start-1","event-grouping-id":"start-1","data":{"resource-id":"ocid1.instance.example","identity":{"principal-name":"burst-start"},"request":{"parameters":{"action":"START"}},"response":{"status":"200"},"state-change":{"previous":{"lifecycleState":"STARTING"},"current":{"lifecycleState":"RUNNING"}}}},{"event-type":"com.oraclecloud.computeapi.StopInstance.begin","event-time":"2026-09-01T00:29:59Z","event-id":"stop-begin","event-grouping-id":"stop-1","data":{"resource-id":"ocid1.instance.example","identity":{"principal-name":"gpu-reaper"},"request":{"parameters":{"action":"STOP"}},"response":{"status":"200"},"state-change":{"previous":{"lifecycleState":"RUNNING"},"current":{"lifecycleState":"STOPPING"}}}},{"event-type":"com.oraclecloud.computeapi.StopInstance.end","event-time":"2026-09-01T00:30:00Z","event-id":"stop-1","event-grouping-id":"stop-1","data":{"resource-id":"ocid1.instance.example","identity":{"principal-name":"gpu-reaper"},"request":{"parameters":{"action":"STOP"}},"response":{"status":"200"},"state-change":{"previous":{"lifecycleState":"STOPPING"},"current":{"lifecycleState":"STOPPED"}}}}]}'
        ;;
    *)
        echo "unexpected OCI argv: $*" >&2
        exit 41
        ;;
esac
EOF
chmod +x "${fake_oci}"
fake_curl="${fixture_root}/curl"
cat >"${fake_curl}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${CURL_CALL_LOG}"
output=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output)
            output="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done
[ -n "$output" ] || exit 42
printf '%s\n' '{"gpu_state":"STOPPED","instance_id":"ocid1.instance.example","written_at":"2026-09-01T00:30:00Z"}' >"$output"
EOF
chmod +x "${fake_curl}"
snapshot="${fixture_root}/gpu-state.json"
receipts="${fixture_root}/wp-receipts.json"
printf '%s\n' '{"state":"stopped","instance_id":"ocid1.instance.example","written_at":1788222600}' >"${snapshot}"
printf '%s\n' '{"items":[{"description":"A red bicycle","timestamp":"2026-09-01T00:20:00Z"}]}' >"${receipts}"
export OCI_BIN="${fake_oci}"
export OCI_CALL_LOG="${call_log}"
export CURL_CALL_LOG="${curl_call_log}"
export PATH="${fixture_root}:${PATH}"

if ! grep -Fxq -- 'docs/evidence/' "${root}/.gitignore"; then
    echo "FAIL: docs/evidence/ is not ignored" >&2
    exit 1
fi

one="${fixture_root}/one"
two="${fixture_root}/two"
run_export() {
    "$exporter" \
        --instance-id ocid1.instance.example \
        --compartment-id ocid1.compartment.example \
        --since 2026-09-01T00:00:00Z \
        --until 2026-09-01T01:00:00Z \
        --out "$1" \
        --state-snapshot "$snapshot" \
        --wp-receipts "$receipts"
}

run_export "$one"
run_export "$two"

if [ -f "${one}/manifest.json" ] && [ -f "${one}/instance.json" ] && [ -f "${one}/audit-events.json" ] \
    && [ -f "${one}/state_history.json" ] && [ -f "${one}/state_snapshot.json" ] \
    && [ -f "${one}/wp_describe_receipts.json" ]; then
    :
else
    echo "FAIL: happy path did not write every expected receipt" >&2
    exit 1
fi

lane_root="$(git rev-parse --show-toplevel)"
if [ -x "$lane_root/.venv/bin/python" ]; then
    resolved_python="$lane_root/.venv/bin/python"
else
    resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }
fi
"$resolved_python" - "$one" "$two" <<'PY'
import hashlib
import json
import sys
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


one, two = (Path(value) for value in sys.argv[1:])
manifest = load(one / "manifest.json")
assert manifest["instance_id"] == "ocid1.instance.example"
assert manifest["compartment_id"] == "ocid1.compartment.example"
assert manifest["since"] == "2026-09-01T00:00:00Z"
assert manifest["until"] == "2026-09-01T01:00:00Z"
assert len(manifest["files"]) == 5
for entry in manifest["files"]:
    target = one / entry["path"]
    assert target.is_file(), entry
    assert hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"], entry
    assert entry["capture_time"].endswith("Z"), entry
commands = {entry["path"]: entry["command"] for entry in manifest["files"]}
assert "compute instance get" in commands["instance.json"]
assert "audit event list" in commands["audit-events.json"]
assert "derived from" in commands["state_history.json"]
history = load(one / "state_history.json")
assert [item["state"] for item in history["observations"]] == ["STOPPED", "RUNNING", "STOPPED"]


def without_capture_time(value):
    if isinstance(value, dict):
        return {
            key: without_capture_time(item)
            for key, item in value.items()
            if key not in {"capture_time", "captured_at"}
        }
    if isinstance(value, list):
        return [without_capture_time(item) for item in value]
    return value


assert without_capture_time(load(one / "manifest.json")) == without_capture_time(load(two / "manifest.json"))
for name in ("instance.json", "audit-events.json", "state_history.json", "state_snapshot.json", "wp_describe_receipts.json"):
    assert (one / name).read_bytes() == (two / name).read_bytes(), name
assert (one.stat().st_mode & 0o777) == 0o700
for path in one.iterdir():
    assert (path.stat().st_mode & 0o777) == 0o600, (path, oct(path.stat().st_mode & 0o777))
PY

schema_root="${fixture_root}/schema-root"
schema_scripts="${schema_root}/scripts"
schema_bin="${schema_root}/bin"
mkdir -p "${schema_scripts}" "${schema_bin}"
cp "${root}/scripts/gpu_burst_evidence.py" "${schema_scripts}/gpu_burst_evidence.py"
# GNU sed -i takes no argument; BSD sed -i requires one. Rewrite via a temp file so
# this suite runs the same on the macOS dev machines and the Linux gate host.
sed -e 's/^SCHEMA_VERSION = 1$/SCHEMA_VERSION = 9/' \
    -e 's/^MANIFEST_FORMAT = .*/MANIFEST_FORMAT = \"oci-gpu-burst-evidence-v9\"/' \
    "${schema_scripts}/gpu_burst_evidence.py" >"${schema_scripts}/gpu_burst_evidence.py.tmp"
mv "${schema_scripts}/gpu_burst_evidence.py.tmp" "${schema_scripts}/gpu_burst_evidence.py"
cat >"${schema_bin}/git" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -eq 2 ] && [ "$1" = "rev-parse" ] && [ "$2" = "--show-toplevel" ]; then
    printf '%s\n' "${SCHEMA_ROOT}"
    exit 0
fi
exit 2
EOF
chmod +x "${schema_bin}/git"
schema_bundle="${fixture_root}/schema-bundle"
schema_call_log="${fixture_root}/schema-oci-calls.log"
SCHEMA_ROOT="${schema_root}" PATH="${schema_bin}:${PATH}" OCI_BIN="${fake_oci}" \
    OCI_CALL_LOG="${schema_call_log}" \
    "${exporter}" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z \
    --until 2026-09-01T01:00:00Z \
    --out "${schema_bundle}"
"$resolved_python" - "${schema_bundle}/manifest.json" "${root}/scripts" <<'PY'
import json
import sys

sys.path.insert(0, sys.argv[2])
from gpu_burst_evidence import MANIFEST_FORMAT, SCHEMA_VERSION

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["schema_version"] == SCHEMA_VERSION
assert manifest["format"] == MANIFEST_FORMAT
assert manifest["schema_version"] != 9
assert manifest["format"] != "oci-gpu-burst-evidence-v9"
PY

# Direct execution outside a git checkout must still import the producer-adjacent
# checker (BASH_SOURCE), not a decoy from cwd. Relative --out stays cwd-relative.
outside_dir="${fixture_root}/outside-repo"
mkdir -p "${outside_dir}/scripts"
cat >"${outside_dir}/scripts/gpu_burst_evidence.py" <<'PY'
SCHEMA_VERSION = 9
MANIFEST_FORMAT = "decoy-from-cwd"


def build_state_history_document(audit, instance_id=None, since=None, until=None):
    return {"observations": [], "state": "unknown", "reason": "decoy"}
PY
outside_rc=0
(
    cd "${outside_dir}"
    OCI_BIN="${fake_oci}" OCI_CALL_LOG="${fixture_root}/outside-oci-calls.log" \
        "${exporter}" \
        --instance-id ocid1.instance.example \
        --compartment-id ocid1.compartment.example \
        --since 2026-09-01T00:00:00Z \
        --until 2026-09-01T01:00:00Z \
        --out cwd-bundle
) >"${fixture_root}/outside-repo.out" 2>&1 || outside_rc=$?
if [ "${outside_rc}" -ne 0 ]; then
    echo "FAIL: outside-repo export exited ${outside_rc}, expected 0" >&2
    cat "${fixture_root}/outside-repo.out" >&2
    exit 1
fi
if [ ! -d "${outside_dir}/cwd-bundle" ]; then
    echo "FAIL: outside-repo relative --out did not create a bundle in cwd" >&2
    exit 1
fi
if [ -e "${root}/cwd-bundle" ]; then
    echo "FAIL: outside-repo relative --out was resolved against the script root" >&2
    exit 1
fi
"$resolved_python" - "${outside_dir}/cwd-bundle/manifest.json" "${root}/scripts" <<'PY'
import json
import sys

sys.path.insert(0, sys.argv[2])
from gpu_burst_evidence import MANIFEST_FORMAT, SCHEMA_VERSION

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["schema_version"] == SCHEMA_VERSION
assert manifest["format"] == MANIFEST_FORMAT
assert manifest["schema_version"] != 9
assert manifest["format"] != "decoy-from-cwd"
PY

unknown_oci="${fixture_root}/unknown-oci"
cat >"${unknown_oci}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case " $* " in
    *" compute instance get "*)
        printf '%s\n' '{"data":{"id":"ocid1.instance.example","lifecycle-state":"STOPPED"}}'
        ;;
    *" audit event list "*)
        printf '%s\n' '{"data":[]}'
        ;;
    *)
        echo "unexpected OCI argv: $*" >&2
        exit 41
        ;;
esac
EOF
chmod +x "${unknown_oci}"
unknown_bundle="${fixture_root}/unknown-bundle"
OCI_BIN="${unknown_oci}" "$exporter" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z \
    --until 2026-09-01T01:00:00Z \
    --out "$unknown_bundle"
"$resolved_python" - "$unknown_bundle/state_history.json" <<'PY'
import json
import sys

history = json.load(open(sys.argv[1], encoding="utf-8"))
assert history["observations"] == []
assert history["proof_status"] == "unknown"
assert "state" not in history
assert isinstance(history["reason"], str) and history["reason"].strip()
PY

"$resolved_python" "${root}/scripts/gpu_burst_evidence.py" \
    --bundle "$one" \
    --expected-stop-principal gpu-reaper \
    --min-descriptions 1 >/dev/null

if [ "$(wc -l <"${call_log}" | tr -d ' ')" -ne 4 ]; then
    echo "FAIL: expected exactly two read-only OCI calls per export" >&2
    exit 1
fi
if ! grep -Fq -- '--connection-timeout' "${call_log}" || ! grep -Fq -- '--read-timeout' "${call_log}"; then
    echo "FAIL: OCI calls did not carry explicit connection/read timeouts" >&2
    exit 1
fi
if ! grep -Fq -- '--end-time 2026-09-01T01:00:00.000001Z' "${call_log}"; then
    echo "FAIL: Audit end time was not extended past the inclusive boundary" >&2
    exit 1
fi

reuse="${fixture_root}/reuse"
run_export "$reuse"
"$exporter" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "$reuse"
if [ -e "${reuse}/state_snapshot.json" ] || [ -e "${reuse}/wp_describe_receipts.json" ]; then
    echo "FAIL: rerunning without optional inputs left stale artifacts" >&2
    exit 1
fi
"$resolved_python" - "$reuse/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert [entry["path"] for entry in manifest["files"]] == [
    "instance.json",
    "audit-events.json",
    "state_history.json",
]
PY

atomic_bundle="${fixture_root}/atomic"
run_export "$atomic_bundle"
old_manifest_sha="$(sha256sum "${atomic_bundle}/manifest.json" | awk '{print $1}')"
old_snapshot_sha="$(sha256sum "${atomic_bundle}/state_snapshot.json" | awk '{print $1}')"
failing_oci="${fixture_root}/failing-oci"
cat >"${failing_oci}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case " $* " in
    *" compute instance get "*)
        printf '%s\n' '{"data":{"id":"ocid1.instance.example","lifecycle-state":"STOPPED"}}'
        ;;
    *)
        echo "deliberate OCI failure" >&2
        exit 73
        ;;
esac
EOF
chmod +x "${failing_oci}"
atomic_rc=0
OCI_BIN="${failing_oci}" "$exporter" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${atomic_bundle}" >"${fixture_root}/atomic-failure.out" 2>&1 || atomic_rc=$?
if [ "$atomic_rc" -ne 73 ]; then
    echo "FAIL: failed export exited ${atomic_rc}, expected 73" >&2
    exit 1
fi
if [ "$(sha256sum "${atomic_bundle}/manifest.json" | awk '{print $1}')" != "$old_manifest_sha" ]; then
    echo "FAIL: failed export replaced the previous manifest" >&2
    exit 1
fi
if [ "$(sha256sum "${atomic_bundle}/state_snapshot.json" | awk '{print $1}')" != "$old_snapshot_sha" ]; then
    echo "FAIL: failed export removed the previous snapshot" >&2
    exit 1
fi
if [ -e "${atomic_bundle}.lock" ] || compgen -G "${atomic_bundle%/*}/.${atomic_bundle##*/}.tmp.*" >/dev/null; then
    echo "FAIL: failed export left transaction artifacts behind" >&2
    exit 1
fi

crash_bundle="${fixture_root}/crash"
run_export "${crash_bundle}"
crash_old_manifest_sha="$(sha256sum "${crash_bundle}/manifest.json" | awk '{print $1}')"
crash_mv_dir="${fixture_root}/crash-mv-bin"
mkdir -p "${crash_mv_dir}"
real_mv="$(command -v mv)"
cat >"${crash_mv_dir}/mv" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
first_arg=""
for arg in "$@"; do
    case "$arg" in
        --)
            continue
            ;;
        *)
            first_arg="$arg"
            break
            ;;
    esac
done
"${REAL_MV}" "$@"
if [ "$first_arg" = "${CRASH_OUT}" ]; then
    kill -KILL "$PPID"
fi
EOF
chmod +x "${crash_mv_dir}/mv"
crash_rc=0
REAL_MV="${real_mv}" CRASH_OUT="${crash_bundle}" PATH="${crash_mv_dir}:${PATH}" \
    OCI_BIN="${fake_oci}" "${exporter}" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${crash_bundle}" >"${fixture_root}/crash.out" 2>&1 || crash_rc=$?
if [ "${crash_rc}" -ne 137 ]; then
    echo "FAIL: SIGKILL publish simulation exited ${crash_rc}, expected 137" >&2
    exit 1
fi
if [ -e "${crash_bundle}" ]; then
    echo "FAIL: SIGKILL publish simulation unexpectedly left the destination present" >&2
    exit 1
fi
crash_transaction=""
for candidate in "${crash_bundle%/*}/.${crash_bundle##*/}.tmp."*; do
    if [ -d "${candidate}" ]; then
        crash_transaction="${candidate}"
        break
    fi
done
if [ -z "${crash_transaction}" ] || [ ! -f "${crash_transaction}/.publish-intent" ] \
    || [ ! -d "${crash_transaction}/previous" ]; then
    echo "FAIL: SIGKILL publish simulation did not leave a recoverable intent and backup" >&2
    exit 1
fi
if ! grep -Eq '^pid=[1-9][0-9]*$' "${crash_bundle}.lock/owner" \
    || ! grep -Eq '^host=.+$' "${crash_bundle}.lock/owner" \
    || ! grep -Eq '^start_time=[1-9][0-9]*$' "${crash_bundle}.lock/owner"; then
    echo "FAIL: evidence lock did not persist owner metadata" >&2
    exit 1
fi
# This foreground crash process has exited with SIGKILL and no other writer
# exists in this fixture. Simulate explicit operator lock release; the exporter
# must preserve and recover the transaction, never steal ownership on its own.
rm -- "${crash_bundle}.lock/owner"
rmdir -- "${crash_bundle}.lock"
recovery_rc=0
EVIDENCE_LOCK_MAX_TIME=1 OCI_BIN="${failing_oci}" "${exporter}" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${crash_bundle}" >"${fixture_root}/crash-recovery.out" 2>&1 || recovery_rc=$?
if [ "${recovery_rc}" -ne 73 ]; then
    echo "FAIL: recovery run exited ${recovery_rc}, expected the deliberate OCI failure 73" >&2
    exit 1
fi
if [ "$(sha256sum "${crash_bundle}/manifest.json" | awk '{print $1}')" != "${crash_old_manifest_sha}" ]; then
    echo "FAIL: stale-lock recovery did not restore the previous bundle before retry" >&2
    exit 1
fi
if ! grep -Fq -- 'restoring the previous evidence bundle' "${fixture_root}/crash-recovery.out"; then
    echo "FAIL: stale-lock recovery was not logged" >&2
    exit 1
fi
run_export "${crash_bundle}"

slow_oci="${fixture_root}/slow-oci"
slow_active="${fixture_root}/slow-active"
slow_overlap="${fixture_root}/slow-overlap"
cat >"${slow_oci}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if mkdir "${SLOW_ACTIVE}" 2>/dev/null; then
    trap 'rmdir "${SLOW_ACTIVE}"' EXIT
    sleep 1
else
    : >"${SLOW_OVERLAP}"
fi
"${OCI_FAKE}" "$@"
EOF
chmod +x "${slow_oci}"
concurrent_bundle="${fixture_root}/concurrent"
OCI_BIN="${slow_oci}" SLOW_ACTIVE="${slow_active}" SLOW_OVERLAP="${slow_overlap}" OCI_FAKE="${fake_oci}" \
    "$exporter" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${concurrent_bundle}" >"${fixture_root}/concurrent-one.out" 2>&1 &
first_export_pid=$!
for _ in $(seq 1 50); do
    [ -d "${slow_active}" ] && break
    sleep 0.1
done
if [ ! -d "${slow_active}" ]; then
    echo "FAIL: slow OCI exporter did not start" >&2
    exit 1
fi
OCI_BIN="${slow_oci}" SLOW_ACTIVE="${slow_active}" SLOW_OVERLAP="${slow_overlap}" OCI_FAKE="${fake_oci}" \
    "$exporter" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${concurrent_bundle}" >"${fixture_root}/concurrent-two.out" 2>&1 &
second_export_pid=$!
first_rc=0
second_rc=0
wait "$first_export_pid" || first_rc=$?
wait "$second_export_pid" || second_rc=$?
if [ "$first_rc" -ne 0 ] || [ "$second_rc" -ne 0 ]; then
    echo "FAIL: serialized exports returned ${first_rc} and ${second_rc}" >&2
    cat "${fixture_root}/concurrent-one.out" "${fixture_root}/concurrent-two.out" >&2
    exit 1
fi
if [ -e "${slow_overlap}" ]; then
    echo "FAIL: concurrent exports reached OCI at the same time" >&2
    exit 1
fi

# A live remote capture can outlive the lock-wait cap: `oci audit event list
# --all` paginates under the per-request read timeout. A well-formed remote
# owner older than the wait cap but still inside the capture budget must not
# be stolen.
remote_lock_bundle="${fixture_root}/remote-lock"
mkdir -p "${remote_lock_bundle}.lock"
remote_lock_start="$(($(date +%s) - 2))"
printf 'pid=%s\nhost=%s\nstart_time=%s\n' "1" "remote-evidence-host" "${remote_lock_start}" \
    >"${remote_lock_bundle}.lock/owner"
chmod 600 "${remote_lock_bundle}.lock/owner"
remote_lock_rc=0
EVIDENCE_LOCK_MAX_TIME=1 OCI_BIN="${fake_oci}" "${exporter}" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${remote_lock_bundle}" \
    >"${fixture_root}/remote-lock.out" 2>&1 || remote_lock_rc=$?
if [ "${remote_lock_rc}" -eq 0 ]; then
    echo "FAIL: remote lock within capture budget was stolen" >&2
    cat "${fixture_root}/remote-lock.out" >&2
    exit 1
fi
if [ -e "${remote_lock_bundle}" ]; then
    echo "FAIL: remote lock steal published a concurrent bundle" >&2
    exit 1
fi
if [ ! -f "${remote_lock_bundle}.lock/owner" ]; then
    echo "FAIL: remote lock within capture budget was removed" >&2
    exit 1
fi
if grep -Fq -- 'breaking stale evidence lock from host' "${fixture_root}/remote-lock.out"; then
    echo "FAIL: remote lock within capture budget was treated as stale" >&2
    cat "${fixture_root}/remote-lock.out" >&2
    exit 1
fi
if ! grep -Fq -- 'timed out waiting for evidence bundle lock' "${fixture_root}/remote-lock.out"; then
    echo "FAIL: remote lock wait did not time out" >&2
    cat "${fixture_root}/remote-lock.out" >&2
    exit 1
fi

missing_rc=0
"$exporter" --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${fixture_root}/missing" >"${fixture_root}/missing.out" 2>&1 || missing_rc=$?
if [ "$missing_rc" -ne 2 ]; then
    echo "FAIL: missing --instance-id exited ${missing_rc}, expected 2" >&2
    exit 1
fi

for zero_timeout in 00 000; do
    zero_timeout_rc=0
    EVIDENCE_CURL_MAX_TIME="$zero_timeout" "$exporter" \
        --instance-id ocid1.instance.example \
        --compartment-id ocid1.compartment.example \
        --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
        --out "${fixture_root}/zero-timeout-${zero_timeout}" \
        >"${fixture_root}/zero-timeout-${zero_timeout}.out" 2>&1 || zero_timeout_rc=$?
    if [ "$zero_timeout_rc" -ne 2 ]; then
        echo "FAIL: zero-padded timeout ${zero_timeout} exited ${zero_timeout_rc}, expected 2" >&2
        exit 1
    fi
done

# 08 crashes Bash octal arithmetic; 010 silently becomes 8. Reject both at
# validation so lock timeout handling stays decimal and fail-closed (RLSE-05).
for padded_lock in 08 010; do
    padded_lock_rc=0
    padded_lock_out="${fixture_root}/padded-lock-${padded_lock}"
    EVIDENCE_LOCK_MAX_TIME="$padded_lock" "$exporter" \
        --instance-id ocid1.instance.example \
        --compartment-id ocid1.compartment.example \
        --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
        --out "${padded_lock_out}" \
        >"${fixture_root}/padded-lock-${padded_lock}.out" 2>&1 || padded_lock_rc=$?
    if [ "$padded_lock_rc" -ne 2 ]; then
        echo "FAIL: zero-padded lock timeout ${padded_lock} exited ${padded_lock_rc}, expected 2" >&2
        cat "${fixture_root}/padded-lock-${padded_lock}.out" >&2
        exit 1
    fi
    if ! grep -Fq -- 'timeouts must be positive integer seconds' "${fixture_root}/padded-lock-${padded_lock}.out"; then
        echo "FAIL: zero-padded lock timeout ${padded_lock} did not fail usage validation" >&2
        cat "${fixture_root}/padded-lock-${padded_lock}.out" >&2
        exit 1
    fi
    if [ -e "${padded_lock_out}" ]; then
        echo "FAIL: zero-padded lock timeout ${padded_lock} left a published bundle" >&2
        exit 1
    fi
done
EVIDENCE_LOCK_MAX_TIME=8 run_export "${fixture_root}/lock-decimal-8"
EVIDENCE_LOCK_MAX_TIME=10 run_export "${fixture_root}/lock-decimal-10"
if [ ! -f "${fixture_root}/lock-decimal-8/manifest.json" ] \
    || [ ! -f "${fixture_root}/lock-decimal-10/manifest.json" ]; then
    echo "FAIL: unpadded decimal lock timeouts did not publish bundles" >&2
    exit 1
fi

# Copies must keep scripts/deploy/lib layout so BASH_SOURCE still finds the
# producer-adjacent checker instead of falling back to git/cwd.
mutated_root="${fixture_root}/mutated-tree"
mkdir -p "${mutated_root}/scripts/deploy/lib"
cp "${root}/scripts/gpu_burst_evidence.py" "${mutated_root}/scripts/gpu_burst_evidence.py"
mutated="${mutated_root}/scripts/deploy/lib/mutated-exporter.sh"
sed 's/run_oci compute instance get/run_oci compute instance action/' "$exporter" >"${mutated}"
chmod +x "${mutated}"
action_rc=0
"$mutated" --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${fixture_root}/action" >"${fixture_root}/action.out" 2>&1 || action_rc=$?
if [ "$action_rc" -ne 3 ]; then
    echo "FAIL: action verb was not rejected with exit 3 (got ${action_rc})" >&2
    cat "${fixture_root}/action.out" >&2
    exit 1
fi

mutated_update="${mutated_root}/scripts/deploy/lib/mutated-update-exporter.sh"
sed 's/run_oci compute instance get/run_oci compute instance update/' "$exporter" >"${mutated_update}"
chmod +x "${mutated_update}"
update_rc=0
"$mutated_update" --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${fixture_root}/update" >"${fixture_root}/update.out" 2>&1 || update_rc=$?
if [ "$update_rc" -ne 3 ]; then
    echo "FAIL: update verb was not rejected with exit 3 (got ${update_rc})" >&2
    cat "${fixture_root}/update.out" >&2
    exit 1
fi

slow_cp_dir="${fixture_root}/slow-cp-bin"
mkdir -p "${slow_cp_dir}"
cat >"${slow_cp_dir}/cp" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
sleep 5
EOF
chmod +x "${slow_cp_dir}/cp"
copy_timeout_rc=0
EVIDENCE_COPY_MAX_TIME=1 PATH="${slow_cp_dir}:${PATH}" OCI_BIN="${fake_oci}" \
    "${exporter}" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${fixture_root}/copy-timeout" \
    --state-snapshot "${snapshot}" >"${fixture_root}/copy-timeout.out" 2>&1 || copy_timeout_rc=$?
if [ "${copy_timeout_rc}" -ne 124 ]; then
    echo "FAIL: bounded copy exited ${copy_timeout_rc}, expected timeout status 124" >&2
    exit 1
fi
if [ -e "${fixture_root}/copy-timeout" ]; then
    echo "FAIL: bounded copy timeout left a published bundle" >&2
    exit 1
fi

url_bundle="${fixture_root}/url-bundle"
snapshot_url='https://snapshot.example.test/gpu-state.json?token=do-not-persist'
"$exporter" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z \
    --until 2026-09-01T01:00:00Z \
    --out "$url_bundle" \
    --state-snapshot "$snapshot_url"
if grep -Fq -- 'do-not-persist' "${url_bundle}/manifest.json"; then
    echo "FAIL: snapshot URL query token was persisted in manifest" >&2
    exit 1
fi
if grep -Fq -- '<redacted-url>' "${url_bundle}/manifest.json"; then
    echo "FAIL: snapshot manifest command retained a redaction placeholder" >&2
    exit 1
fi
if ! grep -Fq -- 'https://snapshot.example.test/gpu-state.json' "${url_bundle}/manifest.json"; then
    echo "FAIL: snapshot manifest command did not retain the object path" >&2
    exit 1
fi
if grep -Fq -- 'gpu-state.json?' "${url_bundle}/manifest.json"; then
    echo "FAIL: snapshot manifest command retained a query delimiter" >&2
    exit 1
fi
if ! grep -Fq -- '--connect-timeout 10' "${curl_call_log}" || ! grep -Fq -- '--max-time 60' "${curl_call_log}"; then
    echo "FAIL: snapshot retrieval did not carry explicit curl timeouts" >&2
    exit 1
fi

old_python_root="${fixture_root}/old-python-root"
old_python_bin="${old_python_root}/bin"
mkdir -p "${old_python_root}/scripts/deploy/lib" "${old_python_root}/scripts" "${old_python_bin}"
cp "${exporter}" "${old_python_root}/scripts/deploy/lib/export-gpu-evidence.sh"
cp "${root}/scripts/gpu_burst_evidence.py" "${old_python_root}/scripts/gpu_burst_evidence.py"
chmod +x "${old_python_root}/scripts/deploy/lib/export-gpu-evidence.sh"
cat >"${old_python_bin}/python3" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "-c" ]; then
    case "${2:-}" in
        *"sys.version_info >= (3, 12)"*)
            exit 1
            ;;
        *"sys.version_info"*)
            printf '%s\n' '3.9.6'
            exit 0
            ;;
    esac
fi
echo "ERROR: unexpected python3 invocation: $*" >&2
exit 1
EOF
chmod +x "${old_python_bin}/python3"
cp "${old_python_bin}/python3" "${old_python_bin}/python3.12"
cp "${old_python_bin}/python3" "${old_python_bin}/python3.13"
old_python_rc=0
PATH="${old_python_bin}:${PATH}" OCI_BIN="${fake_oci}" \
    "${old_python_root}/scripts/deploy/lib/export-gpu-evidence.sh" \
    --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${fixture_root}/old-python-bundle" \
    >"${fixture_root}/old-python.out" 2>&1 || old_python_rc=$?
if [ "${old_python_rc}" -eq 0 ]; then
    echo "FAIL: python 3.9 stub was accepted" >&2
    cat "${fixture_root}/old-python.out" >&2
    exit 1
fi
if grep -Fq -- 'could not read the evidence schema' "${fixture_root}/old-python.out"; then
    echo "FAIL: python 3.9 failure was masked as a schema read error" >&2
    cat "${fixture_root}/old-python.out" >&2
    exit 1
fi
if ! grep -Fq -- '3.9.6' "${fixture_root}/old-python.out" \
    || ! grep -Fq -- '3.12' "${fixture_root}/old-python.out"; then
    echo "FAIL: python 3.9 rejection did not name the found and required versions" >&2
    cat "${fixture_root}/old-python.out" >&2
    exit 1
fi
if [ -e "${fixture_root}/old-python-bundle" ]; then
    echo "FAIL: python 3.9 stub left a published bundle" >&2
    exit 1
fi

echo "all assertions passed"
