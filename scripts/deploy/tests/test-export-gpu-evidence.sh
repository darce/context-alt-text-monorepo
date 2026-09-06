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
cat >"${fake_oci}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${OCI_CALL_LOG}"
case " $* " in
    *" compute instance get "*)
        printf '%s\n' '{"data":{"id":"ocid1.instance.example","compartment-id":"ocid1.compartment.example","lifecycle-state":"STOPPED"}}'
        ;;
    *" audit event list "*)
        printf '%s\n' '{"data":[{"eventName":"StartInstance","eventTime":"2026-09-01T00:10:00Z","eventId":"start-1","responseStatus":200,"data":{"resourceId":"ocid1.instance.example","identity":{"principalName":"burst-start"},"stateChange":{"previous":{"lifecycleState":"STOPPED"}}}},{"eventName":"StopInstance","eventTime":"2026-09-01T00:30:00Z","eventId":"stop-1","responseStatus":200,"data":{"resourceId":"ocid1.instance.example","identity":{"principalName":"gpu-reaper"}}}]}'
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
export PATH="${fixture_root}:${PATH}"

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

mutated="${fixture_root}/mutated-exporter.sh"
sed 's/run_oci compute instance get/run_oci compute instance action/' "$exporter" >"${mutated}"
chmod +x "${mutated}"
action_rc=0
"$mutated" --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${fixture_root}/action" >"${fixture_root}/action.out" 2>&1 || action_rc=$?
if [ "$action_rc" -ne 3 ]; then
    echo "FAIL: action verb was not rejected with exit 3 (got ${action_rc})" >&2
    exit 1
fi

mutated_update="${fixture_root}/mutated-update-exporter.sh"
sed 's/run_oci compute instance get/run_oci compute instance update/' "$exporter" >"${mutated_update}"
chmod +x "${mutated_update}"
update_rc=0
"$mutated_update" --instance-id ocid1.instance.example \
    --compartment-id ocid1.compartment.example \
    --since 2026-09-01T00:00:00Z --until 2026-09-01T01:00:00Z \
    --out "${fixture_root}/update" >"${fixture_root}/update.out" 2>&1 || update_rc=$?
if [ "$update_rc" -ne 3 ]; then
    echo "FAIL: update verb was not rejected with exit 3 (got ${update_rc})" >&2
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
if ! grep -Fq -- '<redacted-url>' "${url_bundle}/manifest.json"; then
    echo "FAIL: snapshot manifest command was not redacted" >&2
    exit 1
fi
if ! grep -Fq -- 'https://snapshot.example.test/gpu-state.json?<redacted-url>' "${url_bundle}/manifest.json"; then
    echo "FAIL: snapshot manifest command did not retain the object path" >&2
    exit 1
fi

echo "all assertions passed"
