#!/usr/bin/env bash
# Local contract tests for check-gpu-snapshots.sh. No Docker or SSH required.

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash" >&2
    exit 2
fi
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
checker="${root}/scripts/deploy/check-gpu-snapshots.sh"
checker_bash=${ACX_GPU_TEST_BASH:-/bin/bash}
prod_compose="${root}/apps/prototype-description-service/docker-compose.prod.yml"
prod_env="${root}/apps/prototype-description-service/.env.prod.example"
makefile=${ACX_GPU_TEST_MAKEFILE:-${root}/Makefile}
fixture_root=$(mktemp -d)
trap 'rm -rf "$fixture_root"' EXIT

failures=0
pass() { printf 'PASS: %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }

assert_contains() {
    local label=$1 needle=$2 file=$3
    if grep -Fq -- "$needle" "$file"; then
        pass "$label"
    else
        fail "$label (missing: $needle)"
    fi
}

assert_line_matches() {
    local label=$1 pattern=$2 file=$3
    if grep -Eq -- "$pattern" "$file"; then
        pass "$label"
    else
        fail "$label (missing line matching: $pattern)"
    fi
}

assert_output_contains() {
    local label=$1 needle=$2 output=$3
    if [[ "$output" == *"$needle"* ]]; then
        pass "$label"
    else
        fail "$label (missing: $needle; output: $output)"
    fi
}

run_checker() {
    env \
        ACX_GPU_UNIT_STATE_PATH="${fixture_root}/run/acx/gpu-state.json" \
        ACX_GPU_UNIT_LOAD_PATH="${fixture_root}/run/acx/describe-load.json" \
        ACX_GPU_STATE_PATH="${fixture_root}/run/acx/gpu-state.json" \
        ACX_DESCRIBE_LOAD_PATH="${fixture_root}/run/acx/describe-load.json" \
        ACX_GPU_STATE_STALE_SECONDS=180 \
        ACX_DESCRIBE_LOAD_STALE_SECONDS=120 \
        ACX_GPU_SNAPSHOT_DIR="${fixture_root}/run/acx" \
        ACX_GPU_COMPOSE_FILE="${fixture_root}/compose.yml" \
        ACX_GPU_READER_UID="$(id -u)" \
        ACX_NOW_EPOCH=1000 \
        "$@" "$checker_bash" "$checker"
}

run_checker_from_install() {
    local fixture_install=${ACX_GPU_INSTALL_SCRIPT:-${fixture_root}/install.sh}
    env -u ACX_GPU_UNIT_STATE_PATH -u ACX_GPU_UNIT_LOAD_PATH \
        ACX_GPU_INSTALL_SCRIPT="$fixture_install" \
        ACX_GPU_STATE_PATH="${fixture_root}/run/acx/gpu-state.json" \
        ACX_DESCRIBE_LOAD_PATH="${fixture_root}/run/acx/describe-load.json" \
        ACX_GPU_STATE_STALE_SECONDS=180 \
        ACX_DESCRIBE_LOAD_STALE_SECONDS=120 \
        ACX_GPU_SNAPSHOT_DIR="${fixture_root}/run/acx" \
        ACX_GPU_COMPOSE_FILE="${fixture_root}/compose.yml" \
        ACX_GPU_READER_UID="$(id -u)" \
        ACX_NOW_EPOCH=1000 \
        "$checker_bash" "$checker"
}

expect_success() {
    local label=$1
    shift
    local output rc=0
    output=$(run_checker "$@" 2>&1) || rc=$?
    if [ "$rc" -eq 0 ]; then
        pass "$label"
    else
        fail "$label (exit $rc; output: $output)"
    fi
}

expect_failure() {
    local label=$1 expected=$2
    shift 2
    local output rc=0
    output=$(run_checker "$@" 2>&1) || rc=$?
    if [ "$rc" -eq 0 ]; then
        fail "$label (unexpected exit 0; output: $output)"
    elif [[ "$output" != *"$expected"* ]]; then
        fail "$label (missing error '$expected'; output: $output)"
    else
        pass "$label"
    fi
}

mkdir -p "${fixture_root}/run/acx"
printf '{"state":"ready","written_at":900}\n' >"${fixture_root}/run/acx/gpu-state.json"
printf '{"queue_depth":0,"in_flight":0,"batch_in_progress":false,"written_at":900}\n' \
    >"${fixture_root}/run/acx/describe-load.json"
chmod 0644 "${fixture_root}/run/acx/"*.json
cat >"${fixture_root}/compose.yml" <<EOF
services:
  api:
    environment:
      - ACX_GPU_STATE_PATH=${fixture_root}/run/acx/gpu-state.json
    volumes:
      - ${fixture_root}/run/acx:${fixture_root}/run/acx:ro
EOF
cat >"${fixture_root}/compose-template.yml" <<'EOF'
services:
  api:
    environment:
      - ACX_GPU_STATE_PATH=${ACX_GPU_STATE_PATH}
    volumes:
      - ${ACX_GPU_SNAPSHOT_DIR}:/run/acx:ro
EOF
cat >"${fixture_root}/compose-template-env.yml" <<EOF
services:
  api:
    environment:
      - ACX_GPU_STATE_PATH=\${ACX_GPU_STATE_PATH}
    volumes:
      - ${fixture_root}/run/acx:${fixture_root}/run/acx:ro
EOF
cat >"${fixture_root}/install.sh" <<EOF
ExecStart=python3 -m infra.oci.gpu_lifecycle --load-json ${fixture_root}/run/acx/describe-load.json --gpu-state-json ${fixture_root}/run/acx/gpu-state.json
ExecStart=python3 -m infra.oci.gpu_lifecycle --load-json ${fixture_root}/run/acx/describe-load.json --gpu-state-json ${fixture_root}/run/acx/gpu-state.json
EOF
cat >"${fixture_root}/install-missing-flags.sh" <<'EOF'
ExecStart=python3 -m infra.oci.gpu_lifecycle --instance-id ocid1.example
EOF

if "$checker_bash" -n "$checker" 2>/dev/null; then
    pass "checker has valid bash syntax"
else
    fail "checker has valid bash syntax"
fi
if grep -Eq '(^|[[:space:]])mapfile([[:space:]]|$)' "$checker"; then
    fail "checker avoids Bash 4-only mapfile"
else
    pass "checker avoids Bash 4-only mapfile"
fi

# Deployment contract: the example env is the one deployment seam. Compose
# consumes those values instead of growing another copy of either host path.
assert_contains "env documents GPU state path" "ACX_GPU_STATE_PATH=/run/acx/gpu-state.json" "$prod_env"
assert_contains "env documents GPU freshness" "ACX_GPU_STATE_STALE_SECONDS=180" "$prod_env"
assert_contains "env documents load path" "ACX_DESCRIBE_LOAD_PATH=/run/acx/describe-load.json" "$prod_env"
assert_contains "env documents load refresh" "ACX_DESCRIBE_LOAD_REFRESH_SECONDS=45" "$prod_env"
assert_contains "compose passes GPU state path" 'ACX_GPU_STATE_PATH=${ACX_GPU_STATE_PATH}' "$prod_compose"
assert_contains "compose mounts snapshot directory read-only" '${ACX_GPU_SNAPSHOT_DIR}:/run/acx:ro' "$prod_compose"
assert_line_matches "live snapshot checker has a make target" '^check-gpu-snapshots-live:' "$makefile"
live_make_output=$(make -C "$root" --no-print-directory -n -f "$makefile" check-gpu-snapshots-live GPU_SNAPSHOT_ENV=dev 2>&1)
assert_output_contains "live snapshot checker executes the checker" \
    "scripts/deploy/check-gpu-snapshots.sh" "$live_make_output"
assert_output_contains "live snapshot checker defaults to the SSH tailnet host" \
    "acx-backend.tail1a44b8.ts.net" "$live_make_output"
alias_make_output=$(make -C "$root" --no-print-directory -n -f "$makefile" deploy-verify-dev 2>&1)
assert_output_contains "fixed deploy verification invokes live snapshot checker" \
    "scripts/deploy/check-gpu-snapshots.sh" "$alias_make_output"
generic_make_output=$(make -C "$root" --no-print-directory -n -f "$makefile" deploy-verify ENV=prod 2>&1)
assert_output_contains "generic deploy verification invokes live snapshot checker" \
    "scripts/deploy/check-gpu-snapshots.sh" "$generic_make_output"
missing_env_output=$(env -u GPU_SNAPSHOT_ENV make -C "$root" --no-print-directory -f "$makefile" check-gpu-snapshots-live 2>&1) && missing_env_rc=0 || missing_env_rc=$?
if [ "$missing_env_rc" -ne 0 ] && [[ "$missing_env_output" == *"GPU_SNAPSHOT_ENV is required"* ]]; then
    pass "live snapshot checker requires an explicit environment"
else
    fail "live snapshot checker requires an explicit environment (exit $missing_env_rc; output: $missing_env_output)"
fi

expect_success "fresh readable snapshots and agreeing mount pass"
derived_output=$(run_checker_from_install 2>&1) || derived_rc=$?
if [ "${derived_rc:-0}" -eq 0 ]; then
    pass "checker derives the single writer paths from lifecycle units"
else
    fail "checker derives lifecycle unit paths (exit ${derived_rc}; output: ${derived_output})"
fi
missing_unit_path_output=$(ACX_GPU_INSTALL_SCRIPT="${fixture_root}/install-missing-flags.sh" run_checker_from_install 2>&1) && missing_unit_path_rc=0 || missing_unit_path_rc=$?
if [ "$missing_unit_path_rc" -ne 0 ] && [[ "$missing_unit_path_output" == *"lifecycle units do not have exactly one agreeing --gpu-state-json path"* ]]; then
    pass "missing lifecycle path reports the accurate unit-contract failure"
else
    fail "missing lifecycle path reports the accurate unit-contract failure (exit $missing_unit_path_rc; output: $missing_unit_path_output)"
fi

mv "${fixture_root}/run/acx/gpu-state.json" "${fixture_root}/run/acx/gpu-state.missing"
expect_failure "missing GPU state fails closed" "missing GPU state snapshot"
mv "${fixture_root}/run/acx/gpu-state.missing" "${fixture_root}/run/acx/gpu-state.json"

printf '{"state":"ready","written_at":819}\n' >"${fixture_root}/run/acx/gpu-state.json"
expect_failure "GPU state older than its budget fails" "stale GPU state snapshot"
printf '{"state":"ready","written_at":900}\n' >"${fixture_root}/run/acx/gpu-state.json"

mv "${fixture_root}/run/acx/describe-load.json" "${fixture_root}/run/acx/describe-load.missing"
expect_failure "missing describe-load fails closed" "missing describe load snapshot"
mv "${fixture_root}/run/acx/describe-load.missing" "${fixture_root}/run/acx/describe-load.json"

printf '{"queue_depth":0,"in_flight":0,"written_at":879}\n' >"${fixture_root}/run/acx/describe-load.json"
expect_failure "describe-load older than its budget fails" "stale describe load snapshot"
printf '{"queue_depth":0,"in_flight":0,"written_at":900}\n' >"${fixture_root}/run/acx/describe-load.json"

if [ "$(id -u)" -eq 0 ]; then
    printf 'SKIP: snapshot unreadable by API uid fails (uid 0 bypasses mode 000)\n'
else
    chmod 000 "${fixture_root}/run/acx/gpu-state.json"
    expect_failure "snapshot unreadable by API uid fails" "unreadable by uid"
    chmod 0644 "${fixture_root}/run/acx/gpu-state.json"
fi

expect_failure "state variable disagreement fails" "ACX_GPU_STATE_PATH disagrees" \
    ACX_GPU_STATE_PATH="${fixture_root}/run/acx/not-the-unit-path.json"

sed 's/:ro$//' "${fixture_root}/compose.yml" >"${fixture_root}/compose-rw.yml"
expect_failure "read-write mount fails" "read-only snapshot mount" \
    ACX_GPU_COMPOSE_FILE="${fixture_root}/compose-rw.yml"

expect_failure "unrendered snapshot mount template fails" "read-only snapshot mount" \
    ACX_GPU_COMPOSE_FILE="${fixture_root}/compose-template.yml"

expect_failure "unrendered GPU state environment template fails" \
    "does not pass the agreeing ACX_GPU_STATE_PATH" \
    ACX_GPU_COMPOSE_FILE="${fixture_root}/compose-template-env.yml"

if [ "$failures" -gt 0 ]; then
    printf 'FAILED: %s case(s)\n' "$failures" >&2
    exit 1
fi
printf 'ALL PASS\n'
