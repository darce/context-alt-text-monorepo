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
# Usage (interactive -- the token is never echoed, never in argv, never on disk):
#     scripts/deploy/ocir-token-rotate.sh [--readable-timeout SECONDS]
#
# Usage (piped, for a password manager):
#     pbpaste | scripts/deploy/ocir-token-rotate.sh --stdin
#
# Bootstrap only: seed the docker username after the proven token is stored.
#     scripts/deploy/ocir-token-rotate.sh --set-username '<namespace>/<email>'
#
# Options:
#     --readable-timeout SECONDS  End-to-end Vault deadline (positive; default 120)
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
OCIR_LOGIN_TIMEOUT="${ACX_OCIR_LOGIN_TIMEOUT:-30}"
OCIR_VERIFY_TIMEOUT="${ACX_OCIR_VERIFY_TIMEOUT:-60}"
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
                echo "--readable-timeout needs a positive number" >&2
                exit 2
            fi
            READABLE_TIMEOUT="$2"
            case "$READABLE_TIMEOUT" in
                ''|*[!0-9.]*|*.*.*)
                    echo "invalid --readable-timeout: ${READABLE_TIMEOUT} (expected a positive number)" >&2
                    exit 2
                    ;;
            esac
            case "$READABLE_TIMEOUT" in
                *[0-9]*) ;;
                *)
                    echo "invalid --readable-timeout: ${READABLE_TIMEOUT} (expected a positive number)" >&2
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

for timeout_name in READABLE_TIMEOUT OCIR_LOGIN_TIMEOUT OCIR_VERIFY_TIMEOUT; do
    timeout_value="${!timeout_name}"
    if ! awk -v value="$timeout_value" 'BEGIN { exit !(value ~ /^([0-9]+([.][0-9]*)?|[.][0-9]+)$/ && value > 0) }'; then
        echo "${timeout_name} must be a positive number (got: ${timeout_value})" >&2
        exit 2
    fi
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

# Run one local command with the same positive-integer Vault deadline used by
# the generated consumer snippets. Keep the child PID visible to cleanup so an
# interrupt cannot leave an OCI process behind.
active_pid=""
run_bounded_for() {
    local timeout="$1" label="$2" started rc
    shift 2
    # Explicit stdin redirection prevents non-interactive Bash from replacing
    # an asynchronous command's stdin with /dev/null (SSH verification and
    # docker --password-stdin both rely on this byte stream).
    "$@" <&0 &
    active_pid=$!
    started=$SECONDS
    while kill -0 "$active_pid" 2>/dev/null; do
        if awk -v elapsed="$((SECONDS - started))" -v limit="$timeout" 'BEGIN { exit !(elapsed >= limit) }'; then
            kill "$active_pid" 2>/dev/null || true
            sleep 0.1
            kill -9 "$active_pid" 2>/dev/null || true
            wait "$active_pid" 2>/dev/null || true
            active_pid=""
            printf 'acx-timeout:%s after %ss\n' "$label" "$timeout" >&2
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
    run_bounded_for "$ACX_VAULT_FETCH_TIMEOUT" "$label" "$@"
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
    "$OCI_PYTHON" "${SCRIPT_DIR}/_vault_put_secret.py" \
        --secret-name "$1" --readable-timeout "$READABLE_TIMEOUT"
}

fetch_secret_value() {
    # $1 = allowlisted secret name; decoded value is emitted without touching disk.
    local secret_name="$1" error_file="$2" fetch_rc=0 encoded
    encoded="$(run_bounded vault "$ACX_LOCAL_OCI_BIN" --auth api_key \
        secrets secret-bundle get-secret-bundle-by-name \
        --vault-id "$ACX_VAULT_OCID" \
        --secret-name "$secret_name" \
        --query 'data."secret-bundle-content".content' \
        --raw-output 2>"$error_file")" || fetch_rc=$?
    if [ "$fetch_rc" -ne 0 ]; then
        return "$fetch_rc"
    fi
    printf '%s' "$encoded" | base64 -d 2>>"$error_file"
}

echo "Mint the token at: OCI Console > profile icon > My Profile > Auth tokens > Generate token"
echo "Paste it below. It is not echoed, not logged, and not written to disk."

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
    proof_username="$(fetch_secret_value "$ACX_OCIR_USERNAME_SECRET" "${runtime_dir}/username.stderr")" || username_rc=$?
    if [ "$username_rc" -ne 0 ]; then
        report_login_failure "laptop username fetch" "$(command cat "${runtime_dir}/username.stderr")"
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
proof_out="$(printf '%s' "$acx_token" | run_bounded_for "$OCIR_LOGIN_TIMEOUT" ocir-fresh-token-login \
    env DOCKER_CONFIG="$proof_docker_config" docker login "$OCIR_REGISTRY" \
    -u "$proof_username" --password-stdin 2>&1)" || proof_rc=$?
if [ "$proof_rc" -ne 0 ]; then
    report_login_failure "fresh token against ${OCIR_REGISTRY}" "$proof_out"
    unset acx_token
    exit 1
fi
echo "ok   fresh token authenticated directly against ${OCIR_REGISTRY}"

# Vault does not offer a transaction spanning two secrets. When changing the
# username, retain the prior token in memory so a failed username write can
# compensate instead of publishing an old-username/new-token pair.
old_token_available=0
old_token=""
if [ -n "$SET_USERNAME" ] \
    && old_token="$(fetch_secret_value "$ACX_OCIR_TOKEN_SECRET" "${runtime_dir}/old-token.stderr")"; then
    old_token_available=1
fi
token_write_rc=0
printf '%s' "$acx_token" | put_secret "$ACX_OCIR_TOKEN_SECRET" || token_write_rc=$?
unset acx_token
if [ "$token_write_rc" -ne 0 ]; then
    exit "$token_write_rc"
fi
if [ -n "$SET_USERNAME" ]; then
    username_write_rc=0
    printf '%s' "$SET_USERNAME" | put_secret "$ACX_OCIR_USERNAME_SECRET" || username_write_rc=$?
    if [ "$username_write_rc" -ne 0 ]; then
        if [ "$old_token_available" -eq 1 ]; then
            echo "username write failed; restoring the prior token before exiting" >&2
            if ! printf '%s' "$old_token" | put_secret "$ACX_OCIR_TOKEN_SECRET"; then
                echo "CRITICAL compensation failed: Vault may contain an old-username/new-token pair; mint a token and rerun with --set-username" >&2
            else
                compensation_username="$(fetch_secret_value "$ACX_OCIR_USERNAME_SECRET" "${runtime_dir}/compensation-username.stderr" || true)"
                compensation_rc=0
                compensation_out="$(printf '%s' "$old_token" | run_bounded_for "$OCIR_LOGIN_TIMEOUT" ocir-compensation-login \
                    env DOCKER_CONFIG="$proof_docker_config" docker login "$OCIR_REGISTRY" \
                    -u "$compensation_username" --password-stdin 2>&1)" || compensation_rc=$?
                if [ "$compensation_rc" -eq 0 ]; then
                    echo "compensation verified: the restored Vault credential authenticates against ${OCIR_REGISTRY}" >&2
                else
                    echo "CRITICAL compensation verification failed; fresh Vault consumers may be unable to authenticate" >&2
                    report_login_failure "restored Vault credential" "$compensation_out"
                fi
            fi
        else
            echo "username write failed and no prior token was readable; bootstrap is incomplete and consumers remain unavailable" >&2
        fi
        exit "$username_write_rc"
    fi
fi
unset old_token

# Release It! 5.5: prove the stored credential through each consumer path while
# the operator is still present, and distinguish SSH transport from a command
# that actually ran on the remote host.
verify_login() {
    local scope="$1" leg="$2" out rc=0 class
    shift 2
    out="$("$@" 2>&1)" || rc=$?
    if [ "$rc" -ne 0 ]; then
        if [ "$leg" = remote ] && ! printf '%s' "$out" | grep -Fq 'acx-ssh-session-ok'; then
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
    run_bounded_for "$OCIR_VERIFY_TIMEOUT" laptop-vault-login \
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
    run_bounded_for "$OCIR_VERIFY_TIMEOUT" production-vm-vault-login \
    ssh -o BatchMode=yes -o ConnectTimeout=5 -o ConnectionAttempts=1 \
    -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -l "${OCI_USER}" -- "${OCI_HOST}" \
    'acx_remote_program=$(cat); bash -c "$acx_remote_program"' \
    <<<"$remote_script" || rc=1

if [ "$rc" -ne 0 ]; then
    echo "token stored but at least one Vault-backed host verification failed (see above)" >&2
    exit 1
fi
echo "rotation complete: both hosts authenticate from acx-vault"
