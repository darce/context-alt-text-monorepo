#!/usr/bin/env bash
# Characterization test for the Vault-backed OCIR credential path
# (scripts/deploy/lib/ocir-auth.sh, OCIRV-1).
#
# Two things are pinned here that cannot be re-checked cheaply at deploy time:
#   1. SECRECY -- the auth token must reach `docker login` only through
#      --password-stdin. If a refactor ever routes it through argv (ps-visible)
#      or a temp file, these assertions go red.
#   2. FAILURE CLASSIFICATION -- Release It! 5.5 wants system failure reported
#      differently from application failure. A Vault denial, a Vault timeout and
#      an OCIR rejection each need a different fix; the previous incident burned
#      a session on a 20-pair username matrix because they all looked alike.
#
# Run: bash scripts/deploy/tests/test-ocir-auth.sh

# R2-11: refuse non-bash before `set -o pipefail`. dash/sh reject pipefail
# with exit 2 and print no assertions, which a caller can misread as green.
if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash, not sh/dash. Example: bash $0" >&2
    exit 2
fi

set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
lib_file="${script_dir}/../lib/ocir-auth.sh"
if [ ! -f "$lib_file" ]; then
    echo "FAIL ocir-auth.sh missing: ${lib_file}"
    exit 1
fi
# shellcheck source=../lib/ocir-auth.sh
source "$lib_file"

failures=0

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        echo "ok   ${label}"
    else
        echo "FAIL ${label}: expected ${expected}, got ${actual}"
        failures=$((failures + 1))
    fi
}

assert_contains() {
    local label="$1" needle="$2" haystack="$3"
    case "$haystack" in
        *"$needle"*) echo "ok   ${label}" ;;
        *) echo "FAIL ${label}: missing '${needle}'"; failures=$((failures + 1)) ;;
    esac
}

assert_absent() {
    local label="$1" needle="$2" haystack="$3"
    case "$haystack" in
        *"$needle"*) echo "FAIL ${label}: unexpectedly present '${needle}'"; failures=$((failures + 1)) ;;
        *) echo "ok   ${label}" ;;
    esac
}

assert_file_bytes() {
    local label="$1" file="$2" expected="$3"
    if [ -f "$file" ] && cmp -s "$file" <(printf '%s' "$expected"); then
        echo "ok   ${label}"
    else
        echo "FAIL ${label}: file bytes differ or ${file} was not created"
        failures=$((failures + 1))
    fi
}

# --- fetch snippet shape -----------------------------------------------------

remote_fetch=$(ocir_vault_fetch_snippet '$HOME/.oci-venv/bin/oci' instance_principal OCIR_AUTH_TOKEN)

assert_contains "fetch uses get-secret-bundle-by-name (runbook s4 form)" \
    'secrets secret-bundle get-secret-bundle-by-name' "$remote_fetch"
assert_contains "fetch threads the acx-vault OCID" \
    "--vault-id ${ACX_VAULT_OCID}" "$remote_fetch"
assert_contains "fetch names the secret, not an OCID (stable across rotation)" \
    '--secret-name OCIR_AUTH_TOKEN' "$remote_fetch"
assert_contains "fetch base64-decodes the bundle content" \
    '| base64 -d' "$remote_fetch"
# The VM carries no credential file; instance principal is the whole point.
assert_contains "remote fetch uses instance_principal" \
    '--auth instance_principal' "$remote_fetch"

local_fetch=$(ocir_vault_fetch_snippet oci api_key OCIR_AUTH_TOKEN)
assert_contains "local fetch uses the operator API key" '--auth api_key' "$local_fetch"
assert_absent "local fetch does not claim instance principal" \
    'instance_principal' "$local_fetch"

# --- login snippet: secrecy invariants ---------------------------------------

login=$(ocir_login_snippet '$HOME/.oci-venv/bin/oci' instance_principal iad.ocir.io)

assert_contains "login reads the password from stdin" '--password-stdin' "$login"
assert_contains "login targets the requested registry" \
    'docker login iad.ocir.io' "$login"

# SECRECY: the token must never be captured into a variable, echoed, or written
# to a file -- only piped. `-p` would put it in argv, where any user on the host
# can read it out of ps.
# Matched on the whole login line, not the literal 'docker login -p': the
# registry argument sits between them, so a naive literal never fires. A
# mutant that piped the token through `xargs -I{} docker login ... -p {}`
# survived that weaker form.
login_cmd=$(printf '%s' "$login" | grep -F 'docker login')
assert_absent "token never passed via docker login -p" ' -p ' "$login_cmd"
assert_absent "token never passed via --password=" '--password=' "$login_cmd"
assert_absent "token never routed through xargs into argv" 'xargs' "$login_cmd"
assert_absent "token never redirected to a file" \
    'OCIR_AUTH_TOKEN --query' "$(printf '%s' "$login" | grep -F '>' | grep -v '>/dev/null' || true)"
assert_absent "token never assigned to a shell variable" \
    'acx_ocir_token=' "$login"
assert_absent "no cached docker config dependency remains" \
    '.docker/config.json' "$login"

# The username is not a secret, so a variable is fine -- but it must be quoted,
# or a namespace/email with shell-active characters would word-split.
assert_contains "username expansion is quoted" \
    '-u "${acx_ocir_user}"' "$login"

# The emitted text is executed by a remote bash -s; a syntax error there would
# surface as an opaque non-zero exit mid-deploy.
snippet_syntax=0
printf '%s' "$login" | bash -n 2>/dev/null || snippet_syntax=$?
assert_eq "emitted login snippet is syntactically valid bash" "0" "$snippet_syntax"

# `set -eu` (not just -e): an unset acx_ocir_user must abort rather than run
# `docker login -u ""` and produce a confusing OCIR rejection.
assert_contains "snippet aborts on unset vars" 'set -eu' "$login"

# Text inspection is useful for spotting familiar leaks, but it cannot prove
# the emitted program actually performs a login. Execute it with controlled
# stand-ins for every external command and observe the process boundary.
behavior_dir=$(mktemp -d "${TMPDIR:-/tmp}/ocir-auth-test.XXXXXX")
trap 'rm -rf "$behavior_dir"' EXIT
fake_bin="${behavior_dir}/bin"
mkdir "$fake_bin"

cat >"${fake_bin}/oci" <<'EOF'
#!/usr/bin/env bash
case " $* " in
    *" --secret-name OCIR_USERNAME "*) printf '%s' "$OCIR_TEST_USERNAME" | base64 ;;
    *" --secret-name OCIR_AUTH_TOKEN "*) printf '%s' "$OCIR_TEST_TOKEN" | base64 ;;
    *) echo "unexpected fake oci arguments" >&2; exit 64 ;;
esac
EOF
cat >"${fake_bin}/timeout" <<'EOF'
#!/usr/bin/env bash
shift
exec "$@"
EOF
cat >"${fake_bin}/docker" <<'EOF'
#!/usr/bin/env bash
: "${OCIR_TEST_DOCKER_ARGV:?}"
: "${OCIR_TEST_DOCKER_STDIN:?}"
printf '%s\0' "$@" >"$OCIR_TEST_DOCKER_ARGV"
cat >"$OCIR_TEST_DOCKER_STDIN"
EOF
chmod +x "${fake_bin}/oci" "${fake_bin}/timeout" "${fake_bin}/docker"

known_user='tenant/user@example.test'
known_token=$(printf '%s%s' 'token-with-shell-chars-' '$!*-[byte-exact]')
behavior_login=$(ocir_login_snippet oci instance_principal iad.ocir.io)
docker_argv="${behavior_dir}/docker.argv"
docker_stdin="${behavior_dir}/docker.stdin"
behavior_stderr="${behavior_dir}/snippet.stderr"
behavior_rc=0
PATH="${fake_bin}:${PATH}" \
OCIR_TEST_USERNAME="$known_user" \
OCIR_TEST_TOKEN="$known_token" \
OCIR_TEST_DOCKER_ARGV="$docker_argv" \
OCIR_TEST_DOCKER_STDIN="$docker_stdin" \
bash -c "$behavior_login" 2>"$behavior_stderr" || behavior_rc=$?
assert_eq "emitted login snippet executes successfully" "0" "$behavior_rc"

if [ -f "$docker_argv" ] && cmp -s "$docker_argv" \
    <(printf '%s\0' login iad.ocir.io -u "$known_user" --password-stdin); then
    echo "ok   docker receives exact login registry/user/password-stdin argv"
else
    echo "FAIL docker receives exact login registry/user/password-stdin argv"
    failures=$((failures + 1))
fi
assert_file_bytes "docker stdin equals the Vault token byte-for-byte" \
    "$docker_stdin" "$known_token"

if [ -f "$docker_argv" ] && \
    grep -aFq -f <(printf '%s\n' "$known_token") "$docker_argv"; then
    echo "FAIL token never appears in docker argv"
    failures=$((failures + 1))
else
    echo "ok   token never appears in docker argv"
fi

token_file_leaks=0
for artifact in "${behavior_dir}"/* "${fake_bin}"/*; do
    [ -f "$artifact" ] || continue
    [ "$artifact" = "$docker_stdin" ] && continue
    if grep -aFq -f <(printf '%s\n' "$known_token") "$artifact"; then
        echo "FAIL token leaked to file: ${artifact}"
        token_file_leaks=$((token_file_leaks + 1))
    fi
done
assert_eq "token appears in no file except docker stdin capture" \
    "0" "$token_file_leaks"

# Delete the assignment from the generated program so acx_ocir_user is truly
# unset at its point of use. Merely searching for `set -eu` would miss a later
# `set +u`, while this execution proves nounset remains effective.
unset_user_login=$(printf '%s' "$behavior_login" | sed '/^acx_ocir_user=/d')
unset_argv="${behavior_dir}/unset-docker.argv"
unset_stdin="${behavior_dir}/unset-docker.stdin"
unset_stderr="${behavior_dir}/unset.stderr"
unset_rc=0
(
    unset acx_ocir_user
    PATH="${fake_bin}:${PATH}" \
    OCIR_TEST_USERNAME="$known_user" \
    OCIR_TEST_TOKEN="$known_token" \
    OCIR_TEST_DOCKER_ARGV="$unset_argv" \
    OCIR_TEST_DOCKER_STDIN="$unset_stdin" \
    bash -c "$unset_user_login" 2>"$unset_stderr"
) || unset_rc=$?
if [ "$unset_rc" -ne 0 ]; then
    echo "ok   required unset variable makes emitted snippet fail"
else
    echo "FAIL required unset variable makes emitted snippet fail: exit 0"
    failures=$((failures + 1))
fi
if [ ! -e "$unset_argv" ] && [ ! -e "$unset_stdin" ]; then
    echo "ok   nounset aborts before docker is invoked"
else
    echo "FAIL nounset aborts before docker is invoked"
    failures=$((failures + 1))
fi

# Vault calls are bounded so a hung control-plane call cannot stall the deploy;
# `timeout` is absent on stock macOS, so it must degrade rather than hard-fail.
assert_contains "vault fetch is time-bounded" "timeout ${ACX_VAULT_FETCH_TIMEOUT}" "$login"
assert_contains "missing timeout(1) degrades instead of failing" \
    'command -v timeout' "$login"

# --- failure classification ---------------------------------------------------
# Inputs are real stderr fragments from the OCI CLI and the Docker daemon.

assert_eq "instance principal not in the dynamic group -> vault_denied" \
    vault_denied \
    "$(ocir_classify_login_failure 'ServiceError: {"status": 404, "code": "NotAuthorizedOrNotFound", "message": "Authorization failed or requested resource not found."}')"

assert_eq "expired/absent signer -> vault_denied" \
    vault_denied \
    "$(ocir_classify_login_failure 'NotAuthenticated: The required information to complete authentication was not provided.')"

assert_eq "control-plane timeout -> vault_unreachable" \
    vault_unreachable \
    "$(ocir_classify_login_failure 'HTTPSConnectionPool(host=secrets.vaults.us-ashburn-1.oci.oraclecloud.com): Read timed out. (read timeout=30)')"

assert_eq "revoked token -> ocir_rejected" \
    ocir_rejected \
    "$(ocir_classify_login_failure 'Error response from daemon: login attempt to https://iad.ocir.io/v2/ failed with status: 401 Unauthorized')"

assert_eq "oci-cli not installed -> oci_cli_missing" \
    oci_cli_missing \
    "$(ocir_classify_login_failure 'bash: line 2: /home/ubuntu/.oci-venv/bin/oci: No such file or directory')"

# OCI collapses 404 and 403 into one NotAuthorizedOrNotFound code, so the code
# alone cannot separate "the secret is missing" from "the grant is broken" --
# and those have opposite fixes. The snippet emits a sentinel once it has
# successfully read a secret from the vault; its presence is the disambiguator.
# Captured live from the VM before OCIR_AUTH_TOKEN existed.
VAULT_404='ServiceError:
{
    "code": "NotAuthorizedOrNotFound",
    "message": "Authorization failed or requested resource not found.",
    "operation_name": "get_secret_bundle_by_name",
    "status": 404
}'

assert_eq "denial after a successful vault read -> secret_missing" \
    secret_missing \
    "$(ocir_classify_login_failure "acx-vault-read-ok
${VAULT_404}")"

assert_eq "same denial with no prior read -> vault_denied" \
    vault_denied \
    "$(ocir_classify_login_failure "${VAULT_404}")"

assert_contains "secret_missing hint routes to storing a token, not to IAM" \
    'make ocir-token-rotate' "$(ocir_login_failure_hint secret_missing)"
assert_absent "secret_missing hint does not send the operator to audit policy" \
    'acx-backend-secret-read' "$(ocir_login_failure_hint secret_missing)"

assert_contains "login snippet emits the read-ok sentinel" \
    'acx-vault-read-ok' "$login"
# The sentinel must go to stderr: stdout is the token pipe into docker login.
assert_contains "sentinel goes to stderr, not into the token pipe" \
    "printf 'acx-vault-read-ok\\n' >&2" "$login"

assert_eq "unrecognised stderr -> unknown" \
    unknown \
    "$(ocir_classify_login_failure 'docker: Cannot connect to the Docker daemon at unix:///var/run/docker.sock.')"

# TEST-15: the classifier is ordered, and the order is load-bearing. A missing
# binary message can also contain "not found"; if oci_cli_missing ever stops
# winning, the operator is sent to check IAM policy for a pip problem.
assert_eq "missing-binary wins over any later pattern" \
    oci_cli_missing \
    "$(ocir_classify_login_failure 'oci: command not found -- 401 Unauthorized NotAuthorizedOrNotFound')"

# --- remediation hints --------------------------------------------------------
# Each class must route somewhere different; identical hints would erase the
# whole point of classifying.

hint_denied=$(ocir_login_failure_hint vault_denied)
hint_unreach=$(ocir_login_failure_hint vault_unreachable)
hint_rejected=$(ocir_login_failure_hint ocir_rejected)
hint_missing=$(ocir_login_failure_hint oci_cli_missing)

assert_contains "vault_denied hint names the dynamic group" \
    'acx-backend-dg' "$hint_denied"
assert_contains "vault_denied hint names the policy" \
    'acx-backend-secret-read' "$hint_denied"
assert_contains "unreachable hint says it is transient" 'retry' "$hint_unreach"
assert_contains "ocir_rejected hint routes to rotation" \
    'make ocir-token-rotate' "$hint_rejected"
assert_contains "oci_cli_missing hint gives the install line" \
    '.oci-venv' "$hint_missing"

# RLSE-11 / Release It! 5.4: the Console click-path is the failure mode this
# work removed. Exactly one hint may mention it -- the one case where Oracle has
# no API that returns the token. Any other Console reference is a regression
# back to crank-turning.
console_hints=0
for class in vault_denied vault_unreachable ocir_rejected oci_cli_missing secret_missing unknown; do
    case "$(ocir_login_failure_hint "$class")" in
        *Console*) console_hints=$((console_hints + 1)) ;;
    esac
done
assert_eq "only the revoked-token hint sends a human to the Console" "1" "$console_hints"

echo
if [ "$failures" -gt 0 ]; then
    echo "${failures} assertion(s) failed"
    exit 1
fi
echo "all assertions passed"
