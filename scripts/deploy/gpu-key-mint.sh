#!/usr/bin/env bash
# Mint the llama.cpp endpoint key through a VM's instance-principal Vault writer.
# The generated key travels only on SSH stdin and remains in memory on this host.

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash" >&2
    exit 2
fi

set -euo pipefail
set +x
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SSH_TARGET="${GPU_KEY_WRITER_SSH_TARGET:-}"
REMOTE_PYTHON="${GPU_KEY_WRITER_PYTHON:-/home/ubuntu/.oci-venv/bin/python3}"
MANIFEST_PATH="${REPO_ROOT}/config/env/manifest.d/10-service-shared.toml"
MODE="bootstrap"
APPROVED=0
SSH_TIMEOUT_SECONDS=185
RESULT_FILE=""
REMOTE_DIR=""
TIMEOUT_BIN=""

usage() {
    cat <<'USAGE'
Usage: scripts/deploy/gpu-key-mint.sh --approve-mint --ssh-target user@host [--rotate] [--manifest PATH]

Bootstrap creates the secret only when absent. Rotation requires the explicit
--rotate flag and reuses the existing secret OCID. The generated key travels
only on SSH stdin. On success, stdout contains only the OCID and byte length.
USAGE
}

fail() {
    echo "FAIL $1" >&2
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --ssh-target)
            [ $# -ge 2 ] || fail "--ssh-target needs user@host"
            SSH_TARGET="$2"
            shift
            ;;
        --manifest)
            [ $# -ge 2 ] || fail "--manifest needs a path"
            MANIFEST_PATH="$2"
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
if [[ ! "${SSH_TARGET}" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$ ]]; then
    fail "set GPU_KEY_WRITER_SSH_TARGET or pass --ssh-target user@host"
fi
if [[ ! "${REMOTE_PYTHON}" =~ ^/[A-Za-z0-9_./-]+$ || "${REMOTE_PYTHON}" == *"/../"* ]]; then
    fail "GPU_KEY_WRITER_PYTHON must be an absolute executable path"
fi

if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_BIN="$(command -v timeout)"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_BIN="$(command -v gtimeout)"
else
    fail "timeout is required (install GNU coreutils on macOS)"
fi
command -v openssl >/dev/null 2>&1 || fail "openssl is required for cryptographic random generation"
command -v ssh >/dev/null 2>&1 || fail "ssh is required"
command -v scp >/dev/null 2>&1 || fail "scp is required"
python3 "${SCRIPT_DIR}/_gpu_key_manifest.py" --check-ready --manifest "${MANIFEST_PATH}"

umask 077
RESULT_FILE="$(mktemp "${TMPDIR:-/tmp}/acx-gpu-key-mint.XXXXXX")"

cleanup() {
    if [ -n "${REMOTE_DIR}" ]; then
        "${TIMEOUT_BIN}" --kill-after=1s 15s ssh -T \
            -o BatchMode=yes -o ConnectTimeout=10 \
            "${SSH_TARGET}" "rm -rf -- '${REMOTE_DIR}'" >/dev/null 2>&1 || true
    fi
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

SSH_OPTIONS=(-T -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2)
REMOTE_DIR="$(bounded 20 ssh "${SSH_OPTIONS[@]}" "${SSH_TARGET}" 'umask 077; mktemp -d /tmp/acx-gpu-key-mint.XXXXXX')"
if [[ ! "${REMOTE_DIR}" =~ ^/tmp/acx-gpu-key-mint\.[A-Za-z0-9]+$ ]]; then
    fail "VM did not return a valid temporary directory"
fi
REMOTE_WRITER="${REMOTE_DIR}/_vault_put_secret.py"
bounded 20 scp -q -- "${SCRIPT_DIR}/_vault_put_secret.py" "${SSH_TARGET}:${REMOTE_WRITER}"

REMOTE_COMMAND="sudo -n ${REMOTE_PYTHON} ${REMOTE_WRITER} --secret-name ACX_GPU_ENDPOINT_API_KEY --instance-principal --result-only --readable-timeout 90 --operation-timeout 150"
if [ "${MODE}" = "bootstrap" ]; then
    REMOTE_COMMAND="${REMOTE_COMMAND} --bootstrap"
else
    REMOTE_COMMAND="${REMOTE_COMMAND} --rotate-existing"
fi
export GPU_KEY_WRITER_SSH_TARGET="${SSH_TARGET}"
export GPU_KEY_WRITER_REMOTE_COMMAND="${REMOTE_COMMAND}"
export GPU_KEY_WRITER_TIMEOUT_BIN="${TIMEOUT_BIN}"
export GPU_KEY_WRITER_TIMEOUT_SECONDS="${SSH_TIMEOUT_SECONDS}"

# The random value is generated and written directly to ssh stdin. It is never
# assigned to a shell variable, passed as an argument, or written to a file.
if ! bounded "${SSH_TIMEOUT_SECONDS}" bash -c '
    set -euo pipefail
    set +x
    openssl rand -hex 32 | "$GPU_KEY_WRITER_TIMEOUT_BIN" --kill-after=2s \
        "${GPU_KEY_WRITER_TIMEOUT_SECONDS}s" ssh -T \
        -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 \
        -o ServerAliveCountMax=2 "$GPU_KEY_WRITER_SSH_TARGET" \
        "$GPU_KEY_WRITER_REMOTE_COMMAND"
' >"${RESULT_FILE}"; then
    fail "Vault writer failed or exceeded its deadline"
fi

RESULT="$(<"${RESULT_FILE}")"
if [[ ! "${RESULT}" =~ ^(ocid1\.vaultsecret\.oc[0-9]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9._-]+)[[:space:]]+([0-9]+)$ ]]; then
    fail "Vault writer returned an invalid result"
fi
SECRET_OCID="${BASH_REMATCH[1]}"
BYTE_LENGTH="${BASH_REMATCH[2]}"
if [ "${BYTE_LENGTH}" != "64" ]; then
    fail "existing or minted GPU key has invalid byte length ${BYTE_LENGTH}"
fi

python3 "${SCRIPT_DIR}/_gpu_key_manifest.py" "${SECRET_OCID}" --manifest "${MANIFEST_PATH}"
printf '%s %s\n' "${SECRET_OCID}" "${BYTE_LENGTH}"
