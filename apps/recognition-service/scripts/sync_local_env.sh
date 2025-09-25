#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_REQUIREMENTS=("requirements_local.txt" "requirements_local_dev.txt")

if [[ $# -gt 0 ]]; then
  REQUIREMENTS=("$@")
else
  REQUIREMENTS=("${DEFAULT_REQUIREMENTS[@]}")
fi

if ! command -v pip-sync >/dev/null 2>&1; then
  echo "pip-sync (pip-tools) is required. Install via 'python -m pip install pip-tools'." >&2
  exit 1
fi

REQ_PATHS=()
for req in "${REQUIREMENTS[@]}"; do
  if [[ ! -f "${PROJECT_ROOT}/${req}" ]]; then
    echo "Requirement file '${req}' not found relative to ${PROJECT_ROOT}." >&2
    exit 1
  fi
  REQ_PATHS+=("${PROJECT_ROOT}/${req}")
done

if [[ $(uname -s) == "Darwin" && $(uname -m) == "arm64" ]]; then
  "${SCRIPT_DIR}/install_insightface_mac.sh"
fi

pip-sync "${REQ_PATHS[@]}"

echo "[sync_local_env] Environment sync complete."
