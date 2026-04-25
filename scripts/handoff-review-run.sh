#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYENV_VERSION="${PYENV_VERSION:-description-service}"

if command -v pyenv >/dev/null 2>&1; then
	exec env PYENV_VERSION="${PYENV_VERSION}" pyenv exec python3 "${REPO_ROOT}/scripts/handoff_review_run.py" "$@"
fi

exec env PYENV_VERSION="${PYENV_VERSION}" python3 "${REPO_ROOT}/scripts/handoff_review_run.py" "$@"