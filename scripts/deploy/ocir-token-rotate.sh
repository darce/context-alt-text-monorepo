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
# Usage (interactive -- the token is never echoed, never in argv, never on disk):
#     scripts/deploy/ocir-token-rotate.sh
#
# Usage (piped, for a password manager):
#     pbpaste | scripts/deploy/ocir-token-rotate.sh --stdin
#
# Bootstrap only: seed the docker username alongside the token.
#     scripts/deploy/ocir-token-rotate.sh --set-username '<namespace>/<email>'

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash. Example: bash $0" >&2
    exit 2
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/ocir-auth.sh
source "${SCRIPT_DIR}/lib/ocir-auth.sh"

OCIR_REGISTRY="${OCIR_REGISTRY:-iad.ocir.io}"
OCI_HOST="${OCI_HOST:-acx-backend.tail1a44b8.ts.net}"
OCI_USER="${OCI_USER:-ubuntu}"

FROM_STDIN=0
SET_USERNAME=""
SKIP_VERIFY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --stdin) FROM_STDIN=1 ;;
        --set-username) SET_USERNAME="${2:?--set-username needs a value}"; shift ;;
        --skip-verify) SKIP_VERIFY=1 ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

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

put_secret() {
    # $1 = secret name. Value arrives on this function's stdin and goes no
    # further than the helper's memory.
    "$OCI_PYTHON" "${SCRIPT_DIR}/_vault_put_secret.py" --secret-name "$1"
}

if [ -n "$SET_USERNAME" ]; then
    # Not a secret, but vaulted with the token so a rotation that also changes
    # the OCIR user is a single atomic operator action in one place.
    printf '%s' "$SET_USERNAME" | put_secret "${ACX_OCIR_USERNAME_SECRET}"
fi

echo "Mint the token at: OCI Console > profile icon > My Profile > Auth tokens > Generate token"
echo "Paste it below. It is not echoed, not logged, and not written to disk."

if [ "$FROM_STDIN" -eq 1 ]; then
    put_secret "${ACX_OCIR_TOKEN_SECRET}"
else
    # `read -rs` keeps the token off the terminal and out of shell history.
    # It is passed to the helper by pipe, so it never becomes an argv entry.
    printf 'OCI auth token: ' >&2
    IFS= read -rs acx_token
    printf '\n' >&2
    printf '%s' "$acx_token" | put_secret "${ACX_OCIR_TOKEN_SECRET}"
    unset acx_token
fi

if [ "$SKIP_VERIFY" -eq 1 ]; then
    echo "stored; verification skipped (--skip-verify)"
    exit 0
fi

# Release It! 5.5: prove the stored credential actually authenticates, here,
# while the operator is still present -- not at the next deploy's push step.
verify() {
    local scope="$1" out rc=0
    shift
    out="$("$@" 2>&1)" || rc=$?
    if [ "$rc" -ne 0 ]; then
        local class
        class="$(ocir_classify_login_failure "$out")"
        echo "FAIL ${scope} [${class}]: $(ocir_login_failure_hint "$class")" >&2
        printf '%s\n' "$out" >&2
        return 1
    fi
    echo "ok   ${scope} authenticated against ${OCIR_REGISTRY}"
}

rc=0
verify "laptop" bash -c "$(ocir_login_snippet "${ACX_LOCAL_OCI_BIN}" api_key "${OCIR_REGISTRY}")" || rc=1
verify "${OCI_USER}@${OCI_HOST}" \
    ssh -o BatchMode=yes -o ConnectTimeout=5 -l "${OCI_USER}" -- "${OCI_HOST}" 'bash -s' \
    <<<"$(ocir_login_snippet "${ACX_REMOTE_OCI_BIN}" instance_principal "${OCIR_REGISTRY}")" || rc=1

if [ "$rc" -ne 0 ]; then
    echo "token stored but at least one host could not authenticate (see above)" >&2
    exit 1
fi
echo "rotation complete: both hosts authenticate from acx-vault"
