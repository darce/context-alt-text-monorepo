#!/usr/bin/env bash
# Behavioural contract for scripts/deploy/ocir-token-rotate.sh (OCIRV-1).

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash" >&2
    exit 2
fi
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
rotate_script="${script_dir}/../ocir-token-rotate.sh"
runbook_file="${script_dir}/../../../infra/oci/vault-instance-principal-runbook.md"
fixture_dir=$(mktemp -d "${TMPDIR:-/tmp}/ocir-rotate-test.XXXXXX")
trap 'rm -rf "$fixture_dir"' EXIT
fake_bin="${fixture_dir}/bin"
mkdir "$fake_bin"

failures=0
assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        echo "ok   ${label}"
    else
        echo "FAIL ${label}: expected '${expected}', got '${actual}'"
        failures=$((failures + 1))
    fi
}
assert_contains() {
    local label="$1" needle="$2" file="$3"
    if grep -Fq -- "$needle" "$file"; then
        echo "ok   ${label}"
    else
        echo "FAIL ${label}: missing '${needle}'"
        failures=$((failures + 1))
    fi
}
assert_absent() {
    local label="$1" needle="$2" file="$3"
    if grep -Fq -- "$needle" "$file"; then
        echo "FAIL ${label}: unexpectedly found '${needle}'"
        failures=$((failures + 1))
    else
        echo "ok   ${label}"
    fi
}
assert_no_file() {
    local label="$1" file="$2"
    if [ ! -s "$file" ]; then
        echo "ok   ${label}"
    else
        echo "FAIL ${label}: ${file} is not empty"
        failures=$((failures + 1))
    fi
}
assert_path_absent() {
    local label="$1" path="$2"
    if [ ! -e "$path" ]; then
        echo "ok   ${label}"
    else
        echo "FAIL ${label}: ${path} still exists"
        failures=$((failures + 1))
    fi
}

# The wrapper discovers `oci` in PATH, while ACX_OCI_PYTHON points at this
# interpreter seam. It accepts the SDK probe and records every helper write.
cat >"${fake_bin}/fake-python" <<'EOF'
#!/usr/bin/env bash
set -eu
if [ "${1:-}" = -c ]; then
    exit 0
fi
secret_name=""
readable_timeout=""
while [ $# -gt 0 ]; do
    case "$1" in
        --secret-name) secret_name="$2"; shift ;;
        --readable-timeout) readable_timeout="$2"; shift ;;
    esac
    shift
done
value=$(cat)
printf '%s|%s|%s\n' "$secret_name" "$readable_timeout" "$value" >>"$OCIR_TEST_PUT_LOG"
EOF

cat >"${fake_bin}/oci" <<'EOF'
#!/usr/bin/env bash
case " $* " in
    *" --secret-name OCIR_USERNAME "*)
        if [ -n "${OCIR_TEST_USERNAME_SLEEP:-}" ]; then
            sleep "$OCIR_TEST_USERNAME_SLEEP"
        fi
        if [ -n "${OCIR_TEST_USERNAME_STDERR:-}" ]; then
            printf '%s\n' "$OCIR_TEST_USERNAME_STDERR" >&2
        fi
        printf '%s' "$OCIR_TEST_STORED_USERNAME" | base64
        ;;
    *" --secret-name OCIR_AUTH_TOKEN "*) printf '%s' "$OCIR_TEST_STORED_TOKEN" | base64 ;;
    *) echo "unexpected fake oci arguments: $*" >&2; exit 64 ;;
esac
EOF

cat >"${fake_bin}/docker" <<'EOF'
#!/usr/bin/env bash
set -eu
count=0
if [ -f "$OCIR_TEST_DOCKER_COUNT" ]; then count=$(cat "$OCIR_TEST_DOCKER_COUNT"); fi
count=$((count + 1))
printf '%s' "$count" >"$OCIR_TEST_DOCKER_COUNT"
value=$(cat)
config_dir="${DOCKER_CONFIG:-${HOME}/.docker}"
printf '%s|%s|%s|%s\n' "$count" "$*" "$value" "$config_dir" >>"$OCIR_TEST_DOCKER_LOG"
mkdir -p "$config_dir"
printf 'fake docker credential %s\n' "$count" >>"${config_dir}/config.json"
if [ "${OCIR_TEST_DOCKER_FAIL_AT:-}" = "$count" ]; then
    echo 'Error response from daemon: login attempt failed with status: 401 Unauthorized' >&2
    exit 1
fi
EOF

cat >"${fake_bin}/ssh" <<'EOF'
#!/usr/bin/env bash
set -eu
printf 'called\n' >>"$OCIR_TEST_SSH_LOG"
if [ "${OCIR_TEST_SSH_MODE:-success}" = timeout ]; then
    printf 'ssh: connect to host example port 22: Connection timed out\033]52;c;VEVSU0lPTg==\a\n' >&2
    exit 255
fi
remote_command=""
for arg in "$@"; do remote_command="$arg"; done
bash -c "$remote_command"
EOF

cat >"${fake_bin}/timeout" <<'EOF'
#!/usr/bin/env bash
shift
exec "$@"
EOF
chmod +x "${fake_bin}/fake-python" "${fake_bin}/oci" \
    "${fake_bin}/docker" "${fake_bin}/ssh" "${fake_bin}/timeout"

put_log="${fixture_dir}/put.log"
docker_log="${fixture_dir}/docker.log"
docker_count="${fixture_dir}/docker.count"
ssh_log="${fixture_dir}/ssh.log"
rotate_stdout="${fixture_dir}/rotate.stdout"
rotate_stderr="${fixture_dir}/rotate.stderr"
known_user='tenant/operator@example.test'
known_token='ROTATE_SENTINEL_token-$!*[]'
home_dir="${fixture_dir}/home"
home_config="${home_dir}/.docker/config.json"
pristine_home_config='pre-existing operator docker configuration'

reset_case() {
    : >"$put_log"
    : >"$docker_log"
    : >"$ssh_log"
    rm -f "$docker_count"
    mkdir -p "$(dirname "$home_config")"
    printf '%s\n' "$pristine_home_config" >"$home_config"
    unset ACX_VAULT_FETCH_TIMEOUT OCIR_TEST_DOCKER_FAIL_AT OCIR_TEST_SSH_MODE \
        OCIR_TEST_STORED_USERNAME OCIR_TEST_USERNAME_SLEEP \
        OCIR_TEST_USERNAME_STDERR
}

run_rotate() {
    local token="$1"
    shift
    rotate_rc=0
    (
        export PATH="${fake_bin}:${PATH}"
        export HOME="$home_dir"
        export ACX_OCI_PYTHON="${fake_bin}/fake-python"
        export ACX_LOCAL_OCI_BIN=oci
        export ACX_REMOTE_OCI_BIN=oci
        export ACX_VAULT_OCID='ocid1.vault.oc1.test.contract'
        export ACX_VAULT_FETCH_TIMEOUT="${ACX_VAULT_FETCH_TIMEOUT:-30}"
        export ACX_OCIR_TOKEN_SECRET=OCIR_AUTH_TOKEN
        export ACX_OCIR_USERNAME_SECRET=OCIR_USERNAME
        export OCIR_TEST_PUT_LOG="$put_log"
        export OCIR_TEST_DOCKER_LOG="$docker_log"
        export OCIR_TEST_DOCKER_COUNT="$docker_count"
        export OCIR_TEST_SSH_LOG="$ssh_log"
        if [ "${OCIR_TEST_STORED_USERNAME+x}" = x ]; then
            export OCIR_TEST_STORED_USERNAME
        else
            export OCIR_TEST_STORED_USERNAME="$known_user"
        fi
        export OCIR_TEST_STORED_TOKEN="$known_token"
        export OCIR_TEST_DOCKER_FAIL_AT="${OCIR_TEST_DOCKER_FAIL_AT:-}"
        export OCIR_TEST_SSH_MODE="${OCIR_TEST_SSH_MODE:-success}"
        export OCIR_TEST_USERNAME_SLEEP="${OCIR_TEST_USERNAME_SLEEP:-}"
        export OCIR_TEST_USERNAME_STDERR="${OCIR_TEST_USERNAME_STDERR:-}"
        printf '%s' "$token" | bash "$rotate_script" --stdin "$@"
    ) >"$rotate_stdout" 2>"$rotate_stderr" || rotate_rc=$?
}

# Happy path executes the whole wrapper: direct proof, ordered writes, local
# Vault round-trip and remote-over-SSH round-trip.
reset_case
run_rotate "$known_token" --set-username "$known_user" --readable-timeout 0
assert_eq "complete rotation exits zero" 0 "$rotate_rc"
assert_contains "success sentinel proves wrapper reached its end" \
    'rotation complete: both hosts authenticate from acx-vault' "$rotate_stdout"
assert_eq "fresh proof plus two Vault-backed login legs ran" 3 "$(cat "$docker_count")"
assert_eq "remote verification ran once" 1 "$(wc -l <"$ssh_log" | tr -d ' ')"
assert_contains "token is committed first with forwarded timeout" \
    "OCIR_AUTH_TOKEN|0|${known_token}" "$put_log"
assert_eq "token and username are the only writes, in safe order" \
    "OCIR_AUTH_TOKEN|0|${known_token}
OCIR_USERNAME|0|${known_user}" "$(cat "$put_log")"
assert_contains "token destination is disclosed before the write" \
    'writing vault ocid1.vault.oc1.test.contract secret OCIR_AUTH_TOKEN' "$rotate_stderr"
assert_contains "username destination is disclosed before the write" \
    'writing vault ocid1.vault.oc1.test.contract secret OCIR_USERNAME' "$rotate_stderr"

# Routine rotations fetch the existing username from Vault. OCI diagnostics
# remain diagnostics, and the direct proof uses a disposable Docker store.
reset_case
OCIR_TEST_USERNAME_STDERR='fake OCI upgrade notice: use a newer profile'
run_rotate "$known_token" --skip-verify
assert_eq "rotation without username override exits zero" 0 "$rotate_rc"
assert_eq "Vault username is passed cleanly to proof login" \
    "login iad.ocir.io -u ${known_user} --password-stdin" \
    "$(sed -n '1s/^[^|]*|\([^|]*\)|.*$/\1/p' "$docker_log")"
assert_absent "OCI username diagnostic is not spliced into docker arguments" \
    "$OCIR_TEST_USERNAME_STDERR" "$docker_log"
proof_config="$(sed -n '1s/^[^|]*|[^|]*|[^|]*|//p' "$docker_log")"
if [ "$proof_config" != "${home_dir}/.docker" ]; then
    echo "ok   direct proof avoids the operator Docker config"
else
    echo "FAIL direct proof avoids the operator Docker config"
    failures=$((failures + 1))
fi
assert_path_absent "direct proof Docker config is removed on exit" "$proof_config"
assert_eq "operator Docker config remains unchanged" \
    "$pristine_home_config" "$(cat "$home_config")"

reset_case
OCIR_TEST_STORED_USERNAME=''
run_rotate "$known_token" --skip-verify
if [ "$rotate_rc" -ne 0 ]; then
    echo "ok   empty Vault username is rejected"
else
    echo "FAIL empty Vault username is rejected: exit 0"
    failures=$((failures + 1))
fi
assert_contains "empty Vault username has a classified diagnostic" \
    '[secret_missing]' "$rotate_stderr"
assert_no_file "empty Vault username is rejected before docker login" "$docker_log"
assert_no_file "empty Vault username is rejected before any Vault write" "$put_log"

reset_case
OCIR_TEST_STORED_USERNAME='   '
run_rotate "$known_token" --skip-verify
if [ "$rotate_rc" -ne 0 ]; then
    echo "ok   whitespace-only Vault username is rejected"
else
    echo "FAIL whitespace-only Vault username is rejected: exit 0"
    failures=$((failures + 1))
fi
assert_contains "whitespace-only Vault username has a classified diagnostic" \
    '[secret_missing]' "$rotate_stderr"
assert_no_file "whitespace-only username is rejected before docker login" "$docker_log"
assert_no_file "whitespace-only username is rejected before any Vault write" "$put_log"

reset_case
ACX_VAULT_FETCH_TIMEOUT=1
OCIR_TEST_USERNAME_SLEEP=3
run_rotate "$known_token" --skip-verify
if [ "$rotate_rc" -ne 0 ]; then
    echo "ok   slow Vault username read is bounded"
else
    echo "FAIL slow Vault username read is bounded: exit 0"
    failures=$((failures + 1))
fi
assert_contains "username-read timeout is Vault-classified" \
    '[vault_unreachable]' "$rotate_stderr"
assert_no_file "timed-out username read happens before docker login" "$docker_log"
assert_no_file "timed-out username read happens before any Vault write" "$put_log"

# Secret-name environment overrides are configuration, not write authority.
reset_case
bad_secret_rc=0
printf '%s' "$known_token" | PATH="${fake_bin}:${PATH}" \
    ACX_OCIR_TOKEN_SECRET=RECOGNITION_ADMIN_TOKEN \
    ACX_OCIR_USERNAME_SECRET=OCIR_USERNAME \
    bash "$rotate_script" --stdin >"$rotate_stdout" 2>"$rotate_stderr" || bad_secret_rc=$?
if [ "$bad_secret_rc" -ne 0 ]; then
    echo "ok   unowned secret name is rejected"
else
    echo "FAIL unowned secret name is rejected: exit 0"
    failures=$((failures + 1))
fi
assert_contains "rejection names the unsafe destination" RECOGNITION_ADMIN_TOKEN "$rotate_stderr"
assert_no_file "unowned name is rejected before any Vault write" "$put_log"
reset_case
bad_username_rc=0
printf '%s' "$known_token" | PATH="${fake_bin}:${PATH}" \
    ACX_OCIR_TOKEN_SECRET=OCIR_AUTH_TOKEN \
    ACX_OCIR_USERNAME_SECRET=POSTGRES_DSN \
    bash "$rotate_script" --stdin >"$rotate_stdout" 2>"$rotate_stderr" || bad_username_rc=$?
if [ "$bad_username_rc" -ne 0 ]; then
    echo "ok   unowned username secret name is rejected"
else
    echo "FAIL unowned username secret name is rejected: exit 0"
    failures=$((failures + 1))
fi
assert_contains "username rejection names the unsafe destination" POSTGRES_DSN "$rotate_stderr"
assert_no_file "unowned username name is rejected before any Vault write" "$put_log"

# A mistyped/revoked fresh token must fail against OCIR before durable state.
reset_case
OCIR_TEST_DOCKER_FAIL_AT=1
run_rotate 'bad-token' --set-username "$known_user"
if [ "$rotate_rc" -ne 0 ]; then
    echo "ok   direct OCIR proof failure exits non-zero"
else
    echo "FAIL direct OCIR proof failure exits non-zero"
    failures=$((failures + 1))
fi
assert_contains "direct proof identifies OCIR rejection" '[ocir_rejected]' "$rotate_stderr"
assert_no_file "failed direct proof leaves Vault untouched" "$put_log"

# --skip-verify never skips the fresh-token proof or local Vault verification;
# it only avoids opening the production SSH session.
reset_case
run_rotate "$known_token" --set-username "$known_user" --skip-verify
assert_eq "safe skip mode exits zero" 0 "$rotate_rc"
assert_eq "safe skip mode still performs direct and local proof" 2 "$(cat "$docker_count")"
assert_no_file "safe skip mode does not contact SSH host" "$ssh_log"
assert_contains "safe skip result states exactly what was omitted" \
    'production-VM SSH verification skipped' "$rotate_stdout"

# Timeout accepts integers/decimals including zero and is passed to each write.
reset_case
run_rotate "$known_token" --set-username "$known_user" --readable-timeout 2.5 --skip-verify
assert_eq "decimal readable timeout is accepted" 0 "$rotate_rc"
assert_contains "decimal timeout reaches token helper" 'OCIR_AUTH_TOKEN|2.5|' "$put_log"
assert_contains "decimal timeout reaches username helper" 'OCIR_USERNAME|2.5|' "$put_log"
for valid_timeout in .5 5.; do
    reset_case
    run_rotate "$known_token" --set-username "$known_user" --readable-timeout "$valid_timeout" --skip-verify
    assert_eq "numeric timeout '${valid_timeout}' is accepted" 0 "$rotate_rc"
    assert_contains "numeric timeout '${valid_timeout}' reaches helper" \
        "OCIR_AUTH_TOKEN|${valid_timeout}|" "$put_log"
done
for invalid_timeout in -1 nope 1.2.3 .; do
    reset_case
    run_rotate "$known_token" --readable-timeout "$invalid_timeout"
    if [ "$rotate_rc" -ne 0 ]; then
        echo "ok   invalid timeout '${invalid_timeout}' is rejected"
    else
        echo "FAIL invalid timeout '${invalid_timeout}' is rejected: exit 0"
        failures=$((failures + 1))
    fi
    assert_contains "invalid timeout '${invalid_timeout}' has a clear diagnostic" \
        'invalid --readable-timeout' "$rotate_stderr"
    assert_no_file "invalid timeout '${invalid_timeout}' causes no write" "$put_log"
done
reset_case
run_rotate "$known_token" --readable-timeout
if [ "$rotate_rc" -ne 0 ]; then
    echo "ok   missing readable timeout value is rejected"
else
    echo "FAIL missing readable timeout value is rejected: exit 0"
    failures=$((failures + 1))
fi
assert_contains "missing timeout has a clear diagnostic" \
    '--readable-timeout needs a non-negative number' "$rotate_stderr"
assert_no_file "missing timeout causes no write" "$put_log"

# A failure after a local command ran stays in the OCIR/Vault taxonomy. A
# failure before the remote-session marker is specifically SSH transport.
reset_case
OCIR_TEST_DOCKER_FAIL_AT=2
run_rotate "$known_token" --set-username "$known_user" --skip-verify
if [ "$rotate_rc" -ne 0 ]; then
    echo "ok   laptop Vault login failure exits non-zero"
else
    echo "FAIL laptop Vault login failure exits non-zero"
    failures=$((failures + 1))
fi
assert_contains "laptop command failure is classified as OCIR" \
    'FAIL laptop Vault credential [ocir_rejected]' "$rotate_stderr"

reset_case
OCIR_TEST_DOCKER_FAIL_AT=3
run_rotate "$known_token" --set-username "$known_user"
if [ "$rotate_rc" -ne 0 ]; then
    echo "ok   remote login command failure exits non-zero"
else
    echo "FAIL remote login command failure exits non-zero"
    failures=$((failures + 1))
fi
assert_contains "remote command failure is classified as OCIR" '[ocir_rejected]' "$rotate_stderr"
assert_absent "executed remote command is not classified as SSH" '[ssh_unreachable]' "$rotate_stderr"

# SSH transport is not an OCIR/Vault error, and hostile terminal controls from
# the endpoint must not be replayed to the operator.
reset_case
OCIR_TEST_SSH_MODE=timeout
run_rotate "$known_token" --set-username "$known_user"
if [ "$rotate_rc" -ne 0 ]; then
    echo "ok   SSH timeout fails rotation"
else
    echo "FAIL SSH timeout fails rotation: exit 0"
    failures=$((failures + 1))
fi
assert_contains "SSH timeout has transport classification" '[ssh_unreachable]' "$rotate_stderr"
assert_absent "SSH timeout is not misclassified as Vault" '[vault_unreachable]' "$rotate_stderr"
osc_payload=$'\033]52;c;VEVSU0lPTg==\a'
assert_absent "OSC-52 byte sequence is removed" "$osc_payload" "$rotate_stderr"
if LC_ALL=C grep -q $'\033' "$rotate_stderr"; then
    echo "FAIL sanitized stderr contains ESC"
    failures=$((failures + 1))
else
    echo "ok   sanitized stderr contains no ESC"
fi
assert_contains "sanitized SSH diagnostic remains legible" 'Connection timed out]52;c;VEVSU0lPTg==' "$rotate_stderr"

# `bash -x` is a real inherited-trace path: the secret must not occur in the
# captured transcript even though the full success workflow executes.
reset_case
xtrace_rc=0
(
    export PATH="${fake_bin}:${PATH}"
    export ACX_OCI_PYTHON="${fake_bin}/fake-python"
    export ACX_LOCAL_OCI_BIN=oci ACX_REMOTE_OCI_BIN=oci
    export ACX_OCIR_TOKEN_SECRET=OCIR_AUTH_TOKEN ACX_OCIR_USERNAME_SECRET=OCIR_USERNAME
    export OCIR_TEST_PUT_LOG="$put_log" OCIR_TEST_DOCKER_LOG="$docker_log"
    export OCIR_TEST_DOCKER_COUNT="$docker_count" OCIR_TEST_SSH_LOG="$ssh_log"
    export OCIR_TEST_STORED_USERNAME="$known_user" OCIR_TEST_STORED_TOKEN="$known_token"
    printf '%s' "$known_token" | bash -x "$rotate_script" --stdin \
        --set-username "$known_user" --skip-verify
) >"$rotate_stdout" 2>"$rotate_stderr" || xtrace_rc=$?
assert_eq "wrapper succeeds under inherited xtrace" 0 "$xtrace_rc"
assert_absent "token is absent from inherited xtrace stderr" "$known_token" "$rotate_stderr"

# Help comes from bounded sentinels, so adding executable lines cannot leak code.
help_rc=0
bash "$rotate_script" --help >"$rotate_stdout" 2>"$rotate_stderr" || help_rc=$?
assert_eq "help exits zero" 0 "$help_rc"
assert_contains "help includes timeout option" '--readable-timeout SECONDS' "$rotate_stdout"
assert_contains "help explains safe skip scope" 'Skip production-VM SSH verification only' "$rotate_stdout"
assert_absent "help does not print Bash conditionals" 'if [' "$rotate_stdout"
assert_absent "help does not print executable exit" 'exit 2' "$rotate_stdout"

# Operational commands must describe deployed state, while the safer
# compartment scope remains explicitly marked as a future migration.
assert_contains "runbook runnable policy matches live tenancy scope" \
    'Allow dynamic-group acx-backend-dg to read secret-family in tenancy where request.permission' "$runbook_file"
assert_contains "runbook marks compartment policy as target state" \
    'applying this **target-state** policy' "$runbook_file"
assert_contains "runbook secret inventory uses the deployed pg-password name" \
    '(`pg-password`, `POSTGRES_DSN`' "$runbook_file"
assert_absent "runbook does not claim rotation touches no host" \
    'No host is touched' "$runbook_file"
assert_contains "runbook discloses production SSH contact" \
    'opens an SSH session to the production VM' "$runbook_file"

if [ "$failures" -ne 0 ]; then
    echo "${failures} assertion(s) failed"
    exit 1
fi
echo "all assertions passed"
