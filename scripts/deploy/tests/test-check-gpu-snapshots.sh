#!/usr/bin/env bash
# Local contract tests for check-gpu-snapshots.sh. No Docker or SSH required.

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash" >&2
    exit 2
fi
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
checker="${root}/scripts/deploy/check-gpu-snapshots.sh"
deployments_file="${root}/scripts/deploy/gpu-snapshot-deployments.conf"
recognition_deploy="${root}/scripts/deploy/recognition-service.sh"
checker_bash=${ACX_GPU_TEST_BASH:-/bin/bash}
prod_compose="${root}/apps/prototype-description-service/docker-compose.prod.yml"
prod_env="${root}/apps/prototype-description-service/.env.prod.example"
environment_compose="${root}/apps/prototype-description-service/docker-compose.env.yml"
makefile=${ACX_GPU_TEST_MAKEFILE:-${root}/Makefile}
fake_gpu_instance_id=ocid1.instance.oc1.phx.anyhqljtestfakegpu000000000000000000000000000000000000000000
fixture_root=$(mktemp -d)
trap 'rm -rf "$fixture_root"' EXIT

failures=0
skips=0
skipped_labels=()
# WBUX6-L5-NEW-04: a SKIP that only prints and then lands under `ALL PASS` is a
# gate that reports success for a case it never ran. Count them, name them in
# the summary, and let a runner that is supposed to be able to run everything
# turn any skip into a failure (RLSE-05 silent failure is the worst failure,
# ~/Development/heuristics-canon-research/lexicons/engineering.md:696;
# OBS-11 the bar must not follow what the runner happens to manage,
# lexicons/engineering.md:481; TEST-11 a coverage number the system itself
# can lower is coverage-gaming, lexicons/engineering.md:392).
require_full_coverage=${ACX_GPU_TEST_REQUIRE_FULL_COVERAGE:-0}
[[ "$require_full_coverage" =~ ^[01]$ ]] ||
    { echo "ACX_GPU_TEST_REQUIRE_FULL_COVERAGE must be 0 or 1" >&2; exit 2; }
pass() { printf 'PASS: %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }

# Two skip reasons, and only one of them is a coverage hole.
#
#   skip           -- this runner LACKS the privilege the case needs. Nothing
#                     else covers it, so on a runner that is supposed to be
#                     privileged (ACX_GPU_TEST_REQUIRE_FULL_COVERAGE=1) this is
#                     a failure, not a note. That flag is what stops the CI job
#                     from quietly degrading to "everything important skipped"
#                     if it ever loses its container/root/setpriv.
#   skip_covered   -- this runner HAS too much privilege: root bypasses the mode
#                     bits the case sets, so the case is unrunnable as root by
#                     construction and the container-gid block below asserts the
#                     same property through the group grant instead. Counted and
#                     named, never fatal -- making it fatal would demand a case
#                     that cannot exist and push the next maintainer to relax
#                     the flag entirely (sr-001).
_record_skip() {
    printf 'SKIP: %s\n' "$*"
    skipped_labels+=("$*")
    skips=$((skips + 1))
}
skip() {
    if [ "$require_full_coverage" -eq 1 ]; then
        fail "$* (SKIPPED for lack of privilege, but ACX_GPU_TEST_REQUIRE_FULL_COVERAGE=1 says this runner must be able to execute it)"
        return
    fi
    _record_skip "$@"
}
skip_covered() { _record_skip "$@"; }

assert_contains() {
    local label=$1 needle=$2 file=$3
    if grep -Fq -- "$needle" "$file"; then
        pass "$label"
    else
        fail "$label (missing: $needle)"
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

assert_output_not_contains() {
    local label=$1 needle=$2 output=$3
    if [[ "$output" == *"$needle"* ]]; then
        fail "$label (unexpected: $needle; output: $output)"
    else
        pass "$label"
    fi
}

run_checker() {
    env \
        ACX_GPU_UNIT_STATE_PATH="${fixture_root}/run/acx/gpu-state.json" \
        ACX_GPU_UNIT_LOAD_DIR="${fixture_root}/run/acx-write" \
        ACX_GPU_STATE_PATH="${fixture_root}/run/acx/gpu-state.json" \
        ACX_GPU_STATE_STALE_SECONDS=180 \
        ACX_DESCRIBE_LOAD_STALE_SECONDS=120 \
        ACX_GPU_SNAPSHOT_DIR="${fixture_root}/run/acx" \
        ACX_DESCRIBE_LOAD_DIR="${fixture_root}/run/acx-write" \
        ACX_GPU_COMPOSE_FILE="${fixture_root}/compose.yml" \
        ACX_GPU_READER_UID="$(id -u)" \
        ACX_NOW_EPOCH=1000 \
        "$@" "$checker_bash" "$checker"
}

run_checker_from_install() {
    local fixture_install=${ACX_GPU_INSTALL_SCRIPT:-${fixture_root}/install.sh}
    env -u ACX_GPU_UNIT_STATE_PATH -u ACX_GPU_UNIT_LOAD_DIR \
        ACX_GPU_INSTALL_SCRIPT="$fixture_install" \
        ACX_GPU_STATE_PATH="${fixture_root}/run/acx/gpu-state.json" \
        ACX_GPU_STATE_STALE_SECONDS=180 \
        ACX_DESCRIBE_LOAD_STALE_SECONDS=120 \
        ACX_GPU_SNAPSHOT_DIR="${fixture_root}/run/acx" \
        ACX_DESCRIBE_LOAD_DIR="${fixture_root}/run/acx-write" \
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

mkdir -p "${fixture_root}/run/acx" \
    "${fixture_root}/run/acx-write/dev" \
    "${fixture_root}/run/acx-write/dev-fir" \
    "${fixture_root}/run/acx-write/staging" \
    "${fixture_root}/run/acx-write/prod"
printf '{"state":"ready","written_at":900}\n' >"${fixture_root}/run/acx/gpu-state.json"
for environment in dev dev-fir staging prod; do
    printf '{"queue_depth":0,"in_flight":0,"batch_in_progress":false,"written_at":900}\n' \
        >"${fixture_root}/run/acx-write/${environment}/describe-load.json"
done
chmod 0644 "${fixture_root}/run/acx/gpu-state.json" \
    "${fixture_root}"/run/acx-write/*/describe-load.json
cat >"${fixture_root}/compose.yml" <<EOF
services:
  api:
    environment:
      - ACX_GPU_STATE_PATH=${fixture_root}/run/acx/gpu-state.json
      - ACX_DESCRIBE_LOAD_PATH=${fixture_root}/run/acx-write/\${ACX_ENV}/describe-load.json
    volumes:
      - ${fixture_root}/run/acx-write/\${ACX_ENV}:${fixture_root}/run/acx-write/\${ACX_ENV}
      - ${fixture_root}/run/acx:${fixture_root}/run/acx:ro
EOF
cat >"${fixture_root}/compose-old-layout.yml" <<EOF
services:
  api:
    environment:
      - ACX_GPU_STATE_PATH=${fixture_root}/run/acx/gpu-state.json
      - ACX_DESCRIBE_LOAD_PATH=${fixture_root}/run/acx-write/\${ACX_ENV}/describe-load.json
    volumes:
      - ${fixture_root}/run/acx/\${ACX_ENV}:${fixture_root}/run/acx-write/\${ACX_ENV}
      - ${fixture_root}/run/acx:${fixture_root}/run/acx:ro
EOF
cat >"${fixture_root}/compose-template.yml" <<'EOF'
services:
  api:
    environment:
      - ACX_GPU_STATE_PATH=${ACX_GPU_STATE_PATH}
      - ACX_DESCRIBE_LOAD_PATH=${ACX_DESCRIBE_LOAD_PATH}
    volumes:
      - ${ACX_DESCRIBE_LOAD_DIR}:/run/acx-write
      - ${ACX_GPU_SNAPSHOT_DIR}:/run/acx:ro
EOF
cat >"${fixture_root}/compose-template-env.yml" <<EOF
services:
  api:
    environment:
      - ACX_GPU_STATE_PATH=\${ACX_GPU_STATE_PATH}
      - ACX_DESCRIBE_LOAD_PATH=${fixture_root}/run/acx-write/\${ACX_ENV}/describe-load.json
    volumes:
      - ${fixture_root}/run/acx-write/\${ACX_ENV}:${fixture_root}/run/acx-write/\${ACX_ENV}
      - ${fixture_root}/run/acx:${fixture_root}/run/acx:ro
EOF
cat >"${fixture_root}/install.sh" <<EOF
ExecStart=python3 -m infra.oci.gpu_lifecycle --load-dir ${fixture_root}/run/acx-write --gpu-state-json ${fixture_root}/run/acx/gpu-state.json
ExecStart=python3 -m infra.oci.gpu_lifecycle --load-dir ${fixture_root}/run/acx-write --gpu-state-json ${fixture_root}/run/acx/gpu-state.json
EOF
cat >"${fixture_root}/install-missing-flags.sh" <<'EOF'
ExecStart=python3 -m infra.oci.gpu_lifecycle --instance-id ocid1.example
EOF
cat >"${fixture_root}/fake-deploy.sh" <<'EOF'
#!/usr/bin/env bash
echo "MUTATION_REACHED_DEPLOY $*"
EOF
chmod +x "${fixture_root}/fake-deploy.sh"
cat >"${fixture_root}/verify-harness.sh" <<'EOF'
source "$1"
curl() {
    printf '{"commit_sha":"%s"}\n' "$(git -C "$REPO_ROOT" rev-parse "$GIT_REF")"
}
read_remote_image_repo() { :; }
verify_running_image_matches_deployed() { return 0; }
verify_live_gpu_snapshots() {
    printf 'LIVE_GPU_SNAPSHOT_CHECK_CALLED:%s\n' "$1"
    return "${FAKE_GPU_SNAPSHOT_RC:-0}"
}
ACX_VERIFY_ATTEMPTS=1
ACX_VERIFY_SLEEP=0
do_verify dev
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
assert_contains "lifecycle units use aggregate load directory" \
    "--load-dir /run/acx-write" "${root}/scripts/deploy/gpu-lifecycle-install.sh"
if grep -Fq -- "--load-json" "${root}/scripts/deploy/gpu-lifecycle-install.sh"; then
    fail "lifecycle installer deletes the single-file load flag"
else
    pass "lifecycle installer deletes the single-file load flag"
fi
assert_contains "installer consumes the shared deployment registry" \
    "gpu-snapshot-deployments.conf" \
    "${root}/scripts/deploy/gpu-lifecycle-install.sh"
assert_contains "checker consumes the shared deployment registry" \
    "gpu-snapshot-deployments.conf" "$checker"

# Production state configuration remains a single deployment seam. The
# multi-environment compose template owns the per-environment load path.
assert_contains "env documents GPU state path" "ACX_GPU_STATE_PATH=/run/acx/gpu-state.json" "$prod_env"
assert_contains "env documents GPU freshness" "ACX_GPU_STATE_STALE_SECONDS=180" "$prod_env"
assert_contains "environment compose isolates load path" \
    'ACX_DESCRIBE_LOAD_PATH=/run/acx-write/${ACX_ENV}/describe-load.json' \
    "$environment_compose"
assert_contains "env documents load refresh" "ACX_DESCRIBE_LOAD_REFRESH_SECONDS=45" "$prod_env"
assert_contains "compose passes GPU state path" 'ACX_GPU_STATE_PATH=${ACX_GPU_STATE_PATH}' "$prod_compose"
assert_contains "compose mounts snapshot directory read-only" '${ACX_GPU_SNAPSHOT_DIR}:/run/acx:ro' "$prod_compose"
live_make_output=$(make -C "$root" --no-print-directory -n -f "$makefile" check-gpu-snapshots-live GPU_SNAPSHOT_ENV=dev 2>&1) || live_make_rc=$?
if [ "${live_make_rc:-0}" -eq 0 ]; then
    pass "live snapshot checker make target is runnable"
else
    fail "live snapshot checker make target is runnable (exit ${live_make_rc}; output: $live_make_output)"
fi
assert_output_contains "live snapshot checker executes the checker" \
    "scripts/deploy/check-gpu-snapshots.sh" "$live_make_output"
assert_output_contains "live snapshot checker defaults to the SSH tailnet host" \
    "acx-backend.tail1a44b8.ts.net" "$live_make_output"
for env_name in dev staging prod; do
    alias_make_rc=0
    alias_make_output=$(make -C "$root" --no-print-directory -n -f "$makefile" "deploy-verify-${env_name}" 2>&1) || alias_make_rc=$?
    if [ "$alias_make_rc" -eq 0 ]; then
        pass "fixed ${env_name} deploy verification make target is runnable"
    else
        fail "fixed ${env_name} deploy verification make target is runnable (exit $alias_make_rc; output: $alias_make_output)"
    fi
    assert_output_contains "fixed ${env_name} deploy verification invokes live snapshot checker" \
        "scripts/deploy/check-gpu-snapshots.sh" "$alias_make_output"
    assert_output_contains "fixed ${env_name} deploy verification retains its verify recipe" \
        "recognition-service.sh\" verify ${env_name}" "$alias_make_output"
done
generic_make_rc=0
generic_make_output=$(make -C "$root" --no-print-directory -n -f "$makefile" deploy-verify ENV=prod 2>&1) || generic_make_rc=$?
if [ "$generic_make_rc" -eq 0 ]; then
    pass "generic deploy verification make target is runnable"
else
    fail "generic deploy verification make target is runnable (exit $generic_make_rc; output: $generic_make_output)"
fi
assert_output_contains "generic deploy verification invokes live snapshot checker" \
    "scripts/deploy/check-gpu-snapshots.sh" "$generic_make_output"
assert_output_contains "generic deploy verification retains its verify recipe" \
    'recognition-service.sh" verify prod' "$generic_make_output"
missing_env_output=$(env -u GPU_SNAPSHOT_ENV make -C "$root" --no-print-directory -f "$makefile" \
    DEPLOY_SCRIPT="${fixture_root}/fake-deploy.sh" deploy-verify 2>&1) && missing_env_rc=0 || missing_env_rc=$?
if [ "$missing_env_rc" -eq 2 ] && [[ "$missing_env_output" == *"GPU_SNAPSHOT_ENV is required"* ]]; then
    pass "generic deploy verification requires an explicit environment"
else
    fail "generic deploy verification requires an explicit environment (exit $missing_env_rc; output: $missing_env_output)"
fi
assert_output_not_contains "missing environment stops before invalid-env fall-through" \
    "invalid GPU_SNAPSHOT_ENV" "$missing_env_output"
assert_output_not_contains "missing environment stops before deploy verification" \
    'MUTATION_REACHED_DEPLOY' "$missing_env_output"

config_make_rc=0
config_make_output=$(make -C "$root" --no-print-directory -f "$makefile" check-gpu-snapshots 2>&1) || config_make_rc=$?
if [ "$config_make_rc" -eq 0 ]; then
    pass "offline snapshot configuration make target is runnable"
else
    fail "offline snapshot configuration make target is runnable (exit $config_make_rc; output: $config_make_output)"
fi
assert_output_contains "offline snapshot configuration target runs config-only" \
    "configuration agree" "$config_make_output"
make_database=$(make -C "$root" --no-print-directory -pn -f "$makefile" 2>/dev/null)
assert_output_contains "check-all depends on snapshot configuration gate" \
    "check-all: check-gpu-snapshots" "$make_database"

verify_output=$(FAKE_GPU_SNAPSHOT_RC=0 "$checker_bash" "${fixture_root}/verify-harness.sh" "$recognition_deploy" 2>&1) || verify_rc=$?
if [ "${verify_rc:-0}" -eq 0 ] && [[ "$verify_output" == *"LIVE_GPU_SNAPSHOT_CHECK_CALLED:dev"* ]]; then
    pass "recognition post-restart verification runs live snapshot checker"
else
    fail "recognition post-restart verification runs live snapshot checker (exit ${verify_rc:-0}; output: $verify_output)"
fi
failed_verify_output=$(FAKE_GPU_SNAPSHOT_RC=1 "$checker_bash" "${fixture_root}/verify-harness.sh" "$recognition_deploy" 2>&1) && failed_verify_rc=0 || failed_verify_rc=$?
if [ "$failed_verify_rc" -ne 0 ] && [[ "$failed_verify_output" == *"GPU snapshot verification failed"* ]]; then
    pass "recognition post-restart verification is gated by snapshot checker exit"
else
    fail "recognition post-restart verification is gated by snapshot checker exit (exit $failed_verify_rc; output: $failed_verify_output)"
fi

expect_success "fresh readable snapshots and agreeing mount pass"

mv "${fixture_root}/run/acx-write/dev-fir/describe-load.json" \
    "${fixture_root}/run/acx-write/dev-fir/describe-load.missing"
expect_failure "missing dev-fir describe-load fails closed" \
    "missing describe load (dev-fir) snapshot"
mv "${fixture_root}/run/acx-write/dev-fir/describe-load.missing" \
    "${fixture_root}/run/acx-write/dev-fir/describe-load.json"

printf '{not-json}\n' >"${fixture_root}/run/acx-write/dev-fir/describe-load.json"
expect_failure "corrupt dev-fir describe-load fails closed" \
    "describe load (dev-fir) snapshot failed schema validation"
printf '{"queue_depth":0,"in_flight":0,"written_at":879}\n' \
    >"${fixture_root}/run/acx-write/dev-fir/describe-load.json"
expect_failure "stale dev-fir describe-load fails closed" \
    "stale describe load (dev-fir) snapshot"
printf '{"queue_depth":0,"in_flight":0,"batch_in_progress":false,"written_at":900}\n' \
    >"${fixture_root}/run/acx-write/dev-fir/describe-load.json"

cp "$deployments_file" "${fixture_root}/deployments-with-future.conf"
printf 'future-preview\n' >>"${fixture_root}/deployments-with-future.conf"
expect_failure "checker derives future deployments from the shared registry" \
    "missing describe-load environment directory: ${fixture_root}/run/acx-write/future-preview" \
    ACX_GPU_DEPLOYMENTS_FILE="${fixture_root}/deployments-with-future.conf"
installer_future_output=$(GPU_INSTANCE_ID="$fake_gpu_instance_id" \
    READY_URL=http://10.0.1.2:8000/health \
    ACX_GPU_DEPLOYMENTS_FILE="${fixture_root}/deployments-with-future.conf" \
    "${root}/scripts/deploy/gpu-lifecycle-install.sh" --host test.invalid \
    --ready-url http://127.0.0.1:8000/health/ready --dry-run 2>&1) || \
    installer_future_rc=$?
if [ "${installer_future_rc:-0}" -eq 0 ] && \
    [[ "$installer_future_output" == *"/run/acx-write/future-preview"* ]]; then
    pass "installer derives future deployment directories from the shared registry"
else
    fail "installer derives future deployment directories from the shared registry (exit ${installer_future_rc:-0}; output: $installer_future_output)"
fi

printf 'dev\ninvalid deployment\n' >"${fixture_root}/deployments-invalid.conf"
expect_failure "checker rejects an invalid shared deployment registry" \
    "invalid GPU snapshot deployment" \
    ACX_GPU_DEPLOYMENTS_FILE="${fixture_root}/deployments-invalid.conf"
installer_invalid_output=$(GPU_INSTANCE_ID="$fake_gpu_instance_id" \
    READY_URL=http://10.0.1.2:8000/health \
    ACX_GPU_DEPLOYMENTS_FILE="${fixture_root}/deployments-invalid.conf" \
    "${root}/scripts/deploy/gpu-lifecycle-install.sh" --host test.invalid --dry-run 2>&1) && \
    installer_invalid_rc=0 || installer_invalid_rc=$?
if [ "$installer_invalid_rc" -ne 0 ] && \
    [[ "$installer_invalid_output" == *"invalid GPU snapshot deployment"* ]]; then
    pass "installer rejects an invalid shared deployment registry"
else
    fail "installer rejects an invalid shared deployment registry (exit $installer_invalid_rc; output: $installer_invalid_output)"
fi

printf '{"state":"bogus","written_at":900}\n' >"${fixture_root}/run/acx/gpu-state.json"
expect_failure "GPU state outside the producer enum fails closed" \
    "state must be one of"
printf '{"written_at":900}\n' >"${fixture_root}/run/acx/gpu-state.json"
expect_failure "GPU state key is required" "state is required"
printf '{"state":"degraded","written_at":900}\n' >"${fixture_root}/run/acx/gpu-state.json"
expect_failure "degraded GPU state requires a reason" \
    "reason must be a non-blank string for degraded state"
printf '{"state":"ready","instance_id":"","written_at":900}\n' >"${fixture_root}/run/acx/gpu-state.json"
expect_failure "GPU instance_id must be a non-blank string when present" \
    "instance_id must be null or a non-blank string"
printf '{"state":"ready","reason":"not-degraded","written_at":900}\n' >"${fixture_root}/run/acx/gpu-state.json"
expect_failure "GPU reason is forbidden outside degraded state" \
    "reason is only valid for degraded state"
printf '{"state":"degraded","instance_id":"ocid1.gpu","reason":"probe_failed","since":850,"written_at":900}\n' \
    >"${fixture_root}/run/acx/gpu-state.json"
expect_success "fully valid degraded GPU and load snapshots pass"
printf '{"state":"ready","written_at":900}\n' >"${fixture_root}/run/acx/gpu-state.json"

printf '{"in_flight":0,"written_at":900}\n' >"${fixture_root}/run/acx-write/dev/describe-load.json"
expect_failure "load queue_depth is required" "queue_depth is required"
printf '{"queue_depth":"0","in_flight":0,"written_at":900}\n' \
    >"${fixture_root}/run/acx-write/dev/describe-load.json"
expect_failure "load queue_depth must be an integer" \
    "queue_depth must be a non-negative integer"
printf '{"queue_depth":-1,"in_flight":0,"written_at":900}\n' \
    >"${fixture_root}/run/acx-write/dev/describe-load.json"
expect_failure "load counters must be non-negative" \
    "queue_depth must be a non-negative integer"
printf '{"queue_depth":0,"in_flight":0,"batch_in_progress":0,"written_at":900}\n' \
    >"${fixture_root}/run/acx-write/dev/describe-load.json"
expect_failure "load batch flag must be a real boolean" \
    "batch_in_progress must be a boolean when present"
printf '{"queue_depth":0,"in_flight":0,"batch_in_progress":false,"written_at":900}\n' \
    >"${fixture_root}/run/acx-write/dev/describe-load.json"
expect_success "fully valid GPU and load snapshot shapes pass"

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

mv "${fixture_root}/run/acx-write/dev/describe-load.json" "${fixture_root}/run/acx-write/dev/describe-load.missing"
expect_failure "missing environment describe-load fails closed" "missing describe load (dev) snapshot"
mv "${fixture_root}/run/acx-write/dev/describe-load.missing" "${fixture_root}/run/acx-write/dev/describe-load.json"

printf '{"queue_depth":0,"in_flight":0,"written_at":879}\n' >"${fixture_root}/run/acx-write/dev/describe-load.json"
expect_failure "environment describe-load older than its budget fails" "stale describe load (dev) snapshot"
printf '{"queue_depth":0,"in_flight":0,"written_at":900}\n' >"${fixture_root}/run/acx-write/dev/describe-load.json"

if [ "$(id -u)" -eq 0 ]; then
    skip_covered "each environment directory must be API-writable (uid 0 bypasses mode 0555; covered by the container-gid block below)"
else
    chmod 0555 "${fixture_root}/run/acx-write/staging"
    expect_failure "each environment directory must be API-writable" "not writable by api container identity"
    chmod 0755 "${fixture_root}/run/acx-write/staging"
fi

if [ "$(id -u)" -eq 0 ]; then
    skip_covered "snapshot unreadable by API uid fails (uid 0 bypasses mode 000; the container-gid block below covers unreadability through the group grant)"
else
    chmod 000 "${fixture_root}/run/acx/gpu-state.json"
    expect_failure "snapshot unreadable by API uid fails" "unreadable by api container identity"
    chmod 0644 "${fixture_root}/run/acx/gpu-state.json"
fi

expect_failure "state variable disagreement fails" "ACX_GPU_STATE_PATH disagrees" \
    ACX_GPU_STATE_PATH="${fixture_root}/run/acx/not-the-unit-path.json"

sed 's/:ro$//' "${fixture_root}/compose.yml" >"${fixture_root}/compose-rw.yml"
expect_failure "read-write state mount fails" "read-only state mount" \
    ACX_GPU_COMPOSE_FILE="${fixture_root}/compose-rw.yml"

expect_failure "old shared host-directory layout fails" "writable load mount" \
    ACX_GPU_COMPOSE_FILE="${fixture_root}/compose-old-layout.yml"

expect_failure "shared state and load unit directory fails" "separate snapshot directories" \
    ACX_GPU_UNIT_LOAD_DIR="${fixture_root}/run/acx" \
    ACX_DESCRIBE_LOAD_DIR="${fixture_root}/run/acx"

expect_failure "load directory variable disagreement fails" "ACX_DESCRIBE_LOAD_DIR disagrees" \
    ACX_DESCRIBE_LOAD_DIR="${fixture_root}/run/not-the-unit-directory"

expect_failure "compose-derived parent must agree with lifecycle load directory" \
    "compose-derived load parent disagrees with lifecycle --load-dir" \
    ACX_GPU_UNIT_LOAD_DIR="${fixture_root}/run/other-load-root" \
    ACX_DESCRIBE_LOAD_DIR="${fixture_root}/run/other-load-root"

expect_failure "unrendered snapshot mount template fails" "must end in describe-load.json" \
    ACX_GPU_COMPOSE_FILE="${fixture_root}/compose-template.yml"

expect_failure "unrendered GPU state environment template fails" \
    "does not pass the agreeing ACX_GPU_STATE_PATH" \
    ACX_GPU_COMPOSE_FILE="${fixture_root}/compose-template-env.yml"

# --- WBUX6-L5-NEW-03: uid 0 must never take the `test -r/-w` fast path -------
#
# Root bypasses mode bits, so a probe that runs as uid 0 reports "the api
# container can read this" about an identity it never assumed and can never
# fail. Deployment runs the checker as root over SSH -- exactly the path where
# the assertion was inert.
#
# The kernel-level version of this needs real root (the block further down), but
# the *decision* -- drop privilege via setpriv, or refuse -- is observable
# anywhere by shimming the three programs the checker consults about identity.
# Keeping these runnable on a developer laptop is the point: the assertions that
# only run under root were the ones nobody was running (WBUX6-L5-NEW-04).
shim_bin="${fixture_root}/shim-root"
mkdir -p "$shim_bin"
setpriv_log="${fixture_root}/setpriv.log"
observed_gid=4242

cat >"${shim_bin}/id" <<'SHIM'
#!/bin/sh
# Present a root shell to the checker without needing one.
case "$1" in
    -u) echo 0 ;;
    *) exec /usr/bin/id "$@" ;;
esac
SHIM

cat >"${shim_bin}/stat" <<SHIM
#!/bin/sh
# Publish a fixed group for the snapshot so the assertion below does not depend
# on the real gid of whoever runs the suite (on many runners uid == gid, which
# would make "used the observed gid" and "used the reader uid" indistinguishable
# -- the exact confusion WBUX6-MRG-01 was made of).
echo ${observed_gid}
SHIM

cat >"${shim_bin}/setpriv" <<SHIM
#!/bin/sh
# Record the identity the checker asked to assume, then run the probe. It
# cannot really drop privilege here; the assertion is about which identity was
# requested, not about the kernel honouring it.
printf '%s\n' "\$*" >>"${setpriv_log}"
while [ \$# -gt 0 ]; do
    case "\$1" in
        --*) shift ;;
        *) break ;;
    esac
done
exec "\$@"
SHIM
chmod +x "${shim_bin}/id" "${shim_bin}/stat" "${shim_bin}/setpriv"

: >"$setpriv_log"
expect_success "uid 0 drops privilege through setpriv instead of probing as root" \
    PATH="${shim_bin}:${PATH}" ACX_GPU_READER_UID=0
if [ -s "$setpriv_log" ]; then
    pass "uid 0 never probes with a bare test -r/-w"
else
    fail "uid 0 never probes with a bare test -r/-w (setpriv was never invoked; root bypassed the mode bits it was supposed to read)"
fi
assert_contains "the privilege drop targets the OBSERVED snapshot group" \
    "--regid=${observed_gid}" "$setpriv_log"
if grep -Fq -- "--regid=0" "$setpriv_log"; then
    fail "the privilege drop must not reuse the reader uid as the gid"
else
    pass "the privilege drop must not reuse the reader uid as the gid"
fi

# ...and when no snapshot has been published there is no group to observe, so
# the resolution must die rather than fall back to the reader uid -- the exact
# guess that made WBUX6-MRG-01 unfalsifiable. The root-only block below asserts
# this too, but only where it can run; this one runs everywhere.
for env_name in dev dev-fir staging prod; do
    mv "${fixture_root}/run/acx-write/${env_name}/describe-load.json" \
        "${fixture_root}/${env_name}-unobservable.json"
done
expect_failure "an unobservable container gid is never guessed from the reader uid" \
    "cannot determine the api container identity" \
    PATH="${shim_bin}:${PATH}" ACX_GPU_READER_UID=0
for env_name in dev dev-fir staging prod; do
    mv "${fixture_root}/${env_name}-unobservable.json" \
        "${fixture_root}/run/acx-write/${env_name}/describe-load.json"
done

# Refusal, not a pass: uid 0 with no setpriv cannot assume the api identity at
# all, so the only honest answer is an error. A restricted PATH is how the
# absence is made real on a runner that does ship setpriv.
shim_nosetpriv="${fixture_root}/shim-root-nosetpriv"
mkdir -p "$shim_nosetpriv"
cp "${shim_bin}/id" "${shim_bin}/stat" "$shim_nosetpriv/"
missing_tool=
for tool in awk sed grep tr sort wc cat date dirname basename env bash python3; do
    tool_path=$(command -v "$tool" 2>/dev/null) || { missing_tool=$tool; break; }
    ln -sf "$tool_path" "${shim_nosetpriv}/${tool}"
done
if [ -n "$missing_tool" ]; then
    fail "setpriv-free PATH fixture could not be built (missing $missing_tool)"
else
    expect_failure "uid 0 without setpriv refuses to probe rather than passing" \
        "cannot assume the api container identity" \
        PATH="$shim_nosetpriv" ACX_GPU_READER_UID=0
fi

# The third branch is the one a laptop actually hits: not root, and not the api
# uid either. It must report "unknown" too. Shimming `id` rather than testing
# the ambient uid keeps this case running on every host, including the root
# container job -- an assertion that only runs for some callers is the defect
# this whole block exists to prevent (WBUX6-L5-NEW-04).
shim_otheruid="${fixture_root}/shim-otheruid"
mkdir -p "$shim_otheruid"
cat >"${shim_otheruid}/id" <<'SHIM'
#!/bin/sh
case "$1" in
    -u) echo 7777 ;;
    *) exec /usr/bin/id "$@" ;;
esac
SHIM
chmod +x "${shim_otheruid}/id"
expect_failure "an unprivileged uid that is not the api uid refuses to probe" \
    "cannot assume the api container identity" \
    PATH="${shim_otheruid}:${PATH}" ACX_GPU_READER_UID=10001

# --- WBUX6-MRG-01: the writability probe must use the container's REAL gid ---
#
# The probe used to run `setpriv --reuid=$reader_uid --regid=$reader_uid`, i.e.
# it assumed the container's gid equals its uid. It does not: the api image
# creates the runtime user with an explicit uid but let the base image pick the
# gid (observed `uid=10001(acx) gid=999(acx)`). The host grants write access to
# /run/acx-write/<env> through group 10001, so with a drifting gid the container
# matches neither owner nor group -- yet the gate, probing the gid it invented,
# reported the directory writable. It could not fail. These cases exercise the
# resolution, and the root-only block exercises the probe itself.

if [ "$(id -u)" -eq 0 ] && command -v setpriv >/dev/null 2>&1; then
    # Reproduce the production shape: the host owns the load dirs and grants
    # write through group 10001; the container published its snapshots as
    # 10001:10001. mktemp -d is 0700, so the fixture chain must be traversable
    # by uid 10001 or every probe would report "unreadable" for the wrong
    # reason and these cases would assert nothing.
    chmod 0755 "$fixture_root" "${fixture_root}/run"
    chown -R root:10001 "${fixture_root}/run/acx-write"
    chmod 0775 "${fixture_root}/run/acx-write" "${fixture_root}/run/acx-write"/*
    chown 10001:10001 "${fixture_root}/run/acx-write"/*/describe-load.json
    chmod 0755 "${fixture_root}/run/acx"
    chmod 0644 "${fixture_root}/run/acx/gpu-state.json"

    expect_success "load dir writable by the container's real gid passes" \
        ACX_GPU_READER_UID=10001

    # The whole point of the finding: a container gid that cannot write must be
    # OBSERVED. Probing --regid=$reader_uid reported this directory writable.
    chown 10001:999 "${fixture_root}/run/acx-write"/*/describe-load.json
    expect_failure "a container gid that cannot write is detected" \
        "not writable by api container identity" \
        ACX_GPU_READER_UID=10001
    chown 10001:10001 "${fixture_root}/run/acx-write"/*/describe-load.json

    # With nothing published there is no observable container identity. The
    # gate must say so rather than invent one.
    for env_name in dev dev-fir staging prod; do
        mv "${fixture_root}/run/acx-write/${env_name}/describe-load.json" \
            "${fixture_root}/${env_name}-load.json"
    done
    expect_failure "an unobservable container identity fails closed" \
        "cannot determine the api container identity" \
        ACX_GPU_READER_UID=10001
    for env_name in dev dev-fir staging prod; do
        mv "${fixture_root}/${env_name}-load.json" \
            "${fixture_root}/run/acx-write/${env_name}/describe-load.json"
    done

    chown -R "$(id -u):$(id -g)" "${fixture_root}/run/acx-write"
else
    skip "container-gid writability probe (needs root + setpriv; enrolled on the Linux container job in .github/workflows/gpu-snapshot-gate.yml)"
fi

if [ "$failures" -gt 0 ]; then
    printf 'FAILED: %s case(s)\n' "$failures" >&2
    exit 1
fi
if [ "$skips" -gt 0 ]; then
    # Never let a skipped case hide behind an unqualified "ALL PASS".
    printf 'PASSED WITH %s SKIPPED case(s):\n' "$skips"
    printf '  - %s\n' "${skipped_labels[@]}"
    printf 'Set ACX_GPU_TEST_REQUIRE_FULL_COVERAGE=1 to make a privilege-lacking skip fatal;\n'
    printf 'the root + setpriv runner is .github/workflows/gpu-snapshot-gate.yml.\n'
    exit 0
fi
printf 'ALL PASS\n'
