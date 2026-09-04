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
# Usage (interactive -- credentials are never echoed or placed in argv):
#     scripts/deploy/ocir-token-rotate.sh [--readable-timeout SECONDS]
#
# Usage (piped, for a password manager):
#     pbpaste | scripts/deploy/ocir-token-rotate.sh --stdin
#
# Bootstrap only: read the docker username without placing it in argv.
#     scripts/deploy/ocir-token-rotate.sh --set-username
# With --stdin, supply the username on fd 3 (the token remains on stdin):
#     password-manager token | scripts/deploy/ocir-token-rotate.sh --stdin --set-username 3< <(password-manager username)
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
SET_USERNAME=0
SKIP_VERIFY=0
READABLE_TIMEOUT=120
while [ $# -gt 0 ]; do
    case "$1" in
        --stdin) FROM_STDIN=1 ;;
        --set-username)
            SET_USERNAME=1
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

# Run one local command with the same positive-integer Vault deadline used by
# the generated consumer snippets. Keep the child PID visible to cleanup so an
# interrupt cannot leave an OCI process behind.
active_pid=""
run_bounded() {
    local label="$1" started rc
    shift
    # Bash otherwise connects an asynchronous command's stdin to /dev/null
    # when job control is unavailable. Preserve the caller's pipe explicitly.
    exec 3<&0
    "$@" <&3 &
    active_pid=$!
    exec 3<&-
    started=$SECONDS
    while kill -0 "$active_pid" 2>/dev/null; do
        if [ $((SECONDS - started)) -ge "$ACX_VAULT_FETCH_TIMEOUT" ]; then
            kill "$active_pid" 2>/dev/null || true
            sleep 0.1
            kill -9 "$active_pid" 2>/dev/null || true
            wait "$active_pid" 2>/dev/null || true
            active_pid=""
            printf 'acx-timeout:%s after %ss\n' "$label" "$ACX_VAULT_FETCH_TIMEOUT" >&2
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

fetch_secret() {
    # $1 = allowlisted secret name; $2 = human-readable scope for diagnostics.
    # The decoded credential is returned in fetched_secret, never in argv or a
    # file. Only sanitized OCI diagnostics use the private runtime directory.
    local secret_name="$1" scope="$2" encoded fetch_rc=0
    fetched_secret=""
    encoded="$(run_bounded vault "$ACX_LOCAL_OCI_BIN" --auth api_key \
        secrets secret-bundle get-secret-bundle-by-name \
        --vault-id "$ACX_VAULT_OCID" \
        --secret-name "$secret_name" \
        --query 'data."secret-bundle-content".content' \
        --raw-output 2>"${runtime_dir}/fetch.stderr")" || fetch_rc=$?
    if [ "$fetch_rc" -ne 0 ]; then
        report_login_failure "$scope" "$(command cat "${runtime_dir}/fetch.stderr")"
        return 1
    fi
    fetched_secret="$(printf '%s' "$encoded" | base64 -d \
        2>>"${runtime_dir}/fetch.stderr")" || fetch_rc=$?
    if [ "$fetch_rc" -ne 0 ]; then
        report_login_failure "$scope" "$(command cat "${runtime_dir}/fetch.stderr")"
        fetched_secret=""
        return 1
    fi
    if [ -z "$fetched_secret" ]; then
        report_login_failure "$scope" 'Vault secret was empty'
        return 1
    fi
}

echo "Mint the token at: OCI Console > profile icon > My Profile > Auth tokens > Generate token"
echo "Paste it below. It is not echoed, logged, or retained on disk."

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

new_username=""
if [ "$SET_USERNAME" -eq 1 ]; then
    if [ "$FROM_STDIN" -eq 1 ]; then
        if ! ( : <&3 ) 2>/dev/null; then
            echo "--stdin --set-username requires the username on file descriptor 3" >&2
            unset acx_token
            exit 2
        fi
        IFS= read -r new_username <&3 || true
        exec 3<&-
    else
        printf 'OCI docker username: ' >&2
        IFS= read -rs new_username || true
        printf '\n' >&2
    fi
    if [ -z "$(printf '%s' "$new_username" | LC_ALL=C tr -d '[:space:]')" ]; then
        echo "refusing an empty OCI docker username" >&2
        unset acx_token new_username
        exit 2
    fi
fi

# Resolve the username before proving the token. A bootstrap username is used
# directly; otherwise fetch only the existing non-secret username from Vault.
if [ "$SET_USERNAME" -eq 1 ]; then
    proof_username="$new_username"

    # The first half of the two-secret update remains reversible until the
    # username has been durably confirmed. Vault has no multi-secret
    # transaction, so retain the prior token in memory for compensation.
    if ! fetch_secret "$ACX_OCIR_TOKEN_SECRET" "rollback token fetch"; then
        unset acx_token new_username proof_username fetched_secret
        exit 1
    fi
    previous_token="$fetched_secret"
    unset fetched_secret
else
    if ! fetch_secret "$ACX_OCIR_USERNAME_SECRET" "laptop username fetch"; then
        unset acx_token
        exit 1
    fi
    proof_username="$fetched_secret"
    unset fetched_secret
    if [ -z "$(printf '%s' "$proof_username" | LC_ALL=C tr -d '[:space:]')" ]; then
        report_login_failure "laptop username fetch" 'Vault username secret was empty'
        unset acx_token
        exit 1
    fi
fi

# Establish validity before durable state. Docker cannot accept its username
# through stdin, so place the pair in its mode-0600 config inside the private,
# trap-cleaned runtime directory. `docker login` then receives no credential in
# argv, and the config is removed immediately after this proof.
proof_config_file="${proof_docker_config}/config.json"
printf '%s\0%s' "$proof_username" "$acx_token" | "$OCI_PYTHON" -c \
    'import base64,json,sys; u,t=sys.stdin.buffer.read().split(b"\0",1); json.dump({"auths":{sys.argv[1]:{"auth":base64.b64encode(u+b":"+t).decode("ascii")}}},open(sys.argv[2],"w"))' \
    "$OCIR_REGISTRY" "$proof_config_file"
chmod 600 "$proof_config_file"
proof_rc=0
proof_out="$(DOCKER_CONFIG="$proof_docker_config" run_bounded ocir \
    docker login "$OCIR_REGISTRY" 2>&1)" || proof_rc=$?
rm -f -- "$proof_config_file"
if [ "$proof_rc" -ne 0 ]; then
    report_login_failure "fresh token against ${OCIR_REGISTRY}" "$proof_out"
    unset acx_token
    exit 1
fi
echo "ok   fresh token authenticated directly against ${OCIR_REGISTRY}"

# Vault does not offer a transaction spanning two secrets. Store the proven
# token first, then replay the idempotent username value with bounded,
# jittered backoff. If it cannot be confirmed, restore the previous token so
# the first half of the pair update is compensating-reversible (RES-01).
printf '%s' "$acx_token" | put_secret "$ACX_OCIR_TOKEN_SECRET"
if [ "$SET_USERNAME" -eq 1 ]; then
    username_written=0
    username_attempt=1
    while [ "$username_attempt" -le 3 ]; do
        if printf '%s' "$new_username" | put_secret "$ACX_OCIR_USERNAME_SECRET"; then
            username_written=1
            break
        fi
        if [ "$username_attempt" -lt 3 ]; then
            # Exponential 100/200ms base plus 0-100ms jitter (COST-12).
            retry_base_ms=$((100 * (1 << (username_attempt - 1))))
            retry_ms=$((retry_base_ms + RANDOM % 101))
            printf 'username write attempt %s failed; retrying in %s.%03ss\n' \
                "$username_attempt" "$((retry_ms / 1000))" "$((retry_ms % 1000))" >&2
            sleep "$((retry_ms / 1000)).$(printf '%03d' "$((retry_ms % 1000))")"
        fi
        username_attempt=$((username_attempt + 1))
    done
    if [ "$username_written" -ne 1 ]; then
        echo "username write could not be confirmed; restoring the previous token" >&2
        rollback_rc=1
        rollback_attempt=1
        while [ "$rollback_attempt" -le 3 ]; do
            if printf '%s' "$previous_token" | put_secret "$ACX_OCIR_TOKEN_SECRET"; then
                rollback_rc=0
                break
            fi
            if [ "$rollback_attempt" -lt 3 ]; then
                retry_base_ms=$((100 * (1 << (rollback_attempt - 1))))
                retry_ms=$((retry_base_ms + RANDOM % 101))
                printf 'token rollback attempt %s failed; retrying in %s.%03ss\n' \
                    "$rollback_attempt" "$((retry_ms / 1000))" "$((retry_ms % 1000))" >&2
                sleep "$((retry_ms / 1000)).$(printf '%03d' "$((retry_ms % 1000))")"
            fi
            rollback_attempt=$((rollback_attempt + 1))
        done
        unset acx_token new_username previous_token proof_username
        if [ "$rollback_rc" -ne 0 ]; then
            echo "CRITICAL: previous OCIR token rollback failed; Vault credential pair needs immediate repair" >&2
        else
            echo "previous OCIR token restored; username update was not completed" >&2
        fi
        exit 1
    fi
fi
unset acx_token new_username previous_token proof_username

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
    ssh -o BatchMode=yes -o ConnectTimeout=5 -l "${OCI_USER}" -- "${OCI_HOST}" \
    'acx_remote_program=$(cat); bash -c "$acx_remote_program"' \
    <<<"$remote_script" || rc=1

if [ "$rc" -ne 0 ]; then
    echo "token stored but at least one Vault-backed host verification failed (see above)" >&2
    exit 1
fi
echo "rotation complete: both hosts authenticate from acx-vault"
