#!/usr/bin/env bash
# Executable contract tests for scripts/deploy/lib/ocir-auth.sh (OCIRV-1).

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash, not sh/dash. Example: bash $0" >&2
    exit 2
fi

set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
lib_file="${script_dir}/../lib/ocir-auth.sh"
unset ACX_VAULT_OCID ACX_OCIR_TOKEN_SECRET ACX_OCIR_USERNAME_SECRET ACX_OCIR_GENERATION_SECRET
unset ACX_REMOTE_OCI_BIN ACX_LOCAL_OCI_BIN ACX_VAULT_FETCH_TIMEOUT
# shellcheck source=../lib/ocir-auth.sh
source "$lib_file"

failures=0

pass() { echo "ok   $1"; }
fail() { echo "FAIL $1"; failures=$((failures + 1)); }

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then pass "$label"; else
        fail "${label}: expected ${expected}, got ${actual}"
    fi
}

assert_contains() {
    local label="$1" needle="$2" haystack="$3"
    case "$haystack" in *"$needle"*) pass "$label" ;; *) fail "${label}: missing '${needle}'" ;; esac
}

assert_absent() {
    local label="$1" needle="$2" haystack="$3"
    case "$haystack" in *"$needle"*) fail "${label}: unexpectedly present '${needle}'" ;; *) pass "$label" ;; esac
}

assert_nonzero() {
    local label="$1" actual="$2"
    if [ "$actual" -ne 0 ]; then pass "$label"; else fail "${label}: unexpectedly exited 0"; fi
}

behavior_dir=$(mktemp -d "${TMPDIR:-/tmp}/ocir-auth-test.XXXXXX")
trap 'rm -rf "$behavior_dir"' EXIT
fake_bin="${behavior_dir}/bin"
portable_bin="${behavior_dir}/portable-bin"
record_dir="${behavior_dir}/records"
test_home="${behavior_dir}/home"
test_tmp="${behavior_dir}/tmp"
mkdir -p "$fake_bin" "$portable_bin" "$record_dir" "$test_home" "$test_tmp"

cat >"${fake_bin}/oci" <<'EOF'
#!/bin/bash
set -eu
case "${OCIR_TEST_OCI_MODE:-ok}" in
    fail) echo 'ServiceError: forced OCI failure' >&2; exit 42 ;;
    empty) exit 0 ;;
    sleep) exec sleep 10 ;;
    generation_absent)
        case " $* " in
            *" --secret-name OCIR_CREDENTIAL_GENERATION "*)
                echo 'ServiceError: NotAuthorizedOrNotFound' >&2
                exit 1
                ;;
        esac
        ;;
    generation_invalid)
        case " $* " in
            *" --secret-name OCIR_CREDENTIAL_GENERATION "*)
                printf '%s' 'unexpected-generation' | base64
                exit 0
                ;;
        esac
        ;;
    generation_timeout)
        case " $* " in
            *" --secret-name OCIR_CREDENTIAL_GENERATION "*) exec sleep 10 ;;
        esac
        ;;
esac
case " $* " in
    *" --secret-name OCIR_CREDENTIAL_GENERATION "*)
        generation=STABLE:test-generation
        if [ "${OCIR_TEST_OCI_MODE:-}" = generation_change ]; then
            generation_file="${OCIR_TEST_RECORD_DIR}/generation.count"
            generation_count=0
            [ ! -f "$generation_file" ] || generation_count=$(cat "$generation_file")
            generation_count=$((generation_count + 1))
            printf '%s' "$generation_count" >"$generation_file"
            generation="STABLE:generation-${generation_count}"
        fi
        printf '%s' "$generation" | base64
        ;;
    *" --secret-name OCIR_USERNAME "*) printf '%s' 'tenant/user@example.test' | base64 ;;
    *) printf '%s%s' 'token-with-shell-chars-' '$!*-[byte-exact]' | base64 ;;
esac
EOF

cat >"${fake_bin}/docker" <<'EOF'
#!/bin/bash
set -eu
: "${OCIR_TEST_RECORD_DIR:?}"
printf '%s\0' "$@" >"${OCIR_TEST_RECORD_DIR}/docker.argv"
env >"${OCIR_TEST_RECORD_DIR}/docker.env"

# Inventory files visible before stdin is consumed. A mutant that stages the
# token in a file is caught by its checksum even if it deletes the file later.
: >"${OCIR_TEST_RECORD_DIR}/visible-files.cksum"
find "${HOME}" "${TMPDIR}" -type f 2>/dev/null | while IFS= read -r file; do
    [ "$file" = "${OCIR_TEST_RECORD_DIR}/visible-files.cksum" ] && continue
    cksum "$file" >>"${OCIR_TEST_RECORD_DIR}/visible-files.cksum" 2>/dev/null || true
done

case "${OCIR_TEST_DOCKER_MODE:-ok}" in
    sleep) exec sleep 10 ;;
esac

# Emulate Docker persisting auth in its configured credential directory. The
# generated snippet must remove this even when login reports failure.
mkdir -p "$DOCKER_CONFIG"
token=$(cat)
printf '{"auths":{"test":{"auth":"%s"}}}' "$token" >"${DOCKER_CONFIG}/config.json"
printf '%s' "$token" | cksum >"${OCIR_TEST_RECORD_DIR}/docker.stdin.cksum"
if [ "${OCIR_TEST_DOCKER_MODE:-ok}" = fail ]; then
    printf 'debug credential=%s; unauthorized\n' "$token" >&2
    unset token
    exit 41
fi
unset token
EOF
chmod +x "${fake_bin}/oci" "${fake_bin}/docker"

# Build a PATH with exactly the commands the generated program and fakes need.
# In particular, it deliberately has no timeout(1).
for utility in awk base64 cat cksum env find mkdir mktemp rm sleep; do
    utility_path=$(command -v "$utility")
    ln -s "$utility_path" "${portable_bin}/${utility}"
done
ln -s "${fake_bin}/oci" "${portable_bin}/oci"
ln -s "${fake_bin}/docker" "${portable_bin}/docker"

known_user='tenant/user@example.test'
known_token=$(printf '%s%s' 'token-with-shell-chars-' '$!*-[byte-exact]')

reset_records() {
    find "$record_dir" -mindepth 1 -maxdepth 1 -type f -delete
}

run_snippet() {
    local transport="$1" snippet="$2" stderr_file="$3" trace_file="$4"
    local rc=0
    if [ "$transport" = c ]; then
        HOME="$test_home" TMPDIR="$test_tmp" \
        PATH="${fake_bin}:${PATH}" OCIR_TEST_RECORD_DIR="$record_dir" \
        BASH_XTRACEFD=4 /bin/bash -x -c "$snippet" \
            4>"$trace_file" 2>"$stderr_file" || rc=$?
    else
        HOME="$test_home" TMPDIR="$test_tmp" \
        PATH="${fake_bin}:${PATH}" OCIR_TEST_RECORD_DIR="$record_dir" \
        BASH_XTRACEFD=4 /bin/bash -x -s \
            4>"$trace_file" 2>"$stderr_file" <<<"$snippet" || rc=$?
    fi
    return "$rc"
}

# --- generated program structure --------------------------------------------

login=$(ocir_login_snippet '$HOME/.oci-venv/bin/oci' instance_principal iad.ocir.io)
behavior_login=$(ocir_login_snippet oci api_key iad.ocir.io)
assert_contains "snippet enables pipeline failure propagation" 'set -euo pipefail' "$login"
assert_contains "snippet uses a private Docker credential directory" 'export DOCKER_CONFIG="$ACX_OCIR_DOCKER_CONFIG"' "$login"
assert_contains "private Docker config has an EXIT cleanup" 'trap acx_cleanup EXIT' "$login"
assert_contains "snippet accepts a caller-owned Docker config" 'ACX_OCIR_DOCKER_CONFIG_DIR=' "$login"
assert_contains "username is a quoted data reference" '--secret-name "$ACX_OCIR_SECRET_NAME"' "$login"
assert_contains "registry is a quoted data reference" 'login "$ACX_OCIR_REGISTRY"' "$login"
assert_contains "username expansion is quoted" '-u "$acx_ocir_user"' "$login"
assert_contains "password reaches Docker on stdin" '--password-stdin' "$login"
assert_contains "consumer checks a shared credential generation" 'acx_ocir_generation_before' "$login"
assert_contains "OCI calls use the portable watchdog" 'acx_bounded vault "$ACX_OCIR_OCI_BIN"' "$login"
assert_contains "Docker login uses the portable watchdog" 'acx_bounded ocir docker login' "$login"
assert_absent "snippet does not silently depend on timeout(1)" 'command -v timeout' "$login"

snippet_syntax=0
printf '%s' "$login" | /bin/bash -n 2>/dev/null || snippet_syntax=$?
assert_eq "emitted login snippet is valid Bash" 0 "$snippet_syntax"

# --- credential confinement and cleanup -------------------------------------

for docker_mode in ok fail; do
    reset_records
    stderr_file="${record_dir}/${docker_mode}.stderr"
    trace_file="${record_dir}/${docker_mode}.trace"
    behavior_rc=0
    OCIR_TEST_DOCKER_MODE="$docker_mode" run_snippet c "$behavior_login" "$stderr_file" "$trace_file" || behavior_rc=$?
    if [ "$docker_mode" = ok ]; then
        if [ "$behavior_rc" -eq 0 ]; then
            pass "${docker_mode}: generated login succeeds"
        else
            fail "${docker_mode}: generated login exited ${behavior_rc}: $(tr '\n' ' ' <"$stderr_file")"
        fi
    else
        assert_nonzero "${docker_mode}: generated login preserves Docker failure" "$behavior_rc"
    fi

    expected_argv="${record_dir}/expected.argv"
    printf '%s\0' login iad.ocir.io -u "$known_user" --password-stdin >"$expected_argv"
    if cmp -s "${record_dir}/docker.argv" "$expected_argv"; then
        pass "${docker_mode}: Docker receives exact non-secret argv"
    else
        fail "${docker_mode}: Docker argv differs"
    fi

    expected_cksum=$(printf '%s' "$known_token" | cksum)
    actual_cksum=missing
    [ ! -f "${record_dir}/docker.stdin.cksum" ] || actual_cksum=$(cat "${record_dir}/docker.stdin.cksum")
    assert_eq "${docker_mode}: Docker stdin is the exact token" "$expected_cksum" "$actual_cksum"

    if grep -aFq "$known_token" "${record_dir}/docker.argv" "${record_dir}/docker.env" "$trace_file" 2>/dev/null; then
        fail "${docker_mode}: token leaked into argv, environment, or shell trace"
    else
        pass "${docker_mode}: token absent from argv, environment, and shell trace"
    fi

    if grep -Fq "${expected_cksum%% *}" "${record_dir}/visible-files.cksum" 2>/dev/null; then
        fail "${docker_mode}: token existed in a file visible to Docker before stdin"
    else
        pass "${docker_mode}: token was not staged in a file"
    fi

    docker_config=$(sed -n 's/^DOCKER_CONFIG=//p' "${record_dir}/docker.env" 2>/dev/null || true)
    case "$docker_config" in
        "${test_tmp}"/acx-ocir-docker.*) pass "${docker_mode}: Docker uses the private config" ;;
        *) fail "${docker_mode}: unexpected DOCKER_CONFIG ${docker_config}" ;;
    esac
    if [ ! -e "$docker_config" ]; then
        pass "${docker_mode}: private Docker config removed on exit"
    else
        fail "${docker_mode}: private Docker config survived exit"
    fi
    if [ ! -e "${test_home}/.docker/config.json" ]; then
        pass "${docker_mode}: host Docker config was never created"
    else
        fail "${docker_mode}: host Docker config was created"
    fi
    remaining_leak=$(grep -R -a -l -F "$known_token" "$test_home" "$test_tmp" "$record_dir" 2>/dev/null || true)
    if [ -z "$remaining_leak" ]; then
        pass "${docker_mode}: no surviving file contains the token"
    else
        fail "${docker_mode}: token survived in ${remaining_leak}"
    fi
done

reset_records
generation_rc=0
OCIR_TEST_OCI_MODE=generation_change run_snippet c "$behavior_login" \
    "${record_dir}/generation.stderr" "${record_dir}/generation.trace" || generation_rc=$?
assert_eq "mixed credential generation is rejected before Docker" 76 "$generation_rc"
if [ ! -e "${record_dir}/docker.argv" ]; then
    pass "mixed credential generation never reaches Docker"
else
    fail "mixed credential generation reached Docker"
fi

reset_records
legacy_rc=0
OCIR_TEST_OCI_MODE=generation_absent run_snippet c "$behavior_login" \
    "${record_dir}/legacy.stderr" "${record_dir}/legacy.trace" || legacy_rc=$?
assert_eq "absent credential generation uses the legacy login path" 0 "$legacy_rc"
assert_contains "legacy path emits its mode diagnostic" \
    'acx-credential-generation:absent-legacy' "$(cat "${record_dir}/legacy.stderr")"
if [ -e "${record_dir}/docker.argv" ]; then
    pass "absent credential generation reaches Docker"
else
    fail "absent credential generation did not reach Docker"
fi

reset_records
invalid_rc=0
OCIR_TEST_OCI_MODE=generation_invalid run_snippet c "$behavior_login" \
    "${record_dir}/generation-invalid.stderr" "${record_dir}/generation-invalid.trace" || invalid_rc=$?
assert_eq "present but unparseable generation is rejected" 76 "$invalid_rc"
assert_contains "unparseable generation has a dedicated diagnostic" \
    'acx-credential-generation:invalid' "$(cat "${record_dir}/generation-invalid.stderr")"
if [ ! -e "${record_dir}/docker.argv" ]; then
    pass "unparseable generation never reaches Docker"
else
    fail "unparseable generation reached Docker"
fi

generation_timeout_login=$(ACX_VAULT_FETCH_TIMEOUT=1 ocir_login_snippet oci api_key iad.ocir.io)
reset_records
generation_timeout_rc=0
OCIR_TEST_OCI_MODE=generation_timeout run_snippet c "$generation_timeout_login" \
    "${record_dir}/generation-timeout.stderr" "${record_dir}/generation-timeout.trace" || generation_timeout_rc=$?
assert_eq "generation fetch timeout fails closed" 124 "$generation_timeout_rc"
assert_contains "generation timeout emits the Vault timeout marker" \
    'acx-timeout:vault' "$(cat "${record_dir}/generation-timeout.stderr")"
assert_absent "generation timeout does not select legacy mode" \
    'acx-credential-generation:absent-legacy' "$(cat "${record_dir}/generation-timeout.stderr")"
if [ ! -e "${record_dir}/docker.argv" ]; then
    pass "generation timeout never reaches Docker"
else
    fail "generation timeout reached Docker"
fi

# --- failed and empty Vault reads -------------------------------------------

for oci_mode in fail empty; do
    reset_records
    stderr_file="${record_dir}/vault-${oci_mode}.stderr"
    trace_file="${record_dir}/vault-${oci_mode}.trace"
    vault_rc=0
    OCIR_TEST_OCI_MODE="$oci_mode" run_snippet c "$behavior_login" "$stderr_file" "$trace_file" || vault_rc=$?
    assert_nonzero "${oci_mode} Vault read fails the snippet" "$vault_rc"
    assert_absent "${oci_mode} Vault read emits no read-ok sentinel" \
        'acx-vault-read-ok' "$(cat "$stderr_file")"
    if [ ! -e "${record_dir}/docker.argv" ]; then
        pass "${oci_mode} Vault read aborts before Docker"
    else
        fail "${oci_mode} Vault read invoked Docker"
    fi
done

# --- injection resistance on both transports -------------------------------

injection_case() {
    local variable="$1" transport="$2"
    local marker="${behavior_dir}/injected-${variable}-${transport}"
    local payload='$(touch '"$marker"')'
    local bin=oci auth=api_key registry=iad.ocir.io snippet rc=0

    ACX_VAULT_OCID='ocid1.vault.test'
    ACX_OCIR_USERNAME_SECRET=OCIR_USERNAME
    ACX_OCIR_TOKEN_SECRET=OCIR_AUTH_TOKEN
    ACX_VAULT_FETCH_TIMEOUT=2
    case "$variable" in
        ACX_LOCAL_OCI_BIN) bin="$payload" ;;
        ACX_REMOTE_OCI_BIN) bin="$payload" ;;
        ACX_OCIR_USERNAME_SECRET) ACX_OCIR_USERNAME_SECRET="$payload" ;;
        ACX_OCIR_TOKEN_SECRET) ACX_OCIR_TOKEN_SECRET="$payload" ;;
        ACX_VAULT_FETCH_TIMEOUT) ACX_VAULT_FETCH_TIMEOUT="$payload" ;;
        ACX_VAULT_OCID) ACX_VAULT_OCID="$payload" ;;
        OCIR_REGISTRY) registry="$payload" ;;
    esac

    if snippet=$(ocir_login_snippet "$bin" "$auth" "$registry" 2>"${record_dir}/inject-generate.stderr"); then
        reset_records
        run_snippet "$transport" "$snippet" "${record_dir}/inject.stderr" "${record_dir}/inject.trace" || rc=$?
    else
        rc=$?
    fi
    [ "$rc" -ge 0 ] # execution result is irrelevant; only code execution matters.
    if [ ! -e "$marker" ]; then
        pass "${variable} substitution is inert via bash -${transport}"
    else
        fail "${variable} executed via bash -${transport}"
    fi
}

for variable in ACX_LOCAL_OCI_BIN ACX_REMOTE_OCI_BIN ACX_OCIR_USERNAME_SECRET \
    ACX_OCIR_TOKEN_SECRET ACX_VAULT_FETCH_TIMEOUT ACX_VAULT_OCID OCIR_REGISTRY; do
    injection_case "$variable" c
    injection_case "$variable" s
done

for invalid_timeout in 0 00 abc; do
    ACX_VAULT_FETCH_TIMEOUT="$invalid_timeout"
    invalid_stderr="${record_dir}/timeout-${invalid_timeout}.stderr"
    invalid_rc=0
    ocir_login_snippet oci api_key iad.ocir.io >"${record_dir}/invalid.snippet" 2>"$invalid_stderr" || invalid_rc=$?
    assert_nonzero "timeout ${invalid_timeout} is rejected" "$invalid_rc"
    assert_contains "timeout ${invalid_timeout} has a clear diagnostic" \
        'must be a positive integer' "$(cat "$invalid_stderr")"
done
ACX_VAULT_FETCH_TIMEOUT=30

# --- portable deadlines without timeout(1) ----------------------------------

deadline_login=$(ACX_VAULT_FETCH_TIMEOUT=1 ocir_login_snippet oci api_key iad.ocir.io)
if [ ! -e "${portable_bin}/timeout" ]; then pass "timeout(1) is absent from watchdog PATH"; else fail "portable PATH contains timeout"; fi

reset_records
vault_timeout_stderr="${record_dir}/vault-timeout.stderr"
vault_started=$SECONDS
vault_timeout_rc=0
HOME="$test_home" TMPDIR="$test_tmp" PATH="$portable_bin" \
OCIR_TEST_RECORD_DIR="$record_dir" OCIR_TEST_OCI_MODE=sleep \
/bin/bash -c "$deadline_login" 2>"$vault_timeout_stderr" || vault_timeout_rc=$?
vault_elapsed=$((SECONDS - vault_started))
assert_nonzero "sleeping OCI is killed without timeout(1)" "$vault_timeout_rc"
if [ "$vault_elapsed" -lt 4 ]; then pass "sleeping OCI respects the one-second deadline"; else fail "sleeping OCI ran ${vault_elapsed}s"; fi
vault_timeout_output=$(cat "$vault_timeout_stderr")
assert_eq "OCI watchdog failure is Vault-classified" vault_unreachable \
    "$(ocir_classify_login_failure "$vault_timeout_output")"

reset_records
docker_timeout_stderr="${record_dir}/docker-timeout.stderr"
docker_started=$SECONDS
docker_timeout_rc=0
HOME="$test_home" TMPDIR="$test_tmp" PATH="$portable_bin" \
OCIR_TEST_RECORD_DIR="$record_dir" OCIR_TEST_DOCKER_MODE=sleep \
/bin/bash -c "$deadline_login" 2>"$docker_timeout_stderr" || docker_timeout_rc=$?
docker_elapsed=$((SECONDS - docker_started))
assert_eq "sleeping Docker returns the watchdog timeout status" 124 "$docker_timeout_rc"
if [ "$docker_elapsed" -lt 4 ]; then pass "sleeping Docker respects the one-second deadline"; else fail "sleeping Docker ran ${docker_elapsed}s"; fi
docker_timeout_output=$(cat "$docker_timeout_stderr")
assert_contains "Docker watchdog emits the OCIR timeout marker" \
    'acx-timeout:ocir' "$docker_timeout_output"
assert_eq "Docker watchdog failure is OCIR-classified" ocir_unreachable \
    "$(ocir_classify_login_failure "$docker_timeout_output")"

# --- table-driven classifier and hint contract ------------------------------

while IFS='|' read -r label expected probe; do
    [ -n "$label" ] || continue
    assert_eq "$label" "$expected" "$(ocir_classify_login_failure "$probe")"
done <<'EOF'
missing OCI executable names OCI|oci_cli_missing|bash: line 2: /home/ubuntu/.oci-venv/bin/oci: No such file or directory
missing Docker executable names Docker|docker_cli_missing|bash: line 5: docker: command not found
ssh path failure names SSH|ssh_failed|ssh: connect to host vm: No such file or directory
ambiguous first username read failure|vault_denied|ServiceError: {"status": 404, "code": "NotAuthorizedOrNotFound", "message": "Authorization failed or requested resource not found."}
explicit Vault access denial|vault_denied|ServiceError: {"status": 403, "code": "NotAuthorized", "message": "not authorized"}
invalid Vault request is terminal|vault_request_failed|ServiceError: {"status": 400, "code": "InvalidParameter"}
conflicting Vault request is terminal|vault_request_failed|ServiceError: {"status": 409, "code": "Conflict"}
Vault throttling is transient|vault_unreachable|ServiceError: {"status": 429, "code": "TooManyRequests"}
Vault server error is transient|vault_unreachable|ServiceError: {"status": 503, "code": "InternalError"}
Vault read timeout is transient|vault_unreachable|HTTPSConnectionPool(host=secrets.vaults.us-ashburn-1.oci.oraclecloud.com): Read timed out. (read timeout=30)
OCIR rejection names registry auth|ocir_rejected|Error response from daemon: login attempt to https://iad.ocir.io/v2/ failed with status: 401 Unauthorized
unrecognized daemon error stays unknown|unknown|docker: Cannot connect to the Docker daemon at unix:///var/run/docker.sock.
EOF

assert_eq "missing token after successful username read" secret_missing \
    "$(ocir_classify_login_failure $'acx-vault-read-ok\nServiceError: {"status": 404, "code": "NotAuthorizedOrNotFound"}')"
assert_eq "mixed generation has a dedicated classification" credential_inconsistent \
    "$(ocir_classify_login_failure 'acx-credential-generation:changed')"

leaked_token='diagnostic-leak-SUPER-SECRET'
safe_diagnostic=$(ocir_safe_login_diagnostic "Error 401 credential=${leaked_token}")
assert_absent "safe login diagnostic never replays credential-bearing stderr" \
    "$leaked_token" "$safe_diagnostic"
assert_contains "safe login diagnostic preserves failure class" \
    'ocir_rejected' "$safe_diagnostic"

assert_contains "Docker-missing hint names Docker" 'Docker CLI' \
    "$(ocir_login_failure_hint docker_cli_missing)"
assert_absent "Docker-missing hint does not prescribe oci-cli" 'oci-cli' \
    "$(ocir_login_failure_hint docker_cli_missing)"
assert_contains "terminal Vault hint says not to retry unchanged" 'non-transient' \
    "$(ocir_login_failure_hint vault_request_failed)"
assert_contains "transient Vault hint recommends retry" 'retry' \
    "$(ocir_login_failure_hint vault_unreachable)"
assert_contains "missing-secret hint includes username" 'OCIR_USERNAME' \
    "$(ocir_login_failure_hint secret_missing)"
assert_contains "confirmed missing-secret hint prescribes rotation" 'make ocir-token-rotate' \
    "$(ocir_login_failure_hint secret_missing)"
assert_contains "denial hint names IAM policy" 'acx-backend-secret-read' \
    "$(ocir_login_failure_hint vault_denied)"
assert_contains "ambiguous first-read hint names missing secrets" 'may be missing' \
    "$(ocir_login_failure_hint vault_denied)"
assert_contains "ambiguous first-read hint names the IAM grant" 'SECRET_BUNDLE_READ' \
    "$(ocir_login_failure_hint vault_denied)"
assert_absent "ambiguous first-read hint does not prescribe rotation" 'make ocir-token-rotate' \
    "$(ocir_login_failure_hint vault_denied)"

console_hints=0
for class in oci_cli_missing docker_cli_missing secret_missing vault_denied \
    vault_unreachable vault_request_failed ocir_unreachable ocir_rejected ssh_failed unknown; do
    case "$(ocir_login_failure_hint "$class")" in *Console*) console_hints=$((console_hints + 1)) ;; esac
done
assert_eq "only revoked-token remediation requires the Console" 1 "$console_hints"

echo
if [ "$failures" -gt 0 ]; then
    echo "${failures} assertion(s) failed"
    exit 1
fi
echo "all assertions passed"
