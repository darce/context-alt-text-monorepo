#!/usr/bin/env bash
# Land an OCI auth token in acx-vault and verify it against OCIR (OCIRV-1).
#
# This is the *whole* human procedure now. Oracle has no API that returns an
# auth token's secret -- `CreateAuthToken` returns it once, and the Python SDK's
# MyAuthToken model omits the field entirely -- so a human minting the token in
# the Console is irreducible. Everything downstream of that click is not: the
# token goes into the vault once, and every host reads it from there.
#
# Release It! 5.4 (Steady State): the previous procedure required a human to
# paste the token into `docker login` on each host, with no record of which
# hosts held which token and no way to tell a revoked credential from a
# misconfigured one. That is the crank-turning this replaces.
#
# BEGIN USAGE
# Usage (interactive -- never echoed or in argv; Docker uses an auto-removed
# temporary config for the direct authentication proof):
#     scripts/deploy/ocir-token-rotate.sh [--readable-timeout SECONDS]
#
# Usage (piped, for a password manager):
#     pbpaste | scripts/deploy/ocir-token-rotate.sh --stdin
#
# Bootstrap only: seed the docker username after the proven token is stored.
#     scripts/deploy/ocir-token-rotate.sh --set-username '<namespace>/<email>'
#
# Options:
#     --readable-timeout SECONDS  Consumer read-back deadline (0 skips the wait)
#     --skip-verify              Skip production-VM SSH verification only
#     -h, --help                 Show this help
# END USAGE

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash. Example: bash $0" >&2
    exit 2
fi

set -euo pipefail
# A caller may have enabled tracing with `bash -x` or SHELLOPTS. Token handling
# is deliberately never traced and tracing is not restored later in the flow.
set +x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/ocir-auth.sh
source "${SCRIPT_DIR}/lib/ocir-auth.sh"

OCIR_REGISTRY="${OCIR_REGISTRY:-iad.ocir.io}"
OCI_HOST="${OCI_HOST:-acx-backend.tail1a44b8.ts.net}"
OCI_USER="${OCI_USER:-ubuntu}"

FROM_STDIN=0
SET_USERNAME=""
SKIP_VERIFY=0
READABLE_TIMEOUT=120
while [ $# -gt 0 ]; do
    case "$1" in
        --stdin) FROM_STDIN=1 ;;
        --set-username)
            if [ $# -lt 2 ]; then
                echo "--set-username needs a value" >&2
                exit 2
            fi
            SET_USERNAME="$2"
            shift
            ;;
        --readable-timeout)
            if [ $# -lt 2 ]; then
                echo "--readable-timeout needs a non-negative number" >&2
                exit 2
            fi
            READABLE_TIMEOUT="$2"
            case "$READABLE_TIMEOUT" in
                ''|*[!0-9.]*|*.*.*)
                    echo "invalid --readable-timeout: ${READABLE_TIMEOUT} (expected a non-negative number)" >&2
                    exit 2
                    ;;
            esac
            case "$READABLE_TIMEOUT" in
                *[0-9]*) ;;
                *)
                    echo "invalid --readable-timeout: ${READABLE_TIMEOUT} (expected a non-negative number)" >&2
                    exit 2
                    ;;
            esac
            shift
            ;;
        --skip-verify) SKIP_VERIFY=1 ;;
        -h|--help)
            awk '/^# BEGIN USAGE$/{show=1; next} /^# END USAGE$/{exit} show{sub(/^# ?/, ""); print}' "$0"
            exit 0
            ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

# Rotation owns exactly these two Vault records. In particular, do not turn an
# inherited deploy override into authority to overwrite an unrelated secret.
if [ "$ACX_OCIR_TOKEN_SECRET" != "OCIR_AUTH_TOKEN" ]; then
    echo "refusing unowned token secret name: ${ACX_OCIR_TOKEN_SECRET}" >&2
    exit 2
fi
if [ "$ACX_OCIR_USERNAME_SECRET" != "OCIR_USERNAME" ]; then
    echo "refusing unowned username secret name: ${ACX_OCIR_USERNAME_SECRET}" >&2
    exit 2
fi

# The OCI CLI ships its own interpreter with the SDK already installed; using it
# avoids requiring `pip install oci` in whatever python3 happens to be on PATH.
oci_bin="$(command -v oci || true)"
if [ -z "$oci_bin" ]; then
    echo "oci CLI not found in PATH. brew install oci-cli" >&2
    exit 1
fi
OCI_PYTHON="${ACX_OCI_PYTHON:-$(head -1 "$oci_bin" | sed 's|^#!||')}"
if ! "$OCI_PYTHON" -c 'import oci' 2>/dev/null; then
    echo "no OCI SDK in ${OCI_PYTHON}; set ACX_OCI_PYTHON to an interpreter that has it" >&2
    exit 1
fi

sanitize_stderr() {
    # Preserve ordinary text plus tab/newline while dropping terminal-active
    # C0/C1 bytes (including ESC, BEL, OSC introducers and DEL).
    LC_ALL=C tr -d '\000-\010\013\014\016-\037\177-\237'
}

report_login_failure() {
    local scope="$1" captured="$2" class
    class="$(ocir_classify_login_failure "$captured")"
    echo "FAIL ${scope} [${class}]: $(ocir_login_failure_hint "$class")" >&2
    printf '%s\n' "$captured" | sanitize_stderr >&2
}

# Run one local command with an explicit positive-integer outer deadline. Keep
# the child PID visible to cleanup so an interrupt cannot leave a network
# process behind.
active_pid=""
run_bounded_for() {
    local label="$1" timeout_seconds="$2" started rc
    shift 2
    exec 3<&0
    "$@" <&3 &
    active_pid=$!
    exec 3<&-
    started=$SECONDS
    while kill -0 "$active_pid" 2>/dev/null; do
        if [ $((SECONDS - started)) -ge "$timeout_seconds" ]; then
            kill "$active_pid" 2>/dev/null || true
            sleep 0.1
            kill -9 "$active_pid" 2>/dev/null || true
            wait "$active_pid" 2>/dev/null || true
            active_pid=""
            printf 'acx-timeout:%s after %ss\n' "$label" "$timeout_seconds" >&2
            return 124
        fi
        sleep 0.05
    done
    if wait "$active_pid"; then rc=0; else rc=$?; fi
    active_pid=""
    if [ "$rc" -eq 127 ]; then
        printf 'acx-command-missing:%s\n' "$label" >&2
    fi
    return "$rc"
}

run_bounded() {
    local label="$1"
    shift
    run_bounded_for "$label" "$ACX_VAULT_FETCH_TIMEOUT" "$@"
}

cleanup() {
    if [ -n "${active_pid:-}" ]; then
        kill "$active_pid" 2>/dev/null || true
        wait "$active_pid" 2>/dev/null || true
    fi
    if [ -n "${runtime_dir:-}" ]; then
        rm -rf -- "$runtime_dir"
    fi
}

ocir_validate_fetch_timeout || exit $?
# The helper gives discovery/mutation an additional Vault-call budget beyond
# the requested consumer propagation window. Round a decimal readiness window
# up because the Bash watchdog uses integer seconds.
readable_whole="${READABLE_TIMEOUT%%.*}"
if [ -z "$readable_whole" ]; then readable_whole=0; fi
readable_fraction=""
case "$READABLE_TIMEOUT" in
    *.*) readable_fraction="${READABLE_TIMEOUT#*.}" ;;
esac
if [ -n "$readable_fraction" ]; then readable_whole=$((readable_whole + 1)); fi
operation_timeout=$((ACX_VAULT_FETCH_TIMEOUT + readable_whole))
umask 077
runtime_dir="$(mktemp -d "${TMPDIR:-/tmp}/acx-ocir-rotate.XXXXXX")"
proof_docker_config="${runtime_dir}/docker"
mkdir "$proof_docker_config"
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

put_secret() {
    # $1 = allowlisted secret name. Value arrives on stdin and goes no further
    # than the helper's memory.
    echo "writing vault ${ACX_VAULT_OCID} secret $1" >&2
    run_bounded_for vault-write "$operation_timeout" \
        "$OCI_PYTHON" "${SCRIPT_DIR}/_vault_put_secret.py" \
        --secret-name "$1" --readable-timeout "$READABLE_TIMEOUT" \
        --operation-timeout "$operation_timeout"
}

echo "Mint the token at: OCI Console > profile icon > My Profile > Auth tokens > Generate token"
echo "Paste it below. It is not echoed or logged; Docker writes proof credentials only to an auto-removed temporary config."

if [ "$FROM_STDIN" -eq 1 ]; then
    acx_token="$(command cat)"
else
    # `read -rs` keeps the token off the terminal and out of shell history.
    printf 'OCI auth token: ' >&2
    IFS= read -rs acx_token || true
    printf '\n' >&2
fi
if [ -z "$acx_token" ]; then
    echo "refusing an empty OCI auth token" >&2
    exit 2
fi

# Resolve the username before proving the token. A bootstrap username is used
# directly; otherwise fetch only the existing non-secret username from Vault.
if [ -n "$SET_USERNAME" ]; then
    proof_username="$SET_USERNAME"
else
    username_rc=0
    run_bounded vault "$ACX_LOCAL_OCI_BIN" --auth api_key \
        secrets secret-bundle get-secret-bundle-by-name \
        --vault-id "$ACX_VAULT_OCID" \
        --secret-name "$ACX_OCIR_USERNAME_SECRET" \
        --query 'data."secret-bundle-content".content' \
        --raw-output >"${runtime_dir}/username.stdout" \
        2>"${runtime_dir}/username.stderr" || username_rc=$?
    if [ "$username_rc" -ne 0 ]; then
        report_login_failure "laptop username fetch" "$(command cat "${runtime_dir}/username.stderr")"
        unset acx_token
        exit 1
    fi
    username_encoded="$(command cat "${runtime_dir}/username.stdout")"
    proof_username="$(printf '%s' "$username_encoded" | base64 -d \
        2>>"${runtime_dir}/username.stderr")" || username_rc=$?
    if [ "$username_rc" -ne 0 ]; then
        report_login_failure "laptop username decode" "$(command cat "${runtime_dir}/username.stderr")"
        unset acx_token
        exit 1
    fi
    if [ -z "$(printf '%s' "$proof_username" | LC_ALL=C tr -d '[:space:]')" ]; then
        report_login_failure "laptop username fetch" 'Vault username secret was empty'
        unset acx_token
        exit 1
    fi
fi

# Establish validity before durable state: the freshly-read bytes go straight
# to docker, never through Vault and never through argv.
proof_rc=0
printf '%s' "$acx_token" | run_bounded ocir env DOCKER_CONFIG="$proof_docker_config" \
    docker login "$OCIR_REGISTRY" -u "$proof_username" --password-stdin \
    >"${runtime_dir}/proof.stdout" 2>"${runtime_dir}/proof.stderr" || proof_rc=$?
if [ "$proof_rc" -ne 0 ]; then
    report_login_failure "fresh token against ${OCIR_REGISTRY}" \
        "$(command cat "${runtime_dir}/proof.stderr")"
    unset acx_token
    exit 1
fi
echo "ok   fresh token authenticated directly against ${OCIR_REGISTRY}"

# Vault does not offer a transaction spanning two secrets. Store the proven
# token first, then the optional username. For a pair change, retain the prior
# active token in memory so a definite second-write failure can be compensated.
previous_token=""
previous_token_available=0
if [ -n "$SET_USERNAME" ]; then
    previous_rc=0
    run_bounded vault "$ACX_LOCAL_OCI_BIN" --auth api_key \
        secrets secret-bundle get-secret-bundle-by-name \
        --vault-id "$ACX_VAULT_OCID" \
        --secret-name "$ACX_OCIR_TOKEN_SECRET" \
        --query 'data."secret-bundle-content".content' \
        --raw-output >"${runtime_dir}/previous-token.stdout" \
        2>"${runtime_dir}/previous-token.stderr" || previous_rc=$?
    if [ "$previous_rc" -eq 0 ]; then
        previous_encoded="$(command cat "${runtime_dir}/previous-token.stdout")"
        previous_token="$(printf '%s' "$previous_encoded" | base64 -d \
            2>>"${runtime_dir}/previous-token.stderr")" || previous_rc=$?
        if [ "$previous_rc" -eq 0 ] && [ -n "$previous_token" ]; then
            previous_token_available=1
        fi
    fi
    if [ "$previous_rc" -ne 0 ] && \
        ! grep -Fq 'NotAuthorizedOrNotFound' "${runtime_dir}/previous-token.stderr"; then
        report_login_failure "prior token fetch for compensation" \
            "$(command cat "${runtime_dir}/previous-token.stderr")"
        unset acx_token previous_token
        exit 1
    fi
fi

token_rc=0
printf '%s' "$acx_token" | put_secret "$ACX_OCIR_TOKEN_SECRET" || token_rc=$?
unset acx_token
if [ "$token_rc" -ne 0 ]; then
    unset previous_token
    exit "$token_rc"
fi
if [ -n "$SET_USERNAME" ]; then
    username_rc=0
    printf '%s' "$SET_USERNAME" | put_secret "$ACX_OCIR_USERNAME_SECRET" || username_rc=$?
    if [ "$username_rc" -ne 0 ]; then
        # Exit 75 means the helper exhausted read-after-timeout reconciliation:
        # the username may already be ACTIVE. Rolling the token back in that
        # state could manufacture the opposite mismatch (new username + old
        # token), so preserve the known token write and report the uncertainty.
        # A definite username failure is safe to compensate.
        if [ "$username_rc" -ne 75 ] && [ "$previous_token_available" -eq 1 ]; then
            compensation_rc=0
            printf '%s' "$previous_token" | put_secret "$ACX_OCIR_TOKEN_SECRET" || compensation_rc=$?
            unset previous_token
            if [ "$compensation_rc" -eq 0 ]; then
                echo "FAIL username write failed; restored the prior OCIR_AUTH_TOKEN" >&2
                exit "$username_rc"
            fi
        else
            unset previous_token
        fi
        recovery_username="${SET_USERNAME//\'/\'\\\'\'}"
        if [ "$username_rc" -eq 75 ]; then
            echo "UNKNOWN/INCONSISTENT: OCIR_AUTH_TOKEN and OCIR_USERNAME may represent different credential generations." >&2
        else
            echo "INCONSISTENT: OCIR_AUTH_TOKEN is new while OCIR_USERNAME is still previous." >&2
        fi
        echo "Recovery: scripts/deploy/ocir-token-rotate.sh --set-username '${recovery_username}'" >&2
        exit "$username_rc"
    fi
fi
unset previous_token

zero_probe="${READABLE_TIMEOUT//0/}"
zero_probe="${zero_probe//./}"
if [ -z "$zero_probe" ]; then
    echo "rotation ACCEPTED-BUT-UNVERIFIED: Vault writes were accepted; immediate Vault-backed laptop and VM verification skipped because --readable-timeout 0 does not wait for propagation"
    exit 0
fi

# Release It! 5.5: prove the stored credential through each consumer path while
# the operator is still present, and distinguish SSH transport from a command
# that actually ran on the remote host.
verify_login() {
    local scope="$1" leg="$2" out rc=0 class
    shift 2
    out="$(run_bounded "${leg}-verify" "$@" 2>&1)" || rc=$?
    if [ "$rc" -ne 0 ]; then
        if [ "$leg" = remote ] && { [ "$rc" -eq 124 ] || \
            ! printf '%s' "$out" | grep -Fq 'acx-ssh-session-ok'; }; then
            class=ssh_unreachable
            echo "FAIL ${scope} [${class}]: SSH could not reach or establish a session with the host." >&2
            printf '%s\n' "$out" | sanitize_stderr >&2
        else
            report_login_failure "$scope" "$out"
        fi
        return 1
    fi
    echo "ok   ${scope} authenticated against ${OCIR_REGISTRY}"
}

rc=0
verify_login "laptop Vault credential" local \
    bash -c "$(ocir_login_snippet "${ACX_LOCAL_OCI_BIN}" api_key "${OCIR_REGISTRY}")" || rc=1

if [ "$SKIP_VERIFY" -eq 1 ]; then
    if [ "$rc" -ne 0 ]; then
        echo "token stored but the laptop Vault-backed verification failed (see above)" >&2
        exit 1
    fi
    echo "rotation complete: fresh token proven and laptop Vault credential verified; production-VM SSH verification skipped"
    exit 0
fi

remote_script="acx_remote_verify() {
printf 'acx-ssh-session-ok\\n' >&2
$(ocir_login_snippet "${ACX_REMOTE_OCI_BIN}" instance_principal "${OCIR_REGISTRY}")
}
acx_remote_verify"
verify_login "${OCI_USER}@${OCI_HOST}" remote \
    ssh -o BatchMode=yes -o ConnectTimeout=5 -o ServerAliveInterval=5 \
    -o ServerAliveCountMax=1 -l "${OCI_USER}" -- "${OCI_HOST}" \
    'acx_remote_program=$(cat); bash -c "$acx_remote_program"' \
    <<<"$remote_script" || rc=1

if [ "$rc" -ne 0 ]; then
    echo "token stored but at least one Vault-backed host verification failed (see above)" >&2
    exit 1
fi
echo "rotation complete: both hosts authenticate from acx-vault"
