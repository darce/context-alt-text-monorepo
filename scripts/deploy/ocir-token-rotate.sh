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

put_secret() {
    # $1 = allowlisted secret name. Value arrives on stdin and goes no further
    # than the helper's memory.
    echo "writing vault ${ACX_VAULT_OCID} secret $1" >&2
    "$OCI_PYTHON" "${SCRIPT_DIR}/_vault_put_secret.py" \
        --secret-name "$1" --readable-timeout "$READABLE_TIMEOUT"
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
    proof_username="$(bash -c "$(ocir_vault_fetch_snippet "${ACX_LOCAL_OCI_BIN}" api_key "${ACX_OCIR_USERNAME_SECRET}")" 2>&1)" || username_rc=$?
    if [ "$username_rc" -ne 0 ]; then
        report_login_failure "laptop username fetch" "$proof_username"
        unset acx_token
        exit 1
    fi
fi

# Establish validity before durable state: the freshly-read bytes go straight
# to docker, never through Vault and never through argv.
proof_rc=0
proof_out="$(printf '%s' "$acx_token" | docker login "$OCIR_REGISTRY" \
    -u "$proof_username" --password-stdin 2>&1)" || proof_rc=$?
if [ "$proof_rc" -ne 0 ]; then
    report_login_failure "fresh token against ${OCIR_REGISTRY}" "$proof_out"
    unset acx_token
    exit 1
fi
echo "ok   fresh token authenticated directly against ${OCIR_REGISTRY}"

# Vault does not offer a transaction spanning two secrets. Store the proven
# token first, then the optional username, so a token-write failure can never
# replace the username while leaving the old token in place.
printf '%s' "$acx_token" | put_secret "$ACX_OCIR_TOKEN_SECRET"
unset acx_token
if [ -n "$SET_USERNAME" ]; then
    printf '%s' "$SET_USERNAME" | put_secret "$ACX_OCIR_USERNAME_SECRET"
fi

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

remote_script="printf 'acx-ssh-session-ok\\n' >&2
$(ocir_login_snippet "${ACX_REMOTE_OCI_BIN}" instance_principal "${OCIR_REGISTRY}")"
verify_login "${OCI_USER}@${OCI_HOST}" remote \
    ssh -o BatchMode=yes -o ConnectTimeout=5 -l "${OCI_USER}" -- "${OCI_HOST}" 'bash -s' \
    <<<"$remote_script" || rc=1

if [ "$rc" -ne 0 ]; then
    echo "token stored but at least one Vault-backed host verification failed (see above)" >&2
    exit 1
fi
echo "rotation complete: both hosts authenticate from acx-vault"
