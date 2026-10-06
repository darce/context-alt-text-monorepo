#!/usr/bin/env bash
# Mint the llama.cpp endpoint key locally with the operator's OCI CLI config.
# The generated key is piped straight into the Vault writer's stdin.

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash" >&2
    exit 2
fi

set -euo pipefail
set +x
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

MANIFEST_PATH="${REPO_ROOT}/config/env/manifest.d/10-service-shared.toml"
TERRAFORM_INPUT_PATH="${REPO_ROOT}/infra/oci/gpu-api-key.tfvars"
MODE="bootstrap"
APPROVED=0
EXPECTED_SECRET_ID=""
EXPECTED_OWNER_SHA256=""
EXPECTED_TERRAFORM_INPUT_SHA256=""
WRITER_TIMEOUT_SECONDS=185
RESULT_FILE=""
TIMEOUT_BIN=""

usage() {
    cat <<'USAGE'
Usage: scripts/deploy/gpu-key-mint.sh --approve-mint [--rotate] [--manifest PATH] [--terraform-input PATH]

Bootstrap creates the secret only when absent. Rotation requires the explicit
--rotate flag and reuses the existing secret OCID. The generated key travels
only on the local writer's stdin and never enters argv, environment, files, or
logs. The writer uses the operator's ~/.oci/config (DEFAULT profile); that identity
needs manage secret-family, use vaults, and use keys in the compartment containing
acx-vault. The backend VM's instance principal stays secret-read only (no Vault
write grant). Requires a configured OCI CLI, GNU timeout (gtimeout from coreutils
on macOS), and openssl. ACX_OCI_PYTHON
may select an interpreter with the OCI SDK. On success, stdout is "<secret ocid> 64".
USAGE
}

fail() {
    echo "FAIL $1" >&2
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --manifest)
            [ $# -ge 2 ] || fail "--manifest needs a path"
            MANIFEST_PATH="$2"
            shift
            ;;
        --terraform-input)
            [ $# -ge 2 ] || fail "--terraform-input needs a path"
            TERRAFORM_INPUT_PATH="$2"
            shift
            ;;
        --expected-secret-id)
            [ $# -ge 2 ] || fail "--expected-secret-id needs a Vault secret OCID"
            EXPECTED_SECRET_ID="$2"
            shift
            ;;
        --expected-owner-sha256)
            [ $# -ge 2 ] || fail "--expected-owner-sha256 needs a SHA-256 digest"
            EXPECTED_OWNER_SHA256="$2"
            shift
            ;;
        --expected-terraform-input-sha256)
            [ $# -ge 2 ] || fail "--expected-terraform-input-sha256 needs a SHA-256 digest"
            EXPECTED_TERRAFORM_INPUT_SHA256="$2"
            shift
            ;;
        --rotate)
            MODE="rotate"
            ;;
        --approve-mint)
            APPROVED=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown argument: $1"
            ;;
    esac
    shift
done

if [ "${APPROVED}" -ne 1 ]; then
    fail "Vault mutation requires explicit --approve-mint after landing"
fi
if [ -n "${EXPECTED_SECRET_ID}" ] && \
    [[ ! "${EXPECTED_SECRET_ID}" =~ ^ocid1\.vaultsecret\.oc[0-9]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9._-]{20,}$ ]]; then
    fail "expected GPU key secret ID is invalid"
fi
if [ -n "${EXPECTED_OWNER_SHA256}" ] && [[ ! "${EXPECTED_OWNER_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
    fail "expected GPU key manifest snapshot is invalid"
fi
if [ -n "${EXPECTED_TERRAFORM_INPUT_SHA256}" ] && \
    [[ "${EXPECTED_TERRAFORM_INPUT_SHA256}" != "missing" && ! "${EXPECTED_TERRAFORM_INPUT_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
    fail "expected GPU key Terraform snapshot is invalid"
fi

if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_BIN="$(command -v timeout)"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_BIN="$(command -v gtimeout)"
else
    fail "timeout is required (install GNU coreutils on macOS)"
fi
command -v openssl >/dev/null 2>&1 || fail "openssl is required for cryptographic random generation"
# Use the OCI CLI's SDK interpreter unless the operator explicitly selects one.
OCI_PYTHON="${ACX_OCI_PYTHON:-}"
if [ -z "$OCI_PYTHON" ]; then
    oci_bin="$(command -v oci || true)"
    if [ -z "$oci_bin" ]; then
        fail "oci CLI not found in PATH. brew install oci-cli"
    fi
    OCI_PYTHON="$(head -1 "$oci_bin" | sed 's|^#!||')"
fi
if ! "$OCI_PYTHON" -c 'import oci' 2>/dev/null; then
    fail "no OCI SDK in ${OCI_PYTHON}; set ACX_OCI_PYTHON to an interpreter that has it"
fi

# Hold one transaction lock across local preflight, the local Vault write, and
# both durable local updates. The helper passes the locked descriptor and
# captured preimage hashes to this internal invocation.
if [ "${GPU_KEY_MINT_TRANSACTION_LOCKED:-0}" != "1" ]; then
    LOCK_ARGS=(
        --run-locked
        --manifest "${MANIFEST_PATH}"
        --terraform-input "${TERRAFORM_INPUT_PATH}"
    )
    if [ "${APPROVED}" -eq 1 ]; then
        LOCK_ARGS+=(--approve-mint)
    fi
    if [ "${MODE}" = "rotate" ]; then
        LOCK_ARGS+=(--rotate)
    fi
    exec python3 "${SCRIPT_DIR}/_gpu_key_manifest.py" "${LOCK_ARGS[@]}"
fi

if [ -z "${EXPECTED_OWNER_SHA256}" ] || [ -z "${EXPECTED_TERRAFORM_INPUT_SHA256}" ]; then
    fail "internal GPU key transaction handoff is incomplete"
fi
if [ "${MODE}" = "rotate" ] && [ -z "${EXPECTED_SECRET_ID}" ]; then
    fail "GPU key rotation requires a recorded GPU secret OCID; bootstrap first"
fi
VALIDATE_ARGS=(
    --validate-transaction
    --manifest "${MANIFEST_PATH}"
    --terraform-input "${TERRAFORM_INPUT_PATH}"
    --expected-owner-sha256 "${EXPECTED_OWNER_SHA256}"
    --expected-terraform-input-sha256 "${EXPECTED_TERRAFORM_INPUT_SHA256}"
)
if [ -n "${EXPECTED_SECRET_ID}" ]; then
    VALIDATE_ARGS+=(--expected-secret-id "${EXPECTED_SECRET_ID}")
fi
python3 "${SCRIPT_DIR}/_gpu_key_manifest.py" "${VALIDATE_ARGS[@]}"

umask 077
RESULT_FILE="$(mktemp "${TMPDIR:-/tmp}/acx-gpu-key-mint.XXXXXX")"

cleanup() {
    if [ -n "${RESULT_FILE}" ]; then
        rm -f -- "${RESULT_FILE}"
    fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

bounded() {
    local seconds="$1"
    shift
    "${TIMEOUT_BIN}" --kill-after=2s "${seconds}s" "$@"
}

export GPU_KEY_WRITER_OCI_PYTHON="${OCI_PYTHON}"
export GPU_KEY_WRITER_PATH="${SCRIPT_DIR}/_vault_put_secret.py"
export GPU_KEY_WRITER_MODE="${MODE}"
export GPU_KEY_WRITER_EXPECTED_SECRET_ID="${EXPECTED_SECRET_ID}"
export GPU_KEY_WRITER_TIMEOUT_BIN="${TIMEOUT_BIN}"
export GPU_KEY_WRITER_TIMEOUT_SECONDS="${WRITER_TIMEOUT_SECONDS}"

# The random value goes straight to the writer's stdin. It is never assigned to
# a shell variable, passed as an argument, or written to a file.
if ! bounded "${WRITER_TIMEOUT_SECONDS}" bash -c '
    set -euo pipefail
    set +x
    WRITER_ARGS=(--secret-name ACX_GPU_ENDPOINT_API_KEY --result-only
        --readable-timeout 90 --operation-timeout 150)
    if [ -n "$GPU_KEY_WRITER_EXPECTED_SECRET_ID" ]; then
        WRITER_ARGS+=(--expected-secret-id "$GPU_KEY_WRITER_EXPECTED_SECRET_ID")
    fi
    if [ "$GPU_KEY_WRITER_MODE" = "bootstrap" ]; then
        WRITER_ARGS+=(--bootstrap)
    else
        WRITER_ARGS+=(--rotate-existing)
    fi
    openssl rand -hex 32 | "$GPU_KEY_WRITER_TIMEOUT_BIN" --kill-after=2s \
        "${GPU_KEY_WRITER_TIMEOUT_SECONDS}s" "$GPU_KEY_WRITER_OCI_PYTHON" \
        "$GPU_KEY_WRITER_PATH" "${WRITER_ARGS[@]}"
' >"${RESULT_FILE}"; then
    fail "Vault writer failed or exceeded its deadline"
fi

RESULT="$(<"${RESULT_FILE}")"
if [[ ! "${RESULT}" =~ ^(ocid1\.vaultsecret\.oc[0-9]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9._-]{20,})[[:space:]]+([0-9]+)$ ]]; then
    fail "Vault writer returned an invalid result"
fi
SECRET_OCID="${BASH_REMATCH[1]}"
BYTE_LENGTH="${BASH_REMATCH[2]}"
if [ "${BYTE_LENGTH}" != "64" ]; then
    fail "existing or minted GPU key has invalid byte length ${BYTE_LENGTH}"
fi

printf '%s %s\n' "${SECRET_OCID}" "${BYTE_LENGTH}"
